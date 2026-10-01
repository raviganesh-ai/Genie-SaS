"""Short-lived server-side store for one OAuth authorization-code + PKCE
round trip.

The opaque ``state`` value is the only thing the browser carries between
Genie-SaS's "start" redirect and Microsoft's redirect back to Genie-SaS's
callback - it must be unguessable (CSRF protection) and must resolve back
to the exact Genie session, provider, and PKCE code verifier that
initiated the flow, without the browser itself carrying any of that detail
in a tamperable query parameter.

ASSUMPTION: in-memory only, expiring after ``ttl_seconds``. On a
horizontally scaled deployment, the callback must land on the same replica
that issued ``state`` - see
``docs/architecture/genie-sas-microsoft-iq.md`` "Remaining blockers" for
the documented follow-up (a shared/distributed pending-flow store).
"""
from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.iq.models import IqProviderName


@dataclass(frozen=True)
class PendingOAuthFlow:
    session_id: str
    provider: IqProviderName
    code_verifier: str
    nonce: str
    created_at: datetime


class PendingOAuthFlowError(RuntimeError):
    """Raised when a ``state`` value is unknown, expired, or already consumed."""


class PendingOAuthFlowStore:
    def __init__(self, *, ttl_seconds: float = 600) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._flows: dict[str, PendingOAuthFlow] = {}
        self._lock = asyncio.Lock()

    async def start(self, *, session_id: str, provider: IqProviderName) -> tuple[str, str]:
        """Creates a new pending flow; returns ``(state, code_verifier)``."""

        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        flow = PendingOAuthFlow(
            session_id=session_id,
            provider=provider,
            code_verifier=code_verifier,
            nonce=secrets.token_urlsafe(16),
            created_at=datetime.now(UTC),
        )
        async with self._lock:
            self._prune_locked()
            self._flows[state] = flow
        return state, code_verifier

    async def consume(self, *, state: str) -> PendingOAuthFlow:
        """Looks up and immediately removes the pending flow for ``state``
        (single-use - a replayed callback cannot reuse the same state)."""

        async with self._lock:
            self._prune_locked()
            flow = self._flows.pop(state, None)
        if flow is None:
            raise PendingOAuthFlowError("The OAuth state is unknown, expired, or already used.")
        return flow

    def _prune_locked(self) -> None:
        now = datetime.now(UTC)
        expired = [s for s, flow in self._flows.items() if now - flow.created_at > self._ttl]
        for s in expired:
            del self._flows[s]
