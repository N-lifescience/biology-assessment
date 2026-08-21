import sqlite3

from fastapi.testclient import TestClient

from app.main import app
from app.settings import detail_catalog_database_path

client = TestClient(app)


def test_subjects_expose_all_course_groups_and_keep_ambiguity_separate() -> None:
    response = client.get("/api/v1/subjects")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 9
    assert any(
        item["curriculum"] == "2022" and item["subject"] == "생명과학" and item["documents"] == 1416
        for item in payload["items"]
    )
    # No 2015/2022-ambiguous subject exists in the current collection: every
    # subject name in the target course groups maps to exactly one curriculum.
    assert not any(item["curriculum_ambiguous"] for item in payload["items"])
    assert "뜻이 아닙니다" in payload["caution"]


def test_trends_return_verified_subject_counts_and_action_tags() -> None:
    biology = client.get("/api/v1/trends", params={"curriculum": "2022", "subject": "생명과학"})
    biology_one = client.get(
        "/api/v1/trends", params={"curriculum": "2015", "subject": "생명과학Ⅰ"}
    )

    assert biology.status_code == 200
    biology_item = biology.json()["items"][0]
    assert biology_item["documents"] == 1416
    assert biology_item["coverage"]["found"] == 1348
    assert biology_item["small_sample"] is False
    assert any(tag["tag"] == "탐구" for tag in biology_item["action_tags"])

    assert biology_one.status_code == 200
    biology_one_item = biology_one.json()["items"][0]
    assert biology_one_item["documents"] == 53
    assert biology_one_item["small_sample"] is False


def test_cases_filter_by_course_without_exposing_local_paths_or_full_text() -> None:
    response = client.get(
        "/api/v1/cases",
        params={"curriculum": "2015", "subject": "생명과학Ⅱ", "limit": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] > 0
    assert len(payload["items"]) == 3
    for item in payload["items"]:
        assert item["subject"] == "생명과학Ⅱ"
        assert item["curriculum"] == "2015"
        assert item["assessment_structure"]["basis"] == "source_detail"
        assert len(item["evidence_excerpt"]) <= 902
        serialized = str(item)
        assert "saved_path" not in serialized
        assert "final_url" not in serialized
        assert "C:\\Users\\" not in serialized


def _published_category() -> str:
    """Return a category id that exists in the published rankings table."""

    connection = sqlite3.connect(detail_catalog_database_path())
    try:
        row = connection.execute(
            "SELECT category FROM assessment_item_rankings"
            " WHERE category <> '' AND priority_score >= 38"
            " GROUP BY category ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    assert row, "published database has no ranked categories"
    return str(row[0])


def test_cases_support_the_whole_library_without_course_filters() -> None:
    response = client.get("/api/v1/cases", params={"limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert 0 < payload["total"] < 8800
    assert len({(item["curriculum"], item["subject"]) for item in payload["items"]}) >= 1
    assert all(
        item["assessment_structure"]["basis"] == "source_detail"
        for item in payload["items"]
    )


def test_curated_cases_use_transparent_evidence_priority() -> None:
    # Read a category the published database actually holds instead of naming
    # one: the 영역명 taxonomy is expected to be revised, and this test is
    # about the endpoint's evidence contract, not about any one category id.
    category = _published_category()
    response = client.get(
        "/api/v1/curated",
        params={"category": category, "limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]
    assert "서열" in payload["interpretation"]
    for item in payload["items"]:
        assert item["category"] == category
        assert item["title_basis"] in {"table", "heading"}
        assert item["priority_signals"]
        assert "\n" not in item["title"]
        assert not item["title"].startswith("평가 방법:")


def test_cases_search_without_the_deploy_only_fts_tables() -> None:
    seed = client.get(
        "/api/v1/cases",
        params={"curriculum": "2022", "subject": "생명과학", "limit": 1},
    ).json()["items"][0]

    response = client.get(
        "/api/v1/cases",
        params={
            "curriculum": "2022",
            "subject": "생명과학",
            "query": seed["primary_task_name"],
                "limit": 30,
        },
    )

    assert response.status_code == 200
    assert any(item["case_id"] == seed["case_id"] for item in response.json()["items"])


def test_facets_offer_course_specific_regions_and_action_tags() -> None:
    response = client.get("/api/v1/facets", params={"curriculum": "2022", "subject": "생명과학"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["regions"]
    assert any(item["value"] == "탐구" for item in payload["action_tags"])
    assert all(item["count"] > 0 for item in payload["regions"])


def test_region_facet_filters_the_library_and_preserves_its_count() -> None:
    facets = client.get(
        "/api/v1/facets", params={"curriculum": "2022", "subject": "생명과학"}
    ).json()
    selected = facets["regions"][0]

    response = client.get(
        "/api/v1/cases",
        params={
            "curriculum": "2022",
            "subject": "생명과학",
            "region": selected["value"],
                "limit": 30,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == selected["count"]
    assert all(item["region"] == selected["value"] for item in payload["items"])


def test_case_detail_uses_stable_identifier_and_public_schoolinfo_source() -> None:
    search = client.get(
        "/api/v1/cases",
        params={"curriculum": "2022", "subject": "생명과학", "limit": 1},
    )
    case_id = search.json()["items"][0]["case_id"]
    detail = client.get(f"/api/v1/cases/{case_id}")

    assert detail.status_code == 200
    item = detail.json()
    assert item["case_id"] == case_id
    assert item["source_url"].startswith("https://www.schoolinfo.go.kr/")
    assert len(item["source_sha256"]) == 64


def test_invalid_filters_are_rejected_before_database_query() -> None:
    response = client.get("/api/v1/cases", params={"limit": 101})

    assert response.status_code == 422


def test_review_query_parameter_cannot_bypass_confirmed_only_catalogue() -> None:
    confirmed = client.get(
        "/api/v1/cases",
        params={"source_status": "confirmed", "limit": 5},
    )
    review = client.get(
        "/api/v1/cases",
        params={"source_status": "review", "limit": 5},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["items"]
    assert all(
        item["assessment_structure"]["basis"] == "source_detail"
        for item in confirmed.json()["items"]
    )
    assert review.status_code == 200
    assert review.json()["items"]
    assert all(
        item["assessment_structure"]["basis"] == "source_detail"
        for item in review.json()["items"]
    )


def test_official_sources_keep_authority_layers_separate() -> None:
    response = client.get("/api/v1/sources")

    assert response.status_code == 200
    payload = response.json()
    assert [layer["level"] for layer in payload["layers"]] == [1, 2, 3]
    assert any(
        source["curriculum"] == "2022"
        and source["identifier"] == "교육부 고시 제2022-33호"
        and source["layer"] == 1
        for source in payload["sources"]
    )
    assert any(
        source["curriculum"] == "2022"
        and source["document_type"] == "고등학교 과학과 공통·선택과목 성취수준"
        and "생명과학" in source["service_use"]
        for source in payload["sources"]
    )
    schoolinfo = next(source for source in payload["sources"] if source["layer"] == 3)
    assert schoolinfo["provider"] == "학교알리미"
    assert "성취기준 원문" not in schoolinfo["service_use"]
    serialized = response.text
    assert "C:\\\\Users\\\\" not in serialized
    assert "saved_path" not in serialized
