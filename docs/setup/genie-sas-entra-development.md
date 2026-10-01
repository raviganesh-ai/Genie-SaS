# Genie-SaS Entra Development App Registration

This document is a **checklist**, not a record of a completed registration.
No IDs, secrets, or tenant information in this file are real - every value
below is a placeholder to be filled in by whoever performs the actual
registration in their own development tenant. See
[`genie-sas-microsoft-iq.md`](../architecture/genie-sas-microsoft-iq.md)
for the full delegated-OAuth architecture this configuration supports.

> **If you cannot register an Entra application from your current
> environment** (no tenant access, no administrator role, no portal
> access), use this document as the exact list of what a tenant
> administrator needs to create and hand back to you. Do not fabricate
> values to make validation appear complete.

## 1. Suggested application name

```
Genie-SaS Development
```

## 2. Supported account type

**Single tenant** - "Accounts in this organizational directory only
(Default Directory only - Single tenant)".

Why: `DelegatedTokenBroker` validates the ID token's `tid` claim against
one configured `GENIE_IQ_OAUTH_TENANT_ID` and rejects anything else with
`TENANT_MISMATCH` (see `app/iq/delegated_token_broker.py`,
`_to_exchanged_token`). A multi-tenant registration would not change this
behavior - Genie-SaS would still reject every other tenant - so single
tenant is both sufficient and clearer about the intended scope.

## 3. Development redirect URI

Derived from the actual callback route implemented in
`app/api/iq_connections.py` (`GET /iq/connections/callback`) and your
local/dev host:

```
http://localhost:8000/iq/connections/callback
```

Replace `http://localhost:8000` with your actual development backend
origin if different (e.g. a deployed non-production Container App FQDN -
in that case use `https://`, not `http://`; see 
`ConfigurationValidator`'s rule that `iq_oauth_redirect_uri` must use
HTTPS whenever a delegated provider is enabled outside pure localhost
manual testing).

## 4. Redirect platform type

**Web**, not **Single-page application (SPA)**.

Why: Genie-SaS's backend (`DelegatedTokenBroker`) is a confidential
client - it authenticates the token exchange with a client secret
(`iq_oauth_client_secret_env_var`) sent directly to Microsoft's token
endpoint from the FastAPI backend, not from the browser. The SPA platform
type is for public clients doing a browser-only PKCE exchange with no
client secret; using it here would not match the implementation and
Microsoft's identity platform would reject the confidential-client token
request.

## 5. Logout / post-logout URI

**Not used.** The current implementation
(`app/iq/delegated_connection_service.py::disconnect`) only clears
Genie-SaS's own local token cache for that session/provider - it never
calls Microsoft's `/logout` endpoint or redirects the browser there. No
post-logout redirect URI needs to be registered for this implementation.

## 6. Required delegated Work IQ permission

```
WorkIQAgent.Ask
```

- **Type:** Delegated (not Application).
- **Admin consent required:** **Yes**, per Microsoft's own Work IQ API
  permissions reference (`AdminConsentRequired: Yes` for
  `WorkIQAgent.Ask`).
- Full scope string Genie-SaS requests by default (see
  `app/iq/microsoft_resource_registry.py`):
  `api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask`.

## 7. Additional OpenID Connect scopes required

Genie-SaS's `DelegatedTokenBroker.build_authorization_url` appends these
two scopes to every authorization request, in addition to the
provider-specific scope(s) above (see
`app/iq/delegated_token_broker.py`):

```
openid
profile
```

- `openid` - required so Microsoft issues an ID token; Genie-SaS parses
  its `tid` (tenant), `oid` (subject), and `name` claims to build the
  `DelegatedIdentityContext` - it is never used to authenticate a Genie
  API call.
- `profile` - supplies the `name` claim used for the connected-account
  display name shown in the UI (`IqConnectionStatus.display_name`).

`offline_access` is **not currently requested** by the implementation.
Without it, Microsoft may not return a `refresh_token`, and
`DelegatedMcpConnectionManager._refresh` will then raise
`session_expired` the first time the access token expires - the
connected user will need to reconnect rather than being silently
refreshed. If you want transparent refresh, add `offline_access` to the
app registration's requested permissions **and** to the scope string
`DelegatedTokenBroker` requests; this is a known, documented gap, not
already-implemented behavior - do not assume it works without both
changes.

## 8. Client authentication method

**Client secret**, read from an environment variable
(`GENIE_IQ_OAUTH_CLIENT_SECRET_ENV_VAR` names *which* environment variable
holds it - the secret value itself is never a typed application setting;
see `app/iq/delegated_token_broker.py::_client_secret`). Certificate-based
client authentication is not implemented.

## 9. Where to configure the client ID, tenant ID, and secret reference

All three are environment variables consumed by `app/config/settings.py`,
prefixed `GENIE_`:

| Value | Environment variable |
| --- | --- |
| Tenant ID | `GENIE_IQ_OAUTH_TENANT_ID` |
| Client (application) ID | `GENIE_IQ_OAUTH_CLIENT_ID` |
| Name of the env var holding the client secret | `GENIE_IQ_OAUTH_CLIENT_SECRET_ENV_VAR` |
| Redirect URI | `GENIE_IQ_OAUTH_REDIRECT_URI` |

