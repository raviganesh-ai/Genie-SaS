"""Persistence for production promotion records."""
from __future__ import annotations

import asyncio
from typing import Protocol

from app.production_promotion.models import ProductionPromotion
from app.repositories.document_store import DocumentStore

_PARTITION_KEY = "production-promotions"
_METADATA_FIELDS = {"partitionKey", "recordType", "_rid", "_self", "_etag", "_attachments", "_ts"}


class ProductionPromotionRepository(Protocol):
    async def put(self, promotion: ProductionPromotion) -> None: ...

    async def get(self, *, promotion_id: str) -> ProductionPromotion | None: ...

    async def list_for_session(self, *, session_id: str) -> list[ProductionPromotion]: ...


class InMemoryProductionPromotionRepository:
    def __init__(self) -> None:
        self._records: dict[str, ProductionPromotion] = {}
        self._lock = asyncio.Lock()

    async def put(self, promotion: ProductionPromotion) -> None:
        async with self._lock:
            self._records[promotion.id] = promotion.model_copy(deep=True)

    async def get(self, *, promotion_id: str) -> ProductionPromotion | None:
        async with self._lock:
            promotion = self._records.get(promotion_id)
            return promotion.model_copy(deep=True) if promotion else None

    async def list_for_session(self, *, session_id: str) -> list[ProductionPromotion]:
        async with self._lock:
            return [
                promotion.model_copy(deep=True)
                for promotion in self._records.values()
                if promotion.session_id == session_id
            ]


class CosmosProductionPromotionRepository:
    def __init__(self, *, store: DocumentStore) -> None:
        self._store = store

    async def put(self, promotion: ProductionPromotion) -> None:
        document = promotion.model_dump(mode="json")
        document.update({"partitionKey": _PARTITION_KEY, "recordType": "production-promotion"})
        await self._store.upsert(document)

    async def get(self, *, promotion_id: str) -> ProductionPromotion | None:
        document = await self._store.read(
            document_id=promotion_id,
            partition_key=_PARTITION_KEY,
        )
        if document is None or document.get("recordType") != "production-promotion":
            return None
        return ProductionPromotion.model_validate(
            {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
        )

    async def list_for_session(self, *, session_id: str) -> list[ProductionPromotion]:
        documents = await self._store.query(
            query=(
                "SELECT * FROM c WHERE c.recordType = @recordType "
                "AND c.session_id = @sessionId ORDER BY c.created_at DESC"
            ),
            parameters=[
                {"name": "@recordType", "value": "production-promotion"},
                {"name": "@sessionId", "value": session_id},
            ],
            partition_key=_PARTITION_KEY,
        )
        return [
            ProductionPromotion.model_validate(
                {key: value for key, value in document.items() if key not in _METADATA_FIELDS}
            )
            for document in documents
        ]

