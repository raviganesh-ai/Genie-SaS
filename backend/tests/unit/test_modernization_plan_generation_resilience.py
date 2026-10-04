"""Unit tests for ModernizationService.generate_plan's resilience to a
malformed/non-JSON-contract Build Agent response - mirrors the same
retry-with-correction pattern already used for the code-analyst agent
(see RepositoryAssessmentService._execute_code_summary) and was added
after reproducing the failure live: the Foundry Build Agent occasionally
wraps its JSON response in Markdown fences (despite being told not to) or
returns a truncated/invalid response, which previously failed the entire
plan generation on the very first attempt with no retry at all."""
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
    async def record_tool_request(self, **_: Any) -> None:
        return None


class _FakeApproval:
    id = "approval-1"


class _FakeApprovalService:
    async def request_approval(self, **_: Any) -> _FakeApproval:
        return _FakeApproval()


class _ScriptedOrchestrator:
    """Returns each entry of ``responses`` in order (one per call/retry
    attempt), recording the variables passed on every call so a test can
    assert the second attempt actually carried a retry_instruction."""

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


async def _build_service(
    *, orchestrator: _ScriptedOrchestrator, pricing_service: Any = None
) -> ModernizationService:
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
        pricing_service=pricing_service,
    )


async def _generate(service: ModernizationService) -> Any:
    return await service.generate_plan(
        session_id="session-1",
        binding_id="binding-code",
        assessment_id="assessment-1",
        capability_id="runtime_upgrade",
        target="Python 3.12",
        requesting_user_id="user-1",
        trace_id="trace-1",
    )


async def test_generate_plan_strips_markdown_fences_from_the_build_agent_response() -> None:
    # Reproduces the exact live failure: the prompt explicitly says "Do not
    # return Markdown fences", but the Build Agent sometimes wraps its JSON
    # response in a ```json ... ``` fence anyway.
    fenced_response = f"```json\n{json.dumps(_VALID_PAYLOAD)}\n```"
    orchestrator = _ScriptedOrchestrator([fenced_response])
    service = await _build_service(orchestrator=orchestrator)

    plan = await _generate(service)

    assert plan.summary == "Upgraded the runtime."
    assert len(orchestrator.calls) == 1


async def test_generate_plan_recovers_from_a_malformed_first_response() -> None:
    orchestrator = _ScriptedOrchestrator(["not valid json at all", json.dumps(_VALID_PAYLOAD)])
    service = await _build_service(orchestrator=orchestrator)

    plan = await _generate(service)

    assert plan.summary == "Upgraded the runtime."
    assert len(orchestrator.calls) == 2
    # The retry attempt must carry a non-empty correction instruction back
    # to the agent, not silently repeat the identical prompt.
    assert orchestrator.calls[0]["retry_instruction"] == ""
    assert orchestrator.calls[1]["retry_instruction"] != ""


async def test_generate_plan_raises_a_clear_error_after_exhausting_retries() -> None:
    orchestrator = _ScriptedOrchestrator(["still not valid json", "also not valid json"])
    service = await _build_service(orchestrator=orchestrator)

    with pytest.raises(ModernizationError, match="invalid modernization plan contract"):
        await _generate(service)

    assert len(orchestrator.calls) == 2


async def test_generate_plan_defaults_to_an_unavailable_cost_estimate_without_a_pricing_service() -> None:
    orchestrator = _ScriptedOrchestrator([json.dumps(_VALID_PAYLOAD)])
    service = await _build_service(orchestrator=orchestrator, pricing_service=None)

    plan = await _generate(service)

    # No pricing service was configured - the plan must still generate
    # successfully (cost estimation is a nice-to-have, not a hard gate),
    # with an honestly-labeled "unavailable" estimate rather than a
    # fabricated number or a missing field.
    assert plan.estimated_cost is not None
    assert plan.estimated_cost.coverage == "unavailable"


async def test_generate_plan_resolves_a_real_cost_estimate_through_the_pricing_service() -> None:
    from app.discovery.models import CostEstimate

    class _FakePricingService:
        def __init__(self) -> None:
            self.received_queries: list[Any] = []

        async def estimate(self, queries: list[Any]) -> CostEstimate:
            self.received_queries = queries
            return CostEstimate(region="eastus", monthly_amount=42.5, coverage="complete")

    payload = {
        **_VALID_PAYLOAD,
        "pricing_queries": [
            {
                "service_name": "Azure App Service",
                "arm_region_name": "eastus",
                "units_per_month": 730,
                "assumption": "One always-on P1v3 instance.",
            }
        ],
    }
    orchestrator = _ScriptedOrchestrator([json.dumps(payload)])
    pricing_service = _FakePricingService()
    service = await _build_service(orchestrator=orchestrator, pricing_service=pricing_service)

    plan = await _generate(service)

    assert plan.estimated_cost is not None
    assert plan.estimated_cost.monthly_amount == 42.5
    assert plan.estimated_cost.coverage == "complete"
    assert len(pricing_service.received_queries) == 1
    assert plan.estimated_cost.is_illustrative is False


