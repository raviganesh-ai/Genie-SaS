"""Unit tests for StandardsService.ingest_architecture_reference - the
optional, descriptive-reference-material counterpart to ``ingest``
(Standards). Covers the gap the user identified live: an "architecture"
-purpose repository binding previously had no consumer anywhere in the
backend."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.repository_connections.models import RepositoryPurposeBinding
from app.repository_connections.repository import InMemoryRepositoryBindingRepository
from app.repository_assessment.repository import InMemoryRepositoryAssessmentRepository
from app.standards.architecture_reference_repository import (
    InMemoryArchitectureReferenceRepository,
)
from app.standards.repository import InMemoryStandardsRepository
from app.standards.service import StandardsError, StandardsService


def _mcp_result(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value)}]}


class _FakeGitHubMcpClient:
    endpoint = "https://github.example.test/mcp"

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name == "get_file_contents"
        path = arguments["path"]
        if path == "":
            return _mcp_result([{"path": "ARCHITECTURE.md", "type": "file"}])
        if path == "ARCHITECTURE.md":
            return _mcp_result(
                {"content": "# Architecture\n\nUse a modular monolith with one database.", "encoding": "utf-8"}
            )
        raise AssertionError(f"Unexpected path: {path}")


class _FakeSessionService:
    async def get_session(self, *, session_id: str, requesting_user_id: str) -> object:
        return object()


class _FakeGovernanceService:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def record_tool_request(self, **request: Any) -> None:
        self.requests.append(request)


def _binding(*, purpose: str, status: str = "approved") -> RepositoryPurposeBinding:
    now = datetime.now(UTC)
    return RepositoryPurposeBinding(
        id="binding-1",
        session_id="session-1",
        owner_user_id="user-1",
        repository_id=42,
        repository_full_name="acme/architecture-reference",
        repository_url="https://github.com/acme/architecture-reference",
        purpose=purpose,  # type: ignore[arg-type]
        requested_ref="main",
        resolved_commit="a" * 40,
        principal="managed-identity",
        status=status,  # type: ignore[arg-type]
        validated_at=now,
        created_at=now,
    )


def _service(*, binding_repository: InMemoryRepositoryBindingRepository) -> StandardsService:
    return StandardsService(
        client=_FakeGitHubMcpClient(),  # type: ignore[arg-type]
        binding_repository=binding_repository,
        assessment_repository=InMemoryRepositoryAssessmentRepository(),
        standards_repository=InMemoryStandardsRepository(),
        architecture_reference_repository=InMemoryArchitectureReferenceRepository(),
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        governance_service=_FakeGovernanceService(),  # type: ignore[arg-type]
        max_files=100,
        max_depth=10,
    )


async def test_ingests_an_architecture_purpose_binding_as_descriptive_reference_text() -> None:
    binding_repository = InMemoryRepositoryBindingRepository()
    await binding_repository.put(_binding(purpose="architecture"))
    service = _service(binding_repository=binding_repository)

    snapshot = await service.ingest_architecture_reference(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    assert "modular monolith" in snapshot.combined_reference_text
    assert snapshot.paths == ["ARCHITECTURE.md"]
    assert snapshot.gaps == []


async def test_rejects_a_code_purpose_binding() -> None:
    binding_repository = InMemoryRepositoryBindingRepository()
    await binding_repository.put(_binding(purpose="code"))
    service = _service(binding_repository=binding_repository)

    with pytest.raises(StandardsError, match="Architecture-purpose"):
        await service.ingest_architecture_reference(
            session_id="session-1",
            binding_id="binding-1",
            requesting_user_id="user-1",
            trace_id="trace-1",
        )


async def test_rejects_a_standards_purpose_binding() -> None:
    binding_repository = InMemoryRepositoryBindingRepository()
    await binding_repository.put(_binding(purpose="standards"))
    service = _service(binding_repository=binding_repository)

    with pytest.raises(StandardsError, match="Architecture-purpose"):
        await service.ingest_architecture_reference(
            session_id="session-1",
            binding_id="binding-1",
            requesting_user_id="user-1",
            trace_id="trace-1",
        )


async def test_list_architecture_reference_snapshots_is_scoped_to_the_session() -> None:
    binding_repository = InMemoryRepositoryBindingRepository()
    await binding_repository.put(_binding(purpose="architecture"))
    service = _service(binding_repository=binding_repository)
    await service.ingest_architecture_reference(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    same_session = await service.list_architecture_reference_snapshots(
        session_id="session-1", requesting_user_id="user-1"
    )
    other_session = await service.list_architecture_reference_snapshots(
        session_id="session-2", requesting_user_id="user-1"
    )

    assert len(same_session) == 1
    assert other_session == []
