"""Task-state persistence."""
from __future__ import annotations

import asyncio
from typing import Protocol

from app.phase_tracking.models import PhaseTaskState
from app.repositories.document_store import DocumentStore

_PARTITION_KEY = "phase-task-states"
_METADATA_FIELDS = {"partitionKey", "recordType", "_rid", "_self", "_etag", "_attachments", "_ts"}


class PhaseTaskStateRepository(Protocol):
    async def put(self, state: PhaseTaskState) -> None: ...
    async def list_for_session(self, *, session_id: str) -> list[PhaseTaskState]: ...


class InMemoryPhaseTaskStateRepository:
    def __init__(self) -> None:
        self._records: dict[str, PhaseTaskState] = {}
        self._lock = asyncio.Lock()

    async def put(self, state: PhaseTaskState) -> None:
        async with self._lock:
            self._records[state.id] = state.model_copy(deep=True)

    async def list_for_session(self, *, session_id: str) -> list[PhaseTaskState]:
        async with self._lock:
            return [
                state.model_copy(deep=True)
                for state in self._records.values()
                if state.session_id == session_id
            ]


class CosmosPhaseTaskStateRepository:
    def __init__(self, *, store: DocumentStore) -> None:
        self._store = store

    async def put(self, state: PhaseTaskState) -> None:
        document = state.model_dump(mode="json")
        document.update({"partitionKey": _PARTITION_KEY, "recordType": "phase-task-state"})
        await self._store.upsert(document)

    async def list_for_session(self, *, session_id: str) -> list[PhaseTaskState]:
        documents = await self._store.query(
            query=(
                "SELECT * FROM c WHERE c.recordType = @recordType "
                "AND c.session_id = @sessionId"
            ),
            parameters=[
                {"name": "@recordType", "value": "phase-task-state"},
                {"name": "@sessionId", "value": session_id},
            ],
            partition_key=_PARTITION_KEY,
        )
        return [
            PhaseTaskState.model_validate(
                {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
            )
            for document in documents
        ]

