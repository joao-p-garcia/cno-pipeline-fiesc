"""Camada staging: dos CSVs da camada raw para parquet tipado.

A etapa é idempotente e não destrutiva: a camada raw nunca é tocada, e rodar de
novo sobre o mesmo snapshot reproduz exatamente o mesmo resultado.

A transcodificação para UTF-8 só acontece nos arquivos que realmente precisam —
os que têm bytes na faixa 0x80-0x9F, onde cp1252 e latin-1 divergem. Os demais o
DuckDB lê direto do original, sem intermediário. Na base atual isso significa
transcodificar 1 arquivo em vez de 5.

Quando há transcodificação, o resultado é reaproveitado entre execuções e
invalidado pelo sha256 dos arquivos de origem registrado no manifesto da
extração, de modo que uma re-extração que mude os dados refaz o intermediário
automaticamente.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from ..bloqueio import travar_snapshot
from ..config import Settings
from ..extract.manifest import Manifest, agora_iso, carregar_manifest, carregar_ultimo
from ..utils import formatar_bytes
from . import sql as sql_mod
from .encoding import contem_bytes_c1, transcodificar
from .schema import TABELAS, TabelaSpec

log = logging.getLogger(__name__)

MARCADOR_UTF8 = "_transcodificado.json"

# Como o DuckDB nomeia os encodings que aceita.
ENCODING_LATIN1 = "latin-1"
ENCODING_UTF8 = "utf-8"


class ErroDeStaging(RuntimeError):
    """Falha durante o tratamento."""


@dataclass(frozen=True)
class FonteCsv:
    """De onde uma tabela é lida e com que encoding."""

    caminho: Path
    encoding: str
    transcodificado: bool


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

    # A trava cobre **tudo** o que escreve sob o snapshot, até a limpeza final:
    # os CSVs transcodificados em `_utf8`, cada partição, e o manifesto de
    # staging. Fechar o bloco antes da limpeza deixaria um `rmtree` fora da
    # proteção, que é exatamente a operação perigosa. Ela não é do orquestrador
    # — vale para dois terminais e para um `airflow tasks run` avulso.
    with travar_snapshot(settings.data_dir, snapshot, etapa="cno transform"):
        utf8_dir = settings.staging_dir / "_utf8" / f"snapshot_date={snapshot}"
        fontes = _preparar_fontes(manifest, csv_dir, utf8_dir, forcar=forcar)

        con = _conectar(settings)
        try:
            metricas = tuple(
                _tratar_tabela(con, spec, fontes, settings, snapshot) for spec in TABELAS
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

        if not settings.manter_intermediarios and utf8_dir.exists():
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


def _preparar_fontes(
    manifest: Manifest, csv_dir: Path, utf8_dir: Path, *, forcar: bool
) -> dict[str, FonteCsv]:
    """Decide, por arquivo, se dá para ler direto ou se precisa transcodificar.

    Transcodificar tudo seria desperdício: na prática só o `cno.csv` tem bytes
    na faixa C1. Nos demais, latin-1 e cp1252 produzem exatamente o mesmo texto,
    e o DuckDB lê o arquivo original sem intermediário nenhum.

    A decisão é por conteúdo, não por lista fixa de nomes — se uma publicação
    futura introduzir tipografia em outra tabela, o pipeline se ajusta sozinho.
    """
    fontes: dict[str, FonteCsv] = {}
    a_transcodificar: dict[str, str] = {}

    for arquivo in manifest.arquivos:
        origem = csv_dir / arquivo.nome
        if not origem.is_file():
            raise ErroDeStaging(f"arquivo ausente na camada raw: {origem}")
        if contem_bytes_c1(origem):
            a_transcodificar[arquivo.nome] = arquivo.sha256
        else:
            fontes[arquivo.nome] = FonteCsv(origem, ENCODING_LATIN1, False)

    if not a_transcodificar:
        log.info("nenhum arquivo precisa de transcodificação")
        return fontes

    log.info(
        "%d de %d arquivos têm bytes C1 e serão transcodificados: %s",
        len(a_transcodificar),
        len(manifest.arquivos),
        ", ".join(sorted(a_transcodificar)),
    )

    marcador = utf8_dir / MARCADOR_UTF8
    reaproveitar = not forcar and _utf8_valido(marcador, utf8_dir, a_transcodificar)
    if reaproveitar:
        log.info("intermediário UTF-8 já válido para %s", manifest.snapshot_id)
    else:
        utf8_dir.mkdir(parents=True, exist_ok=True)
        for nome in sorted(a_transcodificar):
            transcodificar(csv_dir / nome, utf8_dir / nome)
        marcador.write_text(
            json.dumps(
                {"sha256_origem": a_transcodificar, "gerado_em": agora_iso()},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    for nome in a_transcodificar:
        fontes[nome] = FonteCsv(utf8_dir / nome, ENCODING_UTF8, True)
    return fontes


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
    fontes: dict[str, FonteCsv],
    settings: Settings,
    snapshot_id: str,
) -> MetricasTabela:
    inicio = time.monotonic()
    fonte = fontes[spec.arquivo_origem]
    destino = settings.staging_dir / spec.nome

    leitura = sql_mod.fonte_read_csv(str(fonte.caminho), fonte.encoding)
    select = sql_mod.construir(spec, leitura, snapshot_id)

    linhas_origem = con.execute(f"SELECT count(*) FROM {leitura}").fetchone()[0]

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
