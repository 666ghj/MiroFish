#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 2-build-deploy.sh — Build Docker + push a ACR + deploy Container App
#
# Executar a cada nova versió de l'aplicació.
# Requereix que 1-infra.sh hagi estat executat prèviament.
#
# Prerequisites:
#   - az login executat
#   - azure/config.sh existent i configurat
#   - Docker instal·lat i en execució
#   - Infraestructura creada (azure/1-infra.sh)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Carregar configuració ─────────────────────────────────────────────────────
CONFIG_FILE="${SCRIPT_DIR}/config.sh"
if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "ERROR: No s'ha trobat azure/config.sh"
 echo "       Còpia l'exemple: cp azure/config.sh.example azure/config.sh"
  exit 1
fi
# shellcheck source=config.sh.example
source "$CONFIG_FILE"

# ── Validar variables obligatòries ───────────────────────────────────────────
REQUIRED_VARS=(
  AZURE_SUBSCRIPTION_ID RESOURCE_GROUP PROJECT_NAME
  DEMO_PASSWORD SECRET_KEY LLM_API_KEY LLM_BASE_URL LLM_MODEL_NAME
  DATABASE_URL STORAGE_CONNECTION_STRING
)
# Validate graph backend config
GRAPH_BACKEND="${GRAPH_BACKEND:-zep}"
if [[ "$GRAPH_BACKEND" == "zep" && -z "${ZEP_API_KEY:-}" ]]; then
  echo "ERROR: ZEP_API_KEY is required when GRAPH_BACKEND=zep"
  exit 1
fi
if [[ "$GRAPH_BACKEND" == "graphiti" && -z "${NEO4J_PASSWORD:-}" ]]; then
  echo "ERROR: NEO4J_PASSWORD is required when GRAPH_BACKEND=graphiti"
  exit 1
fi
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: La variable $var no està configurada a config.sh"
    exit 1
  fi
done

ACR_NAME="${PROJECT_NAME}acr"

# ── Seleccionar subscripció ───────────────────────────────────────────────────
echo "→ Seleccionant subscripció..."
az account set --subscription "$AZURE_SUBSCRIPTION_ID"

# ── Obtenir dades de la infraestructura existent ──────────────────────────────
echo "→ Obtenint dades de la infraestructura..."

ACR_LOGIN_SERVER=$(az acr show \
  --name "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query loginServer --output tsv)

ENV_ID=$(az containerapp env show \
  --name "${PROJECT_NAME}-env" \
  --resource-group "$RESOURCE_GROUP" \
  --query id --output tsv)

if [[ -z "$ACR_LOGIN_SERVER" || -z "$ENV_ID" ]]; then
  echo "ERROR: No s'ha trobat la infraestructura. Executa primer: bash azure/1-infra.sh"
  exit 1
fi

# ── Generar tag de versió ─────────────────────────────────────────────────────
# Format: <git-sha-curt>-<timestamp> per a traçabilitat
GIT_SHA=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo "nogit")
TIMESTAMP=$(date +%Y%m%d%H%M)
IMAGE_TAG="${GIT_SHA}-${TIMESTAMP}"
FULL_IMAGE="${ACR_LOGIN_SERVER}/${PROJECT_NAME}:${IMAGE_TAG}"
LATEST_IMAGE="${ACR_LOGIN_SERVER}/${PROJECT_NAME}:latest"

echo ""
echo "════════════════════════════════════════════════════════"
echo " MiroFish — Build & Deploy"
echo "════════════════════════════════════════════════════════"
echo " ACR            : $ACR_LOGIN_SERVER"
echo " Imatge         : ${PROJECT_NAME}:${IMAGE_TAG}"
echo " Container Env  : ${PROJECT_NAME}-env"
echo "════════════════════════════════════════════════════════"
echo ""

# ── Login a l'ACR ─────────────────────────────────────────────────────────────
echo "→ Login a l'ACR..."
az acr login --name "$ACR_NAME"

