import json
import sqlite3

from scripts.build_biology_assessment_detail_db import SCHEMA_SQL
from scripts.build_biology_assessment_publish_db import (
    assessment_category,
    assessment_structure,
    category_for,
    derive_task_names,
    normalize_task_name,
    plain_text,
    refresh_cases_from_items,
    task_name_is_rejected,
)


def test_plain_text_preserves_html_table_cells() -> None:
    text = plain_text(
        "<table><tr><td>수행평가</td><td>온도에 따른 효소 반응 속도 측정</td>"
        "<td>소화효소를 이용한 영양소 분해 실험 보고서</td></tr></table>"
    )

    assert "수행평가 | 온도에 따른 효소 반응 속도 측정" in text
    assert "속도 측정 | 소화효소를 이용한 영양소 분해 실험 보고서" in text


def test_derive_task_names_stays_inside_subject_section() -> None:
    evidence = """
    # 2026년도 미디어 영어과 교수학습 및 평가 운영 계획
    <table><tr><td>영어 미디어 스토리보드 보고서</td></tr></table>
    # 2026년도 (생명과학Ⅱ)과 교수학습 및 평가 운영 계획
    <table><tr><td>고사/평가과제</td><td>온도에 따른 효소 반응 속도 측정</td>
    <td>소화효소를 이용한 영양소 분해 실험 보고서</td></tr></table>
    평가방법
    ☑ 서술·논술 □ 구술·발표 □ 토의·토론 □ 프로젝트
    """

    names, local_text, sources = derive_task_names(
        evidence,
        ["영어 미디어 스토리보드 보고서", "☑ 서술·논술 □ 구술·발표"],
        "생명과학Ⅱ",
    )

    assert names[0] == "소화효소를 이용한 영양소 분해 실험 보고서"
    assert "온도에 따른 효소 반응 속도 측정" in names
    assert all("영어" not in name for name in names)
    assert all("서술·논술" not in name for name in names)
    assert "미디어 영어" not in local_text
    assert sources[names[0]] in {"table", "section"}


def test_assessment_method_option_rows_are_not_task_names() -> None:
    assert task_name_is_rejected("☑ 서술·논술 □ 구술·발표 □ 토의·토론 □ 프로젝트")
    assert task_name_is_rejected("◻조사·발표")
    assert task_name_is_rejected("평가방법 | 서술·논술 | 프로젝트")
    assert task_name_is_rejected(
        "발표 전달력이 현저히 낮으며 발표 준비가 부실하여 형식을 지키지 않음.(5점)"
    )


def test_vertical_task_label_does_not_capture_the_whole_rubric_column() -> None:
    evidence = """
    <table>
      <tr><td>수행평가과제명</td><td>혈액형 검사를 통해 혈액형 판별하기</td></tr>
      <tr><td>평가 기준 3개 충족</td><td>우수</td></tr>
      <tr><td>개념 이해 및 적용이 부족함</td><td>미흡</td></tr>
    </table>
    """

    names, _, _ = derive_task_names(evidence, [], "생명과학")

    assert names == ["혈액형 검사를 통해 혈액형 판별하기"]


def test_horizontal_task_header_still_reads_task_name_column() -> None:
    evidence = """
    <table>
      <tr><th>수행평가명</th><th>반영 비율</th></tr>
      <tr><td>방형구법으로 식물군집 분석하기</td><td>20%</td></tr>
    </table>
    """

    names, _, _ = derive_task_names(evidence, [], "생명과학")

    assert names == ["방형구법으로 식물군집 분석하기"]


def test_rowspan_grid_does_not_shift_rubric_cells_into_task_column() -> None:
    evidence = """
    <table>
      <tr><th>평가영역</th><th>평가요소</th><th colspan="2">채점 기준</th><th>부여점수</th></tr>
      <tr><td rowspan="4">생태계보전방안탐구</td><td rowspan="4">생태계보전방안</td>
      <td rowspan="4">주제 선정 및 조사 목표 작성</td>
      <td>평가 기준 4개 모두 충족</td><td>50점</td></tr>
      <tr><td>평가 기준 3개 충족</td><td>40점</td></tr>
      <tr><td>평가 기준 2개 충족</td><td>30점</td></tr>
      <tr><td>평가 기준 1개 이하 충족</td><td>20점</td></tr>
    </table>
    """

    names, _, _ = derive_task_names(evidence, [], "생명과학")

    assert names[0] == "생태계 보전 방안 탐구"
    assert all("평가 기준" not in name for name in names)


