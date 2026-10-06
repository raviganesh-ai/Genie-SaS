<#
.SYNOPSIS
    One-command deployment of a complete Genie evaluation environment into
    ANY Azure subscription you own - never the original author's.

.DESCRIPTION
    Chains every already-existing, individually-tested Genie deployment
    script/Bicep template, in the right order, into a single run:

      1. Confirms (and lets you switch) the signed-in `az` identity -
         never assumes a specific tenant/subscription/account.
      2. Prompts for every subscription id, region, publisher contact,
         GitHub token, and model choice this deployment needs - nothing is
         pre-filled with a real value belonging to any specific
         organization, and no credential is ever written to a file this
         repository tracks or printed back out after it's collected.
      3. Offers to remove a previous deployment for this exact
         (ResourcePrefix, EnvironmentName) pair first, if one already
         exists - always confirmed, scoped only to that one resource
         group (see scripts/remove_existing_deployment.ps1).
      4. Validates Azure resource-provider readiness (fails closed).
      5. Deploys infra/main.bicep - creates its own resource group and
         EVERY foundational resource Genie needs, including (new) an
         Azure Container Registry and a bootstrap backend Container App,
         so an empty subscription ends up with a real, addressable
         Container App resource. This does NOT yet include the API
         Management gateway (step 7) - APIM can only be wired up once
         this step's backend Container App already exists.
      6. Builds and pushes the real FastAPI image.
      7. Provisions the dedicated APIM gateway via
         scripts/deploy_platform_gateway.ps1 - this is what actually
         creates Azure API Management; running infra/main.bicep alone
         (without this script) never does.
      8. Provisions every Genie agent as a real Azure AI Foundry resource
         via scripts/provision_foundry_agents.py.
      9. Rolls out the real backend only after its Foundry-agent dependency
         is verified, then builds and deploys the frontend to the Static Web
         App Bicep already created.
      10. Runs the same health checks documented in README.md.

    This script is intentionally LONG-RUNNING (Azure API Management
    Standard v2 provisioning alone commonly takes 30-45 minutes) and
    intentionally STOPS at the first failure (fail closed) rather than
    attempting a partial/best-effort deployment - re-run it; every stage
    is either already idempotent (the scripts it calls) or safe to retry.
    To start over from a clean slate instead of resuming, see
    scripts/remove_existing_deployment.ps1 (step 3 above runs it for you
    automatically, with your explicit confirmation, every time).

    Per the Purpose and use boundary in README.md: this reproduces
    Genie's ART-OF-THE-POSSIBLE EVALUATION environment, not a
    production-ready deployment. Complete your own security/privacy/
    operational-readiness review before any production use.

    PREREQUISITE: the signed-in account needs Owner, or Contributor plus
    User Access Administrator, on the target subscription. Infrastructure
    provisioning creates least-privilege role assignments for the runtime
    managed identity and grants the interactive operator Foundry data-plane
    access for agent provisioning. See "Create a least-privilege deployment
    identity" in docs/DEPLOYMENT.md for the non-interactive alternative.

.PARAMETER SubscriptionId
    Azure subscription id to deploy into. If omitted, you're prompted to
    pick from `az account list` (your own signed-in account's own
    subscriptions - never a default baked into this script).

.PARAMETER EnvironmentName
    Short, unique name for this environment (e.g. "dev"). Default: "dev".

.PARAMETER Location
    Azure region for every resource. Default: "eastus2" - confirm Azure AI
    Foundry/model availability in your chosen region before accepting. Must
    also be a region Azure Content Understanding supports (see
    config/deployment/content_understanding_regions.yaml) - this script
    fails closed before provisioning anything if it is not, since Content
    Understanding is a mandatory backend startup dependency.

.PARAMETER ResourcePrefix
    Short prefix applied to every resource name. Default: "genie".

.PARAMETER SkipFrontendDeploy
    Skip the final frontend build/deploy stage (useful when iterating on
    backend-only stages during testing).

.PARAMETER RemovePreviousDeployment
    Skip the interactive confirmation prompt and immediately remove a
    previous deployment for this exact (ResourcePrefix, EnvironmentName)
    pair, if one exists, before continuing. Omit this for the normal,
    safer behavior of being asked to type the resource group name back
    before anything is deleted.

.EXAMPLE
    ./scripts/deploy_quickstart.ps1
    (fully interactive - prompts for everything required)

