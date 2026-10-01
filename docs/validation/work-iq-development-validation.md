# Work IQ Development Validation Report

## Validation date

2026-09-30

## Environment type

Local development (Windows, ARM64), backend run directly with `uvicorn`
against this session's authenticated Azure CLI context. Not a shared
hosted development environment, and not production.

## Commit / branch tested

- Branch: `main`
- Base commit: `d9ca13d40a64a8574c2b1f52ce9fdbc9f6b761d7`
- **Uncommitted worktree changes on top of that commit** were what was
  actually tested (this validation work itself, including the fix
  described below). No commit was created as part of this task.

## Feature flags enabled

```
GENIE_ENVIRONMENT=development
GENIE_WORK_IQ_ENABLED=true
GENIE_FABRIC_IQ_ENABLED=false
GENIE_FOUNDRY_MCP_ENABLED=false
GENIE_FOUNDRY_IQ_ENABLED=false
```

Only Work IQ and the Microsoft Connect infrastructure it depends on were
enabled, per the task's boundary.

## Entra registration configured: **NO**

No Microsoft Entra application registration was created. The operator in
this session is an Azure subscription Owner but does not hold an Entra
administrator role (established earlier in this engagement), and this
environment has no interactive browser available to complete app
registration through the Entra portal either way.

The `GENIE_IQ_OAUTH_TENANT_ID` / `GENIE_IQ_OAUTH_CLIENT_ID` values used
for this validation were the **well-known null GUID**
(`00000000-0000-0000-0000-000000000000`) and a **clearly fake client
secret** - used exclusively to satisfy `ConfigurationValidator`'s
presence/format checks so the backend would start. They are not, and
cannot be mistaken for, a real registration. See
[`genie-sas-entra-development.md`](../setup/genie-sas-entra-development.md)
for the exact checklist a tenant administrator would need to complete
this for real.

## Connect Microsoft 365 completed: **PARTIALLY**

- Clicking/invoking **Connect Microsoft 365** (`GET
  /iq/connections/work_iq/start`) **did execute for real** and produced a
  genuine HTTP 302 redirect to Microsoft's real authorization endpoint
  (`https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize`)
  with correct `client_id`, `response_type`, `redirect_uri`,
  `response_mode`, `scope`, `state`, `code_challenge`, and
  `code_challenge_method` parameters.
- **The interactive Microsoft sign-in step was NOT completed.** With no
  real Entra app registered, and no interactive browser available in this
  environment, a human could not sign in and consent. This step requires
  a real tenant administrator action (Entra registration + admin consent)
  that was not available in this session.

## Delegated consent completed: **NO**

Not reached - blocked by the above.

## MCP initialization result

**Not executed against a real connected identity** (no connection was
ever established - see above). What **was** genuinely executed and
verified:

