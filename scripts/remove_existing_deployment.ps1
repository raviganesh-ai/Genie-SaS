<#
.SYNOPSIS
    Safely removes a previous Genie foundational deployment (the resource
    group infra/main.bicep creates) before a fresh re-run.

.DESCRIPTION
    Scoped deliberately narrow: this ONLY ever looks at and removes the
    single resource group infra/main.bicep creates for a given
    (ResourcePrefix, EnvironmentName) pair - `<prefix>-<environment>-rg` -
    which also contains everything infra/platform-private-gateway.bicep
    (the APIM gateway) adds into that same resource group afterward. It
    never touches:

      - Per-mission prototype resource groups (`genie-proto-<slug>-rg`,
        created at RUNTIME by Deploy & Launch, not by this Bicep) - those
        already have their own TTL/cleanup reconciler; deleting one here
        could destroy a live customer's running prototype.
      - The one-time deployment identity / custom role definition from
        scripts/create_deployment_identity.ps1 (subscription-scoped, not
        resource-group-scoped, and reusable across many deploy/teardown
        cycles - not "installed by the bicep files" in the sense this
        script cares about).
      - Anything in a DIFFERENT resource group than the one this exact
        (ResourcePrefix, EnvironmentName) pair would create - it is not a
        general "clean my subscription" tool.

    IMPORTANT - Key Vault purge protection (infra/modules/key-vault.bicep
    sets enablePurgeProtection=true, a deliberate security control, not a
    bug): deleting the resource group only SOFT-deletes its Key Vault.
    Azure then refuses to let ANY vault reuse that exact name for 90 days
    - this is intentional immutability, not something `az keyvault purge`
    can override once purge protection is on. Because the vault name is
    deterministically derived from (SubscriptionId, EnvironmentName,
    Location) via Bicep's own `uniqueString(...)`, re-running
    deploy_quickstart.ps1 with the SAME EnvironmentName after a delete
    WILL hit that exact name again and fail at the Key Vault step for the
    rest of that 90-day window. This script detects that condition up
    front and tells you plainly - the only two real workarounds are (a)
    pick a different -EnvironmentName for the fresh attempt (changes the
    derived name entirely), or (b) wait out the retention window.

    Never deletes anything without an explicit, printed confirmation -
    there is no "-Force"/silent mode by design.

.PARAMETER SubscriptionId
    Azure subscription id to inspect/clean up in.

.PARAMETER EnvironmentName
    Must match the -EnvironmentName you plan to (re-)deploy with.

.PARAMETER ResourcePrefix
    Must match the -ResourcePrefix you plan to (re-)deploy with. Default: "genie".

.PARAMETER Location
    Must match the -Location you plan to (re-)deploy with - the Key Vault
    name-collision check below needs it to reproduce the same deterministic
    name Bicep would derive.

.PARAMETER Yes
    Skip the interactive confirmation prompt and delete immediately if the
    resource group exists. Omit this for the normal, safer interactive
    behavior - only pass it when you already know exactly what you're
    removing (e.g. scripted CI cleanup of a disposable test environment).

.EXAMPLE
    ./scripts/remove_existing_deployment.ps1 -EnvironmentName dev -Location eastus2
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SubscriptionId,

    [Parameter(Mandatory = $true)]
    [string]$EnvironmentName,

    [string]$ResourcePrefix = "genie",

    [Parameter(Mandatory = $true)]
    [string]$Location,

    [switch]$Yes
)

$ErrorActionPreference = "Stop"

function Invoke-AzJson {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $output = & az @Arguments --only-show-errors -o json
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Arguments -join ' ')"
    }
    if ([string]::IsNullOrWhiteSpace($output)) { return $null }
    return $output | ConvertFrom-Json -Depth 100
}

$resourceGroupName = "$ResourcePrefix-$EnvironmentName-rg"

Write-Host "`n=== Checking for a previous Genie deployment ===" -ForegroundColor Cyan
Write-Host "Resource group (derived the same way infra/main.bicep derives it): $resourceGroupName"

