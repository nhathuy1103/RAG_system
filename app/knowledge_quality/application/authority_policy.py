"""Versioned source preference applied strictly after relation detection."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.knowledge_quality.domain.relation_models import (
    AUTHORITY_POLICY_VERSION,
    DocumentRelationContext,
    FinalRelationType,
    VersionDirection,
)
from app.structured_facts.domain.models import SourceAuthority


@dataclass(frozen=True, slots=True)
class AuthorityPolicy:
    """Configurable categorical ranks; publisher names are intentionally absent."""

    approval_ranks: dict[str, int] = field(
        default_factory=lambda: {
            "approved": 50,
            "reviewed": 40,
            "unreviewed": 20,
            "rejected": 0,
        }
    )
    source_type_ranks: dict[str, int] = field(
        default_factory=lambda: {
            "approved_internal": 50,
            "official_publisher": 40,
            "reviewed_internal": 30,
            "unreviewed_internal": 20,
            "third_party": 10,
            "unknown": 0,
        }
    )
    version: str = AUTHORITY_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class EvidencePreference:
    preferred_document_id: str | None
    reason: str | None
    source_rank: tuple[int, int, int]
    target_rank: tuple[int, int, int]
    policy_version: str


def rank_authority(
    authority: SourceAuthority,
    policy: AuthorityPolicy,
) -> tuple[int, int, int]:
    """Return explicit level, approval rank, and configured source rank."""
    official = authority.officiality
    official_rank = 1 if official is True or str(official).casefold() == "official" else 0
    return (
        authority.authority_level or 0,
        policy.approval_ranks.get((authority.approval_status or "").casefold(), 0),
        max(
            official_rank * 40,
            policy.source_type_ranks.get((authority.source_type or "unknown").casefold(), 0),
        ),
    )


def select_preferred_evidence(
    source: DocumentRelationContext,
    target: DocumentRelationContext,
    *,
    relation: FinalRelationType,
    version_direction: VersionDirection,
    policy: AuthorityPolicy | None = None,
) -> EvidencePreference:
    """Select a preference without mutating or suppressing relation evidence."""
    active_policy = policy or AuthorityPolicy()
    source_rank = rank_authority(source.authority, active_policy)
    target_rank = rank_authority(target.authority, active_policy)

    if relation is FinalRelationType.VERSION_UPDATE:
        if version_direction is VersionDirection.SOURCE_SUPERSEDES_TARGET:
            return EvidencePreference(
                source.document_id,
                "newer_business_version",
                source_rank,
                target_rank,
                active_policy.version,
            )
        if version_direction is VersionDirection.TARGET_SUPERSEDES_SOURCE:
            return EvidencePreference(
                target.document_id,
                "newer_business_version",
                source_rank,
                target_rank,
                active_policy.version,
            )

    if source_rank > target_rank:
        preferred = source.document_id
    elif target_rank > source_rank:
        preferred = target.document_id
    else:
        preferred = None
    return EvidencePreference(
        preferred,
        "higher_source_authority" if preferred is not None else None,
        source_rank,
        target_rank,
        active_policy.version,
    )


__all__ = [
    "AuthorityPolicy",
    "EvidencePreference",
    "rank_authority",
    "select_preferred_evidence",
]
