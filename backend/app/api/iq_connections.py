"""Delegated Microsoft 365 connection routes for Work IQ / Fabric IQ.

Two distinct interaction models on this router:

- ``GET /sessions/{session_id}/iq/connections`` and
  ``POST /sessions/{session_id}/iq/connections/{provider}/disconnect``
  are normal JSON API calls, like every other Genie route - domain errors
  propagate to the centrally registered ``domain_error_handler``.
- ``GET /iq/connections/{provider}/start`` and
  ``GET /iq/connections/callback`` are **browser redirects**, not JSON
  calls: the frontend navigates the whole page to "start", which redirects
  to Microsoft, which redirects back to "callback", which redirects back
  to the frontend. Neither ever returns a token to the browser - only a
  redirect Location header. Failures during "callback" still redirect back
  to the frontend (carrying only a status code), rather than rendering a
  raw JSON/HTML error page mid-flow.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from app.api.dependencies import get_delegated_connection_service
from app.iq.delegated_connection_service import (
    DelegatedAuthError,
    DelegatedConnectionService,
    DelegatedConnectionServiceError,
)
from app.iq.models import IqConnectionStatus, IqProviderName
from app.iq.pending_oauth_flow import PendingOAuthFlowError
from app.security.auth_models import AuthenticatedUser
from app.security.dependencies import get_current_user

router = APIRouter(tags=["iq-connections"])
logger = logging.getLogger(__name__)


@router.get("/sessions/{session_id}/iq/connections")
async def list_iq_connections(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: DelegatedConnectionService = Depends(get_delegated_connection_service),
) -> list[IqConnectionStatus]:
    return await service.status(session_id=session_id, requesting_user_id=user.user_id)


@router.get("/iq/connections/{provider}/start")
async def start_iq_connection(
    provider: IqProviderName,
    session_id: str = Query(...),
    user: AuthenticatedUser = Depends(get_current_user),
    service: DelegatedConnectionService = Depends(get_delegated_connection_service),
) -> RedirectResponse:
    authorize_url = await service.start(
        session_id=session_id, provider=provider, requesting_user_id=user.user_id
    )
    return RedirectResponse(url=authorize_url, status_code=302)


@router.get("/iq/connections/callback")
async def iq_connection_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    service: DelegatedConnectionService = Depends(get_delegated_connection_service),
) -> RedirectResponse:
    """No ``get_current_user`` dependency: Microsoft's redirect back to this
    endpoint carries no Genie bearer credential (it is a plain browser
    navigation). Session ownership was already enforced when ``start`` was
    called, and the opaque ``state`` value (bound to that exact session by
    ``PendingOAuthFlowStore``) is this endpoint's only trust anchor -
    resistant to guessing/CSRF, single-use, and short-lived.

    Microsoft redirects here in two shapes, per the authorization code
    flow (https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow):
    a successful authorization carries ``code``+``state``; a user
    cancelling, denying consent, or any authorization-time failure carries
    ``error``(+``error_description``)+``state`` instead, with **no**
    ``code``. Both must redirect back to the frontend with a sanitized
    status - never surface a raw 422/error page mid-flow, and never log
    ``error_description`` verbatim (it can echo request parameters).
    """

    if error is not None:
        logger.info(
            "IQ connection callback denied by Microsoft (error=%s).", error
        )
        return _redirect_to_frontend(status_param="authentication_required", provider=None)
    if code is None or state is None:
        return _redirect_to_frontend(status_param="authentication_required", provider=None)
    try:
        session_id, provider = await service.handle_callback(
            code=code, state=state, trace_id=str(uuid4())
        )
    except (PendingOAuthFlowError, DelegatedAuthError) as exc:
        category = getattr(exc, "category", "authentication_required")
        return _redirect_to_frontend(status_param=category, provider=None)
    return _redirect_to_frontend(status_param="connected", provider=provider, session_id=session_id)


@router.post("/sessions/{session_id}/iq/connections/{provider}/disconnect", status_code=204)
async def disconnect_iq_connection(
    session_id: str,
    provider: IqProviderName,
    user: AuthenticatedUser = Depends(get_current_user),
    service: DelegatedConnectionService = Depends(get_delegated_connection_service),
) -> None:
    await service.disconnect(
        session_id=session_id,
        provider=provider,
        requesting_user_id=user.user_id,
        trace_id=str(uuid4()),
    )


def _redirect_to_frontend(
    *, status_param: str, provider: IqProviderName | None, session_id: str | None = None
) -> RedirectResponse:
    # The frontend route (not a Microsoft/Genie API endpoint) that reads
    # this query string and shows a connect/error banner - see
    # frontend/src/features/iq/IqCollaborationPage.tsx.
    params = {"iq_connect": status_param}
    if provider is not None:
        params["provider"] = provider
    return RedirectResponse(url=f"/iq-collaboration?{urlencode(params)}", status_code=302)


__all__ = ["router", "DelegatedConnectionServiceError"]
