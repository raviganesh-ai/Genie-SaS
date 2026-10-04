"""Unit tests for ModernizationService's conversational Q&A (ask) and
plan-refinement flow (generate_plan called again with previous_plan_id +
refinement_notes) - the two pieces that let a user ask questions about an
already-generated plan and regenerate it with feedback without leaving the
Modernize and deliver page, instead of a dead-end "Review in Governance"
link with no way to influence the plan itself."""
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
from app.standards.repository import InMemoryStandardsRepository

_CONFIG_ROOT = Path(__file__).parents[3] / "config" / "workflows"
_COMMIT = "a" * 40

_VALID_PAYLOAD = {
    "summary": "Upgraded the runtime.",
    "rewrite_strategy": "Upgrade in place; no architectural change is required.",
    "proposed_components": [],
    "deployment_plan": ["Merge the draft pull request after review.", "Deploy as usual."],
    "changes": [{"path": "README.md", "content": "Upgraded.", "reason": "evidence-backed"}],
    "validation_commands": ["pytest"],
    "residual_risks": [],
    "rollback": "git revert",
}


class _FakeSessionService:
    async def get_session(self, *, session_id: str, requesting_user_id: str) -> object:
        return object()


class _FakeGovernanceService:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def record_tool_request(self, **request: Any) -> None:
        self.requests.append(request)


class _FakeApproval:
    id = "approval-1"


class _FakeApprovalService:
    async def request_approval(self, **_: Any) -> _FakeApproval:
        return _FakeApproval()


