#!/usr/bin/env sh
#
# A esteira, no Container Apps Job.
#
# É a mesma sequência que a DAG encadeia e que qualquer pessoa roda na mão. A
# DAG não veio junto de propósito: aqui quem orquestra é o cron do próprio
# recurso, e reproduzir uma falha continua sendo copiar e colar um comando.
#
# `set -e` basta para encadear: se uma etapa falhar, o script sai com o código
# dela e a réplica termina em falha — que é exatamente o que o job precisa ver.
set -eu

echo "=== cno extract ==="
cno extract --json
echo "=== cno transform ==="
cno transform --json
echo "=== cno validate ==="
cno validate --json
echo "=== cno curate ==="
cno curate --json

echo "=== publicando a camada curada no lake ==="
# Login por identidade gerenciada. O --identity-client-id é obrigatório porque
# a réplica pode ter mais de uma identidade atribuída e o azcopy não escolhe.
azcopy login --identity --identity-client-id "$AZURE_CLIENT_ID"

# --delete-destination=false é deliberado: snapshot antigo no lake não é lixo,
# é histórico. É a mesma postura que a camada raw tem localmente — o que já foi
# publicado não se apaga porque chegou coisa nova.
azcopy sync "$CNO_DATA_DIR/curated" "$CNO_LAKE_CURATED" \
  --recursive \
  --delete-destination=false

echo "=== fim ==="