def test_table_position_alone_does_not_publish_a_field_label() -> None:
    evidence = """
    <table>
      <tr><td>수행평가명</td><td>학기말 합계</td></tr>
      <tr><td>수행평가명</td><td>부정행위</td></tr>
      <tr><td>수행평가명</td><td>출제 의도</td></tr>
    </table>
    """

    names, _, _ = derive_task_names(evidence, [], "생명과학")

    assert names == []


def test_only_the_cell_after_a_task_label_gets_label_confidence() -> None:
    evidence = (
        "평가영역 | 생명과학적 탐구 및 분석 | 서술·논술 | "
        "탐구 주제 선정 및 계획 | 실제 문제 해결 역량 평가"
    )

    names, _, sources = derive_task_names(evidence, [], "생명과학")

    assert names == ["생명과학적 탐구 및 분석"]
    assert sources == {"생명과학적 탐구 및 분석": "context"}


def test_rubric_count_and_truncated_sentence_are_rejected() -> None:
    assert task_name_is_rejected(
        "1학기 매 수업시간에 참여하고 올바르게 작성한 실험 관찰 일지를 확인한 총 횟수"
    )


def test_checkbox_and_html_attribute_artifacts_are_removed() -> None:
    evidence = """
    <table>
      <tr><td>수행평가명</td><td>gfedc 프로젝트</td></tr>
      <tr><td>수행평가명</td><td>rowspan="5">독서활동발표</td></tr>
      <tr><td>수행평가명</td><td>lspan="4">생태계 관찰 보고서</td></tr>
      <tr><td>수행평가명</td><td>포트폴리오 gfedc 발표</td></tr>
      <tr><td>수행평가명</td><td>td rowspan="3">돌연변이 실험 설계</td></tr>
    </table>
    """

    names, _, _ = derive_task_names(evidence, [], "생명과학")

    assert "프로젝트" not in names
    assert "독서 활동 발표" in names
    assert "생태계 관찰 보고서" in names
    assert "돌연변이 실험 설계" in names
    assert "포트폴리오 발표" not in names
    assert all("span=" not in name and "gfedc" not in name for name in names)


def test_spacing_variants_are_merged_into_one_readable_title() -> None:
    evidence = """
    <table>
      <tr><td>수행평가명</td><td>식물세포관찰실험</td></tr>
      <tr><td>수행평가명</td><td>식물 세포 관찰 실험</td></tr>
      <tr><td>수행평가명</td><td>돌연변이생성실험</td></tr>
      <tr><td>수행평가명</td><td>돌연변이 생성 실험</td></tr>
    </table>
    """

    names, _, _ = derive_task_names(evidence, [], "생명과학")

    assert set(names) == {"식물 세포 관찰 실험", "돌연변이 생성 실험"}
    assert task_name_is_rejected(
        "세 가지 개념을 정확히 이해하고 설명하지만, 상호 관계에 대한 증명 과"
    )


def test_common_pdf_spacing_breaks_are_repaired_without_rewriting_the_title() -> None:
    assert normalize_task_name("생태 문제분석 및 문제만들기") == (
        "생태 문제 분석 및 문제 만들기"
    )
    assert normalize_task_name("개체군 생태학적 모델링프로젝트") == (
        "개체군 생태학적 모델링 프로젝트"
    )
    assert normalize_task_name("독서기반 생명과학 탐구활동") == "독서 기반 생명과학 탐구 활동"
    assert normalize_task_name("실험 결과를 적 용한 문제풀이") == (
        "실험 결과를 적용한 문제 풀이"
    )


