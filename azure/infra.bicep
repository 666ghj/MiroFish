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

@description('Localitzacio Azure dels recursos')
param location string = resourceGroup().location

@description('Contrasenya de l-administrador de PostgreSQL')
@secure()
param postgresAdminPassword string

@description('Usuari administrador de PostgreSQL')
param postgresAdminUser string = 'mirofish'

@description('SKU de PostgreSQL (B_Standard_B1ms per dev; GP_Standard_D2s_v3 per pro)')
param postgresSku string = 'B_Standard_B1ms'

@description('Nom del Storage Account existent (o buit per crear-ne un de nou: <projectName>store)')
param storageAccountName string = ''

// Nom efectiu: el parametre si s-especifica, sinó el nom generat
var effectiveStorageAccountName = empty(storageAccountName) ? '${replace(projectName, '-', '')}store' : storageAccountName

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

// Registra el File Share dins l-entorn de Container Apps
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
// Si storageAccountName apunta a un compte existent, Bicep el reconcilia sense
// esborrar els File Shares existents (caddydata, neo4jdata, etc.).
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: effectiveStorageAccountName
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
    shareQuota: 100
    enabledProtocols: 'SMB'
  }
}

// ─── Azure Database for PostgreSQL Flexible Server ────────────────────────────
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
    network: { publicNetworkAccess: 'Enabled' }
    authConfig: { activeDirectoryAuth: 'Disabled', passwordAuth: 'Enabled' }
  }
}

resource postgresDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  name: 'mirofish'
  parent: postgresServer
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

// Regla de firewall per permetre trafic de serveis Azure (inclou Container Apps)
resource postgresFirewallAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = {
  name: 'allow-azure-services'
  parent: postgresServer
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// ─── Outputs (usats pels scripts de deploy) ───────────────────────────────────
@description('URL de login de ACR')
output acrLoginServer string = acr.properties.loginServer

@description('Nom del recurs ACR')
output acrName string = acr.name

@description('ID del Container Apps Environment')
output containerAppsEnvId string = containerAppsEnv.id

@description('Nom del Storage Account')
output storageAccountNameOut string = storageAccount.name

@description('Clau primaria del Storage Account')
output storageAccountKey string = storageAccount.listKeys().keys[0].value

@description('Connection string del Storage Account')
output storageConnectionString string = 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net'

@description('Nom del File Share Azure Files')
output fileShareName string = fileShare.name

@description('FQDN del servidor PostgreSQL')
output postgresHost string = postgresServer.properties.fullyQualifiedDomainName

@description('Usuari administrador de PostgreSQL')
output postgresAdminUserOut string = postgresAdminUser

@description('DATABASE_URL per a la Container App')
output databaseUrl string = 'postgresql+psycopg2://${postgresAdminUser}:${postgresAdminPassword}@${postgresServer.properties.fullyQualifiedDomainName}/mirofish?sslmode=require'
