"""Client for the public, unauthenticated Microsoft Learn MCP server.

Confirmed live during development (not merely assumed from documentation):
a stateless ``tools/call`` JSON-RPC request against
``https://learn.microsoft.com/api/mcp`` succeeds immediately with no prior
``initialize`` handshake or session header, and returns a Server-Sent-Events
-framed (``event: message`` / ``data: {...}``) JSON-RPC response - the same
general Streamable HTTP shape ``GitHubMcpClient`` already handles, just
unauthenticated and pointed at a different public endpoint. Exposes exactly
the two tools this server publishes:

- ``microsoft_docs_search`` - real-time search over learn.microsoft.com,
  returning ``{title, content, contentUrl}`` per hit.
- ``microsoft_docs_fetch`` - fetches one page's full real markdown content
  by its exact ``contentUrl``.

Never invents a broader MCP surface than what was actually observed.
"""
from __future__ import annotations

import json
from typing import Any

import httpx


class MicrosoftLearnMcpError(RuntimeError):
    """Raised when the Microsoft Learn MCP server cannot produce live evidence."""


class MicrosoftLearnMcpClient:
    def __init__(self, *, endpoint: str, timeout_seconds: float) -> None:
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds
        self._next_id = 1

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Returns up to the server's own result cap of real document hits,
        each with ``title``, ``content`` (an excerpt), and ``contentUrl``."""
        result = await self._call_tool("microsoft_docs_search", {"query": query})
        payload = self._tool_json(result, "microsoft_docs_search")
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise MicrosoftLearnMcpError(
                "microsoft_docs_search returned an unexpected response shape."
            )
        return [item for item in results if isinstance(item, dict)]

    async def fetch(self, url: str) -> str:
        """Returns one page's full real markdown content for ``url`` (which
        must be a ``contentUrl`` previously returned by ``search``)."""
        result = await self._call_tool("microsoft_docs_fetch", {"url": url})
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    return text
        raise MicrosoftLearnMcpError(f"microsoft_docs_fetch returned no content for '{url}'.")

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                    json=body,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MicrosoftLearnMcpError(
                f"Microsoft Learn MCP rejected tool '{name}' with status "
                f"{exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise MicrosoftLearnMcpError(f"Microsoft Learn MCP tool '{name}' is unavailable.") from exc

        payload = self._parse_response(response.text)
        if payload.get("id") != request_id:
            raise MicrosoftLearnMcpError(
                f"Microsoft Learn MCP returned an unexpected response id for '{name}'."
            )
        protocol_error = payload.get("error")
        if protocol_error is not None:
            message = (
                protocol_error.get("message")
                if isinstance(protocol_error, dict)
                else str(protocol_error)
            )
            raise MicrosoftLearnMcpError(message or f"Microsoft Learn MCP tool '{name}' errored.")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise MicrosoftLearnMcpError(f"Microsoft Learn MCP tool '{name}' returned an invalid result.")
        if result.get("isError"):
            raise MicrosoftLearnMcpError(self._tool_error_text(result, name))
        return result

    @staticmethod
    def _tool_json(result: dict[str, Any], name: str) -> Any:
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError as exc:
                        raise MicrosoftLearnMcpError(
                            f"Microsoft Learn MCP tool '{name}' returned non-JSON content."
                        ) from exc
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        raise MicrosoftLearnMcpError(f"Microsoft Learn MCP tool '{name}' returned no content.")

    @staticmethod
    def _parse_response(raw: str) -> dict[str, Any]:
        stripped = raw.strip()
        if not stripped:
            raise MicrosoftLearnMcpError("Microsoft Learn MCP returned an empty response.")
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
        raise MicrosoftLearnMcpError("Microsoft Learn MCP returned an invalid JSON-RPC response.")

    @staticmethod
    def _tool_error_text(result: dict[str, Any], name: str) -> str:
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    return text
        return f"Microsoft Learn MCP tool '{name}' failed."
