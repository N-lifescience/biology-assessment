"""Build the read-only SQLite publish databases the API serves.

Schema and query shapes are dictated entirely by
``services/biology-assessment-api/app/repository.py`` (read first, not
guessed). ``cases``/``subject_stats``/``subject_action_tags`` are populated
from real reprocessing-pipeline output. When ``--evidence-source`` is given,
``assessment_items``/``assessment_item_rankings``/``case_detail_status`` are
also populated by parsing each case's full source document with
``biology_assessment_detail_parser.parse_assessment_section``; only cases
where the parser finds a confident, source-bounded first item get
``cases.title_basis`` upgraded to ``"source_detail"``
(``"source_detail_bundle_review"`` for a found-but-unbounded section).
Everything else keeps the honest ``"catalog_only"`` value so confirmed-only
endpoints (``/api/v1/cases``, ``/api/v1/cases/{id}``) never fabricate a
title. ``/api/v1/subjects`` and ``/api/v1/trends`` are unaffected either way.

The catalog and detail databases get identical content: this pipeline only
produces one dataset, so there is nothing distinct to put in the "detail"
file. See ``app/settings.py`` for why both paths are checked.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import shutil
import sqlite3
import time
import zlib
from html.parser import HTMLParser
from pathlib import Path

SCHEMA = """
CREATE TABLE cases (
    case_id TEXT PRIMARY KEY,
    curriculum TEXT NOT NULL,
    subject TEXT NOT NULL,
    curriculum_basis TEXT NOT NULL,
    school_name TEXT NOT NULL,
    region TEXT NOT NULL,
    district TEXT NOT NULL,
    academic_years_json TEXT NOT NULL,
    grades_json TEXT NOT NULL,
    semesters_json TEXT NOT NULL,
    primary_task_name TEXT NOT NULL,
    task_names_json TEXT NOT NULL,
    action_tags_json TEXT NOT NULL,
    rubric_marker_count INTEGER NOT NULL,
    achievement_standard_marker_count INTEGER NOT NULL,
    weight_or_points_marker_count INTEGER NOT NULL,
    assessment_method_marker_count INTEGER NOT NULL,
    review_score INTEGER NOT NULL,
    evidence_excerpt TEXT NOT NULL,
    summary_overview TEXT NOT NULL,
    methods_json TEXT NOT NULL,
    weight_summary TEXT NOT NULL,
    standards_json TEXT NOT NULL,
    criteria_json TEXT NOT NULL,
    title_basis TEXT NOT NULL,
    category TEXT NOT NULL,
    priority_score INTEGER NOT NULL,
    priority_signals_json TEXT NOT NULL,
    candidate_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_sha256 TEXT NOT NULL
);
CREATE INDEX idx_cases_curriculum_subject ON cases(curriculum, subject);
CREATE INDEX idx_cases_category ON cases(category);

CREATE TABLE subject_stats (
    curriculum TEXT NOT NULL,
    subject TEXT NOT NULL,
    documents INTEGER NOT NULL,
    schools INTEGER NOT NULL,
    small_sample INTEGER NOT NULL,
    academic_years_json TEXT NOT NULL,
    grade1_documents INTEGER NOT NULL,
    grade2_documents INTEGER NOT NULL,
    grade3_documents INTEGER NOT NULL,
    rubric_documents INTEGER NOT NULL,
    achievement_standard_documents INTEGER NOT NULL,
    weight_or_points_documents INTEGER NOT NULL,
    assessment_method_documents INTEGER NOT NULL,
    median_review_score REAL,
    task_name_candidates INTEGER NOT NULL,
    coverage_found INTEGER,
    coverage_ambiguous INTEGER,
    coverage_not_found INTEGER,
    coverage_offering_unknown INTEGER,
    coverage_extraction_failed INTEGER,
    PRIMARY KEY (curriculum, subject)
);

CREATE TABLE subject_action_tags (
    curriculum TEXT NOT NULL,
    subject TEXT NOT NULL,
    tag TEXT NOT NULL,
    document_count INTEGER NOT NULL,
    school_count INTEGER NOT NULL
);
CREATE INDEX idx_subject_action_tags ON subject_action_tags(curriculum, subject);

CREATE TABLE assessment_items (
    item_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    item_order INTEGER NOT NULL,
    title TEXT NOT NULL,
    title_raw TEXT NOT NULL,
    title_basis TEXT NOT NULL,
    extraction_status TEXT NOT NULL,
    overview TEXT NOT NULL,
    method TEXT NOT NULL,
    timing TEXT NOT NULL,
    score TEXT NOT NULL,
    weight TEXT NOT NULL,
    standards_json TEXT NOT NULL,
    rubric_html_char_count INTEGER NOT NULL,
    source_html_zlib BLOB,
    rubric_html_zlib BLOB
);
CREATE INDEX idx_assessment_items_case_id ON assessment_items(case_id);

CREATE TABLE assessment_item_rankings (
    item_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    priority_score INTEGER NOT NULL,
    priority_signals_json TEXT NOT NULL
);

