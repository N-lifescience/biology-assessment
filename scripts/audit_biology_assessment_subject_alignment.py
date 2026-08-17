"""Check that ``subject_stats``/``subject_action_tags`` still agree with ``cases``.

Both aggregate tables are loaded into the publish DB from the trends and
catalog-summary JSON rather than computed from the case rows themselves, so a
stale intermediate silently ships subject counts the cases no longer support.
Every field that is derivable from ``cases`` is recomputed here and compared;
the ``coverage_*`` columns are school-universe counts with no case-level
equivalent, so they are only checked against their own invariants.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = (
    PROJECT_ROOT / "data" / "publish" / "biology_assessment_catalog_detail.sqlite"
)
SMALL_SAMPLE_SCHOOL_THRESHOLD = 3
MARKER_FIELDS = {
    "rubric_documents": "rubric_marker_count",
    "achievement_standard_documents": "achievement_standard_marker_count",
    "weight_or_points_documents": "weight_or_points_marker_count",
    "assessment_method_documents": "assessment_method_marker_count",
}


def _json_list(value) -> list:
    return json.loads(value) if value else []


def _school_key(row: sqlite3.Row) -> tuple:
    # ``cases`` carries no school_code, so identity is the name plus its
    # administrative location -- plain names repeat across districts.
    return (row["school_name"], row["region"], row["district"])


def recompute_from_cases(connection: sqlite3.Connection) -> tuple[dict, dict]:
    groups: dict[tuple, list] = defaultdict(list)
    for row in connection.execute("SELECT * FROM cases"):
        groups[(row["curriculum"], row["subject"])].append(row)

    stats, tags = {}, {}
    for key, rows in groups.items():
        schools = {_school_key(row) for row in rows}
        grades = Counter(int(g) for row in rows for g in _json_list(row["grades_json"]))
        scores = [int(row["review_score"] or 0) for row in rows]
        tag_documents: Counter[str] = Counter()
        tag_schools: dict[str, set] = defaultdict(set)
        title_candidates = 0
        for row in rows:
            for tag in {str(value) for value in _json_list(row["action_tags_json"])}:
                tag_documents[tag] += 1
                if row["school_name"]:
                    tag_schools[tag].add(_school_key(row))
            title_candidates += sum(
                1 for name in _json_list(row["task_names_json"]) if str(name).strip()
            )
        stats[key] = {
            "documents": len(rows),
            "schools": len(schools),
            "small_sample": 1 if len(schools) < SMALL_SAMPLE_SCHOOL_THRESHOLD else 0,
            "academic_years": sorted(
                {int(y) for row in rows for y in _json_list(row["academic_years_json"])}
            ),
            "grade1_documents": grades.get(1, 0),
            "grade2_documents": grades.get(2, 0),
            "grade3_documents": grades.get(3, 0),
            "median_review_score": statistics.median(scores) if scores else None,
            "task_name_candidates": title_candidates,
            **{
                field: sum(1 for row in rows if int(row[column] or 0) > 0)
                for field, column in MARKER_FIELDS.items()
            },
        }
        tags[key] = {
            tag: (count, len(tag_schools[tag])) for tag, count in tag_documents.items()
        }
    return stats, tags


def compare(connection: sqlite3.Connection) -> tuple[list[str], set]:
    expected_stats, expected_tags = recompute_from_cases(connection)
    mismatches: list[str] = []
    bad_keys: set = set()

    def note(key, message: str) -> None:
        bad_keys.add(key)
        mismatches.append(f"{key}: {message}" if key else message)

    seen = set()
    coverage_totals = set()
    for row in connection.execute("SELECT * FROM subject_stats"):
        key = (row["curriculum"], row["subject"])
        seen.add(key)
        expected = expected_stats.get(key)
        if expected is None:
            note(key, "subject_stats row has no cases")
            continue
        stored = dict(expected)
        for field in expected:
            stored[field] = row[field] if field in row.keys() else None
        stored["academic_years"] = _json_list(row["academic_years_json"])
        for field, want in expected.items():
            got = stored[field]
            if field == "median_review_score":
                same = (want is None) == (got is None) and (
                    want is None or abs(float(got) - float(want)) < 1e-9
                )
            elif field == "task_name_candidates":
                # ``subject_stats`` counts only the names the upstream catalog
                # supplied, while ``cases`` also stores the derive_task_names
                # fallback, so cases can only ever hold more -- never fewer.
                same = got <= want
            else:
                same = got == want
            if not same:
                note(key, f"{field} stored={got!r} recomputed={want!r}")
        if row["coverage_found"] is not None and row["coverage_found"] != expected["schools"]:
            note(key, f"coverage_found={row['coverage_found']} != schools={expected['schools']}")
        coverage_totals.add(
            sum(
                row[field] or 0
                for field in (
                    "coverage_found",
                    "coverage_ambiguous",
                    "coverage_not_found",
                    "coverage_offering_unknown",
                    "coverage_extraction_failed",
                )
            )
        )

    for key in set(expected_stats) - seen:
        note(key, "cases exist with no subject_stats row")
    if len(coverage_totals) > 1:
        note(None, f"coverage_* totals disagree across subjects: {sorted(coverage_totals)}")

    stored_tags: dict[tuple, dict] = defaultdict(dict)
    for row in connection.execute("SELECT * FROM subject_action_tags"):
        stored_tags[(row["curriculum"], row["subject"])][row["tag"]] = (
            row["document_count"],
            row["school_count"],
        )
    for key, want in expected_tags.items():
        got = stored_tags.get(key, {})
        for tag in sorted(set(want) | set(got)):
            if want.get(tag) != got.get(tag):
                note(key, f"action tag {tag!r} stored={got.get(tag)} recomputed={want.get(tag)}")
    return mismatches, bad_keys


def main() -> None:
    if not DEFAULT_DATABASE.is_file():
        raise SystemExit(f"subject alignment audit: {DEFAULT_DATABASE} is missing")
    connection = sqlite3.connect(DEFAULT_DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        mismatches, bad_keys = compare(connection)
        subjects = connection.execute("SELECT COUNT(*) FROM subject_stats").fetchone()[0]
    finally:
        connection.close()

    for line in mismatches:
        print(f"mismatch: {line}")
    mismatched = len({key for key in bad_keys if key is not None})
    print(f"subjects={subjects} aligned={subjects - mismatched} mismatched={mismatched}")


if __name__ == "__main__":
    main()
