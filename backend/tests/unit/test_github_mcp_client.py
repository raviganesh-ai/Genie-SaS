"""Tests for the GitHub MCP HTTP transport."""
from __future__ import annotations

import httpx

from app.repository_connections.github_mcp_client import GitHubMcpClient


class _TokenProvider:
    async def get_token(self) -> str:
        return "server-token"


async def test_call_tool_sends_server_side_bearer_token(monkeypatch) -> None:
    observed_authorization: str | None = None

    async def fake_post(self, url, *, headers, json):
        nonlocal observed_authorization
        observed_authorization = headers.get("Authorization")
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "2.0", "id": json["id"], "result": {"content": []}},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = GitHubMcpClient(
        endpoint="https://github.example.test/mcp",
        token_provider=_TokenProvider(),
        timeout_seconds=10,
    )

    await client.call_tool("get_me", {})

    assert observed_authorization == "Bearer server-token"
