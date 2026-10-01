"""Tests for the delegated OAuth 2.0 + PKCE token broker.

Mocks only the MCP discovery/token-endpoint HTTP calls - no live Microsoft
service is contacted. A real RS256 keypair is generated once per test
module so the broker's ID-token signature validation exercises genuine
cryptographic verification rather than being stubbed out.
"""
from __future__ import annotations

import base64
import hashlib
import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from app.iq.delegated_token_broker import (
    DelegatedAuthError,
    DelegatedTokenBroker,
    generate_pkce_challenge,
)
from app.iq.microsoft_resource_registry import MicrosoftMcpResourceRegistry

_TENANT_ID = "11111111-1111-1111-1111-111111111111"
_CLIENT_ID = "22222222-2222-2222-2222-222222222222"
_SUBJECT = "33333333-3333-3333-3333-333333333333"
_ISSUER = f"https://login.microsoftonline.com/{_TENANT_ID}/v2.0"
_KID = "test-signing-key"
_CLIENT_SECRET_ENV_VAR = "TEST_IQ_OAUTH_CLIENT_SECRET"


@pytest.fixture(scope="module")
def rsa_key() -> RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(rsa_key: RSAPrivateKey) -> dict[str, Any]:
    public_numbers = rsa_key.public_key().public_numbers()

    def _b64(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": _KID,
                "use": "sig",
                "alg": "RS256",
                "n": _b64(public_numbers.n),
                "e": _b64(public_numbers.e),
            }
        ]
    }


def _id_token(
    rsa_key: RSAPrivateKey, *, tenant_id: str = _TENANT_ID, subject: str = _SUBJECT, name: str = "Ada Lovelace"
) -> str:
    now = int(time.time())
    claims = {
        "iss": _ISSUER,
        "aud": _CLIENT_ID,
        "tid": tenant_id,
        "oid": subject,
        "sub": subject,
        "name": name,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": _KID})


def _registry() -> MicrosoftMcpResourceRegistry:
    return MicrosoftMcpResourceRegistry.from_settings(
        work_iq_mcp_endpoint="https://workiq.svc.cloud.microsoft/mcp",
        work_iq_scopes=None,  # exercises the confirmed documented default
        fabric_iq_mcp_endpoint="https://fabriciq.svc.cloud.microsoft/v1/mcp/fabriciq",
        fabric_iq_scopes=("https://analysis.windows.net/powerbi/api/Item.Read.All",),
    )


def _broker() -> DelegatedTokenBroker:
    return DelegatedTokenBroker(
        registry=_registry(),
        client_id=_CLIENT_ID,
        client_secret_env_var=_CLIENT_SECRET_ENV_VAR,
        redirect_uri="https://genie.example.test/iq/connections/callback",
        allowed_tenant_id=_TENANT_ID,
    )


def _mock_transport(monkeypatch, rsa_key: RSAPrivateKey, *, token_response: httpx.Response | Exception):
    async def fake_get(self, url, *args, **kwargs):
        request = httpx.Request("GET", url)
        if "/.well-known/oauth-protected-resource" in url:
            return httpx.Response(
                200,
                request=request,
                json={"authorization_servers": [f"https://login.microsoftonline.com/{_TENANT_ID}/v2.0"]},
            )
        if url.endswith("/.well-known/oauth-authorization-server"):
            return httpx.Response(404, request=request)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                request=request,
                json={
                    "issuer": _ISSUER,
                    "authorization_endpoint": f"{_ISSUER}/oauth2/v2.0/authorize",
                    "token_endpoint": f"{_ISSUER}/oauth2/v2.0/token",
                    "jwks_uri": f"{_ISSUER}/discovery/v2.0/keys",
                },
            )
        if url.endswith("/discovery/v2.0/keys"):
            return httpx.Response(200, request=request, json=_jwks(rsa_key))
        raise AssertionError(f"Unexpected GET {url}")

    async def fake_post(self, url, *args, **kwargs):
        if isinstance(token_response, Exception):
            raise token_response
        return token_response

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


def test_generate_pkce_challenge_is_deterministic_and_matches_s256() -> None:
    verifier = "a-fixed-test-code-verifier-value"

    challenge = generate_pkce_challenge(verifier)

    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected
    assert "=" not in challenge  # PKCE requires unpadded base64url


async def test_build_authorization_url_includes_pkce_and_documented_work_iq_scope(monkeypatch) -> None:
    _mock_transport(monkeypatch, rsa.generate_private_key(public_exponent=65537, key_size=2048), token_response=Exception())
    broker = _broker()

    url = await broker.build_authorization_url(
        provider="work_iq", state="state-value", code_verifier="verifier-value"
    )

    assert url.startswith(f"{_ISSUER}/oauth2/v2.0/authorize?")
    assert "code_challenge_method=S256" in url
    assert "state=state-value" in url
    assert "api%3A%2F%2Fworkiq.svc.cloud.microsoft%2FWorkIQAgent.Ask" in url or "WorkIQAgent.Ask" in url


