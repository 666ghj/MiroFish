#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 1-infra.sh — Crea la infraestructura base de MiroFish a Azure
#
# Executa UNA SOLA VEGADA (o si vols recrear la infraestructura).
# Idempotent: pot executar-se múltiples vegades sense errors.
#
# Prerequisites:
#   - az login executat
#   - azure/config.sh existent (còpia de config.sh.example)
#
# Crea:
#   - Resource Group: rg_mirofish
#   - Azure Container Registry (ACR): ${PROJECT_NAME}acr
#   - Log Analytics Workspace: ${PROJECT_NAME}-logs
#   - Container Apps Environment: ${PROJECT_NAME}-env
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Carregar configuració ─────────────────────────────────────────────────────
#CONFIG_FILE="${SCRIPT_DIR}/config.sh"
#if [[ ! -f "$CONFIG_FILE" ]]; then
#  echo "ERROR: No s'ha trobat azure/config.sh"
#  echo "       Còpia l'exemple: cp azure/config.sh.example azure/config.sh"
#  echo "       Després omple els valors i torna a executar."
#  exit 1
#fi
# shellcheck source=config.sh.example
#source "$CONFIG_FILE"

# ── Validar variables obligatòries ───────────────────────────────────────────
REQUIRED_VARS=(
  AZURE_SUBSCRIPTION_ID AZURE_LOCATION
  RESOURCE_GROUP PROJECT_NAME
)
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: La variable $var no està configurada a config.sh"
    exit 1
  fi
done

ACR_NAME="${PROJECT_NAME}acr"

echo "════════════════════════════════════════════════════════"
echo " MiroFish — Creació d'infraestructura Azure"
echo "════════════════════════════════════════════════════════"
echo " Subscripció : $AZURE_SUBSCRIPTION_ID"
echo " Localització: $AZURE_LOCATION"
echo " Grup recurs : $RESOURCE_GROUP"
echo " ACR         : $ACR_NAME"
echo "════════════════════════════════════════════════════════"
echo ""

# ── Seleccionar subscripció ───────────────────────────────────────────────────
echo "→ Seleccionant subscripció..."
az account set --subscription "$AZURE_SUBSCRIPTION_ID"

# ── Registrar proveïdors necessaris ──────────────────────────────────────────
echo "→ Registrant proveïdors Azure (pot trigar uns minuts la primera vegada)..."
az provider register --namespace Microsoft.App            --wait
az provider register --namespace Microsoft.OperationalInsights --wait
az provider register --namespace Microsoft.ContainerRegistry  --wait

# ── Crear Resource Group ──────────────────────────────────────────────────────
echo "→ Creant Resource Group '$RESOURCE_GROUP'..."
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$AZURE_LOCATION" \
  --output none
echo "   ✓ Resource Group llest"

# ── Desplegar infraestructura via Bicep ──────────────────────────────────────
echo "→ Desplegant infraestructura (ACR + Log Analytics + Container Apps Env)..."
INFRA_OUTPUT=$(az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "${SCRIPT_DIR}/infra.bicep" \
  --parameters \
      projectName="$PROJECT_NAME" \
      location="$AZURE_LOCATION" \
  --output json)

# Extreure outputs del desplegament
ACR_LOGIN_SERVER=$(echo "$INFRA_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['properties']['outputs']['acrLoginServer']['value'])")
ACR_NAME_OUT=$(echo "$INFRA_OUTPUT"    | python3 -c "import sys,json; print(json.load(sys.stdin)['properties']['outputs']['acrName']['value'])")
ENV_ID=$(echo "$INFRA_OUTPUT"          | python3 -c "import sys,json; print(json.load(sys.stdin)['properties']['outputs']['containerAppsEnvId']['value'])")

echo ""
echo "════════════════════════════════════════════════════════"
echo " Infraestructura creada correctament!"
echo "════════════════════════════════════════════════════════"
echo " ACR Login Server     : $ACR_LOGIN_SERVER"
echo " Container Apps Env ID: $ENV_ID"
echo ""
echo " Proper pas: bash azure/2-build-deploy.sh"
echo "════════════════════════════════════════════════════════"
