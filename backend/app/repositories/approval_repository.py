"""Approval framework repository abstraction.

Isolated behind a protocol so the storage backend (in-memory for Phase 5;
Cosmos DB / Azure SQL for a later phase, per ``Settings.lineage_store_backend``)
can change without touching ``ApprovalService`` or any caller.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

from app.models.approval_models import ApprovalAuditRecord, ApprovalDecision, ApprovalRequest

if TYPE_CHECKING:
    from app.repositories.document_store import DocumentStore

_PARTITION_KEY = "approval-records"
_METADATA_FIELDS = {"partitionKey", "recordType", "_rid", "_self", "_etag", "_attachments", "_ts"}


class ApprovalRepository(Protocol):
    """Storage for approval requests, decisions, and audit records."""

    async def put_request(self, request: ApprovalRequest) -> None:
        """Insert or replace a request by its id."""
        ...

    async def get_request(self, *, request_id: str) -> ApprovalRequest | None:
        """Fetch a single request, or ``None`` if it does not exist."""
        ...

    async def list_requests_for_session(self, *, session_id: str) -> list[ApprovalRequest]:
        """List every request within ``session_id``."""
        ...

    async def put_decision(self, decision: ApprovalDecision) -> None:
        """Persist a single approval decision."""
        ...

    async def list_decisions_for_request(self, *, request_id: str) -> list[ApprovalDecision]:
        """List every decision recorded for ``request_id``."""
        ...

    async def put_audit_record(self, record: ApprovalAuditRecord) -> None:
        """Persist a single approval audit record."""
        ...

    async def list_audit_for_session(self, *, session_id: str) -> list[ApprovalAuditRecord]:
        """List every audit record within ``session_id``, in insertion order."""
        ...


class InMemoryApprovalRepository:
    """Process-local ``ApprovalRepository`` for local development and tests.

    Not suitable for production (state is not durable or shared across
    instances); production must configure a real backend (see
    ``Settings.lineage_store_backend``).
    """

    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}
        self._decisions: list[ApprovalDecision] = []
        self._audit_records: list[ApprovalAuditRecord] = []
        self._lock = asyncio.Lock()

    async def put_request(self, request: ApprovalRequest) -> None:
        async with self._lock:
            self._requests[request.id] = request

    async def get_request(self, *, request_id: str) -> ApprovalRequest | None:
        async with self._lock:
            return self._requests.get(request_id)

    async def list_requests_for_session(self, *, session_id: str) -> list[ApprovalRequest]:
        async with self._lock:
            return [
                request for request in self._requests.values() if request.session_id == session_id
            ]

    async def put_decision(self, decision: ApprovalDecision) -> None:
        async with self._lock:
            self._decisions.append(decision)

    async def list_decisions_for_request(self, *, request_id: str) -> list[ApprovalDecision]:
        async with self._lock:
            return [
                decision for decision in self._decisions if decision.request_id == request_id
            ]

    async def put_audit_record(self, record: ApprovalAuditRecord) -> None:
        async with self._lock:
            self._audit_records.append(record)

    async def list_audit_for_session(self, *, session_id: str) -> list[ApprovalAuditRecord]:
        async with self._lock:
            return [record for record in self._audit_records if record.session_id == session_id]


class CosmosApprovalRepository:
    """Approval requests, decisions, and audits persisted in Cosmos DB."""

    def __init__(self, *, store: DocumentStore) -> None:
        self._store = store

    async def put_request(self, request: ApprovalRequest) -> None:
        await self._put(request.model_dump(mode="json"), "approval-request")

    async def get_request(self, *, request_id: str) -> ApprovalRequest | None:
        document = await self._store.read(
            document_id=request_id, partition_key=_PARTITION_KEY
        )
        if document is None or document.get("recordType") != "approval-request":
            return None
        return ApprovalRequest.model_validate(self._payload(document))

    async def list_requests_for_session(self, *, session_id: str) -> list[ApprovalRequest]:
        return [
            ApprovalRequest.model_validate(self._payload(document))
            for document in await self._query(
                "approval-request", "c.session_id = @sessionId", "@sessionId", session_id
            )
        ]

    async def put_decision(self, decision: ApprovalDecision) -> None:
        await self._put(decision.model_dump(mode="json"), "approval-decision")

    async def list_decisions_for_request(self, *, request_id: str) -> list[ApprovalDecision]:
        return [
            ApprovalDecision.model_validate(self._payload(document))
            for document in await self._query(
                "approval-decision", "c.request_id = @requestId", "@requestId", request_id
            )
        ]

    async def put_audit_record(self, record: ApprovalAuditRecord) -> None:
        await self._put(record.model_dump(mode="json"), "approval-audit")

    async def list_audit_for_session(self, *, session_id: str) -> list[ApprovalAuditRecord]:
        return [
            ApprovalAuditRecord.model_validate(self._payload(document))
            for document in await self._query(
                "approval-audit", "c.session_id = @sessionId", "@sessionId", session_id
            )
        ]

    async def _put(self, document: dict[str, object], record_type: str) -> None:
        document.update({"partitionKey": _PARTITION_KEY, "recordType": record_type})
        await self._store.upsert(document)

    async def _query(
        self, record_type: str, predicate: str, parameter_name: str, value: str
    ) -> list[dict[str, object]]:
        return await self._store.query(
            query=(
                f"SELECT * FROM c WHERE c.recordType = @recordType AND {predicate}"
            ),
            parameters=[
                {"name": "@recordType", "value": record_type},
                {"name": parameter_name, "value": value},
            ],
            partition_key=_PARTITION_KEY,
        )

    @staticmethod
    def _payload(document: dict[str, object]) -> dict[str, object]:
        return {
            key: value for key, value in document.items() if key not in _METADATA_FIELDS
        }