def test_concrete_short_task_names_are_still_publishable() -> None:
    evidence = """
    <table>
      <tr><td>수행평가명</td><td>관찰일지</td></tr>
      <tr><td>수행평가명</td><td>생태 지도 그리기</td></tr>
      <tr><td>수행평가명</td><td>표본채집</td></tr>
      <tr><td>수행평가명</td><td>인포그래픽</td></tr>
    </table>
    """

    names, _, _ = derive_task_names(evidence, [], "생명과학")

    assert set(names) == {
        "표본채집",
        "생태 지도 그리기",
        "관찰일지",
        "인포그래픽",
    }


def test_score_and_policy_cells_are_not_task_names() -> None:
    assert task_name_is_rejected("반영 만점(비율) 10점")
    assert task_name_is_rejected("5점 x 2문제 =10점")
    assert task_name_is_rejected("19~20점 16.5~18.5점 12.5~16점 10점 이하")
    assert task_name_is_rejected("생명과학Ⅱ(3학점)")
    assert task_name_is_rejected("1학기 평가 내용 및 점수 부여 기준")
    assert task_name_is_rejected("평가 항목")
    assert task_name_is_rejected("학생 유의사항")
    assert task_name_is_rejected("1차시험(중간시험)")
    assert task_name_is_rejected("성취기준에 기반한 일관성 있는 평가")
    assert task_name_is_rejected("포트폴리오, 발표")
    assert task_name_is_rejected("과제탐구")
    assert task_name_is_rejected("실생활 문제 해결 중심의 역량 평가")
    assert task_name_is_rejected("실생활 데이터 분석 및 융합적 수행 역량 평가")
    assert task_name_is_rejected("토론 및 발표")
    assert task_name_is_rejected("서·논술형, 발표")
    assert task_name_is_rejected("관찰평가 포트폴리오")
    assert task_name_is_rejected("도서 기반 평가 방법 생명과학 탐구")
    assert task_name_is_rejected("추가적인 분량탐구활동")
    assert task_name_is_rejected("생명과학의 기본 개념 이해와 문제 해결 능력 신장")
    assert task_name_is_rejected("주제 선정,자료 수집 및 적용, 탐구 수행 및 결과물 제작")
    assert task_name_is_rejected("III. 창의적 사고와 문화 활동 (2) 문학의 소통과 문화 활동")
    assert task_name_is_rejected("근대 이전 한국사의 이해 2. 근대 이전 한국사의 탐구")
    assert task_name_is_rejected("공간정보와 지리탐구 2. 생활 속 지리탐구")
    assert task_name_is_rejected("화법과 작문 과정형 포트폴리오 제작")
    assert task_name_is_rejected(
        "I. 생명과학 탐구의 이해 II. 생명과학 탐구의 실행과 평가"
    )
    assert task_name_is_rejected("교수학습활동")
    assert task_name_is_rejected("III. 창의적 사고와 문화 활동")
    assert task_name_is_rejected("포트폴리오 ★사이버 어울림활동")
    assert task_name_is_rejected("I. 사회현상의 이해와 탐구")


def test_attached_field_labels_and_trailing_metadata_are_removed() -> None:
    assert normalize_task_name("평가영역도서기반생명과학탐구") == "도서 기반 생명과학 탐구"
    assert normalize_task_name("수행평가명 : 문제 해결 포트폴리오") == (
        "문제 해결 포트폴리오"
    )
    assert normalize_task_name("1. 수행평가명 : 문제해결 포트폴리오") == (
        "문제 해결 포트폴리오"
    )
    assert normalize_task_name("III.생태계와 개체군 교과융합프로젝트") == (
        "생태계와 개체군 교과 융합 프로젝트"
    )
    assert normalize_task_name("★수행평가-실생활 생명과학 탐구보고서") == (
        "실생활 생명과학 탐구 보고서"
    )
    assert normalize_task_name("생명과학 기사 작성 내용 (85)") == "생명과학 기사 작성 내용"
    assert normalize_task_name("탐구 보고서 2회") == "탐구 보고서"
    assert task_name_is_rejected(normalize_task_name("생명과학 기사 작성 내용 (85)"))
    assert task_name_is_rejected("기사문의 창의성 및 흥미도")


