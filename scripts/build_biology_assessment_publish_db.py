"""Build the read-only SQLite publish databases the API serves.

Schema and query shapes are dictated entirely by
``services/biology-assessment-api/app/repository.py`` (read first, not
guessed). ``cases``/``subject_stats``/``subject_action_tags`` are populated
from real reprocessing-pipeline output. When ``--evidence-source`` is given,
``assessment_items``/``assessment_item_rankings``/``case_detail_status`` are
also populated by parsing each case's full source document with
``biology_assessment_detail_parser.parse_assessment_section``; only cases
where the parser finds a confident, source-bounded first item get
``cases.title_basis`` upgraded to ``"source_detail"``
(``"source_detail_bundle_review"`` for a found-but-unbounded section).
Everything else keeps the honest ``"catalog_only"`` value so confirmed-only
endpoints (``/api/v1/cases``, ``/api/v1/cases/{id}``) never fabricate a
title. ``/api/v1/subjects`` and ``/api/v1/trends`` are unaffected either way.

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
import zlib
from html.parser import HTMLParser
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
    summary_overview TEXT NOT NULL,
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


class _HTMLTableExtractor(HTMLParser):
    """Collect every ``<table>``'s cell text, including nested tables."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._tables: list[list[list[str]]] = []
        self._rows: list[list[str]] = []
        self._cells: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._tables.append([])
        elif tag == "tr" and self._tables:
            self._rows.append([])
        elif tag in ("td", "th") and self._rows:
            self._cells.append([])
        elif tag == "br" and self._cells:
            self._cells[-1].append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br" and self._cells:
            self._cells[-1].append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("td", "th") and self._cells:
            text = "".join(self._cells.pop()).strip()
            if self._rows:
                self._rows[-1].append(text)
        elif tag == "tr" and self._rows:
            row = self._rows.pop()
            if self._tables:
                self._tables[-1].append(row)
        elif tag == "table" and self._tables:
            self.tables.append(self._tables.pop())

    def handle_data(self, data: str) -> None:
        if self._cells:
            self._cells[-1].append(data)


def html_tables(value: str) -> list[list[list[str]]]:
    """Parse HTML fragments into tables of rows of cell text.

    Uses the stdlib ``html.parser`` (already a dependency here via
    ``_SafeTableParser`` in ``biology_assessment_detail_parser.py``) rather
    than adding an HTML-parsing library for what is a small, self-contained
    extraction.
    """

    extractor = _HTMLTableExtractor()
    extractor.feed(value)
    extractor.close()
    return extractor.tables


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


def load_school_districts(school_district_path: Path | None) -> dict[str, str]:
    """Map ``school_code`` to 시군구, from a NEIS 학교기본정보 export.

    Optional: older/merged-office school codes (see the 2026 전남·광주 교육청
    통합) have no current NEIS record, so lookups for those simply miss and
    the case's ``district`` stays empty rather than guessed.
    """

    if school_district_path is None:
        return {}
    districts: dict[str, str] = {}
    with school_district_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("school_code") or "")
            district = str(row.get("region_sgg") or "")
            if code and district:
                districts[code] = district
    return districts


def load_cases(
    connection: sqlite3.Connection,
    catalog_path: Path,
    school_districts: dict[str, str] | None = None,
) -> None:
    school_districts = school_districts or {}
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
                school_districts.get(str(source.get("school_code") or ""), ""),
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
        f"INSERT OR REPLACE INTO cases VALUES ({','.join('?' * 31)})", rows
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


