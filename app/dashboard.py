"""Dashboard narrativo do CNO — ponto de entrada.

    streamlit run app/dashboard.py

**Por que uma narrativa e não um painel de filtros.** Um painel entrega liberdade
e nenhuma conclusão; quem abre precisa já saber o que perguntar. Aqui a espinha é
uma história em seis seções, na ordem em que as decisões de engenharia foram
tomadas, e cada seção tem um gráfico fixo que faz um argumento. Os controles
existem, mas ficam **abaixo** do argumento, dentro de um expander: quem quiser a
história lê de cima para baixo; quem quiser explorar, explora.

**O que o app não faz.** Não calcula regra de negócio. Toda consulta vem de
`analise/dados.py`, o mesmo módulo que o notebook usa, e todo número agregado vem
dos marts que o `cno curate` materializou. Se o dashboard e o caderno divergissem
num número, seria falha de arquitetura, não diferença de opinião.
"""

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

# A ordem vive em `componentes.ORDEM`, junto das funções que numeram as seções e
# nomeiam os vizinhos do rodapé. Aqui só se resolve nome de módulo para módulo:
# uma lista só manda na narrativa inteira.
SECOES = tuple(import_module(f"app.secoes.{nome}") for nome in ui.ORDEM)


def _sem_dados(erro: Exception) -> None:
    """Tela honesta quando a camada curada não existe.

    Sem isto o Streamlit mostraria um traceback de DuckDB, que não diz a quem
    acabou de clonar o repositório o que fazer a seguir.
    """
    st.title("A camada curada ainda não existe")
    st.markdown(
        "Este dashboard lê o que o pipeline materializa em `data/curated`. Para gerar tudo do zero:"
    )
    st.code("make pipeline    # extract -> transform -> validate -> curate", language="bash")
    st.markdown(
        "Ou, se a stack em container estiver de pé, espere a DAG `cno_pipeline` terminar "
        "a primeira execução — o dashboard passa a responder sozinho, sem reiniciar."
    )
    # Mensagem, não traceback. Camada ausente é estado esperado de uma instalação
    # nova, e responder a isso com uma pilha vermelha treina quem opera a ignorar
    # pilha vermelha.
    st.caption(str(erro).replace("\n", " "))


def main() -> None:
    # Todas as seções expõem uma função chamada `render`, e o Streamlit inferiria
    # a URL do nome da função — seis páginas com o mesmo endereço. O `url_path`
    # sai do nome do módulo, que já é único e legível: /geo, /tempo, /area.
    # A primeira página fica com a raiz, como o Streamlit exige.
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
