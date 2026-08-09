from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.pipeline.documents.extraction.multimodal.models import (
    CAPTION_POLICY_VERSION,
    Chart,
    ChartAxis,
    ChartDataPoint,
    ChartLegend,
    ChartSeries,
    Diagram,
    DiagramEdge,
    DiagramNode,
    Figure,
    FigureCaptionLink,
    LogoRegion,
    MultimodalEvidence,
    MultimodalIssue,
    SignatureRegion,
    StampRegion,
    VisualAsset,
    VisualBackendResult,
    VisualCandidate,
    VisualRegion,
    VisualRelationGraph,
    VisualTextBlock,
    sha256_json,
    stable_id,
)
from app.pipeline.documents.extraction.tables.models import normalize_cell_text


@dataclass(frozen=True)
class ExtractedVisualStructures:
    figures: tuple[Figure, ...] = ()
    caption_links: tuple[FigureCaptionLink, ...] = ()
    visual_text_blocks: tuple[VisualTextBlock, ...] = ()
    charts: tuple[Chart, ...] = ()
    chart_axes: tuple[ChartAxis, ...] = ()
    chart_legends: tuple[ChartLegend, ...] = ()
    chart_series: tuple[ChartSeries, ...] = ()
    chart_data_points: tuple[ChartDataPoint, ...] = ()
    diagrams: tuple[Diagram, ...] = ()
    diagram_nodes: tuple[DiagramNode, ...] = ()
    diagram_edges: tuple[DiagramEdge, ...] = ()
    signatures: tuple[SignatureRegion, ...] = ()
    stamps: tuple[StampRegion, ...] = ()
    logos: tuple[LogoRegion, ...] = ()
    relation_graphs: tuple[VisualRelationGraph, ...] = ()
    evidence: tuple[MultimodalEvidence, ...] = ()
    issues: tuple[MultimodalIssue, ...] = ()
    review_packages: tuple[dict[str, Any], ...] = ()


