"""Platform-level (not session-scoped) opinionated architecture/standards
reference repositories - configured once by an administrator and used
automatically by every future mission's design-architecture step and
governed modernization plan, unless that specific session supplies its
own override (see app.orchestration.workflow_step_executor and
app.modernization.service, both of which prefer a session-scoped
reference and fall back to this platform-level configuration only when
the session has none).

More than one repository may be configured per purpose (e.g. separate
backend/frontend standards repos) - all configured repositories for a
purpose are combined when consumed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.standards.models import ArchitectureStandardRule, StandardsConflict

PlatformReferencePurpose = Literal["architecture", "standards"]


class PlatformReferenceRepository(BaseModel):
    """One administrator-configured reference repository, commit-pinned at
    configuration time with its content already ingested (re-add the same
    repository to refresh to its current commit - there is no background
    auto-refresh, consistent with every other commit-pinned evidence
    source in Genie-SaS)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    repository_id: int
    repository_full_name: str = Field(min_length=3)
    repository_url: str
    purpose: PlatformReferencePurpose
    requested_ref: str = Field(min_length=1)
    resolved_commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    included_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    principal: str = Field(min_length=1)
    configured_by_user_id: str = Field(min_length=1)
    paths: list[str] = Field(default_factory=list)
    content_hashes: dict[str, str] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)
    # Populated only when purpose == "architecture":
    combined_reference_text: str | None = None
    # Populated only when purpose == "standards":
    rules: list[ArchitectureStandardRule] = Field(default_factory=list)
    conflicts: list[StandardsConflict] = Field(default_factory=list)
    created_at: datetime
