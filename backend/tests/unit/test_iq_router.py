"""Tests for capability-based IQ routing."""
from __future__ import annotations

from typing import cast

import pytest

from app.iq.models import IqCapability
from app.iq.router import IQRouter, IQRouterError


def test_routes_each_capability_to_its_documented_provider() -> None:
    router = IQRouter()

    assert router.route("WORK_CONTEXT") == "work_iq"
    assert router.route("BUSINESS_CONTEXT") == "fabric_iq"
    assert router.route("KNOWLEDGE_CONTEXT") == "foundry_iq"
    assert router.route("FOUNDRY_CONTEXT") == "foundry_mcp"


def test_capabilities_exposes_the_full_mapping() -> None:
    router = IQRouter()

    assert router.capabilities() == {
        "WORK_CONTEXT": "work_iq",
        "BUSINESS_CONTEXT": "fabric_iq",
        "KNOWLEDGE_CONTEXT": "foundry_iq",
        "FOUNDRY_CONTEXT": "foundry_mcp",
    }


def test_unmapped_capability_raises_router_error() -> None:
    router = IQRouter()

    with pytest.raises(IQRouterError):
        router.route(cast(IqCapability, "UNKNOWN_CONTEXT"))
