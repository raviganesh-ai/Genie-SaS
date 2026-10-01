"""Development-only, explicit-action Work IQ end-to-end validation.

Deliberately separate from ``IqEvidenceService.retrieve(...)``: that path
persists governed evidence for later human review (by design - that is
its job). This validation action must NOT persist anything and must NOT
log the retrieved content, per the development-validation boundaries it
was built for - it exists purely to prove, once, that a real delegated
Work IQ retrieval works end to end, using a fixed low-risk query.
"""
from __future__ import annotations

import json
import time
from uuid import uuid4

from app.governance.governance_service import GovernanceService
from app.iq.citations import extract_citations
from app.iq.delegated_connection_manager import DelegatedConnectionError
from app.iq.delegated_connection_service import DelegatedConnectionService
from app.iq.delegated_token_broker import DelegatedAuthError
from app.iq.mcp_client import IqMcpError
from app.iq.models import WorkIqValidationResult
from app.services.session_service import SessionService

# Deliberately fixed and low-risk - this action never accepts an
# arbitrary caller-supplied query, so it cannot be repurposed into a
# general free-text Work IQ query interface that bypasses the governed
# evidence-retrieval workflow.
_TEST_QUERY = "Summarize my upcoming meetings for today."
_PREVIEW_MAX_CHARS = 200


class WorkIqValidationService:
    def __init__(
        self,
        *,
        connection_service: DelegatedConnectionService,
        session_service: SessionService,
        governance_service: GovernanceService,
        retrieve_tool: str,
        query_argument: str,
    ) -> None:
        self._connection_service = connection_service
        self._session_service = session_service
        self._governance_service = governance_service
        self._retrieve_tool = retrieve_tool
        self._query_argument = query_argument

    async def validate(self, *, session_id: str, requesting_user_id: str) -> WorkIqValidationResult:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        correlation_id = str(uuid4())
        started = time.monotonic()

        try:
            ready = await self._connection_service.get_ready_connection(
                session_id=session_id, provider="work_iq"
            )
        except (DelegatedConnectionError, DelegatedAuthError) as exc:
            return self._result(
                success=False,
                tool_invoked=None,
                correlation_id=correlation_id,
                started=started,
                error_category=getattr(exc, "category", "authentication_required"),
                detail="No active Work IQ connection for this session.",
            )
        if ready is None:
            return self._result(
                success=False,
                tool_invoked=None,
                correlation_id=correlation_id,
                started=started,
                error_category="authentication_required",
                detail="Connect Microsoft 365 (Work IQ) before running this validation.",
            )
        client, _identity = ready

        try:
            tools = await client.list_tools()
        except IqMcpError as exc:
            return self._result(
                success=False,
                tool_invoked=None,
                correlation_id=correlation_id,
                started=started,
                error_category=exc.category,
                detail="Work IQ tools/list failed.",
            )
        if self._retrieve_tool not in tools:
            return self._result(
                success=False,
                tool_invoked=None,
                correlation_id=correlation_id,
                started=started,
                error_category="unavailable",
                detail=f"Configured tool '{self._retrieve_tool}' was not found via tools/list.",
            )

        try:
            content = await client.call_tool(
                name=self._retrieve_tool, arguments={self._query_argument: _TEST_QUERY}
            )
        except IqMcpError as exc:
            await self._record(
                session_id=session_id,
                trace_id=correlation_id,
                success=False,
                error_category=exc.category,
            )
            return self._result(
                success=False,
                tool_invoked=self._retrieve_tool,
                correlation_id=correlation_id,
                started=started,
                error_category=exc.category,
                detail="Work IQ tools/call failed.",
            )

        citations = extract_citations(content)
        await self._record(
            session_id=session_id,
            trace_id=correlation_id,
            success=True,
            citation_count=len(citations),
        )
        return self._result(
            success=True,
            tool_invoked=self._retrieve_tool,
            correlation_id=correlation_id,
            started=started,
            citations=citations,
            response_preview=self._safe_preview(content),
            detail="Work IQ retrieval succeeded.",
        )

    async def _record(
        self,
        *,
        session_id: str,
        trace_id: str,
        success: bool,
        error_category: str | None = None,
        citation_count: int | None = None,
    ) -> None:
        # Safe telemetry only - never the query result or any Microsoft
        # 365 content, per the development-validation boundary.
        detail: dict[str, object] = {"success": success}
        if error_category is not None:
            detail["error_category"] = error_category
        if citation_count is not None:
            detail["citation_count"] = citation_count
        await self._governance_service.record_tool_request(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="work-iq-validation-service",
            tool_name=f"work_iq.{self._retrieve_tool}",
            detail=detail,
        )

    @staticmethod
    def _safe_preview(content: object) -> str:
        serialized = content if isinstance(content, str) else json.dumps(content, default=str, ensure_ascii=True)
        if len(serialized) <= _PREVIEW_MAX_CHARS:
            return serialized
        return serialized[:_PREVIEW_MAX_CHARS] + "... (truncated)"

    @staticmethod
    def _result(
        *,
        success: bool,
        tool_invoked: str | None,
        correlation_id: str,
        started: float,
        error_category: str | None = None,
        citations: list[str] | None = None,
        response_preview: str | None = None,
        detail: str,
    ) -> WorkIqValidationResult:
        return WorkIqValidationResult(
            success=success,
            provider="work_iq",
            tool_invoked=tool_invoked,
            response_preview=response_preview,
            citations=citations or [],
            correlation_id=correlation_id,
            duration_ms=(time.monotonic() - started) * 1000,
            error_category=error_category,
            detail=detail,
        )
