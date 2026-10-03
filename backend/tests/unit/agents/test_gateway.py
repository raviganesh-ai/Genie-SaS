"""Unit tests for agent/prompt resolution and Foundry gateway selection.

Azure AI Foundry execution itself is covered by
``test_azure_agent_gateway.py`` and ``foundry/test_agent_provider.py``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.azure_agent_gateway import AzureAgentGateway
from app.agents.gateway import (
    AgentGatewayError,
    PromptResolutionError,
    UnknownAgentError,
    UnknownPromptError,
    create_agent_gateway,
    get_enabled_agent,
    resolve_prompt_text,
)
from app.agents.models import AgentExecutionRequest
from app.agents.registry import AgentRegistry
from app.config.settings import Settings
from app.prompts.registry import PromptRegistry


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def agent_registry(tmp_path: Path) -> AgentRegistry:
    _write(
        tmp_path / "agents" / "registry.yaml",
        "agents:\n"
        "  - id: requirements-analyst\n"
        "    name: Requirements Analyst\n"
        "    role: requirement_discovery\n"
        "    description: Extracts requirements.\n"
        "    model_deployment_ref: claude-sonnet-5\n"
        "    foundry_agent_id: requirements-analyst-agent\n"
        "  - id: disabled-agent\n"
        "    name: Disabled Agent\n"
        "    role: disabled_role\n"
        "    description: Not enabled.\n"
        "    enabled: false\n"
        "  - id: no-foundry-agent\n"
        "    name: No Foundry Agent\n"
        "    role: invalid_role\n"
        "    description: Invalid because no Foundry reference is configured.\n",
    )
    return AgentRegistry.load(tmp_path / "agents")


@pytest.fixture
def prompt_registry(tmp_path: Path) -> PromptRegistry:
    _write(
        tmp_path / "prompts" / "registry.yaml",
        "prompts:\n"
        "  - id: requirements-extraction-v1\n"
        "    name: Requirements Extraction\n"
        "    description: Extracts requirements from a transcript.\n"
        "    template: 'Extract requirements from: {transcript_excerpt}'\n"
        "    variables:\n"
        "      - transcript_excerpt\n",
    )
    return PromptRegistry.load(tmp_path / "prompts")


def _request(**overrides: object) -> AgentExecutionRequest:
    defaults: dict[str, object] = {
        "agent_id": "requirements-analyst",
        "prompt_id": "requirements-extraction-v1",
        "variables": {"transcript_excerpt": "We need a chatbot."},
        "correlation_id": "corr-1",
    }
    defaults.update(overrides)
    return AgentExecutionRequest.model_validate(defaults)


class TestResolutionHelpers:
    def test_get_enabled_agent_returns_agent(self, agent_registry: AgentRegistry):
        agent = get_enabled_agent(agent_registry, "requirements-analyst")
        assert agent.id == "requirements-analyst"

    def test_get_enabled_agent_raises_for_unknown_id(self, agent_registry: AgentRegistry):
        with pytest.raises(UnknownAgentError, match="Unknown agent id"):
            get_enabled_agent(agent_registry, "does-not-exist")

    def test_get_enabled_agent_raises_for_disabled_agent(self, agent_registry: AgentRegistry):
        with pytest.raises(UnknownAgentError, match="disabled"):
            get_enabled_agent(agent_registry, "disabled-agent")

    def test_resolve_prompt_text_formats_template(self, prompt_registry: PromptRegistry):
        request = _request()
        assert resolve_prompt_text(prompt_registry, request) == (
            "Extract requirements from: We need a chatbot."
        )

    def test_resolve_prompt_text_raises_for_unknown_prompt(self, prompt_registry: PromptRegistry):
        request = _request(prompt_id="does-not-exist")
        with pytest.raises(UnknownPromptError, match="Unknown prompt id"):
            resolve_prompt_text(prompt_registry, request)

    def test_resolve_prompt_text_raises_for_missing_variable(
        self, prompt_registry: PromptRegistry
    ):
        request = _request(variables={})
        with pytest.raises(PromptResolutionError, match="missing required variable"):
            resolve_prompt_text(prompt_registry, request)


class TestCreateAgentGateway:
    def test_foundry_configuration_returns_azure_gateway(
        self, agent_registry: AgentRegistry, prompt_registry: PromptRegistry
    ):
        settings = Settings(
            allow_local_agents=False,
            azure_foundry_endpoint="https://genie-foundry.example-project.azure.com",
            azure_foundry_project_name="genie-project",
        )
        gateway = create_agent_gateway(
            settings=settings, agent_registry=agent_registry, prompt_registry=prompt_registry
        )
        assert isinstance(gateway, AzureAgentGateway)

    def test_missing_foundry_configuration_raises(
        self, agent_registry: AgentRegistry, prompt_registry: PromptRegistry
    ):
        settings = Settings(allow_local_agents=False)
        with pytest.raises(AgentGatewayError, match="azure_foundry_endpoint"):
            create_agent_gateway(
                settings=settings, agent_registry=agent_registry, prompt_registry=prompt_registry
            )

    def test_legacy_local_flag_cannot_override_foundry_gateway(
        self, agent_registry: AgentRegistry, prompt_registry: PromptRegistry
    ):
        settings = Settings(
            allow_mock_agents=False,
            allow_local_agents=True,
            use_synthetic_data=False,
            azure_foundry_endpoint="https://genie-foundry.example-project.azure.com",
            azure_foundry_project_name="genie-project",
        )
        gateway = create_agent_gateway(
            settings=settings, agent_registry=agent_registry, prompt_registry=prompt_registry
        )
        assert isinstance(gateway, AzureAgentGateway)