async def test_discovery_requests_the_well_known_path_suffixed_with_the_resource_path(
    monkeypatch, rsa_key
) -> None:
    """Regression test for a real defect found during development validation
    (2026-09-30): a bare
    ``https://workiq.svc.cloud.microsoft/.well-known/oauth-protected-resource``
    request (replacing the resource's own path) was confirmed LIVE against
    Microsoft's real Work IQ MCP server to return HTTP 400 "Invalid request,
    no valid route." RFC 9728 (OAuth 2.0 Protected Resource Metadata) §3.1
    requires the well-known path segment to be inserted before the
    resource's own path, not to replace it -
    ``https://workiq.svc.cloud.microsoft/.well-known/oauth-protected-resource/mcp``
    - confirmed LIVE to return 200 with the expected metadata document. See
    ``docs/validation/work-iq-development-validation.md``."""

    requested_urls: list[str] = []

    async def fake_get(self, url, *args, **kwargs):
        requested_urls.append(str(url))
        request = httpx.Request("GET", url)
        if "/.well-known/oauth-protected-resource/mcp" in url:
            return httpx.Response(
                200,
                request=request,
                json={"authorization_servers": [f"https://login.microsoftonline.com/{_TENANT_ID}/v2.0"]},
            )
        if url.endswith("/.well-known/oauth-authorization-server"):
            return httpx.Response(404, request=request)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                request=request,
                json={
                    "issuer": _ISSUER,
                    "authorization_endpoint": f"{_ISSUER}/oauth2/v2.0/authorize",
                    "token_endpoint": f"{_ISSUER}/oauth2/v2.0/token",
                    "jwks_uri": f"{_ISSUER}/discovery/v2.0/keys",
                },
            )
        raise AssertionError(f"Unexpected GET {url}")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    broker = _broker()

    await broker.build_authorization_url(
        provider="work_iq", state="state-value", code_verifier="verifier-value"
    )

    protected_resource_requests = [u for u in requested_urls if "oauth-protected-resource" in u]
    assert protected_resource_requests == [
        "https://workiq.svc.cloud.microsoft/.well-known/oauth-protected-resource/mcp"
    ]


async def test_exchange_code_returns_identity_bound_to_the_id_token_claims(monkeypatch, rsa_key) -> None:
    monkeypatch.setenv(_CLIENT_SECRET_ENV_VAR, "client-secret-value")
    id_token = _id_token(rsa_key)
    token_response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://example.test"),
        json={
            "access_token": "delegated-access-token",
            "refresh_token": "delegated-refresh-token",
            "id_token": id_token,
            "expires_in": 3600,
        },
    )
    _mock_transport(monkeypatch, rsa_key, token_response=token_response)
    broker = _broker()

    exchanged = await broker.exchange_code(
        provider="work_iq", code="auth-code", code_verifier="verifier-value"
    )

    assert exchanged.access_token == "delegated-access-token"
    assert exchanged.refresh_token == "delegated-refresh-token"
    assert exchanged.tenant_id == _TENANT_ID
    assert exchanged.subject == _SUBJECT
    assert exchanged.display_name == "Ada Lovelace"


async def test_exchange_code_rejects_a_different_tenants_id_token(monkeypatch, rsa_key) -> None:
    monkeypatch.setenv(_CLIENT_SECRET_ENV_VAR, "client-secret-value")
    wrong_tenant_id_token = _id_token(rsa_key, tenant_id="99999999-9999-9999-9999-999999999999")
    token_response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://example.test"),
        json={
            "access_token": "delegated-access-token",
            "id_token": wrong_tenant_id_token,
            "expires_in": 3600,
        },
    )
    _mock_transport(monkeypatch, rsa_key, token_response=token_response)
    broker = _broker()

    with pytest.raises(DelegatedAuthError) as exc_info:
        await broker.exchange_code(provider="work_iq", code="auth-code", code_verifier="verifier-value")

    assert exc_info.value.category == "tenant_mismatch"


async def test_refresh_with_invalid_grant_raises_session_expired(monkeypatch, rsa_key) -> None:
    monkeypatch.setenv(_CLIENT_SECRET_ENV_VAR, "client-secret-value")
    token_response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://example.test"),
        json={"error": "invalid_grant", "error_description": "Token expired"},
    )
    _mock_transport(monkeypatch, rsa_key, token_response=token_response)
    broker = _broker()

    with pytest.raises(DelegatedAuthError) as exc_info:
        await broker.refresh(provider="work_iq", refresh_token="stale-refresh-token")

    assert exc_info.value.category == "session_expired"


async def test_consent_required_error_is_classified_correctly(monkeypatch, rsa_key) -> None:
    monkeypatch.setenv(_CLIENT_SECRET_ENV_VAR, "client-secret-value")
    token_response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://example.test"),
        json={"error": "consent_required"},
    )
    _mock_transport(monkeypatch, rsa_key, token_response=token_response)
    broker = _broker()

    with pytest.raises(DelegatedAuthError) as exc_info:
        await broker.exchange_code(provider="work_iq", code="auth-code", code_verifier="verifier-value")

    assert exc_info.value.category == "consent_required"


async def test_permission_denied_status_is_classified_correctly(monkeypatch, rsa_key) -> None:
    monkeypatch.setenv(_CLIENT_SECRET_ENV_VAR, "client-secret-value")
    token_response = httpx.Response(
        403,
        request=httpx.Request("POST", "https://example.test"),
        json={"error": "access_denied"},
    )
    _mock_transport(monkeypatch, rsa_key, token_response=token_response)
    broker = _broker()

    with pytest.raises(DelegatedAuthError) as exc_info:
        await broker.exchange_code(provider="work_iq", code="auth-code", code_verifier="verifier-value")

    assert exc_info.value.category == "permission_denied"


async def test_missing_client_secret_raises_authentication_required(monkeypatch, rsa_key) -> None:
    monkeypatch.delenv(_CLIENT_SECRET_ENV_VAR, raising=False)
    _mock_transport(monkeypatch, rsa_key, token_response=Exception())
    broker = _broker()

    with pytest.raises(DelegatedAuthError) as exc_info:
        await broker.exchange_code(provider="work_iq", code="auth-code", code_verifier="verifier-value")

    assert exc_info.value.category == "authentication_required"


def test_error_message_never_contains_a_client_secret_or_token() -> None:
    error = DelegatedAuthError("boom", category="authentication_required")

    assert "client-secret-value" not in str(error)
    assert "delegated-access-token" not in str(error)
