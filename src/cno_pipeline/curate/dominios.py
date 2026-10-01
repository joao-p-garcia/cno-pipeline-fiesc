"""Domínios da camada curada."""

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

DIVISOES_CNAE: dict[str, str] = {
    "41": "Construção de edifícios",
    "42": "Obras de infraestrutura",
    "43": "Serviços especializados para construção",
}

# Distância máxima até a mediana do município para o ponto ser plausível. Nenhum
# município brasileiro tem raio perto disso. 48.460 pontos válidos (3,7%) passam
# do limite, alguns no Japão.
LIMITE_PLAUSIBILIDADE_KM = 150


# Cortes a partir da distribuição real (mediana 135 m², p75 270 m², p99 12.049 m²).
FAIXAS_AREA_M2: tuple[tuple[float | None, float | None, str], ...] = (
    (None, 70, "até 70 m²"),
    (70, 150, "70 a 150 m²"),
    (150, 500, "150 a 500 m²"),
    (500, 5000, "500 a 5.000 m²"),
    (5000, None, "acima de 5.000 m²"),
)

# O CNO passou a valer em 21/01/2019 (IN RFB 1.845/2018). Antes disso a série mede
# a cobertura do cadastro, não construção, e muda a cada snapshot porque obras
# antigas continuam sendo registradas.
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
