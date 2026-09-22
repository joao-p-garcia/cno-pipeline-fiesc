"""Seção 1 — o dado como ele chega."""

from __future__ import annotations

import streamlit as st

from analise import estilo

from .. import componentes as ui
from .. import dados_app

TITULO = "A fonte e o encoding"

# Quantos caracteres mostrar depois da última divergência entre os encodings. O
# corte do bloco sai daí: precisa alcançar os bytes que fazem o argumento, com
# um pouco de contexto à direita para o campo não terminar cortado.
FOLGA_JANELA = 30


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "Os dados brutos da Receita são um `.zip` de 315 MB com cinco CSVs dentro, "
        "sem documentação de tipos, nem chave declarada, nem contrato. São 12,5 milhões "
        "de linhas. Antes de modelar qualquer coisa, fui olhar os bytes, porque um "
        "simples pandas read_csv não funcionou no formato padrão.",
       )

    ui.numeros(
        [
            ("arquivo publicado", "315 MB", "cno.zip, republicado sem aviso e sem histórico"),
            ("linhas na origem", "12,5 M", "somando as quatro tabelas"),
            (
                "obras",
                estilo.numero(dados_app.consultar("total_obras")),
                None,
            ),
            ("tempo até a camada curada", "~6,5 min", "a frio, em container, do zero ao dashboard"),
        ]
    )

    st.markdown("### A amostra crua, byte a byte")
    st.markdown(
        "Deixei estas linhas versionadas em `analise/amostra_bruta.csv` **com os "
        "bytes originais**, sem conversão nenhuma. Troque o encoding abaixo e veja o "
        "que acontece."
    )

    encoding = st.radio(
        "Como ler os bytes",
        ["cp1252 (o certo)", "latin-1 (o palpite comum)"],
        horizontal=True,
        label_visibility="collapsed",
    )
    escolhido = "cp1252" if encoding.startswith("cp1252") else "latin-1"

    linhas = dados_app.consultar_amostra()
    texto = dados_app.decodificar_amostra(escolhido)

    # Onde os dois encodings divergem, em (linha, coluna). Calculado, não
    # chutado: este trecho já cortou o bloco em 180 caracteres e fatiou a
    # comparação em [100:160], enquanto as divergências desta amostra estão nas
    # colunas 204, 206 e 207. O seletor não mudava nada na tela e as duas
    # colunas mostravam a mesma string — a seção fazia o argumento certo e não
    # demonstrava coisa nenhuma. A janela agora sai do dado.
    certo = dados_app.decodificar_amostra("cp1252")
    latino = dados_app.decodificar_amostra("latin-1")
    divergencias = [
        (i, j)
        for i, (c, e) in enumerate(zip(certo, latino, strict=True))
        for j, (x, y) in enumerate(zip(c, e, strict=True))
        if x != y
    ]

    if divergencias:
        ate_linha = max(i for i, _ in divergencias) + 1
        ate_coluna = max(j for _, j in divergencias) + FOLGA_JANELA
    else:
        ate_linha, ate_coluna = 5, 180
    st.code(
        "\n".join(t[:ate_coluna] for t in texto[:ate_linha]),
        language="text",
        wrap_lines=True,
    )

    if divergencias:
        i, j = divergencias[0]
        bytes_c1 = ", ".join(f"0x{b:02x}" for b in linhas[i] if 0x80 <= b <= 0x9F)
        inicio, fim = max(0, j - 42), j + 20
        esquerda, direita = st.columns(2)
        esquerda.caption(f"cp1252 — bytes {bytes_c1}")
        esquerda.success(certo[i][inicio:fim])
        direita.caption("latin-1 — mesma sequência, sem erro nenhum")
        direita.error(repr(latino[i][inicio:fim]))

    ui.decisao(
        achado=(
            "O `cno.csv` tem 4.881 bytes na faixa 0x80 a 0x9F. Há uma incompatibilidade "
            "desse formato no latin-1 que se propagaria no resto da pipeline."
        ),
        risco=(
            "O latin-1 decodifica qualquer byte sem levantar exceção, a pipeline rodaria "
            "verde e o texto corrompido apareceria num relatório três camadas depois."
        ),
        decisao=(
            'Fixei `ENCODING_ORIGEM = "cp1252"` como constante em `config.py`. O '
            "tratamento converte para UTF-8 antes de entregar ao DuckDB, que não lê "
            "nativamente cp1252. E coloquei um byte dessa faixa no dado sintético dos "
            "testes, então trocar o encoding quebra os testes em vez de quebrar o "
            "relatório."
        ),
    )

    ui.rodape(*ui.vizinhos(__name__))
