from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from app.structured_facts.ports.repositories import StructuredFactSearch


def _search(**changes: object) -> StructuredFactSearch:
    values: dict[str, object] = {
        "notebook_id": UUID("40000000-0000-0000-0000-000000000004"),
        "document_ids": (UUID("20000000-0000-0000-0000-000000000002"),),
        "predicate": "sale_price",
        "subject_query": "a101",
    }
    values.update(changes)
    return StructuredFactSearch(**values)  # type: ignore[arg-type]


def test_accepts_nested_scalar_qualifier_filters() -> None:
    query = _search(
        qualifiers={
            "stable": {"price_basis": "per_sqm"},
            "optional": {"vat_included": True},
        }
    )

    assert query.qualifiers["stable"] == {"price_basis": "per_sqm"}


@pytest.mark.parametrize(
    "qualifiers",
    [
        {"unknown": {"price_type": "list_price"}},
        {"stable": "list_price"},
        {"stable": {"price_type": {"unexpected": "object"}}},
        {"optional": {"vat_included": None}},
    ],
)
def test_rejects_malformed_qualifier_filters(qualifiers: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="qualifier"):
        _search(qualifiers=qualifiers)


def test_rejects_reversed_validity_interval_before_rpc() -> None:
    with pytest.raises(ValueError, match="reversed"):
        _search(valid_from=date(2026, 4, 1), valid_to=date(2026, 3, 31))


def test_rejects_incomparable_mixed_validity_bound_types() -> None:
    with pytest.raises(ValueError, match="comparable"):
        _search(
            valid_from=date(2026, 3, 1),
            valid_to=datetime(2026, 3, 31, tzinfo=UTC),
        )
