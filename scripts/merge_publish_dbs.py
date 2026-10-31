"""Merge a later disclosure round's publish DB into the current one.

학교알리미 4-가 is disclosed twice a year: 정시 1차 (April, 1학기분) and 정시 3차
(September, 2학기분).  Each round is run through the same pipeline into its own
publish DB; this script adds the later round's cases and detail rows to the
base DB and recomputes the per-subject statistics over the union.

* ``case_id`` is ``sha1(saved_path:subject)``, so cases from different rounds
  never collide by id.  A school that re-discloses the very same file in the
  later round would still be listed twice, so a case whose (document sha256,
  subject) is already in the base is skipped.
* ``subject_stats`` counts are recomputed from the merged ``cases`` table.  The
  coverage split keeps the base round's ``ambiguous``/``offering_unknown``/
  ``extraction_failed`` counts (school-level coverage of the later round is not
  in its DB), sets ``found`` to the schools that now have a case, and leaves the
  rest of the 2,370-school total as ``not_found``.
* ``subject_action_tags`` are recomputed from the merged cases.

Usage:
    python scripts/merge_publish_dbs.py --base data/publish/rebuild/1/biology_assessment_catalog_detail.sqlite \
        --addition data/publish/rebuild/2026_3/biology_assessment_catalog_detail.sqlite \
        --output data/publish/rebuild/merged/biology_assessment_catalog_detail.sqlite
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DETAIL_TABLES = ("assessment_items", "assessment_item_rankings", "assessment_item_axes")
SMALL_SAMPLE_SCHOOL_THRESHOLD = 30


def _columns(connection: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [row[1] for row in connection.execute(f"PRAGMA {schema}.table_info({table})")]


def merge(base: Path, addition: Path, output: Path) -> dict:
    if output.resolve() in (base.resolve(), addition.resolve()):
        raise SystemExit("--output must differ from both inputs")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base, output)
    connection = sqlite3.connect(output)
    connection.execute("ATTACH DATABASE ? AS addition", (str(addition),))
    try:
        before = connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        connection.execute(
            """
            CREATE TEMP TABLE new_cases AS
            SELECT a.case_id FROM addition.cases a
            WHERE NOT EXISTS (SELECT 1 FROM main.cases m WHERE m.case_id = a.case_id)
              AND NOT EXISTS (
                SELECT 1 FROM main.cases m
                WHERE m.source_sha256 = a.source_sha256 AND m.subject = a.subject
              )
            """
        )
        skipped = connection.execute(
            "SELECT COUNT(*) FROM addition.cases WHERE case_id NOT IN (SELECT case_id FROM new_cases)"
        ).fetchone()[0]
        columns = ", ".join(_columns(connection, "cases"))
        connection.execute(
            f"INSERT INTO main.cases ({columns}) SELECT {columns} FROM addition.cases "
            "WHERE case_id IN (SELECT case_id FROM new_cases)"
        )
        status_columns = ", ".join(_columns(connection, "case_detail_status"))
        connection.execute(
            f"INSERT INTO main.case_detail_status ({status_columns}) SELECT {status_columns} "
            "FROM addition.case_detail_status WHERE case_id IN (SELECT case_id FROM new_cases)"
        )
        item_columns = ", ".join(_columns(connection, "assessment_items"))
        connection.execute(
            f"INSERT INTO main.assessment_items ({item_columns}) SELECT {item_columns} "
            "FROM addition.assessment_items WHERE case_id IN (SELECT case_id FROM new_cases)"
        )
        for table in ("assessment_item_rankings", "assessment_item_axes"):
            table_columns = ", ".join(_columns(connection, table))
            connection.execute(
                f"INSERT INTO main.{table} ({table_columns}) SELECT {table_columns} FROM addition.{table} "
                "WHERE item_id IN (SELECT item_id FROM addition.assessment_items "
                "WHERE case_id IN (SELECT case_id FROM new_cases))"
            )
        added = connection.execute("SELECT COUNT(*) FROM new_cases").fetchone()[0]
        recompute_subject_stats(connection, {row[0] for row in connection.execute("SELECT case_id FROM new_cases")})
        connection.commit()
        connection.execute("DETACH DATABASE addition")
        connection.execute("VACUUM")
        after = connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    finally:
        connection.close()
    return {"base_cases": before, "added_cases": added, "skipped_same_document": skipped, "cases": after}


def recompute_subject_stats(connection: sqlite3.Connection, added_case_ids: set[str] | None = None) -> None:
    """Recount ``subject_stats``/``subject_action_tags`` over ``cases``.

    ``task_name_candidates`` is the number of task names the published cases
    hold.  It once carried over the catalogue's count from before item parsing,
    which grew stale (and larger than the cases) as the parser dropped names
    that were not tasks.
    """

    added_case_ids = added_case_ids or set()
    connection.row_factory = sqlite3.Row
    old = {
        (row["curriculum"], row["subject"]): dict(row)
        for row in connection.execute("SELECT * FROM main.subject_stats")
    }
    groups: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in connection.execute("SELECT * FROM main.cases"):
        groups[(row["curriculum"], row["subject"])].append(row)
    connection.row_factory = None

    stats_rows = []
    tag_rows = []
    for key, rows in sorted(groups.items()):
        curriculum, subject = key
        previous = old.get(key, {})
        schools = len({(row["school_name"], row["region"]) for row in rows})
        years = sorted({int(year) for row in rows for year in json.loads(row["academic_years_json"] or "[]")})
        grades = [set(json.loads(row["grades_json"] or "[]")) for row in rows]
        scores = [int(row["review_score"]) for row in rows]
        total = sum(
            int(previous.get(name) or 0)
            for name in ("coverage_found", "coverage_ambiguous", "coverage_not_found",
                         "coverage_offering_unknown", "coverage_extraction_failed")
        )
        ambiguous = previous.get("coverage_ambiguous")
        unknown = previous.get("coverage_offering_unknown")
        failed = previous.get("coverage_extraction_failed")
        not_found = (
            max(0, total - schools - int(ambiguous or 0) - int(unknown or 0) - int(failed or 0))
            if total else previous.get("coverage_not_found")
        )
        stats_rows.append((
            curriculum, subject, len(rows), schools,
            1 if schools < SMALL_SAMPLE_SCHOOL_THRESHOLD else 0,
            json.dumps(years, ensure_ascii=False),
            sum(1 in g for g in grades), sum(2 in g for g in grades), sum(3 in g for g in grades),
            sum(row["rubric_marker_count"] > 0 for row in rows),
            sum(row["achievement_standard_marker_count"] > 0 for row in rows),
            sum(row["weight_or_points_marker_count"] > 0 for row in rows),
            sum(row["assessment_method_marker_count"] > 0 for row in rows),
            statistics.median(scores) if scores else None,
            # Counted from the cases as published: the catalogue's own count
            # included names the detail parser no longer confirms.
            sum(
                1
                for row in rows
                for name in json.loads(row["task_names_json"] or "[]")
                if str(name).strip()
            ),
            schools if total else previous.get("coverage_found"),
            ambiguous, not_found, unknown, failed,
        ))
        documents: dict[str, int] = defaultdict(int)
        school_sets: dict[str, set] = defaultdict(set)
        for row in rows:
            for tag in json.loads(row["action_tags_json"] or "[]"):
                documents[tag] += 1
                school_sets[tag].add((row["school_name"], row["region"]))
        tag_rows.extend(
            (curriculum, subject, tag, count, len(school_sets[tag])) for tag, count in documents.items()
        )
    connection.execute("DELETE FROM main.subject_stats")
    connection.execute("DELETE FROM main.subject_action_tags")
    connection.executemany(f"INSERT INTO main.subject_stats VALUES ({','.join('?' * 20)})", stats_rows)
    connection.executemany("INSERT INTO main.subject_action_tags VALUES (?,?,?,?,?)", tag_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--addition", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(merge(args.base, args.addition, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
