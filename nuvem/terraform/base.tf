resource "azurerm_resource_group" "cno" {
  name     = var.grupo
  location = var.regiao
  tags     = local.etiquetas
}

# O ambiente do Container Apps exige um workspace. O volume de log deste
# projeto é ínfimo (quatro etapas, uma vez por dia), mas o daily_quota_gb
# existe para que um loop de falha em retry não vire fatura.
resource "azurerm_log_analytics_workspace" "cno" {
  name                = "log-cno"
  location            = azurerm_resource_group.cno.location
  resource_group_name = azurerm_resource_group.cno.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 1
  tags                = local.etiquetas
}

# Basic basta: um repositório, uma imagem, sem replicação geográfica e sem
# necessidade de rede privada.
#
# admin_enabled = false de propósito. O usuário admin do ACR é um par
# usuário/senha estático que acaba num secret do CI; aqui tanto o job quanto o
# dashboard puxam a imagem por identidade gerenciada, e o GitHub Actions empurra
# por OIDC. Não há credencial de registry em lugar nenhum.
resource "azurerm_container_registry" "cno" {
  name                = "acrcnofiesc"
  location            = azurerm_resource_group.cno.location
  resource_group_name = azurerm_resource_group.cno.name
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.etiquetas
}
