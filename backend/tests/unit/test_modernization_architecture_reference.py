"""Unit tests for ModernizationService.generate_plan's optional
architecture-reference behavior - the user-supplied "architecture"-purpose
binding is never required, but when present must actually reach the
Foundry prompt; when absent, the plan must still generate using the
documented fallback text (see app.modernization.service's
_NO_ARCHITECTURE_REFERENCE_TEXT)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.agents.models import AgentExecutionResult
from app.modernization.capabilities import load_modernization_capabilities
from app.modernization.repository import InMemoryModernizationPlanRepository
from app.modernization.service import ModernizationError, ModernizationService
from app.repository_assessment.models import RepositoryAssessment, RepositoryInventory
from app.repository_assessment.repository import InMemoryRepositoryAssessmentRepository
from app.repository_connections.models import RepositoryPurposeBinding
from app.repository_connections.repository import InMemoryRepositoryBindingRepository
from app.standards.architecture_reference_repository import (
    InMemoryArchitectureReferenceRepository,
)
from app.standards.models import ArchitectureReferenceSnapshot, StandardsSnapshot
from app.standards.repository import InMemoryStandardsRepository

_CONFIG_ROOT = Path(__file__).parents[3] / "config" / "workflows"
_COMMIT = "a" * 40


class _FakeSessionService:
    async def get_session(self, *, session_id: str, requesting_user_id: str) -> object:
        return object()


class _FakeGovernanceService:
    async def record_tool_request(self, **_: Any) -> None:
        return None


class _RecordingOrchestrator:
    def __init__(self, generated_summary: str = "Upgraded the runtime.") -> None:
        self.calls: list[dict[str, Any]] = []
        self._generated_summary = generated_summary

    async def execute_agent(
        self,
        *,
        agent_id: str,
        prompt_id: str,
        variables: dict[str, str],
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> AgentExecutionResult:
        self.calls.append(variables)
        payload = {
            "summary": self._generated_summary,
            "rewrite_strategy": "Upgrade in place; no architectural change is required.",
            "proposed_components": [],
            "deployment_plan": ["Merge the draft pull request after review.", "Deploy as usual."],
            "changes": [{"path": "README.md", "content": "Upgraded.", "reason": "evidence-backed"}],
            "validation_commands": ["pytest"],
            "residual_risks": [],
            "rollback": "git revert",
        }
        return AgentExecutionResult(
            agent_id=agent_id,
            output_text=json.dumps(payload),
            correlation_id=trace_id or "trace-1",
        )


class _FakeApproval:
    id = "approval-1"


class _FakeApprovalService:
    async def request_approval(self, **_: Any) -> _FakeApproval:
        return _FakeApproval()


def _binding() -> RepositoryPurposeBinding:
    now = datetime.now(UTC)
    return RepositoryPurposeBinding(
        id="binding-code",
        session_id="session-1",
        owner_user_id="user-1",
        repository_id=1,
        repository_full_name="acme/widgets",
        repository_url="https://github.com/acme/widgets",
        purpose="code",
        requested_ref="main",
        resolved_commit=_COMMIT,
        principal="managed-identity",
        status="approved",
        validated_at=now,
        created_at=now,
    )


def _assessment() -> RepositoryAssessment:
    return RepositoryAssessment(
        id="assessment-1",
        session_id="session-1",
        binding_id="binding-code",
        repository_full_name="acme/widgets",
        commit=_COMMIT,
        inventory=RepositoryInventory(file_count=1, analyzed_file_count=1),
        created_at=datetime.now(UTC),
    )


def _standards_snapshot() -> StandardsSnapshot:
    return StandardsSnapshot(
        id="standards-1",
        session_id="session-1",
        binding_id="binding-standards",
        repository_full_name="acme/standards",
        commit=_COMMIT,
        paths=[],
        content_hashes={},
        rules=[],
        conflicts=[],
        gaps=[],
        created_at=datetime.now(UTC),
    )


def _architecture_reference_snapshot(text: str) -> ArchitectureReferenceSnapshot:
    return ArchitectureReferenceSnapshot(
        id="arch-ref-1",
        session_id="session-1",
        binding_id="binding-architecture",
        repository_full_name="acme/architecture-reference",
        commit=_COMMIT,
        paths=["ARCHITECTURE.md"],
        content_hashes={"ARCHITECTURE.md": "b" * 64},
        combined_reference_text=text,
        gaps=[],
        created_at=datetime.now(UTC),
    )


async def _build_service(
    *, orchestrator: _RecordingOrchestrator
) -> tuple[ModernizationService, InMemoryArchitectureReferenceRepository]:
    binding_repository = InMemoryRepositoryBindingRepository()
    await binding_repository.put(_binding())
    assessment_repository = InMemoryRepositoryAssessmentRepository()
    await assessment_repository.put(_assessment())
    standards_repository = InMemoryStandardsRepository()
    await standards_repository.put(_standards_snapshot())
    architecture_reference_repository = InMemoryArchitectureReferenceRepository()

    service = ModernizationService(
        client=None,
        plan_repository=InMemoryModernizationPlanRepository(),
        binding_repository=binding_repository,
        assessment_repository=assessment_repository,
        standards_repository=standards_repository,
        architecture_reference_repository=architecture_reference_repository,
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        orchestrator=orchestrator,  # type: ignore[arg-type]
        approval_service=_FakeApprovalService(),  # type: ignore[arg-type]
        governance_service=_FakeGovernanceService(),  # type: ignore[arg-type]
        capability_catalog=load_modernization_capabilities(_CONFIG_ROOT),
    )
    return service, architecture_reference_repository


async def test_generate_plan_works_without_any_architecture_reference() -> None:
    orchestrator = _RecordingOrchestrator()
    service, _ = await _build_service(orchestrator=orchestrator)

    plan = await service.generate_plan(
        session_id="session-1",
        binding_id="binding-code",
        assessment_id="assessment-1",
        standards_snapshot_id="standards-1",
        capability_id="runtime_upgrade",
        target="Python 3.12",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )

    assert plan.architecture_reference_snapshot_id is None
    [call] = orchestrator.calls
    assert "none provided" in call["architecture_reference_text"]


async def test_generate_plan_aligns_with_a_supplied_architecture_reference() -> None:
    orchestrator = _RecordingOrchestrator()
    service, architecture_reference_repository = await _build_service(orchestrator=orchestrator)
    await architecture_reference_repository.put(
        _architecture_reference_snapshot("Use a modular monolith with one Postgres database.")
    )

    plan = await service.generate_plan(
        session_id="session-1",
        binding_id="binding-code",
        assessment_id="assessment-1",
        standards_snapshot_id="standards-1",
        capability_id="runtime_upgrade",
        target="Python 3.12",
        requesting_user_id="user-1",
        trace_id="trace-1",
        architecture_reference_snapshot_id="arch-ref-1",
    )

    assert plan.architecture_reference_snapshot_id == "arch-ref-1"
    [call] = orchestrator.calls
    assert "modular monolith" in call["architecture_reference_text"]


async def test_generate_plan_rejects_an_architecture_reference_from_another_session() -> None:
    orchestrator = _RecordingOrchestrator()
    service, architecture_reference_repository = await _build_service(orchestrator=orchestrator)
    foreign_snapshot = _architecture_reference_snapshot("Belongs elsewhere.").model_copy(
        update={"session_id": "session-2"}
    )
    await architecture_reference_repository.put(foreign_snapshot)

    with pytest.raises(ModernizationError, match="Architecture reference snapshot"):
        await service.generate_plan(
            session_id="session-1",
            binding_id="binding-code",
            assessment_id="assessment-1",
            standards_snapshot_id="standards-1",
            capability_id="runtime_upgrade",
            target="Python 3.12",
            requesting_user_id="user-1",
            trace_id="trace-1",
            architecture_reference_snapshot_id="arch-ref-1",
        )
