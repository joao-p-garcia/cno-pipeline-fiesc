# cno-pipeline-fiesc · branch `cloud/azure`

Pipeline de extração e tratamento da base do **CNO (Cadastro Nacional de Obras)**
da Receita Federal, com análise descritiva sobre a camada tratada. São 3,6
milhões de obras e 12,5 M de linhas somando as quatro tabelas.

Esta branch é a versão em produção na **Azure**. O código do pipeline, da análise
e do dashboard é o mesmo da `main`; muda onde e como ele roda. A versão local, com
Airflow e Docker Compose, está na branch [`main`](https://github.com/joao-p-garcia/cno-pipeline-fiesc/tree/main).

---

## Como roda na nuvem

```
   push na cloud/azure
        │
        ▼
   GitHub Actions ──▶ docker build ──▶ Azure Container Registry
        (login por OIDC)                      │
                          ┌───────────────────┴───────────────────┐
                          ▼                                       ▼
               Container Apps Job                       Container App
               cron diário, 09:00 UTC                   dashboard Streamlit
               2 vCPU / 4 GiB                           0,5 vCPU / 1 GiB
                          │                                       ▲
                          │ restaura o raw, roda as quatro        │ baixa a camada
                          │ etapas, publica as camadas            │ curated no início
                          ▼                                       │
                       ADLS Gen2 (data lake): raw/ · staging/ · curated/
```

1. **Job diário.** Às 09:00 UTC (06:00 em Brasília) o Container Apps Job sobe um
   contêiner, restaura o `raw` do lake e roda `cno extract`, `cno transform`,
   `cno validate` e `cno curate`, na mesma ordem da DAG da `main`. No fim,
   publica `raw/`, `staging/` e `curated/` no lake. Se a Receita não publicou
   nada novo, o `extract` reconhece pelo ETag e não baixa de novo.
2. **Dashboard.** Um Container App com endereço público. Ao iniciar, baixa a
   camada `curated` do lake (191 MB) e sobe o Streamlit. Fica com zero réplicas
   quando ninguém acessa, então o primeiro acesso demora alguns segundos.
3. **Histórico.** Os snapshots antigos não são apagados do lake.

### Por que um job agendado e não Airflow

O pipeline roda cerca de 6,5 minutos por dia. Na `main`, o Airflow ocupa cinco
contêineres (scheduler, api-server, dag-processor, init e Postgres) ligados o
tempo todo, o que é adequado localmente, onde não há custo. Na nuvem:

| Opção | Por que não foi usada |
|---|---|
| Airflow gerenciado (Data Factory) | roda 24 horas num nó dedicado, com custo de centenas de dólares por mês para 6,5 min de trabalho diário |
| Azure Functions | limite de 1,5 GB de memória e 10 minutos; o `transform` usa 4 GB |
| **Container Apps Job** (escolhido) | só cobra enquanto roda e tem cron próprio |

O que se perde em relação ao Airflow: o retry por etapa (o job inteiro tenta mais
uma vez) e a visualização da DAG. Como cada etapa é idempotente, repetir o job
inteiro não duplica dados. O detalhamento está em [nuvem/PLANO.md](nuvem/PLANO.md).

---

## Diferenças para a `main`

| | `main` | `cloud/azure` |
|---|---|---|
| Onde roda | local, com `docker compose up` | Azure (Brazil South) |
| Orquestração | Airflow 3.3.2 (LocalExecutor + Postgres) | Container Apps Job |
| Agendamento | DAG diária, 04:00 UTC | cron do job, 09:00 UTC |
| Retentativa | por etapa (a extração tenta 3 vezes) | o job inteiro tenta mais 1 vez |
| Armazenamento | volume Docker local | ADLS Gen2 |
| Imagem | `apache/airflow` + venv do pipeline (3,88 GB) | `python:3.12-slim` + azcopy (231 MB) |
| Dashboard | contêiner local, porta 8501 | Container App público |
| Validade da tabela do IBGE | DAG mensal `referencias_ibge` | sem verificação automática |
| CI | lint e testes a cada push e PR | as mudanças de código passam pelo CI na `main` e chegam aqui por merge |
| CD | não tem | build e deploy a cada push |
| Infraestrutura | `Dockerfile` + `docker-compose.yml` | Terraform, com estado remoto |
| Credenciais | não se aplica | identidades gerenciadas e OIDC, sem segredo no repositório |
| Custo | zero | US$ 5 a 10 por mês, com alerta de orçamento |

---

## CI/CD

**CI** (`.github/workflows/ci.yml`). Em push na `main` e em pull requests, roda
`make lint` e `make test` em Python 3.11 e 3.12, e um job separado instala o
Airflow 3.3.2 para os testes das DAGs. Nenhum teste acessa a rede.

**CD** (`.github/workflows/nuvem.yml`). A cada push na `cloud/azure`:

1. confere se as Variables do repositório estão preenchidas;
2. faz login na Azure por OIDC, sem senha ou chave guardada no GitHub;
3. constrói a imagem no runner (o ACR Tasks está bloqueado nesta assinatura) e
   envia ao registry com a tag do commit e `latest`;
4. aponta o job e o dashboard para a imagem nova.

O CD publica a imagem; a próxima execução do job e o próximo início do dashboard
já usam a versão nova.

---

## Infraestrutura

Tudo em `nuvem/terraform/`, com o estado guardado num storage account criado por
`nuvem/bootstrap.sh`.

| Recurso | Função |
|---|---|
| Container Registry (Basic) | guarda a imagem |
| Container Apps Job | roda o pipeline |
| Container App | serve o dashboard |
| Storage ADLS Gen2 | o data lake, com as três camadas |
| Log Analytics | logs do job e do dashboard, com cota diária |
| 3 identidades gerenciadas | o job escreve no lake, o dashboard só lê, o GitHub faz deploy |
| Alerta de orçamento | avisa em 50% do teto e na previsão de estourar o mês |

Para recriar em outra conta: copiar `nuvem/terraform/exemplo.tfvars` para
`terraform.tfvars`, preencher, rodar `sh nuvem/bootstrap.sh` e depois
`terraform init` e `terraform apply` em `nuvem/terraform/`.

---

## O pipeline

Igual ao da `main`. Na nuvem, as camadas são publicadas no lake ao fim de cada
execução.

```
        Receita Federal (.zip, 315 MB)
                 │
   extract  ─────┤  HTTP com ETag, download resumível, sha256 por arquivo
                 ▼
            raw/          o zip e os CSVs originais, por snapshot
                 │
   transform ────┤  cp1252 → UTF-8, tipos, duplicatas, datas inválidas
                 ▼
            staging/      parquet tipado, particionado por snapshot
                 │
   validate  ────┤  19 regras + reconciliação com os totais da fonte
                 ▼
   curate    ────┤  uma linha por obra, geocodificação, 3 marts
                 ▼
            curated/  ──▶  notebook + dashboard
```

| | |
|---|---|
| **DuckDB** | processamento em SQL sobre parquet |
| **Parquet** | formato das camadas staging e curated |
| **Streamlit + Altair** | dashboard |
| **pytest + ruff** | 273 testes offline, mais 15 das DAGs, lint e formatação |

Python 3.11+, empacotado como CLI (`cno`). As decisões de cada etapa, com as
medições, estão em [ARQUITETURA.md](ARQUITETURA.md).

### Fontes

| Fonte | O quê | Atualização |
|---|---|---|
| CNO, Receita Federal | 3,6 M de obras | diária, pelo job |
| IBGE | municípios, região, população e malha | anual, tabela versionada em `analise/` |

A tabela do IBGE fica fora do pipeline e é regerada com
`python analise/construir_municipios.py`. Ela vale até 19/09/2027. Nesta branch
não há verificação automática da validade; `python analise/construir_municipios.py --verificar`
faz a checagem manualmente.

---

## Rodar localmente

Os arquivos da versão local continuam nesta branch. Com Docker:

```
docker compose up -d --build
```

Sobe o Airflow em <http://localhost:8080> (`airflow` / `airflow`) e o dashboard em
<http://localhost:8501>. A primeira execução leva cerca de 6,5 minutos.

Sem Docker, com Python 3.11+:

```
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev,dashboard]"
cno extract && cno transform && cno validate && cno curate
streamlit run app/dashboard.py
```

Instruções completas no README da [`main`](https://github.com/joao-p-garcia/cno-pipeline-fiesc/tree/main).

---

## Estrutura

```
src/cno_pipeline/     o pipeline: extract, transform, validate, curate
dags/                 as DAGs do Airflow (usadas na versão local)
analise/              consultas, estilo, malha, tabela do IBGE e o notebook
app/                  o dashboard (Streamlit), uma seção por arquivo
tests/                testes offline
nuvem/
├── Dockerfile        imagem da nuvem, sem Airflow
├── entrypoint-job.sh       restaura o raw, roda o pipeline, publica no lake
├── entrypoint-dashboard.sh baixa a curated e sobe o Streamlit
├── bootstrap.sh      cria o storage do estado do Terraform
├── terraform/        a infraestrutura
└── PLANO.md          o plano e as decisões da migração
```

---

## Limitações

- O CNO mede o cadastro de obras, não o setor da construção.
- 58,8% das obras não têm ponto no mapa.
- A área é declarada pelo contribuinte e não tem fonte externa para conferir.
- A população é de 2026 e as obras são de todos os anos, então a taxa por mil
  habitantes compara municípios entre si, não serve como série histórica.
- Nesta branch, a validade da tabela do IBGE não é verificada automaticamente.
