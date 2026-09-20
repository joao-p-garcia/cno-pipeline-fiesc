# Plano — o mesmo pipeline rodando na Azure

Esta branch (`cloud/azure`) é uma trilha paralela: ela **não altera** o pipeline,
o dashboard, o README nem a apresentação. O objetivo é poder abrir o portal da
Azure no fim da apresentação e mostrar a mesma esteira rodando gerenciada, com a
camada curada num data lake.

A propriedade que torna isso barato: o pipeline já é um CLI configurado
inteiramente por variável de ambiente, sem estado fora de `CNO_DATA_DIR` e
idempotente por ETag. Nada disso precisa mudar para ir para a nuvem — e este
plano é construído em cima dessa restrição. **Se em algum momento for preciso
editar `src/cno_pipeline/`, o desenho está errado.**

---

## O que já está no ar (20/09/2026)

| | |
|---|---|
| Assinatura | `a473d0e0-3635-4fac-bf47-a55cc5cbd547` · tenant `b82ee7d5-…` |
| Região | `brazilsouth` |
| Grupos | `rg-cno-nuvem` (a esteira) · `rg-cno-tfstate` (o state) |
| Registry | `acrcnofiesc.azurecr.io` |
| Lake | `https://stcnolakefiesc.dfs.core.windows.net/lake/curated` |
| Dashboard | https://ca-cno-dashboard.agreeablecoast-cf9edb1a.brazilsouth.azurecontainerapps.io |
| Imagem | 231 MB (a da raiz, com Airflow, tem 3,88 GB) |

Terraform: 21 recursos, state remoto. Tudo em `nuvem/terraform/`.

**A única coisa que falta é manual e é sua:** cadastrar cinco *Variables*
(não Secrets) no repositório do GitHub, para o CD funcionar. Os valores saem de
`terraform output github_variaveis`.

---

## O desenho

```
   GitHub (push na cloud/azure)
        │
        │  OIDC, sem segredo guardado
        ▼
   GitHub Actions ──▶ docker build ──▶ ACR  (a imagem, construída no runner)
                                        │
                        ┌───────────────┴───────────────┐
                        ▼                               ▼
              Container Apps Job              Container App (dashboard)
              cron 09:00 UTC                  ingress público, :8501
              2 vCPU / 4 GiB                  0,5 vCPU / 1 GiB
              identidade: escrita             identidade: leitura
                        │                               ▲
                        │  extract→transform→           │  baixa 191 MB
                        │  validate→curate no           │  no boot
                        │  disco efêmero, depois        │
                        └──────▶  ADLS Gen2  ───────────┘
                                 curated/ + _manifests/
```

### O que substitui o quê

| Hoje (compose) | Azure | Nota |
|---|---|---|
| DAG Airflow + scheduler + api-server + dag-processor + Postgres | **Container Apps Job**, trigger cron | 5 serviços viram 1 recurso que escala a zero |
| volume `cno-dados` | **ADLS Gen2** (storage com HNS) | só o `curated/` sobe; raw e staging são efêmeros |
| `make build` na máquina | **ACR** + `docker build` no runner | é o "CD ainda não existe" do README, resolvido |
| serviço `dashboard` | **Container App** | mesma imagem, entrypoint diferente |
| `airflow-logs` | **Log Analytics** | histórico de execução visível no portal |

---

## Decisões, e por que elas

**Container Apps Job, e não Functions.** O plano Consumption do Functions dá
1,5 GB de memória e teto de 10 minutos. O `transform` sozinho pede 4 GB de
DuckDB e 4 GB de disco. Não cabe, e forçar caberia custaria reescrever a etapa.

**Container Apps Job, e não Managed Airflow.** O *Workflow Orchestration
Manager* do Data Factory é Airflow gerenciado de verdade, mas roda 24/7 num nó
dedicado — centenas de dólares por mês para orquestrar quatro tasks que ocupam
6,5 minutos por dia. O Airflow continua sendo a escolha certa *na entrega
local*, onde ele é grátis e mostra a DAG; na nuvem ele é desproporcional ao
trabalho.