class _ScriptedOrchestrator:
    """Returns each entry of ``responses`` in order (one per call/retry
    attempt), recording the variables passed on every call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
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
        self.calls.append(dict(variables))
        output_text = self._responses.pop(0)
        return AgentExecutionResult(
            agent_id=agent_id,
            output_text=output_text,
            correlation_id=trace_id or "trace-1",
        )


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


async def _build_service(*, orchestrator: _ScriptedOrchestrator) -> ModernizationService:
    binding_repository = InMemoryRepositoryBindingRepository()
    await binding_repository.put(_binding())
    assessment_repository = InMemoryRepositoryAssessmentRepository()
    await assessment_repository.put(_assessment())

    return ModernizationService(
        client=None,
        plan_repository=InMemoryModernizationPlanRepository(),
        binding_repository=binding_repository,
        assessment_repository=assessment_repository,
        standards_repository=InMemoryStandardsRepository(),
        architecture_reference_repository=InMemoryArchitectureReferenceRepository(),
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        orchestrator=orchestrator,  # type: ignore[arg-type]
        approval_service=_FakeApprovalService(),  # type: ignore[arg-type]
        governance_service=_FakeGovernanceService(),  # type: ignore[arg-type]
        capability_catalog=load_modernization_capabilities(_CONFIG_ROOT),
    )


async def _generate(service: ModernizationService, **overrides: Any) -> Any:
    return await service.generate_plan(
        session_id="session-1",
        binding_id="binding-code",
        assessment_id="assessment-1",
        capability_id="runtime_upgrade",
        target="Python 3.12",
        requesting_user_id="user-1",
        trace_id="trace-1",
        **overrides,
    )


async def test_ask_answers_grounded_in_the_plan_and_filters_unknown_referenced_fields() -> None:
    chat_response = json.dumps(
        {
            "answer": "The plan upgrades the runtime to Python 3.12.",
            "referenced_fields": ["summary", "rewrite_strategy", "not_a_real_field"],
        }
    )
    orchestrator = _ScriptedOrchestrator([json.dumps(_VALID_PAYLOAD), chat_response])
    service = await _build_service(orchestrator=orchestrator)
    plan = await _generate(service)

    answer = await service.ask(
        session_id="session-1",
        plan_id=plan.id,
        requesting_user_id="user-1",
        message="What does this plan do?",
        trace_id="trace-2",
    )

    assert answer.answer == "The plan upgrades the runtime to Python 3.12."
    # "not_a_real_field" is not a real ModernizationPlan field and must be
    # dropped rather than surfaced to the user as if it were grounded.
    assert answer.referenced_fields == ["summary", "rewrite_strategy"]


async def test_ask_rejects_an_empty_question() -> None:
    orchestrator = _ScriptedOrchestrator([json.dumps(_VALID_PAYLOAD)])
    service = await _build_service(orchestrator=orchestrator)
    plan = await _generate(service)

    with pytest.raises(ModernizationError, match="Describe what you'd like to know"):
        await service.ask(
            session_id="session-1",
            plan_id=plan.id,
            requesting_user_id="user-1",
            message="   ",
            trace_id="trace-2",
        )


async def test_ask_recovers_from_a_malformed_first_response() -> None:
    chat_response = json.dumps({"answer": "It upgrades the runtime.", "referenced_fields": []})
    orchestrator = _ScriptedOrchestrator(
        [json.dumps(_VALID_PAYLOAD), "not valid json", chat_response]
    )
    service = await _build_service(orchestrator=orchestrator)
    plan = await _generate(service)

    answer = await service.ask(
        session_id="session-1",
        plan_id=plan.id,
        requesting_user_id="user-1",
        message="What does this plan do?",
        trace_id="trace-2",
    )

    assert answer.answer == "It upgrades the runtime."


async def test_ask_rejects_a_plan_from_another_session() -> None:
    orchestrator = _ScriptedOrchestrator([json.dumps(_VALID_PAYLOAD)])
    service = await _build_service(orchestrator=orchestrator)
    plan = await _generate(service)

    with pytest.raises(ModernizationError, match="was not found"):
        await service.ask(
            session_id="a-different-session",
            plan_id=plan.id,
            requesting_user_id="user-1",
            message="What does this plan do?",
            trace_id="trace-2",
        )


async def test_refining_a_plan_passes_the_previous_plan_and_feedback_to_the_agent() -> None:
    refined_payload = {**_VALID_PAYLOAD, "summary": "Upgraded the runtime, keeping X unchanged."}
    orchestrator = _ScriptedOrchestrator(
        [json.dumps(_VALID_PAYLOAD), json.dumps(refined_payload)]
    )
    service = await _build_service(orchestrator=orchestrator)
    original_plan = await _generate(service)

    refined_plan = await _generate(
        service,
        previous_plan_id=original_plan.id,
        refinement_notes="Keep the existing retry behavior unchanged.",
    )

    assert refined_plan.id != original_plan.id
    assert refined_plan.summary == "Upgraded the runtime, keeping X unchanged."
    # The refinement linkage and the user's own feedback must be
    # persisted on the resulting plan (not just passed transiently to the
    # prompt) so the frontend can show a real "what changed" summary even
    # after a page reload - see ModernizationPlan.previous_plan_id.
    assert refined_plan.previous_plan_id == original_plan.id
    assert refined_plan.refinement_notes == "Keep the existing retry behavior unchanged."
    assert original_plan.previous_plan_id is None
    assert original_plan.refinement_notes is None
    # The second call must have actually carried the previous plan's own
    # content and the user's free-text feedback into the prompt, not a
    # silent no-op regeneration.
    second_call_variables = orchestrator.calls[1]
    assert second_call_variables["refinement_notes"] == "Keep the existing retry behavior unchanged."
    assert "Upgraded the runtime." in second_call_variables["previous_plan_json"]
    # The original plan must still exist, independently approvable - a
    # refinement produces an additional plan, never a silent in-place edit.
    all_plans = await service.list_plans(session_id="session-1", requesting_user_id="user-1")
    assert {p.id for p in all_plans} == {original_plan.id, refined_plan.id}


async def test_refining_rejects_a_previous_plan_from_another_session() -> None:
    orchestrator = _ScriptedOrchestrator([json.dumps(_VALID_PAYLOAD)])
    service = await _build_service(orchestrator=orchestrator)
    original_plan = await _generate(service)
    # Simulate a plan belonging to someone else's session by pointing at a
    # fabricated id that was never stored under "session-1".
    foreign_plan_id = "does-not-exist"
    assert foreign_plan_id != original_plan.id

    with pytest.raises(ModernizationError, match="Previous modernization plan was not found"):
        await _generate(service, previous_plan_id=foreign_plan_id)
