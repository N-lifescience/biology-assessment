"""Grade how much a candidate assessment title can be trusted as-is.

``derive_task_names`` (in ``build_biology_assessment_publish_db``) already
throws away obvious noise. This module grades what survives that filter on a
finer three-way scale -- ``supported`` / ``review`` / ``reject`` -- so a
short, source-confirmed unit name (e.g. ``광합성`` next to an explicit
``평가영역명`` label) can be trusted without being confused with a rubric
sentence or a field value that merely sits in the same table position.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from pathlib import Path

from scripts.build_biology_assessment_publish_db import (
    GENERIC_BARE_NOUNS,
    case_id_for,
    compact_text,
    derive_task_names,
    read_jsonl,
)

# Bare field values, period labels, and other administrative meta-words that
# are never a task title even when an explicit source label points at them.
FIELD_VALUE_TERMS = {
    compact_text(term)
    for term in (
        "평소", "단원", "수준", "점수(점)", "정기1차시험", "중간", "기말",
        "학습", "직무", "수행평가", "II", "생명과학Ⅱ 전체",
    )
}
GENERIC_STRUCTURAL_TERMS = {compact_text(term) for term in ("영역별",)}
OTHER_SUBJECT_TERMS = {compact_text(term) for term in ("기본권 쟁점 파악",)}
HARD_REJECT_COMPOUND_TERMS = {compact_text(term) for term in ("탐구설계", "보고서 작성")}
FIELD_MARKER_TERMS = ("평가항목", "평가방법", "채점기준")
SCORE_OR_QUANTITY_RE = re.compile(r"\d+\s*[~-]\s*\d+\s*(?:점|쪽|장|줄)")
TASK_COMPLETION_SUFFIXES = ("하기", "보고서", "발표", "작성")
TRAILING_PAREN_NUMBER_RE = re.compile(r"\s*\(\s*\d+\s*\)\s*$")
LEADING_NUMBER_RE = re.compile(r"^\d+\s*[.)]\s*")


def audit_flags(title: str, source: str) -> dict:
    text = re.sub(r"\s+", " ", title).strip()
    text_no_paren = TRAILING_PAREN_NUMBER_RE.sub("", text)
    text_no_paren = LEADING_NUMBER_RE.sub("", text_no_paren)
    compact = compact_text(text_no_paren)
    words = [word for word in text_no_paren.split(" ") if word]
    return {
        "source": source,
        "word_count": len(words),
        "is_question": text.endswith("?"),
        "is_field_value": compact in FIELD_VALUE_TERMS,
        "is_generic_structural": compact in GENERIC_STRUCTURAL_TERMS,
        "is_other_subject": compact in OTHER_SUBJECT_TERMS,
        "is_hard_reject_compound": compact in HARD_REJECT_COMPOUND_TERMS,
        # A bare method noun ("포트폴리오", "배점") next to an explicit label is
        # still not a title -- the label just says what *kind* of thing is
        # missing, same denylist derive_task_names already trusts.
        "is_generic_bare_method": compact in GENERIC_BARE_NOUNS,
        "has_field_marker": any(marker in compact for marker in FIELD_MARKER_TERMS),
        "has_score_or_quantity": bool(SCORE_OR_QUANTITY_RE.search(text)),
        "is_method_enumeration": text.count(",") >= 2,
        "has_task_completion": text_no_paren.endswith(TASK_COMPLETION_SUFFIXES),
    }


def confidence(flags: dict, source: str, explicit_source_label: bool = False) -> str:
    hard_reject = (
        flags["is_question"]
        or flags["is_field_value"]
        or flags["is_generic_structural"]
        or flags["is_other_subject"]
        or flags["is_hard_reject_compound"]
        or flags["is_generic_bare_method"]
        or flags["has_field_marker"]
        or flags["has_score_or_quantity"]
        or flags["is_method_enumeration"]
    )
    if hard_reject:
        return "reject"
    if flags["word_count"] <= 1:
        return "supported" if explicit_source_label else "review"
    if flags["has_task_completion"]:
        return "supported"
    return "supported" if explicit_source_label else "reject"


def audit_catalog(catalog_path: Path):
    """Yield one audit row per candidate title in every catalog record.

    A candidate's ``source`` and its ``explicit_source_label`` status both
    come straight out of ``derive_task_names``: ``"section"`` means the name
    was read from a bare line with no source-authored label pointing at it,
    while ``"table"``/``"context"`` both mean a real label cell was found.
    """

    for record in read_jsonl(catalog_path):
        source = record.get("source") or {}
        source_key = str(source.get("saved_path") or source.get("final_url") or "")
        subject = str(record.get("subject") or "")
        evidence_text = str(record.get("evidence_text") or "")
        upstream_names = [str(v) for v in (record.get("task_name_candidates") or [])]

        if upstream_names:
            names = upstream_names
            sources = {name: "table" for name in names}
        elif evidence_text:
            names, _, sources = derive_task_names(evidence_text, [], subject)
        else:
            names, sources = [], {}

        case_id = case_id_for(source_key, subject)
        for title in names:
            title_source = sources.get(title, "table")
            flags = audit_flags(title, title_source)
            grade = confidence(flags, title_source, explicit_source_label=title_source != "section")
            yield {
                "case_id": case_id,
                "subject": subject,
                "title": title,
                "source": title_source,
                "confidence": grade,
            }


def audit_database(database: Path):
    """Same grading, run over the titles the detail DB actually publishes.

    ``assessment_items`` is the post-derivation product of the same pipeline,
    so ``title_basis`` already records what ``derive_task_names`` returned as
    the candidate's ``source``: a ``table`` basis means a source-authored label
    cell pointed at the title, while ``heading``/``unbounded_bundle`` mean it
    was read off a bare line with no label -- the ``section`` case.
    """

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT i.item_id, i.case_id, i.title, i.title_basis, i.extraction_status, "
            "c.subject FROM assessment_items i JOIN cases c ON c.case_id = i.case_id"
        ).fetchall()
    finally:
        connection.close()

    for row in rows:
        title_source = "table" if row["title_basis"].startswith("table") else "section"
        flags = audit_flags(row["title"], title_source)
        yield {
            "item_id": row["item_id"],
            "case_id": row["case_id"],
            "subject": row["subject"],
            "title": row["title"],
            "title_basis": row["title_basis"],
            "extraction_status": row["extraction_status"],
            "source": title_source,
            "confidence": confidence(
                flags, title_source, explicit_source_label=title_source != "section"
            ),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, help="candidate-title catalog JSONL")
    parser.add_argument("--database", type=Path, help="publish detail sqlite")
    parser.add_argument("--output", type=Path, help="one audited title per line (JSONL)")
    parser.add_argument("--summary", type=Path, help="grade counts (JSON)")
    parser.add_argument("--queue", type=Path, help="non-supported titles for review (CSV)")
    args = parser.parse_args()
    if bool(args.catalog) == bool(args.database):
        parser.error("pass exactly one of --catalog or --database")
    if not any((args.output, args.summary, args.queue)):
        parser.error("pass at least one of --output, --summary, --queue")

    rows = audit_catalog(args.catalog) if args.catalog else audit_database(args.database)
    counts = {"supported": 0, "review": 0, "reject": 0}
    by_status: dict[str, dict[str, int]] = {}
    queued: list[dict] = []
    output = None
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        output = args.output.open("w", encoding="utf-8")
    try:
        for row in rows:
            counts[row["confidence"]] += 1
            status = row.get("extraction_status")
            if status:
                by_status.setdefault(status, dict.fromkeys(counts, 0))[row["confidence"]] += 1
            if row["confidence"] != "supported":
                queued.append(row)
            if output:
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
    finally:
        if output:
            output.close()

    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(
            json.dumps(
                {
                    "titles": sum(counts.values()),
                    "confidence": counts,
                    "by_extraction_status": by_status,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if args.queue:
        fields = [
            "item_id", "case_id", "subject", "title", "title_basis",
            "source", "extraction_status", "confidence",
        ]
        args.queue.parent.mkdir(parents=True, exist_ok=True)
        with args.queue.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows({field: row.get(field, "") for field in fields} for row in queued)

    print(f"supported={counts['supported']} review={counts['review']} reject={counts['reject']}")


if __name__ == "__main__":
    main()
