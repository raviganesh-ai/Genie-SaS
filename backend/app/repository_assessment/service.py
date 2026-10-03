"""Deterministic commit-pinned repository inventory and graph construction."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import tomllib
import xml.etree.ElementTree as ET
from collections import deque
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.agents.gateway import AgentGatewayError
from app.governance.governance_service import GovernanceService
from app.orchestration.agent_orchestrator import AgentOrchestrator
from app.repository_assessment.models import (
    ComponentRoleInsight,
    CoverageGap,
    DependencyEdge,
    DependencyNode,
    GraphEvidence,
    RepositoryAssessment,
    RepositoryChatAnswer,
    RepositoryCodeSummary,
    RepositoryInventory,
)
from app.repository_assessment.parsing import (
    RepositoryAssessmentAgentResponseError,
    parse_agent_response,
)
from app.repository_assessment.repository import RepositoryAssessmentRepository
from app.repository_connections.github_mcp_client import GitHubMcpClient, GitHubMcpError
from app.repository_connections.models import RepositoryPurposeBinding
from app.repository_connections.repository import RepositoryBindingRepository
from app.services.session_service import SessionService

_MANIFEST_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "pom.xml",
}
_SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".cs", ".java", ".go"}
_LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".cs": "C#",
    ".java": "Java",
    ".go": "Go",
}
_IMPORT_PATTERNS = (
    re.compile(r"^\s*(?:from|import)\s+([A-Za-z0-9_.-]+)", re.MULTILINE),
    re.compile(r"""(?:import|require)\s*(?:\(|[^'"]*from\s*)?['"]([^'"]+)['"]"""),
    re.compile(r"^\s*using\s+([A-Za-z0-9_.-]+)\s*;", re.MULTILINE),
)
_URL_PATTERN = re.compile(r"https://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")

# Curated, deterministic (non-LLM) package-name -> human-readable framework
# name lookup used only to label "built_on" technology nodes with real
# evidence (the declaring manifest path) - never a substitute for genuine
# dependency analysis, just a small enrichment on top of it.
_FRAMEWORK_PACKAGES = {
    "react": "React",
    "react-dom": "React",
    "next": "Next.js",
    "vue": "Vue.js",
    "@angular/core": "Angular",
    "express": "Express",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "uvicorn": "Uvicorn",
    "@fluentui/react-components": "Fluent UI",
    "reactflow": "React Flow",
    "spring-boot-starter": "Spring Boot",
}


class _ComponentRoleDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_path: str
    role: str
    confidence: float = Field(ge=0, le=1)
    rationale: str


class _CodeSummaryEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    highlights: list[str] = Field(default_factory=list)
    components: list[_ComponentRoleDraft] = Field(default_factory=list)


class _ChatAnswerEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    referenced_paths: list[str] = Field(default_factory=list)


class RepositoryAssessmentError(RuntimeError):
    """Raised when a live immutable repository assessment cannot complete."""


class RepositoryAssessmentService:
    def __init__(
        self,
        *,
        client: GitHubMcpClient | None,
        binding_repository: RepositoryBindingRepository,
        assessment_repository: RepositoryAssessmentRepository,
        session_service: SessionService,
        governance_service: GovernanceService,
        max_files: int,
        max_depth: int,
        max_source_bytes: int,
        orchestrator: AgentOrchestrator | None = None,
    ) -> None:
        self._client = client
        self._binding_repository = binding_repository
        self._assessment_repository = assessment_repository
        self._session_service = session_service
        self._governance_service = governance_service
        self._max_files = max_files
        self._max_depth = max_depth
        self._max_source_bytes = max_source_bytes
        # Optional: the plain-language code summary + component role
        # classification (see _attach_code_summary) is a layered enrichment
        # on top of the always-available deterministic graph below, not a
        # requirement for it - omitting this (e.g. in tests, or if Foundry
        # is not configured in this environment) simply skips that layer
        # rather than failing the whole assessment.
        self._orchestrator = orchestrator

    async def assess(
        self,
        *,
        session_id: str,
        binding_id: str,
        requesting_user_id: str,
        trace_id: str,
    ) -> RepositoryAssessment:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        binding = await self._binding_repository.get(binding_id=binding_id)
        if binding is None or binding.session_id != session_id:
            raise RepositoryAssessmentError("Repository binding was not found for this session.")
        if binding.owner_user_id != requesting_user_id:
            raise RepositoryAssessmentError("Repository binding access was denied.")
        if binding.status not in {"validated", "approved"}:
            raise RepositoryAssessmentError("Repository binding is not active.")
        client = self._require_client()
        owner, repository = self._split_repository(binding.repository_full_name)
        files, traversal_gaps = await self._enumerate_files(
            client=client,
            owner=owner,
            repository=repository,
            binding=binding,
        )
        assessment = await self._build_assessment(
            client=client,
            owner=owner,
            repository=repository,
            binding=binding,
            files=files,
            traversal_gaps=traversal_gaps,
        )
        assessment = await self._attach_code_summary(
            assessment=assessment, binding=binding, trace_id=trace_id
        )
        await self._assessment_repository.put(assessment)
        await self._governance_service.record_tool_request(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="repository-assessment-service",
            tool_name="github_mcp.assess_repository",
            detail={
                "assessment_id": assessment.id,
                "binding_id": binding.id,
                "code_summary_generated": assessment.code_summary is not None,
                "repository_full_name": binding.repository_full_name,
                "commit": binding.resolved_commit,
                "file_count": assessment.inventory.file_count,
                "analyzed_file_count": assessment.inventory.analyzed_file_count,
                "node_count": len(assessment.nodes),
                "edge_count": len(assessment.edges),
                "coverage_gap_count": len(assessment.coverage_gaps),
            },
        )
        return assessment

    async def list_assessments(
        self, *, session_id: str, requesting_user_id: str
    ) -> list[RepositoryAssessment]:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        return await self._assessment_repository.list_for_session(session_id=session_id)

    async def ask(
        self,
        *,
        session_id: str,
        assessment_id: str,
        requesting_user_id: str,
        message: str,
        trace_id: str,
    ) -> RepositoryChatAnswer:
        """Answers one free-text question about an already-completed
        assessment (code analysis) - grounded only in its deterministic
        graph, never requiring the whole repository to be re-read. Fails
        closed (raises) rather than ever answering from the model's own
        general knowledge: unlike the summary attached during `assess()`
        (which fails soft with a coverage gap so it never blocks the
        graph), this is a user-initiated, on-demand request with nothing
        else useful to return if it cannot be grounded."""
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        cleaned_message = message.strip()
        if not cleaned_message:
            raise RepositoryAssessmentError("Describe what you'd like to know about this repository.")
        if self._orchestrator is None:
            raise RepositoryAssessmentError("Azure AI Foundry orchestrator is not configured.")
        assessment = await self._assessment_repository.get(assessment_id=assessment_id)
        if assessment is None or assessment.session_id != session_id:
            raise RepositoryAssessmentError("Repository assessment was not found for this session.")
        evidence = self._code_summary_evidence(assessment)
        valid_paths = {
            path
            for component in evidence["components"]
            for path in component["sample_paths"]
        } | {component["component_path"] for component in evidence["components"]}
        variables = {
            "evidence_json": json.dumps(evidence),
            "prior_summary": assessment.code_summary.summary if assessment.code_summary else "",
            "question": cleaned_message,
            "retry_instruction": "",
        }
        for attempt in range(2):
            result = await self._orchestrator.execute_agent(
                agent_id="code-analyst",
                prompt_id="repository-code-chat-v1",
                variables=variables,
                session_id=session_id,
                trace_id=f"{trace_id}:repository-chat",
            )
            try:
                envelope = parse_agent_response(result.output_text, _ChatAnswerEnvelope)
                break
            except RepositoryAssessmentAgentResponseError as exc:
                if attempt == 1:
                    raise RepositoryAssessmentError(str(exc)) from exc
                variables["retry_instruction"] = (
                    "A prior response was malformed, truncated, or schema-invalid. "
                    f"Correct these exact validation issues: {exc} Regenerate the "
                    "complete response as fresh JSON, referencing only paths that "
                    "literally appear in evidence_json."
                )
        else:
            raise RepositoryAssessmentError("Repository chat retry loop exited unexpectedly.")
        answer = RepositoryChatAnswer(
            question=cleaned_message,
            answer=envelope.answer,
            referenced_paths=[path for path in envelope.referenced_paths if path in valid_paths],
            generated_at=datetime.now(UTC),
        )
        await self._governance_service.record_tool_request(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="repository-assessment-service",
            tool_name="code_analyst.ask",
            detail={
                "assessment_id": assessment.id,
                "question": cleaned_message,
                "referenced_path_count": len(answer.referenced_paths),
            },
        )
        return answer

    async def _attach_code_summary(
        self,
        *,
        assessment: RepositoryAssessment,
        binding: RepositoryPurposeBinding,
        trace_id: str,
    ) -> RepositoryAssessment:
        """Layers a plain-language code summary + per-component role
        classification onto an already-built deterministic assessment.

        This never blocks or invalidates the deterministic graph above it:
        if Foundry is not configured, or the agent's response cannot be
        parsed after retrying, the assessment is returned unchanged except
        for one explanatory `coverage_gaps` entry - a real, visible failure
        (fail closed), never a fabricated summary."""
        if self._orchestrator is None:
            return assessment
        try:
            summary = await self._execute_code_summary(
                assessment=assessment, binding=binding, trace_id=trace_id
            )
        except (RepositoryAssessmentAgentResponseError, AgentGatewayError) as exc:
            gap = CoverageGap(
                category="summary_unavailable",
                detail=f"Genie could not generate a plain-language code summary: {exc}",
                paths=[],
            )
            return assessment.model_copy(
                update={"coverage_gaps": [*assessment.coverage_gaps, gap]}
            )
        return assessment.model_copy(update={"code_summary": summary})

    async def _execute_code_summary(
        self,
        *,
        assessment: RepositoryAssessment,
        binding: RepositoryPurposeBinding,
        trace_id: str,
    ) -> RepositoryCodeSummary:
        orchestrator = self._orchestrator
        if orchestrator is None:
            raise RepositoryAssessmentError("Azure AI Foundry orchestrator is not configured.")
        evidence = self._code_summary_evidence(assessment)
        component_ids = {item["component_path"]: item["id"] for item in evidence["components"]}
        variables = {
            "repository_full_name": assessment.repository_full_name,
            "commit": assessment.commit,
            "evidence_json": json.dumps(evidence),
            "retry_instruction": "",
        }
        for attempt in range(2):
            result = await orchestrator.execute_agent(
                agent_id="code-analyst",
                prompt_id="repository-code-summary-v1",
                variables=variables,
                session_id=binding.session_id,
                trace_id=f"{trace_id}:code-summary",
            )
            try:
                envelope = parse_agent_response(result.output_text, _CodeSummaryEnvelope)
            except RepositoryAssessmentAgentResponseError as exc:
                if attempt == 1:
                    raise
                variables["retry_instruction"] = (
                    "A prior response was malformed, truncated, or schema-invalid. "
                    f"Correct these exact validation issues: {exc} Regenerate the "
                    "complete response as fresh JSON, referencing only "
                    "component_path values that literally appear in evidence_json."
                )
                continue
            component_roles = [
                ComponentRoleInsight(
                    component_id=component_ids[item.component_path],
                    component_path=item.component_path,
                    role=item.role,
                    confidence=item.confidence,
                    rationale=item.rationale,
                )
                for item in envelope.components
                if item.component_path in component_ids
            ]
            return RepositoryCodeSummary(
                summary=envelope.summary,
                highlights=envelope.highlights,
                component_roles=component_roles,
                generated_at=datetime.now(UTC),
            )
        raise RuntimeError("Repository code summary retry loop exited unexpectedly.")

    @staticmethod
    def _code_summary_evidence(assessment: RepositoryAssessment) -> dict[str, Any]:
        """Builds a compact, fully evidence-backed JSON view of the already
        -built graph for the LLM to summarize/classify - never the raw
        file contents, and never anything the deterministic analyzers did
        not already find."""
        nodes_by_id = {node.id: node for node in assessment.nodes}
        components: list[dict[str, Any]] = []
        for node in assessment.nodes:
            if node.type != "component":
                continue
            file_nodes = [
                nodes_by_id[edge.target]
                for edge in assessment.edges
                if edge.source == node.id
                and edge.type == "contains"
                and edge.target in nodes_by_id
            ]
            technology_nodes = [
                nodes_by_id[edge.target]
                for edge in assessment.edges
                if edge.source == node.id
                and edge.type == "built_on"
                and edge.target in nodes_by_id
            ]
            components.append(
                {
                    "id": node.id,
                    "component_path": node.name,
                    "file_count": len(file_nodes),
                    "sample_paths": sorted(f.path for f in file_nodes if f.path)[:8],
                    "technologies": sorted({t.name for t in technology_nodes}),
                }
            )
        packages = sorted({node.name for node in assessment.nodes if node.type == "package"})[:30]
        endpoints = sorted(
            {node.name for node in assessment.nodes if node.type == "integration_endpoint"}
        )[:20]
        return {
            "languages": assessment.inventory.languages,
            "file_count": assessment.inventory.file_count,
            "analyzed_file_count": assessment.inventory.analyzed_file_count,
            "components": components,
            "packages": packages,
            "integration_endpoints": endpoints,
        }

    async def _enumerate_files(
        self,
        *,
        client: GitHubMcpClient,
        owner: str,
        repository: str,
        binding: RepositoryPurposeBinding,
    ) -> tuple[list[dict[str, Any]], list[CoverageGap]]:
        roots = binding.included_paths or [""]
        queue: deque[tuple[str, int]] = deque((path, 0) for path in roots)
        files: list[dict[str, Any]] = []
        gaps: list[CoverageGap] = []
        visited: set[str] = set()
        while queue and len(files) < self._max_files:
            path, depth = queue.popleft()
            if path in visited or self._is_excluded(path, binding.excluded_paths):
                continue
            visited.add(path)
            if depth > self._max_depth:
                gaps.append(
                    CoverageGap(
                        category="depth_limit",
                        detail=f"Directory traversal exceeded depth {self._max_depth}.",
                        paths=[path],
                    )
                )
                continue
            try:
                raw = await self._get_contents_resilient(
                    client=client,
                    owner=owner,
                    repository=repository,
                    path=path,
                    commit=binding.resolved_commit,
                )
            except RepositoryAssessmentError as exc:
                gaps.append(
                    CoverageGap(
                        category="unreadable_directory",
                        detail=f"GitHub MCP could not list this path after retrying: {exc}",
                        paths=[path],
                    )
                )
                continue
            entries = self._directory_entries(raw)
            if entries is None:
                if isinstance(raw, dict):
                    files.append(raw)
                continue
            for entry in entries:
                entry_path = str(entry.get("path") or "")
                if not entry_path or self._is_excluded(entry_path, binding.excluded_paths):
                    continue
                entry_type = str(entry.get("type") or "").lower()
                if entry_type in {"dir", "directory", "tree"}:
                    queue.append((entry_path, depth + 1))
                elif entry_type in {"file", "blob"}:
                    files.append(entry)
                    if len(files) >= self._max_files:
                        break
                else:
                    gaps.append(
                        CoverageGap(
                            category="unsupported_entry",
                            detail=f"Repository entry type '{entry_type or 'unknown'}' was not read.",
                            paths=[entry_path],
                        )
                    )
        if queue:
            gaps.append(
                CoverageGap(
                    category="file_limit",
                    detail=f"Assessment stopped at the configured {self._max_files}-file limit.",
                    paths=[path for path, _ in list(queue)[:20]],
                )
            )
        return files, gaps

    async def _build_assessment(
        self,
        *,
        client: GitHubMcpClient,
        owner: str,
        repository: str,
        binding: RepositoryPurposeBinding,
        files: list[dict[str, Any]],
        traversal_gaps: list[CoverageGap],
    ) -> RepositoryAssessment:
        repository_node_id = self._node_id("repository", binding.repository_full_name)
        nodes: dict[str, DependencyNode] = {
            repository_node_id: DependencyNode(
                id=repository_node_id,
                type="repository",
                name=binding.repository_full_name,
                attributes={"commit": binding.resolved_commit, "purpose": binding.purpose},
            )
        }
        edges: dict[str, DependencyEdge] = {}
        package_nodes: dict[str, str] = {}
        component_nodes: dict[str, str] = {}
        # Deterministic intra-repository "depends_on" resolution (see
        # _resolve_local_dependencies): every analyzed source file is
        # registered here by id, and every import that did NOT match a
        # declared external package is queued for a second pass once every
        # file is known, so a cross-component local import can be
        # distinguished from an external one in a single read of each file.
        source_file_registry: dict[str, tuple[str, str]] = {}
        pending_local_imports: list[tuple[str, str, str, str]] = []
        analyzed_count = 0
        languages: set[str] = set()
        manifest_paths: list[str] = []
        infrastructure_paths: list[str] = []
        workflow_paths: list[str] = []
        test_paths: list[str] = []
        gaps = list(traversal_gaps)

        for file_entry in files:
            path = str(file_entry.get("path") or "")
            if not path:
                continue
            pure_path = PurePosixPath(path)
            suffix = pure_path.suffix.lower()
            name = pure_path.name
            if suffix in _LANGUAGES:
                languages.add(_LANGUAGES[suffix])
            lower_path = path.lower()
            if suffix in {".bicep", ".tf"} or name in {"Dockerfile", "azure.yaml"}:
                infrastructure_paths.append(path)
            if ".github/workflows/" in lower_path or lower_path.endswith("azure-pipelines.yml"):
                workflow_paths.append(path)
            if any(part in {"test", "tests", "__tests__"} for part in pure_path.parts):
                test_paths.append(path)
            is_manifest = name in _MANIFEST_NAMES or suffix in {".csproj"}
            is_source = suffix in _SOURCE_SUFFIXES
            if not is_manifest and not is_source:
                continue
            size = self._entry_size(file_entry)
            if size is not None and size > self._max_source_bytes:
                gaps.append(
                    CoverageGap(
                        category="large_file",
                        detail="File exceeded the configured source-analysis size limit.",
                        paths=[path],
                    )
                )
                continue
            if size == 0:
                # A directory-listing size of exactly 0 bytes is GitHub's own,
                # authoritative statement that the file is intentionally
                # empty (e.g. a marker `__init__.py`) - there is nothing to
                # read, so there is nothing "unreadable" about it. Skip the
                # content fetch entirely (one fewer GitHub MCP call) and
                # record it as analyzed with empty content rather than as a
                # coverage gap.
                content: str | None = ""
            else:
                try:
                    raw = await self._get_contents_resilient(
                        client=client,
                        owner=owner,
                        repository=repository,
                        path=path,
                        commit=binding.resolved_commit,
                    )
                except RepositoryAssessmentError as exc:
                    gaps.append(
                        CoverageGap(
                            category="unreadable_content",
                            detail=f"GitHub MCP could not read this file after retrying: {exc}",
                            paths=[path],
                        )
                    )
                    continue
                content = self._file_text(raw)
                if content is None:
                    gaps.append(
                        CoverageGap(
                            category="unreadable_content",
                            detail="GitHub MCP did not return readable text content.",
                            paths=[path],
                        )
                    )
                    continue
            analyzed_count += 1
            file_node_id = self._node_id("manifest" if is_manifest else "source_file", path)
            nodes[file_node_id] = DependencyNode(
                id=file_node_id,
                type="manifest" if is_manifest else "source_file",
                name=name,
                path=path,
            )
            self._add_edge(
                edges,
                source=repository_node_id,
                target=file_node_id,
                edge_type="contains",
                binding=binding,
                path=path,
            )
            # Group this file into its top-level-folder component (the
            # "Recommended" deterministic grouping) - every analyzed file
            # belongs to exactly one component, and every component is
            # reachable from the repository node, independent of whether
            # the code-analyst's LLM-assisted role classification below
            # ever runs or succeeds.
            component_key = self._component_key(path)
            component_id = component_nodes.get(component_key)
            if component_id is None:
                component_id = self._node_id("component", component_key)
                component_nodes[component_key] = component_id
                nodes[component_id] = DependencyNode(
                    id=component_id,
                    type="component",
                    name=component_key,
                    path=component_key,
                )
                self._add_edge(
                    edges,
                    source=repository_node_id,
                    target=component_id,
                    edge_type="contains",
                    binding=binding,
                    path=component_key,
                )
            self._add_edge(
                edges,
                source=component_id,
                target=file_node_id,
                edge_type="contains",
                binding=binding,
                path=path,
            )
            if suffix in _LANGUAGES:
                self._add_technology_edge(
                    nodes=nodes,
                    edges=edges,
                    component_id=component_id,
                    technology_name=_LANGUAGES[suffix],
                    binding=binding,
                    path=path,
                )
            if not is_manifest:
                source_file_registry[file_node_id] = (component_id, path)
            if is_manifest:
                manifest_paths.append(path)
                try:
                    dependencies = self._parse_dependencies(path, content)
                except (json.JSONDecodeError, tomllib.TOMLDecodeError, ET.ParseError, ValueError) as exc:
                    gaps.append(
                        CoverageGap(
                            category="manifest_parse_error",
                            detail=f"Manifest could not be parsed: {type(exc).__name__}.",
                            paths=[path],
                        )
                    )
                    continue
                for dependency_name, version in dependencies:
                    package_id = self._node_id("package", dependency_name.lower())
                    package_nodes[dependency_name.lower()] = package_id
                    nodes.setdefault(
                        package_id,
                        DependencyNode(
                            id=package_id,
                            type="package",
                            name=dependency_name,
                            version=version,
                        ),
                    )
                    self._add_edge(
                        edges,
                        source=file_node_id,
                        target=package_id,
                        edge_type="declares",
                        binding=binding,
                        path=path,
                        excerpt=f"{dependency_name} {version or ''}".strip(),
                    )
                    framework_name = _FRAMEWORK_PACKAGES.get(dependency_name.lower())
                    if framework_name is not None:
                        self._add_technology_edge(
                            nodes=nodes,
                            edges=edges,
                            component_id=component_id,
                            technology_name=framework_name,
                            binding=binding,
                            path=path,
                        )
            else:
                for imported in self._parse_imports(content):
                    package_id = self._match_package(imported, package_nodes)
                    if package_id is not None:
                        self._add_edge(
                            edges,
                            source=file_node_id,
                            target=package_id,
                            edge_type="imports",
                            binding=binding,
                            path=path,
                            excerpt=imported,
                            confidence=0.9,
                        )
                    else:
                        pending_local_imports.append((file_node_id, component_id, path, imported))
                for endpoint in self._parse_endpoints(content):
                    endpoint_id = self._node_id("integration_endpoint", endpoint)
                    nodes.setdefault(
                        endpoint_id,
                        DependencyNode(
                            id=endpoint_id,
                            type="integration_endpoint",
                            name=endpoint,
                        ),
                    )
                    self._add_edge(
                        edges,
                        source=file_node_id,
                        target=endpoint_id,
                        edge_type="integrates_with",
                        binding=binding,
                        path=path,
                        excerpt=endpoint,
                        confidence=0.85,
                    )

        self._resolve_local_dependencies(
            edges=edges,
            binding=binding,
            source_file_registry=source_file_registry,
            pending_local_imports=pending_local_imports,
        )

        inventory = RepositoryInventory(
            file_count=len(files),
            analyzed_file_count=analyzed_count,
            languages=sorted(languages),
            manifest_paths=sorted(manifest_paths),
            infrastructure_paths=sorted(infrastructure_paths),
            workflow_paths=sorted(workflow_paths),
            test_paths=sorted(test_paths),
        )
        return RepositoryAssessment(
            id=str(uuid4()),
            session_id=binding.session_id,
            binding_id=binding.id,
            repository_full_name=binding.repository_full_name,
            commit=binding.resolved_commit,
            inventory=inventory,
            nodes=list(nodes.values()),
            edges=list(edges.values()),
            coverage_gaps=gaps,
            created_at=datetime.now(UTC),
        )

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
            return await client.call_tool(
                "get_file_contents",
                {
                    "owner": owner,
                    "repo": repository,
                    "path": path,
                    "ref": commit,
                },
            )
        except GitHubMcpError as exc:
            raise RepositoryAssessmentError(
                f"GitHub MCP could not read commit-pinned path '{path or '/'}'."
            ) from exc

    async def _get_contents_resilient(
        self,
        *,
        client: GitHubMcpClient,
        owner: str,
        repository: str,
        path: str,
        commit: str,
        max_attempts: int = 3,
    ) -> Any:
        """Retries a single commit-pinned fetch a few times before giving up.

        A real GitHub MCP read can transiently fail even for a
        well-formed, previously-successful request (secondary rate
        limiting, a brief network blip) - and a full assessment of a
        real, several-hundred-file repository makes that many sequential
        calls, so hitting at least one transient failure is common, not
        exceptional. Raises RepositoryAssessmentError only after every
        attempt is exhausted, so callers can record one coverage gap for
        that single path and continue the rest of the assessment instead
        of the whole run aborting over one unlucky request.
        """
        last_error: RepositoryAssessmentError | None = None
        for attempt in range(max_attempts):
            try:
                return await self._get_contents(
                    client=client,
                    owner=owner,
                    repository=repository,
                    path=path,
                    commit=commit,
                )
            except RepositoryAssessmentError as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _require_client(self) -> GitHubMcpClient:
        if self._client is None:
            raise RepositoryAssessmentError("GitHub MCP is not configured.")
        return self._client

    @staticmethod
    def _directory_entries(raw: Any) -> list[dict[str, Any]] | None:
        return GitHubMcpClient.file_directory_entries(raw)

    @staticmethod
    def _file_text(raw: Any) -> str | None:
        return GitHubMcpClient.file_text(raw)

    @staticmethod
    def _entry_size(entry: dict[str, Any]) -> int | None:
        value = entry.get("size")
        return value if isinstance(value, int) and value >= 0 else None

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
            raise RepositoryAssessmentError("Repository name must use the 'owner/name' format.")
        return parts[0], parts[1]

    @staticmethod
    def _node_id(node_type: str, value: str) -> str:
        digest = hashlib.sha256(f"{node_type}:{value}".encode()).hexdigest()[:24]
        return f"{node_type}:{digest}"

    @staticmethod
    def _edge_id(source: str, target: str, edge_type: str) -> str:
        return hashlib.sha256(f"{source}:{edge_type}:{target}".encode()).hexdigest()[:24]

    @classmethod
    def _add_edge(
        cls,
        edges: dict[str, DependencyEdge],
        *,
        source: str,
        target: str,
        edge_type: str,
        binding: RepositoryPurposeBinding,
        path: str,
        excerpt: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        edge_id = cls._edge_id(source, target, edge_type)
        evidence = GraphEvidence(
            repository_full_name=binding.repository_full_name,
            commit=binding.resolved_commit,
            path=path,
            excerpt=excerpt,
        )
        existing = edges.get(edge_id)
        if existing is not None:
            existing.evidence.append(evidence)
            return
        edges[edge_id] = DependencyEdge(
            id=edge_id,
            source=source,
            target=target,
            type=edge_type,
            confidence=confidence,
            evidence=[evidence],
        )

    @staticmethod
    def _component_key(path: str) -> str:
        """Groups a file into a component by its top-level repository
        folder - the simplest, fully evidence-based grouping (no
        inference): a root-level file (no folder) forms a synthetic
        "(root)" component so it is still represented in the graph."""
        parts = PurePosixPath(path).parts
        return parts[0] if len(parts) > 1 else "(root)"

    @classmethod
    def _add_technology_edge(
        cls,
        *,
        nodes: dict[str, DependencyNode],
        edges: dict[str, DependencyEdge],
        component_id: str,
        technology_name: str,
        binding: RepositoryPurposeBinding,
        path: str,
    ) -> None:
        technology_id = cls._node_id("technology", technology_name.lower())
        nodes.setdefault(
            technology_id,
            DependencyNode(id=technology_id, type="technology", name=technology_name),
        )
        cls._add_edge(
            edges,
            source=component_id,
            target=technology_id,
            edge_type="built_on",
            binding=binding,
            path=path,
            excerpt=technology_name,
        )

    @classmethod
    def _resolve_local_dependencies(
        cls,
        *,
        edges: dict[str, DependencyEdge],
        binding: RepositoryPurposeBinding,
        source_file_registry: dict[str, tuple[str, str]],
        pending_local_imports: list[tuple[str, str, str, str]],
    ) -> None:
        """Second pass (see ``pending_local_imports``): links components
        that depend on each other via plain intra-repository imports - an
        import that did not match any declared external package. This is
        necessarily heuristic (file-stem matching, not full language-aware
        module resolution): a match is used only when it is unambiguous
        (exactly one other analyzed file shares that stem), so an
        uncertain guess is skipped rather than asserted as fact - hence the
        reduced 0.6 confidence even when a match is found. Only surfaces
        genuine cross-component coupling; two files in the SAME component
        importing each other is normal internal structure, not a
        reportable interdependency.
        """
        stem_index: dict[str, list[tuple[str, str]]] = {}
        for file_node_id, (component_id, path) in source_file_registry.items():
            stem = PurePosixPath(path).stem.lower()
            stem_index.setdefault(stem, []).append((file_node_id, component_id))

        for source_file_id, source_component_id, path, imported in pending_local_imports:
            # Take the last slash-segment first (correctly isolates a JS/TS
            # relative import's final path component, e.g. "../lib/helper"
            # -> "helper"), then the LAST dot-segment (correctly isolates a
            # Python dotted-package import's final module name, e.g.
            # "shared.helper" -> "helper", not the package name "shared").
            last_segment = imported.rstrip("/").split("/")[-1]
            candidate_stem = last_segment.split(".")[-1].lower() if last_segment else ""
            if not candidate_stem:
                continue
            candidates = [
                candidate
                for candidate in stem_index.get(candidate_stem, [])
                if candidate[0] != source_file_id
            ]
            if len(candidates) != 1:
                continue  # no match, or ambiguous (several same-named files) - never guess
            _, target_component_id = candidates[0]
            if target_component_id == source_component_id:
                continue  # only cross-component coupling is reportable
            cls._add_edge(
                edges,
                source=source_component_id,
                target=target_component_id,
                edge_type="depends_on",
                binding=binding,
                path=path,
                excerpt=imported,
                confidence=0.6,
            )

    @staticmethod
    def _parse_dependencies(path: str, content: str) -> list[tuple[str, str | None]]:
        name = PurePosixPath(path).name
        if name == "package.json":
            payload = json.loads(content)
            result: list[tuple[str, str | None]] = []
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                values = payload.get(section, {})
                if isinstance(values, dict):
                    result.extend((str(key), str(value)) for key, value in values.items())
            return result
        if name == "pyproject.toml":
            payload = tomllib.loads(content)
            project = payload.get("project", {})
            dependencies = project.get("dependencies", []) if isinstance(project, dict) else []
            result = [
                RepositoryAssessmentService._split_python_requirement(str(value))
                for value in dependencies
            ]
            poetry = payload.get("tool", {}).get("poetry", {}).get("dependencies", {})
            if isinstance(poetry, dict):
                result.extend(
                    (str(key), str(value) if not isinstance(value, dict) else None)
                    for key, value in poetry.items()
                    if str(key).lower() != "python"
                )
            return result
        if name == "requirements.txt":
            return [
                RepositoryAssessmentService._split_python_requirement(line)
                for line in content.splitlines()
                if line.strip() and not line.lstrip().startswith(("#", "-", "git+"))
            ]
        if name == "go.mod":
            return [
                (match.group(1), match.group(2))
                for match in re.finditer(
                    r"^\s*([A-Za-z0-9._~/-]+)\s+(v[^\s]+)", content, re.MULTILINE
                )
            ]
        if name.endswith(".csproj"):
            root = ET.fromstring(content)
            return [
                (
                    element.attrib.get("Include") or element.attrib.get("Update") or "",
                    element.attrib.get("Version")
                    or next(
                        (child.text for child in element if child.tag.endswith("Version")),
                        None,
                    ),
                )
                for element in root.iter()
                if element.tag.endswith("PackageReference")
                and (element.attrib.get("Include") or element.attrib.get("Update"))
            ]
        if name == "pom.xml":
            root = ET.fromstring(content)
            result = []
            for dependency in root.iter():
                if not dependency.tag.endswith("dependency"):
                    continue
                group = next(
                    (child.text for child in dependency if child.tag.endswith("groupId")), None
                )
                artifact = next(
                    (child.text for child in dependency if child.tag.endswith("artifactId")), None
                )
                version = next(
                    (child.text for child in dependency if child.tag.endswith("version")), None
                )
                if group and artifact:
                    result.append((f"{group}:{artifact}", version))
            return result
        return []

    @staticmethod
    def _split_python_requirement(value: str) -> tuple[str, str | None]:
        stripped = value.strip()
        match = re.match(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(.*)$", stripped)
        if match is None:
            raise ValueError("Invalid Python dependency declaration.")
        version = match.group(2).strip() or None
        return match.group(1), version

    @staticmethod
    def _parse_imports(content: str) -> set[str]:
        imports: set[str] = set()
        for pattern in _IMPORT_PATTERNS:
            imports.update(match.group(1) for match in pattern.finditer(content))
        return imports

    @staticmethod
    def _match_package(imported: str, packages: dict[str, str]) -> str | None:
        candidate = imported.split("/")[0].split(".")[0].lower()
        normalized = candidate.replace("_", "-")
        for package, package_id in packages.items():
            package_root = package.split("/")[0].split(".")[0].lower().replace("_", "-")
            if normalized == package_root:
                return package_id
        return None

    @staticmethod
    def _parse_endpoints(content: str) -> set[str]:
        endpoints: set[str] = set()
        for match in _URL_PATTERN.finditer(content):
            parsed = urlsplit(match.group(0).rstrip(".,);'\""))
            if parsed.scheme == "https" and parsed.hostname:
                endpoints.add(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")))
        return endpoints

