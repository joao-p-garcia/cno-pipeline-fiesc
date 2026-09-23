# cno-pipeline-fiesc

Pipeline de extração e tratamento da base do **CNO (Cadastro Nacional de Obras)**
da Receita Federal, com análise descritiva em cima da camada tratada.

Do `.zip` publicado pela Receita até um dashboard narrativo, sem download manual
e sem passo manual nenhum no meio. **3,6 milhões de obras**, 12,5 M de linhas
somando as quatro tabelas.

---

## Rodar

Caso seu sistema operacional não seja Linux, recomendo usar Docker Desktop.
Pra rodar esse repositório basta apenas Docker, sem necessidade de instalar mais nada.
O Docker, por ser solução de container, garante que rode igual em qualquer ambiente.

| Sua máquina | Comando |
|---|---|
| **Windows** + Docker Desktop | `docker compose up -d --build` (PowerShell) |
| **macOS** + Docker Desktop | `docker compose up -d --build` |
| **Linux** ou **WSL2** + Docker | `make up`, ou o mesmo `docker compose up -d --build` |
| qualquer sistema, sem Docker | [Sem Docker](#sem-docker), abaixo |

`make` : tem uma Makefile, mas Make não funciona no Windows. Se estiver no Linux, pode usar pra facilitar.

### Com Docker

```
docker compose up -d --build
```

Sobe Airflow 3.3.2 + Postgres + o dashboard, e a DAG **começa a rodar sozinha**:
baixa os ~315 MB, trata, valida e cura. Primeira execução ~6,5 min.
Acompanhe o funcionamento nos localhost abaixo:

| Onde | O quê |
|---|---|
| <http://localhost:8080> | Airflow (`airflow` / `airflow`) |
| <http://localhost:8501> | o dashboard da análise |

```
docker compose logs -f             # acompanhar a primeira execução
docker compose down                # derruba, preservando os dados
docker compose down --volumes      # derruba e apaga os volumes também
```

Equivalentes no Makefile, para quem está em Linux ou WSL2: `make logs`,
`make down`, `make down-tudo`, `make dag-run`.

**Se `docker` não for reconhecido:** no Windows, isso significa que falta o
Docker Desktop (ou você esqueceu de abrir), ou que o Docker está instalado só dentro de uma distro WSL, e
nesse caso os comandos acima precisam ser dados de dentro do WSL. Numa distro
WSL com engine nativo, o daemon costuma começar parado: `sudo systemctl start
docker` antes de subir a stack.

### Sem Docker

Precisa de Python 3.11+. O `cno` é o mesmo executável que a DAG invoca, ou seja,
montei o código de forma que não necessita do Airflow necessariamente. Então
esta via roda exatamente as mesmas etapas:

```
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev,dashboard]"

cno info        # compara com a fonte sem baixar nada (só um HEAD)
cno extract     # camada raw (~315 MB comprimidos, 1,4 GB extraídos)
cno transform   # camada staging em parquet tipado e particionado  (~20s)
cno validate    # 19 regras + reconciliação com os totais da Receita (~6s)
cno curate      # camada curada: tabela analítica e três marts      (~35s)

streamlit run app/dashboard.py                        # http://localhost:8501
```

Em Linux e WSL2, `make pipeline` encadeia a pipeline e `make dashboard` sobe o
app. Esta via nativa foi exercitada em Linux e WSL2; **no Windows, prefira o
Docker**,  os alvos do Makefile assumem o layout POSIX do venv (`.venv/bin`).

`cno extract` é idempotente, se o ETag da fonte bate com o do manifesto local e
os arquivos conferem, não baixa nada. `cno validate` sai com código 1 se houver
divergência e falha a DAG.

**Configuração** é opcional, sem nada o pipeline usa `./data`. Para mudar, copie
`.env.exemplo` para `.env`. A variável que mais importa é `CNO_DATA_DIR`, útil em
WSL para manter os 1,4 GB fora de `/mnt/c`.

### Testes

| O que roda | Linux / WSL | Windows (sem `make`) |
|---|---|---|
| cobertura de testes: 272 testes offline | `make test` | `pytest` |
| estilo e erros estáticos | `make lint` | `ruff check src tests dags analise app` |
| 15 testes das DAGs | `make test-dag` | exige o venv do Airflow |

Os testes montam camada sintética e, quando precisam de
HTTP, sobem um servidor local, sem contato com a rede em si. O CI roda os três a cada push, em Python 3.11 e
3.12.

Para as DAGs, o Airflow tem venv própria, porque as bibliotecas podem conflitar com a pipeline.
Porém se você rodar direto no Docker, não precisa disso.

```bash
python3 -m venv ~/.venvs/airflow
~/.venvs/airflow/bin/pip install "apache-airflow==3.3.2" \
  --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt
AIRFLOW_HOME=~/airflow ~/.venvs/airflow/bin/airflow db migrate
```

---

## Fontes

| Fonte | O quê | Frequência |
|---|---|---|
| **CNO — Receita Federal** | dados de 3,6 M obras | extração **diária**, 04:00 (`cno_pipeline`) |
| **IBGE** | municípios, UF, região, população e malha | extração **anual**; por fora do pipeline |

Acrescentei os dados do IBGE para poder agregar por 
município e comparar por porte. Deixei ela de **fora do pipeline** como uma 
tabela de referência versionada no repositório. A DAG `referencias_ibge`
roda mensalmente para verificar se o dado versionado atual do IBGE ainda está válido. 
Não acessa a rede e **falha quando esses dados vencem**. Existe um script
no código `construir_municipios.py` para extrair esses dados do IBGE de novo.

A extração diária do CNO é idempotente, se o ETag da fonte não mudou, não baixa de novo.

---

## Stack

| | |
|---|---|
| **DuckDB** | todo o processamento, transform, validate e curate, em SQL sobre parquet |
| **Parquet** | formato das camadas staging e curated, particionado por snapshot |
| **Airflow 3.3.2** | orquestração, duas DAGs, LocalExecutor sobre Postgres |
| **Docker Compose** | para abrir a entrega em qualquer ambiente |
| **Streamlit + Altair** | analise exploratória em formato de dash interativo |
| **pytest + ruff** | 272 testes offline, lint e formatação |

Python 3.11+, empacotado como CLI (`cno`). Sem Spark, sem data warehouse, os
12,5 M de linhas cabem com folga no DuckDB de uma máquina só. Ler mais em
[ARQUITETURA.md](ARQUITETURA.md).

---

## CI/CD

**CI**, hoje: a cada push e a cada PR, o GitHub Actions roda lint e a suíte em
Python 3.11 e 3.12, e num job separado sobe o Airflow 3.3.2 para os testes das
DAGs. Como nenhum teste toca a rede, a CI não depende de a Receita estar no ar.

**CD** ainda não existe nessa branch. O caminho é publicar a imagem
`cno-pipeline` num registry a cada tag e aplicar a stack num ambiente
gerenciado, porque a imagem é autossuficiente
(sem bind mount e sem dependência do host). A decisão é ser uma DAG 
entregável e que funcione num computador localmente. 

---

## O que a solução faz

```
        Receita Federal (.zip, 315 MB)
                 │
   extract  ─────┤  HTTP com ETag, download resumível, sha256 por arquivo
                 ▼
            data/raw/          o zip e os CSVs originais, por snapshot
                 │
   transform ────┤  cp1252 → UTF-8, tipos, duplicatas, sentinelas de data
                 ▼
            data/staging/      parquet tipado, particionado por snapshot
                 │
   validate  ────┤  19 regras + reconciliação contra os totais da fonte
                 ▼
   curate    ────┤  uma linha por obra, geocodificação, 3 marts
                 ▼
            data/curated/  ──▶  notebook  +  dashboard
```

**Duas DAGs.** `cno_pipeline` encadeia as quatro etapas, diariamente.
`referencias_ibge` é separada e só vigia a validade da tabela do IBGE — pode
ficar vermelha sem afetar o pipeline.

**Três camadas.** `raw` com os dados originais, `staging` com tratamentos
iniciais, remoções de duplicatas e tratamento de colunas, e `curated` 
possui agregações e transformações voltadas para a análise.

### A análise

```bash
make dashboard    # dez seções, na ordem em que as decisões surgiram
make notebook     # reexecuta analise/exploracao.ipynb com as saídas
```
O notebook (`analise/exploracao.ipynb`) é uma organização dos testes, 
exploração dos dados inicial e para a construção do dashboard em si, e 
está versionado **com as saídas**, para ser lido sem ser executado.

O dashboard é um Streamlit que já contém uma apresentação com tomadas 
de decisão, arquitetura e conclusões.

---

## Decisões técnicas

O porquê de cada uma, com as medições, está em **[ARQUITETURA.md](ARQUITETURA.md)**.
Em resumo:

| Decisão | Por quê, em uma linha |
|---|---|
| **DuckDB**, não pandas | 3,6 M de linhas cabem com folga e ele escreve parquet particionado nativamente — [detalhes](ARQUITETURA.md#tratamento) |
| **cp1252**, não latin-1 | 4.881 bytes na faixa C1; latin-1 decodifica todos **sem erro**, e o defeito só aparece no relatório — [detalhes](ARQUITETURA.md#tratamento) |
| Nulo do responsável **não é imputado** | 66,39% de ausência é pessoa física, não lacuna; virou `responsavel_tipo` — [detalhes](ARQUITETURA.md#tratamento) |
| Área implausível é **marcada, não excluída** | quem plota filtra, quem investiga tem o caso — [detalhes](ARQUITETURA.md#curadoria) |
| `area_m2` só existe em m² e sem suspeita | dois defeitos independentes; cada filtro sozinho ainda erra por uma ordem de grandeza — [detalhes](ARQUITETURA.md#curadoria) |
| Geocodificação **offline**, via Plus Code | 2,1 M de registros, sem serviço pago; 3,7% são válidos e apontam errado, daí `geo_plausivel` — [detalhes](ARQUITETURA.md#curadoria) |
| Série comparável **a partir de 2019** | o CNO não existia antes de nov/2018: o passado é subcontado e instável entre snapshots — [detalhes](ARQUITETURA.md#curadoria) |
| **Validação derruba a execução** | publicar número sobre dado reprovado é pior que não publicar — [detalhes](ARQUITETURA.md#validação) |
| **IBGE fica fora do pipeline** | o pipeline processa uma fonte só e reconcilia contra ela; o IBGE entra como tabela de referência versionada, com validade vigiada por DAG — [detalhes](ARQUITETURA.md#fronteira-de-dados-externos) |
| **DAG é enxuta** | encadeia os mesmos comandos que se roda na mão; nenhuma regra de negócio mora nela — [detalhes](ARQUITETURA.md#orquestração) |
| **Trava por snapshot dentro da etapa** | duas execuções simultâneas corromperiam a partição **sem levantar erro**; a garantia não pode depender do orquestrador — [detalhes](ARQUITETURA.md#orquestração) |

---

## Estrutura

```
src/cno_pipeline/     o pipeline: extract, transform, validate, curate
├── config.py         parâmetros, todos sobrescrevíveis por variável de ambiente
├── bloqueio.py       trava por snapshot, para duas execuções não se atropelarem
├── extract/          HTTP resumível, descompactação validada, manifesto
├── transform/        contrato de dados, transcodificação, carga em parquet
├── validate/         19 regras + reconciliação com os totais da fonte
└── curate/           tabela analítica, geocodificação e os três marts

dags/                 cno_pipeline (as quatro etapas) e referencias_ibge
analise/              camada de análise: consultas, estilo, malha e o caderno
app/                  o dashboard narrativo (Streamlit), uma seção por arquivo
├── .streamlit/       o tema: as cores do chrome, que o `analise/estilo.py` espelha
└── static/fontes/    Montserrat e Open Sans, versionadas em vez de vir de CDN
tests/                272 testes offline, mais 15 das DAGs que pedem o Airflow
data/                 raw / staging / curated
```

`analise/` traz também a tabela de referência do IBGE já gerada
(`municipios.csv`, a malha e as 17 correções de nome), então o dashboard
funciona num clone limpo sem buscar nada. Para regerá-la, use
`python analise/construir_municipios.py`. Ela declara a própria validade, e a
DAG `referencias_ibge` falha quando esse dado está vencido.

---

## Limitações conhecidas

Declaradas de propósito, e também visíveis na seção 6 do dashboard:

- **O CNO mede o cadastro da construção, não o setor.** Serve para *onde há obra
  cadastrada*; não serve para PIB setorial.
- **58,8% das obras não têm ponto no mapa**, e a ausência não é aleatória. Todo
  mapa aqui é de um subconjunto.
- **A área é autodeclarada** e não há como validá-la contra nada externo.
- **A população é de 2026 e as obras são de todos os anos** — a taxa por mil
  habitantes compara municípios entre si, não serve como série histórica.
