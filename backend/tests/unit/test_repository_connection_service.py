"""Unit tests for administrator-managed GitHub MCP repository connections."""
from __future__ import annotations

import json
from typing import Any

from app.repository_connections.models import GitHubRepositorySummary
from app.repository_connections.repository import InMemoryRepositoryBindingRepository
from app.repository_connections.service import RepositoryConnectionService


def _mcp_result(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value)}]}


class _FakeGitHubMcpClient:
    endpoint = "https://github.example.test/mcp"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if name == "get_me":
            return _mcp_result({"login": "managed-identity"})
        if name == "search_repositories":
            return _mcp_result(
                {
                    "total_count": 1,
                    "incomplete_results": False,
                    "items": [
                        {
                            "id": 42,
                            "name": "source",
                            "full_name": "trusted/source",
                            "description": "Observed from GitHub MCP",
                            "html_url": "https://github.com/trusted/source",
                            "private": True,
                            "archived": False,
                            "default_branch": "main",
                            "language": "Python",
                            "updated_at": "2025-01-01T00:00:00Z",
                        }
                    ],
                }
            )
        if name == "list_commits":
            return _mcp_result([{"sha": "a" * 40}])
        if name == "get_file_contents":
            return _mcp_result({"type": "dir"})
        raise AssertionError(f"Unexpected tool call: {name}")


class _FakeSessionService:
    async def get_session(self, *, session_id: str, requesting_user_id: str) -> object:
        assert session_id == "session-1"
        assert requesting_user_id == "user-1"
        return object()


class _FakeGovernanceService:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def record_tool_request(self, **request: Any) -> None:
        self.requests.append(request)


async def test_status_requires_explicit_connect_before_live_verification() -> None:
    client = _FakeGitHubMcpClient()
    service = RepositoryConnectionService(
        client=client,  # type: ignore[arg-type]
        repository=InMemoryRepositoryBindingRepository(),
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        governance_service=_FakeGovernanceService(),  # type: ignore[arg-type]
    )

    status = await service.connection_status()
    connected = await service.connect()

    assert status.configured is True
    assert status.connected is False
    assert client.calls == [("get_me", {})]
    assert connected.connected is True
    assert connected.account_login == "managed-identity"
    assert connected.authentication_mode == "administrator_managed_mcp"


async def test_binding_persists_mcp_observed_repository_metadata() -> None:
    client = _FakeGitHubMcpClient()
    governance = _FakeGovernanceService()
    repository = InMemoryRepositoryBindingRepository()
    service = RepositoryConnectionService(
        client=client,  # type: ignore[arg-type]
        repository=repository,
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        governance_service=governance,  # type: ignore[arg-type]
    )
    browser_supplied = GitHubRepositorySummary(
        repository_id=999,
        name="source",
        full_name="trusted/source",
        description="Untrusted browser value",
        html_url="https://attacker.example/repository",
        private=False,
        archived=False,
        default_branch="untrusted",
    )

    binding = await service.bind_repository(
        session_id="session-1",
        requesting_user_id="user-1",
        repository=browser_supplied,
        purpose="code",
        requested_ref="main",
        included_paths=["src"],
        excluded_paths=[],
        trace_id="trace-1",
    )

    assert binding.repository_id == 42
    assert binding.repository_url == "https://github.com/trusted/source"
    assert binding.resolved_commit == "a" * 40
    assert binding.principal == "managed-identity"
    assert client.calls[0] == (
        "search_repositories",
        {
            "query": "repo:trusted/source",
            "page": 1,
            "perPage": 10,
            "minimal_output": True,
        },
    )
    assert len(governance.requests) == 1
