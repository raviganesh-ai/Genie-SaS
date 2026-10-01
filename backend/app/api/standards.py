"""Architecture standards ingestion and conformance routes."""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_standards_service
from app.security.auth_models import AuthenticatedUser
from app.security.dependencies import get_current_user
from app.standards.models import (
    ArchitectureReferenceSnapshot,
    StandardsConformanceReport,
    StandardsSnapshot,
)
from app.standards.service import StandardsService

router = APIRouter(prefix="/sessions/{session_id}/standards", tags=["standards"])
architecture_reference_router = APIRouter(
    prefix="/sessions/{session_id}/architecture-reference", tags=["standards"]
)


class EvaluateStandardsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1)
    assessment_id: str = Field(min_length=1)


@router.get("")
async def list_standards_snapshots(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: StandardsService = Depends(get_standards_service),
) -> list[StandardsSnapshot]:
    return await service.list_snapshots(
        session_id=session_id,
        requesting_user_id=user.user_id,
    )


@router.post("/ingest/{binding_id}", status_code=status.HTTP_201_CREATED)
async def ingest_standards(
    session_id: str,
    binding_id: str,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: StandardsService = Depends(get_standards_service),
) -> StandardsSnapshot:
    return await service.ingest(
        session_id=session_id,
        binding_id=binding_id,
        requesting_user_id=user.user_id,
        trace_id=x_correlation_id or str(uuid4()),
    )


@router.post("/evaluate")
async def evaluate_standards(
    session_id: str,
    body: EvaluateStandardsRequest,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: StandardsService = Depends(get_standards_service),
) -> StandardsConformanceReport:
    return await service.evaluate(
        session_id=session_id,
        snapshot_id=body.snapshot_id,
        assessment_id=body.assessment_id,
        requesting_user_id=user.user_id,
        trace_id=x_correlation_id or str(uuid4()),
    )


@architecture_reference_router.get("")
async def list_architecture_reference_snapshots(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: StandardsService = Depends(get_standards_service),
) -> list[ArchitectureReferenceSnapshot]:
    return await service.list_architecture_reference_snapshots(
        session_id=session_id,
        requesting_user_id=user.user_id,
    )


@architecture_reference_router.post("/ingest/{binding_id}", status_code=status.HTTP_201_CREATED)
async def ingest_architecture_reference(
    session_id: str,
    binding_id: str,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: StandardsService = Depends(get_standards_service),
) -> ArchitectureReferenceSnapshot:
    return await service.ingest_architecture_reference(
        session_id=session_id,
        binding_id=binding_id,
        requesting_user_id=user.user_id,
        trace_id=x_correlation_id or str(uuid4()),
    )

