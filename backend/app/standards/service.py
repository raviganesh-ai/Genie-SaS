"""Commit-pinned standards ingestion, classification, and conformance."""
from __future__ import annotations

import base64
import hashlib
import re
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from app.governance.governance_service import GovernanceService
from app.repository_assessment.repository import RepositoryAssessmentRepository
from app.repository_connections.github_mcp_client import GitHubMcpClient, GitHubMcpError
from app.repository_connections.models import RepositoryPurposeBinding
from app.repository_connections.repository import RepositoryBindingRepository
from app.services.session_service import SessionService
from app.standards.models import (
    ArchitectureStandardRule,
    ConformanceResult,
    StandardCitation,
    StandardsConflict,
    StandardsConformanceReport,
    StandardsSnapshot,
)
from app.standards.repository import StandardsRepository

_MODAL_PATTERN = re.compile(
    r"\b(must\s+not|shall\s+not|must|shall|required|should|recommended|may|optional)\b",
    re.IGNORECASE,
)
_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.#/+:-]{2,}")
_COMMON_WORDS = {
    "architecture",
    "application",
    "component",
    "service",
    "system",
    "using",
    "used",
    "with",
    "from",
    "that",
    "this",
    "must",
    "shall",
    "should",
    "recommended",
    "required",
    "optional",
}


class StandardsError(RuntimeError):
    """Raised when standards evidence cannot be read or evaluated."""