See [Step 3: development configuration](#) in the validation task for the
exact `.env` template - `backend/.env.example`.

## 10. Required secret-management approach

**Local development:** put the actual secret value in a local `.env` file
that is already `.gitignore`d (confirm `backend/.env` is not tracked
before adding it - never commit a populated `.env`). The variable *name*
referenced by `GENIE_IQ_OAUTH_CLIENT_SECRET_ENV_VAR` must match exactly.

**Hosted non-production environment:** use the same pattern Genie-SaS
already uses for its other MCP secrets (GitHub MCP token) - a Container
App secret reference (`secretRef`), not a plain environment variable
value, provisioned via `scripts/deploy_backend.ps1`'s existing
`Set-ContainerSecretEnvironmentVariable` helper. Do not introduce a new
secret-storage mechanism for this one value.

## 11. How to remove or rotate development credentials

1. In the Entra app registration's **Certificates & secrets** blade,
   delete the old client secret (or let it expire - development secrets
   should use the shortest available expiry, e.g. 90 days).
2. Generate a new client secret.
3. Update the value stored under whatever secret store name
   `GENIE_IQ_OAUTH_CLIENT_SECRET_ENV_VAR` resolves to (local `.env`, or the
   Container App secret) - **do not** change the env var *name* unless you
   also update `GENIE_IQ_OAUTH_CLIENT_SECRET_ENV_VAR` to match.
4. Restart/redeploy Genie-SaS so the new secret is read at startup.
5. To fully decommission: delete the app registration entirely once no
   environment still references its client ID.

## 12. Expected consent experience

1. User clicks **Connect Microsoft 365** (Work IQ) in Genie-SaS.
2. Genie-SaS's backend redirects the whole browser tab to Microsoft's
   `/oauth2/v2.0/authorize` endpoint (discovered dynamically, not
   hardcoded - see `DelegatedTokenBroker._discover`).
3. The user signs in with their own Microsoft work/school account for the
   configured tenant.
4. **First time only** (until a tenant administrator has granted admin
   consent for `WorkIQAgent.Ask`): the user sees a permissions consent
   screen requesting `WorkIQAgent.Ask`, `openid`, `profile`. If the
   tenant requires admin consent and none has been granted, the user sees
   an error ("needs permission from an administrator") instead of being
   able to consent themselves.
5. On success, Microsoft redirects back to
   `GENIE_IQ_OAUTH_REDIRECT_URI` with `code`+`state`; Genie-SaS exchanges
   the code server-side and redirects the browser back to
   `/iq-collaboration?iq_connect=connected&provider=work_iq`.

## 13. Troubleshooting

| Symptom | Likely cause | Where to look |
| --- | --- | --- |
| Redirect URI mismatch | The registered redirect URI does not **exactly** match `GENIE_IQ_OAUTH_REDIRECT_URI` (including scheme, host, port, and path) | Compare the app registration's **Web** redirect URI list against the exact configured value |
| Invalid state | The `state` value was reused, expired (default 600s TTL, `GENIE_IQ_OAUTH_STATE_TTL_SECONDS`), or the callback landed on a different backend replica than the one that issued it | `app/iq/pending_oauth_flow.py`; single-instance dev deployments are unaffected |
| Missing consent | Tenant administrator has not granted admin consent for `WorkIQAgent.Ask` | Grant admin consent in the app registration's **API permissions** blade, or have the user consent if the tenant allows user consent for this permission |
| Tenant mismatch | The signed-in user's account belongs to a tenant other than `GENIE_IQ_OAUTH_TENANT_ID` | `DelegatedAuthError` with `category="tenant_mismatch"`; confirm the user is signing in with the correct tenant's account |
| Invalid client | `GENIE_IQ_OAUTH_CLIENT_ID` does not match the registered application, or the redirect platform is SPA instead of Web | Re-check the app registration's **Overview** blade application (client) ID and **Authentication** blade platform type |
| Expired secret | The client secret's expiry date has passed | Rotate per [section 11](#11-how-to-remove-or-rotate-development-credentials) |
| 401 from Work IQ | The delegated access token is invalid, expired, or the MCP server rejected it | `IqMcpError` with `category="authentication_required"`; check `IqDiagnostics.last_error_category` via the dev-only diagnostics endpoint |
| 403 from Work IQ | The signed-in user lacks a required permission, or admin consent was granted for the wrong permission | `IqMcpError` with `category="permission_denied"` |
| Work IQ service principal not provisioned | The Work IQ service principal is created automatically in a tenant only on first use; in rare cases (e.g. policy configured before any use) it may not exist yet | Per Microsoft's docs, a tenant administrator can provision it - see [Enable your tenant for Work IQ](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/enable-work-iq) |
| `WorkIQAgent.Ask` unavailable | Work IQ has not been enabled for the tenant | A tenant administrator must enable Work IQ before this permission can be used or consented |
| MCP initialization failure | The `initialize` handshake to `https://workiq.svc.cloud.microsoft/mcp` failed | `IqMcpError` categories `timeout`/`unavailable`; check `GENIE_WORK_IQ_MCP_ENDPOINT` and network egress from the backend |
| `tools/list` failure | Same transport-layer causes as above, after `initialize` succeeded | `IqDiagnostics.mcp_initialized=false` with `tools_discovered_count=null` |
| `tools/call` failure | The configured tool name/arguments were rejected, or the same transport-layer failure occurred | `WorkIqValidationResult.error_category`; re-run `tools/list` to confirm the tool name is still correct (never hardcode past a live `tools/list` response) |

## Official references

- [Work IQ MCP overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/overview)
- [Work IQ MCP tool reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference)
- [Work IQ API permissions reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/permissions)
- [Microsoft identity platform authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
