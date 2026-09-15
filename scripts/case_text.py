"""Fetch one case's full source text through the evidence-source offset index."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data/publish/biology_assessment_catalog_detail.sqlite"
DEFAULT_SOURCE = (
    PROJECT_ROOT / "data/drive/학교알리미_원문추출본/02_원문_추출본"
    / "math_assessment_all_subject_evidence_v2_source.jsonl"
)
DEFAULT_INDEX = PROJECT_ROOT / "data/derived/evidence_source_offsets.json"
_OFFSETS: dict[str, int] | None = None


def offsets() -> dict[str, int]:
    global _OFFSETS
    if _OFFSETS is None:
        _OFFSETS = json.loads(DEFAULT_INDEX.read_text(encoding="utf-8"))
    return _OFFSETS


def text_for_sha(sha: str, source: Path = DEFAULT_SOURCE) -> str:
    offset = offsets().get(sha)
    if offset is None:
        return ""
    with source.open("rb") as handle:
        handle.seek(offset)
        return str(json.loads(handle.readline().decode("utf-8")).get("text") or "")


def case_meta(case_id: str, database: Path = DEFAULT_DB) -> dict:
    connection = sqlite3.connect(database)
    row = connection.execute(
        "SELECT subject, school_name, region, source_sha256 FROM cases WHERE case_id=?", (case_id,)
    ).fetchone()
    connection.close()
    if not row:
        raise KeyError(case_id)
    return {"case_id": case_id, "subject": row[0], "school": row[1], "region": row[2], "sha256": row[3]}


def case_text(case_id: str) -> tuple[dict, str]:
    meta = case_meta(case_id)
    return meta, text_for_sha(meta["sha256"])