.EXAMPLE
    ./scripts/deploy_quickstart.ps1 -SubscriptionId <your-subscription-id> -EnvironmentName dev -Location eastus2
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId,
    [string]$EnvironmentName = "dev",
    [string]$Location = "eastus2",
    [string]$ResourcePrefix = "genie",
    [string]$ResourceGroupName,
    [string]$GitHubMcpEndpoint = "https://api.githubcopilot.com/mcp/",
    [string]$PublisherEmail,
    [string]$PublisherName,
    [string]$DefaultLlmDeploymentName = "gpt-5-mini",
    [string]$DefaultLlmModel = "gpt-5-mini",
    [hashtable]$FoundryModelCatalog = @{},
    [switch]$NonInteractive,
    [switch]$SkipFrontendDeploy,
    [switch]$RemovePreviousDeployment
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

function Write-Stage {
    param([string]$Text)
    Write-Host "`n=== $Text ===" -ForegroundColor Cyan
}

function Read-RequiredValue {
    param(
        [Parameter(Mandatory = $true)][string]$Prompt,
        [string]$Default
    )
    if ($NonInteractive) {
        if ([string]::IsNullOrWhiteSpace($Default)) {
            throw "A non-interactive value is required for '$Prompt'."
        }
        return $Default
    }
    $suffix = if ($Default) { " [$Default]" } else { "" }
    while ($true) {
        $value = Read-Host "$Prompt$suffix"
        if ([string]::IsNullOrWhiteSpace($value) -and $Default) { return $Default }
        if (-not [string]::IsNullOrWhiteSpace($value)) { return $value }
        Write-Host "A value is required." -ForegroundColor Yellow
    }
}

function Read-SecretValue {
    param([Parameter(Mandatory = $true)][string]$Prompt)
    $secure = Read-Host $Prompt -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Invoke-AzJson {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $output = & az @Arguments --only-show-errors -o json
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Arguments -join ' ')"
    }
    return $output | ConvertFrom-Json -Depth 100
}

function Assert-ContentUnderstandingSupportedRegion {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Location
    )

    $registryPath = Join-Path $RepoRoot "config\deployment\content_understanding_regions.yaml"
    if (-not (Test-Path $registryPath)) {
        throw "Content Understanding region registry not found at '$registryPath'."
    }
    $supportedRegions = @(
        Get-Content -Path $registryPath |
            Where-Object { $_ -match '^\s*-\s*(\S+)\s*$' } |
            ForEach-Object { $matches[1] }
    )
    if ($supportedRegions.Count -eq 0) {
        throw "Content Understanding region registry at '$registryPath' is empty."
    }
    if ($Location -notin $supportedRegions) {
        throw (
            "Azure region '$Location' does not support Content Understanding, a mandatory " +
            "backend startup dependency (see $registryPath). Choose one of: " +
            ($supportedRegions -join ', ')
        )
    }
}

function Get-ModelVersionSortKey {
    param([Parameter(Mandatory = $true)][string]$Version)

    $dateVersion = [datetime]::MinValue
    if ([datetime]::TryParseExact(
        $Version,
        "yyyy-MM-dd",
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::None,
        [ref]$dateVersion
    )) {
        return "2:$($dateVersion.Ticks.ToString('D20'))"
    }

    $numericVersion = [long]0
    if ([long]::TryParse($Version, [ref]$numericVersion)) {
        return "1:$($numericVersion.ToString('D20'))"
    }

    return "0:$Version"
}

function Resolve-LatestAzureModelDeployment {
    param(
        [Parameter(Mandatory = $true)][string]$DeploymentName,
        [Parameter(Mandatory = $true)][string]$ModelName,
        [Parameter(Mandatory = $true)][object[]]$Catalog
    )

    $availableModels = @(
        $Catalog |
            Where-Object {
                $_.model.name -eq $ModelName -and
                -not [string]::IsNullOrWhiteSpace($_.model.version)
            }
    )
    if ($availableModels.Count -eq 0) {
        throw "Azure model '$ModelName' is not available in region '$Location' for the selected subscription."
    }

    $selectedModel = $availableModels |
        Sort-Object -Property @{
            Expression = { Get-ModelVersionSortKey -Version $_.model.version }
            Descending = $true
        } |
        Select-Object -First 1

    Write-Host "Resolved Azure model '$ModelName' to latest version '$($selectedModel.model.version)' in '$Location'." -ForegroundColor Green
    return @{
        name = $DeploymentName
        model = $ModelName
        version = $selectedModel.model.version
        format = $selectedModel.model.format
    }
}