def extract_visual_structures(
    *,
    candidates: tuple[VisualCandidate, ...],
    assets: tuple[VisualAsset, ...],
    regions: tuple[VisualRegion, ...],
    backend_results: tuple[VisualBackendResult, ...],
    existing_issues: tuple[MultimodalIssue, ...] = (),
) -> ExtractedVisualStructures:
    candidates_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    assets_by_candidate = {asset.candidate_id: asset for asset in assets}
    regions_by_candidate = {region.candidate_id: region for region in regions}

    figures: list[Figure] = []
    caption_links: list[FigureCaptionLink] = []
    visual_text_blocks: list[VisualTextBlock] = []
    charts: list[Chart] = []
    chart_axes: list[ChartAxis] = []
    chart_legends: list[ChartLegend] = []
    chart_series: list[ChartSeries] = []
    chart_data_points: list[ChartDataPoint] = []
    diagrams: list[Diagram] = []
    diagram_nodes: list[DiagramNode] = []
    diagram_edges: list[DiagramEdge] = []
    signatures: list[SignatureRegion] = []
    stamps: list[StampRegion] = []
    logos: list[LogoRegion] = []
    relation_graphs: list[VisualRelationGraph] = []
    evidence: list[MultimodalEvidence] = []
    issues: list[MultimodalIssue] = list(existing_issues)

    for result in backend_results:
        candidate = candidates_by_id[result.candidate_id]
        asset = assets_by_candidate[result.candidate_id]
        region = regions_by_candidate[result.candidate_id]
        detected = result.detected_type
        for text in result.visual_text:
            block = _visual_text_block(candidate, region, text)
            visual_text_blocks.append(block)
            evidence.append(
                _evidence(candidate, "visual_text", block.to_dict(), (result.result_id,))
            )
        if detected == "figure":
            figure = _figure(candidate, asset, region, result)
            figures.append(figure)
            evidence.append(_evidence(candidate, "figure", figure.to_dict(), (result.result_id,)))
            caption = str(
                candidate.metadata.get("caption_text") or candidate.text_hint or ""
            ).strip()
            if caption:
                link = FigureCaptionLink(
                    link_id=stable_id("caption-link", figure.figure_id, caption),
                    figure_id=figure.figure_id,
                    caption_region_id=stable_id("caption-region", candidate.candidate_id),
                    caption_text=caption,
                    confidence=0.99,
                    rule=CAPTION_POLICY_VERSION,
                )
                caption_links.append(link)
                evidence.append(_evidence(candidate, "figure", link.to_dict(), (figure.figure_id,)))
        elif detected == "chart" and result.chart is not None:
            chart, axes, legends, series, points = _chart(candidate, asset, region, result.chart)
            charts.append(chart)
            chart_axes.extend(axes)
            chart_legends.extend(legends)
            chart_series.extend(series)
            chart_data_points.extend(points)
            evidence.append(_evidence(candidate, "chart", chart.to_dict(), (result.result_id,)))
        elif detected == "diagram" and result.diagram is not None:
            diagram, nodes, edges, graph = _diagram(candidate, asset, region, result.diagram)
            diagrams.append(diagram)
            diagram_nodes.extend(nodes)
            diagram_edges.extend(edges)
            relation_graphs.append(graph)
            evidence.append(_evidence(candidate, "diagram", graph.to_dict(), (result.result_id,)))
            if not graph.valid:
                issues.append(
                    _issue(
                        candidate,
                        "diagram_relation_graph_invalid",
                        "high",
                        "diagram relation graph failed validation",
                        review=True,
                    )
                )
        elif detected == "signature" and result.signature is not None:
            signature = SignatureRegion(
                signature_id=stable_id("signature", candidate.candidate_id),
                candidate_id=candidate.candidate_id,
                asset_id=asset.asset_id,
                region_id=region.region_id,
                document_id=candidate.document_id,
                page_number=candidate.page_number,
                linked_text=result.signature.get("linked_text"),
                confidence=float(result.signature.get("confidence", 0.99)),
                identity_inferred=False,
            )
            signatures.append(signature)
            evidence.append(
                _evidence(candidate, "signature", signature.to_dict(), (result.result_id,))
            )
        elif detected == "stamp" and result.stamp is not None:
            stamp = StampRegion(
                stamp_id=stable_id("stamp", candidate.candidate_id),
                candidate_id=candidate.candidate_id,
                asset_id=asset.asset_id,
                region_id=region.region_id,
                document_id=candidate.document_id,
                page_number=candidate.page_number,
                linked_text=result.stamp.get("linked_text"),
                confidence=float(result.stamp.get("confidence", 0.99)),
            )
            stamps.append(stamp)
            evidence.append(_evidence(candidate, "stamp", stamp.to_dict(), (result.result_id,)))
        elif detected == "logo" and result.logo is not None:
            logo = LogoRegion(
                logo_id=stable_id("logo", candidate.candidate_id),
                candidate_id=candidate.candidate_id,
                asset_id=asset.asset_id,
                region_id=region.region_id,
                document_id=candidate.document_id,
                page_number=candidate.page_number,
                brand_text=result.logo.get("linked_text"),
                confidence=float(result.logo.get("confidence", 0.99)),
            )
            logos.append(logo)
            evidence.append(_evidence(candidate, "logo", logo.to_dict(), (result.result_id,)))
        elif detected == "visual_table" and result.table_verification is not None:
            table_value = dict(result.table_verification)
            evidence.append(
                _evidence(
                    candidate,
                    "visual_table_verification",
                    table_value,
                    (result.result_id,),
                )
            )
            if table_value.get("disagreement"):
                issues.append(
                    _issue(
                        candidate,
                        "visual_text_table_disagreement",
                        "high",
                        "visual cell value disagrees with text/table evidence",
                        review=True,
                    )
                )
        elif detected == "unknown":
            issues.append(
                _issue(
                    candidate,
                    "visual_type_unknown",
                    "medium",
                    "visual backend could not classify candidate",
                    review=True,
                )
            )

    review_packages = tuple(
        {
            "review_package_id": stable_id("visual-review", issue.candidate_id, issue.issue_type),
            "candidate_id": issue.candidate_id,
            "issue_id": issue.issue_id,
            "issue_type": issue.issue_type,
            "severity": issue.severity,
            "message": issue.message,
            "source_refs": list(issue.source_refs),
        }
        for issue in issues
        if issue.review_required
    )
    return ExtractedVisualStructures(
        figures=tuple(figures),
        caption_links=tuple(caption_links),
        visual_text_blocks=tuple(visual_text_blocks),
        charts=tuple(charts),
        chart_axes=tuple(chart_axes),
        chart_legends=tuple(chart_legends),
        chart_series=tuple(chart_series),
        chart_data_points=tuple(chart_data_points),
        diagrams=tuple(diagrams),
        diagram_nodes=tuple(diagram_nodes),
        diagram_edges=tuple(diagram_edges),
        signatures=tuple(signatures),
        stamps=tuple(stamps),
        logos=tuple(logos),
        relation_graphs=tuple(relation_graphs),
        evidence=tuple(evidence),
        issues=tuple(issues),
        review_packages=review_packages,
    )


