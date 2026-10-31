"""Apply ``scripts/review/title_review.csv`` to a publish DB that is already built.

The publish build applies the review while it parses (``_apply_title_review``).
A row added after the build -- a rubric row read as a task that only the case's
context gives away -- would otherwise wait for the next full refresh.  This
applies the same judgement to the stored items: a reviewed title leaves the
confirmed list (``bundle_review``/``reviewed_not_task``), a ``fixed_name``
renames it.  Applying it twice changes nothing.

Usage:
    python scripts/apply_title_review.py \
        --database data/publish/biology_assessment_catalog_detail.sqlite
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from scripts.build_biology_assessment_publish_db import (
    _review_key,
    _title_review,
    refresh_cases_from_items,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "publish" / "biology_assessment_catalog_detail.sqlite"


def apply_review(database: Path) -> dict[str, int]:
    reviewed = _title_review()
    connection = sqlite3.connect(database)
    counts = {"demoted": 0, "renamed": 0}
    try:
        rows = connection.execute(
            "SELECT item_id, case_id, title, overview FROM assessment_items "
            "WHERE extraction_status = 'bounded'"
        ).fetchall()
        for item_id, case_id, title, overview in rows:
            fixed = reviewed.get(case_id, {}).get(_review_key(title))
            if fixed is None or fixed == title:
                continue
            if fixed:
                connection.execute(
                    "UPDATE assessment_items SET title = ?, title_raw = ?, overview = ? "
                    "WHERE item_id = ?",
                    (fixed, fixed, overview or title, item_id),
                )
                counts["renamed"] += 1
            else:
                connection.execute(
                    "UPDATE assessment_items SET extraction_status = 'bundle_review', "
                    "title_basis = 'reviewed_not_task' WHERE item_id = ?",
                    (item_id,),
                )
                counts["demoted"] += 1
        if any(counts.values()):
            # 사례의 대표 과제명·과제 목록은 확정 항목에서 다시 뽑는다.
            refresh_cases_from_items(connection)
        # 확정 항목이 하나도 남지 않은 사례는 다른 미확정 사례처럼 검토 묶음으로 둔다.
        counts["cases_to_review"] = connection.execute(
            "UPDATE cases SET title_basis = 'source_detail_bundle_review' "
            "WHERE title_basis = 'source_detail' AND case_id NOT IN ("
            "SELECT case_id FROM assessment_items WHERE extraction_status = 'bounded' "
            "AND title_basis IN ('table', 'heading'))"
        ).rowcount
        connection.commit()
    finally:
        connection.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    arguments = parser.parse_args()
    counts = apply_review(arguments.database)
    print(
        f"title review applied: demoted={counts['demoted']} renamed={counts['renamed']} "
        f"cases_to_review={counts['cases_to_review']}"
    )


if __name__ == "__main__":
    main()
