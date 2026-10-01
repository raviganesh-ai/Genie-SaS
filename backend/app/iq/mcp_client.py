"""Generic authenticated MCP client for runtime-discovered IQ tools.

Implements the subset of the MCP lifecycle Genie's IQ providers need:
``initialize`` (once, before any other call), ``tools/list``, and
``tools/call``, over JSON-RPC 2.0 per the Model Context Protocol
specification (https://modelcontextprotocol.io). Errors are categorized so
callers (``IqEvidenceService``) can represent provider state using Genie's
explicit IQ status vocabulary instead of crashing the calling workflow.

Two token-sourcing modes are supported:

- ``token_environment_variable`` - the legacy administrator-managed static
  token mode (still used by Foundry IQ / Foundry MCP, which keep the prior
  configuration-based authorization model).
- ``token_provider`` - an async callable returning the *current* valid
  access token for one call. Used exclusively by
  ``DelegatedMcpConnectionManager`` for Work IQ/Fabric IQ, where the token
  is a per-user delegated token that can expire/refresh between calls -
  the client never caches or owns that token itself.

Exactly one of the two must be supplied.

ASSUMPTION (isolated behind this module so it can be corrected without
touching callers): this hand-rolled JSON-RPC-over-HTTPX client implements
the lifecycle/tool subset of the protocol rather than depending on the
official `mcp` Python SDK (PyPI: `mcp`, https://pypi.org/project/mcp/),
which was evaluated but not adopted this iteration pending verification of
its bearer-token injection and dependency footprint. See
``docs/architecture/genie-sas-microsoft-iq.md`` for the recommended
follow-up.
"""
from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import httpx

IqMcpErrorCategory = Literal[
    "authentication_required",
    "permission_denied",
    "timeout",
    "unavailable",
    "malformed_response",
]

TokenProvider = Callable[[], Awaitable[str]]


class IqMcpError(RuntimeError):
    """Raised when an IQ MCP provider cannot satisfy its live contract."""

    def __init__(self, message: str, *, category: IqMcpErrorCategory = "unavailable") -> None:
        super().__init__(message)
        self.category = category


class IqMcpClient:
    def __init__(
        self,
        *,
        endpoint: str,
        timeout_seconds: float,
        token_environment_variable: str | None = None,
        token_provider: TokenProvider | None = None,
    ) -> None:
        if (token_environment_variable is None) == (token_provider is None):
            raise ValueError(
                "Exactly one of 'token_environment_variable' or 'token_provider' must be set."
            )
        self._endpoint = endpoint
        self._token_environment_variable = token_environment_variable
        self._token_provider = token_provider
        self._timeout_seconds = timeout_seconds
        self._request_id = 1
        self._initialized = False

    @property
    def endpoint(self) -> str:
        return self._endpoint

    async def list_tools(self) -> list[str]:
        tools = await self.list_tools_detailed()
        names = [tool["name"] for tool in tools if isinstance(tool.get("name"), str)]
        return sorted(names)

    async def list_tools_detailed(self) -> list[dict[str, Any]]:
        """Returns the raw ``tools/list`` entries (including ``annotations``
        where the server provides them) - used by
        ``app.iq.tool_classification`` to classify mutation behavior before
        a tool is ever called."""
        await self._ensure_initialized()
        result = await self._request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list) or not all(isinstance(tool, dict) for tool in tools):
            raise IqMcpError(
                "IQ MCP tools/list returned an invalid tool collection.",
                category="malformed_response",
            )
        return tools

    async def call_tool(self, *, name: str, arguments: dict[str, Any]) -> Any:
        await self._ensure_initialized()
        result = await self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        if result.get("isError"):
            raise IqMcpError(self._content_text(result) or f"IQ MCP tool '{name}' failed.")
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        text = self._content_text(result)
        if text is None:
            raise IqMcpError(
                f"IQ MCP tool '{name}' returned no content.", category="malformed_response"
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    async def _ensure_initialized(self) -> None:
        """Performs the MCP lifecycle handshake exactly once per client.

        Per the MCP specification, a client must send ``initialize`` and
        receive the server's capabilities before issuing any other request,
        then send the ``notifications/initialized`` notification to
        complete the handshake.
        """
        if self._initialized:
            return
        await self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "genie-sas", "version": "1.0.0"},
            },
        )
        await self._notify("notifications/initialized", {})
        self._initialized = True

    async def _resolve_token(self) -> str:
        if self._token_provider is not None:
            token = await self._token_provider()
            if not token:
                raise IqMcpError(
                    "The delegated token provider returned an empty token.",
                    category="authentication_required",
                )
            return token
        token = os.environ.get(self._token_environment_variable or "")
        if not token:
            raise IqMcpError(
                "The configured IQ credential environment variable is empty.",
                category="authentication_required",
            )
        return token

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        token = await self._resolve_token()
        request_id = self._request_id
        self._request_id += 1
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": params,
                    },
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise IqMcpError(
                f"IQ MCP request '{method}' timed out.", category="timeout"
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 401:
                raise IqMcpError(
                    f"IQ MCP rejected '{method}' as unauthenticated (401).",
                    category="authentication_required",
                ) from exc
            if status_code == 403:
                raise IqMcpError(
                    f"IQ MCP denied permission for '{method}' (403).",
                    category="permission_denied",
                ) from exc
            raise IqMcpError(
                f"IQ MCP rejected '{method}' with status {status_code}.",
                category="unavailable",
            ) from exc
        except httpx.HTTPError as exc:
            raise IqMcpError(
                f"IQ MCP request '{method}' is unavailable.", category="unavailable"
            ) from exc
        payload = self._parse_payload(response.text)
        if payload.get("id") != request_id:
            raise IqMcpError(
                "IQ MCP returned an unexpected response id.", category="malformed_response"
            )
        if payload.get("error") is not None:
            error = payload["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise IqMcpError(message or f"IQ MCP request '{method}' failed.")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise IqMcpError(
                f"IQ MCP request '{method}' returned an invalid result.",
                category="malformed_response",
            )
        return result

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        """Sends a fire-and-forget JSON-RPC notification (no ``id``, no response)."""
        token = await self._resolve_token()
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                await client.post(
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                    json={"jsonrpc": "2.0", "method": method, "params": params},
                )
        except httpx.TimeoutException as exc:
            raise IqMcpError(f"IQ MCP notification '{method}' timed out.", category="timeout") from exc
        except httpx.HTTPError as exc:
            raise IqMcpError(
                f"IQ MCP notification '{method}' is unavailable.", category="unavailable"
            ) from exc

    @staticmethod
    def _parse_payload(raw: str) -> dict[str, Any]:
        candidates = [
            line[len("data:") :].strip()
            for line in raw.strip().splitlines()
            if line.startswith("data:")
        ]
        for serialized in reversed(candidates or [raw.strip()]):
            try:
                payload = json.loads(serialized)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise IqMcpError("IQ MCP returned an invalid JSON-RPC response.", category="malformed_response")

    @staticmethod
    def _content_text(result: dict[str, Any]) -> str | None:
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    return text
        return None

