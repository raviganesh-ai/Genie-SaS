"""Typed repository assessment and dependency graph models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DependencyNodeType = Literal[
    "repository", "source_file", "manifest", "package", "integration_endpoint"
]
DependencyEdgeType = Literal[
    "contains", "declares", "depends_on", "imports", "integrates_with"
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
    created_at: datetime

