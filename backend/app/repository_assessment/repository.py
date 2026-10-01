"""Persistence for repository assessments."""
from __future__ import annotations

import asyncio
from typing import Protocol

from app.repositories.document_store import DocumentStore
from app.repository_assessment.models import RepositoryAssessment

_PARTITION_KEY = "repository-assessments"
_METADATA_FIELDS = {"partitionKey", "recordType", "_rid", "_self", "_etag", "_attachments", "_ts"}


class RepositoryAssessmentRepository(Protocol):
    async def put(self, assessment: RepositoryAssessment) -> None: ...

    async def get(self, *, assessment_id: str) -> RepositoryAssessment | None: ...

    async def list_for_session(self, *, session_id: str) -> list[RepositoryAssessment]: ...


class InMemoryRepositoryAssessmentRepository:
    def __init__(self) -> None:
        self._assessments: dict[str, RepositoryAssessment] = {}
        self._lock = asyncio.Lock()

    async def put(self, assessment: RepositoryAssessment) -> None:
        async with self._lock:
            self._assessments[assessment.id] = assessment.model_copy(deep=True)

    async def get(self, *, assessment_id: str) -> RepositoryAssessment | None:
        async with self._lock:
            assessment = self._assessments.get(assessment_id)
            return assessment.model_copy(deep=True) if assessment else None

    async def list_for_session(self, *, session_id: str) -> list[RepositoryAssessment]:
        async with self._lock:
            return [
                assessment.model_copy(deep=True)
                for assessment in self._assessments.values()
                if assessment.session_id == session_id
            ]


class CosmosRepositoryAssessmentRepository:
    def __init__(self, *, store: DocumentStore) -> None:
        self._store = store

    async def put(self, assessment: RepositoryAssessment) -> None:
        document = assessment.model_dump(mode="json")
        document.update(
            {
                "partitionKey": _PARTITION_KEY,
                "recordType": "repository-assessment",
            }
        )
        await self._store.upsert(document)

    async def get(self, *, assessment_id: str) -> RepositoryAssessment | None:
        document = await self._store.read(
            document_id=assessment_id,
            partition_key=_PARTITION_KEY,
        )
        if document is None or document.get("recordType") != "repository-assessment":
            return None
        return RepositoryAssessment.model_validate(
            {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
        )

    async def list_for_session(self, *, session_id: str) -> list[RepositoryAssessment]:
        documents = await self._store.query(
            query=(
                "SELECT * FROM c WHERE c.recordType = @recordType "
                "AND c.session_id = @sessionId ORDER BY c.created_at DESC"
            ),
            parameters=[
                {"name": "@recordType", "value": "repository-assessment"},
                {"name": "@sessionId", "value": session_id},
            ],
            partition_key=_PARTITION_KEY,
        )
        return [
            RepositoryAssessment.model_validate(
                {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
            )
            for document in documents
        ]