def load_source_texts(evidence_source_path: Path, wanted_shas: set[str]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for record in read_jsonl(evidence_source_path):
        sha = str(record.get("sha256") or "")
        if sha in wanted_shas and sha not in texts:
            texts[sha] = str(record.get("text") or "")
    return texts


def item_category_and_signals(item) -> tuple[str, list[str]]:
    """Mirror ``category_for`` at item granularity using the item's own text.

    Cases classify by their pre-extracted ``action_tags``; individual items
    have no such pre-extracted tags, so this scans the item's own title/
    overview/method text for the same marker words instead.
    """

    haystack = f"{item.title} {item.overview} {item.method}"
    tags = [tag for tag, _ in CATEGORY_TAG_ORDER if tag in haystack]
    return category_for(tags), tags


def source_format_for(saved_path: str) -> str:
    suffix = Path(saved_path).suffix.lstrip(".").lower()
    return suffix or "unknown"


def load_case_details(
    connection: sqlite3.Connection, catalog_path: Path, evidence_source_path: Path
) -> tuple[int, int, int]:
    """Parse each case's source document into assessment items.

    Populates ``assessment_items``/``assessment_item_rankings``/
    ``case_detail_status`` and upgrades ``cases.title_basis`` from
    ``catalog_only`` only where the parser found a confident section. A
    parse failure or an unbounded result leaves the case's honest
    ``catalog_only`` value in place.
    """

    from scripts.biology_assessment_detail_parser import parse_assessment_section

    case_rows = []
    for record in read_jsonl(catalog_path):
        source = record.get("source") or {}
        source_key = str(source.get("saved_path") or source.get("final_url") or "")
        subject = str(record.get("subject") or "")
        case_rows.append(
            (
                case_id_for(source_key, subject),
                subject,
                str(record.get("sha256") or ""),
                int(record.get("review_score") or record.get("evidence_score") or 0),
                source_format_for(str(source.get("saved_path") or "")),
            )
        )
    wanted_shas = {sha for _, _, sha, _, _ in case_rows if sha}
    texts = load_source_texts(evidence_source_path, wanted_shas)

    item_rows = []
    ranking_rows = []
    status_rows = []
    title_basis_updates = []
    parsed_cases = 0
    confirmed_cases = 0
    for case_id, subject, sha, review_score, source_format in case_rows:
        text = texts.get(sha)
        if not text:
            continue
        try:
            section = parse_assessment_section(text, subject)
        except Exception:
            continue
        if not section.items:
            continue
        parsed_cases += 1
        status_rows.append(
            (case_id, source_format, section.boundary_status, len(section.source_markdown))
        )
        first_confirmed = False
        for order, item in enumerate(section.items, 1):
            item_id = f"{case_id}-{order}"
            item_rows.append(
                (
                    item_id,
                    case_id,
                    order,
                    item.title,
                    item.title_raw,
                    item.title_basis,
                    item.extraction_status,
                    item.overview,
                    item.method,
                    item.timing,
                    item.score,
                    item.weight,
                    json.dumps(list(item.standards), ensure_ascii=False),
                    len(item.rubric_html),
                    zlib.compress(item.source_html.encode("utf-8")),
                    zlib.compress(item.rubric_html.encode("utf-8")),
                )
            )
            category, signals = item_category_and_signals(item)
            ranking_rows.append(
                (item_id, category, review_score, json.dumps(signals, ensure_ascii=False))
            )
            if order == 1 and item.extraction_status == "bounded" and item.title_basis in (
                "table",
                "heading",
            ):
                first_confirmed = True
        title_basis_updates.append(
            ("source_detail" if first_confirmed else "source_detail_bundle_review", case_id)
        )
        confirmed_cases += 1 if first_confirmed else 0

    connection.executemany(
        f"INSERT INTO assessment_items VALUES ({','.join('?' * 16)})", item_rows
    )
    connection.executemany(
        "INSERT INTO assessment_item_rankings VALUES (?,?,?,?)", ranking_rows
    )
    connection.executemany("INSERT INTO case_detail_status VALUES (?,?,?,?)", status_rows)
    connection.executemany(
        "UPDATE cases SET title_basis = ? WHERE case_id = ?", title_basis_updates
    )
    print(
        f"assessment_items={len(item_rows)} parsed_cases={parsed_cases} "
        f"confirmed_cases={confirmed_cases}"
    )
    return parsed_cases, confirmed_cases, len(item_rows)


def build(
    output_path: Path,
    catalog_path: Path,
    trends_json_path: Path,
    catalog_summary_path: Path,
    evidence_source_path: Path | None = None,
    school_district_path: Path | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    connection = sqlite3.connect(output_path)
    try:
        connection.executescript(SCHEMA)
        load_cases(connection, catalog_path, load_school_districts(school_district_path))
        load_subject_stats(connection, trends_json_path, catalog_summary_path)
        if evidence_source_path is not None:
            load_case_details(connection, catalog_path, evidence_source_path)
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
    parser.add_argument("--evidence-source", type=Path, default=None)
    parser.add_argument("--school-district", type=Path, default=None)
    args = parser.parse_args()

    build(
        args.catalog_db,
        args.catalog,
        args.trends_json,
        args.catalog_summary,
        args.evidence_source,
        args.school_district,
    )
    build(
        args.detail_db,
        args.catalog,
        args.trends_json,
        args.catalog_summary,
        args.evidence_source,
        args.school_district,
    )


if __name__ == "__main__":
    main()
