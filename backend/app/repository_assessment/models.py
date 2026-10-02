"""Typed repository assessment and dependency graph models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DependencyNodeType = Literal[
    "repository",
    "source_file",
    "manifest",
    "package",
    "integration_endpoint",
    "component",
    "technology",
]
DependencyEdgeType = Literal[
    "contains", "declares", "depends_on", "imports", "integrates_with", "built_on"
]


class GraphEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_full_name: str
    commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    path: str
    excerpt: str | None = None


class DependencyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: DependencyNodeType
    name: str
    version: str | None = None
    path: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class DependencyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    target: str
    type: DependencyEdgeType
    confidence: float = Field(ge=0, le=1)
    evidence: list[GraphEvidence] = Field(min_length=1)


class CoverageGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    detail: str
    paths: list[str] = Field(default_factory=list)


class ComponentRoleInsight(BaseModel):
    """One component's Genie-inferred architectural role.

    Grounded only in the deterministic component graph (see
    ``component_path``, which must match a real ``component`` node's
    ``name``) - a model response referencing a path that is not already in
    the graph is discarded rather than used to invent a new component.
    """

    model_config = ConfigDict(extra="forbid")

    component_id: str
    component_path: str
    role: str
    confidence: float = Field(ge=0, le=1)
    rationale: str


class RepositoryCodeSummary(BaseModel):
    """A Genie-generated, evidence-grounded plain-language explanation of a
    commit-pinned repository - layered on top of (never a substitute for)
    the deterministic dependency graph. This is a model interpretation, not
    a confirmed fact; callers should present it as such."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    highlights: list[str] = Field(default_factory=list)
    component_roles: list[ComponentRoleInsight] = Field(default_factory=list)
    generated_by: str = "code-analyst"
    generated_at: datetime


class RepositoryChatAnswer(BaseModel):
    """One answer in an ad hoc conversation about an already-assessed
    repository - grounded only in that assessment's deterministic
    dependency/component graph (see RepositoryAssessmentService.ask),
    never raw file contents or the model's own general knowledge."""

    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str
    referenced_paths: list[str] = Field(default_factory=list)
    generated_by: str = "code-analyst"
    generated_at: datetime


class RepositoryInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_count: int = Field(ge=0)
    analyzed_file_count: int = Field(ge=0)
    languages: list[str] = Field(default_factory=list)
    manifest_paths: list[str] = Field(default_factory=list)
    infrastructure_paths: list[str] = Field(default_factory=list)
    workflow_paths: list[str] = Field(default_factory=list)
    test_paths: list[str] = Field(default_factory=list)


class RepositoryAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    binding_id: str
    repository_full_name: str
    commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    inventory: RepositoryInventory
    nodes: list[DependencyNode] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)
    coverage_gaps: list[CoverageGap] = Field(default_factory=list)
    code_summary: RepositoryCodeSummary | None = None
    created_at: datetime

