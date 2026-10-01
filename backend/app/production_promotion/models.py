"""Typed production rehearsal and rollout state."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PromotionStatus = Literal[
    "draft",
    "rehearsed",
    "pending_approval",
    "canary",
    "completed",
    "rolled_back",
    "failed",
]


class ProductionPromotion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    deployment_run_id: str
    resource_group_name: str
    backend_app_name: str
    health_url: str
    status: PromotionStatus = "draft"
    approval_request_id: str | None = None
    rehearsal_latency_ms: float | None = Field(default=None, ge=0)
    candidate_revision_name: str | None = None
    previous_revision_name: str | None = None
    canary_weight_percent: int = Field(ge=1, le=50)
    rollback_detail: str | None = None
    created_at: datetime
    updated_at: datetime

