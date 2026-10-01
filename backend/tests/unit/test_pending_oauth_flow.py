"""Tests for the short-lived PKCE pending-flow store."""
from __future__ import annotations

import pytest

from app.iq.pending_oauth_flow import PendingOAuthFlowError, PendingOAuthFlowStore


async def test_start_then_consume_returns_the_bound_session_and_provider() -> None:
    store = PendingOAuthFlowStore()

    state, code_verifier = await store.start(session_id="session-1", provider="work_iq")
    flow = await store.consume(state=state)

    assert flow.session_id == "session-1"
    assert flow.provider == "work_iq"
    assert flow.code_verifier == code_verifier


async def test_state_is_single_use() -> None:
    store = PendingOAuthFlowStore()
    state, _ = await store.start(session_id="session-1", provider="work_iq")

    await store.consume(state=state)

    with pytest.raises(PendingOAuthFlowError):
        await store.consume(state=state)


async def test_unknown_state_raises() -> None:
    store = PendingOAuthFlowStore()

    with pytest.raises(PendingOAuthFlowError):
        await store.consume(state="never-issued")


async def test_expired_flow_raises_and_is_pruned() -> None:
    store = PendingOAuthFlowStore(ttl_seconds=-1)  # already expired the instant it's created

    state, _ = await store.start(session_id="session-1", provider="work_iq")

    with pytest.raises(PendingOAuthFlowError):
        await store.consume(state=state)


async def test_two_concurrent_flows_do_not_collide() -> None:
    store = PendingOAuthFlowStore()

    state_a, verifier_a = await store.start(session_id="session-A", provider="work_iq")
    state_b, verifier_b = await store.start(session_id="session-B", provider="fabric_iq")

    assert state_a != state_b
    assert verifier_a != verifier_b

    flow_a = await store.consume(state=state_a)
    flow_b = await store.consume(state=state_b)

    assert flow_a.session_id == "session-A"
    assert flow_b.session_id == "session-B"
