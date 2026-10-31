"""Drop cases that repeat another case's plan from the same school disclosure.

A school often attaches the same plan twice to one 공시 record -- an HWP and a
PDF, a file and its "_수정" copy -- or re-posts the 1차 file in the 3차 round.
Each attachment has its own sha256 and FILE_SEQ/JG_CHASU, so the merge (which
skips only identical files) kept both, and the site listed the same plan twice
and counted it twice in the trends.

Two cases of one subject from the same school record (``SHL_IDF_CD``) with the
same academic years and semesters are the same plan when their item titles are
the same set and their item text is nearly identical (identical when the two
name different grades, or one names none).  The case showing the most
confirmed items is kept -- a newer attachment the parser could not confirm must
not hide the plan the site shows -- then the latest round (``JG_CHASU``) and
attachment (``FILE_SEQ``).  A case is dropped only when every confirmed task it
shows is also shown by the case kept.

Usage:
    python scripts/dedupe_publish_cases.py \
        --database data/publish/biology_assessment_catalog_detail.sqlite
"""

from __future__ import annotations

import argparse
import difflib
import re
import sqlite3
import zlib
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts.merge_publish_dbs import recompute_subject_stats

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "publish" / "biology_assessment_catalog_detail.sqlite"
# Revisions of one plan differ by a corrected sentence or two; a different
# plan that happens to share its task titles differs far more.
SAME_PLAN_RATIO = 0.8
# 학년만 다른 두 사례는 본문이 사실상 같을 때만 같은 계획이다.
SAME_TEXT_RATIO = 0.95
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def _query_value(url: str, name: str) -> str:
    return (parse_qs(urlparse(url).query).get(name) or [""])[0]


def _version(url: str) -> tuple[int, int]:
    def number(name: str) -> int:
        value = _query_value(url, name)
        return int(value) if value.isdigit() else 0

    return number("JG_CHASU"), number("FILE_SEQ")


def _plain(html: str) -> str:
    return SPACE_RE.sub("", TAG_RE.sub("", html))


def _plans(
    connection: sqlite3.Connection,
) -> dict[str, tuple[frozenset[str], str, frozenset[str]]]:
    """``case_id -> (all item titles, item text, confirmed item titles)``."""

    titles: dict[str, list[str]] = defaultdict(list)
    public: dict[str, list[str]] = defaultdict(list)
    texts: dict[str, list[str]] = defaultdict(list)
    for case_id, title, status, basis, blob in connection.execute(
        "SELECT case_id, title, extraction_status, title_basis, source_html_zlib "
        "FROM assessment_items ORDER BY case_id, item_order"
    ):
        key = SPACE_RE.sub("", str(title))
        titles[case_id].append(key)
        if status == "bounded" and basis in ("table", "heading"):
            public[case_id].append(key)
        texts[case_id].append(_plain(zlib.decompress(blob).decode("utf-8")) if blob else "")
    return {
        case_id: (frozenset(titles[case_id]), "".join(texts[case_id]), frozenset(public[case_id]))
        for case_id in titles
    }


def _same_plan(left: str, right: str, ratio: float = SAME_PLAN_RATIO) -> bool:
    if left == right:
        return True
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    return matcher.quick_ratio() >= ratio and matcher.ratio() >= ratio


def find_duplicates(connection: sqlite3.Connection) -> dict[str, str]:
    """Return ``{dropped case_id: kept case_id}``."""

    plans = _plans(connection)
    grades_of: dict[str, str] = {}
    groups: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
    for case_id, subject, url, years, semesters, grades in connection.execute(
        "SELECT case_id, subject, source_url, academic_years_json, semesters_json, grades_json "
        "FROM cases"
    ):
        school = _query_value(str(url), "SHL_IDF_CD")
        if not school or case_id not in plans:
            continue
        grades_of[case_id] = str(grades or "[]")
        groups[(school, subject, years, semesters, plans[case_id][0])].append(
            (case_id, str(url))
        )

    def same(keep: str, case_id: str) -> bool:
        # 지우는 쪽이 보여 주는 과제는 남기는 쪽도 모두 보여 줘야 한다.
        if not plans[case_id][2] <= plans[keep][2]:
            return False
        same_grades = grades_of[keep] == grades_of[case_id] or "[]" in (
            grades_of[keep],
            grades_of[case_id],
        )
        ratio = SAME_PLAN_RATIO if same_grades else SAME_TEXT_RATIO
        return _same_plan(plans[keep][1], plans[case_id][1], ratio)

    dropped: dict[str, str] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        # 확정 과제를 가장 많이 보여 주는 판, 그다음 최신 차수·최신 첨부부터 남긴다.
        members.sort(
            key=lambda member: (len(plans[member[0]][2]), _version(member[1]), member[0]),
            reverse=True,
        )
        kept: list[str] = []
        for case_id, _url in members:
            match = next((keep for keep in kept if same(keep, case_id)), None)
            if match is None:
                kept.append(case_id)
            else:
                dropped[case_id] = match
    return dropped


def dedupe_database(database: Path) -> dict[str, int]:
    connection = sqlite3.connect(database)
    try:
        dropped = find_duplicates(connection)
        ids = [(case_id,) for case_id in dropped]
        item_filter = "item_id IN (SELECT item_id FROM assessment_items WHERE case_id = ?)"
        for table in ("assessment_item_axes", "assessment_item_rankings"):
            connection.executemany(f"DELETE FROM {table} WHERE {item_filter}", ids)
        for table in ("assessment_items", "case_detail_status", "cases"):
            connection.executemany(f"DELETE FROM {table} WHERE case_id = ?", ids)
        if dropped:
            recompute_subject_stats(connection)
        connection.commit()
        if dropped:
            connection.execute("VACUUM")
    finally:
        connection.close()
    return {"dropped_cases": len(dropped)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    arguments = parser.parse_args()
    counts = dedupe_database(arguments.database)
    print(f"duplicate cases dropped: {counts['dropped_cases']}")


if __name__ == "__main__":
    main()
