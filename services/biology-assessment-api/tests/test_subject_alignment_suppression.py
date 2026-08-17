import sqlite3

from fastapi.testclient import TestClient

from app.main import app
from app.settings import detail_catalog_database_path

client = TestClient(app)


def test_cross_subject_evidence_is_suppressed_from_the_public_case() -> None:
    """annotate_case_subject_alignment.py flags cases whose evidence_excerpt
    quotes another subject's achievement code. The API must not publish that
    text (SOURCE_POLICY.md's public boundary rule) even though it is still on
    the record for audit."""
    connection = sqlite3.connect(detail_catalog_database_path())
    try:
        case_id = connection.execute(
            "SELECT case_id FROM cases"
            " WHERE subject_alignment = 'other' AND title_basis = 'source_detail'"
            " LIMIT 1"
        ).fetchone()[0]
    finally:
        connection.close()

    response = client.get(f"/api/v1/cases/{case_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_excerpt"] == ""
    assert payload["assessment_structure"]["overview"] == ""
    assert payload["assessment_structure"]["standards"] == []
    assert payload["assessment_structure"]["criteria"] == []
    # source_url still stands in for it, per SOURCE_POLICY.md.
    assert payload["source_url"]


def test_html_markup_never_reaches_a_case_response_as_literal_text() -> None:
    # The source DB still stores the scraped HTML fragments as-is (that is
    # the pipeline's raw record); the API must clean them on the way out.
    connection = sqlite3.connect(detail_catalog_database_path())
    try:
        row = connection.execute(
            "SELECT case_id FROM cases"
            " WHERE (evidence_excerpt LIKE '%<td%' OR evidence_excerpt LIKE '%<tr%')"
            " AND title_basis = 'source_detail'"
            " LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    assert row is not None, "fixture assumption stale: no case has raw markup to clean anymore"

    response = client.get(f"/api/v1/cases/{row[0]}")

    assert response.status_code == 200
    payload = response.json()
    assert "<td" not in payload["evidence_excerpt"]
    assert "<tr" not in payload["evidence_excerpt"]
    assert "<td" not in payload["assessment_structure"]["overview"]
