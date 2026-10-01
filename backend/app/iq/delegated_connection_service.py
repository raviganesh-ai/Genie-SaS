"""Application service backing the delegated IQ connection API routes:
start the OAuth flow, handle the callback, report status, and disconnect.

Every method validates Genie session ownership through the existing
``SessionService`` before touching any delegated-auth component, exactly
like every other per-session Genie API (repository connections, IQ
evidence, modernization, ...).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.iq.delegated_connection_manager import DelegatedConnectionError, DelegatedMcpConnectionManager
from app.iq.delegated_token_broker import DelegatedAuthError, DelegatedTokenBroker
from app.iq.mcp_client import IqMcpClient
from app.iq.models import DelegatedIdentityContext, IqConnectionStatus, IqProviderName
from app.iq.pending_oauth_flow import PendingOAuthFlowError, PendingOAuthFlowStore
from app.iq.session_identity_index import SessionIdentityIndex

if TYPE_CHECKING:
    from app.governance.governance_service import GovernanceService
    from app.services.session_service import SessionService


class DelegatedConnectionServiceError(RuntimeError):
    """Raised when a delegated-connection request is invalid (unknown or
    disabled provider) - distinct from ``DelegatedAuthError``, which
    represents a Microsoft-side authentication/authorization outcome."""


class DelegatedConnectionService:
    def __init__(
        self,
        *,
        connection_manager: DelegatedMcpConnectionManager,
        token_broker: DelegatedTokenBroker,
        pending_flow_store: PendingOAuthFlowStore,
        session_identity_index: SessionIdentityIndex,
        session_service: SessionService,
        governance_service: GovernanceService,
        enabled_providers: frozenset[IqProviderName],
    ) -> None:
        self._connection_manager = connection_manager
        self._token_broker = token_broker
        self._pending_flow_store = pending_flow_store
        self._session_identity_index = session_identity_index
        self._session_service = session_service
        self._governance_service = governance_service
        self._enabled_providers = enabled_providers

    async def start(self, *, session_id: str, provider: IqProviderName, requesting_user_id: str) -> str:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        self._require_enabled(provider)
        state, code_verifier = await self._pending_flow_store.start(
            session_id=session_id, provider=provider
        )
        return await self._token_broker.build_authorization_url(
            provider=provider, state=state, code_verifier=code_verifier
        )

    async def handle_callback(self, *, code: str, state: str, trace_id: str) -> tuple[str, IqProviderName]:
        """Completes one OAuth round trip. Returns ``(session_id, provider)``
        on success. Raises ``PendingOAuthFlowError``/``DelegatedAuthError``
        on failure - the API route converts either into a redirect back to
        the frontend carrying only a status code, never the raw error."""

        flow = await self._pending_flow_store.consume(state=state)
        exchanged = await self._token_broker.exchange_code(
            provider=flow.provider, code=code, code_verifier=flow.code_verifier
        )
        identity = await self._connection_manager.store_exchanged_token(
            provider=flow.provider,
            session_id=flow.session_id,
            access_token=exchanged.access_token,
            refresh_token=exchanged.refresh_token,
            expires_at=exchanged.expires_at,
            scopes=exchanged.scopes,
            tenant_id=exchanged.tenant_id,
            subject=exchanged.subject,
            display_name=exchanged.display_name,
        )
        await self._session_identity_index.put(identity, flow.provider)
        await self._governance_service.record_tool_request(
            session_id=flow.session_id,
            trace_id=trace_id,
            agent_id="iq-delegated-connection-service",
            tool_name=f"{flow.provider}.delegated_connect",
            detail={"tenant_id": exchanged.tenant_id},
        )
        return flow.session_id, flow.provider

    async def status(
        self, *, session_id: str, requesting_user_id: str
    ) -> list[IqConnectionStatus]:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        statuses: list[IqConnectionStatus] = []
        for provider in sorted(self._enabled_providers):
            identity = await self._session_identity_index.get(session_id=session_id, provider=provider)
            if identity is None:
                statuses.append(
                    IqConnectionStatus(
                        provider=provider,
                        status="IQ_AUTHENTICATION_REQUIRED",
                        connected=False,
                        detail="Not connected. Start Connect Microsoft 365 to use this capability.",
                    )
                )
                continue
            statuses.append(
                IqConnectionStatus(
                    provider=provider,
                    status="IQ_AVAILABLE",
                    connected=True,
                    tenant_id=identity.tenant_id,
                    display_name=identity.display_name,
                    detail=f"Connected as {identity.display_name or 'a Microsoft 365 user'}.",
                )
            )
        return statuses

    async def disconnect(
        self, *, session_id: str, provider: IqProviderName, requesting_user_id: str, trace_id: str
    ) -> None:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        identity = await self._session_identity_index.get(session_id=session_id, provider=provider)
        if identity is not None:
            await self._connection_manager.disconnect(identity=identity, provider=provider)
        await self._session_identity_index.clear(session_id=session_id, provider=provider)
        await self._governance_service.record_tool_request(
            session_id=session_id,
            trace_id=trace_id,
            agent_id="iq-delegated-connection-service",
            tool_name=f"{provider}.delegated_disconnect",
            detail={},
        )

    async def clear_session(self, *, session_id: str) -> None:
        """Logout/session-termination hook - clears every delegated
        connection (tokens and identity) for this Genie session."""

        await self._connection_manager.clear_session(session_id=session_id)
        await self._session_identity_index.clear_session(session_id=session_id)

    async def resolve_identity(
        self, *, session_id: str, provider: IqProviderName
    ) -> DelegatedIdentityContext | None:
        """Used by ``IqEvidenceService`` to resolve a connected identity
        before calling ``DelegatedMcpConnectionManager.connection_for``."""

        return await self._session_identity_index.get(session_id=session_id, provider=provider)

    async def get_ready_connection(
        self, *, session_id: str, provider: IqProviderName
    ) -> tuple[IqMcpClient, DelegatedIdentityContext] | None:
        """Resolves the session's connected identity (if any) and returns a
        ready ``IqMcpClient`` bound to it, refreshing the cached token first
        if needed. Returns ``None`` when the session has no connection for
        this provider yet - callers should surface that as
        ``IQ_AUTHENTICATION_REQUIRED``, never raise. A stale/revoked
        connection instead raises ``DelegatedConnectionError``/
        ``DelegatedAuthError`` with the precise failure category."""

        identity = await self.resolve_identity(session_id=session_id, provider=provider)
        if identity is None:
            return None
        client, _ = await self._connection_manager.connection_for(identity=identity, provider=provider)
        return client, identity

    def _require_enabled(self, provider: IqProviderName) -> None:
        if provider not in self._enabled_providers:
            raise DelegatedConnectionServiceError(
                f"Delegated IQ provider '{provider}' is not enabled."
            )


__all__ = [
    "DelegatedAuthError",
    "DelegatedConnectionError",
    "DelegatedConnectionService",
    "DelegatedConnectionServiceError",
    "PendingOAuthFlowError",
]
