"""Persistence for modernization deployment attempts (see
app.modernization.deployment_service.ModernizationDeploymentService) -
mirrors app.modernization.repository's exact pattern for the plan
repository."""
from __future__ import annotations

import asyncio
from typing import Protocol

from app.modernization.models import ModernizationDeployment
from app.repositories.document_store import DocumentStore

_PARTITION_KEY = "modernization-deployments"
_METADATA_FIELDS = {"partitionKey", "recordType", "_rid", "_self", "_etag", "_attachments", "_ts"}


class ModernizationDeploymentRepository(Protocol):
    async def put(self, deployment: ModernizationDeployment) -> None: ...

    async def get(self, *, deployment_id: str) -> ModernizationDeployment | None: ...

    async def list_for_plan(self, *, plan_id: str) -> list[ModernizationDeployment]: ...


class InMemoryModernizationDeploymentRepository:
    def __init__(self) -> None:
        self._deployments: dict[str, ModernizationDeployment] = {}
        self._lock = asyncio.Lock()

    async def put(self, deployment: ModernizationDeployment) -> None:
        async with self._lock:
            self._deployments[deployment.id] = deployment.model_copy(deep=True)

    async def get(self, *, deployment_id: str) -> ModernizationDeployment | None:
        async with self._lock:
            deployment = self._deployments.get(deployment_id)
            return deployment.model_copy(deep=True) if deployment else None

    async def list_for_plan(self, *, plan_id: str) -> list[ModernizationDeployment]:
        async with self._lock:
            return sorted(
                (
                    deployment.model_copy(deep=True)
                    for deployment in self._deployments.values()
                    if deployment.plan_id == plan_id
                ),
                key=lambda deployment: deployment.created_at,
                reverse=True,
            )


class CosmosModernizationDeploymentRepository:
    def __init__(self, *, store: DocumentStore) -> None:
        self._store = store

    async def put(self, deployment: ModernizationDeployment) -> None:
        document = deployment.model_dump(mode="json")
        document.update(
            {"partitionKey": _PARTITION_KEY, "recordType": "modernization-deployment"}
        )
        await self._store.upsert(document)

    async def get(self, *, deployment_id: str) -> ModernizationDeployment | None:
        document = await self._store.read(document_id=deployment_id, partition_key=_PARTITION_KEY)
        if document is None or document.get("recordType") != "modernization-deployment":
            return None
        return ModernizationDeployment.model_validate(
            {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
        )

    async def list_for_plan(self, *, plan_id: str) -> list[ModernizationDeployment]:
        documents = await self._store.query(
            query=(
                "SELECT * FROM c WHERE c.recordType = @recordType "
                "AND c.plan_id = @planId ORDER BY c.created_at DESC"
            ),
            parameters=[
                {"name": "@recordType", "value": "modernization-deployment"},
                {"name": "@planId", "value": plan_id},
            ],
            partition_key=_PARTITION_KEY,
        )
        return [
            ModernizationDeployment.model_validate(
                {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
            )
            for document in documents
        ]
