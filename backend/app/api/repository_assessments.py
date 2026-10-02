"""Authenticated repository assessment and dependency graph routes."""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_repository_assessment_service
from app.repository_assessment.models import RepositoryAssessment, RepositoryChatAnswer
from app.repository_assessment.service import RepositoryAssessmentService
from app.security.auth_models import AuthenticatedUser
from app.security.dependencies import get_current_user

router = APIRouter(prefix="/sessions/{session_id}/repository-assessments", tags=["repository-assessments"])


class RepositoryChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)


@router.get("")
async def list_repository_assessments(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: RepositoryAssessmentService = Depends(get_repository_assessment_service),
) -> list[RepositoryAssessment]:
    return await service.list_assessments(
        session_id=session_id,
        requesting_user_id=user.user_id,
    )


@router.post("/{binding_id}", status_code=status.HTTP_201_CREATED)
async def create_repository_assessment(
    session_id: str,
    binding_id: str,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: RepositoryAssessmentService = Depends(get_repository_assessment_service),
) -> RepositoryAssessment:
    return await service.assess(
        session_id=session_id,
        binding_id=binding_id,
        requesting_user_id=user.user_id,
        trace_id=x_correlation_id or str(uuid4()),
    )


@router.post("/{assessment_id}/ask")
async def ask_about_repository(
    session_id: str,
    assessment_id: str,
    request: RepositoryChatRequest,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: RepositoryAssessmentService = Depends(get_repository_assessment_service),
) -> RepositoryChatAnswer:
    return await service.ask(
        session_id=session_id,
        assessment_id=assessment_id,
        requesting_user_id=user.user_id,
        message=request.message,
        trace_id=x_correlation_id or str(uuid4()),
    )