def test_trailing_score_metadata_is_removed_from_a_real_title() -> None:
    assert normalize_task_name("멘델의 유전 법칙을 이용한 완두콩 교배 탐구 : 100점, 25%") == (
        "멘델의 유전 법칙을 이용한 완두콩 교배 탐구"
    )


def test_mathematical_or_natural_language_is_not_overfiltered() -> None:
    assert not task_name_is_rejected(
        "생물 표본을 이용하여 곤충, 식물, 균류 중 2종 이상을 포함한 독창적인 도감 만들기"
    )
    assert not task_name_is_rejected(
        "저작권을 밝힌 글과 그렇지 못한 글 찾아 분석하기"
    )
    assert not task_name_is_rejected("먹이 사슬을 활용한 생태계 문제 만들기")
    assert not task_name_is_rejected("서식지를 고려한 나만의 생태 지도 설계")
    assert not task_name_is_rejected("생명과학으로 보는 환경 기사")
    assert not task_name_is_rejected("문학 작품 속 생태학적 구조 탐구")
    assert not task_name_is_rejected("미술 작품 속 생물학적 형태 탐구")


def test_subject_localization_stops_before_the_next_course() -> None:
    evidence = """
    생명 현상을 관찰하여 가설을 검증하기
    생명과학Ⅱ 교과가 목표로 하는 세부 능력을 평가한다.
    # 영어과 교수학습 및 평가 운영 계획
    영어 비판적 사고 영문 저널 프로젝트
    """

    names, local_text, _ = derive_task_names(evidence, [], "생명과학Ⅱ")

    assert names == ["생명 현상을 관찰하여 가설을 검증하기"]
    assert "영문 저널" not in local_text


def test_task_table_is_preferred_and_exposed_as_structured_fields() -> None:
    evidence = """
    ## 나. 수행평가 출제계획
    ## 1) 생명과학 독서 기반 사고 확장 글쓰기
    <table>
      <tr><th>수행평가과제명</th><th>생명과학 독서 기반<br>사고 확장 글쓰기</th></tr>
      <tr><td>평가 영역 (성취기준)</td><td>[12생과01-01] 생명의 특성을 설명한다.</td></tr>
      <tr><td>평가 요소</td><td>문제 해결 능력 · 탐구 논리</td></tr>
      <tr><td>평가 방법</td><td>☑ 서술·논술 □ 구술·발표 ☑ 포트폴리오</td></tr>
      <tr><td>반영 비율</td><td>20점 / 20%</td></tr>
    </table>
    """

    names, _, sources = derive_task_names(evidence, [], "생명과학")
    assert names[0] == "생명과학 독서 기반 사고 확장 글쓰기"
    structure = assessment_structure(evidence, names[0], sources)
    assert structure["basis"] == "table"
    assert structure["standards"] == ["12생과01-01"]
    assert "서술·논술" in structure["methods"]
    assert structure["weight"] == "20점 · 20%"
    assert assessment_category(names[0], structure, evidence) == "reading"


def test_category_uses_the_displayed_task_not_a_neighboring_table_task() -> None:
    structure = {
        "overview": "문제 해결 과제와 생명과학 독서 보고서를 함께 운영한다.",
        "criteria": ["독서 결과물의 완성도를 평가한다."],
    }

    assert assessment_category("서술형 문제 해결력", structure, "") == ""
    assert assessment_category("생명과학 독서 탐구", structure, "") == "reading"


def test_colspan_values_are_not_repeated_in_the_public_overview() -> None:
    evidence = """
    <table>
      <tr><td>수행평가명</td><td colspan="3">생태 그래프 탐구 보고서</td></tr>
      <tr><td>평가개요</td><td colspan="3">개체수의 변화를 관찰하고 보고서로 정리한다.</td></tr>
    </table>
    """

    names, _, sources = derive_task_names(evidence, [], "생명과학")
    structure = assessment_structure(evidence, names[0], sources)

    assert structure["overview"] == "개체수의 변화를 관찰하고 보고서로 정리한다."


