"""Persistence for standards snapshots."""
from __future__ import annotations

import asyncio
from typing import Protocol

from app.repositories.document_store import DocumentStore
from app.standards.models import StandardsSnapshot

_PARTITION_KEY = "standards-snapshots"
_METADATA_FIELDS = {"partitionKey", "recordType", "_rid", "_self", "_etag", "_attachments", "_ts"}


class StandardsRepository(Protocol):
    async def put(self, snapshot: StandardsSnapshot) -> None: ...

    async def get(self, *, snapshot_id: str) -> StandardsSnapshot | None: ...

    async def list_for_session(self, *, session_id: str) -> list[StandardsSnapshot]: ...


class InMemoryStandardsRepository:
    def __init__(self) -> None:
        self._snapshots: dict[str, StandardsSnapshot] = {}
        self._lock = asyncio.Lock()

    async def put(self, snapshot: StandardsSnapshot) -> None:
        async with self._lock:
            self._snapshots[snapshot.id] = snapshot.model_copy(deep=True)

    async def get(self, *, snapshot_id: str) -> StandardsSnapshot | None:
        async with self._lock:
            snapshot = self._snapshots.get(snapshot_id)
            return snapshot.model_copy(deep=True) if snapshot else None

    async def list_for_session(self, *, session_id: str) -> list[StandardsSnapshot]:
        async with self._lock:
            return [
                snapshot.model_copy(deep=True)
                for snapshot in self._snapshots.values()
                if snapshot.session_id == session_id
            ]


class CosmosStandardsRepository:
    def __init__(self, *, store: DocumentStore) -> None:
        self._store = store

    async def put(self, snapshot: StandardsSnapshot) -> None:
        document = snapshot.model_dump(mode="json")
        document.update({"partitionKey": _PARTITION_KEY, "recordType": "standards-snapshot"})
        await self._store.upsert(document)

    async def get(self, *, snapshot_id: str) -> StandardsSnapshot | None:
        document = await self._store.read(
            document_id=snapshot_id,
            partition_key=_PARTITION_KEY,
        )
        if document is None or document.get("recordType") != "standards-snapshot":
            return None
        return StandardsSnapshot.model_validate(
            {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
        )

    async def list_for_session(self, *, session_id: str) -> list[StandardsSnapshot]:
        documents = await self._store.query(
            query=(
                "SELECT * FROM c WHERE c.recordType = @recordType "
                "AND c.session_id = @sessionId ORDER BY c.created_at DESC"
            ),
            parameters=[
                {"name": "@recordType", "value": "standards-snapshot"},
                {"name": "@sessionId", "value": session_id},
            ],
            partition_key=_PARTITION_KEY,
        )
        return [
            StandardsSnapshot.model_validate(
                {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
            )
            for document in documents
        ]

