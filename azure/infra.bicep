// ─────────────────────────────────────────────────────────────────────────────
// MiroFish — Infraestructura base (executar una sola vegada)
//
// Crea:
//   - Azure Container Registry (ACR) per emmagatzemar la imatge Docker
//   - Log Analytics Workspace (NOR0016-C: 90 dies retenció)
//   - Container Apps Environment (plataforma d'execució CTTI)
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
    adminUserEnabled: true    // necessari per a la autenticació des dels scripts
  }
}

// ─── Log Analytics Workspace ──────────────────────────────────────────────────
// NOR0016-C: retenció mínima de logs de seguretat = 90 dies
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${projectName}-logs'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 90
  }
}

// ─── Container Apps Environment ───────────────────────────────────────────────
resource containerAppsEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: '${projectName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    // TODO (ops): descomentar per integrar en VNet Hub-Spoke CTTI
    // vnetConfiguration: {
    //   infrastructureSubnetId: '/subscriptions/.../subnets/container-apps-subnet'
    //   internal: true
    // }
  }
}

// ─── Outputs (usats pels scripts de deploy) ───────────────────────────────────
@description('URL de login de l\'ACR (ex: mirofsihacr.azurecr.io)')
output acrLoginServer string = acr.properties.loginServer

@description('Nom del recurs ACR (per a az acr build)')
output acrName string = acr.name

@description('ID del Container Apps Environment')
output containerAppsEnvId string = containerAppsEnv.id

@description('ID del Log Analytics Workspace')
output logAnalyticsId string = logAnalytics.id
