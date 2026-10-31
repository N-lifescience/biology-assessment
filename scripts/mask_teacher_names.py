"""Mask teachers' names in a publish DB before it is packaged for the site.

A school's plan names its teachers ("지도교사: 홍길동", ``담당교사 │ 홍길동``),
and the site shows the plan's tables as the school published them.  The
archive is about assessments, not people: the published copy replaces each
such name with "○○○".  The archived full text keeps the original.

Usage:
    python scripts/mask_teacher_names.py \
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
MASK = "○○○"

# A role title naming the teacher who holds it ("지도교사", "평가교사",
# "공동 채점교사", "교과담당교사"), not a bare "교사:" that opens a sentence
# about what the teacher does in class ("교사: 학생 간의 상호작용 관찰").
TEACHER_LABEL = (
    r"(?:지도|담당|교과\s*담당|수업\s*담당|평가|출제|채점|공동\s*(?:채점|출제)|검토|담임"
    # "보충지도 수업 교사 │ 홍길동", "평가 및 기록: 교사 홍길동"(일화기록 서식)
    r"|보충\s*(?:지도\s*)?(?:수업\s*)?|기록\s*[:：]\s*)\s*교\s*사(?:\s*명)?"
    r"|교\s*사\s*명"
)
NAME = r"(?<![가-힣0-9])[가-힣]{2,4}(?![가-힣ⅠⅡⅢ0-9])"
# "김민주 (1학년), 김진옥 (2,3학년)", "신용주(국악과)": a tag on each name.
TAGGED_NAME = NAME + r"(?:\s*\([^()<>]{1,12}\))?"
NAME_LIST = TAGGED_NAME + r"(?:(?:\s*[,，]\s*|/\s*|·)" + TAGGED_NAME + ")*"
# "지도교사(강사)": a role tag after the title.
ROLE_TAG = r"(?:\s*\([가-힣]{1,4}\))?"
LABEL_THEN_NAMES_RE = re.compile(
    "((?:" + TEACHER_LABEL + ")" + ROLE_TAG + r"\s*(?:[:：]\s*(?:/\s*)?(?:</t[dh]>\s*<t[dh][^>]*>\s*)?|\s·\s+"
    r"|(?:</t[dh]>|<br\s*/?>)\s*(?:<t[dh][^>]*>)?\s*"
    # …also a table the converter escaped into a cell ("&lt;td&gt;담당교사&lt;/td&gt;&lt;td&gt;…")
    r"|&lt;/t[dh]&gt;\s*(?:&lt;t[dh][^&]*&gt;)?\s*|\s+))"
    # " · " between names is a cell boundary in flattened text, not a list.
    "(" + NAME_LIST + ")"
)
# "담당교사 홍길동 김은정 / …": names spaced apart to the end of a flattened row.
SPACED_ROW_NAMES_RE = re.compile(
    # (a name the label rule already masked still belongs to the run)
    "((?:" + TEACHER_LABEL + ")" + ROLE_TAG + r"\s+)((?:(?:[가-힣]{3}|○○○)\s+)+(?:[가-힣]{3}|○○○))"
    r"(?=\s*(?: / |\n|\|\||$))"
)
# "<p>1. 담당교사</p><p>김동연</p>": the title and the names in two paragraphs
# (or headings: "<h4>1. 담당교사</h4><h4>김동연</h4>").
# Only a paragraph that holds nothing but names counts.
PARAGRAPH_LABEL_THEN_NAMES_RE = re.compile(
    "((?:" + TEACHER_LABEL + r")\s*[:：]?\s*</(?:p|h[1-6])>\s*<(?:p|h[1-6])\b[^>]*>\s*)(" + NAME_LIST + r")"
    r"(?=\s*</(?:p|h[1-6])>)"
)
# "강정민 (인)": a name before a seal mark is a signature wherever it stands
# (also in a case summary that lost the table it was signed in).
SEAL_NAME_RE = re.compile(r"(?<![가-힣])([가-힣]{2,4})(\s*\(인\))")
# A form's blank signature line ("성명 (인)", "보호자 (인)") names nobody.
SEAL_FIELD_WORDS = frozenset({"성명", "이름", "서명", "보호자", "학부모", "담임", "교사", "학생", "확인"})
BRACKETED_RE = re.compile(r"\([^()]*\)")
# A table column or row headed by a teacher title ("지도교사", "담당 교사",
# "출제교사"): its cells that hold only names are the teachers.
TEACHER_HEADER_RE = re.compile(
    r"(?:지도|담당|교과담당|수업담당|평가|출제|채점|공동채점|공동출제|담임)?교사(?:명)?(?:\([가-힣]{1,4}\))?|담당|성명"
)
TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.S | re.I)
ROW_RE = re.compile(r"(<tr\b[^>]*>)(.*?)(</tr>)", re.S | re.I)
CELL_RE = re.compile(r"(<(t[dh])\b([^>]*)>)(.*?)(</\2>)", re.S | re.I)
LISTED_NAMES_RE = re.compile(r"\s*" + NAME + r"(?:\s*[,，·/]\s*" + NAME + r")*\s*[,，/]?\s*")
NAME_RE = re.compile(NAME)
NAME_TAG_RE = re.compile(r"(?<=[가-힣])\s*\([가-힣]{1,3}\)")
# Words that follow a role title and are not anyone's name.
NOT_A_NAME = frozenset(
    {
        "교사", "선생님", "없음", "전원", "공통", "협의", "배정", "미정", "전체", "각반", "각자",
        "본인", "담당", "학년", "학급", "과목", "교과", "관찰", "평가", "반영비율", "날인", "교무",
        "기록", "확인", "서명", "결재", "작성", "학생", "의견", "지도", "수업", "채점", "기준",
        "협의회", "별도", "교사가", "전체교사", "해당", "동일", "공동", "모든", "각", "교과별",
        "모두", "허가", "또는", "추천", "출석통계", "및", "등", "교감", "교장", "진로", "시기",
        "학기", "성함", "동시", "성취도", "일반", "선택", "대상", "학교명", "과목명", "비고",
    }
)


def _is_name(word: str, *, listed: bool = False) -> bool:
    """A name, unless a stop word; a lone word after a space also not a particle phrase.

    After a colon, in the next table cell or within a comma list ("홍길동,
    김은정, 이철수") every word is a name; "담당교사 전원이" is not.
    """

    # Column labels a header row puts beside the teacher column ("평가영역",
    # "주당시수", "과목유형", "교무부장").
    if word in NOT_A_NAME or re.search(
        # Not "이수": 이수현 is a name; 이수학점·이수단위·이수시간 end in a column word.
        r"^(?:평가|학습|수업|교과|운영|주당|교육|담당|과목|성취|교무)"
        r"|(?:시수|학점|단위|시간|비고|기타|학급|유형|과정|부장|여부|편제|단계|등급|방법|영역|기준|목표|계획)$",
        word,
    ):
        return False
    return listed or not re.search(r"(?:을|를|의|에|로|와|과|이|가|은|는|하여|하고)$", word)


def _seal_name(word: str) -> bool:
    return word not in SEAL_FIELD_WORDS and _is_name(word, listed=True)


def _listed(match: re.Match[str]) -> bool:
    return bool(
        re.search(r"[:：·]|</t[dh]>|<br|</p>", match.group(1))
        or re.search(r"[,，·/]", BRACKETED_RE.sub(" ", match.group(2)))
    )


def _mask_names(names: str, *, listed: bool) -> str:
    # A bracketed tag ("(국악과)", "(1학년)") is not a name.
    return "".join(
        part if BRACKETED_RE.fullmatch(part) else NAME_RE.sub(
            lambda match: MASK if _is_name(match.group(0), listed=listed) else match.group(0), part
        )
        for part in re.split(r"(\([^()]*\))", names)
    )


def _cell_text(content: str) -> str:
    return re.sub(r"<[^>]+>", " ", content).replace("&nbsp;", " ")


def _names_only(content: str) -> bool:
    """A cell holding nothing but names: "홍길동", "홍길동, 김은정", "이영희/ 김철수".

    Words joined only by spaces count when each is a three-syllable name
    ("홍길동 김은정"); "자연 현상에 대한 탐구" is a sentence.
    """

    # "홍길동(사)": a name tagged with the teacher's subject.
    shown = NAME_TAG_RE.sub("", _cell_text(content)).strip()
    # A name already masked keeps the column going.
    if shown and re.fullmatch(r"(?:○+[\s,，/·]*)+", shown):
        return True
    # "장 한": a name the converter spaced apart.
    if re.fullmatch(r"[가-힣](?:\s[가-힣]){1,3}", shown):
        return True
    words = [word for word in re.split(r"[\s,，/·]+", shown) if word]
    if not words or not all(re.fullmatch(r"[가-힣]{2,4}", word) for word in words):
        return False
    if re.search(r"[,，/·]", shown) or len(words) == 1:
        return all(_is_name(word, listed=True) for word in words)
    return all(len(word) == 3 and _is_name(word) for word in words)


def _teacher_cells(table: str) -> list[tuple[int, int]]:
    """Spans of the cells under a teacher column or after a teacher row title."""

    spans: list[tuple[int, int]] = []
    columns: set[int] = set()
    carried: dict[int, int] = {}  # column -> rows a rowspan above still covers
    for row in ROW_RE.finditer(table):
        position = 0
        cells = []
        below: dict[int, int] = {}
        for cell in CELL_RE.finditer(row.group(2)):
            while carried.get(position, 0) > 0:
                position += 1
            span = re.search(r"colspan\s*=\s*\"?(\d+)", cell.group(3))
            width = int(span.group(1)) if span else 1
            down = re.search(r"rowspan\s*=\s*\"?(\d+)", cell.group(3))
            for column in range(position, position + width):
                if down and int(down.group(1)) > 1:
                    below[column] = int(down.group(1)) - 1
            cells.append((position, width, cell))
            position += width
        carried = {
            column: rows - 1 for column, rows in carried.items() if rows - 1 > 0
        } | below
        header_here = {
            column
            for start, width, cell in cells
            if TEACHER_HEADER_RE.fullmatch(re.sub(r"\s+", "", _cell_text(cell.group(4))))
            for column in range(start, start + width)
        }
        row_title = bool(cells) and bool(
            TEACHER_HEADER_RE.fullmatch(re.sub(r"\s+", "", _cell_text(cells[0][2].group(4))))
        )
        offset = row.start(2)
        named_under_column = False
        for index, (start, width, cell) in enumerate(cells):
            under_column = not header_here and any(
                column in columns for column in range(start, start + width)
            )
            if (under_column or (row_title and index > 0)) and _names_only(cell.group(4)):
                spans.append((offset + cell.start(4), offset + cell.end(4)))
                named_under_column |= under_column
        # The names sit right under their header; a row with none ends the column.
        columns = header_here or (columns if named_under_column else set())
    return spans


SPACED_NAME_RE = re.compile(r"\s*[가-힣](?:\s[가-힣]){1,3}\s*")


def _mask_cell(content: str) -> str:
    if SPACED_NAME_RE.fullmatch(_cell_text(content)):
        return MASK
    return _mask_names(content, listed=True)


def _cell_names(content: str) -> list[str]:
    shown = _cell_text(content)
    if SPACED_NAME_RE.fullmatch(shown):
        return [re.sub(r"\s+", "", shown)]
    return [word for word in NAME_RE.findall(shown) if _is_name(word, listed=True)]


FLAT_ROW_RE = re.compile(r" / |\n")
SUBJECT_HEADER_RE = re.compile(r"(?:세부)?(?:교과목|과목|교과)(?:명)?(?:\(.*\))?")
FLAT_CELL_RE = re.compile(r" · ")


def _flat_cells(text: str, start: int, end: int) -> list[tuple[int, int]]:
    cells = []
    for separator in FLAT_CELL_RE.finditer(text, start, end):
        cells.append((start, separator.start()))
        start = separator.end()
    cells.append((start, end))
    return cells


def _flat_teacher_cells(text: str) -> list[tuple[int, int]]:
    """Spans of the names under a teacher heading in a table flattened to text.

    A case summary keeps a plan's table as "대상 · 학기 · 담당 교사 / 2 · 4 ·
    홍길동, 김은정": " / " ends a row, " · " a cell.  A row shorter than its
    heading row lost its leading merged cells, so the two line up from the right;
    a longer one is not that heading's row.
    """

    spans: list[tuple[int, int]] = []
    rows = []
    start = 0
    for separator in FLAT_ROW_RE.finditer(text):
        rows.append(_flat_cells(text, start, separator.start()))
        start = separator.end()
    rows.append(_flat_cells(text, start, len(text)))
    for header, cells in zip(rows, rows[1:]):
        if len(header) < 2 or len(cells) > len(header):
            continue
        for index, (head_start, head_end) in enumerate(header):
            if not TEACHER_HEADER_RE.fullmatch(re.sub(r"\s+", "", text[head_start:head_end])):
                continue
            target = index if len(cells) == len(header) else len(cells) - (len(header) - index)
            # "학교명 · 학년 · 과목 · 지도교사 / ○○고 · 1학년 · 한국사": the row lost its
            # last cell instead, and the subject sits under its own heading.
            if target != index and SUBJECT_HEADER_RE.fullmatch(
                re.sub(r"\s+", "", text[slice(*header[target])])
            ):
                continue
            if 0 <= target < len(cells) and _names_only(text[slice(*cells[target])]):
                spans.append(cells[target])
    return spans


def _mask_flat_rows(text: str) -> str:
    for start, end in sorted(_flat_teacher_cells(text), reverse=True):
        text = text[:start] + _mask_cell(text[start:end]) + text[end:]
    return text


def _mask_tables(text: str) -> str:
    pieces = []
    last = 0
    for table in TABLE_RE.finditer(text):
        body = table.group(0)
        masked = body
        for start, end in reversed(_teacher_cells(body)):
            masked = masked[:start] + _mask_cell(masked[start:end]) + masked[end:]
        pieces.append(text[last : table.start()])
        pieces.append(masked)
        last = table.end()
    pieces.append(text[last:])
    return "".join(pieces)


def mask_teacher_names(text: str) -> str:
    """Replace the names after every 교사 label and in every teacher column of ``text``."""

    text = SEAL_NAME_RE.sub(
        lambda match: MASK + match.group(2) if _seal_name(match.group(1)) else match.group(0), text
    )
    if "교" not in text and "성명" not in text and "담당" not in text:
        return text
    text = LABEL_THEN_NAMES_RE.sub(
        lambda match: match.group(1) + _mask_names(match.group(2), listed=_listed(match)), text
    )
    for pattern in (PARAGRAPH_LABEL_THEN_NAMES_RE, SPACED_ROW_NAMES_RE):
        text = pattern.sub(
            lambda match: match.group(1) + _mask_names(match.group(2), listed=True), text
        )
    if "<table" in text.lower():
        return _mask_tables(text)
    return _mask_flat_rows(text) if " · " in text else text


def teacher_names_left(text: str) -> list[str]:
    """Names still standing after a 교사 label or in a teacher column (what the gate rejects)."""

    text = text or ""
    found = [match.group(1) for match in SEAL_NAME_RE.finditer(text) if _seal_name(match.group(1))]
    for table in TABLE_RE.finditer(text):
        for start, end in _teacher_cells(table.group(0)):
            found.extend(_cell_names(table.group(0)[start:end]))
    if "<table" not in text.lower():
        for start, end in _flat_teacher_cells(text):
            found.extend(_cell_names(text[start:end]))
    for match in LABEL_THEN_NAMES_RE.finditer(text):
        listed = _listed(match)
        found.extend(
            word
            for word in NAME_RE.findall(BRACKETED_RE.sub(" ", match.group(2)))
            if _is_name(word, listed=listed)
        )
    for match in (
        *PARAGRAPH_LABEL_THEN_NAMES_RE.finditer(text),
        *SPACED_ROW_NAMES_RE.finditer(text),
    ):
        found.extend(
            word
            for word in NAME_RE.findall(BRACKETED_RE.sub(" ", match.group(2)))
            if _is_name(word, listed=True)
        )
    return found


def mask_database(database: Path) -> dict[str, int]:
    connection = sqlite3.connect(database)
    counts = {"items": 0, "cases": 0}
    try:
        updates = []
        for item_id, source, rubric in connection.execute(
            "SELECT item_id, source_html_zlib, rubric_html_zlib FROM assessment_items"
        ):
            new_blobs = []
            changed = False
            for blob in (source, rubric):
                if blob is None:
                    new_blobs.append(None)
                    continue
                text = zlib.decompress(blob).decode("utf-8")
                masked = mask_teacher_names(text)
                changed |= masked != text
                new_blobs.append(zlib.compress(masked.encode("utf-8")) if masked != text else blob)
            if changed:
                updates.append((new_blobs[0], new_blobs[1], item_id))
        connection.executemany(
            "UPDATE assessment_items SET source_html_zlib = ?, rubric_html_zlib = ? "
            "WHERE item_id = ?",
            updates,
        )
        counts["items"] = len(updates)
        text_columns = ("evidence_excerpt", "summary_overview")
        case_updates = []
        for row in connection.execute(f"SELECT case_id, {', '.join(text_columns)} FROM cases"):
            masked = [mask_teacher_names(value or "") for value in row[1:]]
            if masked != [value or "" for value in row[1:]]:
                case_updates.append((*masked, row[0]))
        connection.executemany(
            f"UPDATE cases SET {', '.join(f'{column} = ?' for column in text_columns)} "
            "WHERE case_id = ?",
            case_updates,
        )
        counts["cases"] = len(case_updates)
        connection.commit()
        if updates or case_updates:
            connection.execute("VACUUM")
    finally:
        connection.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    arguments = parser.parse_args()
    counts = mask_database(arguments.database)
    print(f"teacher names masked: items={counts['items']} cases={counts['cases']}")


if __name__ == "__main__":
    main()