def _visual_text_block(
    candidate: VisualCandidate,
    region: VisualRegion,
    text: dict[str, Any],
) -> VisualTextBlock:
    raw = str(text.get("text") or "")
    return VisualTextBlock(
        text_block_id=stable_id("visual-text", candidate.candidate_id, raw),
        candidate_id=candidate.candidate_id,
        region_id=region.region_id,
        document_id=candidate.document_id,
        page_number=candidate.page_number,
        text=raw,
        normalized_text=str(text.get("normalized_text") or normalize_cell_text(raw)),
        language=str(text.get("language") or "vi"),
        confidence=float(text.get("confidence", 0.99)),
        diacritics_preserved=bool(text.get("diacritics_preserved", True)),
        source_refs=(region.region_id,),
    )


def _figure(
    candidate: VisualCandidate,
    asset: VisualAsset,
    region: VisualRegion,
    result: VisualBackendResult,
) -> Figure:
    return Figure(
        figure_id=stable_id("figure", candidate.candidate_id),
        candidate_id=candidate.candidate_id,
        asset_id=asset.asset_id,
        region_id=region.region_id,
        document_id=candidate.document_id,
        page_number=candidate.page_number,
        figure_type=str(candidate.metadata.get("figure_type") or "embedded"),
        caption_text=str(candidate.metadata.get("caption_text") or candidate.text_hint or "")
        or None,
        confidence=result.confidence,
        provenance={
            "backend_result_id": result.result_id,
            "asset_checksum": asset.image_checksum,
            "raw_asset_reference_preserved": True,
        },
    )


def _chart(
    candidate: VisualCandidate,
    asset: VisualAsset,
    region: VisualRegion,
    payload: dict[str, Any],
) -> tuple[
    Chart,
    tuple[ChartAxis, ...],
    tuple[ChartLegend, ...],
    tuple[ChartSeries, ...],
    tuple[ChartDataPoint, ...],
]:
    chart_id = stable_id("chart", candidate.candidate_id)
    points_payload = [dict(item) for item in payload.get("data_points") or []]
    exact = sum(item.get("value_semantics") == "exact" for item in points_payload)
    estimated = sum(item.get("value_semantics") == "estimated" for item in points_payload)
    chart = Chart(
        chart_id=chart_id,
        candidate_id=candidate.candidate_id,
        asset_id=asset.asset_id,
        region_id=region.region_id,
        document_id=candidate.document_id,
        page_number=candidate.page_number,
        chart_type=str(payload.get("chart_type") or "bar"),
        title=str(payload.get("title") or "Chart"),
        confidence=0.99,
        exact_value_count=exact,
        estimated_value_count=estimated,
        unsafe_exact_value=bool(payload.get("unsafe_exact_value", False)),
    )
    axes = tuple(
        ChartAxis(
            axis_id=stable_id("chart-axis", chart_id, item.get("axis"), item.get("label")),
            chart_id=chart_id,
            axis=str(item.get("axis") or "x"),
            label=str(item.get("label") or ""),
            scale=str(item.get("scale") or "linear"),
            confidence=float(item.get("confidence", 0.99)),
        )
        for item in payload.get("axes") or ()
    )
    legends = tuple(
        ChartLegend(
            legend_id=stable_id("chart-legend", chart_id, item.get("label"), item.get("color")),
            chart_id=chart_id,
            label=str(item.get("label") or ""),
            color=str(item.get("color") or ""),
            confidence=float(item.get("confidence", 0.99)),
        )
        for item in payload.get("legends") or ()
    )
    series = tuple(
        ChartSeries(
            series_id=stable_id("chart-series", chart_id, item.get("label")),
            chart_id=chart_id,
            label=str(item.get("label") or "Series 1"),
            chart_type=str(item.get("chart_type") or chart.chart_type),
            confidence=float(item.get("confidence", 0.99)),
        )
        for item in payload.get("series")
        or ({"label": "Series 1", "chart_type": chart.chart_type},)
    )
    first_series_id = (
        series[0].series_id if series else stable_id("chart-series", chart_id, "Series 1")
    )
    points = tuple(
        ChartDataPoint(
            point_id=stable_id("chart-point", chart_id, item.get("label"), item.get("value")),
            chart_id=chart_id,
            series_id=str(item.get("series_id") or first_series_id),
            label=str(item.get("label") or ""),
            value=float(item.get("value", 0.0)),
            value_semantics=str(item.get("value_semantics") or "estimated"),
            uncertainty=float(item.get("uncertainty", 0.0)),
            evidence=str(item.get("evidence") or "visual_chart_evidence"),
            confidence=float(item.get("confidence", 0.99)),
        )
        for item in points_payload
    )
    return chart, axes, legends, series, points


