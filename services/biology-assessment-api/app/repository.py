"""Read-only SQLite queries for trends and evidence cases."""

from __future__ import annotations

import json
import re
import sqlite3
import zlib
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from app.source_html import restore_escaped_table_rows, rubric_tables_from_source_html

SUBJECT_ORDER = {
    # 파이프라인 매니페스트가 내는 9개 라벨. 아라비아 숫자는 로마자로 정규화된다.
    "통합과학": 1,
    "통합과학1": 2,
    "과학탐구실험": 3,
    "과학탐구실험1": 4,
    "생명과학": 5,
    "생명과학Ⅰ": 6,
    "생명과학Ⅱ": 7,
    "생명과학실험": 8,
    "고급생명과학": 9,
}
CURRICULUM_ORDER = {"2015": 1, "2022": 2, "shared": 3}
SEARCH_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣ⅠⅡ]+")
ROUGH_OVERVIEW_RE = re.compile(
    r"매우\s*(?:부족|미흡)|현저히|보이지\s*않음|평가\(채점\)\s*기준|^\s*\d+\s*$"
)
UNCONFIRMED_BUNDLE_TITLE = "수행평가명 미확정 · 원문 묶음"
_BLOCK_TAGS = {
    "br", "tr", "td", "th", "table", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6",
}


