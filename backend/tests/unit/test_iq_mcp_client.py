"""Tests for the IQ MCP JSON-RPC transport (mocked - no live Microsoft service)."""
from __future__ import annotations

import httpx
import pytest

from app.iq.mcp_client import IqMcpClient, IqMcpError

_ENDPOINT = "https://iq.example.test/mcp"
_TOKEN_ENV_VAR = "TEST_IQ_TOKEN"


def _client() -> IqMcpClient:
    return IqMcpClient(endpoint=_ENDPOINT, token_environment_variable=_TOKEN_ENV_VAR, timeout_seconds=5)


def _ok_response(request: httpx.Request, *, request_id: object, result: dict) -> httpx.Response:
    return httpx.Response(
        200, request=request, json={"jsonrpc": "2.0", "id": request_id, "result": result}
    )


async def test_initialize_handshake_runs_once_before_the_first_tools_list(monkeypatch) -> None:
    monkeypatch.setenv(_TOKEN_ENV_VAR, "token-value")
    methods_called: list[str] = []

    async def fake_post(self, url, *, headers, json):
        methods_called.append(json["method"])
        request = httpx.Request("POST", url)
        if json["method"] == "initialize":
            return _ok_response(request, request_id=json["id"], result={"capabilities": {}})
        if json["method"] == "notifications/initialized":
            return httpx.Response(202, request=request)
        if json["method"] == "tools/list":
            return _ok_response(
                request, request_id=json["id"], result={"tools": [{"name": "retrieve"}]}
            )
        raise AssertionError(f"Unexpected method: {json['method']}")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = _client()

    tools = await client.list_tools()
    tools_again = await client.list_tools()

    assert tools == ["retrieve"]
    assert tools_again == ["retrieve"]
    # The initialize handshake must run exactly once, not once per call.
    assert methods_called.count("initialize") == 1
    assert methods_called.count("notifications/initialized") == 1
    assert methods_called == ["initialize", "notifications/initialized", "tools/list", "tools/list"]


async def test_call_tool_returns_structured_content(monkeypatch) -> None:
    monkeypatch.setenv(_TOKEN_ENV_VAR, "token-value")

    async def fake_post(self, url, *, headers, json):
        request = httpx.Request("POST", url)
        if json["method"] == "initialize":
            return _ok_response(request, request_id=json["id"], result={})
        if json["method"] == "notifications/initialized":
            return httpx.Response(202, request=request)
        if json["method"] == "tools/call":
            assert json["params"] == {"name": "retrieve", "arguments": {"query": "hello"}}
            return _ok_response(
                request,
                request_id=json["id"],
                result={"structuredContent": {"answer": "world"}},
            )
        raise AssertionError(f"Unexpected method: {json['method']}")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = _client()

    result = await client.call_tool(name="retrieve", arguments={"query": "hello"})

    assert result == {"answer": "world"}


async def test_call_tool_sends_the_configured_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv(_TOKEN_ENV_VAR, "server-token")
    observed_authorization: str | None = None

    async def fake_post(self, url, *, headers, json):
        nonlocal observed_authorization
        request = httpx.Request("POST", url)
        if json["method"] == "tools/call":
            observed_authorization = headers.get("Authorization")
            return _ok_response(request, request_id=json["id"], result={"structuredContent": {}})
        if json["method"] == "notifications/initialized":
            return httpx.Response(202, request=request)
        return _ok_response(request, request_id=json["id"], result={})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = _client()

    await client.call_tool(name="retrieve", arguments={})

    assert observed_authorization == "Bearer server-token"


async def test_missing_token_raises_authentication_required(monkeypatch) -> None:
    monkeypatch.delenv(_TOKEN_ENV_VAR, raising=False)
    client = _client()

    with pytest.raises(IqMcpError) as exc_info:
        await client.list_tools()

    assert exc_info.value.category == "authentication_required"


async def test_http_401_raises_authentication_required(monkeypatch) -> None:
    monkeypatch.setenv(_TOKEN_ENV_VAR, "token-value")

    async def fake_post(self, url, *, headers, json):
        return httpx.Response(401, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = _client()

    with pytest.raises(IqMcpError) as exc_info:
        await client.list_tools()

    assert exc_info.value.category == "authentication_required"


async def test_http_403_raises_permission_denied(monkeypatch) -> None:
    monkeypatch.setenv(_TOKEN_ENV_VAR, "token-value")

    async def fake_post(self, url, *, headers, json):
        request = httpx.Request("POST", url)
        if json["method"] == "initialize":
            return _ok_response(request, request_id=json["id"], result={})
        if json["method"] == "notifications/initialized":
            return httpx.Response(202, request=request)
        return httpx.Response(403, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = _client()

    with pytest.raises(IqMcpError) as exc_info:
        await client.list_tools()

    assert exc_info.value.category == "permission_denied"


async def test_timeout_raises_timeout_category(monkeypatch) -> None:
    monkeypatch.setenv(_TOKEN_ENV_VAR, "token-value")

    async def fake_post(self, url, *, headers, json):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = _client()

    with pytest.raises(IqMcpError) as exc_info:
        await client.list_tools()

    assert exc_info.value.category == "timeout"


async def test_connection_error_raises_unavailable_category(monkeypatch) -> None:
    monkeypatch.setenv(_TOKEN_ENV_VAR, "token-value")

    async def fake_post(self, url, *, headers, json):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = _client()

    with pytest.raises(IqMcpError) as exc_info:
        await client.list_tools()

    assert exc_info.value.category == "unavailable"


async def test_malformed_result_raises_malformed_response_category(monkeypatch) -> None:
    monkeypatch.setenv(_TOKEN_ENV_VAR, "token-value")

    async def fake_post(self, url, *, headers, json):
        request = httpx.Request("POST", url)
        if json["method"] == "initialize":
            return _ok_response(request, request_id=json["id"], result={})
        if json["method"] == "notifications/initialized":
            return httpx.Response(202, request=request)
        # "tools/list" result with no "tools" key - malformed per the MCP contract.
        return _ok_response(request, request_id=json["id"], result={"unexpected": True})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = _client()

    with pytest.raises(IqMcpError) as exc_info:
        await client.list_tools()

    assert exc_info.value.category == "malformed_response"
