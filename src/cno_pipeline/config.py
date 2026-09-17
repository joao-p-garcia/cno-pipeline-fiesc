"""Configuração central do pipeline.

Todos os parâmetros são sobrescrevíveis por variável de ambiente, para que o
mesmo código rode sem alteração em execução local, em container e em CI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Share público da Receita Federal (Nextcloud). Responde 303 e redireciona para
# o `cno.zip` atual. Não há histórico de versões: o share sempre aponta para a
# publicação mais recente, por isso o versionamento é responsabilidade nossa.
DEFAULT_SOURCE_URL = "https://arquivos.receitafederal.gov.br/s/PC6732BXG9B98W3/download"

# Arquivos esperados dentro do zip. Serve de contrato mínimo de extração:
# se a Receita mudar o pacote, a extração falha de forma explícita em vez de
# produzir uma camada raw silenciosamente incompleta.
ARQUIVOS_ESPERADOS = (
    "cno.csv",
    "cno_areas.csv",
    "cno_cnaes.csv",
    "cno_vinculos.csv",
    "cno_totais.csv",
)

# Os CSVs da Receita são **cp1252** (Windows-1252), não UTF-8 e não ISO-8859-1.
#
# A distinção importa: o `cno.csv` contém 4.881 bytes na faixa 0x80-0x9F, que
# em cp1252 são tipografia legítima (travessão, aspas curvas, bullet) e em
# ISO-8859-1 são caracteres de controle indefinidos. Lido como "latin-1", o
# Python decodifica sem erro e produz caracteres de controle no lugar do texto —
# corrupção silenciosa. Verificado: cp1252 decodifica os cinco arquivos
# integralmente, sem nenhum byte indefinido.
ENCODING_ORIGEM = "cp1252"

# DuckDB não lê cp1252 (aceita utf-8, utf-16 e latin-1), por isso o tratamento
# transcodifica para UTF-8 antes de carregar.
ENCODING_DESTINO = "utf-8"


def _env_str(nome: str, padrao: str) -> str:
    valor = os.environ.get(nome, "").strip()
    return valor or padrao


def _env_int(nome: str, padrao: int) -> int:
    bruto = os.environ.get(nome, "").strip()
    if not bruto:
        return padrao
    try:
        return int(bruto)
    except ValueError as exc:
        raise ValueError(f"{nome} deve ser inteiro, recebido {bruto!r}") from exc


def _env_bool(nome: str, padrao: bool) -> bool:
    bruto = os.environ.get(nome, "").strip().lower()
    if not bruto:
        return padrao
    return bruto in {"1", "true", "yes", "y", "sim"}


@dataclass(frozen=True)
class Settings:
    """Parâmetros de execução do pipeline."""

    source_url: str
    data_dir: Path

    # Rede
    connect_timeout: float
    read_timeout: float
    max_tentativas: int
    backoff_base: float
    chunk_size: int
    user_agent: str

    # Comportamento
    manter_zip: bool

    @property
    def raw_dir(self) -> Path:
        """Camada raw: artefato original e CSVs extraídos, imutáveis."""
        return self.data_dir / "raw"

    @property
    def staging_dir(self) -> Path:
        """Camada intermediária: parquet tipado, 1:1 com a origem."""
        return self.data_dir / "staging"

    @property
    def curated_dir(self) -> Path:
        """Camada final: modelo pronto para análise."""
        return self.data_dir / "curated"

    @property
    def manifests_dir(self) -> Path:
        """Manifestos de proveniência de cada snapshot."""
        return self.raw_dir / "_manifests"

    def snapshot_dir(self, snapshot_id: str) -> Path:
        """Partição estilo Hive, já no formato que as camadas seguintes usam."""
        return self.raw_dir / f"snapshot_date={snapshot_id}"

    @property
    def timeout(self) -> tuple[float, float]:
        return (self.connect_timeout, self.read_timeout)


def get_settings() -> Settings:
    """Monta as configurações a partir do ambiente, com defaults sensatos."""
    raiz_padrao = Path(__file__).resolve().parents[2] / "data"
    return Settings(
        source_url=_env_str("CNO_SOURCE_URL", DEFAULT_SOURCE_URL),
        data_dir=Path(_env_str("CNO_DATA_DIR", str(raiz_padrao))).resolve(),
        connect_timeout=float(_env_int("CNO_CONNECT_TIMEOUT", 15)),
        read_timeout=float(_env_int("CNO_READ_TIMEOUT", 120)),
        max_tentativas=_env_int("CNO_MAX_TENTATIVAS", 5),
        backoff_base=float(_env_int("CNO_BACKOFF_BASE", 2)),
        chunk_size=_env_int("CNO_CHUNK_SIZE", 1024 * 1024),
        user_agent=_env_str(
            "CNO_USER_AGENT",
            "cno-pipeline/0.1 (+https://github.com/joao-p-garcia/cno-pipeline-fiesc)",
        ),
        manter_zip=_env_bool("CNO_MANTER_ZIP", True),
    )