CREATE TABLE case_detail_status (
    case_id TEXT PRIMARY KEY,
    source_format TEXT NOT NULL,
    boundary_status TEXT NOT NULL,
    source_section_char_count INTEGER NOT NULL
);
"""

UNCONFIRMED_TASK_NAME = "구체적 과제명 미탐지"
# (action tag, source-text pattern, category). The tag strings must stay equal
# to the upstream keys in ``build_biology_assessment_evidence_index.ACTION_TAGS``
# because ``cases.action_tags_json`` carries those exact strings; the patterns
# repeat the upstream spellings so item-level text scanning tolerates the
# spacing the source documents actually use ("생태 조사", "문제 해결"). Kept in
# the same relative order as upstream ``ACTION_TAGS`` (case-level classifier)
# minus 생태조사: too few bounded items (16 corpus-wide) to carry its own
# reference tab, decided with the project owner 2026-08-21.
CATEGORY_TAG_ORDER = [
    ("탐구", re.compile(r"탐구"), "inquiry"),
    ("프로젝트", re.compile(r"프로젝트"), "project"),
    ("문제해결", re.compile(r"문제\s*해결"), "problem"),
    ("발표", re.compile(r"발표"), "presentation"),
    ("토론", re.compile(r"토론"), "debate"),
    ("포트폴리오", re.compile(r"포트폴리오"), "portfolio"),
    ("보고서", re.compile(r"보고서"), "reading"),
    ("제작", re.compile(r"제작"), "production"),
    ("실험", re.compile(r"실험"), "experiment"),
]
# ponytail: a school count below this is treated as too small to publish
# per-school detail confidently. No official threshold was handed off.
SMALL_SAMPLE_SCHOOL_THRESHOLD = 3


class _HTMLTableExtractor(HTMLParser):
    """Collect every ``<table>``'s cell text, including nested tables."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._tables: list[list[list[str]]] = []
        self._rows: list[list[str]] = []
        self._cells: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._tables.append([])
        elif tag == "tr" and self._tables:
            self._rows.append([])
        elif tag in ("td", "th") and self._rows:
            self._cells.append([])
        elif tag == "br" and self._cells:
            self._cells[-1].append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br" and self._cells:
            self._cells[-1].append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("td", "th") and self._cells:
            text = "".join(self._cells.pop()).strip()
            if self._rows:
                self._rows[-1].append(text)
        elif tag == "tr" and self._rows:
            row = self._rows.pop()
            if self._tables:
                self._tables[-1].append(row)
        elif tag == "table" and self._tables:
            self.tables.append(self._tables.pop())

    def handle_data(self, data: str) -> None:
        if self._cells:
            self._cells[-1].append(data)


def html_tables(value: str) -> list[list[list[str]]]:
    """Parse HTML fragments into tables of rows of cell text.

    Uses the stdlib ``html.parser`` (already a dependency here via
    ``_SafeTableParser`` in ``biology_assessment_detail_parser.py``) rather
    than adding an HTML-parsing library for what is a small, self-contained
    extraction.
    """

    extractor = _HTMLTableExtractor()
    extractor.feed(value)
    extractor.close()
    return extractor.tables


def compact_text(value: str) -> str:
    """Collapse whitespace/punctuation for label and dedup comparisons."""

    return re.sub(r"[^0-9A-Za-z가-힣ⅠⅡⅢⅣⅤ]", "", value)


