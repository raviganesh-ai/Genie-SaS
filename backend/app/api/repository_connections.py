"""Authenticated GitHub MCP discovery and repository-purpose binding routes."""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_repository_connection_service
from app.repository_connections.models import (
    GitHubMcpConnectionStatus,
    GitHubRepositoryPage,
    GitHubRepositorySummary,
    RepositoryPurpose,
    RepositoryPurposeBinding,
)
from app.repository_connections.service import RepositoryConnectionService
from app.security.auth_models import AuthenticatedUser
from app.security.dependencies import get_current_user

router = APIRouter(tags=["repository-connections"])


class CreateRepositoryBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: GitHubRepositorySummary
    purpose: RepositoryPurpose
    requested_ref: str = Field(min_length=1)
    included_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)


@router.get("/repository-connections/github/status")
async def github_mcp_status(
    _: AuthenticatedUser = Depends(get_current_user),
    service: RepositoryConnectionService = Depends(get_repository_connection_service),
) -> GitHubMcpConnectionStatus:
    return await service.connection_status()


@router.post("/repository-connections/github/connect")
async def connect_github_mcp(
    _: AuthenticatedUser = Depends(get_current_user),
    service: RepositoryConnectionService = Depends(get_repository_connection_service),
) -> GitHubMcpConnectionStatus:
    return await service.connect()


@router.get("/repository-connections/github/repositories")
async def list_github_repositories(
    query: str | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    _: AuthenticatedUser = Depends(get_current_user),
    service: RepositoryConnectionService = Depends(get_repository_connection_service),
) -> GitHubRepositoryPage:
    return await service.list_repositories(query=query, page=page, per_page=per_page)


@router.get("/sessions/{session_id}/repository-bindings")
async def list_repository_bindings(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: RepositoryConnectionService = Depends(get_repository_connection_service),
) -> list[RepositoryPurposeBinding]:
    return await service.list_bindings(
        session_id=session_id, requesting_user_id=user.user_id
    )


@router.post(
    "/sessions/{session_id}/repository-bindings",
    status_code=status.HTTP_201_CREATED,
)
async def create_repository_binding(
    session_id: str,
    body: CreateRepositoryBindingRequest,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: RepositoryConnectionService = Depends(get_repository_connection_service),
) -> RepositoryPurposeBinding:
    return await service.bind_repository(
        session_id=session_id,
        requesting_user_id=user.user_id,
        repository=body.repository,
        purpose=body.purpose,
        requested_ref=body.requested_ref,
        included_paths=body.included_paths,
        excluded_paths=body.excluded_paths,
        trace_id=x_correlation_id or str(uuid4()),
    )
