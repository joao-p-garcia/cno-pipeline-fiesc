#!/usr/bin/env sh
#
# Bootstrap do backend de estado do Terraform. O state precisa de um storage
# account que o próprio Terraform ainda não criou. É imperativo em vez de um
# segundo root module, que só empurraria "onde mora o state do state" um degrau
# adiante. Idempotente. Rodar com `sh nuvem/bootstrap.sh`.
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
# Sem chave de conta para vazar, a autenticação é sempre Entra ID, e por isso o
# provider precisa de storage_use_azuread. Sem acesso público porque o state
# contém tudo que a infraestrutura sabe.
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
# O state é o único arquivo do projeto que não se recupera reprocessando.
az storage account blob-service-properties update \
  --account-name "$CONTA" \
  --resource-group "$GRUPO" \
  --enable-versioning true \
  --enable-delete-retention true \
  --delete-retention-days 7 \
  --output none

echo "==> papel de dado para o usuário corrente"
# Ser Owner da assinatura não dá acesso ao conteúdo dos blobs. Control plane e
# data plane são separados na Azure, e ler o state exige papel de dado.
ESCOPO="/subscriptions/$ASSINATURA/resourceGroups/$GRUPO/providers/Microsoft.Storage/storageAccounts/$CONTA"
az role assignment create \
  --assignee-object-id "$USUARIO" \
  --assignee-principal-type User \
  --role "Storage Blob Data Contributor" \
  --scope "$ESCOPO" \
  --output none 2>/dev/null || echo "    já atribuído"

echo "==> esperando o RBAC propagar"
# Atribuição de papel não vale na mesma hora. Sem a espera o próximo comando
# falha com 403 de forma intermitente.
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
