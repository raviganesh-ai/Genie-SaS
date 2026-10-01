"""Rejects every non-Foundry agent execution mode."""
from __future__ import annotations

from app.config.settings import Settings
from app.validation.base import ValidationResult


class ProviderModeValidator:
    """Requires Azure AI Foundry and prohibits mock, local, or synthetic modes."""

    name = "ProviderModeValidator"

    def validate(self, settings: Settings) -> ValidationResult:
        errors: list[str] = []
        if settings.allow_local_agents:
            errors.append("allow_local_agents must be false; local agent execution is prohibited.")
        if settings.allow_mock_agents:
            errors.append("allow_mock_agents must be false; mock agent execution is prohibited.")
        if settings.use_synthetic_data:
            errors.append("use_synthetic_data must be false; synthetic execution data is prohibited.")
        if not settings.azure_foundry_endpoint:
            errors.append("azure_foundry_endpoint is required for all agent execution.")
        elif not settings.azure_foundry_endpoint.startswith("https://"):
            errors.append("azure_foundry_endpoint must use HTTPS.")
        if not settings.azure_foundry_project_name:
            errors.append("azure_foundry_project_name is required for all agent execution.")
        if errors:
            return ValidationResult.fail(self.name, errors)
        return ValidationResult.ok(self.name)

