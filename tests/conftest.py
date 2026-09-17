"""Fixtures dos testes.

O servidor fake existe para exercitar o extrator sem depender da Receita:
os testes precisam rodar em CI, offline, em segundos, e precisam conseguir
simular falhas que não dá para provocar num servidor real (queda no meio da
transferência, mudança de publicação durante o download, servidor que ignora
`Range`).
"""

from __future__ import annotations

import io
import threading
import zipfile
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cno_pipeline.config import Settings

LAST_MODIFIED = "Sat, 12 Sep 2026 04:59:45 GMT"

# Conteúdo mínimo que respeita o contrato real: mesmos nomes de arquivo,
# mesmo encoding latin-1 e o cno_totais.csv com os rótulos originais.
CSVS = {
    "cno.csv": (
        '"CNO","Nome do município","Estado","Área total"\n'
        '010010092278,"BRASÍLIA","DF",412.00\n'
        '010010119379,"SÃO PAULO","SP",5258.21\n'
    ),
    "cno_areas.csv": (
        '"CNO","Categoria","Metragem"\n'
        '010010092278,"Obra Nova",412.00\n'
        '010010119379,"Reforma",5258.21\n'
        '010010119379,"Acréscimo",100.00\n'
    ),
    "cno_cnaes.csv": '"CNO","CNAE"\n010010092278,4120400\n010010119379,4399103\n',
    "cno_vinculos.csv": '"CNO","Qualificação do contribuinte"\n010010092278,0053\n',
    "cno_totais.csv": (
        '"Total de obras","Total de cnaes","Total de áreas","Total de vínculos"\n'
        '"00000000002","00000000002","00000000003","00000000001"\n'
    ),
}


def construir_zip(extra: dict[str, str] | None = None) -> bytes:
    """Monta em memória um zip com a mesma cara do pacote da Receita."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome, conteudo in CSVS.items():
            zf.writestr(nome, conteudo.encode("latin-1"))
        for nome, conteudo in (extra or {}).items():
            zf.writestr(nome, conteudo.encode("latin-1"))
    return buffer.getvalue()


@dataclass
class EstadoServidor:
    """Controla o comportamento do servidor fake durante um teste."""

    corpo: bytes
    etag: str = "etag-de-teste-1"
    last_modified: str = LAST_MODIFIED
    # Se >0, a resposta de corpo é cortada após N bytes, simulando queda de
    # conexão no meio do download.
    cortar_apos: int = 0
    # Por padrão o corte acontece só na primeira resposta (para testar a
    # retomada). Com `cortar_sempre`, toda resposta é truncada — é assim que
    # se testa o esgotamento das tentativas.
    cortar_sempre: bool = False
    # Se True, responde 200 (corpo inteiro) mesmo quando pedem Range.
    ignorar_range: bool = False
    # Contadores para os testes conferirem o que aconteceu.
    requisicoes: list[str] = field(default_factory=list)
    ja_cortou: bool = False


class _Handler(BaseHTTPRequestHandler):
    estado: EstadoServidor  # injetado pela fixture

    def log_message(self, *_args) -> None:  # silencia o log do http.server
        pass

    def _cabecalhos_comuns(self) -> None:
        self.send_header("ETag", f'"{self.estado.etag}"')
        self.send_header("Last-Modified", self.estado.last_modified)
        self.send_header("Content-Type", "application/zip")

    def do_HEAD(self) -> None:  # noqa: N802 (nome exigido por BaseHTTPRequestHandler)
        self.estado.requisicoes.append("HEAD")
        self.send_response(200)
        self._cabecalhos_comuns()
        self.send_header("Content-Length", str(len(self.estado.corpo)))
        # De propósito NÃO mandamos Accept-Ranges: é assim que a fonte real se
        # comporta, e o extrator precisa descobrir o suporte por conta própria.
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        faixa = self.headers.get("Range")
        self.estado.requisicoes.append(f"GET {faixa or 'completo'}")
        corpo = self.estado.corpo
        total = len(corpo)

        if faixa and not self.estado.ignorar_range:
            inicio = int(faixa.split("=")[1].split("-")[0])
            fim_txt = faixa.split("=")[1].split("-")[1]
            fim = int(fim_txt) if fim_txt else total - 1
            fatia = corpo[inicio : fim + 1]
            self.send_response(206)
            self._cabecalhos_comuns()
            self.send_header("Content-Range", f"bytes {inicio}-{fim}/{total}")
            self.send_header("Content-Length", str(len(fatia)))
            self.end_headers()
            self.wfile.write(fatia)
            return

        self.send_response(200)
        self._cabecalhos_comuns()
        self.send_header("Content-Length", str(total))
        self.end_headers()

        if self.estado.cortar_apos and (self.estado.cortar_sempre or not self.estado.ja_cortou):
            # Escreve só um pedaço e fecha: o cliente vê a conexão cair.
            self.estado.ja_cortou = True
            self.wfile.write(corpo[: self.estado.cortar_apos])
            self.wfile.flush()
            self.close_connection = True
            return

        self.wfile.write(corpo)


@pytest.fixture
def estado_servidor() -> EstadoServidor:
    return EstadoServidor(corpo=construir_zip())


@pytest.fixture
def servidor(estado_servidor: EstadoServidor):
    """Sobe o servidor fake numa porta livre e devolve a URL."""
    handler = type("HandlerDoTeste", (_Handler,), {"estado": estado_servidor})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/cno.zip"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def settings(tmp_path: Path, servidor: str) -> Settings:
    """Settings apontando para o servidor fake, com backoff zerado."""
    return Settings(
        source_url=servidor,
        data_dir=tmp_path / "data",
        connect_timeout=5.0,
        read_timeout=5.0,
        max_tentativas=4,
        backoff_base=0.0,  # testes não podem dormir
        # Chunk pequeno de propósito: o payload de teste tem poucas centenas de
        # bytes, e com chunk grande nenhum bloco chegaria a ser gravado antes da
        # queda — o teste de retomada não exercitaria a retomada.
        chunk_size=64,
        user_agent="cno-pipeline-test",
        manter_zip=True,
    )