O que se perde com o job único: o retry por task e a visualização de DAG. Se
valer a pena depois, um pipeline do Data Factory chamando o job quatro vezes
recupera as duas coisas — fica registrado como opcional, não como fase 1.

**O DuckDB não escreve no lake. O job escreve.** A tentação é apontar o `COPY`
para `abfss://` e acabar. Três motivos para não:

1. `Settings` é todo `Path` (`config.py`), e toda a hierarquia de camadas
   depende disso. Trocar por URI de object store espalha mudança por
   `transform/`, `curate/`, `validate/` e pela camada de análise.
2. Raw e staging são ~2,5 GB de escrita e releitura por execução. Mandar esse
   churn pela rede a cada rodada é pagar latência por dado que ninguém guarda.
3. A trava de concorrência é `flock` (`bloqueio.py`), que sobre mount SMB é
   terreno movediço — e ela existe porque uma sobreposição real já produziu
   partição pela metade *sem levantar exceção*. Não é a peça para experimentar.

Então: o job trabalha no disco efêmero, exatamente como faz hoje num volume, e
**publica só o `curated/` e os manifestos** no fim. 191 MB por dia.

**O dashboard baixa em vez de ler remoto.** São 191 MB de mesma região; leva
segundos no boot. A alternativa (extensão `azure` do DuckDB lendo `abfss://`
direto) funciona para leitura, mas põe latência de rede em cada consulta e
exige mexer na camada de dados do app. Baixando, `CNO_DATA_DIR` aponta para o
disco local e **`app/` e `analise/` não mudam uma linha.**

**Duas identidades, não uma.** A do job escreve no lake; a do dashboard só lê.
É a mesma afirmação que o compose já faz ao montar o volume do dashboard como
`:ro` — *quem publica número não escreve dado* — agora com o RBAC da nuvem
sustentando, e não a boa vontade do processo.

**Uma imagem só, dois entrypoints.** Igual ao compose hoje: o serviço `cno` e o
`dashboard` saem da mesma imagem. Mas a base muda de `apache/airflow` para
`python:3.12-slim` — sem Airflow na nuvem, não há motivo para carregar o
resolvedor de dependências dele. O venv do pipeline já é isolado em
`/opt/cno/.venv`, então é trocar a base e manter o resto do Dockerfile.

**`docker build`, porque `az acr build` não está disponível.** A primeira
escolha era construir dentro da Azure com ACR Tasks: dispensaria cross-build
para `linux/amd64` e não subiria a imagem pela conexão de casa. Mas esta
assinatura recusa:

```
ERROR: (TasksOperationsNotAllowed) ACR Tasks requests for the registry
acrcnofiesc and a473d0e0-… are not permitted.
```

É uma restrição de assinatura nova, não do registry nem do plano Basic, e
levantá-la exige chamado na Microsoft. O contorno custa pouco: a máquina é
amd64 e o runner do GitHub também, então `docker build` nos dois lugares produz
a arquitetura certa sem buildx. O que se paga é o push da imagem pela conexão
local, uma vez — no CD quem empurra é o runner.

Efeito colateral bom: a identidade de deploy fica com menos permissão. Com ACR
Tasks seria preciso `Container Registry Tasks Contributor`, que é control
plane; com push basta `AcrPush` mais `Reader`.

**Estado do Terraform remoto, num bootstrap à parte.** O backend precisa de um
storage account que ainda não existe — o ouroboros clássico. Resolvido por um
script `az` de ~15 linhas que cria o grupo, a conta e o container do tfstate, e
só depois o Terraform assume. O state do bootstrap não existe: ele é
imperativo de propósito, para não haver um segundo state a proteger.

---

## Fase 0 — antes de escrever qualquer `.tf`

**0.1 — O teste que podia derrubar o plano inteiro. ✅ passou em 20/09/2026.**

A fonte é um Nextcloud público da Receita que responde 303, e a extração depende
de `HEAD` devolvendo ETag e de sondagem de `Range`. Nada garantia que ela se
comportasse igual vista de um datacenter da Azure. Verificado com um Container
Instance descartável em `brazilsouth` (`rg-cno-smoke`, destruído depois):

