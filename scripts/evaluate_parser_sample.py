"""Re-parse published cases with the current parser and compare against the publish DB.

Reads full text through the offset index, so a full pass over all 7,211 cases
is parser-bound only.  Reports, per region and overall, how many cases gain or
lose bounded items versus what is published, and writes one JSON row per case
so regressions can be inspected individually.

Usage:
  python scripts/evaluate_parser_sample.py --output data/derived/parser_eval.jsonl [--limit 500] [--region 부산광역시]
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.biology_assessment_detail_parser import parse_assessment_section  # noqa: E402
from scripts.case_text import DEFAULT_DB, text_for_sha  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--region", default=None)
    parser.add_argument("--only-failing", action="store_true")
    args = parser.parse_args()

    connection = sqlite3.connect(args.database)
    query = (
        "SELECT c.case_id, c.subject, c.region, c.school_name, c.source_sha256, "
        "COALESCE(SUM(i.extraction_status='bounded'), 0), COUNT(i.item_id) "
        "FROM cases c LEFT JOIN assessment_items i ON i.case_id = c.case_id "
        + ("WHERE c.region = ? " if args.region else "")
        + "GROUP BY c.case_id ORDER BY c.case_id"
    )
    rows = connection.execute(query, (args.region,) if args.region else ()).fetchall()
    connection.close()
    if args.only_failing:
        rows = [row for row in rows if row[5] == 0]
    if args.limit:
        rows = rows[: args.limit]

    totals = collections.Counter()
    by_region: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        for index, (case_id, subject, region, school, sha, old_bounded, old_total) in enumerate(rows, 1):
            text = text_for_sha(sha)
            try:
                section = parse_assessment_section(text, subject) if text else None
                items = section.items if section else []
                error = ""
            except Exception as exc:  # noqa: BLE001
                items, error = [], f"{type(exc).__name__}: {exc}"[:200]
            new_bounded = sum(1 for item in items if item.extraction_status == "bounded")
            change = "gain" if new_bounded > old_bounded else "loss" if new_bounded < old_bounded else "same"
            for counter in (totals, by_region[region]):
                counter["cases"] += 1
                counter[change] += 1
                counter["old_failing"] += old_bounded == 0
                counter["new_failing"] += new_bounded == 0
            out.write(json.dumps({
                "case_id": case_id, "subject": subject, "region": region, "school": school,
                "old_bounded": old_bounded, "old_total": old_total,
                "new_bounded": new_bounded, "new_total": len(items),
                "new_titles": [item.title[:40] for item in items if item.extraction_status == "bounded"][:8],
                "boundary": section.boundary_status if section else "", "error": error,
            }, ensure_ascii=False) + "\n")
            if index % 250 == 0:
                print(f"progress {index}/{len(rows)} {dict(totals)}", flush=True)
    print(json.dumps({"totals": dict(totals)}, ensure_ascii=False))
    for region, counter in sorted(by_region.items(), key=lambda kv: -kv[1]["cases"]):
        n = counter["cases"]
        print(f"{region:10s} n={n:5d} failing {counter['old_failing']:4d} -> {counter['new_failing']:4d}  "
              f"gain={counter['gain']} loss={counter['loss']}")


if __name__ == "__main__":
    main()
