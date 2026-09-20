"""Peças de interface que se repetem em todas as seções.

A estrutura de cada seção é sempre a mesma, e é ela que faz a narrativa
funcionar:

1. um **título** e um parágrafo curto com o que foi visto;
2. o **gráfico fixo** que faz o argumento — é este que vai para a apresentação,
   e ele não muda com filtro nenhum;
3. o **bloco da decisão**: o que quebraria se fosse ignorado, e o que mudou no
   sistema por causa disso;
4. um expander **"explorar"**, com os controles.

O passo 4 vem depois de propósito. Storytelling e BI puxam em direções opostas:
uma história precisa de uma ordem, um painel precisa de liberdade. Separar os
dois em camadas é o que permite os dois no mesmo app — quem quiser a história lê
de cima para baixo e nunca abre um expander; quem quiser explorar tem tudo ali.
"""

from __future__ import annotations

import streamlit as st

from analise import estilo

from . import dados_app

# A ordem da narrativa, e a **única** fonte dela. A numeração do topo de cada
# seção, os vizinhos do rodapé e as páginas do `st.navigation` saem daqui.
#
# Antes cada seção escrevia `"Seção 3 de 6"` e o nome do vizinho à mão. Com seis
# seções já eram doze lugares para desencontrar; a primeira mudança de ordem
# deixaria metade do app mentindo sobre onde o leitor está — e mentira de
# navegação é do tipo que ninguém reporta, só desorienta.
ORDEM = ("fonte", "tabelas", "nulos", "area", "geo", "tempo", "camadas", "conclusoes")


def _titulo_de(modulo: str) -> str:
    """O `TITULO` de uma seção, importada sob demanda.

    O import é adiado de propósito: `componentes` é importado por toda seção no
    topo, e importar as seções aqui em cima fecharia o ciclo. Dentro da função
    ele só roda quando a página está sendo desenhada, com tudo já carregado.
    """
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
        page_title="CNO — da fonte à conclusão",
        page_icon="🏗️",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def cabecalho() -> None:
    """Barra de proveniência, presente em todas as páginas.

    A data do snapshot fica visível o tempo todo porque é ela que separa um
    dashboard de um extrato: o número que está na tela veio de uma publicação
    identificada da Receita, e a esteira sabe qual.
    """
    curada = dados_app.conexao()
    meta = dados_app.metadados_referencia()

    colunas = st.columns([2, 1, 1, 2])
    colunas[0].caption("snapshot da Receita Federal")
    colunas[0].markdown(f"**{curada.snapshot}**")

    # As duas medidas saem de uma varredura só, e são as mesmas que a seção 1
    # exibe: o cabeçalho não pode discordar do corpo da página.
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
        colunas[3].markdown("**ausente** — o app funciona sem ela, sem o denominador")
    st.divider()


def titulo(numero: str, texto: str, resumo: str) -> None:
    st.markdown(f"##### {numero}")
    st.markdown(f"## {texto}")
    st.markdown(resumo)


def decisao(vi: str, quebraria: str, mudou: str) -> None:
    """O bloco que transforma um gráfico numa decisão de engenharia."""
    with st.container(border=True):
        st.markdown(f"**O que eu vi.** {vi}")
        st.markdown(f"**O que quebraria se eu ignorasse.** {quebraria}")
        st.markdown(f"**O que mudou no sistema.** {mudou}")


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
