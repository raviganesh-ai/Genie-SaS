"""Async client for the configured GitHub MCP Streamable HTTP endpoint."""
from __future__ import annotations

import base64
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
    def file_directory_entries(result: dict[str, Any]) -> list[dict[str, Any]] | None:
        """Returns a ``get_file_contents`` directory listing, or ``None`` if
        this response is not a directory listing (e.g. it is a single
        file's content - callers should then try ``file_text``).

        Unlike ``tool_json``, never raises on non-JSON ``content[].text`` -
        a single file's response legitimately has a human-readable, non-JSON
        first text block (see ``file_text``'s docstring), so failing to
        parse it as JSON here must fall through, not raise.
        """
        structured = result.get("structuredContent")
        if isinstance(structured, list) and all(isinstance(item, dict) for item in structured):
            return structured
        if isinstance(structured, dict):
            for key in ("items", "entries"):
                value = structured.get(key)
                if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                    return value
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, list) and all(isinstance(entry, dict) for entry in parsed):
                        return parsed
        return None

    @staticmethod
    def file_text(result: dict[str, Any]) -> str | None:
        """Returns one file's decoded text content for a ``get_file_contents``
        call on a file path, or ``None`` if this response is not a single
        file's text content (e.g. it is a directory listing, or the file
        could not be decoded as text).

        The real GitHub MCP server's documented response shape for a file is
        NOT a single JSON-encoded object in ``content[0].text`` - it is a
        human-readable informational message ("successfully downloaded text
        file") in ``content[0]``, with the actual file content in a
        *separate* ``content[]`` item of type ``"resource"`` (and/or
        mirrored into ``structuredContent`` - both are checked here since
        real-world responses have been observed to vary; see
        https://github.com/github/github-mcp-server/issues/595 and
        https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1624).
        Confirmed via a live call against the real endpoint during
        development (not only documentation) - see
        docs/validation/work-iq-development-validation.md's sibling
        investigation for this repository-assessment defect.
        """
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            content = structured.get("content")
            if isinstance(content, str):
                if structured.get("encoding") == "base64":
                    try:
                        return base64.b64decode(content, validate=True).decode("utf-8")
                    except (ValueError, UnicodeDecodeError):
                        return None
                return content
        for item in result.get("content", []):
            if not isinstance(item, dict) or item.get("type") != "resource":
                continue
            resource = item.get("resource")
            if not isinstance(resource, dict):
                continue
            text = resource.get("text")
            if isinstance(text, str):
                return text
            blob = resource.get("blob")
            if isinstance(blob, str):
                try:
                    return base64.b64decode(blob, validate=True).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    return None
        return None

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
