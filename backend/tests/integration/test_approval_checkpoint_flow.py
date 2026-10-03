"""Integration tests for the approval checkpoint flow (pause / block / proceed)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models.workflow_models import WorkflowStepInput
from ._orchestration_helpers import create_test_agent_orchestrator


@pytest.fixture
def orchestrator(tmp_path: Path):
    return create_test_agent_orchestrator(tmp_path / "config")


def _step_inputs() -> dict[str, WorkflowStepInput]:
    return {
        "step-a": WorkflowStepInput(step_id="step-a", variables={"x": "1"}),
        "step-b": WorkflowStepInput(step_id="step-b", variables={"y": "2"}),
    }


async def test_workflow_pauses_at_waiting_for_approval(orchestrator) -> None:
    result = await orchestrator.run_workflow(
        workflow_id="parallel-workflow",
        session_id="session-approval-pause",
        trace_id="trace-1",
        step_inputs=_step_inputs(),
    )

    assert result.status == "waiting_for_approval"
    assert not any(r.step_id == "step-c" for r in result.step_results)


async def test_workflow_completes_once_approval_is_granted(orchestrator) -> None:
    result = await orchestrator.run_workflow(
        workflow_id="parallel-workflow",
        session_id="session-approval-grant",
        trace_id="trace-1",
        step_inputs=_step_inputs(),
    )
    requests = await orchestrator.approval_service.list_requests_for_session(
        "session-approval-grant"
    )
    await orchestrator.approval_service.decide(
        request_id=requests[0].id, decision="approved", decided_by="reviewer-1"
    )

    resumed = await orchestrator.resume_workflow(
        workflow_run_id=result.workflow_run_id,
        session_id="session-approval-grant",
        trace_id="trace-2",
    )

    assert resumed.status == "completed"
    assert any(r.step_id == "step-c" for r in resumed.step_results)


async def test_workflow_blocks_once_approval_is_rejected(orchestrator) -> None:
    result = await orchestrator.run_workflow(
        workflow_id="parallel-workflow",
        session_id="session-approval-reject",
        trace_id="trace-1",
        step_inputs=_step_inputs(),
    )
    requests = await orchestrator.approval_service.list_requests_for_session(
        "session-approval-reject"
    )
    await orchestrator.approval_service.decide(
        request_id=requests[0].id, decision="rejected", decided_by="reviewer-1"
    )

    resumed = await orchestrator.resume_workflow(
        workflow_run_id=result.workflow_run_id,
        session_id="session-approval-reject",
        trace_id="trace-2",
    )

    assert resumed.status == "blocked"
    assert not any(r.step_id == "step-c" for r in resumed.step_results)
