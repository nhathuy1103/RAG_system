"""HTTP contract tests for the non-persisting extraction inspector."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.api.routers.extraction import router
from app.api.schemas.auth import CurrentUser
from app.pipeline.bootstrap.settings import Settings, get_settings


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="20000000-0000-0000-0000-000000000002",
        email="inspector@example.com",
        role="authenticated",
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        advanced_extraction_enabled=True,
        ocr_enabled=False,
        extraction_quality_mode="rag",
    )
    return app


def test_inspector_returns_content_quality_metadata_and_canonical_ir() -> None:
    with TestClient(make_app()) as client:
        response = client.post(
            "/documents/extraction-inspect",
            files={
                "file": (
                    "brief.txt",
                    "Doanh thu năm 2026 tăng 15%.\n\nChi phí được kiểm soát.",
                    "text/plain",
                )
            },
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    payload = response.json()
    assert payload["source"]["filename"] == "brief.txt"
    assert payload["summary"]["parser_name"] == "txt"
    assert payload["summary"]["index_allowed"] is True
    assert payload["summary"]["quality_status"] == "PASS"
    assert payload["summary"]["chunk_count"] == 1
    assert "Doanh thu" in payload["content"]["text"]
    assert payload["chunking"]["status"] == "generated"
    assert payload["chunking"]["embedding_applied"] is False
    assert payload["chunks"][0]["text"] == payload["content"]["text"]
    assert payload["chunks"][0]["retrieval_metadata"]["title"] == "brief.txt"
    assert payload["parsed_document"]["pages"][0]["page_number"] == 1
    assert payload["quality_decision"]["action"] == "ACCEPT"
    assert payload["canonical_ir"]["schema_version"] == "2.0.0"
    assert payload["canonical_ir_validation"]["valid"] is True
    assert payload["phases"]["tables"]["structured_tables"] == []


def test_inspector_rejects_unsupported_file_without_persisting() -> None:
    with TestClient(make_app()) as client:
        response = client.post(
            "/documents/extraction-inspect",
            files={"file": ("malware.exe", b"not executable", "application/octet-stream")},
        )

    assert response.status_code == 415
    assert response.json()["detail"] == "File extension is not supported."


def test_inspector_returns_parser_and_reconstructed_csv_tables() -> None:
    with TestClient(make_app()) as client:
        response = client.post(
            "/documents/extraction-inspect",
            files={
                "file": (
                    "prices.csv",
                    b"Unit,Price,VAT\nA101,2000000000,included\nA102,2200000000,excluded\n",
                    "text/csv",
                )
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["parser_name"] == "csv"
    assert payload["summary"]["table_count"] == 1
    assert payload["parsed_document"]["tables"][0]["header"] == ["Unit", "Price", "VAT"]
    assert payload["parsed_document"]["tables"][0]["rows"][1][0] == "A101"
    assert len(payload["phases"]["tables"]["structured_tables"]) == 1
    assert payload["summary"]["chunk_count"] == 1
    assert payload["chunks"][0]["table_identity"] is not None
    assert payload["chunks"][0]["source_block_ids"]
