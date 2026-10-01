"""Production rehearsal and staged-promotion routes."""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Header, status
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from app.api.dependencies import get_production_promotion_service
from app.production_promotion.models import ProductionPromotion
from app.production_promotion.service import ProductionPromotionService
from app.security.auth_models import AuthenticatedUser
from app.security.dependencies import get_current_user

router = APIRouter(
    prefix="/sessions/{session_id}/production-promotions",
    tags=["production-promotions"],
)


class CreateProductionPromotionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment_run_id: str = Field(min_length=1)
    resource_group_name: str = Field(min_length=1)
    backend_app_name: str = Field(min_length=1)
    health_url: AnyHttpUrl


@router.get("")
async def list_production_promotions(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: ProductionPromotionService = Depends(get_production_promotion_service),
) -> list[ProductionPromotion]:
    return await service.list_for_session(
        session_id=session_id,
        requesting_user_id=user.user_id,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_production_promotion(
    session_id: str,
    body: CreateProductionPromotionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    service: ProductionPromotionService = Depends(get_production_promotion_service),
) -> ProductionPromotion:
    return await service.create(
        session_id=session_id,
        deployment_run_id=body.deployment_run_id,
        resource_group_name=body.resource_group_name,
        backend_app_name=body.backend_app_name,
        health_url=str(body.health_url),
        requesting_user_id=user.user_id,
    )


@router.post("/{promotion_id}/rehearse")
async def rehearse_production_promotion(
    session_id: str,
    promotion_id: str,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: ProductionPromotionService = Depends(get_production_promotion_service),
) -> ProductionPromotion:
    return await service.rehearse(
        promotion_id=promotion_id,
        session_id=session_id,
        requesting_user_id=user.user_id,
        trace_id=x_correlation_id or str(uuid4()),
    )


@router.post("/{promotion_id}/promote")
async def promote_to_production(
    session_id: str,
    promotion_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: ProductionPromotionService = Depends(get_production_promotion_service),
) -> ProductionPromotion:
    return await service.promote(
        promotion_id=promotion_id,
        session_id=session_id,
        requesting_user_id=user.user_id,
    )
