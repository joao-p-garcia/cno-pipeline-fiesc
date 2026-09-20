variable "assinatura" {
  description = "ID da assinatura Azure onde tudo é criado."
  type        = string
  default     = "a473d0e0-3635-4fac-bf47-a55cc5cbd547"
}

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
  description = "Grupo de recursos da esteira (o do state é outro, criado pelo bootstrap)."
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

variable "email_alerta" {
  description = "Destino dos avisos de orçamento. O dono da assinatura."
  type        = string
  default     = "joaopedrogarciaufsc@gmail.com"
}
