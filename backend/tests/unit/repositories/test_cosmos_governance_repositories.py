"""Restart-style tests for durable governance repositories."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.approval_models import ApprovalAuditRecord, ApprovalDecision, ApprovalRequest
from app.models.governance_event import GovernanceEvent
from app.models.recommendation_lineage import RecommendationLineage
from app.repositories.approval_repository import CosmosApprovalRepository
from app.repositories.governance_event_repository import CosmosGovernanceEventRepository
from app.repositories.recommendation_lineage_repository import (
    CosmosRecommendationLineageRepository,
)


class _Store:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], dict[str, Any]] = {}

    async def upsert(self, document: dict[str, Any]) -> None:
        self.documents[(document["partitionKey"], document["id"])] = dict(document)

    async def read(self, *, document_id: str, partition_key: str):
        return self.documents.get((partition_key, document_id))

    async def query(self, *, query, parameters, partition_key):
        del query
        values = {item["name"]: item["value"] for item in parameters}
        return [
            document
            for (key, _), document in self.documents.items()
            if key == partition_key
            and document["recordType"] == values["@recordType"]
            and (
                "@sessionId" not in values
                or document["session_id"] == values["@sessionId"]
            )
            and (
                "@requestId" not in values
                or document["request_id"] == values["@requestId"]
            )
            and (
                "@recommendationId" not in values
                or document["recommendation_id"] == values["@recommendationId"]
            )
        ]


async def test_governance_events_survive_repository_recreation() -> None:
    store = _Store()
    event = GovernanceEvent(
        id="event-1",
        category="tool_request",
        session_id="session-1",
        trace_id="trace-1",
        timestamp=datetime.now(UTC),
    )
    await CosmosGovernanceEventRepository(store=store).append(event)

    assert await CosmosGovernanceEventRepository(store=store).list_for_session(
        session_id="session-1"
    ) == [event]


async def test_approval_state_survives_repository_recreation() -> None:
    store = _Store()
    now = datetime.now(UTC)
    request = ApprovalRequest(
        id="request-1",
        checkpoint_id="approve-architecture",
        session_id="session-1",
        trace_id="trace-1",
        requested_by_agent_id="agent-1",
        subject_type="architecture",
        subject_id="architecture-1",
        requested_at=now,
    )
    decision = ApprovalDecision(
        id="decision-1",
        request_id=request.id,
        decision="approved",
        decided_by="user-1",
        decided_at=now,
    )
    audit = ApprovalAuditRecord(
        id="audit-1",
        request_id=request.id,
        session_id=request.session_id,
        trace_id=request.trace_id,
        event="approved",
        timestamp=now,
        actor="user-1",
    )
    repository = CosmosApprovalRepository(store=store)
    await repository.put_request(request)
    await repository.put_decision(decision)
    await repository.put_audit_record(audit)
    restarted = CosmosApprovalRepository(store=store)

    assert await restarted.get_request(request_id=request.id) == request
    assert await restarted.list_requests_for_session(session_id=request.session_id) == [request]
    assert await restarted.list_decisions_for_request(request_id=request.id) == [decision]
    assert await restarted.list_audit_for_session(session_id=request.session_id) == [audit]


async def test_recommendation_lineage_survives_repository_recreation() -> None:
    store = _Store()
    lineage = RecommendationLineage(
        id="lineage-1",
        session_id="session-1",
        trace_id="trace-1",
        recommendation_id="recommendation-1",
        recommendation_type="modernization",
        produced_by_agent_id="agent-1",
        produced_by_agent_version="1",
        confidence_score=0.9,
        timestamp=datetime.now(UTC),
    )
    await CosmosRecommendationLineageRepository(store=store).put(lineage)
    restarted = CosmosRecommendationLineageRepository(store=store)

    assert await restarted.get(
        session_id=lineage.session_id,
        recommendation_id=lineage.recommendation_id,
    ) == lineage
    assert await restarted.list_for_session(session_id=lineage.session_id) == [lineage]
