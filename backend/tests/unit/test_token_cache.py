"""Tests for the partitioned delegated-token cache.

Focus: cross-user/tenant/session/resource isolation is the core security
guarantee this module provides - a lookup with any one partition field
changed must never return another partition's token.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.iq.token_cache import (
    CachedDelegatedToken,
    InMemoryUserTokenCachePartition,
    TokenCachePartitionKey,
)


def _token(value: str, *, expires_in_seconds: float = 3600) -> CachedDelegatedToken:
    return CachedDelegatedToken(
        access_token=value,
        refresh_token=f"refresh-{value}",
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
        scopes=("scope-a",),
    )


async def test_put_then_get_round_trips_within_the_same_partition() -> None:
    cache = InMemoryUserTokenCachePartition()
    key = TokenCachePartitionKey(
        tenant_id="tenant-1", subject="user-1", session_id="session-1", provider="work_iq"
    )

    await cache.put(key, _token("token-a"))
    result = await cache.get(key)

    assert result is not None
    assert result.access_token == "token-a"


async def test_different_session_never_sees_another_sessions_token() -> None:
    cache = InMemoryUserTokenCachePartition()
    key_a = TokenCachePartitionKey(
        tenant_id="tenant-1", subject="user-1", session_id="session-A", provider="work_iq"
    )
    key_b = TokenCachePartitionKey(
        tenant_id="tenant-1", subject="user-1", session_id="session-B", provider="work_iq"
    )

    await cache.put(key_a, _token("token-for-session-A"))

    assert await cache.get(key_b) is None


async def test_different_subject_never_sees_another_users_token() -> None:
    cache = InMemoryUserTokenCachePartition()
    key_a = TokenCachePartitionKey(
        tenant_id="tenant-1", subject="user-A", session_id="session-1", provider="work_iq"
    )
    key_b = TokenCachePartitionKey(
        tenant_id="tenant-1", subject="user-B", session_id="session-1", provider="work_iq"
    )

    await cache.put(key_a, _token("token-for-user-A"))

    assert await cache.get(key_b) is None


async def test_different_tenant_never_sees_another_tenants_token() -> None:
    cache = InMemoryUserTokenCachePartition()
    key_a = TokenCachePartitionKey(
        tenant_id="tenant-A", subject="user-1", session_id="session-1", provider="work_iq"
    )
    key_b = TokenCachePartitionKey(
        tenant_id="tenant-B", subject="user-1", session_id="session-1", provider="work_iq"
    )

    await cache.put(key_a, _token("token-for-tenant-A"))

    assert await cache.get(key_b) is None


async def test_different_provider_never_sees_another_providers_token() -> None:
    cache = InMemoryUserTokenCachePartition()
    key_work_iq = TokenCachePartitionKey(
        tenant_id="tenant-1", subject="user-1", session_id="session-1", provider="work_iq"
    )
    key_fabric_iq = TokenCachePartitionKey(
        tenant_id="tenant-1", subject="user-1", session_id="session-1", provider="fabric_iq"
    )

    await cache.put(key_work_iq, _token("work-iq-token"))

    assert await cache.get(key_fabric_iq) is None


async def test_clear_removes_only_its_own_partition() -> None:
    cache = InMemoryUserTokenCachePartition()
    key_a = TokenCachePartitionKey(
        tenant_id="tenant-1", subject="user-1", session_id="session-1", provider="work_iq"
    )
    key_b = TokenCachePartitionKey(
        tenant_id="tenant-1", subject="user-1", session_id="session-1", provider="fabric_iq"
    )
    await cache.put(key_a, _token("token-a"))
    await cache.put(key_b, _token("token-b"))

    await cache.clear(key_a)

    assert await cache.get(key_a) is None
    assert await cache.get(key_b) is not None


async def test_clear_session_removes_every_provider_for_that_session_only() -> None:
    cache = InMemoryUserTokenCachePartition()
    session_a_work_iq = TokenCachePartitionKey(
        tenant_id="tenant-1", subject="user-1", session_id="session-A", provider="work_iq"
    )
    session_a_fabric_iq = TokenCachePartitionKey(
        tenant_id="tenant-1", subject="user-1", session_id="session-A", provider="fabric_iq"
    )
    session_b_work_iq = TokenCachePartitionKey(
        tenant_id="tenant-1", subject="user-1", session_id="session-B", provider="work_iq"
    )
    await cache.put(session_a_work_iq, _token("a-work"))
    await cache.put(session_a_fabric_iq, _token("a-fabric"))
    await cache.put(session_b_work_iq, _token("b-work"))

    await cache.clear_session(session_id="session-A")

    assert await cache.get(session_a_work_iq) is None
    assert await cache.get(session_a_fabric_iq) is None
    assert await cache.get(session_b_work_iq) is not None


async def test_is_expired_respects_skew() -> None:
    token = _token("token-a", expires_in_seconds=30)

    assert token.is_expired(skew_seconds=60) is True
    assert token.is_expired(skew_seconds=0) is False


def test_repr_and_str_never_include_the_raw_token_value() -> None:
    token = _token("super-secret-access-token")

    rendered_repr = repr(token)
    rendered_str = str(token)

    assert "super-secret-access-token" not in rendered_repr
    assert "super-secret-access-token" not in rendered_str
    assert "refresh-super-secret-access-token" not in rendered_repr
    assert "***redacted***" in rendered_repr
