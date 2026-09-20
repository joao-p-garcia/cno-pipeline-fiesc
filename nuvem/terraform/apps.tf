locals {
  imagem_completa = "${azurerm_container_registry.cno.login_server}/${var.imagem}"

  # Endpoint dfs, e não blob: a conta tem hierarchical namespace, e o azcopy
  # lida melhor com diretórios de verdade pelo dfs.
  lake_base    = "${azurerm_storage_account.lake.primary_dfs_endpoint}${azurerm_storage_data_lake_gen2_filesystem.lake.name}"
  lake_curated = "${local.lake_base}/curated"
  lake_raw     = "${local.lake_base}/raw"
}

resource "azurerm_container_app_environment" "cno" {
  name                       = "cae-cno"
  location                   = azurerm_resource_group.cno.location
  resource_group_name        = azurerm_resource_group.cno.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.cno.id
  tags                       = local.etiquetas

  # Declarado explicitamente embora seja o default. A Azure preenche este bloco
  # sozinha, e sem ele aqui todo `terraform plan` acusaria uma mudança pendente
  # que não existe. Plan limpo é o que prova que o que está no ar é o que está
  # versionado — e isso é item do roteiro de demonstração.
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

# --- o pipeline ------------------------------------------------------------
#
# Isto é o que substitui os cinco contêineres do Airflow. O cron é embutido no
# recurso; não há scheduler para manter de pé, e entre uma execução e outra não
# existe nada rodando nem sendo cobrado.
#
# O que se perde em relação à DAG: retry por etapa e o grafo visual. O retry por
# etapa importa menos do que parece aqui, porque a idempotência vive dentro de
# cada comando — reexecutar o job inteiro reaproveita o que já foi feito e o
# `extract` devolve em menos de um segundo quando não há publicação nova.
resource "azurerm_container_app_job" "pipeline" {
  name                         = "job-cno-pipeline"
  location                     = azurerm_resource_group.cno.location
  resource_group_name          = azurerm_resource_group.cno.name
  container_app_environment_id = azurerm_container_app_environment.cno.id

  # Localmente o pipeline inteiro leva ~6,5 min; uma hora é folga para uma
  # publicação maior ou uma rede ruim, sem deixar um job pendurado para sempre.
  replica_timeout_in_seconds = 3600
  replica_retry_limit        = 1
  workload_profile_name      = "Consumption"

  schedule_trigger_config {
    cron_expression          = var.cron
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "cno"
      image  = local.imagem_completa
      cpu    = 2.0
      memory = "4Gi"

      command = ["/opt/cno/nuvem/entrypoint-job.sh"]

      # Pico de disco medido: 1,4 GB de CSV cru + 1,4 GB do intermediário UTF-8
      # + 1,1 GB de staging ≈ 4 GB. O efêmero deste par de vCPU/memória tem de
      # comportar isso — é o maior risco aberto do plano.
      env {
        name  = "CNO_DATA_DIR"
        value = "/opt/cno/data"
      }
      env {
        name  = "CNO_LOG_JSON"
        value = "1"
      }
      # O zip fica, ao contrário do intermediário UTF-8: ele é o artefato
      # original, e o share da Receita não guarda histórico. É o único arquivo
      # deste pipeline que, uma vez perdido, não se reproduz — então sobrevive à
      # etapa para ser arquivado no lake no fim do job.
      env {
        name  = "CNO_MANTER_ZIP"
        value = "1"
      }
      env {
        name  = "CNO_MANTER_INTERMEDIARIOS"
        value = "0"
      }
      # 3 GB e não 4: o teto do DuckDB precisa caber *dentro* da memória da
      # réplica, com espaço para o interpretador e o resto do processo.
      env {
        name  = "CNO_DUCKDB_MEMORY"
        value = "3GB"
      }
      env {
        name  = "CNO_DUCKDB_THREADS"
        value = "2"
      }
      env {
        name  = "CNO_LAKE_CURATED"
        value = local.lake_curated
      }
      env {
        name  = "CNO_LAKE_RAW"
        value = local.lake_raw
      }
      # O azcopy precisa saber *qual* identidade usar: a réplica pode ter mais
      # de uma atribuída, e sem isto ele não escolhe sozinho.
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.job.client_id
      }
    }
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.job.id]
  }

  registry {
    server   = azurerm_container_registry.cno.login_server
    identity = azurerm_user_assigned_identity.job.id
  }

  tags = local.etiquetas

  lifecycle {
    # Depois do primeiro apply quem manda na tag é o GitHub Actions. Sem isto,
    # o próximo `terraform apply` reverteria a imagem publicada pelo CD.
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.job_puxa_imagem]
}

# --- o dashboard ----------------------------------------------------------

resource "azurerm_container_app" "dashboard" {
  name                         = "ca-cno-dashboard"
  resource_group_name          = azurerm_resource_group.cno.name
  container_app_environment_id = azurerm_container_app_environment.cno.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  template {
    # Zero réplicas paradas é o que mantém a conta perto de zero: uma réplica
    # 24/7 seria o único item de custo relevante do projeto inteiro. O preço é
    # cold start de dezenas de segundos mais o download dos 191 MB — por isso
    # a última linha do roteiro de apresentação é abrir a URL antes de começar.
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "dashboard"
      image  = local.imagem_completa
      cpu    = 0.5
      memory = "1Gi"

      command = ["/opt/cno/nuvem/entrypoint-dashboard.sh"]

      env {
        name  = "CNO_DATA_DIR"
        value = "/opt/cno/data"
      }
      env {
        name  = "CNO_LAKE_CURATED"
        value = local.lake_curated
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.dashboard.client_id
      }
      env {
        name  = "CNO_DUCKDB_MEMORY"
        value = "768MB"
      }
      env {
        name  = "CNO_DUCKDB_THREADS"
        value = "2"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8501
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.dashboard.id]
  }

  registry {
    server   = azurerm_container_registry.cno.login_server
    identity = azurerm_user_assigned_identity.dashboard.id
  }

  tags = local.etiquetas

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.dashboard_puxa_imagem]
}
