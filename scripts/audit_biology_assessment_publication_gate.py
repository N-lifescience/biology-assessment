"""Evidence gate for the items published as ``extraction_status='bounded'``.

``docs/SOURCE_POLICY.md`` ("공개 경계") only allows a source excerpt to be
published when its provenance is complete and its subject boundary is certain:
an unclear origin or interpretation must be sent to ``검토 필요`` instead. This
checks each bounded item for a source URL and SHA-256, a boundary lookup that
did not come back empty, and HTML that actually decompresses -- items failing
any of those go to the manual review queue rather than the site. It is the
provenance half of the release gate; ``package_biology_assessment_vercel_data``
covers the personal-data half.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import zlib
from collections import Counter
from pathlib import Path

from scripts.audit_biology_assessment_table_structure import boundary_grade

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = (
    PROJECT_ROOT / "data" / "publish" / "biology_assessment_catalog_detail.sqlite"
)


def gate_reasons(row: sqlite3.Row) -> list[str]:
    reasons = []
    if not (row["source_url"] or "").strip():
        reasons.append("missing_source_url")
    if not (row["source_sha256"] or "").strip():
        reasons.append("missing_source_sha256")
    grade = boundary_grade(row["boundary_status"])
    if grade != "trusted":
        reasons.append(f"boundary_{grade}")
    if row["source_html_zlib"] is None:
        reasons.append("missing_source_html")
    else:
        try:
            zlib.decompress(row["source_html_zlib"]).decode("utf-8")
        except (zlib.error, UnicodeDecodeError):
            reasons.append("undecodable_source_html")
    return reasons


def audit(database: Path) -> tuple[dict, list[dict]]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        status_counts = dict(
            connection.execute(
                "SELECT extraction_status, COUNT(*) FROM assessment_items "
                "GROUP BY 1 ORDER BY 2 DESC"
            )
        )
        rows = connection.execute(
            "SELECT i.item_id, i.case_id, i.source_html_zlib, c.source_url, "
            "c.source_sha256, s.boundary_status "
            "FROM assessment_items i "
            "JOIN cases c ON c.case_id = i.case_id "
            "JOIN case_detail_status s ON s.case_id = i.case_id "
            "WHERE i.extraction_status = 'bounded'"
        ).fetchall()
    finally:
        connection.close()

    queue = []
    reason_counts: Counter[str] = Counter()
    for row in rows:
        reasons = gate_reasons(row)
        if not reasons:
            continue
        reason_counts.update(reasons)
        queue.append(
            {
                "item_id": row["item_id"],
                "case_id": row["case_id"],
                "boundary_status": row["boundary_status"],
                "reason": "|".join(reasons),
            }
        )

    summary = {
        "extraction_status": status_counts,
        "bounded_checked": len(rows),
        "bounded_passed": len(rows) - len(queue),
        "bounded_queued": len(queue),
        "queued_reasons": dict(reason_counts.most_common()),
    }
    return summary, queue


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    arguments = parser.parse_args()
    if not arguments.database.is_file():
        raise SystemExit(f"publication gate: {arguments.database} is missing")

    summary, queue = audit(arguments.database)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    arguments.queue.parent.mkdir(parents=True, exist_ok=True)
    with arguments.queue.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["item_id", "case_id", "boundary_status", "reason"]
        )
        writer.writeheader()
        writer.writerows(queue)

    print(
        f"bounded={summary['bounded_checked']} passed={summary['bounded_passed']} "
        f"queued={summary['bounded_queued']} "
        + " ".join(f"{name}={value}" for name, value in summary["queued_reasons"].items())
    )
    # Provenance that is outright absent means an item was published with no
    # way back to its source -- a build failure, not a review item.
    fatal = {
        name: value
        for name, value in summary["queued_reasons"].items()
        if name.startswith(("missing_", "undecodable_"))
    }
    if fatal:
        raise SystemExit(
            "publication gate: bounded items without usable provenance: "
            + ", ".join(f"{name}={value}" for name, value in sorted(fatal.items()))
            + f" (queue in {arguments.queue})"
        )


if __name__ == "__main__":
    main()
