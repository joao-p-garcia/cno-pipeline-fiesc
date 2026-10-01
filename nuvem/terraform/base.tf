resource "azurerm_resource_group" "cno" {
  name     = var.grupo
  location = var.regiao
  tags     = local.etiquetas
}

# Exigido pelo ambiente do Container Apps. A cota diária evita que um loop de
# falha vire fatura.
resource "azurerm_log_analytics_workspace" "cno" {
  name                = "log-cno"
  location            = azurerm_resource_group.cno.location
  resource_group_name = azurerm_resource_group.cno.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 1
  tags                = local.etiquetas
}

# Sem usuário admin. Job e dashboard puxam por identidade gerenciada e o CD
# empurra por OIDC, então não existe credencial de registry.
resource "azurerm_container_registry" "cno" {
  name                = "acrcnofiesc"
  location            = azurerm_resource_group.cno.location
  resource_group_name = azurerm_resource_group.cno.name
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.etiquetas
}
