from pathlib import Path

import pytest

from app.modernization.capabilities import (
    ModernizationCapabilityError,
    load_modernization_capabilities,
)


CONFIG_ROOT = Path(__file__).parents[3] / "config" / "workflows"


def test_loads_bounded_modernization_capabilities() -> None:
    catalog = load_modernization_capabilities(CONFIG_ROOT)

    assert [item.id for item in catalog.capabilities] == [
        "runtime_upgrade",
        "framework_upgrade",
        "dependency_upgrade",
        "standards_remediation",
        "strategy_recommendation",
        "rehost_lift_and_shift",
        "replatform",
        "monolith_modularization",
    ]
    assert catalog.get("runtime_upgrade").instruction("Python 3.12").startswith(
        "Upgrade the repository to Python 3.12."
    )


def test_rejects_unsupported_capability() -> None:
    catalog = load_modernization_capabilities(CONFIG_ROOT)

    with pytest.raises(ModernizationCapabilityError, match="Unsupported"):
        catalog.get("rehost")


def test_requires_target_only_for_targeted_capabilities() -> None:
    catalog = load_modernization_capabilities(CONFIG_ROOT)

    with pytest.raises(ModernizationCapabilityError, match="requires"):
        catalog.get("framework_upgrade").instruction(None)
    with pytest.raises(ModernizationCapabilityError, match="does not accept"):
        catalog.get("standards_remediation").instruction("arbitrary work")


def test_strategy_recommendation_requires_no_target_and_evaluates_all_options() -> None:
    catalog = load_modernization_capabilities(CONFIG_ROOT)

    instruction = catalog.get("strategy_recommendation").instruction(None)
    for option in ("retain", "retire", "replace", "rehost", "relocate", "replatform", "refactor"):
        assert option in instruction
    assert "MODERNIZATION_STRATEGY.md" in instruction
    with pytest.raises(ModernizationCapabilityError, match="does not accept"):
        catalog.get("strategy_recommendation").instruction("arbitrary")


def test_rehost_and_replatform_require_a_bounded_target() -> None:
    catalog = load_modernization_capabilities(CONFIG_ROOT)

    assert catalog.get("rehost_lift_and_shift").instruction("Azure Container Apps").startswith(
        "Rehost this workload to Azure Container Apps"
    )
    with pytest.raises(ModernizationCapabilityError, match="requires"):
        catalog.get("rehost_lift_and_shift").instruction(None)

    assert catalog.get("replatform").instruction("Azure SQL Database").startswith(
        "Replatform this workload onto Azure SQL Database"
    )
    with pytest.raises(ModernizationCapabilityError, match="requires"):
        catalog.get("replatform").instruction(None)


def test_monolith_modularization_requires_no_target_and_prefers_strangler_pattern() -> None:
    catalog = load_modernization_capabilities(CONFIG_ROOT)

    instruction = catalog.get("monolith_modularization").instruction(None)
    assert "modular monolith" in instruction
    assert "strangler-pattern" in instruction
    with pytest.raises(ModernizationCapabilityError, match="does not accept"):
        catalog.get("monolith_modularization").instruction("arbitrary")
