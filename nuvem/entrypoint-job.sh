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
# Autenticação por identidade gerenciada, via ambiente e não por `azcopy login`.
#
# O `azcopy login --identity` falha aqui com "failed to get keyring during
# saving token, operation not permitted": ele quer persistir o token num
# keyring do sistema (Secret Service), que não existe num container. Custou uma
# execução inteira para aparecer, porque só acontece *depois* das quatro etapas.
#
# Com estas duas variáveis o azcopy autentica por conta própria a cada operação
# e não tenta guardar nada. O MSI_CLIENT_ID é obrigatório porque a réplica pode
# ter mais de uma identidade atribuída e ele não escolhe sozinho.
export AZCOPY_AUTO_LOGIN_TYPE=MSI
export AZCOPY_MSI_CLIENT_ID="$AZURE_CLIENT_ID"

# --delete-destination=false é deliberado: snapshot antigo no lake não é lixo,
# é histórico. É a mesma postura que a camada raw tem localmente — o que já foi
# publicado não se apaga porque chegou coisa nova.
azcopy sync "$CNO_DATA_DIR/curated" "$CNO_LAKE_CURATED" \
  --recursive \
  --delete-destination=false

echo "=== fim ==="
