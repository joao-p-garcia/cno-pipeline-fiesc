"""Domínios da camada curada.

Aqui moram classificações que são **estrutura**, não dado: a divisão do CNAE em
seções é uma regra fixa da CNAE 2.0, publicada pela CONCLA, que não muda de ano
para ano nem depende de qual snapshot está sendo processado. Embutir 21 constantes
é honesto; seria desonesto embutir população ou PIB, que envelhecem — esses ficam
fora do pipeline, na camada de análise.

A decodificação de `Situação` e `Qualificação` **não está aqui**: já acontece em
`transform/schema.py`, a partir dos domínios que o próprio dicionário de dados da
Receita publica inline. A camada curada não repete o que a staging já fez.
"""

from __future__ import annotations

# Seções da CNAE 2.0, por faixa de divisão (os dois primeiros dígitos do código).
# O CNAE na base é numérico de 7 dígitos, sem pontuação: `4391600` é divisão 43.
SECOES_CNAE: tuple[tuple[int, int, str, str], ...] = (
    (1, 3, "A", "Agricultura, pecuária, produção florestal, pesca e aquicultura"),
    (5, 9, "B", "Indústrias extrativas"),
    (10, 33, "C", "Indústrias de transformação"),
    (35, 35, "D", "Eletricidade e gás"),
    (36, 39, "E", "Água, esgoto, gestão de resíduos e descontaminação"),
    (41, 43, "F", "Construção"),
    (45, 47, "G", "Comércio e reparação de veículos automotores e motocicletas"),
    (49, 53, "H", "Transporte, armazenagem e correio"),
    (55, 56, "I", "Alojamento e alimentação"),
    (58, 63, "J", "Informação e comunicação"),
    (64, 66, "K", "Atividades financeiras, de seguros e serviços relacionados"),
    (68, 68, "L", "Atividades imobiliárias"),
    (69, 75, "M", "Atividades profissionais, científicas e técnicas"),
    (77, 82, "N", "Atividades administrativas e serviços complementares"),
    (84, 84, "O", "Administração pública, defesa e seguridade social"),
    (85, 85, "P", "Educação"),
    (86, 88, "Q", "Saúde humana e serviços sociais"),
    (90, 93, "R", "Artes, cultura, esporte e recreação"),
    (94, 96, "S", "Outras atividades de serviços"),
    (97, 97, "T", "Serviços domésticos"),
    (99, 99, "U", "Organismos internacionais e outras instituições extraterritoriais"),
)

# Divisões da seção F. O CNO é um cadastro de obras: as três divisões abaixo
# cobrem 100% da base (41 com 1.905.075 obras, 43 com 1.415.825, 42 com 283.256),
# e nenhuma outra divisão aparece. Agrupar por seção seria inútil aqui — daria
# uma linha só —, então é a divisão que serve de recorte setorial.
#
# As demais divisões da CNAE não estão nomeadas de propósito: nomear 87 divisões
# que não ocorrem seria peso morto. Se uma publicação futura trouxer outra, o
# código da divisão continua preenchido e só o nome fica nulo — visível, não
# silencioso.
DIVISOES_CNAE: dict[str, str] = {
    "41": "Construção de edifícios",
    "42": "Obras de infraestrutura",
    "43": "Serviços especializados para construção",
}

# Distância máxima entre o ponto geocodificado e a mediana do município para o
# ponto ser considerado plausível. Não há município brasileiro com raio perto
# disso — o maior, Altamira/PA, fica bem abaixo —, então passar de 150 km
# significa que o código aponta para outro lugar.
#
# O limite existe porque um Plus Code pode ser sintaticamente válido e mesmo
# assim estar errado: medidos 48.460 pontos (3,7% dos decodificados) a mais de
# 150 km do município declarado, 39.105 deles a mais de 500 km, alguns caindo no
# Japão. Sem esse corte, o mapa mostraria obras catarinenses em Kyushu.
LIMITE_PLAUSIBILIDADE_KM = 150


# Faixas de área para segmentar a análise. Os cortes saem da distribuição real
# (mediana 135 m², p75 270 m², p99 12.049 m²), não de números redondos escolhidos
# no olho: 150 separa a obra residencial típica, 500 separa o multifamiliar
# pequeno, e 5.000 isola o que é obra de porte industrial ou comercial.
FAIXAS_AREA_M2: tuple[tuple[float | None, float | None, str], ...] = (
    (None, 70, "até 70 m²"),
    (70, 150, "70 a 150 m²"),
    (150, 500, "150 a 500 m²"),
    (500, 5000, "500 a 5.000 m²"),
    (5000, None, "acima de 5.000 m²"),
)

# A partir deste ano a série é comparável. Antes disso o volume reflete a
# migração da matrícula CEI para o CNO, não atividade de construção: as obras por
# ano saltam de 87 mil (2016) para 307 mil (2019) e depois estabilizam em ~300
# mil, que é assinatura de recadastramento, não de crescimento setorial.
PRIMEIRO_ANO_COMPARAVEL = 2019


def secao_cnae(codigo: str | None) -> tuple[str, str] | None:
    """Devolve (letra, nome) da seção CNAE, ou None se o código não for válido."""
    if not codigo or len(codigo) < 2 or not codigo[:2].isdigit():
        return None
    divisao = int(codigo[:2])
    for inicio, fim, letra, nome in SECOES_CNAE:
        if inicio <= divisao <= fim:
            return letra, nome
    return None


def divisao_cnae(codigo: str | None) -> tuple[str, str | None] | None:
    """Devolve (divisão, nome) do CNAE. O nome é None fora da seção F."""
    if not codigo or len(codigo) < 2 or not codigo[:2].isdigit():
        return None
    divisao = codigo[:2]
    return divisao, DIVISOES_CNAE.get(divisao)
