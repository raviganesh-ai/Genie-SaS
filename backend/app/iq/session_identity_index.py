"""In-memory index of which delegated Microsoft identity (if any) is
connected for a given Genie session and provider.

Deliberately separate from ``app.iq.token_cache``: this index holds only
the non-secret ``DelegatedIdentityContext`` (session id, tenant id,
subject, display name) - never a token - so that connection status can be
reported to the frontend, and a connection resolved for
``DelegatedMcpConnectionManager.connection_for(...)``, without ever
touching the token cache for a read-only status check.
"""
from __future__ import annotations

import asyncio

from app.iq.models import DelegatedIdentityContext, IqProviderName


class SessionIdentityIndex:
    def __init__(self) -> None:
        self._identities: dict[tuple[str, IqProviderName], DelegatedIdentityContext] = {}
        self._lock = asyncio.Lock()

    async def put(self, identity: DelegatedIdentityContext, provider: IqProviderName) -> None:
        async with self._lock:
            self._identities[(identity.session_id, provider)] = identity

    async def get(
        self, *, session_id: str, provider: IqProviderName
    ) -> DelegatedIdentityContext | None:
        async with self._lock:
            return self._identities.get((session_id, provider))

    async def clear(self, *, session_id: str, provider: IqProviderName) -> None:
        async with self._lock:
            self._identities.pop((session_id, provider), None)

    async def clear_session(self, *, session_id: str) -> None:
        async with self._lock:
            for key in [k for k in self._identities if k[0] == session_id]:
                del self._identities[key]
