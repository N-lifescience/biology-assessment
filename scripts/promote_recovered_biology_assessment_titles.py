"""Decide which recovered-title candidates are safe to promote into the catalog.

``audit_unresolved_biology_assessment_titles`` produces one audit record per
recovery attempt, several of which can point at the same case. Promotion is
only safe for a candidate that is fully source-verified -- read from an
actual table row, under an explicit title label, aligned with the expected
subject, and not contaminated by another subject's text. Everything else is
counted and left for manual review rather than silently discarded.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.build_biology_assessment_publish_db import compact_text

# A candidate string that is itself a pipeline placeholder (a reference to a
# raw source region) rather than an actual recovered title.
SENTINEL_TITLE_TERMS = {compact_text(term) for term in ("수행평가 원문 구간",)}


def candidates_by_case(audit: dict) -> tuple[dict[str, list[str]], dict[str, int]]:
    selected: dict[str, list[str]] = {}
    skipped: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()

    def bump(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for candidate in audit.get("candidates", []):
        case_id = str(candidate.get("case_id") or "")
        title = str(candidate.get("candidate") or "")
        if not case_id or not title or compact_text(title) in SENTINEL_TITLE_TERMS:
            bump("missing_case_or_title")
            continue

        key = (case_id, title)
        if key in seen:
            continue

        source_verified_high = (
            candidate.get("confidence") == "high"
            and candidate.get("detection") == "table_row"
            and candidate.get("subject_alignment") == "expected"
            and candidate.get("explicit_name_label") is True
            and candidate.get("title_looks_complete") is True
        )
        if not source_verified_high:
            bump("not_source_verified_high")
            continue

        if candidate.get("other_subject_signal"):
            bump("other_subject_signal")
            continue

        seen.add(key)
        selected.setdefault(case_id, []).append(title)

    return selected, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates", type=Path, required=True, help="output of audit_unresolved_biology_assessment_titles"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidates = []
    with args.candidates.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                candidates.append(json.loads(line))

    selected, skipped = candidates_by_case({"candidates": candidates})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for case_id, titles in selected.items():
            handle.write(json.dumps({"case_id": case_id, "titles": titles}, ensure_ascii=False) + "\n")

    skipped_summary = " ".join(f"{reason}={count}" for reason, count in sorted(skipped.items()))
    print(f"promoted_cases={len(selected)} {skipped_summary}")


if __name__ == "__main__":
    main()