```
HEAD          303 → 200
              ETag: "76bb7f934f457be4234c5733ee92b40b"
              Last-Modified: Sat, 12 Sep 2026 04:59:45 GMT
              Content-Length: 330.628.581

GET Range: bytes=0-0            → 206 Partial Content
GET Range: bytes=104857600-…    → 206, Content-Range: bytes 104857600-104858600/330628581

50 MiB em 9,6 s  →  5,45 MB/s  →  ~60 s para o pacote inteiro
```

Tudo de que a extração precisa está de pé: idempotência por ETag, snapshot
datado pelo `Last-Modified` (o corrente é **2026-09-12**) e retomada por
`Range`. O download não será o gargalo do job.

**Duas peculiaridades da fonte, descobertas aqui e que valem registro:**

*`HEAD` com cabeçalho `Range` devolve `500`.* Inofensivo — o pipeline nunca faz
essa requisição; a sonda é um `GET` (`source.py:_suporta_range`). Só apareceu
porque o primeiro teste usou `curl -I` por engano.

*`Range: bytes=0-0` devolve `206`, mas com o arquivo inteiro* —
`Content-Range: bytes 0-330628580/330628581`. O servidor honra o início da
faixa e ignora o fim quando o fim é zero (cheira a `if (!$end) $end = $size-1`
em PHP, com `0` caindo como falso). Uma faixa fechada de verdade, testada a
partir de 100 MB, é honrada nas duas pontas.

Isso **não** é um problema para o pipeline, por duas razões que já estavam
certas por desenho:

1. A sonda usa `stream=True` e fecha a resposta sem iterar o corpo, então os
   315 MB nunca chegam a ser transferidos — o `curl` do teste baixou tudo
   justamente por não fazer isso, e foi o que denunciou o comportamento.
2. A retomada real pede `bytes={já_temos}-`, faixa aberta, e `_range_confere`
   compara **só o offset inicial**. Se comparasse a faixa inteira, este servidor
   a reprovaria.

Fica como nota para quem mexer nessa parte depois: não “melhore” a sonda para
exigir `Content-Range: bytes 0-0/…`. Esta fonte reprovaria, e a retomada seria
desligada em silêncio — de volta a rebaixar 315 MB a cada falha de rede.

**0.2 — Ferramental. ✅ feito em 20/09/2026.** `az` e `terraform` no **Windows
nativo**, via winget — não no WSL, como este plano dizia antes, e não em
container.

```powershell
winget install --id Hashicorp.Terraform --exact --silent
winget install --id Microsoft.AzureCLI   --exact --silent
az login
```

Três razões para o Windows, contra o WSL que estava escrito aqui:

1. `az login` abre o navegador e resolve sozinho; no WSL cai no fluxo de
   device code, e em container o token morre com o container.
2. O provider `azurerm` autentica reaproveitando o cache de token do `az`
   (`~/.azure`). Nativo, as duas ferramentas se enxergam sem costura.
3. Esta trilha não tem dependência POSIX: é `az`, `terraform` e `git`. O
   pipeline continua rodando pelo WSL, com os dados em `/home/administrador/cno-data`.

Container foi descartado apesar de o projeto ser todo container, e a distinção
vale registrar: container empacota o que **roda sozinho** — o pipeline, o
dashboard. CLI de operador, executada dezenas de vezes por sessão e precisando
de cache de credencial e de ~100 MB de providers persistentes, só ganha
cerimônia com ele.

Instalado: Terraform 1.16.2, Azure CLI 2.90.0.

**0.3 — Registrar providers e conferir cota. ✅ registrado em 20/09/2026.**
É o `gcloud services enable` da Azure: numa subscription nova **nada** vem
registrado, e descobrir isso no meio de um `apply` é ruim.

```powershell
foreach ($ns in @("Microsoft.App","Microsoft.ContainerRegistry","Microsoft.Storage",
                  "Microsoft.OperationalInsights","Microsoft.ContainerInstance")) {
  az provider register --namespace $ns --wait
}
```

