"""Persistence for modernization plans."""
from __future__ import annotations

import asyncio
from typing import Protocol

from app.modernization.models import ModernizationPlan
from app.repositories.document_store import DocumentStore

_PARTITION_KEY = "modernization-plans"
_METADATA_FIELDS = {"partitionKey", "recordType", "_rid", "_self", "_etag", "_attachments", "_ts"}


class ModernizationPlanRepository(Protocol):
    async def put(self, plan: ModernizationPlan) -> None: ...

    async def get(self, *, plan_id: str) -> ModernizationPlan | None: ...

    async def list_for_session(self, *, session_id: str) -> list[ModernizationPlan]: ...


class InMemoryModernizationPlanRepository:
    def __init__(self) -> None:
        self._plans: dict[str, ModernizationPlan] = {}
        self._lock = asyncio.Lock()

    async def put(self, plan: ModernizationPlan) -> None:
        async with self._lock:
            self._plans[plan.id] = plan.model_copy(deep=True)

    async def get(self, *, plan_id: str) -> ModernizationPlan | None:
        async with self._lock:
            plan = self._plans.get(plan_id)
            return plan.model_copy(deep=True) if plan else None

    async def list_for_session(self, *, session_id: str) -> list[ModernizationPlan]:
        async with self._lock:
            return [
                plan.model_copy(deep=True)
                for plan in self._plans.values()
                if plan.session_id == session_id
            ]


class CosmosModernizationPlanRepository:
    def __init__(self, *, store: DocumentStore) -> None:
        self._store = store

    async def put(self, plan: ModernizationPlan) -> None:
        document = plan.model_dump(mode="json")
        document.update({"partitionKey": _PARTITION_KEY, "recordType": "modernization-plan"})
        await self._store.upsert(document)

    async def get(self, *, plan_id: str) -> ModernizationPlan | None:
        document = await self._store.read(document_id=plan_id, partition_key=_PARTITION_KEY)
        if document is None or document.get("recordType") != "modernization-plan":
            return None
        return ModernizationPlan.model_validate(
            {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
        )

    async def list_for_session(self, *, session_id: str) -> list[ModernizationPlan]:
        documents = await self._store.query(
            query=(
                "SELECT * FROM c WHERE c.recordType = @recordType "
                "AND c.session_id = @sessionId ORDER BY c.created_at DESC"
            ),
            parameters=[
                {"name": "@recordType", "value": "modernization-plan"},
                {"name": "@sessionId", "value": session_id},
            ],
            partition_key=_PARTITION_KEY,
        )
        return [
            ModernizationPlan.model_validate(
                {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
            )
            for document in documents
        ]

