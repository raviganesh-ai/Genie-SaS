"""Typed IQ provider and evidence models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

IqProviderName = Literal["work_iq", "foundry_iq", "fabric_iq", "foundry_mcp"]
CandidateStatus = Literal["pending", "confirmed", "rejected", "unresolved", "superseded", "promoted"]

# Providers whose live authorization model requires a signed-in Microsoft
# user's delegated identity (Work IQ, Fabric IQ - confirmed by Microsoft's
# own documentation to have no application-only/service-principal path).
# Every other provider keeps the prior administrator-token/configuration
# pattern (app.iq.mcp_client + a static token environment variable).
DELEGATED_PROVIDERS: frozenset[IqProviderName] = frozenset({"work_iq", "fabric_iq"})

# Capability is the abstraction Genie agents and the IQ router use - never a
# Microsoft-service-specific name. The router (app.iq.router.IQRouter) is the
# single place that maps a capability onto a concrete provider.
IqCapability = Literal["WORK_CONTEXT", "BUSINESS_CONTEXT", "KNOWLEDGE_CONTEXT", "FOUNDRY_CONTEXT"]

# Explicit provider status vocabulary. IQ is always enrichment, never a hard
# dependency - a provider settling on anything other than IQ_AVAILABLE must
# not fail the calling workflow; callers decide whether to proceed without it.
# The CONSENT_REQUIRED/SESSION_EXPIRED/TENANT_MISMATCH/APPROVAL_REQUIRED/
# FAILED members exist specifically for delegated (OAuth) providers; they
# are never emitted by the static administrator-token providers.
IqStatus = Literal[
    "IQ_AVAILABLE",
    "IQ_NOT_REQUIRED",
    "IQ_NOT_CONFIGURED",
    "IQ_AUTHENTICATION_REQUIRED",
    "IQ_CONSENT_REQUIRED",
    "IQ_SESSION_EXPIRED",
    "IQ_TENANT_MISMATCH",
    "IQ_PERMISSION_DENIED",
    "IQ_APPROVAL_REQUIRED",
    "IQ_UNAVAILABLE",
    "IQ_TIMEOUT",
    "IQ_FAILED",
]

# MCP tool mutation classification, derived from the tool's official MCP
# annotations (readOnlyHint/destructiveHint/idempotentHint/openWorldHint -
# see https://modelcontextprotocol.io) where the server provides them.
# "unknown" is the safe default when a server omits annotations entirely;
# app.iq.tool_classification treats "unknown" the same as every mutating
# class - approval required before the tool is called.
IqToolMutationClass = Literal[
    "read_only",
    "data_querying",
    "configuration_changing",
    "resource_creating",
    "resource_deleting",
    "permission_changing",
    "unknown",
]


class DelegatedIdentityContext(BaseModel):
    """Stable identifiers for one delegated Microsoft identity bound to one
    Genie session. Deliberately holds no token, scope, or authority value -
    every identity-boundary component (DelegatedTokenBroker, token cache,
    connection manager) accepts this object, never a raw credential, per
    the "agents must not acquire/inspect/cache/forward tokens" requirement.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    # The Entra object id (oid) of the signed-in user - stable across token
    # refreshes and the correct partition key, unlike a mutable UPN/email.
    subject: str = Field(min_length=1)
    display_name: str | None = None
    correlation_id: str = Field(min_length=1)


# Category vocabulary raised by
# ``app.iq.delegated_token_broker.DelegatedAuthError``, kept in 1:1
# correspondence with the delegated-provider subset of ``IqStatus`` above.
DelegatedAuthErrorCategoryName = Literal[
    "authentication_required",
    "consent_required",
    "session_expired",
    "tenant_mismatch",
    "permission_denied",
]


class IqProviderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: IqProviderName
    status: IqStatus
    # Retained for backward compatibility with existing callers/UI built
    # against the boolean contract; both are always derivable from `status`.
    enabled: bool
    connected: bool
    retrieve_tool: str | None = None
    available_tools: list[str] = Field(default_factory=list)
    detail: str


class IqEvidenceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    provider: IqProviderName
    query: str
    content: Any
    citations: list[str] = Field(default_factory=list)
    sensitivity: str
    authorization_principal: str
    retrieved_at: datetime
    raw_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class IqEvidenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    evidence: IqEvidenceEnvelope
    status: CandidateStatus = "pending"
    review_comment: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class IqConnectionStatus(BaseModel):
    """Per-session, per-provider delegated connection status returned to the
    frontend. Deliberately exposes only non-sensitive identifiers - never a
    token, refresh token, authorization code, or client secret."""

    model_config = ConfigDict(extra="forbid")

    provider: IqProviderName
    status: IqStatus
    connected: bool
    tenant_id: str | None = None
    display_name: str | None = None
    connected_at: datetime | None = None
    detail: str


class IqDiagnostics(BaseModel):
    """Development-only diagnostic snapshot. Every field is a boolean,
    count, category label, or correlation id - this model must never gain
    a field that could hold a token, secret, authorization code, or
    Microsoft 365 content. Enforced by ``extra="forbid"`` plus the
    dev-only route gate in ``app/api/iq_diagnostics.py``."""

    model_config = ConfigDict(extra="forbid")

    microsoft_connect_enabled: bool
    work_iq_enabled: bool
    tenant_configured: bool
    client_configured: bool
    redirect_uri_configured: bool
    work_iq_endpoint_configured: bool
    connected: bool
    mcp_initialized: bool
    tools_discovered_count: int | None = None
    last_error_category: str | None = None
    correlation_id: str


class WorkIqValidationResult(BaseModel):
    """Result of the development-only, explicit-action Work IQ validation
    call. Never persisted (see ``WorkIqValidationService`` - no repository
    write occurs) and never carries raw Microsoft 365 content -
    ``response_preview`` is truncated and ``citations`` are reference URLs
    only, matching the existing ``IqEvidenceEnvelope.citations`` contract."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    provider: IqProviderName
    tool_invoked: str | None = None
    response_preview: str | None = None
    citations: list[str] = Field(default_factory=list)
    correlation_id: str
    duration_ms: float
    error_category: str | None = None
    detail: str


