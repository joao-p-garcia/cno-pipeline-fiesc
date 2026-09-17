# cno-pipeline-fiesc

Pipeline de extração e tratamento da base do **CNO — Cadastro Nacional de Obras**
da Receita Federal.

> **Status:** etapa de extração concluída e testada. Aqui, a ideia é realizar uma análise inicial dos dados para entender como transformar eles pra algo mais útil, ao mesmo tempo em que já estou construindo uma solução escalável quando colocarmos o deploy. Tratamento, orquestração e análise descritiva em construção — veja [Roadmap](#roadmap).

## Requisitos

Python 3.11+  (por enquanto, em construção). Utilizar o pyproject.toml para baixar as libs necessárias.
## Como executar

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Consultar a fonte sem baixar nada (faz só um `HEAD`):

```bash
cno info
```

Baixar e materializar a camada raw (~315 MB comprimidos, ~1,4 GB extraídos):

```bash
cno extract
```

Rodar de novo não baixa nada: se o ETag da fonte bate com o do manifesto local (ou seja, comparamos os metadados para saber se houve dados novos ou não) e
os arquivos conferem, a etapa é pulada. Para forçar, `cno extract --force`.

Testes (não tocam a rede, rodam em segundos):

```bash
pytest
```

Deixei uma MAKEFILE para facilitar rodar o código. (`make setup`, `make info`,
`make extract`, `make test`, `make lint`).

### Configuração local opcional

Sem nenhuma configuração o pipeline usa `./data` e defaults sensatos. Para
mudar, copie `.env.exemplo` para `.env` — ele não é versionado. A variável mais
útil é `CNO_DATA_DIR`, que move as camadas de dados para fora do repositório:

```bash
CNO_DATA_DIR=/caminho/para/dados
```

Isso importa quando o repositório está numa pasta montada — em WSL, com o código
em `/mnt/c`, apontar os dados para um caminho nativo do Linux acelera bastante o
processamento dos 1,4 GB de CSV.

## Estrutura

```
src/cno_pipeline/
├── config.py            parâmetros, todos sobrescrevíveis por variável de ambiente
├── cli.py               comandos `cno extract` e `cno info`
├── logging_conf.py      log em texto ou JSON (CNO_LOG_JSON=1)
└── extract/
    ├── source.py        HTTP: HEAD, sonda de Range, download resumível com retry
    ├── cno.py           orquestração, descompactação validada, totais de controle
    └── manifest.py      proveniência e controle de idempotência

data/                    gerado, nunca versionado
└── raw/
    ├── _manifests/      um JSON por snapshot + ponteiro latest.json
    └── snapshot_date=AAAA-MM-DD/
        ├── cno.zip      artefato original, preservado
        └── csv/         os cinco CSVs extraídos
```

## Decisões técnicas

**O snapshot é identificado pela data de publicação da fonte**, lida do
`Last-Modified`, não pela data em que o pipeline rodou. Reprocessar amanhã não
cria um snapshot novo para os mesmos dados.

**A idempotência é controlada por ETag local.** O share da Receita
**não respeita `If-None-Match`** — responde `200` e reenvia os 315 MB inteiros.
Um `HEAD` retorna o ETag, que é comparado com o último snapshot para saber se precisa baixar hoje.

**O suporte a `Range` é detectado por sondagem, não pelo cabeçalho.** O `HEAD`
desta fonte não devolve `Accept-Ranges`, embora o servidor responda `206` a um
`GET` com `Range`. Acreditar no cabeçalho faria o pipeline rebaixar tudo do zero
a cada falha de rede, então uma requisição de 1 byte resolve a dúvida e habilita
download resumível.

**Os dados são baixados para `.part` e só promovidos ao nome final após
conferência de tamanho**, de modo que uma interrupção nunca deixa um arquivo
truncado parecendo completo.

**A descompactação valida o pacote antes de escrever**: rejeita membros com
caminho (`zip-slip`) e falha explicitamente se algum dos cinco arquivos
esperados sumir, em vez de produzir uma camada raw silenciosamente incompleta.

**Os totais oficiais da Receita viram parte do manifesto.** O `cno_totais.csv`
publica as contagens de cada tabela (3.604.156 obras, 4.553.076 áreas,
3.942.713 cnaes, 431.211 vínculos). Registrá-los na extração dá à etapa de
validação um oráculo externo para reconciliar, em vez de o pipeline conferir
apenas contra si mesmo.

## Sobre os dados

Aqui fiz uma análise inicial dos dados antes de montar a pipeline. Isso serve para evitar erros em produção.
Características apuradas por perfilamento completo da base, que orientam o
tratamento:

- Os CSVs são **cp1252** (Windows-1252), não UTF-8 e **não ISO-8859-1**. O
  `cno.csv` tem 4.881 bytes na faixa `0x80-0x9F`, que em cp1252 são tipografia
  (travessão, aspas curvas, bullet) e em ISO-8859-1 são controles indefinidos.
  Ler como `latin-1` não dá erro — produz caracteres de controle no lugar do
  texto, corrompendo em silêncio.
- `CNO` é chave primária limpa na tabela principal (zero duplicatas em 3,6 M).
  As tabelas filhas têm duplicatas exatas reais: 21.449 em áreas, 10.873 em
  vínculos.
- Integridade referencial perfeita: nenhum órfão nas três tabelas filhas.
- **`NI do responsável` e `Nome empresarial` nulos em 66,39% não são dados
  faltantes.** Por definição da Receita, ficam em branco quando o responsável é
  pessoa física. Serão modelados como flag PF/PJ, nunca imputados.
- `Código de localização` é **Plus Code** em 2,11 M registros (59%), o que
  permite geocodificação sem serviço externo.
- Sujeira conhecida: `1970-01-01` e `1900-01-01` como sentinelas de data
  desconhecida; áreas absurdas (máximo de 555.555.555.555 m²); campo `Estado`
  com 35 valores distintos, incluindo lixo como `'CHILE'` e `'estado'`.

## Roadmap

- [x] Extração programática, idempotente e resumível
- [x] Camada raw versionada por snapshot, com manifesto de proveniência
- [x] Testes automatizados da extração (offline)
- [ ] Tratamento: CSV → parquet tipado
- [ ] Funções de validação, com reconciliação contra os totais oficiais
- [ ] Orquestração em DAG
- [ ] Containerização
- [ ] Análise descritiva
