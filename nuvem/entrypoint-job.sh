#!/usr/bin/env sh
#
# O pipeline no Container Apps Job, na mesma sequência da DAG. O disco da
# réplica nasce vazio, então o raw é restaurado do lake antes e as camadas são
# publicadas depois. Sem isso a idempotência por ETag se perde e o snapshot some
# quando a Receita publica o próximo.
set -eu

export AZCOPY_AUTO_LOGIN_TYPE=MSI
export AZCOPY_MSI_CLIENT_ID="$AZURE_CLIENT_ID"

RAW_LOCAL="$CNO_DATA_DIR/raw"
PY=/opt/cno/.venv/bin/python

# --- restauração ----------------------------------------------------------

echo "=== restaurando o raw do lake ==="
mkdir -p "$RAW_LOCAL/_manifests"
ANTERIOR=""

# O `latest.json` diz qual snapshot restaurar sem listar o lake inteiro.
if azcopy copy "$CNO_LAKE_RAW/_manifests/latest.json" "$RAW_LOCAL/_manifests/latest.json"; then
  ANTERIOR=$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['snapshot_id'])" \
    "$RAW_LOCAL/_manifests/latest.json")
  echo "último snapshot no lake: $ANTERIOR"

  azcopy copy "$CNO_LAKE_RAW/_manifests/$ANTERIOR.json" "$RAW_LOCAL/_manifests/"

  # Sem o zip, que não entra na conferência de integridade.
  azcopy sync "$CNO_LAKE_RAW/snapshot_date=$ANTERIOR" "$RAW_LOCAL/snapshot_date=$ANTERIOR" \
    --recursive --exclude-pattern="*.zip" --delete-destination=false
else
  echo "lake ainda não tem raw: esta é a primeira execução"
fi

# --- o pipeline ------------------------------------------------------------

echo "=== cno extract ==="
RESUMO=$(cno extract --json | tail -1)
echo "$RESUMO"
ATUAL=$("$PY" -c "import json,sys;print(json.loads(sys.argv[1])['snapshot_id'])" "$RESUMO")

if [ -n "$ANTERIOR" ] && [ "$ANTERIOR" != "$ATUAL" ]; then
  # Publicação nova. O snapshot antigo já está no lake e ocupa 1,4 GB do disco.
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

echo "=== publicando raw, staging e curated no lake ==="
# Snapshots antigos não são apagados, ficam como histórico.
#
# CNO_LAKE_STAGING é opcional porque a imagem pode rodar antes do terraform
# apply que cria a variável, e com `set -u` a referência derrubaria o script.
azcopy sync "$RAW_LOCAL" "$CNO_LAKE_RAW" --recursive --delete-destination=false
if [ -n "${CNO_LAKE_STAGING:-}" ]; then
  azcopy sync "$CNO_DATA_DIR/staging" "$CNO_LAKE_STAGING" --recursive --delete-destination=false
else
  echo "CNO_LAKE_STAGING não definida (terraform apply pendente); pulando a staging"
fi
azcopy sync "$CNO_DATA_DIR/curated" "$CNO_LAKE_CURATED" --recursive --delete-destination=false

echo "=== fim ==="
