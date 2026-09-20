#!/usr/bin/env python3
"""Gera a tabela de referência de municípios usada pela análise.

**Isto não é uma etapa do pipeline, e é de propósito.** O pipeline processa uma
fonte só — o CNO da Receita — e toda a camada curada é derivável e reconciliável
a partir dela. Município, população e malha vêm do IBGE, mudam uma vez por ano e
não tornam nenhum número do pipeline certo ou errado: sem eles a análise perde o
per capita e o mapa, mas o dado continua válido.

Três motivos para essa separação, na ordem em que pesam:

1. **Acoplamento de falha.** Como task da DAG, uma indisponibilidade do IBGE
   derrubaria o pipeline do CNO, que não precisa do IBGE para nada.
2. **Cadências incompatíveis.** A DAG roda diariamente; o IBGE publica uma vez
   por ano. Seriam 365 buscas do mesmo arquivo.
3. **Assimetria de custo.** Trocar a safra da população é trocar um arquivo de
   300 KB, não reprocessar 3,6 M de linhas.

O resultado é **tabela de referência versionada**, não processo rodando por fora
— a mesma categoria dos nomes das seções da CNAE, que estão como constantes em
`dominios.py` e ninguém acha estranho que não sejam buscados toda noite.

Uso:

    python analise/construir_municipios.py              # regera os arquivos
    python analise/construir_municipios.py --verificar  # falha se a safra venceu

O modo `--verificar` existe para que o envelhecimento seja detectado por máquina,
e não pela memória de alguém. É o que a DAG `referencias_ibge` executa uma vez
por ano, e o que um passo de CI pode rodar num deploy em nuvem.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent

ARQUIVO_MUNICIPIOS = AQUI / "municipios.csv"
ARQUIVO_MALHA = AQUI / "malha_municipios.geojson.gz"
ARQUIVO_META = AQUI / "municipios.meta.json"

USER_AGENT = "cno-pipeline/0.1 (+https://github.com/joao-p-garcia/cno-pipeline-fiesc)"

# Lista de municípios, com código IBGE, UF e as regiões geográficas imediata e
# intermediária — que são o recorte regional oficial, e o que permite agregar os
# 295 municípios de SC em regiões que o público da FIESC reconhece.
URL_LOCALIDADES = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"

# População residente estimada, tabela 6579 do SIDRA, variável 9324, último ano
# publicado. Estimativa anual, não Censo: a defasagem é de meses, não de anos.
URL_POPULACAO = "https://apisidra.ibge.gov.br/values/t/6579/n6/all/v/9324/p/last"

# Malha municipal do país inteiro, na qualidade mínima (já simplificada pelo
# IBGE). São 3,1 MB de GeoJSON que comprimem para 0,8 MB — o suficiente para um
# coroplético sem depender de rede em tempo de execução.
URL_MALHA = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
    "?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=municipio"
)

# Quanto tempo a tabela vale antes de pedir revisão. O IBGE publica a estimativa
# populacional anualmente, por volta de agosto.
VALIDADE_MESES = 12


class ErroDeConstrucao(RuntimeError):
    """Falha ao montar a tabela de referência."""


# ---------------------------------------------------------------------------
# Busca
# ---------------------------------------------------------------------------


def _buscar(url: str, timeout: int = 300) -> bytes:
    requisicao = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            bruto = resposta.read()
    except OSError as exc:
        raise ErroDeConstrucao(f"falha ao buscar {url}: {exc}") from exc
    try:
        return gzip.decompress(bruto)
    except OSError:
        # A resposta não veio comprimida; é o caso comum.
        return bruto


def _localidades() -> dict[str, dict[str, str]]:
    """Código IBGE -> nome, UF e regiões geográficas."""
    dados = json.loads(_buscar(URL_LOCALIDADES).decode("utf-8"))
    municipios: dict[str, dict[str, str]] = {}
    for item in dados:
        imediata = item.get("regiao-imediata") or {}
        intermediaria = imediata.get("regiao-intermediaria") or {}
        # A UF aparece por dois caminhos conforme a resposta; o segundo é o
        # fallback para registros sem microrregião.
        micro = item.get("microrregiao") or {}
        uf = (micro.get("mesorregiao") or {}).get("UF") or intermediaria.get("UF") or {}
        municipios[str(item["id"])] = {
            "nome": item["nome"],
            "uf": uf.get("sigla", ""),
            "regiao_imediata": imediata.get("nome", ""),
            "regiao_intermediaria": intermediaria.get("nome", ""),
        }
    if not municipios:
        raise ErroDeConstrucao("a API de localidades não devolveu municípios")
    return municipios


def _populacao() -> tuple[dict[str, int], str]:
    """Código IBGE -> população, e o ano de referência declarado pela fonte."""
    dados = json.loads(_buscar(URL_POPULACAO).decode("utf-8"))
    # A primeira linha do SIDRA é o cabeçalho descritivo, não dado.
    linhas = dados[1:]
    populacao: dict[str, int] = {}
    anos: set[str] = set()
    for linha in linhas:
        valor = linha.get("V")
        if valor in (None, "...", "-", "X"):
            continue
        populacao[linha["D1C"]] = int(valor)
        anos.add(linha.get("D3N", ""))
    if not populacao:
        raise ErroDeConstrucao("o SIDRA não devolveu população")
    if len(anos) != 1:
        raise ErroDeConstrucao(f"esperava um único ano de referência, vieram {sorted(anos)}")
    return populacao, anos.pop()


def _centroide(geometria: dict) -> tuple[float, float]:
    """Centro do envelope da feição.

    Média das coordenadas, não centroide de polígono. É aproximação suficiente
    para posicionar um marcador ou uma legenda — o coroplético usa a malha, não
    este ponto —, e evita trazer shapely só para isso.
    """
    xs: list[float] = []
    ys: list[float] = []

    def andar(coordenadas) -> None:
        if isinstance(coordenadas[0], (int, float)):
            xs.append(coordenadas[0])
            ys.append(coordenadas[1])
            return
        for sub in coordenadas:
            andar(sub)

    andar(geometria["coordinates"])
    return sum(ys) / len(ys), sum(xs) / len(xs)


def _malha() -> tuple[bytes, dict[str, tuple[float, float]]]:
    """GeoJSON comprimido da malha e os centroides por código IBGE."""
    bruto = _buscar(URL_MALHA)
    geo = json.loads(bruto.decode("utf-8"))
    feicoes = geo.get("features", [])
    if not feicoes:
        raise ErroDeConstrucao("a malha não devolveu feições")

    centroides = {
        str(f["properties"]["codarea"]): _centroide(f["geometry"])
        for f in feicoes
        if f.get("geometry")
    }
    compacto = json.dumps(geo, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return gzip.compress(compacto, 9), centroides


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------

COLUNAS_FIXAS = (
    "codigo_ibge",
    "nome",
    "uf",
    "regiao_imediata",
    "regiao_intermediaria",
    "latitude",
    "longitude",
)


def construir() -> dict:
    """Busca as três fontes e materializa os arquivos de referência."""
    print("buscando lista de municípios...", flush=True)
    localidades = _localidades()
    print(f"  {len(localidades)} municípios")

    print("buscando população...", flush=True)
    populacao, ano = _populacao()
    print(f"  {len(populacao)} municípios, referência {ano}")

    print("buscando malha municipal...", flush=True)
    malha_gz, centroides = _malha()
    print(f"  {len(centroides)} feições, {len(malha_gz) / 1024:.0f} KB comprimidos")

    # A safra vai no nome da coluna, nunca numa nota de rodapé. Quem escrever
    # `populacao` sem o ano vai receber um erro de coluna inexistente em vez de
    # dividir 2026 por um denominador de outra época sem perceber.
    coluna_populacao = f"populacao_{ano}"
    cabecalho = [*COLUNAS_FIXAS, coluna_populacao]

    sem_populacao = 0
    sem_centroide = 0
    with ARQUIVO_MUNICIPIOS.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(cabecalho)
        for codigo in sorted(localidades):
            dados = localidades[codigo]
            lat, lon = centroides.get(codigo, ("", ""))
            if codigo not in centroides:
                sem_centroide += 1
            if codigo not in populacao:
                sem_populacao += 1
            escritor.writerow(
                [
                    codigo,
                    dados["nome"],
                    dados["uf"],
                    dados["regiao_imediata"],
                    dados["regiao_intermediaria"],
                    f"{lat:.6f}" if lat != "" else "",
                    f"{lon:.6f}" if lon != "" else "",
                    populacao.get(codigo, ""),
                ]
            )

    ARQUIVO_MALHA.write_bytes(malha_gz)

    hoje = datetime.now(UTC).date()
    meta = {
        "gerado_em": hoje.isoformat(),
        "valido_ate": hoje.replace(year=hoje.year + VALIDADE_MESES // 12).isoformat(),
        "safra_populacao": ano,
        "municipios": len(localidades),
        "sem_populacao": sem_populacao,
        "sem_centroide": sem_centroide,
        "fontes": {
            "localidades": URL_LOCALIDADES,
            "populacao": URL_POPULACAO,
            "malha": URL_MALHA,
        },
        "aviso": (
            "Tabela de referência do IBGE, fora do pipeline de propósito. "
            "Regerar com `python analise/construir_municipios.py` quando vencer. "
            "A DAG `referencias_ibge` verifica isso uma vez por ano."
        ),
    }
    ARQUIVO_META.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta


def verificar() -> int:
    """Falha se a tabela venceu. É o que a DAG de vigilância executa."""
    if not ARQUIVO_META.is_file():
        print(f"ERRO: {ARQUIVO_META} não existe — a tabela nunca foi gerada.")
        return 1
    meta = json.loads(ARQUIVO_META.read_text(encoding="utf-8"))
    valido_ate = date.fromisoformat(meta["valido_ate"])
    hoje = datetime.now(UTC).date()
    dias = (valido_ate - hoje).days

    print(f"safra da população : {meta['safra_populacao']}")
    print(f"gerado em          : {meta['gerado_em']}")
    print(f"válido até         : {meta['valido_ate']}")

    if dias < 0:
        print(
            f"\nERRO: a tabela de municípios venceu há {-dias} dias.\n"
            "O IBGE publica nova estimativa populacional por volta de agosto.\n"
            "Regere com:  python analise/construir_municipios.py"
        )
        return 1
    if dias < 30:
        print(f"\nAVISO: vence em {dias} dias.")
    else:
        print(f"\nOK: válida por mais {dias} dias.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--verificar",
        action="store_true",
        help="não busca nada; só confere se a safra atual ainda vale",
    )
    args = parser.parse_args(argv)

    if args.verificar:
        return verificar()

    try:
        meta = construir()
    except ErroDeConstrucao as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    print()
    print(f"{ARQUIVO_MUNICIPIOS.name}: {meta['municipios']} municípios")
    print(f"{ARQUIVO_MALHA.name}: {ARQUIVO_MALHA.stat().st_size / 1024:.0f} KB")
    print(f"safra da população: {meta['safra_populacao']} · válida até {meta['valido_ate']}")
    if meta["sem_populacao"] or meta["sem_centroide"]:
        print(f"sem população: {meta['sem_populacao']} · sem centroide: {meta['sem_centroide']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
