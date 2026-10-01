"""Tests for MCP tool mutation classification and approval policy."""
from __future__ import annotations

from app.iq.tool_classification import classify_tool, requires_approval


def test_read_only_hint_true_classifies_as_read_only() -> None:
    tool = {"name": "fetch", "annotations": {"readOnlyHint": True}}

    assert classify_tool(tool) == "read_only"
    assert requires_approval("read_only") is False


def test_destructive_hint_true_classifies_as_resource_deleting() -> None:
    tool = {"name": "delete_entity", "annotations": {"readOnlyHint": False, "destructiveHint": True}}

    assert classify_tool(tool) == "resource_deleting"
    assert requires_approval("resource_deleting") is True


def test_non_destructive_idempotent_classifies_as_configuration_changing() -> None:
    tool = {
        "name": "update_entity",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    }

    assert classify_tool(tool) == "configuration_changing"
    assert requires_approval("configuration_changing") is True


def test_missing_annotations_falls_back_to_name_heuristic() -> None:
    assert classify_tool({"name": "create_entity"}) == "resource_creating"
    assert classify_tool({"name": "delete_entity"}) == "resource_deleting"
    assert classify_tool({"name": "update_entity"}) == "configuration_changing"
    assert classify_tool({"name": "grant_role"}) == "permission_changing"
    assert classify_tool({"name": "get_schema"}) == "read_only"
    assert classify_tool({"name": "search_paths"}) == "data_querying"


def test_ambiguous_generic_invoke_tools_default_to_unknown() -> None:
    # Work IQ's do_action/call_function can do anything - Genie cannot see
    # the underlying action from tools/list alone, so these must never be
    # misclassified as read-only.
    assert classify_tool({"name": "do_action"}) == "unknown"
    assert classify_tool({"name": "call_function"}) == "unknown"


def test_no_name_and_no_annotations_is_unknown() -> None:
    assert classify_tool({}) == "unknown"


def test_unknown_always_requires_approval() -> None:
    assert requires_approval("unknown") is True


def test_read_only_and_data_querying_never_require_approval() -> None:
    assert requires_approval("read_only") is False
    assert requires_approval("data_querying") is False


def test_every_mutating_class_requires_approval() -> None:
    for mutation_class in (
        "configuration_changing",
        "resource_creating",
        "resource_deleting",
        "permission_changing",
    ):
        assert requires_approval(mutation_class) is True
