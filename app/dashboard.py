"""Dashboard narrativo do CNO."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from importlib import import_module  # noqa: E402

from analise import dados  # noqa: E402
from app import componentes as ui  # noqa: E402

SECOES = tuple(import_module(f"app.secoes.{nome}") for nome in ui.ORDEM)


def _sem_dados(erro: Exception) -> None:
    """Tela exibida quando a camada curada não existe."""
    st.title("A camada curada ainda não existe")
    st.markdown(
        "Este dashboard lê o que o pipeline materializa em `data/curated`. Para gerar tudo do zero:"
    )
    st.code("make pipeline    # extract -> transform -> validate -> curate", language="bash")
    st.markdown(
        "Ou, se a stack em container estiver de pé, espere a DAG `cno_pipeline` terminar "
        "a primeira execução. O dashboard passa a responder sozinho, sem reiniciar."
    )
    st.caption(str(erro).replace("\n", " "))


def main() -> None:
    paginas = [
        st.Page(
            secao.render,
            title=secao.TITULO,
            url_path="" if indice == 0 else secao.__name__.rsplit(".", 1)[-1],
            default=indice == 0,
        )
        for indice, secao in enumerate(SECOES)
    ]
    pagina = st.navigation(paginas)

    with st.sidebar:
        st.divider()
        st.caption(
            "A entrega da análise é este app. O caminho até ele está em "
            "`analise/exploracao.ipynb`, versionado com as saídas."
        )

    pagina.run()


ui.configurar_pagina()
try:
    main()
except dados.CamadaAusente as erro:
    _sem_dados(erro)
