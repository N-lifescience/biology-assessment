"""Flag cases whose evidence_excerpt carries another subject's achievement code.

``cases.evidence_excerpt``/``summary_overview`` come from a looser boundary
detector than ``assessment_items`` (which is already verified clean). When a
school's assessment-plan document lists several subjects, that detector can
grab a neighbouring subject's table instead of the requested one -- the
excerpt then quotes e.g. Korean-history achievement codes under a 통합과학1
case. ``segment_subject_alignment`` (already used and tested for the detail
parser) is the one existing, tested tool for this: it reads the bracketed
achievement-standard codes in a text segment and checks them against the
subject's expected code prefix. This script runs that check once per case and
stores the verdict in ``cases.subject_alignment`` so the read-only API can
suppress excerpts it did not write for.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from scripts.biology_assessment_detail_parser import segment_subject_alignment


def ensure_column(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(cases)")}
    if "subject_alignment" not in columns:
        connection.execute("ALTER TABLE cases ADD COLUMN subject_alignment TEXT")


def annotate(database: Path) -> dict[str, int]:
    connection = sqlite3.connect(database)
    counts = {"expected": 0, "other": 0, "unknown": 0}
    try:
        ensure_column(connection)
        rows = connection.execute("SELECT case_id, subject, evidence_excerpt FROM cases").fetchall()
        for case_id, subject, evidence_excerpt in rows:
            verdict = segment_subject_alignment(evidence_excerpt or "", subject or "")
            counts[verdict] += 1
            connection.execute(
                "UPDATE cases SET subject_alignment = ? WHERE case_id = ?", (verdict, case_id)
            )
        connection.commit()
    finally:
        connection.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    counts = annotate(args.database)
    print(f"subject_alignment: expected={counts['expected']} other={counts['other']} unknown={counts['unknown']}")


if __name__ == "__main__":
    main()
