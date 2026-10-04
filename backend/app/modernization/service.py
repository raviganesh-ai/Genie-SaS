"""Foundry-generated, approval-gated GitHub modernization pull requests."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.discovery.models import CostEstimate, PricingQuery
from app.discovery.pricing_service import PricingService
from app.governance.approval_service import ApprovalService
from app.governance.governance_service import GovernanceService
from app.modernization.capabilities import ModernizationCapability, ModernizationCapabilityCatalog
from app.modernization.models import (
    ModernizationFileChange,
    ModernizationPlan,
    ModernizationPlanChatAnswer,
    ModernizationProposedComponent,
)
from app.modernization.parsing import ModernizationAgentResponseError, parse_agent_response
from app.modernization.repository import ModernizationPlanRepository
from app.orchestration.agent_orchestrator import AgentOrchestrator
from app.platform_config.repository import PlatformReferenceRepositoryStore
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

# Returned when no PricingService is configured for this environment (it is
# an optional dependency - see ModernizationService.__init__) - mirrors
# AzureRetailPricingService.estimate()'s own "no queries" fallback shape, so
# plan generation always succeeds and the frontend sees one consistent,
# honestly-labeled "unavailable" cost shape rather than a missing field.
_PRICING_UNAVAILABLE = CostEstimate(
    region="unknown",
    coverage="unavailable",
    assumptions=["Azure retail pricing is not configured for this environment."],
)

# Allowlisted top-level ModernizationPlan field names the chat answer may
# cite as `referenced_fields` (see ModernizationService.ask) - a small,
# static set (unlike RepositoryAssessmentService.ask's dynamic per-file
# path allowlist) since a plan's own shape never varies.
_PLAN_CHAT_REFERENCEABLE_FIELDS = {
    "summary",
    "rewrite_strategy",
    "proposed_components",
    "deployment_plan",
    "changes",
    "validation_commands",
    "residual_risks",
    "rollback",
    "estimated_cost",
}


class ModernizationError(RuntimeError):
    """Raised when a governed modernization action cannot complete."""


class _GeneratedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    rewrite_strategy: str = Field(min_length=1)
    proposed_components: list[ModernizationProposedComponent] = Field(default_factory=list)
    deployment_plan: list[str] = Field(min_length=1)
    changes: list[ModernizationFileChange] = Field(min_length=1)
    validation_commands: list[str] = Field(min_length=1)
    residual_risks: list[str] = Field(default_factory=list)
    rollback: str = Field(min_length=1)
    pricing_queries: list[PricingQuery] = Field(default_factory=list)
    illustrative_pricing_queries: list[PricingQuery] = Field(default_factory=list)

    @model_validator(mode="after")
    def _depends_on_reference_known_components(self) -> _GeneratedPlan:
        known_ids = {component.id for component in self.proposed_components}
        unknown = sorted(
            {
                dependency
                for component in self.proposed_components
                for dependency in component.depends_on
                if dependency not in known_ids
            }
        )
        if unknown:
            raise ValueError(
                f"proposed_components depends_on references unknown component id(s): {unknown}"
            )
        return self


class _PlanChatAnswerEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    referenced_fields: list[str] = Field(default_factory=list)


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
        platform_reference_repository_store: PlatformReferenceRepositoryStore | None = None,
        pricing_service: PricingService | None = None,
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
        self._platform_reference_repository_store = platform_reference_repository_store
        self._pricing_service = pricing_service

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
        refinement_notes: str | None = None,
        previous_plan_id: str | None = None,
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

        # A "refine this plan" request (see ask()'s chat-driven refinement
        # flow) is simply generate_plan called again with the prior plan's
        # own JSON plus the user's free-text feedback appended to the
        # prompt - this produces a brand-new, independently approvable
        # plan rather than mutating the original in place, mirroring
        # Discovery's "ideate an additional solution" pattern (an
        # additional candidate, not a silent edit of an already-reviewed
        # one). previous_plan_json intentionally omits full file contents
        # (paths/reasons only) to keep the prompt bounded.
        previous_plan_json = "{}"
        cleaned_refinement_notes = (refinement_notes or "").strip()
        if previous_plan_id:
            previous_plan = await self._plan_repository.get(plan_id=previous_plan_id)
            if previous_plan is None or previous_plan.session_id != session_id:
                raise ModernizationError("Previous modernization plan was not found for this session.")
            previous_plan_json = json.dumps(
                {
                    "summary": previous_plan.summary,
                    "rewrite_strategy": previous_plan.rewrite_strategy,
                    "proposed_components": [
                        component.model_dump(mode="json")
                        for component in previous_plan.proposed_components
                    ],
                    "deployment_plan": previous_plan.deployment_plan,
                    "changed_file_paths_and_reasons": [
                        {"path": change.path, "reason": change.reason}
                        for change in previous_plan.changes
                    ],
                    "residual_risks": previous_plan.residual_risks,
                }
            )

        # Optional, exactly like the architecture reference below: a user
        # may supply their own opinionated standards (a "standards"-purpose
        # binding) so the generated plan is constrained by them; if absent,
        # fall back to any administrator-configured platform-level standards
        # repositories (see app.platform_config); if there are none of those
        # either, Genie applies its own best-practice judgment instead of
        # failing closed - standards are a quality aid here, not a
        # precondition.
        standards_json = "{}"
        if standards_snapshot_id:
            standards = await self._standards_repository.get(snapshot_id=standards_snapshot_id)
            if standards is None or standards.session_id != session_id:
                raise ModernizationError("Standards snapshot was not found for this session.")
            standards_json = standards.model_dump_json()
        elif self._platform_reference_repository_store is not None:
            platform_repositories = await self._platform_reference_repository_store.list_all()
            platform_rules = [
                rule.model_dump(mode="json")
                for repository in platform_repositories
                if repository.purpose == "standards"
                for rule in repository.rules
            ]
            if platform_rules:
                standards_json = json.dumps({"rules": platform_rules})

        # Optional: a user may supply their own opinionated architecture
        # reference (an "architecture"-purpose binding) so the generated
        # plan aligns with their vision; if absent, fall back to any
        # administrator-configured platform-level architecture repositories;
        # if there are none of those either, Genie decides the architecture
        # itself (Microsoft Azure Architecture Center guidance + available
        # IQ context) - see _NO_ARCHITECTURE_REFERENCE_TEXT.
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
        elif self._platform_reference_repository_store is not None:
            platform_repositories = await self._platform_reference_repository_store.list_all()
            platform_texts = [
                repository.combined_reference_text
                for repository in platform_repositories
                if repository.purpose == "architecture"
                and repository.combined_reference_text
                and repository.combined_reference_text.strip()
            ]
            if platform_texts:
                architecture_reference_text = "\n\n---\n\n".join(platform_texts)

        capability = self._capability_catalog.get(capability_id)
        instruction = capability.instruction(target)
        variables = {
            "repository_full_name": binding.repository_full_name,
            "base_commit": binding.resolved_commit,
            "capability_name": capability.name,
            "modernization_instruction": instruction,
            "assessment_json": assessment.model_dump_json(),
            "standards_json": standards_json,
            "architecture_reference_text": architecture_reference_text,
            "previous_plan_json": previous_plan_json,
            "refinement_notes": cleaned_refinement_notes,
            "retry_instruction": "",
        }
        generated = await self._generate_plan_contents(
            variables=variables, session_id=session_id, trace_id=trace_id
        )
        estimated_cost = await self._estimate_plan_cost(generated)

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
            previous_plan_id=previous_plan_id,
            refinement_notes=cleaned_refinement_notes or None,
            summary=generated.summary,
            rewrite_strategy=generated.rewrite_strategy,
            proposed_components=generated.proposed_components,
            deployment_plan=generated.deployment_plan,
            changes=generated.changes,
            validation_commands=generated.validation_commands,
            residual_risks=generated.residual_risks,
            rollback=generated.rollback,
            pricing_queries=generated.pricing_queries,
            illustrative_pricing_queries=generated.illustrative_pricing_queries,
            estimated_cost=estimated_cost,
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

    async def _generate_plan_contents(
        self,
        *,
        variables: dict[str, str],
        session_id: str,
        trace_id: str,
    ) -> _GeneratedPlan:
        """Calls the Build Agent and strictly parses its JSON contract,
        retrying once with an explicit correction instruction if the first
        response is malformed, truncated, or schema-invalid - the same
        resilience pattern already used for the code-analyst and other
        Foundry agents in this codebase, since an occasional malformed LLM
        response (e.g. wrapped in Markdown fences despite being told not
        to) should not fail the entire plan generation outright."""
        for attempt in range(2):
            result = await self._orchestrator.execute_agent(
                agent_id="build-agent",
                prompt_id="modernization-plan-v1",
                variables=variables,
                session_id=session_id,
                trace_id=trace_id,
            )
            try:
                return parse_agent_response(result.output_text, _GeneratedPlan)
            except ModernizationAgentResponseError as exc:
                if attempt == 1:
                    raise ModernizationError(
                        f"The Foundry Build Agent returned an invalid modernization plan "
                        f"contract: {exc}"
                    ) from exc
                variables["retry_instruction"] = (
                    "A prior response was malformed, truncated, or schema-invalid. "
                    f"Correct these exact validation issues: {exc} Regenerate the complete "
                    "response as fresh JSON with no Markdown fences."
                )
        raise ModernizationError("Modernization plan generation retry loop exited unexpectedly.")

    async def _estimate_plan_cost(self, generated: _GeneratedPlan) -> CostEstimate:
        """Resolves the plan's real, incremental cost from pricing_queries
        when present. When the Build Agent left pricing_queries empty
        (this capability doesn't change hosting costs - see
        modernization-plan-v1's prompt), falls back to a clearly-marked
        illustrative baseline from illustrative_pricing_queries if the
        agent supplied one, so the user sees a labeled estimate instead of
        a bare "Unavailable" whenever a reasonable baseline exists."""
        if self._pricing_service is None:
            return _PRICING_UNAVAILABLE
        if generated.pricing_queries:
            return await self._pricing_service.estimate(generated.pricing_queries)
        if generated.illustrative_pricing_queries:
            illustrative = await self._pricing_service.estimate(
                generated.illustrative_pricing_queries
            )
            if illustrative.coverage != "unavailable":
                return illustrative.model_copy(update={"is_illustrative": True})
        return _PRICING_UNAVAILABLE

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

    async def ask(
        self,
        *,
        session_id: str,
        plan_id: str,
        requesting_user_id: str,
        message: str,
        trace_id: str,
    ) -> ModernizationPlanChatAnswer:
        """Answers one free-text question about an already-generated
        modernization plan. Facts about the specific repository/plan are
        grounded only in that plan's own JSON, never requiring the
        repository to be re-read - but advisory "how do we..." questions
        about cross-cutting concerns (security, reliability, etc.) may also
        draw on genuine Azure Well-Architected Framework guidance, mirroring
        the same allowance already granted during plan generation (see
        modernization-plan-chat-v1's prompt template). Mirrors
        RepositoryAssessmentService.ask's identical contract and retry
        behavior; see that method's docstring for why this fails closed
        (raises) rather than returning a degraded answer."""
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        cleaned_message = message.strip()
        if not cleaned_message:
            raise ModernizationError("Describe what you'd like to know about this plan.")
        plan = await self._owned_plan(session_id=session_id, plan_id=plan_id)
        plan_json = plan.model_dump_json(
            include={
                "summary",
                "rewrite_strategy",
                "proposed_components",
                "deployment_plan",
                "changes",
                "validation_commands",
                "residual_risks",
                "rollback",
                "estimated_cost",
                "capability_name",
                "target",
            }
        )
        variables = {
            "plan_json": plan_json,
            "question": cleaned_message,
            "retry_instruction": "",
        }
        for attempt in range(2):
            result = await self._orchestrator.execute_agent(
                agent_id="build-agent",
                prompt_id="modernization-plan-chat-v1",
                variables=variables,
                session_id=session_id,
                trace_id=f"{trace_id}:modernization-chat",
            )
            try:
                envelope = parse_agent_response(result.output_text, _PlanChatAnswerEnvelope)
                break
            except ModernizationAgentResponseError as exc:
                if attempt == 1:
                    raise ModernizationError(str(exc)) from exc
                variables["retry_instruction"] = (
                    "A prior response was malformed, truncated, or schema-invalid. "
                    f"Correct these exact validation issues: {exc} Regenerate the "
                    "complete response as fresh JSON."
                )
        else:
            raise ModernizationError("Modernization plan chat retry loop exited unexpectedly.")
        answer = ModernizationPlanChatAnswer(
            question=cleaned_message,
            answer=envelope.answer,
            referenced_fields=[
                field for field in envelope.referenced_fields
                if field in _PLAN_CHAT_REFERENCEABLE_FIELDS
            ],
            generated_at=datetime.now(UTC),
        )
        await self._governance_service.record_tool_request(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="modernization-service",
            tool_name="build_agent.ask",
            detail={
                "plan_id": plan.id,
                "question": cleaned_message,
                "referenced_field_count": len(answer.referenced_fields),
            },
        )
        return answer

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
