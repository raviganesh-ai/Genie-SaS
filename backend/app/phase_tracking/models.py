"""Phase catalog and session task state."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["pending", "in_progress", "blocked", "completed"]


class PhaseTaskDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class PhaseDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    tasks: list[PhaseTaskDefinition] = Field(min_length=1)


class PhaseCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1)
    workflows: list[dict[str, object]] = Field(default_factory=list)
    phases: list[PhaseDefinition] = Field(min_length=1)


class PhaseTaskState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    session_id: str
    phase_id: str
    task_id: str
    status: TaskStatus = "pending"
    evidence_uri: str | None = None
    evidence_provider: Literal["azure", "github", "genie"] | None = None
    evidence_verified_at: datetime | None = None
    evidence_reference: str | None = None
    detail: str = ""
    updated_by: str
    updated_at: datetime


class TrackedTask(BaseModel):
    definition: PhaseTaskDefinition
    state: PhaseTaskState


class TrackedPhase(BaseModel):
    id: str
    name: str
    tasks: list[TrackedTask]
