import shutil
import sqlite3
from pathlib import Path

import pytest
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
        item["curriculum"] == "2022" and item["subject"] == "생명과학" and item["documents"] == 1690
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
    assert biology_item["documents"] == 1690
    assert biology_item["coverage"]["found"] == 1477
    assert biology_item["small_sample"] is False
    assert any(tag["tag"] == "탐구" for tag in biology_item["action_tags"])

    assert biology_one.status_code == 200
    biology_one_item = biology_one.json()["items"][0]
    assert biology_one_item["documents"] == 95
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


@pytest.fixture(scope="module")
def semester_database(tmp_path_factory) -> Path:
    """Use the existing published-schema fixture pattern without changing source data."""
    database = tmp_path_factory.mktemp("semesters") / "catalog.sqlite"
    shutil.copyfile(detail_catalog_database_path(), database)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        case_seed = dict(connection.execute(
            "SELECT * FROM cases WHERE title_basis = 'source_detail' LIMIT 1"
        ).fetchone())
        item_seed = dict(connection.execute(
            "SELECT * FROM assessment_items WHERE extraction_status = 'bounded'"
            " AND title_basis IN ('table', 'heading') LIMIT 1"
        ).fetchone())
        status_seed = dict(connection.execute(
            "SELECT * FROM case_detail_status LIMIT 1"
        ).fetchone())
        ranking_seed = dict(connection.execute(
            "SELECT * FROM assessment_item_rankings LIMIT 1"
        ).fetchone())
        for table in (
            "assessment_item_axes", "assessment_item_rankings", "assessment_items",
            "case_detail_status", "cases",
        ):
            connection.execute(f"DELETE FROM {table}")

        def insert(table: str, values: dict) -> None:
            placeholders = ", ".join("?" for _ in values)
            connection.execute(
                f"INSERT INTO {table} ({', '.join(values)}) VALUES ({placeholders})",
                list(values.values()),
            )

        for index in range(1, 10):
            case_id = f"{index:024x}"
            url = "https://www.schoolinfo.go.kr/download.do?year=2026"
            if index != 3:
                url += f"&JG_CHASU={1 if index == 1 else 3}"
            insert("cases", {
                **case_seed, "case_id": case_id, "source_url": url,
                # Deliberately contradict the body semester to catch accidental use of it.
                "semesters_json": "[2]" if index in (1, 3) else "[1]",
                "curriculum": "2015" if index == 6 else "2022",
                "subject": "생명과학Ⅰ" if index == 6 else "생명과학",
                "school_name": "가상고등학교", "region": "부산" if index == 4 else "서울",
                "district": "송파구" if index == 5 else "강남구",
                "action_tags_json": '["보고서"]' if index == 7 else '["탐구"]',
                "primary_task_name": "대사 조사" if index == 8 else "세포 탐구",
                "task_names_json": "[]", "evidence_excerpt": "조사 결과를 설명한다.",
                "title_basis": "source_detail_bundle_review" if index == 9 else "source_detail",
            })
            insert("case_detail_status", {**status_seed, "case_id": case_id})
            # A second assessment in case 2 distinguishes case counts from item counts.
            for order in range(1, 3 if index == 2 else 2):
                item_id = f"{case_id}-{order}"
                insert("assessment_items", {
                    **item_seed, "item_id": item_id, "case_id": case_id, "item_order": order,
                    "title": "대사 조사" if index == 8 else "세포 탐구",
                    "overview": "조사 결과를 설명한다.",
                    "title_basis": "context" if index == 9 else "table",
                    "extraction_status": "bounded",
                })
                category = "writing" if index == 8 else "inquiry"
                topic = "genetics" if index == 7 else "cell"
                insert("assessment_item_rankings", {
                    **ranking_seed, "item_id": item_id, "category": category,
                    "topic": topic, "priority_score": 68,
                })
                connection.executemany(
                    "INSERT INTO assessment_item_axes VALUES (?, ?, ?)",
                    [(item_id, "method", category), (item_id, "topic", topic)],
                )
    return database


