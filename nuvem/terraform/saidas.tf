output "registry" {
  description = "Servidor do ACR."
  value       = azurerm_container_registry.cno.login_server
}

output "dashboard_url" {
  description = "URL pública do dashboard."
  value       = "https://${azurerm_container_app.dashboard.ingress[0].fqdn}"
}

output "lake_curated" {
  description = "Destino da publicação do job e origem da leitura do dashboard."
  value       = local.lake_curated
}

# Nenhum destes valores é segredo, quem autentica é o token OIDC do runner.
output "github_variaveis" {
  description = "Valores para as Variables do repositório (não Secrets)."
  value = {
    AZURE_CLIENT_ID       = azurerm_user_assigned_identity.deploy.client_id
    AZURE_TENANT_ID       = data.azurerm_client_config.atual.tenant_id
    AZURE_SUBSCRIPTION_ID = var.assinatura
    AZURE_RESOURCE_GROUP  = azurerm_resource_group.cno.name
    AZURE_REGISTRY        = azurerm_container_registry.cno.name
  }
}
