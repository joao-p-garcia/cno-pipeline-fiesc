"""Orquestração da extração: inspeciona, baixa, valida e descompacta.

A camada raw é tratada como imutável e endereçada por snapshot. O id do
snapshot vem do `Last-Modified` da fonte (a data em que a Receita publicou),
não da data em que rodamos — assim reprocessar amanhã não cria um snapshot
novo para os mesmos dados.
"""

from __future__ import annotations

import csv
import logging
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..config import ARQUIVOS_ESPERADOS, ENCODING_ORIGEM, Settings
from ..utils import formatar_bytes
from .manifest import (
    ArquivoExtraido,
    Manifest,
    agora_iso,
    carregar_manifest,
    sha256_arquivo,
)
from .source import HttpSource, RemoteInfo

log = logging.getLogger(__name__)

# Nome do arquivo de totais publicado pela Receita, usado como oráculo de
# reconciliação pelas etapas seguintes.
ARQUIVO_TOTAIS = "cno_totais.csv"

# Mapeia os rótulos do cno_totais.csv para os nomes das tabelas, para que a
# validação possa comparar contagem por contagem sem adivinhar.
ROTULOS_TOTAIS = {
    "total de obras": "cno",
    "total de cnaes": "cno_cnaes",
    "total de areas": "cno_areas",
    "total de vinculos": "cno_vinculos",
}


class ErroDeExtracao(RuntimeError):
    """Falha durante a extração ou a descompactação."""


@dataclass(frozen=True)
class ResultadoExtracao:
    manifest: Manifest
    snapshot_dir: Path
    reaproveitado: bool  # True = nada foi baixado, snapshot já estava íntegro


def executar_extracao(settings: Settings, *, forcar: bool = False) -> ResultadoExtracao:
    """Ponto de entrada da etapa de extração.

    Idempotente: se o ETag da fonte bate com o do manifesto local e os arquivos
    conferem, não baixa nada. `forcar=True` ignora o cache.
    """
    with HttpSource(settings) as fonte:
        info = fonte.inspecionar()
        snapshot_id = _derivar_snapshot_id(info)
        snapshot_dir = settings.snapshot_dir(snapshot_id)

        anterior = carregar_manifest(settings.manifests_dir, snapshot_id)
        if not forcar and anterior and _snapshot_integro(anterior, snapshot_dir, info):
            log.info(
                "snapshot %s já está íntegro (etag %s) — nada a baixar",
                snapshot_id,
                anterior.etag,
            )
            return ResultadoExtracao(anterior, snapshot_dir, reaproveitado=True)

        if anterior and not forcar:
            log.info("snapshot %s existe mas não confere; refazendo", snapshot_id)

        snapshot_dir.mkdir(parents=True, exist_ok=True)
        zip_destino = snapshot_dir / "cno.zip"

        log.info("baixando snapshot %s para %s", snapshot_id, zip_destino)
        fonte.baixar(zip_destino, info, on_progress=_logar_progresso())

    sha_zip = sha256_arquivo(zip_destino)
    log.info("sha256 do pacote: %s", sha_zip)

    arquivos = _descompactar(zip_destino, snapshot_dir / "csv")
    totais = _ler_totais_controle(snapshot_dir / "csv" / ARQUIVO_TOTAIS)

    manifest = Manifest(
        snapshot_id=snapshot_id,
        source_url=settings.source_url,
        etag=info.etag,
        last_modified=info.last_modified,
        content_length=zip_destino.stat().st_size,
        sha256_zip=sha_zip,
        baixado_em=agora_iso(),
        extraido_em=agora_iso(),
        arquivos=arquivos,
        totais_controle=totais,
    )
    manifest.salvar(settings.manifests_dir)

    if not settings.manter_zip:
        zip_destino.unlink(missing_ok=True)
        log.info("pacote removido (CNO_MANTER_ZIP=0)")

    log.info("extração concluída: %d arquivos em %s", len(arquivos), snapshot_dir / "csv")
    return ResultadoExtracao(manifest, snapshot_dir, reaproveitado=False)


# -- apoio ---------------------------------------------------------------


def _derivar_snapshot_id(info: RemoteInfo) -> str:
    """Id do snapshot = data de publicação da fonte (AAAA-MM-DD).

    Sem `Last-Modified`, cai para a data de execução — pior, mas não trava o
    pipeline por causa de um cabeçalho ausente.
    """
    publicado = info.data_publicacao
    if publicado:
        return publicado.isoformat()
    log.warning("fonte não informou Last-Modified; usando a data de hoje como id")
    return datetime.now(UTC).date().isoformat()


