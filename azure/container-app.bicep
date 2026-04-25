// ─────────────────────────────────────────────────────────────────────────────
// MiroFish — Container App (executar a cada deploy)
//
// Rep com a paràmetres els outputs d'infra.bicep (containerAppsEnvId,
// acrLoginServer) i desplega/actualitza la Container App amb la nova imatge.
//
// Executar amb: azure/2-build-deploy.sh
//
// Extensions pendents per a l'equip d'operacions:
//   - DNS: afegir CNAME a *.intranet.gencat.cat (PRE) / *.gencat.cat (PRO)
//   - ingress.external: canviar a false per a accés exclusiu per intranet
//   - TLS: certificat gestionat via Container Apps o Azure Front Door
// ─────────────────────────────────────────────────────────────────────────────

@description('Nom base del projecte')
param projectName string = 'mirofish'

@description('Localització Azure dels recursos')
param location string = resourceGroup().location

@description('ID del Container Apps Environment (output d\'infra.bicep)')
param containerAppsEnvId string

@description('Imatge Docker completa (acrLoginServer/nom:tag)')
param containerImage string

@description('Login server de l\'ACR (ex: mirofsihacr.azurecr.io)')
param acrLoginServer string

// ─── Paràmetres secrets (@secure — mai visibles als logs de desplegament) ────

@description('Nom d\'usuari de l\'ACR (az acr credential show --name <acr> --query username)')
@secure()
param acrUsername string

@description('Contrasenya de l\'ACR (az acr credential show --name <acr> --query passwords[0].value)')
@secure()
param acrPassword string

@description('Contrasenya de l\'usuari demo')
@secure()
param demoPassword string

@description('Clau de l\'API LLM principal (OpenAI-compatible)')
@secure()
param llmApiKey string

@description('Clau de l\'API LLM acceleradora (opcional, deixar buit si no s\'usa)')
@secure()
param llmBoostApiKey string = ''

@description('Clau de l\'API Zep Cloud (obligatori si GRAPH_BACKEND=zep)')
@secure()
param zepApiKey string = ''

@description('Contrasenya de Neo4j (obligatori si GRAPH_BACKEND=graphiti)')
@secure()
param neo4jPassword string = ''

@description('SECRET_KEY de Flask per a JWT (python -c "import secrets; print(secrets.token_hex(32))")')
@secure()
param secretKey string

// ─── Paràmetres LLM principal ─────────────────────────────────────────────────

@description('URL base de l\'API LLM principal')
param llmBaseUrl string = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

@description('Nom del model LLM principal')
param llmModelName string = 'qwen-plus'

@description('Proveïdor LLM (gemini per a Google AI Studio; buit per a qualsevol compatible OpenAI)')
param llmProvider string = ''

// ─── Paràmetres del backend de graf ──────────────────────────────────────────

@description('Backend de graf: zep (Zep Cloud) o graphiti (Neo4j local/Azure)')
param graphBackend string = 'zep'

@description('URI de connexió bolt de Neo4j (necessari si GRAPH_BACKEND=graphiti)')
param neo4jUri string = 'bolt://localhost:7687'

@description('Usuari de Neo4j')
param neo4jUser string = 'neo4j'

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

// ─── Secrets i env vars condicionals (Azure rebutja secrets amb valor buit) ───
var mandatorySecrets = [
  { name: 'acr-password',  value: acrPassword }
  { name: 'demo-password', value: demoPassword }
  { name: 'llm-api-key',   value: llmApiKey }
  { name: 'secret-key',    value: secretKey }
]
var optionalSecrets = concat(
  empty(llmBoostApiKey) ? [] : [{ name: 'llm-boost-api-key', value: llmBoostApiKey }],
  empty(zepApiKey)      ? [] : [{ name: 'zep-api-key',       value: zepApiKey }],
  empty(neo4jPassword)  ? [] : [{ name: 'neo4j-password',    value: neo4jPassword }]
)
var allSecrets = concat(mandatorySecrets, optionalSecrets)

var mandatoryEnv = [
  { name: 'DEMO_PASSWORD', secretRef: 'demo-password' }
  { name: 'LLM_API_KEY',   secretRef: 'llm-api-key' }
  { name: 'SECRET_KEY',    secretRef: 'secret-key' }
  { name: 'LLM_BASE_URL',          value: llmBaseUrl }
  { name: 'LLM_MODEL_NAME',        value: llmModelName }
  { name: 'LLM_PROVIDER',          value: llmProvider }
  { name: 'LLM_BOOST_BASE_URL',    value: llmBoostBaseUrl }
  { name: 'LLM_BOOST_MODEL_NAME',  value: llmBoostModelName }
  { name: 'GRAPH_BACKEND',         value: graphBackend }
  { name: 'NEO4J_URI',             value: neo4jUri }
  { name: 'NEO4J_USER',            value: neo4jUser }
  { name: 'OASIS_DEFAULT_MAX_ROUNDS',           value: oasisDefaultMaxRounds }
  { name: 'REPORT_AGENT_MAX_TOOL_CALLS',        value: reportAgentMaxToolCalls }
  { name: 'REPORT_AGENT_MAX_REFLECTION_ROUNDS', value: reportAgentMaxReflectionRounds }
  { name: 'REPORT_AGENT_TEMPERATURE',           value: reportAgentTemperature }
  { name: 'FLASK_DEBUG', value: 'False' }
]
var optionalEnv = concat(
  empty(llmBoostApiKey) ? [] : [{ name: 'LLM_BOOST_API_KEY', secretRef: 'llm-boost-api-key' }],
  empty(zepApiKey)      ? [] : [{ name: 'ZEP_API_KEY',       secretRef: 'zep-api-key' }],
  empty(neo4jPassword)  ? [] : [{ name: 'NEO4J_PASSWORD',    secretRef: 'neo4j-password' }]
)
var allEnv = concat(mandatoryEnv, optionalEnv)

// ─── Container App ─────────────────────────────────────────────────────────────
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: projectName
  location: location
  properties: {
    managedEnvironmentId: containerAppsEnvId

    configuration: {
      secrets: allSecrets

      // Credencials del registre privat (ACR)
      registries: [
        {
          server: acrLoginServer
          username: acrUsername
          passwordSecretRef: 'acr-password'
        }
      ]

      // Ingrés: port únic 5001 (Flask serveix frontend + API)
      ingress: {
        external: true        // TODO (ops): canviar a false en entorn intranet CTTI
        targetPort: 5001
        transport: 'http'
        // TODO (ops): afegir domini corporatiu quan estigui assignat
        // customDomains: [
        //   { name: 'mirofish.intranet.gencat.cat', certificateId: '...', bindingType: 'SniEnabled' }
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
          env: allEnv

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
@description('FQDN públic de l\'aplicació')
output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn

@description('Nom del recurs Container App')
output containerAppName string = containerApp.name
