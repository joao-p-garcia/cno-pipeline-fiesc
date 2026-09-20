"""Testes de contrato da camada de análise — as falhas que não levantam exceção.

Os outros testes conferem números. Estes conferem **acoplamentos**, e existem
porque cada um deles corresponde a um defeito que de fato aconteceu neste
projeto e que a suíte de então não pegou:

* `dados.py` mudou três assinaturas (`Curada.valor`, `destinacoes(limite=)`,
  `histograma_area(teto=)`) e uma coluna de retorno (`ordem`). O `ruff` não vê,
  o import não vê, e o caderno só reclama quando é executado inteiro — o que
  `make test` não faz.
* A regra "o app não tem SQL" estava escrita em três docstrings e em nenhum
  teste. Erodiu em três telas, incluindo uma cópia caractere por caractere da
  consulta mais citada da narrativa.
* Constantes do pipeline foram redigitadas na análise (o corte de 2019, o limite
  de 150 km, os rótulos das faixas). Redigitar não dá erro: dá dois lugares que
  podem discordar e continuar coerentes consigo mesmos.
* Gráfico que falha em silêncio é a regra nesta base (ver `DECISOES.md`, erros
  10 e 11). `AppTest` diz que a página subiu, não que o gráfico apareceu.

Nenhum destes precisa da camada curada real: três são estáticos e o de gráfico
usa a camada sintética.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from analise import dados, estilo, malha
from cno_pipeline.config import Settings
from cno_pipeline.curate import dominios, executar_curadoria
from cno_pipeline.transform import executar_staging

from .dados_sinteticos import SNAPSHOT

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "app"
NOTEBOOK = RAIZ / "analise" / "exploracao.ipynb"


def _celulas_de_codigo() -> list[tuple[str, str]]:
    """(rótulo, fonte) de cada célula de código do caderno."""
    caderno = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return [
        (f"caderno[{i}]", "".join(c["source"]))
        for i, c in enumerate(caderno["cells"])
        if c["cell_type"] == "code"
    ]


def _fontes_do_app() -> list[tuple[str, str]]:
    return [(str(p.relative_to(RAIZ)), p.read_text(encoding="utf-8")) for p in APP.rglob("*.py")]


# ---------------------------------------------------------------------------
# 1. As assinaturas que o caderno e o app assumem
# ---------------------------------------------------------------------------

# Como cada arquivo se refere ao módulo de consultas. O caderno usa `dados`, o
# app usa `consultas` para não colidir com `dados_app`.
APELIDOS = {"dados": dados, "consultas": dados, "malha": malha, "estilo": estilo}


def _chamadas(fonte: str):
    """(módulo, função, nº de posicionais, nomes dos nomeados) de cada chamada."""
    for no in ast.walk(ast.parse(fonte)):
        if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)):
            continue
        dono = no.func.value
        if isinstance(dono, ast.Name) and dono.id in APELIDOS:
            nomeados = [k.arg for k in no.keywords if k.arg]
            yield dono.id, no.func.attr, len(no.args), nomeados


@pytest.mark.parametrize("rotulo,fonte", _celulas_de_codigo() + _fontes_do_app())
def test_chamadas_batem_com_a_assinatura(rotulo, fonte):
    """Toda chamada a `dados.*` existe e aceita os argumentos passados.

    É o teste que faltava quando `histograma_area` perdeu o parâmetro `teto`: o
    caderno continuou pedindo, e só a execução completa acusou. Aqui a
    verificação é estática e custa milissegundos.
    """
    for apelido, nome, posicionais, nomeados in _chamadas(fonte):
        modulo = APELIDOS[apelido]
        alvo = getattr(modulo, nome, None)
        assert alvo is not None, f"{rotulo}: {apelido}.{nome} não existe em {modulo.__name__}"
        if not callable(alvo):
            continue
        try:
            inspect.signature(alvo).bind_partial(*[None] * posicionais, **dict.fromkeys(nomeados))
        except TypeError as erro:
            pytest.fail(f"{rotulo}: {apelido}.{nome}(...) — {erro}")


# ---------------------------------------------------------------------------
# 2. A fronteira: quem publica número não inventa a pergunta
# ---------------------------------------------------------------------------

# `Curada.df` e `Curada.valor` são a camada de SQL. Quem pode chamá-las é
# `analise/dados.py` — e os testes, que usam `valor` como oráculo.
PALAVRAS_DE_SQL = ("SELECT ", "FROM ", " WHERE ", "GROUP BY")


@pytest.mark.parametrize("rotulo,fonte", _celulas_de_codigo() + _fontes_do_app())
def test_nao_ha_sql_fora_da_camada_de_consultas(rotulo, fonte):
    """Nem o app nem o caderno escrevem SQL.

    A regra não é purismo. Cada `SELECT` solto é uma pergunta que passa a existir
    em dois lugares, e duas cópias divergem sem que nenhuma quebre: foi assim que
    o funil de geocodificação — o número mais citado da análise — passou a ser
    calculado por dois SQLs iguais, um no app e um no caderno.
    """
    encontrados = [p for p in PALAVRAS_DE_SQL if p in fonte]
    assert not encontrados, (
        f"{rotulo} contém SQL ({', '.join(encontrados)}). "
        "Toda consulta mora em analise/dados.py, com um nome."
    )


# ---------------------------------------------------------------------------
# 3. As constantes são as do pipeline, não cópias
# ---------------------------------------------------------------------------


def test_constantes_sao_o_objeto_do_pipeline():
    """A análise reexporta as constantes da curadoria — não as redigita.

    `is`, e não `==`: dois inteiros iguais passariam num `==` e continuariam
    sendo duas fontes de verdade. O que este teste protege é a identidade.
    """
    assert dados.ANO_SERIE_COMPARAVEL is dominios.PRIMEIRO_ANO_COMPARAVEL
    assert dados.LIMITE_PLAUSIVEL_KM is dominios.LIMITE_PLAUSIBILIDADE_KM
    assert tuple(r for _, _, r in dominios.FAIXAS_AREA_M2) == dados.ROTULOS_FAIXA_AREA


def test_rotulos_de_faixa_saem_da_tupla_do_pipeline():
    """Renomear uma faixa em `dominios.py` reflete na análise sem edição aqui."""
    assert len(dados.ROTULOS_FAIXA_AREA) == len(dominios.FAIXAS_AREA_M2)
    assert all(isinstance(r, str) and r for r in dados.ROTULOS_FAIXA_AREA)


# ---------------------------------------------------------------------------
# 4. O gráfico apareceu — não "a página subiu"
# ---------------------------------------------------------------------------


@pytest.fixture
def curada(camada_raw: Settings) -> dados.Curada:
    executar_staging(camada_raw, snapshot_id=SNAPSHOT)
    executar_curadoria(camada_raw, snapshot_id=SNAPSHOT)
    estilo.registrar_altair()
    return dados.abrir(camada_raw.curated_dir)


def _renderizar(chart) -> bytes:
    """PNG do gráfico, pelo mesmo compilador Vega-Lite que o navegador usa.

    Import direto, e não `importorskip`: `vl-convert-python` está declarado no
    extra `dev`, então ausência dele é ambiente quebrado, não ambiente mínimo.
    A versão com `importorskip` fazia estes dois testes — os únicos que provam
    que o gráfico saiu — **pularem em silêncio** onde mais importa, que é um CI
    recém-provisionado.
    """
    import vl_convert as vlc

    return vlc.vegalite_to_png(chart.to_json(), scale=1)


# Um gráfico vazio ainda produz PNG — só que pequeno, com título e mais nada.
# Medido nesta base: os gráficos reais passam de 15 KB; o vazio do `alt.Step`
# ficava em ~4 KB. O piso vai baixo de propósito: o teste existe para pegar
# gráfico que sumiu, não para vigiar bytes.
PISO_PNG_BYTES = 8_000


def test_grafico_em_escala_log_desenha(curada):
    """Barra em escala log não desenha, e não dá erro — vira gráfico em branco.

    Este é o gráfico que a `DECISOES.md` #11 documenta: virou `mark_rule` mais
    `mark_point` por causa disso. Nada além de renderizar e medir pega a
    regressão.
    """
    from app import graficos

    png = _renderizar(
        graficos.decomposicao_log(
            dados.decomposicao_area(curada), titulo="decomposição", subtitulo="teste"
        )
    )
    assert len(png) > PISO_PNG_BYTES, "gráfico em escala log saiu vazio"


def test_grafico_com_camadas_tem_altura(curada):
    """`alt.Step` em spec com camadas devolve gráfico vazio (DECISOES.md #11).

    A altura é calculada em pixel por causa disso. Se alguém voltar a `step`, o
    spec continua válido e o PNG encolhe.
    """
    from app import graficos

    png = _renderizar(
        graficos.barras(
            dados.faixas_area(curada), categoria="faixa_area", valor="obras", titulo="faixas"
        )
    )
    assert len(png) > PISO_PNG_BYTES, "gráfico com camadas saiu vazio"


# ---------------------------------------------------------------------------
# 5. O número chega ao leitor em português
# ---------------------------------------------------------------------------


def test_eixo_numerico_troca_os_separadores():
    """O tema formata eixo numérico em pt-BR, e a troca é global.

    Não é cosmético: a versão anterior carimbava `formatLocale` em
    `usermeta.embedOptions`, que o Streamlit **descarta**. Todo eixo do
    dashboard vinha com vírgula de milhar e nada acusava.
    """
    eixo = estilo.tema_altair()["config"]["axis"]
    assert eixo.get("labelExpr") == estilo.ROTULO_NUMERO_BR
    assert "/g" in estilo.ROTULO_NUMERO_BR, (
        "sem o /g o replace do Vega troca só a primeira ocorrência, e "
        "1.000.000 sai como '1.000,000'"
    )


def test_eixo_de_ano_nao_leva_separador(curada):
    """Ano é a exceção do default: `format(2019, ',')` daria "2.019".

    O eixo de ano precisa declarar a exceção. Se alguém remover o `labelExpr`
    explícito, ele volta a herdar o do tema e a série passa a falar de "2.019".
    """
    from app import graficos

    grafico = graficos.serie_temporal(
        dados.obras_por_ano(curada, desde=1995),
        x="ano",
        y="obras",
        titulo="série",
        rotulo_valor="obras",
    )
    spec = grafico.to_dict()
    eixos_x = [
        camada["encoding"]["x"].get("axis", {})
        for camada in spec["layer"]
        if "x" in camada.get("encoding", {})
    ]
    assert eixos_x, "a série não declarou eixo x"
    assert all(
        eixo.get("labelExpr") == estilo.ROTULO_SEM_SEPARADOR for eixo in eixos_x if "values" in eixo
    ), "o eixo de ano herdou o separador de milhar do tema"


def test_tooltip_nao_usa_o_format_do_vega():
    """O número do tooltip sai formatado do Python, não do d3.

    Não há gancho de expressão em tooltip: um `format=` ali volta a escrever em
    inglês, e o hover é justamente onde o leitor vai conferir o número.
    """
    fonte = (APP / "graficos.py").read_text(encoding="utf-8")
    assert "format=" not in fonte, (
        "tooltip com `format=` formata em inglês; use `_tooltips`, que "
        "pré-formata a coluna com estilo.numero"
    )
