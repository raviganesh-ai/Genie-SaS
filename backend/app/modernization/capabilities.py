"""Configured modernization capability catalog."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.utils.yaml_loader import YamlLoadError, load_yaml_file


class ModernizationCapabilityError(RuntimeError):
    """Raised when modernization capability configuration is invalid."""


class ModernizationCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    target_label: str | None = None
    instruction_template: str = Field(min_length=1)

    @field_validator("instruction_template")
    @classmethod
    def _validate_target_placeholder(cls, value: str) -> str:
        unexpected = value.replace("{target}", "")
        if "{" in unexpected or "}" in unexpected:
            raise ValueError("instruction_template supports only the '{target}' placeholder.")
        return value

    def instruction(self, target: str | None) -> str:
        normalized_target = target.strip() if target else ""
        if self.target_label and not normalized_target:
            raise ModernizationCapabilityError(
                f"'{self.name}' requires {self.target_label.lower()}."
            )
        if not self.target_label and normalized_target:
            raise ModernizationCapabilityError(f"'{self.name}' does not accept a target.")
        return self.instruction_template.format(target=normalized_target)


class ModernizationCapabilityCatalog(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str = Field(min_length=1)
    capabilities: list[ModernizationCapability] = Field(min_length=1)

    def get(self, capability_id: str) -> ModernizationCapability:
        for capability in self.capabilities:
            if capability.id == capability_id:
                return capability
        raise ModernizationCapabilityError(
            f"Unsupported modernization capability '{capability_id}'."
        )


def load_modernization_capabilities(workflows_path: Path) -> ModernizationCapabilityCatalog:
    path = workflows_path / "modernization_capabilities.yaml"
    try:
        catalog = ModernizationCapabilityCatalog.model_validate(load_yaml_file(path))
    except (YamlLoadError, ValidationError) as exc:
        raise ModernizationCapabilityError(
            f"Invalid modernization capability catalog '{path}': {exc}"
        ) from exc
    ids = [capability.id for capability in catalog.capabilities]
    if len(ids) != len(set(ids)):
        raise ModernizationCapabilityError(
            "Modernization capability catalog contains duplicate ids."
        )
    return catalog
