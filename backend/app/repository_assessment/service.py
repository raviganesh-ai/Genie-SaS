"""Deterministic commit-pinned repository inventory and graph construction."""
from __future__ import annotations

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

from app.governance.governance_service import GovernanceService
from app.repository_assessment.models import (
    CoverageGap,
    DependencyEdge,
    DependencyNode,
    GraphEvidence,
    RepositoryAssessment,
    RepositoryInventory,
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
    ) -> None:
        self._client = client
        self._binding_repository = binding_repository
        self._assessment_repository = assessment_repository
        self._session_service = session_service
        self._governance_service = governance_service
        self._max_files = max_files
        self._max_depth = max_depth
        self._max_source_bytes = max_source_bytes

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
        await self._assessment_repository.put(assessment)
        await self._governance_service.record_tool_request(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="repository-assessment-service",
            tool_name="github_mcp.assess_repository",
            detail={
                "assessment_id": assessment.id,
                "binding_id": binding.id,
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
            raw = await self._get_contents(
                client=client,
                owner=owner,
                repository=repository,
                path=path,
                commit=binding.resolved_commit,
            )
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
            raw = await self._get_contents(
                client=client,
                owner=owner,
                repository=repository,
                path=path,
                commit=binding.resolved_commit,
            )
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

