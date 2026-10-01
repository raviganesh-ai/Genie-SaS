"""Evidence-based phase tracking service."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.phase_tracking.evidence_verification import EvidenceVerificationService
from app.phase_tracking.models import (
    PhaseCatalog,
    PhaseTaskState,
    TaskStatus,
    TrackedPhase,
    TrackedTask,
)
from app.phase_tracking.repository import PhaseTaskStateRepository
from app.services.session_service import SessionService
from app.utils.yaml_loader import YamlLoadError, load_yaml_file


class PhaseTrackingError(RuntimeError):
    """Raised when a phase transition or catalog is invalid."""


def load_phase_catalog(workflows_path: Path) -> PhaseCatalog:
    path = workflows_path / "modernization_phases.yaml"
    try:
        payload = load_yaml_file(path)
        return PhaseCatalog.model_validate(payload)
    except (YamlLoadError, ValidationError) as exc:
        raise PhaseTrackingError(f"Invalid phase catalog '{path}': {exc}") from exc


class PhaseTrackingService:
    def __init__(
        self,
        *,
        catalog: PhaseCatalog,
        repository: PhaseTaskStateRepository,
        session_service: SessionService,
        evidence_verification_service: EvidenceVerificationService,
    ) -> None:
        self._catalog = catalog
        self._repository = repository
        self._session_service = session_service
        self._evidence_verification_service = evidence_verification_service
        phase_ids = [phase.id for phase in catalog.phases]
        if len(set(phase_ids)) != len(phase_ids):
            raise PhaseTrackingError("Phase catalog contains duplicate phase ids.")
        for phase in catalog.phases:
            task_ids = [task.id for task in phase.tasks]
            if len(set(task_ids)) != len(task_ids):
                raise PhaseTrackingError(f"Phase '{phase.id}' contains duplicate task ids.")

    async def list_phases(
        self, *, session_id: str, requesting_user_id: str
    ) -> list[TrackedPhase]:
        await self._session_service.get_session(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        states = {
            (state.phase_id, state.task_id): state
            for state in await self._repository.list_for_session(session_id=session_id)
        }
        now = datetime.now(UTC)
        return [
            TrackedPhase(
                id=phase.id,
                name=phase.name,
                tasks=[
                    TrackedTask(
                        definition=task,
                        state=states.get((phase.id, task.id))
                        or PhaseTaskState(
                            id=self._state_id(session_id, phase.id, task.id),
                            session_id=session_id,
                            phase_id=phase.id,
                            task_id=task.id,
                            updated_by=requesting_user_id,
                            updated_at=now,
                        ),
                    )
                    for task in phase.tasks
                ],
            )
            for phase in self._catalog.phases
        ]

    async def update_task(
        self,
        *,
        session_id: str,
        phase_id: str,
        task_id: str,
        task_status: TaskStatus,
        evidence_uri: str | None,
        detail: str,
        requesting_user_id: str,
    ) -> PhaseTaskState:
        phases = await self.list_phases(
            session_id=session_id, requesting_user_id=requesting_user_id
        )
        phase_index = next(
            (index for index, phase in enumerate(phases) if phase.id == phase_id),
            None,
        )
        if phase_index is None:
            raise PhaseTrackingError(f"Unknown phase '{phase_id}'.")
        phase = phases[phase_index]
        if not any(task.definition.id == task_id for task in phase.tasks):
            raise PhaseTrackingError(f"Unknown task '{task_id}' in phase '{phase_id}'.")
        if task_status in {"in_progress", "completed"}:
            incomplete_predecessors = [
                task.definition.name
                for predecessor in phases[:phase_index]
                for task in predecessor.tasks
                if task.state.status != "completed"
            ]
            if incomplete_predecessors:
                raise PhaseTrackingError(
                    "Previous phases must be completed before advancing this task."
                )
        if task_status == "completed" and not evidence_uri:
            raise PhaseTrackingError("Completed tasks require a live evidence URI.")
        if task_status == "blocked" and not detail.strip():
            raise PhaseTrackingError("Blocked tasks require a blocker description.")
        verification = None
        if task_status == "completed" and evidence_uri:
            verification = await self._evidence_verification_service.verify(
                uri=evidence_uri,
                session_id=session_id,
            )
        state = PhaseTaskState(
            id=self._state_id(session_id, phase_id, task_id),
            session_id=session_id,
            phase_id=phase_id,
            task_id=task_id,
            status=task_status,
            evidence_uri=evidence_uri,
            evidence_provider=verification.provider if verification else None,
            evidence_verified_at=verification.verified_at if verification else None,
            evidence_reference=verification.reference if verification else None,
            detail=detail.strip(),
            updated_by=requesting_user_id,
            updated_at=datetime.now(UTC),
        )
        await self._repository.put(state)
        return state

    @staticmethod
    def _state_id(session_id: str, phase_id: str, task_id: str) -> str:
        return f"{session_id}:{phase_id}:{task_id}"
