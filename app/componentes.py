"""Peças de interface que se repetem em todas as seções."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from analise import estilo

from . import dados_app

ORDEM = (
    "fonte",
    "tabelas",
    "arquitetura",
    "dags",
    "nulos",
    "area",
    "geo",
    "tempo",
    "camadas",
    "conclusoes",
)


def diagrama(svg: str, altura: int) -> None:
    """Desenha um SVG num iframe, com a superfície e a tipografia do app."""
    pagina = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  @font-face {{
    font-family: 'Montserrat';
    src: url('/app/static/fontes/{estilo.FONTE[0]}.woff2') format('woff2');
    font-weight: 400 700;
    font-display: swap;
  }}
  html, body {{ margin: 0; padding: 0; background: {estilo.SUPERFICIE}; }}
  body {{ font-family: {estilo.FONTE_CSS}; }}
</style>
</head><body>{svg}</body></html>"""
    components.html(pagina, height=altura)


def _titulo_de(modulo: str) -> str:
    """O `TITULO` de uma seção, importada sob demanda."""
    from importlib import import_module

    return import_module(f".secoes.{modulo}", package=__package__).TITULO


def _nome_curto(modulo: str) -> str:
    """`app.secoes.geo` -> `geo`. É o que as seções passam como `__name__`."""
    return modulo.rsplit(".", 1)[-1]


def posicao(modulo: str) -> str:
    """ "Seção 4 de 8", calculado a partir de `ORDEM`."""
    return f"Seção {ORDEM.index(_nome_curto(modulo)) + 1} de {len(ORDEM)}"


def vizinhos(modulo: str) -> tuple[str | None, str | None]:
    """Títulos da seção anterior e da próxima, ou `None` nas pontas."""
    i = ORDEM.index(_nome_curto(modulo))
    anterior = _titulo_de(ORDEM[i - 1]) if i > 0 else None
    proxima = _titulo_de(ORDEM[i + 1]) if i < len(ORDEM) - 1 else None
    return anterior, proxima


def configurar_pagina() -> None:
    st.set_page_config(
        page_title="CNO, da fonte à conclusão",
        page_icon="🏗️",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def cabecalho() -> None:
    """Barra de proveniência, presente em todas as páginas."""
    curada = dados_app.conexao()
    meta = dados_app.metadados_referencia()

    colunas = st.columns([2, 1, 1, 2])
    colunas[0].caption("snapshot da Receita Federal")
    colunas[0].markdown(f"**{curada.snapshot}**")

    totais = dados_app.consultar("totais_do_cabecalho")
    colunas[1].caption("obras")
    colunas[1].markdown(f"**{estilo.numero(totais['obras'])}**")

    colunas[2].caption("municípios")
    colunas[2].markdown(f"**{estilo.numero(totais['municipios'])}**")

    colunas[3].caption("referência do IBGE")
    if meta:
        colunas[3].markdown(
            f"**população {meta['safra_populacao']}** · válida até {meta['valido_ate']}"
        )
    else:
        colunas[3].markdown("**ausente**. O app funciona sem ela, só perde o denominador")
    st.divider()


def titulo(numero: str, texto: str, resumo: str) -> None:
    st.markdown(f"##### {numero}")
    st.markdown(f"## {texto}")
    st.markdown(resumo)


def decisao(achado: str, risco: str, decisao: str) -> None:
    """O bloco que transforma um gráfico numa decisão de engenharia."""
    with st.container(border=True):
        st.markdown(f"**Achado.** {achado}")
        st.markdown(f"**Risco.** {risco}")
        st.markdown(f"**Decisão.** {decisao}")


def numeros(itens: list[tuple[str, str, str | None]]) -> None:
    """Fileira de números soltos. Um número que é a história inteira não vira gráfico."""
    for coluna, (rotulo, valor, ajuda) in zip(st.columns(len(itens)), itens, strict=True):
        coluna.metric(rotulo, valor, help=ajuda)


def explorar(titulo: str = "Explorar por conta própria"):
    """Expander padrão dos controles. Fechado por padrão: a história vem primeiro."""
    return st.expander(f"🔎 {titulo}", expanded=False)


def seletor_uf(chave: str, *, rotulo: str = "UF") -> str | None:
    """Seletor de UF com 'Brasil' como primeira opção, devolvendo `None` para o total."""
    ufs = dados_app.consultar("ufs_disponiveis")
    escolha = st.selectbox(rotulo, ["Brasil (todas)", *ufs], key=chave)
    return None if escolha.startswith("Brasil") else escolha


def rodape(anterior: str | None = None, proxima: str | None = None) -> None:
    st.divider()
    esquerda, direita = st.columns(2)
    if anterior:
        esquerda.caption(f"← anterior: {anterior}")
    if proxima:
        direita.caption(f"próxima: {proxima} →")
