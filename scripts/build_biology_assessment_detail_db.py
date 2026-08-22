"""Schema for the detail-side tables that ``build_biology_assessment_publish_db``
writes into the publish databases: ``case_detail_status``, ``assessment_items``,
``assessment_item_rankings``.

Kept as its own module (rather than importing the string out of
``build_biology_assessment_publish_db.py``) so tests can build a scratch
detail database without pulling in the full publish pipeline. Column shapes
must stay identical to ``build_biology_assessment_publish_db.SCHEMA`` --
that script is the one that actually populates these tables from real
reprocessing-pipeline output.
"""

from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS case_detail_status (
    case_id TEXT PRIMARY KEY,
    source_format TEXT NOT NULL,
    boundary_status TEXT NOT NULL,
    source_section_char_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS assessment_items (
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

CREATE TABLE IF NOT EXISTS assessment_item_rankings (
    item_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    topic TEXT NOT NULL,
    category_ambiguous INTEGER NOT NULL,
    priority_score INTEGER NOT NULL,
    priority_signals_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assessment_item_axes (
    item_id TEXT NOT NULL,
    axis TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (item_id, axis, value)
) WITHOUT ROWID;
"""
