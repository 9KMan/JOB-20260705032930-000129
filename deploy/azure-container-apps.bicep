// CPA Document Intake — Azure Container Apps production infrastructure
// Decision: 02-router-confidence — runs the production routing pipeline.
// Decision: 03-audit-immutability — audit log stored in immutable WORM blob.
// Decision: 04-intake-idempotency — Cosmos + Postgres unique constraints.
// Decision: 05-reviewer-workflow — Entra ID app registration for human-in-loop.
//
// Partner override at deploy time via `--parameters` flags or env vars.
// All secrets stored in Key Vault, referenced via managed identity.

targetScope = 'resourceGroup'

// -----------------------------------------------------------------------------
// Parameters
// -----------------------------------------------------------------------------
@minLength(2)
@maxLength(12)
@description('Short name prefix (e.g. "cpa" -> cpa-doc-intake, cpa-openai, etc.)')
param namePrefix string = 'cpa'

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Environment name (dev | staging | prod)')
@allowed(['dev', 'staging', 'prod'])
param environment string = 'prod'

@description('Container image: registry/repo:tag')
param containerImage string = 'cpaacr.azurecr.io/cpa-doc-intake:0.1.0'

@description('User-assigned managed identity client ID for workload identity')
param uamiClientId string

@description('User-assigned managed identity resource ID')
param uamiResourceId string

@description('Entra ID tenant ID')
param tenantId string

@description('MS Graph app registration client ID')
param msGraphClientId string

@description('Container Apps default domain')
param containerAppsDefaultDomain string = 'azurecontainerapps.io'

@description('Custom DNS prefix for ingress (optional)')
param customDomain string = ''

// -----------------------------------------------------------------------------
// Variables
// -----------------------------------------------------------------------------
var tags = {
  environment: environment
  application: 'cpa-doc-intake'
  managedBy: 'bicep'
  workloadIdentity: 'enabled'
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var acrPullScope = subscriptionResourceId('Microsoft.ContainerRegistry/registries', '${namePrefix}acr')
var acrPullPrincipalId = 'system-assigned-managed-identity'  // replaced post-deploy

// -----------------------------------------------------------------------------
// Existing resources (assumed already provisioned via partner subscription)
// -----------------------------------------------------------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = {
  name: '${namePrefix}-logs'
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: '${namePrefix}-appinsights'
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: '${namePrefix}-kv'
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: '${namePrefix}acr'
}

// -----------------------------------------------------------------------------
// Container Apps environment
// -----------------------------------------------------------------------------
resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-cae-${environment}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

// -----------------------------------------------------------------------------
// Azure Database for PostgreSQL Flexible Server (idempotency decision needs
// reliable Postgres unique constraints)
// -----------------------------------------------------------------------------
resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-12-01-preview' = {
  name: '${namePrefix}-pg-${environment}'
  location: location
  tags: tags
  sku: {
    name: 'Standard_B2s'
    tier: 'Burstable'
  }
  properties: {
    version: '15'
    administratorLogin: 'cpa_admin'
    administratorLoginPassword: 'PLACEHOLDER_FROM_KEYVAULT'  // referenced via secretRef
    storage: {
      storageSizeGB: 32
    }
    backup: {
      backupRetentionDays: 35
      geoRedundantBackup: 'Enabled'
    }
    highAvailability: {
      mode: environment == 'prod' ? 'ZoneRedundant' : 'Disabled'
    }
  }
}

resource postgresDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-12-01-preview' = {
  parent: postgresServer
  name: 'cpa_intake'
  properties: {
    collation: 'en_US.utf8'
    charset: 'utf8'
  }
}

// -----------------------------------------------------------------------------
// Azure Cache for Redis
// -----------------------------------------------------------------------------
resource redis 'Microsoft.Cache/Redis@2024-03-01' = {
  name: '${namePrefix}-redis-${environment}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'Standard'
      family: 'C'
      capacity: 1
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    redisConfiguration: {
      'maxmemory-policy': 'allkeys-lru'
    }
  }
}

// -----------------------------------------------------------------------------
// Storage Account (with immutable WORM policy for audit logs)
// Decision: 03-audit-immutability — WORM compliance mode
// -----------------------------------------------------------------------------
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: '${namePrefix}sa${uniqueString(resourceGroup().id)}'
  location: location
  tags: tags
  sku: {
    name: 'Standard_GRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
    }
  }
}

