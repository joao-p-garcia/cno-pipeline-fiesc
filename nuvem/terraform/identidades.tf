# Três identidades, uma por papel. O dashboard só lê o lake, por RBAC.

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

# Credencial federada para o OIDC do GitHub Actions, sem segredo no repositório.
# O `subject` restringe a confiança a uma branch.
locals {
  dono_github = split("/", var.repositorio_github)[0]
  repo_github = split("/", var.repositorio_github)[1]

  # Formato immutable do claim `sub`, com os IDs numéricos do dono e do
  # repositório. É o que este repositório emite, e não muda com renomeação.
  subject_github = "repo:${local.dono_github}@${var.owner_id_github}/${local.repo_github}@${var.repo_id_github}:ref:refs/heads/${var.branch_github}"
}

resource "azurerm_federated_identity_credential" "github" {
  name                      = "github-actions"
  user_assigned_identity_id = azurerm_user_assigned_identity.deploy.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = local.subject_github
}

resource "azurerm_role_assignment" "deploy_empurra_imagem" {
  scope                = azurerm_container_registry.cno.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
}

# O `az acr login` precisa ler o recurso antes, e AcrPush não cobre isso.
resource "azurerm_role_assignment" "deploy_le_o_registry" {
  scope                = azurerm_container_registry.cno.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
}

# O `azure/login` seleciona a assinatura logo após autenticar, e sem papel nela
# o principal não a enxerga. Reader não dá acesso a dado.
resource "azurerm_role_assignment" "deploy_enxerga_a_assinatura" {
  scope                = "/subscriptions/${var.assinatura}"
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
}

# Dois papéis porque o Container App e o Job são tipos de recurso diferentes, e
# Container Apps Contributor não cobre Microsoft.App/jobs.
resource "azurerm_role_assignment" "deploy_atualiza_apps" {
  scope                = azurerm_resource_group.cno.id
  role_definition_name = "Container Apps Contributor"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
}

resource "azurerm_role_assignment" "deploy_atualiza_jobs" {
  scope                = azurerm_resource_group.cno.id
  role_definition_name = "Container Apps Jobs Contributor"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
}
