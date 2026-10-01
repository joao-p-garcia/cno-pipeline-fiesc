#!/usr/bin/env sh
#
# O dashboard no Container App. Baixa a camada curada do lake para o disco e
# sobe o Streamlit, assim `app/` e `analise/` rodam sem mudança. Se o download
# falhar o app sobe assim mesmo e explica o que falta.
set -eu

echo "=== baixando a camada curada do lake ==="
export AZCOPY_AUTO_LOGIN_TYPE=MSI
export AZCOPY_MSI_CLIENT_ID="$AZURE_CLIENT_ID"

mkdir -p "$CNO_DATA_DIR/curated"
azcopy sync "$CNO_LAKE_CURATED" "$CNO_DATA_DIR/curated" --recursive \
  || echo "AVISO: sync falhou; subindo assim mesmo, o app se explica"

echo "=== subindo o streamlit ==="
# O ingress termina o TLS, e com CORS e XSRF ligados o Streamlit recusa o
# websocket. O app é público e só de leitura.
exec streamlit run /opt/cno/app/dashboard.py \
  --server.port=8501 \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false \
  --browser.gatherUsageStats=false