def _logar_progresso(intervalo_mb: int = 50) -> Callable[[int, int | None], None]:
    """Callback de progresso que loga a cada N MB, sem poluir a saída.

    Barra de progresso não serve aqui: o pipeline roda em container e em
    scheduler, onde a saída vai para arquivo de log, não para um terminal.
    """
    limite = intervalo_mb * 1024 * 1024
    estado = {"ultimo_marco": 0}

    def callback(escritos: int, total: int | None) -> None:
        if escritos - estado["ultimo_marco"] < limite:
            return
        estado["ultimo_marco"] = escritos
        if total:
            log.info(
                "  ... %s de %s (%.0f%%)",
                formatar_bytes(escritos),
                formatar_bytes(total),
                100 * escritos / total,
            )
        else:
            log.info("  ... %s baixados", formatar_bytes(escritos))

    return callback


def _snapshot_integro(manifest: Manifest, snapshot_dir: Path, info: RemoteInfo) -> bool:
    """Confere se o snapshot local corresponde ao que está publicado agora."""
    if info.etag and manifest.etag and info.etag != manifest.etag:
        return False
    if not manifest.arquivos:
        return False

    csv_dir = snapshot_dir / "csv"
    nomes = {a.nome for a in manifest.arquivos}
    if not set(ARQUIVOS_ESPERADOS).issubset(nomes):
        return False

    for arquivo in manifest.arquivos:
        caminho = csv_dir / arquivo.nome
        if not caminho.is_file() or caminho.stat().st_size != arquivo.bytes:
            log.info("arquivo %s ausente ou com tamanho diferente", arquivo.nome)
            return False
    return True


def _descompactar(zip_path: Path, destino: Path) -> tuple[ArquivoExtraido, ...]:
    """Descompacta o pacote validando nomes e conteúdo.

    Recusa membros com caminho (zip-slip) e exige que todos os arquivos do
    contrato estejam presentes.
    """
    destino.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            corrompido = zf.testzip()
            if corrompido is not None:
                raise ErroDeExtracao(f"pacote corrompido no membro {corrompido}")

            membros = [m for m in zf.infolist() if not m.is_dir()]
            for membro in membros:
                _validar_nome_membro(membro.filename)

            nomes = {Path(m.filename).name for m in membros}
            faltando = set(ARQUIVOS_ESPERADOS) - nomes
            if faltando:
                raise ErroDeExtracao(
                    "pacote não contém os arquivos esperados: " + ", ".join(sorted(faltando))
                )

            extraidos: list[ArquivoExtraido] = []
            for membro in membros:
                nome = Path(membro.filename).name
                alvo = destino / nome
                log.info("extraindo %s (%s)", nome, f"{membro.file_size:,} bytes")
                with zf.open(membro) as origem, alvo.open("wb") as saida:
                    while bloco := origem.read(1024 * 1024):
                        saida.write(bloco)
                extraidos.append(
                    ArquivoExtraido(
                        nome=nome,
                        bytes=alvo.stat().st_size,
                        sha256=sha256_arquivo(alvo),
                    )
                )
    except zipfile.BadZipFile as exc:
        raise ErroDeExtracao(f"arquivo baixado não é um zip válido: {exc}") from exc

    return tuple(sorted(extraidos, key=lambda a: a.nome))


def _validar_nome_membro(nome: str) -> None:
    """Barra path traversal: só aceitamos arquivos simples, sem diretórios."""
    caminho = Path(nome)
    if caminho.is_absolute() or ".." in caminho.parts or "\\" in nome:
        raise ErroDeExtracao(f"nome de membro suspeito no zip: {nome!r}")


def _ler_totais_controle(caminho: Path) -> dict[str, int]:
    """Lê o `cno_totais.csv`, que traz as contagens oficiais de cada tabela.

    Esses números viram o oráculo de reconciliação: a etapa de validação
    compara as linhas efetivamente carregadas contra o que a Receita publicou.
    """
    if not caminho.is_file():
        log.warning("%s não encontrado; sem totais de controle", caminho.name)
        return {}

    with caminho.open(encoding=ENCODING_ORIGEM, newline="") as fh:
        linhas = list(csv.DictReader(fh))

    if not linhas:
        log.warning("%s está vazio", caminho.name)
        return {}

    totais: dict[str, int] = {}
    for rotulo, valor in linhas[0].items():
        if rotulo is None or valor is None:
            continue
        chave = ROTULOS_TOTAIS.get(_normalizar(rotulo))
        if chave is None:
            log.warning("rótulo desconhecido em %s: %r", caminho.name, rotulo)
            continue
        try:
            totais[chave] = int(valor.strip())
        except ValueError:
            log.warning("total não numérico para %r: %r", rotulo, valor)

    log.info("totais de controle publicados pela fonte: %s", totais)
    return totais


def _normalizar(texto: str) -> str:
    """minúsculas e sem acento, para casar rótulos de forma estável."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.strip().lower()