def plain_text(value: str) -> str:
    """Flatten HTML (tables included) into pipe-joined lines for regex scanning.

    Each table row becomes one ``cell | cell | cell`` line so downstream
    label/value scanning can treat a real ``<table>`` row the same way as a
    plain-text pseudo-row copied out of a PDF.
    """

    def render_table(match: re.Match[str]) -> str:
        lines = []
        for table in html_tables(match.group(0)):
            for row in table:
                cells = [re.sub(r"\s+", " ", cell).strip() for cell in row]
                cells = [cell for cell in cells if cell]
                if cells:
                    lines.append(" | ".join(cells))
        return "\n" + "\n".join(lines) + "\n"

    text = re.sub(r"<table\b.*?</table>", render_table, value, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


# --- task-name normalization -------------------------------------------------

LEADING_NUMBERING_RE = re.compile(
    r"^(?:\d+\s*\.\s*|[IVX]{1,4}\s*\.\s*|[가나다라마바사아자차카타파하]\s*[.)]\s*)+"
)
LEADING_LABEL_RE = re.compile(
    r"^★?\s*(?:수행평가명|수행평가영역|수행평가과제명|수행평가|평가영역|과제명)"
    r"\s*[:：\-–—]?\s*"
)
TRAILING_PAREN_NUMBER_RE = re.compile(r"\s*\(\s*\d+\s*\)\s*$")
TRAILING_COUNT_RE = re.compile(r"\s*\d+\s*회\s*$")
TRAILING_SCORE_SUFFIX_RE = re.compile(r"\s*[:：]\s*[0-9][0-9.,%~점\s]*$")

# ponytail: only the one PDF word-split observed in fixtures is repaired here;
# extend this map if another glued-then-split word turns up.
STRAY_SPACE_JOIN_RE = {re.compile(r"적\s+용"): "적용"}

# Known multi-char tokens used to re-segment a run of Korean text that a PDF/
# HWP converter glued together with no spaces at all. A chunk is only ever
# rewritten when it can be *fully* consumed by these tokens end to end, so an
# unrelated compound (e.g. "수학칼럼쓰기") that only partially matches is left
# untouched rather than partially split.
TASK_NAME_WORD_DICTIONARY = (
    "이용한",
    "모델링", "프로젝트", "보고서",
    "독서", "기반", "탐구", "활동", "해결", "교과", "융합",
    "도서", "문제", "분석", "만들기", "풀이", "주제", "발표",
    "생명과학", "생태계", "보전", "방안", "돌연변이", "생성",
    "식물", "세포", "관찰", "실험",
)


def _segment_glued_chunk(chunk: str) -> str:
    tokens: list[str] = []
    position = 0
    while position < len(chunk):
        match = next(
            (
                word
                for word in TASK_NAME_WORD_DICTIONARY
                if chunk.startswith(word, position)
            ),
            None,
        )
        if match is None:
            return chunk
        tokens.append(match)
        position += len(match)
    return " ".join(tokens) if len(tokens) >= 2 else chunk


HTML_ATTR_ARTIFACT_RE = re.compile(r'(?:\w+\s+)?(?:row|col|l)?span\s*=\s*"[^"]*"\s*>?')
GFEDC_ARTIFACT_RE = re.compile(r"\bgfedc\b")


def normalize_task_name(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    text = HTML_ATTR_ARTIFACT_RE.sub("", text)
    text = GFEDC_ARTIFACT_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = LEADING_NUMBERING_RE.sub("", text)
    text = LEADING_LABEL_RE.sub("", text)
    for pattern, replacement in STRAY_SPACE_JOIN_RE.items():
        text = pattern.sub(replacement, text)
    for _ in range(2):
        text = TRAILING_SCORE_SUFFIX_RE.sub("", text)
        text = TRAILING_COUNT_RE.sub("", text)
        text = TRAILING_PAREN_NUMBER_RE.sub("", text)
    text = text.strip()
    chunks = [_segment_glued_chunk(chunk) for chunk in text.split(" ") if chunk]
    return " ".join(chunks)


# --- task-name rejection ------------------------------------------------------

CHECKBOX_RE = re.compile(r"[☑☐□◻■]")
STAR_MARK_RE = re.compile(r"[★☆※]")
HTML_TAG_SHAPE_RE = re.compile(r"</|/>|<\s*[A-Za-z][^>]*>")
# Bullet markers only count when they open a line/segment (leading or after
# whitespace) -- a Korean word-separator dot ("소화·순환·호흡") uses the same
# glyph mid-word and must not be mistaken for an enumerated list.
BULLET_MARK_RE = re.compile(r"(?:^|\s)[▪∙◦‣•·]")
LEADING_ROMAN_RE = re.compile(r"^[IVX]{1,4}\s*\.\s*")
MID_ENUMERATION_RE = re.compile(r"[가-힣]\s+\d+\s*\.\s*[가-힣]")
SCORE_OR_CREDIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*[~-]\s*\d+(?:\.\d+)?\s*점"
    r"|\d+\s*점\s*[x×]\s*\d"
    r"|=\s*\d+\s*점"
    r"|\(\s*\d+\s*학점\s*\)"
    r"|^(?:반영\s*만점|배점|영역\s*만점)"
    r"|\d+(?:\.\d+)?\s*점\s*이하"
)
EXAM_LABEL_RE = re.compile(
    r"^(?:제?\d*\s*[차회]?\s*)?(?:중간|기말|정기)?\s*(?:고사|시험)(?:\s*\([^)]*\))?$"
)
ADMIN_TERM_RE = re.compile(
    r"부정행위|결시자|미응시자|학적\s*변동|성적\s*처리|이의\s*신청|"
    r"출제\s*의도|학기말\s*합계|재응시|결과물\s*보존"
)
DECLARATIVE_SENTENCE_RE = re.compile(r"(?:다|음|함|됨)\.\s*(?:\([^)]*\))?(?:\s|$)")
FIELD_LABEL_MARKERS = (
    "평가방법",
    "평가항목",
    "학생유의사항",
    "점수부여",
    "배점기준",
    "채점기준",
    "반영만점",
    "영역만점",
)
REJECT_ENDING_WORDS = (
    "평가",
    "항목",
    "기준",
    "사항",
    "횟수",
    "신장",
    "내용",
    "흥미도",
)
SHORT_COMMA_LIST_RE = re.compile(r"^[가-힣·]{2,10}(?:\s*,\s*[가-힣·]{2,10}){1,3}$")
SHORT_AND_PAIR_RE = re.compile(r"^[가-힣·]{2,8}\s*및\s*[가-힣·]{2,8}$")
DANGLING_PARTICLE_RE = re.compile(r"[가-힣]\s[을를이가은는의과와도로에]$")
GENERIC_BARE_NOUNS = {
    "프로젝트",
    "포트폴리오",
    "보고서",
    "발표",
    "탐구",
    "조사",
    "활동",
    "과제",
    "수행평가",
    "제작",
    "글쓰기",
    "토론",
    "관찰",
}
# ponytail: literal denylist for phrases that don't reduce to any general
# rule above (course/unit names, one-off generic labels). Extend it, don't
# loosen a rule above, when a new false-accept turns up.
COMPACT_REJECT_SET = {
    "과제탐구",
    "교수학습활동",
    "관찰평가포트폴리오",
    "추가적인분량탐구활동",
    "화법과작문과정형포트폴리오제작",
}


def task_name_is_rejected(text: str) -> bool:
    stripped = re.sub(r"\s+", " ", text).strip()
    if not stripped:
        return True
    compact = compact_text(stripped)
    if compact in COMPACT_REJECT_SET:
        return True
    if CHECKBOX_RE.search(stripped) or STAR_MARK_RE.search(stripped):
        return True
    if HTML_TAG_SHAPE_RE.search(stripped):
        return True
    if stripped.startswith("[zip:"):
        return True
    if len(BULLET_MARK_RE.findall(stripped)) >= 2:
        return True
    if len(re.findall(r"\d{1,2}\s*\.\s*\d{1,2}\s*\([월화수목금토일]\)", stripped)) >= 2:
        return True
    if LEADING_ROMAN_RE.match(stripped):
        return True
    if MID_ENUMERATION_RE.search(stripped):
        return True
    if any(marker in compact for marker in FIELD_LABEL_MARKERS):
        return True
    if SCORE_OR_CREDIT_RE.search(stripped) or EXAM_LABEL_RE.match(stripped):
        return True
    if ADMIN_TERM_RE.search(stripped) or DECLARATIVE_SENTENCE_RE.search(stripped):
        return True
    if any(stripped.endswith(word) for word in REJECT_ENDING_WORDS):
        return True
    if SHORT_COMMA_LIST_RE.match(stripped) or SHORT_AND_PAIR_RE.match(stripped):
        return True
    if stripped.count(",") >= 2 and "및" in stripped:
        return True
    if DANGLING_PARTICLE_RE.search(stripped):
        return True
    chunks = stripped.split(" ")
    if chunks and all(compact_text(chunk) in GENERIC_BARE_NOUNS for chunk in chunks):
        return True
    return False


class _HTMLSpanTableExtractor(HTMLParser):
    """Like ``_HTMLTableExtractor`` but keeps each cell's rowspan/colspan."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[tuple[str, int, int]]]] = []
        self._tables: list[list[list[tuple[str, int, int]]]] = []
        self._rows: list[list[tuple[str, int, int]]] = []
        self._cells: list[list[str]] = []
        self._cell_spans: list[tuple[int, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._tables.append([])
        elif tag == "tr" and self._tables:
            self._rows.append([])
        elif tag in ("td", "th") and self._rows:
            self._cells.append([])
            attr_map = {key.lower(): (value or "") for key, value in attrs}

            def span(name: str) -> int:
                try:
                    return max(1, int(attr_map.get(name, "1")))
                except ValueError:
                    return 1

            self._cell_spans.append((span("rowspan"), span("colspan")))
        elif tag == "br" and self._cells:
            self._cells[-1].append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br" and self._cells:
            self._cells[-1].append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("td", "th") and self._cells:
            text = "".join(self._cells.pop()).strip()
            rowspan, colspan = self._cell_spans.pop()
            if self._rows:
                self._rows[-1].append((text, rowspan, colspan))
        elif tag == "tr" and self._rows:
            row = self._rows.pop()
            if self._tables:
                self._tables[-1].append(row)
        elif tag == "table" and self._tables:
            self.tables.append(self._tables.pop())

    def handle_data(self, data: str) -> None:
        if self._cells:
            self._cells[-1].append(data)


def _expand_table_grid(rows: list[list[tuple[str, int, int]]]) -> list[list[str]]:
    grid: list[dict[int, str]] = []
    pending: dict[int, tuple[str, int]] = {}
    for row in rows:
        grid_row: dict[int, str] = {}
        col = 0
        cell_index = 0
        max_col_needed = max(pending.keys(), default=-1)
        while cell_index < len(row) or col <= max_col_needed:
            if col in pending:
                text, remaining = pending[col]
                grid_row[col] = text
                if remaining <= 1:
                    del pending[col]
                else:
                    pending[col] = (text, remaining - 1)
                col += 1
                continue
            if cell_index < len(row):
                text, rowspan, colspan = row[cell_index]
                cell_index += 1
                for offset in range(colspan):
                    grid_row[col + offset] = text
                    if rowspan > 1:
                        pending[col + offset] = (text, rowspan - 1)
                col += colspan
                max_col_needed = max(max_col_needed, col - 1)
            else:
                col += 1
        grid.append(grid_row)
    width = max((max(row.keys(), default=-1) for row in grid), default=-1) + 1
    return [[row.get(col, "") for col in range(width)] for row in grid]


def html_table_grids(value: str) -> list[list[list[str]]]:
    """Parse HTML tables into a rowspan/colspan-expanded grid per table."""

    extractor = _HTMLSpanTableExtractor()
    extractor.feed(value)
    extractor.close()
    return [_expand_table_grid(rows) for rows in extractor.tables]


TASK_LABEL_MARKERS = (
    "수행평가명",
    "수행평가과제명",
    "수행평가영역",
    "수행평가과제",
    "평가과제명",
    "평가과제",
    "평가영역",
    "과제명",
    "수행평가",
)
FIELD_STOP_LABELS = {
    compact_text(label)
    for label in (
        "반영비율",
        "성취기준",
        "평가시기",
        "평가방법",
        "배점",
        "만점",
        "총점",
        "채점기준",
        "평가요소",
        "평가항목",
        "평가내용",
        "평가방식",
        "평가만점",
        "성취수준",
        "기준영역",
        "구분",
        "시기",
        "학기",
        "영역만점",
        "부여점수",
    )
}
FOREIGN_COURSE_HEADING_RE = re.compile(r"교수학습.*평가.*(?:계획|운영)")
HEADING_RE = re.compile(r"^[ \t]*#+[ \t]+(.+?)[ \t]*$", re.M)


def _looks_like_task_label(cell: str) -> bool:
    compact = compact_text(cell)
    return bool(compact) and any(marker in compact for marker in TASK_LABEL_MARKERS)


def _localize_subject_section(evidence: str, subject: str) -> str:
    """Return only the part of ``evidence`` that plausibly belongs to ``subject``.

    A combined Schoolinfo attachment often lists several subjects' plans one
    after another under a heading such as ``# ...과 교수학습 및 평가 운영
    계획``. Only headings that look like such a course-plan boundary are used
    to cut the document; a heading that is merely internal document structure
    (e.g. ``## 1) 과제 이름``) never truncates the section.
    """

    headings = [(m.start(), m.group(1)) for m in HEADING_RE.finditer(evidence)]
    course_headings = [
        (start, text)
        for start, text in headings
        if FOREIGN_COURSE_HEADING_RE.search(compact_text(text))
    ]
    subject_key = compact_text(subject)
    matching = [
        (start, text) for start, text in course_headings if subject_key and subject_key in compact_text(text)
    ]
    if matching:
        start = matching[0][0]
        end = len(evidence)
        for h_start, h_text in course_headings:
            if h_start > start and (not subject_key or subject_key not in compact_text(h_text)):
                end = h_start
                break
        return evidence[start:end].strip()
    if course_headings:
        return evidence[: course_headings[0][0]].strip()
    return evidence.strip()


def _table_row_candidates(table_html: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for grid in html_table_grids(table_html):
        num_rows = len(grid)
        width = len(grid[0]) if grid else 0
        for row_index in range(num_rows):
            for col_index in range(width):
                cell = grid[row_index][col_index]
                if not cell or not _looks_like_task_label(cell):
                    continue
                following = [
                    grid[row_index][c]
                    for c in range(col_index + 1, width)
                    if grid[row_index][c].strip()
                ]
                header_only = bool(following) and all(
                    compact_text(v) in FIELD_STOP_LABELS for v in following
                )
                if following and not header_only:
                    for value in following:
                        if compact_text(value) in FIELD_STOP_LABELS or _looks_like_task_label(value):
                            break
                        candidates.append((value, "table"))
                    continue
                distinct: list[str] = []
                seen_keys: set[str] = set()
                for next_row in range(row_index + 1, num_rows):
                    value = grid[next_row][col_index].strip()
                    if not value:
                        continue
                    key = compact_text(value)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        distinct.append(value)
                if len(distinct) == 1:
                    candidates.append((distinct[0], "table"))
    return candidates


def derive_task_names(
    evidence: str, seen: list[str], subject: str
) -> tuple[list[str], str, dict[str, str]]:
    local_text = _localize_subject_section(evidence, subject)
    seen_keys = {compact_text(normalize_task_name(item)) for item in seen}

    table_spans = [
        (match.start(), match.end())
        for match in re.finditer(r"<table\b.*?</table>", local_text, re.I | re.S)
    ]
    non_table_text = local_text
    for start, end in reversed(table_spans):
        non_table_text = non_table_text[:start] + "\n" + non_table_text[end:]

    raw_candidates: list[tuple[str, str]] = []
    for start, end in table_spans:
        raw_candidates.extend(_table_row_candidates(local_text[start:end]))

    for line in non_table_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if " | " in line:
            cells = [cell.strip() for cell in line.split("|")]
            for index, cell in enumerate(cells):
                if (
                    _looks_like_task_label(cell)
                    and index + 1 < len(cells)
                    and cells[index + 1].strip()
                ):
                    raw_candidates.append((cells[index + 1].strip(), "context"))
        elif not table_spans and not line.startswith("#"):
            raw_candidates.append((line, "section"))

    accepted: dict[str, tuple[str, str, int]] = {}
    for order, (raw, source) in enumerate(raw_candidates):
        name = normalize_task_name(raw)
        if not name or task_name_is_rejected(name):
            continue
        key = compact_text(name)
        if key in seen_keys or key in accepted:
            continue
        accepted[key] = (name, source, order)

    # "section" candidates are bare paragraph lines (no table/label anchor),
    # so a long 평가 원칙 sentence out-scores a short real title on length
    # alone -- rank labeled/table candidates first, longest-first only within
    # the same source.
    ordered = sorted(
        accepted.values(),
        key=lambda item: (item[1] == "section", -len(compact_text(item[0])), item[2]),
    )
    names = [item[0] for item in ordered]
    sources = {item[0]: item[1] for item in ordered}
    return names, local_text, sources


OVERVIEW_LABELS = {compact_text(label) for label in ("평가개요", "평가내용", "수행과제", "과제내용")}
METHOD_LABELS = {compact_text(label) for label in ("평가방법", "방법")}
WEIGHT_LABELS = {compact_text(label) for label in ("반영비율", "점수반영비율", "평가비율")}
STANDARD_CODE_RE = re.compile(r"\[(\d{1,2}[가-힣A-Za-z]+\d{2}-\d{2})\]")
CHECKED_METHOD_RE = re.compile(r"☑\s*([^☑□]+)")


def assessment_structure(evidence: str, task_name: str, sources: dict[str, str]) -> dict:
    structure: dict = {
        "basis": "table" if sources.get(task_name) == "table" else "text",
        "overview": "",
        "methods": [],
        "weight": "",
        "standards": [],
        "criteria": [],
    }
    for table_match in re.finditer(r"<table\b.*?</table>", evidence, re.I | re.S):
        for grid in html_table_grids(table_match.group(0)):
            for row in grid:
                if not row:
                    continue
                label = compact_text(row[0])
                following = next(
                    (
                        cell
                        for cell in row[1:]
                        if cell.strip() and compact_text(cell) not in FIELD_STOP_LABELS
                    ),
                    "",
                )
                if not following:
                    continue
                if not structure["overview"] and label in OVERVIEW_LABELS:
                    structure["overview"] = following.strip()
                if label in METHOD_LABELS:
                    structure["methods"] = [
                        match.strip() for match in CHECKED_METHOD_RE.findall(following)
                    ]
                if label in WEIGHT_LABELS:
                    structure["weight"] = re.sub(
                        r"\s*/\s*", " · ", re.sub(r"\s+", " ", following)
                    ).strip()
    structure["standards"] = STANDARD_CODE_RE.findall(evidence)
    return structure


CATEGORY_KEYWORDS = (
    ("독서", "reading"),
    ("탐구", "inquiry"),
    ("발표", "presentation"),
    ("포트폴리오", "portfolio"),
    ("보고서", "reading"),
)


def assessment_category(task_name: str, structure: dict, evidence: str) -> str:
    compact = compact_text(task_name)
    for keyword, category in CATEGORY_KEYWORDS:
        if keyword in compact:
            return category
    return ""


def case_id_for(source_key: str, subject: str) -> str:
    return hashlib.sha1(f"{source_key}:{subject}".encode("utf-8")).hexdigest()[:24]


def category_for(action_tags: list[str]) -> str:
    """Return the published category, or "" when no tag supports one.

    An unmatched tag set means the source text showed none of the six seed
    types.  Publishing those as ``inquiry`` would put unclassified work in the
    주제탐구 tab, so they stay uncategorised instead.
    """

    tags = set(action_tags)
    for tag, _, category in CATEGORY_TAG_ORDER:
        if tag in tags:
            return category
    return ""


def region_from_saved_path(saved_path: str) -> str:
    parts = saved_path.split("/")
    if len(parts) >= 5 and parts[0] == "data" and parts[2] == "schoolinfo":
        return parts[4]
    return ""


def read_jsonl(path: Path, max_resumes: int = 50):
    """Stream a JSONL file, resuming after a transient removable-drive drop.

    The evidence source lives on an external USB drive; a brief power-state
    hiccup mid-read raises ``OSError: [Errno 22] Invalid argument`` while
    reading, or ``PermissionError: [Errno 13]`` while Windows is still
    re-mounting the drive right after a reconnect -- either would otherwise
    lose a multi-hour rebuild. Only those two errnos are treated as
    resumable; the drive being genuinely gone or actually unauthorized
    raises a different errno (e.g. ENOENT) and is left to propagate. A
    permanently wrong permission would also hit ``max_resumes`` and raise
    rather than retry forever.
    """

    RESUMABLE_ERRNOS = {13, 22}
    offset = 0
    resumes = 0
    while True:
        try:
            with path.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                while True:
                    # readline(), not "for line in handle" -- the iterator
                    # protocol's internal readahead buffering disables tell()
                    # ("telling position disabled by next() call"), which
                    # would break resuming after the very error this exists
                    # to survive.
                    line = handle.readline()
                    if not line:
                        break
                    offset = handle.tell()
                    if line.strip():
                        yield json.loads(line)
            return
        except OSError as error:
            if error.errno not in RESUMABLE_ERRNOS or resumes >= max_resumes:
                raise
            resumes += 1
            print(f"read_jsonl: resuming after transient I/O error (attempt {resumes})")
            time.sleep(2)


def load_school_districts(school_district_path: Path | None) -> dict[str, str]:
    """Map ``school_code`` to 시군구, from a NEIS 학교기본정보 export.

    Optional: older/merged-office school codes (see the 2026 전남·광주 교육청
    통합) have no current NEIS record, so lookups for those simply miss and
    the case's ``district`` stays empty rather than guessed.
    """

    if school_district_path is None:
        return {}
    districts: dict[str, str] = {}
    with school_district_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("school_code") or "")
            district = str(row.get("region_sgg") or "")
            if code and district:
                districts[code] = district
    return districts


def load_cases(
    connection: sqlite3.Connection,
    catalog_path: Path,
    school_districts: dict[str, str] | None = None,
) -> None:
    school_districts = school_districts or {}
    rows = []
    for record in read_jsonl(catalog_path):
        source = record.get("source") or {}
        source_key = str(source.get("saved_path") or source.get("final_url") or "")
        subject = str(record.get("subject") or "")
        curriculum = str(record.get("resolved_curriculum") or "shared")
        task_names = [str(v) for v in (record.get("task_name_candidates") or [])]
        action_tags = [str(v) for v in (record.get("action_tags") or [])]
        markers = record.get("marker_counts") or {}
        review_score = int(record.get("review_score") or record.get("evidence_score") or 0)
        evidence_text = str(record.get("evidence_text") or "")

        # The upstream reprocessing pipeline's heading match (bare 가./나./다.
        # list markers) also catches 평가 원칙 프리앰블 문장 that merely start
        # with a matching syllable, not just real 과제명 headings -- run the
        # same rejection rules used below so a policy sentence never lands as
        # the displayed 수행평가명.
        task_names = [normalize_task_name(name) for name in task_names]
        task_names = [name for name in task_names if name and not task_name_is_rejected(name)]
        task_names = list(dict.fromkeys(task_names))

        sources: dict[str, str] = {}
        if not task_names and evidence_text:
            task_names, _, sources = derive_task_names(evidence_text, [], subject)

        structure = assessment_structure(evidence_text, task_names[0] if task_names else "", sources)
        summary_overview = structure["overview"] or evidence_text[:600]

        rows.append(
            (
                case_id_for(source_key, subject),
                curriculum,
                subject,
                str(record.get("curriculum_resolution_basis") or ""),
                str(source.get("school_name") or ""),
                region_from_saved_path(str(source.get("saved_path") or "")),
                school_districts.get(str(source.get("school_code") or ""), ""),
                json.dumps(record.get("academic_years") or [], ensure_ascii=False),
                json.dumps(record.get("grades") or [], ensure_ascii=False),
                json.dumps(record.get("semesters") or [], ensure_ascii=False),
                task_names[0] if task_names else UNCONFIRMED_TASK_NAME,
                json.dumps(task_names, ensure_ascii=False),
                json.dumps(action_tags, ensure_ascii=False),
                int(markers.get("rubric") or 0),
                int(markers.get("achievement_standard") or 0),
                int(markers.get("weight_or_points") or 0),
                int(markers.get("assessment_method") or 0),
                review_score,
                evidence_text[:600],
                summary_overview,
                json.dumps(structure["methods"], ensure_ascii=False),
                structure["weight"],
                json.dumps(structure["standards"], ensure_ascii=False),
                "[]",
                "catalog_only",
                category_for(action_tags),
                review_score,
                json.dumps(action_tags, ensure_ascii=False),
                str(source.get("candidate_name") or ""),
                str(source.get("final_url") or source.get("source_url") or ""),
                str(record.get("sha256") or ""),
            )
        )
    connection.executemany(
        f"INSERT OR REPLACE INTO cases VALUES ({','.join('?' * 31)})", rows
    )
    print(f"cases={len(rows)}")


def load_subject_stats(
    connection: sqlite3.Connection, trends_json_path: Path, catalog_summary_path: Path
) -> None:
    trends = json.loads(trends_json_path.read_text(encoding="utf-8"))
    catalog_summary = json.loads(catalog_summary_path.read_text(encoding="utf-8"))
    by_subject_coverage = catalog_summary.get("by_subject") or {}

    stats_rows = []
    tag_rows = []
    for key, group in (trends.get("subject_groups") or {}).items():
        curriculum, subject = key.split(":", 1)
        coverage = by_subject_coverage.get(key) or {}
        schools = int(group.get("schools") or 0)
        stats_rows.append(
            (
                curriculum,
                subject,
                int(group.get("documents") or 0),
                schools,
                1 if schools < SMALL_SAMPLE_SCHOOL_THRESHOLD else 0,
                json.dumps(group.get("academic_years") or [], ensure_ascii=False),
                int(group.get("grade1_documents") or 0),
                int(group.get("grade2_documents") or 0),
                int(group.get("grade3_documents") or 0),
                int(group.get("rubric_documents") or 0),
                int(group.get("achievement_standard_documents") or 0),
                int(group.get("weight_or_points_documents") or 0),
                int(group.get("assessment_method_documents") or 0),
                group.get("median_review_score") if group.get("median_review_score") != "" else None,
                int(group.get("task_name_candidates") or 0),
                coverage.get("found"),
                coverage.get("found_curriculum_ambiguous"),
                coverage.get("not_found_in_collected_plans"),
                coverage.get("offering_unknown"),
                coverage.get("extraction_failed"),
            )
        )
        for tag, count in (group.get("action_tag_document_counts") or {}).items():
            school_count = (group.get("action_tag_school_counts") or {}).get(tag, 0)
            tag_rows.append((curriculum, subject, tag, int(count), int(school_count)))

    connection.executemany(
        f"INSERT OR REPLACE INTO subject_stats VALUES ({','.join('?' * 20)})", stats_rows
    )
    connection.executemany("INSERT INTO subject_action_tags VALUES (?,?,?,?,?)", tag_rows)
    print(f"subject_stats={len(stats_rows)} subject_action_tags={len(tag_rows)}")


def item_category_and_signals(item) -> tuple[str, list[str]]:
    """Return the item's category and the evidence fields it actually has.

    Cases classify by their pre-extracted ``action_tags``; individual items
    have no such pre-extracted tags, so this scans the item's own title/
    overview/method text with the same patterns instead.

    The signals are what the UI labels 확인된 근거, so they name the source
    fields present in this item, not the inferred activity tags.
    """

    haystack = f"{item.title} {item.overview} {item.method}"
    tags = [tag for tag, pattern, _ in CATEGORY_TAG_ORDER if pattern.search(haystack)]
    signals = [
        name
        for name, present in (
            ("채점기준", bool(item.rubric_html.strip())),
            ("성취기준", bool(item.standards)),
            ("배점", bool(item.score.strip() or item.weight.strip())),
            ("평가방법", bool(item.method.strip())),
            ("평가 개요", bool(item.overview.strip())),
        )
        if present
    ]
    return category_for(tags), signals


def source_format_for(saved_path: str) -> str:
    suffix = Path(saved_path).suffix.lstrip(".").lower()
    return suffix or "unknown"


def refresh_cases_from_items(connection: sqlite3.Connection) -> int:
    """Re-derive the case-level assessment fields from the item-level parse.

    ``load_cases`` fills these fields from a legacy whole-document scan that
    never applies the subject boundary, so a plan covering several courses
    leaks a neighbouring subject's overview, standards, and task name into a
    biology case.  ``assessment_items`` is parsed *inside* the boundary, so
    wherever bounded items exist they are the better source.  Cases without
    bounded items keep their catalogue values, and every field keeps its old
    value when the items have nothing to put there.

    ``criteria_json`` stays as ``load_cases`` left it: rubric criterion names
    are not extracted at item level either, so there is nothing truer to copy.
    """

    grouped: dict[str, list[tuple[str, str, str, str, str, str]]] = {}
    for row in connection.execute(
        """
        SELECT case_id, title, overview, method, score, weight, standards_json
        FROM assessment_items
        WHERE extraction_status = 'bounded' AND title_basis IN ('table', 'heading')
        ORDER BY case_id, item_order
        """
    ):
        grouped.setdefault(str(row[0]), []).append(tuple(str(value) for value in row[1:]))

    def first(values: list[str]) -> str:
        return next((value for value in values if value.strip()), "")

    def unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value.strip()))

    updates = []
    for case_id, items in grouped.items():
        titles = unique([item[0] for item in items])
        if not titles:
            continue
        standards = unique(
            [code for item in items for code in json.loads(item[5] or "[]")]
        )
        updates.append(
            (
                titles[0],
                json.dumps(titles, ensure_ascii=False),
                first([item[1] for item in items]),
                json.dumps(unique([item[2] for item in items]), ensure_ascii=False),
                first([item[4] for item in items]) or first([item[3] for item in items]),
                json.dumps(standards, ensure_ascii=False),
                case_id,
            )
        )

    connection.executemany(
        """
        UPDATE cases SET
            primary_task_name = ?,
            task_names_json = ?,
            summary_overview = ?,
            methods_json = ?,
            weight_summary = ?,
            standards_json = ?
        WHERE case_id = ?
        """,
        updates,
    )
    return len(updates)


def load_case_details(
    connection: sqlite3.Connection, catalog_path: Path, evidence_source_path: Path
) -> tuple[int, int, int]:
    """Parse each case's source document into assessment items.

    Populates ``assessment_items``/``assessment_item_rankings``/
    ``case_detail_status`` and upgrades ``cases.title_basis`` from
    ``catalog_only`` only where the parser found a confident section. A
    parse failure or an unbounded result leaves the case's honest
    ``catalog_only`` value in place.
    """

    case_rows = []
    for record in read_jsonl(catalog_path):
        source = record.get("source") or {}
        source_key = str(source.get("saved_path") or source.get("final_url") or "")
        subject = str(record.get("subject") or "")
        case_rows.append(
            (
                case_id_for(source_key, subject),
                subject,
                str(record.get("sha256") or ""),
                int(record.get("review_score") or record.get("evidence_score") or 0),
                source_format_for(str(source.get("saved_path") or "")),
            )
        )
    # Stream the evidence source instead of loading every wanted document into
    # a dict first: the source file is several GB and this machine has ~8GB of
    # RAM, so holding all of it was the MemoryError that kept killing rebuilds.
    cases_by_sha: dict[str, list[tuple[str, str, str, int, str]]] = {}
    for row in case_rows:
        if row[2]:
            cases_by_sha.setdefault(row[2], []).append(row)

    item_rows = []
    ranking_rows = []
    status_rows = []
    title_basis_updates = []
    total_items = 0
    for record in read_jsonl(evidence_source_path):
        sha = str(record.get("sha256") or "")
        pending = cases_by_sha.pop(sha, None)
        if not pending:
            continue
        text = str(record.get("text") or "")
        if not text:
            continue
        for case_id, subject, _, review_score, source_format in pending:
            _parse_one_case(
                text,
                case_id,
                subject,
                review_score,
                source_format,
                item_rows,
                ranking_rows,
                status_rows,
                title_basis_updates,
            )
        if len(item_rows) >= 2000:
            total_items += _flush_detail_rows(
                connection, item_rows, ranking_rows, status_rows, title_basis_updates
            )
    total_items += _flush_detail_rows(
        connection, item_rows, ranking_rows, status_rows, title_basis_updates
    )
    parsed_cases = connection.execute("SELECT COUNT(*) FROM case_detail_status").fetchone()[0]
    confirmed_cases = connection.execute(
        "SELECT COUNT(*) FROM cases WHERE title_basis = 'source_detail'"
    ).fetchone()[0]

    print(f"cases_refreshed_from_items={refresh_cases_from_items(connection)}")
    print(
        f"assessment_items={total_items} parsed_cases={parsed_cases} "
        f"confirmed_cases={confirmed_cases}"
    )
    return parsed_cases, confirmed_cases, total_items


def _flush_detail_rows(
    connection: sqlite3.Connection,
    item_rows: list,
    ranking_rows: list,
    status_rows: list,
    title_basis_updates: list,
) -> int:
    written = len(item_rows)
    connection.executemany(
        f"INSERT INTO assessment_items VALUES ({','.join('?' * 16)})", item_rows
    )
    connection.executemany(
        "INSERT INTO assessment_item_rankings VALUES (?,?,?,?)", ranking_rows
    )
    connection.executemany("INSERT INTO case_detail_status VALUES (?,?,?,?)", status_rows)
    connection.executemany(
        "UPDATE cases SET title_basis = ? WHERE case_id = ?", title_basis_updates
    )
    item_rows.clear()
    ranking_rows.clear()
    status_rows.clear()
    title_basis_updates.clear()
    return written


def _parse_one_case(
    text: str,
    case_id: str,
    subject: str,
    review_score: int,
    source_format: str,
    item_rows: list,
    ranking_rows: list,
    status_rows: list,
    title_basis_updates: list,
) -> None:
    """Parse one case's document and append its rows to the pending batches."""

    from scripts.biology_assessment_detail_parser import parse_assessment_section

    try:
        section = parse_assessment_section(text, subject)
    except Exception:
        return
    if not section.items:
        return
    status_rows.append(
        (case_id, source_format, section.boundary_status, len(section.source_markdown))
    )
    first_confirmed = False
    for order, item in enumerate(section.items, 1):
        item_id = f"{case_id}-{order}"
        item_rows.append(
            (
                item_id,
                case_id,
                order,
                item.title,
                item.title_raw,
                item.title_basis,
                item.extraction_status,
                item.overview,
                item.method,
                item.timing,
                item.score,
                item.weight,
                json.dumps(list(item.standards), ensure_ascii=False),
                len(item.rubric_html),
                zlib.compress(item.source_html.encode("utf-8")),
                zlib.compress(item.rubric_html.encode("utf-8")),
            )
        )
        category, signals = item_category_and_signals(item)
        ranking_rows.append(
            (item_id, category, review_score, json.dumps(signals, ensure_ascii=False))
        )
        if order == 1 and item.extraction_status == "bounded" and item.title_basis in (
            "table",
            "heading",
        ):
            first_confirmed = True
    title_basis_updates.append(
        ("source_detail" if first_confirmed else "source_detail_bundle_review", case_id)
    )


def build(
    output_path: Path,
    catalog_path: Path,
    trends_json_path: Path,
    catalog_summary_path: Path,
    evidence_source_path: Path | None = None,
    school_district_path: Path | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    connection = sqlite3.connect(output_path)
    try:
        connection.executescript(SCHEMA)
        load_cases(connection, catalog_path, load_school_districts(school_district_path))
        load_subject_stats(connection, trends_json_path, catalog_summary_path)
        if evidence_source_path is not None:
            load_case_details(connection, catalog_path, evidence_source_path)
        connection.commit()
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--trends-json", type=Path, required=True)
    parser.add_argument("--catalog-summary", type=Path, required=True)
    parser.add_argument("--catalog-db", type=Path, required=True)
    parser.add_argument("--detail-db", type=Path, required=True)
    parser.add_argument("--evidence-source", type=Path, default=None)
    parser.add_argument("--school-district", type=Path, default=None)
    args = parser.parse_args()

    build(
        args.detail_db,
        args.catalog,
        args.trends_json,
        args.catalog_summary,
        args.evidence_source,
        args.school_district,
    )
    # 두 DB는 같은 인자로 만들면 내용이 완전히 같다. 한 번만 빌드하고 복사해
    # evidence_source 스캔과 피크 메모리를 두 배로 쓰지 않는다.
    # ponytail: 아직 파일 두 벌이 필요하다(배포 스테이징이 두 경로를 모두 읽음).
    # 카탈로그를 detail 테이블 없이 만들려면 repository.cases()의
    # source_status='confirmed' 분기에 테이블 존재 가드를 먼저 넣어야 한다.
    args.catalog_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.detail_db, args.catalog_db)


if __name__ == "__main__":
    main()
