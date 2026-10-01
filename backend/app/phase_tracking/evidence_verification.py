"""Provider-backed phase evidence verification."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import BaseModel, ConfigDict

from app.repository_connections.github_mcp_client import GitHubMcpClient, GitHubMcpError
from app.repository_connections.repository import RepositoryBindingRepository


class EvidenceVerificationError(RuntimeError):
    """Raised when phase evidence cannot be verified with its provider."""


class AccessToken(Protocol):
    token: str


class AzureTokenCredential(Protocol):
    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken: ...


class EvidenceVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    reference: str
    verified_at: datetime


class EvidenceVerificationService:
    def __init__(
        self,
        *,
        github_client: GitHubMcpClient | None,
        repository_binding_repository: RepositoryBindingRepository,
        azure_credential: AzureTokenCredential,
        azure_subscription_id: str | None,
        timeout_seconds: float = 30,
    ) -> None:
        self._github_client = github_client
        self._binding_repository = repository_binding_repository
        self._azure_credential = azure_credential
        self._azure_subscription_id = azure_subscription_id
        self._timeout_seconds = timeout_seconds

    async def verify(self, *, uri: str, session_id: str) -> EvidenceVerification:
        parsed = urlparse(uri)
        if parsed.scheme == "github":
            return await self._verify_github(parsed)
        if parsed.scheme == "genie":
            return await self._verify_genie(parsed, session_id=session_id)
        if parsed.scheme == "https" and parsed.hostname == "management.azure.com":
            return await self._verify_azure(parsed)
        raise EvidenceVerificationError(
            "Evidence URI must identify GitHub, Genie, or Azure Resource Manager evidence."
        )

    async def _verify_github(self, parsed: Any) -> EvidenceVerification:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 3 or parts[1] != "commit":
            raise EvidenceVerificationError(
                "GitHub evidence must use github://owner/repository/commit/<40-character-sha>."
            )
        owner = parsed.netloc
        repository, _, commit = parts
        if not owner or len(commit) != 40 or any(char not in "0123456789abcdefABCDEF" for char in commit):
            raise EvidenceVerificationError("GitHub commit evidence is malformed.")
        if self._github_client is None:
            raise EvidenceVerificationError("GitHub MCP evidence verification is unavailable.")
        try:
            raw = GitHubMcpClient.tool_json(
                await self._github_client.call_tool(
                    "get_commit",
                    {"owner": owner, "repo": repository, "sha": commit},
                )
            )
        except GitHubMcpError as exc:
            raise EvidenceVerificationError("GitHub commit evidence could not be verified.") from exc
        observed_sha = raw.get("sha") if isinstance(raw, dict) else None
        if not isinstance(observed_sha, str) or observed_sha.casefold() != commit.casefold():
            raise EvidenceVerificationError("GitHub returned a different commit than requested.")
        return self._result("github", f"{owner}/{repository}@{observed_sha}")

    async def _verify_genie(self, parsed: Any, *, session_id: str) -> EvidenceVerification:
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.netloc != "repository-bindings" or len(parts) != 1:
            raise EvidenceVerificationError(
                "Genie evidence must use genie://repository-bindings/<binding-id>."
            )
        binding = await self._binding_repository.get(binding_id=parts[0])
        if binding is None or binding.session_id != session_id:
            raise EvidenceVerificationError(
                "The repository binding does not exist in this Genie session."
            )
        return self._result("genie", f"repository-binding:{binding.id}")

    async def _verify_azure(self, parsed: Any) -> EvidenceVerification:
        resource_id = parsed.path
        query = parse_qs(parsed.query)
        api_version = query.get("api-version", [None])[0]
        if not resource_id.startswith("/subscriptions/") or not api_version:
            raise EvidenceVerificationError(
                "Azure evidence must include an ARM resource ID and api-version."
            )
        segments = resource_id.split("/")
        subscription_id = segments[2] if len(segments) > 2 else ""
        if (
            not self._azure_subscription_id
            or subscription_id.casefold() != self._azure_subscription_id.casefold()
        ):
            raise EvidenceVerificationError(
                "Azure evidence is outside the configured Genie subscription."
            )
        token = await self._azure_credential.get_token(
            "https://management.azure.com/.default"
        )
        url = f"https://management.azure.com{resource_id}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(
                    url,
                    params={"api-version": api_version},
                    headers={"Authorization": f"Bearer {token.token}"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EvidenceVerificationError(
                "Azure Resource Manager evidence could not be verified."
            ) from exc
        observed_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(observed_id, str) or observed_id.casefold() != resource_id.casefold():
            raise EvidenceVerificationError("Azure returned a different resource than requested.")
        return self._result("azure", observed_id)

    @staticmethod
    def _result(provider: str, reference: str) -> EvidenceVerification:
        return EvidenceVerification(
            provider=provider,
            reference=reference,
            verified_at=datetime.now(UTC),
        )
