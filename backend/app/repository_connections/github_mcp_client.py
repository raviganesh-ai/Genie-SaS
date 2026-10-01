"""Async client for the configured GitHub MCP Streamable HTTP endpoint."""
from __future__ import annotations

import json
import os
from typing import Any, Protocol

import httpx


class GitHubMcpError(RuntimeError):
    """Raised when the configured GitHub MCP connection cannot produce live evidence."""


class GitHubTokenProvider(Protocol):
    async def get_token(self) -> str: ...


class EnvironmentGitHubTokenProvider:
    def __init__(self, *, environment_variable: str) -> None:
        self._environment_variable = environment_variable

    async def get_token(self) -> str:
        token = os.environ.get(self._environment_variable)
        if not token:
            raise GitHubMcpError(
                "The configured GitHub MCP credential environment variable is empty."
            )
        return token


class GitHubMcpClient:
    def __init__(
        self,
        *,
        endpoint: str,
        token_provider: GitHubTokenProvider,
        timeout_seconds: float,
    ) -> None:
        self._endpoint = endpoint
        self._token_provider = token_provider
        self._timeout_seconds = timeout_seconds
        self._next_id = 1

    @property
    def endpoint(self) -> str:
        return self._endpoint

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        token = await self._token_provider.get_token()
        request_id = self._next_id
        self._next_id += 1
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                    json=body,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GitHubMcpError(
                f"GitHub MCP rejected tool '{name}' with status {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise GitHubMcpError(f"GitHub MCP tool '{name}' is unavailable.") from exc

        payload = self._parse_response(response.text)
        if payload.get("id") != request_id:
            raise GitHubMcpError(f"GitHub MCP returned an unexpected response id for '{name}'.")
        protocol_error = payload.get("error")
        if protocol_error is not None:
            message = (
                protocol_error.get("message")
                if isinstance(protocol_error, dict)
                else str(protocol_error)
            )
            raise GitHubMcpError(message or f"GitHub MCP tool '{name}' returned an error.")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise GitHubMcpError(f"GitHub MCP tool '{name}' returned an invalid result.")
        if result.get("isError"):
            raise GitHubMcpError(self._tool_error_text(result, name))
        return result

    @staticmethod
    def tool_json(result: dict[str, Any]) -> Any:
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError as exc:
                        raise GitHubMcpError("GitHub MCP returned non-JSON tool content.") from exc
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        raise GitHubMcpError("GitHub MCP returned no structured tool content.")

    @staticmethod
    def tool_content(result: dict[str, Any]) -> Any:
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return text
        raise GitHubMcpError("GitHub MCP returned no tool content.")

    @staticmethod
    def _parse_response(raw: str) -> dict[str, Any]:
        stripped = raw.strip()
        if not stripped:
            raise GitHubMcpError("GitHub MCP returned an empty response.")
        candidates: list[str] = []
        for line in stripped.splitlines():
            if line.startswith("data:"):
                candidates.append(line[len("data:") :].strip())
        serialized_candidates = list(reversed(candidates)) if candidates else [stripped]
        for serialized in serialized_candidates:
            try:
                payload = json.loads(serialized)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise GitHubMcpError("GitHub MCP returned an invalid JSON-RPC response.")

    @staticmethod
    def _tool_error_text(result: dict[str, Any], name: str) -> str:
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    return text
        return f"GitHub MCP tool '{name}' failed."
