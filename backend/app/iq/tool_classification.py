"""MCP tool mutation classification and approval-requirement policy.

Classifies a discovered MCP tool (from ``tools/list``) into an
``IqToolMutationClass`` using the tool's official MCP annotations
(https://modelcontextprotocol.io - ``readOnlyHint``/``destructiveHint``/
``idempotentHint``/``openWorldHint``) as the primary, spec-correct signal.

These four boolean hints cannot by themselves distinguish every category
this module's vocabulary names (e.g. "resource_creating" vs
"permission_changing" vs "configuration_changing" are all just "not
read-only, not clearly destructive" under the spec's four hints). Where
annotations are present but underspecify the category, or are absent
entirely, a generic, provider-agnostic verb-prefix heuristic over the
tool's ``name`` is used as a best-effort secondary signal - this is a
naming-convention heuristic applicable to any MCP server, never a
hardcoded schema for one specific provider's fixed tool list. When neither
signal can confidently classify a tool, it is "unknown" - and, per policy,
unknown always requires approval, the same as every mutating class.
"""
from __future__ import annotations

from typing import Any

from app.iq.models import IqToolMutationClass

# Mutation classes that must never execute without explicit human approval.
# Deliberately everything except the two read-oriented classes.
_REQUIRES_APPROVAL: frozenset[IqToolMutationClass] = frozenset(
    {
        "configuration_changing",
        "resource_creating",
        "resource_deleting",
        "permission_changing",
        "unknown",
    }
)

_CREATE_PREFIXES = ("create_", "add_")
_DELETE_PREFIXES = ("delete_", "remove_")
_UPDATE_PREFIXES = ("update_", "modify_", "set_", "edit_")
_PERMISSION_PREFIXES = ("grant_", "revoke_")
_PERMISSION_SUBSTRINGS = ("permission", "role")
_READ_ONLY_PREFIXES = ("get_", "list_", "read_", "fetch_", "find_", "describe_")
_DATA_QUERYING_PREFIXES = ("search_", "query_", "ask")


def classify_tool(tool: dict[str, Any]) -> IqToolMutationClass:
    """Classifies one ``tools/list`` entry. ``tool`` is the raw MCP tool
    object (``{"name": ..., "annotations": {...}, ...}``)."""

    name = tool.get("name")
    annotations = tool.get("annotations")
    from_annotations = _classify_from_annotations(annotations) if isinstance(annotations, dict) else None
    if from_annotations is not None:
        return from_annotations
    if isinstance(name, str):
        from_name = _classify_from_name_heuristic(name)
        if from_name is not None:
            return from_name
    return "unknown"


def requires_approval(mutation_class: IqToolMutationClass) -> bool:
    """Returns whether a tool of this mutation class must be gated behind
    explicit human approval before Genie calls it."""

    return mutation_class in _REQUIRES_APPROVAL


def _classify_from_annotations(annotations: dict[str, Any]) -> IqToolMutationClass | None:
    read_only_hint = annotations.get("readOnlyHint")
    if read_only_hint is True:
        return "read_only"
    destructive_hint = annotations.get("destructiveHint")
    idempotent_hint = annotations.get("idempotentHint")
    if destructive_hint is True:
        return "resource_deleting"
    if destructive_hint is False and idempotent_hint is True:
        return "configuration_changing"
    # readOnlyHint explicitly False with no other hint set is still a real
    # signal ("this tool mutates"), but not specific enough to place in one
    # of the finer-grained mutating categories - fall through to the name
    # heuristic (handled by the caller) rather than guessing here.
    return None


def _classify_from_name_heuristic(name: str) -> IqToolMutationClass | None:
    lowered = name.lower()
    if any(lowered.startswith(prefix) for prefix in _PERMISSION_PREFIXES) or any(
        substring in lowered for substring in _PERMISSION_SUBSTRINGS
    ):
        return "permission_changing"
    if any(lowered.startswith(prefix) for prefix in _DELETE_PREFIXES):
        return "resource_deleting"
    if any(lowered.startswith(prefix) for prefix in _CREATE_PREFIXES):
        return "resource_creating"
    if any(lowered.startswith(prefix) for prefix in _UPDATE_PREFIXES):
        return "configuration_changing"
    if any(lowered.startswith(prefix) for prefix in _READ_ONLY_PREFIXES):
        return "read_only"
    if any(lowered.startswith(prefix) for prefix in _DATA_QUERYING_PREFIXES):
        return "data_querying"
    if lowered.startswith("call_function") or lowered.startswith("do_action"):
        # Generic "invoke something" tools (e.g. Work IQ's call_function,
        # do_action) cannot be classified from the name alone - the action
        # itself determines mutation behavior, which Genie cannot see from
        # tools/list. Leave unclassified so the caller defaults to unknown.
        return None
    return None
