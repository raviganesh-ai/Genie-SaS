// Genie foundational infrastructure - subscription-scoped entry point.
//
// Assumes the target Azure subscription is EMPTY: creates its own resource
// group and every foundational resource Genie depends on (no existing
// resource group, managed identity, Key Vault, AI Search, Cosmos DB,
// Storage Account, Container Apps environment, Static Web App, Application
// Insights, or Log Analytics workspace is assumed to exist).
//
// Run `scripts/validate_deployment_readiness.py` (or
// `scripts/deploy_infra.ps1`, which runs it automatically) BEFORE this
// template - deployment readiness validation must occur before
// infrastructure provisioning, per .github/copilot-instructions.md.
//
// Usage:
//   az deployment sub create \
//     --location <location> \
//     --template-file infra/main.bicep \
//     --parameters infra/main.parameters.json
targetScope = 'subscription'

@minLength(1)
@maxLength(16)
@description('Short, unique name for this Genie environment (e.g. "dev", "prod"). Used to derive resource names.')
param environmentName string

@description('Azure region every resource is deployed into.')
param location string

@description('Azure region used ONLY for the resource group\'s own location property - defaults to `location`. Azure does not allow changing an existing resource group\'s location, so when redeploying into an already-existing resource group (e.g. a previous run in a different region whose deletion was declined), pass that resource group\'s actual, unchanged location here while `location` continues to drive every child resource. Leaving this at its default is correct for a brand-new resource group.')
param resourceGroupLocation string = location

@description('Azure region for Azure AI Search. Defaults to `location`; override this independently if AI Search lacks capacity in the primary region.')
param aiSearchLocation string = location

@description('Address space reserved for the Genie Container Apps environment and private endpoints.')
param virtualNetworkAddressPrefix string = '10.20.0.0/16'

@description('Dedicated subnet for the Container Apps workload-profiles environment; must be /27 or larger.')
param containerAppsInfrastructureSubnetPrefix string = '10.20.0.0/23'

@description('Dedicated subnet for Azure private endpoints.')
param privateEndpointSubnetPrefix string = '10.20.2.0/24'

@description('Dedicated subnet for API Management Standard v2 outbound VNet integration; must be /27 or larger.')
param apiManagementSubnetPrefix string = '10.20.4.0/24'

@description('Short prefix applied to every resource name (lowercase letters/numbers only).')
@minLength(2)
@maxLength(8)
param resourcePrefix string = 'genie'

@description('Optional exact resource group name. When empty, uses `<resourcePrefix>-<environmentName>-rg`.')
param resourceGroupNameOverride string = ''

@description('Object id of the operator running quick-start. Granted Cognitive Services User on the new Foundry account so the out-of-band agent provisioning stage can create and verify Prompt Agents.')
param deployerPrincipalId string = ''

@description('Model deployments to create on the Azure AI Foundry account as part of this deployment. Each item needs: name (the deployment name agents reference, e.g. config/agents/registry.yaml model_deployment_ref), model, version, and optionally format/skuName/skuCapacity. Leave empty to skip and deploy models manually afterward.')
param foundryModelDeployments array = []

@description('Deploy an Azure Container Registry and a bootstrap backend Container App as part of this same template - recommended so a brand-new, empty subscription ends up with a real (if not-yet-configured) Container App resource that scripts/deploy_backend.ps1 can then roll the real image onto. Set to false if you already have your own registry/app.')
param deployContainerRegistryAndBackendApp bool = true

@description('Create or update the bootstrap backend Container App. Set to false with existingBackendContainerAppName when quick-start detects an already provisioned, healthy Genie backend that must be preserved.')
param provisionBackendContainerApp bool = true

@description('Existing healthy Genie backend Container App name to preserve when provisionBackendContainerApp is false.')
param existingBackendContainerAppName string = ''

@description('Azure Container Registry SKU.')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param containerRegistrySkuName string = 'Basic'

// Deterministic, collision-resistant suffix derived from the subscription
// and environment name - never a hardcoded/customer-specific value.
var resourceToken = uniqueString(subscription().id, environmentName, location)
var resourceGroupName = empty(resourceGroupNameOverride) ? '${resourcePrefix}-${environmentName}-rg' : resourceGroupNameOverride
var tags = {
  application: 'genie'
  environment: environmentName
}

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: resourceGroupLocation
  tags: tags
}

module foundationalResources 'modules/foundational-resources.bicep' = {
  name: 'genie-foundational-resources'
  scope: resourceGroup
  params: {
    location: location
    aiSearchLocation: aiSearchLocation
    resourcePrefix: resourcePrefix
    resourceToken: resourceToken
    virtualNetworkAddressPrefix: virtualNetworkAddressPrefix
    containerAppsInfrastructureSubnetPrefix: containerAppsInfrastructureSubnetPrefix
    privateEndpointSubnetPrefix: privateEndpointSubnetPrefix
    apiManagementSubnetPrefix: apiManagementSubnetPrefix
    deployerPrincipalId: deployerPrincipalId
    foundryModelDeployments: foundryModelDeployments
    deployContainerRegistryAndBackendApp: deployContainerRegistryAndBackendApp
    provisionBackendContainerApp: provisionBackendContainerApp
    existingBackendContainerAppName: existingBackendContainerAppName
    containerRegistrySkuName: containerRegistrySkuName
    tags: tags
  }
}

module prototypeGatewayRbac 'modules/prototype-gateway-rbac.bicep' = {
  name: 'genie-prototype-gateway-rbac'
  params: {
    managedIdentityPrincipalId: foundationalResources.outputs.managedIdentityPrincipalId
  }
}

output resourceGroupName string = resourceGroup.name
output managedIdentityPrincipalId string = foundationalResources.outputs.managedIdentityPrincipalId
output managedIdentityClientId string = foundationalResources.outputs.managedIdentityClientId
output keyVaultUri string = foundationalResources.outputs.keyVaultUri
output keyVaultName string = foundationalResources.outputs.keyVaultName
output storageAccountName string = foundationalResources.outputs.storageAccountName
output aiSearchEndpoint string = foundationalResources.outputs.aiSearchEndpoint
output cosmosDbEndpoint string = foundationalResources.outputs.cosmosDbEndpoint
output aiFoundryEndpoint string = foundationalResources.outputs.aiFoundryEndpoint
output aiFoundryApiEndpoint string = foundationalResources.outputs.aiFoundryApiEndpoint
output aiFoundryAccountName string = foundationalResources.outputs.aiFoundryAccountName
output aiFoundryProjectName string = foundationalResources.outputs.aiFoundryProjectName
output containerAppsEnvironmentId string = foundationalResources.outputs.containerAppsEnvironmentId
output containerAppsEnvironmentName string = foundationalResources.outputs.containerAppsEnvironmentName
output staticWebAppDefaultHostname string = foundationalResources.outputs.staticWebAppDefaultHostname
output staticWebAppName string = foundationalResources.outputs.staticWebAppName
output applicationInsightsConnectionString string = foundationalResources.outputs.applicationInsightsConnectionString
output logAnalyticsWorkspaceId string = foundationalResources.outputs.logAnalyticsWorkspaceId
output containerRegistryName string = foundationalResources.outputs.containerRegistryName
output containerRegistryLoginServer string = foundationalResources.outputs.containerRegistryLoginServer
output backendContainerAppName string = foundationalResources.outputs.backendContainerAppName
output backendContainerAppFqdn string = foundationalResources.outputs.backendContainerAppFqdn
