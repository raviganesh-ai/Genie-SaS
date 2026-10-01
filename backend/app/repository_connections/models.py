"""Strongly typed GitHub MCP repository connection models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RepositoryPurpose = Literal["code", "architecture", "standards"]
RepositoryBindingStatus = Literal["validated", "approved", "expired", "superseded"]


class GitHubMcpConnectionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    connected: bool
    authentication_mode: Literal["administrator_managed_mcp"] = "administrator_managed_mcp"
    account_login: str | None = None
    server_endpoint: str | None = None
    detail: str


class GitHubRepositorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_id: int
    name: str = Field(min_length=1)
    full_name: str = Field(min_length=3)
    description: str = ""
    html_url: str
    private: bool
    archived: bool
    default_branch: str = Field(min_length=1)
    language: str | None = None
    updated_at: datetime | None = None


class GitHubRepositoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repositories: list[GitHubRepositorySummary] = Field(default_factory=list)
    total_count: int = Field(ge=0)
    incomplete_results: bool = False
    page: int = Field(ge=1)
    per_page: int = Field(ge=1, le=100)


class RepositoryPurposeBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    owner_user_id: str = Field(min_length=1)
    repository_id: int
    repository_full_name: str = Field(min_length=3)
    repository_url: str
    purpose: RepositoryPurpose
    requested_ref: str = Field(min_length=1)
    resolved_commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    included_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    principal: str = Field(min_length=1)
    status: RepositoryBindingStatus = "approved"
    validated_at: datetime
    created_at: datetime
