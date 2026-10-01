"""Tests for ``DelegatedMcpConnectionManager`` - the component that ties
the token broker, partitioned cache, and MCP client together.

Focus areas: per-partition isolation end-to-end through the manager
(not just the cache in isolation), transparent refresh-on-expiry, refresh
failure invalidating the cache, and disconnect/logout cleanup.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.iq.delegated_connection_manager import (
    DelegatedConnectionError,
    DelegatedMcpConnectionManager,
)
from app.iq.delegated_token_broker import DelegatedAuthError, ExchangedDelegatedToken
from app.iq.microsoft_resource_registry import MicrosoftMcpResourceRegistry
from app.iq.models import DelegatedIdentityContext
from app.iq.token_cache import InMemoryUserTokenCachePartition


class _FakeTokenBroker:
    def __init__(self) -> None:
        self.refresh_calls: list[tuple[str, str]] = []
        self.next_refresh_result: ExchangedDelegatedToken | Exception | None = None

    async def refresh(self, *, provider: str, refresh_token: str) -> ExchangedDelegatedToken:
        self.refresh_calls.append((provider, refresh_token))
        if isinstance(self.next_refresh_result, Exception):
            raise self.next_refresh_result
        assert self.next_refresh_result is not None
        return self.next_refresh_result


def _registry() -> MicrosoftMcpResourceRegistry:
    return MicrosoftMcpResourceRegistry.from_settings(
        work_iq_mcp_endpoint="https://workiq.svc.cloud.microsoft/mcp",
        work_iq_scopes=None,
        fabric_iq_mcp_endpoint="https://fabriciq.svc.cloud.microsoft/v1/mcp/fabriciq",
        fabric_iq_scopes=("https://analysis.windows.net/powerbi/api/Item.Read.All",),
    )


def _manager(broker: _FakeTokenBroker) -> DelegatedMcpConnectionManager:
    return DelegatedMcpConnectionManager(
        registry=_registry(),
        token_broker=broker,  # type: ignore[arg-type]
        token_cache=InMemoryUserTokenCachePartition(),
        mcp_timeout_seconds=30,
    )


def _identity(session_id: str = "session-1", subject: str = "user-1", tenant_id: str = "tenant-1") -> DelegatedIdentityContext:
    return DelegatedIdentityContext(
        session_id=session_id, tenant_id=tenant_id, subject=subject, correlation_id="trace-1"
    )


async def test_connection_for_raises_when_nothing_was_ever_connected() -> None:
    manager = _manager(_FakeTokenBroker())

    with pytest.raises(DelegatedConnectionError):
        await manager.connection_for(identity=_identity(), provider="work_iq")


async def test_store_then_connection_for_returns_the_cached_token() -> None:
    manager = _manager(_FakeTokenBroker())
    identity = await manager.store_exchanged_token(
        provider="work_iq",
        session_id="session-1",
        access_token="access-token-1",
        refresh_token="refresh-token-1",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("scope-a",),
        tenant_id="tenant-1",
        subject="user-1",
        display_name="Ada Lovelace",
    )

    _client, cached = await manager.connection_for(identity=identity, provider="work_iq")

    assert cached.access_token == "access-token-1"
    assert identity.tenant_id == "tenant-1"
    assert identity.subject == "user-1"


async def test_different_session_cannot_reach_another_sessions_connection() -> None:
    manager = _manager(_FakeTokenBroker())
    await manager.store_exchanged_token(
        provider="work_iq",
        session_id="session-A",
        access_token="access-token-A",
        refresh_token="refresh-token-A",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("scope-a",),
        tenant_id="tenant-1",
        subject="user-1",
        display_name=None,
    )

    with pytest.raises(DelegatedConnectionError):
        await manager.connection_for(identity=_identity(session_id="session-B"), provider="work_iq")


async def test_two_sessions_connecting_different_microsoft_users_never_cross_reuse() -> None:
    """Step 7 negative test: two anonymous Genie sessions each connect a
    different real Microsoft user/tenant. Neither session's connection
    manager lookup may ever resolve the other's token."""

    manager = _manager(_FakeTokenBroker())
    identity_a = await manager.store_exchanged_token(
        provider="work_iq",
        session_id="session-A",
        access_token="access-token-user-A",
        refresh_token="refresh-token-user-A",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("scope-a",),
        tenant_id="tenant-A",
        subject="user-A",
        display_name="User A",
    )
    identity_b = await manager.store_exchanged_token(
        provider="work_iq",
        session_id="session-B",
        access_token="access-token-user-B",
        refresh_token="refresh-token-user-B",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("scope-a",),
        tenant_id="tenant-B",
        subject="user-B",
        display_name="User B",
    )

    _client_a, cached_a = await manager.connection_for(identity=identity_a, provider="work_iq")
    _client_b, cached_b = await manager.connection_for(identity=identity_b, provider="work_iq")

    assert cached_a.access_token == "access-token-user-A"
    assert cached_b.access_token == "access-token-user-B"

    # Session A's identity must never resolve session B's token, even
    # though both are connected to the same provider simultaneously.
    with pytest.raises(DelegatedConnectionError):
        await manager.connection_for(
            identity=_identity(session_id="session-A", subject="user-B", tenant_id="tenant-B"),
            provider="work_iq",
        )


