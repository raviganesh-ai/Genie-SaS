"""Per-user, per-tenant, per-session, per-resource delegated token cache.

This is the only place a live Microsoft access/refresh token is held in
memory. Every read/write is partitioned by the full
``(tenant_id, subject, session_id, provider)`` tuple - callers cannot
construct a partition key that collides across two different users,
tenants, sessions, or resources, which is what prevents cross-user MCP
session/token reuse.

ASSUMPTION (isolated behind this module so it can be corrected without
touching callers): tokens are cached in-memory only. A persistent
(Cosmos-backed) implementation is a documented follow-up - see
``docs/architecture/genie-sas-microsoft-iq.md`` "Remaining blockers" -
because persisting refresh tokens durably requires an explicit
encryption-at-rest design this task does not implement.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.iq.models import IqProviderName


@dataclass(frozen=True)
class TokenCachePartitionKey:
    tenant_id: str
    subject: str
    session_id: str
    provider: IqProviderName


@dataclass(frozen=True)
class CachedDelegatedToken:
    """Holds the live token material. Never logged, never serialized into
    any API response, governance event, or agent-visible object - only
    ``DelegatedMcpConnectionManager`` reads ``access_token``."""

    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scopes: tuple[str, ...]
    display_name: str | None = None

    def is_expired(self, *, skew_seconds: float = 60) -> bool:
        return datetime.now(UTC) >= (self.expires_at - timedelta(seconds=skew_seconds))

    def __repr__(self) -> str:  # pragma: no cover - defensive redaction
        # Defense in depth: even an accidental `logger.info(str(token))` or
        # a debugger/exception traceback must never print the token value.
        return (
            f"CachedDelegatedToken(access_token='***redacted***', "
            f"refresh_token={'***redacted***' if self.refresh_token else None}, "
            f"expires_at={self.expires_at.isoformat()!r}, scopes={self.scopes!r})"
        )

    __str__ = __repr__


class UserTokenCachePartition(Protocol):
    async def get(self, key: TokenCachePartitionKey) -> CachedDelegatedToken | None: ...

    async def put(self, key: TokenCachePartitionKey, token: CachedDelegatedToken) -> None: ...

    async def clear(self, key: TokenCachePartitionKey) -> None: ...

    async def clear_session(self, *, session_id: str) -> None:
        """Clears every cached token for one Genie session, regardless of
        provider/tenant/subject - the logout/session-termination path."""
        ...


class InMemoryUserTokenCachePartition:
    def __init__(self) -> None:
        self._tokens: dict[TokenCachePartitionKey, CachedDelegatedToken] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: TokenCachePartitionKey) -> CachedDelegatedToken | None:
        async with self._lock:
            token = self._tokens.get(key)
            return replace(token) if token else None

    async def put(self, key: TokenCachePartitionKey, token: CachedDelegatedToken) -> None:
        async with self._lock:
            self._tokens[key] = replace(token)

    async def clear(self, key: TokenCachePartitionKey) -> None:
        async with self._lock:
            self._tokens.pop(key, None)

    async def clear_session(self, *, session_id: str) -> None:
        async with self._lock:
            for key in [k for k in self._tokens if k.session_id == session_id]:
                del self._tokens[key]
