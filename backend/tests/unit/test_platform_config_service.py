"""Unit tests for PlatformConfigService - the platform-level (not
session-scoped) architecture/standards reference repository configuration
the user asked for: "configure option on left panel... there could be more
than one repo". Covers add/remove, multi-repository combination, and
purpose isolation."""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.platform_config.repository import InMemoryPlatformReferenceRepositoryStore
from app.platform_config.service import PlatformConfigError, PlatformConfigService
from app.repository_connections.models import GitHubRepositorySummary


def _mcp_result(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value)}]}


def _mcp_file_result(text: str) -> dict[str, Any]:
    """Mirrors the REAL GitHub MCP server's documented file-content shape -
    see GitHubMcpClient.file_text's docstring for why content[0].text alone
    is never JSON for a real file response."""
    return {
        "content": [
            {"type": "text", "text": "successfully downloaded text file (SHA: deadbeef)"},
            {"type": "resource", "resource": {"uri": "repo://test/test/contents/x", "text": text}},
        ]
    }


class _FakeGitHubMcpClient:
    endpoint = "https://github.example.test/mcp"

    def __init__(self, *, root_entries: list[dict[str, Any]], file_contents: dict[str, str]) -> None:
        self._root_entries = root_entries
        self._file_contents = file_contents

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "list_commits":
            return _mcp_result([{"sha": "a" * 40}])
        if name == "get_me":
            return _mcp_result({"login": "managed-identity"})
        if name == "get_file_contents":
            path = arguments["path"]
            if path == "":
                return _mcp_result(self._root_entries)
            if path in self._file_contents:
                return _mcp_file_result(self._file_contents[path])
            raise AssertionError(f"Unexpected path: {path}")
        raise AssertionError(f"Unexpected tool call: {name}")


class _FakeGovernanceService:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def record_tool_request(self, **request: Any) -> None:
        self.requests.append(request)


def _repository_summary(full_name: str = "acme/architecture-reference") -> GitHubRepositorySummary:
    return GitHubRepositorySummary(
        repository_id=1,
        name=full_name.split("/")[1],
        full_name=full_name,
        html_url=f"https://github.com/{full_name}",
        private=False,
        archived=False,
        default_branch="main",
    )


def _service(*, root_entries: list[dict[str, Any]], file_contents: dict[str, str]) -> tuple[
    PlatformConfigService, InMemoryPlatformReferenceRepositoryStore, _FakeGovernanceService
]:
    store = InMemoryPlatformReferenceRepositoryStore()
    governance = _FakeGovernanceService()
    service = PlatformConfigService(
        client=_FakeGitHubMcpClient(root_entries=root_entries, file_contents=file_contents),  # type: ignore[arg-type]
        repository_store=store,
        governance_service=governance,  # type: ignore[arg-type]
        max_files=100,
        max_depth=10,
    )
    return service, store, governance


async def test_adds_an_architecture_repository_and_ingests_its_content() -> None:
    service, store, governance = _service(
        root_entries=[{"path": "ARCHITECTURE.md", "type": "file"}],
        file_contents={"ARCHITECTURE.md": "Use a modular monolith with one Postgres database."},
    )

    added = await service.add_repository(
        repository=_repository_summary(),
        purpose="architecture",
        requested_ref="main",
        included_paths=[],
        excluded_paths=[],
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    assert added.purpose == "architecture"
    assert "modular monolith" in (added.combined_reference_text or "")
    assert len(await store.list_all()) == 1
    assert governance.requests[0]["tool_name"] == "github_mcp.configure_platform_reference_repository"


async def test_adds_a_standards_repository_and_classifies_rules() -> None:
    service, _store, _governance = _service(
        root_entries=[{"path": "STANDARDS.md", "type": "file"}],
        file_contents={
            "STANDARDS.md": "# Security\n- Services must use managed identity instead of embedded credentials."
        },
    )

    added = await service.add_repository(
        repository=_repository_summary("acme/standards"),
        purpose="standards",
        requested_ref="main",
        included_paths=[],
        excluded_paths=[],
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    assert added.purpose == "standards"
    assert len(added.rules) == 1
    assert added.rules[0].classification == "mandatory"
    assert added.combined_reference_text is None


async def test_combines_multiple_architecture_repositories() -> None:
    service, _store, _governance = _service(
        root_entries=[{"path": "A.md", "type": "file"}],
        file_contents={"A.md": "First reference."},
    )
    await service.add_repository(
        repository=_repository_summary("acme/architecture-one"),
        purpose="architecture",
        requested_ref="main",
        included_paths=[],
        excluded_paths=[],
        requesting_user_id="user-1",
        trace_id="trace-1",
    )
    await service.add_repository(
        repository=_repository_summary("acme/architecture-two"),
        purpose="architecture",
        requested_ref="main",
        included_paths=[],
        excluded_paths=[],
        requesting_user_id="user-1",
        trace_id="trace-2",
    )

    combined = await service.combined_architecture_reference_text()

    assert combined is not None
    assert combined.count("First reference.") == 2


async def test_combines_multiple_standards_repositories_rules() -> None:
    service, _store, _governance = _service(
        root_entries=[{"path": "S.md", "type": "file"}],
        file_contents={"S.md": "- Services must use managed identity."},
    )
    await service.add_repository(
        repository=_repository_summary("acme/standards-one"),
        purpose="standards",
        requested_ref="main",
        included_paths=[],
        excluded_paths=[],
        requesting_user_id="user-1",
        trace_id="trace-1",
    )
    await service.add_repository(
        repository=_repository_summary("acme/standards-two"),
        purpose="standards",
        requested_ref="main",
        included_paths=[],
        excluded_paths=[],
        requesting_user_id="user-1",
        trace_id="trace-2",
    )

    rules = await service.combined_standards_rules()

    assert len(rules) == 2


async def test_list_repositories_filters_by_purpose() -> None:
    service, _store, _governance = _service(
        root_entries=[{"path": "A.md", "type": "file"}],
        file_contents={"A.md": "Reference."},
    )
    await service.add_repository(
        repository=_repository_summary("acme/architecture-reference"),
        purpose="architecture",
        requested_ref="main",
        included_paths=[],
        excluded_paths=[],
        requesting_user_id="user-1",
        trace_id="trace-1",
    )
    await service.add_repository(
        repository=_repository_summary("acme/standards"),
        purpose="standards",
        requested_ref="main",
        included_paths=[],
        excluded_paths=[],
        requesting_user_id="user-1",
        trace_id="trace-2",
    )

    architecture_only = await service.list_repositories(purpose="architecture")
    all_repositories = await service.list_repositories()

    assert len(architecture_only) == 1
    assert architecture_only[0].repository_full_name == "acme/architecture-reference"
    assert len(all_repositories) == 2


async def test_remove_repository_deletes_it_and_records_governance_event() -> None:
    service, store, governance = _service(
        root_entries=[{"path": "A.md", "type": "file"}],
        file_contents={"A.md": "Reference."},
    )
    added = await service.add_repository(
        repository=_repository_summary(),
        purpose="architecture",
        requested_ref="main",
        included_paths=[],
        excluded_paths=[],
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    await service.remove_repository(repository_id=added.id, trace_id="trace-2")

    assert await store.list_all() == []
    assert governance.requests[-1]["tool_name"] == "github_mcp.remove_platform_reference_repository"


async def test_remove_repository_fails_closed_for_unknown_id() -> None:
    service, _store, _governance = _service(root_entries=[], file_contents={})

    with pytest.raises(PlatformConfigError, match="not found"):
        await service.remove_repository(repository_id="does-not-exist", trace_id="trace-1")
