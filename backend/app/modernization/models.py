"""Typed modernization plan and pull-request models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.discovery.models import CostEstimate, PricingQuery

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


class ModernizationProposedComponent(BaseModel):
    """One node in the plan's proposed target architecture - either a
    module that stays inside the modular monolith, or a component the plan
    recommends extracting into its own independently deployed service.
    Rendered as a graph (see the frontend's dependencyGraphLayout reuse)
    so the user can see the proposed decomposition at a glance rather than
    only reading prose."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    responsibility: str = Field(min_length=1)
    extracted: bool
    depends_on: list[str] = Field(default_factory=list)


class ModernizationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    binding_id: str
    assessment_id: str
    standards_snapshot_id: str | None = None
    repository_full_name: str
    base_commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    base_ref: str
    goal: str
    capability_id: str | None = None
    capability_name: str | None = None
    target: str | None = None
    # Optional "architecture"-purpose binding's ingested reference material
    # this plan was aligned to, if the user supplied one - see
    # ModernizationService.generate_plan. None means Genie decided the
    # architecture itself.
    architecture_reference_snapshot_id: str | None = None
    summary: str
    # Prose rationale for *why* this approach (e.g. modular monolith with a
    # strangler-pattern extraction) was chosen over alternatives - answers
    # "what is the rewrite strategy" distinctly from the file-level changes.
    rewrite_strategy: str = Field(min_length=1)
    # The proposed target architecture's components/modules - empty for
    # capabilities where a decomposition graph doesn't apply (e.g. a plain
    # dependency upgrade); the frontend only renders the graph when non-empty.
    proposed_components: list[ModernizationProposedComponent] = Field(default_factory=list)
    # Ordered, human-readable rollout steps distinct from the individual
    # file changes below (e.g. "ship behind a feature flag", "run the
    # strangler proxy in shadow mode first", "cut over traffic").
    deployment_plan: list[str] = Field(min_length=1)
    changes: list[ModernizationFileChange] = Field(min_length=1)
    validation_commands: list[str]
    residual_risks: list[str]
    rollback: str
    # Agent-proposed usage assumptions for the *target* architecture - unit
    # prices are always resolved externally via the real Azure Retail
    # Prices API (see ModernizationService._pricing_service), never
    # hallucinated, mirroring Discovery's identical pricing_queries pattern.
    pricing_queries: list[PricingQuery] = Field(default_factory=list)
    estimated_cost: CostEstimate | None = None
    branch_name: str
    status: ModernizationStatus = "draft"
    approval_request_id: str | None = None
    pull_request_url: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _depends_on_reference_known_components(self) -> ModernizationPlan:
        known_ids = {component.id for component in self.proposed_components}
        unknown = sorted(
            {
                dependency
                for component in self.proposed_components
                for dependency in component.depends_on
                if dependency not in known_ids
            }
        )
        if unknown:
            raise ValueError(
                f"proposed_components depends_on references unknown component id(s): {unknown}"
            )
        return self


class ModernizationPlanChatAnswer(BaseModel):
    """One answer in an ad hoc conversation about an already-generated
    modernization plan - grounded only in that plan's own JSON (summary,
    rewrite_strategy, proposed_components, deployment_plan, changes,
    validation_commands, residual_risks, rollback, estimated_cost), never
    raw repository contents or the model's own general knowledge. See
    ModernizationService.ask."""

    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str
    referenced_fields: list[str] = Field(default_factory=list)
    generated_at: datetime

