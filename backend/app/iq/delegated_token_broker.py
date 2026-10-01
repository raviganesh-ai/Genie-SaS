"""Delegated OAuth 2.0 authorization-code + PKCE broker for Work IQ / Fabric IQ.

Implements exactly the flow Microsoft documents for these two services:
delegated Microsoft Entra ID user authentication, discovered per the MCP
Authorization specification (https://modelcontextprotocol.io) rather than
a hardcoded Microsoft-specific shortcut:

1. ``GET {mcp origin}/.well-known/oauth-protected-resource`` - discovers
   which authorization server(s) protect the MCP resource.
2. ``GET {authorization_server}/.well-known/oauth-authorization-server``
   (falling back to the standard OIDC ``/.well-known/openid-configuration``
   document, which Microsoft Entra ID's v2 issuer serves) - discovers the
   ``authorization_endpoint``/``token_endpoint``/``jwks_uri``.
3. Standard OAuth 2.0 authorization-code + PKCE (S256) against those
   discovered endpoints, using Genie-SaS's own confidential-client
   registration (client id + Key-Vault-backed client secret + redirect URI,
   all externally configured - never hardcoded).
4. The returned ID token is signature-validated (RS256, via the discovered
   ``jwks_uri``) purely to extract the ``tid``/``oid``/``name`` claims
   needed to bind the resulting token to a ``DelegatedIdentityContext`` and
   to detect a tenant mismatch - it is never used to authenticate a Genie
   API request (Genie-SaS's own request authentication is unchanged).

No token, refresh token, authorization code, or client secret is ever
logged, returned to a caller error message, or included in any exception
string - every error is raised as a ``DelegatedAuthError`` carrying only a
classification category and a safe, static message.
"""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from app.iq.microsoft_resource_registry import MicrosoftMcpResourceRegistry
from app.iq.models import DelegatedAuthErrorCategoryName, IqProviderName


class DelegatedAuthError(RuntimeError):
    """Raised for every delegated OAuth failure. ``category`` maps 1:1 onto
    the delegated-provider subset of ``IqStatus`` - callers never need to
    parse the message to decide how to respond."""

    def __init__(self, message: str, *, category: DelegatedAuthErrorCategoryName) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class OAuthDiscoveryDocument:
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    issuer: str


@dataclass(frozen=True)
class ExchangedDelegatedToken:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scopes: tuple[str, ...]
    tenant_id: str
    subject: str
    display_name: str | None

    def __repr__(self) -> str:  # pragma: no cover - defensive redaction
        return (
            f"ExchangedDelegatedToken(access_token='***redacted***', "
            f"refresh_token={'***redacted***' if self.refresh_token else None}, "
            f"tenant_id={self.tenant_id!r}, subject={self.subject!r})"
        )

    __str__ = __repr__


