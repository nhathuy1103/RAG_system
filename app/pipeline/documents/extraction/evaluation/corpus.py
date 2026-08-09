from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = {".csv", ".docx", ".html", ".htm", ".md", ".pdf", ".pptx", ".txt", ".xlsx"}
DEFAULT_EXCLUDES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "data",
    "node_modules",
    "site-packages",
}


@dataclass(frozen=True)
class CorpusCase:
    case_id: str
    document_path: str
    sha256: str
    domain: str
    parser_mode: str
    validation_status: str
    expected_text: list[dict[str, object]]
    expected_tables: list[dict[str, object]]
    expected_issues: list[dict[str, object]]
    metadata: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def discover_corpus_cases(
    roots: list[Path],
    *,
    limit: int = 30,
    version: str = "extraction_v1",
) -> dict[str, object]:
    cases: list[CorpusCase] = []
    seen_hashes: set[str] = set()
    for path in _iter_candidate_files(roots):
        content = path.read_bytes()
        checksum = hashlib.sha256(content).hexdigest()
        if checksum in seen_hashes:
            continue
        seen_hashes.add(checksum)
        cases.append(_case_from_path(path, checksum, index=len(cases) + 1))
        if len(cases) >= limit:
            break
    return {
        "version": version,
        "cases": [case.to_dict() for case in cases],
    }


def _iter_candidate_files(roots: list[Path]) -> list[Path]:
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix.lower() in SUPPORTED_EXTENSIONS:
                candidates.append(root)
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            relative_parts = path.relative_to(root).parts
            if any(part in DEFAULT_EXCLUDES for part in relative_parts):
                continue
            candidates.append(path)
    return sorted(candidates, key=lambda item: (domain_priority(item), str(item).lower()))


def _case_from_path(path: Path, checksum: str, *, index: int) -> CorpusCase:
    domain = infer_domain(path)
    return CorpusCase(
        case_id=f"{index:03d}_{_slug(path.stem)}",
        document_path=str(path),
        sha256=checksum,
        domain=domain,
        parser_mode="auto",
        validation_status="DRAFT",
        expected_text=[],
        expected_tables=[],
        expected_issues=[],
        metadata={
            "source": "auto_discovered",
            "extension": path.suffix.lower().lstrip("."),
            "size_bytes": path.stat().st_size,
        },
    )


def infer_domain(path: Path) -> str:
    folded = _fold_identifier(" ".join(path.parts))
    if any(
        marker in folded
        for marker in (
            "bao_cao_tai_chinh",
            "baocaotaichinh",
            "baocao",
            "financial",
            "ke_toan",
            "ketoan",
        )
    ):
        return "structured_document"
    if any(marker in folded for marker in ("luat", "luattiepcanthongtin", "qh13", "qh15", "law")):
        return "legal"
    if any(marker in folded for marker in ("transformer", "rnn", "lstm", "nlp", "whitepaper")):
        return "technical_education"
    return "unknown"


def domain_priority(path: Path) -> int:
    domain = infer_domain(path)
    return {
        "structured_document": 0,
        "legal": 1,
        "technical_education": 2,
        "unknown": 3,
    }.get(domain, 4)


def _slug(value: str) -> str:
    return _fold_identifier(value)[:80] or "document"


def _fold_identifier(value: str) -> str:
    lowered = value.lower()
    normalized = []
    last_underscore = False
    for char in lowered:
        if char.isalnum():
            normalized.append(char)
            last_underscore = False
        elif not last_underscore:
            normalized.append("_")
            last_underscore = True
    return "".join(normalized).strip("_")
