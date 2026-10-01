"""Governed IQ capability discovery, normalization, review, and promotion."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.agents.models import AgentDefinition
from app.governance.governance_service import GovernanceService
from app.iq.citations import extract_citations
from app.iq.delegated_connection_service import (
    DelegatedAuthError,
    DelegatedConnectionError,
    DelegatedConnectionService,
)
from app.iq.mcp_client import IqMcpClient, IqMcpError, IqMcpErrorCategory
from app.iq.models import (
    DELEGATED_PROVIDERS,
    CandidateStatus,
    DelegatedAuthErrorCategoryName,
    IqCapability,
    IqEvidenceCandidate,
    IqEvidenceEnvelope,
    IqProviderName,
    IqProviderStatus,
    IqStatus,
)
from app.iq.repository import IqEvidenceRepository
from app.iq.router import IQRouter
from app.memory.memory_service import MemoryService
from app.services.session_service import SessionService

_ERROR_CATEGORY_TO_STATUS: dict[IqMcpErrorCategory, IqStatus] = {
    "authentication_required": "IQ_AUTHENTICATION_REQUIRED",
    "permission_denied": "IQ_PERMISSION_DENIED",
    "timeout": "IQ_TIMEOUT",
    "unavailable": "IQ_UNAVAILABLE",
    # The status vocabulary Genie agents/UI consume has no distinct
    # "malformed" state - a malformed MCP response is itself a form of the
    # provider being unavailable/untrustworthy right now.
    "malformed_response": "IQ_UNAVAILABLE",
}

_DELEGATED_ERROR_CATEGORY_TO_STATUS: dict[DelegatedAuthErrorCategoryName, IqStatus] = {
    "authentication_required": "IQ_AUTHENTICATION_REQUIRED",
    "consent_required": "IQ_CONSENT_REQUIRED",
    "session_expired": "IQ_SESSION_EXPIRED",
    "tenant_mismatch": "IQ_TENANT_MISMATCH",
    "permission_denied": "IQ_PERMISSION_DENIED",
}


class IqEvidenceError(RuntimeError):
    """Raised when governed IQ evidence processing cannot complete."""

    def __init__(self, message: str, *, status: IqStatus = "IQ_UNAVAILABLE") -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class IqProviderRegistration:
    name: IqProviderName
    enabled: bool
    # Static/admin-token providers (Foundry IQ, Foundry MCP) set `client`;
    # delegated providers (Work IQ, Fabric IQ) leave it `None` - their
    # connection is resolved per-session through `DelegatedConnectionService`.
    client: IqMcpClient | None
    retrieve_tool: str | None
    query_argument: str


class IqEvidenceService:
    def __init__(
        self,
        *,
        providers: list[IqProviderRegistration],
        repository: IqEvidenceRepository,
        session_service: SessionService,
        governance_service: GovernanceService,
        memory_service: MemoryService,
        promoter_agent: AgentDefinition,
        router: IQRouter | None = None,
        delegated_connection_service: DelegatedConnectionService | None = None,
    ) -> None:
        self._providers = {provider.name: provider for provider in providers}
        self._repository = repository
        self._session_service = session_service
        self._governance_service = governance_service
        self._memory_service = memory_service
        self._promoter_agent = promoter_agent
        self._router = router or IQRouter()
        self._delegated_connection_service = delegated_connection_service

    async def provider_statuses(self) -> list[IqProviderStatus]:
        return [await self._provider_status(provider) for provider in self._providers.values()]

    async def retrieve_by_capability(
        self,
        *,
        session_id: str,
        requesting_user_id: str,
        capability: IqCapability,
        query: str,
        sensitivity: str,
        trace_id: str,
    ) -> IqEvidenceCandidate:
        """Capability-first entry point: resolves the provider via the IQ
        router so callers (agents, API routes) never name a Microsoft
        service directly."""
        provider_name = self._router.route(capability)
        return await self.retrieve(
            session_id=session_id,
            requesting_user_id=requesting_user_id,
            provider_name=provider_name,
            query=query,
            sensitivity=sensitivity,
            trace_id=trace_id,
        )

    async def retrieve(
        self,
        *,
        session_id: str,
        requesting_user_id: str,
        provider_name: IqProviderName,
        query: str,
        sensitivity: str,
        trace_id: str,
    ) -> IqEvidenceCandidate:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        provider = self._require_provider(provider_name)
        if not provider.enabled:
            raise IqEvidenceError(f"IQ provider '{provider_name}' is disabled.", status="IQ_NOT_CONFIGURED")
        if provider_name in DELEGATED_PROVIDERS:
            content = await self._call_delegated_retrieve_tool(
                provider=provider, session_id=session_id, query=query
            )
        else:
            content = await self._call_static_retrieve_tool(provider=provider, query=query)
        serialized = json.dumps(content, sort_keys=True, default=str, ensure_ascii=True)
        evidence = IqEvidenceEnvelope(
            id=str(uuid4()),
            session_id=session_id,
            provider=provider_name,
            query=query,
            content=content,
            citations=self._extract_citations(content),
            sensitivity=sensitivity,
            authorization_principal=requesting_user_id,
            retrieved_at=datetime.now(UTC),
            raw_content_hash=hashlib.sha256(serialized.encode()).hexdigest(),
        )
        candidate = IqEvidenceCandidate(
            id=str(uuid4()),
            session_id=session_id,
            evidence=evidence,
        )
        await self._repository.put(candidate)
        await self._governance_service.record_tool_request(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="iq-evidence-service",
            tool_name=f"{provider_name}.{provider.retrieve_tool}",
            detail={
                "candidate_id": candidate.id,
                "evidence_id": evidence.id,
                "content_hash": evidence.raw_content_hash,
                "citation_count": len(evidence.citations),
                "sensitivity": evidence.sensitivity,
            },
        )
        return candidate

    async def list_candidates(
        self, *, session_id: str, requesting_user_id: str
    ) -> list[IqEvidenceCandidate]:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        return await self._repository.list_for_session(session_id=session_id)

    async def review(
        self,
        *,
        session_id: str,
        candidate_id: str,
        requesting_user_id: str,
        status: CandidateStatus,
        comment: str | None,
        trace_id: str,
    ) -> IqEvidenceCandidate:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        if status not in {"confirmed", "rejected", "unresolved", "superseded"}:
            raise IqEvidenceError("Review status must be a review decision.")
        candidate = await self._owned_candidate(session_id=session_id, candidate_id=candidate_id)
        updated = candidate.model_copy(
            update={
                "status": status,
                "review_comment": comment,
                "reviewed_by": requesting_user_id,
                "reviewed_at": datetime.now(UTC),
            },
            deep=True,
        )
        await self._repository.put(updated)
        await self._governance_service.record_policy_evaluation(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="iq-evidence-service",
            policy_name="iq-candidate-review",
            allowed=status == "confirmed",
            detail={"candidate_id": candidate.id, "decision": status},
        )
        return updated

    async def promote(
        self,
        *,
        session_id: str,
        candidate_id: str,
        requesting_user_id: str,
        trace_id: str,
    ) -> IqEvidenceCandidate:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        candidate = await self._owned_candidate(session_id=session_id, candidate_id=candidate_id)
        if candidate.status != "confirmed":
            raise IqEvidenceError("Only confirmed IQ evidence can enter shared memory.")
        await self._memory_service.shared.write(
            agent=self._promoter_agent,
            session_id=session_id,
            trace_id=trace_id,
            key=f"iq-evidence:{candidate.id}",
            classification="architecture_finding",
            content={
                "provider": candidate.evidence.provider,
                "query": candidate.evidence.query,
                "content": candidate.evidence.content,
                "citations": candidate.evidence.citations,
                "sensitivity": candidate.evidence.sensitivity,
                "content_hash": candidate.evidence.raw_content_hash,
            },
            approval_status="approved",
            evidence_references=[
                f"iq:{candidate.evidence.provider}:{candidate.evidence.id}",
                *candidate.evidence.citations,
            ],
            confidence_score=1.0,
        )
        promoted = candidate.model_copy(update={"status": "promoted"}, deep=True)
        await self._repository.put(promoted)
        return promoted

    async def _call_delegated_retrieve_tool(
        self, *, provider: IqProviderRegistration, session_id: str, query: str
    ) -> Any:
        if self._delegated_connection_service is None or not provider.retrieve_tool:
            raise IqEvidenceError(
                f"IQ provider '{provider.name}' is not configured for delegated retrieval.",
                status="IQ_NOT_CONFIGURED",
            )
        try:
            ready = await self._delegated_connection_service.get_ready_connection(
                session_id=session_id, provider=provider.name
            )
        except (DelegatedConnectionError, DelegatedAuthError) as exc:
            category = getattr(exc, "category", "authentication_required")
            raise IqEvidenceError(
                str(exc), status=_DELEGATED_ERROR_CATEGORY_TO_STATUS.get(category, "IQ_UNAVAILABLE")
            ) from exc
        if ready is None:
            raise IqEvidenceError(
                f"No delegated {provider.name} connection exists for this session. "
                "Connect Microsoft 365 first.",
                status="IQ_AUTHENTICATION_REQUIRED",
            )
        client, _identity = ready
        try:
            return await client.call_tool(
                name=provider.retrieve_tool,
                arguments={provider.query_argument: query},
            )
        except IqMcpError as exc:
            raise IqEvidenceError(
                str(exc), status=_ERROR_CATEGORY_TO_STATUS[exc.category]
            ) from exc

    async def _call_static_retrieve_tool(
        self, *, provider: IqProviderRegistration, query: str
    ) -> Any:
        if provider.client is None or not provider.retrieve_tool:
            raise IqEvidenceError(
                f"IQ provider '{provider.name}' configuration is incomplete.",
                status="IQ_NOT_CONFIGURED",
            )
        try:
            return await provider.client.call_tool(
                name=provider.retrieve_tool,
                arguments={provider.query_argument: query},
            )
        except IqMcpError as exc:
            raise IqEvidenceError(
                str(exc), status=_ERROR_CATEGORY_TO_STATUS[exc.category]
            ) from exc

    async def _provider_status(self, provider: IqProviderRegistration) -> IqProviderStatus:
        if not provider.enabled:
            return IqProviderStatus(
                provider=provider.name,
                status="IQ_NOT_CONFIGURED",
                enabled=False,
                connected=False,
                detail="Provider is disabled.",
            )
        if provider.name in DELEGATED_PROVIDERS:
            # Delegated connection state is inherently per-session (per
            # signed-in Microsoft identity) - this session-less status
            # check can only confirm the provider itself is enabled, never
            # whether any particular session is connected. See
            # GET /sessions/{session_id}/iq/connections for the per-session
            # answer, backed by DelegatedConnectionService.
            if not provider.retrieve_tool:
                return IqProviderStatus(
                    provider=provider.name,
                    status="IQ_NOT_CONFIGURED",
                    enabled=True,
                    connected=False,
                    detail="Provider configuration is incomplete.",
                )
            return IqProviderStatus(
                provider=provider.name,
                status="IQ_AUTHENTICATION_REQUIRED",
                enabled=True,
                connected=False,
                retrieve_tool=provider.retrieve_tool,
                detail=(
                    "Delegated connection required. Each Genie session connects its own "
                    "Microsoft 365 identity via Connect Microsoft 365."
                ),
            )
        if provider.client is None or not provider.retrieve_tool:
            return IqProviderStatus(
                provider=provider.name,
                status="IQ_NOT_CONFIGURED",
                enabled=True,
                connected=False,
                retrieve_tool=provider.retrieve_tool,
                detail="Provider configuration is incomplete.",
            )
        try:
            tools = await provider.client.list_tools()
        except IqMcpError as exc:
            # IQ is enrichment, never a hard dependency - a provider being
            # unreachable, unauthenticated, or timing out must surface as an
            # explicit status, not raise and crash the calling workflow (or,
            # at startup, the whole application). See
            # docs/architecture/genie-sas-microsoft-iq.md "Optional IQ
            # enrichment".
            return IqProviderStatus(
                provider=provider.name,
                status=_ERROR_CATEGORY_TO_STATUS[exc.category],
                enabled=True,
                connected=False,
                retrieve_tool=provider.retrieve_tool,
                detail=str(exc),
            )
        if provider.retrieve_tool not in tools:
            return IqProviderStatus(
                provider=provider.name,
                status="IQ_UNAVAILABLE",
                enabled=True,
                connected=False,
                retrieve_tool=provider.retrieve_tool,
                available_tools=tools,
                detail=f"Configured retrieve tool '{provider.retrieve_tool}' is unavailable.",
            )
        return IqProviderStatus(
            provider=provider.name,
            status="IQ_AVAILABLE",
            enabled=True,
            connected=True,
            retrieve_tool=provider.retrieve_tool,
            available_tools=tools,
            detail="Live MCP capability contract verified.",
        )

    def _require_provider(self, name: IqProviderName) -> IqProviderRegistration:
        provider = self._providers.get(name)
        if provider is None:
            raise IqEvidenceError(f"IQ provider '{name}' is not registered.")
        return provider

    async def _owned_candidate(
        self, *, session_id: str, candidate_id: str
    ) -> IqEvidenceCandidate:
        candidate = await self._repository.get(candidate_id=candidate_id)
        if candidate is None or candidate.session_id != session_id:
            raise IqEvidenceError("IQ evidence candidate was not found for this session.")
        return candidate

    @staticmethod
    def _extract_citations(value: Any) -> list[str]:
        return extract_citations(value)

