"""Tests for ``IqDiagnosticsService`` - a development-only diagnostics
snapshot that must never leak a token, secret, or Microsoft 365 content.
"""
from __future__ import annotations

from app.iq.iq_diagnostics_service import IqDiagnosticsConfig, IqDiagnosticsService
from app.iq.models import DelegatedIdentityContext


class _FakeSessionService:
    async def get_session(self, *, session_id: str, requesting_user_id: str) -> None:
        return None


class _FakeConnectionService:
    def __init__(self, *, identity: DelegatedIdentityContext | None, ready) -> None:
        self._identity = identity
        self._ready = ready

    async def resolve_identity(self, *, session_id: str, provider: str):
        return self._identity

    async def get_ready_connection(self, *, session_id: str, provider: str):
        return self._ready


class _FakeMcpClient:
    def __init__(self, *, tools: list[str]) -> None:
        self._tools = tools

    async def list_tools(self) -> list[str]:
        return self._tools


def _config(**overrides) -> IqDiagnosticsConfig:
    defaults = dict(
        work_iq_enabled=True,
        tenant_configured=True,
        client_configured=True,
        redirect_uri_configured=True,
        work_iq_endpoint_configured=True,
    )
    defaults.update(overrides)
    return IqDiagnosticsConfig(**defaults)


async def test_reports_configuration_flags_without_a_connection() -> None:
    service = IqDiagnosticsService(
        config=_config(),
        connection_service=_FakeConnectionService(identity=None, ready=None),
        session_service=_FakeSessionService(),
    )

    diagnostics = await service.diagnostics(session_id="session-1", requesting_user_id="user-1")

    assert diagnostics.work_iq_enabled is True
    assert diagnostics.tenant_configured is True
    assert diagnostics.connected is False
    assert diagnostics.mcp_initialized is False
    assert diagnostics.tools_discovered_count is None


async def test_reports_connected_and_tool_count_when_ready() -> None:
    identity = DelegatedIdentityContext(
        session_id="session-1", tenant_id="tenant-1", subject="user-1", correlation_id="trace-1"
    )
    client = _FakeMcpClient(tools=["ask", "fetch", "get_schema"])
    service = IqDiagnosticsService(
        config=_config(),
        connection_service=_FakeConnectionService(identity=identity, ready=(client, identity)),
        session_service=_FakeSessionService(),
    )

    diagnostics = await service.diagnostics(session_id="session-1", requesting_user_id="user-1")

    assert diagnostics.connected is True
    assert diagnostics.mcp_initialized is True
    assert diagnostics.tools_discovered_count == 3


async def test_reports_disabled_configuration_when_not_configured() -> None:
    service = IqDiagnosticsService(
        config=_config(
            work_iq_enabled=False,
            tenant_configured=False,
            client_configured=False,
            redirect_uri_configured=False,
            work_iq_endpoint_configured=False,
        ),
        connection_service=None,
        session_service=_FakeSessionService(),
    )

    diagnostics = await service.diagnostics(session_id="session-1", requesting_user_id="user-1")

    assert diagnostics.work_iq_enabled is False
    assert diagnostics.connected is False
    assert diagnostics.mcp_initialized is False


def test_diagnostics_model_has_no_field_that_could_hold_a_secret() -> None:
    # Enforced structurally: IqDiagnostics uses extra="forbid" and every
    # declared field is a bool, int, or short category/id string - assert
    # the exact field set here so a future edit cannot silently add an
    # unsafe field without this test catching it.
    from app.iq.models import IqDiagnostics

    assert set(IqDiagnostics.model_fields.keys()) == {
        "microsoft_connect_enabled",
        "work_iq_enabled",
        "tenant_configured",
        "client_configured",
        "redirect_uri_configured",
        "work_iq_endpoint_configured",
        "connected",
        "mcp_initialized",
        "tools_discovered_count",
        "last_error_category",
        "correlation_id",
    }
