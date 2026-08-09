# Advanced Extraction Subsystem

The official repository contains the advanced extraction subsystem from
the source implementation, mapped under the `documents` bounded context.

Runtime flow:

1. `documents.application.extraction_pipeline.AdvancedExtractionPipeline`
   parses and sanitizes source content.
2. The quality gate evaluates the parsed document and routes the result.
3. Canonical IR v2 is built and validated.
4. Phase 3 layout and reading-order artifacts are generated.
5. Phase 4 structured table reconstruction runs from canonical/layout
   evidence.
6. Phase 5 provider verification runs deterministic local providers by
   default.
7. Phase 6 multimodal extraction is available and defaults to disabled
   mode unless configured.
8. `indexing.application.pipeline.IngestionEmbeddingPipeline` embeds
   only when extraction quality allows indexing.

Safety properties:

- Extraction failure or a blocking quality decision prevents embedding.
- OCR is opt-in via `OCR_ENABLED=true`.
- Heavy OCR dependencies are kept in the `ocr` optional dependency group.
- Concrete parsers, visual backends, and vector stores remain adapters.
- The indexing layer does not implement extraction logic.
