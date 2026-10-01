# Genie-SaS IQ Architecture

> **Superseded for Work IQ and Fabric IQ:** those two providers now use
> delegated Microsoft Entra ID OAuth (authorization-code + PKCE), not the
> administrator-managed static token described below. See
> [`genie-sas-microsoft-iq.md`](./genie-sas-microsoft-iq.md) for the
> current authentication model, delegated-identity isolation, tool
> approval, feature flags, and testing. Foundry IQ and Foundry MCP remain
> as described in this document.

Genie-SaS is a standalone application. This document describes how its
**backend** consumes Microsoft's officially provided IQ capabilities -
Work IQ, Fabric IQ, Microsoft Foundry MCP, and Foundry IQ - through the
Model Context Protocol (MCP). It is not part of, and does not depend on,
the VS Code / GitHub Copilot development environment used to build Genie.

## 1. Genie-SaS IQ architecture

```
            USER
              |
              v
      Genie-SaS React UI
              |
              v
      Genie-SaS Backend (FastAPI)
              |
              v
       IqEvidenceService
              |
              v
          IQRouter                     app/iq/router.py
        /    |    |    \
       v     v    v     v
   WORK_   BUSINESS_ KNOWLEDGE_ FOUNDRY_
   CONTEXT CONTEXT   CONTEXT    CONTEXT
       |     |         |          |
       v     v         v          v
   work_iq fabric_iq foundry_iq foundry_mcp    IqProviderRegistration
       |     |         |          |
       +-----+----+----+----------+
                  |
             IqMcpClient                       app/iq/mcp_client.py
                  |
        ==========================
         Trust / Auth Boundary
        ==========================
                  |
       /      |        |       \
      v       v        v        v
  Work IQ  Fabric IQ  Foundry  Foundry IQ
    MCP       MCP       MCP       MCP
```

Genie agents and API callers ask for a **capability**
(`WORK_CONTEXT` / `BUSINESS_CONTEXT` / `KNOWLEDGE_CONTEXT` /
`FOUNDRY_CONTEXT`), never a Microsoft-service-specific name. `IQRouter`
(`app/iq/router.py`) is the single place that maps a capability onto a
concrete provider. `IqEvidenceService.retrieve_by_capability(...)` is the
capability-first entry point; the pre-existing provider-first
`retrieve(provider_name=...)` remains for explicit provider selection.

Every MCP transport concern - JSON-RPC framing, the `initialize` lifecycle
handshake, bearer-token injection, and error categorization - lives in
`IqMcpClient` (`app/iq/mcp_client.py`). No Genie agent (Requirements,
Architecture, Coding, Validation) or the React UI instantiates an MCP
client or acquires a token directly.

## 2. Work IQ

**Purpose:** WORK_CONTEXT - Microsoft 365 workplace intelligence (meetings,
email, documents, Copilot semantic search) for the Requirements workflow.

- **Endpoint:** `https://workiq.svc.cloud.microsoft/mcp` (Microsoft-hosted;
  configured via `GENIE_WORK_IQ_MCP_ENDPOINT`, no default is hardcoded).
- **Tools:** 10 generic tools (`fetch`, `create_entity`, `update_entity`,
  `delete_entity`, `do_action`, `call_function`, `ask`, `list_agents`,
  `get_schema`, `search_paths`) operating on resource paths, not a growing
  tool surface. Genie's `work_iq_retrieve_tool` setting currently targets
  `ask` for natural-language retrieval (Copilot-backed semantic search).
- **Authentication:** Microsoft Entra ID, discovered via the server's
  `/.well-known/oauth-protected-resource` endpoint. **Delegated user
  authentication only** - Microsoft's Work IQ MCP documentation describes
  no application-only/service-principal flow.

## 3. Fabric IQ

**Purpose:** BUSINESS_CONTEXT - Power BI reports and Fabric semantic models
for the Architecture workflow's data-layer grounding.

- **Endpoint:** `https://fabriciq.svc.cloud.microsoft/v1/mcp/fabriciq`
  (private-link tenants use `https://api.fabric.microsoft.com/v1/mcp/fabriciq`
  instead - configure whichever applies via `GENIE_FABRIC_IQ_MCP_ENDPOINT`).
- **Tools:** read-only Power BI content discovery, report/model metadata,
  value search, and DAX query execution. Fabric IQ does not expose a
  natural-language answering tool itself; Genie's configured
  `fabric_iq_retrieve_tool` must be one of the discovered DAX/metadata tools.
