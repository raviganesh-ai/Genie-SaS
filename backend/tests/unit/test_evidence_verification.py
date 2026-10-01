"""Tests for provider-backed phase evidence verification."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from app.phase_tracking.evidence_verification import (
    EvidenceVerificationError,
    EvidenceVerificationService,
)
from app.repository_connections.models import RepositoryPurposeBinding
from app.repository_connections.repository import InMemoryRepositoryBindingRepository


class _GitHubClient:
    async def call_tool(self, name, arguments):
        assert name == "get_commit"
        value = {"sha": arguments["sha"]}
        return {"content": [{"type": "text", "text": json.dumps(value)}]}


class _AzureCredential:
    async def get_token(self, *scopes, **kwargs):
        assert scopes == ("https://management.azure.com/.default",)
        return SimpleNamespace(token="azure-token")


def _service(
    repository: InMemoryRepositoryBindingRepository | None = None,
) -> EvidenceVerificationService:
    return EvidenceVerificationService(
        github_client=_GitHubClient(),  # type: ignore[arg-type]
        repository_binding_repository=repository or InMemoryRepositoryBindingRepository(),
        azure_credential=_AzureCredential(),
        azure_subscription_id="subscription-1",
    )


async def test_verifies_github_commit_with_mcp() -> None:
    commit = "a" * 40

    result = await _service().verify(
        uri=f"github://owner/repository/commit/{commit}",
        session_id="session-1",
    )

    assert result.provider == "github"
    assert result.reference == f"owner/repository@{commit}"


async def test_verifies_session_owned_genie_binding() -> None:
    repository = InMemoryRepositoryBindingRepository()
    now = datetime.now(UTC)
    await repository.put(
        RepositoryPurposeBinding(
            id="binding-1",
            session_id="session-1",
            owner_user_id="user-1",
            repository_id=1,
            repository_full_name="owner/repository",
            repository_url="https://github.com/owner/repository",
            purpose="code",
            requested_ref="main",
            resolved_commit="a" * 40,
            principal="managed",
            status="approved",
            validated_at=now,
            created_at=now,
        )
    )

    result = await _service(repository).verify(
        uri="genie://repository-bindings/binding-1",
        session_id="session-1",
    )

    assert result.provider == "genie"
    assert result.reference == "repository-binding:binding-1"


async def test_rejects_azure_resource_from_other_subscription() -> None:
    with pytest.raises(EvidenceVerificationError, match="outside"):
        await _service().verify(
            uri=(
                "https://management.azure.com/subscriptions/other/resourceGroups/rg"
                "/providers/Microsoft.App/containerApps/app?api-version=2025-01-01"
            ),
            session_id="session-1",
        )


async def test_verifies_azure_resource_with_managed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_id = (
        "/subscriptions/subscription-1/resourceGroups/rg"
        "/providers/Microsoft.App/containerApps/app"
    )

    async def fake_get(self, url, *, params, headers):
        assert headers["Authorization"] == "Bearer azure-token"
        assert params == {"api-version": "2025-01-01"}
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"id": resource_id},
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await _service().verify(
        uri=f"https://management.azure.com{resource_id}?api-version=2025-01-01",
        session_id="session-1",
    )

    assert result.provider == "azure"
    assert result.reference == resource_id