# ── Build de la imatge Docker ─────────────────────────────────────────────────
echo "→ Build de la imatge Docker..."
docker build \
  ${NO_CACHE:+--no-cache} \
  --tag "$FULL_IMAGE" \
  --tag "$LATEST_IMAGE" \
  "$REPO_ROOT"
echo "   ✓ Build completat"

# ── Push de la imatge a l'ACR ─────────────────────────────────────────────────
echo "→ Push a l'ACR ($FULL_IMAGE)..."
docker push "$FULL_IMAGE"
docker push "$LATEST_IMAGE"
echo "   ✓ Push completat"

# ── Obtenir credencials ACR per al Bicep ─────────────────────────────────────
echo "→ Obtenint credencials ACR..."
ACR_USERNAME=$(az acr credential show \
  --name "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query username --output tsv)
ACR_PASSWORD=$(az acr credential show \
  --name "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "passwords[0].value" --output tsv)

# ── Desplegar Container App via Bicep ─────────────────────────────────────────
echo "→ Desplegant Container App..."
DEPLOY_OUTPUT=$(az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "${SCRIPT_DIR}/container-app.bicep" \
  --parameters \
      projectName="$PROJECT_NAME" \
      containerAppsEnvId="$ENV_ID" \
      containerImage="$FULL_IMAGE" \
      acrLoginServer="$ACR_LOGIN_SERVER" \
      acrUsername="$ACR_USERNAME" \
      acrPassword="$ACR_PASSWORD" \
      demoPassword="$DEMO_PASSWORD" \
      llmApiKey="$LLM_API_KEY" \
      llmBoostApiKey="${LLM_BOOST_API_KEY:-}" \
      llmProvider="${LLM_PROVIDER:-}" \
      zepApiKey="${ZEP_API_KEY:-}" \
      neo4jPassword="${NEO4J_PASSWORD:-}" \
      neo4jUri="${NEO4J_URI:-bolt://localhost:7687}" \
      neo4jUser="${NEO4J_USER:-neo4j}" \
      neo4jDatabase="${NEO4J_DATABASE:-neo4j}" \
      graphBackend="${GRAPH_BACKEND:-zep}" \
      secretKey="$SECRET_KEY" \
      llmBaseUrl="$LLM_BASE_URL" \
      llmModelName="$LLM_MODEL_NAME" \
      llmBoostBaseUrl="${LLM_BOOST_BASE_URL:-}" \
      llmBoostModelName="${LLM_BOOST_MODEL_NAME:-}" \
      llmEmbedApiKey="${LLM_EMBED_API_KEY:-}" \
      llmEmbedBaseUrl="${LLM_EMBED_BASE_URL:-}" \
      llmEmbedModelName="${LLM_EMBED_MODEL_NAME:-}" \
      llmSmallApiKey="${LLM_SMALL_API_KEY:-}" \
      llmSmallBaseUrl="${LLM_SMALL_BASE_URL:-}" \
      llmSmallModelName="${LLM_SMALL_MODEL_NAME:-}" \
      oasisDefaultMaxRounds="${OASIS_DEFAULT_MAX_ROUNDS:-10}" \
      reportAgentMaxToolCalls="${REPORT_AGENT_MAX_TOOL_CALLS:-5}" \
      reportAgentMaxReflectionRounds="${REPORT_AGENT_MAX_REFLECTION_ROUNDS:-2}" \
      reportAgentTemperature="${REPORT_AGENT_TEMPERATURE:-0.5}" \
      storageConnectionString="${STORAGE_CONNECTION_STRING:-}" \
      storageAccountName="${STORAGE_ACCOUNT_NAME:-}" \
      databaseUrl="${DATABASE_URL:-}" \
  --output json)

FQDN=$(echo "$DEPLOY_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['properties']['outputs']['containerAppFqdn']['value'])")

echo ""
echo "════════════════════════════════════════════════════════"
echo " Deploy completat!"
echo "════════════════════════════════════════════════════════"
echo " URL de l'aplicació: https://$FQDN"
echo " Imatge desplegada : $FULL_IMAGE"
echo "════════════════════════════════════════════════════════"
