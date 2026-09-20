# cno-pipeline-fiesc

Pipeline de extração e tratamento da base do **CNO — Cadastro Nacional de Obras**
da Receita Federal, com análise descritiva em cima da camada tratada.

Do `.zip` publicado pela Receita até um dashboard narrativo, sem download manual
e sem passo manual nenhum no meio. **3,6 milhões de obras**, 12,5 M de linhas
somando as quatro tabelas.

---

## Rodar

Caso seu sistema operacional não seja Linux, recomendo usar Docker Desktop.

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

Precisa de Python 3.11+. O `cno` é o mesmo executável que a DAG invoca, então
esta via roda exatamente as mesmas quatro etapas:

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

Em Linux e WSL2, `make pipeline` encadeia as quatro e `make dashboard` sobe o
app. Esta via nativa foi exercitada em Linux e WSL2; **no Windows, prefira o
Docker** — os alvos do Makefile assumem o layout POSIX do venv (`.venv/bin`).

`cno extract` é idempotente: se o ETag da fonte bate com o do manifesto local e
os arquivos conferem, não baixa nada. `cno validate` sai com código 1 se houver
divergência — é o que faz a task falhar no orquestrador.

**Configuração** é opcional: sem nada, o pipeline usa `./data`. Para mudar, copie
`.env.exemplo` para `.env`. A variável que mais importa é `CNO_DATA_DIR`, útil em
WSL para manter os 1,4 GB fora de `/mnt/c`.

### Testes

| O que roda | Linux / WSL | Windows (sem `make`) |
|---|---|---|
| a suíte: 233 testes, offline, em segundos | `make test` | `pytest` |
| estilo e erros estáticos | `make lint` | `ruff check src tests dags analise app` |
| 15 testes das DAGs | `make test-dag` | exige o venv do Airflow — veja abaixo |

As duas colunas rodam a mesma coisa: os alvos do Makefile são atalhos para os
comandos da direita.

Nenhum teste toca a rede: eles montam camada sintética e, quando precisam de
HTTP, sobem um servidor local. O CI roda os três a cada push, em Python 3.11 e
3.12.

Para as DAGs, o Airflow vive num venv separado porque suas pinagens conflitam
com as do pipeline:

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
| **CNO — Receita Federal** | a base do desafio: 3,6 M de obras | extração **diária**, 04:00 (`cno_pipeline`) |
| **IBGE** | municípios, UF, região, população e malha | safra **anual**; fora do pipeline |

A do desafio é a primeira. A segunda eu acrescentei para poder agregar por
município e comparar por porte — e ela fica **fora do pipeline** de propósito:
é tabela de referência versionada no repositório, não dado que a esteira busca.
Como muda uma vez por ano, o que existe é vigilância: a DAG `referencias_ibge`
roda mensalmente, não acessa a rede e **falha quando a safra vence**.

A extração diária do CNO é idempotente: se o ETag da fonte não mudou, não baixa
nada.

---

## Stack

| | |
|---|---|
| **DuckDB** | todo o processamento — transform, validate e curate, em SQL sobre parquet |
| **Parquet** | formato das camadas staging e curated, particionado por snapshot |
| **Airflow 3.3.2** | orquestração: duas DAGs, LocalExecutor sobre Postgres |
| **Docker Compose** | a entrega: seis serviços, um comando |
| **Streamlit + Altair** | o dashboard narrativo |
| **pytest + ruff** | 248 testes offline, lint e formatação |

Python 3.11+, empacotado como CLI (`cno`). Sem Spark, sem data warehouse: os
12,5 M de linhas cabem com folga no DuckDB de uma máquina só — o porquê está no
[ARQUITETURA.md](ARQUITETURA.md).

---

## CI/CD

**CI**, hoje: a cada push e a cada PR, o GitHub Actions roda lint e a suíte em
Python 3.11 e 3.12, e num job separado sobe o Airflow 3.3.2 para os testes das
DAGs. Como nenhum teste toca a rede, a CI não depende de a Receita estar no ar.

**CD** ainda não existe — é o próximo passo. O caminho é publicar a imagem
`cno-pipeline` num registry a cada tag e aplicar a stack num ambiente
gerenciado; a parte difícil já está feita, porque a imagem é autossuficiente
(sem bind mount e sem dependência do host).

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
ficar vermelha sem afetar a esteira.

**Três camadas.** `raw` preserva o artefato original; `staging` é o parquet
tratado e validado; `curated` é o que a análise consome, com uma linha por obra
e três marts pré-agregados.

### A análise

```bash
make dashboard    # a entrega: oito seções, na ordem em que as decisões surgiram
make notebook     # o caminho: reexecuta analise/exploracao.ipynb com as saídas
```

O dashboard não é painel de filtros: é a história do que o dado ensinou sobre
como construir o sistema. Cada seção tem um gráfico que faz o argumento, um
bloco *o que eu vi → o que quebraria → o que mudei no sistema*, e só então os
controles para explorar.

| Seção | O achado |
|---|---|
| 1. O dado como ele chega | 315 MB em cp1252 — e ler com o encoding errado **não dá erro** |
| 2. As quatro tabelas | 1 linha por obra em `cno.csv`, N nas outras três — e a fonte publicando o próprio gabarito |
| 3. O nulo que não é dado faltante | 66% sem NI do responsável são pessoas físicas |
| 4. A soma que mente | `SUM(area_total)` erra por um fator de **312** |
| 5. O endereço vem em Plus Code | cobertura honesta de **41,2%**, não os 59% aparentes |
| 6. A série que triplica | o degrau de 2018-2019 é o cadastro entrando no ar |
| 7. Das tabelas às camadas | onde cada decisão das seções anteriores foi parar |
| 8. O que dá para afirmar | e, explicitamente, o que **não** dá |

O caderno (`analise/exploracao.ipynb`) está versionado **com as saídas**, para
ser lido sem ser executado.

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
| **A DAG é fina** | encadeia os mesmos comandos que se roda na mão; nenhuma regra de negócio mora nela — [detalhes](ARQUITETURA.md#orquestração) |
| **Trava por snapshot dentro da etapa** | duas execuções simultâneas corromperiam a partição **sem levantar erro**; a garantia não pode depender do orquestrador — [detalhes](ARQUITETURA.md#orquestração) |
| **Uma camada de consultas, dois consumidores** | o caderno e o app chamam as mesmas funções; nenhum dos dois escreve SQL — [detalhes](ARQUITETURA.md#análise-e-visualização) |

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
tests/                248 testes, todos offline
data/                 raw / staging / curated — gerado, nunca versionado
```

`analise/` traz também a tabela de referência do IBGE já gerada
(`municipios.csv`, a malha e as 17 correções de nome), então o dashboard
funciona num clone limpo sem buscar nada. Para regerá-la —
`python analise/construir_municipios.py`. Ela declara a própria validade, e a
DAG `referencias_ibge` falha quando a safra vence.

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
