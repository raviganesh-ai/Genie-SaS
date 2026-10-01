"""Persistence for normalized IQ evidence candidates."""
from __future__ import annotations

import asyncio
from typing import Protocol

from app.iq.models import IqEvidenceCandidate
from app.repositories.document_store import DocumentStore

_PARTITION_KEY = "iq-evidence-candidates"
_METADATA_FIELDS = {"partitionKey", "recordType", "_rid", "_self", "_etag", "_attachments", "_ts"}


class IqEvidenceRepository(Protocol):
    async def put(self, candidate: IqEvidenceCandidate) -> None: ...

    async def get(self, *, candidate_id: str) -> IqEvidenceCandidate | None: ...

    async def list_for_session(self, *, session_id: str) -> list[IqEvidenceCandidate]: ...


class InMemoryIqEvidenceRepository:
    def __init__(self) -> None:
        self._candidates: dict[str, IqEvidenceCandidate] = {}
        self._lock = asyncio.Lock()

    async def put(self, candidate: IqEvidenceCandidate) -> None:
        async with self._lock:
            self._candidates[candidate.id] = candidate.model_copy(deep=True)

    async def get(self, *, candidate_id: str) -> IqEvidenceCandidate | None:
        async with self._lock:
            candidate = self._candidates.get(candidate_id)
            return candidate.model_copy(deep=True) if candidate else None

    async def list_for_session(self, *, session_id: str) -> list[IqEvidenceCandidate]:
        async with self._lock:
            return [
                candidate.model_copy(deep=True)
                for candidate in self._candidates.values()
                if candidate.session_id == session_id
            ]


class CosmosIqEvidenceRepository:
    def __init__(self, *, store: DocumentStore) -> None:
        self._store = store

    async def put(self, candidate: IqEvidenceCandidate) -> None:
        document = candidate.model_dump(mode="json")
        document.update({"partitionKey": _PARTITION_KEY, "recordType": "iq-evidence-candidate"})
        await self._store.upsert(document)

    async def get(self, *, candidate_id: str) -> IqEvidenceCandidate | None:
        document = await self._store.read(
            document_id=candidate_id,
            partition_key=_PARTITION_KEY,
        )
        if document is None or document.get("recordType") != "iq-evidence-candidate":
            return None
        return IqEvidenceCandidate.model_validate(
            {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
        )

    async def list_for_session(self, *, session_id: str) -> list[IqEvidenceCandidate]:
        documents = await self._store.query(
            query=(
                "SELECT * FROM c WHERE c.recordType = @recordType "
                "AND c.session_id = @sessionId ORDER BY c.evidence.retrieved_at DESC"
            ),
            parameters=[
                {"name": "@recordType", "value": "iq-evidence-candidate"},
                {"name": "@sessionId", "value": session_id},
            ],
            partition_key=_PARTITION_KEY,
        )
        return [
            IqEvidenceCandidate.model_validate(
                {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
            )
            for document in documents
        ]

