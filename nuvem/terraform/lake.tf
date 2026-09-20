# O data lake.
#
# is_hns_enabled = true é o que transforma um storage account comum em ADLS
# Gen2: hierarquia de diretórios de verdade, em vez de nomes de blob com barra
# dentro. Para o que sobe aqui — partições Hive `snapshot_date=.../uf=...` — a
# diferença aparece na hora de listar e de renomear um diretório inteiro.
#
# O particionamento não precisou mudar nada para vir para cá, e isso não é
# sorte: partição Hive sempre foi só prefixo de caminho.
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

  # Mesma postura do backend do state: sem chave de conta, a autenticação é
  # sempre Entra ID. É o que permite que o job e o dashboard usem identidade
  # gerenciada sem que exista um segredo em lugar nenhum para vazar.
  shared_access_key_enabled = false

  tags = local.etiquetas
}

# Sem isto o `apply` falha com 403 de forma intermitente.
#
# O Terraform acaba de criar a conta e já quer criar um filesystem dentro dela —
# mas isso é *data plane*, e na Azure ser dono do recurso não dá acesso ao
# conteúdo. Precisa de um papel de dado explícito, e uma atribuição de papel não
# vale no instante em que é criada.
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