class StandardsService:
    def __init__(
        self,
        *,
        client: GitHubMcpClient | None,
        binding_repository: RepositoryBindingRepository,
        assessment_repository: RepositoryAssessmentRepository,
        standards_repository: StandardsRepository,
        session_service: SessionService,
        governance_service: GovernanceService,
        max_files: int,
        max_depth: int,
    ) -> None:
        self._client = client
        self._binding_repository = binding_repository
        self._assessment_repository = assessment_repository
        self._standards_repository = standards_repository
        self._session_service = session_service
        self._governance_service = governance_service
        self._max_files = max_files
        self._max_depth = max_depth

    async def ingest(
        self,
        *,
        session_id: str,
        binding_id: str,
        requesting_user_id: str,
        trace_id: str,
    ) -> StandardsSnapshot:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        binding = await self._binding_repository.get(binding_id=binding_id)
        if (
            binding is None
            or binding.session_id != session_id
            or binding.owner_user_id != requesting_user_id
        ):
            raise StandardsError("Standards repository binding was not found for this session.")
        if binding.purpose != "standards" or binding.status not in {"validated", "approved"}:
            raise StandardsError("An active Standards-purpose repository binding is required.")

        owner, repository = self._split_repository(binding.repository_full_name)
        markdown_files, traversal_gaps = await self._read_markdown_files(
            binding=binding,
            owner=owner,
            repository=repository,
        )
        rules: list[ArchitectureStandardRule] = []
        hashes: dict[str, str] = {}
        for path, content in markdown_files.items():
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            hashes[path] = content_hash
            rules.extend(
                self._classify_rules(
                    binding=binding,
                    path=path,
                    content=content,
                    content_hash=content_hash,
                )
            )
        conflicts = self._find_conflicts(rules)
        gaps = list(traversal_gaps)
        if not markdown_files:
            gaps.append("No readable Markdown standards were found in the approved path scope.")
        if not any(rule.classification == "mandatory" for rule in rules):
            gaps.append("No mandatory standards were identified.")
        snapshot = StandardsSnapshot(
            id=str(uuid4()),
            session_id=session_id,
            binding_id=binding.id,
            repository_full_name=binding.repository_full_name,
            commit=binding.resolved_commit,
            paths=sorted(markdown_files),
            content_hashes=hashes,
            rules=rules,
            conflicts=conflicts,
            gaps=gaps,
            created_at=datetime.now(UTC),
        )
        await self._standards_repository.put(snapshot)
        await self._governance_service.record_tool_request(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="standards-service",
            tool_name="github_mcp.ingest_standards",
            detail={
                "snapshot_id": snapshot.id,
                "binding_id": binding.id,
                "commit": binding.resolved_commit,
                "path_count": len(snapshot.paths),
                "rule_count": len(snapshot.rules),
                "conflict_count": len(snapshot.conflicts),
            },
        )
        return snapshot

    async def list_snapshots(
        self, *, session_id: str, requesting_user_id: str
    ) -> list[StandardsSnapshot]:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        return await self._standards_repository.list_for_session(session_id=session_id)

    async def evaluate(
        self,
        *,
        session_id: str,
        snapshot_id: str,
        assessment_id: str,
        requesting_user_id: str,
        trace_id: str,
    ) -> StandardsConformanceReport:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        snapshot = await self._standards_repository.get(snapshot_id=snapshot_id)
        assessment = await self._assessment_repository.get(assessment_id=assessment_id)
        if snapshot is None or snapshot.session_id != session_id:
            raise StandardsError("Standards snapshot was not found for this session.")
        if assessment is None or assessment.session_id != session_id:
            raise StandardsError("Repository assessment was not found for this session.")

        searchable_nodes = [
            (node.id, f"{node.name} {node.version or ''}".lower())
            for node in assessment.nodes
            if node.type in {"package", "integration_endpoint", "manifest"}
        ]
        results: list[ConformanceResult] = []
        for rule in snapshot.rules:
            keywords = self._rule_keywords(rule.statement)
            matched = [
                node_id
                for node_id, searchable in searchable_nodes
                if any(keyword in searchable for keyword in keywords)
            ]
            negated = bool(re.search(r"\b(must|shall)\s+not\b", rule.statement, re.IGNORECASE))
            if rule.classification == "superseded":
                status = "not_applicable"
                detail = "Superseded rule is retained for lineage and not enforced."
            elif not keywords:
                status = "unresolved"
                detail = "No deterministic component or dependency keyword could be resolved."
            elif negated and matched:
                status = "non_conformant"
                detail = "A prohibited dependency or integration is present."
            elif negated:
                status = "conformant"
                detail = "No prohibited dependency or integration was detected."
            elif matched:
                status = "conformant"
                detail = "The graph contains evidence matching this standard."
            else:
                status = "unresolved"
                detail = "No graph evidence matched; human review is required."
            results.append(
                ConformanceResult(
                    rule_id=rule.id,
                    status=status,
                    matched_node_ids=matched,
                    detail=detail,
                    citation=rule.citation,
                )
            )
        report = StandardsConformanceReport(
            snapshot_id=snapshot.id,
            assessment_id=assessment.id,
            results=results,
            evaluated_at=datetime.now(UTC),
        )
        await self._governance_service.record_policy_evaluation(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="standards-service",
            policy_name="architecture-standards-conformance",
            allowed=not any(result.status == "non_conformant" for result in results),
            detail={
                "snapshot_id": snapshot.id,
                "assessment_id": assessment.id,
                "result_count": len(results),
            },
        )
        return report

    async def _read_markdown_files(
        self,
        *,
        binding: RepositoryPurposeBinding,
        owner: str,
        repository: str,
    ) -> tuple[dict[str, str], list[str]]:
        client = self._require_client()
        roots = binding.included_paths or [""]
        queue: deque[tuple[str, int]] = deque((path, 0) for path in roots)
        markdown_files: dict[str, str] = {}
        gaps: list[str] = []
        visited: set[str] = set()
        while queue and len(markdown_files) < self._max_files:
            path, depth = queue.popleft()
            if path in visited or self._is_excluded(path, binding.excluded_paths):
                continue
            visited.add(path)
            if depth > self._max_depth:
                gaps.append(f"Traversal depth limit reached at '{path}'.")
                continue
            raw = await self._get_contents(
                client=client,
                owner=owner,
                repository=repository,
                path=path,
                commit=binding.resolved_commit,
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
                if not entry_path or self._is_excluded(entry_path, binding.excluded_paths):
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
                        commit=binding.resolved_commit,
                    )
                    text = self._file_text(file_raw)
                    if text is not None:
                        markdown_files[entry_path] = text
                        if len(markdown_files) >= self._max_files:
                            break
        if queue:
            gaps.append(f"Standards ingestion stopped at the {self._max_files}-file limit.")
        return markdown_files, gaps

    @staticmethod
    def _classify_rules(
        *,
        binding: RepositoryPurposeBinding,
        path: str,
        content: str,
        content_hash: str,
    ) -> list[ArchitectureStandardRule]:
        rules: list[ArchitectureStandardRule] = []
        heading = PurePosixPath(path).name
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            line = raw_line.strip()
            if line.startswith("#"):
                heading = line.lstrip("#").strip() or heading
                continue
            statement = re.sub(r"^[-*+]\s+|^\d+[.)]\s+", "", line).strip()
            if not statement:
                continue
            lowered = statement.lower()
            if any(word in lowered for word in ("superseded", "deprecated", "obsolete")):
                classification = "superseded"
            elif re.search(r"\b(must|shall|required)\b", lowered):
                classification = "mandatory"
            elif re.search(r"\b(should|recommended)\b", lowered):
                classification = "preferred"
            elif re.search(r"\b(may|optional)\b", lowered):
                classification = "advisory"
            else:
                classification = "example"
            rule_id = hashlib.sha256(
                f"{binding.resolved_commit}:{path}:{line_number}:{statement}".encode()
            ).hexdigest()[:24]
            rules.append(
                ArchitectureStandardRule(
                    id=rule_id,
                    title=heading,
                    statement=statement,
                    classification=classification,
                    citation=StandardCitation(
                        repository_full_name=binding.repository_full_name,
                        commit=binding.resolved_commit,
                        path=path,
                        line=line_number,
                        content_hash=content_hash,
                    ),
                )
            )
        return rules

    @classmethod
    def _find_conflicts(
        cls, rules: list[ArchitectureStandardRule]
    ) -> list[StandardsConflict]:
        grouped: dict[str, list[ArchitectureStandardRule]] = defaultdict(list)
        for rule in rules:
            normalized = _MODAL_PATTERN.sub("", rule.statement.lower())
            normalized = re.sub(r"\bnot\b", "", normalized)
            normalized = re.sub(r"\W+", " ", normalized).strip()
            if normalized:
                grouped[normalized].append(rule)
        conflicts: list[StandardsConflict] = []
        for related in grouped.values():
            has_negated = any(
                re.search(r"\b(must|shall)\s+not\b", rule.statement, re.IGNORECASE)
                for rule in related
            )
            has_positive = any(
                rule.classification == "mandatory"
                and not re.search(r"\b(must|shall)\s+not\b", rule.statement, re.IGNORECASE)
                for rule in related
            )
            if has_negated and has_positive:
                conflicts.append(
                    StandardsConflict(
                        rule_ids=[rule.id for rule in related],
                        detail="Mandatory standards contain both positive and negative forms.",
                    )
                )
        return conflicts

    @staticmethod
    def _rule_keywords(statement: str) -> set[str]:
        return {
            word.lower()
            for word in _WORD_PATTERN.findall(statement)
            if word.lower() not in _COMMON_WORDS
        }

    async def _get_contents(
        self,
        *,
        client: GitHubMcpClient,
        owner: str,
        repository: str,
        path: str,
        commit: str,
    ) -> Any:
        try:
            result = await client.call_tool(
                "get_file_contents",
                {"owner": owner, "repo": repository, "path": path, "ref": commit},
            )
            return GitHubMcpClient.tool_json(result)
        except GitHubMcpError as exc:
            raise StandardsError(
                f"GitHub MCP could not read commit-pinned standards path '{path or '/'}'."
            ) from exc

    def _require_client(self) -> GitHubMcpClient:
        if self._client is None:
            raise StandardsError("GitHub MCP is not configured.")
        return self._client

    @staticmethod
    def _directory_entries(raw: Any) -> list[dict[str, Any]] | None:
        if isinstance(raw, list) and all(isinstance(item, dict) for item in raw):
            return raw
        if isinstance(raw, dict):
            for key in ("items", "entries"):
                value = raw.get(key)
                if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                    return value
        return None

    @staticmethod
    def _file_text(raw: Any) -> str | None:
        if not isinstance(raw, dict) or not isinstance(raw.get("content"), str):
            return None
        content = raw["content"]
        if raw.get("encoding") == "base64":
            try:
                return base64.b64decode(content, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return None
        return content

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
            raise StandardsError("Repository name must use the 'owner/name' format.")
        return parts[0], parts[1]