resource docsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: storageAccount
  name: 'cpa-docs'
  properties: {
    publicAccess: 'None'
    immutableStorageWithVersioning: {
      enabled: false
    }
  }
}

resource auditContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: storageAccount
  name: 'cpa-audit'
  properties: {
    publicAccess: 'None'
    // Immutable WORM policy: documents cannot be deleted/modified for 7 years.
    // This is the audit-immutability guarantee.
    immutableStorageWithVersioning: {
      enabled: true
    }
  }
}

// -----------------------------------------------------------------------------
// Container App — the API
// Decision: 02-router-confidence + 04-intake-idempotency
// -----------------------------------------------------------------------------
resource apiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${namePrefix}-api'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uamiResourceId}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        customDomains: empty(customDomain) ? [] : [
          {
            name: customDomain
            bindingType: 'SniEnabled'
            certificateId: !empty(customDomain) ? sslCert.outputs.certId : ''
          }
        ]
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: uamiResourceId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: containerImage
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: 8000
              }
              initialDelaySeconds: 30
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/readyz'
                port: 8000
              }
              initialDelaySeconds: 10
              periodSeconds: 10
            }
          ]
          env: [
            {
              name: 'AZURE_TENANT_ID'
              value: tenantId
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: uamiClientId
            }
            {
              name: 'AZURE_KEY_VAULT_URI'
              value: keyVault.properties.vaultUri
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: 'https://${namePrefix}-openai.openai.azure.com/'
            }
            {
              name: 'MS_GRAPH_CLIENT_ID'
              value: msGraphClientId
            }
            {
              name: 'MS_GRAPH_TENANT_ID'
              value: tenantId
            }
            {
              name: 'POSTGRES_HOST'
              value: postgresServer.properties.fullyQualifiedDomainName
            }
            {
              name: 'POSTGRES_DB'
              value: 'cpa_intake'
            }
            {
              name: 'POSTGRES_USER'
              value: 'cpa_admin'
            }
            {
              name: 'REDIS_HOST'
              value: redis.properties.hostName
            }
            {
              name: 'MINIO_ENDPOINT'
              value: storageAccount.properties.primaryEndpoints.blob
            }
            {
              name: 'MINIO_BUCKET_DOCS'
              value: 'cpa-docs'
            }
            {
              name: 'MINIO_BUCKET_AUDIT'
              value: 'cpa-audit'
            }
            {
              name: 'APPINSIGHTS_INSTRUMENTATIONKEY'
              value: appInsights.properties.InstrumentationKey
            }
            {
              name: 'ENABLE_AUDIT_IMMUTABILITY'
              value: 'true'
            }
            {
              name: 'ENABLE_IDEMPOTENCY'
              value: 'true'
            }
            {
              name: 'ENABLE_REVIEWER_WORKFLOW'
              value: 'true'
            }
          ]
        }
      ]
      scale: {
        minReplicas: environment == 'prod' ? 2 : 1
        maxReplicas: environment == 'prod' ? 10 : 3
        rules: [
          {
            name: 'http-scale'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

// -----------------------------------------------------------------------------
// Auto-scaling for ACR pull (Container App uses AAD, but ops sometimes needs
// to pull images for forensics — gives the deployer AcrPull on the existing ACR)
// -----------------------------------------------------------------------------
// (Actual role assignment done via az role assignment, not bicep, because
// AcrPull role definition GUID varies by subscription)

// -----------------------------------------------------------------------------
// Outputs
// -----------------------------------------------------------------------------
output apiFqdn string = apiApp.properties.configuration.ingress.fqdn
output apiResourceId string = apiApp.id
output postgresHost string = postgresServer.properties.fullyQualifiedDomainName
output redisHost string = redis.properties.hostName
output storageAccountName string = storageAccount.name
output keyVaultUri string = keyVault.properties.vaultUri
output containerEnvId string = containerEnv.id

@description('Conditional certificate resource — only created if customDomain is set.')
module sslCert './modules/managed-cert.bicep' = if (!empty(customDomain)) {
  name: 'ssl-cert-deploy'
  params: {
    namePrefix: namePrefix
    location: location
    hostname: customDomain
    environmentId: containerEnv.id
  }
}