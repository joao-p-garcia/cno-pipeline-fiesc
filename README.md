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

Tratar os dados e materializar a camada staging em parquet (~20s para os 12,5 M
de linhas das quatro tabelas):

```bash
cno transform
```

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
├── cli.py               comandos `cno extract`, `cno transform` e `cno info`
├── logging_conf.py      log em texto ou JSON (CNO_LOG_JSON=1)
├── extract/
│   ├── source.py        HTTP: HEAD, sonda de Range, download resumível com retry
│   ├── cno.py           orquestração, descompactação validada, totais de controle
│   └── manifest.py      proveniência e controle de idempotência
└── transform/
    ├── schema.py        contrato de dados: domínios, tipos e regras de limpeza
    ├── sql.py           o SQL do tratamento, montado a partir do contrato
    ├── encoding.py      transcodificação cp1252 → UTF-8
    └── staging.py       carga no DuckDB e escrita em parquet particionado

data/                    gerado, nunca versionado
├── raw/
│   ├── _manifests/      um JSON por snapshot + ponteiro latest.json
│   └── snapshot_date=AAAA-MM-DD/
│       ├── cno.zip      artefato original, preservado
│       └── csv/         os cinco CSVs extraídos
└── staging/
    ├── _manifests/      métricas de cada execução do tratamento
    ├── obras/snapshot_date=.../uf=SC/*.parquet
    ├── areas/snapshot_date=.../*.parquet
    ├── cnaes/snapshot_date=.../*.parquet
    └── vinculos/snapshot_date=.../*.parquet
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

### Tratamento

**Os CSVs são transcodificados para UTF-8 antes da carga.** O DuckDB lê `utf-8`,
`utf-16` e `latin-1`, mas não cp1252. A alternativa — carregar como `latin-1` e
corrigir os caracteres em SQL — exigiria aplicar a correção coluna a coluna, e
esquecer uma seria corrupção invisível. O intermediário é reaproveitado entre
execuções e invalidado automaticamente pelo sha256 dos arquivos de origem.

**Tudo é lido como texto e convertido com `TRY_CAST`.** Deixar o `read_csv`
inferir tipos faria a carga inteira falhar num único valor ruim. Assim, um valor
inconversível vira `NULL` e as 3,6 M de linhas continuam carregando.

**Identificadores são texto, não número.** `cno`, `cep`, `ni_responsavel` e os
códigos de município e qualificação têm zeros à esquerda que um tipo numérico
destruiria (`010010092278` viraria `10010092278`).

**Flags booleanas nunca são nulas.** Em SQL, `NULL LIKE '%+%'` devolve `NULL`, e
uma flag de três valores é armadilha: `WHERE NOT tem_plus_code` descartaria em
silêncio os 40,78% de registros sem código de localização. Todas as flags passam
por `coalesce(..., false)`.

**Nada é excluído por suspeita.** As 323 obras com área implausível em m² recebem
`area_suspeita = true` e permanecem na tabela. Quem analisa decide o que fazer
com elas; o pipeline não decide por ele.

**Os 66,39% de nulos em `ni_responsavel` viram `responsavel_tipo`.** Não são
dados faltantes: a Receita deixa o campo em branco quando o responsável é pessoa
física. Imputar destruiria a informação.

**O particionamento é por `snapshot_date` e `uf`.** Uma consulta restrita a Santa
Catarina lê só 239 mil linhas em vez de 3,6 milhões.

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
- [x] Tratamento: CSV → parquet tipado e particionado
- [ ] Funções de validação, com reconciliação contra os totais oficiais
- [ ] Orquestração em DAG
- [ ] Containerização
- [ ] Análise descritiva
