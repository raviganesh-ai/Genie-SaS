// Azure Container App: the actual running Genie FastAPI backend resource
// (NOT just the Container Apps environment, which only hosts it) - per the
// "Images and hosting" Azure concern in README.md.
//
// Bootstraps with a small, publicly pullable placeholder image because no
// Genie-specific image can exist in a brand-new Azure Container Registry
// before this very deployment creates that registry (a one-time
// chicken-and-egg only a first deployment hits). `scripts/deploy_backend.ps1`
// (already idempotent and used for every subsequent rollout) swaps in the
// real, commit-pinned FastAPI image and finishes wiring runtime
// configuration/secrets immediately afterward - see
// `scripts/deploy_quickstart.ps1`. Nothing here is meant to be the final,
// fully-configured backend; it only has to exist so later steps have a
// real Container App resource to patch.
param location string
param name string
param containerAppsEnvironmentId string
param containerRegistryLoginServer string
param managedIdentityResourceId string
param managedIdentityClientId string
param tags object

@description('Placeholder public image used only for the very first deployment, before a real backend image has been built and pushed.')
param bootstrapImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Placeholder ingress target port matching bootstrapImage - deploy_backend.ps1 repoints this at FastAPI\'s port 8000 the moment the real image is rolled out.')
param bootstrapTargetPort int = 80

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityResourceId}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironmentId
    configuration: {
      ingress: {
        external: true
        targetPort: bootstrapTargetPort
        transport: 'auto'
      }
      registries: [
        {
          server: containerRegistryLoginServer
          identity: managedIdentityResourceId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'genie-backend'
          image: bootstrapImage
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            {
              // Tells DefaultAzureCredential which user-assigned identity to
              // use once the real FastAPI image (which relies on it) is
              // rolled out - see the Troubleshooting entry in README.md
              // about ManagedIdentityCredential crash-loops without this.
              name: 'AZURE_CLIENT_ID'
              value: managedIdentityClientId
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

output name string = containerApp.name
output fqdn string = containerApp.properties.configuration.ingress.fqdn
