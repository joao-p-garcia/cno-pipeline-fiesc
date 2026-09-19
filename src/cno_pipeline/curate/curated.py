"""Camada curada: da staging para o modelo que a análise consome.

Idempotente e não destrutiva, como as etapas anteriores: a staging nunca é
tocada, e reprocessar um snapshot só reescreve a partição daquele snapshot.

A etapa materializa quatro tabelas. `obras_analitico` tem uma linha por obra e
serve ao drill-down; os três marts são pré-agregados e são o que o dashboard lê,
porque um Streamlit não pode varrer 3,6 M de linhas a cada clique num filtro.
Todos derivam da mesma definição — o app não recalcula regra de negócio, e é isso
que impede o dashboard e o notebook de divergirem com o tempo.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import duckdb

from ..config import Settings
from ..extract.manifest import agora_iso
from ..utils import formatar_bytes
from . import sql as sql_mod
from .geocodificacao import registrar_udfs

log = logging.getLogger(__name__)

TABELA_ANALITICA = "obras_analitico"


class ErroDeCuradoria(RuntimeError):
    """Falha durante a curadoria."""


@dataclass(frozen=True)
class MetricasTabela:
    nome: str
    linhas: int
    arquivos_parquet: int
    bytes_parquet: int
    segundos: float


@dataclass(frozen=True)
class MetricasGeo:
    """Quanto da base ficou geocodificada, e por qual caminho."""

    obras: int
    completos: int
    curtos_recuperados: int
    sem_geocodificacao: int
    municipios_com_ancora: int
    curtos_sem_ancora: int
    # Preenchido depois da materialização: a plausibilidade só existe quando o
    # ponto pode ser comparado com a mediana do seu município.
    plausiveis: int = 0

    @property
    def cobertura(self) -> float:
        """Bruta: tudo que decodificou, plausível ou não."""
        if not self.obras:
            return 0.0
        return (self.completos + self.curtos_recuperados) / self.obras

    @property
    def cobertura_util(self) -> float:
        """A que vale para mapa e relatório: só o ponto que cai no município certo.

        É esta que deve ser citada. A diferença entre as duas são 48 mil Plus
        Codes válidos apontando para o lugar errado, alguns do outro lado do
        planeta.
        """
        if not self.obras:
            return 0.0
        return self.plausiveis / self.obras


@dataclass(frozen=True)
class ResultadoCuradoria:
    snapshot_id: str
    curated_dir: Path
    tabelas: tuple[MetricasTabela, ...]
    geo: MetricasGeo
    segundos_total: float

    def tabela(self, nome: str) -> MetricasTabela:
        for m in self.tabelas:
            if m.nome == nome:
                return m
        raise KeyError(nome)


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------


def executar_curadoria(settings: Settings, *, snapshot_id: str | None = None) -> ResultadoCuradoria:
    """Modela a camada curada a partir de um snapshot já tratado."""
    inicio = time.monotonic()
    manifesto = _carregar_manifesto_staging(settings, snapshot_id)
    snapshot = manifesto["snapshot_id"]
    staging = str(settings.staging_dir).replace("\\", "/")

    con = _conectar(settings)
    try:
        registrar_udfs(con)
        con.execute(f"CREATE OR REPLACE TEMP VIEW base AS {sql_mod.sql_base(staging, snapshot)}")

        geo = _geocodificar(con)

        tabelas = [
            _materializar(
                con,
                settings,
                snapshot,
                TABELA_ANALITICA,
                sql_mod.sql_obras_analitico(staging, snapshot),
                particoes=("snapshot_date", "uf"),
            )
        ]

        # Os marts leem o parquet recém-escrito, não a consulta em memória: assim
        # o que eles agregam é literalmente o que ficou em disco, e uma diferença
        # entre os dois não tem como passar despercebida.
        analitico = _read_parquet(settings.curated_dir / TABELA_ANALITICA, snapshot)
        plausiveis = con.execute(
            f"SELECT count(*) FILTER (WHERE geo_plausivel) FROM {analitico}"
        ).fetchone()[0]
        geo = replace(geo, plausiveis=plausiveis)
        log.info(
            "plausibilidade: %s de %s pontos caem no município declarado "
            "(%.1f%% da base, contra %.1f%% brutos)",
            f"{plausiveis:,}",
            f"{geo.completos + geo.curtos_recuperados:,}",
            geo.cobertura_util * 100,
            geo.cobertura * 100,
        )

        for nome, construtor in sql_mod.MARTS.items():
            tabelas.append(
                _materializar(
                    con,
                    settings,
                    snapshot,
                    nome,
                    construtor(analitico),
                    particoes=("snapshot_date",),
                )
            )
    finally:
        con.close()

    resultado = ResultadoCuradoria(
        snapshot_id=snapshot,
        curated_dir=settings.curated_dir,
        tabelas=tuple(tabelas),
        geo=geo,
        segundos_total=time.monotonic() - inicio,
    )
    _salvar_manifesto(settings, resultado)

    log.info(
        "curadoria concluída em %.1fs: %s obras, %.1f%% com ponto utilizável",
        resultado.segundos_total,
        f"{geo.obras:,}",
        geo.cobertura_util * 100,
    )
    return resultado


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------


def _carregar_manifesto_staging(settings: Settings, snapshot_id: str | None) -> dict:
    dir_manifestos = settings.staging_dir / "_manifests"
    if snapshot_id:
        caminho = dir_manifestos / f"{snapshot_id}.json"
    else:
        disponiveis = sorted(dir_manifestos.glob("*.json"))
        if not disponiveis:
            raise ErroDeCuradoria("nenhuma camada tratada encontrada; rode `cno transform` antes")
        caminho = disponiveis[-1]

    if not caminho.is_file():
        raise ErroDeCuradoria(f"manifesto de tratamento não encontrado: {caminho}")
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ErroDeCuradoria(f"manifesto ilegível em {caminho}: {exc}") from exc


def _conectar(settings: Settings) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{settings.duckdb_memory_limit}'")
    con.execute(f"SET threads = {settings.duckdb_threads}")
    temp = settings.curated_dir / "_tmp"
    temp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory = '{str(temp).replace(chr(92), '/')}'")
    return con


def _geocodificar(con: duckdb.DuckDBPyConnection) -> MetricasGeo:
    """Decodifica os Plus Codes completos e recupera os curtos pela âncora municipal."""
    inicio = time.monotonic()

    con.execute(sql_mod.SQL_GEO_COMPLETO)
    con.execute(sql_mod.SQL_ANCORAS)
    con.execute(sql_mod.SQL_GEO_CURTO)

    obras, completos = con.execute("""
        SELECT count(*),
               count(*) FILTER (WHERE b.forma_plus_code = 'completo' AND g.latitude IS NOT NULL)
        FROM base b LEFT JOIN geo_completo g USING (codigo_norm)
    """).fetchone()

    curtos_ok, curtos_total = con.execute("""
        SELECT
            count(*) FILTER (WHERE gc.latitude IS NOT NULL),
            count(*)
        FROM base b
        LEFT JOIN geo_curto gc
               ON gc.codigo_norm = b.codigo_norm
              AND gc.codigo_municipio = b.codigo_municipio
        WHERE b.forma_plus_code = 'curto'
    """).fetchone()

    municipios = con.execute("SELECT count(*) FROM ancoras").fetchone()[0]

    metricas = MetricasGeo(
        obras=obras,
        completos=completos,
        curtos_recuperados=curtos_ok,
        sem_geocodificacao=obras - completos - curtos_ok,
        municipios_com_ancora=municipios,
        curtos_sem_ancora=curtos_total - curtos_ok,
    )
    log.info(
        "geocodificação em %.1fs: %s completos + %s curtos recuperados = %.1f%% "
        "(%s municípios com âncora, %s curtos sem)",
        time.monotonic() - inicio,
        f"{metricas.completos:,}",
        f"{metricas.curtos_recuperados:,}",
        metricas.cobertura * 100,
        f"{metricas.municipios_com_ancora:,}",
        f"{metricas.curtos_sem_ancora:,}",
    )
    return metricas


def _read_parquet(destino: Path, snapshot_id: str) -> str:
    caminho = str(destino / f"snapshot_date={snapshot_id}" / "**" / "*.parquet")
    return f"read_parquet('{caminho.replace(chr(92), '/')}', hive_partitioning=true)"


def _materializar(
    con: duckdb.DuckDBPyConnection,
    settings: Settings,
    snapshot_id: str,
    nome: str,
    select: str,
    *,
    particoes: tuple[str, ...],
) -> MetricasTabela:
    inicio = time.monotonic()
    destino = settings.curated_dir / nome

    # Só a partição deste snapshot: reprocessar um não pode apagar os outros.
    particao = destino / f"snapshot_date={snapshot_id}"
    shutil.rmtree(particao, ignore_errors=True)
    destino.mkdir(parents=True, exist_ok=True)

    alvo = str(destino).replace("\\", "/")
    con.execute(f"""
        COPY ({select})
        TO '{alvo}'
        (FORMAT PARQUET,
         PARTITION_BY ({", ".join(particoes)}),
         COMPRESSION zstd,
         OVERWRITE_OR_IGNORE true)
    """)

    arquivos = sorted(particao.rglob("*.parquet"))
    if not arquivos:
        raise ErroDeCuradoria(f"{nome} não produziu nenhum arquivo em {particao}")

    linhas = con.execute(f"SELECT count(*) FROM {_read_parquet(destino, snapshot_id)}").fetchone()[
        0
    ]
    metricas = MetricasTabela(
        nome=nome,
        linhas=linhas,
        arquivos_parquet=len(arquivos),
        bytes_parquet=sum(a.stat().st_size for a in arquivos),
        segundos=time.monotonic() - inicio,
    )
    log.info(
        "%-20s %12s linhas · %9s em %d arquivos · %.1fs",
        metricas.nome,
        f"{metricas.linhas:,}",
        formatar_bytes(metricas.bytes_parquet),
        metricas.arquivos_parquet,
        metricas.segundos,
    )
    return metricas


def _salvar_manifesto(settings: Settings, resultado: ResultadoCuradoria) -> Path:
    destino = settings.curated_dir / "_manifests" / f"{resultado.snapshot_id}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    conteudo = {
        "snapshot_id": resultado.snapshot_id,
        "gerado_em": agora_iso(),
        "segundos": round(resultado.segundos_total, 1),
        "geocodificacao": {
            **asdict(resultado.geo),
            "cobertura": round(resultado.geo.cobertura, 4),
            "cobertura_util": round(resultado.geo.cobertura_util, 4),
        },
        "tabelas": [asdict(m) for m in resultado.tabelas],
    }
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(conteudo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(destino)
    return destino