async def test_generate_plan_falls_back_to_an_illustrative_estimate_when_pricing_queries_is_empty() -> None:
    from app.discovery.models import CostEstimate

    class _FakePricingService:
        def __init__(self) -> None:
            self.received_queries: list[Any] = []

        async def estimate(self, queries: list[Any]) -> CostEstimate:
            self.received_queries = queries
            return CostEstimate(region="eastus", monthly_amount=12.3, coverage="complete")

    # No pricing_queries (this capability doesn't change hosting costs -
    # see modernization-plan-v1), but the Build Agent still supplied an
    # illustrative baseline for the existing, unchanged stack.
    payload = {
        **_VALID_PAYLOAD,
        "illustrative_pricing_queries": [
            {
                "service_name": "Azure Container Apps",
                "arm_region_name": "eastus",
                "units_per_month": 730,
                "assumption": "One small always-on single-replica container app.",
            }
        ],
    }
    orchestrator = _ScriptedOrchestrator([json.dumps(payload)])
    pricing_service = _FakePricingService()
    service = await _build_service(orchestrator=orchestrator, pricing_service=pricing_service)

    plan = await _generate(service)

    assert plan.estimated_cost is not None
    assert plan.estimated_cost.monthly_amount == 12.3
    assert plan.estimated_cost.is_illustrative is True
    assert len(pricing_service.received_queries) == 1
    assert pricing_service.received_queries[0].assumption == (
        "One small always-on single-replica container app."
    )


async def test_generate_plan_stays_unavailable_when_illustrative_pricing_also_fails_to_resolve() -> None:
    from app.discovery.models import CostEstimate

    class _FakePricingService:
        async def estimate(self, queries: list[Any]) -> CostEstimate:
            return CostEstimate(region="unknown", coverage="unavailable")

    payload = {
        **_VALID_PAYLOAD,
        "illustrative_pricing_queries": [
            {
                "service_name": "Azure Container Apps",
                "arm_region_name": "eastus",
                "units_per_month": 730,
                "assumption": "One small always-on single-replica container app.",
            }
        ],
    }
    orchestrator = _ScriptedOrchestrator([json.dumps(payload)])
    service = await _build_service(orchestrator=orchestrator, pricing_service=_FakePricingService())

    plan = await _generate(service)

    # The real lookup itself failed (e.g. no matching retail price) - must
    # not be mislabeled as a successful illustrative estimate.
    assert plan.estimated_cost is not None
    assert plan.estimated_cost.coverage == "unavailable"
    assert plan.estimated_cost.is_illustrative is False


async def test_generate_plan_builds_the_proposed_component_graph() -> None:
    payload = {
        **_VALID_PAYLOAD,
        "proposed_components": [
            {
                "id": "billing-module",
                "name": "Billing module",
                "responsibility": "Owns invoicing and payment logic.",
                "extracted": False,
                "depends_on": [],
            },
            {
                "id": "notifications-service",
                "name": "Notifications service",
                "responsibility": "Sends transactional emails independently of billing load.",
                "extracted": True,
                "depends_on": ["billing-module"],
            },
        ],
    }
    orchestrator = _ScriptedOrchestrator([json.dumps(payload)])
    service = await _build_service(orchestrator=orchestrator)

    plan = await _generate(service)

    assert len(plan.proposed_components) == 2
    extracted = next(c for c in plan.proposed_components if c.extracted)
    assert extracted.id == "notifications-service"
    assert extracted.depends_on == ["billing-module"]


async def test_generate_plan_rejects_a_proposed_component_depending_on_an_unknown_id() -> None:
    payload = {
        **_VALID_PAYLOAD,
        "proposed_components": [
            {
                "id": "billing-module",
                "name": "Billing module",
                "responsibility": "Owns invoicing and payment logic.",
                "extracted": False,
                "depends_on": ["does-not-exist"],
            },
        ],
    }
    orchestrator = _ScriptedOrchestrator([json.dumps(payload), json.dumps(payload)])
    service = await _build_service(orchestrator=orchestrator)

    with pytest.raises(ModernizationError):
        await _generate(service)
