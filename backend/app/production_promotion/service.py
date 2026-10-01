"""Live rehearsal and approval-gated Container Apps traffic promotion."""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.deploy_launch.pipeline_service import DeploymentPipelineService
from app.governance.approval_service import ApprovalService
from app.production_promotion.models import ProductionPromotion
from app.production_promotion.repository import ProductionPromotionRepository
from app.services.session_service import SessionService


class ProductionPromotionError(RuntimeError):
    """Raised when live evidence or production controls are incomplete."""


class ProductionPromotionService:
    def __init__(
        self,
        *,
        subscription_id: str,
        allowed_resource_group: str,
        repository: ProductionPromotionRepository,
        pipeline_service: DeploymentPipelineService,
        session_service: SessionService,
        approval_service: ApprovalService,
        canary_weight_percent: int,
        health_timeout_seconds: float,
    ) -> None:
        self._subscription_id = subscription_id
        self._allowed_resource_group = allowed_resource_group
        self._repository = repository
        self._pipeline_service = pipeline_service
        self._session_service = session_service
        self._approval_service = approval_service
        self._canary_weight_percent = canary_weight_percent
        self._health_timeout_seconds = health_timeout_seconds

    async def create(
        self,
        *,
        session_id: str,
        deployment_run_id: str,
        resource_group_name: str,
        backend_app_name: str,
        health_url: str,
        requesting_user_id: str,
    ) -> ProductionPromotion:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        if resource_group_name != self._allowed_resource_group:
            raise ProductionPromotionError(
                "Production target is outside the configured production resource group."
            )
        if not health_url.lower().startswith("https://"):
            raise ProductionPromotionError("Production health URL must use HTTPS.")
        if urlparse(health_url).path.rstrip("/") != "/health/ready":
            raise ProductionPromotionError(
                "Production rehearsal must use the live /health/ready endpoint."
            )
        await self._validate_target(
            resource_group_name=resource_group_name,
            backend_app_name=backend_app_name,
            health_url=health_url,
        )
        run = self._pipeline_service.get_run(deployment_run_id)
        if run is None or run.session_id != session_id:
            raise ProductionPromotionError("Deployment run was not found for this session.")
        now = datetime.now(UTC)
        promotion = ProductionPromotion(
            id=str(uuid4()),
            session_id=session_id,
            deployment_run_id=deployment_run_id,
            resource_group_name=resource_group_name,
            backend_app_name=backend_app_name,
            health_url=health_url,
            canary_weight_percent=self._canary_weight_percent,
            created_at=now,
            updated_at=now,
        )
        await self._repository.put(promotion)
        return promotion

    async def rehearse(
        self,
        *,
        promotion_id: str,
        session_id: str,
        requesting_user_id: str,
        trace_id: str,
    ) -> ProductionPromotion:
        promotion = await self._owned(promotion_id, requesting_user_id)
        if promotion.session_id != session_id:
            raise ProductionPromotionError("Production promotion was not found for this session.")
        run = self._pipeline_service.get_run(promotion.deployment_run_id)
        if run is None or run.status != "completed":
            raise ProductionPromotionError("Non-production deployment is not completed.")
        if run.fidelity_report is None or run.fidelity_report.status != "passed":
            raise ProductionPromotionError("Live requirement-fidelity evidence did not pass.")
        if run.security_findings_count is None or run.security_findings_count != 0:
            raise ProductionPromotionError("Live security evidence is missing or has findings.")
        if not all(
            (
                run.data_endpoint,
                run.data_database_name,
                run.data_container_name,
                run.data_schema_version,
            )
        ):
            raise ProductionPromotionError("Live data-layer evidence is incomplete.")
        candidate_name, previous_name = await self._resolve_revisions(promotion)
        latency_ms = await self._validate_health(promotion.health_url)
        approval = await self._approval_service.request_approval(
            checkpoint_id="production-promotion-approval",
            session_id=promotion.session_id,
            trace_id=trace_id,
            requested_by_agent_id="release-agent",
            subject_type="production_promotion",
            subject_id=promotion.id,
        )
        updated = promotion.model_copy(
            update={
                "status": "pending_approval",
                "rehearsal_latency_ms": latency_ms,
                "candidate_revision_name": candidate_name,
                "previous_revision_name": previous_name,
                "approval_request_id": approval.id,
                "updated_at": datetime.now(UTC),
            }
        )
        await self._repository.put(updated)
        return updated

    async def promote(
        self,
        *,
        promotion_id: str,
        session_id: str,
        requesting_user_id: str,
    ) -> ProductionPromotion:
        promotion = await self._owned(promotion_id, requesting_user_id)
        if promotion.session_id != session_id:
            raise ProductionPromotionError("Production promotion was not found for this session.")
        if not promotion.approval_request_id:
            raise ProductionPromotionError("Production promotion has no approval request.")
        approval = await self._approval_service.get_request(promotion.approval_request_id)
        if (
            approval is None
            or approval.status != "approved"
            or approval.subject_type != "production_promotion"
            or approval.subject_id != promotion.id
        ):
            raise ProductionPromotionError("Production promotion requires explicit approval.")
        client, traffic_weight = self._container_apps_client()
        revisions = await asyncio.to_thread(
            lambda: list(
                client.container_apps_revisions.list_revisions(
                    promotion.resource_group_name,
                    promotion.backend_app_name,
                )
            )
        )
        healthy_revisions = self._healthy_revisions(revisions)
        if len(healthy_revisions) < 2:
            raise ProductionPromotionError(
                "Canary promotion requires a healthy candidate and rollback revision."
            )
        candidate, previous = healthy_revisions[0], healthy_revisions[1]
        if (
            candidate.name != promotion.candidate_revision_name
            or previous.name != promotion.previous_revision_name
        ):
            await asyncio.to_thread(client.close)
            raise ProductionPromotionError(
                "Production revisions changed after rehearsal; a new rehearsal and approval "
                "are required."
            )
        app = await asyncio.to_thread(
            client.container_apps.get,
            promotion.resource_group_name,
            promotion.backend_app_name,
        )
        canary = promotion.model_copy(
            update={
                "status": "canary",
                "candidate_revision_name": candidate.name,
                "previous_revision_name": previous.name,
                "updated_at": datetime.now(UTC),
            }
        )
        await self._repository.put(canary)
        try:
            app.configuration.ingress.traffic = [
                traffic_weight(
                    revision_name=candidate.name,
                    weight=promotion.canary_weight_percent,
                ),
                traffic_weight(
                    revision_name=previous.name,
                    weight=100 - promotion.canary_weight_percent,
                ),
            ]
            await asyncio.to_thread(
                lambda: client.container_apps.begin_create_or_update(
                    promotion.resource_group_name,
                    promotion.backend_app_name,
                    app,
                ).result()
            )
            await self._validate_health(promotion.health_url)
            app.configuration.ingress.traffic = [
                traffic_weight(revision_name=candidate.name, weight=100)
            ]
            await asyncio.to_thread(
                lambda: client.container_apps.begin_create_or_update(
                    promotion.resource_group_name,
                    promotion.backend_app_name,
                    app,
                ).result()
            )
            await self._validate_health(promotion.health_url)
        except Exception as exc:
            app.configuration.ingress.traffic = [
                traffic_weight(revision_name=previous.name, weight=100)
            ]
            try:
                await asyncio.to_thread(
                    lambda: client.container_apps.begin_create_or_update(
                        promotion.resource_group_name,
                        promotion.backend_app_name,
                        app,
                    ).result()
                )
            except Exception as rollback_exc:
                failed = canary.model_copy(
                    update={
                        "status": "failed",
                        "rollback_detail": (
                            "Automatic rollback failed after validation error: "
                            f"{rollback_exc}"
                        ),
                        "updated_at": datetime.now(UTC),
                    }
                )
                await self._repository.put(failed)
                raise ProductionPromotionError(
                    "Production validation and automatic rollback both failed."
                ) from rollback_exc
            rolled_back = canary.model_copy(
                update={
                    "status": "rolled_back",
                    "rollback_detail": str(exc),
                    "updated_at": datetime.now(UTC),
                }
            )
            await self._repository.put(rolled_back)
            raise ProductionPromotionError(
                "Production health validation failed; traffic was rolled back."
            ) from exc
        finally:
            await asyncio.to_thread(client.close)
        completed = canary.model_copy(
            update={"status": "completed", "updated_at": datetime.now(UTC)}
        )
        await self._repository.put(completed)
        return completed

    async def list_for_session(
        self, *, session_id: str, requesting_user_id: str
    ) -> list[ProductionPromotion]:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        return await self._repository.list_for_session(session_id=session_id)

    async def _owned(
        self, promotion_id: str, requesting_user_id: str
    ) -> ProductionPromotion:
        promotion = await self._repository.get(promotion_id=promotion_id)
        if promotion is None:
            raise ProductionPromotionError("Production promotion was not found.")
        await self._session_service.get_session(
            session_id=promotion.session_id, requesting_user_id=requesting_user_id
        )
        return promotion

    async def _validate_health(self, health_url: str) -> float:
        started = time.perf_counter()
        async with httpx.AsyncClient(
            timeout=self._health_timeout_seconds,
            follow_redirects=False,
        ) as client:
            response = await client.get(health_url)
        response.raise_for_status()
        if response.headers.get("content-type", "").split(";", maxsplit=1)[0] != "application/json":
            raise ProductionPromotionError("Health endpoint did not return JSON.")
        body = response.json()
        if not isinstance(body, dict) or body.get("status") not in {
            "healthy",
            "ok",
            "ready",
        }:
            raise ProductionPromotionError("Health endpoint did not report a healthy status.")
        return (time.perf_counter() - started) * 1000

    async def _validate_target(
        self,
        *,
        resource_group_name: str,
        backend_app_name: str,
        health_url: str,
    ) -> None:
        client, _ = self._container_apps_client()
        try:
            app = await asyncio.to_thread(
                client.container_apps.get,
                resource_group_name,
                backend_app_name,
            )
        finally:
            await asyncio.to_thread(client.close)
        ingress = getattr(getattr(app, "configuration", None), "ingress", None)
        fqdn = getattr(ingress, "fqdn", None)
        if not fqdn or urlparse(health_url).hostname != fqdn:
            raise ProductionPromotionError(
                "Health URL host must match the live production Container App ingress."
            )

    async def _resolve_revisions(
        self, promotion: ProductionPromotion
    ) -> tuple[str, str]:
        client, _ = self._container_apps_client()
        try:
            revisions = await asyncio.to_thread(
                lambda: list(
                    client.container_apps_revisions.list_revisions(
                        promotion.resource_group_name,
                        promotion.backend_app_name,
                    )
                )
            )
        finally:
            await asyncio.to_thread(client.close)
        healthy_revisions = self._healthy_revisions(revisions)
        if len(healthy_revisions) < 2:
            raise ProductionPromotionError(
                "Production rehearsal requires a healthy candidate and rollback revision."
            )
        return healthy_revisions[0].name, healthy_revisions[1].name

    @staticmethod
    def _healthy_revisions(revisions: list[object]) -> list[object]:
        healthy_revisions = [
            revision
            for revision in revisions
            if getattr(revision, "name", None)
            and getattr(getattr(revision, "properties", None), "health_state", None)
            == "Healthy"
        ]
        healthy_revisions.sort(
            key=lambda revision: str(
                getattr(getattr(revision, "properties", None), "created_time", "")
            ),
            reverse=True,
        )
        return healthy_revisions

    def _container_apps_client(self) -> tuple[object, type[object]]:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.appcontainers import ContainerAppsAPIClient
            from azure.mgmt.appcontainers.models import TrafficWeight
        except ImportError as exc:
            raise ProductionPromotionError(
                "Azure Container Apps SDK dependencies are unavailable."
            ) from exc
        return (
            ContainerAppsAPIClient(
                credential=DefaultAzureCredential(),
                subscription_id=self._subscription_id,
            ),
            TrafficWeight,
        )