- A real, live HTTP request was made from this machine to
  `https://workiq.svc.cloud.microsoft/.well-known/oauth-protected-resource`
  (bare path) and to
  `https://workiq.svc.cloud.microsoft/.well-known/oauth-protected-resource/mcp`
  (path-suffixed with the resource's own `/mcp` path).
- **A real defect was found and fixed as a direct result of this live
  testing** (see "Findings" below).

## `tools/list` result

Not executed - requires a connected identity, which was not established.

## Work IQ retrieval result

**Not executed.** `POST /sessions/{id}/iq/work-iq/validate` was called
against the real running backend without a connection and correctly
returned:

```json
{
  "success": false,
  "provider": "work_iq",
  "tool_invoked": null,
  "error_category": "authentication_required",
  "detail": "Connect Microsoft 365 (Work IQ) before running this validation."
}
```

This confirms the validation action fails safely and does not fabricate a
result - it does **not** confirm a real Work IQ retrieval succeeded.

## Citation propagation result

Not executed live (no real retrieval occurred). Citation extraction logic
itself is covered by dedicated unit tests
(`tests/unit/test_iq_citations.py`) and exercised inside the mocked
validation-service tests
(`tests/unit/test_work_iq_validation_service.py::test_citations_are_preserved_when_returned`).

## Disconnect cleanup result

**Executed and verified live** against the real local backend:
`POST /sessions/{id}/iq/connections/work_iq/disconnect` on a
never-connected session returned `204` (safe no-op), and
`GET /sessions/{id}/iq/connections` continued to correctly report
`work_iq` as `IQ_AUTHENTICATION_REQUIRED` afterward. Full disconnect
cleanup of an actually-connected session (token cache + identity index)
is separately verified by
`tests/unit/test_delegated_connection_service.py::test_disconnect_clears_the_connection_and_records_an_audit_event`.

## Anonymous-flow regression result

**Executed and verified live**:

- `GET /health/ready` → `{"status": "ready"}`
- `POST /sessions` with **no `Authorization` header** → `201`, returned a
  session owned by the fixed `genie-internal-user` principal, exactly as
  designed.
- `GET /sessions` (listing) continued to work normally after all of the
  above IQ activity.

Anonymous Genie-SaS behavior is unaffected by enabling Work IQ.

## Automated test results

- **Backend:** 614 passed. 38 failed - all 38 are pre-existing failures
  unrelated to this change (Deploy & Launch pipeline test fixtures, one
  architecture-boundary test, and two validation tests already failing
  before this task began in this session; none touch Work IQ, delegated
  auth, or any file this task modified).
- **New tests added this task:** 33 (citations, diagnostics service,
  validation service, route gate, callback cancel/error handling,
  cross-user isolation, and 7 new `ConfigurationValidator` negative tests
  for the delegated OAuth block).
- **Frontend:** typecheck clean, lint clean (`--max-warnings=0`), 78
  passed / 4 failed - the 4 failures are pre-existing, unrelated
  Deploy & Launch UI tests.
- `git diff --check`: clean (no whitespace errors).

## Build and lint results

- Backend: `ruff check app tests` → all checks passed.
- Backend: full `app.main` import succeeds; local `uvicorn` startup
  succeeds against this session's real, already-provisioned Azure AI
  Foundry project.
- Frontend: `npm run typecheck`, `npm run lint`, `npm run build` all
  succeed.

## Sanitized errors encountered

1. `ConfigurationValidator: config_root 'config' does not exist.` - the
   documented dev startup command (`cd backend && uvicorn ...`) assumes a
   `backend/config` directory that does not exist; `config/` is at the
   repository root. Worked around locally with an absolute
   `GENIE_CONFIG_ROOT`. **This is a pre-existing environment/documentation
   gap, not something introduced by this task** - left unmodified as
   out of scope.
2. `ConfigurationValidator: iq_oauth_redirect_uri must use HTTPS.` -
   expected; corrected by using an `https://localhost` placeholder
   (unused for a real redirect in this test).
3. `SpeechServiceUnavailableError: No usable speech-to-text backend` -
   pre-existing, unrelated required configuration (Azure AI Speech
   endpoint); resolved by reusing the already-deployed AIServices
   endpoint's non-secret URL.
4. `MissionIdentityProvisioningError: azure_subscription_id must be
   configured` - pre-existing, unrelated required configuration
   (Deploy & Launch mission identity wiring is constructed unconditionally
   at startup); resolved by reusing the already-deployed environment's
   non-secret subscription/resource-group/ACR/Container-Apps-environment
   identifiers.
5. **`DelegatedAuthError` (category `authentication_required`): "Unable
   to discover the delegated authorization configuration for this
   Microsoft MCP resource."** - a **real defect**, found through live
   testing against Microsoft's actual Work IQ MCP server, not a
   configuration problem. See "Findings" below.

## Findings

### Fixed: incorrect RFC 9728 well-known URI construction

`DelegatedTokenBroker._discover` built the protected-resource metadata URL
by **replacing** the resource's path with
`/.well-known/oauth-protected-resource`, discarding the resource's own
`/mcp` path segment. Confirmed live against Microsoft's real Work IQ MCP
server:

- `https://workiq.svc.cloud.microsoft/.well-known/oauth-protected-resource`
  (path replaced) → **HTTP 400** `{"error":{"code":"BadRequest","message":"Invalid request, no valid route."}}`
- `https://workiq.svc.cloud.microsoft/.well-known/oauth-protected-resource/mcp`
  (path suffixed, per RFC 9728 §3.1) → **HTTP 200** with a real metadata
  document (`authorization_servers`, `scopes_supported`,
  `bearer_methods_supported`, `resource_name: "Work IQ"`).

**Fixed** in `app/iq/delegated_token_broker.py::_discover` to insert the
well-known path segment before the resource's own path instead of
replacing it. Added a dedicated regression test
(`tests/unit/test_delegated_token_broker.py::test_discovery_requests_the_well_known_path_suffixed_with_the_resource_path`)
and updated the existing mocked-transport tests to match. **This defect
would have blocked every real Work IQ (and Fabric IQ) connection
attempt**, independent of whether a real Entra app is registered - fixing
it was necessary before any further live validation could be meaningful.

### Observation: Work IQ's discovered authorization server is multi-tenant

The live metadata document's `authorization_servers` value was
`https://login.microsoftonline.com/organizations/v2.0` - Microsoft's
common multi-tenant endpoint, not a tenant-specific one. This matches the
implementation: `DelegatedTokenBroker` does not assume a tenant-specific
authorization server; it uses whatever the resource's own discovery
document declares, and separately enforces tenant restriction by
validating the returned ID token's `tid` claim against
`GENIE_IQ_OAUTH_TENANT_ID` after the fact. No code change was needed for
this - documented here because it is a real, previously-unconfirmed
detail about Work IQ's live behavior.

### Observation: discovered scope format uses a GUID prefix, not the App ID URI

The live metadata's `scopes_supported` value was
`fdcc1f02-fc51-4226-8753-f668596af7f7/WorkIQAgent.Ask` - an Application ID
(GUID)-prefixed scope, not the `api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask`
Application-ID-URI form documented on Microsoft's permissions reference
page. Microsoft Entra ID generally accepts both forms as equivalent scope
identifiers for the same resource (the App ID URI is an alias for the
underlying Application ID), so this is recorded as an observation, not a
contradiction requiring a code change - the implementation continues to
request the documented App-ID-URI form by default
(`GENIE_WORK_IQ_SCOPES` remains overridable if a specific tenant ever
requires the literal discovered form).

## Remaining blockers

1. **No Entra app registration exists.** Requires a tenant administrator
   (the current operator has Azure subscription Owner but not an Entra
   administrator role). See
   [`genie-sas-entra-development.md`](../setup/genie-sas-entra-development.md).
2. **No interactive browser is available in this environment** to
   complete a real Microsoft sign-in/consent, even once an app is
   registered.
3. **`offline_access` is not requested**, so once a real connection is
   established, access-token expiry will surface as `IQ_SESSION_EXPIRED`
   rather than transparently refreshing, until this is explicitly added
   (documented as a known gap in the Entra checklist).
4. The documented dev startup command (`cd backend && uvicorn ...`)
   assumes `backend/config`, which does not exist - `config/` is at the
   repository root. Pre-existing, unrelated to this task; not fixed here.
5. In-memory-only token cache and pending-OAuth-flow store (documented
   in `docs/architecture/genie-sas-microsoft-iq.md` "Remaining
   blockers") remain unaddressed.

## Production-readiness recommendation

**Not production-ready.** Beyond the blockers above:

- No real end-to-end Work IQ retrieval has ever been executed - only the
  pre-authentication portion of the flow (start → real Microsoft
  redirect) has been verified live.
- A real tenant's admin consent experience, token exchange, ID-token
  validation against a real signed token, and live `tools/list`/
  `tools/call` behavior remain unverified.
- The fixed discovery defect should be re-verified once a real
  connection can be completed, to confirm the full chain (not just
  discovery) behaves as expected end to end.

**Recommended next step:** a tenant administrator completes the Entra
app registration per
[`genie-sas-entra-development.md`](../setup/genie-sas-entra-development.md),
grants admin consent for `WorkIQAgent.Ask`, and an operator with access to
an interactive browser performs the full manual sequence in
`GENIE_ENVIRONMENT=development` against this now-fixed implementation.
