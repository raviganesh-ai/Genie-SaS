"""Platform-level reference repository configuration routes - deliberately
NOT nested under /sessions/{session_id}, since this configuration applies
across all of Genie-SaS (see app.platform_config.models' docstring)."""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_platform_config_service
from app.platform_config.models import PlatformReferencePurpose, PlatformReferenceRepository
from app.platform_config.service import PlatformConfigService
from app.repository_connections.models import GitHubRepositorySummary
from app.security.auth_models import AuthenticatedUser
from app.security.dependencies import get_current_user

router = APIRouter(prefix="/platform-config/reference-repositories", tags=["platform-config"])


class AddPlatformReferenceRepositoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: GitHubRepositorySummary
    purpose: PlatformReferencePurpose
    requested_ref: str = Field(min_length=1)
    included_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)


@router.get("")
async def list_platform_reference_repositories(
    purpose: PlatformReferencePurpose | None = None,
    _: AuthenticatedUser = Depends(get_current_user),
    service: PlatformConfigService = Depends(get_platform_config_service),
) -> list[PlatformReferenceRepository]:
    return await service.list_repositories(purpose=purpose)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_platform_reference_repository(
    body: AddPlatformReferenceRepositoryRequest,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: PlatformConfigService = Depends(get_platform_config_service),
) -> PlatformReferenceRepository:
    return await service.add_repository(
        repository=body.repository,
        purpose=body.purpose,
        requested_ref=body.requested_ref,
        included_paths=body.included_paths,
        excluded_paths=body.excluded_paths,
        requesting_user_id=user.user_id,
        trace_id=x_correlation_id or str(uuid4()),
    )


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_platform_reference_repository(
    repository_id: str,
    x_correlation_id: str | None = Header(default=None),
    _: AuthenticatedUser = Depends(get_current_user),
    service: PlatformConfigService = Depends(get_platform_config_service),
) -> None:
    await service.remove_repository(
        repository_id=repository_id,
        trace_id=x_correlation_id or str(uuid4()),
    )
