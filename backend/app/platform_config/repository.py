"""Persistence for platform-level reference repositories - deliberately
NOT session-scoped (no session_id/partition-per-session), unlike every
other repository in this codebase. Mirrors app.standards.repository's
Protocol + InMemory + Cosmos pattern."""
from __future__ import annotations

import asyncio
from typing import Protocol

from app.platform_config.models import PlatformReferenceRepository
from app.repositories.document_store import DocumentStore

_PARTITION_KEY = "platform-reference-repositories"
_METADATA_FIELDS = {"partitionKey", "recordType", "_rid", "_self", "_etag", "_attachments", "_ts"}


class PlatformReferenceRepositoryStore(Protocol):
    async def put(self, repository: PlatformReferenceRepository) -> None: ...

    async def get(self, *, repository_id: str) -> PlatformReferenceRepository | None: ...

    async def list_all(self) -> list[PlatformReferenceRepository]: ...

    async def delete(self, *, repository_id: str) -> None: ...


class InMemoryPlatformReferenceRepositoryStore:
    def __init__(self) -> None:
        self._repositories: dict[str, PlatformReferenceRepository] = {}
        self._lock = asyncio.Lock()

    async def put(self, repository: PlatformReferenceRepository) -> None:
        async with self._lock:
            self._repositories[repository.id] = repository.model_copy(deep=True)

    async def get(self, *, repository_id: str) -> PlatformReferenceRepository | None:
        async with self._lock:
            repository = self._repositories.get(repository_id)
            return repository.model_copy(deep=True) if repository else None

    async def list_all(self) -> list[PlatformReferenceRepository]:
        async with self._lock:
            return [repository.model_copy(deep=True) for repository in self._repositories.values()]

    async def delete(self, *, repository_id: str) -> None:
        async with self._lock:
            self._repositories.pop(repository_id, None)


class CosmosPlatformReferenceRepositoryStore:
    def __init__(self, *, store: DocumentStore) -> None:
        self._store = store

    async def put(self, repository: PlatformReferenceRepository) -> None:
        document = repository.model_dump(mode="json")
        document.update({"partitionKey": _PARTITION_KEY, "recordType": "platform-reference-repository"})
        await self._store.upsert(document)

    async def get(self, *, repository_id: str) -> PlatformReferenceRepository | None:
        document = await self._store.read(
            document_id=repository_id,
            partition_key=_PARTITION_KEY,
        )
        if document is None or document.get("recordType") != "platform-reference-repository":
            return None
        return PlatformReferenceRepository.model_validate(
            {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
        )

    async def list_all(self) -> list[PlatformReferenceRepository]:
        documents = await self._store.query(
            query=(
                "SELECT * FROM c WHERE c.recordType = @recordType ORDER BY c.created_at DESC"
            ),
            parameters=[{"name": "@recordType", "value": "platform-reference-repository"}],
            partition_key=_PARTITION_KEY,
        )
        return [
            PlatformReferenceRepository.model_validate(
                {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
            )
            for document in documents
        ]

    async def delete(self, *, repository_id: str) -> None:
        await self._store.delete(document_id=repository_id, partition_key=_PARTITION_KEY)
