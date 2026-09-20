"""Acesso à camada curada, compartilhado pelo notebook e pelo dashboard.

**Por que este módulo existe.** O notebook e o Streamlit respondem às mesmas
perguntas. Se cada um escrevesse o próprio SQL, bastaria um `WHERE` diferente
para os dois divergirem num número — e ninguém perceberia, porque os dois
continuariam rodando. Aqui cada pergunta tem uma função só, com um nome, e as
duas pontas chamam a mesma. **Não há SQL fora daqui**: nem no app, nem no
caderno.

**O que ele não faz.** Regra de negócio nenhuma. `area_m2`, `geo_plausivel`,
`serie_comparavel`, o corte da série e o limite de plausibilidade já vêm
decididos do pipeline — as constantes são importadas de `curate.dominios`, não
redigitadas. É a mesma fronteira que faz os marts existirem: quem publica número
não pode redefinir o número.

**O que lê o quê.** Uma parte das perguntas é sobre a *distribuição de uma
coluna* (unidade de medida, quantis de área, distância dos pontos) e não cabe num
agregado: essas varrem `obras_analitico`, 3,6 M de linhas. Todo o resto lê os
marts, que têm de 11 mil a 133 mil linhas. **A docstring de cada função diz qual
das duas ela toca**, e nenhuma varre a analítica mais de uma vez por resposta.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import duckdb
import pandas as pd

from cno_pipeline.config import get_settings
from cno_pipeline.curate.dominios import (
    FAIXAS_AREA_M2,
    LIMITE_PLAUSIBILIDADE_KM,
    PRIMEIRO_ANO_COMPARAVEL,
)

from . import referencias

AQUI = Path(__file__).resolve().parent
ARQUIVO_AMOSTRA_BRUTA = AQUI / "amostra_bruta.csv"

# View criada na conexão -> tabela materializada pela etapa de curadoria.
TABELAS = {
    "obras": "obras_analitico",
    "municipio_ano": "mart_municipio_ano",
    "setor_ano": "mart_setor_ano",
    "destinacao_ano": "mart_destinacao_ano",
}

# Reexportados com o nome que a análise usa, para que o app e o caderno não
# precisem importar de dentro do pipeline — mas **são os mesmos objetos**. A
# primeira versão deste módulo redigitava o 2019 "porque a análise pode querer um
# corte diferente"; ninguém quis, e a cópia só criou a chance de os dois lados
# cortarem em anos distintos e cada um continuar coerente consigo mesmo.
ANO_SERIE_COMPARAVEL = PRIMEIRO_ANO_COMPARAVEL
LIMITE_PLAUSIVEL_KM = LIMITE_PLAUSIBILIDADE_KM

# Rótulos das faixas de área na ordem em que o pipeline as define. Derivado da
# mesma tupla que gera a coluna, então renomear uma faixa não embaralha o gráfico.
ROTULOS_FAIXA_AREA = tuple(rotulo for _, _, rotulo in FAIXAS_AREA_M2)


class CamadaAusente(FileNotFoundError):
    """A camada curada não foi materializada."""

    def __init__(self, caminho: Path) -> None:
        super().__init__(
            f"camada curada não encontrada em {caminho}.\n"
            "Rode `make pipeline` (ou `cno curate`, se a staging já existe)."
        )


# Os três recursos que podem faltar numa instalação legítima. Ficam juntos para
# que quem monta uma tela precise de um `except` só — ver `app/dashboard.py`.
RECURSOS_AUSENTES = (CamadaAusente, referencias.ReferenciaAusente)


def tem_referencias() -> bool:
    """A tabela do IBGE é opcional: sem ela o app perde o denominador, não o resto."""
    return referencias.ARQUIVO_MUNICIPIOS.is_file()


# ---------------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Curada:
    """Conexão DuckDB com as tabelas curadas e a referência do IBGE registradas.

    Só de leitura: nada aqui escreve em disco. Instanciar é barato — o DuckDB não
    carrega nada até a primeira consulta, e lê o parquet coluna a coluna.
    """

    con: duckdb.DuckDBPyConnection
    curated_dir: Path

    def df(self, sql: str) -> pd.DataFrame:
        return self.con.execute(sql).df()

    def valor(self, sql: str):
        """Primeira coluna da primeira linha.

        Público porque os testes o usam como oráculo: eles conferem cada mart
        contra uma contagem direta na analítica, e essa contagem precisa ser SQL
        cru — é o que torna o teste independente da função que ele verifica.

        **O que não pode é o app chamar isto.** A regra não é "ninguém escreve
        SQL", é "quem publica número não inventa a pergunta": o dashboard e o
        caderno chamam funções nomeadas daqui, e cada pergunta tem uma só. A
        versão anterior expunha um `dados_app.valor(sql)` "para um número avulso"
        e, em três telas, esse avulso já era a cópia de uma consulta que existia.
        """
        return self.con.execute(sql).fetchone()[0]

    @cached_property
    def snapshot(self) -> str:
        """Data de publicação do snapshot, no formato `AAAA-MM-DD`.

        É o que prova que o dashboard olha para uma esteira viva, e não para um
        extrato tirado à mão em algum momento do passado.

        Vem do nome do diretório de partição, não de um `max(snapshot_date)`. O
        motivo é prático e vale registrar: o DuckDB 1.5.5 responde agregado sobre
        coluna de partição pela estatística do arquivo, e nesse caminho ele
        estoura um erro interno (`Attempted to access index 17 within vector of
        size 17`). Ler o nome do diretório não varre nada e não depende de quem
        conserta o bug.
        """
        return snapshot_mais_recente(self.curated_dir)


def snapshot_mais_recente(curated_dir: Path) -> str:
    """A data do snapshot, lida do nome do diretório de partição.

    Fora da classe porque o dashboard precisa dela **sem** passar pela conexão:
    a conexão vive presa ao processo, e um valor preso a ela envelheceria junto,
    carimbando dado novo com data velha.
    """
    particao = curated_dir / TABELAS["municipio_ano"]
    datas = sorted(p.name.split("=", 1)[1] for p in particao.glob("snapshot_date=*"))
    if not datas:
        raise CamadaAusente(particao)
    return datas[-1]


def abrir(curated_dir: Path | None = None, *, threads: int | None = None) -> Curada:
    """Abre a camada curada e registra as views que o resto do módulo usa.

    O caminho vem do `Settings` do pipeline, não de uma variável própria: quem
    define onde os dados moram é quem os escreve. Assim `CNO_DATA_DIR` vale para
    o pipeline, para o notebook e para o dashboard sem ser declarado três vezes.

    `threads` fica sem default: o do DuckDB é o número de núcleos disponíveis, e
    era isso que um teto fixo de 4 estava jogando fora justamente nas consultas
    caras, que são as que escalam com paralelismo.
    """
    destino = curated_dir or get_settings().curated_dir
    if not destino.is_dir():
        raise CamadaAusente(destino)

    con = duckdb.connect()
    if threads:
        con.execute(f"SET threads = {threads}")
    for view, tabela in TABELAS.items():
        if not (destino / tabela).is_dir():
            raise CamadaAusente(destino / tabela)
        caminho = str(destino / tabela / "**" / "*.parquet").replace("\\", "/")
        con.execute(f"""
            CREATE OR REPLACE VIEW {view} AS
            SELECT * FROM read_parquet('{caminho}', hive_partitioning=true)
        """)
    if tem_referencias():
        referencias.registrar(con)
    return Curada(con=con, curated_dir=destino)


def _onde(uf: str | None = None, *, comparavel: bool = False, extra: str = "") -> str:
    """Monta a cláusula WHERE comum a quase toda consulta.

    `comparavel` corta a série em 2019, o primeiro ano inteiro em que o CNO
    existe (IN RFB 1.845/2018, em vigor desde 21/01/2019). Antes disso a curva
    mede cobertura do cadastro, não construção — ver `PRIMEIRO_ANO_COMPARAVEL`.
    Fica opcional em vez de embutido porque o degrau de 2018-2019 é ele próprio
    um achado: escondê-lo por padrão apagaria a evidência de que a série precisa
    ser cortada.
    """
    clausulas = []
    if uf:
        clausulas.append(f"uf = '{uf}'")
    if comparavel:
        clausulas.append(f"ano_inicio >= {ANO_SERIE_COMPARAVEL}")
    if extra:
        clausulas.append(extra)
    return "WHERE " + " AND ".join(clausulas) if clausulas else ""


def _em_linhas(sql_agregados: str, rotulo: str, valor: str) -> str:
    """Transpõe um `SELECT` de N agregados em N linhas, com `UNPIVOT`.

    Existe para que uma tabela de N medidas custe **uma** varredura em vez de N.
    A alternativa óbvia — `SELECT ... UNION ALL SELECT ...` — lê o parquet uma vez
    por ramo (seis leituras de 3,6 M de linhas, no caso da volumetria) e ainda
    obriga a repetir o filtro em cada ramo, onde esquecer um não dá erro: dá uma
    linha que não conversa com a vizinha.

    A ordem das colunas vira a ordem das linhas, o que dispensa a coluna `ordem`.
    """
    return f"""
        UNPIVOT ({sql_agregados})
        ON COLUMNS(*)
        INTO NAME {rotulo} VALUE {valor}
    """


# ---------------------------------------------------------------------------
# 1. O dado como chega
# ---------------------------------------------------------------------------


def amostra_bruta() -> list[bytes]:
    """Linhas do `cno.csv` original, em bytes, exatamente como a Receita publica.

    Ficam em bytes de propósito: é o único jeito de mostrar que a mesma sequência
    decodifica de duas formas diferentes e só uma delas está certa.
    """
    return ARQUIVO_AMOSTRA_BRUTA.read_bytes().splitlines()


def decodificar(linhas: list[bytes], encoding: str) -> list[str]:
    """Decodifica a amostra crua no encoding pedido, sem levantar erro.

    `latin-1` nunca falha — decodifica qualquer byte. É exatamente por isso que
    ele é a escolha perigosa: o erro não aparece na leitura, aparece no relatório.
    """
    return [linha.decode(encoding, errors="replace") for linha in linhas]


def totais_do_cabecalho(curada: Curada, uf: str | None = None) -> dict:
    """Obras e municípios, do mart. É o que o topo de toda página do app mostra."""
    linha = curada.df(f"""
        SELECT sum(n_obras) AS obras, count(DISTINCT codigo_municipio) AS municipios
        FROM municipio_ano
        {_onde(uf)}
    """).iloc[0]
    return {"obras": int(linha["obras"]), "municipios": int(linha["municipios"])}


def volumetria(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """O tamanho de cada coisa, já na camada curada. Uma varredura da analítica."""
    return curada.df(
        _em_linhas(
            f"""
            SELECT
                count(*)                          AS "obras (uma linha por obra)",
                count(DISTINCT codigo_municipio)  AS "municípios distintos",
                count(DISTINCT uf)                AS "UFs",
                sum(n_areas)                      AS "áreas declaradas (1:N)",
                sum(n_cnaes)                      AS "CNAEs declarados (1:N)",
                sum(n_vinculos)                   AS "vínculos (1:N)"
            FROM obras
            {_onde(uf)}
            """,
            rotulo="o_que",
            valor="quantas",
        )
    )


# ---------------------------------------------------------------------------
# 2. Perfilamento — o que exige olhar a distribuição, e não o agregado
# ---------------------------------------------------------------------------


def perfil_unidades(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Distribuição de `unidade_medida` e o quanto cada unidade soma.

    Varre `obras_analitico`. É a consulta que desmonta o `SUM(area_total)`: a
    coluna de área guarda metro quadrado, quilômetro, metro cúbico e quilowatt no
    mesmo lugar, e a soma crua não pergunta.
    """
    return curada.df(f"""
        SELECT
            unidade_medida                                      AS unidade,
            count(*)                                            AS obras,
            round(sum(area_declarada) / 1e6, 1)                 AS soma_milhoes,
            round(100.0 * count(*) / sum(count(*)) OVER (), 2)  AS pct_obras
        FROM obras
        {_onde(uf)}
        GROUP BY 1
        ORDER BY obras DESC
    """)


