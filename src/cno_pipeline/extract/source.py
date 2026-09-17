"""Acesso HTTP à fonte da Receita Federal.

Comportamento observado do endpoint (verificado em 16/09/2026):

* `GET` responde 303 e redireciona para o `cno.zip` atual (~330 MB).
* `HEAD` devolve `ETag`, `Last-Modified` e `Content-Length` sem baixar o corpo —
  é o que usamos para decidir se vale a pena baixar de novo.
* `If-None-Match` **não é respeitado**: devolve 200 e reenvia o arquivo inteiro.
  Por isso a comparação de versão é feita por nós, contra o manifesto local.
* `Range` **é** suportado (`206 Partial Content`), então o download é resumível.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from ..config import Settings
from ..utils import formatar_bytes

log = logging.getLogger(__name__)


class ErroDeFonte(RuntimeError):
    """Falha ao falar com a fonte que não vale a pena tentar de novo."""


class _RecomecarDoZero(Exception):
    """Sinaliza que o arquivo parcial não serve mais e deve ser descartado."""


class _TransferenciaIncompleta(Exception):
    """A resposta terminou antes do tamanho anunciado.

    Nem todo servidor derruba a conexão de um jeito que o `requests` converta em
    exceção: às vezes o corpo simplesmente acaba cedo. Sem isto, um download
    truncado seria tratado como erro definitivo em vez de ser retomado.
    """


@dataclass(frozen=True)
class RemoteInfo:
    """O que o servidor diz sobre o arquivo, sem baixá-lo."""

    url_final: str
    etag: str | None
    last_modified: str | None
    content_length: int | None
    aceita_range: bool

    @property
    def data_publicacao(self) -> date | None:
        """`Last-Modified` convertido em data, usado como id do snapshot."""
        if not self.last_modified:
            return None
        try:
            return parsedate_to_datetime(self.last_modified).date()
        except (TypeError, ValueError):
            return None


class HttpSource:
    """Cliente HTTP da fonte, com retry e retomada de download."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sessao = requests.Session()
        self.sessao.headers.update({"User-Agent": settings.user_agent})

    def __enter__(self) -> HttpSource:
        return self

    def __exit__(self, *_exc) -> None:
        self.sessao.close()

    # -- inspeção --------------------------------------------------------

    def inspecionar(self) -> RemoteInfo:
        """`HEAD` na fonte: descobre versão e tamanho sem transferir o corpo."""
        resposta = self._com_retry(
            lambda: self.sessao.head(
                self.settings.source_url,
                allow_redirects=True,
                timeout=self.settings.timeout,
            ),
            descricao="HEAD na fonte",
        )
        if resposta.status_code != 200:
            raise ErroDeFonte(
                f"HEAD devolveu {resposta.status_code} para {self.settings.source_url}"
            )

        tamanho = resposta.headers.get("Content-Length")
        info = RemoteInfo(
            url_final=resposta.url,
            etag=_normalizar_etag(resposta.headers.get("ETag")),
            last_modified=resposta.headers.get("Last-Modified"),
            content_length=int(tamanho) if tamanho and tamanho.isdigit() else None,
            aceita_range=self._suporta_range(),
        )
        log.info(
            "fonte inspecionada: etag=%s publicado=%s tamanho=%s",
            info.etag,
            info.data_publicacao,
            formatar_bytes(info.content_length),
        )
        return info

    def _suporta_range(self) -> bool:
        """Testa retomada pedindo 1 byte.

        O `HEAD` desta fonte **não** devolve `Accept-Ranges`, embora o servidor
        responda `206` a um `GET` com `Range`. Confiar no cabeçalho faria o
        pipeline desistir da retomada e rebaixar 315 MB do zero a cada falha de
        rede, então vale a requisição extra de um byte para saber a verdade.
        """
        try:
            resposta = self.sessao.get(
                self.settings.source_url,
                headers={"Range": "bytes=0-0"},
                stream=True,
                allow_redirects=True,
                timeout=self.settings.timeout,
            )
        except requests.RequestException as exc:
            log.warning("sonda de Range falhou (%s); assumindo sem retomada", exc)
            return False

        with resposta:
            suporta = resposta.status_code == 206
            resposta.close()
        log.debug("sonda de Range devolveu %s", resposta.status_code)
        return suporta

    # -- download --------------------------------------------------------

    def baixar(
        self,
        destino: Path,
        info: RemoteInfo,
        on_progress: Callable[[int, int | None], None] | None = None,
    ) -> Path:
        """Baixa o zip para `destino`, retomando de onde parou se possível.

        A escrita é feita num `.part` e só é promovida ao nome final depois da
        conferência de tamanho — nunca deixa um arquivo truncado parecendo
        completo.
        """
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_name(destino.name + ".part")

        limite = self.settings.max_tentativas
        for tentativa in range(1, limite + 1):
            try:
                self._baixar_uma_vez(parcial, info, on_progress)
                break
            except _RecomecarDoZero:
                log.warning("arquivo parcial inválido; recomeçando o download")
                parcial.unlink(missing_ok=True)
            except (_TransferenciaIncompleta, requests.RequestException, OSError) as exc:
                if tentativa == limite:
                    raise ErroDeFonte(f"download falhou após {limite} tentativas: {exc}") from exc
                espera = self.settings.backoff_base**tentativa
                log.warning(
                    "falha no download (tentativa %d/%d): %s — aguardando %.0fs",
                    tentativa,
                    limite,
                    exc,
                    espera,
                )
                time.sleep(espera)
        else:
            raise ErroDeFonte(f"download não concluiu em {limite} tentativas")

        baixado = parcial.stat().st_size
        if info.content_length is not None and baixado != info.content_length:
            parcial.unlink(missing_ok=True)
            raise ErroDeFonte(f"tamanho final {baixado} difere do anunciado {info.content_length}")

        parcial.replace(destino)
        log.info("download concluído: %s (%s)", destino.name, formatar_bytes(baixado))
        return destino

    def _baixar_uma_vez(
        self,
        parcial: Path,
        info: RemoteInfo,
        on_progress: Callable[[int, int | None], None] | None,
    ) -> None:
        ja_temos = parcial.stat().st_size if parcial.exists() else 0

        if info.content_length is not None and ja_temos > info.content_length:
            raise _RecomecarDoZero
        if info.content_length is not None and ja_temos == info.content_length:
            return  # já está completo

        cabecalhos: dict[str, str] = {}
        if ja_temos and info.aceita_range:
            cabecalhos["Range"] = f"bytes={ja_temos}-"
            # Se a publicação mudou no meio do caminho, o servidor deve recusar
            # a retomada em vez de costurar bytes de versões diferentes.
            if info.etag:
                cabecalhos["If-Range"] = f'"{info.etag}"'

        with self.sessao.get(
            self.settings.source_url,
            headers=cabecalhos,
            stream=True,
            allow_redirects=True,
            timeout=self.settings.timeout,
        ) as resposta:
            resposta.raise_for_status()

            etag_agora = _normalizar_etag(resposta.headers.get("ETag"))
            if info.etag and etag_agora and etag_agora != info.etag:
                raise ErroDeFonte(
                    "a publicação mudou durante o download "
                    f"({info.etag} -> {etag_agora}); rode novamente"
                )

            if ja_temos and resposta.status_code == 200:
                # Servidor ignorou o Range: o corpo vem do início, então o que
                # já tínhamos não pode ser reaproveitado.
                raise _RecomecarDoZero
            if (
                ja_temos
                and resposta.status_code == 206
                and not _range_confere(resposta.headers.get("Content-Range"), ja_temos)
            ):
                raise _RecomecarDoZero

            modo = "ab" if ja_temos and resposta.status_code == 206 else "wb"
            if modo == "wb":
                ja_temos = 0

            escritos = ja_temos
            with parcial.open(modo) as fh:
                for bloco in resposta.iter_content(self.settings.chunk_size):
                    if not bloco:
                        continue
                    fh.write(bloco)
                    escritos += len(bloco)
                    if on_progress:
                        on_progress(escritos, info.content_length)

        if info.content_length is not None and escritos < info.content_length:
            raise _TransferenciaIncompleta(f"recebidos {escritos} de {info.content_length} bytes")

    # -- infra -----------------------------------------------------------

    def _com_retry(
        self, acao: Callable[[], requests.Response], descricao: str
    ) -> requests.Response:
        ultima: Exception | None = None
        for tentativa in range(1, self.settings.max_tentativas + 1):
            try:
                return acao()
            except requests.RequestException as exc:
                ultima = exc
                if tentativa == self.settings.max_tentativas:
                    break
                espera = self.settings.backoff_base**tentativa
                log.warning(
                    "%s falhou (%d/%d): %s — aguardando %.0fs",
                    descricao,
                    tentativa,
                    self.settings.max_tentativas,
                    exc,
                    espera,
                )
                time.sleep(espera)
        raise ErroDeFonte(f"{descricao} falhou: {ultima}") from ultima


def _normalizar_etag(bruto: str | None) -> str | None:
    """Remove aspas e o prefixo `W/` das ETags fracas, para comparar valores."""
    if not bruto:
        return None
    valor = bruto.strip()
    if valor.startswith("W/"):
        valor = valor[2:]
    return valor.strip('"') or None


def _range_confere(content_range: str | None, esperado_inicio: int) -> bool:
    """Confirma que o 206 começa exatamente onde o arquivo parcial termina."""
    if not content_range:
        return False
    try:
        faixa = content_range.split()[1].split("/")[0]
        inicio = int(faixa.split("-")[0])
    except (IndexError, ValueError):
        return False
    return inicio == esperado_inicio
