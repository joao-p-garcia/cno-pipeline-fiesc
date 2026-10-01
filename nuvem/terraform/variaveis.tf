# As variáveis sem `default` identificam a conta de quem aplica e ficam em
# `terraform.tfvars`, fora do repositório. Para outro ambiente, copie
# `exemplo.tfvars` para `terraform.tfvars` e preencha.

variable "assinatura" {
  description = "ID da assinatura Azure onde tudo é criado."
  type        = string
}

variable "email_alerta" {
  description = "Destino dos avisos de orçamento."
  type        = string
}

variable "owner_id_github" {
  description = "ID numérico do dono no GitHub."
  type        = string
}

variable "repo_id_github" {
  description = "ID numérico do repositório no GitHub."
  type        = string
}

# --- daqui para baixo, nada é específico de uma conta ----------------------

variable "regiao" {
  description = "Região de tudo. brazilsouth pela latência, com custo quase igual ao de eastus2."
  type        = string
  default     = "brazilsouth"
}

variable "grupo" {
  description = "Grupo de recursos do pipeline (o do state é criado pelo bootstrap)."
  type        = string
  default     = "rg-cno-nuvem"
}

variable "repositorio_github" {
  description = "owner/repo, para o subject da credencial federada."
  type        = string
  default     = "joao-p-garcia/cno-pipeline-fiesc"
}

variable "branch_github" {
  description = "Branch autorizada a publicar imagem e atualizar os apps."
  type        = string
  default     = "cloud/azure"
}

variable "imagem" {
  description = "Tag da imagem no ACR. Só vale na criação, depois a tag é do CD."
  type        = string
  default     = "cno-pipeline:latest"
}

variable "cron" {
  description = "Horário do job, em UTC. 09:00 UTC = 06:00 em Brasília."
  type        = string
  default     = "0 9 * * *"
}

locals {
  etiquetas = {
    projeto   = "cno-pipeline-fiesc"
    ambiente  = "demonstracao"
    terraform = "true"
  }
}
