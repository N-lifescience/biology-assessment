"""Personal-data release gate for the HTML the API publishes verbatim.

``assessment_items.source_html_zlib``/``rubric_html_zlib`` are the
teacher-facing HTML excerpts served by ``/api/v1/assessment-items/{id}`` for
``extraction_status='bounded'`` rows (see ``AGENTS.md``/``SOURCE_POLICY.md``:
individual identifiers must never reach that public HTML). Run this before
any Vercel data package ships -- it raises rather than silently strips, so a
hit is a build failure a human has to look at, not a quiet redaction.
"""

from __future__ import annotations

import re
import sqlite3
import zlib
from pathlib import Path

# Korean mobile numbers ("010-1234-5678", "010 1234 5678", "01012345678") and
# resident registration numbers ("990101-1234567"). Narrow on purpose: this is
# a release gate, not a general PII classifier, so it should not misfire on
# ordinary scores/rubric text like "10점" or "[12생과01-01]".
PII_PATTERNS = [
    re.compile(r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}"),
    re.compile(r"\d{6}[-\s]?[1-4]\d{6}"),
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
