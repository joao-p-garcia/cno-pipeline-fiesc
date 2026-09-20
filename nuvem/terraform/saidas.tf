output "registry" {
  description = "Servidor do ACR, para o `az acr build`."
  value       = azurerm_container_registry.cno.login_server
}

output "dashboard_url" {
  description = "A URL pública do dashboard. É o que se abre na apresentação."
  value       = "https://${azurerm_container_app.dashboard.ingress[0].fqdn}"
}

output "lake_curated" {
  description = "Destino da publicação do job e origem da leitura do dashboard."
  value       = local.lake_curated
}

# Os três valores que o workflow do GitHub Actions precisa. Nenhum deles é
# segredo: o que autentica é o token OIDC que o runner emite na hora, e a
# credencial federada só aceita trocá-lo se vier da branch declarada.
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
