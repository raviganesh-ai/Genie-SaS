"""Shared, provider-agnostic citation extraction for MCP tool results.

Walks an arbitrary MCP ``structuredContent``/JSON value looking for known
citation-shaped keys (``citation``/``url``/``sourceUrl``/``webUrl``) and
returns their string values verbatim, de-duplicated. Used by both
``IqEvidenceService`` (governed evidence retrieval) and
``WorkIqValidationService`` (the development-only validation action) so
citation handling stays identical across both call paths.

Treats the input as untrusted data: it only ever reads known-shaped keys
and copies string values through - it never evaluates, executes, or
otherwise interprets the content.
"""
from __future__ import annotations

from typing import Any

_CITATION_KEYS = {"citation", "url", "sourceurl", "weburl"}


def extract_citations(value: Any) -> list[str]:
    citations: list[str] = []
    _collect_citations(value, citations)
    return list(dict.fromkeys(citations))


def _collect_citations(value: Any, citations: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() in _CITATION_KEYS and isinstance(nested, str):
                citations.append(nested)
            else:
                _collect_citations(nested, citations)
    elif isinstance(value, list):
        for nested in value:
            _collect_citations(nested, citations)
