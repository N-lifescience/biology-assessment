"""Referential-integrity and completeness audit for the publish detail DB.

AGENTS.md requires the document count, school count, success/short/failure
counts, duplicate count and unverified count to be reconciled before any
extraction is called done. The detail DB has no foreign keys, so ``cases`` /
``case_detail_status`` (1:1), ``assessment_items`` /
``assessment_item_rankings`` (1:1) and ``assessment_items.case_id`` can drift
apart silently after a partial rebuild. Structural breakage raises; the
per-status and short-rubric counts are reported as statistics.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = (
    PROJECT_ROOT / "data" / "publish" / "biology_assessment_catalog_detail.sqlite"
)
# Anything below this is an empty or header-only rubric conversion, not a table.
SHORT_RUBRIC_CHARS = 200
PAIRS = (
    ("cases", "case_id", "case_detail_status", "case_id"),
    ("case_detail_status", "case_id", "cases", "case_id"),
    ("assessment_items", "item_id", "assessment_item_rankings", "item_id"),
    ("assessment_item_rankings", "item_id", "assessment_items", "item_id"),
    ("assessment_items", "case_id", "cases", "case_id"),
)


def _count(connection: sqlite3.Connection, sql: str) -> int:
    return connection.execute(sql).fetchone()[0]


def audit(database: Path) -> dict:
    connection = sqlite3.connect(database)
    try:
        counts = {
            table: _count(connection, f"SELECT COUNT(*) FROM {table}")
            for table in (
                "cases",
                "assessment_items",
                "case_detail_status",
                "assessment_item_rankings",
                "subject_stats",
                "subject_action_tags",
            )
        }
        orphans = {}
        for left, left_key, right, right_key in PAIRS:
            orphans[f"{left}.{left_key}->{right}.{right_key}"] = _count(
                connection,
                f"SELECT COUNT(*) FROM {left} l LEFT JOIN {right} r "
                f"ON r.{right_key} = l.{left_key} WHERE r.{right_key} IS NULL",
            )
        duplicates = {
            f"{table}.{key}": _count(
                connection,
                f"SELECT COUNT(*) FROM (SELECT {key} FROM {table} "
                f"GROUP BY {key} HAVING COUNT(*) > 1)",
            )
            for table, key in (("cases", "case_id"), ("assessment_items", "item_id"))
        }
        extraction_status = dict(
            connection.execute(
                "SELECT extraction_status, COUNT(*) FROM assessment_items "
                "GROUP BY 1 ORDER BY 2 DESC"
            )
        )
        rubric = {
            "empty": _count(
                connection,
                "SELECT COUNT(*) FROM assessment_items "
                "WHERE COALESCE(rubric_html_char_count, 0) = 0",
            ),
            f"under_{SHORT_RUBRIC_CHARS}": _count(
                connection,
                "SELECT COUNT(*) FROM assessment_items "
                f"WHERE COALESCE(rubric_html_char_count, 0) BETWEEN 1 AND {SHORT_RUBRIC_CHARS - 1}",
            ),
        }
        bounded_missing_html = dict(
            connection.execute(
                "SELECT 'source_html_zlib', COUNT(*) FROM assessment_items "
                "WHERE extraction_status = 'bounded' AND source_html_zlib IS NULL "
                "UNION ALL SELECT 'rubric_html_zlib', COUNT(*) FROM assessment_items "
                "WHERE extraction_status = 'bounded' AND rubric_html_zlib IS NULL"
            )
        )
        samples = {
            name: [
                row[0]
                for row in connection.execute(
                    f"SELECT {key} FROM {table} GROUP BY {key} HAVING COUNT(*) > 1 LIMIT 5"
                )
            ]
            for name, (table, key) in {
                "cases.case_id": ("cases", "case_id"),
                "assessment_items.item_id": ("assessment_items", "item_id"),
            }.items()
            if duplicates[name]
        }
    finally:
        connection.close()

    return {
        "counts": counts,
        "orphans": orphans,
        "duplicates": duplicates,
        "duplicate_samples": samples,
        "extraction_status": extraction_status,
        "rubric_html": rubric,
        "bounded_missing_html": bounded_missing_html,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if not arguments.database.is_file():
        raise SystemExit(f"detail db audit: {arguments.database} is missing")

    report = audit(arguments.database)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    counts = report["counts"]
    print(
        f"cases={counts['cases']} items={counts['assessment_items']} "
        + " ".join(f"{name}={value}" for name, value in report["extraction_status"].items())
        + f" empty_rubric={report['rubric_html']['empty']}"
    )
    broken = {
        **{f"orphan {name}": value for name, value in report["orphans"].items() if value},
        **{f"duplicate {name}": value for name, value in report["duplicates"].items() if value},
        **{
            f"bounded missing {name}": value
            for name, value in report["bounded_missing_html"].items()
            if value
        },
    }
    if broken:
        raise SystemExit(
            "detail db audit: "
            + ", ".join(f"{name}={value}" for name, value in sorted(broken.items()))
            + f" (details in {arguments.output})"
        )
    print("detail db audit ok: no orphans, duplicates, or missing bounded HTML")


if __name__ == "__main__":
    main()