def decomposicao_area(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Os quatro valores possíveis para "quantos km² esta base soma".

    As duas linhas do meio isolam **um** problema cada — a unidade misturada e a
    área implausível —, e a última aplica os dois. A distância entre a primeira e
    a última é o tamanho do erro que um `SUM` desavisado publicaria. Uma varredura
    só: os quatro critérios são `FILTER` sobre o mesmo scan.
    """
    return curada.df(
        _em_linhas(
            f"""
            SELECT
                round(sum(area_declarada) / 1e6, 1)
                    AS "SUM(area_total) cru",
                round(sum(area_declarada) FILTER (WHERE NOT area_suspeita) / 1e6, 1)
                    AS "sem as áreas implausíveis",
                round(sum(area_declarada) FILTER (WHERE unidade_medida = 'm2') / 1e6, 1)
                    AS "só o que está em m²",
                round(sum(area_m2) / 1e6, 1)
                    AS "m² e sem implausíveis (area_m2)"
            FROM obras
            {_onde(uf)}
            """,
            rotulo="criterio",
            valor="km2",
        )
    )


def areas_implausiveis(curada: Curada, limite: int = 10) -> pd.DataFrame:
    """As maiores áreas declaradas — as que o pipeline marca em vez de excluir."""
    return curada.df(f"""
        SELECT cno, uf, nome_municipio AS municipio, unidade_medida AS unidade,
               area_declarada, destinacao_obra AS destinacao
        FROM obras
        WHERE area_suspeita
        ORDER BY area_declarada DESC
        LIMIT {limite}
    """)


def quantis_area(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Média, mediana e quantis de `area_m2`. Varre a tabela analítica.

    A média e a mediana no mesmo quadro porque a diferença entre elas é o
    argumento: a média de 834 m² não descreve obra nenhuma.
    """
    return curada.df(f"""
        SELECT
            count(area_m2)                  AS obras_com_area,
            round(avg(area_m2), 1)          AS media,
            quantile_cont(area_m2, 0.25)    AS p25,
            median(area_m2)                 AS mediana,
            quantile_cont(area_m2, 0.75)    AS p75,
            quantile_cont(area_m2, 0.95)    AS p95,
            quantile_cont(area_m2, 0.99)    AS p99
        FROM obras
        {_onde(uf)}
    """)


# Teto do histograma de área e largura da faixa. Acima do teto a cauda é longa
# demais para caber num gráfico legível — e some do gráfico, não da contagem: a
# última barra acumula. As duas são constantes porque o eixo do gráfico **tem que
# dizer o mesmo que o SQL**: o notebook e o app escreviam "faixas de 20 m², acima
# de 1.000 m² empilhado" à mão, e mexer aqui deixaria os dois rótulos mentindo.
TETO_HISTOGRAMA_M2 = 1000
LARGURA_FAIXA_HISTOGRAMA_M2 = 20


def histograma_area(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Histograma de `area_m2`, truncado em `TETO_HISTOGRAMA_M2`."""
    return curada.df(f"""
        SELECT
            least(
                floor(area_m2 / {LARGURA_FAIXA_HISTOGRAMA_M2}) * {LARGURA_FAIXA_HISTOGRAMA_M2},
                {TETO_HISTOGRAMA_M2}
            )        AS faixa_inicio,
            count(*) AS obras
        FROM obras
        {_onde(uf, extra="area_m2 IS NOT NULL AND area_m2 > 0")}
        GROUP BY 1
        ORDER BY 1
    """)


def faixas_area(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Contagem por faixa de área, na classificação que o pipeline gravou.

    Lê o mart. A ordem sai de `FAIXAS_AREA_M2`, a mesma tupla que gera os
    rótulos: escrever o `CASE` à mão faria uma faixa renomeada cair num `ELSE` e
    embaralhar o gráfico em silêncio.
    """
    ordem = ", ".join(f"'{rotulo}'" for rotulo in ROTULOS_FAIXA_AREA)
    return curada.df(f"""
        SELECT faixa_area, sum(n_obras) AS obras, sum(area_m2_total) / 1e6 AS area_km2
        FROM destinacao_ano
        {_onde(uf, extra="faixa_area IS NOT NULL")}
        GROUP BY 1
        ORDER BY list_position([{ordem}], faixa_area)
    """)


def cardinalidade(curada: Curada) -> pd.DataFrame:
    """Quanta informação o colapso para uma linha por obra teve que guardar.

    É o tamanho do 1:N que `n_areas` e `n_cnaes` preservam — e a razão de as duas
    colunas existirem em vez de o colapso ser silencioso.
    """
    return curada.df(
        _em_linhas(
            """
            SELECT
                count(*) FILTER (WHERE n_areas > 1)    AS "obras com mais de uma área",
                count(*) FILTER (WHERE n_areas = 0)    AS "obras sem nenhuma área",
                count(*) FILTER (WHERE n_cnaes > 1)    AS "obras com mais de um CNAE",
                count(*) FILTER (WHERE n_vinculos > 0) AS "obras com algum vínculo",
                max(n_areas)                           AS "maior número de áreas numa obra"
            FROM obras
            """,
            rotulo="situacao",
            valor="obras",
        )
    )


def responsavel(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """PF x PJ — a coluna que nasceu de um campo nulo em 66% das linhas.

    Lê o mart, não a analítica: `responsavel_tipo` só tem dois valores e nunca é
    nulo, então `PF = obras - PJ` é exato, não aproximado.
    """
    linha = curada.df(f"""
        SELECT sum(n_obras) AS obras, sum(n_pj) AS pj
        FROM municipio_ano
        {_onde(uf)}
    """).iloc[0]
    obras, pj = int(linha["obras"] or 0), int(linha["pj"] or 0)
    tabela = pd.DataFrame({"tipo": ["PF", "PJ"], "obras": [obras - pj, pj]}).sort_values(
        "obras", ascending=False, ignore_index=True
    )
    tabela["pct"] = (100.0 * tabela["obras"] / obras).round(1) if obras else 0.0
    return tabela


def situacao(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Distribuição por situação cadastral. Uma varredura do mart."""
    tabela = curada.df(
        _em_linhas(
            f"""
            SELECT
                sum(n_encerradas) AS "Encerrada",
                sum(n_ativas)     AS "Ativa",
                sum(n_paralisadas) AS "Paralisada",
                sum(n_nulas)      AS "Nula",
                sum(n_suspensas)  AS "Suspensa"
            FROM municipio_ano
            {_onde(uf)}
            """,
            rotulo="situacao",
            valor="obras",
        )
    )
    return tabela.sort_values("obras", ascending=False, ignore_index=True)


# ---------------------------------------------------------------------------
# 3. Geocodificação
# ---------------------------------------------------------------------------

# Rótulo das obras que não têm código utilizável. Mora aqui, e não no app, porque
# quem precisa reconhecê-lo depois é o funil — e uma string combinada entre duas
# camadas é uma string que um dia vai divergir.
SEM_GEOCODIFICACAO = "sem código utilizável"


def perfil_geo(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Cobertura da geocodificação por origem do ponto, com a plausibilidade ao lado.

    As duas colunas juntas são o argumento: `pontos` é a cobertura que um
    relatório otimista citaria, `plausiveis` é a que sobrevive a ser conferida
    contra o município declarado.
    """
    return curada.df(f"""
        SELECT
            coalesce(geo_origem, '{SEM_GEOCODIFICACAO}') AS origem,
            count(*)                                     AS pontos,
            count(*) FILTER (WHERE geo_plausivel)        AS plausiveis,
            round(median(geo_distancia_municipio_km), 2) AS dist_mediana_km,
            round(max(geo_distancia_municipio_km), 0)    AS dist_maxima_km
        FROM obras
        {_onde(uf)}
        GROUP BY 1
        ORDER BY pontos DESC
    """)


def funil_geocodificacao(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Os três números de "cobertura", do mais generoso ao publicável.

    Uma varredura só, e **uma definição só**: é esta função que o caderno e o app
    chamam. A versão anterior contava o degrau ingênuo com um `contains(..., '+')`
    escrito à mão nos dois lugares — o número mais citado da narrativa calculado
    por duas cópias do mesmo SQL.
    """
    tabela = curada.df(
        _em_linhas(
            f"""
            SELECT
                count(*) FILTER (WHERE contains(codigo_localizacao, '+'))
                    AS "contém um '+'",
                count(*) FILTER (WHERE geocodificada)
                    AS "decodifica de fato",
                count(*) FILTER (WHERE geo_plausivel)
                    AS "cai no município certo"
            FROM obras
            {_onde(uf)}
            """,
            rotulo="etapa",
            valor="obras",
        )
    )
    total = total_obras(curada, uf)
    tabela["pct_da_base"] = (100.0 * tabela["obras"] / total).round(1)
    return tabela


def total_obras(curada: Curada, uf: str | None = None) -> int:
    """Quantas obras o recorte tem. Do mart, e é o mesmo total do cabeçalho."""
    return int(curada.valor(f"SELECT sum(n_obras) FROM municipio_ano {_onde(uf)}") or 0)


def distancia_geo(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Quantos pontos caem perto, longe e do outro lado do mundo.

    O corte de plausibilidade é `LIMITE_PLAUSIBILIDADE_KM`, importado do pipeline:
    é o mesmo número que gravou `geo_plausivel`. Redigitá-lo faria este gráfico
    contradizer o funil ao lado, cada um chamando de "plausível" uma coisa.
    """
    return curada.df(f"""
        SELECT
            CASE
                WHEN geo_distancia_municipio_km <= {LIMITE_PLAUSIVEL_KM}
                    THEN 'até {LIMITE_PLAUSIVEL_KM} km (plausível)'
                WHEN geo_distancia_municipio_km <= 500  THEN '{LIMITE_PLAUSIVEL_KM} a 500 km'
                WHEN geo_distancia_municipio_km <= 5000 THEN '500 a 5.000 km'
                ELSE 'mais de 5.000 km'
            END      AS faixa,
            count(*) AS pontos
        FROM obras
        {_onde(uf, extra="geocodificada")}
        GROUP BY 1
        ORDER BY min(geo_distancia_municipio_km)
    """)


def pontos_fora(curada: Curada, limite: int = 10) -> pd.DataFrame:
    """Plus Codes válidos que decodificam para o outro lado do planeta."""
    return curada.df(f"""
        SELECT cno, uf, nome_municipio AS municipio, codigo_localizacao AS plus_code,
               round(latitude, 3) AS latitude, round(longitude, 3) AS longitude,
               round(geo_distancia_municipio_km, 0) AS distancia_km
        FROM obras
        WHERE geocodificada
        ORDER BY geo_distancia_municipio_km DESC
        LIMIT {limite}
    """)


def mapa_municipios(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Um ponto por município, com a mediana das coordenadas plausíveis.

    Lê o mart, não as 3,6 M de obras: o mapa responde na hora e continua sendo o
    mesmo número que o resto do painel mostra.
    """
    return curada.df(f"""
        SELECT
            uf,
            nome_municipio           AS municipio,
            sum(n_obras)             AS obras,
            sum(n_geocodificadas)    AS geocodificadas,
            sum(area_m2_total) / 1e6 AS area_km2,
            median(lat_mediana)      AS latitude,
            median(lon_mediana)      AS longitude
        FROM municipio_ano
        {_onde(uf, extra="lat_mediana IS NOT NULL")}
        GROUP BY 1, 2
        HAVING sum(n_geocodificadas) > 0
        ORDER BY obras DESC
    """)


def prefixo_ibge(curada: Curada, uf: str) -> str:
    """Os dois dígitos com que o código do IBGE identifica a UF.

    Sai da tabela de referência, não de um dicionário de 27 linhas escrito à mão.
    É o que permite recortar a malha municipal sem uma segunda de-para.
    """
    codigo = curada.valor(f"SELECT min(codigo_ibge)::VARCHAR FROM municipios WHERE uf = '{uf}'")
    return str(codigo)[:2]


# ---------------------------------------------------------------------------
# 4. Tempo
# ---------------------------------------------------------------------------


def obras_por_ano(
    curada: Curada, uf: str | None = None, desde: int = 1990, ate: int | None = None
) -> pd.DataFrame:
    """Série anual de obras e de área, do mart de municípios.

    `ate` é aberto por default de propósito: a versão anterior tinha `2026` fixo
    na assinatura, e um ano fixo num limite superior é uma data de validade que
    ninguém percebe vencer — em 2027 a série simplesmente pararia de crescer.
    """
    limite = f"ano_inicio BETWEEN {desde} AND {ate}" if ate else f"ano_inicio >= {desde}"
    return curada.df(f"""
        SELECT
            ano_inicio               AS ano,
            sum(n_obras)             AS obras,
            sum(area_m2_total) / 1e6 AS area_km2,
            sum(n_ativas)            AS ativas
        FROM municipio_ano
        {_onde(uf, extra=limite)}
        GROUP BY 1
        ORDER BY 1
    """)


def entrada_no_cadastro(curada: Curada) -> pd.DataFrame:
    """Quando as obras **entraram no CNO** — `data_registro`, não `data_inicio`.

    É a evidência que sustenta o corte de 2019 sem depender de ler a norma: o
    registro mais antigo é de 19/11/2018 — na mesma semana da IN RFB 1.845, de
    22/11/2018, três dias antes de ela sair — e 2018 inteiro tem 385 registros,
    todos de nov/dez. Antes disso o cadastro não existia, então a
    série por ano de início não mede construção — mede até onde o cadastro
    alcança para trás.
    """
    return curada.df("""
        SELECT
            year(data_registro) AS ano_registro,
            count(*)            AS obras,
            min(data_registro)  AS primeiro_registro
        FROM obras
        WHERE data_registro IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """)


def registro_de_obras_antigas(curada: Curada) -> pd.DataFrame:
    """Em que ano entraram as obras que **começaram antes** do corte.

    Desmonta a explicação fácil. Se o CNO tivesse absorvido o estoque do CEI
    *de uma vez*, as obras antigas teriam entrado todas em 2019. Entraram
    espalhadas por todos os anos — e mais em 2021 do que em 2019 —, porque
    registrar obra atrasada é rotina, não evento.
    """
    return curada.df(f"""
        SELECT
            year(data_registro) AS ano_registro,
            count(*)            AS obras_iniciadas_antes_de_{ANO_SERIE_COMPARAVEL}
        FROM obras
        WHERE ano_inicio < {ANO_SERIE_COMPARAVEL} AND data_registro IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """)


def atraso_de_registro(curada: Curada) -> pd.DataFrame:
    """Quanto tempo separa o início declarado da obra da sua entrada no cadastro.

    O número que fecha o argumento: 1,6 M de obras — 45% da base — foram
    registradas mais de um ano depois de começarem. Registro atrasado é o modo
    normal de operação desta base, não exceção.
    """
    return curada.df(
        _em_linhas(
            """
            SELECT
                count(*) FILTER (WHERE data_registro < data_inicio)
                    AS "registrada antes de começar",
                count(*) FILTER (WHERE datediff('day', data_inicio, data_registro)
                    BETWEEN 0 AND 30)        AS "registrada em até 30 dias",
                count(*) FILTER (WHERE datediff('day', data_inicio, data_registro)
                    BETWEEN 31 AND 365)      AS "registrada em até um ano",
                count(*) FILTER (WHERE datediff('day', data_inicio, data_registro) > 365)
                    AS "registrada mais de um ano depois"
            FROM obras
            WHERE data_registro IS NOT NULL AND data_inicio IS NOT NULL
            """,
            rotulo="situacao",
            valor="obras",
        )
    )


def datas_ausentes(curada: Curada) -> pd.DataFrame:
    """O que fica de fora da série: data nula e ano anterior a 1990."""
    return curada.df("""
        SELECT
            count(*) FILTER (WHERE data_inicio IS NULL) AS sem_data_inicio,
            count(*) FILTER (WHERE ano_inicio < 1990)   AS antes_de_1990,
            min(data_inicio)                            AS data_mais_antiga,
            max(data_inicio)                            AS data_mais_recente
        FROM obras
    """)


# ---------------------------------------------------------------------------
# 5. Recortes: território e setor
# ---------------------------------------------------------------------------

# Sem a tabela do IBGE não há denominador. As colunas continuam existindo, com
# valor nulo: **o esquema do retorno não muda**. Uma função que devolve colunas
# diferentes conforme um arquivo existir obriga todo chamador a saber disso, e
# quem esquecer recebe `KeyError` numa tela que deveria apenas degradar.
COLUNAS_SEM_REFERENCIA = """
    NULL::VARCHAR AS codigo_ibge,
    nome_municipio AS nome_ibge,
    NULL::VARCHAR AS regiao_imediata,
    NULL::VARCHAR AS regiao_intermediaria,
    NULL::BIGINT  AS populacao,
    NULL::DOUBLE  AS latitude_municipio,
    NULL::DOUBLE  AS longitude_municipio,
    false         AS casou_por_correcao
"""


def ranking_ufs(curada: Curada, comparavel: bool = False) -> pd.DataFrame:
    """Obras e área por UF. Com a referência do IBGE, também por mil habitantes."""
    base = f"""
        SELECT uf, sum(n_obras) AS obras, sum(area_m2_total) / 1e6 AS area_km2
        FROM municipio_ano
        {_onde(comparavel=comparavel, extra="uf IS NOT NULL")}
        GROUP BY 1
    """
    if not tem_referencias():
        return curada.df(f"""
            SELECT *, NULL::BIGINT AS populacao, NULL::DOUBLE AS obras_por_mil_hab
            FROM ({base}) ORDER BY obras DESC
        """)

    return curada.df(f"""
        SELECT b.*, p.populacao,
               round(1000.0 * b.obras / p.populacao, 1) AS obras_por_mil_hab
        FROM ({base}) b
        LEFT JOIN (
            SELECT uf, sum({referencias.coluna_populacao()}) AS populacao
            FROM municipios GROUP BY 1
        ) p USING (uf)
        ORDER BY b.obras DESC
    """)


def municipios(
    curada: Curada,
    uf: str | None = None,
    comparavel: bool = False,
    populacao_minima: int = 0,
) -> pd.DataFrame:
    """Um registro por município, com população e região quando há referência.

    A junção com o IBGE é a de `referencias.sql_juntar` — a mesma que o notebook
    usa. É `LEFT JOIN`: município que não casa continua na contagem, com o
    denominador nulo, em vez de sumir do total sem aviso.

    `populacao_minima` existe porque taxa por habitante em município de 2 mil
    habitantes é ruído: três obras a mais mudam o ranking do estado. É decisão de
    análise, então mora aqui e não na tela que desenha o ranking.
    """
    base = f"""
        SELECT
            uf, codigo_municipio, nome_municipio,
            sum(n_obras)          AS obras,
            sum(n_ativas)         AS ativas,
            sum(n_geocodificadas) AS geocodificadas,
            sum(area_m2_total)    AS area_m2
        FROM municipio_ano
        {_onde(uf, comparavel=comparavel)}
        GROUP BY 1, 2, 3
    """
    if tem_referencias():
        juntado = referencias.sql_juntar(f"({base})")
    else:
        juntado = f"SELECT *, {COLUNAS_SEM_REFERENCIA} FROM ({base})"

    return curada.df(f"""
        SELECT *,
               CASE WHEN populacao > 0 THEN round(1000.0 * obras / populacao, 1) END
                   AS obras_por_mil_hab
        FROM ({juntado})
        WHERE coalesce(populacao, 0) >= {populacao_minima}
        ORDER BY obras DESC
    """)


def divisoes_cnae(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """As três divisões da seção F, com obras e metros quadrados lado a lado.

    Lado a lado porque é aí que está o achado: infraestrutura é uma fatia pequena
    das obras e uma fatia grande da área.
    """
    return curada.df(f"""
        SELECT
            cnae_divisao                 AS divisao,
            any_value(cnae_divisao_nome) AS nome,
            sum(n_obras)                 AS obras,
            sum(area_m2_total) / 1e6     AS area_km2,
            round(100.0 * sum(n_obras) / sum(sum(n_obras)) OVER (), 1) AS pct_obras,
            round(100.0 * sum(area_m2_total) / sum(sum(area_m2_total)) OVER (), 1) AS pct_area
        FROM setor_ano
        {_onde(uf, extra="cnae_divisao IS NOT NULL")}
        GROUP BY 1
        ORDER BY obras DESC
    """)


def destinacoes(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Para que serve a obra, e de que tamanho ela costuma ser.

    Varre a tabela analítica, embora exista um mart com o mesmo recorte. O motivo
    é a mediana: o mart guarda a mediana de cada grupo (UF × destinação × faixa ×
    ano), e **mediana de medianas não é mediana** — somar contagens a partir de um
    agregado é exato, tirar quantil não é. Um número inventado por conveniência é
    exatamente o que este projeto não publica.

    Devolve todas as destinações; quem quiser as N maiores usa `.head(N)`. O corte
    ficava na consulta e fazia duas chamadas com limites diferentes pagarem duas
    varreduras pelo mesmo resultado.
    """
    return curada.df(f"""
        SELECT
            coalesce(destinacao_obra, 'não informada') AS destinacao,
            count(*)                 AS obras,
            sum(area_m2) / 1e6       AS area_km2,
            median(area_m2)          AS area_mediana_m2
        FROM obras
        {_onde(uf)}
        GROUP BY 1
        ORDER BY obras DESC
    """)


def regioes(curada: Curada, uf: str) -> pd.DataFrame:
    """Agrega por região intermediária do IBGE. Exige a tabela de referência."""
    base = f"""
        SELECT uf, nome_municipio, sum(n_obras) AS obras, sum(area_m2_total) AS area_m2
        FROM municipio_ano {_onde(uf)} GROUP BY 1, 2
    """
    return curada.df(f"""
        SELECT
            regiao_intermediaria                           AS regiao,
            count(*)                                       AS municipios,
            sum(obras)                                     AS obras,
            sum(populacao)                                 AS populacao,
            round(1000.0 * sum(obras) / sum(populacao), 1) AS obras_por_mil_hab,
            sum(area_m2) / 1e6                             AS area_km2
        FROM ({referencias.sql_juntar(f"({base})")})
        WHERE regiao_intermediaria IS NOT NULL
        GROUP BY 1
        ORDER BY obras DESC
    """)


def cobertura_referencias(curada: Curada) -> pd.DataFrame:
    """Quantos municípios do CNO casaram com o IBGE, e por qual caminho."""
    base = "SELECT DISTINCT uf, nome_municipio FROM municipio_ano WHERE uf IS NOT NULL"
    return curada.df(f"""
        SELECT
            count(*)                                    AS municipios_no_cno,
            count(codigo_ibge)                          AS casaram,
            count(*) FILTER (WHERE casou_por_correcao)  AS via_tabela_de_correcao,
            count(*) FILTER (WHERE codigo_ibge IS NULL) AS sem_par_no_ibge
        FROM ({referencias.sql_juntar(f"({base})")})
    """)


def ufs_disponiveis(curada: Curada) -> list[str]:
    """UFs presentes na base, para alimentar o seletor do dashboard."""
    return [
        linha[0]
        for linha in curada.con.execute(
            "SELECT DISTINCT uf FROM municipio_ano WHERE uf IS NOT NULL ORDER BY 1"
        ).fetchall()
    ]
