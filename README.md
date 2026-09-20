# cno-pipeline-fiesc

Pipeline de extração e tratamento da base do **CNO — Cadastro Nacional de Obras**
da Receita Federal.

> **Status:** etapa de extração concluída e testada. Aqui, a ideia é realizar uma análise inicial dos dados para entender como transformar eles pra algo mais útil, ao mesmo tempo em que já estou construindo uma solução escalável quando colocarmos o deploy. Tratamento, orquestração e análise descritiva em construção — veja [Roadmap](#roadmap).

## Requisitos

Python 3.11+  (por enquanto, em construção). Utilizar o pyproject.toml para baixar as libs necessárias.

Para rodar em container, só Docker com Compose v2 — nem Python nem Airflow
precisam existir na máquina. Veja [Em container](#em-container).

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

Validar a camada tratada e reconciliar com os totais da Receita (~6s):

```bash
cno validate
```

Sai com código 1 se houver divergência de reconciliação ou violação de regra com
severidade de erro — é o que faz a task falhar no orquestrador.

Modelar a camada curada, que é o que a análise e o dashboard consomem (~35s):

```bash
cno curate
```

Ela produz uma linha por obra em `obras_analitico` e três marts pré-agregados.
É também onde a geocodificação acontece, a partir do Plus Code, sem serviço
externo.

Testes (não tocam a rede, rodam em segundos):

```bash
pytest
```

O pipeline inteiro de uma vez:

```bash
make pipeline      # extract -> transform -> validate
```

Deixei uma MAKEFILE para facilitar rodar o código. `make help` lista tudo
(`setup`, `info`, `extract`, `transform`, `validate`, `pipeline`, `test`,
`test-dag`, `lint`, `fmt`, `clean`).

### Orquestração

A DAG vive em `dags/cno_pipeline_dag.py` e encadeia as três etapas. Para rodar
localmente é preciso um venv separado com o Airflow:

```bash
python3 -m venv ~/.venvs/airflow
~/.venvs/airflow/bin/pip install "apache-airflow==3.3.2"   --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt

export AIRFLOW_HOME=~/airflow
export AIRFLOW__CORE__DAGS_FOLDER=$PWD/dags
export CNO_BIN=$PWD/.venv/bin/cno
~/.venvs/airflow/bin/airflow db migrate
~/.venvs/airflow/bin/airflow dags test cno_pipeline
```

Os testes da DAG rodam com `make test-dag`.

### Em container

Se a ideia for só ver tudo funcionando, sem instalar Python, Airflow nem
Postgres, tem Docker:

```bash
make up
```

Isso constrói a imagem, sobe Airflow 3.3.2 com LocalExecutor sobre Postgres e
deixa a UI em <http://localhost:8080> (usuário `airflow`, senha `airflow`).

A DAG sobe despausada e **começa a rodar sozinha**, sem nenhum passo a mais:
baixa os ~315 MB da Receita, trata as 12,5 M de linhas e valida o resultado.
Medido nesta stack, a primeira execução leva 2m13s (1m37s só de download) e as
seguintes 31s, porque a extração reaproveita o snapshot. Para disparar de novo:
`make dag-run`, ou o botão na UI.

Se preferir que nada rode até você mandar, ponha
`AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: 'true'` no `docker-compose.yml`.

```bash
make logs        # acompanha a execução
make ps          # estado dos serviços
make down        # derruba, preservando os dados já materializados
make down-tudo   # derruba e apaga os volumes também
```

Para rodar o pipeline sem orquestrador nenhum, em containers efêmeros que
escrevem no mesmo volume:

```bash
make docker-pipeline                      # extract -> transform -> validate
docker compose run --rm cno info          # ou uma etapa isolada
```

As camadas de dados ficam num volume Docker (`cno-dados`), não no repositório.
Isso mantém o clone limpo e evita o custo de I/O de escrever 1,4 GB numa pasta
montada do host.

O container é o empacotamento da entrega, não o ambiente de desenvolvimento —
para desenvolver, `make pipeline` roda direto e sem esperar build.

### Camada de análise e a tabela do IBGE

O pipeline processa **uma fonte só**: o CNO da Receita. Município, população e
malha territorial vêm do IBGE e ficam **fora** do pipeline, em `analise/`, como
tabela de referência versionada:

```
analise/
├── construir_municipios.py     gera os arquivos abaixo a partir das APIs do IBGE
├── municipios.csv              5.571 municípios: código, UF, região, população, centroide
├── correcoes_municipios.csv    as 17 divergências de nome, escritas à mão
├── malha_municipios.geojson.gz malha municipal para o mapa (792 KB)
└── referencias.py              a junção, usada igual pelo notebook e pelo dashboard
```

> ### ⚠️ Regerar uma vez por ano
>
> A população é a estimativa anual do IBGE, publicada por volta de **agosto**.
> Os arquivos declaram a própria validade em `municipios.meta.json`, e a partir
> dela **nada depende da memória de ninguém**:
>
> ```bash
> python analise/construir_municipios.py --verificar   # falha se a safra venceu
> python analise/construir_municipios.py               # regera e atualiza a validade
> ```
>
> A DAG **`referencias_ibge`** roda esse `--verificar` mensalmente e falha
> quando a safra vence — e falha no Airflow é o que dispara o alerta. Ela é uma
> DAG **separada** de propósito: pode ficar vermelha sem afetar a
> `cno_pipeline`.
>
> Enquanto não for regerada, todo número per capita usa um denominador vencido.

**Por que fora do pipeline:** uma indisponibilidade do IBGE não pode derrubar uma
esteira que não precisa do IBGE para nada; a DAG roda diariamente e o IBGE
publica uma vez por ano; e trocar a safra é trocar um arquivo de 400 KB em vez de
reprocessar 3,6 M de linhas. Ver [Fronteira de dados externos](#fronteira-de-dados-externos).

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
├── transform/
│   ├── schema.py        contrato de dados: domínios, tipos e regras de limpeza
│   ├── sql.py           o SQL do tratamento, montado a partir do contrato
│   ├── encoding.py      transcodificação cp1252 → UTF-8, só onde é preciso
│   └── staging.py       carga no DuckDB e escrita em parquet particionado
├── validate/
│   ├── regras.py        19 regras, cada uma um SELECT do que está errado
│   └── executor.py      avalia, reconcilia com a fonte e emite o relatório
└── curate/
    ├── dominios.py      seções e divisões da CNAE, faixas de área, limites
    ├── geocodificacao.py  Plus Code offline, com recuperação dos códigos curtos
    ├── sql.py           a tabela analítica e os três marts
    └── curated.py       orquestração e métricas de cobertura

dags/
├── cno_pipeline_dag.py     encadeia extract -> transform -> validate -> curate
└── referencias_ibge_dag.py vigia a validade da tabela do IBGE (DAG separada)

analise/                 camada de análise, fora do pipeline
├── construir_municipios.py  gera a tabela de referência do IBGE
├── municipios.csv           5.571 municípios com população e centroide
├── correcoes_municipios.csv as 17 divergências de nome, à mão
├── malha_municipios.geojson.gz  malha para o coroplético
└── referencias.py           a junção, usada pelo notebook e pelo dashboard

Dockerfile               imagem única: Airflow oficial + pipeline em /opt/cno/.venv
docker-compose.yml       stack de entrega: Airflow LocalExecutor + Postgres

data/                    gerado, nunca versionado
├── raw/
│   ├── _manifests/      um JSON por snapshot + ponteiro latest.json
│   └── snapshot_date=AAAA-MM-DD/
│       ├── cno.zip      artefato original, preservado
│       └── csv/         os cinco CSVs extraídos
└── staging/
    ├── _manifests/      métricas de cada execução do tratamento
    ├── _validacao/      relatório de validação por snapshot
    ├── obras/snapshot_date=.../uf=SC/*.parquet
    ├── areas/snapshot_date=.../*.parquet
    ├── cnaes/snapshot_date=.../*.parquet
    └── vinculos/snapshot_date=.../*.parquet
└── curated/
    ├── _manifests/      cobertura da geocodificação e tamanho de cada tabela
    ├── obras_analitico/ uma linha por obra, para drill-down
    ├── mart_municipio_ano/   133 mil linhas
    ├── mart_setor_ano/        12 mil linhas
    └── mart_destinacao_ano/   59 mil linhas
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

**Só o arquivo que precisa é transcodificado para UTF-8.**

cp1252 e ISO-8859-1 são idênticos em `0x00-0x7F` e `0xA0-0xFF`. Divergem
*somente* em `0x80-0x9F` — onde cp1252 põe tipografia e ISO-8859-1 deixa
controles indefinidos. Um arquivo sem nenhum byte nessa faixa, portanto,
decodifica exatamente igual nos dois, e o DuckDB pode lê-lo direto como
`latin-1`, sem intermediário. Na base atual isso vale para 4 dos 5 arquivos; só
o `cno.csv` tem os tais bytes, e só ele é convertido. A decisão é tomada por
varredura de conteúdo, não por lista de nomes, então uma publicação futura que
introduza tipografia em outra tabela se resolve sozinha.

A conversão em si é trabalho inevitável: bytes cp1252 precisam virar texto
Unicode em algum momento, e todo engine faz isso. A diferença é só *onde*.
pandas e polars convertem em memória a cada leitura; aqui convertemos uma vez em
disco e reaproveitamos, invalidando pelo sha256 da origem.

A alternativa de carregar tudo como `latin-1` e corrigir os caracteres em SQL foi
descartada: exigiria aplicar a correção coluna a coluna, e esquecer uma seria
corrupção invisível.

**Por que DuckDB e não pandas ou polars.** Medido na leitura completa do
`cno.csv` (884 MB, 3,6 M linhas), cada abordagem em processo isolado:

| | tempo | pico de RAM |
|---|---|---|
| DuckDB no UTF-8 | **0,8s** | **457 MB** |
| Polars `windows-1252` | 4,3s | 2.641 MB |
| pandas `cp1252` | 19,6s | 4.031 MB |

Polars lê cp1252 nativamente, o que eliminaria o passo de conversão — mas só na
API eager: `scan_csv` aceita apenas `utf8`, então a execução lazy fica
indisponível e a tabela inteira precisa caber na memória. Como o pipeline vai
rodar em worker de orquestrador com memória limitada, 457 MB contra 2,6 GB
decide a escolha.

Vale registrar que o DuckDB é também o mais rigoroso dos três: ele **recusa** um
arquivo declarado como `latin-1` que contenha bytes da faixa C1. pandas e polars
aceitariam calados e produziriam caracteres de controle. Foi essa recusa que
revelou o encoding real da base.

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

### Validação

**Reconciliação contra a fonte.** O `cno_totais.csv` publica as contagens
oficiais de cada tabela, e a validação as confronta com o que foi carregado.
É a única checagem que olha para fora do pipeline: todas as outras comparam o
dado com regras que nós mesmos escrevemos e, por isso, não detectariam uma
extração que perdeu metade do arquivo.

A comparação usa a contagem **antes** da deduplicação, porque é isso que a
Receita conta — confrontar o número pós-dedup acusaria divergência justamente
onde o pipeline funcionou.

**Cada regra é um SELECT do que está errado.** Conjunto vazio significa regra
cumprida; o executor conta, amostra exemplos e decide o código de saída.
Acrescentar uma regra é escrever uma consulta, sem tocar em mecânica nenhuma.

**Erro reprova, aviso não.** `ERRO` é violação de contrato — chave duplicada,
órfão, valor fora de domínio — e derruba a execução. `AVISO` é sujeira conhecida
da fonte que queremos medir e acompanhar. Marcar tudo como erro tornaria a
validação inútil, já que um cadastro público de 3,6 milhões de registros sempre
tem sujeira; marcar tudo como aviso a tornaria decorativa.

**Regra que não roda falha alto.** Se o SQL de uma regra quebrar, a validação
levanta erro em vez de contabilizar zero violações — o modo de falha mais
perigoso seria uma regra silenciosamente não avaliada passando por aprovada.

Resultado no snapshot atual: reconciliação exata nas quatro tabelas, 17 das 19
regras cumpridas, 2 avisos (323 áreas implausíveis e 2 obras sem UF).

### Orquestração

**A DAG é fina de propósito.** Ela encadeia os mesmos comandos que se roda na
mão e não contém regra de negócio nenhuma. Isso mantém a lógica testável fora do
Airflow — os 65 testes das etapas rodam sem subir scheduler — e faz com que
reproduzir uma falha de produção seja copiar e colar um comando do log.

**O pipeline é invocado como subprocesso, não importado.** Os dois pacotes até
convivem no mesmo ambiente (`pip check` passa limpo), mas a fronteira de
processo dá o que a de import não dá: o pipeline pode ser atualizado sem
reinstalar o Airflow, e a etapa que falha devolve um código de saída em vez de
uma exceção que a DAG teria de saber interpretar. O contrato entre os dois é a
linha de comando e um JSON.

**Não há sensor de novidade, e é deliberado.** A tentação seria um
`ShortCircuitOperator` checando o ETag antes de baixar — mas o `cno extract` já
faz exatamente isso e responde em menos de um segundo quando não há publicação
nova. Um gate na DAG duplicaria a regra em dois lugares e criaria o risco de
pular etapas a jusante que ainda não rodaram. A idempotência vive nas etapas.

**Retry só onde ele ajuda.** `extract` tem 3 tentativas com backoff exponencial,
porque depende de rede e o download é resumível — a retentativa continua de onde
parou. `transform` e `validate` são determinísticos: se falharam, falharão de
novo, e retentar só multiplicaria o mesmo erro no log.

**O `snapshot_id` viaja entre as etapas.** A extração devolve qual snapshot
processou e as etapas seguintes o recebem, em vez de cada uma resolver "o mais
recente" sozinha — assim uma publicação da Receita no meio da execução não faz a
DAG misturar dois snapshots.

### Curadoria

**A staging é fiel à origem e é isso que a impede de responder perguntas.** Ela
tem quatro tabelas e uma linha por registro publicado — ótimo para auditar,
inútil para perguntar "quantos m² Joinville construiu em 2023". A camada curada
toma as decisões que a fonte não toma, e as toma num lugar só, explicitamente.

**`area_m2` só existe quando a unidade é metro quadrado.** A base mistura
unidades no mesmo campo: 3.404.652 obras em m², mas 21.328 em km, 14.539 em m³,
3.580 em kW e 156.712 em "Outra" — são dutos, rodovias, subestações. Somar a
coluna crua dá 49.286 km² de área construída no Brasil; somando só o que é metro
quadrado dá 2.839 km². **Fator de 17 entre o número certo e o errado**, e o
errado é o que sai de um `SUM(area_total)` desavisado. A área declarada continua
na tabela ao lado da unidade; o que muda é que existe uma coluna segura de somar.

**A geocodificação não usa serviço externo, e recupera mais do que parecia.** O
`Código de localização` é Plus Code em parte da base, mas só 36,4% dos registros
trazem um código completo. Outros 6,2% vêm na forma curta (`RF8J+VH`), a que
faltam os 4 caracteres do bloco de 1° — e a recuperação desses normalmente exige
um centroide municipal, ou seja, dado externo. Aqui a âncora sai da própria base:
a **mediana dos pontos já decodificados do mesmo município**. Isso cobre 226.854
dos 227.074 códigos curtos, e 5.516 dos 5.572 municípios têm âncora própria.

**Um Plus Code pode ser válido e estar errado, e 3,7% estão.** Medidos 48.436
pontos que decodificam perfeitamente e caem a mais de 150 km do município
declarado — 39 mil deles a mais de 500 km, alguns no Japão. Por isso a tabela
grava `geo_distancia_municipio_km` e `geo_plausivel`, e os marts contam só o
ponto plausível. A coordenada crua fica gravada para auditoria, como
`area_suspeita` faz na staging: marcar, não apagar. **A cobertura honesta é
41,2%**, não os 42,5% brutos nem os 59% que "contém um `+`" sugeririam.

**O recorte setorial é por divisão da CNAE, não por seção.** O CNO é cadastro de
obra: 100% da base cai na seção F, então agrupar por seção daria uma linha só. As
três divisões que ocorrem são 41 Construção de edifícios (1,9 M), 43 Serviços
especializados (1,4 M) e 42 Obras de infraestrutura (283 mil) — e é aí que a
diferença aparece: infraestrutura é 7% das obras e 29% dos metros quadrados.

**Os marts existem por causa do dashboard.** Um Streamlit não pode varrer 3,6 M
de linhas a cada clique num filtro. As três tabelas agregadas têm de 12 mil a 133
mil linhas, respondem instantaneamente e carregam as mesmas definições da tabela
analítica — o app não recalcula regra de negócio, que é o que impede o dashboard
e o notebook de divergirem com o tempo. Há um teste que confere que os três marts
somam exatamente o mesmo que `obras_analitico`.

**A curadoria roda depois da validação.** É ela que alimenta gráfico e relatório,
e publicar número em cima de dado reprovado é pior do que não publicar número
nenhum. Como a validação derruba a execução quando reprova, chegar na curadoria
já significa que a camada tratada reconcilia com a fonte.

**Dado externo não entra aqui.** População, PIB e malha municipal ficam na camada
de análise, fora do pipeline. O pipeline reconcilia contra a fonte, e um dado que
a fonte não publica não tem como ser reconciliado; além disso, misturar safras
(snapshot de 2026, população de 2022) dentro da mesma linha é o tipo de erro que
não dá sintoma. Se um dia precisar entrar, a forma é uma dimensão `municipios`
separada, nunca colunas na tabela de obras.

### Fronteira de dados externos

**O pipeline processa uma fonte só, e isso é uma decisão, não uma limitação.**
Toda a camada curada é derivável do snapshot do CNO e reconciliável contra os
totais que a própria Receita publica. No momento em que uma coluna de
`obras_analitico` viesse de outra fonte, com outra data de referência, a frase
"esta camada reconcilia com a fonte" deixaria de ser verdadeira para a tabela.

Município, população e malha do IBGE entram na **camada de análise**, e os
motivos, em ordem de peso:

**Acoplamento de falha.** Como task da DAG, uma indisponibilidade do IBGE
derrubaria o pipeline do CNO — que não usa o IBGE para nada. Seria deixar um
terceiro que não contribui para o produto principal poder quebrá-lo.

**Cadências incompatíveis.** A DAG roda diariamente; o IBGE publica uma vez por
ano. Seriam 365 buscas do mesmo arquivo, ou lógica condicional para evitá-las —
complexidade para benefício zero.

**Assimetria de custo.** Como tabela separada, trocar a safra da população é
trocar um arquivo. Como coluna na tabela de obras, é reprocessar 3,6 M de linhas
para mudar um dado que nem veio da Receita.

**O resultado não é processo rodando por fora — é tabela de referência
versionada.** A mesma categoria dos nomes das seções da CNAE, que são constantes
em `dominios.py` e ninguém espera que sejam buscados da CONCLA toda noite. O
script ao lado existe para regerar quando vencer, e a DAG `referencias_ibge`
avisa quando esse momento chega.

**A junção é por nome normalizado, não por código.** A Receita usa TOM de 4
dígitos, o IBGE usa código de 7, e a de-para entre os dois não tem fonte
canônica estável. Medido na base real: normalizar (maiúscula, sem acento, sem
hífen e apóstrofo) casa **5.555 de 5.572 (99,7%)**. Os 17 restantes são o
conjunto clássico — `PARATI`/`Paraty`, `SANTANA DO LIVRAMENTO`/`Sant'Ana do
Livramento`, `BOA SAÚDE`/`Januário Cicco` — e viram uma tabela de correção
auditável linha a linha, com o motivo de cada uma. Importar a tabela TOM de
5.570 linhas de um terceiro não evitaria esse trabalho: só o esconderia num
arquivo que não dá para revisar. **Não se evita a de-para; escolhe-se o tamanho
dela.**

Com as correções, o casamento é de **5.570 de 5.570**. E o efeito no resultado é
o esperado: em SC, o ranking por obras por mil habitantes não tem nenhum dos
municípios do topo absoluto — aparecem Itapoá (58,0), Maravilha (49,4) e
Balneário Piçarras (48,3), separando litoral de Oeste. Sem denominador, todo
ranking municipal é um ranking populacional disfarçado.

### Containerização

**Uma imagem só, com dois ambientes Python dentro.** O Airflow vem da imagem
oficial e o pipeline é instalado num venv separado, em `/opt/cno/.venv`, que a
DAG invoca pelo caminho absoluto em `CNO_BIN`. Poderiam dividir o mesmo
ambiente — `pip check` passa limpo com os dois juntos —, mas aí toda subida de
versão do `requests` ou do `urllib3` no pipeline passaria pelo resolvedor de
dependências do Airflow, que fixa versões por necessidade. Dois venvs custam
uns poucos MB e removem esse acoplamento; a fronteira entre eles continua sendo
a mesma que já existia em desenvolvimento, a linha de comando.

**A DAG vai embutida na imagem, não montada do host.** Bind mount de `./dags`
dá edição ao vivo, mas traz o problema de UID do compose oficial (arquivos
criados como root no host) e abre a janela em que scheduler e dag-processor leem
versões diferentes do arquivo. Como o container aqui é entrega e não ambiente de
desenvolvimento, embutir sai mais barato: `docker compose up` funciona a partir
de um clone recém-feito, sem nenhum passo de preparação. Mexer na DAG pede um
`make build`.

**O volume de dados é criado na imagem, com dono `airflow`.** Um volume nomeado
herda dono e permissão do diretório que existe na imagem sob o ponto de
montagem. Criar `/opt/cno/data` já com o dono certo no `Dockerfile` é o que
dispensa a variável `AIRFLOW_UID` e o passo de `chown -R` que o compose oficial
precisa executar como root antes de tudo.

**LocalExecutor, não Celery.** O compose oficial monta Redis, worker e Flower
para dar execução distribuída. Esta DAG tem três tasks em linha reta, e o
gargalo é I/O de rede e disco num processo só — uma fila distribuída
acrescentaria dois serviços e nenhum paralelismo aproveitável. Pelo mesmo
critério ficou de fora o triggerer: nenhuma task aqui é deferrable. São cinco
serviços, cada um com motivo.

**No container, o pipeline não guarda os intermediários.** `CNO_MANTER_ZIP=0` e
`CNO_MANTER_INTERMEDIARIOS=0` economizam ~1,7 GB por snapshot. O que eles
aceleram é o reprocessamento do mesmo snapshot, que é raro; a idempotência não
depende deles, porque a extração confere os CSVs contra o manifesto, não o zip.

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
- [x] Funções de validação, com reconciliação contra os totais oficiais
- [x] Orquestração em DAG
- [x] Camada curada, com geocodificação e marts
- [x] Tabela de referência do IBGE, com validade vigiada por DAG
- [x] Containerização
- [ ] Análise descritiva
