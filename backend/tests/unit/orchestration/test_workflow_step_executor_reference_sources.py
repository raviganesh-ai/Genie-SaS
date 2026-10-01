"""Unit tests for WorkflowStepExecutor's optional, session-scoped
"architecture-reference"/"standards-reference" variable sources - the
mechanism that lets design-architecture (and, by the same code path,
governed modernization) honor a user-supplied opinionated architecture or
standards reference when one exists, and fall back gracefully when it
does not (see app.modernization.service's analogous, independently-wired
optionality contract)."""
from __future__ import annotations

from datetime import UTC, datetime

from app.agents.models import AgentDefinition
from app.orchestration.workflow_step_executor import WorkflowStepExecutor
from app.standards.architecture_reference_repository import (
    InMemoryArchitectureReferenceRepository,
)
from app.standards.models import ArchitectureReferenceSnapshot, ArchitectureStandardRule, StandardCitation, StandardsSnapshot
from app.standards.repository import InMemoryStandardsRepository
from app.workflows.models import WorkflowStep


def _agent() -> AgentDefinition:
    return AgentDefinition(
        id="genie-orchestrator",
        name="genie-orchestrator",
        role="test_role",
        description="A test agent.",
        memory_access=["shared"],
    )


def _step() -> WorkflowStep:
    return WorkflowStep(
        id="design-architecture",
        agent_id="genie-orchestrator",
        description="Design the architecture.",
        depends_on=[],
        variable_sources={
            "architecture_reference_text": "architecture-reference",
            "standards_reference_text": "standards-reference",
        },
    )


def _architecture_snapshot(
    *, snapshot_id: str, text: str, created_at: datetime
) -> ArchitectureReferenceSnapshot:
    return ArchitectureReferenceSnapshot(
        id=snapshot_id,
        session_id="session-1",
        binding_id="binding-1",
        repository_full_name="acme/architecture-reference",
        commit="a" * 40,
        paths=["ARCHITECTURE.md"],
        content_hashes={"ARCHITECTURE.md": "b" * 64},
        combined_reference_text=text,
        gaps=[],
        created_at=created_at,
    )


def _standards_snapshot(*, snapshot_id: str, created_at: datetime) -> StandardsSnapshot:
    citation = StandardCitation(
        repository_full_name="acme/standards",
        commit="c" * 40,
        path="STANDARDS.md",
        line=1,
        content_hash="d" * 64,
    )
    rule = ArchitectureStandardRule(
        id="rule-1",
        title="Use managed identity",
        statement="Services must use managed identity instead of embedded credentials.",
        classification="mandatory",
        citation=citation,
    )
    return StandardsSnapshot(
        id=snapshot_id,
        session_id="session-1",
        binding_id="binding-2",
        repository_full_name="acme/standards",
        commit="c" * 40,
        paths=["STANDARDS.md"],
        content_hashes={"STANDARDS.md": "d" * 64},
        rules=[rule],
        conflicts=[],
        gaps=[],
        created_at=created_at,
    )


def _executor(
    *,
    architecture_reference_repository=None,
    standards_repository=None,
    platform_reference_repository_store=None,
) -> WorkflowStepExecutor:
    return WorkflowStepExecutor(
        agent_registry=None,  # unused by _resolve_variables
        prompt_registry=None,
        agent_gateway=None,
        governance_service=None,
        architecture_reference_repository=architecture_reference_repository,
        standards_repository=standards_repository,
        platform_reference_repository_store=platform_reference_repository_store,
    )


async def test_falls_back_to_none_provided_text_when_nothing_was_ever_configured() -> None:
    executor = _executor()

    resolved = await executor._resolve_variables(
        step=_step(),
        transcript_text="",
        step_outputs={},
        step_input=None,
        agent=_agent(),
        session_id="session-1",
        trace_id="trace-1",
    )

    assert "none provided" in resolved["architecture_reference_text"]
    assert "none provided" in resolved["standards_reference_text"]


async def test_falls_back_to_none_provided_text_when_repositories_exist_but_are_empty() -> None:
    executor = _executor(
        architecture_reference_repository=InMemoryArchitectureReferenceRepository(),
        standards_repository=InMemoryStandardsRepository(),
    )

    resolved = await executor._resolve_variables(
        step=_step(),
        transcript_text="",
        step_outputs={},
        step_input=None,
        agent=_agent(),
        session_id="session-1",
        trace_id="trace-1",
    )

    assert "none provided" in resolved["architecture_reference_text"]
    assert "none provided" in resolved["standards_reference_text"]


