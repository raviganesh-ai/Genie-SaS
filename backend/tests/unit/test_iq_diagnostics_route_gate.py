"""Tests for the development-only IQ diagnostics/validation route gate.

Uses a minimal FastAPI app mounting only ``app.api.iq_diagnostics.router``
with stubbed ``app.state`` - much faster and more focused than full
application startup, and sufficient to prove the environment-based 404
gate (the actual security boundary under test).
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import iq_diagnostics
from app.security.auth_models import AuthenticatedUser
from app.security.dependencies import get_current_user


def _build_app(*, environment: str) -> FastAPI:
    app = FastAPI()
    app.state.settings = SimpleNamespace(environment=environment)
    app.state.iq_diagnostics_service = None
    app.state.work_iq_validation_service = None
    app.include_router(iq_diagnostics.router)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id="user-1", object_id="user-1", roles=[]
    )
    return app


def test_diagnostics_route_returns_404_in_production() -> None:
    app = _build_app(environment="production")
    with TestClient(app) as client:
        response = client.get("/sessions/session-1/iq/diagnostics")

    assert response.status_code == 404


def test_validation_route_returns_404_in_production() -> None:
    app = _build_app(environment="production")
    with TestClient(app) as client:
        response = client.post("/sessions/session-1/iq/work-iq/validate")

    assert response.status_code == 404


def test_diagnostics_route_is_reachable_in_development() -> None:
    app = _build_app(environment="development")
    # Service is None (not configured) - this test only proves the
    # environment gate lets the request through to the dependency layer,
    # which then raises its own 503 (see test_dependencies-level coverage) -
    # not a 404.
    with TestClient(app) as client:
        response = client.get("/sessions/session-1/iq/diagnostics")

    assert response.status_code != 404
