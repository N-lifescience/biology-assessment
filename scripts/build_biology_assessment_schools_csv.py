"""Derive a minimal schools roster CSV from the source manifest.

``build_school_subject_assessment_catalog.py`` requires a ``--schools`` CSV
with at least ``school_code``/``school_name`` columns. No such roster was
handed off, so this rebuilds the unique school list (and region, parsed out
of the raw storage path since the manifest's own ``region`` column is
always empty) from ``data/source/source_manifest.csv``.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def region_from_saved_path(saved_path: str) -> str:
    parts = saved_path.split("/")
    if len(parts) >= 5 and parts[0] == "data" and parts[2] == "schoolinfo":
        return parts[4]
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    schools: dict[str, dict[str, str]] = {}
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("school_code") or "")
            if not code or code in schools:
                continue
            schools[code] = {
                "school_code": code,
                "school_name": row.get("school_name", ""),
                "region_sido": region_from_saved_path(row.get("saved_path", "")),
            }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["school_code", "school_name", "region_sido"])
        writer.writeheader()
        writer.writerows(schools.values())
    print(f"schools={len(schools)}")


if __name__ == "__main__":
    main()
