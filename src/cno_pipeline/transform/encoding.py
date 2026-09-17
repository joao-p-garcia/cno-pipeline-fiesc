"""Transcodificação cp1252 → UTF-8.

Existe por uma limitação concreta: o DuckDB lê `utf-8`, `utf-16` e `latin-1`,
mas **não** cp1252, que é o encoding real da fonte. E ler como `latin-1` não
serve — os 4.881 bytes da faixa `0x80-0x9F` do `cno.csv` virariam caracteres de
controle silenciosamente (ver `config.ENCODING_ORIGEM`).

A alternativa seria corrigir os caracteres em SQL depois de carregar, mas isso
exigiria lembrar de aplicar a correção em cada coluna de texto, uma por uma —
esquecer uma seria uma corrupção invisível. Transcodificar o arquivo resolve o
problema na entrada, de uma vez, para todas as colunas.
"""

from __future__ import annotations

import codecs
import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import ENCODING_DESTINO, ENCODING_ORIGEM
from ..utils import formatar_bytes

log = logging.getLogger(__name__)

CHUNK = 8 * 1024 * 1024


class ErroDeTranscodificacao(RuntimeError):
    """O arquivo não pôde ser decodificado no encoding declarado."""


@dataclass(frozen=True)
class ResultadoTranscodificacao:
    origem: Path
    destino: Path
    bytes_lidos: int
    bytes_escritos: int
    caracteres_c1: int  # quantos vieram da faixa que latin-1 corromperia


def transcodificar(
    origem: Path,
    destino: Path,
    *,
    encoding_origem: str = ENCODING_ORIGEM,
    encoding_destino: str = ENCODING_DESTINO,
) -> ResultadoTranscodificacao:
    """Reescreve `origem` em `destino` mudando o encoding, em streaming.

    Escreve num `.part` e renomeia só ao final, para que uma interrupção não
    deixe um arquivo truncado que pareça válido para a etapa seguinte.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".part")

    decoder = codecs.getincrementaldecoder(encoding_origem)(errors="strict")
    lidos = escritos = c1 = 0

    try:
        with origem.open("rb") as entrada, parcial.open("wb") as saida:
            while bloco := entrada.read(CHUNK):
                lidos += len(bloco)
                c1 += sum(1 for b in bloco if 0x80 <= b <= 0x9F)
                texto = decoder.decode(bloco)
                dados = texto.encode(encoding_destino)
                saida.write(dados)
                escritos += len(dados)

            resto = decoder.decode(b"", final=True)
            if resto:
                dados = resto.encode(encoding_destino)
                saida.write(dados)
                escritos += len(dados)
    except UnicodeDecodeError as exc:
        parcial.unlink(missing_ok=True)
        raise ErroDeTranscodificacao(f"{origem.name} não é {encoding_origem}: {exc}") from exc
    except Exception:
        parcial.unlink(missing_ok=True)
        raise

    parcial.replace(destino)

    log.info(
        "transcodificado %s: %s -> %s (%d caracteres da faixa C1)",
        origem.name,
        formatar_bytes(lidos),
        formatar_bytes(escritos),
        c1,
    )
    return ResultadoTranscodificacao(
        origem=origem,
        destino=destino,
        bytes_lidos=lidos,
        bytes_escritos=escritos,
        caracteres_c1=c1,
    )
