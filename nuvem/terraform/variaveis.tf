# As variáveis sem `default` são os identificadores do ambiente de quem aplica:
# assinatura, e-mail de alerta e os IDs do repositório no GitHub. Elas moram em
# `terraform.tfvars`, que **não é versionado** — o repositório é público, e um
# módulo que traz embutidos os identificadores de uma conta específica é ruim
# por dois motivos independentes: expõe o que não precisa ser exposto, e só
# serve para aquela conta.
#
# Para aplicar noutro ambiente, copie `exemplo.tfvars` para `terraform.tfvars`
# e preencha. O Terraform lê esse nome automaticamente.

variable "assinatura" {
  description = "ID da assinatura Azure onde tudo é criado."
  type        = string
}

variable "email_alerta" {
  description = "Destino dos avisos de orçamento. Normalmente o dono da assinatura."
  type        = string
}

variable "owner_id_github" {
  description = "ID numérico do dono no GitHub. Ver o comentário em identidades.tf."
  type        = string
}

variable "repo_id_github" {
  description = "ID numérico do repositório no GitHub."
  type        = string
}

# --- daqui para baixo, nada é específico de uma conta ----------------------

variable "regiao" {
  description = <<-TXT
    Região de tudo. brazilsouth e não eastus2: o job cabe na cota gratuita nas
    duas e o dashboard fica em min_replicas=0, então a diferença de custo é de
    uns US$ 2/mês — enquanto o RTT de Florianópolis cai de ~150 ms para ~20 ms,
    e o Streamlit faz round-trip por websocket a cada interação de widget.
  TXT
  type        = string
  default     = "brazilsouth"
}

variable "grupo" {
  description = "Grupo de recursos do pipeline (o do state é outro, criado pelo bootstrap)."
  type        = string
  default     = "rg-cno-nuvem"
}

variable "repositorio_github" {
  description = "owner/repo, para o subject da credencial federada do OIDC."
  type        = string
  default     = "joao-p-garcia/cno-pipeline-fiesc"
}

variable "branch_github" {
  description = "Branch autorizada a publicar imagem e atualizar os apps."
  type        = string
  default     = "cloud/azure"
}

variable "imagem" {
  description = <<-TXT
    Tag da imagem no ACR. Só vale para a criação: depois do primeiro apply quem
    manda na tag é o GitHub Actions, e os dois recursos ignoram mudanças neste
    campo (ver o lifecycle em apps.tf).
  TXT
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
