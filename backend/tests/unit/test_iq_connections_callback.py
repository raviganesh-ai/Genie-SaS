"""Tests for the ``/iq/connections/callback`` route, including the
Microsoft authorization-code-flow "user cancelled / denied consent" shape
(``error``+``error_description``+``state``, no ``code``) - see
https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow.

Uses a minimal FastAPI app mounting only ``app.api.iq_connections.router``
with a fake ``DelegatedConnectionService`` - focused on this route's own
redirect-status-mapping logic, not the full connection stack (already
covered by ``test_delegated_connection_service.py``).
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import iq_connections
from app.api.dependencies import get_delegated_connection_service
from app.iq.delegated_token_broker import DelegatedAuthError
from app.iq.pending_oauth_flow import PendingOAuthFlowError


class _FakeConnectionService:
    def __init__(self, *, callback_result=None, callback_error: Exception | None = None) -> None:
        self._callback_result = callback_result
        self._callback_error = callback_error

    async def handle_callback(self, *, code: str, state: str, trace_id: str):
        if self._callback_error is not None:
            raise self._callback_error
        return self._callback_result


def _build_app(service: _FakeConnectionService) -> FastAPI:
    app = FastAPI()
    app.include_router(iq_connections.router)
    app.dependency_overrides[get_delegated_connection_service] = lambda: service
    return app


def _redirect_params(response) -> dict:
    location = response.headers["location"]
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


def test_user_cancelling_consent_redirects_with_authentication_required() -> None:
    # Microsoft's shape for a cancelled/denied authorization: error +
    # error_description + state, deliberately with NO code parameter.
    app = _build_app(_FakeConnectionService())
    with TestClient(app, follow_redirects=False) as client:
        response = client.get(
            "/iq/connections/callback",
            params={
                "error": "access_denied",
                "error_description": "The user declined to consent.",
                "state": "some-state-value",
            },
        )

    assert response.status_code == 302
    params = _redirect_params(response)
    assert params["iq_connect"] == "authentication_required"
    # The full Microsoft error_description must never be echoed back to
    # the browser redirect target.
    assert "declined" not in response.headers["location"]


def test_missing_code_without_error_redirects_safely() -> None:
    app = _build_app(_FakeConnectionService())
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/iq/connections/callback", params={"state": "some-state-value"})

    assert response.status_code == 302
    assert _redirect_params(response)["iq_connect"] == "authentication_required"


def test_successful_callback_redirects_with_connected_status() -> None:
    app = _build_app(_FakeConnectionService(callback_result=("session-1", "work_iq")))
    with TestClient(app, follow_redirects=False) as client:
        response = client.get(
            "/iq/connections/callback",
            params={"code": "auth-code", "state": "some-state-value"},
        )

    assert response.status_code == 302
    params = _redirect_params(response)
    assert params["iq_connect"] == "connected"
    assert params["provider"] == "work_iq"


def test_invalid_state_redirects_with_its_category() -> None:
    app = _build_app(
        _FakeConnectionService(callback_error=PendingOAuthFlowError("expired or unknown state"))
    )
    with TestClient(app, follow_redirects=False) as client:
        response = client.get(
            "/iq/connections/callback",
            params={"code": "auth-code", "state": "replayed-or-unknown"},
        )

    assert response.status_code == 302
    assert _redirect_params(response)["iq_connect"] == "authentication_required"


def test_tenant_mismatch_redirects_with_that_exact_category() -> None:
    app = _build_app(
        _FakeConnectionService(
            callback_error=DelegatedAuthError("wrong tenant", category="tenant_mismatch")
        )
    )
    with TestClient(app, follow_redirects=False) as client:
        response = client.get(
            "/iq/connections/callback",
            params={"code": "auth-code", "state": "some-state-value"},
        )

    assert response.status_code == 302
    assert _redirect_params(response)["iq_connect"] == "tenant_mismatch"
