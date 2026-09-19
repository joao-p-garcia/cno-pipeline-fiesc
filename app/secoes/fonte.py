"""Seção 1 — o dado como ele chega."""

from __future__ import annotations

import streamlit as st

from analise import estilo

from .. import componentes as ui
from .. import dados_app

TITULO = "O dado como ele chega"


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        "Seção 1 de 6",
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
                estilo.numero(dados_app.valor("SELECT sum(n_obras) FROM municipio_ano")),
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
    st.code("\n".join(t[:180] for t in texto[:5]), language="text", wrap_lines=True)

    diferentes = [
        (bruta, certa, errada)
        for bruta, certa, errada in zip(
            linhas,
            dados_app.decodificar_amostra("cp1252"),
            dados_app.decodificar_amostra("latin-1"),
            strict=True,
        )
        if certa != errada
    ]
    if diferentes:
        bruta, certa, errada = diferentes[0]
        bytes_c1 = ", ".join(f"0x{b:02x}" for b in bruta if 0x80 <= b <= 0x9F)
        esquerda, direita = st.columns(2)
        esquerda.caption(f"cp1252 — bytes {bytes_c1}")
        esquerda.success(certa[100:160])
        direita.caption("latin-1 — mesma sequência, sem erro nenhum")
        direita.error(repr(errada[100:160]))

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

    st.markdown("### A fonte publica o próprio gabarito")
    st.markdown(
        "Dentro do zip vem um `cno_totais.csv` com quatro números — quantas obras, CNAEs, "
        "áreas e vínculos aquela publicação tem. É pequeno o bastante para passar "
        "despercebido e é a coisa mais valiosa do pacote: **sem oráculo externo, validação "
        "é o pipeline conferindo contra si mesmo**."
    )
    volumetria = dados_app.consultar("volumetria")
    st.dataframe(
        volumetria.assign(quantas=volumetria["quantas"].map(estilo.numero)),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "As três últimas linhas somam o 1:N depois do tratamento: 4.531.627 áreas contra "
        "4.553.076 publicadas, 420.338 vínculos contra 431.211. A diferença são 21.449 e "
        "10.873 **linhas exatamente duplicadas** na origem — e o número bate ao registro."
    )

    with ui.explorar("Ver a volumetria por UF"):
        uf = ui.seletor_uf("uf_fonte")
        st.dataframe(
            dados_app.consultar("situacao", uf=uf),
            hide_index=True,
            width="stretch",
        )

    ui.rodape(proxima="O nulo que não é dado faltante")
