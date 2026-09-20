#!/usr/bin/env sh
#
# O dashboard, no Container App.
#
# Ele baixa a camada curada do lake para o disco local e só então sobe o
# Streamlit. A alternativa seria a extensão `azure` do DuckDB lendo abfss://
# direto — funciona para leitura, mas põe latência de rede em cada consulta e
# exigiria mexer na camada de dados do app. São 191 MB de mesma região: baixar
# custa segundos no boot e mantém `app/` e `analise/` sem uma linha de mudança.
#
# O download NÃO é fatal se falhar. Quando não há camada curada, o próprio app
# explica o que rodar — comportamento que já existe e que vale mais do que um
# container em CrashLoopBackOff sem dizer por quê.
set -eu

echo "=== baixando a camada curada do lake ==="
if azcopy login --identity --identity-client-id "$AZURE_CLIENT_ID"; then
  mkdir -p "$CNO_DATA_DIR/curated"
  azcopy sync "$CNO_LAKE_CURATED" "$CNO_DATA_DIR/curated" --recursive \
    || echo "AVISO: sync falhou; subindo assim mesmo, o app se explica"
else
  echo "AVISO: login por identidade falhou; subindo sem dados"
fi

echo "=== subindo o streamlit ==="
# enableCORS/enableXsrfProtection desligados porque o ingress do Container Apps
# termina o TLS e repassa: com eles ligados o Streamlit rejeita o upgrade de
# websocket e a página fica carregando para sempre. O app é público e somente
# leitura, então não há o que proteger com XSRF aqui.
exec streamlit run /opt/cno/app/dashboard.py \
  --server.port=8501 \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false \
  --browser.gatherUsageStats=false