Subscription: `Azure subscription 1` (`a473d0e0-3635-4fac-bf47-a55cc5cbd547`),
tenant `b82ee7d5-cc25-4077-b154-8e83daa18cd5`.

**Região: `brazilsouth`.** Uma versão anterior deste plano dizia `eastus2`, por
custo. O argumento não sobrevive ao desenho: o job cabe na cota gratuita nas
duas regiões e o dashboard fica em `min_replicas = 0`, então a diferença real
se resume ao ACR Basic e a centavos de storage — uns US$ 2/mês. Contra isso, o
RTT de Florianópolis para `eastus2` é da ordem de 150 ms, e o Streamlit faz
round-trip por websocket a cada interação de widget: numa demonstração ao vivo
isso se sente. Dois dólares não compram isso de volta. Confirmado que
`Microsoft.App/managedEnvironments` existe em `brazilsouth`; de brinde, a
narrativa fecha melhor.

A **cota** de Container Apps ainda não foi conferida: o `az quota` exige uma
extensão em preview e não valeu o desvio. Ela se revela no `apply` do
`managedEnvironment`, que é barato de tentar e de desfazer.

---

## Fase 1 — bootstrap do state

`nuvem/bootstrap.sh`: cria `rg-cno-tfstate`, um storage account com nome
aleatório (o namespace é global) e o container `tfstate`. Depois:

```hcl
terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
  }
  backend "azurerm" {
    resource_group_name  = "rg-cno-tfstate"
    storage_account_name = "stcnotfstateXXXXX"
    container_name       = "tfstate"
    key                  = "cno.tfstate"
    use_azuread_auth     = true          # sem chave de conta em lugar nenhum
  }
}

provider "azurerm" {
  features {}
  storage_use_azuread = true             # necessário: as contas nascem com
}                                        # shared_access_key_enabled = false
```

Aquele `storage_use_azuread` é o detalhe que custa meia hora se esquecido: com
`shared_access_key_enabled = false` no lake, o próprio Terraform não consegue
criar o filesystem sem ele.

---

## Fase 2 — a infra

Root module em `nuvem/terraform/`. Os recursos, agrupados por arquivo:

**`base.tf`** — `azurerm_resource_group`, `azurerm_log_analytics_workspace`
(retenção 30 dias e *daily cap* baixo; o volume de log daqui é ínfimo, mas o
cap evita surpresa), `azurerm_container_registry` (SKU `Basic`,
`admin_enabled = false`).

**`lake.tf`** — `azurerm_storage_account` com `is_hns_enabled = true`,
`account_replication_type = "LRS"`, `min_tls_version = "TLS1_2"`,
`shared_access_key_enabled = false`; e um
`azurerm_storage_data_lake_gen2_filesystem` chamado `lake`. Dentro dele o
pipeline reproduz a hierarquia que já escreve — `curated/snapshot_date=.../uf=...`
sobe como está, porque partição Hive é só prefixo de caminho.

**`identidades.tf`** — três `azurerm_user_assigned_identity`:

| identidade | papel | escopo |
|---|---|---|
| `id-cno-job` | `Storage Blob Data Contributor` + `AcrPull` | lake, ACR |
| `id-cno-dashboard` | `Storage Blob Data Reader` + `AcrPull` | lake, ACR |
| `id-cno-deploy` | `AcrPush` + `Container Apps Contributor` | ACR, RG |

Mais um `azurerm_federated_identity_credential` na `id-cno-deploy`, com
`subject = "repo:joao-p-garcia/cno-pipeline-fiesc:ref:refs/heads/cloud/azure"`
e issuer `https://token.actions.githubusercontent.com`. Isso é o que dispensa
segredo no GitHub — e é federação sobre *managed identity*, sem precisar de
registro de aplicação no Entra ID.

**`apps.tf`** — o `azurerm_container_app_environment` e os dois recursos que
importam:

