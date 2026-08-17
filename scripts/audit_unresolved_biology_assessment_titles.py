"""Recover a title for cases the main audit left unresolved.

``audit_biology_assessment_titles_full.confidence`` grades a title that
``derive_task_names`` already produced. This module instead looks at cases
that pipeline never produced a title for at all, and asks a narrower
question: does the source document contain an *explicit* title label (a
table cell literally saying ``평가 과제`` or similar) next to a usable
fragment? Only that direct, source-verified signal is trusted here -- a long
``수행 과제`` cell is usually instructions, not a name, so it is deliberately
excluded.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from scripts.audit_biology_assessment_titles_full import audit_flags, confidence
from scripts.biology_assessment_detail_parser import segment_subject_alignment
from scripts.build_biology_assessment_publish_db import (
    FIELD_STOP_LABELS,
    case_id_for,
    compact_text,
    html_table_grids,
    read_jsonl,
)

# Cell text that itself literally *is* the title label (not the title). A
# bare "수행 과제" is excluded on purpose: in the source plans that cell is
# almost always a paragraph of instructions, not a title.
EXPLICIT_NAME_LABEL_TERMS = {
    compact_text(term)
    for term in ("평가 과제", "평가과제", "평가 과제명", "평가과제명", "수행평가명", "평가영역명", "과제명")
}


def explicit_name_label(text: str) -> bool:
    return compact_text(text) in EXPLICIT_NAME_LABEL_TERMS


# A usable title fragment: an optional leading bullet/middle-dot glyph
# (tables often prefix an item with "・" or "ㆍ"), then ordinary title text.
TITLE_FRAGMENT_RE = re.compile(r"[·ㆍ・]?\s*[0-9A-Za-z가-힣][0-9A-Za-z가-힣·ㆍ・()%,.\s]*")


def find_recovery_candidates(evidence_text: str, subject: str) -> list[dict]:
    """Scan every table for an explicit title label and grade what follows it.

    ``subject_alignment`` reuses the detail parser's own achievement-code
    boundary check rather than a second implementation of it.
    """

    alignment = segment_subject_alignment(evidence_text, subject)
    candidates: list[dict] = []
    seen: set[str] = set()
    for table_match in re.finditer(r"<table\b.*?</table>", evidence_text, re.I | re.S):
        for grid in html_table_grids(table_match.group(0)):
            for row in grid:
                for col_index in range(len(row) - 1):
                    if not explicit_name_label(row[col_index]):
                        continue
                    value = re.sub(r"\s+", " ", row[col_index + 1]).strip()
                    key = compact_text(value)
                    if not value or not key or key in seen or not TITLE_FRAGMENT_RE.fullmatch(value):
                        continue
                    # A header-only row (e.g. label "평가과제" next to another
                    # header "배점") must not be read as label/value; a value
                    # that is itself a label or a bare field name is never a
                    # real title, no matter how it lines up positionally.
                    if key in FIELD_STOP_LABELS or explicit_name_label(value):
                        continue
                    flags = audit_flags(value, "table")
                    grade = confidence(flags, "table", explicit_source_label=True)
                    if grade == "reject":
                        continue
                    seen.add(key)
                    candidates.append(
                        {
                            "candidate": value,
                            "confidence": "high" if grade == "supported" else "review",
                            "detection": "table_row",
                            "subject_alignment": alignment,
                            "explicit_name_label": True,
                            "title_looks_complete": grade == "supported",
                            "other_subject_signal": alignment == "other",
                        }
                    )
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True, help="output of audit_biology_assessment_titles_full")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    resolved_case_ids: set[str] = set()
    with args.audit.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("confidence") == "supported":
                resolved_case_ids.add(str(row.get("case_id") or ""))

    unresolved_cases = 0
    output_rows: list[dict] = []
    for record in read_jsonl(args.catalog):
        source = record.get("source") or {}
        source_key = str(source.get("saved_path") or source.get("final_url") or "")
        subject = str(record.get("subject") or "")
        case_id = case_id_for(source_key, subject)
        if case_id in resolved_case_ids:
            continue
        evidence_text = str(record.get("evidence_text") or "")
        if not evidence_text:
            continue
        candidates = find_recovery_candidates(evidence_text, subject)
        if not candidates:
            continue
        unresolved_cases += 1
        for candidate in candidates:
            output_rows.append({"case_id": case_id, **candidate})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"unresolved_cases_with_candidates={unresolved_cases} candidates={len(output_rows)}")


if __name__ == "__main__":
    main()
