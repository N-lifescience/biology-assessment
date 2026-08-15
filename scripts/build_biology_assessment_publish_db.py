"""Build the read-only SQLite publish databases the API serves.

Schema and query shapes are dictated entirely by
``services/biology-assessment-api/app/repository.py`` (read first, not
guessed). ``cases``/``subject_stats``/``subject_action_tags`` are populated
from real reprocessing-pipeline output. ``assessment_items``,
``assessment_item_rankings``, and ``case_detail_status`` are created with
the correct schema but left EMPTY: populating them means parsing individual
assessment items out of source HTML (``biology_assessment_detail_parser.py``
+ its missing ``html_tables()`` dependency), which is out of scope here. The
API already degrades gracefully for that: ``cases.title_basis`` is set to
the honest, non-matching value ``"catalog_only"`` (never ``"source_detail"``)
so confirmed-only endpoints (``/api/v1/cases``, ``/api/v1/cases/{id}``)
correctly report nothing rather than fabricate a title. ``/api/v1/subjects``
and ``/api/v1/trends`` are unaffected and serve real data.

The catalog and detail databases get identical content: this pipeline only
produces one dataset, so there is nothing distinct to put in the "detail"
file. See ``app/settings.py`` for why both paths are checked.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE cases (
    case_id TEXT PRIMARY KEY,
    curriculum TEXT NOT NULL,
    subject TEXT NOT NULL,
    curriculum_basis TEXT NOT NULL,
    school_name TEXT NOT NULL,
    region TEXT NOT NULL,
    district TEXT NOT NULL,
    academic_years_json TEXT NOT NULL,
    grades_json TEXT NOT NULL,
    semesters_json TEXT NOT NULL,
    primary_task_name TEXT NOT NULL,
    task_names_json TEXT NOT NULL,
    action_tags_json TEXT NOT NULL,
    rubric_marker_count INTEGER NOT NULL,
    achievement_standard_marker_count INTEGER NOT NULL,
    weight_or_points_marker_count INTEGER NOT NULL,
    assessment_method_marker_count INTEGER NOT NULL,
    review_score INTEGER NOT NULL,
    evidence_excerpt TEXT NOT NULL,
    methods_json TEXT NOT NULL,
    weight_summary TEXT NOT NULL,
    standards_json TEXT NOT NULL,
    criteria_json TEXT NOT NULL,
    title_basis TEXT NOT NULL,
    category TEXT NOT NULL,
    priority_score INTEGER NOT NULL,
    priority_signals_json TEXT NOT NULL,
    candidate_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_sha256 TEXT NOT NULL
);
CREATE INDEX idx_cases_curriculum_subject ON cases(curriculum, subject);
CREATE INDEX idx_cases_category ON cases(category);

CREATE TABLE subject_stats (
    curriculum TEXT NOT NULL,
    subject TEXT NOT NULL,
    documents INTEGER NOT NULL,
    schools INTEGER NOT NULL,
    small_sample INTEGER NOT NULL,
    academic_years_json TEXT NOT NULL,
    grade1_documents INTEGER NOT NULL,
    grade2_documents INTEGER NOT NULL,
    grade3_documents INTEGER NOT NULL,
    rubric_documents INTEGER NOT NULL,
    achievement_standard_documents INTEGER NOT NULL,
    weight_or_points_documents INTEGER NOT NULL,
    assessment_method_documents INTEGER NOT NULL,
    median_review_score REAL,
    task_name_candidates INTEGER NOT NULL,
    coverage_found INTEGER,
    coverage_ambiguous INTEGER,
    coverage_not_found INTEGER,
    coverage_offering_unknown INTEGER,
    coverage_extraction_failed INTEGER,
    PRIMARY KEY (curriculum, subject)
);

CREATE TABLE subject_action_tags (
    curriculum TEXT NOT NULL,
    subject TEXT NOT NULL,
    tag TEXT NOT NULL,
    document_count INTEGER NOT NULL,
    school_count INTEGER NOT NULL
);
CREATE INDEX idx_subject_action_tags ON subject_action_tags(curriculum, subject);

CREATE TABLE assessment_items (
    item_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    item_order INTEGER NOT NULL,
    title TEXT NOT NULL,
    title_raw TEXT NOT NULL,
    title_basis TEXT NOT NULL,
    extraction_status TEXT NOT NULL,
    overview TEXT NOT NULL,
    method TEXT NOT NULL,
    timing TEXT NOT NULL,
    score TEXT NOT NULL,
    weight TEXT NOT NULL,
    standards_json TEXT NOT NULL,
    rubric_html_char_count INTEGER NOT NULL,
    source_html_zlib BLOB,
    rubric_html_zlib BLOB
);

CREATE TABLE assessment_item_rankings (
    item_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    priority_score INTEGER NOT NULL,
    priority_signals_json TEXT NOT NULL
);

CREATE TABLE case_detail_status (
    case_id TEXT PRIMARY KEY,
    source_format TEXT NOT NULL,
    boundary_status TEXT NOT NULL,
    source_section_char_count INTEGER NOT NULL
);
"""

UNCONFIRMED_TASK_NAME = "구체적 과제명 미탐지"
CATEGORY_TAG_ORDER = [
    ("생태조사", "ecology"),
    ("탐구", "inquiry"),
    ("문제해결", "problem"),
    ("발표", "presentation"),
    ("포트폴리오", "portfolio"),
    ("보고서", "reading"),
]
# ponytail: a school count below this is treated as too small to publish
# per-school detail confidently. No official threshold was handed off.
SMALL_SAMPLE_SCHOOL_THRESHOLD = 3


