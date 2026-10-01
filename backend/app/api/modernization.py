"""Governed modernization plan and pull-request routes."""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_modernization_service
from app.modernization.capabilities import ModernizationCapability
from app.modernization.models import ModernizationPlan
from app.modernization.service import ModernizationService
from app.security.auth_models import AuthenticatedUser
from app.security.dependencies import get_current_user

router = APIRouter(prefix="/sessions/{session_id}/modernization", tags=["modernization"])


class GenerateModernizationPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str = Field(min_length=1)
    assessment_id: str = Field(min_length=1)
    standards_snapshot_id: str | None = Field(default=None, min_length=1)
    capability_id: str = Field(min_length=1)
    target: str | None = Field(default=None, max_length=200)
    architecture_reference_snapshot_id: str | None = Field(default=None, min_length=1)


@router.get("")
async def list_modernization_plans(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: ModernizationService = Depends(get_modernization_service),
) -> list[ModernizationPlan]:
    return await service.list_plans(
        session_id=session_id,
        requesting_user_id=user.user_id,
    )


@router.get("/capabilities")
async def list_modernization_capabilities(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: ModernizationService = Depends(get_modernization_service),
) -> list[ModernizationCapability]:
    return await service.list_capabilities(
        session_id=session_id,
        requesting_user_id=user.user_id,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def generate_modernization_plan(
    session_id: str,
    body: GenerateModernizationPlanRequest,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: ModernizationService = Depends(get_modernization_service),
) -> ModernizationPlan:
    return await service.generate_plan(
        session_id=session_id,
        binding_id=body.binding_id,
        assessment_id=body.assessment_id,
        standards_snapshot_id=body.standards_snapshot_id,
        capability_id=body.capability_id,
        target=body.target,
        architecture_reference_snapshot_id=body.architecture_reference_snapshot_id,
        requesting_user_id=user.user_id,
        trace_id=x_correlation_id or str(uuid4()),
    )


@router.post("/{plan_id}/execute")
async def execute_modernization_plan(
    session_id: str,
    plan_id: str,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: ModernizationService = Depends(get_modernization_service),
) -> ModernizationPlan:
    return await service.execute_plan(
        session_id=session_id,
        plan_id=plan_id,
        requesting_user_id=user.user_id,
        trace_id=x_correlation_id or str(uuid4()),
    )