class _PlainTextExtractor(HTMLParser):
    """Collapse a scraped fragment's leftover HTML markup into plain text.

    ``evidence_excerpt``/``summary_overview`` sometimes retain literal
    ``<table>``/``<br>`` markup the extraction pipeline didn't convert. A
    reader must never see a raw tag; this keeps the text and drops the tags,
    inserting a space at each block boundary so words don't run together.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self._chunks.append(" ")

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def _plain_text(value: str) -> str:
    if "<" not in value:
        return value
    parser = _PlainTextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return value
    return parser.text()


_SELECTED_BOX_RE = re.compile(r"[■☑☒✓✔]|□\s*[VvＶ]")
_METHOD_DROP_RE = re.compile(
    r"성취\s*기준|평가\s*기준|정기\s*시험|지필\s*평가|선택형|서답형|합계|"
    r"^\s*\[?(?:10|12)[^\]]*\]?\s*$"
)


def display_methods(values: list[str]) -> list[str]:
    """Render source 평가 방법 cells as the methods a reader can act on.

    The source cells are kept verbatim in the publish DB, but a raw cell is
    often a whole checkbox menu ("□ 서술·논술 ☑ 실험･실습 □ 기타"), a label that
    leaked in from the neighbouring 성취기준 column, or an exam name. Only the
    ticked options are the school's actual choice, so unticked options, leaked
    labels, and exam names are left out of the published field rather than
    presented as if the school selected them.
    """

    output: list[str] = []
    for value in values:
        text = re.sub(r"\s+", " ", _plain_text(str(value))).strip()
        if not text:
            continue
        parts = [text]
        if _SELECTED_BOX_RE.search(text):
            parts = [
                segment.strip(" ·|")
                for segment in re.split(r"(?=[■☑☒✓✔□])", text)
                if _SELECTED_BOX_RE.match(segment.strip())
            ]
            parts = [_SELECTED_BOX_RE.sub("", part).strip(" ·|") for part in parts]
        for part in parts:
            part = part.strip(" ·|")
            if not part or _METHOD_DROP_RE.search(part):
                continue
            if part not in output:
                output.append(part)
    return output[:6]


def parse_json_list(value: object) -> list[Any]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def search_tokens(value: str) -> list[str]:
    return SEARCH_TOKEN_RE.findall(value)[:8]


def like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class CatalogRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    @property
    def ready(self) -> bool:
        return self.database_path.is_file()

    def connect(self) -> sqlite3.Connection:
        if not self.ready:
            raise FileNotFoundError(self.database_path)
        connection = sqlite3.connect(
            f"file:{self.database_path.resolve()}?mode=ro",
            uri=True,
            timeout=5,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _has_axes(connection: sqlite3.Connection) -> bool:
        """True when this database recorded every axis value per item.

        The table has to be non-empty, not merely present: an empty one would
        make the membership filter match nothing and blank the whole site,
        where falling back to the single stored value still answers.
        """

        if connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type = 'table'"
            " AND name = 'assessment_item_axes'"
        ).fetchone() is None:
            return False
        return connection.execute(
            "SELECT 1 FROM assessment_item_axes LIMIT 1"
        ).fetchone() is not None

    @staticmethod
    def _curated_filters(
        *,
        category: str,
        curriculum: str | None,
        subject: str | None,
        region: str | None = None,
        district: str | None = None,
        topic: str | None = None,
        multi_axis: bool = False,
    ) -> tuple[list[str], list[object]]:
        # ``category`` is the 방법 axis; ``topic`` narrows the 주제 axis of the
        # same 영역명 matrix, so passing both asks for one matrix cell.  An item
        # can honestly sit in several cells ("탐구 실험 보고서" is 실험평가 and
        # 작성), so where the build recorded every axis value the filter matches
        # membership rather than the single displayed value.
        axis_clause = (
            "EXISTS (SELECT 1 FROM assessment_item_axes axes"
            " WHERE axes.item_id = item.item_id AND axes.axis = ? AND axes.value = ?)"
        )
        clauses = [
            axis_clause if multi_axis else "ranking.category = ?",
            "ranking.priority_score >= 38",
            "item.extraction_status = 'bounded'",
            "item.title_basis IN ('table', 'heading')",
        ]
        parameters: list[object] = ["method", category] if multi_axis else [category]
        if topic:
            clauses.append(axis_clause if multi_axis else "ranking.topic = ?")
            parameters.extend(["topic", topic] if multi_axis else [topic])
        for column, value in (
            ("curriculum", curriculum),
            ("subject", subject),
            ("region", region),
            ("district", district),
        ):
            if value:
                clauses.append(f"cases.{column} = ?")
                parameters.append(value)
        return clauses, parameters

    def catalog_counts(self) -> tuple[int, int]:
        if not self.ready:
            return 0, 0
        with self.connect() as connection:
            cases = int(connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0])
            subjects = int(connection.execute("SELECT COUNT(*) FROM subject_stats").fetchone()[0])
        return cases, subjects

    def publication_snapshot(self) -> dict[str, int]:
        """자료 안내 페이지의 검증 스냅숏 5개 수치. subject_stats.coverage_*는
        과목마다 같은 학교알리미 평가계획 모집단을 기준으로 하므로 한 행만 합산한다."""
        empty = {
            "plans_checked": 0,
            "normalized_cases": 0,
            "published_schools": 0,
            "published_cases": 0,
            "published_assessment_items": 0,
        }
        if not self.ready:
            return empty
        with self.connect() as connection:
            plans_checked = connection.execute(
                "SELECT coverage_found + coverage_ambiguous + coverage_not_found"
                " + coverage_offering_unknown + coverage_extraction_failed"
                " FROM subject_stats LIMIT 1"
            ).fetchone()
            normalized_cases = connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
            published_schools = connection.execute(
                "SELECT COUNT(DISTINCT c.school_name || '|' || c.region || '|' || c.district)"
                " FROM cases c JOIN assessment_items a ON a.case_id = c.case_id"
                " WHERE a.extraction_status = 'bounded'"
            ).fetchone()[0]
            published_cases = connection.execute(
                "SELECT COUNT(DISTINCT c.case_id)"
                " FROM cases c JOIN assessment_items a ON a.case_id = c.case_id"
                " WHERE a.extraction_status = 'bounded'"
            ).fetchone()[0]
            published_items = connection.execute(
                "SELECT COUNT(*) FROM assessment_items WHERE extraction_status = 'bounded'"
            ).fetchone()[0]
        return {
            "plans_checked": int(plans_checked[0]) if plans_checked else 0,
            "normalized_cases": int(normalized_cases),
            "published_schools": int(published_schools),
            "published_cases": int(published_cases),
            "published_assessment_items": int(published_items),
        }

    def subjects(self, curriculum: str | None = None) -> list[dict[str, object]]:
        sql = "SELECT * FROM subject_stats"
        parameters: tuple[object, ...] = ()
        if curriculum:
            sql += " WHERE curriculum = ?"
            parameters = (curriculum,)
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        items = [self._subject_item(row) for row in rows]
        return sorted(
            items,
            key=lambda item: (
                CURRICULUM_ORDER.get(str(item["curriculum"]), 9),
                SUBJECT_ORDER.get(str(item["subject"]), 99),
                str(item["subject"]),
            ),
        )

    def trends(
        self, curriculum: str | None = None, subject: str | None = None
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        parameters: list[object] = []
        if curriculum:
            clauses.append("curriculum = ?")
            parameters.append(curriculum)
        if subject:
            clauses.append("subject = ?")
            parameters.append(subject)
        sql = "SELECT * FROM subject_stats"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
            tag_rows = connection.execute(
                "SELECT * FROM subject_action_tags ORDER BY document_count DESC, tag"
            ).fetchall()
        tags: dict[tuple[str, str], list[dict[str, object]]] = {}
        for row in tag_rows:
            key = (str(row["curriculum"]), str(row["subject"]))
            tags.setdefault(key, []).append(
                {
                    "tag": str(row["tag"]),
                    "documents": int(row["document_count"]),
                    "schools": int(row["school_count"]),
                }
            )
        items = [self._trend_item(row, tags) for row in rows]
        return sorted(
            items,
            key=lambda item: (
                CURRICULUM_ORDER.get(str(item["curriculum"]), 9),
                SUBJECT_ORDER.get(str(item["subject"]), 99),
                str(item["subject"]),
            ),
        )

    def cases(
        self,
        *,
        curriculum: str | None,
        subject: str | None,
        tag: str | None,
        region: str | None,
        district: str | None,
        source_status: str | None,
        query: str | None,
        include_ambiguous: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], int]:
        joins: list[str] = []
        clauses: list[str] = []
        parameters: list[object] = []
        search = search_tokens(query or "")
        if tag:
            clauses.append(
                "EXISTS (SELECT 1 FROM json_each(c.action_tags_json) WHERE value = ?)"
            )
            parameters.append(tag)
        for token in search:
            clauses.append(
                "(c.primary_task_name LIKE ? ESCAPE '\\' "
                "OR c.evidence_excerpt LIKE ? ESCAPE '\\' "
                "OR c.school_name LIKE ? ESCAPE '\\' "
                "OR c.subject LIKE ? ESCAPE '\\')"
            )
            pattern = like_pattern(token)
            parameters.extend([pattern, pattern, pattern, pattern])
        if curriculum:
            if include_ambiguous and subject:
                clauses.append("c.curriculum IN (?, 'shared')")
            else:
                clauses.append("c.curriculum = ?")
            parameters.append(curriculum)
        if subject:
            clauses.append("c.subject = ?")
            parameters.append(subject)
        if region:
            clauses.append("c.region = ?")
            parameters.append(region)
        if district:
            clauses.append("c.district = ?")
            parameters.append(district)
        if source_status == "confirmed":
            clauses.append("c.title_basis = 'source_detail'")
            clauses.append(
                "EXISTS (SELECT 1 FROM assessment_items public_item "
                "WHERE public_item.case_id = c.case_id "
                "AND public_item.extraction_status = 'bounded' "
                "AND public_item.title_basis IN ('table', 'heading'))"
            )
        elif source_status == "review":
            clauses.append("c.title_basis = 'source_detail_bundle_review'")
        elif source_status == "unconfirmed":
            clauses.append(
                "(c.primary_task_name = '구체적 과제명 미탐지' "
                "OR c.title_basis NOT IN ('source_detail', 'source_detail_bundle_review'))"
            )
        join_sql = " ".join(joins)
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(DISTINCT c.case_id) FROM cases c {join_sql}{where_sql}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT DISTINCT c.* FROM cases c {join_sql}{where_sql}
                ORDER BY c.review_score DESC, c.case_id
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
        return [self._case_item(row) for row in rows], total

    def facets(
        self, curriculum: str | None, subject: str | None, region: str | None
    ) -> dict[str, list[dict[str, object]]]:
        clauses: list[str] = []
        parameters: list[object] = []
        with self.connect() as connection:
            has_detail_items = connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE type = 'table' "
                "AND name = 'assessment_items'"
            ).fetchone() is not None
        if has_detail_items:
            clauses.append("c.title_basis = 'source_detail'")
            clauses.append(
                "EXISTS (SELECT 1 FROM assessment_items public_item "
                "WHERE public_item.case_id = c.case_id "
                "AND public_item.extraction_status = 'bounded' "
                "AND public_item.title_basis IN ('table', 'heading'))"
            )
        if curriculum:
            if subject:
                clauses.append("c.curriculum IN (?, 'shared')")
            else:
                clauses.append("c.curriculum = ?")
            parameters.append(curriculum)
        if subject:
            clauses.append("c.subject = ?")
            parameters.append(subject)
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        district_clauses = [*clauses]
        district_parameters = [*parameters]
        if region:
            district_clauses.append("c.region = ?")
            district_parameters.append(region)
        district_where = (
            " WHERE " + " AND ".join(district_clauses) if district_clauses else ""
        )
        with self.connect() as connection:
            region_rows = connection.execute(
                f"""
                SELECT c.region AS value, COUNT(*) AS count
                FROM cases c {where_sql}
                GROUP BY c.region
                HAVING c.region != ''
                ORDER BY count DESC, value
                """,
                parameters,
            ).fetchall()
            district_rows = connection.execute(
                f"""
                SELECT c.district AS value, COUNT(*) AS count
                FROM cases c {district_where}
                GROUP BY c.district
                HAVING c.district != ''
                ORDER BY count DESC, value
                """,
                district_parameters,
            ).fetchall()
            tag_rows = connection.execute(
                f"""
                SELECT cat.value AS value, COUNT(DISTINCT c.case_id) AS count
                FROM cases c
                JOIN json_each(c.action_tags_json) cat
                {district_where}
                GROUP BY cat.value
                ORDER BY count DESC, value
                """,
                district_parameters,
            ).fetchall()
        return {
            "regions": [
                {"value": str(row["value"]), "count": int(row["count"])} for row in region_rows
            ],
            "districts": [
                {"value": str(row["value"]), "count": int(row["count"])} for row in district_rows
            ],
            "action_tags": [
                {"value": str(row["value"]), "count": int(row["count"])} for row in tag_rows
            ],
        }

    def case(self, case_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return self._case_item(row) if row else None

    def case_detail(self, case_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            status = connection.execute(
                "SELECT * FROM case_detail_status WHERE case_id = ?", (case_id,)
            ).fetchone()
            if status is None:
                return None
            rows = connection.execute(
                """
                SELECT item_id, item_order, title, title_raw, title_basis,
                       extraction_status, overview, method, timing, score,
                       weight, standards_json, rubric_html_char_count
                FROM assessment_items
                WHERE case_id = ?
                  AND extraction_status = 'bounded'
                  AND title_basis IN ('table', 'heading')
                ORDER BY item_order
                """,
                (case_id,),
            ).fetchall()
        if not rows:
            return None
        confirmed_titles = [str(row["title"]) for row in rows]
        return {
            "case_id": case_id,
            "source_format": str(status["source_format"]),
            "boundary_status": str(status["boundary_status"]),
            "extraction_status": "bounded",
            "detected_titles": confirmed_titles,
            "source_section_char_count": int(status["source_section_char_count"]),
            "items": [self._assessment_item_summary(row) for row in rows],
        }

    def assessment_item(self, item_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            case_columns = {
                str(column[1]) for column in connection.execute("PRAGMA table_info(cases)")
            }
            district_select = "cases.district" if "district" in case_columns else "'' AS district"
            row = connection.execute(
                f"""
                SELECT item.*, cases.curriculum, cases.subject, cases.school_name,
                       cases.region, {district_select}, cases.candidate_name, cases.source_url
                FROM assessment_items item
                JOIN cases ON cases.case_id = item.case_id
                WHERE item.item_id = ?
                """,
                (item_id,),
            ).fetchone()
        if row is None:
            return None
        if str(row["extraction_status"]) != "bounded" or str(row["title_basis"]) not in {
            "table",
            "heading",
        }:
            return None
        item = self._assessment_item_summary(row)
        # Public HTML is limited to individually bounded assessment sections.
        # Bundled/review and cross-subject matches retain metadata only until a
        # teacher-safe boundary and privacy review is completed.
        source_available = str(row["extraction_status"]) == "bounded"
        source_html = ""
        rubric_html = ""
        if source_available:
            source_html = restore_escaped_table_rows(
                zlib.decompress(row["source_html_zlib"]).decode("utf-8")
            )
            rubric_html = restore_escaped_table_rows(
                zlib.decompress(row["rubric_html_zlib"]).decode("utf-8")
            )
            if not rubric_html.strip():
                rubric_html = rubric_tables_from_source_html(source_html)
            item["has_rubric"] = bool(rubric_html.strip())
        item.update(
            {
                "case_id": str(row["case_id"]),
                "curriculum": str(row["curriculum"]),
                "subject": str(row["subject"]),
                "school_name": str(row["school_name"]),
                "region": str(row["region"]),
                "district": str(row["district"]),
                "source_name": str(row["candidate_name"]),
                "source_url": str(row["source_url"]),
                "source_html": source_html,
                "rubric_html": rubric_html,
            }
        )
        return item

    def curated_items(
        self,
        *,
        curriculum: str | None,
        subject: str | None,
        region: str | None,
        district: str | None,
        category: str,
        limit: int,
        topic: str | None = None,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        with self.connect() as connection:
            has_rankings = connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE type = 'table' "
                "AND name = 'assessment_item_rankings'"
            ).fetchone() is not None
            if has_rankings:
                case_columns = {
                    str(column[1]) for column in connection.execute("PRAGMA table_info(cases)")
                }
                has_district = "district" in case_columns
                if district and not has_district:
                    return []
                ranking_columns = {
                    str(column[1])
                    for column in connection.execute(
                        "PRAGMA table_info(assessment_item_rankings)"
                    )
                }
                has_topic = "topic" in ranking_columns
                if topic and not has_topic:
                    return []
                clauses, parameters = self._curated_filters(
                    category=category,
                    curriculum=curriculum,
                    subject=subject,
                    region=region,
                    district=district,
                    topic=topic if has_topic else None,
                    multi_axis=self._has_axes(connection),
                )
                district_select = "cases.district" if has_district else "'' AS district"
                topic_select = "ranking.topic" if has_topic else "'' AS topic"
                rows = connection.execute(
                    f"""
                    SELECT item.*, ranking.category, {topic_select},
                           ranking.priority_score,
                           ranking.priority_signals_json, cases.curriculum,
                           cases.subject, cases.school_name, cases.region, {district_select}
                    FROM assessment_items item
                    JOIN assessment_item_rankings ranking ON ranking.item_id = item.item_id
                    JOIN cases ON cases.case_id = item.case_id
                    WHERE {" AND ".join(clauses)}
                    ORDER BY ranking.priority_score DESC, item.item_id
                    LIMIT ? OFFSET ?
                    """,
                    [*parameters, limit, offset],
                ).fetchall()
            else:
                rows = []
        if has_rankings:
            output: list[dict[str, object]] = []
            for row in rows:
                item = self._assessment_item_summary(row)
                item.update(
                    {
                        "case_id": str(row["case_id"]),
                        "curriculum": str(row["curriculum"]),
                        "subject": str(row["subject"]),
                        "school_name": str(row["school_name"]),
                        "region": str(row["region"]),
                        "district": str(row["district"]),
                        "category": str(row["category"]),
                        "topic": str(row["topic"]),
                        "priority_score": int(row["priority_score"]),
                        "priority_signals": [
                            str(value)
                            for value in parse_json_list(row["priority_signals_json"])
                        ],
                    }
                )
                output.append(item)
            return output

        legacy = self.curated_cases(
            curriculum=curriculum,
            subject=subject,
            region=region,
            district=district,
            category=category,
            limit=limit + offset,
        )
        return [
            {
                "item_id": f"legacy-{item['case_id']}",
                "order": 1,
                "title": str(item["primary_task_name"]),
                "title_raw": str(item["primary_task_name"]),
                "title_basis": str(item["assessment_structure"]["basis"]),
                "extraction_status": "legacy",
                "overview": str(item["assessment_structure"]["overview"]),
                "method": " · ".join(item["assessment_structure"]["methods"]),
                "timing": "",
                "score": "",
                "weight": str(item["assessment_structure"]["weight"]),
                "standards": list(item["assessment_structure"]["standards"]),
                "has_rubric": bool(item["evidence_markers"]["rubric"]),
                "case_id": str(item["case_id"]),
                "curriculum": str(item["curriculum"]),
                "subject": str(item["subject"]),
                "school_name": str(item["school_name"]),
                "region": str(item["region"]),
                "district": str(item["district"]),
                "category": str(item["category"]),
                "priority_score": int(item["priority_score"]),
                "priority_signals": list(item["priority_signals"]),
            }
            for item in legacy[offset:]
        ]

    def curated_total(
        self,
        *,
        curriculum: str | None,
        subject: str | None,
        region: str | None,
        district: str | None,
        category: str,
        topic: str | None = None,
    ) -> int:
        with self.connect() as connection:
            has_topic = any(
                str(column[1]) == "topic"
                for column in connection.execute(
                    "PRAGMA table_info(assessment_item_rankings)"
                )
            )
            if topic and not has_topic:
                return 0
            clauses, parameters = self._curated_filters(
                category=category,
                curriculum=curriculum,
                subject=subject,
                region=region,
                district=district,
                topic=topic if has_topic else None,
                multi_axis=self._has_axes(connection),
            )
            row = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM assessment_items item
                JOIN assessment_item_rankings ranking ON ranking.item_id = item.item_id
                JOIN cases ON cases.case_id = item.case_id
                WHERE {" AND ".join(clauses)}
                """,
                parameters,
            ).fetchone()
        return int(row[0])

    def curated_facets(
        self,
        *,
        curriculum: str | None,
        subject: str | None,
        region: str | None,
        category: str,
    ) -> dict[str, list[dict[str, object]]]:
        joins = """
            FROM assessment_items item
            JOIN assessment_item_rankings ranking ON ranking.item_id = item.item_id
            JOIN cases ON cases.case_id = item.case_id
        """
        with self.connect() as connection:
            clauses, parameters = self._curated_filters(
                category=category,
                curriculum=curriculum,
                subject=subject,
                multi_axis=self._has_axes(connection),
            )
            where_sql = " AND ".join(clauses)
            district_clauses = [*clauses]
            district_parameters = [*parameters]
            if region:
                district_clauses.append("cases.region = ?")
                district_parameters.append(region)
            region_rows = connection.execute(
                f"""
                SELECT cases.region AS value, COUNT(*) AS count
                {joins}
                WHERE {where_sql} AND cases.region != ''
                GROUP BY cases.region
                ORDER BY count DESC, value
                """,
                parameters,
            ).fetchall()
            district_rows = connection.execute(
                f"""
                SELECT cases.district AS value, COUNT(*) AS count
                {joins}
                WHERE {" AND ".join(district_clauses)} AND cases.district != ''
                GROUP BY cases.district
                ORDER BY count DESC, value
                """,
                district_parameters,
            ).fetchall()
        return {
            "regions": [
                {"value": str(row["value"]), "count": int(row["count"])}
                for row in region_rows
            ],
            "districts": [
                {"value": str(row["value"]), "count": int(row["count"])}
                for row in district_rows
            ],
            "action_tags": [],
        }

    def curated_cases(
        self,
        *,
        curriculum: str | None,
        subject: str | None,
        region: str | None,
        district: str | None,
        category: str,
        limit: int,
        topic: str | None = None,
    ) -> list[dict[str, object]]:
        with self.connect() as connection:
            has_detail_items = connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE type = 'table' "
                "AND name = 'assessment_items'"
            ).fetchone() is not None
        clauses = [
            "c.category = ?",
            "c.priority_score >= 38",
            "c.primary_task_name NOT LIKE '%' || char(10) || '%'",
            "c.primary_task_name NOT LIKE '%문맥 전환%'",
            "c.primary_task_name NOT LIKE '평가 방법:%'",
            "c.primary_task_name NOT GLOB '* [0-9]'",
            "NOT (c.subject NOT LIKE '생명과학%' AND c.primary_task_name LIKE '%생명과학%')",
        ]
        if has_detail_items:
            clauses.extend(
                [
                    "c.title_basis = 'source_detail'",
                    "EXISTS (SELECT 1 FROM assessment_items detail_item "
                    "WHERE detail_item.case_id = c.case_id "
                    "AND detail_item.item_order = 1 "
                    "AND detail_item.extraction_status = 'bounded' "
                    "AND detail_item.title_basis IN ('table', 'heading'))",
                ]
            )
        else:
            clauses.append("c.title_basis IN ('table', 'heading')")
        parameters: list[object] = [category]
        if curriculum:
            clauses.append("c.curriculum = ?")
            parameters.append(curriculum)
        if subject:
            clauses.append("c.subject = ?")
            parameters.append(subject)
        if region:
            clauses.append("c.region = ?")
            parameters.append(region)
        if district:
            clauses.append("c.district = ?")
            parameters.append(district)
        where_sql = " AND ".join(clauses)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.* FROM cases c
                WHERE {where_sql}
                ORDER BY c.priority_score DESC, c.review_score DESC, c.case_id
                LIMIT ?
                """,
                [*parameters, limit],
            ).fetchall()
        return [self._case_item(row) for row in rows]

    @staticmethod
    def _subject_item(row: sqlite3.Row) -> dict[str, object]:
        curriculum = str(row["curriculum"])
        return {
            "curriculum": curriculum,
            "subject": str(row["subject"]),
            "documents": int(row["documents"]),
            "schools": int(row["schools"]),
            "small_sample": bool(row["small_sample"]),
            "curriculum_ambiguous": curriculum == "shared",
        }

    @classmethod
    def _trend_item(
        cls,
        row: sqlite3.Row,
        tags: dict[tuple[str, str], list[dict[str, object]]],
    ) -> dict[str, object]:
        item = cls._subject_item(row)
        key = (str(row["curriculum"]), str(row["subject"]))
        item.update(
            {
                "academic_years": [
                    int(value) for value in parse_json_list(row["academic_years_json"])
                ],
                "grade_documents": {
                    "1": int(row["grade1_documents"]),
                    "2": int(row["grade2_documents"]),
                    "3": int(row["grade3_documents"]),
                },
                "evidence_documents": {
                    "rubric": int(row["rubric_documents"]),
                    "achievement_standard": int(row["achievement_standard_documents"]),
                    "weight_or_points": int(row["weight_or_points_documents"]),
                    "assessment_method": int(row["assessment_method_documents"]),
                },
                "median_evidence_score": row["median_review_score"],
                "task_name_candidates": int(row["task_name_candidates"]),
                "action_tags": tags.get(key, []),
                "coverage": {
                    "found": row["coverage_found"],
                    "found_curriculum_ambiguous": row["coverage_ambiguous"],
                    "not_found_in_collected_plans": row["coverage_not_found"],
                    "offering_unknown": row["coverage_offering_unknown"],
                    "extraction_failed": row["coverage_extraction_failed"],
                },
            }
        )
        return item

    @staticmethod
    def _case_item(row: sqlite3.Row) -> dict[str, object]:
        curriculum = str(row["curriculum"])
        # A precomputed verdict from annotate_case_subject_alignment.py: "other"
        # means the excerpt's own achievement-standard code names a different
        # subject than this case is filed under (a neighbouring subject's
        # table was pulled in by mistake). Per SOURCE_POLICY.md's public
        # boundary rule, that text is not published -- the school's official
        # Schoolinfo link (source_url, kept below) stands in for it.
        subject_confirmed = (
            "subject_alignment" not in row.keys() or row["subject_alignment"] != "other"
        )
        overview = (
            re.sub(r"\s+", " ", _plain_text(str(row["summary_overview"]))).strip()
            if subject_confirmed
            else ""
        )
        if ROUGH_OVERVIEW_RE.search(overview):
            overview = ""
        title_basis = str(row["title_basis"])
        primary_task_name = _plain_text(str(row["primary_task_name"])).strip()
        task_names = [
            _plain_text(str(value)).strip() for value in parse_json_list(row["task_names_json"])
        ]

        # A bundle without a source-table title is useful for coverage, but its
        # legacy catalogue title can be a rubric heading or a neighbouring
        # subject's text.  Never present that value as a confirmed task name.
        # The original is retained only in the private/audit database, while
        # teachers see the honest boundary state and can follow the official
        # Schoolinfo link for the full document.
        if title_basis == "source_detail_bundle_review":
            primary_task_name = UNCONFIRMED_BUNDLE_TITLE
            task_names = []
        return {
            "case_id": str(row["case_id"]),
            "curriculum": curriculum,
            "subject": str(row["subject"]),
            "curriculum_ambiguous": curriculum == "shared",
            "curriculum_basis": str(row["curriculum_basis"]),
            "school_name": str(row["school_name"]),
            "region": str(row["region"]),
            "district": str(row["district"]) if "district" in row.keys() else "",
            "academic_years": [int(value) for value in parse_json_list(row["academic_years_json"])],
            "grades": [int(value) for value in parse_json_list(row["grades_json"])],
            "semesters": [int(value) for value in parse_json_list(row["semesters_json"])],
            "primary_task_name": primary_task_name,
            "task_names": task_names,
            "action_tags": [str(value) for value in parse_json_list(row["action_tags_json"])],
            "evidence_markers": {
                "rubric": int(row["rubric_marker_count"]),
                "achievement_standard": int(row["achievement_standard_marker_count"]),
                "weight_or_points": int(row["weight_or_points_marker_count"]),
                "assessment_method": int(row["assessment_method_marker_count"]),
            },
            "evidence_score": int(row["review_score"]),
            "evidence_excerpt": (
                re.sub(r"\s+", " ", _plain_text(str(row["evidence_excerpt"]))).strip()
                if subject_confirmed
                else ""
            ),
            "assessment_structure": {
                "overview": overview,
                "methods": display_methods(
                    [str(value) for value in parse_json_list(row["methods_json"])]
                ),
                "weight": (
                    ""
                    if str(row["weight_summary"]) in {"0점", "0%"}
                    else str(row["weight_summary"])
                ),
                "standards": (
                    [str(value) for value in parse_json_list(row["standards_json"])]
                    if subject_confirmed
                    else []
                ),
                "criteria": (
                    [str(value) for value in parse_json_list(row["criteria_json"])]
                    if subject_confirmed
                    else []
                ),
                "basis": title_basis,
            },
            "category": str(row["category"]),
            "priority_score": int(row["priority_score"]),
            "priority_signals": [
                str(value) for value in parse_json_list(row["priority_signals_json"])
            ],
            "source_name": str(row["candidate_name"]),
            "source_url": str(row["source_url"]),
            "source_sha256": str(row["source_sha256"]),
        }

    @staticmethod
    def _assessment_item_summary(row: sqlite3.Row) -> dict[str, object]:
        source_available = str(row["extraction_status"]) == "bounded"
        return {
            "item_id": str(row["item_id"]),
            "order": int(row["item_order"]),
            "title": str(row["title"]),
            "title_raw": str(row["title_raw"]),
            "title_basis": str(row["title_basis"]),
            "extraction_status": str(row["extraction_status"]),
            "overview": str(row["overview"]),
            "method": " · ".join(display_methods([str(row["method"])])),
            "timing": str(row["timing"]),
            "score": str(row["score"]),
            "weight": str(row["weight"]),
            "standards": [
                str(value) for value in parse_json_list(row["standards_json"])
            ],
            "has_rubric": source_available and int(row["rubric_html_char_count"]) > 0,
            "source_available": source_available,
        }
