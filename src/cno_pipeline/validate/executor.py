"""Execução das regras de validação e produção do relatório.

Duas famílias de verificação, com naturezas diferentes:

**Reconciliação** confronta o que carregamos com os totais que a *própria
Receita* publica no `cno_totais.csv`. É a única checagem que olha para fora do
pipeline — as demais comparam o dado com as regras que nós mesmos escrevemos, e
por isso não detectariam uma extração que perdeu metade do arquivo.

**Regras** verificam o contrato da camada tratada: chave, integridade
referencial, domínios e coerência interna.

O comando falha (código de saída 1) quando há divergência de reconciliação ou
violação de regra com severidade de erro. Avisos são reportados e não derrubam
a execução.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from ..config import Settings
from ..extract.manifest import agora_iso
from ..transform.schema import TABELAS, TOTAIS_CONTROLE
from .regras import REGRAS, Regra, Severidade

log = logging.getLogger(__name__)

MAX_EXEMPLOS = 5


class ErroDeValidacao(RuntimeError):
    """Impossível executar a validação (dado ausente, não violação de regra)."""


@dataclass(frozen=True)
class Reconciliacao:
    tabela: str
    linhas_origem: int
    total_oficial: int | None
    duplicatas_removidas: int
    linhas_tratadas: int

    @property
    def confere(self) -> bool:
        """Sem total publicado não há o que conferir; não é falha."""
        if self.total_oficial is None:
            return True
        return self.linhas_origem == self.total_oficial

    @property
    def diferenca(self) -> int:
        if self.total_oficial is None:
            return 0
        return self.linhas_origem - self.total_oficial


@dataclass(frozen=True)
class ResultadoRegra:
    nome: str
    descricao: str
    severidade: str
    violacoes: int
    exemplos: tuple[dict, ...]

    @property
    def passou(self) -> bool:
        return self.violacoes == 0


@dataclass(frozen=True)
class Relatorio:
    snapshot_id: str
    reconciliacoes: tuple[Reconciliacao, ...]
    regras: tuple[ResultadoRegra, ...]
    segundos: float

    @property
    def reconciliacoes_divergentes(self) -> tuple[Reconciliacao, ...]:
        return tuple(r for r in self.reconciliacoes if not r.confere)

    @property
    def erros(self) -> tuple[ResultadoRegra, ...]:
        return tuple(
            r for r in self.regras if not r.passou and r.severidade == Severidade.ERRO.value
        )

    @property
    def avisos(self) -> tuple[ResultadoRegra, ...]:
        return tuple(
            r for r in self.regras if not r.passou and r.severidade == Severidade.AVISO.value
        )

    @property
    def passou(self) -> bool:
        return not self.erros and not self.reconciliacoes_divergentes


# ---------------------------------------------------------------------------


def executar_validacao(settings: Settings, *, snapshot_id: str | None = None) -> Relatorio:
    """Valida a camada tratada de um snapshot."""
    inicio = time.monotonic()
    manifesto = _carregar_manifesto_staging(settings, snapshot_id)
    snapshot = manifesto["snapshot_id"]

    reconciliacoes = _reconciliar(manifesto)

    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{settings.duckdb_memory_limit}'")
    con.execute(f"SET threads = {settings.duckdb_threads}")
    try:
        tabelas = _mapear_tabelas(settings, snapshot)
        resultados = tuple(_avaliar(con, regra, tabelas) for regra in REGRAS)
    finally:
        con.close()

    relatorio = Relatorio(
        snapshot_id=snapshot,
        reconciliacoes=reconciliacoes,
        regras=resultados,
        segundos=time.monotonic() - inicio,
    )
    _salvar_relatorio(settings, relatorio)

    log.info(
        "validação concluída em %.1fs: %d regras, %d erros, %d avisos",
        relatorio.segundos,
        len(relatorio.regras),
        len(relatorio.erros),
        len(relatorio.avisos),
    )
    return relatorio


# ---------------------------------------------------------------------------


def _carregar_manifesto_staging(settings: Settings, snapshot_id: str | None) -> dict:
    dir_manifestos = settings.staging_dir / "_manifests"
    if snapshot_id:
        caminho = dir_manifestos / f"{snapshot_id}.json"
    else:
        disponiveis = sorted(dir_manifestos.glob("*.json"))
        if not disponiveis:
            raise ErroDeValidacao("nenhuma camada tratada encontrada; rode `cno transform` antes")
        caminho = disponiveis[-1]

    if not caminho.is_file():
        raise ErroDeValidacao(f"manifesto de tratamento não encontrado: {caminho}")
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ErroDeValidacao(f"manifesto ilegível em {caminho}: {exc}") from exc


def _reconciliar(manifesto: dict) -> tuple[Reconciliacao, ...]:
    """Confronta o carregado com os totais publicados pela fonte.

    A comparação usa `linhas_origem`, antes da deduplicação: os totais da Receita
    contam as linhas do arquivo, duplicatas incluídas. Comparar contra o número
    pós-dedup acusaria divergência onde o pipeline funcionou corretamente.
    """
    totais = manifesto.get("totais_controle", {})
    metricas = {t["nome"]: t for t in manifesto.get("tabelas", [])}

    reconciliacoes = []
    for spec in TABELAS:
        m = metricas.get(spec.nome)
        if m is None:
            continue
        chave = TOTAIS_CONTROLE.get(spec.nome)
        reconciliacoes.append(
            Reconciliacao(
                tabela=spec.nome,
                linhas_origem=m["linhas_origem"],
                total_oficial=totais.get(chave) if chave else None,
                duplicatas_removidas=m["duplicatas_removidas"],
                linhas_tratadas=m["linhas_destino"],
            )
        )
    return tuple(reconciliacoes)


def _mapear_tabelas(settings: Settings, snapshot_id: str) -> dict[str, str]:
    """Nome da tabela -> expressão `read_parquet` da partição do snapshot."""
    mapa = {}
    for spec in TABELAS:
        particao = settings.staging_dir / spec.nome / f"snapshot_date={snapshot_id}"
        if not particao.is_dir():
            raise ErroDeValidacao(
                f"partição ausente para {spec.nome} no snapshot {snapshot_id}; "
                "rode `cno transform` antes"
            )
        mapa[spec.nome] = f"read_parquet('{particao}/**/*.parquet')"
    return mapa


def _avaliar(
    con: duckdb.DuckDBPyConnection, regra: Regra, tabelas: dict[str, str]
) -> ResultadoRegra:
    consulta = regra.violacoes.format(**tabelas)

    try:
        violacoes = con.execute(f"SELECT count(*) FROM ({consulta})").fetchone()[0]
    except duckdb.Error as exc:
        # Regra quebrada é problema nosso, não do dado: falha alto e claro em
        # vez de passar como se a regra tivesse sido cumprida.
        raise ErroDeValidacao(f"regra {regra.nome!r} não pôde ser avaliada: {exc}") from exc

    exemplos: tuple[dict, ...] = ()
    if violacoes:
        colunas = ", ".join(regra.amostra) if regra.amostra else "*"
        linhas = con.execute(f"SELECT {colunas} FROM ({consulta}) LIMIT {MAX_EXEMPLOS}").fetchall()
        nomes = [d[0] for d in con.description]
        exemplos = tuple(dict(zip(nomes, linha, strict=False)) for linha in linhas)

    nivel = logging.ERROR if regra.severidade == Severidade.ERRO else logging.WARNING
    if violacoes:
        log.log(nivel, "%-34s %s violações", regra.nome, f"{violacoes:,}")

    return ResultadoRegra(
        nome=regra.nome,
        descricao=regra.descricao,
        severidade=regra.severidade.value,
        violacoes=violacoes,
        exemplos=exemplos,
    )


def _salvar_relatorio(settings: Settings, relatorio: Relatorio) -> Path:
    destino = settings.staging_dir / "_validacao" / f"{relatorio.snapshot_id}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    conteudo = {
        "snapshot_id": relatorio.snapshot_id,
        "avaliado_em": agora_iso(),
        "segundos": round(relatorio.segundos, 1),
        "passou": relatorio.passou,
        "reconciliacao": [
            {**asdict(r), "confere": r.confere, "diferenca": r.diferenca}
            for r in relatorio.reconciliacoes
        ],
        "regras": [
            {**asdict(r), "passou": r.passou, "exemplos": [_serializar(e) for e in r.exemplos]}
            for r in relatorio.regras
        ],
    }
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(conteudo, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(destino)
    return destino


def _serializar(exemplo: dict) -> dict:
    return {k: (str(v) if v is not None else None) for k, v in exemplo.items()}
