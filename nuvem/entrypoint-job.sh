#!/usr/bin/env sh
#
# A esteira, no Container Apps Job.
#
# É a mesma sequência que a DAG encadeia e que qualquer pessoa roda na mão. A
# DAG não veio junto de propósito: aqui quem orquestra é o cron do próprio
# recurso, e reproduzir uma falha continua sendo copiar e colar um comando.
#
# O que existe aqui e não existe na DAG é a ponte com o lake, nas duas pontas:
# restaurar o raw antes e publicar depois. Ela existe porque o disco desta
# réplica nasce vazio e morre com ela — e sem a ponte o pipeline perderia duas
# propriedades que foram construídas de propósito:
#
# 1. **A camada raw preserva o que a fonte não preserva.** O share da Receita
#    sempre aponta para a publicação mais recente e não tem histórico
#    (`config.py`). Se o snapshot de hoje não for para algum lugar durável, ele
#    deixa de existir no mundo quando a Receita publicar o próximo.
#
# 2. **A idempotência por ETag.** O `cno extract` decide se precisa baixar
#    comparando o ETag da fonte com o manifesto *local*. Em disco efêmero esse
#    manifesto nunca existe, então sem restauração o pipeline rebaixaria 315 MB
#    da Receita todo dia, mesmo sem publicação nova. Não custa dinheiro, mas é
#    bater num serviço público à toa — e é a regressão de um comportamento que
#    o projeto construiu de propósito.
#
set -eu

export AZCOPY_AUTO_LOGIN_TYPE=MSI
export AZCOPY_MSI_CLIENT_ID="$AZURE_CLIENT_ID"

RAW_LOCAL="$CNO_DATA_DIR/raw"
PY=/opt/cno/.venv/bin/python

# --- restauração ----------------------------------------------------------

echo "=== restaurando o raw do lake ==="
mkdir -p "$RAW_LOCAL/_manifests"
ANTERIOR=""

# O ponteiro `latest.json` tem alguns bytes e diz qual snapshot restaurar —
# por isso ele existe, e é o que evita listar e ordenar o lake inteiro.
if azcopy copy "$CNO_LAKE_RAW/_manifests/latest.json" "$RAW_LOCAL/_manifests/latest.json"; then
  ANTERIOR=$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['snapshot_id'])" \
    "$RAW_LOCAL/_manifests/latest.json")
  echo "último snapshot no lake: $ANTERIOR"

  azcopy copy "$CNO_LAKE_RAW/_manifests/$ANTERIOR.json" "$RAW_LOCAL/_manifests/"

  # Só o snapshot corrente, e sem o zip. O zip é arquivo histórico: não entra
  # na conferência de integridade (que olha os CSVs contra o manifesto) e
  # custaria 315 MB de download por dia sem serventia nenhuma.
  azcopy sync "$CNO_LAKE_RAW/snapshot_date=$ANTERIOR" "$RAW_LOCAL/snapshot_date=$ANTERIOR" \
    --recursive --exclude-pattern="*.zip" --delete-destination=false
else
  echo "lake ainda não tem raw: esta é a primeira execução"
fi

# --- a esteira ------------------------------------------------------------

echo "=== cno extract ==="
# O JSON no stdout é o contrato que a etapa publica para quem a orquestra —
# a DAG usa o mesmo. Aqui ele serve para saber se houve publicação nova.
RESUMO=$(cno extract --json | tail -1)
echo "$RESUMO"
ATUAL=$("$PY" -c "import json,sys;print(json.loads(sys.argv[1])['snapshot_id'])" "$RESUMO")

if [ -n "$ANTERIOR" ] && [ "$ANTERIOR" != "$ATUAL" ]; then
  # Publicação nova: o snapshot restaurado virou peso morto de 1,4 GB num disco
  # que precisa comportar ~4 GB de pico. Ele já está no lake; sai daqui.
  echo "publicação nova ($ANTERIOR -> $ATUAL); liberando o snapshot antigo do disco"
  rm -rf "$RAW_LOCAL/snapshot_date=$ANTERIOR"
fi

echo "=== cno transform ==="
cno transform --json
echo "=== cno validate ==="
cno validate --json
echo "=== cno curate ==="
cno curate --json

# --- publicação -----------------------------------------------------------

echo "=== publicando raw e curated no lake ==="
# Autenticação por identidade gerenciada vem do ambiente, e não de
# `azcopy login`: dentro de um container o login tenta persistir o token num
# keyring do sistema que não existe, e falha com "operation not permitted" —
# depois das quatro etapas terem rodado, que é o pior momento para descobrir.
#
# --delete-destination=false é deliberado nas duas: snapshot antigo no lake não
# é lixo, é histórico. É a mesma postura que a camada raw tem localmente.
azcopy sync "$RAW_LOCAL" "$CNO_LAKE_RAW" --recursive --delete-destination=false
azcopy sync "$CNO_DATA_DIR/curated" "$CNO_LAKE_CURATED" --recursive --delete-destination=false

echo "=== fim ==="