function Find-ProvisionedGenieBackend {
    param(
        [Parameter(Mandatory = $true)][string]$SubscriptionId,
        [Parameter(Mandatory = $true)][string]$ResourceGroup
    )

    $resourceGroupExists = & az group exists `
        --subscription $SubscriptionId `
        --name $ResourceGroup `
        --only-show-errors `
        -o tsv
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to check whether resource group '$ResourceGroup' exists."
    }
    if ($resourceGroupExists -ne "true") {
        return $null
    }

    $candidates = @()
    $apps = @(Invoke-AzJson containerapp list --subscription $SubscriptionId --resource-group $ResourceGroup)
    foreach ($app in $apps) {
        $backendContainers = @(
            $app.properties.template.containers |
                Where-Object { $_.name -eq "genie-backend" }
        )
        if ($backendContainers.Count -ne 1) {
            continue
        }
        $backendContainer = $backendContainers[0]
        $serviceName = @(
            $backendContainer.env |
                Where-Object { $_.name -eq "GENIE_SERVICE_NAME" -and $_.value -eq "genie-backend" }
        )
        $isGenieImage = $backendContainer.image -match "/genie-backend:[^/]+$"
        $isReadyRevision = (
            -not [string]::IsNullOrWhiteSpace($app.properties.latestRevisionName) -and
            $app.properties.latestRevisionName -eq $app.properties.latestReadyRevisionName -and
            $app.properties.runningStatus -eq "Running"
        )
        if (-not $isGenieImage -or $serviceName.Count -ne 1 -or -not $isReadyRevision) {
            continue
        }

        $revision = Invoke-AzJson containerapp revision show `
            --subscription $SubscriptionId `
            --resource-group $ResourceGroup `
            --name $app.name `
            --revision $app.properties.latestRevisionName
        if (
            $revision.properties.provisioningState -eq "Provisioned" -and
            $revision.properties.runningState -eq "Running" -and
            $revision.properties.healthState -eq "Healthy"
        ) {
            $candidates += [pscustomobject]@{
                name = $app.name
                image = $backendContainer.image
                revision = $app.properties.latestRevisionName
            }
        }
    }

    if ($candidates.Count -gt 1) {
        throw "Found multiple healthy Genie backends in resource group '$ResourceGroup'; cannot safely choose one to preserve."
    }
    return $candidates | Select-Object -First 1
}

Write-Host @"
Genie - one-command deploy into YOUR Azure subscription
=========================================================
This provisions a complete, isolated Genie evaluation environment. It never
reads or writes any credential, subscription id, or secret belonging to the
original authoring environment - every value below comes from you, right now.

Genie is an art-of-the-possible evaluation prototype, not a production-ready
deployment - see "Purpose and use boundary" in README.md.
"@ -ForegroundColor White

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI ('az') was not found on PATH. Install it from https://learn.microsoft.com/cli/azure/install-azure-cli and re-run this script."
    exit 1
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error "Node.js/npm was not found on PATH. Install Node.js 20 or later and re-run this script."
    exit 1
}

# ---------------------------------------------------------------------------
# Stage 0: identity - confirm (or establish) YOUR OWN signed-in az session.
# ---------------------------------------------------------------------------
Write-Stage "Stage 0/10: confirm your Azure identity"
$account = $null
try { $account = Invoke-AzJson account show } catch { $account = $null }
if (-not $account) {
    Write-Host "Not signed in to Azure CLI - opening an interactive 'az login'..." -ForegroundColor Yellow
    az login | Out-Null
    $account = Invoke-AzJson account show
}
Write-Host "Signed in as: $($account.user.name)" -ForegroundColor Green
Write-Host "Active subscription: $($account.name) ($($account.id))"

