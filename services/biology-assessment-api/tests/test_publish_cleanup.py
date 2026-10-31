import sqlite3
import zlib

from scripts.dedupe_publish_cases import find_duplicates

URL = (
    "https://www.schoolinfo.go.kr/servlets/EiFileDownLoad.do?SHL_IDF_CD={school}"
    "&JG_CHASU={round}&FILE_SEQ={seq}"
)


def _database(rows: list[tuple]) -> sqlite3.Connection:
    """rows: (case_id, subject, url, items[, grades, public]) -- public=False makes every
    item a review bundle that the site does not show."""

    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE cases (case_id TEXT, subject TEXT, source_url TEXT, "
        "academic_years_json TEXT, semesters_json TEXT, grades_json TEXT)"
    )
    connection.execute(
        "CREATE TABLE assessment_items (case_id TEXT, item_order INTEGER, title TEXT, "
        "extraction_status TEXT, title_basis TEXT, source_html_zlib BLOB)"
    )
    for case_id, subject, url, items, *rest in rows:
        grades = rest[0] if rest else "[1]"
        public = rest[1] if len(rest) > 1 else True
        connection.execute(
            "INSERT INTO cases VALUES (?, ?, ?, '[2026]', '[2]', ?)",
            (case_id, subject, url, grades),
        )
        for order, (title, html) in enumerate(items, 1):
            connection.execute(
                "INSERT INTO assessment_items VALUES (?, ?, ?, ?, ?, ?)",
                (
                    case_id, order, title,
                    "bounded" if public else "bundle_review",
                    "table" if public else "unbounded_bundle",
                    zlib.compress(html.encode("utf-8")),
                ),
            )
    return connection


def test_the_same_plan_attached_twice_keeps_the_latest_version() -> None:
    plan = [("효소 반응 탐구 보고서", "<p>효소의 활성에 영향을 주는 요인을 실험으로 확인한다.</p>")]
    revised = [("효소 반응 탐구 보고서", "<p>효소의 활성에 영향을 주는 요인을 실험으로 본다.</p>")]
    connection = _database([
        ("first", "세포와 물질대사", URL.format(school="a", round=1, seq=16), plan),
        ("third", "세포와 물질대사", URL.format(school="a", round=3, seq=1), revised),
        ("pdf", "세포와 물질대사", URL.format(school="a", round=3, seq=4), plan),
    ])

    dropped = find_duplicates(connection)

    # 3차·첨부 4가 가장 새 판이다.
    assert dropped == {"first": "pdf", "third": "pdf"}


def test_different_plans_schools_and_subjects_are_kept() -> None:
    plan = [("효소 반응 탐구 보고서", "<p>효소의 활성에 영향을 주는 요인을 실험으로 확인한다.</p>")]
    other_plan = [("효소 반응 탐구 보고서", "<p>감자즙과 과산화수소로 기체 발생량을 잰다.</p>")]
    connection = _database([
        ("a1", "세포와 물질대사", URL.format(school="a", round=3, seq=1), plan),
        ("a2", "세포와 물질대사", URL.format(school="a", round=3, seq=2), other_plan),
        ("b1", "세포와 물질대사", URL.format(school="b", round=3, seq=1), plan),
        ("a3", "생명과학", URL.format(school="a", round=3, seq=3), plan),
    ])

    assert find_duplicates(connection) == {}


PLAN = [("효소 반응 탐구 보고서", "<p>효소의 활성에 영향을 주는 요인을 실험으로 확인한다.</p>")]


def test_a_newer_attachment_the_site_does_not_show_never_hides_the_plan() -> None:
    connection = _database([
        ("shown", "생명과학", URL.format(school="a", round=1, seq=1), PLAN),
        ("hidden", "생명과학", URL.format(school="a", round=3, seq=1), PLAN, "[1]", False),
    ])

    # 3차 판은 확정 과제가 없다. 보이는 1차 판을 남긴다.
    assert find_duplicates(connection) == {"hidden": "shown"}


def test_the_same_text_for_another_grade_or_no_grade_is_one_plan() -> None:
    near = [("효소 반응 탐구 보고서", "<p>효소의 활성에 영향을 주는 요인을 실험으로 본다.</p>")]
    connection = _database([
        ("grade1", "과학탐구실험2", URL.format(school="a", round=3, seq=2), PLAN, "[1]"),
        ("grade2", "과학탐구실험2", URL.format(school="a", round=3, seq=1), PLAN, "[2]"),
        ("blank", "과학탐구실험2", URL.format(school="a", round=1, seq=1), near, "[]"),
    ])

    dropped = find_duplicates(connection)

    # 학년이 다르면 본문이 같아야 하고, 학년이 비어 있으면 비슷하기만 해도 된다.
    assert dropped == {"grade2": "grade1", "blank": "grade1"}


def test_different_grades_with_revised_text_are_kept_apart() -> None:
    revised = [("효소 반응 탐구 보고서", "<p>효소의 활성에 영향을 주는 요인을 실험으로 본다.</p>")]
    connection = _database([
        ("grade1", "과학탐구실험2", URL.format(school="a", round=3, seq=2), PLAN, "[1]"),
        ("grade2", "과학탐구실험2", URL.format(school="a", round=3, seq=1), revised, "[2]"),
    ])

    assert find_duplicates(connection) == {}


def test_glyphs_are_normalized_in_every_table_including_without_rowid(tmp_path) -> None:
    from scripts.normalize_symbol_glyphs import normalize_database

    database = tmp_path / "publish.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE assessment_items (item_id TEXT, method TEXT, "
        "source_html_zlib BLOB, rubric_html_zlib BLOB, rubric_html_char_count INTEGER)"
    )
    connection.execute(
        "CREATE TABLE assessment_item_axes (item_id TEXT, axis TEXT, value TEXT, "
        "PRIMARY KEY (item_id, axis, value)) WITHOUT ROWID"
    )
    connection.execute(
        "INSERT INTO assessment_items VALUES ('a-1', ?, ?, NULL, 0)",
        (" 서술  실험", zlib.compress("<p> 활동</p>".encode())),
    )
    connection.execute("INSERT INTO assessment_item_axes VALUES ('a-1', 'method', ' 실험')")
    connection.commit()
    connection.close()

    normalize_database(database)

    connection = sqlite3.connect(database)
    method, html = connection.execute(
        "SELECT method, source_html_zlib FROM assessment_items"
    ).fetchone()
    assert method == "□ 서술 ☑ 실험"
    assert zlib.decompress(html).decode("utf-8") == "<p>• 활동</p>"
    assert connection.execute("SELECT value FROM assessment_item_axes").fetchone()[0] == "☑ 실험"