def generate_pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class DelegatedTokenBroker:
    def __init__(
        self,
        *,
        registry: MicrosoftMcpResourceRegistry,
        client_id: str,
        client_secret_env_var: str,
        redirect_uri: str,
        allowed_tenant_id: str,
        timeout_seconds: float = 30,
    ) -> None:
        self._registry = registry
        self._client_id = client_id
        self._client_secret_env_var = client_secret_env_var
        self._redirect_uri = redirect_uri
        self._allowed_tenant_id = allowed_tenant_id
        self._timeout_seconds = timeout_seconds
        self._discovery_cache: dict[IqProviderName, OAuthDiscoveryDocument] = {}

    async def build_authorization_url(
        self, *, provider: IqProviderName, state: str, code_verifier: str
    ) -> str:
        resource = self._registry.get(provider)
        discovery = await self._discover(provider)
        challenge = generate_pkce_challenge(code_verifier)
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "response_mode": "query",
            "scope": " ".join((*resource.scopes, "openid", "profile")),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        query = httpx.QueryParams(params)
        return f"{discovery.authorization_endpoint}?{query}"

    async def exchange_code(
        self, *, provider: IqProviderName, code: str, code_verifier: str
    ) -> ExchangedDelegatedToken:
        discovery = await self._discover(provider)
        resource = self._registry.get(provider)
        form = {
            "client_id": self._client_id,
            "client_secret": self._client_secret(),
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
            "code_verifier": code_verifier,
            "scope": " ".join((*resource.scopes, "openid", "profile")),
        }
        payload = await self._post_token_endpoint(discovery.token_endpoint, form)
        return await self._to_exchanged_token(payload, discovery=discovery, scopes=resource.scopes)

    async def refresh(
        self, *, provider: IqProviderName, refresh_token: str
    ) -> ExchangedDelegatedToken:
        discovery = await self._discover(provider)
        resource = self._registry.get(provider)
        form = {
            "client_id": self._client_id,
            "client_secret": self._client_secret(),
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join((*resource.scopes, "openid", "profile")),
        }
        payload = await self._post_token_endpoint(discovery.token_endpoint, form, is_refresh=True)
        return await self._to_exchanged_token(payload, discovery=discovery, scopes=resource.scopes)

    def _client_secret(self) -> str:
        secret = os.environ.get(self._client_secret_env_var)
        if not secret:
            raise DelegatedAuthError(
                "The configured IQ OAuth client secret environment variable is empty.",
                category="authentication_required",
            )
        return secret

    async def _post_token_endpoint(
        self, token_endpoint: str, form: dict[str, str], *, is_refresh: bool = False
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    token_endpoint,
                    data=form,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.TimeoutException as exc:
            raise DelegatedAuthError(
                "The Microsoft token endpoint timed out.", category="authentication_required"
            ) from exc
        except httpx.HTTPError as exc:
            raise DelegatedAuthError(
                "The Microsoft token endpoint is unavailable.", category="authentication_required"
            ) from exc
        if response.status_code == 200:
            return response.json()
        self._raise_for_token_error_response(response, is_refresh=is_refresh)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _raise_for_token_error_response(response: httpx.Response, *, is_refresh: bool) -> None:
        try:
            body = response.json()
        except ValueError:
            body = {}
        error_code = str(body.get("error", "")) if isinstance(body, dict) else ""
        # Microsoft Entra ID error codes: https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes
        if error_code in {"invalid_grant"} and is_refresh:
            raise DelegatedAuthError(
                "The delegated refresh token is expired or has been revoked.",
                category="session_expired",
            )
        if error_code in {"consent_required", "interaction_required"}:
            raise DelegatedAuthError(
                "Microsoft requires additional user consent for this scope.",
                category="consent_required",
            )
        if response.status_code in (401, 400) and error_code in {"invalid_client", "invalid_grant"}:
            raise DelegatedAuthError(
                "The delegated authorization could not be completed.",
                category="authentication_required",
            )
        if response.status_code == 403:
            raise DelegatedAuthError(
                "The signed-in user does not have permission for this resource.",
                category="permission_denied",
            )
        raise DelegatedAuthError(
            "The Microsoft token endpoint rejected the request.",
            category="authentication_required",
        )

    async def _to_exchanged_token(
        self,
        payload: dict[str, Any],
        *,
        discovery: OAuthDiscoveryDocument,
        scopes: tuple[str, ...],
    ) -> ExchangedDelegatedToken:
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise DelegatedAuthError(
                "Microsoft did not return a delegated access token.",
                category="authentication_required",
            )
        id_token = payload.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise DelegatedAuthError(
                "Microsoft did not return an ID token to bind the delegated identity.",
                category="authentication_required",
            )
        claims = await self._validate_id_token(id_token, discovery=discovery)
        tenant_id = claims.get("tid")
        subject = claims.get("oid") or claims.get("sub")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise DelegatedAuthError(
                "The Microsoft ID token has no tenant claim.", category="authentication_required"
            )
        if not isinstance(subject, str) or not subject:
            raise DelegatedAuthError(
                "The Microsoft ID token has no stable subject claim.",
                category="authentication_required",
            )
        if tenant_id != self._allowed_tenant_id:
            raise DelegatedAuthError(
                "The signed-in user belongs to a different Microsoft Entra tenant.",
                category="tenant_mismatch",
            )
        expires_in = payload.get("expires_in")
        expires_at = datetime.now(UTC) + timedelta(seconds=float(expires_in) if expires_in else 3600)
        display_name = claims.get("name") if isinstance(claims.get("name"), str) else None
        return ExchangedDelegatedToken(
            access_token=access_token,
            refresh_token=payload.get("refresh_token"),
            expires_at=expires_at,
            scopes=scopes,
            tenant_id=tenant_id,
            subject=subject,
            display_name=display_name,
        )

    async def _validate_id_token(
        self, id_token: str, *, discovery: OAuthDiscoveryDocument
    ) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise DelegatedAuthError(
                "The Microsoft ID token header is invalid.", category="authentication_required"
            ) from exc
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise DelegatedAuthError(
                "The Microsoft ID token signing header is invalid.",
                category="authentication_required",
            )
        key = await self._signing_key(discovery.jwks_uri, kid)
        try:
            return jwt.decode(
                id_token,
                key=key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=discovery.issuer,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise DelegatedAuthError(
                "The Microsoft ID token could not be validated.",
                category="authentication_required",
            ) from exc

    async def _signing_key(self, jwks_uri: str, kid: str) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(jwks_uri)
            response.raise_for_status()
            jwks = response.json()
        for value in jwks.get("keys", []):
            if isinstance(value, dict) and value.get("kid") == kid:
                return jwt.PyJWK.from_dict(value, algorithm="RS256").key
        raise DelegatedAuthError(
            "Microsoft's signing key for this ID token is unknown.",
            category="authentication_required",
        )

    async def _discover(self, provider: IqProviderName) -> OAuthDiscoveryDocument:
        cached = self._discovery_cache.get(provider)
        if cached is not None:
            return cached
        resource = self._registry.get(provider)
        origin = httpx.URL(resource.mcp_endpoint)
        # RFC 9728 (OAuth 2.0 Protected Resource Metadata) §3.1: when the
        # resource identifier has a non-empty path component, the
        # well-known URI is constructed by INSERTING the well-known path
        # segment between the host and the resource's own path - never by
        # replacing the resource's path outright. Confirmed against the
        # live Work IQ MCP server: a bare
        # "https://workiq.svc.cloud.microsoft/.well-known/oauth-protected-resource"
        # request returns HTTP 400 "Invalid request, no valid route.",
        # while
        # "https://workiq.svc.cloud.microsoft/.well-known/oauth-protected-resource/mcp"
        # (this resource's own "/mcp" path appended) returns 200 with the
        # expected metadata document. See
        # docs/validation/work-iq-development-validation.md for this
        # finding's full context.
        resource_path = origin.path if origin.path not in ("", "/") else ""
        protected_resource_url = origin.copy_with(
            path=f"/.well-known/oauth-protected-resource{resource_path}", query=None
        )
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            try:
                protected_resource_response = await client.get(str(protected_resource_url))
                protected_resource_response.raise_for_status()
            except httpx.HTTPError as exc:
                raise DelegatedAuthError(
                    "Unable to discover the delegated authorization configuration for this "
                    "Microsoft MCP resource.",
                    category="authentication_required",
                ) from exc
            protected_resource = protected_resource_response.json()
            authorization_servers = protected_resource.get("authorization_servers")
            if not isinstance(authorization_servers, list) or not authorization_servers:
                raise DelegatedAuthError(
                    "The Microsoft MCP resource did not declare an authorization server.",
                    category="authentication_required",
                )
            authorization_server = str(authorization_servers[0]).rstrip("/")
            as_metadata = await self._fetch_authorization_server_metadata(
                client, authorization_server
            )
        discovery = OAuthDiscoveryDocument(
            authorization_endpoint=as_metadata["authorization_endpoint"],
            token_endpoint=as_metadata["token_endpoint"],
            jwks_uri=as_metadata["jwks_uri"],
            issuer=as_metadata["issuer"],
        )
        self._discovery_cache[provider] = discovery
        return discovery

    @staticmethod
    async def _fetch_authorization_server_metadata(
        client: httpx.AsyncClient, authorization_server: str
    ) -> dict[str, Any]:
        # MCP Authorization spec-first: try the OAuth 2.0 Authorization
        # Server Metadata path (RFC 8414) before falling back to the
        # standard OIDC discovery document Microsoft Entra ID's v2 issuer
        # serves at the same origin.
        for path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
            try:
                response = await client.get(f"{authorization_server}{path}")
            except httpx.HTTPError:
                continue
            if response.status_code == 200:
                metadata = response.json()
                if all(
                    key in metadata
                    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer")
                ):
                    return metadata
        raise DelegatedAuthError(
            "Unable to discover the Microsoft Entra authorization server metadata.",
            category="authentication_required",
        )
