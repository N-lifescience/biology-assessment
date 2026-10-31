"""Replace word-processor symbol-font glyphs in a publish DB with real characters.

HWP and Word store a bullet or checkbox drawn in a symbol font (Wingdings,
Hancom's own symbol and equation fonts) as a private-use code point.  The site
has no such font, so the reader saw an empty box where the plan had "☑" or "□"
-- and the 평가 방법 cell lost which options the school actually ticked.  This
rewrites the code points whose meaning the corpus shows, in every text column
and in the stored source/rubric HTML, before the DB is packaged.

Usage:
    python scripts/normalize_symbol_glyphs.py \
        --database data/publish/biology_assessment_catalog_detail.sqlite
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import zlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "publish" / "biology_assessment_catalog_detail.sqlite"

# Wingdings sits at U+F000 + its byte; Hancom's fonts at U+E000-U+EFFF.  Each
# entry was read off the surrounding text in the corpus (" 서술·논술 ·
#  실험·실습" is an unticked and a ticked box; "총합이 20점이 넘더라도
# 점" is the equation font's "20").
GLYPHS = {
    "": " ",
    "": "•",
    "": "●",
    "": "❍",
    "": "■",
    "": "□",
    "": "□",
    "": "❖",
    "": "◆",
    "": "☒",
    "": "·",
    "": "•",
    "": "·",
    "": "▪",
    "": "□",
    "": "•",
    "": "➢",
    "": "➔",
    "": "•",
    "": "✗",
    "": "✓",
    "": "☒",
    "": "☑",
    "": "·",
    "": "·",
    "": "•",
    "": "·",
    "": "·",
    "": "·",
    "": "□",
    "": "☑",
    "": "☑",
    "": "=",
    "": "+",
    **{chr(0xE034 + offset): str(offset + 1) for offset in range(9)},
    "": "0",
}
GLYPH_RE = re.compile("[" + "".join(GLYPHS) + "]")
# A private-use glyph no plan explains is dropped; between two letters it was a
# separator ("구술발표"), so it becomes the same middle dot.
UNKNOWN_BETWEEN_RE = re.compile(r"(?<=[^\s<>])[-\U000f0000-\U0010ffff]+(?=[^\s<>])")
UNKNOWN_RE = re.compile(r"[-\U000f0000-\U0010ffff]")


# 글머리 기호 글리프가 두 글자 사이에 끼면 가운뎃점이다("서술논술" = 서술·논술).
BULLET_GLYPHS = "".join(
    code for code, value in GLYPHS.items() if value in {"•", "▪", "●", "◆", "❖", "❍", "·"}
)
BULLET_BETWEEN_RE = re.compile(rf"(?<=[가-힣A-Za-z])[{BULLET_GLYPHS}](?=[가-힣A-Za-z])")


def normalize_symbol_glyphs(text: str) -> str:
    text = BULLET_BETWEEN_RE.sub("·", text)
    text = GLYPH_RE.sub(lambda match: GLYPHS[match.group()], text)
    # 원문 글머리 뒤에 바뀐 글머리가 붙어 "· ·"가 된 것은 하나로.
    text = re.sub(r"·(?:\s*·)+", "·", text)
    text = UNKNOWN_BETWEEN_RE.sub("·", text)
    return UNKNOWN_RE.sub("", text)


def _text_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(column[1])
        for column in connection.execute(f"PRAGMA table_info({table})")
        if str(column[2]).upper() == "TEXT"
    ]


def normalize_database(database: Path) -> dict[str, int]:
    connection = sqlite3.connect(database)
    counts: dict[str, int] = {}
    try:
        updates = []
        for item_id, source, rubric in connection.execute(
            "SELECT item_id, source_html_zlib, rubric_html_zlib FROM assessment_items"
        ):
            texts = [
                zlib.decompress(blob).decode("utf-8") if blob else None for blob in (source, rubric)
            ]
            fixed = [
                normalize_symbol_glyphs(text) if text is not None else None for text in texts
            ]
            if fixed != texts:
                updates.append((
                    zlib.compress(fixed[0].encode("utf-8")) if fixed[0] is not None else None,
                    zlib.compress(fixed[1].encode("utf-8")) if fixed[1] is not None else None,
                    len(fixed[1] or ""),
                    item_id,
                ))
        connection.executemany(
            "UPDATE assessment_items SET source_html_zlib = ?, rubric_html_zlib = ?, "
            "rubric_html_char_count = ? WHERE item_id = ?",
            updates,
        )
        counts["item_html"] = len(updates)
        tables = [
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        for table in tables:
            columns = _text_columns(connection, table)
            if not columns:
                continue
            # WITHOUT ROWID 표(assessment_item_axes)는 기본키 열로 줄을 찾는다.
            keys = [
                str(column[1])
                for column in connection.execute(f"PRAGMA table_info({table})")
                if int(column[5])
            ]
            has_rowid = True
            try:
                connection.execute(f"SELECT rowid FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                has_rowid = False
            locator = ["rowid"] if has_rowid else keys
            changed = 0
            for column in columns:
                rows = connection.execute(
                    f"SELECT {', '.join(locator)}, {column} FROM {table} "
                    f"WHERE {column} IS NOT NULL"
                ).fetchall()
                column_updates = [
                    (normalize_symbol_glyphs(row[-1]), *row[:-1])
                    for row in rows
                    if isinstance(row[-1], str) and normalize_symbol_glyphs(row[-1]) != row[-1]
                ]
                where = " AND ".join(f"{name} = ?" for name in locator)
                connection.executemany(
                    f"UPDATE OR IGNORE {table} SET {column} = ? WHERE {where}", column_updates
                )
                changed += len(column_updates)
            counts[table] = changed
        connection.commit()
        if any(counts.values()):
            connection.execute("VACUUM")
    finally:
        connection.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    arguments = parser.parse_args()
    counts = normalize_database(arguments.database)
    summary = " ".join(f"{key}={value}" for key, value in counts.items())
    print(f"symbol glyphs normalized: {summary}")


if __name__ == "__main__":
    main()
