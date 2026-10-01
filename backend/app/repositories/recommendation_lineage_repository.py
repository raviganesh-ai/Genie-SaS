"""Recommendation lineage repository abstraction.

Isolated behind a protocol so the storage backend (in-memory for Phase 5;
Cosmos DB / Azure SQL for a later phase, per ``Settings.lineage_store_backend``)
can change without touching ``RecommendationLineageService`` or any caller.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

from app.models.recommendation_lineage import RecommendationLineage

if TYPE_CHECKING:
    from app.repositories.document_store import DocumentStore

_PARTITION_KEY = "recommendation-lineage"
_METADATA_FIELDS = {"partitionKey", "recordType", "_rid", "_self", "_etag", "_attachments", "_ts"}


class RecommendationLineageRepository(Protocol):
    """Session-scoped storage for recommendation lineage records."""

    async def put(self, lineage: RecommendationLineage) -> None:
        """Insert or replace a record by its id."""
        ...

    async def get(
        self, *, session_id: str, recommendation_id: str
    ) -> RecommendationLineage | None:
        """Fetch the lineage for a single recommendation, if any."""
        ...

    async def list_for_session(self, *, session_id: str) -> list[RecommendationLineage]:
        """List every recommendation lineage record within ``session_id``."""
        ...


class InMemoryRecommendationLineageRepository:
    """Process-local ``RecommendationLineageRepository`` for local development and tests.

    Not suitable for production (state is not durable or shared across
    instances); production must configure a real backend (see
    ``Settings.lineage_store_backend``).
    """

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], RecommendationLineage] = {}
        self._lock = asyncio.Lock()

    async def put(self, lineage: RecommendationLineage) -> None:
        async with self._lock:
            self._records[(lineage.session_id, lineage.recommendation_id)] = lineage

    async def get(
        self, *, session_id: str, recommendation_id: str
    ) -> RecommendationLineage | None:
        async with self._lock:
            return self._records.get((session_id, recommendation_id))

    async def list_for_session(self, *, session_id: str) -> list[RecommendationLineage]:
        async with self._lock:
            return [
                record
                for (rec_session_id, _), record in self._records.items()
                if rec_session_id == session_id
            ]


class CosmosRecommendationLineageRepository:
    """Recommendation lineage persisted through managed-identity Cosmos access."""

    def __init__(self, *, store: DocumentStore) -> None:
        self._store = store

    async def put(self, lineage: RecommendationLineage) -> None:
        document = lineage.model_dump(mode="json")
        document.update(
            {"partitionKey": _PARTITION_KEY, "recordType": "recommendation-lineage"}
        )
        await self._store.upsert(document)

    async def get(
        self, *, session_id: str, recommendation_id: str
    ) -> RecommendationLineage | None:
        documents = await self._store.query(
            query=(
                "SELECT * FROM c WHERE c.recordType = @recordType "
                "AND c.session_id = @sessionId "
                "AND c.recommendation_id = @recommendationId"
            ),
            parameters=[
                {"name": "@recordType", "value": "recommendation-lineage"},
                {"name": "@sessionId", "value": session_id},
                {"name": "@recommendationId", "value": recommendation_id},
            ],
            partition_key=_PARTITION_KEY,
        )
        if not documents:
            return None
        return RecommendationLineage.model_validate(self._payload(documents[0]))

    async def list_for_session(self, *, session_id: str) -> list[RecommendationLineage]:
        documents = await self._store.query(
            query=(
                "SELECT * FROM c WHERE c.recordType = @recordType "
                "AND c.session_id = @sessionId ORDER BY c.timestamp"
            ),
            parameters=[
                {"name": "@recordType", "value": "recommendation-lineage"},
                {"name": "@sessionId", "value": session_id},
            ],
            partition_key=_PARTITION_KEY,
        )
        return [
            RecommendationLineage.model_validate(self._payload(document))
            for document in documents
        ]

    @staticmethod
    def _payload(document: dict[str, object]) -> dict[str, object]:
        return {
            key: value for key, value in document.items() if key not in _METADATA_FIELDS
        }
