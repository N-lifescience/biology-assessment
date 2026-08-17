"""Self-checks for the audits behind ``npm run audit:data``."""

import sqlite3
import zlib

import pytest
from scripts.audit_biology_assessment_detail_db import audit as detail_db_audit
from scripts.audit_biology_assessment_publication_gate import gate_reasons
from scripts.audit_biology_assessment_subject_alignment import compare
from scripts.audit_biology_assessment_table_structure import boundary_grade
from scripts.audit_biology_assessment_titles_full import audit_database

SCHEMA = """
CREATE TABLE cases (
    case_id TEXT, curriculum TEXT, subject TEXT, school_name TEXT, region TEXT,
    district TEXT, academic_years_json TEXT, grades_json TEXT, task_names_json TEXT,
    action_tags_json TEXT, rubric_marker_count INTEGER,
    achievement_standard_marker_count INTEGER, weight_or_points_marker_count INTEGER,
    assessment_method_marker_count INTEGER, review_score INTEGER, source_url TEXT,
    source_sha256 TEXT);
CREATE TABLE subject_stats (
    curriculum TEXT, subject TEXT, documents INTEGER, schools INTEGER,
    small_sample INTEGER, academic_years_json TEXT, grade1_documents INTEGER,
    grade2_documents INTEGER, grade3_documents INTEGER, rubric_documents INTEGER,
    achievement_standard_documents INTEGER, weight_or_points_documents INTEGER,
    assessment_method_documents INTEGER, median_review_score REAL,
    task_name_candidates INTEGER, coverage_found INTEGER, coverage_ambiguous INTEGER,
    coverage_not_found INTEGER, coverage_offering_unknown INTEGER,
    coverage_extraction_failed INTEGER);
CREATE TABLE subject_action_tags (
    curriculum TEXT, subject TEXT, tag TEXT, document_count INTEGER, school_count INTEGER);
CREATE TABLE case_detail_status (
    case_id TEXT, source_format TEXT, boundary_status TEXT,
    source_section_char_count INTEGER);
CREATE TABLE assessment_items (
    item_id TEXT, case_id TEXT, title TEXT, title_basis TEXT, extraction_status TEXT,
    rubric_html_char_count INTEGER, source_html_zlib BLOB, rubric_html_zlib BLOB);
CREATE TABLE assessment_item_rankings (item_id TEXT, category TEXT);
"""


def build(path):
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    blob = zlib.compress(b"<table></table>")
    connection.executemany(
        "INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("c1", "2015", "생명과학Ⅰ", "가고", "서울", "강남", "[2025]", "[1]",
             '["탐구 보고서 작성"]', '["inquiry"]', 1, 0, 1, 0, 40, "https://x/1", "aa"),
            ("c2", "2015", "생명과학Ⅰ", "가고", "부산", "해운대", "[2026]", "[2]",
             "[]", '["inquiry","reading"]', 0, 0, 0, 0, 50, "https://x/2", "bb"),
        ],
    )
    connection.execute(
        "INSERT INTO subject_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("2015", "생명과학Ⅰ", 2, 2, 1, "[2025, 2026]", 1, 1, 0, 1, 0, 1, 0, 45.0, 1,
         2, 0, 8, 0, 0),
    )
    connection.executemany(
        "INSERT INTO subject_action_tags VALUES (?,?,?,?,?)",
        [("2015", "생명과학Ⅰ", "inquiry", 2, 2), ("2015", "생명과학Ⅰ", "reading", 1, 1)],
    )
    connection.executemany(
        "INSERT INTO case_detail_status VALUES (?,?,?,?)",
        [
            ("c1", "pdf", "subject_heading:assessment_anchor", 5000),
            ("c2", "hwp", "subject_heading_not_found:assessment_anchor_not_found", 100),
        ],
    )
    connection.executemany(
        "INSERT INTO assessment_items VALUES (?,?,?,?,?,?,?,?)",
        [
            ("i1", "c1", "탐구 보고서 작성", "table_bundle", "bounded", 900, blob, blob),
            ("i2", "c2", "광합성", "heading", "bundle_review", 0, None, None),
        ],
    )
    connection.executemany(
        "INSERT INTO assessment_item_rankings VALUES (?,?)",
        [("i1", "inquiry"), ("i2", "reading")],
    )
    connection.commit()
    connection.close()
    return path


@pytest.fixture
def database(tmp_path):
    return build(tmp_path / "detail.sqlite")


@pytest.mark.parametrize(
    "boundary_status,grade",
    [
        ("subject_heading:assessment_anchor", "trusted"),
        ("subject_mention_only:assessment_anchor", "trusted"),
        ("subject_heading:assessment_anchor_not_found", "partial"),
        ("subject_heading_not_found:assessment_anchor", "partial"),
        ("subject_heading_not_found:assessment_anchor_not_found", "untrusted"),
    ],
)
def test_boundary_grade_counts_only_failed_lookups(boundary_status, grade):
    assert boundary_grade(boundary_status) == grade


def test_subject_stats_recomputed_from_cases_agree(database):
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    mismatches, _ = compare(connection)
    assert mismatches == []


def test_subject_alignment_catches_a_stale_aggregate(database):
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("UPDATE subject_stats SET documents = 99, schools = 7")
    mismatches, bad_keys = compare(connection)
    assert any("documents stored=99" in line for line in mismatches)
    assert any("schools stored=7" in line for line in mismatches)
    assert bad_keys == {("2015", "생명과학Ⅰ")}


def test_detail_db_audit_is_clean_then_catches_an_orphan(database):
    report = detail_db_audit(database)
    assert set(report["orphans"].values()) == {0}
    assert set(report["duplicates"].values()) == {0}
    assert report["extraction_status"] == {"bounded": 1, "bundle_review": 1}
    assert report["rubric_html"]["empty"] == 1
    assert report["bounded_missing_html"] == {"source_html_zlib": 0, "rubric_html_zlib": 0}

    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO assessment_items VALUES ('i3','ghost','x','table','bounded',1,NULL,NULL)"
    )
    connection.commit()
    connection.close()
    broken = detail_db_audit(database)
    assert broken["orphans"]["assessment_items.case_id->cases.case_id"] == 1
    assert broken["orphans"]["assessment_items.item_id->assessment_item_rankings.item_id"] == 1
    assert broken["bounded_missing_html"]["source_html_zlib"] == 1


def test_publication_gate_reasons_cover_every_evidence_requirement():
    good = {
        "source_url": "https://x/1",
        "source_sha256": "aa",
        "boundary_status": "subject_heading:assessment_anchor",
        "source_html_zlib": zlib.compress(b"<table></table>"),
    }
    assert gate_reasons(good) == []
    assert gate_reasons({**good, "source_url": " "}) == ["missing_source_url"]
    assert gate_reasons({**good, "source_sha256": None}) == ["missing_source_sha256"]
    assert gate_reasons({**good, "source_html_zlib": None}) == ["missing_source_html"]
    assert gate_reasons({**good, "source_html_zlib": b"not zlib"}) == ["undecodable_source_html"]
    partial = {**good, "boundary_status": "subject_heading:assessment_anchor_not_found"}
    assert gate_reasons(partial) == ["boundary_partial"]


def test_title_basis_decides_whether_a_source_label_backed_the_title(database):
    rows = {row["item_id"]: row for row in audit_database(database)}
    # A bundle table title still came out of a labelled cell...
    assert rows["i1"]["source"] == "table"
    assert rows["i1"]["confidence"] == "supported"
    # ...while a heading title is a bare line, so a one-word name stays unproven.
    assert rows["i2"]["source"] == "section"
    assert rows["i2"]["confidence"] == "review"
