"""Unit tests for WellArchitectedQaService - grounded Azure Well-Architected
Framework / Microsoft-docs Q&A that must never let a hallucinated citation
or an ungrounded guess reach the user."""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.agents.models import AgentExecutionResult
from app.well_architected.microsoft_learn_client import MicrosoftLearnMcpError
from app.well_architected.service import WellArchitectedQaError, WellArchitectedQaService


class _FakeLearnClient:
    def __init__(
        self,
        *,
        search_results: list[dict[str, Any]] | None = None,
        search_error: bool = False,
        fetch_text: str | None = None,
    ) -> None:
        self._search_results = search_results or []
        self._search_error = search_error
        self._fetch_text = fetch_text
        self.search_calls: list[str] = []
        self.fetch_calls: list[str] = []

    async def search(self, query: str) -> list[dict[str, Any]]:
        self.search_calls.append(query)
        if self._search_error:
            raise MicrosoftLearnMcpError("Microsoft Learn MCP is unavailable.")
        return self._search_results

    async def fetch(self, url: str) -> str:
        self.fetch_calls.append(url)
        if self._fetch_text is None:
            raise MicrosoftLearnMcpError(f"Could not fetch {url}.")
        return self._fetch_text


class _FakeSessionService:
    async def get_session(self, *, session_id: str, requesting_user_id: str) -> object:
        return object()


class _FakeGovernanceService:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def record_tool_request(self, **request: Any) -> None:
        self.requests.append(request)


