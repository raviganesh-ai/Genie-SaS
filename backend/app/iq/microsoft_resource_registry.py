"""Static, typed metadata for the Microsoft MCP resources Genie-SaS connects
to under delegated user authentication.

This registry holds only non-secret, externally configured values - the
documented MCP endpoint and the delegated OAuth scope(s) an administrator
has exposed/consented for that resource in their own Entra tenant/app
registration. It never performs a network call itself (see
``app.iq.delegated_token_broker`` for the live `.well-known` discovery
chain) and never holds a client secret or token.

CONFIRMED FROM OFFICIAL MICROSOFT DOCUMENTATION (see
``docs/architecture/genie-sas-microsoft-iq.md`` "Official Microsoft
references" for the exact source pages):

- Work IQ MCP endpoint: ``https://workiq.svc.cloud.microsoft/mcp``.
  Application ID URI: ``api://workiq.svc.cloud.microsoft``. Delegated
  permission: ``WorkIQAgent.Ask`` (admin consent required) -> full scope
  string ``api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask``.
- Fabric IQ MCP endpoint: ``https://fabriciq.svc.cloud.microsoft/v1/mcp/fabriciq``
  (private-link tenants: ``https://api.fabric.microsoft.com/v1/mcp/fabriciq``).
  Required delegated Power BI Service API permissions: ``Item.Read.All``,
  ``Item.Execute.All``, ``Dataset.Read.All``.

The exact Fabric IQ delegated *scope strings* depend on how the
administrator exposed/consented those Power BI Service API permissions in
Genie-SaS's own Entra app registration, so Genie does not hardcode a
default scope list for Fabric IQ - it is required configuration
(``GENIE_IQ_FABRIC_IQ_SCOPES``), confirmed by the administrator against
their own app registration's exposed API permissions. The Work IQ endpoint
and Application ID URI are unambiguous and documented, so a default scope
is provided, but remains overridable.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.iq.models import IqProviderName

# Confirmed, documented default - see module docstring. Still overridable
# via configuration in case Microsoft documents an additional/replacement
# scope in the future.
_DEFAULT_WORK_IQ_SCOPE = "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"


class MicrosoftMcpResourceRegistryError(RuntimeError):
    """Raised when a delegated provider's resource metadata is incomplete."""


@dataclass(frozen=True)
class MicrosoftMcpResource:
    provider: IqProviderName
    mcp_endpoint: str
    # Delegated OAuth scopes requested during the authorization code flow.
    # Always non-empty for a usable delegated resource.
    scopes: tuple[str, ...]


class MicrosoftMcpResourceRegistry:
    """Looks up the confirmed MCP endpoint + delegated scopes for a
    delegated provider. Holds no token, client secret, or authority - those
    live in ``DelegatedTokenBroker``/settings, resolved per Entra tenant."""

    def __init__(self, *, resources: dict[IqProviderName, MicrosoftMcpResource]) -> None:
        self._resources = resources

    def get(self, provider: IqProviderName) -> MicrosoftMcpResource:
        try:
            return self._resources[provider]
        except KeyError as exc:
            raise MicrosoftMcpResourceRegistryError(
                f"No Microsoft MCP resource metadata is configured for provider '{provider}'."
            ) from exc

    @classmethod
    def from_settings(
        cls,
        *,
        work_iq_mcp_endpoint: str | None,
        work_iq_scopes: tuple[str, ...] | None,
        fabric_iq_mcp_endpoint: str | None,
        fabric_iq_scopes: tuple[str, ...] | None,
    ) -> "MicrosoftMcpResourceRegistry":
        resources: dict[IqProviderName, MicrosoftMcpResource] = {}
        if work_iq_mcp_endpoint:
            resources["work_iq"] = MicrosoftMcpResource(
                provider="work_iq",
                mcp_endpoint=work_iq_mcp_endpoint,
                scopes=work_iq_scopes or (_DEFAULT_WORK_IQ_SCOPE,),
            )
        if fabric_iq_mcp_endpoint and fabric_iq_scopes:
            resources["fabric_iq"] = MicrosoftMcpResource(
                provider="fabric_iq",
                mcp_endpoint=fabric_iq_mcp_endpoint,
                scopes=fabric_iq_scopes,
            )
        return cls(resources=resources)
