# O data lake. is_hns_enabled faz do storage account um ADLS Gen2, com
# diretórios de verdade para as partições Hive.
resource "azurerm_storage_account" "lake" {
  name                = "stcnolakefiesc"
  resource_group_name = azurerm_resource_group.cno.name
  location            = azurerm_resource_group.cno.location

  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  is_hns_enabled           = true

  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false

  # Sem chave de conta, a autenticação é sempre Entra ID.
  shared_access_key_enabled = false

  tags = local.etiquetas
}

# Criar o filesystem é data plane e exige papel de dado, que não vale no
# instante em que é atribuído. Sem a espera o apply falha com 403 intermitente.
resource "azurerm_role_assignment" "terraform_no_lake" {
  scope                = azurerm_storage_account.lake.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = data.azurerm_client_config.atual.object_id
}

resource "time_sleep" "rbac_do_lake" {
  depends_on      = [azurerm_role_assignment.terraform_no_lake]
  create_duration = "60s"
}

resource "azurerm_storage_data_lake_gen2_filesystem" "lake" {
  name               = "lake"
  storage_account_id = azurerm_storage_account.lake.id

  depends_on = [time_sleep.rbac_do_lake]
}
