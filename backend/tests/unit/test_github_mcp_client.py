"""Tests for the GitHub MCP HTTP transport."""
from __future__ import annotations

import base64
import json

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


def test_file_directory_entries_parses_a_real_directory_listing() -> None:
    """Directory listings put a JSON array directly in content[0].text -
    this has always worked, and must keep working."""
    result = {
        "content": [
            {"type": "text", "text": json.dumps([{"path": "script.js", "type": "file"}])},
        ]
    }

    entries = GitHubMcpClient.file_directory_entries(result)

    assert entries == [{"path": "script.js", "type": "file"}]


def test_file_directory_entries_returns_none_for_a_file_response() -> None:
    """A single file's response must not be misread as a directory listing -
    its first text block is a human-readable message, not a JSON array."""
    result = {
        "content": [
            {"type": "text", "text": "successfully downloaded text file (SHA: deadbeef)"},
            {"type": "resource", "resource": {"text": "console.log('hi');"}},
        ]
    }

    assert GitHubMcpClient.file_directory_entries(result) is None


def test_file_text_reads_the_real_resource_block_shape() -> None:
    """Regression test for the production bug: the real GitHub MCP server
    response for a file puts an info message in content[0], NOT the file's
    content - the actual text lives in a separate "resource"-type block."""
    result = {
        "content": [
            {"type": "text", "text": "successfully downloaded text file (SHA: deadbeef)"},
            {"type": "resource", "resource": {"uri": "repo://o/r/contents/script.js", "text": "console.log('hi');"}},
        ]
    }

    assert GitHubMcpClient.file_text(result) == "console.log('hi');"


def test_file_text_decodes_a_base64_blob_resource() -> None:
    encoded = base64.b64encode(b"console.log('hi');").decode("ascii")
    result = {
        "content": [
            {"type": "text", "text": "successfully downloaded text file (SHA: deadbeef)"},
            {"type": "resource", "resource": {"blob": encoded}},
        ]
    }

    assert GitHubMcpClient.file_text(result) == "console.log('hi');"


def test_file_text_reads_structured_content_fallback() -> None:
    result = {
        "structuredContent": {"content": "console.log('hi');", "encoding": "utf-8"},
        "content": [{"type": "text", "text": "successfully downloaded text file"}],
    }

    assert GitHubMcpClient.file_text(result) == "console.log('hi');"


def test_file_text_decodes_base64_structured_content() -> None:
    encoded = base64.b64encode(b"console.log('hi');").decode("ascii")
    result = {
        "structuredContent": {"content": encoded, "encoding": "base64"},
        "content": [{"type": "text", "text": "successfully downloaded text file"}],
    }

    assert GitHubMcpClient.file_text(result) == "console.log('hi');"


def test_file_text_returns_none_for_a_directory_response() -> None:
    """A directory listing must not be misread as a single file's text."""
    result = {"content": [{"type": "text", "text": json.dumps([{"path": "script.js", "type": "file"}])}]}

    assert GitHubMcpClient.file_text(result) is None
