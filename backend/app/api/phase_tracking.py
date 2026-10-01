"""Session phase and evidence-tracking routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_phase_tracking_service
from app.phase_tracking.models import PhaseTaskState, TaskStatus, TrackedPhase
from app.phase_tracking.service import PhaseTrackingService
from app.security.auth_models import AuthenticatedUser
from app.security.dependencies import get_current_user

router = APIRouter(prefix="/sessions/{session_id}/phases", tags=["phase-tracking"])


class UpdatePhaseTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus
    evidence_uri: str | None = None
    detail: str = Field(default="", max_length=4000)


@router.get("")
async def list_phases(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: PhaseTrackingService = Depends(get_phase_tracking_service),
) -> list[TrackedPhase]:
    return await service.list_phases(
        session_id=session_id,
        requesting_user_id=user.user_id,
    )


@router.put("/{phase_id}/tasks/{task_id}")
async def update_phase_task(
    session_id: str,
    phase_id: str,
    task_id: str,
    body: UpdatePhaseTaskRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    service: PhaseTrackingService = Depends(get_phase_tracking_service),
) -> PhaseTaskState:
    return await service.update_task(
        session_id=session_id,
        phase_id=phase_id,
        task_id=task_id,
        task_status=body.status,
        evidence_uri=body.evidence_uri,
        detail=body.detail,
        requesting_user_id=user.user_id,
    )

