"""Grounded Azure Well-Architected Framework and Microsoft-docs Q&A.

Never lets the agent answer from its own trained knowledge alone: every
question first retrieves real Microsoft Learn documents (live, at question
time, via MicrosoftLearnMcpClient), and the agent is instructed to answer
only from that retrieved evidence - citations are additionally validated
against the real retrieved URLs here (not merely trusted from the model's
own response), so a hallucinated citation can never reach the user."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.governance.governance_service import GovernanceService
from app.orchestration.agent_orchestrator import AgentOrchestrator
from app.services.session_service import SessionService
from app.well_architected.microsoft_learn_client import (
    MicrosoftLearnMcpClient,
    MicrosoftLearnMcpError,
)
from app.well_architected.models import DocCitation, WellArchitectedAnswer
from app.well_architected.parsing import WellArchitectedAgentResponseError, parse_agent_response


class WellArchitectedQaError(RuntimeError):
    """Raised when a grounded Well-Architected/Azure-docs answer cannot be produced."""


class _CitationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    url: str


class _AnswerEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    grounded: bool
    citations: list[_CitationDraft] = Field(default_factory=list)


class WellArchitectedQaService:
    def __init__(
        self,
        *,
        learn_client: MicrosoftLearnMcpClient,
        orchestrator: AgentOrchestrator | None,
        session_service: SessionService,
        governance_service: GovernanceService,
        max_search_results: int,
        max_fetched_documents: int,
    ) -> None:
        self._learn_client = learn_client
        self._orchestrator = orchestrator
        self._session_service = session_service
        self._governance_service = governance_service
        self._max_search_results = max_search_results
        self._max_fetched_documents = max_fetched_documents

    async def ask(
        self,
        *,
        session_id: str,
        requesting_user_id: str,
        question: str,
        trace_id: str,
    ) -> WellArchitectedAnswer:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        cleaned_question = question.strip()
        if not cleaned_question:
            raise WellArchitectedQaError(
                "Describe the Well-Architected pillar or Azure service question you'd "
                "like answered."
            )
        if self._orchestrator is None:
            raise WellArchitectedQaError("Azure AI Foundry orchestrator is not configured.")

        try:
            hits = await self._learn_client.search(cleaned_question)
        except MicrosoftLearnMcpError as exc:
            raise WellArchitectedQaError(
                f"Could not retrieve Microsoft documentation: {exc}"
            ) from exc
        hits = hits[: self._max_search_results]

        documents: list[dict[str, str]] = []
        for hit in hits:
            url = str(hit.get("contentUrl") or "").strip()
            if not url:
                continue
            documents.append(
                {
                    "title": str(hit.get("title") or url),
                    "url": url,
                    "search_excerpt": str(hit.get("content") or ""),
                    "evidence_text": str(hit.get("content") or ""),
                }
            )

        if not documents:
            answer = WellArchitectedAnswer(
                question=cleaned_question,
                answer=(
                    "Genie could not find Microsoft documentation that addresses this "
                    "question, so it will not guess - try rephrasing, or ask about a "
                    "specific Well-Architected pillar or Azure service by name."
                ),
                citations=[],
                grounded=False,
                generated_at=datetime.now(UTC),
            )
            await self._record_governance(
                session_id=session_id,
                trace_id=trace_id,
                question=cleaned_question,
                answer=answer,
                document_count=0,
            )
            return answer

        for document in documents[: self._max_fetched_documents]:
            try:
                document["evidence_text"] = (await self._learn_client.fetch(document["url"]))[:6000]
            except MicrosoftLearnMcpError:
                continue  # keep the shorter search excerpt as evidence instead

        valid_urls = {document["url"] for document in documents}
        envelope = await self._execute_answer(
            question=cleaned_question,
            documents=documents,
            session_id=session_id,
            trace_id=trace_id,
        )
        citations = [
            DocCitation(
                title=next(
                    (d["title"] for d in documents if d["url"] == citation.url),
                    citation.title,
                ),
                url=citation.url,
                excerpt=next(
                    (d["search_excerpt"] for d in documents if d["url"] == citation.url), ""
                ),
            )
            for citation in envelope.citations
            if citation.url in valid_urls
        ]
        answer = WellArchitectedAnswer(
            question=cleaned_question,
            answer=envelope.answer,
            citations=citations,
            grounded=envelope.grounded and len(citations) > 0,
            generated_at=datetime.now(UTC),
        )
        await self._record_governance(
            session_id=session_id,
            trace_id=trace_id,
            question=cleaned_question,
            answer=answer,
            document_count=len(documents),
        )
        return answer

    async def _execute_answer(
        self,
        *,
        question: str,
        documents: list[dict[str, str]],
        session_id: str,
        trace_id: str,
    ) -> _AnswerEnvelope:
        orchestrator = self._orchestrator
        if orchestrator is None:
            raise WellArchitectedQaError("Azure AI Foundry orchestrator is not configured.")
        evidence_json = json.dumps(
            [
                {"title": d["title"], "url": d["url"], "evidence_text": d["evidence_text"]}
                for d in documents
            ]
        )
        variables = {
            "question": question,
            "evidence_json": evidence_json,
            "retry_instruction": "",
        }
        for attempt in range(2):
            result = await orchestrator.execute_agent(
                agent_id="well-architected-advisor",
                prompt_id="well-architected-qa-v1",
                variables=variables,
                session_id=session_id,
                trace_id=f"{trace_id}:well-architected-qa",
            )
            try:
                return parse_agent_response(result.output_text, _AnswerEnvelope)
            except WellArchitectedAgentResponseError as exc:
                if attempt == 1:
                    raise WellArchitectedQaError(str(exc)) from exc
                variables["retry_instruction"] = (
                    "A prior response was malformed, truncated, or schema-invalid. "
                    f"Correct these exact validation issues: {exc} Regenerate the "
                    "complete response as fresh JSON, citing only url values that "
                    "literally appear in evidence_json."
                )
        raise WellArchitectedQaError("Well-architected Q&A retry loop exited unexpectedly.")

    async def _record_governance(
        self,
        *,
        session_id: str,
        trace_id: str,
        question: str,
        answer: WellArchitectedAnswer,
        document_count: int,
    ) -> None:
        await self._governance_service.record_tool_request(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="well-architected-qa-service",
            tool_name="microsoft_learn_mcp.ask",
            detail={
                "question": question,
                "documents_retrieved": document_count,
                "citations_returned": len(answer.citations),
                "grounded": answer.grounded,
            },
        )
