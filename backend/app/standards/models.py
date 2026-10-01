"""Typed standards, conflicts, and conformance models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RuleClassification = Literal["mandatory", "preferred", "advisory", "example", "superseded"]
ConformanceStatus = Literal["conformant", "non_conformant", "not_applicable", "unresolved"]


class StandardCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_full_name: str
    commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    path: str
    line: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArchitectureStandardRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    statement: str
    classification: RuleClassification
    citation: StandardCitation


class StandardsConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_ids: list[str] = Field(min_length=2)
    detail: str


class StandardsSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    binding_id: str
    repository_full_name: str
    commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    paths: list[str]
    content_hashes: dict[str, str]
    rules: list[ArchitectureStandardRule]
    conflicts: list[StandardsConflict]
    gaps: list[str]
    created_at: datetime


class ConformanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    status: ConformanceStatus
    matched_node_ids: list[str] = Field(default_factory=list)
    detail: str
    citation: StandardCitation


class StandardsConformanceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    assessment_id: str
    results: list[ConformanceResult]
    evaluated_at: datetime

