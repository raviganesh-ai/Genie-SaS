"""Strongly typed models for grounded Well-Architected / Microsoft docs Q&A."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocCitation(BaseModel):
    """One real, retrieved Microsoft Learn page an answer is grounded in.

    ``url`` always equals a ``contentUrl`` actually returned by
    ``MicrosoftLearnMcpClient.search`` for this question - never a
    model-invented URL (see WellArchitectedQaService._execute_answer, which
    discards any citation whose url is not in the retrieved set)."""

    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    excerpt: str


class WellArchitectedAnswer(BaseModel):
    """A plain-language answer about Azure Well-Architected Framework
    pillars or Azure service-level guidance, grounded only in documents
    retrieved live from Microsoft Learn at question time."""

    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str
    citations: list[DocCitation] = Field(default_factory=list)
    grounded: bool
    generated_by: str = "well-architected-advisor"
    generated_at: datetime