def case_id_for(source_key: str, subject: str) -> str:
    return hashlib.sha1(f"{source_key}:{subject}".encode("utf-8")).hexdigest()[:24]


def category_for(action_tags: list[str]) -> str:
    tags = set(action_tags)
    for tag, category in CATEGORY_TAG_ORDER:
        if tag in tags:
            return category
    return "inquiry"


def region_from_saved_path(saved_path: str) -> str:
    parts = saved_path.split("/")
    if len(parts) >= 5 and parts[0] == "data" and parts[2] == "schoolinfo":
        return parts[4]
    return ""


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_cases(connection: sqlite3.Connection, catalog_path: Path) -> None:
    rows = []
    for record in read_jsonl(catalog_path):
        source = record.get("source") or {}
        source_key = str(source.get("saved_path") or source.get("final_url") or "")
        subject = str(record.get("subject") or "")
        curriculum = str(record.get("resolved_curriculum") or "shared")
        task_names = [str(v) for v in (record.get("task_name_candidates") or [])]
        action_tags = [str(v) for v in (record.get("action_tags") or [])]
        markers = record.get("marker_counts") or {}
        review_score = int(record.get("review_score") or record.get("evidence_score") or 0)
        evidence_text = str(record.get("evidence_text") or "")
        rows.append(
            (
                case_id_for(source_key, subject),
                curriculum,
                subject,
                str(record.get("curriculum_resolution_basis") or ""),
                str(source.get("school_name") or ""),
                region_from_saved_path(str(source.get("saved_path") or "")),
                "",
                json.dumps(record.get("academic_years") or [], ensure_ascii=False),
                json.dumps(record.get("grades") or [], ensure_ascii=False),
                json.dumps(record.get("semesters") or [], ensure_ascii=False),
                task_names[0] if task_names else UNCONFIRMED_TASK_NAME,
                json.dumps(task_names, ensure_ascii=False),
                json.dumps(action_tags, ensure_ascii=False),
                int(markers.get("rubric") or 0),
                int(markers.get("achievement_standard") or 0),
                int(markers.get("weight_or_points") or 0),
                int(markers.get("assessment_method") or 0),
                review_score,
                evidence_text[:600],
                "[]",
                "",
                "[]",
                "[]",
                "catalog_only",
                category_for(action_tags),
                review_score,
                json.dumps(action_tags, ensure_ascii=False),
                str(source.get("candidate_name") or ""),
                str(source.get("final_url") or source.get("source_url") or ""),
                str(record.get("sha256") or ""),
            )
        )
    connection.executemany(
        f"INSERT OR REPLACE INTO cases VALUES ({','.join('?' * 30)})", rows
    )
    print(f"cases={len(rows)}")


def load_subject_stats(
    connection: sqlite3.Connection, trends_json_path: Path, catalog_summary_path: Path
) -> None:
    trends = json.loads(trends_json_path.read_text(encoding="utf-8"))
    catalog_summary = json.loads(catalog_summary_path.read_text(encoding="utf-8"))
    by_subject_coverage = catalog_summary.get("by_subject") or {}

    stats_rows = []
    tag_rows = []
    for key, group in (trends.get("subject_groups") or {}).items():
        curriculum, subject = key.split(":", 1)
        coverage = by_subject_coverage.get(key) or {}
        schools = int(group.get("schools") or 0)
        stats_rows.append(
            (
                curriculum,
                subject,
                int(group.get("documents") or 0),
                schools,
                1 if schools < SMALL_SAMPLE_SCHOOL_THRESHOLD else 0,
                json.dumps(group.get("academic_years") or [], ensure_ascii=False),
                int(group.get("grade1_documents") or 0),
                int(group.get("grade2_documents") or 0),
                int(group.get("grade3_documents") or 0),
                int(group.get("rubric_documents") or 0),
                int(group.get("achievement_standard_documents") or 0),
                int(group.get("weight_or_points_documents") or 0),
                int(group.get("assessment_method_documents") or 0),
                group.get("median_review_score") if group.get("median_review_score") != "" else None,
                int(group.get("task_name_candidates") or 0),
                coverage.get("found"),
                coverage.get("found_curriculum_ambiguous"),
                coverage.get("not_found_in_collected_plans"),
                coverage.get("offering_unknown"),
                coverage.get("extraction_failed"),
            )
        )
        for tag, count in (group.get("action_tag_document_counts") or {}).items():
            school_count = (group.get("action_tag_school_counts") or {}).get(tag, 0)
            tag_rows.append((curriculum, subject, tag, int(count), int(school_count)))

    connection.executemany(
        f"INSERT OR REPLACE INTO subject_stats VALUES ({','.join('?' * 20)})", stats_rows
    )
    connection.executemany("INSERT INTO subject_action_tags VALUES (?,?,?,?,?)", tag_rows)
    print(f"subject_stats={len(stats_rows)} subject_action_tags={len(tag_rows)}")


def build(output_path: Path, catalog_path: Path, trends_json_path: Path, catalog_summary_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    connection = sqlite3.connect(output_path)
    try:
        connection.executescript(SCHEMA)
        load_cases(connection, catalog_path)
        load_subject_stats(connection, trends_json_path, catalog_summary_path)
        connection.commit()
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--trends-json", type=Path, required=True)
    parser.add_argument("--catalog-summary", type=Path, required=True)
    parser.add_argument("--catalog-db", type=Path, required=True)
    parser.add_argument("--detail-db", type=Path, required=True)
    args = parser.parse_args()

    build(args.catalog_db, args.catalog, args.trends_json, args.catalog_summary)
    build(args.detail_db, args.catalog, args.trends_json, args.catalog_summary)


if __name__ == "__main__":
    main()