```hcl
resource "azurerm_container_app_job" "pipeline" {
  name                       = "job-cno-pipeline"
  replica_timeout_in_seconds = 3600
  replica_retry_limit        = 1

  schedule_trigger_config {
    cron_expression          = "0 9 * * *"   # UTC → 06:00 em Brasília
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "cno"
      image  = "${azurerm_container_registry.cno.login_server}/cno-pipeline:latest"
      cpu    = 2.0
      memory = "4Gi"
      # 4 GB de pico de disco: 1,4 (raw) + 1,4 (intermediário utf-8) + 1,1 (staging).
      # O efêmero acompanha o tamanho do container — CONFERIR na doc corrente
      # que este par entrega os ~8 GiB do topo do plano consumo.
    }
  }

  lifecycle {
    # Depois do primeiro apply, quem manda na tag é o GitHub Actions.
    ignore_changes = [template[0].container[0].image]
  }
}
```

O cron é **UTC**. `0 9 * * *` é 06:00 em Brasília e não muda com horário de
verão (que não existe mais, mas o hábito de anotar fica).

O dashboard é um `azurerm_container_app` com ingress externo na 8501,
`min_replicas = 0` e `max_replicas = 1`. Zero é o default porque uma réplica
parada 24/7 é o único item de custo relevante do projeto; antes de apresentar,
abrir a URL uma vez para aquecer.

### O ovo e a galinha do primeiro apply

O Container App referencia uma imagem que ainda não existe no ACR. Primeiro
apply em dois tempos:

```bash
terraform apply -target=azurerm_container_registry.cno
docker build --platform linux/amd64 -f nuvem/Dockerfile -t acrcnofiesc.azurecr.io/cno-pipeline:latest .
az acr login --name acrcnofiesc && docker push acrcnofiesc.azurecr.io/cno-pipeline:latest
terraform apply
```

Do segundo apply em diante é um comando só, e o `ignore_changes` impede que o
Terraform reverta a tag que o Actions publicou.

---

## Fase 3 — a imagem e o entrypoint

**`nuvem/Dockerfile`** — cópia do Dockerfile da raiz com a base trocada para
`python:3.12-slim`, sem o `COPY dags/` e sem o Airflow. Mantém os dois testes
de fumaça em tempo de build (a geocodificação e o `import streamlit`), que já
pegaram uma dependência implícita neste projeto uma vez.

Adiciona o **azcopy** (binário único, ~30 MB) — é o que fala com o lake.

**`nuvem/entrypoint-job.sh`**:

```sh
set -euo pipefail
cno extract --json && cno transform --json && cno validate --json && cno curate --json
azcopy login --identity --identity-client-id "$AZURE_CLIENT_ID"
azcopy sync "$CNO_DATA_DIR/curated" "https://<conta>.blob.core.windows.net/lake/curated" \
  --recursive --delete-destination=false
```

O `--delete-destination=false` é deliberado: snapshot antigo no lake não é lixo,
é histórico — a mesma postura que o `raw/` tem localmente.

**`nuvem/entrypoint-dashboard.sh`** faz o inverso (`azcopy copy` do lake para
`$CNO_DATA_DIR/curated`) e então sobe o Streamlit exatamente com a linha de
comando que o compose já usa. Se o lake estiver vazio, o app já sabe se
explicar sozinho — esse comportamento existe e não precisa de tratamento novo.

**`nuvem/publicar.py` (alternativa considerada)**: fazer o mesmo com
`azure-storage-blob` + `DefaultAzureCredential`, num script fora de
`src/cno_pipeline/` — na mesma fronteira em que `analise/` já vive. É mais
elegante e mais fácil de testar, mas são ~60 linhas contra duas de azcopy.
Fica registrado; começar pelo azcopy.

---

## Fase 4 — CD

`.github/workflows/nuvem.yml`, disparado em push nesta branch e em tag:

1. `azure/login@v2` com `client-id` da `id-cno-deploy`, `tenant-id`,
   `subscription-id` — em `vars`, não em `secrets`, porque nenhum deles é
   segredo; o que autentica é o token OIDC do próprio runner
   (`permissions: id-token: write`).
