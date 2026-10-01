"""Typed modernization plan and pull-request models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ModernizationStatus = Literal[
    "draft", "pending_approval", "approved", "executing", "pull_request_opened", "failed"
]


class ModernizationFileChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    content: str
    reason: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def _repository_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip("/")
        if not normalized or ".." in normalized.split("/"):
            raise ValueError("path must be a safe repository-relative path.")
        return normalized


class ModernizationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    binding_id: str
    assessment_id: str
    standards_snapshot_id: str
    repository_full_name: str
    base_commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    base_ref: str
    goal: str
    capability_id: str | None = None
    capability_name: str | None = None
    target: str | None = None
    summary: str
    changes: list[ModernizationFileChange] = Field(min_length=1)
    validation_commands: list[str]
    residual_risks: list[str]
    rollback: str
    branch_name: str
    status: ModernizationStatus = "draft"
    approval_request_id: str | None = None
    pull_request_url: str | None = None
    created_at: datetime
    updated_at: datetime