def _diagram(
    candidate: VisualCandidate,
    asset: VisualAsset,
    region: VisualRegion,
    payload: dict[str, Any],
) -> tuple[Diagram, tuple[DiagramNode, ...], tuple[DiagramEdge, ...], VisualRelationGraph]:
    diagram_id = stable_id("diagram", candidate.candidate_id)
    diagram = Diagram(
        diagram_id=diagram_id,
        candidate_id=candidate.candidate_id,
        asset_id=asset.asset_id,
        region_id=region.region_id,
        document_id=candidate.document_id,
        page_number=candidate.page_number,
        diagram_type=str(payload.get("diagram_type") or "flowchart"),
        confidence=0.99,
        relation_graph_valid=bool(payload.get("relation_graph_valid", True)),
    )
    nodes = tuple(
        DiagramNode(
            node_id=stable_id("diagram-node", diagram_id, item.get("label")),
            diagram_id=diagram_id,
            label=str(item.get("label") or ""),
            bbox=dict(item.get("bbox") or region.bbox),
            confidence=float(item.get("confidence", 0.99)),
        )
        for item in payload.get("nodes") or ()
    )
    nodes_by_label = {node.label: node.node_id for node in nodes}
    edges = tuple(
        DiagramEdge(
            edge_id=stable_id(
                "diagram-edge",
                diagram_id,
                item.get("source_label"),
                item.get("target_label"),
            ),
            diagram_id=diagram_id,
            source_node_id=nodes_by_label.get(str(item.get("source_label")))
            or (nodes[0].node_id if nodes else ""),
            target_node_id=nodes_by_label.get(str(item.get("target_label")))
            or (nodes[-1].node_id if nodes else ""),
            direction=str(item.get("direction") or "forward"),
            relation_type=str(item.get("relation_type") or "flow"),
            confidence=float(item.get("confidence", 0.99)),
        )
        for item in payload.get("edges") or ()
    )
    graph_valid = bool(nodes) and all(edge.source_node_id and edge.target_node_id for edge in edges)
    graph = VisualRelationGraph(
        graph_id=stable_id("relation-graph", diagram_id),
        candidate_id=candidate.candidate_id,
        node_ids=tuple(node.node_id for node in nodes),
        edge_ids=tuple(edge.edge_id for edge in edges),
        valid=graph_valid and diagram.relation_graph_valid,
        reason_codes=("diagram_relation_graph_v1",),
    )
    return diagram, nodes, edges, graph


def _evidence(
    candidate: VisualCandidate,
    evidence_type: str,
    value: dict[str, Any],
    source_refs: tuple[str, ...],
) -> MultimodalEvidence:
    return MultimodalEvidence(
        evidence_id=stable_id(
            "visual-evidence", candidate.candidate_id, evidence_type, sha256_json(value)
        ),
        candidate_id=candidate.candidate_id,
        evidence_type=evidence_type,
        value=value,
        confidence=float(value.get("confidence", 0.99)) if isinstance(value, dict) else 0.99,
        source_refs=source_refs,
    )


def _issue(
    candidate: VisualCandidate,
    issue_type: str,
    severity: str,
    message: str,
    *,
    review: bool,
) -> MultimodalIssue:
    return MultimodalIssue(
        issue_id=stable_id("visual-issue", candidate.candidate_id, issue_type),
        candidate_id=candidate.candidate_id,
        issue_type=issue_type,
        severity=severity,
        terminal=True,
        message=message,
        review_required=review,
        source_refs=tuple(candidate.source_refs),
    )


__all__ = ["ExtractedVisualStructures", "extract_visual_structures"]
