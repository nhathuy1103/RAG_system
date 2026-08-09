from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageDraw

from app.pipeline.documents.extraction.canonical.geometry import (
    AxisAlignedBoundingBox,
    CoordinateSpace,
    CoordinateSpaceType,
)
from app.pipeline.documents.extraction.canonical.serialization import read_canonical_document

DEFAULT_COLORS = {
    "text_block": "#1f77b4",
    "paragraph": "#1f77b4",
    "heading": "#2ca02c",
    "table": "#d62728",
    "table_cell": "#ff7f0e",
    "figure": "#9467bd",
    "unknown": "#7f7f7f",
}


def render_overlay(
    *,
    document_path: str | Path,
    artifact_path: str | Path,
    page_number: int,
    output_path: str | Path,
    element_types: set[str] | None = None,
) -> Path:
    canonical = read_canonical_document(artifact_path)
    page = next(
        (item for item in canonical.pages if item.page_number == page_number),
        None,
    )
    if page is None:
        raise ValueError(f"Canonical IR artifact has no page {page_number}.")
    image = _load_page_image(Path(document_path), page_number=page_number)
    draw = ImageDraw.Draw(image)
    spaces = {space.space_id: space for space in page.coordinate_spaces}
    for element in page.elements:
        if element_types and element.element_type not in element_types:
            continue
        if element.geometry is None:
            continue
        bbox = element.geometry.bbox or element.geometry.normalized_bbox
        if bbox is None:
            continue
        _draw_bbox(
            draw,
            image=image,
            bbox=bbox,
            spaces=spaces,
            label=f"{element.element_id} {element.element_type}",
            color=DEFAULT_COLORS.get(element.element_type, DEFAULT_COLORS["unknown"]),
        )
    for table in page.tables:
        if element_types and "table" not in element_types:
            continue
        if table.bbox is not None:
            _draw_bbox(
                draw,
                image=image,
                bbox=table.bbox,
                spaces=spaces,
                label=f"{table.table_id} table",
                color=DEFAULT_COLORS["table"],
            )
        if not element_types or "table_cell" in element_types:
            for cell in table.cells:
                if cell.bbox is None:
                    continue
                _draw_bbox(
                    draw,
                    image=image,
                    bbox=cell.bbox,
                    spaces=spaces,
                    label=f"r{cell.row_index}c{cell.column_index}",
                    color=DEFAULT_COLORS["table_cell"],
                )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output


def _load_page_image(document_path: Path, *, page_number: int) -> Image.Image:
    suffix = document_path.suffix.lower()
    if suffix == ".pdf":
        try:
            import fitz
        except Exception as exc:  # pragma: no cover - depends on optional runtime
            raise RuntimeError(
                "PyMuPDF is required to render PDF overlays. Install the ocr extra or provide a page image."
            ) from exc
        with fitz.open(document_path) as pdf:
            if page_number < 1 or page_number > pdf.page_count:
                raise ValueError(f"PDF has no page {page_number}.")
            page = pdf.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            return Image.frombytes(
                "RGB",
                (pixmap.width, pixmap.height),
                pixmap.samples,
            )
    with Image.open(document_path) as image:
        return image.convert("RGB")


def _draw_bbox(
    draw: ImageDraw.ImageDraw,
    *,
    image: Image.Image,
    bbox: AxisAlignedBoundingBox,
    spaces: dict[str, CoordinateSpace],
    label: str,
    color: str,
) -> None:
    projected = _project_to_image_pixels(bbox, image=image, spaces=spaces)
    draw.rectangle(
        [projected.x_min, projected.y_min, projected.x_max, projected.y_max],
        outline=color,
        width=2,
    )
    text_y = max(0, projected.y_min - 12)
    draw.text((projected.x_min, text_y), label, fill=color)


def _project_to_image_pixels(
    bbox: AxisAlignedBoundingBox,
    *,
    image: Image.Image,
    spaces: dict[str, CoordinateSpace],
) -> AxisAlignedBoundingBox:
    space = spaces.get(bbox.coordinate_space_id)
    if space is None:
        raise ValueError(f"Missing coordinate space {bbox.coordinate_space_id}.")
    if space.type == CoordinateSpaceType.NORMALIZED_PAGE_SPACE.value:
        return AxisAlignedBoundingBox(
            bbox.x_min * image.width,
            bbox.y_min * image.height,
            bbox.x_max * image.width,
            bbox.y_max * image.height,
            "overlay-image",
        )
    scale_x = image.width / space.width if space.width else 1.0
    scale_y = image.height / space.height if space.height else 1.0
    return AxisAlignedBoundingBox(
        bbox.x_min * scale_x,
        bbox.y_min * scale_y,
        bbox.x_max * scale_x,
        bbox.y_max * scale_y,
        "overlay-image",
    )


def _parse_types(values: Iterable[str] | None) -> set[str] | None:
    if not values:
        return None
    parsed = {value.strip() for item in values for value in item.split(",")}
    return {value for value in parsed if value}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render Canonical IR v2 overlay.")
    parser.add_argument("--document", required=True, help="Source PDF or image path.")
    parser.add_argument("--artifact", required=True, help="Canonical IR v2 JSON artifact.")
    parser.add_argument("--page", required=True, type=int, help="1-based page number.")
    parser.add_argument("--output", required=True, help="Overlay PNG output path.")
    parser.add_argument(
        "--types",
        action="append",
        help="Optional element type filter. Can be repeated or comma-separated.",
    )
    args = parser.parse_args(argv)
    render_overlay(
        document_path=args.document,
        artifact_path=args.artifact,
        page_number=args.page,
        output_path=args.output,
        element_types=_parse_types(args.types),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
