"""Build a deterministic manifest of SCHOOLINFO 4-가 files likely to contain biology plans.

This step deliberately does not read or interpret document contents.  It only records
provenance, applies conservative filename aliases, and marks generic files for later
text scanning.  Semantic extraction is a separate, model-gated step.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
from pathlib import Path


ALIASES: list[tuple[str, str, str]] = [
    ("고급생명과학", "고급생명과학", r"고급\s*생명\s*과학"),
    ("생명과학실험", "생명과학실험", r"생명\s*과학\s*실험"),
    # ``II`` has to stay an alternation.  As the character class ``[ⅡII2]`` a
    # single Latin ``I`` matches Ⅱ, and Ⅱ is tested first, so ``생명과학I``
    # was filed as 생명과학Ⅱ.
    ("생명과학Ⅱ", "생명과학Ⅱ", r"생명\s*과학\s*(?:Ⅱ|II|2)"),
    ("생명과학Ⅰ", "생명과학Ⅰ", r"생명\s*과학\s*(?:Ⅰ|I|1)"),
    ("생명과학", "생명과학", r"생명\s*과학(?!\s*[ⅠⅡI12])"),
    ("과학탐구실험1", "과학탐구실험1", r"과학\s*탐구\s*실험\s*[ⅠI1]"),
    ("과학탐구실험", "과학탐구실험", r"과학\s*탐구\s*실험(?!\s*[ⅠⅡI12])"),
    ("통합과학1", "통합과학1", r"통합\s*과학\s*[ⅠI1]"),
    # ``통합과학2`` is outside the published subject scope; the negative
    # lookahead lets it fall through to the generic alias instead of being
    # mislabelled as the 2015 single-course ``통합과학``.
    ("통합과학", "통합과학", r"통합\s*과학(?!\s*[ⅠⅡI12])"),
    ("과학", "과학", r"과학"),
]


def classify(name: str) -> tuple[str, str, str]:
    for label, canonical, pattern in ALIASES:
        if re.search(pattern, name, flags=re.IGNORECASE):
            return label, canonical, "filename_alias"
    return "unknown", "unknown", "needs_text_scan"


def curriculum(year_text: str, name: str) -> str:
    # Prefer an explicit year in the filename.  Schoolinfo URLs can contain both
    # the current disclosure year and the attachment's actual JG_YEAR.
    name_years = [int(y) for y in re.findall(r"20\d{2}", name)]
    if name_years:
        years = name_years
    else:
        jg_years = [int(y) for y in re.findall(r"JG_YEAR(?:=|%3D)(20\d{2})", year_text, flags=re.IGNORECASE)]
        years = jg_years or [int(y) for y in re.findall(r"20\d{2}", year_text)]
    if any(y >= 2025 for y in years):
        return "2022_candidate"
    if any(2015 <= y <= 2024 for y in years):
        return "2015_candidate"
    return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    if args.log.suffix.lower() == ".jsonl":
        with args.log.open("r", encoding="utf-8") as handle:
            source_rows = [json.loads(line) for line in handle if line.strip()]
    else:
        with args.log.open("r", encoding="utf-8-sig", newline="") as handle:
            source_rows = list(csv.DictReader(handle))
    for row in source_rows:
        if row.get("result") != "downloaded":
            continue
        if row.get("item_no") not in {None, "", "4-가"}:
            continue
        if row.get("record_type") not in {None, "", "attachment"}:
            continue
        path = row.get("saved_path", "")
        key = path or row.get("final_url", "")
        if key in seen:
            continue
        seen.add(key)
        name = row.get("candidate_name", "")
        raw, canonical, match_type = classify(name)
        cur = curriculum(
            " ".join(
                (
                    str(row.get("year", "")),
                    row.get("final_url", ""),
                    row.get("source_url", ""),
                )
            ),
            name,
        )
        rows.append(
            {
                "curriculum_candidate": cur,
                "year": row.get("year", ""),
                "school_code": row.get("school_code", ""),
                "school_name": row.get("school_name", ""),
                "region": row.get("region", row.get("sido", "")),
                "candidate_name": name,
                "subject_match": raw,
                "subject_canonical": canonical,
                "match_type": match_type,
                "needs_text_scan": "false" if match_type == "filename_alias" else "true",
                "saved_path": _local_path(path),
                "source_saved_path": path,
                "source_url": row.get("source_url", ""),
                "final_url": row.get("final_url", ""),
                "size_bytes": row.get("size_bytes", ""),
            }
        )

    rows.sort(key=lambda r: (r["curriculum_candidate"], r["subject_canonical"], r["school_name"], r["candidate_name"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=args.output.stem + "_", suffix=".partial", dir=args.output.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["curriculum_candidate"])
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp_path, args.output)

    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['curriculum_candidate']}::{row['subject_canonical']}"
        counts[key] = counts.get(key, 0) + 1
    print(f"rows={len(rows)} schools={len({r['school_code'] for r in rows})}")
    for key, value in sorted(counts.items()):
        print(f"{key}={value}")


def _local_path(source_path: str) -> str:
    marker = "교육과정운영계획/data/raw/4ga/"
    if marker in source_path:
        return "data/raw/schoolinfo/4ga/" + source_path.split(marker, 1)[1]
    return source_path


if __name__ == "__main__":
    main()
