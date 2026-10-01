"""Development-only Microsoft Connect / Work IQ diagnostics and validation
routes.

Both routes are hard-gated to non-production environments
(``require_non_production``) - in production they return 404, as if the
route did not exist, rather than a 503 that would confirm the route's
existence to an unauthenticated prober. Neither route ever returns a
client secret, access token, refresh token, authorization code,
Authorization header, serialized token cache, full Microsoft 365
response, or email/meeting/chat/document content - see ``IqDiagnostics``
and ``WorkIqValidationResult`` in ``app/iq/models.py`` for the enforced,
narrow field sets.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import get_iq_diagnostics_service, get_work_iq_validation_service
from app.iq.iq_diagnostics_service import IqDiagnosticsService
from app.iq.models import IqDiagnostics, WorkIqValidationResult
from app.iq.work_iq_validation_service import WorkIqValidationService
from app.security.auth_models import AuthenticatedUser
from app.security.dependencies import get_current_user

router = APIRouter(tags=["iq-diagnostics"])


def require_non_production(request: Request) -> None:
    settings = getattr(request.app.state, "settings", None)
    environment = getattr(settings, "environment", "production")
    if environment == "production":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found.",
        )


@router.get(
    "/sessions/{session_id}/iq/diagnostics",
    dependencies=[Depends(require_non_production)],
)
async def get_iq_diagnostics(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: IqDiagnosticsService = Depends(get_iq_diagnostics_service),
) -> IqDiagnostics:
    return await service.diagnostics(session_id=session_id, requesting_user_id=user.user_id)


@router.post(
    "/sessions/{session_id}/iq/work-iq/validate",
    dependencies=[Depends(require_non_production)],
)
async def validate_work_iq(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: WorkIqValidationService = Depends(get_work_iq_validation_service),
) -> WorkIqValidationResult:
    return await service.validate(session_id=session_id, requesting_user_id=user.user_id)
