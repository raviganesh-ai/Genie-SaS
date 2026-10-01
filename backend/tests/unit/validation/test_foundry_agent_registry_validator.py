"""Unit tests for FoundryAgentRegistryValidator."""
from __future__ import annotations

from app.config.settings import Settings
from app.validation.foundry_agent_registry_validator import FoundryAgentRegistryValidator


def test_complete_registry_passes(foundry_configured_settings: Settings):
    result = FoundryAgentRegistryValidator().validate(foundry_configured_settings)

    assert result.passed