if ([string]::IsNullOrWhiteSpace($SubscriptionId)) {
    $switchAccount = Read-Host "Use a different Azure account/subscription? (y/N)"
    if ($switchAccount -match '^(y|yes)$') {
        az login | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Azure login failed."
        }
        $account = Invoke-AzJson account show
        $subscriptions = Invoke-AzJson account list
        if ($subscriptions.Count -gt 1) {
            Write-Host "`nAvailable subscriptions for this account:"
            for ($i = 0; $i -lt $subscriptions.Count; $i++) {
                Write-Host "  [$i] $($subscriptions[$i].name) ($($subscriptions[$i].id))"
            }
            $index = Read-RequiredValue -Prompt "Pick a subscription by index" -Default "0"
            $SubscriptionId = $subscriptions[[int]$index].id
        }
        else {
            $SubscriptionId = $account.id
        }
    }
    else {
        $SubscriptionId = $account.id
    }
}
az account set --subscription $SubscriptionId --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to select Azure subscription '$SubscriptionId'."
}
$deployerPrincipalId = az ad signed-in-user show --query id -o tsv --only-show-errors
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($deployerPrincipalId)) {
    throw "Quick-start requires an interactive Azure user identity whose object id can be resolved for Foundry data-plane access."
}
Write-Host "Deploying into subscription: $SubscriptionId" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Stage 1: collect every other required value interactively.
# ---------------------------------------------------------------------------
Write-Stage "Stage 1/10: collect deployment parameters"
$EnvironmentName = Read-RequiredValue -Prompt "Environment name" -Default $EnvironmentName
$Location = Read-RequiredValue -Prompt "Azure region" -Default $Location
Assert-ContentUnderstandingSupportedRegion -RepoRoot $repoRoot -Location $Location
$ResourcePrefix = Read-RequiredValue -Prompt "Resource name prefix" -Default $ResourcePrefix

$githubMcpEndpoint = Read-RequiredValue -Prompt "GitHub MCP endpoint" -Default $GitHubMcpEndpoint

Write-Host "`nAzure API Management requires a publisher contact - this is shown on" -ForegroundColor White
Write-Host "developer-portal/error pages, never used for anything else." -ForegroundColor White
$publisherEmail = Read-RequiredValue -Prompt "APIM publisher email" -Default $PublisherEmail
$publisherName = Read-RequiredValue -Prompt "APIM publisher display name" -Default $(if ($PublisherName) { $PublisherName } else { "Genie" })

$defaultLlmDeploymentName = Read-RequiredValue -Prompt "Deployment name (agents will reference this exact name)" -Default $DefaultLlmDeploymentName
$defaultLlmModel = Read-RequiredValue -Prompt "Model name" -Default $DefaultLlmModel
$azureModelCatalog = @(
    Invoke-AzJson cognitiveservices model list --location $Location
)
$modelDeployments = @(
    Resolve-LatestAzureModelDeployment `
        -DeploymentName $defaultLlmDeploymentName `
        -ModelName $defaultLlmModel `
        -Catalog $azureModelCatalog
)

# ---------------------------------------------------------------------------
# Stage 2: offer to remove a previous Genie deployment for this exact
# (ResourcePrefix, EnvironmentName) pair before provisioning a fresh one -
# scoped narrowly to scripts/remove_existing_deployment.ps1's own resource
# group only (never per-mission prototype resource groups). Always
# interactive/confirmed - never deletes anything without you explicitly
# typing the resource group name back.
# ---------------------------------------------------------------------------
Write-Stage "Stage 2/10: check for a previous deployment to remove first"
& (Join-Path $repoRoot "scripts\remove_existing_deployment.ps1") `
    -SubscriptionId $SubscriptionId `
    -EnvironmentName $EnvironmentName `
    -ResourcePrefix $ResourcePrefix `
    -ResourceGroupName $ResourceGroupName `
    -Location $Location `
    -Yes:$RemovePreviousDeployment
if ($LASTEXITCODE -ne 0) {
    throw "Pre-deployment cleanup check failed."
}

$expectedResourceGroup = if ([string]::IsNullOrWhiteSpace($ResourceGroupName)) {
    "$ResourcePrefix-$EnvironmentName-rg"
}
else {
    $ResourceGroupName
}
$provisionedBackend = Find-ProvisionedGenieBackend `
    -SubscriptionId $SubscriptionId `
    -ResourceGroup $expectedResourceGroup
$reuseProvisionedBackend = $false
if ($null -ne $provisionedBackend) {
    if ($NonInteractive) {
        $reuseProvisionedBackend = $true
    }
    else {
        $provisionAgain = Read-Host "A healthy Genie backend is already provisioned. Provision it again? (y/N)"
        $reuseProvisionedBackend = $provisionAgain -notmatch '^(y|yes)$'
    }
}
elseif (-not $NonInteractive) {
    $provisionBackend = Read-Host "No healthy Genie backend was found. Provision it now? (Y/n)"
    if ($provisionBackend -match '^(n|no)$') {
        throw "Backend provisioning was declined, but no healthy Genie backend exists to reuse."
    }
}

if ($reuseProvisionedBackend) {
    Write-Host "Reusing healthy Genie backend '$($provisionedBackend.name)' revision '$($provisionedBackend.revision)'." -ForegroundColor Green
}
else {
    Write-Host "`nGenie's backend connects to GitHub repositories through a GitHub MCP" -ForegroundColor White
    Write-Host "server using a token YOU provide - never a token belonging to anyone else." -ForegroundColor White
    Write-Host "Create a fine-grained Personal Access Token at https://github.com/settings/tokens" -ForegroundColor White
    Write-Host "(read-only repo scopes are enough unless you plan to test branch/PR creation)." -ForegroundColor White
    $githubMcpToken = [Environment]::GetEnvironmentVariable("GENIE_GITHUB_MCP_TOKEN")
    if ([string]::IsNullOrWhiteSpace($githubMcpToken)) {
        $githubMcpToken = Read-SecretValue -Prompt "GitHub Personal Access Token"
    }
}

