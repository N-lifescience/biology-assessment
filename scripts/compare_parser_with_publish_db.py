"""Re-read every case with the current parser and compare it with a publish DB.

A parser change is judged case by case: which cases stop being confirmed
(``lost``), which become confirmed (``gained``), and how the confirmed titles
change.  Reading the kordoc full text through a sha256 offset index makes the
whole corpus (9,346 cases) take a few minutes on 8 processes.

Build the offset indexes once per evidence source:

    python scripts/index_evidence_source.py \
        --evidence-source data/derived/kordoc_evidence_source_2026_1.jsonl \
        --output data/derived/kordoc_offsets_2026_1.json

Usage:
    python scripts/compare_parser_with_publish_db.py \
        --source data/derived/kordoc_offsets_2026_1.json=\
data/derived/kordoc_evidence_source_2026_1.jsonl \
        --source data/derived/kordoc_offsets_2026_3.json=\
data/derived/2026_3/kordoc_evidence_source.jsonl \
        --output data/derived/parser_compare
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.biology_assessment_detail_parser import parse_assessment_section  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data/publish/biology_assessment_catalog_detail.sqlite"
EXAM_RE = re.compile(r"중간\s*고사|기말\s*고사|지필")
QUESTION_RE = re.compile(r"는가\s*\??$")
# A question naming the task asks with a question word ("어떻게 … 유지하는가?").
POINTS_RE = re.compile(r"[(（]\s*\d+\s*점\s*[)）]|\d+\s*점\s*$")
QUESTION_WORD_RE = re.compile(r"어떻게|어디|무엇|왜|누구|언제|얼마|어느|어떤|무슨|몇")
QUESTION_GRADING_RE = re.compile(r"수\s*있는가|[였었했]는가|옳게|바르게|정확하게|명확하게|적절하게")
_SOURCES: list[tuple[dict[str, int], Path]] = []


def _init(sources: list[tuple[str, str]]) -> None:
    for index_path, source_path in sources:
        offsets = json.loads(Path(index_path).read_text(encoding="utf-8"))
        _SOURCES.append((offsets, Path(source_path)))


def _text_for(sha: str) -> str:
    for offsets, source in _SOURCES:
        if sha in offsets:
            with source.open("rb") as handle:
                handle.seek(offsets[sha])
                return str(json.loads(handle.readline()).get("text") or "")
    return ""


def _parse(row: tuple[str, str, str]) -> dict:
    case_id, subject, sha = row
    try:
        section = parse_assessment_section(_text_for(sha), subject)
    except Exception as error:  # noqa: BLE001 -- one bad case must not stop the run
        return {"case_id": case_id, "error": repr(error)[:200]}
    return {
        "case_id": case_id,
        "new": [item.title for item in section.items if item.extraction_status == "bounded"],
        "new_status": section.boundary_status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="<offset index json>=<evidence source jsonl>; repeat per source",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    sources = [tuple(value.split("=", 1)) for value in args.source]

    connection = sqlite3.connect(args.database)
    rows = connection.execute("SELECT case_id, subject, source_sha256 FROM cases").fetchall()
    old: dict[str, list[str]] = {}
    old_status = dict(connection.execute("SELECT case_id, boundary_status FROM case_detail_status"))
    for case_id, title in connection.execute(
        "SELECT case_id, title FROM assessment_items WHERE extraction_status='bounded' "
        "ORDER BY case_id, item_order"
    ):
        old.setdefault(case_id, []).append(title)
    connection.close()

    args.output.mkdir(parents=True, exist_ok=True)
    stats: Counter[str] = Counter()
    with (
        mp.Pool(args.workers, initializer=_init, initargs=(sources,)) as pool,
        (args.output / "cases.jsonl").open("w", encoding="utf-8") as handle,
    ):
        for result in pool.imap_unordered(_parse, rows, chunksize=20):
            if "error" in result:
                stats["errors"] += 1
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                continue
            before = old.get(result["case_id"], [])
            after = result["new"]
            result["old"] = before
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            stats["cases"] += 1
            stats["confirmed_old"] += bool(before)
            stats["confirmed_new"] += bool(after)
            stats["gained_cases"] += bool(after) and not before
            stats["lost_cases"] += bool(before) and not after
            stats["items_old"] += len(before)
            stats["items_new"] += len(after)
            stats["changed_cases"] += before != after
            # Bounded items the publication gate holds back: the case boundary
            # still has a lookup that came back empty.
            stats["gate_partial_old"] += len(before) if "not_found" in old_status.get(
                result["case_id"], ""
            ) else 0
            stats["gate_partial_new"] += len(after) if "not_found" in result["new_status"] else 0
            for label, titles in (("old", before), ("new", after)):
                stats[f"long45_{label}"] += sum(len(title) >= 45 for title in titles)
                stats[f"exam_{label}"] += sum(bool(EXAM_RE.search(title)) for title in titles)
                stats[f"question_{label}"] += sum(
                    bool(QUESTION_RE.search(title))
                    and (
                        bool(QUESTION_GRADING_RE.search(title))
                        or not QUESTION_WORD_RE.search(title)
                    )
                    for title in titles
                )
                stats[f"points_{label}"] += sum(bool(POINTS_RE.search(title)) for title in titles)
                stats[f"duplicate_{label}"] += len(titles) - len(set(titles))
    (args.output / "summary.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
