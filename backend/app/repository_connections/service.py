"""Application service for live GitHub MCP discovery and repository bindings."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.repository_connections.github_mcp_client import GitHubMcpClient, GitHubMcpError
from app.repository_connections.models import (
    GitHubMcpConnectionStatus,
    GitHubRepositoryPage,
    GitHubRepositorySummary,
    RepositoryPurpose,
    RepositoryPurposeBinding,
)

if TYPE_CHECKING:
    from app.governance.governance_service import GovernanceService
    from app.repository_connections.repository import RepositoryBindingRepository
    from app.services.session_service import SessionService


class RepositoryBindingError(RuntimeError):
    """Raised when live repository discovery or binding validation fails."""


class RepositoryConnectionService:
    def __init__(
        self,
        *,
        client: GitHubMcpClient | None,
        repository: RepositoryBindingRepository,
        session_service: SessionService,
        governance_service: GovernanceService,
    ) -> None:
        self._client = client
        self._repository = repository
        self._session_service = session_service
        self._governance_service = governance_service

    async def connection_status(self) -> GitHubMcpConnectionStatus:
        if self._client is None:
            return GitHubMcpConnectionStatus(
                configured=False,
                connected=False,
                detail="GitHub MCP is not configured.",
            )
        return GitHubMcpConnectionStatus(
            configured=True,
            connected=False,
            server_endpoint=self._client.endpoint,
            detail="GitHub MCP is configured. Connect to verify the managed credential.",
        )

    async def connect(self) -> GitHubMcpConnectionStatus:
        client = self._require_client()
        try:
            account = GitHubMcpClient.tool_json(await client.call_tool("get_me", {}))
        except GitHubMcpError as exc:
            raise RepositoryBindingError(str(exc)) from exc
        login = self._required_string(account, "login", context="GitHub account")
        return GitHubMcpConnectionStatus(
            configured=True,
            connected=True,
            account_login=login,
            server_endpoint=client.endpoint,
            detail=f"Connected through the administrator-managed GitHub MCP identity {login}.",
        )

    async def list_repositories(
        self, *, query: str | None, page: int, per_page: int
    ) -> GitHubRepositoryPage:
        client = self._require_client()
        account = GitHubMcpClient.tool_json(await client.call_tool("get_me", {}))
        login = self._required_string(account, "login", context="GitHub account")
        effective_query = query.strip() if query and query.strip() else f"user:{login}"
        raw = GitHubMcpClient.tool_json(
            await client.call_tool(
                "search_repositories",
                {
                    "query": effective_query,
                    "page": page,
                    "perPage": per_page,
                    "sort": "updated",
                    "order": "desc",
                    "minimal_output": True,
                },
            )
        )
        if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
            raise RepositoryBindingError("GitHub MCP returned an invalid repository page.")
        repositories = [self._parse_repository(item) for item in raw["items"]]
        return GitHubRepositoryPage(
            repositories=repositories,
            total_count=self._required_int(raw, "total_count", context="repository search"),
            incomplete_results=bool(raw.get("incomplete_results", False)),
            page=page,
            per_page=per_page,
        )

    async def list_bindings(
        self, *, session_id: str, requesting_user_id: str
    ) -> list[RepositoryPurposeBinding]:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        return await self._repository.list_for_session(session_id=session_id)

    async def bind_repository(
        self,
        *,
        session_id: str,
        requesting_user_id: str,
        repository: GitHubRepositorySummary,
        purpose: RepositoryPurpose,
        requested_ref: str,
        included_paths: list[str],
        excluded_paths: list[str],
        trace_id: str,
    ) -> RepositoryPurposeBinding:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        owner, repo = self._split_full_name(repository.full_name)
        client = self._require_client()
        observed_repository = await self._resolve_repository(
            client=client,
            full_name=repository.full_name,
        )
        commits = GitHubMcpClient.tool_json(
            await client.call_tool(
                "list_commits",
                {
                    "owner": owner,
                    "repo": repo,
                    "sha": requested_ref,
                    "perPage": 1,
                },
            )
        )
        if not isinstance(commits, list) or not commits:
            raise RepositoryBindingError(
                f"GitHub MCP could not resolve '{requested_ref}' for '{repository.full_name}'."
            )
        resolved_commit = self._required_string(commits[0], "sha", context="commit")
        await client.call_tool(
            "get_file_contents",
            {
                "owner": owner,
                "repo": repo,
                "path": "",
                "ref": resolved_commit,
            },
        )
        account = GitHubMcpClient.tool_json(await client.call_tool("get_me", {}))
        principal = self._required_string(account, "login", context="GitHub account")
        now = datetime.now(UTC)
        binding = RepositoryPurposeBinding(
            id=str(uuid4()),
            session_id=session_id,
            owner_user_id=requesting_user_id,
            repository_id=observed_repository.repository_id,
            repository_full_name=observed_repository.full_name,
            repository_url=observed_repository.html_url,
            purpose=purpose,
            requested_ref=requested_ref,
            resolved_commit=resolved_commit,
            included_paths=self._normalize_paths(included_paths),
            excluded_paths=self._normalize_paths(excluded_paths),
            principal=principal,
            status="approved",
            validated_at=now,
            created_at=now,
        )
        existing_bindings = await self._repository.list_for_session(session_id=session_id)
        for existing in existing_bindings:
            if existing.purpose == purpose and existing.status in {"validated", "approved"}:
                await self._repository.put(
                    existing.model_copy(update={"status": "superseded"}, deep=True)
                )
        await self._repository.put(binding)
        await self._governance_service.record_tool_request(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="repository-connection-service",
            tool_name="github_mcp.bind_repository",
            detail={
                "binding_id": binding.id,
                "repository_id": binding.repository_id,
                "repository_full_name": binding.repository_full_name,
                "purpose": binding.purpose,
                "requested_ref": binding.requested_ref,
                "resolved_commit": binding.resolved_commit,
                "included_paths": binding.included_paths,
                "excluded_paths": binding.excluded_paths,
                "principal": binding.principal,
            },
        )
        return binding

    async def _resolve_repository(
        self,
        *,
        client: GitHubMcpClient,
        full_name: str,
    ) -> GitHubRepositorySummary:
        raw = GitHubMcpClient.tool_json(
            await client.call_tool(
                "search_repositories",
                {
                    "query": f"repo:{full_name}",
                    "page": 1,
                    "perPage": 10,
                    "minimal_output": True,
                },
            )
        )
        if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
            raise RepositoryBindingError("GitHub MCP returned an invalid repository page.")
        for item in raw["items"]:
            observed = self._parse_repository(item)
            if observed.full_name.casefold() == full_name.casefold():
                return observed
        raise RepositoryBindingError(
            f"GitHub MCP could not verify access to repository '{full_name}'."
        )

    def _require_client(self) -> GitHubMcpClient:
        if self._client is None:
            raise RepositoryBindingError("GitHub MCP is not configured.")
        return self._client

    @staticmethod
    def _parse_repository(value: Any) -> GitHubRepositorySummary:
        if not isinstance(value, dict):
            raise RepositoryBindingError("GitHub MCP returned an invalid repository record.")
        try:
            return GitHubRepositorySummary(
                repository_id=int(RepositoryConnectionService._field(value, "id", "ID")),
                name=str(RepositoryConnectionService._field(value, "name", "Name")),
                full_name=str(
                    RepositoryConnectionService._field(value, "full_name", "FullName")
                ),
                description=str(
                    RepositoryConnectionService._field(
                        value, "description", "Description", default=""
                    )
                    or ""
                ),
                html_url=str(
                    RepositoryConnectionService._field(value, "html_url", "HTMLURL")
                ),
                private=bool(
                    RepositoryConnectionService._field(
                        value, "private", "Private", default=False
                    )
                ),
                archived=bool(
                    RepositoryConnectionService._field(
                        value, "archived", "Archived", default=False
                    )
                ),
                default_branch=str(
                    RepositoryConnectionService._field(
                        value, "default_branch", "DefaultBranch"
                    )
                ),
                language=RepositoryConnectionService._field(
                    value, "language", "Language", default=None
                ),
                updated_at=RepositoryConnectionService._field(
                    value, "updated_at", "UpdatedAt", default=None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RepositoryBindingError("GitHub MCP returned an invalid repository record.") from exc

    @staticmethod
    def _required_string(value: Any, key: str, *, context: str) -> str:
        if not isinstance(value, dict):
            raise RepositoryBindingError(f"GitHub MCP returned an invalid {context} response.")
        result = value.get(key)
        if not isinstance(result, str) or not result.strip():
            raise RepositoryBindingError(f"GitHub MCP {context} response omitted '{key}'.")
        return result

    @staticmethod
    def _required_int(value: Any, key: str, *, context: str) -> int:
        if not isinstance(value, dict):
            raise RepositoryBindingError(f"GitHub MCP returned an invalid {context} response.")
        result = value.get(key)
        if not isinstance(result, int):
            raise RepositoryBindingError(f"GitHub MCP {context} response omitted '{key}'.")
        return result

    @staticmethod
    def _field(value: dict[str, Any], *keys: str, default: Any = ...) -> Any:
        for key in keys:
            if key in value:
                return value[key]
        if default is not ...:
            return default
        raise KeyError(keys[0])

    @staticmethod
    def _split_full_name(full_name: str) -> tuple[str, str]:
        parts = full_name.split("/")
        if len(parts) != 2 or not all(parts):
            raise RepositoryBindingError("Repository name must use the 'owner/name' format.")
        return parts[0], parts[1]

    @staticmethod
    def _normalize_paths(paths: list[str]) -> list[str]:
        normalized: list[str] = []
        for path in paths:
            cleaned = path.strip().strip("/")
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized
