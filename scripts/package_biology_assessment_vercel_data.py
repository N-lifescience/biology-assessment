"""Personal-data release gate for the HTML the API publishes verbatim.

``assessment_items.source_html_zlib``/``rubric_html_zlib`` are the
teacher-facing HTML excerpts served by ``/api/v1/assessment-items/{id}`` for
``extraction_status='bounded'`` rows (see ``AGENTS.md``/``SOURCE_POLICY.md``:
individual identifiers must never reach that public HTML). Run this before
any Vercel data package ships -- it raises rather than silently strips, so a
hit is a build failure a human has to look at, not a quiet redaction.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import zlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = (
    PROJECT_ROOT / "data" / "publish" / "biology_assessment_catalog_detail.sqlite"
)

# Korean mobile numbers ("010-1234-5678", "010 1234 5678", "01012345678") and
# resident registration numbers ("990101-1234567"). Narrow on purpose: this is
# a release gate, not a general PII classifier, so it should not misfire on
# ordinary scores/rubric text like "10점" or "[12생과01-01]".
# The digit boundaries are load-bearing. Table converters glue a whole rubric
# score column into one cell without separators ("3028272625242322212019181716151413"
# is 30/28/27/..., "50454035302520" is 50/45/40/...), and an unanchored match
# happily finds an 11-digit "phone number" inside that run. A real phone number
# or RRN is always bounded by non-digits, so requiring that keeps the gate strict
# for actual identifiers while honouring "should not misfire on ordinary scores".
#
# The resident registration number's leading six digits are a real YYMMDD birth
# date, so the month/day are constrained. Requiring that is not a loosening: it
# rejects "2018161412108" (a 20/18/16/14/12/10/8 score column -- month "18" does
# not exist) while every genuine RRN still matches.
PII_PATTERNS = [
    re.compile(r"(?<!\d)01[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"),
    re.compile(
        r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[-\s]?[1-4]\d{6}(?!\d)"
    ),
]


def assert_bounded_html_privacy(database: Path) -> None:
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT item_id, source_html_zlib FROM assessment_items "
            "WHERE extraction_status = 'bounded' AND source_html_zlib IS NOT NULL"
        ).fetchall()
    finally:
        connection.close()

    hits = []
    for item_id, blob in rows:
        html = zlib.decompress(blob).decode("utf-8")
        if any(pattern.search(html) for pattern in PII_PATTERNS):
            hits.append(item_id)

    if hits:
        raise RuntimeError(
            f"personal-data release gate: {len(hits)} bounded item(s) contain a "
            f"phone number or resident registration number pattern: {hits[:5]}"
        )
    print(f"personal-data release gate ok: {len(rows)} bounded item(s) checked")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    arguments = parser.parse_args()
    if not arguments.database.is_file():
        raise SystemExit(
            f"personal-data release gate: {arguments.database} is missing. "
            "Build the publish pipeline first; refusing to pass without checking anything."
        )
    assert_bounded_html_privacy(arguments.database)


if __name__ == "__main__":
    main()