class _FakeAgentOrchestrator:
    def __init__(self, *, responses: list[str] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    async def execute_agent(
        self,
        *,
        agent_id: str,
        prompt_id: str,
        variables: dict[str, str],
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> AgentExecutionResult:
        self.calls.append({"agent_id": agent_id, "prompt_id": prompt_id, "variables": variables})
        return AgentExecutionResult(
            agent_id=agent_id,
            output_text=self._responses.pop(0),
            correlation_id=trace_id or "trace-1",
        )


_HITS = [
    {
        "title": "Overview of the reliability pillar",
        "content": "The reliability pillar focuses on consistent, resilient workloads.",
        "contentUrl": "https://learn.microsoft.com/azure/well-architected/reliability",
    },
    {
        "title": "What is the Azure Well-Architected Framework?",
        "content": "A design framework with five pillars.",
        "contentUrl": "https://learn.microsoft.com/azure/well-architected/what-is-well-architected-framework",
    },
]


def _service(
    *, learn_client: Any, orchestrator: Any = None
) -> WellArchitectedQaService:
    return WellArchitectedQaService(
        learn_client=learn_client,
        orchestrator=orchestrator,
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        governance_service=_FakeGovernanceService(),  # type: ignore[arg-type]
        max_search_results=5,
        max_fetched_documents=2,
    )


async def test_rejects_a_blank_question() -> None:
    service = _service(learn_client=_FakeLearnClient(), orchestrator=_FakeAgentOrchestrator())

    with pytest.raises(WellArchitectedQaError, match="Describe"):
        await service.ask(
            session_id="session-1", requesting_user_id="user-1", question="   ", trace_id="t1"
        )


async def test_requires_an_orchestrator_to_be_configured() -> None:
    service = _service(learn_client=_FakeLearnClient(search_results=_HITS), orchestrator=None)

    with pytest.raises(WellArchitectedQaError, match="Foundry"):
        await service.ask(
            session_id="session-1",
            requesting_user_id="user-1",
            question="What is the reliability pillar?",
            trace_id="t1",
        )


async def test_returns_an_ungrounded_answer_without_calling_the_agent_when_no_docs_are_found() -> None:
    orchestrator = _FakeAgentOrchestrator()
    service = _service(learn_client=_FakeLearnClient(search_results=[]), orchestrator=orchestrator)

    answer = await service.ask(
        session_id="session-1",
        requesting_user_id="user-1",
        question="Some obscure question",
        trace_id="t1",
    )

    assert answer.grounded is False
    assert answer.citations == []
    assert len(orchestrator.calls) == 0


async def test_fails_closed_when_the_search_itself_errors() -> None:
    learn_client = _FakeLearnClient(search_error=True)
    orchestrator = _FakeAgentOrchestrator()
    service = _service(learn_client=learn_client, orchestrator=orchestrator)

    with pytest.raises(WellArchitectedQaError, match="Could not retrieve"):
        await service.ask(
            session_id="session-1",
            requesting_user_id="user-1",
            question="What is the reliability pillar?",
            trace_id="t1",
        )
    assert len(orchestrator.calls) == 0


async def test_returns_a_grounded_answer_with_real_citations_when_the_agent_succeeds() -> None:
    envelope = json.dumps(
        {
            "answer": "The reliability pillar focuses on building resilient, available workloads.",
            "grounded": True,
            "citations": [
                {
                    "title": "Overview of the reliability pillar",
                    "url": "https://learn.microsoft.com/azure/well-architected/reliability",
                }
            ],
        }
    )
    learn_client = _FakeLearnClient(search_results=_HITS, fetch_text="Full page text.")
    orchestrator = _FakeAgentOrchestrator(responses=[envelope])
    service = _service(learn_client=learn_client, orchestrator=orchestrator)

    answer = await service.ask(
        session_id="session-1",
        requesting_user_id="user-1",
        question="What is the reliability pillar?",
        trace_id="t1",
    )

    assert answer.grounded is True
    assert len(answer.citations) == 1
    assert answer.citations[0].url == "https://learn.microsoft.com/azure/well-architected/reliability"
    assert answer.citations[0].title == "Overview of the reliability pillar"
    assert orchestrator.calls[0]["agent_id"] == "well-architected-advisor"
    assert orchestrator.calls[0]["prompt_id"] == "well-architected-qa-v1"
    # The top max_fetched_documents results get their full content fetched.
    assert len(learn_client.fetch_calls) == 2


async def test_discards_a_citation_whose_url_was_never_actually_retrieved() -> None:
    envelope = json.dumps(
        {
            "answer": "Some answer.",
            "grounded": True,
            "citations": [
                {"title": "Fabricated page", "url": "https://learn.microsoft.com/made-up-page"}
            ],
        }
    )
    learn_client = _FakeLearnClient(search_results=_HITS, fetch_text="Full page text.")
    orchestrator = _FakeAgentOrchestrator(responses=[envelope])
    service = _service(learn_client=learn_client, orchestrator=orchestrator)

    answer = await service.ask(
        session_id="session-1",
        requesting_user_id="user-1",
        question="What is the reliability pillar?",
        trace_id="t1",
    )

    # The model claimed grounded=True, but its only citation did not match a
    # real retrieved URL, so it must be discarded and grounded forced false.
    assert answer.citations == []
    assert answer.grounded is False


async def test_retries_once_on_a_malformed_response_then_succeeds() -> None:
    valid_envelope = json.dumps({"answer": "x" * 200, "grounded": False, "citations": []})
    learn_client = _FakeLearnClient(search_results=_HITS, fetch_text="Full page text.")
    orchestrator = _FakeAgentOrchestrator(responses=["not json", valid_envelope])
    service = _service(learn_client=learn_client, orchestrator=orchestrator)

    answer = await service.ask(
        session_id="session-1",
        requesting_user_id="user-1",
        question="What is the reliability pillar?",
        trace_id="t1",
    )

    assert answer.answer == "x" * 200
    assert len(orchestrator.calls) == 2
    assert orchestrator.calls[1]["variables"]["retry_instruction"] != ""


async def test_raises_when_the_agent_keeps_returning_malformed_json() -> None:
    learn_client = _FakeLearnClient(search_results=_HITS, fetch_text="Full page text.")
    orchestrator = _FakeAgentOrchestrator(responses=["not json", "still not json"])
    service = _service(learn_client=learn_client, orchestrator=orchestrator)

    with pytest.raises(WellArchitectedQaError):
        await service.ask(
            session_id="session-1",
            requesting_user_id="user-1",
            question="What is the reliability pillar?",
            trace_id="t1",
        )
