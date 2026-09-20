# Três identidades, e a separação é uma afirmação de arquitetura.
#
# O compose já dizia isto ao montar o volume do dashboard como `:ro` — *quem
# publica número não escreve dado*. Lá a garantia era a boa vontade do processo;
# aqui é o RBAC do provedor. O dashboard não consegue escrever no lake nem se
# alguém empurrar um bug que tente.

# --- quem roda o pipeline -------------------------------------------------

resource "azurerm_user_assigned_identity" "job" {
  name                = "id-cno-job"
  location            = azurerm_resource_group.cno.location
  resource_group_name = azurerm_resource_group.cno.name
  tags                = local.etiquetas
}

resource "azurerm_role_assignment" "job_escreve_no_lake" {
  scope                = azurerm_storage_account.lake.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.job.principal_id
}

resource "azurerm_role_assignment" "job_puxa_imagem" {
  scope                = azurerm_container_registry.cno.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.job.principal_id
}

# --- quem publica o número ------------------------------------------------

resource "azurerm_user_assigned_identity" "dashboard" {
  name                = "id-cno-dashboard"
  location            = azurerm_resource_group.cno.location
  resource_group_name = azurerm_resource_group.cno.name
  tags                = local.etiquetas
}

resource "azurerm_role_assignment" "dashboard_le_o_lake" {
  scope                = azurerm_storage_account.lake.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.dashboard.principal_id
}

resource "azurerm_role_assignment" "dashboard_puxa_imagem" {
  scope                = azurerm_container_registry.cno.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.dashboard.principal_id
}

# --- quem faz o deploy ----------------------------------------------------

resource "azurerm_user_assigned_identity" "deploy" {
  name                = "id-cno-deploy"
  location            = azurerm_resource_group.cno.location
  resource_group_name = azurerm_resource_group.cno.name
  tags                = local.etiquetas
}

# A credencial federada: o GitHub Actions apresenta o token OIDC que o próprio
# runner emite, e a Azure o troca por um token de acesso. Nenhum segredo é
# guardado no repositório — é o mesmo conceito do Workload Identity Federation
# do GCP, e aqui nem exige registro de aplicação no Entra ID, porque federa
# direto sobre a identidade gerenciada.
#
# O `subject` amarra a confiança a uma branch específica: um push em qualquer
# outra não consegue trocar token nenhum.
resource "azurerm_federated_identity_credential" "github" {
  name                      = "github-actions"
  user_assigned_identity_id = azurerm_user_assigned_identity.deploy.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:${var.repositorio_github}:ref:refs/heads/${var.branch_github}"
}

resource "azurerm_role_assignment" "deploy_empurra_imagem" {
  scope                = azurerm_container_registry.cno.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
}

# AcrPush sozinho não basta para o `az acr login`: ele carrega apenas
# `registries/pull/read` e `registries/push/write`, que são o data plane, e o
# login precisa antes *ler o recurso* para descobrir o login server. Reader é o
# recorte mínimo que resolve — metadados do registry, nada mais.
#
# Vale registrar o que NÃO está aqui: `Container Registry Tasks Contributor`,
# que seria o papel do `az acr build`. Esta assinatura tem ACR Tasks bloqueado
# (TasksOperationsNotAllowed, restrição de conta nova que exige chamado na
# Microsoft), então a imagem é construída no runner e empurrada — o que só
# precisa de push. Se as Tasks forem liberadas um dia, o caminho de volta é
# este papel mais uma linha no workflow.
resource "azurerm_role_assignment" "deploy_le_o_registry" {
  scope                = azurerm_container_registry.cno.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
}

# Precisa poder trocar a tag da imagem no job e no app. `Contributor` no grupo
# seria mais simples e é o que a maioria dos tutoriais faz; este papel é o
# recorte certo, e o grupo inteiro continua fora do alcance dele.
resource "azurerm_role_assignment" "deploy_atualiza_apps" {
  scope                = azurerm_resource_group.cno.id
  role_definition_name = "Container Apps Contributor"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
}
