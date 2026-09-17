"""Testes da transcodificação cp1252 → UTF-8."""

from __future__ import annotations

from pathlib import Path

import pytest

from cno_pipeline.transform.encoding import ErroDeTranscodificacao, transcodificar

# Bytes da faixa C1: tipografia em cp1252, indefinidos em ISO-8859-1.
TRAVESSAO = b"\x96"
ASPAS_ABRE = b"\x93"
ASPAS_FECHA = b"\x94"

# Os cinco bytes que nem cp1252 define.
INDEFINIDOS = [b"\x81", b"\x8d", b"\x8f", b"\x90", b"\x9d"]


def test_converte_acentuacao_comum(tmp_path: Path):
    origem = tmp_path / "e.csv"
    origem.write_bytes("BRASÍLIA;SÃO PAULO;ÁGUA\n".encode("cp1252"))

    r = transcodificar(origem, tmp_path / "s.csv")

    assert r.destino.read_text("utf-8") == "BRASÍLIA;SÃO PAULO;ÁGUA\n"


def test_tipografia_c1_vira_utf8_correto(tmp_path: Path):
    """O caso que motiva o módulo: 0x96 tem que virar travessão, não controle."""
    origem = tmp_path / "e.csv"
    origem.write_bytes(b"OBRA " + TRAVESSAO + b" FASE 2\n")

    r = transcodificar(origem, tmp_path / "s.csv")
    texto = r.destino.read_text("utf-8")

    assert texto == "OBRA – FASE 2\n"  # travessão de verdade
    assert "" not in texto  # e não o caractere de controle
    assert r.caracteres_c1 == 1


def test_conta_todos_os_caracteres_c1(tmp_path: Path):
    origem = tmp_path / "e.csv"
    origem.write_bytes(TRAVESSAO + ASPAS_ABRE + b"texto" + ASPAS_FECHA + b"\n")

    r = transcodificar(origem, tmp_path / "s.csv")

    assert r.caracteres_c1 == 3
    assert r.destino.read_text("utf-8") == "–“texto”\n"


def test_arquivo_maior_que_o_chunk(tmp_path: Path):
    """Garante que a decodificação incremental não corta nada entre blocos."""
    linha = "obra – ÁGUA çã\n"
    conteudo = linha * 200_000  # ~3 MB
    origem = tmp_path / "e.csv"
    origem.write_bytes(conteudo.encode("cp1252"))

    r = transcodificar(origem, tmp_path / "s.csv")

    assert r.destino.read_text("utf-8") == conteudo
    assert r.caracteres_c1 == 200_000  # um travessão por linha


@pytest.mark.parametrize("byte_indefinido", INDEFINIDOS)
def test_byte_indefinido_em_cp1252_falha_explicitamente(tmp_path: Path, byte_indefinido: bytes):
    """Melhor falhar do que gravar `?` e seguir com dado corrompido."""
    origem = tmp_path / "e.csv"
    origem.write_bytes(b"antes" + byte_indefinido + b"depois\n")
    destino = tmp_path / "s.csv"

    with pytest.raises(ErroDeTranscodificacao, match="não é cp1252"):
        transcodificar(origem, destino)

    # e não pode deixar resíduo
    assert not destino.exists()
    assert not list(tmp_path.glob("*.part"))


def test_escrita_e_atomica(tmp_path: Path):
    origem = tmp_path / "e.csv"
    origem.write_bytes("teste\n".encode("cp1252"))
    destino = tmp_path / "s.csv"

    transcodificar(origem, destino)

    assert destino.is_file()
    assert not list(tmp_path.glob("*.part"))


def test_destino_em_diretorio_inexistente_e_criado(tmp_path: Path):
    origem = tmp_path / "e.csv"
    origem.write_bytes("teste\n".encode("cp1252"))

    r = transcodificar(origem, tmp_path / "a" / "b" / "s.csv")

    assert r.destino.is_file()


def test_sobrescreve_destino_anterior(tmp_path: Path):
    """Reprocessar um snapshot não pode concatenar em cima do resultado velho."""
    origem = tmp_path / "e.csv"
    destino = tmp_path / "s.csv"
    destino.write_text("lixo de uma execução anterior, bem mais longo\n", "utf-8")
    origem.write_bytes("novo\n".encode("cp1252"))

    transcodificar(origem, destino)

    assert destino.read_text("utf-8") == "novo\n"
