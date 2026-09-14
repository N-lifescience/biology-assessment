"""Queue the source rows whose text extraction came back short, failed or missing.

The initial extraction batches (``biology_subject_candidate_text_*.jsonl`` and
``biology_allplan_remaining_text_*.jsonl``) keep one row per source file with
an ``extract_status``.  Only ``ok`` rows carry usable full text; everything
else is retried once with the slower extractor before the evidence index is
built.  The queue keeps the whole ``source`` record so the retry writes rows
in the same shape as the initial batches, and the summary records why each
row was queued so the retry outcome can be compared row by row.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
from pathlib import Path

RETRY_STATUSES = ("short", "failed", "missing")


def source_key(record: dict) -> str:
    source = record.get("source") or {}
    return str(source.get("saved_path") or source.get("final_url") or "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--derived-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument(
        "--input-jsonl", type=Path, action="append", default=[],
        help="explicit source batch; repeatable (default: every batch in --derived-dir)",
    )
    args = parser.parse_args()

    inputs = [str(path) for path in args.input_jsonl]
    if not inputs:
        for pattern in (
            "biology_subject_candidate_text_[0-9]*.jsonl",
            "biology_allplan_remaining_text_[0-9]*.jsonl",
        ):
            inputs += sorted(glob.glob(str(args.derived_dir / pattern)))
    if not inputs:
        raise SystemExit("no extraction batches found")

    # Keep the best status seen per source: a row that later extracted ``ok``
    # in another batch must not be retried because an earlier batch failed.
    rank = {"ok": 3, "short": 2, "failed": 1, "missing": 0}
    best: dict[str, dict] = {}
    bad_json = 0
    total = 0
    for name in inputs:
        with Path(name).open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    bad_json += 1
                    continue
                total += 1
                key = source_key(record)
                if not key:
                    continue
                current = best.get(key)
                status = str(record.get("extract_status") or "missing")
                if current is None or rank.get(status, 0) > rank.get(
                    str(current.get("extract_status") or "missing"), 0
                ):
                    best[key] = record

    reasons: collections.Counter[str] = collections.Counter()
    queued = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        for key in sorted(best):
            record = best[key]
            status = str(record.get("extract_status") or "missing")
            if status not in RETRY_STATUSES:
                continue
            reasons[status] += 1
            queued += 1
            out.write(json.dumps(
                {"source": record.get("source") or {}, "sha256": record.get("sha256", ""),
                 "previous_extract_status": status,
                 "previous_char_count": int(record.get("char_count") or 0)},
                ensure_ascii=False, separators=(",", ":"),
            ) + "\n")

    summary = {
        "input_files": [Path(name).name for name in inputs],
        "rows_read": total,
        "bad_json_rows": bad_json,
        "unique_sources": len(best),
        "queued": queued,
        "queued_by_previous_status": dict(reasons),
    }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
