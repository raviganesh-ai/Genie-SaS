"""Unit tests for RepositoryAssessmentService - the deterministic
dependency/component/technology graph builder, plus the optional,
layered-on-top plain-language code summary + component-role classification
(_attach_code_summary) that calls the code-analyst Foundry agent."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.agents.gateway import AgentGatewayError
from app.agents.models import AgentExecutionResult
from app.repository_assessment.repository import InMemoryRepositoryAssessmentRepository
from app.repository_assessment.service import RepositoryAssessmentError, RepositoryAssessmentService
from app.repository_connections.github_mcp_client import GitHubMcpError
from app.repository_connections.models import RepositoryPurposeBinding
from app.repository_connections.repository import InMemoryRepositoryBindingRepository


def _mcp_result(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value)}]}


def _mcp_file_result(text: str) -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": "successfully downloaded text file (SHA: deadbeef)"},
            {"type": "resource", "resource": {"uri": "repo://test/test/contents/x", "text": text}},
        ]
    }


_FILES = {
    "frontend/app.tsx": "import React from 'react';\nexport const App = () => null;\n",
    "frontend/package.json": json.dumps({"dependencies": {"react": "^18.2.0"}}),
    "backend/main.py": (
        "import fastapi\n\nENDPOINT = \"https://api.example.test/webhook\"\n"
    ),
    "backend/requirements.txt": "fastapi==0.110.0\n",
}


class _FakeGitHubMcpClient:
    endpoint = "https://github.example.test/mcp"

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name == "get_file_contents"
        path = arguments["path"]
        if path == "":
            return _mcp_result(
                [
                    {"path": "README.md", "type": "file"},
                    {"path": "frontend", "type": "dir"},
                    {"path": "backend", "type": "dir"},
                ]
            )
        if path == "frontend":
            return _mcp_result(
                [
                    {"path": "frontend/app.tsx", "type": "file"},
                    {"path": "frontend/package.json", "type": "file"},
                ]
            )
        if path == "backend":
            return _mcp_result(
                [
                    {"path": "backend/main.py", "type": "file"},
                    {"path": "backend/requirements.txt", "type": "file"},
                ]
            )
        if path in _FILES:
            return _mcp_file_result(_FILES[path])
        raise AssertionError(f"Unexpected path: {path}")


class _FakeSessionService:
    async def get_session(self, *, session_id: str, requesting_user_id: str) -> object:
        return object()


class _FakeGovernanceService:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def record_tool_request(self, **request: Any) -> None:
        self.requests.append(request)


class _FakeAgentOrchestrator:
    """Returns each entry of ``responses`` in order (one per retry attempt),
    or raises ``AgentGatewayError`` if ``raise_error`` is set - mirroring
    the two real failure modes _attach_code_summary must tolerate."""

    def __init__(
        self, *, responses: list[str] | None = None, raise_error: bool = False
    ) -> None:
        self._responses = list(responses or [])
        self._raise_error = raise_error
        self.calls: list[dict[str, Any]] = []

    async def execute_agent(
        self,
        *,
        agent_id: str,
        prompt_id: str,
        variables: dict[str, str],
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> AgentExecutionResult:
        self.calls.append({"agent_id": agent_id, "prompt_id": prompt_id, "variables": variables})
        if self._raise_error:
            raise AgentGatewayError("Azure AI Foundry is unavailable.")
        output_text = self._responses.pop(0)
        return AgentExecutionResult(
            agent_id=agent_id,
            output_text=output_text,
            correlation_id=trace_id or "trace-1",
        )


def _binding() -> RepositoryPurposeBinding:
    now = datetime.now(UTC)
    return RepositoryPurposeBinding(
        id="binding-1",
        session_id="session-1",
        owner_user_id="user-1",
        repository_id=7,
        repository_full_name="acme/juniper-table-demo",
        repository_url="https://github.com/acme/juniper-table-demo",
        purpose="code",
        requested_ref="main",
        resolved_commit="a" * 40,
        principal="managed-identity",
        status="approved",
        validated_at=now,
        created_at=now,
    )


@pytest.fixture
async def seeded_binding_repository() -> InMemoryRepositoryBindingRepository:
    repository = InMemoryRepositoryBindingRepository()
    await repository.put(_binding())
    return repository


def _service_with_bindings(
    binding_repository: InMemoryRepositoryBindingRepository, *, orchestrator: Any = None
) -> RepositoryAssessmentService:
    return RepositoryAssessmentService(
        client=_FakeGitHubMcpClient(),  # type: ignore[arg-type]
        binding_repository=binding_repository,
        assessment_repository=InMemoryRepositoryAssessmentRepository(),
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        governance_service=_FakeGovernanceService(),  # type: ignore[arg-type]
        max_files=100,
        max_depth=10,
        max_source_bytes=1_000_000,
        orchestrator=orchestrator,
    )


async def test_groups_analyzed_files_into_top_level_folder_components(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    service = _service_with_bindings(seeded_binding_repository)

    assessment = await service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    component_names = {node.name for node in assessment.nodes if node.type == "component"}
    assert component_names == {"frontend", "backend"}
    # README.md was discovered but never analyzed (not a manifest/source
    # suffix), so it must not have created a "(root)" component.
    assert "(root)" not in component_names


async def test_detects_languages_and_curated_frameworks_as_technology_nodes(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    service = _service_with_bindings(seeded_binding_repository)

    assessment = await service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    technology_names = {node.name for node in assessment.nodes if node.type == "technology"}
    assert technology_names == {"TypeScript", "React", "Python", "FastAPI"}

    nodes_by_id = {node.id: node for node in assessment.nodes}
    frontend_id = next(n.id for n in assessment.nodes if n.name == "frontend")
    backend_id = next(n.id for n in assessment.nodes if n.name == "backend")
    built_on_targets = {
        (edge.source, nodes_by_id[edge.target].name)
        for edge in assessment.edges
        if edge.type == "built_on"
    }
    assert (frontend_id, "TypeScript") in built_on_targets
    assert (frontend_id, "React") in built_on_targets
    assert (backend_id, "Python") in built_on_targets
    assert (backend_id, "FastAPI") in built_on_targets


_LOCAL_IMPORT_FILES = {
    "backend/main.py": (
        "import fastapi\nfrom shared.helper import do_thing\nfrom utils import local_helper\n"
    ),
    "backend/requirements.txt": "fastapi==0.110.0\n",
    "backend/utils.py": "def local_helper():\n    pass\n",
    "shared/helper.py": "def do_thing():\n    pass\n",
}


class _FakeGitHubMcpClientWithLocalImport:
    """A second repo layout, isolated from `_FakeGitHubMcpClient` above, with
    both a cross-component local import (backend -> shared) and a
    same-component local import (backend -> backend) - so the two cases can
    be asserted independently of the other graph-construction tests."""

    endpoint = "https://github.example.test/mcp"

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name == "get_file_contents"
        path = arguments["path"]
        if path == "":
            return _mcp_result([{"path": "backend", "type": "dir"}, {"path": "shared", "type": "dir"}])
        if path == "backend":
            return _mcp_result(
                [
                    {"path": "backend/main.py", "type": "file"},
                    {"path": "backend/requirements.txt", "type": "file"},
                    {"path": "backend/utils.py", "type": "file"},
                ]
            )
        if path == "shared":
            return _mcp_result([{"path": "shared/helper.py", "type": "file"}])
        if path in _LOCAL_IMPORT_FILES:
            return _mcp_file_result(_LOCAL_IMPORT_FILES[path])
        raise AssertionError(f"Unexpected path: {path}")


def _service_with_local_imports(
    binding_repository: InMemoryRepositoryBindingRepository,
) -> RepositoryAssessmentService:
    return RepositoryAssessmentService(
        client=_FakeGitHubMcpClientWithLocalImport(),  # type: ignore[arg-type]
        binding_repository=binding_repository,
        assessment_repository=InMemoryRepositoryAssessmentRepository(),
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        governance_service=_FakeGovernanceService(),  # type: ignore[arg-type]
        max_files=100,
        max_depth=10,
        max_source_bytes=1_000_000,
        orchestrator=None,
    )


async def test_links_cross_component_local_imports_as_depends_on_edges(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    service = _service_with_local_imports(seeded_binding_repository)

    assessment = await service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    nodes_by_id = {node.id: node for node in assessment.nodes}
    backend_id = next(n.id for n in assessment.nodes if n.name == "backend")
    shared_id = next(n.id for n in assessment.nodes if n.name == "shared")
    depends_on_edges = [edge for edge in assessment.edges if edge.type == "depends_on"]

    # backend/main.py's "from shared.helper import do_thing" is an
    # unambiguous cross-component match (shared/helper.py) -> reported.
    assert any(
        edge.source == backend_id and edge.target == shared_id for edge in depends_on_edges
    )
    matched_edge = next(
        edge for edge in depends_on_edges if edge.source == backend_id and edge.target == shared_id
    )
    assert matched_edge.confidence == pytest.approx(0.6)

    # backend/main.py's "from utils import local_helper" resolves to
    # backend/utils.py - the SAME component - so it must never appear as a
    # reportable (self-loop) interdependency edge.
    assert not any(
        edge.source == backend_id and edge.target == backend_id for edge in depends_on_edges
    )
    assert nodes_by_id[shared_id].type == "component"


async def test_assess_without_an_orchestrator_skips_the_code_summary_silently(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    service = _service_with_bindings(seeded_binding_repository, orchestrator=None)

    assessment = await service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    assert assessment.code_summary is None
    assert assessment.coverage_gaps == []


async def test_assess_attaches_a_grounded_code_summary_when_the_agent_succeeds(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    envelope = json.dumps(
        {
            "summary": "This repository pairs a React/TypeScript frontend with a "
            "FastAPI backend that exposes a webhook integration.",
            "highlights": ["Frontend uses React", "Backend uses FastAPI"],
            "components": [
                {
                    "component_path": "frontend",
                    "role": "UI layer",
                    "confidence": 0.8,
                    "rationale": "Contains a .tsx file and declares react.",
                },
                {
                    "component_path": "backend",
                    "role": "API layer",
                    "confidence": 0.85,
                    "rationale": "Contains a FastAPI app with a webhook endpoint.",
                },
            ],
        }
    )
    orchestrator = _FakeAgentOrchestrator(responses=[envelope])
    service = _service_with_bindings(seeded_binding_repository, orchestrator=orchestrator)

    assessment = await service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    assert assessment.code_summary is not None
    assert "FastAPI" in assessment.code_summary.summary
    assert len(assessment.code_summary.highlights) == 2
    roles = {item.component_path: item.role for item in assessment.code_summary.component_roles}
    assert roles == {"frontend": "UI layer", "backend": "API layer"}
    assert orchestrator.calls[0]["agent_id"] == "code-analyst"
    assert orchestrator.calls[0]["prompt_id"] == "repository-code-summary-v1"


async def test_code_summary_retries_once_on_a_malformed_response_then_succeeds(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    valid_envelope = json.dumps(
        {"summary": "x" * 400, "highlights": [], "components": []}
    )
    orchestrator = _FakeAgentOrchestrator(responses=["not json at all", valid_envelope])
    service = _service_with_bindings(seeded_binding_repository, orchestrator=orchestrator)

    assessment = await service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    assert assessment.code_summary is not None
    assert len(orchestrator.calls) == 2
    assert orchestrator.calls[1]["variables"]["retry_instruction"] != ""


async def test_code_summary_ignores_a_component_path_not_in_the_evidence(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    envelope = json.dumps(
        {
            "summary": "x" * 400,
            "highlights": [],
            "components": [
                {
                    "component_path": "a-component-that-does-not-exist",
                    "role": "Invented layer",
                    "confidence": 0.9,
                    "rationale": "Fabricated.",
                }
            ],
        }
    )
    orchestrator = _FakeAgentOrchestrator(responses=[envelope])
    service = _service_with_bindings(seeded_binding_repository, orchestrator=orchestrator)

    assessment = await service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    assert assessment.code_summary is not None
    assert assessment.code_summary.component_roles == []


async def test_assess_fails_closed_with_a_coverage_gap_when_foundry_is_unavailable(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    orchestrator = _FakeAgentOrchestrator(raise_error=True)
    service = _service_with_bindings(seeded_binding_repository, orchestrator=orchestrator)

    assessment = await service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    assert assessment.code_summary is None
    assert any(gap.category == "summary_unavailable" for gap in assessment.coverage_gaps)
    # The deterministic graph must still be fully populated even though the
    # LLM-backed summary failed - a Foundry outage never blocks it.
    assert any(node.type == "component" for node in assessment.nodes)


async def test_assess_fails_closed_when_the_agent_keeps_returning_malformed_json(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    orchestrator = _FakeAgentOrchestrator(responses=["not json", "still not json"])
    service = _service_with_bindings(seeded_binding_repository, orchestrator=orchestrator)

    assessment = await service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    assert assessment.code_summary is None
    assert any(gap.category == "summary_unavailable" for gap in assessment.coverage_gaps)
    assert len(orchestrator.calls) == 2


async def _assessed_without_summary(
    binding_repository: InMemoryRepositoryBindingRepository,
) -> tuple[Any, InMemoryRepositoryAssessmentRepository]:
    """Runs a real assess() with no orchestrator (so it never touches the
    code-summary agent call at all), then returns the resulting assessment
    alongside the assessment repository it was persisted to - letting each
    ask() test configure its own independent fake orchestrator/responses
    without any response-pool collision with assess()'s own (skipped)
    code-summary generation."""
    assessment_repository = InMemoryRepositoryAssessmentRepository()
    setup_service = RepositoryAssessmentService(
        client=_FakeGitHubMcpClient(),  # type: ignore[arg-type]
        binding_repository=binding_repository,
        assessment_repository=assessment_repository,
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        governance_service=_FakeGovernanceService(),  # type: ignore[arg-type]
        max_files=100,
        max_depth=10,
        max_source_bytes=1_000_000,
        orchestrator=None,
    )
    assessment = await setup_service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )
    return assessment, assessment_repository


def _service_sharing_assessments(
    *,
    binding_repository: InMemoryRepositoryBindingRepository,
    assessment_repository: InMemoryRepositoryAssessmentRepository,
    orchestrator: Any = None,
) -> RepositoryAssessmentService:
    return RepositoryAssessmentService(
        client=_FakeGitHubMcpClient(),  # type: ignore[arg-type]
        binding_repository=binding_repository,
        assessment_repository=assessment_repository,
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        governance_service=_FakeGovernanceService(),  # type: ignore[arg-type]
        max_files=100,
        max_depth=10,
        max_source_bytes=1_000_000,
        orchestrator=orchestrator,
    )


async def test_ask_answers_a_question_grounded_in_an_existing_assessment(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    assessment, assessment_repository = await _assessed_without_summary(seeded_binding_repository)
    chat_envelope = json.dumps(
        {
            "answer": "The backend component declares a dependency on fastapi.",
            "referenced_paths": ["backend", "backend/main.py"],
        }
    )
    orchestrator = _FakeAgentOrchestrator(responses=[chat_envelope])
    service = _service_sharing_assessments(
        binding_repository=seeded_binding_repository,
        assessment_repository=assessment_repository,
        orchestrator=orchestrator,
    )

    answer = await service.ask(
        session_id="session-1",
        assessment_id=assessment.id,
        requesting_user_id="user-1",
        message="What does the backend depend on?",
        trace_id="trace-2",
    )

    assert answer.answer == "The backend component declares a dependency on fastapi."
    assert "backend" in answer.referenced_paths
    assert "backend/main.py" in answer.referenced_paths
    assert orchestrator.calls[-1]["agent_id"] == "code-analyst"
    assert orchestrator.calls[-1]["prompt_id"] == "repository-code-chat-v1"


async def test_ask_discards_a_referenced_path_that_is_not_in_the_evidence(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    assessment, assessment_repository = await _assessed_without_summary(seeded_binding_repository)
    chat_envelope = json.dumps(
        {"answer": "Some answer.", "referenced_paths": ["a-path-that-does-not-exist.py"]}
    )
    orchestrator = _FakeAgentOrchestrator(responses=[chat_envelope])
    service = _service_sharing_assessments(
        binding_repository=seeded_binding_repository,
        assessment_repository=assessment_repository,
        orchestrator=orchestrator,
    )

    answer = await service.ask(
        session_id="session-1",
        assessment_id=assessment.id,
        requesting_user_id="user-1",
        message="What is this?",
        trace_id="trace-2",
    )

    assert answer.referenced_paths == []


async def test_ask_rejects_a_blank_message(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    assessment, assessment_repository = await _assessed_without_summary(seeded_binding_repository)
    service = _service_sharing_assessments(
        binding_repository=seeded_binding_repository,
        assessment_repository=assessment_repository,
        orchestrator=_FakeAgentOrchestrator(),
    )

    with pytest.raises(RepositoryAssessmentError, match="Describe"):
        await service.ask(
            session_id="session-1",
            assessment_id=assessment.id,
            requesting_user_id="user-1",
            message="   ",
            trace_id="trace-2",
        )


async def test_ask_requires_an_orchestrator_to_be_configured(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    assessment, assessment_repository = await _assessed_without_summary(seeded_binding_repository)
    service = _service_sharing_assessments(
        binding_repository=seeded_binding_repository,
        assessment_repository=assessment_repository,
        orchestrator=None,
    )

    with pytest.raises(RepositoryAssessmentError, match="Foundry"):
        await service.ask(
            session_id="session-1",
            assessment_id=assessment.id,
            requesting_user_id="user-1",
            message="What does this repository do?",
            trace_id="trace-2",
        )


async def test_ask_rejects_an_assessment_id_from_a_different_session(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    assessment, assessment_repository = await _assessed_without_summary(seeded_binding_repository)
    service = _service_sharing_assessments(
        binding_repository=seeded_binding_repository,
        assessment_repository=assessment_repository,
        orchestrator=_FakeAgentOrchestrator(),
    )

    with pytest.raises(RepositoryAssessmentError, match="not found"):
        await service.ask(
            session_id="a-different-session",
            assessment_id=assessment.id,
            requesting_user_id="user-1",
            message="What does this repository do?",
            trace_id="trace-2",
        )


class _FlakyGitHubMcpClient:
    """Mirrors `_FakeGitHubMcpClient`'s layout, but one named file's
    `get_file_contents` call fails a configurable number of times before
    succeeding (or always fails, if `fail_count` exceeds the retry budget)
    - simulating the real, observed GitHub MCP behavior of a transient
    failure on an otherwise well-formed, previously-successful request."""

    endpoint = "https://github.example.test/mcp"

    def __init__(self, *, flaky_path: str, fail_count: int) -> None:
        self._flaky_path = flaky_path
        self._fail_count = fail_count
        self.attempts_for_flaky_path = 0

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name == "get_file_contents"
        path = arguments["path"]
        if path == self._flaky_path:
            self.attempts_for_flaky_path += 1
            if self.attempts_for_flaky_path <= self._fail_count:
                raise GitHubMcpError("Simulated transient GitHub MCP failure.")
        if path == "":
            return _mcp_result(
                [
                    {"path": "README.md", "type": "file"},
                    {"path": "frontend", "type": "dir"},
                    {"path": "backend", "type": "dir"},
                ]
            )
        if path == "frontend":
            return _mcp_result(
                [
                    {"path": "frontend/app.tsx", "type": "file"},
                    {"path": "frontend/package.json", "type": "file"},
                ]
            )
        if path == "backend":
            return _mcp_result(
                [
                    {"path": "backend/main.py", "type": "file"},
                    {"path": "backend/requirements.txt", "type": "file"},
                ]
            )
        if path in _FILES:
            return _mcp_file_result(_FILES[path])
        raise AssertionError(f"Unexpected path: {path}")


def _service_with_flaky_client(
    binding_repository: InMemoryRepositoryBindingRepository, *, client: Any
) -> RepositoryAssessmentService:
    return RepositoryAssessmentService(
        client=client,
        binding_repository=binding_repository,
        assessment_repository=InMemoryRepositoryAssessmentRepository(),
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        governance_service=_FakeGovernanceService(),  # type: ignore[arg-type]
        max_files=100,
        max_depth=10,
        max_source_bytes=1_000_000,
        orchestrator=None,
    )


async def test_assess_recovers_from_a_transient_single_file_read_failure(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    client = _FlakyGitHubMcpClient(flaky_path="backend/main.py", fail_count=1)
    service = _service_with_flaky_client(seeded_binding_repository, client=client)

    assessment = await service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    # Succeeded on retry - no coverage gap, and the file was still analyzed.
    assert assessment.coverage_gaps == []
    assert any(node.name == "main.py" for node in assessment.nodes)
    assert client.attempts_for_flaky_path == 2


class _EmptyInitFileGitHubMcpClient:
    """Mirrors `_FakeGitHubMcpClient`'s layout, but `backend` additionally
    contains a legitimately empty `__init__.py` (a 0-byte marker file, as
    reported by GitHub's own directory listing `size` field) - if
    `get_file_contents` is ever called for it, that is itself the bug this
    test guards against, so it raises instead of returning a fake result."""

    endpoint = "https://github.example.test/mcp"

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name == "get_file_contents"
        path = arguments["path"]
        if path == "":
            return _mcp_result(
                [
                    {"path": "README.md", "type": "file"},
                    {"path": "frontend", "type": "dir"},
                    {"path": "backend", "type": "dir"},
                ]
            )
        if path == "frontend":
            return _mcp_result(
                [
                    {"path": "frontend/app.tsx", "type": "file"},
                    {"path": "frontend/package.json", "type": "file"},
                ]
            )
        if path == "backend":
            return _mcp_result(
                [
                    {"path": "backend/main.py", "type": "file"},
                    {"path": "backend/requirements.txt", "type": "file"},
                    {"path": "backend/__init__.py", "type": "file", "size": 0},
                ]
            )
        if path in _FILES:
            return _mcp_file_result(_FILES[path])
        raise AssertionError(f"get_file_contents must not be called for a known-empty file: {path}")


async def test_assess_treats_a_known_empty_file_as_analyzed_not_a_coverage_gap(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    client = _EmptyInitFileGitHubMcpClient()
    service = _service_with_flaky_client(seeded_binding_repository, client=client)

    assessment = await service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    assert assessment.coverage_gaps == []
    assert any(node.name == "__init__.py" for node in assessment.nodes)


async def test_assess_records_a_gap_and_continues_when_one_file_persistently_fails(
    seeded_binding_repository: InMemoryRepositoryBindingRepository,
) -> None:
    client = _FlakyGitHubMcpClient(flaky_path="backend/main.py", fail_count=10)
    service = _service_with_flaky_client(seeded_binding_repository, client=client)

    assessment = await service.assess(
        session_id="session-1",
        binding_id="binding-1",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    # The whole assessment must still complete - one persistently
    # unreadable file is recorded as a gap, never a fatal error that
    # discards every other file already (or still to be) analyzed.
    assert any(gap.category == "unreadable_content" for gap in assessment.coverage_gaps)
    assert not any(node.name == "main.py" for node in assessment.nodes)
    # The rest of the repository was still analyzed normally.
    assert any(node.name == "app.tsx" for node in assessment.nodes)
