"""Tests for ``WorkIqValidationService`` - the development-only, explicit
end-to-end Work IQ validation action.

Focus: it must require a real connection, use a fixed low-risk query
(never an arbitrary caller-supplied one), never persist the retrieved
content, and never log the query result.
"""
from __future__ import annotations

from app.iq.mcp_client import IqMcpError
from app.iq.models import DelegatedIdentityContext
from app.iq.work_iq_validation_service import WorkIqValidationService


class _FakeSessionService:
    async def get_session(self, *, session_id: str, requesting_user_id: str) -> None:
        return None


class _FakeGovernanceService:
    def __init__(self) -> None:
        self.recorded_tool_requests: list[dict] = []

    async def record_tool_request(self, **kwargs) -> None:
        self.recorded_tool_requests.append(kwargs)


class _FakeConnectionService:
    def __init__(self, *, ready, error: Exception | None = None) -> None:
        self._ready = ready
        self._error = error

    async def get_ready_connection(self, *, session_id: str, provider: str):
        if self._error is not None:
            raise self._error
        return self._ready


class _FakeMcpClient:
    def __init__(
        self, *, tools: list[str], call_result=None, call_error: IqMcpError | None = None
    ) -> None:
        self._tools = tools
        self._call_result = call_result
        self._call_error = call_error
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[str]:
        return self._tools

    async def call_tool(self, *, name: str, arguments: dict):
        self.calls.append((name, arguments))
        if self._call_error is not None:
            raise self._call_error
        return self._call_result


def _service(connection_service: _FakeConnectionService, governance: _FakeGovernanceService | None = None):
    return WorkIqValidationService(
        connection_service=connection_service,  # type: ignore[arg-type]
        session_service=_FakeSessionService(),
        governance_service=governance or _FakeGovernanceService(),
        retrieve_tool="ask",
        query_argument="query",
    )


async def test_returns_authentication_required_when_not_connected() -> None:
    service = _service(_FakeConnectionService(ready=None))

    result = await service.validate(session_id="session-1", requesting_user_id="user-1")

    assert result.success is False
    assert result.error_category == "authentication_required"
    assert result.tool_invoked is None


async def test_uses_the_fixed_low_risk_query_not_an_arbitrary_one() -> None:
    client = _FakeMcpClient(tools=["ask"], call_result={"text": "You have 2 meetings today."})
    identity = DelegatedIdentityContext(
        session_id="session-1", tenant_id="tenant-1", subject="user-1", correlation_id="trace-1"
    )
    service = _service(_FakeConnectionService(ready=(client, identity)))

    result = await service.validate(session_id="session-1", requesting_user_id="user-1")

    assert result.success is True
    assert result.tool_invoked == "ask"
    assert client.calls == [("ask", {"query": "Summarize my upcoming meetings for today."})]


async def test_response_preview_is_truncated_and_does_not_persist_full_content() -> None:
    long_text = "A" * 5000
    client = _FakeMcpClient(tools=["ask"], call_result={"text": long_text})
    identity = DelegatedIdentityContext(
        session_id="session-1", tenant_id="tenant-1", subject="user-1", correlation_id="trace-1"
    )
    service = _service(_FakeConnectionService(ready=(client, identity)))

    result = await service.validate(session_id="session-1", requesting_user_id="user-1")

    assert result.response_preview is not None
    assert len(result.response_preview) < len(long_text)
    assert result.response_preview.endswith("(truncated)")


async def test_governance_audit_never_records_the_response_content() -> None:
    client = _FakeMcpClient(tools=["ask"], call_result={"text": "sensitive meeting details here"})
    identity = DelegatedIdentityContext(
        session_id="session-1", tenant_id="tenant-1", subject="user-1", correlation_id="trace-1"
    )
    governance = _FakeGovernanceService()
    service = _service(_FakeConnectionService(ready=(client, identity)), governance)

    await service.validate(session_id="session-1", requesting_user_id="user-1")

    assert len(governance.recorded_tool_requests) == 1
    detail = str(governance.recorded_tool_requests[0]["detail"])
    assert "sensitive meeting details here" not in detail


async def test_citations_are_preserved_when_returned() -> None:
    client = _FakeMcpClient(
        tools=["ask"], call_result={"text": "Summary", "citation": "https://example.test/meeting"}
    )
    identity = DelegatedIdentityContext(
        session_id="session-1", tenant_id="tenant-1", subject="user-1", correlation_id="trace-1"
    )
    service = _service(_FakeConnectionService(ready=(client, identity)))

    result = await service.validate(session_id="session-1", requesting_user_id="user-1")

    assert result.citations == ["https://example.test/meeting"]


async def test_configured_tool_missing_from_tools_list_fails_safely() -> None:
    client = _FakeMcpClient(tools=["some_other_tool"])
    identity = DelegatedIdentityContext(
        session_id="session-1", tenant_id="tenant-1", subject="user-1", correlation_id="trace-1"
    )
    service = _service(_FakeConnectionService(ready=(client, identity)))

    result = await service.validate(session_id="session-1", requesting_user_id="user-1")

    assert result.success is False
    assert client.calls == []  # never invoked a tool the server didn't advertise


async def test_tool_call_failure_is_classified_and_reported() -> None:
    client = _FakeMcpClient(
        tools=["ask"], call_error=IqMcpError("denied", category="permission_denied")
    )
    identity = DelegatedIdentityContext(
        session_id="session-1", tenant_id="tenant-1", subject="user-1", correlation_id="trace-1"
    )
    service = _service(_FakeConnectionService(ready=(client, identity)))

    result = await service.validate(session_id="session-1", requesting_user_id="user-1")

    assert result.success is False
    assert result.error_category == "permission_denied"


async def test_duration_ms_is_recorded_and_non_negative() -> None:
    client = _FakeMcpClient(tools=["ask"], call_result={"text": "ok"})
    identity = DelegatedIdentityContext(
        session_id="session-1", tenant_id="tenant-1", subject="user-1", correlation_id="trace-1"
    )
    service = _service(_FakeConnectionService(ready=(client, identity)))

    result = await service.validate(session_id="session-1", requesting_user_id="user-1")

    assert result.duration_ms >= 0
