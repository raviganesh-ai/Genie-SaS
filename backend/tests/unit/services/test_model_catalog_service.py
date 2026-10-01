"""Unit tests for ModelCatalogService's resource-group resolution.

Regression coverage for a real production bug: a Genie-SaS environment can
provision its own dedicated infrastructure while deliberately reusing an
existing Azure AI Foundry project that lives in a *different* resource
group (to avoid re-registering every Foundry agent). Before
``azure_foundry_resource_group`` existed, the model catalog service always
looked up the Foundry account inside ``deployment_resource_group`` - which
is correct only when the two happen to be the same resource group - and
failed with ``ResourceNotFound`` whenever they weren't.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config.settings import Settings
from app.services.model_catalog_service import (
    ModelCatalogService,
    ModelCatalogUnavailableError,
)


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[call-arg]


class _FakeDeploymentSource:
    def __init__(self, models: list[str]) -> None:
        self.models = models
        self.calls: list[dict[str, str]] = []

    def list_model_deployments(
        self, *, subscription_id: str, resource_group: str, account_name: str
    ) -> list[str]:
        self.calls.append(
            {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "account_name": account_name,
            }
        )
        return self.models


_FAKE_AGENT_REGISTRY = SimpleNamespace(list=lambda: [])


async def test_uses_deployment_resource_group_when_foundry_resource_group_is_unset():
    source = _FakeDeploymentSource(["gpt-4o"])
    service = ModelCatalogService(
        settings=_settings(
            azure_foundry_endpoint="https://genie-foundry.services.ai.azure.com/api/projects/genie-project",
            azure_subscription_id="11111111-1111-1111-1111-111111111111",
            deployment_resource_group="genie-shared-rg",
        ),
        agent_registry=_FAKE_AGENT_REGISTRY,  # type: ignore[arg-type]
        deployment_source=source,  # type: ignore[arg-type]
    )

    catalog = await service.get_catalog()

    assert catalog.available_models == ["gpt-4o"]
    assert source.calls == [
        {
            "subscription_id": "11111111-1111-1111-1111-111111111111",
            "resource_group": "genie-shared-rg",
            "account_name": "genie-foundry",
        }
    ]


async def test_prefers_dedicated_foundry_resource_group_over_deployment_resource_group():
    """The real-world case this regression protects: a dedicated environment
    whose Deploy & Launch target resource group differs from the resource
    group actually hosting the reused Foundry account."""
    source = _FakeDeploymentSource(["gpt-4o"])
    service = ModelCatalogService(
        settings=_settings(
            azure_foundry_endpoint="https://genie-foundry.services.ai.azure.com/api/projects/genie-project",
            azure_subscription_id="11111111-1111-1111-1111-111111111111",
            deployment_resource_group="genie-wiq-rg",
            azure_foundry_resource_group="genie-dev-rg",
        ),
        agent_registry=_FAKE_AGENT_REGISTRY,  # type: ignore[arg-type]
        deployment_source=source,  # type: ignore[arg-type]
    )

    catalog = await service.get_catalog()

    assert catalog.available_models == ["gpt-4o"]
    assert source.calls[0]["resource_group"] == "genie-dev-rg"


async def test_blank_foundry_resource_group_falls_back_to_deployment_resource_group():
    source = _FakeDeploymentSource(["gpt-4o"])
    service = ModelCatalogService(
        settings=_settings(
            azure_foundry_endpoint="https://genie-foundry.services.ai.azure.com/api/projects/genie-project",
            azure_subscription_id="11111111-1111-1111-1111-111111111111",
            deployment_resource_group="genie-shared-rg",
            azure_foundry_resource_group="   ",
        ),
        agent_registry=_FAKE_AGENT_REGISTRY,  # type: ignore[arg-type]
        deployment_source=source,  # type: ignore[arg-type]
    )

    await service.get_catalog()

    assert source.calls[0]["resource_group"] == "genie-shared-rg"


async def test_falls_back_to_configured_models_when_no_resource_group_is_configured():
    source = _FakeDeploymentSource(["gpt-4o"])
    service = ModelCatalogService(
        settings=_settings(
            azure_foundry_endpoint="https://genie-foundry.services.ai.azure.com/api/projects/genie-project",
            azure_subscription_id="11111111-1111-1111-1111-111111111111",
        ),
        agent_registry=_FAKE_AGENT_REGISTRY,  # type: ignore[arg-type]
        deployment_source=source,  # type: ignore[arg-type]
    )

    catalog = await service.get_catalog()

    assert catalog.available_models == [service._settings.default_llm]
    assert source.calls == []


async def test_surfaces_underlying_error_when_resource_lookup_fails():
    class _FailingSource:
        def list_model_deployments(self, **_: object) -> list[str]:
            raise RuntimeError("(ResourceNotFound) boom")

    service = ModelCatalogService(
        settings=_settings(
            azure_foundry_endpoint="https://genie-foundry.services.ai.azure.com/api/projects/genie-project",
            azure_subscription_id="11111111-1111-1111-1111-111111111111",
            deployment_resource_group="genie-wiq-rg",
        ),
        agent_registry=_FAKE_AGENT_REGISTRY,  # type: ignore[arg-type]
        deployment_source=_FailingSource(),  # type: ignore[arg-type]
    )

    with pytest.raises(ModelCatalogUnavailableError, match="ResourceNotFound"):
        await service.get_catalog()
