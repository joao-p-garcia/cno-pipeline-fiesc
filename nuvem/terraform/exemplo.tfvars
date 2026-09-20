# Copie para `terraform.tfvars` e preencha. Esse nome o Terraform lê sozinho,
# e o .gitignore deste diretório o mantém fora do repositório.
#
# Onde achar cada um:
#
#   assinatura       az account show --query id -o tsv
#   owner_id_github  curl -s https://api.github.com/repos/<dono>/<repo> | jq .owner.id
#   repo_id_github   curl -s https://api.github.com/repos/<dono>/<repo> | jq .id
#
# Os dois IDs do GitHub entram no subject da credencial federada porque este
# repositório emite o claim OIDC no formato immutable. Ver identidades.tf.

assinatura      = "00000000-0000-0000-0000-000000000000"
email_alerta    = "voce@exemplo.com"
owner_id_github = "00000000"
repo_id_github  = "0000000000"
