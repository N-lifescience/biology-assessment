"""Fingerprint the table structure of every published case's assessment section.

Step 1 of template-aware parsing.  For each case the assessment block of its
subject section is located exactly as the detail parser does, then every table
in that block is reduced to a structural fingerprint: the header row and the
first-column labels, normalised so spacing/spelling variants collapse.  The
output (one JSON row per case) is the raw material for clustering documents
by 교육청 양식 and for writing per-template parsing profiles.

Usage:
  python scripts/profile_source_templates.py --database data/publish/biology_assessment_catalog_detail.sqlite \\
      --evidence-source <full-text jsonl> --output data/derived/template_signatures.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.biology_assessment_detail_parser import (  # noqa: E402
    _source_tables,
    assessment_block,
    compact_text,
    subject_local_markdown,
    visible_text,
)
from scripts.build_biology_assessment_publish_db import read_jsonl  # noqa: E402

# Synonym buckets: the same slot spelled differently across 교육청 forms.
LABEL_BUCKETS: list[tuple[str, re.Pattern[str]]] = [
    ("AREA", re.compile(r"^(?:수행)?평가영역|^영역명|^수행평가영역|^평가영역명")),
    ("TITLE", re.compile(r"^(?:수행)?평가명|^수행평가명|^평가과제|^과제명|^수행과제|^평가주제")),
    ("WEIGHT", re.compile(r"^반영비율|^반영비|^비율")),
    ("MAXSCORE", re.compile(r"^영역만점|^만점|^배점|^총점|^평가만점")),
    ("BASESCORE", re.compile(r"^기본점수")),
    ("STANDARD", re.compile(r"성취기준")),
    ("LEVEL", re.compile(r"^성취수준|^수준|^등급|^평가기준")),
    ("METHOD", re.compile(r"^평가방법|^평가방식|^평가유형|^평가종류")),
    ("TIMING", re.compile(r"^평가시기|^시기|^실시시기|^평가시기및횟수")),
    ("ELEMENT", re.compile(r"^평가요소|^평가내용|^평가항목|^세부평가요소|^채점요소")),
    ("RUBRIC", re.compile(r"^채점기준|^세부기준|^평가척도|^수행수준|^점수부여기준|^평가기준")),
    ("SCORE", re.compile(r"^점수|^배점|^평정점|^평정")),
    ("UNIT", re.compile(r"^관련단원|^단원|^평가단원|^단원명")),
    ("COMPETENCY", re.compile(r"^교과역량|^핵심역량|^역량")),
    ("GRADE_ABCDE", re.compile(r"^[A-E]$")),
    ("GRADE_SMH", re.compile(r"^(상|중|하)$")),
    ("CODE", re.compile(r"^\[?(?:10|12)[가-힣ⅠⅡ]{1,8}\d{2}-\d{2}")),
    ("SUBJECT", re.compile(r"^과목|^교과")),
    ("STUDENT", re.compile(r"^학번|^이름|^성명|^학생")),
    ("NOTE", re.compile(r"^비고|^유의사항|^기타")),
    ("MISSING", re.compile(r"^미응시|^결시|^인정점")),
]


def bucket(label: str) -> str:
    key = compact_text(visible_text(label))[:24]
    if not key:
        return "_"
    for name, pattern in LABEL_BUCKETS:
        if pattern.search(key):
            return name
    if re.fullmatch(r"[\d.,%점/~\-()\s]+", key):
        return "NUM"
    return "TXT"


def table_fingerprint(rows: list[list[str]]) -> dict:
    header = [bucket(cell) for cell in rows[0][:8]] if rows else []
    first_column = [bucket(row[0]) for row in rows[1:] if row]
    # Run-length collapse the first column so a 12-row rubric and a 4-row
    # rubric with the same skeleton hash the same.
    collapsed: list[str] = []
    for label in first_column:
        if not collapsed or collapsed[-1] != label:
            collapsed.append(label)
    width = max((len(row) for row in rows), default=0)
    return {
        "header": header,
        "first_column": collapsed[:16],
        "rows": len(rows),
        "width": width,
        "labels_raw": [compact_text(visible_text(row[0]))[:14] for row in rows[:6] if row],
    }


def signature_key(tables: list[dict]) -> str:
    parts = []
    for table in tables[:6]:
        parts.append("H:" + ",".join(table["header"][:5]) + "|C:" + ",".join(table["first_column"][:8]))
    return " || ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--evidence-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    connection = sqlite3.connect(args.database)
    cases_by_sha: dict[str, list[tuple]] = {}
    for row in connection.execute(
        "SELECT c.case_id, c.subject, c.region, c.school_name, c.source_sha256, c.title_basis, "
        "s.source_format, s.boundary_status "
        "FROM cases c LEFT JOIN case_detail_status s ON s.case_id = c.case_id"
    ):
        cases_by_sha.setdefault(str(row[4]), []).append(row)
    item_stats = {
        str(case_id): (int(total), int(bounded), int(no_rubric))
        for case_id, total, bounded, no_rubric in connection.execute(
            "SELECT case_id, COUNT(*), SUM(extraction_status='bounded'), "
            "SUM(extraction_status='bounded' AND rubric_html_char_count=0) "
            "FROM assessment_items GROUP BY case_id"
        )
    }
    connection.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        for record in read_jsonl(args.evidence_source):
            pending = cases_by_sha.pop(str(record.get("sha256") or ""), None)
            if not pending:
                continue
            text = str(record.get("text") or "")
            for case_id, subject, region, school, _sha, title_basis, fmt, boundary in pending:
                try:
                    markdown, _s, _e, subject_status = subject_local_markdown(text, subject)
                    block, _bs, _be, block_status = assessment_block(markdown)
                except Exception as exc:  # noqa: BLE001
                    block, subject_status, block_status = "", f"error:{type(exc).__name__}", ""
                tables = [table_fingerprint(rows) for rows in _source_tables(block) if rows]
                total, bounded, no_rubric = item_stats.get(case_id, (0, 0, 0))
                out.write(json.dumps({
                    "case_id": case_id, "subject": subject, "region": region, "school": school,
                    "source_format": fmt, "boundary_status": boundary, "title_basis": title_basis,
                    "subject_status": subject_status, "block_status": block_status,
                    "block_chars": len(block), "table_count": len(tables),
                    "items": total, "bounded": bounded, "no_rubric": no_rubric,
                    "signature": signature_key(tables), "tables": tables[:12],
                }, ensure_ascii=False) + "\n")
                written += 1
            if args.limit and written >= args.limit:
                break
            if not cases_by_sha:
                break
    print(json.dumps({"cases_written": written, "cases_unmatched": sum(len(v) for v in cases_by_sha.values())}))


if __name__ == "__main__":
    main()