def test_generic_colspan_label_is_not_used_as_an_overview() -> None:
    evidence = """
    <table>
      <tr><td>수행평가명</td><td colspan="3">생태 그래프 탐구 보고서</td></tr>
      <tr><td colspan="4">세부 평가 내용</td></tr>
    </table>
    """

    names, _, sources = derive_task_names(evidence, [], "생명과학")
    structure = assessment_structure(evidence, names[0], sources)

    assert structure["overview"] == ""


def test_category_does_not_leak_from_unrelated_document_context() -> None:
    structure = {"overview": "문제 풀이 과정을 작성한다.", "criteria": []}
    assert assessment_category("문제 풀이 과정 작성하기", structure, "앞부분 독서 안내") == ""


def _case_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(SCHEMA_SQL)
    connection.execute(
        """
        CREATE TABLE cases (
            case_id TEXT PRIMARY KEY,
            primary_task_name TEXT NOT NULL,
            task_names_json TEXT NOT NULL,
            summary_overview TEXT NOT NULL,
            methods_json TEXT NOT NULL,
            weight_summary TEXT NOT NULL,
            standards_json TEXT NOT NULL
        )
        """
    )
    return connection


def _insert_item(connection: sqlite3.Connection, **fields) -> None:
    row = {
        "item_id": "item-1",
        "case_id": "case-1",
        "item_order": 1,
        "title": "",
        "title_raw": "",
        "title_basis": "table",
        "extraction_status": "bounded",
        "overview": "",
        "method": "",
        "timing": "",
        "score": "",
        "weight": "",
        "standards_json": "[]",
        "rubric_html_char_count": 0,
        "source_html_zlib": None,
        "rubric_html_zlib": None,
    } | fields
    connection.execute(
        f"INSERT INTO assessment_items VALUES ({','.join('?' * len(row))})",
        tuple(row.values()),
    )


def test_case_fields_are_rederived_from_the_bounded_items() -> None:
    connection = _case_connection()
    connection.execute(
        "INSERT INTO cases VALUES (?,?,?,?,?,?,?)",
        (
            "case-1",
            "사회 집단의 유형",
            json.dumps(["사회 집단의 유형"]),
            "사회 조직의 유형과 사례를 조사하고",
            "[]",
            "",
            json.dumps(["[12사문01-01]"]),
        ),
    )
    _insert_item(
        connection,
        title="효소 탐구 보고서",
        overview="효소의 작용을 실험으로 확인한다",
        method="보고서",
        weight="20 %",
        standards_json=json.dumps(["[12생과Ⅱ01-01]"]),
    )
    _insert_item(
        connection,
        item_id="item-2",
        item_order=2,
        title="광합성 색소 분리 실험",
        title_basis="heading",
        standards_json=json.dumps(["[12생과Ⅱ03-02]"]),
    )

    assert refresh_cases_from_items(connection) == 1

    row = connection.execute("SELECT * FROM cases").fetchone()
    assert row[1] == "효소 탐구 보고서"
    assert json.loads(row[2]) == ["효소 탐구 보고서", "광합성 색소 분리 실험"]
    assert row[3] == "효소의 작용을 실험으로 확인한다"
    assert json.loads(row[4]) == ["보고서"]
    assert row[5] == "20 %"
    assert json.loads(row[6]) == ["[12생과Ⅱ01-01]", "[12생과Ⅱ03-02]"]


def test_unbounded_items_leave_the_case_fields_alone() -> None:
    connection = _case_connection()
    connection.execute(
        "INSERT INTO cases VALUES (?,?,?,?,?,?,?)",
        ("case-1", "원래 이름", "[]", "원래 개요", "[]", "", "[]"),
    )
    _insert_item(
        connection,
        title="수행평가 원문 구간",
        title_basis="unbounded_bundle",
        extraction_status="bundle_review",
    )

    assert refresh_cases_from_items(connection) == 0
    assert connection.execute("SELECT primary_task_name FROM cases").fetchone()[0] == "원래 이름"


def test_category_is_empty_when_no_seed_tag_matches() -> None:
    assert category_for(["생태조사"]) == ""
    assert category_for(["탐구"]) == "inquiry"
    assert category_for(["토론", "탐구"]) == "inquiry"
    assert category_for(["실험"]) == "experiment"