- **Authentication:** delegated OAuth 2.0 through Microsoft Entra ID only.
  Microsoft's documentation states explicitly: *"Service-principal and
  application-only authentication aren't supported."* Required delegated
  Power BI scopes: `Item.Read.All`, `Item.Execute.All`, `Dataset.Read.All`.
- Fabric IQ enforces the caller's existing Fabric permissions (including
  row-/object-level security) - Genie never bypasses or widens this.

## 4. Microsoft Foundry MCP

**Purpose:** FOUNDRY_CONTEXT - Foundry project/service tool access (models,
deployments, and other Foundry resources) without calling Foundry backend
REST APIs directly.

- **Endpoint:** `https://mcp.ai.azure.com` (public preview).
- **Authentication:** built-in Microsoft Entra ID. Microsoft's published
  get-started guide documents connection **only** from an interactive
  MCP-compliant developer client (Visual Studio Code + GitHub Copilot Agent
  Mode), where a human signs in via the VS Code Entra flow and holds
  Contributor-or-higher on the target Foundry project. **No
  service-principal, application-only, or other headless backend
  integration path is documented.**
- **Genie-SaS status:** the provider/router abstraction is implemented
  (`foundry_mcp` in `IqProviderName`, `FOUNDRY_CONTEXT` in `IqCapability`,
  full settings/validation/wiring), but it is **disabled by default and not
  confirmed usable from a standalone backend**, per the "Microsoft-provided
  MCP first, never fabricate" rule. It must not be enabled until Microsoft
  publishes a supported headless integration, or until this is explicitly
  re-evaluated.

## 5. Foundry IQ

**Purpose:** KNOWLEDGE_CONTEXT - enterprise knowledge-base grounding
(architectural guidance, approved patterns, approved knowledge) for the
Requirements, Architecture, and Validation agents.

- **Configuration:** `GENIE_FOUNDRY_IQ_MCP_ENDPOINT` /
  `GENIE_FOUNDRY_IQ_TOKEN_ENV_VAR` /  `GENIE_FOUNDRY_IQ_RETRIEVE_TOOL`, plus
  any project/knowledge-base identifiers the configured knowledge source
  requires (externalized, never hardcoded).
- Citations returned by the knowledge source are preserved verbatim on the
  `IqEvidenceEnvelope.citations` field and copied into shared-memory
  evidence references at promotion time - never rewritten or summarized
  away.

## 6. MCP lifecycle

`IqMcpClient` implements the subset of the Model Context Protocol lifecycle
Genie's IQ providers need, over JSON-RPC 2.0:

1. **`initialize`** - sent once per client instance, before any other
   request, with `protocolVersion`, `capabilities`, and `clientInfo`.
2. **`notifications/initialized`** - the fire-and-forget notification that
   completes the handshake.
3. **`tools/list`** - runtime tool discovery (never a hardcoded tool
   schema).
4. **`tools/call`** - invokes the configured retrieve tool.