async def test_uses_the_users_opinionated_architecture_reference_when_one_was_ingested() -> None:
    architecture_repository = InMemoryArchitectureReferenceRepository()
    await architecture_repository.put(
        _architecture_snapshot(
            snapshot_id="arch-1",
            text="# ARCHITECTURE.md\n\nUse a modular monolith with a single Postgres database.",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    executor = _executor(architecture_reference_repository=architecture_repository)

    resolved = await executor._resolve_variables(
        step=_step(),
        transcript_text="",
        step_outputs={},
        step_input=None,
        agent=_agent(),
        session_id="session-1",
        trace_id="trace-1",
    )

    assert "modular monolith" in resolved["architecture_reference_text"]


async def test_uses_the_most_recently_ingested_architecture_reference_when_several_exist() -> None:
    architecture_repository = InMemoryArchitectureReferenceRepository()
    await architecture_repository.put(
        _architecture_snapshot(
            snapshot_id="arch-old",
            text="Old reference.",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    await architecture_repository.put(
        _architecture_snapshot(
            snapshot_id="arch-new",
            text="New reference.",
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )
    executor = _executor(architecture_reference_repository=architecture_repository)

    resolved = await executor._resolve_variables(
        step=_step(),
        transcript_text="",
        step_outputs={},
        step_input=None,
        agent=_agent(),
        session_id="session-1",
        trace_id="trace-1",
    )

    assert resolved["architecture_reference_text"] == "New reference."


async def test_formats_the_users_standards_reference_rules_when_one_was_ingested() -> None:
    standards_repository = InMemoryStandardsRepository()
    await standards_repository.put(
        _standards_snapshot(snapshot_id="std-1", created_at=datetime(2026, 1, 1, tzinfo=UTC))
    )
    executor = _executor(standards_repository=standards_repository)

    resolved = await executor._resolve_variables(
        step=_step(),
        transcript_text="",
        step_outputs={},
        step_input=None,
        agent=_agent(),
        session_id="session-1",
        trace_id="trace-1",
    )

    assert "[mandatory]" in resolved["standards_reference_text"]
    assert "managed identity" in resolved["standards_reference_text"]


async def test_reference_sources_are_scoped_to_the_requesting_session() -> None:
    architecture_repository = InMemoryArchitectureReferenceRepository()
    other_session_snapshot = _architecture_snapshot(
        snapshot_id="arch-other-session",
        text="Belongs to a different session.",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    ).model_copy(update={"session_id": "session-2"})
    await architecture_repository.put(other_session_snapshot)
    executor = _executor(architecture_reference_repository=architecture_repository)

    resolved = await executor._resolve_variables(
        step=_step(),
        transcript_text="",
        step_outputs={},
        step_input=None,
        agent=_agent(),
        session_id="session-1",
        trace_id="trace-1",
    )

    assert "none provided" in resolved["architecture_reference_text"]


async def test_falls_back_to_platform_configured_architecture_reference_when_session_has_none() -> None:
    from app.platform_config.models import PlatformReferenceRepository
    from app.platform_config.repository import InMemoryPlatformReferenceRepositoryStore

    platform_store = InMemoryPlatformReferenceRepositoryStore()
    await platform_store.put(
        PlatformReferenceRepository(
            id="platform-arch-1",
            repository_id=1,
            repository_full_name="acme/platform-architecture",
            repository_url="https://github.com/acme/platform-architecture",
            purpose="architecture",
            requested_ref="main",
            resolved_commit="a" * 40,
            principal="managed-identity",
            configured_by_user_id="admin-1",
            combined_reference_text="Administrator-configured platform reference.",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    executor = _executor(
        architecture_reference_repository=InMemoryArchitectureReferenceRepository(),
        platform_reference_repository_store=platform_store,
    )

    resolved = await executor._resolve_variables(
        step=_step(),
        transcript_text="",
        step_outputs={},
        step_input=None,
        agent=_agent(),
        session_id="session-1",
        trace_id="trace-1",
    )

    assert resolved["architecture_reference_text"] == "Administrator-configured platform reference."


async def test_session_level_architecture_reference_overrides_the_platform_default() -> None:
    from app.platform_config.models import PlatformReferenceRepository
    from app.platform_config.repository import InMemoryPlatformReferenceRepositoryStore

    architecture_repository = InMemoryArchitectureReferenceRepository()
    await architecture_repository.put(
        _architecture_snapshot(
            snapshot_id="arch-session-override",
            text="This mission's own override.",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    platform_store = InMemoryPlatformReferenceRepositoryStore()
    await platform_store.put(
        PlatformReferenceRepository(
            id="platform-arch-1",
            repository_id=1,
            repository_full_name="acme/platform-architecture",
            repository_url="https://github.com/acme/platform-architecture",
            purpose="architecture",
            requested_ref="main",
            resolved_commit="a" * 40,
            principal="managed-identity",
            configured_by_user_id="admin-1",
            combined_reference_text="Administrator-configured platform reference.",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    executor = _executor(
        architecture_reference_repository=architecture_repository,
        platform_reference_repository_store=platform_store,
    )

    resolved = await executor._resolve_variables(
        step=_step(),
        transcript_text="",
        step_outputs={},
        step_input=None,
        agent=_agent(),
        session_id="session-1",
        trace_id="trace-1",
    )

    assert resolved["architecture_reference_text"] == "This mission's own override."
