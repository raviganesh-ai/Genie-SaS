from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[4]


def _read(relative_path: str) -> str:
    return (_REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_quickstart_orders_verified_parent_stages_before_dependents() -> None:
    script = _read("scripts/deploy_quickstart.ps1")

    stages = [
        "Stage 4/10: provisioning infrastructure",
        "Stage 5/10: building and pushing the backend image",
        "Stage 6/10: provisioning the API Management gateway",
        "Stage 7/10: provisioning Azure AI Foundry agents",
        "Stage 8/10: configuring and rolling out the real backend",
        "Stage 9/10: building and deploying the frontend",
        "Stage 10/10: verifying health",
    ]

    positions = [script.index(stage) for stage in stages]
    assert positions == sorted(positions)
    assert "BootstrapBackend = -not $reuseProvisionedBackend" in script
    assert 'throw "Foundry agent provisioning failed."' in script
    assert 'throw "Foundry agent live synchronization failed."' in script
    assert "az ad signed-in-user show --query id" in script


def test_quickstart_keeps_the_active_subscription_when_switch_is_declined() -> None:
    script = _read("scripts/deploy_quickstart.ps1")

    identity_start = script.index('Write-Stage "Stage 0/10: confirm your Azure identity"')
    identity_end = script.index('Write-Stage "Stage 1/10: collect deployment parameters"')
    identity_stage = script[identity_start:identity_end]

    assert 'Read-Host "Use a different Azure account/subscription? (y/N)"' in identity_stage
    assert "if ($switchAccount -match '^(y|yes)$')" in identity_stage
    assert "else {\n        $SubscriptionId = $account.id\n    }" in identity_stage
    assert identity_stage.index("$subscriptions = Invoke-AzJson account list") < identity_stage.index(
        "else {\n        $SubscriptionId = $account.id\n    }"
    )


def test_quickstart_configures_required_backend_runtime_dependencies() -> None:
    script = _read("scripts/deploy_quickstart.ps1")

    required_settings = {
        "GENIE_AZURE_FOUNDRY_ENDPOINT",
        "GENIE_AZURE_FOUNDRY_PROJECT_NAME",
        "GENIE_AZURE_FOUNDRY_RESOURCE_GROUP",
        "GENIE_AZURE_SUBSCRIPTION_ID",
        "GENIE_DEPLOYMENT_RESOURCE_GROUP",
        "GENIE_DEPLOYMENT_ACR_NAME",
        "GENIE_DEPLOYMENT_CONTAINER_APPS_ENVIRONMENT_ID",
        "GENIE_DEPLOYMENT_LOCATION",
        "GENIE_DEPLOYMENT_STORAGE_ACCOUNT_NAME",
        "GENIE_DEFAULT_LLM",
    }

    for setting in required_settings:
        assert f"{setting}=" in script


def test_quickstart_supports_exact_resource_group_and_noninteractive_inputs() -> None:
    script = _read("scripts/deploy_quickstart.ps1")
    main_template = _read("infra/main.bicep")

    assert "[string]$ResourceGroupName" in script
    assert "[switch]$NonInteractive" in script
    assert "resourceGroupNameOverride = @{ value = $ResourceGroupName }" in script
    assert 'GetEnvironmentVariable("GENIE_GITHUB_MCP_TOKEN")' in script
    assert "param resourceGroupNameOverride string = ''" in main_template
    assert "empty(resourceGroupNameOverride)" in main_template


def test_quickstart_defaults_every_agent_to_gpt_5_mini() -> None:
    script = _read("scripts/deploy_quickstart.ps1")
    agent_registry = _read("config/agents/registry.yaml")

    assert '[string]$DefaultLlmDeploymentName = "gpt-5-mini"' in script
    assert '[string]$DefaultLlmModel = "gpt-5-mini"' in script
    assert "model_deployment_ref: gpt-5-1" not in agent_registry
    assert agent_registry.count("model_deployment_ref: gpt-5-mini") == 2


def test_quickstart_resolves_the_latest_regional_model_version() -> None:
    script = _read("scripts/deploy_quickstart.ps1")

    assert "Invoke-AzJson cognitiveservices model list --location $Location" in script
    assert "function Resolve-LatestAzureModelDeployment" in script
    assert "$_.model.name -eq $ModelName" in script
    assert "Get-ModelVersionSortKey -Version $_.model.version" in script
    assert "version = $selectedModel.model.version" in script
    assert "Model version (check" not in script
    assert "[string]$DefaultLlmVersion" not in script


def test_quickstart_uses_the_current_foundry_provisioning_cli_contract() -> None:
    script = _read("scripts/deploy_quickstart.ps1")

    provisioning_line = next(
        line for line in script.splitlines() if '"scripts/provision_foundry_agents.py"' in line
    )
    assert "--endpoint" in provisioning_line
    assert "--project" not in provisioning_line


def test_bootstrap_gateway_defers_readiness_to_real_backend_rollout() -> None:
    script = _read("scripts/deploy_platform_gateway.ps1")

    assert "[switch]$BootstrapBackend" in script
    assert script.count("if (-not $BootstrapBackend)") == 2
    assert script.count('"pending_backend_rollout"') == 2


def test_backend_rollout_waits_for_readiness_without_a_default_deadline() -> None:
    script = _read("scripts/deploy_backend.ps1")

    assert "[int]$WaitTimeoutSeconds = 0" in script
    assert "while ($true)" in script
    assert "containerapp revision show" in script
    assert '$revision.properties.provisioningState -match "Failed$"' in script
    assert '$revision.properties.runningState -match "Failed$"' in script
    assert "function Write-BackendFailureDiagnostics" in script
    assert "--revision $RevisionName" in script
    assert '@("system", "console")' in script
    assert '$revision.properties.healthState -eq "Healthy"' in script
    assert "did not become ready within 600 seconds" not in script


def test_quickstart_preserves_an_existing_healthy_genie_backend() -> None:
    script = _read("scripts/deploy_quickstart.ps1")
    main_template = _read("infra/main.bicep")
    foundational_template = _read("infra/modules/foundational-resources.bicep")

    assert "function Find-ProvisionedGenieBackend" in script
    assert '$backendContainer.image -match "/genie-backend:[^/]+$"' in script
    assert '$_.name -eq "GENIE_SERVICE_NAME" -and $_.value -eq "genie-backend"' in script
    assert "A healthy Genie backend is already provisioned. Provision it again? (y/N)" in script
    assert "No healthy Genie backend was found. Provision it now? (Y/n)" in script
    assert "Backend provisioning was declined, but no healthy Genie backend exists to reuse." in script
    assert "provisionBackendContainerApp = @{ value = -not $reuseProvisionedBackend }" in script
    assert "Stage 5/10: reusing the provisioned backend" in script
    assert "Stage 8/10: preserving the provisioned backend" in script
    assert "BootstrapBackend = -not $reuseProvisionedBackend" in script
    assert "param provisionBackendContainerApp bool = true" in main_template
    assert "param existingBackendContainerAppName string = ''" in main_template
    assert "if (deployContainerRegistryAndBackendApp && provisionBackendContainerApp)" in foundational_template
    assert "existingBackendContainerApp" in foundational_template


def test_foundry_lookup_only_treats_not_found_as_unprovisioned() -> None:
    script = _read("scripts/provision_foundry_agents.py")

    assert "except ResourceNotFoundError:" in script
    assert "except Exception:" not in script


def test_foundry_infrastructure_grants_the_quickstart_operator_data_plane_access() -> None:
    main_template = _read("infra/main.bicep")
    foundry_module = _read("infra/modules/ai-foundry.bicep")

    assert "param deployerPrincipalId string = ''" in main_template
    assert "deployerPrincipalId: deployerPrincipalId" in main_template
    assert "deployerCognitiveServicesUserRoleAssignment" in foundry_module
    assert "if (!empty(deployerPrincipalId))" in foundry_module


def test_foundry_endpoint_uses_the_services_ai_azure_com_host() -> None:
    foundry_module = _read("infra/modules/ai-foundry.bicep")
    foundational_template = _read("infra/modules/foundational-resources.bicep")
    main_template = _read("infra/main.bicep")
    script = _read("scripts/deploy_quickstart.ps1")

    # The generic `endpoint` output (legacy `.cognitiveservices.azure.com`
    # host) must still exist for Speech Services, but AIProjectClient and
    # Content Understanding require the dedicated `.services.ai.azure.com`
    # host - conflating the two is what caused Content Understanding's
    # `/contentunderstanding/*` routes to 404 at backend startup.
    assert "output endpoint string = foundryAccount.properties.endpoint" in foundry_module
    assert (
        "output aiFoundryApiEndpoint string = 'https://${accountName}.services.ai.azure.com'"
        in foundry_module
    )
    assert "output aiFoundryApiEndpoint string = aiFoundry.outputs.aiFoundryApiEndpoint" in foundational_template
    assert (
        "output aiFoundryApiEndpoint string = foundationalResources.outputs.aiFoundryApiEndpoint"
        in main_template
    )
    assert '$aiFoundryAccountEndpoint = $outputs.aiFoundryApiEndpoint.value.TrimEnd("/")' in script
    assert '$aiServicesEndpoint = $outputs.aiFoundryEndpoint.value.TrimEnd("/")' in script


def test_quickstart_validates_content_understanding_region_support() -> None:
    script = _read("scripts/deploy_quickstart.ps1")
    registry_path = _REPO_ROOT / "config/deployment/content_understanding_regions.yaml"
    registry = registry_path.read_text(encoding="utf-8")

    assert "function Get-ContentUnderstandingSupportedRegions" in script
    assert "function Assert-ContentUnderstandingSupportedRegion" in script
    assert "Assert-ContentUnderstandingSupportedRegion -RepoRoot $repoRoot -Location $Location" in script
    assert script.index("$contentUnderstandingSupportedRegions = Get-ContentUnderstandingSupportedRegions") < script.index(
        "Assert-ContentUnderstandingSupportedRegion -RepoRoot $repoRoot -Location $Location"
    )
    assert "- eastus2" in registry
    assert "- centralus" not in registry


def test_quickstart_presents_region_as_an_indexed_selection_list() -> None:
    script = _read("scripts/deploy_quickstart.ps1")

    menu_start = script.index('Write-Host "`nAzure region (must support Content Understanding')
    menu_end = script.index("Assert-ContentUnderstandingSupportedRegion", menu_start)
    menu_body = script[menu_start:menu_end]

    # The operator picks a numbered index - never types a region name -
    # matching the existing subscription-picker convention in Stage 0.
    assert 'Write-Host "  [$i] $($contentUnderstandingSupportedRegions[$i])"' in menu_body
    assert 'Read-RequiredValue -Prompt "Pick a region by index"' in menu_body
    assert "[int]::TryParse($regionIndexInput, [ref]$parsedRegionIndex)" in menu_body
    assert "$Location = $contentUnderstandingSupportedRegions[$parsedRegionIndex]" in menu_body
    assert "if ($NonInteractive)" in script[
        script.index("Stage 1/10: collect deployment parameters") : menu_start
    ]


def test_key_vault_is_private_and_policy_compliant() -> None:
    key_vault_module = _read("infra/modules/key-vault.bicep")
    private_endpoint_module = _read("infra/modules/key-vault-private-endpoint.bicep")

    assert "publicNetworkAccess: 'Disabled'" in key_vault_module
    assert "defaultAction: 'Deny'" in key_vault_module
    assert "key-vault-private-endpoint.bicep" in key_vault_module
    assert "privatelink.vaultcore.azure.net" in private_endpoint_module
    assert "'vault'" in private_endpoint_module