@pytest.fixture
def semester_client(semester_database, monkeypatch) -> TestClient:
    monkeypatch.setenv("BIOLOGY_ASSESSMENT_DETAIL_DB", str(semester_database))
    monkeypatch.setenv("BIOLOGY_ASSESSMENT_PUBLISH_DB", str(semester_database))
    return TestClient(app)


SEMESTER_FILTERS = {
    "curriculum": "2022", "subject": "생명과학", "region": "서울", "district": "강남구",
}


@pytest.mark.parametrize("semester, expected_ids", [("1", [1, 3]), ("2", [2])])
def test_cases_filter_disclosure_semester_with_existing_filters(
    semester_client, semester, expected_ids
) -> None:
    response = semester_client.get("/api/v1/cases", params={
        **SEMESTER_FILTERS, "tag": "탐구", "query": "세포", "semester": semester,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == len(expected_ids)
    assert {item["case_id"] for item in payload["items"]} == {
        f"{index:024x}" for index in expected_ids
    }
    assert all(item["disclosure_semester"] == int(semester) for item in payload["items"])
    assert all(item["semesters"] != [int(semester)] for item in payload["items"])


def test_disclosure_semester_is_present_in_all_detail_responses(semester_client) -> None:
    for index, semester in ((1, 1), (2, 2), (3, 1)):
        case_id = f"{index:024x}"
        for path in (f"cases/{case_id}", f"cases/{case_id}/detail",
                     f"assessment-items/{case_id}-1"):
            response = semester_client.get(f"/api/v1/{path}")
            assert response.status_code == 200
            assert response.json()["disclosure_semester"] == semester


def test_semester_facets_use_all_other_filters_and_keep_both_options(semester_client) -> None:
    filters = {**SEMESTER_FILTERS, "tag": "탐구", "query": "세포", "semester": "2"}
    response = semester_client.get("/api/v1/facets", params=filters)
    assert response.status_code == 200
    payload = response.json()
    assert payload["semesters"] == [{"value": "1", "count": 2}, {"value": "2", "count": 1}]
    # Other facets do narrow to the selected semester (case 1 and 3 are excluded).
    assert sum(item["count"] for item in payload["regions"]) == 5
    assert payload["action_tags"]
    empty = semester_client.get("/api/v1/facets", params={**filters, "query": "없음"})
    assert empty.json()["semesters"] == [{"value": "1", "count": 0}, {"value": "2", "count": 0}]


@pytest.mark.parametrize("endpoint", ["curated", "references"])
def test_reference_items_filter_disclosure_semester_and_report_matching_total(
    semester_client, endpoint
) -> None:
    response = semester_client.get(f"/api/v1/{endpoint}", params={
        **SEMESTER_FILTERS, "semester": "2", "category": "inquiry", "topic": "cell", "limit": 1,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 1
    assert payload["items"][0]["case_id"] == f"{2:024x}"
    assert payload["items"][0]["disclosure_semester"] == 2
    if endpoint == "references":
        assert payload["facets"]["semesters"] == [
            {"value": "1", "count": 2}, {"value": "2", "count": 2},
        ]
        second = semester_client.get("/api/v1/references", params={
            **SEMESTER_FILTERS, "semester": "2", "category": "inquiry", "topic": "cell",
            "limit": 1, "offset": 1,
        }).json()
        assert second["total"] == 2
        assert second["items"][0]["item_id"] != payload["items"][0]["item_id"]


@pytest.mark.parametrize("endpoint", ["cases", "curated", "references", "facets"])
@pytest.mark.parametrize("semester", ["3", "", "12"])
def test_invalid_semester_is_rejected(endpoint, semester) -> None:
    response = client.get(f"/api/v1/{endpoint}", params={"semester": semester})
    assert response.status_code == 422
