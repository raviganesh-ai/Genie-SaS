"""Validates complete Azure AI Foundry metadata for every enabled agent."""
from __future__ import annotations

from app.agents.registry import AgentRegistry, AgentRegistryError
from app.config.settings import Settings
from app.validation.base import ValidationResult

__all__ = ["FoundryAgentRegistryValidator"]


class FoundryAgentRegistryValidator:
    """Fails closed when an enabled agent cannot be synchronized to Foundry."""

    name = "FoundryAgentRegistryValidator"

    def validate(self, settings: Settings) -> ValidationResult:
        try:
            registry = AgentRegistry.load(
                settings.agents_path, default_llm=settings.default_llm
            )
        except AgentRegistryError as exc:
            return ValidationResult.fail(self.name, [str(exc)])

        errors: list[str] = []
        for agent in registry.list():
            if not agent.enabled:
                continue
            missing: list[str] = []
            if not agent.foundry_agent_id:
                missing.append("foundry_agent_id")
            if not agent.model_deployment_ref:
                missing.append("model_deployment_ref")
            if not agent.owner:
                missing.append("owner")
            if not agent.governance_policy_id:
                missing.append("governance_policy_id")
            if not agent.prompt_template_ref:
                missing.append("prompt_template_ref")
            if not agent.memory_access:
                missing.append("memory_access")
            if missing:
                errors.append(
                    f"Enabled agent '{agent.id}' is missing required Foundry metadata: "
                    f"{', '.join(missing)}."
                )
        if errors:
            return ValidationResult.fail(self.name, errors)
        return ValidationResult.ok(self.name)
