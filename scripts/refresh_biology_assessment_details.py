"""Re-parse every case's source document into the detail tables of a publish DB.

The full pipeline (``run_final_biology_assessment_pipeline.py``) needs the
Windows-only extraction stage.  When only the parser changed -- the table
renderer in ``biology_assessment_detail_parser`` -- the published catalogue can
be refreshed in place: keep ``cases`` (and therefore every ``case_id`` and
public URL), rebuild ``assessment_items``/``assessment_item_rankings``/
``assessment_item_axes``/``case_detail_status`` from the archived full text,
and let ``refresh_cases_from_items`` re-derive the case-level fields exactly
as a fresh build would.

The catalogue JSONL the builder expects is reconstructed from ``cases`` plus
the source manifest: ``case_id`` is ``sha1(saved_path:subject)``, so the
manifest row whose ``saved_path`` reproduces the stored id is the case's
source.  Any case that cannot be reproduced aborts the run rather than being
silently dropped.

Usage:
    python scripts/refresh_biology_assessment_details.py \
        --database data/publish/biology_assessment_catalog_detail.sqlite \
        --output data/publish/rebuild/biology_assessment_catalog_detail.sqlite \
        --manifest <source manifest csv> --evidence-source <full-text jsonl>
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_biology_assessment_publish_db import (  # noqa: E402
    case_id_for,
    load_case_details,
)

DETAIL_TABLES = (
    "assessment_items",
    "assessment_item_rankings",
    "assessment_item_axes",
    "case_detail_status",
)


def manifest_rows(manifest_path: Path) -> dict[tuple[str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (str(row.get("school_name") or ""), str(row.get("candidate_name") or ""))
            grouped.setdefault(key, []).append(row)
    return grouped


def catalog_records(connection: sqlite3.Connection, manifest_path: Path) -> list[dict]:
    grouped = manifest_rows(manifest_path)
    records: list[dict] = []
    unresolved: list[str] = []
    rows = connection.execute(
        "SELECT case_id, subject, school_name, candidate_name, source_sha256, review_score "
        "FROM cases"
    ).fetchall()
    for case_id, subject, school_name, candidate_name, sha256, review_score in rows:
        matches = [
            row
            for row in grouped.get((str(school_name), str(candidate_name)), [])
            if case_id_for(str(row.get("saved_path") or ""), str(subject)) == case_id
        ]
        if len(matches) != 1:
            unresolved.append(str(case_id))
            continue
        source = dict(matches[0])
        records.append(
            {
                "source": source,
                "subject": subject,
                "sha256": sha256,
                "review_score": review_score,
            }
        )
    if unresolved:
        raise SystemExit(
            f"{len(unresolved)} cases could not be matched to a manifest row: "
            f"{unresolved[:5]}"
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence-source", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.database.resolve():
        raise SystemExit("--output must differ from --database")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.database, args.output)
    connection = sqlite3.connect(args.output)
    try:
        records = catalog_records(connection, args.manifest)
        before = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in DETAIL_TABLES
        }
        for table in DETAIL_TABLES:
            connection.execute(f"DELETE FROM {table}")
        # A fresh build starts every case at the catalogue's own honest value
        # and lets the parser upgrade it; mirror that so a case whose parse no
        # longer bounds does not keep a stale ``source_detail``.
        connection.execute("UPDATE cases SET title_basis = 'catalog_only'")
        connection.commit()

        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".jsonl", delete=False, dir=args.output.parent
        ) as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            catalog_path = Path(handle.name)
        try:
            load_case_details(connection, catalog_path, args.evidence_source)
        finally:
            catalog_path.unlink(missing_ok=True)
        connection.commit()
        connection.execute("VACUUM")
        after = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in DETAIL_TABLES
        }
        summary = {"cases": len(records), "before": before, "after": after}
        print(json.dumps(summary, ensure_ascii=False))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