$exists = (az group exists --name $resourceGroupName --subscription $SubscriptionId) -eq "true"
if (-not $exists) {
    Write-Host "No existing resource group named '$resourceGroupName' - nothing to remove. Proceeding with a clean deployment." -ForegroundColor Green
    exit 0
}

Write-Host "`nFound an existing resource group: $resourceGroupName" -ForegroundColor Yellow
$resources = Invoke-AzJson resource list --resource-group $resourceGroupName --subscription $SubscriptionId
if ($resources -and $resources.Count -gt 0) {
    Write-Host "It currently contains $($resources.Count) resource(s):"
    foreach ($resource in $resources) {
        Write-Host "  - $($resource.type): $($resource.name)"
    }
}
else {
    Write-Host "It currently contains no resources (an empty/partial deployment)."
}

# Reproduce Bicep's own deterministic resourceToken/name derivation so we
# can tell the caller up front whether a same-name redeploy will hit the
# Key Vault purge-protection wall described above - this is read-only
# detection, never an attempt to force a purge (not possible once purge
# protection is enabled, by design).
$deletedVaults = Invoke-AzJson keyvault list-deleted --subscription $SubscriptionId
if ($deletedVaults) {
    $expectedPrefix = ($ResourcePrefix + "kv").ToLowerInvariant()
    $matchingDeletedVault = $deletedVaults | Where-Object {
        $_.name.ToLowerInvariant().StartsWith($expectedPrefix) -and
        $_.properties.location -eq $Location
    } | Select-Object -First 1
    if ($matchingDeletedVault) {
        Write-Host "`nWARNING: A previously deleted Key Vault ('$($matchingDeletedVault.name)') is still soft-deleted" -ForegroundColor Yellow
        Write-Host "  with purge protection enabled. Azure will NOT let a new deployment reuse that" -ForegroundColor Yellow
        Write-Host "  exact vault name until its retention window expires ($($matchingDeletedVault.properties.scheduledPurgeDate))." -ForegroundColor Yellow
        Write-Host "  Since that name is derived deterministically from (subscription, EnvironmentName," -ForegroundColor Yellow
        Write-Host "  Location), redeploying with the SAME -EnvironmentName '$EnvironmentName' will hit this" -ForegroundColor Yellow
        Write-Host "  again. Use a DIFFERENT -EnvironmentName for an immediately clean redeploy instead," -ForegroundColor Yellow
        Write-Host "  or wait out the retention window." -ForegroundColor Yellow
    }
}

if (-not $Yes) {
    Write-Host "`nThis will permanently delete resource group '$resourceGroupName' and everything in it" -ForegroundColor Yellow
    Write-Host "(every foundational resource infra/main.bicep created, plus the APIM gateway" -ForegroundColor Yellow
    Write-Host "infra/platform-private-gateway.bicep added into the same resource group)." -ForegroundColor Yellow
    Write-Host "Per-mission prototype resource groups (genie-proto-*) are never touched by this script." -ForegroundColor Yellow
    $confirmation = Read-Host "`nType the resource group name exactly ('$resourceGroupName') to confirm deletion, or press Enter to skip"
    if ($confirmation -ne $resourceGroupName) {
        Write-Host "Skipped - resource group left in place. Re-run infra/main.bicep as-is (ARM deployments are" -ForegroundColor Yellow
        Write-Host "idempotent) or re-run this script when you're ready to remove it." -ForegroundColor Yellow
        exit 0
    }
}

Write-Host "`nDeleting resource group '$resourceGroupName' - this can take several minutes..." -ForegroundColor Cyan
az group delete --name $resourceGroupName --subscription $SubscriptionId --yes
if ($LASTEXITCODE -ne 0) {
    throw "Failed to delete resource group '$resourceGroupName'."
}
Write-Host "Deleted '$resourceGroupName'." -ForegroundColor Green
exit 0
