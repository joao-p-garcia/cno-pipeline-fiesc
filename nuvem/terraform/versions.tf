terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    # Para esperar o RBAC do lake propagar.
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }

  # Criado por nuvem/bootstrap.sh. A conta não tem chave, daí o use_azuread_auth.
  backend "azurerm" {
    resource_group_name  = "rg-cno-tfstate"
    storage_account_name = "stcnotfstatefiesc"
    container_name       = "tfstate"
    key                  = "cno.tfstate"
    use_azuread_auth     = true
  }
}

provider "azurerm" {
  features {}

  subscription_id = var.assinatura

  # Sem chave de conta no storage, o provider precisa autenticar por Entra ID.
  storage_use_azuread = true
}

data "azurerm_client_config" "atual" {}
