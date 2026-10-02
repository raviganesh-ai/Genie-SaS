"""Authenticated, grounded Well-Architected/Microsoft-docs Q&A route."""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_well_architected_qa_service
from app.security.auth_models import AuthenticatedUser
from app.security.dependencies import get_current_user
from app.well_architected.models import WellArchitectedAnswer
from app.well_architected.service import WellArchitectedQaService

router = APIRouter(prefix="/sessions/{session_id}/well-architected", tags=["well-architected"])


class WellArchitectedQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)


@router.post("/ask")
async def ask_well_architected_question(
    session_id: str,
    request: WellArchitectedQuestionRequest,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: WellArchitectedQaService = Depends(get_well_architected_qa_service),
) -> WellArchitectedAnswer:
    return await service.ask(
        session_id=session_id,
        requesting_user_id=user.user_id,
        question=request.question,
        trace_id=x_correlation_id or str(uuid4()),
    )
