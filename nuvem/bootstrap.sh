#!/usr/bin/env sh
#
# Bootstrap do backend de estado do Terraform.
#
# Existe porque o Terraform precisa guardar o state num storage account que ele
# próprio ainda não criou — o ouroboros clássico. A saída é resolver esta parte
# de forma imperativa, uma vez, e deixar o Terraform assumir dali em diante.
#
# É deliberadamente imperativo, e não um segundo root module: um módulo que cria
# o backend do outro teria um state próprio a proteger, e aí a pergunta "onde
# mora o state do state" só anda um degrau.
#
# Idempotente: rodar de novo não estraga nada e não recria o que já existe.
#
#   sh nuvem/bootstrap.sh
#
set -eu

REGIAO="${REGIAO:-brazilsouth}"
GRUPO="${GRUPO:-rg-cno-tfstate}"
CONTA="${CONTA:-stcnotfstatefiesc}"
CONTAINER="${CONTAINER:-tfstate}"

echo "==> assinatura"
ASSINATURA=$(az account show --query id -o tsv)
USUARIO=$(az ad signed-in-user show --query id -o tsv)
echo "    $(az account show --query name -o tsv) ($ASSINATURA)"

echo "==> grupo de recursos $GRUPO em $REGIAO"
az group create --name "$GRUPO" --location "$REGIAO" --output none

echo "==> storage account $CONTA"
# --allow-shared-key-access false: nenhuma chave de conta existe para vazar, nem
#   no .env de alguém nem na saída de um `terraform show`. A autenticação é
#   sempre Entra ID, e é por isso que o provider precisa de storage_use_azuread.
# --allow-blob-public-access false: state de Terraform contém, por natureza,
#   tudo que a infraestrutura sabe.
if az storage account show --name "$CONTA" --resource-group "$GRUPO" --output none 2>/dev/null; then
  echo "    já existe"
else
  az storage account create \
    --name "$CONTA" \
    --resource-group "$GRUPO" \
    --location "$REGIAO" \
    --sku Standard_LRS \
    --kind StorageV2 \
    --min-tls-version TLS1_2 \
    --allow-blob-public-access false \
    --allow-shared-key-access false \
    --output none
fi

echo "==> versionamento e retenção no blob"
# O state é o único arquivo do projeto cuja perda não se recupera reprocessando.
# Versionamento e soft delete são o seguro barato contra um apply infeliz.
az storage account blob-service-properties update \
  --account-name "$CONTA" \
  --resource-group "$GRUPO" \
  --enable-versioning true \
  --enable-delete-retention true \
  --delete-retention-days 7 \
  --output none

echo "==> papel de dado para o usuário corrente"
# Este é o passo que surpreende quem vem do GCP: ser Owner da assinatura NÃO dá
# acesso ao conteúdo dos blobs. Control plane e data plane são separados na
# Azure, e ler o state exige um papel de dado explícito.
ESCOPO="/subscriptions/$ASSINATURA/resourceGroups/$GRUPO/providers/Microsoft.Storage/storageAccounts/$CONTA"
az role assignment create \
  --assignee-object-id "$USUARIO" \
  --assignee-principal-type User \
  --role "Storage Blob Data Contributor" \
  --scope "$ESCOPO" \
  --output none 2>/dev/null || echo "    já atribuído"

echo "==> esperando o RBAC propagar"
# Atribuição de papel não vale na mesma hora. Sem esta espera, o próximo comando
# falha com 403 de forma intermitente — o pior tipo de falha para depurar.
TENTATIVA=1
while [ "$TENTATIVA" -le 20 ]; do
  if az storage container exists \
       --name "$CONTAINER" \
       --account-name "$CONTA" \
       --auth-mode login \
       --output none 2>/dev/null; then
    echo "    pronto na tentativa $TENTATIVA"
    break
  fi
  if [ "$TENTATIVA" -eq 20 ]; then
    echo "    ERRO: RBAC não propagou em ~100s; rode o script de novo" >&2
    exit 1
  fi
  TENTATIVA=$((TENTATIVA + 1))
  sleep 5
done

echo "==> container $CONTAINER"
az storage container create \
  --name "$CONTAINER" \
  --account-name "$CONTA" \
  --auth-mode login \
  --output none

echo
echo "pronto. o backend abaixo já está em nuvem/terraform/backend.tf:"
echo
echo "  resource_group_name  = \"$GRUPO\""
echo "  storage_account_name = \"$CONTA\""
echo "  container_name       = \"$CONTAINER\""
echo "  key                  = \"cno.tfstate\""
echo "  use_azuread_auth     = true"
