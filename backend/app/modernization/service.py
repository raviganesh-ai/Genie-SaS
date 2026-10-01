"""Foundry-generated, approval-gated GitHub modernization pull requests."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.governance.approval_service import ApprovalService
from app.governance.governance_service import GovernanceService
from app.modernization.capabilities import ModernizationCapability, ModernizationCapabilityCatalog
from app.modernization.models import ModernizationFileChange, ModernizationPlan
from app.modernization.repository import ModernizationPlanRepository
from app.orchestration.agent_orchestrator import AgentOrchestrator
from app.repository_assessment.repository import RepositoryAssessmentRepository
from app.repository_connections.github_mcp_client import GitHubMcpClient, GitHubMcpError
from app.repository_connections.repository import RepositoryBindingRepository
from app.services.session_service import SessionService
from app.standards.architecture_reference_repository import ArchitectureReferenceRepository
from app.standards.repository import StandardsRepository

_URL_PATTERN = re.compile(r"https://github\.com/[^\s\"']+/pull/\d+")

# Shown to the Foundry Build Agent in place of real reference content when the
# caller supplied no "architecture"-purpose binding - see generate_plan's
# architecture_reference_snapshot_id (optional by design: a user may supply
# their own opinionated architecture reference, or let Genie fall back to its
# own Microsoft Azure Architecture Center knowledge and available IQ context).
_NO_ARCHITECTURE_REFERENCE_TEXT = (
    "(none provided - determine the architecture using Microsoft Azure Architecture Center "
    "reference guidance and any available IQ context; do not invent an unsupported reference.)"
)


class ModernizationError(RuntimeError):
    """Raised when a governed modernization action cannot complete."""


class _GeneratedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    changes: list[ModernizationFileChange] = Field(min_length=1)
    validation_commands: list[str] = Field(min_length=1)
    residual_risks: list[str] = Field(default_factory=list)
    rollback: str = Field(min_length=1)


class ModernizationService:
    def __init__(
        self,
        *,
        client: GitHubMcpClient | None,
        plan_repository: ModernizationPlanRepository,
        binding_repository: RepositoryBindingRepository,
        assessment_repository: RepositoryAssessmentRepository,
        standards_repository: StandardsRepository,
        architecture_reference_repository: ArchitectureReferenceRepository,
        session_service: SessionService,
        orchestrator: AgentOrchestrator,
        approval_service: ApprovalService,
        governance_service: GovernanceService,
        capability_catalog: ModernizationCapabilityCatalog,
    ) -> None:
        self._client = client
        self._plan_repository = plan_repository
        self._binding_repository = binding_repository
        self._assessment_repository = assessment_repository
        self._standards_repository = standards_repository
        self._architecture_reference_repository = architecture_reference_repository
        self._session_service = session_service
        self._orchestrator = orchestrator
        self._approval_service = approval_service
        self._governance_service = governance_service
        self._capability_catalog = capability_catalog

    async def generate_plan(
        self,
        *,
        session_id: str,
        binding_id: str,
        assessment_id: str,
        capability_id: str,
        target: str | None,
        requesting_user_id: str,
        trace_id: str,
        standards_snapshot_id: str | None = None,
        architecture_reference_snapshot_id: str | None = None,
    ) -> ModernizationPlan:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        binding = await self._binding_repository.get(binding_id=binding_id)
        assessment = await self._assessment_repository.get(assessment_id=assessment_id)
        if (
            binding is None
            or binding.session_id != session_id
            or binding.owner_user_id != requesting_user_id
            or binding.purpose != "code"
            or binding.status not in {"validated", "approved"}
        ):
            raise ModernizationError("An active Code repository binding is required.")
        if assessment is None or assessment.session_id != session_id:
            raise ModernizationError("Repository assessment was not found for this session.")
        if assessment.binding_id != binding.id or assessment.commit != binding.resolved_commit:
            raise ModernizationError("Assessment does not match the active immutable binding.")

        # Optional, exactly like the architecture reference below: a user
        # may supply their own opinionated standards (a "standards"-purpose
        # binding) so the generated plan is constrained by them; if absent,
        # Genie applies its own best-practice judgment instead of failing
        # closed - standards are a quality aid here, not a precondition.
        standards_json = "{}"
        if standards_snapshot_id:
            standards = await self._standards_repository.get(snapshot_id=standards_snapshot_id)
            if standards is None or standards.session_id != session_id:
                raise ModernizationError("Standards snapshot was not found for this session.")
            standards_json = standards.model_dump_json()

        # Optional: a user may supply their own opinionated architecture
        # reference (an "architecture"-purpose binding) so the generated
        # plan aligns with their vision; if absent, Genie decides the
        # architecture itself (Microsoft Azure Architecture Center guidance
        # + available IQ context) - see _NO_ARCHITECTURE_REFERENCE_TEXT.
        architecture_reference_text = _NO_ARCHITECTURE_REFERENCE_TEXT
        if architecture_reference_snapshot_id:
            architecture_reference = await self._architecture_reference_repository.get(
                snapshot_id=architecture_reference_snapshot_id
            )
            if architecture_reference is None or architecture_reference.session_id != session_id:
                raise ModernizationError(
                    "Architecture reference snapshot was not found for this session."
                )
            if architecture_reference.combined_reference_text.strip():
                architecture_reference_text = architecture_reference.combined_reference_text

        capability = self._capability_catalog.get(capability_id)
        instruction = capability.instruction(target)
        result = await self._orchestrator.execute_agent(
            agent_id="build-agent",
            prompt_id="modernization-plan-v1",
            variables={
                "repository_full_name": binding.repository_full_name,
                "base_commit": binding.resolved_commit,
                "capability_name": capability.name,
                "modernization_instruction": instruction,
                "assessment_json": assessment.model_dump_json(),
                "standards_json": standards_json,
                "architecture_reference_text": architecture_reference_text,
            },
            session_id=session_id,
            trace_id=trace_id,
        )
        try:
            generated = _GeneratedPlan.model_validate(json.loads(result.output_text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ModernizationError(
                "The Foundry Build Agent returned an invalid modernization plan contract."
            ) from exc

        now = datetime.now(UTC)
        plan_id = str(uuid4())
        plan = ModernizationPlan(
            id=plan_id,
            session_id=session_id,
            binding_id=binding.id,
            assessment_id=assessment.id,
            standards_snapshot_id=standards_snapshot_id,
            repository_full_name=binding.repository_full_name,
            base_commit=binding.resolved_commit,
            base_ref=binding.requested_ref,
            goal=instruction,
            capability_id=capability.id,
            capability_name=capability.name,
            target=target.strip() if target else None,
            architecture_reference_snapshot_id=architecture_reference_snapshot_id,
            summary=generated.summary,
            changes=generated.changes,
            validation_commands=generated.validation_commands,
            residual_risks=generated.residual_risks,
            rollback=generated.rollback,
            branch_name=f"genie/modernize-{plan_id[:8]}",
            created_at=now,
            updated_at=now,
        )
        approval = await self._approval_service.request_approval(
            checkpoint_id="modernization-pr-approval",
            session_id=session_id,
            trace_id=trace_id,
            requested_by_agent_id="build-agent",
            subject_type="modernization_plan",
            subject_id=plan.id,
        )
        plan = plan.model_copy(
            update={
                "status": "pending_approval",
                "approval_request_id": approval.id,
                "updated_at": datetime.now(UTC),
            },
            deep=True,
        )
        await self._plan_repository.put(plan)
        return plan

    async def execute_plan(
        self,
        *,
        session_id: str,
        plan_id: str,
        requesting_user_id: str,
        trace_id: str,
    ) -> ModernizationPlan:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        plan = await self._owned_plan(session_id=session_id, plan_id=plan_id)
        if not plan.approval_request_id:
            raise ModernizationError("Modernization plan has no approval request.")
        approval = await self._approval_service.get_request(plan.approval_request_id)
        if (
            approval is None
            or approval.status != "approved"
            or approval.subject_id != plan.id
            or approval.subject_type != "modernization_plan"
        ):
            raise ModernizationError("Modernization plan requires an approved governance decision.")
        client = self._require_client()
        owner, repository = self._split_repository(plan.repository_full_name)
        executing = plan.model_copy(
            update={"status": "executing", "updated_at": datetime.now(UTC)},
            deep=True,
        )
        await self._plan_repository.put(executing)
        try:
            await client.call_tool(
                "create_branch",
                {
                    "owner": owner,
                    "repo": repository,
                    "branch": plan.branch_name,
                    "from_branch": plan.base_ref,
                },
            )
            await client.call_tool(
                "push_files",
                {
                    "owner": owner,
                    "repo": repository,
                    "branch": plan.branch_name,
                    "message": f"Apply approved modernization plan {plan.id}",
                    "files": [
                        {"path": change.path, "content": change.content}
                        for change in plan.changes
                    ],
                },
            )
            for change in plan.changes:
                await client.call_tool(
                    "get_file_contents",
                    {
                        "owner": owner,
                        "repo": repository,
                        "path": change.path,
                        "ref": plan.branch_name,
                    },
                )
            pull_request_result = GitHubMcpClient.tool_content(
                await client.call_tool(
                    "create_pull_request",
                    {
                        "owner": owner,
                        "repo": repository,
                        "title": plan.summary,
                        "head": plan.branch_name,
                        "base": plan.base_ref,
                        "body": self._pull_request_body(plan),
                        "draft": True,
                    },
                )
            )
        except GitHubMcpError as exc:
            failed = executing.model_copy(
                update={"status": "failed", "updated_at": datetime.now(UTC)},
                deep=True,
            )
            await self._plan_repository.put(failed)
            raise ModernizationError(str(exc)) from exc
        pull_request_url = self._find_pull_request_url(pull_request_result)
        if not pull_request_url:
            raise ModernizationError("GitHub MCP did not return a pull request URL.")
        completed = executing.model_copy(
            update={
                "status": "pull_request_opened",
                "pull_request_url": pull_request_url,
                "updated_at": datetime.now(UTC),
            },
            deep=True,
        )
        await self._plan_repository.put(completed)
        await self._governance_service.record_tool_request(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="modernization-service",
            tool_name="github_mcp.create_pull_request",
            detail={
                "plan_id": plan.id,
                "repository_full_name": plan.repository_full_name,
                "base_commit": plan.base_commit,
                "branch_name": plan.branch_name,
                "pull_request_url": pull_request_url,
                "changed_paths": [change.path for change in plan.changes],
            },
        )
        return completed

    async def list_plans(
        self, *, session_id: str, requesting_user_id: str
    ) -> list[ModernizationPlan]:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        return await self._plan_repository.list_for_session(session_id=session_id)

    async def list_capabilities(
        self, *, session_id: str, requesting_user_id: str
    ) -> list[ModernizationCapability]:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        return self._capability_catalog.capabilities

    async def _owned_plan(self, *, session_id: str, plan_id: str) -> ModernizationPlan:
        plan = await self._plan_repository.get(plan_id=plan_id)
        if plan is None or plan.session_id != session_id:
            raise ModernizationError("Modernization plan was not found for this session.")
        return plan

    def _require_client(self) -> GitHubMcpClient:
        if self._client is None:
            raise ModernizationError("GitHub MCP is not configured.")
        return self._client

    @staticmethod
    def _split_repository(full_name: str) -> tuple[str, str]:
        parts = full_name.split("/")
        if len(parts) != 2 or not all(parts):
            raise ModernizationError("Repository name must use the 'owner/name' format.")
        return parts[0], parts[1]

    @staticmethod
    def _pull_request_body(plan: ModernizationPlan) -> str:
        commands = "\n".join(f"- `{command}`" for command in plan.validation_commands)
        risks = "\n".join(f"- {risk}" for risk in plan.residual_risks) or "- None declared"
        return (
            f"## Approved modernization plan\n\n{plan.summary}\n\n"
            f"Base commit: `{plan.base_commit}`\n\n"
            f"## Required live validation\n{commands}\n\n"
            f"## Residual risks\n{risks}\n\n"
            f"## Rollback\n{plan.rollback}\n"
        )

    @classmethod
    def _find_pull_request_url(cls, value: Any) -> str | None:
        if isinstance(value, str):
            match = _URL_PATTERN.search(value)
            return match.group(0) if match else None
        if isinstance(value, dict):
            for key in ("html_url", "url"):
                nested = value.get(key)
                if isinstance(nested, str) and _URL_PATTERN.fullmatch(nested):
                    return nested
            for nested in value.values():
                found = cls._find_pull_request_url(nested)
                if found:
                    return found
        if isinstance(value, list):
            for nested in value:
                found = cls._find_pull_request_url(nested)
                if found:
                    return found
        return None
