"""Unit tests for the Foundry startup configuration helper."""
from __future__ import annotations

from app.main import _uses_azure_agent_gateway


def test_uses_azure_gateway_when_foundry_configured_settings_used(foundry_configured_settings):
    assert _uses_azure_agent_gateway(foundry_configured_settings) is True


def test_legacy_local_flag_does_not_disable_foundry(foundry_configured_settings):
    settings = foundry_configured_settings.model_copy(update={"allow_local_agents": True})
    assert _uses_azure_agent_gateway(settings) is True


def test_missing_foundry_configuration_is_false(local_settings):
    assert local_settings.allow_local_agents is True
    assert _uses_azure_agent_gateway(local_settings) is False
