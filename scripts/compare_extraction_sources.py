"""Parse every published case from two full-text sources and compare the results.

The parser is held fixed and only the extraction changes, so the report shows
what the kordoc flow text (``extract_kordoc_documents.py``) does to item
counts, titles and the published tables compared with the archived 2025
extraction.  Table quality is measured on the HTML each item would publish:
escaped tag text, nested tables, rows whose span-expanded width disagrees with
the rest of the table, empty tables, and items with no table at all.

Usage:
    python scripts/compare_extraction_sources.py \
        --new-source data/derived/kordoc_evidence_source_2026_1.jsonl \
        --output data/derived/extraction_compare.jsonl --workers 8
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.biology_assessment_detail_parser import parse_assessment_section  # noqa: E402
from scripts.case_text import DEFAULT_DB, text_for_sha  # noqa: E402

_NEW_OFFSETS: dict[str, int] = {}
_NEW_PATH: Path | None = None


class _TableShape(HTMLParser):
    """Per top-level table: span-expanded row widths, nesting, and whether any cell has text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self.depth = 0
        self.nested = 0
        self._rows: list[int] = []
        self._spans: list[tuple[int, int]] = []
        self._width = 0
        self._text = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.depth += 1
            if self.depth > 1:
                self.nested += 1
            else:
                self._rows, self._spans, self._text = [], [], False
        elif self.depth == 1 and tag == "tr":
            carry = sum(cols for rows, cols in self._spans if rows > 0)
            self._spans = [(rows - 1, cols) for rows, cols in self._spans if rows - 1 > 0]
            self._width = carry
        elif self.depth == 1 and tag in ("td", "th"):
            values = dict(attrs)
            cols = int(values.get("colspan") or 1) if str(values.get("colspan") or "1").isdigit() else 1
            rows = int(values.get("rowspan") or 1) if str(values.get("rowspan") or "1").isdigit() else 1
            self._width += cols
            if rows > 1:
                self._spans.append((rows - 1, cols))

    def handle_endtag(self, tag):
        if self.depth == 1 and tag == "tr":
            self._rows.append(self._width)
        elif tag == "table":
            if self.depth == 1:
                self.tables.append({"widths": self._rows, "has_text": self._text})
            self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if self.depth >= 1 and data.strip():
            self._text = True


def table_metrics(fragment: str) -> collections.Counter:
    metrics: collections.Counter = collections.Counter()
    if not fragment.strip():
        return metrics
    if re.search(r"&lt;/?(?:table|tr|td|th)\b", fragment):
        metrics["escaped_table_tags"] += 1
    shape = _TableShape()
    shape.feed(fragment)
    shape.close()
    metrics["tables"] += len(shape.tables)
    metrics["nested_tables"] += shape.nested
    if not shape.tables:
        metrics["no_table"] += 1
    for table in shape.tables:
        widths = [width for width in table["widths"] if width]
        if not table["has_text"]:
            metrics["empty_tables"] += 1
        elif len(set(widths)) > 1:
            metrics["ragged_tables"] += 1
    return metrics


def _index_new_source(path: Path) -> dict[str, int]:
    offsets: dict[str, int] = {}
    with path.open("rb") as handle:
        while True:
            offset = handle.tell()
            line = handle.readline()
            if not line:
                break
            match = re.search(rb'"sha256":\s*"([0-9a-f]{64})"', line[:200])
            if match:
                offsets[match.group(1).decode()] = offset
    return offsets


def _new_text(sha: str) -> str:
    offset = _NEW_OFFSETS.get(sha)
    if offset is None or _NEW_PATH is None:
        return ""
    with _NEW_PATH.open("rb") as handle:
        handle.seek(offset)
        return str(json.loads(handle.readline()).get("text") or "")


def _init(new_path: str, offsets: dict[str, int]) -> None:
    global _NEW_PATH, _NEW_OFFSETS
    _NEW_PATH = Path(new_path)
    _NEW_OFFSETS = offsets


def _parse(text: str, subject: str) -> tuple[list, str, str]:
    if not text:
        return [], "", "no_text"
    try:
        section = parse_assessment_section(text, subject)
    except Exception as exc:  # noqa: BLE001 - recorded per case
        return [], "", f"{type(exc).__name__}: {exc}"[:200]
    return list(section.items), section.boundary_status, ""


def compare_case(row: tuple) -> dict:
    case_id, subject, region, school, sha, published_bounded = row
    result = {"case_id": case_id, "subject": subject, "region": region, "school": school,
              "published_bounded": published_bounded}
    for label, text in (("old", text_for_sha(sha)), ("new", _new_text(sha))):
        items, boundary, error = _parse(text, subject)
        bounded = [item for item in items if item.extraction_status == "bounded"]
        metrics: collections.Counter = collections.Counter()
        for item in bounded:
            item_metrics = table_metrics(item.source_html)
            metrics.update({f"source_{k}": v for k, v in item_metrics.items()})
            metrics.update({f"rubric_{k}": v for k, v in table_metrics(item.rubric_html).items()
                            if k != "no_table"})
            metrics["methods_found"] += bool(item.method)
            metrics["scores_found"] += bool(item.score)
            metrics["weights_found"] += bool(item.weight)
        result[label] = {
            "bounded": len(bounded), "total": len(items), "boundary": boundary, "error": error,
            "titles": [item.title[:50] for item in bounded][:10], "metrics": dict(metrics),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--new-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    connection = sqlite3.connect(args.database)
    rows = connection.execute(
        "SELECT c.case_id, c.subject, c.region, c.school_name, c.source_sha256, "
        "COALESCE(SUM(i.extraction_status='bounded'), 0) "
        "FROM cases c LEFT JOIN assessment_items i ON i.case_id = c.case_id "
        "GROUP BY c.case_id ORDER BY c.case_id"
    ).fetchall()
    connection.close()
    offsets = _index_new_source(args.new_source)
    # Only cases whose document the new source holds; a partial source compares a sample.
    rows = [row for row in rows if row[4] in offsets]
    if args.limit:
        rows = rows[: args.limit]

    totals: collections.Counter = collections.Counter()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as out, ProcessPoolExecutor(
        max_workers=args.workers, initializer=_init, initargs=(str(args.new_source), offsets)
    ) as pool:
        for index, result in enumerate(pool.map(compare_case, rows, chunksize=8), 1):
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            old, new = result["old"], result["new"]
            totals["cases"] += 1
            totals["old_bounded_items"] += old["bounded"]
            totals["new_bounded_items"] += new["bounded"]
            totals["old_failing_cases"] += old["bounded"] == 0
            totals["new_failing_cases"] += new["bounded"] == 0
            totals["gain" if new["bounded"] > old["bounded"] else "loss" if new["bounded"] < old["bounded"] else "same"] += 1
            for label in ("old", "new"):
                for key, value in result[label]["metrics"].items():
                    totals[f"{label}_{key}"] += value
            if index % 500 == 0:
                print(f"progress {index}/{len(rows)}", flush=True)
    print(json.dumps(dict(sorted(totals.items())), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
