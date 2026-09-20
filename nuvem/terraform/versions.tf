terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    # Só para esperar o RBAC propagar antes de usar o data plane do lake.
    # Ver o comentário em lake.tf — não é preciosismo, é uma falha real e
    # intermitente sem isso.
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }

  # Criado por nuvem/bootstrap.sh. use_azuread_auth porque a conta nasce com
  # --allow-shared-key-access false: não existe chave para o Terraform usar.
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

  # A partir da série 4.x o provider não adivinha mais a assinatura do contexto
  # do az; ela é obrigatória. E sem isto aqui ele tentaria chave de conta ao
  # falar com o storage, que não existe em nenhuma conta deste projeto.
  storage_use_azuread = true
}

data "azurerm_client_config" "atual" {}