2. `az acr login`, depois `docker build` e `docker push` com duas tags: o sha
   do commit e `latest`.
3. `az containerapp job update` e `az containerapp update` com a nova tag.

O CI atual (`.github/workflows/ci.yml`) continua como está: os 256 testes não
tocam a rede e não têm nada a ver com nuvem.

---

## Custo

| Item | Estimativa |
|---|---|
| Container Apps Job | ~3,3 h/mês de compute → dentro da cota gratuita mensal (180k vCPU-s / 360k GiB-s) |
| ADLS Gen2 | 191 MB/dia acumulando; poucos GB em hot → centavos |
| ACR Basic | ~US$ 5/mês |
| Log Analytics | ~US$ 0 no volume deste projeto |
| Dashboard com `min_replicas = 0` | ~US$ 0 parado; centavos por sessão |
| *Dashboard sempre no ar (se quiser)* | *de poucos dólares a ~US$ 35/mês, conforme conte como ocioso* |

Ordem de grandeza: **US$ 5–10/mês** no desenho recomendado. Se a conta ainda
tiver o crédito inicial de US$ 200, tudo isso passa despercebido.

Vale pôr um **budget alert** na subscription no primeiro dia. Não pelo risco
deste desenho, mas porque descobrir um recurso esquecido pela fatura é uma
lição cara de aprender duas vezes.

---

## O que pode morder

1. ~~**A fonte vista da Azure**~~ — **descartado em 20/09/2026** pela fase 0.1.
   Era o único risco que invalidava o plano; respondeu com ETag, `Last-Modified`
   e `206` a 5,45 MB/s.
2. **Disco efêmero apertado.** ~4 GB de pico contra um teto que depende do par
   vCPU/memória. Se não couber: montar um Azure Files só para o scratch — mas
   aí o `flock` volta a ser questão, então a saída melhor é aumentar o container.
   **É o maior risco aberto agora.**
3. **Cota de Container Apps em subscription nova.** Providers registrados
   (fase 0.3); a cota em si só se revela no `apply` do `managedEnvironment`.
4. **Versão do provider azurerm.** `azurerm_container_app_job` existe desde a
   série 3.x, mas os nomes dos blocos mudaram no caminho. Pinar `~> 4.0` e
   conferir a doc da versão exata antes de escrever — não confiar em exemplo
   antigo de blog.
5. **Cold start do dashboard** com `min_replicas = 0`: dezenas de segundos, mais
   o download dos 191 MB. Numa demonstração ao vivo isso é uma eternidade.
   Abrir a URL antes de começar a apresentar.

---

## Roteiro da demonstração

O que abrir, na ordem, depois que o Streamlit local terminar:

1. **O job no portal** — histórico de execuções, com a de hoje verde e a
   duração real. É a prova de que roda sozinho.
2. **O log da última execução** — as mesmas linhas JSON que o Airflow mostra
   localmente, com os totais de controle da Receita reconciliando.
3. **O storage browser** — a hierarquia `curated/snapshot_date=.../uf=...`, a
   mesma que o `data/` local tem. O particionamento não mudou porque nunca foi
   sobre o sistema de arquivos.
4. **A URL pública do dashboard** — o mesmo app, os mesmos números.
5. **`terraform plan` limpo no terminal** — nenhuma mudança pendente: o que
   está no ar é o que está versionado.

---

## Ordem de execução

- [x] 0.1 testar a fonte de dentro da Azure — **passou**
- [x] 0.2 instalar az + terraform no Windows, `az login`
- [x] 0.3 registrar providers, região definida (`brazilsouth`); cota fica para o apply
- [ ] 1 `bootstrap.sh` e o backend
- [ ] 2 `base.tf`, `lake.tf`, `identidades.tf`
- [x] 3 `nuvem/Dockerfile` e os dois entrypoints; build e push na mão
- [ ] 2b `apps.tf` e o apply completo
- [ ] 3b disparar o job na mão (`az containerapp job start`) e ver o lake encher
- [ ] 4 o workflow de CD
- [ ] 5 aquecer, ensaiar o roteiro, pôr o budget alert
