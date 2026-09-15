"""Build a sha256 -> byte offset index for the multi-GB evidence source JSONL.

Random access by sha256 then costs one seek instead of a full scan, which
makes per-case debugging (``dump_case_block.py``) and template work fast.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SHA_RE = re.compile(rb'"sha256"\s*:\s*"([0-9a-f]{64})"')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evidence-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    offsets: dict[str, int] = {}
    with args.evidence_source.open("rb") as handle:
        offset = 0
        for line in handle:
            match = SHA_RE.search(line[:4000]) or SHA_RE.search(line)
            if match:
                offsets.setdefault(match.group(1).decode(), offset)
            offset += len(line)
    args.output.write_text(json.dumps(offsets), encoding="utf-8")
    print(f"indexed={len(offsets)} source={args.evidence_source}")


if __name__ == "__main__":
    main()
