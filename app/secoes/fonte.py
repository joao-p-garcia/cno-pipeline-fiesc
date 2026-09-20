"""Seção 1 — o dado como ele chega."""

from __future__ import annotations

import streamlit as st

from analise import estilo

from .. import componentes as ui
from .. import dados_app

TITULO = "O dado como ele chega"

# Quantos caracteres mostrar depois da última divergência entre os encodings. O
# corte do bloco sai daí: precisa alcançar os bytes que fazem o argumento, com
# um pouco de contexto à direita para o campo não terminar cortado.
FOLGA_JANELA = 30


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "Um `.zip` de 315 MB num share da Receita Federal, com cinco CSVs dentro. "
        "Sem dicionário de tipos, sem chave declarada, sem contrato — e 12,5 milhões "
        "de linhas que precisam virar resposta. **A primeira coisa a fazer não é "
        "modelar: é olhar os bytes.**",
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
        "Estas linhas estão versionadas em `analise/amostra_bruta.csv` **com os bytes "
        "originais**, não com o texto já convertido. Troque o encoding abaixo e veja o "
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
        vi=(
            "O `cno.csv` tem **4.881 bytes na faixa `0x80`–`0x9F`**. Em cp1252 essa faixa "
            "é tipografia — travessão, aspas curvas. Em ISO-8859-1 ela é caractere de "
            "controle indefinido."
        ),
        quebraria=(
            "Nada, imediatamente — e esse é o problema. `latin-1` decodifica **qualquer** "
            "byte sem levantar exceção. O pipeline rodaria verde e entregaria "
            "`AGEHAB \\x96 OBRA` num relatório, três camadas adiante."
        ),
        mudou=(
            '`ENCODING_ORIGEM = "cp1252"` virou constante documentada em `config.py`, o '
            "tratamento transcodifica para UTF-8 antes de entregar ao DuckDB (que não lê "
            "cp1252), e o dado sintético dos testes contém o byte `0x96` de propósito: "
            "trocar o encoding quebra a suíte em vez de quebrar o relatório."
        ),
    )

    ui.rodape(*ui.vizinhos(__name__))
