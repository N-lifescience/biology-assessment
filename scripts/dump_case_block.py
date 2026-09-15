"""Print the assessment block the parser sees for given case ids (debugging aid)."""

from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import json  # noqa: E402

from scripts.biology_assessment_detail_parser import (  # noqa: E402
    assessment_block,
    subject_local_markdown,
)


def iter_records(evidence_source: Path, shas: list[str]) -> list[str]:
    """Return the JSONL lines for the given sha256 values, via the offset index when present."""

    index_path = evidence_source.parent.parent.parent.parent / "derived" / "evidence_source_offsets.json"
    if not index_path.is_file():
        index_path = PROJECT_ROOT / "data" / "derived" / "evidence_source_offsets.json"
    if index_path.is_file():
        offsets = json.loads(index_path.read_text(encoding="utf-8"))
        lines = []
        with evidence_source.open("rb") as handle:
            for sha in shas:
                offset = offsets.get(sha)
                if offset is None:
                    continue
                handle.seek(offset)
                lines.append(handle.readline().decode("utf-8"))
        return lines
    pattern_file = Path("/tmp/dump_case_shas.txt")
    pattern_file.write_text("\n".join(shas) + "\n", encoding="utf-8")
    grep = subprocess.run(
        ["grep", "-F", "-f", str(pattern_file), str(evidence_source)],
        capture_output=True, text=True, env={"LC_ALL": "C"},
    )
    return grep.stdout.splitlines()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--evidence-source", type=Path, required=True)
    parser.add_argument("--chars", type=int, default=5000)
    parser.add_argument("--full", action="store_true", help="print the subject section, not only the block")
    parser.add_argument("case_ids", nargs="+")
    args = parser.parse_args()
    connection = sqlite3.connect(args.database)
    wanted = {}
    for case_id in args.case_ids:
        row = connection.execute(
            "SELECT subject, school_name, region, source_sha256 FROM cases WHERE case_id=?", (case_id,)
        ).fetchone()
        if row:
            wanted[row[3]] = (case_id, row[0], row[1], row[2])
    lines = iter_records(args.evidence_source, list(wanted))
    for line in lines:
        record = json.loads(line)
        info = wanted.get(record.get("sha256"))
        if not info:
            continue
        case_id, subject, school, region = info
        text = record.get("text") or ""
        markdown, _, _, subject_status = subject_local_markdown(text, subject)
        block, _, _, block_status = assessment_block(markdown)
        shown = markdown if args.full else block
        shown = re.sub(r"\n{3,}", "\n\n", shown)
        print(f"\n{'=' * 100}\n{case_id} {region} {school} [{subject}] subject={subject_status} block={block_status} "
              f"section={len(markdown)} block={len(block)} chars\n{'=' * 100}")
        print(shown[: args.chars])


if __name__ == "__main__":
    main()
