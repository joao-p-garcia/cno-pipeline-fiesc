"""Testes da etapa de extração, todos offline contra o servidor fake."""

from __future__ import annotations

import io
import zipfile

import pytest

from cno_pipeline.config import Settings
from cno_pipeline.extract import HttpSource, carregar_manifest, carregar_ultimo
from cno_pipeline.extract.cno import ErroDeExtracao, executar_extracao
from cno_pipeline.extract.manifest import Manifest, sha256_arquivo
from cno_pipeline.extract.source import ErroDeFonte

from .conftest import CSVS


def _zip_com(nomes: list[str], extra: dict[str, str] | None = None) -> bytes:
    """Monta um zip contendo só os arquivos pedidos."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for nome in nomes:
            zf.writestr(nome, CSVS[nome].encode("cp1252"))
        for nome, conteudo in (extra or {}).items():
            zf.writestr(nome, conteudo.encode("cp1252"))
    return buffer.getvalue()


def _gets_completos(estado) -> int:
    return sum(1 for r in estado.requisicoes if r == "GET completo")


# -- inspeção ------------------------------------------------------------


def test_inspecionar_detecta_range_sem_accept_ranges(settings: Settings):
    """O HEAD não anuncia Accept-Ranges; a sonda de 1 byte tem que descobrir."""
    with HttpSource(settings) as fonte:
        info = fonte.inspecionar()

    assert info.aceita_range is True
    assert info.etag == "etag-de-teste-1"
    assert info.data_publicacao.isoformat() == "2026-09-12"


def test_snapshot_id_vem_da_data_de_publicacao(settings: Settings):
    """O id do snapshot é a data em que a fonte publicou, não a de hoje."""
    resultado = executar_extracao(settings)
    assert resultado.manifest.snapshot_id == "2026-09-12"
    assert resultado.snapshot_dir.name == "snapshot_date=2026-09-12"


# -- extração feliz ------------------------------------------------------


def test_extracao_completa(settings: Settings):
    resultado = executar_extracao(settings)
    m = resultado.manifest

    assert resultado.reaproveitado is False
    assert {a.nome for a in m.arquivos} == set(CSVS)

    csv_dir = resultado.snapshot_dir / "csv"
    for arquivo in m.arquivos:
        caminho = csv_dir / arquivo.nome
        assert caminho.is_file()
        assert caminho.stat().st_size == arquivo.bytes
        assert sha256_arquivo(caminho) == arquivo.sha256

    # o pacote original fica preservado na camada raw
    assert (resultado.snapshot_dir / "cno.zip").is_file()
    # e nenhum .part sobra
    assert not list(resultado.snapshot_dir.glob("*.part"))


def test_totais_de_controle_sao_lidos(settings: Settings):
    """Os rótulos têm acento e o arquivo é cp1252: os dois têm que funcionar."""
    m = executar_extracao(settings).manifest
    assert m.totais_controle == {
        "cno": 2,
        "cno_cnaes": 2,
        "cno_areas": 3,
        "cno_vinculos": 1,
    }


def test_acentos_preservados_na_extracao(settings: Settings):
    resultado = executar_extracao(settings)
    conteudo = (resultado.snapshot_dir / "csv" / "cno.csv").read_text("cp1252")
    assert "BRASÍLIA" in conteudo
    assert "SÃO PAULO" in conteudo


def test_tipografia_cp1252_nao_vira_caractere_de_controle(settings: Settings):
    """Regressão de encoding.

    O travessão (byte 0x96) existe em cp1252 e é indefinido em ISO-8859-1. Lido
    como latin-1 ele vira U+0096, um caractere de controle, **sem levantar
    erro** — exatamente a corrupção silenciosa que a base real sofreria em 4.881
    posições se usássemos o encoding errado.
    """
    resultado = executar_extracao(settings)
    bruto = (resultado.snapshot_dir / "csv" / "cno.csv").read_bytes()

    assert b"\x96" in bruto, "o fixture precisa conter o byte da faixa C1"
    assert "–" in bruto.decode("cp1252"), "cp1252 deve produzir travessão"
    assert "" in bruto.decode("latin-1"), (
        "latin-1 produz caractere de controle — é o que estamos evitando"
    )


def test_manifest_persistido_e_recuperavel(settings: Settings):
    m = executar_extracao(settings).manifest

    recuperado = carregar_manifest(settings.manifests_dir, m.snapshot_id)
    assert recuperado == m

    ultimo = carregar_ultimo(settings.manifests_dir)
    assert ultimo is not None
    assert ultimo.snapshot_id == m.snapshot_id


# -- idempotência --------------------------------------------------------


def test_segunda_execucao_nao_rebaixa(settings: Settings, estado_servidor):
    primeira = executar_extracao(settings)
    assert primeira.reaproveitado is False
    assert _gets_completos(estado_servidor) == 1

    segunda = executar_extracao(settings)
    assert segunda.reaproveitado is True
    assert segunda.manifest == primeira.manifest
    # nenhum download novo: o ETag bateu com o do manifesto
    assert _gets_completos(estado_servidor) == 1


def test_force_rebaixa_mesmo_atualizado(settings: Settings, estado_servidor):
    executar_extracao(settings)
    resultado = executar_extracao(settings, forcar=True)

    assert resultado.reaproveitado is False
    assert _gets_completos(estado_servidor) == 2


def test_etag_novo_dispara_rebaixa(settings: Settings, estado_servidor):
    executar_extracao(settings)
    estado_servidor.etag = "etag-de-teste-2"

    resultado = executar_extracao(settings)
    assert resultado.reaproveitado is False
    assert resultado.manifest.etag == "etag-de-teste-2"


def test_arquivo_apagado_dispara_reextracao(settings: Settings, estado_servidor):
    """Se alguém mexer na camada raw, a integridade tem que ser refeita."""
    primeira = executar_extracao(settings)
    (primeira.snapshot_dir / "csv" / "cno_cnaes.csv").unlink()

    segunda = executar_extracao(settings)
    assert segunda.reaproveitado is False
    assert (segunda.snapshot_dir / "csv" / "cno_cnaes.csv").is_file()


# -- robustez de rede ----------------------------------------------------


def test_retoma_download_apos_queda(settings: Settings, estado_servidor):
    """Servidor derruba a conexão no meio; o cliente retoma pelo Range."""
    total = len(estado_servidor.corpo)
    estado_servidor.cortar_apos = total // 3

    resultado = executar_extracao(settings)

    zip_baixado = resultado.snapshot_dir / "cno.zip"
    assert zip_baixado.stat().st_size == total
    assert zip_baixado.read_bytes() == estado_servidor.corpo

    # confirma que houve retomada, e não um download inteiro do zero
    ranges = [r for r in estado_servidor.requisicoes if r.startswith("GET bytes=")]
    assert any(r != "GET bytes=0-0" for r in ranges), (
        f"esperava uma requisição de retomada, vi: {estado_servidor.requisicoes}"
    )


def test_recomeça_quando_servidor_ignora_range(settings: Settings, estado_servidor):
    """Se o servidor ignorar o Range e mandar tudo, não pode costurar bytes."""
    total = len(estado_servidor.corpo)
    estado_servidor.cortar_apos = total // 3
    estado_servidor.ignorar_range = True

    resultado = executar_extracao(settings)

    zip_baixado = resultado.snapshot_dir / "cno.zip"
    assert zip_baixado.read_bytes() == estado_servidor.corpo


def test_desiste_apos_maximo_de_tentativas(settings: Settings, estado_servidor):
    """Corpo sempre truncado: tem que falhar explicitamente, não travar."""
    estado_servidor.cortar_apos = 10
    estado_servidor.cortar_sempre = True

    with pytest.raises(ErroDeFonte, match="tentativas"):
        executar_extracao(settings)

    # e não pode deixar um snapshot pela metade registrado
    assert carregar_ultimo(settings.manifests_dir) is None


# -- validação do pacote -------------------------------------------------


def test_zip_slip_e_rejeitado(settings: Settings, estado_servidor):
    """Membro com caminho para fora do destino não pode ser extraído."""
    estado_servidor.corpo = _zip_com(list(CSVS), extra={"../fora.csv": "nao deveria sair daqui\n"})

    with pytest.raises(ErroDeExtracao, match="suspeito"):
        executar_extracao(settings)


def test_pacote_sem_arquivo_esperado_falha(settings: Settings, estado_servidor):
    """Contrato de extração: faltou tabela, a etapa falha em vez de seguir."""
    estado_servidor.corpo = _zip_com(["cno.csv", "cno_totais.csv"])

    with pytest.raises(ErroDeExtracao, match="não contém os arquivos esperados"):
        executar_extracao(settings)


def test_conteudo_invalido_nao_vira_snapshot(settings: Settings, estado_servidor):
    estado_servidor.corpo = b"isto definitivamente nao e um zip"

    with pytest.raises(ErroDeExtracao, match="não é um zip válido"):
        executar_extracao(settings)

    assert carregar_ultimo(settings.manifests_dir) is None


# -- manifesto -----------------------------------------------------------


def test_manifest_roundtrip_ignora_campos_desconhecidos():
    """Manifesto gravado por uma versão futura não pode quebrar a leitura."""
    original = Manifest(
        snapshot_id="2026-09-12",
        source_url="http://exemplo/cno.zip",
        etag="abc",
        last_modified=None,
        content_length=10,
        sha256_zip="deadbeef",
        baixado_em="2026-09-16T00:00:00+00:00",
    )
    dados = original.to_dict()
    dados["campo_do_futuro"] = "ignore-me"

    assert Manifest.from_dict(dados) == original
