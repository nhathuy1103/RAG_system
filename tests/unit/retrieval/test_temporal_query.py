from datetime import date
from uuid import UUID

from app.chat.application.services import _resolve_allowed_document_ids
from app.documents.domain.models import Document
from app.retrieval.application.temporal_query import extract_query_time_range


def _document(
    suffix: int,
    *,
    effective_from: date | None,
    effective_to: date | None,
    current: bool,
) -> Document:
    value = UUID(f"00000000-0000-0000-0000-{suffix:012d}")
    return Document(
        id=value,
        owner_id=UUID("10000000-0000-0000-0000-000000000001"),
        notebook_id=UUID("20000000-0000-0000-0000-000000000002"),
        original_filename=f"price-{suffix}.pdf",
        storage_bucket="documents",
        storage_object_path=f"price-{suffix}.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        content_hash=None,
        status="ready",
        error_message=None,
        is_active=True,
        created_at=None,
        updated_at=None,
        effective_from=effective_from,
        effective_to=effective_to,
        is_current=current,
    )


def test_extracts_vietnamese_month_as_closed_range() -> None:
    result = extract_query_time_range("Giá căn A101 tháng 3/2025 là bao nhiêu?")

    assert result is not None
    assert result.start == date(2025, 3, 1)
    assert result.end == date(2025, 3, 31)


def test_historical_scope_selects_overlapping_version_not_current() -> None:
    february = _document(
        1,
        effective_from=date(2025, 2, 1),
        effective_to=date(2025, 2, 28),
        current=False,
    )
    march = _document(
        2,
        effective_from=date(2025, 3, 1),
        effective_to=date(2025, 3, 31),
        current=False,
    )
    current = _document(
        3,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        current=True,
    )
    valid_time = extract_query_time_range("tháng 3 năm 2025")

    assert valid_time is not None
    assert _resolve_allowed_document_ids(
        [february, march, current],
        None,
        valid_time=valid_time,
    ) == (march.id,)


def test_historical_scope_fails_closed_when_intervals_are_unknown() -> None:
    current = _document(1, effective_from=None, effective_to=None, current=True)
    valid_time = extract_query_time_range("tháng 3/2025")

    assert valid_time is not None
    assert _resolve_allowed_document_ids([current], None, valid_time=valid_time) == ()
