"""Governed IQ provider, retrieval, review, and promotion routes."""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.dependencies import get_iq_evidence_service
from app.iq.models import CandidateStatus, IqCapability, IqEvidenceCandidate, IqProviderName, IqProviderStatus
from app.iq.router import IQRouter
from app.iq.service import IqEvidenceService
from app.security.auth_models import AuthenticatedUser
from app.security.dependencies import get_current_user

router = APIRouter(tags=["iq-evidence"])


class RetrieveIqEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Callers should prefer `capability` (WORK_CONTEXT/BUSINESS_CONTEXT/
    # KNOWLEDGE_CONTEXT/FOUNDRY_CONTEXT) so they never need to name a
    # Microsoft service directly; `provider` remains supported for existing
    # callers and for explicitly bypassing the router's default mapping.
    capability: IqCapability | None = None
    provider: IqProviderName | None = None
    query: str = Field(min_length=1)
    sensitivity: str = Field(min_length=1)

    @model_validator(mode="after")
    def _require_exactly_one_target(self) -> "RetrieveIqEvidenceRequest":
        if (self.capability is None) == (self.provider is None):
            raise ValueError("Exactly one of 'capability' or 'provider' must be set.")
        return self


class ReviewIqEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CandidateStatus
    comment: str | None = None


@router.get("/iq/providers")
async def list_iq_provider_statuses(
    _: AuthenticatedUser = Depends(get_current_user),
    service: IqEvidenceService = Depends(get_iq_evidence_service),
) -> list[IqProviderStatus]:
    return await service.provider_statuses()


@router.get("/iq/capabilities")
async def list_iq_capabilities(
    _: AuthenticatedUser = Depends(get_current_user),
) -> dict[IqCapability, IqProviderName]:
    """Exposes the capability -> provider mapping the IQ router enforces,
    so the UI (and any future agent) can present capabilities rather than
    Microsoft-service-specific provider names."""
    return IQRouter().capabilities()


@router.get("/sessions/{session_id}/iq/candidates")
async def list_iq_candidates(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: IqEvidenceService = Depends(get_iq_evidence_service),
) -> list[IqEvidenceCandidate]:
    return await service.list_candidates(
        session_id=session_id,
        requesting_user_id=user.user_id,
    )


@router.post("/sessions/{session_id}/iq/retrieve")
async def retrieve_iq_evidence(
    session_id: str,
    body: RetrieveIqEvidenceRequest,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: IqEvidenceService = Depends(get_iq_evidence_service),
) -> IqEvidenceCandidate:
    trace_id = x_correlation_id or str(uuid4())
    if body.capability is not None:
        return await service.retrieve_by_capability(
            session_id=session_id,
            requesting_user_id=user.user_id,
            capability=body.capability,
            query=body.query,
            sensitivity=body.sensitivity,
            trace_id=trace_id,
        )
    if body.provider is None:
        raise ValueError("Exactly one of 'capability' or 'provider' must be set.")
    return await service.retrieve(
        session_id=session_id,
        requesting_user_id=user.user_id,
        provider_name=body.provider,
        query=body.query,
        sensitivity=body.sensitivity,
        trace_id=trace_id,
    )


@router.post("/sessions/{session_id}/iq/candidates/{candidate_id}/review")
async def review_iq_evidence(
    session_id: str,
    candidate_id: str,
    body: ReviewIqEvidenceRequest,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: IqEvidenceService = Depends(get_iq_evidence_service),
) -> IqEvidenceCandidate:
    return await service.review(
        session_id=session_id,
        candidate_id=candidate_id,
        requesting_user_id=user.user_id,
        status=body.status,
        comment=body.comment,
        trace_id=x_correlation_id or str(uuid4()),
    )


@router.post("/sessions/{session_id}/iq/candidates/{candidate_id}/promote")
async def promote_iq_evidence(
    session_id: str,
    candidate_id: str,
    x_correlation_id: str | None = Header(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    service: IqEvidenceService = Depends(get_iq_evidence_service),
) -> IqEvidenceCandidate:
    return await service.promote(
        session_id=session_id,
        candidate_id=candidate_id,
        requesting_user_id=user.user_id,
        trace_id=x_correlation_id or str(uuid4()),
    )

