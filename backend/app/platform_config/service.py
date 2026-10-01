"""Platform-level reference repository configuration service.

Lets an administrator configure one or more "architecture"/"standards"
reference repositories once, commit-pinning and ingesting their content
immediately, for every future mission to use automatically (see
app.platform_config.models.PlatformReferenceRepository's docstring). Uses
the same administrator-managed GitHub MCP credential every other
repository-connection flow uses - never a separate, per-user credential.
"""
from __future__ import annotations

import hashlib
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.platform_config.models import PlatformReferencePurpose, PlatformReferenceRepository
from app.repository_connections.github_mcp_client import GitHubMcpClient, GitHubMcpError
from app.repository_connections.models import GitHubRepositorySummary
from app.standards.service import classify_markdown_rules, find_rule_conflicts

if TYPE_CHECKING:
    from app.governance.governance_service import GovernanceService
    from app.platform_config.repository import PlatformReferenceRepositoryStore


class PlatformConfigError(RuntimeError):
    """Raised when platform reference-repository configuration fails."""


class PlatformConfigService:
    def __init__(
        self,
        *,
        client: GitHubMcpClient | None,
        repository_store: PlatformReferenceRepositoryStore,
        governance_service: GovernanceService,
        max_files: int,
        max_depth: int,
    ) -> None:
        self._client = client
        self._repository_store = repository_store
        self._governance_service = governance_service
        self._max_files = max_files
        self._max_depth = max_depth

    async def list_repositories(
        self, *, purpose: PlatformReferencePurpose | None = None
    ) -> list[PlatformReferenceRepository]:
        repositories = await self._repository_store.list_all()
        if purpose is not None:
            repositories = [repository for repository in repositories if repository.purpose == purpose]
        return sorted(repositories, key=lambda repository: repository.created_at, reverse=True)

    async def add_repository(
        self,
        *,
        repository: GitHubRepositorySummary,
        purpose: PlatformReferencePurpose,
        requested_ref: str,
        included_paths: list[str],
        excluded_paths: list[str],
        requesting_user_id: str,
        trace_id: str,
    ) -> PlatformReferenceRepository:
        client = self._require_client()
        owner, repo = self._split_repository(repository.full_name)
        commits = GitHubMcpClient.tool_json(
            await client.call_tool(
                "list_commits", {"owner": owner, "repo": repo, "sha": requested_ref, "perPage": 1}
            )
        )
        if not isinstance(commits, list) or not commits:
            raise PlatformConfigError(
                f"GitHub MCP could not resolve '{requested_ref}' for '{repository.full_name}'."
            )
        resolved_commit = self._required_string(commits[0], "sha", context="commit")
        account = GitHubMcpClient.tool_json(await client.call_tool("get_me", {}))
        principal = self._required_string(account, "login", context="GitHub account")

        normalized_included = self._normalize_paths(included_paths)
        normalized_excluded = self._normalize_paths(excluded_paths)
        markdown_files, gaps = await self._read_markdown_files(
            client=client,
            owner=owner,
            repository=repo,
            commit=resolved_commit,
            included_paths=normalized_included,
            excluded_paths=normalized_excluded,
        )

        rules: list = []
        conflicts: list = []
        combined_reference_text: str | None = None
        hashes: dict[str, str] = {}
        for path, content in markdown_files.items():
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            hashes[path] = content_hash
            if purpose == "standards":
                rules.extend(
                    classify_markdown_rules(
                        repository_full_name=repository.full_name,
                        resolved_commit=resolved_commit,
                        path=path,
                        content=content,
                        content_hash=content_hash,
                    )
                )
        if purpose == "standards":
            conflicts = find_rule_conflicts(rules)
            if not markdown_files:
                gaps.append("No readable Markdown standards were found in the approved path scope.")
        else:
            combined_reference_text = "\n\n".join(
                f"# {path}\n\n{content}" for path, content in sorted(markdown_files.items())
            )
            if not markdown_files:
                gaps.append(
                    "No readable Markdown architecture reference was found in the approved path scope."
                )

        platform_repository = PlatformReferenceRepository(
            id=str(uuid4()),
            repository_id=repository.repository_id,
            repository_full_name=repository.full_name,
            repository_url=repository.html_url,
            purpose=purpose,
            requested_ref=requested_ref,
            resolved_commit=resolved_commit,
            included_paths=normalized_included,
            excluded_paths=normalized_excluded,
            principal=principal,
            configured_by_user_id=requesting_user_id,
            paths=sorted(markdown_files),
            content_hashes=hashes,
            gaps=gaps,
            combined_reference_text=combined_reference_text,
            rules=rules,
            conflicts=conflicts,
            created_at=datetime.now(UTC),
        )
        await self._repository_store.put(platform_repository)
        await self._governance_service.record_tool_request(
            session_id="platform",
            trace_id=trace_id,
            agent_id="platform-config-service",
            tool_name="github_mcp.configure_platform_reference_repository",
            detail={
                "repository_id": platform_repository.id,
                "repository_full_name": repository.full_name,
                "purpose": purpose,
                "commit": resolved_commit,
                "configured_by_user_id": requesting_user_id,
            },
        )
        return platform_repository

    async def remove_repository(self, *, repository_id: str, trace_id: str) -> None:
        existing = await self._repository_store.get(repository_id=repository_id)
        if existing is None:
            raise PlatformConfigError("Platform reference repository was not found.")
        await self._repository_store.delete(repository_id=repository_id)
        await self._governance_service.record_tool_request(
            session_id="platform",
            trace_id=trace_id,
            agent_id="platform-config-service",
            tool_name="github_mcp.remove_platform_reference_repository",
            detail={"repository_id": repository_id, "repository_full_name": existing.repository_full_name},
        )

    async def combined_architecture_reference_text(self) -> str | None:
        repositories = await self.list_repositories(purpose="architecture")
        texts = [
            repository.combined_reference_text
            for repository in repositories
            if repository.combined_reference_text and repository.combined_reference_text.strip()
        ]
        if not texts:
            return None
        return "\n\n---\n\n".join(texts)

    async def combined_standards_rules(self) -> list:
        repositories = await self.list_repositories(purpose="standards")
        rules: list = []
        for repository in repositories:
            rules.extend(repository.rules)
        return rules

    def _require_client(self) -> GitHubMcpClient:
        if self._client is None:
            raise PlatformConfigError("GitHub MCP is not configured.")
        return self._client

    async def _read_markdown_files(
        self,
        *,
        client: GitHubMcpClient,
        owner: str,
        repository: str,
        commit: str,
        included_paths: list[str],
        excluded_paths: list[str],
    ) -> tuple[dict[str, str], list[str]]:
        roots = included_paths or [""]
        queue: deque[tuple[str, int]] = deque((path, 0) for path in roots)
        markdown_files: dict[str, str] = {}
        gaps: list[str] = []
        visited: set[str] = set()
        while queue and len(markdown_files) < self._max_files:
            path, depth = queue.popleft()
            if path in visited or self._is_excluded(path, excluded_paths):
                continue
            visited.add(path)
            if depth > self._max_depth:
                gaps.append(f"Traversal depth limit reached at '{path}'.")
                continue
            raw = await self._get_contents(
                client=client, owner=owner, repository=repository, path=path, commit=commit
            )
            entries = self._directory_entries(raw)
            if entries is None:
                if path.lower().endswith(".md"):
                    text = self._file_text(raw)
                    if text is not None:
                        markdown_files[path] = text
                continue
            for entry in entries:
                entry_path = str(entry.get("path") or "")
                if not entry_path or self._is_excluded(entry_path, excluded_paths):
                    continue
                entry_type = str(entry.get("type") or "").lower()
                if entry_type in {"dir", "directory", "tree"}:
                    queue.append((entry_path, depth + 1))
                elif entry_type in {"file", "blob"} and entry_path.lower().endswith(".md"):
                    file_raw = await self._get_contents(
                        client=client,
                        owner=owner,
                        repository=repository,
                        path=entry_path,
                        commit=commit,
                    )
                    text = self._file_text(file_raw)
                    if text is not None:
                        markdown_files[entry_path] = text
                        if len(markdown_files) >= self._max_files:
                            break
        if queue:
            gaps.append("Maximum file limit reached before the traversal completed.")
        return markdown_files, gaps

    async def _get_contents(
        self, *, client: GitHubMcpClient, owner: str, repository: str, path: str, commit: str
    ) -> Any:
        try:
            return await client.call_tool(
                "get_file_contents",
                {"owner": owner, "repo": repository, "path": path, "ref": commit},
            )
        except GitHubMcpError as exc:
            raise PlatformConfigError(
                f"GitHub MCP could not read commit-pinned path '{path or '/'}'."
            ) from exc

    @staticmethod
    def _directory_entries(raw: Any) -> list[dict[str, Any]] | None:
        return GitHubMcpClient.file_directory_entries(raw)

    @staticmethod
    def _file_text(raw: Any) -> str | None:
        return GitHubMcpClient.file_text(raw)

    @staticmethod
    def _is_excluded(path: str, exclusions: list[str]) -> bool:
        normalized = path.strip("/")
        return any(
            normalized == exclusion or normalized.startswith(f"{exclusion}/")
            for exclusion in exclusions
        )

    @staticmethod
    def _split_repository(full_name: str) -> tuple[str, str]:
        parts = full_name.split("/")
        if len(parts) != 2 or not all(parts):
            raise PlatformConfigError("Repository name must use the 'owner/name' format.")
        return parts[0], parts[1]

    @staticmethod
    def _normalize_paths(paths: list[str]) -> list[str]:
        normalized: list[str] = []
        for path in paths:
            cleaned = path.strip().strip("/")
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    @staticmethod
    def _required_string(value: Any, key: str, *, context: str) -> str:
        if not isinstance(value, dict):
            raise PlatformConfigError(f"GitHub MCP returned an invalid {context} response.")
        result = value.get(key)
        if not isinstance(result, str) or not result.strip():
            raise PlatformConfigError(f"GitHub MCP {context} response omitted '{key}'.")
        return result
