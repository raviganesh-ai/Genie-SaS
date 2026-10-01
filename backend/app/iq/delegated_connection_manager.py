"""Ties the token broker, partitioned token cache, and MCP client together
into one per-identity, per-resource delegated MCP connection.

This is the only component that hands a live ``IqMcpClient`` to a caller
(``IqEvidenceService``). It never returns a raw token - callers receive a
ready client whose token-provider closure resolves (and transparently
refreshes) the correct cached token for exactly the
``(tenant_id, subject, session_id, provider)`` partition of the supplied
``DelegatedIdentityContext``.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from app.iq.delegated_token_broker import DelegatedAuthError, DelegatedTokenBroker
from app.iq.mcp_client import IqMcpClient
from app.iq.microsoft_resource_registry import MicrosoftMcpResourceRegistry
from app.iq.models import DelegatedIdentityContext, IqProviderName
from app.iq.token_cache import (
    CachedDelegatedToken,
    TokenCachePartitionKey,
    UserTokenCachePartition,
)


class DelegatedConnectionError(RuntimeError):
    """Raised when no delegated connection exists yet for this identity and
    provider. ``category`` is always ``"authentication_required"`` - there
    is nothing to refresh or reclassify because the user never connected."""

    category = "authentication_required"


class DelegatedMcpConnectionManager:
    def __init__(
        self,
        *,
        registry: MicrosoftMcpResourceRegistry,
        token_broker: DelegatedTokenBroker,
        token_cache: UserTokenCachePartition,
        mcp_timeout_seconds: float,
    ) -> None:
        self._registry = registry
        self._token_broker = token_broker
        self._token_cache = token_cache
        self._mcp_timeout_seconds = mcp_timeout_seconds

    async def store_exchanged_token(
        self,
        *,
        provider: IqProviderName,
        session_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime,
        scopes: tuple[str, ...],
        tenant_id: str,
        subject: str,
        display_name: str | None,
    ) -> DelegatedIdentityContext:
        """Persists a freshly exchanged token and returns the resulting
        identity context. Called only by ``DelegatedConnectionService``
        immediately after a successful authorization-code exchange."""

        key = TokenCachePartitionKey(
            tenant_id=tenant_id, subject=subject, session_id=session_id, provider=provider
        )
        await self._token_cache.put(
            key,
            CachedDelegatedToken(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                scopes=scopes,
                display_name=display_name,
            ),
        )
        return DelegatedIdentityContext(
            session_id=session_id,
            tenant_id=tenant_id,
            subject=subject,
            display_name=display_name,
            correlation_id=str(uuid.uuid4()),
        )

    async def connection_for(
        self, *, identity: DelegatedIdentityContext, provider: IqProviderName
    ) -> tuple[IqMcpClient, CachedDelegatedToken]:
        """Returns a ready ``IqMcpClient`` bound to the caller's exact
        partition, refreshing the cached token first if it has expired.
        Raises ``DelegatedConnectionError``/``DelegatedAuthError`` (never a
        bare token) when no usable connection exists."""

        key = self._partition_key(identity, provider)
        cached = await self._token_cache.get(key)
        if cached is None:
            raise DelegatedConnectionError(
                f"No delegated {provider} connection exists for this session."
            )
        if cached.is_expired():
            cached = await self._refresh(key=key, cached=cached, provider=provider)
        resource = self._registry.get(provider)

        async def _token_provider() -> str:
            # Re-read from cache on every call (not a closed-over local) so
            # a refresh performed by a concurrent request is observed.
            current = await self._token_cache.get(key)
            if current is None:
                raise DelegatedConnectionError(
                    f"The delegated {provider} connection was cleared."
                )
            if current.is_expired():
                current = await self._refresh(key=key, cached=current, provider=provider)
            return current.access_token

        client = IqMcpClient(
            endpoint=resource.mcp_endpoint,
            timeout_seconds=self._mcp_timeout_seconds,
            token_provider=_token_provider,
        )
        return client, cached

    async def disconnect(self, *, identity: DelegatedIdentityContext, provider: IqProviderName) -> None:
        """Clears the local token cache for this identity/provider. This
        does not revoke the underlying Microsoft Entra ID consent grant -
        Microsoft does not expose a standard delegated-token revocation API
        to the resource's own client; the user can separately manage/revoke
        consent through https://myapplications.microsoft.com or their
        tenant administrator."""

        await self._token_cache.clear(self._partition_key(identity, provider))

    async def clear_session(self, *, session_id: str) -> None:
        """Clears every delegated connection for one Genie session - the
        logout/session-termination path."""

        await self._token_cache.clear_session(session_id=session_id)

    async def _refresh(
        self, *, key: TokenCachePartitionKey, cached: CachedDelegatedToken, provider: IqProviderName
    ) -> CachedDelegatedToken:
        if not cached.refresh_token:
            await self._token_cache.clear(key)
            raise DelegatedAuthError(
                "The delegated connection expired and cannot be silently refreshed.",
                category="session_expired",
            )
        try:
            exchanged = await self._token_broker.refresh(
                provider=provider, refresh_token=cached.refresh_token
            )
        except DelegatedAuthError:
            # A refresh failure (expired/revoked refresh token, tenant
            # mismatch, permission change, ...) always invalidates the
            # cached entry - never silently retry with a stale token.
            await self._token_cache.clear(key)
            raise
        refreshed = CachedDelegatedToken(
            access_token=exchanged.access_token,
            refresh_token=exchanged.refresh_token or cached.refresh_token,
            expires_at=exchanged.expires_at,
            scopes=exchanged.scopes,
            display_name=exchanged.display_name or cached.display_name,
        )
        await self._token_cache.put(key, refreshed)
        return refreshed

    @staticmethod
    def _partition_key(
        identity: DelegatedIdentityContext, provider: IqProviderName
    ) -> TokenCachePartitionKey:
        return TokenCachePartitionKey(
            tenant_id=identity.tenant_id,
            subject=identity.subject,
            session_id=identity.session_id,
            provider=provider,
        )
