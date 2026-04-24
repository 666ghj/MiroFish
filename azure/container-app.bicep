// ─────────────────────────────────────────────────────────────────────────────
// MiroFish — Azure Container App
// Segueix les directrius CTTI per a desplegament d'aplicacions a Azure
// (DA/TM: Azure Container Apps com a plataforma de desplegament de contenidors)
//
// Paràmetres que l'equip d'ops ha de proporcionar en desplegar:
//   Secrets (@secure): demoPassword, llmApiKey, llmBoostApiKey, zepApiKey, secretKey
//   Valors:            containerImage, llmBaseUrl, llmModelName, llmBoostBaseUrl,
//                      llmBoostModelName, oasisDefaultMaxRounds,
//                      reportAgentMaxToolCalls, reportAgentMaxReflectionRounds,
//                      reportAgentTemperature
//
// Extensions pendents per a l'equip d'operacions:
//   - DNS: afegir CNAME a *.intranet.gencat.cat (PRE) / *.gencat.cat (PRO)
//   - Xarxa: integrar en VNet Hub-Spoke + Private Link per a serveis interns
//     (descomentar el bloc vnetConfiguration a l'entorn)
//   - TLS: certificat gestionat via Container Apps o Azure Front Door
//   - ingress.external: canviar a false per a accés exclusiu per intranet
// ─────────────────────────────────────────────────────────────────────────────

@description('Nom base del projecte (es fa servir per als noms dels recursos)')
param projectName string = 'mirofish'

@description('Localització Azure dels recursos')
param location string = resourceGroup().location

@description('Imatge Docker completa (registry/imatge:tag)')
param containerImage string

// ─── Paràmetres secrets (@secure — mai visibles als logs de desplegament) ────

@description('Contrasenya de l\'usuari demo')
@secure()
param demoPassword string

@description('Clau de l\'API LLM principal (OpenAI-compatible)')
@secure()
param llmApiKey string

@description('Clau de l\'API LLM acceleradora (opcional, deixar buit si no s\'usa)')
@secure()
param llmBoostApiKey string = ''

@description('Clau de l\'API Zep Cloud')
@secure()
param zepApiKey string

@description('SECRET_KEY de Flask per a JWT (generar amb: python -c "import secrets; print(secrets.token_hex(32))")')
@secure()
param secretKey string

// ─── Paràmetres LLM principal ─────────────────────────────────────────────────

@description('URL base de l\'API LLM principal')
param llmBaseUrl string = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

@description('Nom del model LLM principal')
param llmModelName string = 'qwen-plus'

// ─── Paràmetres LLM accelerador (opcionals) ──────────────────────────────────

@description('URL base de l\'API LLM acceleradora (opcional)')
param llmBoostBaseUrl string = ''

@description('Nom del model LLM accelerador (opcional)')
param llmBoostModelName string = ''

// ─── Paràmetres de simulació OASIS ───────────────────────────────────────────

@description('Nombre màxim de rondes per a la simulació OASIS')
param oasisDefaultMaxRounds string = '10'

// ─── Paràmetres del Report Agent ─────────────────────────────────────────────

@description('Nombre màxim de crides a eines del Report Agent')
param reportAgentMaxToolCalls string = '5'

@description('Nombre màxim de rondes de reflexió del Report Agent')
param reportAgentMaxReflectionRounds string = '2'

@description('Temperatura del model LLM per al Report Agent')
param reportAgentTemperature string = '0.5'

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
    //   internal: true   // true = accés únicament per intranet
    // }
  }
}

// ─── Container App ─────────────────────────────────────────────────────────────
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: projectName
  location: location
  properties: {
    managedEnvironmentId: containerAppsEnv.id

    configuration: {
      // Secrets de Container Apps — mai en text pla a les variables d'entorn
      secrets: [
        { name: 'demo-password',   value: demoPassword }
        { name: 'llm-api-key',     value: llmApiKey }
        { name: 'llm-boost-api-key', value: llmBoostApiKey }
        { name: 'zep-api-key',     value: zepApiKey }
        { name: 'secret-key',      value: secretKey }
      ]

      // Ingrés: port únic 5001 (Flask serveix frontend + API)
      ingress: {
        external: true        // TODO (ops): canviar a false en entorn intranet CTTI
        targetPort: 5001
        transport: 'http'
        // TODO (ops): afegir domini corporatiu quan estigui assignat
        // customDomains: [
        //   {
        //     name: 'mirofish.intranet.gencat.cat'   // PRE
        //     certificateId: '<id-certificat-aca>'
        //     bindingType: 'SniEnabled'
        //   }
        // ]
      }

      // Revisió única activa (zero-downtime via revision-based deployments)
      activeRevisionsMode: 'Single'
    }

    template: {
      containers: [
        {
          name: projectName
          image: containerImage

          env: [
            // ── Secrets referenciats per nom (mai valor en text pla) ──
            { name: 'DEMO_PASSWORD',         secretRef: 'demo-password' }
            { name: 'LLM_API_KEY',           secretRef: 'llm-api-key' }
            { name: 'LLM_BOOST_API_KEY',     secretRef: 'llm-boost-api-key' }
            { name: 'ZEP_API_KEY',           secretRef: 'zep-api-key' }
            { name: 'SECRET_KEY',            secretRef: 'secret-key' }

            // ── Variables no sensibles ──
            { name: 'LLM_BASE_URL',          value: llmBaseUrl }
            { name: 'LLM_MODEL_NAME',        value: llmModelName }
            { name: 'LLM_BOOST_BASE_URL',    value: llmBoostBaseUrl }
            { name: 'LLM_BOOST_MODEL_NAME',  value: llmBoostModelName }

            // ── Simulació OASIS ──
            { name: 'OASIS_DEFAULT_MAX_ROUNDS', value: oasisDefaultMaxRounds }

            // ── Report Agent ──
            { name: 'REPORT_AGENT_MAX_TOOL_CALLS',        value: reportAgentMaxToolCalls }
            { name: 'REPORT_AGENT_MAX_REFLECTION_ROUNDS', value: reportAgentMaxReflectionRounds }
            { name: 'REPORT_AGENT_TEMPERATURE',           value: reportAgentTemperature }

            // ── Flask ──
            { name: 'FLASK_DEBUG', value: 'False' }
          ]

          // Recursos mínim viable — escalar horitzontalment via rèpliques
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]

      // Escalat: mínim 1 rèplica (evita cold start en PRO), màxim 10
      scale: {
        minReplicas: 1
        maxReplicas: 10
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

// ─── Outputs ──────────────────────────────────────────────────────────────────
@description('FQDN de l\'aplicació desplegada')
output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn

@description('Nom del recurs Container App')
output containerAppName string = containerApp.name

@description('ID del workspace de Log Analytics')
output logAnalyticsWorkspaceId string = logAnalytics.id
