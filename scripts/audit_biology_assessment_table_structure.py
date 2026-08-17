"""Grade how well each source document's assessment table was located.

``case_detail_status.boundary_status`` records two independent lookups --
whether the subject heading was found and whether the assessment-table anchor
was found -- and each half can fail on its own. Failures are not spread evenly
across ``source_format``: a scanned PDF and a ZIP member do not degrade the
same way, and only the format x grade cross-tab shows which converter is
losing structure. Cases that failed both lookups, or whose extracted section is
too short to hold a rubric table at all, land in the review queue.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = (
    PROJECT_ROOT / "data" / "publish" / "biology_assessment_catalog_detail.sqlite"
)
# A 수행평가 section shorter than this cannot hold a rubric table plus its
# headings, so the boundary was found in name only.
SHORT_SECTION_CHARS = 500
GRADES = {0: "trusted", 1: "partial", 2: "untrusted"}


def boundary_grade(boundary_status: str) -> str:
    """``trusted``/``partial``/``untrusted`` by how many lookups came back empty."""
    parts = (boundary_status or "").split(":")
    return GRADES[min(2, sum(1 for part in parts if part.endswith("_not_found")))]


def audit(database: Path) -> tuple[dict, list[dict]]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT case_id, source_format, boundary_status, source_section_char_count "
            "FROM case_detail_status"
        ).fetchall()
    finally:
        connection.close()

    cross_tab: dict[str, Counter] = {}
    grade_totals: Counter[str] = Counter()
    queue = []
    for row in rows:
        grade = boundary_grade(row["boundary_status"])
        grade_totals[grade] += 1
        cross_tab.setdefault(row["source_format"], Counter())[grade] += 1
        reasons = []
        if grade == "untrusted":
            reasons.append("boundary_untrusted")
        if (row["source_section_char_count"] or 0) < SHORT_SECTION_CHARS:
            reasons.append("section_too_short")
        if reasons:
            queue.append(
                {
                    "case_id": row["case_id"],
                    "source_format": row["source_format"],
                    "boundary_status": row["boundary_status"],
                    "source_section_char_count": row["source_section_char_count"],
                    "reason": "|".join(reasons),
                }
            )

    summary = {
        "cases": len(rows),
        "short_section_chars": SHORT_SECTION_CHARS,
        "grades": dict(grade_totals),
        "by_source_format": {
            fmt: dict(counts) for fmt, counts in sorted(cross_tab.items())
        },
        "boundary_status": dict(
            Counter(row["boundary_status"] for row in rows).most_common()
        ),
        "queued": len(queue),
    }
    return summary, queue


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    arguments = parser.parse_args()
    if not arguments.database.is_file():
        raise SystemExit(f"table structure audit: {arguments.database} is missing")

    summary, queue = audit(arguments.database)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    arguments.queue.parent.mkdir(parents=True, exist_ok=True)
    with arguments.queue.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "source_format",
                "boundary_status",
                "source_section_char_count",
                "reason",
            ],
        )
        writer.writeheader()
        writer.writerows(queue)

    grades = summary["grades"]
    print(
        f"cases={summary['cases']} trusted={grades.get('trusted', 0)} "
        f"partial={grades.get('partial', 0)} untrusted={grades.get('untrusted', 0)} "
        f"queued={summary['queued']}"
    )


if __name__ == "__main__":
    main()