Each of these maps to Genie's "Required functionality" checklist:
initialization, `tools/list`, `tools/call`, timeout, cancellation (request
timeout is enforced per call via `iq_mcp_timeout_seconds`; explicit
mid-flight cancellation is not yet wired through the FastAPI request
lifecycle - see [Remaining blockers](#13-remaining-blockers-and-next-step)),
authentication-required handling, permission-denied handling, structured
MCP errors, tool discovery, and safe diagnostics (error messages never
include the bearer token or raw response bodies).

### Why not the official `mcp` Python SDK yet

The official MCP Python SDK (PyPI package `mcp`,
https://pypi.org/project/mcp/) exists and supports streamable HTTP client
transport. It was evaluated but **not adopted this iteration**: swapping
`IqMcpClient`'s internals would need independent verification of its
bearer-token injection path (Genie needs to inject a per-provider token
resolved from an environment variable at request time, not a static
client-construction-time credential) and its additional dependency
footprint, without unverified behavior change risk to already-working
GitHub MCP and IQ MCP transports that share this pattern. This is the
recommended next implementation step (see below).

## 7. IQ routing

`IQRouter.route(capability) -> IqProviderName`:

| Capability | Provider |
|---|---|
| `WORK_CONTEXT` | `work_iq` |
| `BUSINESS_CONTEXT` | `fabric_iq` |
| `KNOWLEDGE_CONTEXT` | `foundry_iq` |
| `FOUNDRY_CONTEXT` | `foundry_mcp` |

Genie never calls all four providers for one request; a capability always
resolves to exactly one provider. `POST /sessions/{id}/iq/retrieve` accepts
either `capability` (preferred) or an explicit `provider` (for callers that
need to bypass the router's default mapping) - exactly one must be set.
`GET /iq/capabilities` exposes the full mapping for UI/tooling discovery.

## 8. Authentication boundary

```
Genie Agents
     |
     v
IqEvidenceService / IQRouter
     |
     v
IqMcpClient (MCP transport + auth)
     |
=========================
 AUTHENTICATION BOUNDARY
=========================
     |
     v
Microsoft MCP Service
```

Authentication is isolated entirely inside `IqMcpClient`. No Genie agent
(Requirements, Architecture, Coding, Validation) and no React UI component
acquires a token, holds a client, or contains Microsoft-service-specific
authentication logic.

**Token model:** each provider resolves its bearer token from an
administrator-configured environment variable at request time
(`GENIE_WORK_IQ_TOKEN_ENV_VAR`, `GENIE_FABRIC_IQ_TOKEN_ENV_VAR`,
`GENIE_FOUNDRY_IQ_TOKEN_ENV_VAR`, `GENIE_FOUNDRY_MCP_TOKEN_ENV_VAR`) - the
same administrator-provisioned-secret pattern Genie already uses for its
GitHub MCP integration. Genie-SaS's own user-facing authentication is
intentionally anonymous (see the root `README.md` "Authentication"
section); this IQ token model does not reintroduce interactive Microsoft
Entra ID sign-in anywhere in Genie-SaS itself, and does not require it to.

## 9. Authorization model

Each Microsoft IQ service enforces its own permission boundary independent
of Genie:

- Work IQ: policy-gated by four broad OAuth permissions at the tenant/path
  level.
- Fabric IQ: the caller's existing Fabric row-level and object-level
  security continues to restrict returned data; Genie cannot see more than
  the token's holder can.
- Foundry IQ / Foundry MCP: scoped to the configured project/knowledge-base
  and the calling identity's Foundry role assignment.

Genie never attempts to widen, cache past expiry, or bypass any of these
boundaries.

## 10. Security

- React UI never receives a Microsoft access or refresh token - tokens
  never cross the `IqMcpClient` boundary in either direction.
- No credential is hardcoded or committed; every endpoint and token
  environment-variable name is externalized configuration
  (`app/config/settings.py`).
- Enterprise response bodies are not logged by default. Safe telemetry
  recorded via `GovernanceService.record_tool_request` is limited to
  provider, tool name, candidate/evidence id, content hash, citation count,
  and sensitivity label - never the raw content.
- IQ evidence is not persisted beyond Genie's existing evidence-candidate
  review/promotion workflow (`IqEvidenceCandidate`), which already requires
  explicit human confirmation before anything enters shared memory.

## 11. Configuration

All Work IQ / Fabric IQ / Foundry IQ / Foundry MCP configuration is
externalized under the `GENIE_` environment-variable prefix (see
`app/config/settings.py`); no value defaults to a real Microsoft endpoint
except where Microsoft's own documentation confirms one (Work IQ, Fabric
IQ, and Foundry MCP each publish exactly one documented endpoint, reflected
above - Genie does not hardcode them as defaults, only as documentation).

| Provider | Enable | Endpoint | Token env var | Retrieve tool | Query argument |
|---|---|---|---|---|---|
| Work IQ | `GENIE_WORK_IQ_ENABLED` | `GENIE_WORK_IQ_MCP_ENDPOINT` | `GENIE_WORK_IQ_TOKEN_ENV_VAR` | `GENIE_WORK_IQ_RETRIEVE_TOOL` | `GENIE_WORK_IQ_QUERY_ARGUMENT` |
| Fabric IQ | `GENIE_FABRIC_IQ_ENABLED` | `GENIE_FABRIC_IQ_MCP_ENDPOINT` | `GENIE_FABRIC_IQ_TOKEN_ENV_VAR` | `GENIE_FABRIC_IQ_RETRIEVE_TOOL` | `GENIE_FABRIC_IQ_QUERY_ARGUMENT` |
| Foundry IQ | `GENIE_FOUNDRY_IQ_ENABLED` | `GENIE_FOUNDRY_IQ_MCP_ENDPOINT` | `GENIE_FOUNDRY_IQ_TOKEN_ENV_VAR` | `GENIE_FOUNDRY_IQ_RETRIEVE_TOOL` | `GENIE_FOUNDRY_IQ_QUERY_ARGUMENT` |
| Foundry MCP | `GENIE_FOUNDRY_MCP_ENABLED` | `GENIE_FOUNDRY_MCP_ENDPOINT` | `GENIE_FOUNDRY_MCP_TOKEN_ENV_VAR` | `GENIE_FOUNDRY_MCP_RETRIEVE_TOOL` | `GENIE_FOUNDRY_MCP_QUERY_ARGUMENT` |

`GENIE_IQ_MCP_TIMEOUT_SECONDS` (default 60s) applies to every provider.
Endpoint values are validated to require HTTPS; every enabled provider must
have a complete endpoint/token-env-var/retrieve-tool triple or Genie's
`ConfigurationValidator` fails startup with an explicit message.

## 12. Optional IQ enrichment

IQ integrations are enrichment capabilities, never a hard dependency:

- If a provider is disabled, misconfigured, unreachable, unauthenticated,
  permission-denied, or times out, `IqEvidenceService.provider_statuses()`
  returns an explicit status for that provider - it does not raise, and it
  does not crash Genie startup or any workflow that doesn't specifically
  require that evidence.
- **Status vocabulary** (`IqStatus` in `app/iq/models.py`):
  - `IQ_AVAILABLE` - configured, reachable, retrieve tool confirmed present.
  - `IQ_NOT_REQUIRED` - reserved for a future per-workflow "this capability
    isn't needed for this request" signal; not yet emitted by any code path.
  - `IQ_NOT_CONFIGURED` - disabled, or enabled with an incomplete
    endpoint/token-env-var/retrieve-tool configuration.
  - `IQ_AUTHENTICATION_REQUIRED` - the configured credential is missing, or
    the MCP service rejected it (HTTP 401 / discovery failure).
  - `IQ_PERMISSION_DENIED` - the MCP service rejected the call as
    unauthorized for the authenticated identity (HTTP 403).
  - `IQ_UNAVAILABLE` - any other transport failure, a malformed MCP
    response, or the configured retrieve tool not being present in
    `tools/list`.
  - `IQ_TIMEOUT` - the configured request timeout elapsed.
- A `retrieve()`/`retrieve_by_capability()` call still raises
  `IqEvidenceError` when its specific provider is unavailable - that failure
  is scoped to the one requested retrieval, and it is the caller's (agent's
  or API consumer's) responsibility to treat it as "continue without this
  evidence," never to retry into a hard failure of the whole workflow.
- Genie never fabricates missing context: an unavailable provider yields no
  evidence, not synthesized evidence.

## 13. Remaining blockers and next implementation step

> **Update:** the "no IQ provider can reach `IQ_AVAILABLE`" conclusion
> below no longer applies to Work IQ or Fabric IQ - see
> [`genie-sas-microsoft-iq.md`](./genie-sas-microsoft-iq.md) for the
> delegated OAuth implementation that supersedes it. It still applies to
> Foundry MCP and Foundry IQ, which remain administrator-token/
> configuration-based.

**Authentication requirements discovered (all three real IQ MCP services):**

| Service | Delegated user auth | Application-only / service-principal auth |
|---|---|---|
| Work IQ | Required (Entra ID) | Not documented as supported |
| Fabric IQ | Required (Entra ID) | Explicitly **not supported** per Microsoft's docs |
| Foundry MCP | Required (Entra ID, interactive VS Code flow) | Not documented as supported |
| Foundry IQ | Depends on the configured knowledge-base/project binding | Configuration-dependent; not assumed |

Because every real Microsoft MCP service Genie targets requires **delegated
Entra ID user authentication**, and Genie-SaS's own user-facing
authentication is intentionally anonymous (no interactive Entra ID sign-in
anywhere in Genie-SaS - see the root `README.md`), **no IQ provider can
reach `IQ_AVAILABLE` today** unless an administrator manually provisions a
delegated user token, obtained through some out-of-band interactive sign-in
outside Genie-SaS, into the provider's configured token environment
variable. Every provider therefore resolves to `IQ_NOT_CONFIGURED` (no
token/endpoint set) or `IQ_AUTHENTICATION_REQUIRED` (configured but the
resolved token is missing/invalid/expired) in Genie-SaS's current
deployment. This is the expected, correct behavior per this document's
"CRITICAL IMPLEMENTATION RULE" - Genie must not work around Microsoft's
security model, and does not.

Genie-SaS previously implemented and then deliberately removed interactive
Microsoft Entra ID sign-in for its own users (see the root `README.md`
"Authentication" section and its deployment log). Reintroducing any form of
Entra ID authentication into Genie-SaS - even narrowly scoped to obtaining
delegated IQ tokens on a user's behalf - is a decision that was explicitly
reversed once and must not be made unilaterally by a future change; it
requires an explicit, separate decision.

**Recommended next implementation steps, in order:**

1. Decide, explicitly, whether Genie-SaS should (a) remain IQ-provider-token
   administrator-provisioned only (current state - safe, no Entra ID
   reintroduction, but IQ stays unavailable in practice), or (b) introduce a
   narrowly scoped, MCP-transport-only delegated authentication mechanism
   (e.g. on-behalf-of token exchange) - which would require reintroducing
   some Entra ID capability and must be discussed before implementation.
2. Evaluate adopting the official `mcp` Python SDK for `IqMcpClient`'s
   transport, verifying its bearer-token injection point against Genie's
   per-request, per-provider token resolution requirement.
3. Confirm the exact Work IQ tool (`ask` vs. a `fetch`/`call_function` path)
   and the exact Fabric IQ DAX/metadata tool Genie should configure as each
   provider's `retrieve_tool`, once a delegated token is available to test
   against the real `tools/list` contract.
4. Wire `IqCapability`-based retrieval into the Requirements and
   Architecture agents' workflows (the "Genie Prototyping Flow") as
   optional enrichment steps, using `retrieve_by_capability` and treating
   any non-`IQ_AVAILABLE` status as "continue without this evidence."
5. Re-evaluate Microsoft Foundry MCP (`mcp.ai.azure.com`) once Microsoft
   publishes a documented non-interactive integration path; until then, keep
   `foundry_mcp` disabled.

## 14. Official Microsoft references

- [Work IQ API overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/api-overview)
- [Work IQ MCP overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/overview)
- [Work IQ MCP tool reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference)
- [Work IQ + Foundry authentication quickstart](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/quickstart/foundry)
- [Fabric IQ MCP](https://learn.microsoft.com/en-us/fabric/iq/connectors/fabric-iq-mcp)
- [Foundry MCP get started](https://learn.microsoft.com/en-us/azure/foundry/mcp/get-started)
- [Connect agents to Foundry IQ knowledge bases](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [MCP Python SDK](https://pypi.org/project/mcp/)

## Testing

Unit tests mock the MCP transport only (`httpx.AsyncClient.post`); none
require a live Microsoft service:

- `backend/tests/unit/test_iq_mcp_client.py` - `initialize` handshake
  runs exactly once, `tools/list`/`tools/call`, bearer-token injection, and
  every error-category mapping (authentication required, permission denied,
  timeout, unavailable, malformed response).
- `backend/tests/unit/test_iq_router.py` - capability -> provider mapping,
  including an unmapped-capability failure.
- `backend/tests/unit/test_iq_evidence_service.py` - every `IqStatus`
  mapping, the regression guard that a provider error never raises out of
  `provider_statuses()` (the startup-crash bug this change fixes), and
  `retrieve_by_capability` routing through `IQRouter`.

## Troubleshooting

| Symptom | Likely cause | Where to look |
|---|---|---|
| Provider status is `IQ_NOT_CONFIGURED` | Provider disabled, or endpoint/token-env-var/retrieve-tool incomplete | `app/config/settings.py` IQ block; `GET /iq/providers` `detail` field |
| Provider status is `IQ_AUTHENTICATION_REQUIRED` | Token environment variable unset, or the MCP service returned 401 | Confirm the administrator-provisioned delegated token is present and unexpired |
| Provider status is `IQ_PERMISSION_DENIED` | Authenticated identity lacks the required delegated scope/role for that service | Re-check the specific service's required permissions (section 2-5 above) |
| Provider status is `IQ_TIMEOUT` | Request exceeded `GENIE_IQ_MCP_TIMEOUT_SECONDS` | Increase the timeout or check the Microsoft service's health |
| `POST /sessions/{id}/iq/retrieve` returns a 422 with "Exactly one of 'capability' or 'provider' must be set" | Request body set both or neither field | Set exactly one of `capability` / `provider` |
| Genie fails to start citing an IQ provider | Should no longer happen - see section 12; if it does, it is a regression of this fix | `app/main.py` `create_app` IQ wiring |
