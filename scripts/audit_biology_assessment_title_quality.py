"""Flag published assessment titles that are unlikely to be a task name.

The publish pipeline reads thousands of school plans whose table layouts differ
by 시도, so a parser rule that is right for one template silently misreads
another.  Spot-checking single cases in the browser finds those one at a time;
this sweeps every published item and groups the suspects by *why* they look
wrong, so one parser fix can be aimed at a whole template family at once.

A flag is a suspicion, never a verdict: the rules below intentionally over-flag
so a reviewer sees the borderline cases too.  Nothing here edits the database.

Usage:
    node scripts/run-python.mjs scripts/audit_biology_assessment_title_quality.py \
        --database data/publish/biology_assessment_catalog_detail.sqlite \
        --output data/derived/biology_assessment_title_quality_audit.json \
        --queue data/derived/biology_assessment_title_quality_queue.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from scripts.biology_assessment_detail_parser import (
    NON_TASK_TITLE_RE,
    compact_text,
    heading_title_is_structural,
    is_rubric_criterion_sentence,
)

# Each rule answers one question about a published title, and each is worded so
# a reviewer can confirm or reject it against the item's own source table.
STANDARD_CODE_RE = re.compile(r"^\[?(?:10|12)[가-힣A-ZⅠ-Ⅹ]{1,6}\d")
FIELD_LABEL_TITLE_RE = re.compile(
    r"^(?:교육과정\s*)?(?:성취\s*기준|평가\s*기준|평가\s*요소|평가\s*방법|평가\s*내용|"
    r"평가\s*영역|관련\s*단원|단원명|핵심\s*아이디어|핵심\s*역량|배점|척도|채점\s*기준)$"
)
SCORE_ONLY_RE = re.compile(r"^[\d\s.,()%점배분]+$")


def _rules(title: str) -> list[str]:
    stripped = title.strip()
    compact = compact_text(stripped)
    flags: list[str] = []

    if not compact:
        flags.append("empty_title")
    if heading_title_is_structural(stripped):
        flags.append("structural_heading")
    if is_rubric_criterion_sentence(stripped):
        flags.append("rubric_sentence")
    if NON_TASK_TITLE_RE.fullmatch(stripped):
        flags.append("exam_name")
    if FIELD_LABEL_TITLE_RE.fullmatch(stripped):
        flags.append("field_label_as_title")
    if STANDARD_CODE_RE.match(stripped):
        flags.append("achievement_code_as_title")
    if SCORE_ONLY_RE.fullmatch(stripped):
        flags.append("score_only")
    if len(compact) > 60:
        flags.append("sentence_length")
    if stripped.startswith(("·", "•", "▪", "-", "∙", "ㆍ")):
        flags.append("bullet_prefix")
    # Deliberately no "title repeats inside its own source table" rule: a
    # sampled review of every item it flagged found the title correct in all
    # of them -- an area name legitimately reappears as a rubric row-group
    # label and in a tie-break column. The rule only produced noise, and a
    # noisy audit gets ignored, so it is gone rather than tuned.
    return flags


def audit(database: Path) -> dict[str, object]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT item.item_id, item.case_id, item.item_order, item.title,
               item.title_basis, item.extraction_status,
               cases.school_name, cases.subject, cases.region, cases.candidate_name
        FROM assessment_items item
        JOIN cases ON cases.case_id = item.case_id
        WHERE item.extraction_status = 'bounded'
          AND item.title_basis IN ('table', 'heading')
        ORDER BY item.item_id
        """
    ).fetchall()

    flagged: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    per_school: Counter[str] = Counter()
    for row in rows:
        flags = _rules(str(row["title"]))
        if not flags:
            continue
        counts.update(flags)
        per_school[f"{row['school_name']}|{row['candidate_name']}"] += 1
        flagged.append(
            {
                "item_id": str(row["item_id"]),
                "case_id": str(row["case_id"]),
                "order": int(row["item_order"]),
                "title": str(row["title"]),
                "title_basis": str(row["title_basis"]),
                "school_name": str(row["school_name"]),
                "region": str(row["region"]),
                "subject": str(row["subject"]),
                "source_name": str(row["candidate_name"]),
                "flags": flags,
            }
        )

    # Cases the reference list can publish but /api/v1/cases/{id} refuses,
    # which reads to a teacher as a dead "원문 표 보기" link.
    unreachable = connection.execute(
        """
        SELECT COUNT(DISTINCT item.case_id)
        FROM assessment_items item
        JOIN cases ON cases.case_id = item.case_id
        WHERE item.extraction_status = 'bounded'
          AND item.title_basis IN ('table', 'heading')
          AND cases.title_basis <> 'source_detail'
        """
    ).fetchone()[0]

    # Items whose type the source does not settle. These are for a human to
    # decide, not for another heuristic: either the school declared several
    # methods at once, or it declared none and the title's own wording points
    # at more than one type (a "탐구 보고서 발표" is honestly all three).
    ambiguous = connection.execute(
        """
        SELECT item.item_id, item.title, item.method, ranking.category,
               cases.school_name, cases.subject
        FROM assessment_items item
        JOIN assessment_item_rankings ranking ON ranking.item_id = item.item_id
        JOIN cases ON cases.case_id = item.case_id
        WHERE item.extraction_status = 'bounded'
          AND item.title_basis IN ('table', 'heading')
          AND (
                ranking.category = ''
             OR (item.method = '' AND (
                    (item.title LIKE '%탐구%') + (item.title LIKE '%보고서%')
                  + (item.title LIKE '%발표%') + (item.title LIKE '%실험%')
                  + (item.title LIKE '%포트폴리오%') + (item.title LIKE '%프로젝트%')
                  + (item.title LIKE '%토론%') + (item.title LIKE '%제작%') >= 2
                ))
          )
        ORDER BY item.item_id
        """
    ).fetchall()

    # One case publishing many near-identical titles is the signature of a
    # rubric table being split into an item per row.
    duplicate_heavy = connection.execute(
        """
        SELECT case_id, COUNT(*) AS items
        FROM assessment_items
        WHERE extraction_status = 'bounded' AND title_basis IN ('table', 'heading')
        GROUP BY case_id
        HAVING items >= 8
        ORDER BY items DESC
        LIMIT 40
        """
    ).fetchall()
    connection.close()

    return {
        "checked_items": len(rows),
        "flagged_items": len(flagged),
        "flag_counts": dict(counts.most_common()),
        "unreachable_case_count": int(unreachable),
        "ambiguous_category_count": len(ambiguous),
        "ambiguous_category_sample": [
            {
                "item_id": str(row["item_id"]),
                "title": str(row["title"]),
                "declared_method": str(row["method"])[:120],
                "category": str(row["category"]),
                "school_name": str(row["school_name"]),
                "subject": str(row["subject"]),
            }
            for row in ambiguous[:60]
        ],
        "case_ids_with_many_items": [
            {"case_id": str(row["case_id"]), "items": int(row["items"])}
            for row in duplicate_heavy
        ],
        "worst_sources": [
            {"source": key, "flagged": value} for key, value in per_school.most_common(30)
        ],
        "flagged": flagged,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    args = parser.parse_args()

    report = audit(args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary = {key: value for key, value in report.items() if key != "flagged"}
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    args.queue.parent.mkdir(parents=True, exist_ok=True)
    with args.queue.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["item_id", "case_id", "order", "flags", "title", "school_name",
             "region", "subject", "source_name", "title_basis"]
        )
        for row in report["flagged"]:  # type: ignore[index]
            writer.writerow(
                [
                    row["item_id"], row["case_id"], row["order"], "|".join(row["flags"]),
                    row["title"], row["school_name"], row["region"], row["subject"],
                    row["source_name"], row["title_basis"],
                ]
            )

    print(
        f"title quality: checked={report['checked_items']} "
        f"flagged={report['flagged_items']} "
        f"unreachable_cases={report['unreachable_case_count']} "
        f"ambiguous_category={report['ambiguous_category_count']}"
    )
    for flag, count in report["flag_counts"].items():  # type: ignore[union-attr]
        print(f"  {flag}: {count}")


if __name__ == "__main__":
    main()