# ---------------------------------------------------------------------------
# Stage 3: deployment readiness validation (fail closed).
# ---------------------------------------------------------------------------
Write-Stage "Stage 3/10: deployment readiness validation"
$pythonExe = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-Host "Creating backend virtual environment (first run only)..." -ForegroundColor Yellow
    Push-Location (Join-Path $repoRoot "backend")
    try {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Failed to create the backend Python virtual environment." }
        & .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip in the backend virtual environment." }
        & .venv\Scripts\python.exe -m pip install --quiet -e ".[dev]"
        if ($LASTEXITCODE -ne 0) { throw "Failed to install backend dependencies." }
    }
    finally {
        Pop-Location
    }
}
$env:GENIE_DEFAULT_LLM = $defaultLlmDeploymentName
$inventoryOutput = & $pythonExe (Join-Path $repoRoot "scripts\export_foundry_inventory.py")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to resolve the model deployments required by the configured Foundry agents."
}
$inventory = ($inventoryOutput -join [Environment]::NewLine) | ConvertFrom-Json
$requiredAgentModels = @(
    $inventory |
        ForEach-Object { $_.model_deployment_ref } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Sort-Object -Unique
)
foreach ($requiredDeploymentName in $requiredAgentModels) {
    if ($requiredDeploymentName -eq $defaultLlmDeploymentName) {
        continue
    }
    Write-Host "`nAgent configuration also requires model deployment '$requiredDeploymentName'." -ForegroundColor White
    $configuredModel = $FoundryModelCatalog[$requiredDeploymentName]
    $requiredModelName = Read-RequiredValue -Prompt "Azure model name for '$requiredDeploymentName'" -Default $configuredModel.model
    $modelDeployments += Resolve-LatestAzureModelDeployment `
        -DeploymentName $requiredDeploymentName `
        -ModelName $requiredModelName `
        -Catalog $azureModelCatalog
}
$env:GENIE_DEPLOY_SUBSCRIPTION_ID = $SubscriptionId
Push-Location $repoRoot
try {
    & $pythonExe "scripts/validate_deployment_readiness.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Deployment readiness check failed (exit code $LASTEXITCODE). Register the missing resource provider(s) it lists, then re-run this script."
    }
}
finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# Stage 3: provision infrastructure (infra/main.bicep).
# ---------------------------------------------------------------------------
Write-Stage "Stage 4/10: provisioning infrastructure (this can take 10-20 minutes)"
$deploymentName = "genie-$EnvironmentName-$(Get-Date -Format 'yyyyMMddHHmmss')"
# Array-typed Bicep parameters (foundryModelDeployments) are passed via a
# generated ARM parameters file rather than an inline `name=value` CLI
# argument - deliberately avoids any risk of PowerShell/Azure CLI shell
# quoting mangling embedded JSON quotes/brackets.
$overlayParamsFile = Join-Path ([System.IO.Path]::GetTempPath()) "genie-quickstart-params-$([guid]::NewGuid().ToString('N')).json"
$armParameters = @{
    '$schema'      = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
    contentVersion = '1.0.0.0'
    parameters     = @{
        environmentName         = @{ value = $EnvironmentName }
        location                = @{ value = $Location }
        resourcePrefix           = @{ value = $ResourcePrefix }
        resourceGroupNameOverride = @{ value = $ResourceGroupName }
        deployerPrincipalId       = @{ value = $deployerPrincipalId }
        foundryModelDeployments  = @{ value = $modelDeployments }
        provisionBackendContainerApp = @{ value = -not $reuseProvisionedBackend }
        existingBackendContainerAppName = @{ value = $(if ($reuseProvisionedBackend) { $provisionedBackend.name } else { "" }) }
    }
}
try {
    $armParameters | ConvertTo-Json -Depth 10 | Set-Content -Path $overlayParamsFile -Encoding utf8
    az deployment sub create `
        --name $deploymentName `
        --location $Location `
        --subscription $SubscriptionId `
        --template-file (Join-Path $repoRoot "infra\main.bicep") `
        --parameters "@$overlayParamsFile" `
        --only-show-errors -o none
    if ($LASTEXITCODE -ne 0) {
        throw "Infrastructure deployment failed."
    }
}
finally {
    if (Test-Path $overlayParamsFile) { Remove-Item -Path $overlayParamsFile -Force }
}
$outputs = (Invoke-AzJson deployment sub show --name $deploymentName --subscription $SubscriptionId).properties.outputs
$resourceGroup = $outputs.resourceGroupName.value
$containerAppName = $outputs.backendContainerAppName.value
$containerRegistryName = $outputs.containerRegistryName.value
$acrLoginServer = $outputs.containerRegistryLoginServer.value
$cosmosDbEndpoint = $outputs.cosmosDbEndpoint.value
# AI Foundry's own account metadata (`properties.endpoints["AI Foundry
# API"]` / `["Content Understanding"]`) advertises
# `<account>.services.ai.azure.com`, not the generic `aiFoundryEndpoint`
# output's legacy `.cognitiveservices.azure.com` host - using the latter
# for AIProjectClient/Content Understanding 404s on a freshly provisioned
# account. `aiFoundryApiEndpoint` is the dedicated, deterministic output
# for this (see infra/modules/ai-foundry.bicep).
$aiFoundryAccountEndpoint = $outputs.aiFoundryApiEndpoint.value.TrimEnd("/")
$aiFoundryProjectName = $outputs.aiFoundryProjectName.value
$aiFoundryEndpoint = "$aiFoundryAccountEndpoint/api/projects/$aiFoundryProjectName"
$containerAppsEnvironmentId = $outputs.containerAppsEnvironmentId.value
$storageAccountName = $outputs.storageAccountName.value
$keyVaultUri = $outputs.keyVaultUri.value
$staticWebAppHostname = $outputs.staticWebAppDefaultHostname.value
$staticWebAppName = $outputs.staticWebAppName.value
$allowedOrigin = "https://$staticWebAppHostname"
Write-Host "Resource group: $resourceGroup" -ForegroundColor Green

if ([string]::IsNullOrWhiteSpace($containerAppName) -or [string]::IsNullOrWhiteSpace($containerRegistryName)) {
    throw "infra/main.bicep did not produce a backend Container App/Container Registry - pass deployContainerRegistryAndBackendApp=true or provision them yourself before continuing."
}

# ---------------------------------------------------------------------------
# Stage 4: build and push the real backend image.
# ---------------------------------------------------------------------------
if ($reuseProvisionedBackend) {
    Write-Stage "Stage 5/10: reusing the provisioned backend"
    $backendImage = $provisionedBackend.image
}
else {
    Write-Stage "Stage 5/10: building and pushing the backend image"
    $imageTag = (git -C $repoRoot rev-parse --short HEAD 2>$null)
    if ([string]::IsNullOrWhiteSpace($imageTag)) { $imageTag = Get-Date -Format "yyyyMMddHHmmss" }
    $backendImage = "$acrLoginServer/genie-backend:$imageTag"
    az acr build `
        --subscription $SubscriptionId `
        --registry $containerRegistryName `
        --image "genie-backend:$imageTag" `
        --file (Join-Path $repoRoot "backend\Dockerfile") `
        $repoRoot `
        --only-show-errors
    if ($LASTEXITCODE -ne 0) {
        throw "Backend image build failed."
    }
}

# ---------------------------------------------------------------------------
# Stage 5: provision the dedicated API Management gateway.
# ---------------------------------------------------------------------------
Write-Stage "Stage 6/10: provisioning the API Management gateway (first run commonly takes 30-45 minutes)"
$gatewayParameters = @{
    SubscriptionId = $SubscriptionId
    ResourceGroup = $resourceGroup
    ContainerAppName = $containerAppName
    AllowedOrigin = $allowedOrigin
    PublisherEmail = $publisherEmail
    PublisherName = $publisherName
    BootstrapBackend = -not $reuseProvisionedBackend
}
$gateway = & (Join-Path $repoRoot "scripts\deploy_platform_gateway.ps1") @gatewayParameters | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "Platform gateway deployment failed."
}
$gatewayUrl = $gateway.gatewayUrl
Write-Host "Gateway URL: $gatewayUrl" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Stage 6: provision every Genie agent before the backend starts. Backend
# startup fails closed until every configured Foundry agent exists.
# ---------------------------------------------------------------------------
Write-Stage "Stage 7/10: provisioning Azure AI Foundry agents"
$env:GENIE_AZURE_FOUNDRY_ENDPOINT = $aiFoundryEndpoint
$env:GENIE_AZURE_FOUNDRY_PROJECT_NAME = $aiFoundryProjectName
Push-Location $repoRoot
try {
    & $pythonExe "scripts/provision_foundry_agents.py" --endpoint $aiFoundryEndpoint
    if ($LASTEXITCODE -ne 0) {
        throw "Foundry agent provisioning failed."
    }
    & $pythonExe "scripts/validate_foundry_agents.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Foundry agent configuration validation failed."
    }
    & $pythonExe "scripts/sync_foundry_agents.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Foundry agent live synchronization failed."
    }
}
finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# Stage 7: store the GitHub MCP token and roll out the real backend image.
# ---------------------------------------------------------------------------
if ($reuseProvisionedBackend) {
    Write-Stage "Stage 8/10: preserving the provisioned backend"
}
else {
    Write-Stage "Stage 8/10: configuring and rolling out the real backend"
    az containerapp secret set `
        --subscription $SubscriptionId `
        --resource-group $resourceGroup `
        --name $containerAppName `
        --secrets "github-mcp-token=$githubMcpToken" `
        --only-show-errors -o none
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to store the GitHub MCP token on the Container App."
    }
    Remove-Variable githubMcpToken -ErrorAction SilentlyContinue

    # Speech Services routes stay on the legacy `.cognitiveservices.azure.com`
    # host per Azure's own account metadata - unlike $aiFoundryAccountEndpoint
    # above, this is deliberately sourced from the generic `aiFoundryEndpoint`
    # output, not `aiFoundryApiEndpoint`.
    $aiServicesEndpoint = $outputs.aiFoundryEndpoint.value.TrimEnd("/")
    $backendEnvironmentVariables = @(
        "GENIE_SERVICE_NAME=genie-backend",
        "GENIE_ENVIRONMENT=development",
        "GENIE_ALLOW_MOCK_AGENTS=false",
        "GENIE_ALLOW_LOCAL_AGENTS=false",
        "GENIE_USE_SYNTHETIC_DATA=false",
        "GENIE_GOVERNANCE_PROVIDER=local",
        "GENIE_AZURE_FOUNDRY_ENDPOINT=$aiFoundryEndpoint",
        "GENIE_AZURE_FOUNDRY_PROJECT_NAME=$aiFoundryProjectName",
        "GENIE_AZURE_FOUNDRY_RESOURCE_GROUP=$resourceGroup",
        "GENIE_AZURE_SPEECH_ENDPOINT=$aiServicesEndpoint",
        "GENIE_KEY_VAULT_URI=$keyVaultUri",
        "GENIE_AZURE_SUBSCRIPTION_ID=$SubscriptionId",
        "GENIE_DEPLOYMENT_RESOURCE_GROUP=$resourceGroup",
        "GENIE_DEPLOYMENT_ACR_NAME=$containerRegistryName",
        "GENIE_DEPLOYMENT_CONTAINER_APPS_ENVIRONMENT_ID=$containerAppsEnvironmentId",
        "GENIE_DEPLOYMENT_LOCATION=$Location",
        "GENIE_DEPLOYMENT_STORAGE_ACCOUNT_NAME=$storageAccountName",
        "GENIE_DEFAULT_LLM=$defaultLlmDeploymentName"
    )
    az containerapp update `
        --subscription $SubscriptionId `
        --resource-group $resourceGroup `
        --name $containerAppName `
        --set-env-vars @backendEnvironmentVariables `
        --only-show-errors -o none | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to configure the Genie backend runtime environment."
    }

    $revisionSuffix = ("q" + (Get-Date -Format "MMddHHmm"))
    & (Join-Path $repoRoot "scripts\deploy_backend.ps1") `
        -SubscriptionId $SubscriptionId `
        -ResourceGroup $resourceGroup `
        -ContainerAppName $containerAppName `
        -BackendImage $backendImage `
        -AllowedOrigin $allowedOrigin `
        -GatewayUrl $gatewayUrl `
        -MemoryStoreEndpoint $cosmosDbEndpoint `
        -GitHubMcpEndpoint $githubMcpEndpoint `
        -GitHubMcpTokenSecretName "github-mcp-token" `
        -PrototypeApiGatewayPublisherEmail $publisherEmail `
        -PrototypeApiGatewayPublisherName $publisherName `
        -PrototypeMaxActivePerOwner 0 `
        -RevisionSuffix $revisionSuffix
    if ($LASTEXITCODE -ne 0) {
        throw "Backend rollout failed."
    }
}

# ---------------------------------------------------------------------------
# Stage 8: build and deploy the frontend.
# ---------------------------------------------------------------------------
if (-not $SkipFrontendDeploy) {
    Write-Stage "Stage 9/10: building and deploying the frontend"
    Push-Location (Join-Path $repoRoot "frontend")
    try {
        $env:VITE_GENIE_API_BASE_URL = $gatewayUrl
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
        $swaToken = az staticwebapp secrets list `
            --subscription $SubscriptionId `
            --resource-group $resourceGroup `
            --name $staticWebAppName `
            --query properties.apiKey -o tsv --only-show-errors
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($swaToken)) {
            throw "Failed to retrieve the Static Web App deployment token."
        }
        npx --yes @azure/static-web-apps-cli@latest deploy dist --deployment-token $swaToken --env production
        if ($LASTEXITCODE -ne 0) { throw "Frontend deploy failed." }
    }
    finally {
        Remove-Item Env:\VITE_GENIE_API_BASE_URL -ErrorAction SilentlyContinue
        Pop-Location
    }
}
else {
    Write-Stage "Stage 9/10: skipped (-SkipFrontendDeploy)"
}

# ---------------------------------------------------------------------------
# Stage 9: health checks + summary.
# ---------------------------------------------------------------------------
Write-Stage "Stage 10/10: verifying health"
$live = Invoke-WebRequest -Uri "$gatewayUrl/health/live" -UseBasicParsing -TimeoutSec 30
$ready = Invoke-WebRequest -Uri "$gatewayUrl/health/ready" -UseBasicParsing -TimeoutSec 30
if ($live.StatusCode -ne 200 -or $ready.StatusCode -ne 200) {
    throw "Genie backend health verification failed."
}
Write-Host "health/live: $($live.StatusCode)   health/ready: $($ready.StatusCode)" -ForegroundColor Green

if (-not $SkipFrontendDeploy) {
    $frontendUrl = "https://$staticWebAppHostname"
    $frontendDeadline = (Get-Date).AddMinutes(5)
    do {
        try {
            $frontend = Invoke-WebRequest -Uri $frontendUrl -UseBasicParsing -TimeoutSec 30
            $frontendReady = (
                $frontend.StatusCode -eq 200 -and
                $frontend.Content -match "Genie.+Agentic Experience Center"
            )
        }
        catch {
            $frontendReady = $false
        }
        if (-not $frontendReady) {
            Start-Sleep -Seconds 10
        }
    } while (-not $frontendReady -and (Get-Date) -lt $frontendDeadline)
    if (-not $frontendReady) {
        throw "Genie frontend verification failed at '$frontendUrl'."
    }
    Write-Host "frontend: 200   $frontendUrl" -ForegroundColor Green
}

Write-Host "`n=== Done ===" -ForegroundColor Cyan
Write-Host "Resource group:   $resourceGroup"
Write-Host "API gateway:      $gatewayUrl"
if (-not $SkipFrontendDeploy) {
    Write-Host "Frontend:         https://$staticWebAppHostname"
}
Write-Host "`nThis is an art-of-the-possible evaluation environment - see 'Purpose and use boundary' in README.md before any production use." -ForegroundColor Yellow
