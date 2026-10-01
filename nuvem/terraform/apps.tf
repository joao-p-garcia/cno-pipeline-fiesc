locals {
  imagem_completa = "${azurerm_container_registry.cno.login_server}/${var.imagem}"

  # Endpoint dfs porque a conta tem hierarchical namespace.
  lake_base    = "${azurerm_storage_account.lake.primary_dfs_endpoint}${azurerm_storage_data_lake_gen2_filesystem.lake.name}"
  lake_curated = "${local.lake_base}/curated"
  lake_raw     = "${local.lake_base}/raw"
  lake_staging = "${local.lake_base}/staging"
}

resource "azurerm_container_app_environment" "cno" {
  name                       = "cae-cno"
  location                   = azurerm_resource_group.cno.location
  resource_group_name        = azurerm_resource_group.cno.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.cno.id
  tags                       = local.etiquetas

  # É o default, mas sem declarar todo plan acusa uma mudança que não existe.
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

# --- o pipeline ------------------------------------------------------------
#
# Substitui os cinco contêineres do Airflow. O cron é do próprio recurso, e entre
# execuções nada roda nem é cobrado. Perde o retry por etapa, que pesa pouco
# porque cada comando já é idempotente.
resource "azurerm_container_app_job" "pipeline" {
  name                         = "job-cno-pipeline"
  location                     = azurerm_resource_group.cno.location
  resource_group_name          = azurerm_resource_group.cno.name
  container_app_environment_id = azurerm_container_app_environment.cno.id

  # O pipeline leva ~6,5 min, uma hora é folga sem deixar job pendurado.
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

      # Pico de disco medido em ~4 GB (CSV cru, intermediário UTF-8 e staging).
      env {
        name  = "CNO_DATA_DIR"
        value = "/opt/cno/data"
      }
      env {
        name  = "CNO_LOG_JSON"
        value = "1"
      }
      # O zip é mantido para ir ao lake, porque a Receita não guarda histórico.
      env {
        name  = "CNO_MANTER_ZIP"
        value = "1"
      }
      env {
        name  = "CNO_MANTER_INTERMEDIARIOS"
        value = "0"
      }
      # Abaixo dos 4 GB da réplica, para sobrar memória ao resto do processo.
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
      env {
        name  = "CNO_LAKE_STAGING"
        value = local.lake_staging
      }
      # Identidade que o azcopy deve usar.
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
    # A tag da imagem é do CD. Sem isto o apply reverteria a imagem publicada.
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
    # Zero réplicas paradas mantém o custo perto de zero. O preço é um cold start
    # de dezenas de segundos.
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
