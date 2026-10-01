"""Development-only diagnostic snapshot service for Microsoft Connect / Work IQ.

Deliberately narrow: every value returned is a boolean, a count, a safe
error-category label, or a correlation id. It never returns a client
secret, access token, refresh token, authorization code, Authorization
header, serialized token-cache entry, or raw Microsoft 365 response - see
``IqDiagnostics`` in ``app/iq/models.py`` for the enforced field set.

Callers (``app/api/iq_diagnostics.py``) additionally gate this entire
capability to non-production environments - this service does not gate
itself, so it remains simple to unit test directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.iq.delegated_connection_manager import DelegatedConnectionError
from app.iq.delegated_connection_service import DelegatedConnectionService
from app.iq.delegated_token_broker import DelegatedAuthError
from app.iq.mcp_client import IqMcpError
from app.iq.models import IqDiagnostics
from app.services.session_service import SessionService


@dataclass(frozen=True)
class IqDiagnosticsConfig:
    """Non-secret configuration-presence flags, computed once at startup
    from ``Settings`` - deliberately booleans only, never the configured
    values themselves (a tenant id or client id is not a secret, but this
    service's whole purpose is to answer "configured: yes/no" questions,
    not to echo configuration back)."""

    work_iq_enabled: bool
    tenant_configured: bool
    client_configured: bool
    redirect_uri_configured: bool
    work_iq_endpoint_configured: bool


class IqDiagnosticsService:
    def __init__(
        self,
        *,
        config: IqDiagnosticsConfig,
        connection_service: DelegatedConnectionService | None,
        session_service: SessionService,
    ) -> None:
        self._config = config
        self._connection_service = connection_service
        self._session_service = session_service

    async def diagnostics(self, *, session_id: str, requesting_user_id: str) -> IqDiagnostics:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        correlation_id = str(uuid4())
        connected = False
        mcp_initialized = False
        tools_discovered_count: int | None = None
        last_error_category: str | None = None

        if self._connection_service is not None:
            identity = await self._connection_service.resolve_identity(
                session_id=session_id, provider="work_iq"
            )
            connected = identity is not None
            if connected:
                try:
                    ready = await self._connection_service.get_ready_connection(
                        session_id=session_id, provider="work_iq"
                    )
                except (DelegatedConnectionError, DelegatedAuthError) as exc:
                    last_error_category = getattr(exc, "category", "unavailable")
                else:
                    if ready is not None:
                        client, _identity = ready
                        try:
                            tools = await client.list_tools()
                        except IqMcpError as exc:
                            last_error_category = exc.category
                        else:
                            tools_discovered_count = len(tools)
                            mcp_initialized = True

        return IqDiagnostics(
            microsoft_connect_enabled=self._config.work_iq_enabled,
            work_iq_enabled=self._config.work_iq_enabled,
            tenant_configured=self._config.tenant_configured,
            client_configured=self._config.client_configured,
            redirect_uri_configured=self._config.redirect_uri_configured,
            work_iq_endpoint_configured=self._config.work_iq_endpoint_configured,
            connected=connected,
            mcp_initialized=mcp_initialized,
            tools_discovered_count=tools_discovered_count,
            last_error_category=last_error_category,
            correlation_id=correlation_id,
        )
