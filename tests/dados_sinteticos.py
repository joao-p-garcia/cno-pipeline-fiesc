"""Dados sintéticos que imitam o pacote real da Receita.

Vive em módulo próprio porque tanto os testes de tratamento quanto os de
validação precisam da mesma camada raw de mentira. As 26 colunas do `cno.csv`
aparecem com os nomes originais, typos da fonte inclusive, porque o SQL do
tratamento referencia esses nomes literalmente — um fixture simplificado passaria
sem exercitar o contrato de verdade.
"""

from __future__ import annotations

SNAPSHOT = "2026-09-12"

CABECALHO_OBRAS = (
    '"CNO","Código do Pais","Nome do pais","Data de início",'
    '"Data de inicio da responsabilidade","Data de registro","CNO vinculado","CEP",'
    '"NI do responsável","Qualificação do responsavel","Nome","Código do municipio",'
    '"Nome do município","Tipo de logradouro","Logradouro","Número do logradouro",'
    '"Bairro","Estado","Caixa Postal","Complemento","Unidade de medida","Área total",'
    '"Situação","Data da situação","Nome empresarial","Código de localização"\n'
)


def _obra(
    cno: str,
    *,
    uf: str = "SC",
    ni: str = "",
    empresarial: str = "",
    data_inicio: str = "2020-03-15",
    data_situacao: str = "2021-06-01",
    area: str = "412.00",
    unidade: str = "m2",
    situacao: str = "02",
    qualificacao: str = "0070",
    pais: str = "105",
    nome_pais: str = "BRASIL",
    localizacao: str = "58PJ64Q5+JP",
    nome: str = "OBRA DE TESTE",
) -> str:
    return (
        f'{cno},{pais},"{nome_pais}",{data_inicio},{data_inicio},2022-05-17,,88010000,'
        f'{ni},{qualificacao},"{nome}",8105,"FLORIANÓPOLIS","RUA","DAS PALMEIRAS","150",'
        f'"CENTRO","{uf}",,"APTO 3","{unidade}",{area},{situacao},{data_situacao},'
        f'"{empresarial}","{localizacao}"\n'
    )


OBRAS_CSV = CABECALHO_OBRAS + "".join(
    [
        # pessoa física: NI e nome empresarial vazios por definição da Receita
        _obra("010010092278"),
        # pessoa jurídica
        _obra("010010119379", ni="02688984000170", empresarial="CONSTRUTORA X LTDA"),
        # sentinelas de data
        _obra("010010119380", data_inicio="1970-01-01", data_situacao="1970-01-01"),
        _obra("010010119381", data_inicio="1900-01-01", data_situacao="2000-01-01"),
        # área absurda, em m2 -> deve ganhar flag e permanecer
        _obra("010010119382", area="555555555555.55"),
        # área grande mas em km -> não é suspeita
        _obra("010010119383", area="9999999.00", unidade="km"),
        # UF por extenso, recuperável
        _obra("010010119384", uf="SÃO PAULO"),
        # UF lixo, deve virar NULL
        _obra("010010119385", uf="estado"),
        # obra no exterior
        _obra("010010119386", uf="EX", pais="249", nome_pais="ESTADOS UNIDOS"),
        # sem plus code
        _obra("010010119387", localizacao=""),
        # situação encerrada
        _obra("010010119388", situacao="15"),
        # tipografia cp1252 no nome
        _obra("010010119389", nome="OBRA – FASE 2"),
    ]
)

AREAS_CSV = (
    '"CNO","Categoria","Destinação","Tipo de obra","Tipo de Área",'
    '"Tipo de Área Complementar","Metragem"\n'
    '010010092278,"Obra Nova","Residencial unifamiliar","Alvenaria","Principal",,412.00\n'
    # linha idêntica à anterior: duplicata real, deve sumir
    '010010092278,"Obra Nova","Residencial unifamiliar","Alvenaria","Principal",,412.00\n'
    # mesma obra, área complementar legítima: NÃO é duplicata
    '010010092278,"Obra Nova","Residencial unifamiliar","Alvenaria",'
    '"Complementar","Piscina",30.00\n'
    '010010119379,"Reforma","Galpão industrial","Mista","Principal",,5258.21\n'
)

CNAES_CSV = (
    '"CNO","CNAE","Data de registro"\n'
    "010010092278,4120400,2022-05-17\n"
    "010010119379,4399103,2026-06-30\n"
)

VINCULOS_CSV = (
    '"CNO","Data de início","Data de fim","Data de registro",'
    '"Qualificação do contribuinte","NI do responsável"\n'
    "010010092278,1988-08-01,,2022-05-26,0053,02688984000170\n"
    # duplicata exata
    "010010092278,1988-08-01,,2022-05-26,0053,02688984000170\n"
    "010010119379,2025-05-23,2026-01-31,2025-05-23,0110,\n"
)

TOTAIS_CSV = (
    '"Total de obras","Total de cnaes","Total de áreas","Total de vínculos"\n'
    '"00000000012","00000000002","00000000004","00000000003"\n'
)

ARQUIVOS = {
    "cno.csv": OBRAS_CSV,
    "cno_areas.csv": AREAS_CSV,
    "cno_cnaes.csv": CNAES_CSV,
    "cno_vinculos.csv": VINCULOS_CSV,
    "cno_totais.csv": TOTAIS_CSV,
}
