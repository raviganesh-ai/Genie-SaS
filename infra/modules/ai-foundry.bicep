// Azure AI Foundry account + project: hosts every production agent Genie
// executes through AzureAgentGateway, per the Production Agent Rules in
// .github/copilot-instructions.md.
//
// ASSUMPTION (documented per "Document assumptions in comments when SDK
// behavior is uncertain"): Azure AI Foundry's account/project resource
// schema is newer and more volatile than the other resources in this
// template. This module targets the Cognitive Services "AIServices" kind
// account with a nested `projects` sub-resource, which is the current
// Foundry resource shape at authoring time. Bicep requires resource
// type/apiVersion to be a literal string (not a variable), so if the
// target subscription rejects these versions, bump the `@2025-06-01`
// literals on the `foundryAccount` and `foundryProject` resources below
// directly rather than changing the resource shape elsewhere. Confirmed
// against the real subscription on 2026-07-23: `accounts/projects` no
// longer supports the original `2024-10-01-preview` (retired), and the
// `accounts` resource must also be on `2025-06-01` (not `2024-10-01`)
// for the `allowProjectManagement` property to be recognized -
// `2025-06-01` is the oldest stable version still accepted for both.
param location string
param accountName string
param projectName string
param managedIdentityPrincipalId string
param deployerPrincipalId string
param tags object

@description('Model deployments created on the Foundry account as part of this same Bicep deployment (e.g. the default LLM referenced by config/agents/registry.yaml). Each entry must use a model/version/SKU actually available in `location` for this subscription - deploying an unavailable combination fails this template with the exact Azure error, never a silent fallback.')
param modelDeployments array = []

// Built-in role definition id for "Cognitive Services User" - lets the
// managed identity invoke the account's models/agents without granting
// control-plane (account management) permissions.
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
    allowProjectManagement: true
  }
}

// Model deployments must be created one at a time against the same
// account resource (Azure rejects concurrent deployment writes), so this
// loop declares an explicit dependsOn against the previous iteration's
// resource via Bicep's `@batchSize(1)` decorator rather than relying on
// implicit parallel resource-group provisioning.
@batchSize(1)
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = [
  for deployment in modelDeployments: {
    parent: foundryAccount
    name: deployment.name
    sku: {
      name: deployment.?skuName ?? 'GlobalStandard'
      capacity: deployment.?skuCapacity ?? 10
    }
    properties: {
      model: {
        format: deployment.?format ?? 'OpenAI'
        name: deployment.model
        version: deployment.version
      }
    }
  }
]

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundryAccount
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
  // Both this resource and modelDeployment[] only declare `parent:
  // foundryAccount` above, so Bicep has no implicit ordering between
  // them - it may issue both writes concurrently. Cognitive Services'
  // control plane treats any nested write (project OR deployment) as
  // acquiring an account-level lock, so a concurrent write collides with
  // "RequestConflict: Another operation is in progress on the resource
  // .../accounts/<name>" (confirmed live, 2026-10-06). This explicit
  // dependsOn forces every model deployment to finish first - harmless
  // when modelDeployments is empty, since the loop then produces zero
  // resources and this dependency list resolves to empty too.
  dependsOn: [
    modelDeployment
  ]
}

resource cognitiveServicesUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, managedIdentityPrincipalId, cognitiveServicesUserRoleId)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      cognitiveServicesUserRoleId
    )
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerCognitiveServicesUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(foundryAccount.id, deployerPrincipalId, cognitiveServicesUserRoleId)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      cognitiveServicesUserRoleId
    )
    principalId: deployerPrincipalId
  }
}

output endpoint string = foundryAccount.properties.endpoint
// ASSUMPTION: `foundryAccount.properties.endpoint` (and the generic
// `properties.endpoint` ARM field in general) returns the legacy
// `<account>.cognitiveservices.azure.com` host - correct for capabilities
// that still only route there (e.g. Speech Services, per
// `GENIE_AZURE_SPEECH_ENDPOINT`'s usage in
// backend/app/transcription/speech_service.py), but NOT the host AI
// Foundry's own account metadata (`properties.endpoints["AI Foundry API"]`
// / `properties.endpoints["Content Understanding"]`, confirmed live via
// `az cognitiveservices account show` on 2026-10-06) actually advertises
// for the AI Foundry project API and Content Understanding:
// `<account>.services.ai.azure.com`. `customSubDomainName` above is fixed
// to `accountName`, so that hostname is reserved for and resolves to this
// exact account - constructing it directly (rather than indexing the
// dynamic `properties.endpoints` map, which Bicep cannot do by display
// name) is deterministic. Wiring the legacy host into
// `GENIE_AZURE_FOUNDRY_ENDPOINT` instead of this one is what caused
// Content Understanding's `/contentunderstanding/*` routes to 404 at
// backend startup on a freshly provisioned account.
output aiFoundryApiEndpoint string = 'https://${accountName}.services.ai.azure.com'
output accountName string = foundryAccount.name
output projectName string = foundryProject.name