async def test_expired_token_is_transparently_refreshed() -> None:
    broker = _FakeTokenBroker()
    manager = _manager(broker)
    identity = await manager.store_exchanged_token(
        provider="work_iq",
        session_id="session-1",
        access_token="stale-access-token",
        refresh_token="refresh-token-1",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),  # already expired
        scopes=("scope-a",),
        tenant_id="tenant-1",
        subject="user-1",
        display_name=None,
    )
    broker.next_refresh_result = ExchangedDelegatedToken(
        access_token="fresh-access-token",
        refresh_token="new-refresh-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("scope-a",),
        tenant_id="tenant-1",
        subject="user-1",
        display_name="Ada Lovelace",
    )

    _client, cached = await manager.connection_for(identity=identity, provider="work_iq")

    assert cached.access_token == "fresh-access-token"
    assert broker.refresh_calls == [("work_iq", "refresh-token-1")]


async def test_failed_refresh_clears_the_cache_and_propagates_session_expired() -> None:
    broker = _FakeTokenBroker()
    manager = _manager(broker)
    identity = await manager.store_exchanged_token(
        provider="work_iq",
        session_id="session-1",
        access_token="stale-access-token",
        refresh_token="revoked-refresh-token",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
        scopes=("scope-a",),
        tenant_id="tenant-1",
        subject="user-1",
        display_name=None,
    )
    broker.next_refresh_result = DelegatedAuthError("revoked", category="session_expired")

    with pytest.raises(DelegatedAuthError) as exc_info:
        await manager.connection_for(identity=identity, provider="work_iq")
    assert exc_info.value.category == "session_expired"

    # The stale cache entry must be gone - a second attempt must not
    # silently reuse the invalidated token.
    with pytest.raises(DelegatedConnectionError):
        await manager.connection_for(identity=identity, provider="work_iq")


async def test_disconnect_clears_only_the_requested_provider() -> None:
    manager = _manager(_FakeTokenBroker())
    identity = await manager.store_exchanged_token(
        provider="work_iq",
        session_id="session-1",
        access_token="work-iq-token",
        refresh_token="work-iq-refresh",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("scope-a",),
        tenant_id="tenant-1",
        subject="user-1",
        display_name=None,
    )
    await manager.store_exchanged_token(
        provider="fabric_iq",
        session_id="session-1",
        access_token="fabric-iq-token",
        refresh_token="fabric-iq-refresh",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("scope-b",),
        tenant_id="tenant-1",
        subject="user-1",
        display_name=None,
    )

    await manager.disconnect(identity=identity, provider="work_iq")

    with pytest.raises(DelegatedConnectionError):
        await manager.connection_for(identity=identity, provider="work_iq")
    # fabric_iq's connection must survive work_iq's disconnect.
    await manager.connection_for(identity=identity, provider="fabric_iq")


async def test_clear_session_removes_every_provider_for_that_session() -> None:
    manager = _manager(_FakeTokenBroker())
    identity = await manager.store_exchanged_token(
        provider="work_iq",
        session_id="session-1",
        access_token="work-iq-token",
        refresh_token="work-iq-refresh",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("scope-a",),
        tenant_id="tenant-1",
        subject="user-1",
        display_name=None,
    )

    await manager.clear_session(session_id="session-1")

    with pytest.raises(DelegatedConnectionError):
        await manager.connection_for(identity=identity, provider="work_iq")


async def test_token_provider_reads_current_cache_state_not_a_stale_snapshot() -> None:
    """The closure returned inside the ``IqMcpClient`` must re-read the
    cache on every call, not close over the token fetched at connection
    time - otherwise a concurrent refresh would be invisible to it."""

    manager = _manager(_FakeTokenBroker())
    identity = await manager.store_exchanged_token(
        provider="work_iq",
        session_id="session-1",
        access_token="first-access-token",
        refresh_token="refresh-token-1",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("scope-a",),
        tenant_id="tenant-1",
        subject="user-1",
        display_name=None,
    )

    client, _ = await manager.connection_for(identity=identity, provider="work_iq")

    # Simulate a concurrent request refreshing the cache after this client
    # was constructed but before its token provider is actually invoked.
    await manager._token_cache.put(
        manager._partition_key(identity, "work_iq"),
        (await manager._token_cache.get(manager._partition_key(identity, "work_iq"))).__class__(
            access_token="second-access-token",
            refresh_token="refresh-token-1",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=("scope-a",),
        ),
    )

    resolved_token = await client._resolve_token()

    assert resolved_token == "second-access-token"
