# cno-pipeline-fiesc

Pipeline de extração e tratamento da base do **CNO — Cadastro Nacional de Obras**
da Receita Federal, com análise descritiva em cima da camada tratada.

Do `.zip` publicado pela Receita até um dashboard narrativo, sem download manual
e sem passo manual nenhum no meio. **3,6 milhões de obras**, 12,5 M de linhas
somando as quatro tabelas.

---

## Rodar

### Com Docker (não precisa de Python nem Airflow)

```bash
make up
```

Sobe Airflow 3.3.2 + Postgres + o dashboard, e a DAG **começa a rodar sozinha**:
baixa os ~315 MB, trata, valida e cura. Primeira execução ~6,5 min.

| Onde | O quê |
|---|---|
| <http://localhost:8080> | Airflow (`airflow` / `airflow`) |
| <http://localhost:8501> | o dashboard da análise |

`make down` derruba preservando os dados; `make down-tudo` apaga os volumes.

### Sem Docker

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,dashboard]"

make pipeline     # extract -> transform -> validate -> curate
make dashboard    # http://localhost:8501
```

Ou etapa por etapa, que é como a DAG as invoca:

```bash
cno info        # compara com a fonte sem baixar nada (só um HEAD)
cno extract     # camada raw (~315 MB comprimidos, 1,4 GB extraídos)
cno transform   # camada staging em parquet tipado e particionado  (~20s)
cno validate    # 19 regras + reconciliação com os totais da Receita (~6s)
cno curate      # camada curada: tabela analítica e três marts      (~35s)
```

`cno extract` é idempotente: se o ETag da fonte bate com o do manifesto local e
os arquivos conferem, não baixa nada. `cno validate` sai com código 1 se houver
divergência — é o que faz a task falhar no orquestrador.

**Configuração** é opcional: sem nada, o pipeline usa `./data`. Para mudar, copie
`.env.exemplo` para `.env`. A variável que mais importa é `CNO_DATA_DIR`, útil em
WSL para manter os 1,4 GB fora de `/mnt/c`.

### Testes

```bash
make test       # 233 testes, offline, em segundos
make test-dag   # 15 testes das DAGs (exige o venv do Airflow — veja abaixo)
make lint
```

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
make dashboard    # a entrega: seis seções, na ordem em que as decisões surgiram
make notebook     # o caminho: reexecuta analise/exploracao.ipynb com as saídas
```

O dashboard não é painel de filtros: é a história do que o dado ensinou sobre
como construir o sistema. Cada seção tem um gráfico que faz o argumento, um
bloco *o que eu vi → o que quebraria → o que mudei no sistema*, e só então os
controles para explorar.

| Seção | O achado |
|---|---|
| 1. O dado como ele chega | 315 MB, cp1252 — e a fonte publicando o próprio gabarito |
| 2. O nulo que não é dado faltante | 66% sem NI do responsável são pessoas físicas |
| 3. A soma que mente | `SUM(area_total)` erra por um fator de **312** |
| 4. O endereço vem em Plus Code | cobertura honesta de **41,2%**, não os 59% aparentes |
| 5. A série que triplica | o degrau de 2018-2019 é o cadastro entrando no ar |
| 6. O que dá para afirmar | e, explicitamente, o que **não** dá |

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
