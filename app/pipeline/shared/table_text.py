from __future__ import annotations

from collections.abc import Sequence

from app.pipeline.shared.text_utils import normalize_text


def render_table_text(rows: Sequence[Sequence[object]]) -> str:
    """Render structured table rows into stable, pipe-delimited chunk text."""
    column_count = max((len(row) for row in rows), default=0)
    rendered_rows: list[str] = []
    for row in rows:
        cells = [_render_cell(cell) for cell in row]
        cells.extend("" for _ in range(column_count - len(cells)))
        rendered_rows.append(" | ".join(cells))
    return "\n".join(rendered_rows)


def render_markdown_table_text(rows: Sequence[Sequence[object]]) -> str:
    """Render table rows as GitHub-flavored Markdown for chunk text."""
    column_count = max((len(row) for row in rows), default=0)
    if column_count == 0:
        return ""
    padded_rows: list[list[str]] = []
    for row in rows:
        cells = [_render_cell(cell) for cell in row]
        cells.extend("" for _ in range(column_count - len(cells)))
        padded_rows.append(cells)
    if not padded_rows:
        return ""
    header = padded_rows[0]
    separator = ["---" for _ in range(column_count)]
    body = padded_rows[1:]
    return "\n".join(_markdown_row(row) for row in [header, separator, *body])


def _render_cell(value: object) -> str:
    normalized = normalize_text(str(value))
    return normalized.replace("|", r"\|").replace("\n", "<br>")


def _markdown_row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"
