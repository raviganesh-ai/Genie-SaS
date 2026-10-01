"""Persistence for repository-purpose bindings."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

from app.repository_connections.models import RepositoryPurposeBinding

if TYPE_CHECKING:
    from app.repositories.document_store import DocumentStore

_PARTITION_KEY = "repository-bindings"
_METADATA_FIELDS = {"partitionKey", "recordType", "_rid", "_self", "_etag", "_attachments", "_ts"}


class RepositoryBindingRepository(Protocol):
    async def put(self, binding: RepositoryPurposeBinding) -> None: ...

    async def get(self, *, binding_id: str) -> RepositoryPurposeBinding | None: ...

    async def list_for_session(self, *, session_id: str) -> list[RepositoryPurposeBinding]: ...


class InMemoryRepositoryBindingRepository:
    def __init__(self) -> None:
        self._bindings: dict[str, RepositoryPurposeBinding] = {}
        self._lock = asyncio.Lock()

    async def put(self, binding: RepositoryPurposeBinding) -> None:
        async with self._lock:
            self._bindings[binding.id] = binding.model_copy(deep=True)

    async def get(self, *, binding_id: str) -> RepositoryPurposeBinding | None:
        async with self._lock:
            binding = self._bindings.get(binding_id)
            return binding.model_copy(deep=True) if binding is not None else None

    async def list_for_session(self, *, session_id: str) -> list[RepositoryPurposeBinding]:
        async with self._lock:
            return [
                binding.model_copy(deep=True)
                for binding in self._bindings.values()
                if binding.session_id == session_id
            ]


class CosmosRepositoryBindingRepository:
    def __init__(self, *, store: DocumentStore) -> None:
        self._store = store

    async def put(self, binding: RepositoryPurposeBinding) -> None:
        document = binding.model_dump(mode="json")
        document.update(
            {
                "id": binding.id,
                "partitionKey": _PARTITION_KEY,
                "recordType": "repository-binding",
            }
        )
        await self._store.upsert(document)

    async def get(self, *, binding_id: str) -> RepositoryPurposeBinding | None:
        document = await self._store.read(
            document_id=binding_id,
            partition_key=_PARTITION_KEY,
        )
        if document is None or document.get("recordType") != "repository-binding":
            return None
        return RepositoryPurposeBinding.model_validate(
            {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
        )

    async def list_for_session(self, *, session_id: str) -> list[RepositoryPurposeBinding]:
        documents = await self._store.query(
            query=(
                "SELECT * FROM c WHERE c.recordType = @recordType "
                "AND c.session_id = @sessionId ORDER BY c.created_at"
            ),
            parameters=[
                {"name": "@recordType", "value": "repository-binding"},
                {"name": "@sessionId", "value": session_id},
            ],
            partition_key=_PARTITION_KEY,
        )
        return [
            RepositoryPurposeBinding.model_validate(
                {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
            )
            for document in documents
        ]
