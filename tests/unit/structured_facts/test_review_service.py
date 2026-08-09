"""Structured relation review service contracts."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.structured_facts.application.review import StructuredFactReviewService
from app.structured_facts.domain.review import StructuredClaimResolutionAction

NOTEBOOK_ID = UUID("10000000-0000-0000-0000-000000000001")
RELATION_ID = UUID("20000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 8, 5, tzinfo=UTC)


class FakeNotebookRepository:
    async def exists_owned(self, notebook_id: UUID) -> bool:
        return notebook_id == NOTEBOOK_ID


class FakeReviewRepository:
    def __init__(self) -> None:
        self.resolve_call: tuple[object, ...] | None = None

    async def list_pending_relations(
        self,
        notebook_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[object], int]:
        return [], 0

    async def get_relation_evidence(
        self,
        notebook_id: UUID,
        relation_id: UUID,
    ) -> None:
        return None

    async def resolve_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        action: StructuredClaimResolutionAction,
        expected_updated_at: datetime,
        reason: str,
    ) -> None:
        self.resolve_call = (
            notebook_id,
            relation_id,
            action,
            expected_updated_at,
            reason,
        )


@pytest.mark.anyio
async def test_review_service_checks_notebook_and_normalizes_reason() -> None:
    repository = FakeReviewRepository()
    service = StructuredFactReviewService(  # type: ignore[arg-type]
        FakeNotebookRepository(),
        repository,
    )

    assert await service.notebook_exists(NOTEBOOK_ID) is True
    await service.resolve_relation(
        NOTEBOOK_ID,
        RELATION_ID,
        StructuredClaimResolutionAction.CONFIRM_CONFLICT,
        NOW,
        "  Verified source values  ",
    )

    assert repository.resolve_call is not None
    assert repository.resolve_call[-1] == "Verified source values"


@pytest.mark.anyio
async def test_review_service_rejects_blank_reason() -> None:
    repository = FakeReviewRepository()
    service = StructuredFactReviewService(  # type: ignore[arg-type]
        FakeNotebookRepository(),
        repository,
    )

    with pytest.raises(ValueError, match="reason"):
        await service.resolve_relation(
            NOTEBOOK_ID,
            RELATION_ID,
            StructuredClaimResolutionAction.DISMISS,
            NOW,
            "   ",
        )

    assert repository.resolve_call is None
