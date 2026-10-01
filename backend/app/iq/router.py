"""Capability-based IQ routing.

Genie agents and API callers ask for a capability (``IqCapability``), never
a Microsoft-service-specific name. This is the single place that maps a
capability onto a concrete provider, so no other component needs to know
that, for example, WORK_CONTEXT is satisfied by Work IQ today. Swapping the
provider behind a capability (or adding a second provider for the same
capability) only requires a change here.
"""
from __future__ import annotations

from app.iq.models import IqCapability, IqProviderName


class IQRouterError(RuntimeError):
    """Raised when a capability has no mapped provider."""


# WORK_CONTEXT    -> Work IQ (Microsoft 365 workplace intelligence)
# BUSINESS_CONTEXT -> Fabric IQ (Power BI / Fabric semantic + data context)
# KNOWLEDGE_CONTEXT -> Foundry IQ (enterprise knowledge-base retrieval)
# FOUNDRY_CONTEXT  -> Microsoft Foundry MCP (Foundry project/service tools)
_CAPABILITY_TO_PROVIDER: dict[IqCapability, IqProviderName] = {
    "WORK_CONTEXT": "work_iq",
    "BUSINESS_CONTEXT": "fabric_iq",
    "KNOWLEDGE_CONTEXT": "foundry_iq",
    "FOUNDRY_CONTEXT": "foundry_mcp",
}


class IQRouter:
    """Routes an ``IqCapability`` to the single provider that satisfies it.

    Deliberately capability-based, not provider-based: this class (and only
    this class) knows which Microsoft IQ service backs each capability, so
    that no other Genie agent or API route contains Microsoft-service-
    specific routing logic.
    """

    def route(self, capability: IqCapability) -> IqProviderName:
        try:
            return _CAPABILITY_TO_PROVIDER[capability]
        except KeyError as exc:
            raise IQRouterError(f"No IQ provider is mapped to capability '{capability}'.") from exc

    def capabilities(self) -> dict[IqCapability, IqProviderName]:
        return dict(_CAPABILITY_TO_PROVIDER)
