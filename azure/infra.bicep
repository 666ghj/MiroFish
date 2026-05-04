// ─────────────────────────────────────────────────────────────────────────────
// MiroFish — Infraestructura base (executar una sola vegada)
//
// Crea:
//   - Azure Container Registry (ACR)
//   - Container Apps Environment
//   - Storage Account + File Share (muntat al container per a dades OASIS)
//   - Azure Database for PostgreSQL Flexible Server
//
// Executar amb: azure/1-infra.sh
// ─────────────────────────────────────────────────────────────────────────────

@description('Nom base del projecte')
param projectName string = 'mirofish'

@description('Localització Azure dels recursos')
param location string = resourceGroup().location

@description('Contrasenya de l\'administrador de PostgreSQL')
@secure()
param postgresAdminPassword string

@description('Nom de l\'usuari administrador de PostgreSQL')
param postgresAdminUser string = 'mirofish'

@description('SKU de PostgreSQL (B_Standard_B1ms per dev; GP_Standard_D2s_v3 per pro)')
param postgresSku string = 'B_Standard_B1ms'

// ─── Azure Container Registry ─────────────────────────────────────────────────
resource acr 'Microsoft.ContainerRegistry/registries@2023-01-01-preview' = {
  name: '${projectName}acr'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: true }
}

// ─── Container Apps Environment ───────────────────────────────────────────────
// Necessita el Storage Account abans per poder registrar el file share com a volum
resource containerAppsEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: '${projectName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
  }
  dependsOn: [storageAccount]
}

// Registra el File Share dins l'entorn de Container Apps
resource envStorage 'Microsoft.App/managedEnvironments/storages@2023-05-01' = {
  name: 'uploads'
  parent: containerAppsEnv
  properties: {
    azureFile: {
      accountName: storageAccount.name
      accountKey: storageAccount.listKeys().keys[0].value
      shareName: fileShare.name
      accessMode: 'ReadWrite'
    }
  }
}

// ─── Storage Account + File Share (dades OASIS persistents) ──────────────────
// Azure Files és necessari per a:
//   - uploads/simulations/  (SQLite DBs, JSONL, IPC files de les simulacions OASIS)
//   - uploads/projects/     (fitxers pujats per l'usuari)
// Standard LRS: suficient per a escenaris non-HA
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: '${replace(projectName, '-', '')}store'  // sense guions, màx 24 chars
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-01-01' = {
  name: 'default'
  parent: storageAccount
}

resource fileShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-01-01' = {
  name: 'mirofish-uploads'
  parent: fileService
  properties: {
    shareQuota: 100  // GB; augmenta si les simulacions creixen
    enabledProtocols: 'SMB'
  }
}

// ─── Azure Database for PostgreSQL Flexible Server ────────────────────────────
// Flexible Server és el recomanat per a desplegaments nous (Single Server deprecated)
// La base de dades 'mirofish' es crea automàticament
resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: '${projectName}-pg'
  location: location
  sku: {
    name: postgresSku
    tier: startsWith(postgresSku, 'B_') ? 'Burstable' : 'GeneralPurpose'
  }
  properties: {
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    version: '16'
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    // Accés públic desactivat; usa firewall rule per a Container Apps o VNet
    network: { publicNetworkAccess: 'Enabled' }
    authConfig: { activeDirectoryAuth: 'Disabled', passwordAuth: 'Enabled' }
  }
}

resource postgresDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  name: 'mirofish'
  parent: postgresServer
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

// Regla de firewall per permetre tràfic de serveis Azure (inclou Container Apps)
resource postgresFirewallAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = {
  name: 'allow-azure-services'
  parent: postgresServer
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// ─── Outputs (usats pels scripts de deploy) ───────────────────────────────────
@description('URL de login de l\'ACR')
output acrLoginServer string = acr.properties.loginServer

@description('Nom del recurs ACR')
output acrName string = acr.name

@description('ID del Container Apps Environment')
output containerAppsEnvId string = containerAppsEnv.id

@description('Nom del Storage Account')
output storageAccountName string = storageAccount.name

@description('Clau primària del Storage Account (per a AZURE_STORAGE_CONNECTION_STRING)')
@sensitive()
output storageAccountKey string = storageAccount.listKeys().keys[0].value

@description('Connection string del Storage Account (per a AZURE_STORAGE_CONNECTION_STRING)')
@sensitive()
output storageConnectionString string = 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net'

@description('Nom del File Share d\'Azure Files')
output fileShareName string = fileShare.name

@description('FQDN del servidor PostgreSQL')
output postgresHost string = postgresServer.properties.fullyQualifiedDomainName

@description('Usuari administrador de PostgreSQL')
output postgresAdminUser string = postgresAdminUser

@description('DATABASE_URL per a la Container App (postgresql+psycopg2://...)')
@sensitive()
output databaseUrl string = 'postgresql+psycopg2://${postgresAdminUser}:${postgresAdminPassword}@${postgresServer.properties.fullyQualifiedDomainName}/mirofish?sslmode=require'
