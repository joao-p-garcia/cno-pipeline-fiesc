"""Manifesto de snapshot: proveniência e controle de idempotência.

O share da Receita não expõe histórico de versões e **não respeita
`If-None-Match`** (testado: devolve 200 e reenvia os 330 MB inteiros). Por isso
o controle de "já baixei esta versão?" fica aqui: guardamos o ETag observado
num `HEAD` e comparamos antes de decidir baixar.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

VERSAO_MANIFESTO = 1


def sha256_arquivo(caminho: Path, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 em streaming, para não carregar 330 MB em memória."""
    h = hashlib.sha256()
    with caminho.open("rb") as fh:
        while bloco := fh.read(chunk_size):
            h.update(bloco)
    return h.hexdigest()


def agora_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ArquivoExtraido:
    nome: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class Manifest:
    """Registro imutável do que foi extraído e de onde veio."""

    snapshot_id: str
    source_url: str
    etag: str | None
    last_modified: str | None
    content_length: int
    sha256_zip: str
    baixado_em: str
    extraido_em: str | None = None
    arquivos: tuple[ArquivoExtraido, ...] = ()
    # Totais publicados pela própria Receita em cno_totais.csv. Servem de
    # oráculo para reconciliação nas etapas seguintes.
    totais_controle: dict[str, int] = field(default_factory=dict)
    versao_manifesto: int = VERSAO_MANIFESTO

    # -- serialização ----------------------------------------------------

    def to_dict(self) -> dict:
        dados = asdict(self)
        dados["arquivos"] = [asdict(a) for a in self.arquivos]
        return dados

    @classmethod
    def from_dict(cls, dados: dict) -> Manifest:
        dados = dict(dados)
        dados["arquivos"] = tuple(ArquivoExtraido(**a) for a in dados.get("arquivos", []))
        # Ignora chaves desconhecidas de versões futuras em vez de estourar.
        conhecidas = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in dados.items() if k in conhecidas})

    # -- persistência ----------------------------------------------------

    def caminho(self, manifests_dir: Path) -> Path:
        return manifests_dir / f"{self.snapshot_id}.json"

    def salvar(self, manifests_dir: Path) -> Path:
        manifests_dir.mkdir(parents=True, exist_ok=True)
        destino = self.caminho(manifests_dir)
        _escrever_json_atomico(destino, self.to_dict())
        # Ponteiro para o snapshot mais recente, para as camadas seguintes
        # não precisarem listar e ordenar diretórios.
        _escrever_json_atomico(
            manifests_dir / "latest.json",
            {"snapshot_id": self.snapshot_id, "atualizado_em": agora_iso()},
        )
        return destino


def _escrever_json_atomico(destino: Path, dados: dict) -> None:
    """Escreve via arquivo temporário + rename, para nunca deixar JSON parcial."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(destino)


def carregar_manifest(manifests_dir: Path, snapshot_id: str) -> Manifest | None:
    caminho = manifests_dir / f"{snapshot_id}.json"
    if not caminho.is_file():
        return None
    try:
        return Manifest.from_dict(json.loads(caminho.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError, ValueError):
        # Manifesto corrompido equivale a não ter manifesto: refaz a extração.
        return None


def carregar_ultimo(manifests_dir: Path) -> Manifest | None:
    ponteiro = manifests_dir / "latest.json"
    if not ponteiro.is_file():
        return None
    try:
        snapshot_id = json.loads(ponteiro.read_text(encoding="utf-8"))["snapshot_id"]
    except (json.JSONDecodeError, KeyError):
        return None
    return carregar_manifest(manifests_dir, snapshot_id)
