"""Camada staging: dos CSVs da camada raw para parquet tipado.

A etapa é idempotente e não destrutiva: a camada raw nunca é tocada, e rodar de
novo sobre o mesmo snapshot reproduz exatamente o mesmo resultado.

A transcodificação para UTF-8 é feita uma vez por snapshot e reaproveitada nas
execuções seguintes, comparando o sha256 dos arquivos de origem registrado no
manifesto da extração — assim uma re-extração que mude os dados invalida o
intermediário automaticamente.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from ..config import Settings
from ..extract.manifest import Manifest, agora_iso, carregar_manifest, carregar_ultimo
from ..utils import formatar_bytes
from . import sql as sql_mod
from .encoding import transcodificar
from .schema import TABELAS, TabelaSpec

log = logging.getLogger(__name__)

MARCADOR_UTF8 = "_transcodificado.json"


class ErroDeStaging(RuntimeError):
    """Falha durante o tratamento."""


@dataclass(frozen=True)
class MetricasTabela:
    nome: str
    linhas_origem: int
    linhas_destino: int
    duplicatas_removidas: int
    arquivos_parquet: int
    bytes_parquet: int
    segundos: float


@dataclass(frozen=True)
class ResultadoStaging:
    snapshot_id: str
    staging_dir: Path
    tabelas: tuple[MetricasTabela, ...]
    segundos_total: float

    def tabela(self, nome: str) -> MetricasTabela:
        for m in self.tabelas:
            if m.nome == nome:
                return m
        raise KeyError(nome)


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------


def executar_staging(
    settings: Settings,
    *,
    snapshot_id: str | None = None,
    forcar: bool = False,
) -> ResultadoStaging:
    """Trata um snapshot da camada raw e materializa parquet em staging."""
    inicio = time.monotonic()
    manifest = _resolver_manifest(settings, snapshot_id)
    snapshot = manifest.snapshot_id
    csv_dir = settings.snapshot_dir(snapshot) / "csv"

    if not csv_dir.is_dir():
        raise ErroDeStaging(
            f"camada raw ausente para o snapshot {snapshot}: rode `cno extract` antes"
        )

    utf8_dir = settings.staging_dir / "_utf8" / f"snapshot_date={snapshot}"
    _preparar_utf8(manifest, csv_dir, utf8_dir, forcar=forcar)

    con = _conectar(settings)
    try:
        metricas = tuple(
            _tratar_tabela(con, spec, utf8_dir, settings, snapshot) for spec in TABELAS
        )
    finally:
        con.close()

    resultado = ResultadoStaging(
        snapshot_id=snapshot,
        staging_dir=settings.staging_dir,
        tabelas=metricas,
        segundos_total=time.monotonic() - inicio,
    )
    _salvar_manifesto_staging(settings, manifest, resultado)

    if not settings.manter_intermediarios:
        shutil.rmtree(utf8_dir, ignore_errors=True)
        log.info("intermediário UTF-8 removido (CNO_MANTER_INTERMEDIARIOS=0)")

    log.info(
        "staging concluído em %.1fs: %s linhas tratadas",
        resultado.segundos_total,
        f"{sum(m.linhas_destino for m in metricas):,}",
    )
    return resultado


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------


def _resolver_manifest(settings: Settings, snapshot_id: str | None) -> Manifest:
    manifest = (
        carregar_manifest(settings.manifests_dir, snapshot_id)
        if snapshot_id
        else carregar_ultimo(settings.manifests_dir)
    )
    if manifest is None:
        alvo = snapshot_id or "mais recente"
        raise ErroDeStaging(f"nenhum manifesto de extração encontrado ({alvo}); rode `cno extract`")
    return manifest


def _preparar_utf8(manifest: Manifest, csv_dir: Path, utf8_dir: Path, *, forcar: bool) -> None:
    """Transcodifica os CSVs para UTF-8, reaproveitando o que já estiver válido."""
    esperado = {a.nome: a.sha256 for a in manifest.arquivos}
    marcador = utf8_dir / MARCADOR_UTF8

    if not forcar and _utf8_valido(marcador, utf8_dir, esperado):
        log.info("intermediário UTF-8 já válido para %s", manifest.snapshot_id)
        return

    utf8_dir.mkdir(parents=True, exist_ok=True)
    for nome in sorted(esperado):
        origem = csv_dir / nome
        if not origem.is_file():
            raise ErroDeStaging(f"arquivo ausente na camada raw: {origem}")
        transcodificar(origem, utf8_dir / nome)

    marcador.write_text(
        json.dumps(
            {"sha256_origem": esperado, "gerado_em": agora_iso()},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _utf8_valido(marcador: Path, utf8_dir: Path, esperado: dict[str, str]) -> bool:
    """O intermediário só vale se veio exatamente dos mesmos arquivos de origem."""
    if not marcador.is_file():
        return False
    try:
        registrado = json.loads(marcador.read_text(encoding="utf-8"))["sha256_origem"]
    except (json.JSONDecodeError, KeyError):
        return False
    if registrado != esperado:
        log.info("origem mudou desde a última transcodificação; refazendo")
        return False
    return all((utf8_dir / nome).is_file() for nome in esperado)


def _conectar(settings: Settings) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{settings.duckdb_memory_limit}'")
    con.execute(f"SET threads = {settings.duckdb_threads}")
    # Sem isto, um spill de memória escreveria no diretório temporário do
    # sistema, que pode estar num disco diferente e bem menor.
    temp = settings.staging_dir / "_tmp"
    temp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory = '{temp}'")
    return con


def _tratar_tabela(
    con: duckdb.DuckDBPyConnection,
    spec: TabelaSpec,
    utf8_dir: Path,
    settings: Settings,
    snapshot_id: str,
) -> MetricasTabela:
    inicio = time.monotonic()
    csv = utf8_dir / spec.arquivo_origem
    destino = settings.staging_dir / spec.nome

    select = sql_mod.construir(spec, str(csv), snapshot_id)

    linhas_origem = con.execute(
        f"SELECT count(*) FROM read_csv('{csv}', header = true, all_varchar = true)"
    ).fetchone()[0]

    # Remove só a partição deste snapshot: reprocessar um snapshot não pode
    # apagar os outros já materializados.
    particao = destino / f"snapshot_date={snapshot_id}"
    shutil.rmtree(particao, ignore_errors=True)
    destino.mkdir(parents=True, exist_ok=True)

    particoes = ("snapshot_date", *spec.particoes)
    con.execute(f"""
        COPY ({select})
        TO '{destino}'
        (FORMAT PARQUET,
         PARTITION_BY ({", ".join(particoes)}),
         COMPRESSION zstd,
         OVERWRITE_OR_IGNORE true)
    """)

    linhas_destino = con.execute(
        f"SELECT count(*) FROM read_parquet('{particao}/**/*.parquet')"
    ).fetchone()[0]

    arquivos = sorted(particao.rglob("*.parquet"))
    metricas = MetricasTabela(
        nome=spec.nome,
        linhas_origem=linhas_origem,
        linhas_destino=linhas_destino,
        duplicatas_removidas=linhas_origem - linhas_destino,
        arquivos_parquet=len(arquivos),
        bytes_parquet=sum(a.stat().st_size for a in arquivos),
        segundos=time.monotonic() - inicio,
    )
    log.info(
        "%-9s %10s -> %10s linhas (%s duplicatas) · %s em %d arquivos · %.1fs",
        spec.nome,
        f"{metricas.linhas_origem:,}",
        f"{metricas.linhas_destino:,}",
        f"{metricas.duplicatas_removidas:,}",
        formatar_bytes(metricas.bytes_parquet),
        metricas.arquivos_parquet,
        metricas.segundos,
    )
    return metricas


def _salvar_manifesto_staging(
    settings: Settings, extracao: Manifest, resultado: ResultadoStaging
) -> Path:
    destino = settings.staging_dir / "_manifests" / f"{resultado.snapshot_id}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    conteudo = {
        "snapshot_id": resultado.snapshot_id,
        "gerado_em": agora_iso(),
        "segundos": round(resultado.segundos_total, 1),
        "extracao": {
            "etag": extracao.etag,
            "sha256_zip": extracao.sha256_zip,
            "baixado_em": extracao.baixado_em,
        },
        "totais_controle": extracao.totais_controle,
        "tabelas": [asdict(m) for m in resultado.tabelas],
    }
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(conteudo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(destino)
    return destino
