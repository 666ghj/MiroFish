// ─────────────────────────────────────────────────────────────────────────────
// MiroFish — Infraestructura base (executar una sola vegada)
//
// Crea:
//   - Azure Container Registry (ACR) per emmagatzemar la imatge Docker
//   - Container Apps Environment (plataforma d'execució)
//
// Executar amb: azure/1-infra.sh
// ─────────────────────────────────────────────────────────────────────────────

@description('Nom base del projecte')
param projectName string = 'mirofish'

@description('Localització Azure dels recursos')
param location string = resourceGroup().location

// ─── Azure Container Registry ─────────────────────────────────────────────────
// SKU Basic: suficient per a imatges privades sense geo-replicació
resource acr 'Microsoft.ContainerRegistry/registries@2023-01-01-preview' = {
  name: '${projectName}acr'   // ACR no admet guions, tot minúscula
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true    // necessari per a l'autenticació des dels scripts
  }
}

// ─── Container Apps Environment ───────────────────────────────────────────────
resource containerAppsEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: '${projectName}-env'
  location: location
  properties: {}
  // TODO (ops): afegir appLogsConfiguration amb Log Analytics si es vol observabilitat
  // TODO (ops): descomentar per integrar en VNet Hub-Spoke
  // vnetConfiguration: {
  //   infrastructureSubnetId: '/subscriptions/.../subnets/container-apps-subnet'
  //   internal: true
  // }
}

// ─── Outputs (usats pels scripts de deploy) ───────────────────────────────────
@description('URL de login de l\'ACR (ex: mirofsihacr.azurecr.io)')
output acrLoginServer string = acr.properties.loginServer

@description('Nom del recurs ACR')
output acrName string = acr.name

@description('ID del Container Apps Environment')
output containerAppsEnvId string = containerAppsEnv.id
