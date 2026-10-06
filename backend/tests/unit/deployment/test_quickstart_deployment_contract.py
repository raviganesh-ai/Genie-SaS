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
    assert "-BootstrapBackend" in script
    assert 'throw "Foundry agent provisioning failed."' in script
    assert 'throw "Foundry agent live synchronization failed."' in script
    assert "az ad signed-in-user show --query id" in script


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
