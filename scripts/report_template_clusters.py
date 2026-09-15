"""Summarise template clusters (from profile_source_templates) with before/after parser results.

Joins ``template_signatures.jsonl`` with an ``evaluate_parser_sample`` output
and prints, per structural cluster, the case count, dominant regions and the
share of cases without a bounded item before and after the parser change.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def cluster_key(row: dict) -> str:
    labels: set[str] = set()
    for table in row["tables"]:
        labels.update(table["first_column"])
        labels.update(table["header"])
    labels -= {"TXT", "NUM", "_"}
    return (row["block_status"] or "?") + " | " + ",".join(sorted(labels))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--signatures", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--by-region", action="store_true")
    args = parser.parse_args()
    evaluation = {}
    with args.evaluation.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            evaluation[row["case_id"]] = row
    clusters: dict[str, list[dict]] = collections.defaultdict(list)
    regions: dict[str, list[dict]] = collections.defaultdict(list)
    with args.signatures.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            result = evaluation.get(row["case_id"])
            if not result:
                continue
            clusters[cluster_key(row)].append(result)
            regions[row["region"]].append(result)

    def line(name: str, rows: list[dict]) -> str:
        n = len(rows)
        before = sum(1 for r in rows if r["old_bounded"] == 0)
        after = sum(1 for r in rows if r["new_bounded"] == 0)
        top = collections.Counter(r["region"][:2] for r in rows).most_common(3)
        return (f"n={n:5d} 실패 {100*before/n:4.0f}% -> {100*after/n:4.0f}%  "
                f"{' '.join(f'{k}{v}' for k, v in top)}  :: {name[:100]}")

    groups = regions if args.by_region else clusters
    for name, rows in sorted(groups.items(), key=lambda kv: -len(kv[1]))[: args.top]:
        print(line(name, rows))


if __name__ == "__main__":
    main()
