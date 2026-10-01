"""Tests for ``DelegatedConnectionService`` - the application service
backing the /iq/connections API routes.

Focus areas: session ownership enforcement, disabled-provider rejection,
per-session status before/after connecting, disconnect cleanup, and that
governance audit events never carry a raw token.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.iq.delegated_connection_manager import DelegatedMcpConnectionManager
from app.iq.delegated_connection_service import (
    DelegatedConnectionService,
    DelegatedConnectionServiceError,
)
from app.iq.delegated_token_broker import ExchangedDelegatedToken
from app.iq.microsoft_resource_registry import MicrosoftMcpResourceRegistry
from app.iq.pending_oauth_flow import PendingOAuthFlowStore
from app.iq.session_identity_index import SessionIdentityIndex
from app.iq.token_cache import InMemoryUserTokenCachePartition


class _FakeSessionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get_session(self, *, session_id: str, requesting_user_id: str) -> None:
        self.calls.append((session_id, requesting_user_id))


class _FakeGovernanceService:
    def __init__(self) -> None:
        self.recorded_tool_requests: list[dict] = []

    async def record_tool_request(self, **kwargs) -> None:
        self.recorded_tool_requests.append(kwargs)


class _FakeTokenBroker:
    def __init__(self) -> None:
        self.build_authorization_url_calls: list[dict] = []
        self.next_exchange_result: ExchangedDelegatedToken | None = None

    async def build_authorization_url(self, *, provider, state, code_verifier) -> str:
        self.build_authorization_url_calls.append(
            {"provider": provider, "state": state, "code_verifier": code_verifier}
        )
        return f"https://login.microsoftonline.com/authorize?state={state}"

    async def exchange_code(self, *, provider, code, code_verifier) -> ExchangedDelegatedToken:
        assert self.next_exchange_result is not None
        return self.next_exchange_result


def _registry() -> MicrosoftMcpResourceRegistry:
    return MicrosoftMcpResourceRegistry.from_settings(
        work_iq_mcp_endpoint="https://workiq.svc.cloud.microsoft/mcp",
        work_iq_scopes=None,
        fabric_iq_mcp_endpoint="https://fabriciq.svc.cloud.microsoft/v1/mcp/fabriciq",
        fabric_iq_scopes=("https://analysis.windows.net/powerbi/api/Item.Read.All",),
    )


def _service(broker: _FakeTokenBroker, *, enabled_providers=frozenset({"work_iq", "fabric_iq"})):
    manager = DelegatedMcpConnectionManager(
        registry=_registry(),
        token_broker=broker,  # type: ignore[arg-type]
        token_cache=InMemoryUserTokenCachePartition(),
        mcp_timeout_seconds=30,
    )
    session_service = _FakeSessionService()
    governance_service = _FakeGovernanceService()
    service = DelegatedConnectionService(
        connection_manager=manager,
        token_broker=broker,  # type: ignore[arg-type]
        pending_flow_store=PendingOAuthFlowStore(),
        session_identity_index=SessionIdentityIndex(),
        session_service=session_service,
        governance_service=governance_service,
        enabled_providers=enabled_providers,
    )
    return service, session_service, governance_service


async def test_start_validates_session_ownership_before_anything_else() -> None:
    service, session_service, _ = _service(_FakeTokenBroker())

    await service.start(session_id="session-1", provider="work_iq", requesting_user_id="user-1")

    assert session_service.calls == [("session-1", "user-1")]


async def test_start_rejects_a_disabled_provider() -> None:
    service, _, _ = _service(_FakeTokenBroker(), enabled_providers=frozenset({"work_iq"}))

    with pytest.raises(DelegatedConnectionServiceError):
        await service.start(session_id="session-1", provider="fabric_iq", requesting_user_id="user-1")


async def test_status_reports_authentication_required_before_connecting() -> None:
    service, _, _ = _service(_FakeTokenBroker())

    statuses = await service.status(session_id="session-1", requesting_user_id="user-1")

    assert {s.provider: s.status for s in statuses} == {
        "work_iq": "IQ_AUTHENTICATION_REQUIRED",
        "fabric_iq": "IQ_AUTHENTICATION_REQUIRED",
    }
    assert all(not s.connected for s in statuses)


async def test_callback_then_status_reports_available_and_records_a_redacted_audit_event() -> None:
    broker = _FakeTokenBroker()
    service, _, governance_service = _service(broker)
    broker.next_exchange_result = ExchangedDelegatedToken(
        access_token="super-secret-access-token",
        refresh_token="super-secret-refresh-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("scope-a",),
        tenant_id="tenant-1",
        subject="user-1",
        display_name="Ada Lovelace",
    )
    state, code_verifier = await service._pending_flow_store.start(
        session_id="session-1", provider="work_iq"
    )

    session_id, provider = await service.handle_callback(code="auth-code", state=state, trace_id="trace-1")

    assert session_id == "session-1"
    assert provider == "work_iq"

    statuses = await service.status(session_id="session-1", requesting_user_id="user-1")
    work_iq_status = next(s for s in statuses if s.provider == "work_iq")
    assert work_iq_status.status == "IQ_AVAILABLE"
    assert work_iq_status.connected is True
    assert work_iq_status.display_name == "Ada Lovelace"

    # Governance audit trail must never carry the raw token.
    assert len(governance_service.recorded_tool_requests) == 1
    recorded_detail = governance_service.recorded_tool_requests[0]["detail"]
    serialized_detail = str(recorded_detail)
    assert "super-secret-access-token" not in serialized_detail
    assert "super-secret-refresh-token" not in serialized_detail


async def test_disconnect_clears_the_connection_and_records_an_audit_event() -> None:
    broker = _FakeTokenBroker()
    service, _, governance_service = _service(broker)
    broker.next_exchange_result = ExchangedDelegatedToken(
        access_token="access-token-1",
        refresh_token="refresh-token-1",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("scope-a",),
        tenant_id="tenant-1",
        subject="user-1",
        display_name=None,
    )
    state, _ = await service._pending_flow_store.start(session_id="session-1", provider="work_iq")
    await service.handle_callback(code="auth-code", state=state, trace_id="trace-1")

    await service.disconnect(
        session_id="session-1", provider="work_iq", requesting_user_id="user-1", trace_id="trace-2"
    )

    statuses = await service.status(session_id="session-1", requesting_user_id="user-1")
    work_iq_status = next(s for s in statuses if s.provider == "work_iq")
    assert work_iq_status.status == "IQ_AUTHENTICATION_REQUIRED"
    assert len(governance_service.recorded_tool_requests) == 2  # connect + disconnect


async def test_resolve_identity_returns_none_when_not_connected() -> None:
    service, _, _ = _service(_FakeTokenBroker())

    identity = await service.resolve_identity(session_id="session-1", provider="work_iq")

    assert identity is None


async def test_get_ready_connection_returns_none_when_not_connected() -> None:
    service, _, _ = _service(_FakeTokenBroker())

    ready = await service.get_ready_connection(session_id="session-1", provider="work_iq")

    assert ready is None
