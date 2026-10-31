# NOTE(biology-fork): fixtures below are translated from the original math-fork
# suite to biology subjects/achievement codes. The parser itself
# (biology_assessment_detail_parser.py) is subject-agnostic; only the subject
# names and achievement-code prefixes needed to match this fork's
# EXPECTED_STANDARD_PREFIXES for the alignment-sensitive tests to still
# exercise real logic.
#
# Nine tests from the original file are intentionally dropped, not translated:
# they exercised scripts.repair_biology_assessment_titles and
# scripts.build_biology_assessment_detail_db, two modules that test a
# separate title-recovery/detail-priority pipeline that was never ported to
# this biology fork (neither exists here, and neither existed in the math
# reference dump this project was forked from). Inventing them from the test
# assertions alone would mean fabricating scoring/business logic no one
# reviewed for biology; that is out of scope for this fix.

import pytest
from scripts.biology_assessment_detail_parser import (
    _field_value_is_usable,
    balance_table_tags,
    biology_standard_codes,
    heading_title_is_structural,
    markdown_fragment_to_html,
    normalize_checkbox_glyphs,
    parse_assessment_section,
    segment_subject_alignment,
    subject_local_markdown,
    visible_text,
)


def test_subject_code_alignment_does_not_confuse_math_one_and_two() -> None:
    math_two = "<table><tr><td>[12생과Ⅱ01-04] 연속함수의 성질</td></tr></table>"
    math_one = "<table><tr><td>[12생과Ⅰ01-01] 지수함수와 로그함수</td></tr></table>"

    assert segment_subject_alignment(math_two, "생명과학Ⅰ") == "other"
    assert segment_subject_alignment(math_two, "생명과학Ⅱ") == "expected"
    assert segment_subject_alignment(math_one, "생명과학Ⅰ") == "expected"
    assert segment_subject_alignment(math_one, "생명과학Ⅱ") == "other"


@pytest.mark.parametrize(
    ("code", "subject"),
    [
        # 전문교과·중학교 코드는 앞자리 학년 숫자가 없거나 한 자리라, 예전
        # "10|12로 시작하는 코드"만 보던 규칙에는 코드로 잡히지도 않았다.
        ("[프로02-01]", "생명과학Ⅱ"),
        ("[자구01-02]", "생명과학Ⅱ"),
        ("[알설04-01]", "생명과학Ⅱ"),
        ("[9음03-01]", "통합과학1"),
        ("[일물I21-01]", "생명과학실험"),
        ("[11지능01-02]", "생명과학Ⅱ"),
    ],
)
def test_other_subject_code_marks_the_segment_as_another_subject(
    code: str, subject: str
) -> None:
    segment = f"<table><tr><td>{code} 프로그램을 구현할 수 있다</td></tr></table>"

    assert segment_subject_alignment(segment, subject) == "other"


@pytest.mark.parametrize(
    ("code", "subject"),
    [
        # 학교가 자리 순서를 바꿔 적은 생명과학 교과군 코드는 그대로 남는다.
        ("[12고생01-01]", "고급생명과학"),
        ("[고생1201-01]", "고급생명과학"),
        ("[10통과1-03-05]", "통합과학1"),
        ("[통과1-03-05]", "통합과학1"),
        ("[12생과Ⅱ01-01]", "생명과학Ⅱ"),
        ("[12생실01-01]", "생명과학실험"),
    ],
)
def test_biology_group_codes_are_not_read_as_another_subject(
    code: str, subject: str
) -> None:
    segment = f"<table><tr><td>{code} 세포를 관찰할 수 있다</td></tr></table>"

    assert segment_subject_alignment(segment, subject) != "other"


def test_score_labels_shaped_like_codes_are_not_subject_evidence() -> None:
    # "[기본점수 - 4]"는 배점 표기지 성취기준 코드가 아니다.
    segment = "<table><tr><td>[기본점수 - 4]</td><td>[영역2-1]</td></tr></table>"

    assert segment_subject_alignment(segment, "생명과학Ⅱ") == "unknown"


def test_combined_plan_uses_exact_short_course_heading_boundary() -> None:
    source = """
    생명과학과 평가계획
    1. 통합과학1
    2. 생명과학
    3. 과학탐구실험

    # 통합과학1
    ## 수행평가 세부 계획
    가. 공통생명과학 탐구
    <table><tr><th>성취기준</th><td>[10통과1-01-01]</td></tr><tr><th>평가방법</th><td>탐구</td></tr></table>

    # 생명과학
    ## 수행평가 세부 계획
    가. 지수함수 모델링
    <table><tr><th>성취기준</th><td>[12생과01-01]</td></tr><tr><th>평가방법</th><td>보고서</td></tr></table>

    # 과학탐구실험 (2학기)
    ## 수행평가 세부 계획
    가. 이차곡선 설계
    <table><tr><th>성취기준</th><td>[10과탐01-01]</td></tr><tr><th>평가방법</th><td>프로젝트</td></tr></table>
    """

    algebra = parse_assessment_section(source, "생명과학")

    assert algebra.boundary_status.startswith("subject_heading_exact:")
    assert [item.title for item in algebra.items] == ["지수함수 모델링"]
    assert algebra.items[0].extraction_status == "bounded"
    assert "이차곡선 설계" not in algebra.source_markdown


def test_exact_math_heading_stops_at_a_non_math_course_plan() -> None:
    source = """
    # 통합과학1
    ## 수행평가 세부 계획
    가. 이차함수 문제 해결
    <table><tr><th>성취기준</th><td>[10통과1-02-07]</td></tr>
    <tr><th>평가방법</th><td>서술형</td></tr></table>

    # 2026학년도 1학기 [공통영어1] 교수학습 및 평가 운영 계획
    # 공통영어1
    ## 수행평가 세부 계획
    가. 영어 역할극 영상 제작
    <table><tr><th>성취기준</th><td>[10공영1-02-01]</td></tr></table>
    """

    section = parse_assessment_section(source, "통합과학1")

    assert [item.title for item in section.items] == ["이차함수 문제 해결"]
    assert "영어 역할극" not in section.source_markdown


def test_short_performance_assessment_heading_is_a_block_anchor() -> None:
    source = """
    # 과학탐구실험
    가. 평가 목적
    평가를 통해 학습을 지원한다.
    라. 수행평가 영역 및 배점
    1) 이차곡선 설계 프로젝트
    <table><tr><th>성취기준</th><td>[10과탐01-01]</td></tr><tr><th>평가방법</th><td>프로젝트</td></tr></table>
    마. 결시자 처리 기준
    """

    section = parse_assessment_section(source, "과학탐구실험")

    assert section.boundary_status == "subject_heading_exact:assessment_anchor"
    assert [item.title for item in section.items] == ["이차곡선 설계 프로젝트"]
    assert section.items[0].extraction_status == "bounded"


def test_pdf_summary_table_rows_become_separate_confirmed_items() -> None:
    source = """
    # 생명과학실험
    ## 수행평가 세부 계획
    | 평가방법 | 성취기준 | 평가 요소 | 배점 | 수행평가 과제 |
    | --- | --- | --- | --- | --- |
    | 서·논술형 | [12생실03-06] | 표본평균 설명 | 100점 | 주제 탐구 프로젝트 |
    | 포트폴리오 | [12생실03-07] | 풀이 과정 기록 | 100점 | 오답 노트 작성 |
    """

    section = parse_assessment_section(source, "생명과학실험")

    assert [item.title for item in section.items] == ["주제 탐구 프로젝트", "오답 노트 작성"]
    assert all(item.extraction_status == "bounded" for item in section.items)
    assert section.items[0].standards == ("[12생실03-06]",)
    assert "오답 노트 작성" not in section.items[0].source_html


def test_summary_table_item_keeps_its_matching_rubric_row() -> None:
    source = """
    # 생명과학실험
    ## 수행평가 세부 계획
    | 평가방법 | 성취기준 | 배점 | 수행평가 과제 |
    | --- | --- | --- | --- |
    | 서·논술형 | [12생실03-06] | 100점 | 주제 탐구 프로젝트 |
    | 포트폴리오 | [12생실03-07] | 100점 | 오답 노트 작성 |

    ### 수행평가 채점 기준
    | 평가과제 | 수행평가 채점 기준 |
    | --- | --- |
    | 주제 탐구 프로젝트 | 자료 분석 근거가 정확하면 100점 |
    | 오답 노트 작성 | 풀이 과정이 충실하면 100점 |
    """

    section = parse_assessment_section(source, "생명과학실험")

    first = next(item for item in section.items if item.title == "주제 탐구 프로젝트")
    assert "자료 분석 근거가 정확하면 100점" in first.rubric_html
    assert "풀이 과정이 충실하면 100점" not in first.rubric_html


def test_rubric_rows_do_not_become_separate_assessment_items() -> None:
    source = """
    # 고급생명과학
    ## 수행평가 세부 계획
    | 평가방법 | 성취기준 | 수행평가 과제 |
    | --- | --- | --- |
    | 보고서 | [12고생01-01] | 현상 분석 탐구 보고서 |

    ## 수행평가 채점 기준
    | 평가 항목 | 평가 요소 | 수행 수준 | 배점 |
    | --- | --- | --- | --- |
    | 주제 선정 | 적절성 | 탐구 목적이 분명함 | 10점 |
    | 자료 분석 | 논리성 | 근거가 타당함 | 10점 |
    """

    section = parse_assessment_section(source, "고급생명과학")

    assert [item.title for item in section.items] == ["현상 분석 탐구 보고서"]


def test_written_exam_columns_of_the_summary_table_are_not_assessment_titles() -> None:
    source = """
    # 생명과학
    Ⅳ. 평가 방법
    <table>
    <tr><td>구분</td><td colspan="2">정기시험 (60%)</td><td colspan="2">수행평가 (40%)</td></tr>
    <tr><td>평가영역</td><td>단답형</td><td>서술형</td>
    <td>생명과학 에세이</td><td>독서발표</td></tr>
    <tr><td>반영비율</td><td>30%</td><td>30%</td><td>25%</td><td>15%</td></tr>
    </table>
    2. 수행평가 세부 기준
    <table>
    <tr><td>평가 영역</td><td>생명과학 에세이</td><td>만점(반영비율)</td><td>100점(25%)</td></tr>
    <tr><td>성취기준</td><td colspan="3">[12생과01-01] 세포를 설명할 수 있다</td></tr>
    <tr><td>평가요소</td><td colspan="2">채점기준</td><td>배점</td></tr>
    <tr><td>내용</td><td colspan="2">근거가 타당함</td><td>50</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "생명과학")

    titles = [item.title for item in section.items if item.extraction_status == "bounded"]
    assert "단답형" not in titles
    assert "서술형" not in titles


def test_rubric_table_after_overview_table_stays_a_separate_table() -> None:
    fragment = """
<table>
<tr><th colspan="2">평가영역</th><th colspan="3">생명과학의 역사</th>
<th>반영비율</th><th>20 %</th></tr>
<tr><td colspan="2">교과 역량</td><td colspan="5"></td></tr>
<tr><td colspan="2" rowspan="2">성취기준</td><td rowspan="2">[12생과Ⅱ01-01]</td>
<td>상</td><td colspan="3">설명할 수 있다.</td></tr>
<tr><td>중</td><td colspan="3">나열할 수 있다.</td></tr>
</table>

<table>
<tr><th>평가요소</th><th>횟수</th><th>배점</th><th>채점기준</th><th>평정점</th></tr>
<tr><td>내용의 적절성</td><td>1</td><td>80</td><td>논리적으로 표현한 경우</td><td>80</td></tr>
</table>
"""

    rendered = markdown_fragment_to_html(fragment)

    assert rendered.count("<table>") == 2
    assert rendered.count("</table>") == 2


def test_the_next_assessments_table_is_not_fused_into_the_previous_one() -> None:
    # kordoc keeps a multi-page table whole; a table that follows another with
    # only blank lines between is the next assessment's table (실측: 서울 한
    # 학교 계획서의 "기타 사항" 행 뒤 "평가과제(영역)명 | 진로 연계 발표").
    fragment = """
<table>
<tr><th>평가과제(영역)명</th><th>심화 주제 탐구 프로젝트</th></tr>
<tr><td>기타 사항</td><td>▪수행평가 결과물을 백지로 제출한 경우 기본 점수 부여</td></tr>
</table>

<table>
<tr><th>평가과제(영역)명</th><th>진로 연계 발표</th></tr>
<tr><td>평가시기</td><td>5월</td></tr>
</table>
"""

    rendered = markdown_fragment_to_html(fragment)

    assert rendered.count("<table>") == 2
    assert rendered.count("</table>") == 2
    first, second = rendered.split("</table>", 1)
    assert "진로 연계 발표" not in first
    assert "진로 연계 발표" in second


def test_summary_row_with_another_course_code_is_not_published() -> None:
    source = """
    # 생명과학
    ## 수행평가 세부 계획
    <table>
      <tr><th>평가방법</th><th>성취기준</th><th>평가과제</th></tr>
      <tr><td>보고서</td><td>[10과탐01-01]</td><td>이차곡선 탐구</td></tr>
      <tr><td>보고서</td><td>[12생과01-01]</td><td>지수함수 모델링</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "생명과학")

    assert [item.title for item in section.items] == ["지수함수 모델링"]


def test_expected_code_table_recovers_math_from_headingless_combined_source() -> None:
    source = """
    여러 교과 평가계획
    <table>
      <tr><th>평가 영역명</th><td>영어 역할극</td></tr>
      <tr><th>성취기준</th><td>[10공영1-02-04]</td></tr>
      <tr><th>평가방법</th><td>발표</td></tr>
    </table>
    <table>
      <tr><th>평가 영역명</th><td>지수함수로 미래 예측하기</td></tr>
      <tr><th>성취기준</th><td>[12생과01-01]</td></tr>
      <tr><th>평가방법</th><td>탐구 보고서</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "생명과학")

    assert [item.title for item in section.items] == ["지수함수로 미래 예측하기"]
    assert section.items[0].extraction_status == "bounded"
    assert "영어 역할극" not in section.items[0].source_html


def test_mixed_standard_code_table_is_not_recovered_globally() -> None:
    source = """
    여러 교과 평가계획
    <table>
      <tr><th>평가 영역명</th><td>교과 융합 자료 묶음</td></tr>
      <tr><th>성취기준</th><td>[12생과01-01] [10공영1-02-04]</td></tr>
      <tr><th>평가방법</th><td>보고서</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "생명과학").items[0]

    assert item.extraction_status == "bundle_review"
    assert item.title == "수행평가 원문 구간"


def test_explicit_table_is_recovered_inside_exact_course_without_section_anchor() -> None:
    source = """
    # 생명과학Ⅱ
    평가 운영 안내
    <table>
      <tr><th>평가 영역명</th><td>문제 해결과정 논술하기</td><th>영역만점</th><td>10점</td></tr>
      <tr><th>수행과제</th><td>논리적인 근거를 제시하여 해결 과정을 설명한다.</td></tr>
      <tr><th>성취기준</th><td>[12생과Ⅱ02-01]</td></tr>
      <tr><th>평가방법</th><td>서·논술형</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "생명과학Ⅱ")

    assert [item.title for item in section.items] == ["문제 해결과정 논술하기"]
    assert section.items[0].extraction_status == "bounded"


def test_plain_assessment_area_label_is_source_authored_title_evidence() -> None:
    source = """
    # 2026학년도 (과학탐구실험1)과 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    <table>
      <tr><th>평가영역</th><td>텍스트 자료 처리하기</td><th>영역만점</th><td>20점</td></tr>
      <tr><th>평가요소</th><td>텍스트에서 유용한 정보 찾기 20(점)</td></tr>
      <tr><th>성취기준</th><td>[10과탐102-02]</td></tr>
      <tr><th>평가방법</th><td>프로젝트</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "과학탐구실험1").items[0]

    assert item.title == "텍스트 자료 처리하기"


def test_area_max_header_recovers_task_name_and_strips_score_suffix() -> None:
    source = """
    # 2026학년도 (고급생명과학)과 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    <table>
      <tr><th>영역(만점)</th><th>평가항목</th><th>평가요소</th>
      <th>채점기준</th><th>배점</th></tr>
      <tr><td>고급생명과학보고서 (25)</td><td>주제</td>
      <td>논리성</td><td>타당함</td><td>25</td></tr>
      <tr><th>성취기준</th><td colspan="4">[12고생02-03]</td></tr>
      <tr><th>평가방법</th><td colspan="4">보고서</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "고급생명과학").items[0]

    assert item.title == "고급생명과학보고서"


def test_assessment_matrix_keeps_only_performance_assessment_columns() -> None:
    source = """
    # 통합과학1
    ## 평가의 종류와 반영 비율
    <table>
      <tr><th>평가종류</th><th>정기고사</th><th>정기고사</th><th>수행평가</th><th>수행평가</th></tr>
      <tr><th>반영비율</th><td>30%</td><td>30%</td><td>20%</td><td>20%</td></tr>
      <tr><th>평가영역</th><td>1차 정기고사</td><td>2차 정기고사</td>
      <td>생명과학 탐구 및 발표</td><td>문제해결 포트폴리오</td></tr>
      <tr><th>만점</th><td>100점</td><td>100점</td><td>100점</td><td>100점</td></tr>
      <tr><th>평가방법</th><td>선택형</td><td>선택형</td><td>탐구 발표</td><td>활동지 작성</td></tr>
      <tr><th>성취기준</th><td></td><td></td><td>[10통과1-01-01]</td><td>[10통과1-02-01]</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "통합과학1")

    assert [item.title for item in section.items] == [
        "생명과학 탐구 및 발표",
        "문제해결 포트폴리오",
    ]
    assert section.items[0].weight == "20%"
    assert section.items[0].method == "탐구 발표"
    assert "1차 정기고사" not in section.items[0].source_html


def test_catalogue_hint_is_used_only_when_the_original_table_cell_confirms_it() -> None:
    source = """
    # 생명과학
    <table>
      <tr><th>구분</th><th>내용</th></tr>
      <tr><td>수행평가 활동</td><td>하노이 탑 수열 규칙 탐구</td></tr>
      <tr><td>성취기준</td><td>[12생과03-01]</td></tr>
      <tr><td>평가방법</td><td>탐구 보고서</td></tr>
      <tr><td>배점</td><td>20점</td></tr>
    </table>
    """

    section = parse_assessment_section(
        source,
        "생명과학",
        ("하노이 탑 수열 규칙 탐구", "원문에 없는 제목"),
    )

    assert [item.title for item in section.items] == ["하노이 탑 수열 규칙 탐구"]
    assert section.items[0].extraction_status == "bounded"


def test_separates_each_heading_and_keeps_its_own_rubric() -> None:
    source = """
    # 2026학년도 (생명과학)과 교수학습 및 평가 운영 계획
    ## 6. 수행평가 세부 기준

    가. 지수와 로그 문제해결력 평가(100점 만점, 반영 비율 10%)
    <table>
      <tr><th>성취기준</th><td>[12생과01-01]</td></tr>
      <tr><th>평가개요</th><td>지수와 로그 문제의 풀이 과정을 평가한다.</td></tr>
      <tr><th>평가 방법</th><td>논·서술형</td></tr>
      <tr><th>평가영역</th><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
      <tr><td>문제해결</td><td>논리</td><td>과정이 정확함</td><td>10점</td></tr>
    </table>

    나. 삼각함수 문제해결력 평가(100점 만점, 반영 비율 10%)
    <table>
      <tr><th>성취기준</th><td>[12생과02-01]</td></tr>
      <tr><th>평가개요</th><td>삼각함수 문제의 풀이 과정을 평가한다.</td></tr>
      <tr><th>평가 방법</th><td>논·서술형</td></tr>
      <tr><th>평가요소</th><th>세부기준</th><th>부여점수</th></tr>
      <tr><td>표현</td><td>그래프가 정확함</td><td>10점</td></tr>
    </table>

    # 7. 결시자와 학적 변동자 처리 기준
    """

    section = parse_assessment_section(source, "생명과학")

    assert [item.title for item in section.items] == [
        "지수와 로그 문제해결력 평가",
        "삼각함수 문제해결력 평가",
    ]
    assert section.items[0].overview == "지수와 로그 문제의 풀이 과정을 평가한다."
    assert section.items[0].standards == ("[12생과01-01]",)
    assert "과정이 정확함" in section.items[0].rubric_html
    assert "그래프가 정확함" not in section.items[0].rubric_html
    assert "그래프가 정확함" in section.items[1].rubric_html


def test_explicit_area_name_replaces_a_structural_numbered_heading() -> None:
    source = """
    # 2025학년도 (생명과학Ⅱ)과 교수학습 및 평가 운영 계획
    ## 6. 수행평가 세부 기준
    1) 교육과정 성취기준 및 평가기준, 평가 요소 및 배점
    <table>
      <tr><th>평가 영역명</th><td>미분을 활용하여 함수 그래프 그리기</td>
      <th>영역만점</th><td>15점</td></tr>
      <tr><th>수행과제</th><td>함수의 증가와 감소를 설명한다.</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
      <tr><td>그래프</td><td>개형이 정확함</td><td>15점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "생명과학Ⅱ").items[0]

    assert item.title == "미분을 활용하여 함수 그래프 그리기"
    assert item.title_basis == "table"
    assert item.extraction_status == "bounded"
    assert item.score == "15점"


def test_explicit_task_field_replaces_a_generic_process_assessment_heading() -> None:
    source = """
    # 2026학년도 (생명과학)과 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    다. 학습과정평가
    <table>
      <tr><th>평가 영역명</th><td>학습과정평가</td><th>영역만점</th><td>10점</td></tr>
      <tr><th>수행과제</th><td>학습과정 포트폴리오(수업 필기 및 문제풀이 정리)</td></tr>
      <tr><th>성취기준</th><td>[12생과01-01]</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>정리</td><td>근거가 타당함</td><td>10점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "생명과학").items[0]

    assert item.title == "학습과정 포트폴리오(수업 필기 및 문제풀이 정리)"
    assert item.title_basis == "table"
    assert item.extraction_status == "bounded"


def test_long_task_instruction_does_not_replace_the_source_heading_as_a_title() -> None:
    source = """
    # 2026학년도 (통합과학1)과 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    나. 생활 속 주제 탐구
    <table>
      <tr><th>수행 과제</th><td>통합과학1에서 배우는 다항식, 방정식과 부등식,
      경우의 수, 행렬과 관련하여 자유롭게 주제를 선정하여 보고서 작성하기.</td></tr>
      <tr><th>성취기준</th><td>[10통과1-01-01]</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>주제 선정</td><td>근거가 타당함</td><td>100점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "통합과학1").items[0]

    assert item.title == "생활 속 주제 탐구"
    assert item.title_basis == "heading"


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        (
            "4. 수행평가 세부 계획<br>가. 생명과학 독서 글쓰기(50%)",
            "생명과학 독서 글쓰기",
        ),
        (
            "6. 수행평가 세부기준<br>가. 수행평가 1: 이차곡선의 활용 탐구보고서(논술형)",
            # 평가 유형("논술형")은 평가 방법 칸에 따로 보인다.
            "이차곡선의 활용 탐구보고서",
        ),
        ("4. 포트폴리오 수행평가 기준", "포트폴리오"),
        ("4. 수행평가 영역1 : 서술형 평가", "서술형 평가"),
        ("4. 문제 해결 평가 기준", "문제 해결"),
        (
            "4. 포트폴리오 평가 (평가시기 : 3~6월 수시평가): 20점, 기본점수: 0점",
            "포트폴리오 평가",
        ),
        (
            "4. [서·논술형] 창의융합 프로젝트(평가시기: 6월) : 10점, 기본점수: 1점",
            "창의융합 프로젝트",
        ),
        (
            "4. 주제탐구1,2(25%, 25점): 단원에서 학습한 내용을 바탕으로 탐구함.",
            "주제탐구1,2",
        ),
        (
            "4. 수행평가 세부기준 (가) 주제탐구 독서감상문",
            "주제탐구 독서감상문",
        ),
        (
            "4. 4순위(학기말 반영 비율): 학습활동지 포트폴리오를 통한 생명과학 원리 내면화",
            "학습활동지 포트폴리오를 통한 생명과학 원리 내면화",
        ),
    ],
)
def test_embedded_task_name_is_separated_from_the_structural_heading(
    heading: str, expected: str
) -> None:
    source = f"""
    # 2026학년도 (생명과학) 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    {heading}
    <table>
      <tr><th>반영비율</th><td>20%</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>탐구</td><td>근거가 타당함</td><td>20점</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "생명과학")

    assert [item.title for item in section.items] == [expected]
    assert section.items[0].title_basis == "heading"
    assert section.items[0].extraction_status == "bounded"


def test_structural_subheading_is_not_published_as_an_assessment_name() -> None:
    source = """
    # 2026학년도 (생명과학)과 교수학습 및 평가 운영 계획
    ## 6. 수행평가 세부 기준
    가. 평가 개요
    <table>
      <tr><th>반영비율</th><td>20%</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
      <tr><td>탐구</td><td>근거가 정확함</td><td>20점</td></tr>
    </table>
    나. 채점기준표
    <table><tr><th>평가 항목</th><th>채점기준</th><th>점수</th></tr></table>
    """

    section = parse_assessment_section(source, "생명과학")

    assert [item.title for item in section.items] == ["수행평가 원문 구간"]
    assert all(item.extraction_status == "bundle_review" for item in section.items)
    assert section.detected_titles == ()


@pytest.mark.parametrize(
    "title",
    [
        "교육과정 성취기준 : [12생과01-01] ~ [12생과03-07]",
        "[10과탐01-01] ~ [10과탐03-07]",
        (
            "동일학년 동일교과를 2인 이상의 교사가 지도할 경우 "
            "수행평가 영역 및 배점을 같게 할 수 있다."
        ),
        "신체장애 학생이 특정 영역의 수행평가가 불가능한 경우 인정점을 부여할 수 있다.",
        "채점기준표 ‣ 다양한 실생활 자료에 녹아있는 생명과학적 사실을 설명할 수 있다.",
        "수행평가 결시자의 성적처리는 별도의 평가 기간을 정해 재평가하는 것을 원칙으로 한다.",
        "전·편입생은 다음과 같이 처리한다.",
        "질병 및 인정 결석으로 참여하지 못한 경우 추가평가의 기회를 부여한다.",
        "특수교육 대상자 및 기타 사항에 대하여는 본교 학업성적관리규정에 따른다.",
        "수행평가를 할 때 표절 행위가 발생하지 않도록 사전 교육을 충분히 실시한다.",
        "AI는 수업·평가에서 보조적으로 활용할 수 있으나 공정성을 훼손하지 않도록 유의한다.",
        "AI의 활용을 허용하는 경우에는 AI 활용 범위에 대한 구체적 기준을 마련한다.",
        "AI를 활용한 경우 활동지의 AI 활용 내역란에 도구와 목적을 반드시 기록한다.",
        "출제 원안에는 문항별 배점을 모두 표과학탐구실험며 100점 만점으로 한다.",
        "영역 만점은 20점으로 한다.",
        (
            "수행평가 결시자의 성적처리는 별도의 평가 기간을 정해 재평가하는 것을 "
            "원칙으로 한다. 단, 질병 장기"
        ),
        "수행평가 영역별 특성에 따른 배점 비율의 적정성을 유지하고 상세한 채점 기준을 마련",
        "영역의 특성, 평가 목표, 평가 내용, 평가 상황 등을 고려하여 선다형 평가를 실시",
        "질병 및 인정 결석으로 참여하지 못한 경우 추가평가의 기회를 부여한다. 단, 응하지",
        (
            "특수교육 대상자 및 기타 사항에 대하여는 본교 학업성적관리규정에 따르고 "
            "교과협의회를 통하여"
        ),
        "수행평가의 목표, 영역, 횟수, 배점에 관한 세부기준은 수행평가 세부계획",
        (
            "수행평가를 할 때 표절 행위가 발생하지 않도록 사전 교육을 충분히 실시하고 "
            "표절이 의심되는 경우"
        ),
        "수행평가는 교과 담당교사가 교과 수업시간에 학생의 수행 과정 및 결과를 직접 관찰하고",
        "AI는 수업·평가에서 보조적으로 활용할 수 있으나 공정성을 훼손하지 않도록 유의",
        "AI의 활용을 허용하는 경우에는 AI 활용 범위에 대한 구체적 기준을 마련하고 유의",
        "수행평가 인공지능(AI) 도구 활용 시 평가 시행 전 학생 유의 사항을 안내하고",
        "교과의 특성을 고려하여 수행평가의 영역·방법·횟수·세부 기준과 반영 비율을 정하고",
        "AI를 활용한 경우 활동지의 AI 활용 내역란에 도구와 목적을 반드시 기록",
        "수행평가 결과물은 학생 개개인의 피드백을 위해 개인에게 돌려주어 학습에 활용하도록",
        "전입생이 실시한 수행평가는 교과협의회를 통해 본교 수행평가로 인정하거나 재실시",
        "성취기준에 근거한 평가의 영역·요소·방법·횟수·세부기준·반영비율 등 구체적인 방법은",
        (
            "정기시험은 문항별 배점을 표시하여 가급적 100점 만점으로 출제한다. "
            "또한 다양한 성취수준을 판별할"
        ),
        "정기시험에서 평가할 성취기준, 성취기준별 성취수준, 영역별 성취수준, 학기 단위 성취",
        "내용 영역, 성취기준, 난이도, 정답, 문항별 배점 및 채점기준이 명시된 문항정보표를 작성",
        "모둠토의와 협력활동 시간에 AI를 활용하여 자신의 의견을 대체하는 행위 금지",
        "포트폴리오에서 생명과학적으로 오류가 발견되면 완성하여 제출한 것으로 보지 않는다.",
        "성취기준별 성취수준에 따른 수행 정도의 차이를 반영한 채점 기준 개발",
        "정리한 개념과 사례를 접목하여 풀이과정을 서술함.",
        "비고 : 매 수업 활동 참여도가 부족한 경우 1점씩 감점한다.",
        "평가요소: 흥미, 성취동기, 수업 준비, 참여",
        "결석의 경우 결석 사유 소멸 후 1주일 이내로 평가한다.",
        "수행평가 시간에 결석이나 조퇴로 출석하지 않은 학생은 추가 기회를 주고",
        "수행평가의 반영 비율은 학기 단위 성적의 30% 이상으로 하되 타당도를 확보",
        "학생이 성취기준에 도달한 정도와 이를 판단한 근거 및 흥미와 성취욕구를 기록",
        "원안 제출 시 정답과 문항별 배점 및 채점기준이 명시된 문항정보표를 함께 제출",
        "문제를 해결하는 과정과 절차를 논리적으로 수행하였는가?",
        "생명과학 학습 의지와 끈기를 갖고 성실히 활동을 수행하였는가?",
        "수행평가 세부 계획과 채점 기준 및 배점을 사전에 안내하고 학생에게 설명",
        "결석의 경우 결석 사유 소멸 후 1주일 이내로 평가하고 미응시한 것으로 처리",
        "객관적이고 공정한 채점 기준을 세워 평가실시 전 평가 영역별 기준을 안내",
        "모든 출제 원안에는 문항별로 배점을 표시하되 평가의 변별력을 높이도록",
        "결시생, 재입학, 전·편입생 및 특수교육대상자의 성적 처리",
        "결시(인정결, 병결)로 인한 수행평가 결시자에게 추가 응시 기회를 부여",
        "심화 탐구하면서 느낀 점 또는 향후 학습계획을 명확하게 밝히고 있는가?",
        "수행평가에 참여한 학생에게 기본적으로 부여하는 최소 점수를 의미함.",
        "5지 선다형과 서·논술형 등 성취기준의 도달 여부를 확인할 문항으로 출제",
        "평가(정기시험 및 수행평가)의 영역, 요소, 방법, 시기, 횟수, 반영비율",
        "성취기준을 분석하여 적합한 평가 요소를 도출하고 성취수준을 판별",
        "학생의 수업 시간 활동 및 내용을 작성하여 기록",
        # 종결어미로 끝나는 채점 서술문 -- 문장이지 과제명이 아니다.
        "대사성 질환 예방을 위한 방법을 포함한 상관관계 분석 보고서를 작성함.",
        "논제에 대한 본인의 주장과 근거를 제시하여 토론을 준비함.",
        "과학적 근거를 바탕으로 실험을 설계하고 결과를 추론할 수 있는 역량을 평가함.",
        (
            "평가는 크게 정기시험과 수행평가로 나뉘며 평가방법, 내용, 횟수, 시기 등 "
            "세부사항은 다음과 같다."
        ),
        "위 기준을 위반할 경우 평가에서 감점 또는 재제출 조치가 이루어질 수 있다.",
        "평가 실시 후 성적 결과를 기준으로 분할점수를 임의로 설정하면 안 됨.",
        # 셀 너비에서 잘린 방침 문단 -- 조사·연결어미로 끝난다.
        (
            "수행평가의 결과물은 학생의 이의 신청, 처리, 확인 과정등의 적절한 조치가 "
            "완료된 후 당해연도에"
        ),
        "수행평가 시행 전 안내된 부정행위 유형에 해당하는 경우, 해당 수행평가 영역의",
        "복수의 학생이 공동으로 수행하는 모둠활동 등을 평가할 때에는 개별 학생에게 역할을 부여하고",
        # 평가 운영 어휘로만 된 문서 구조 라벨.
        "평가 요소",
        "배점 합계",
        "세부 기준안",
        "수행평가 채점 기준",
        "수행평가 영역별 배점 및 채점 기준",
        "1학기 수행평가 영역 및 평가항목, 배점 및 채점기준",
        "평가 항목 (채점 기준)",
        "1회(기말고사)",
        "정기시험 1회",
        # 성적 처리 규정.
        "정기시험 및 수행평가의 이의신청 기간 및 절차",
        "인정점 부여 시 기준고사/영역 설정",
        "동점자 처리 1순위",
        "자발적 미응시/미제출",
        # 대단원이 둘 이상 나열된 평가 범위 표기.
        "Ⅰ. 생명과학의 역사 Ⅱ. 세포의 특성 Ⅳ. 유전자의 발현과 조절",
        "Ⅰ.생명의 시스템 ~ Ⅲ.생명의 다양성과 연속성",
        # 무엇을 평가하는지 쓴 채점 서술.
        (
            "보고서 설계, 데이터 수집, 자료 해석 및 결론 도출 등을 활용하여 융합적 "
            "사고력, 협력적 문제 발견 및 해결 능력, 의사소통 능력을 평가"
        ),
        "실험을 수행하고 실험 보고서를 작성한 내용을 평가",
        # 학교알리미 서식의 표준 문구가 여러 학교에서 반복 추출된다.
        "수행평가 영역별 기준 성취율",
        "영역별 평가 개요",
        "영역별 기본 점수",
        "수행평가 영역별 분할점수 기준",
        "수행평가 세부사항",
    ],
)
def test_policy_and_standard_headings_are_structural(title: str) -> None:
    assert heading_title_is_structural(title)


@pytest.mark.parametrize(
    "title",
    [
        # 활동어를 가진 실제 과제명은 평가 운영 어휘가 섞여도 살아남는다.
        "효모의 물질대사 탐구 (동점자 1순위)",
        "생명과학II의 과학적 개념 및 형성평가 문항 풀이하고 기록하기",
        (
            "수업 시간 내 학습한 핵심 개념을 바탕으로 정기적인 퀴즈 및 형성평가 문항을 "
            "해결하여 학습 목표 도달 확인하기"
        ),
        # 조사와 겹치는 끝 글자를 가진 명사구 제목.
        "스펙트럼 분석을 통한 별의 일생과 원소의 생성 과정 탐구보고서",
        "천연 항생물질 탐색 및 항생 활성화 비교 실험 보고서",
        "생명과학과 에너지 : 세포호흡과 광합성 유전자 발현 조절 프로젝트 과제 발표 보고서",
        "표준화되지 않은 생활 속 단위 조사 및 표준화 방안 토의",
        # 평가 어휘가 아닌 내용어를 가진 짧은 제목.
        "생명 시스템의 화학 반응 조절과 과학적 탐구 보고서",
        "유전 정보의 흐름 탐구",
        "삼투 현상 탐구 보고서",
        # 대단원 하나를 앞에 붙여 쓴 실제 과제명은 범위 표기가 아니다.
        (
            "Ⅰ. 과학의 본성과 역사 속의 과학 탐구 / "
            "01.과학사에서 동시 발견으로 이룬 과학 발전 추적하기"
        ),
    ],
)
def test_real_task_names_survive_the_policy_prose_filter(title: str) -> None:
    assert not heading_title_is_structural(title)


@pytest.mark.parametrize(
    "heading",
    [
        "수행평가 과제별 세부 계획",
        "평가방법 및 채점기준 배점",
        "채점기준 및 배점",
        "질병 결석으로 추가 평가가 불가능한 경우는 본교 규정에 따라 처리",
        "실시 시기 및 횟수",
        "성취기준별 성취수준",
        "평가관점·요소",
        "수행수준 (채점기준) 및 배점",
        "세부내용 및 평가척도표",
        "세부기준",
        "수행평가 개요",
        "수행평가 영역별 평가 요소 및 채점 기준",
        "평가 요소 및 성취 기준",
        "동점자 처리 기준",
        "피드백 및 기록",
        "수행평가 분할점수",
        "수행평가 영역 및 배점",
        "관련 성취기준",
        "평가 방법 및 결과의 활용",
        "수행평가 영역별 성취기준 및 평가 척도",
        "평가 영역별 세부 채점 기준",
        "평가 유의사항",
        "수행평가 성취율과 원점수",
        "정의적 능력 평가 세부 사항",
        "정의적 능력 평가",
        "정의적 영역 평가",
        "정의적 능력 평가의 실제",
        "사회정서학습 연계 정의적 능력 평가",
        "학습과정평가",
        "생명과학학습과정평가",
        "서·논술형 평가 계획",
        "서술·논술형 평가",
        "공통 유의사항",
        "[유의사항]",
        "영역별 세부 평가 기준",
        "성취 기준과 평가기준",
        "평가 과제",
        "세부 채점 기준",
        "평가 항목과 배점",
        "정의적 능력 평가 계획",
        "수행평가 세부기준(영역별 배점과 채점 기준)",
        "수행평가 분할 점수 산출",
        "영역별 평가 방법과 채점 기준",
        "평가 영역 및 배점",
        "평가방법 및 내용",
        "성취기준 및 평가 방법",
        "평가 영역별 반영 비율",
        "정기시험 및 수행평가 세부계획",
        "기타 사항",
        "정의적 능력 평가 요소와 평가 방법",
        "평가과제1",
        "수행과제2",
        "평가영역1",
        "수행 1",
        "항목별 계획",
        "평가 영역",
        "평가 요소별 세부 채점 기준",
        "평가 항목별 채점 기준",
        "기본 점수 부여 여부 및 방법",
        "평가 방법 및 활용",
        "4. 고사별 배점",
        "수행평가의 세부 기준 (평가 과제별로 작성)",
        "수행 평가 세부기준 및 배점",
        "수행 평가 세부 계획",
        "수업참여도 세부기준",
        "방침",
        "수행평가 과제별 개요",
        "수행평가 범위와 기준",
        "평가 과제별 세부 계획",
        "AI 활용 금지 범위",
        "수행평가 인정점 산출 기준",
        "수행평가 평가 기준",
        "과정중심 수행평가 세부 계획",
        "평가 방법 및 반영 비율",
        "수업 계획",
        "수행평가 영역 및 평가항목, 배점 및 채점기준",
        "수행평가 요소 및 성취 기준",
        "평가과제별 반영 비율 및 성취수준",
        "평가과제별 채점 기준",
        "수행평가 1",
        "수행평가1",
        "세부 평가 내용",
        "평가 방법 및 평가내용",
        "정기 시험 세부계획",
        "과제별 배점",
        "최종 배점",
        "수행평가 내용 및 평가 세부 기준",
        "수행평가 인정점 부여 기준",
        "수행평가 세부 기준(영역별 배점 및 채점기준)",
        "수행 평가 세부 계획 ※ 과목 특성에 따라 양식 변경",
        "기본 방향",
        "평가 방법과 반영 비율",
        "수행 평가 세부 계획 (교과 사정에 따라 변경될 수 있음.)",
        "수행평가 세부 계획(1)",
        "항목별 평가 기준",
        "통계",
        "벡터",
        "행렬",
        "수행평가 세부 계획(평가과제별로 작성)",
        "평가 요소 : 흥미와 자신감",
        "최하 3점부터 최고 20점까지 0.5점 급간으로 점수를 부여하며 세부 내용은 아래와 같다.",
        "공교육 정상화 촉진 및 선행교육 규제에 관한 특별법에 따라 학생이 배운 범위만 평가",
        (
        "수행평가 결과물에 AI 활용 여부와 활용 목적을 간단히 기록하여야 하며 "
            "AI가 생성한 내용을 그대로 제출하면 불이익을 받을 수 있음."
        ),
        "학기 단위 성취수준 설정,",
        "학기 단위 성취수준 설정 13. 최소 성취수준 설정(공통과목)",
        "일반사항",
        "영역별",
        "문제 해결 과정에서 막히는 부분에 한하여 힌트 요청할 때, AI 활용 가능",
        "평가 관련 제반 문제는 교과협의회에서 협의하고, 주요 결정 사항은 심의한다.",
        "평소 수업 활동이 자연스럽게 평가로 이어지도록 계획한다.",
    ],
)
def test_field_and_policy_headings_do_not_become_assessment_titles(heading: str) -> None:
    source = f"""
    # 2026학년도 (생명과학) 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    가. {heading}
    <table>
      <tr><th>반영비율</th><td>20%</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>탐구</td><td>근거가 타당함</td><td>20점</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "생명과학")

    assert all(item.title != heading for item in section.items)
    assert all(item.extraction_status != "bounded" for item in section.items)


def test_curriculum_unit_with_only_achievement_levels_is_not_a_task() -> None:
    source = """
    # 2026학년도 (통합과학1) 교수학습 및 평가 운영 계획
    ## 6. 성취기준별 평가 기준
    (1) 다항식
    <table>
      <tr><th>성취기준</th><th>성취기준별 평가 기준</th></tr>
      <tr><td>[10통과1-01-01] 다항식의 사칙연산을 할 수 있다.</td><td>A 매우 우수함</td></tr>
    </table>
    ## 7. 수행평가 세부 계획
    """

    section = parse_assessment_section(source, "통합과학1")

    assert all(item.title != "다항식" for item in section.items)
    assert all(item.extraction_status != "bounded" for item in section.items)


def test_explicit_table_name_outweighs_a_generic_numbered_heading() -> None:
    source = """
    # 2026학년도 (생명과학) 교수학습 및 평가 운영 계획
    ## 6. 수행평가 세부 계획
    1. 수열
    <table>
      <tr><th>평가영역명</th><td>수열의 규칙을 활용한 모델링 탐구</td>
      <th>영역만점</th><td>20점</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>모델링</td><td>근거가 타당함</td><td>20점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "생명과학").items[0]

    assert item.title == "수열의 규칙을 활용한 모델링 탐구"
    assert item.title_basis == "table"
    assert item.extraction_status == "bounded"


def test_explicit_table_title_preserves_source_roman_numeral_spelling() -> None:
    source = """
    # 2026학년도 (통합과학1) 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    가. 원리의 적용과 해석Ⅰ(11점)
    <table>
      <tr><th>평가 영역명</th><td>원리의 적용과 해석Ⅰ</td></tr>
      <tr><th>수행 과제</th><td>생명과학 포트폴리오</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>해석</td><td>근거가 타당함</td><td>11점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "통합과학1").items[0]

    assert item.title == "원리의 적용과 해석Ⅰ"
    # The heading carries the area's 배점, so it is what named the item and
    # title_raw quotes that heading line; either way the Ⅰ survives cleaning.
    assert item.title_raw == "가. 원리의 적용과 해석Ⅰ(11점)"


def test_explicit_table_title_trims_merged_score_and_semester_metadata() -> None:
    source = """
    # 2026학년도 (생명과학) 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    가. 수행평가 세부 기준
    <table>
      <tr><th>평가 영역명</th><td>생명과학적 모델링 영역 만점 15점 학기 1학기</td></tr>
      <tr><th>수행 과제</th><td>실생활 자료를 함수로 나타내기</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>모델</td><td>근거가 타당함</td><td>15점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "생명과학").items[0]

    assert item.title == "생명과학적 모델링"
    assert item.title_raw == "생명과학적 모델링"


def test_short_subject_mention_cannot_publish_another_courses_rubric() -> None:
    source = """
    # 2026학년도 (생명과학)
    ## 수행평가 세부 기준
    2) 세부 시행 계획 및 채점 기준
    <table>
      <tr><th>평가영역명</th><td>듣기 기반 담화 구성</td></tr>
      <tr><th>성취기준</th><td>[12실영01-01] 핵심 정보를 파악한다.</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
      <tr><td>듣기</td><td>정확함</td><td>20점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "생명과학").items[0]

    assert item.title == "수행평가 원문 구간"
    assert item.extraction_status == "source_mismatch_review"
    assert item.overview == ""
    assert item.standards == ()


def test_roman_numeral_standard_code_confirms_the_requested_course() -> None:
    source = """
    # 2025학년도 (생명과학Ⅱ)
    ## 수행평가 세부 기준
    가. 함수의 극한 문제 해결
    <table>
      <tr><th>성취기준</th><td>[12생과Ⅱ01-01] 함수의 극한의 뜻을 안다.</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
      <tr><td>극한</td><td>풀이가 정확함</td><td>20점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "생명과학Ⅱ").items[0]

    assert item.extraction_status == "bounded"
    assert item.title == "함수의 극한 문제 해결"


def test_keeps_rowspan_and_colspan_in_safe_source_html() -> None:
    source = """
    # 2026학년도 (통합과학1)과 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    1. 변화율 모델링 탐구
    <table onclick="alert(1)">
      <tr><th rowspan="2">평가요소</th><th colspan="2">채점 기준</th></tr>
      <tr><td>설명</td><td>점수</td></tr>
      <tr><td>모델</td><td><script>bad()</script>타당함</td><td>20점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "통합과학1").items[0]

    assert 'rowspan="2"' in item.source_html
    assert 'colspan="2"' in item.source_html
    assert "onclick" not in item.source_html
    assert "<script" not in item.source_html
    assert "타당함" in item.source_html


def test_unbounded_document_is_one_honest_bundle() -> None:
    source = """
    # 2026학년도 (과학탐구실험)과 교수학습 및 평가 운영 계획
    <table>
      <tr><th>평가 일시(횟수)</th><th>만점</th><th>반영 비율</th>
      <th>평가 내용</th><th>평가 방법</th></tr>
      <tr><td>4월</td><td>30점</td><td>30%</td>
      <td>이차곡선 탐구 보고서</td><td>보고서 평가</td></tr>
    </table>
    수행평가의 채점 기준과 평가 방법은 다음과 같다.
    """

    item = parse_assessment_section(source, "과학탐구실험").items[0]

    assert item.extraction_status == "bundle_review"
    assert item.title == "이차곡선 탐구 보고서"
    assert "이차곡선 탐구 보고서" in item.source_html


def test_uncertain_multi_title_bundle_does_not_publish_mixed_summary_values() -> None:
    source = """
    # 2026학년도 (생명과학) 교수학습 및 평가계획
    | 수행평가명 | 반영비율 | 만점 |
    | --- | --- | --- |
    | 지수 탐구 | 20% | 100점 |
    | 수열 발표 | 20% | 100점 |
    수행평가 자료와 채점 기준을 안내한다.
    """

    section = parse_assessment_section(source, "생명과학")
    item = section.items[0]

    assert item.title == "수행평가 원문 구간"
    assert item.extraction_status == "bundle_review"
    assert item.weight == ""
    assert item.score == ""
    assert section.detected_titles == ()
    assert "지수 탐구" in item.source_html
    assert "수열 발표" in item.source_html


def test_rejects_previous_context_jump_artifacts() -> None:
    source = "# 생명과학 교수학습 및 평가 운영 계획\n[...문맥 전환...]"

    try:
        parse_assessment_section(source, "생명과학")
    except ValueError as exc:
        assert "context-jump" in str(exc)
    else:
        raise AssertionError("context-jump marker must fail the lossless parser")


def test_markdown_pipe_table_becomes_accessible_html_table() -> None:
    rendered = markdown_fragment_to_html("| 평가영역 | 반영비율 |\n| --- | --- |\n| 모델링 | 20% |")

    assert "<thead>" in rendered
    assert "<th>평가영역</th>" in rendered
    assert "<td>20%</td>" in rendered


def test_zip_member_boundary_keeps_only_the_requested_subject() -> None:
    source = """
    [zip:2학년/2026학년도 화학 평가계획.hwp][ok]
    # 2026학년도 (화학) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 기체의 분자량 구하기
    <table><tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
    <tr><td>실험</td><td>타당함</td><td>20점</td></tr></table>

    [zip:2학년/2026학년도 2학년 1학기 생명과학 평가계획.hwp][ok]
    # 2026학년도 (생명과학) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 생활 속 데이터의 주기성 분석 및 함수 만들기
    <table><tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
    <tr><td>모델링</td><td>타당함</td><td>30점</td></tr></table>
    ### 결시자 처리 기준

    [zip:2학년/2026학년도 영어 평가계획.hwp][ok]
    # 2026학년도 (영어) 교수학습 및 평가계획
    """

    section = parse_assessment_section(source, "생명과학")

    assert section.boundary_status.startswith("zip_member_subject:")
    assert [item.title for item in section.items] == ["생활 속 데이터의 주기성 분석 및 함수 만들기"]
    assert "기체의 분자량" not in section.source_markdown
    assert "영어" not in section.source_markdown


def test_zip_member_prefers_exact_math_filename_over_economic_math() -> None:
    source = """
    [zip:3학년/2025학년도 생명과학실험 평가계획.hwp][ok]
    # 2025학년도 (생명과학실험) 교수학습 및 평가계획
    ## 수행평가 세부 계획
    가. 경제지표 탐구
    <table><tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
    <tr><td>분석</td><td>타당함</td><td>20점</td></tr></table>

    [zip:1학년/2025학년도 생명과학 평가계획.hwp][ok]
    # 2025학년도 (생명과학) 교수학습 및 평가계획
    ## 수행평가 세부 계획
    가. 방정식 문제해결
    <table><tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
    <tr><td>풀이</td><td>정확함</td><td>20점</td></tr></table>
    """

    section = parse_assessment_section(source, "생명과학")

    assert [item.title for item in section.items] == ["방정식 문제해결"]
    assert "경제지표" not in section.source_markdown


def test_numbered_cells_in_markdown_table_are_not_item_headings() -> None:
    source = """
    # 2026학년도 (생명과학) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 함수 모델링 탐구
    | 평가요소 | 채점기준 | 점수 |
    | --- | --- | --- |
    | 1. 생명과학적 타당성 | 근거가 정확함 | 20점 |
    | 2. 의사소통 | 설명이 명확함 | 10점 |
    ### 결시자 처리 기준
    """

    section = parse_assessment_section(source, "생명과학")

    assert [item.title for item in section.items] == ["함수 모델링 탐구"]


def test_pdf_style_pipe_table_populates_exact_fields_and_rubric() -> None:
    source = """
    # 2026학년도 (생명과학) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 생활 자료 함수 모델링
    | 평가시기 | 반영비율 | 영역만점 | 평가방법 |
    | --- | --- | --- | --- |
    | 5월 2주 | 30% | 100점 | 프로젝트 |

    | 평가요소 | 채점기준 | 척도(배점) |
    | --- | --- | --- |
    | 모델의 타당성 | 근거가 정확함 | 30점 |
    ### 결시자 처리 기준
    """

    item = parse_assessment_section(source, "생명과학").items[0]

    assert item.timing == "5월 2주"
    assert item.weight == "30%"
    assert item.score == "100점"
    assert item.method == "프로젝트"
    assert "근거가 정확함" in item.rubric_html
    assert "<table>" in item.rubric_html


def test_wide_merged_pdf_row_stops_each_value_at_the_next_field_label() -> None:
    source = """
    # 2026학년도 (생명과학) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 데이터 주기성 분석
    | 성취기준 | 내용 |  |  |  |  |  |  |  |  |  |  |  |
    | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
    | 평가시기 | 3월 4주-6월 3주 | 반영비율 |  |  | 20% |  |  | 영역만점 |  |  | 100점 |  |
    | 평가 방법 | ☑ 서술･논술 |  | □ 구술･발표 |  |  | □ 토의･토론 |  |  |  | ☑ 프로젝트 |  |  |
    | 평가요소 | 지수와 로그 |  |  |  |  |  |  |  |  |  |  |  |
    | 채점요소 | 채점기준 |  |  |  |  |  |  |  |  |  |  | 척도(배점) |
    | 모델링 | 함수가 타당함 |  |  |  |  |  |  |  |  |  |  | 20점 |
    ### 결시자 처리 기준
    """

    item = parse_assessment_section(source, "생명과학").items[0]

    assert item.timing == "3월 4주-6월 3주"
    assert item.weight == "20%"
    assert item.score == "100점"
    assert item.method == "☑ 서술･논술 · ☑ 프로젝트"


def test_rubric_score_column_is_not_misreported_as_the_task_total() -> None:
    source = """
    # 2026학년도 (생명과학) 교수학습 및 평가계획
    ## 수행평가 세부 계획
    가. 로그 모델링
    <table>
      <tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
      <tr><td>모델</td><td>타당함</td><td>30점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "생명과학").items[0]

    assert item.score == ""
    assert "30점" in item.rubric_html


def test_truncated_source_table_is_closed_for_browser_rendering() -> None:
    repaired = balance_table_tags("<table><tr><td>원문</td></tr>")

    assert repaired.count("<table") == repaired.count("</table>") == 1


def test_excessive_heading_candidates_fall_back_to_one_review_bundle() -> None:
    noisy = "\n".join(
        f"{index}. 표의 항목 {index}\n평가요소 채점기준 배점" for index in range(1, 15)
    )
    source = f"""
    # 2026학년도 (생명과학) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    {noisy}
    """

    section = parse_assessment_section(source, "생명과학")

    assert len(section.items) == 1
    assert section.items[0].extraction_status == "bundle_review"




def test_area_label_unit_name_loses_to_a_task_naming_heading() -> None:
    """A 평가영역 cell often holds the unit, not the task, name."""

    source = """
    # 2026학년도 (생명과학Ⅱ) 교수학습 및 평가계획
    ## 수행평가 세부 계획
    1. 수행평가 ( 1 ) - 탐구 실험 보고서
    <table>
      <tr><th>평가영역</th><th>생명과학의 역사</th><th>반영비율</th><th>20 %</th></tr>
      <tr><td>성취기준</td><td>[12생과Ⅱ01-01]</td><td>평가방법</td><td>탐구보고서</td></tr>
      <tr><td>평가요소</td><td>조사</td><td>채점기준</td><td>배점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "생명과학Ⅱ").items[0]

    assert item.title == "탐구 실험 보고서"
    assert item.title_basis == "heading"


def test_explicit_task_label_still_outranks_the_heading() -> None:
    source = """
    # 2026학년도 (생명과학Ⅱ) 교수학습 및 평가계획
    ## 수행평가 세부 계획
    1. 평가 영역 2
    <table>
      <tr><th>수행과제</th><th>효소의 작용 탐구</th><th>반영비율</th><th>20 %</th></tr>
      <tr><td>성취기준</td><td>[12생과Ⅱ01-01]</td><td>평가방법</td><td>실험</td></tr>
      <tr><td>평가요소</td><td>실험 설계</td><td>채점기준</td><td>배점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "생명과학Ⅱ").items[0]

    assert item.title == "효소의 작용 탐구"
    assert item.title_basis == "table"


def test_written_exam_names_never_become_task_titles() -> None:
    source = """
    # 2026학년도 (생명과학Ⅱ) 교수학습 및 평가계획
    ## 수행평가 세부 계획
    <table>
      <tr><th>평가종류</th><th>수행평가</th><th>수행평가</th></tr>
      <tr><th>평가영역</th><td>기말고사</td><td>효소 탐구 보고서</td></tr>
      <tr><td>성취기준</td><td>[12생과Ⅱ01-01]</td><td>[12생과Ⅱ01-02]</td></tr>
      <tr><td>평가방법</td><td>지필</td><td>보고서</td></tr>
      <tr><td>반영비율</td><td>20 %</td><td>30 %</td></tr>
    </table>
    """

    titles = [item.title for item in parse_assessment_section(source, "생명과학Ⅱ").items]

    assert "기말고사" not in titles


def test_hangul_checkbox_glyph_artifact_restores_check_state() -> None:
    """HWP/PDF extraction flattens a checkbox symbol font's strokes into the
    literal letters 'gfedcb' (checked) and 'gfedc' (unchecked); the visible
    text must read as an actual checkbox, not raw component-glyph letters."""

    assert normalize_checkbox_glyphs("gfedcb 논술") == "☑ 논술"
    assert normalize_checkbox_glyphs("gfedc 구술‧발표") == "□ 구술‧발표"
    assert (
        visible_text("<td>gfedcb 논술</td><td>gfedc 구술‧발표</td>")
        == "☑ 논술 □ 구술‧발표"
    )


def test_each_source_table_keeps_its_own_cells_and_spans() -> None:
    """The renderer copies a table as kordoc gave it: spans kept, no rows moved."""

    fragment = """<table>
<tr><th rowspan="2">평가 요소</th><th colspan="2">채점 기준</th><th>배점</th></tr>
<tr><td>수준</td><td>내용</td><td>100점</td></tr>
<tr><td rowspan="2">보고서 작성<br>(30점)</td><td>A</td><td>모든 항목을 작성함</td><td>30</td></tr>
<tr><td>B</td><td>누락된 부분이 1~2개 있음</td><td>28</td></tr>
</table>
"""

    rendered = markdown_fragment_to_html(fragment)

    assert rendered.count("<table>") == 1
    assert '<th rowspan="2">평가 요소</th>' in rendered
    assert '<th colspan="2">채점 기준</th>' in rendered
    # The old extractor collapsed these rows into one cell ("302826").
    assert "<td>30</td>" in rendered and "<td>28</td>" in rendered


def test_tables_separated_by_other_content_stay_separate() -> None:
    fragment = """<table>
<tr><td>첫 번째 표</td></tr>
</table>

<p>설명 문단</p>

<table>
<tr><td>독립된 두 번째 표</td></tr>
</table>
"""

    rendered = markdown_fragment_to_html(fragment)

    assert rendered.count("<table") == rendered.count("</table>") == 2


def test_label_value_row_names_one_assessment_not_one_per_rubric_row() -> None:
    """``평가과제 | <이름>`` answers itself horizontally.

    Reading that column downwards instead turns every 평가요소 rubric
    dimension -- and every rubric criterion sentence under it -- into its own
    "assessment", which is what a 금성고 plan produced (9 items for 1 task).
    """

    source = """
    # 2026학년도 (생명과학) 교수학습 및 평가계획
    ## 수행평가 세부 계획
    <table>
      <tr><th>평가과제</th><th colspan="7">우리학교 생태지도 만들기</th></tr>
      <tr><td>성취기준</td><td colspan="7">[12생과01-01] ~ [12생과01-07]와 관련하여
        생태 지도를 제작한다.</td></tr>
      <tr><td>평가내용</td><td colspan="7">우리 학교 내 다양한 생물과 서식 환경을 관찰하고
        조사하여 생태 지도를 제작함으로써 학교 생태계에 대한 이해를 높일 수 있다.</td></tr>
      <tr><td>평가시기</td><td>4월 2주</td><td>반영비율(%)</td><td>15%</td><td>만점</td>
        <td colspan="3">100</td></tr>
      <tr><td>평가요소</td><td colspan="5">평가기준</td><td>척도</td><td>배점</td></tr>
      <tr><td rowspan="2">생태 환경 조사 및 기록</td>
        <td colspan="5">학교 내 생물 6종 이상을 관찰하고 기록하였다.</td>
        <td>30</td><td rowspan="2">30</td></tr>
      <tr><td colspan="5">학교 내 생물 3종 이하를 관찰하여 기록하였다.</td><td>10</td></tr>
      <tr><td rowspan="2">생태지도 내용의 정확성</td>
        <td colspan="5">3가지 요소가 모두 지도에 표시되어 있다.</td>
        <td>40</td><td rowspan="2">40</td></tr>
      <tr><td colspan="5">위 요소 중 1가지만 표시되어 있다.</td><td>20</td></tr>
    </table>
    """

    titles = [item.title for item in parse_assessment_section(source, "생명과학").items]

    assert titles == ["우리학교 생태지도 만들기"]


def test_column_header_summary_table_still_lists_each_row() -> None:
    """The opposite layout must keep working: sibling field labels in the
    header row mean the assessments really are the rows underneath."""

    source = """
    # 2026학년도 (생명과학) 교수학습 및 평가계획
    ## 수행평가 세부 계획
    <table>
      <tr><th>평가영역</th><th>성취기준</th><th>평가방법</th><th>반영비율</th></tr>
      <tr><td>효소 탐구 보고서</td><td>[12생과01-01]</td><td>보고서</td><td>20%</td></tr>
      <tr><td>광합성 색소 분리 실험</td><td>[12생과01-02]</td><td>실험</td><td>20%</td></tr>
    </table>
    """

    titles = [item.title for item in parse_assessment_section(source, "생명과학").items]

    assert "효소 탐구 보고서" in titles
    assert "광합성 색소 분리 실험" in titles


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[12생과Ⅱ01-01] 세포를 관찰한다", ["[12생과Ⅱ01-01]"]),
        ("[10통과1-03-05] 시스템과 상호작용", ["[10통과1-03-05]"]),
        ("[12생실01-01]와 [12고생04-04]", ["[12생실01-01]", "[12고생04-04]"]),
        # 물결표는 코드가 아니라 범위 표기가 깨진 것이다.
        ("[12생과02~02] 과학 신문 만들기", []),
        # 영역 번호까지만 있는 값은 성취기준이 아니다.
        ("[10통과1-01] 창의적인 원소 카드 만들기", []),
        # 12로 시작해도 다른 교과 코드는 이 교과군의 성취기준이 아니다.
        ("[12보05-03] 성문제에 대한 논술 및 발표", []),
        ("[프로02-01] 변수의 개념을 이해한다", []),
    ],
)
def test_only_this_subject_groups_achievement_codes_are_collected(
    text: str, expected: list[str]
) -> None:
    assert biology_standard_codes(text) == expected


def test_score_and_weight_reject_a_header_row_without_numbers() -> None:
    source = """
    # 생명과학Ⅱ
    ## 수행평가 세부 계획
    가. 광합성 색소 분리 탐구
    <table>
      <tr><th>성취기준</th><td>[12생과Ⅱ03-01]</td></tr>
      <tr><th>만점</th><td>등급</td><td>평가 척도</td><td>배점</td></tr>
      <tr><th>평가방법</th><td>실험</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "생명과학Ⅱ").items[0]

    assert item.score == ""


@pytest.mark.parametrize(
    ("key", "value", "usable"),
    [
        # 평가 시기 칸에 다른 칸의 라벨이 섞이면 표 행이 통째로 들어온 것이다.
        ("timing", "단원명 · Ⅰ. 과학의 기초 Ⅱ. 물질과 규칙성 · 평가영역", False),
        ("timing", "4월 반영비율(%) 25% 만점 50점", False),
        ("timing", "4월 1주~4월 2주", True),
        # 점수·비율 칸에 숫자가 없으면 값이 아니라 표 머리글이다.
        ("score", "등급 · 평가 척도 · 배점", False),
        ("score", "50점", True),
        ("weight", "반영비율", False),
        ("weight", "30%", True),
    ],
)
def test_leaked_table_rows_are_not_published_as_field_values(
    key: str, value: str, usable: bool
) -> None:
    assert _field_value_is_usable(key, value) is usable


def test_timing_keeps_a_real_schedule_value() -> None:
    source = """
    # 통합과학1
    ## 수행평가 세부 계획
    가. 자연의 구성 원소 탐구
    <table>
      <tr><th>성취기준</th><td>[10통과1-02-01]</td></tr>
      <tr><th>평가시기</th><td>4월 1주~4월 2주</td></tr>
      <tr><th>평가방법</th><td>보고서</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "통합과학1").items[0]

    assert item.timing == "4월 1주~4월 2주"


def test_table_of_contents_entry_does_not_open_the_subject_section() -> None:
    source = """
    2026_1학기_1학년_과학탐구실험1_교수학습 및 평가계획(정보공시) ··········· 55
    2026_1학기_1학년_통합과학1_교수학습 및 평가계획(정보공시) ··········· 61

    # 2026학년도 1학기 [과학탐구실험1] 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    ### 1. 패러다임의 전환 탐구
    <table>
      <tr><th>성취기준</th><td>[10과탐1-01-01] 결정적 실험을 따라 할 수 있다</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>실험 수행</td><td>절차에 따라 수행함</td><td>10</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "과학탐구실험1")

    assert section.boundary_status.startswith("subject_heading")
    assert [item.title for item in section.items if item.extraction_status == "bounded"] == [
        "패러다임의 전환 탐구"
    ]


def test_policy_paragraph_anchor_yields_to_the_block_with_tables() -> None:
    source = """
    # 2026학년도 (생명과학) 교수학습 및 평가 운영 계획
    ## 2. 평가 방침
    나. 수행평가
    1) 수행평가의 내용과 평가척도 및 배점은 학생들에게 미리 제시하여 평가의 객관성을 유지한다.
    2) 결시자의 성적 처리는 학업성적관리규정에 따른다.
    ## 3. 수행평가 세부 계획
    ### 가. 생명 활동 유지 탐구
    <table>
      <tr><th>성취기준</th><td>[12생과01-01] 세포를 설명할 수 있다</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>탐구</td><td>근거가 타당함</td><td>10</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "생명과학")

    assert [item.title for item in section.items if item.extraction_status == "bounded"] == [
        "생명 활동 유지 탐구"
    ]


def test_matrix_summary_with_colspan_reads_the_performance_columns() -> None:
    source = """
    # 2026학년도 [1]학년 1학기 [통합과학1] 교수학습 및 평가 계획
    Ⅲ. 평가 기준
    <table>
    <tr><th>평가종류</th><th colspan="2">정기시험</th><th colspan="2">수행평가</th></tr>
    <tr><td rowspan="2">영역</td><td>중간고사</td><td>기말고사</td>
    <td rowspan="2">전기전도성 탐구</td><td rowspan="2">DNA 모형 제작</td></tr>
    <tr><td>선택형</td><td>서답형</td></tr>
    <tr><td>반영비율</td><td>30%</td><td>30%</td><td>20%</td><td>20%</td></tr>
    <tr><td>성취기준</td><td>-</td><td>-</td><td>[10통과1-02-03]</td><td>[10통과1-02-05]</td></tr>
    <tr><td>평가요소</td><td>-</td><td>-</td><td>전기전도성 측정</td><td>모형 제작</td></tr>
    <tr><td>평가시기</td><td>4월</td><td>7월</td><td>5월</td><td>6월</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "통합과학1")

    titles = [item.title for item in section.items if item.extraction_status == "bounded"]
    assert titles == ["전기전도성 탐구", "DNA 모형 제작"]
    assert "중간고사" not in titles


def test_single_rubric_table_grouped_by_assessment_name_splits_into_items() -> None:
    source = """
    # 2026학년도 [과학탐구실험] 교수학습 및 평가 계획
    2. 수행평가 세부 기준안
    <table>
    <tr><th>수행평가 내용</th><th>평가요소(배점)</th><th>채점기준</th><th>점수</th></tr>
    <tr><td rowspan="3">과학 원리 탐구</td><td rowspan="3">탐구 능력</td>
    <td>2개 항목을 모두 갖추었다.</td><td>20</td></tr>
    <tr><td>1개 항목을 갖추었다.</td><td>10</td></tr>
    <tr><td>제출하지 않았다.</td><td>0</td></tr>
    <tr><td rowspan="2">생활 주변 탐구</td><td rowspan="2">문제 해결력</td>
    <td>3개 항목을 모두 갖추었다.</td><td>40</td></tr>
    <tr><td>제출하지 않았다.</td><td>0</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "과학탐구실험")

    bounded = [item for item in section.items if item.extraction_status == "bounded"]
    assert [item.title for item in bounded] == ["과학 원리 탐구", "생활 주변 탐구"]
    assert "2개 항목을 모두 갖추었다" in bounded[0].rubric_html
    assert "3개 항목" not in bounded[0].rubric_html


def test_abbreviated_sibling_codes_do_not_count_as_another_subject() -> None:
    segment = "[10통과1-01-01] 자연을 기술할 수 있다. 이외 [10통과01-02~04], [10통과02-01~06]"

    assert segment_subject_alignment(segment, "통합과학1") == "expected"
    assert segment_subject_alignment("[10통과01-02] 만 있는 구간", "통합과학1") == "other"


def test_bracketed_per_course_h1_bounds_the_subject_section() -> None:
    source = """
    # 2026학년도 1학기 (과학탐구실험1)과 교수학습 계획서
    | 학년 | 담당 |
    | --- | --- |
    | 1학년 | 김○○ |
    # 평가 계획
    <table>
    <tr><th>평가 유형</th><th colspan="2">수행평가</th><th>합계</th></tr>
    <tr><td>반영 비율</td><td colspan="2">100%</td><td>100%</td></tr>
    <tr><td>횟수/영역</td><td>패러다임의 전환을 만화로 표현하기</td>
    <td>생활 속의 과학 탐구</td><td>-</td></tr>
    <tr><td>평가 방법</td><td>프로젝트</td><td>실험·실습</td><td>-</td></tr>
    <tr><td>교육과정 성취 기준</td><td>[10과탐1-01-01]</td><td>[10과탐1-02-01]</td><td>-</td></tr>
    <tr><td>평가 시기</td><td>3~4월</td><td>5~7월</td><td>-</td></tr>
    </table>
    # 2026학년도 1학기 (체육1)과 교수학습 계획서
    <table>
    <tr><th>평가 유형</th><th colspan="2">수행평가</th><th>합계</th></tr>
    <tr><td>횟수/영역</td><td>등반</td><td>건강 관리</td><td>-</td></tr>
    <tr><td>교육과정 성취 기준</td><td>[12체육01-01]</td><td>[12체육01-02]</td><td>-</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "과학탐구실험1")

    # The bracketed course name now marks an exact course heading.
    assert section.boundary_status.startswith(("subject_heading:", "subject_heading_exact:"))
    titles = [item.title for item in section.items if item.extraction_status == "bounded"]
    assert titles == ["패러다임의 전환을 만화로 표현하기", "생활 속의 과학 탐구"]
    assert "등반" not in section.source_markdown



def test_a_plain_title_line_ending_in_the_bracketed_course_opens_its_section() -> None:
    # kordoc 는 PDF 표지 제목을 "#" 없는 문단으로 읽는다(서울 개포고 3학년 계획서).
    source = """
# 3학년 평가계획

2026학년도 3학년 ( 화학II )

<table>
<tr><th>평가과제</th><th>산화 환원 적정 실험</th></tr>
<tr><td>성취기준</td><td>[12화학Ⅱ04-01]</td></tr>
</table>

2026학년도 3학년 ( 생명과학II )

1. 연간 평가 계획표

<table>
<tr><th>평가과제</th><th>나의 질문, 생명으로 답하다</th></tr>
<tr><td>성취기준</td><td>[12생과Ⅱ01-01] 생명과학의 역사를 설명할 수 있다.</td></tr>
<tr><td>평가 방법</td><td>☑ 서술·논술 □ 구술·발표</td></tr>
<tr><td>배점</td><td>30점</td></tr>
</table>
"""

    section = parse_assessment_section(source, "생명과학Ⅱ")

    assert section.boundary_status.startswith("subject_heading_exact")
    assert "산화 환원" not in section.source_markdown
    titles = [item.title for item in section.items if item.extraction_status == "bounded"]
    assert titles == ["나의 질문, 생명으로 답하다"]


def test_a_method_label_merged_over_menu_rows_reads_every_ticked_option() -> None:
    # kordoc 는 "평가 방법" 칸이 세 행을 덮고, 체크(□V)를 ☑ 로 살려 둔다.
    source = """
# 생명과학
## 수행평가 세부 계획
<table>
<tr><th>평가과제</th><th colspan="3">생태계 보전 방안 탐구 보고서</th></tr>
<tr><td>성취기준</td><td colspan="3">[12생과05-03] 생태계 보전 방안을 제안할 수 있다.</td></tr>
<tr><td rowspan="3">평가 방법</td><td>□ 서술·논술</td><td>☑ 구술·발표</td><td>□ 토의･토론</td></tr>
<tr><td>□ 실험･실습</td><td>☑ 포트폴리오</td><td>□ 기타</td></tr>
<tr><td>☑ 교사 관찰 및 기록</td><td>□ 자기평가</td><td>□ 동료평가</td></tr>
<tr><td>배점</td><td colspan="3">20점</td></tr>
</table>
"""

    items = [
        item for item in parse_assessment_section(source, "생명과학").items
        if item.extraction_status == "bounded"
    ]

    assert [item.title for item in items] == ["생태계 보전 방안 탐구 보고서"]
    method = items[0].method
    assert "구술·발표" in method and "포트폴리오" in method and "교사 관찰 및 기록" in method
    assert "서술·논술" not in method and "동료평가" not in method


def test_a_numbered_section_word_does_not_cut_the_task_heading_short() -> None:
    # 인천 동인천고 PDF: kordoc 는 "1) 평가 개요"를 번호와 한 줄로 낸다.
    source = """
# 2026학년도 1학기 ( 생명과학Ⅱ )과 교수학습 및 평가 운영 계획

3. 수행 평가 기준안

### 가. 영역 : 유전 정보의 흐름 탐구

## 1) 평가 개요

<table>
<tr><th>단원명</th><th>Ⅳ. 유전자의 발현과 조절</th></tr>
<tr><td>성취기준</td><td>[12생과Ⅱ04-02], [12생과Ⅱ04-03]</td></tr>
<tr><td>평가유형</td><td>서술형, 논술형</td></tr>
</table>

## 2) 채점 기준

<table>
<tr><th>평가 요소</th><th>채점 기준</th><th>배점</th></tr>
<tr><td>자료해석</td><td>주어진 자료를 90% 이상 올바르게 해석하여 서술한 경우</td><td>15</td></tr>
</table>
"""

    titles = [
        item.title for item in parse_assessment_section(source, "생명과학Ⅱ").items
        if item.extraction_status == "bounded"
    ]

    assert titles == ["유전 정보의 흐름 탐구"]


def test_title_course_part_reads_the_course_out_of_plan_titles() -> None:
    from scripts.biology_assessment_detail_parser import _standalone_course_heading as heading

    assert heading(
        "### 2026학년도 1학기 3학년 생명과학II과 교수ㆍ학습 및 평가 운영 계획"
    ) == "생명과학Ⅱ"
    assert heading("## 1 생명과학II과 교수․학습 운영 계획") == "생명과학Ⅱ"
    assert heading("## 40 생명과학") == "생명과학"
    assert heading("2026학년도 1학기 생명과학Ⅱ") == "생명과학Ⅱ"
    # A department plan and a numbered list entry are not course titles.
    assert heading("생명과학과 평가계획") == ""
    assert heading("2. 생명과학") == ""
    assert heading("2026학년도 1학기 지구과학Ⅱ") == ""


def test_a_title_box_split_into_headings_keeps_its_course_section() -> None:
    # 충남 호서고: 표지 상자가 "# 2026학년도 1학기 / # 생명과학 / # 교수학습 평가계획"으로 나뉜다.
    source = """
# 2026학년도 1학기

# 생명과학

# 교수학습 평가계획

## Ⅳ. 평가의 종류와 반영비율

<table>
<tr><th>평가 종류</th><th>정기시험</th><th colspan="2">수행평가</th></tr>
<tr><td>영역</td><td>1회고사</td><td>식물군집 분석(방형구법)</td><td>혈액형 판정 실험</td></tr>
<tr><td>반영비율</td><td>40%</td><td>30%</td><td>30%</td></tr>
<tr><td>성취기준</td><td>-</td><td>[12생과05-01]</td><td>[12생과02-05]</td></tr>
</table>
"""

    section = parse_assessment_section(source, "생명과학")

    assert section.boundary_status.startswith("subject_heading_exact")
    assert "식물군집" in section.source_markdown


def test_an_area_score_label_after_an_item_number_names_the_task() -> None:
    # 경기 역곡고: 첫 칸이 항목 번호 "(1)", 그다음 "영역(만점) │ 세포호흡 설명하기(20)".
    from scripts.biology_assessment_detail_parser import explicit_segment_title_with_label

    segment = """<table>
<tr><th>(1)</th><th colspan="2">영역(만점)</th><th colspan="3">세포호흡 설명하기(20)</th></tr>
<tr><td>성취기준</td><td colspan="5">[12생과Ⅱ03-02] 세포 호흡 과정을 설명할 수 있다.</td></tr>
</table>"""

    title, label = explicit_segment_title_with_label(segment)

    assert title.startswith("세포호흡 설명하기")
    assert label == "영역만점"


def test_a_name_before_a_seal_mark_is_not_published() -> None:
    rendered = markdown_fragment_to_html(
        "담당교사: 강여은(인), 차종우 (인)\n\n"
        "<table>\n<tr><td>지도교사</td><td>이형수 (인)</td></tr>\n</table>"
    )

    assert "강여은" not in rendered and "차종우" not in rendered and "이형수" not in rendered
    assert "○○○(인)" in rendered and "○○○ (인)" in rendered


HAEGANG_TASK_DESCRIPTION_SOURCE = """
# 2026학년도 (통합과학1) 교수학습 및 평가계획
## 수행평가 세부 계획
1. 수행평가 범위와 기준 및 반영 비율
<table>
<tr><th>학기</th><th>평가 영역</th><th>성취 기준</th><th>반영비율</th></tr>
<tr><td rowspan="2">1</td><td>동시낙하 실험보고서</td>
<td>[10통과1-03-03]</td><td>20%</td></tr>
<tr><td>스펙트럼 관찰 실험보고서</td><td>[10통과1-02-01]</td><td>20%</td></tr>
</table>
2. 세부계획
1) 동시낙하 실험보고서
<table>
<tr><th>수행과제</th><th colspan="4">· 낙하 운동 분석<br>
· 중력 작용 설명<br>
· 이동 거리 계산</th></tr>
<tr><td>성취기준</td><td colspan="4">[10통과1-03-03] 중력 운동</td></tr>
<tr><td>평가방법</td><td colspan="4">☑ 실험･실습 □ 포트폴리오</td></tr>
<tr><td>채점기준</td><td>A</td><td colspan="3">낙하를 해석한다.</td></tr>
</table>
2) 스펙트럼 관찰 실험보고서
<table>
<tr><th>수행과제</th><th colspan="4">· 간이 분광기 제작하기<br>
· 여러 광원의 스펙트럼 관찰<br>
· 결론 작성하기</th></tr>
<tr><td>성취기준</td><td colspan="4">[10통과1-02-01] 원소의 생성</td></tr>
<tr><td>평가방법</td><td colspan="4">☑ 실험･실습 □ 포트폴리오</td></tr>
<tr><td>채점기준</td><td>A</td><td colspan="3">원소를 추론한다.</td></tr>
</table>
"""


def test_a_task_description_cell_under_a_short_heading_becomes_the_overview() -> None:
    # 부산 해강고: "1) 동시낙하 실험보고서" 아래 표의 수행과제 칸은 할 일을
    # 줄줄이 적은 설명이다. 머리글이 이름이고 칸은 개요다. 같은 설명이 따로
    # 한 과제로 다시 실리지 않고, 맨 위 요약표 머리글도 과제가 아니다.
    source = HAEGANG_TASK_DESCRIPTION_SOURCE
    items = parse_assessment_section(source, "통합과학1").items
    bounded = [item for item in items if item.extraction_status == "bounded"]

    assert [item.title for item in bounded] == [
        "동시낙하 실험보고서",
        "스펙트럼 관찰 실험보고서",
    ]
    assert all(item.title_basis == "heading" for item in bounded)
    assert "낙하 운동 분석" in bounded[0].overview
    assert not any("범위와 기준" in item.title for item in items)


def test_a_task_name_cell_still_outranks_a_short_heading() -> None:
    # 칸이 설명이 아니라 이름일 때(짧고 한 덩어리)는 지금처럼 칸이 이긴다.
    source = HAEGANG_TASK_DESCRIPTION_SOURCE.replace(
        "· 낙하 운동 분석<br>\n· 중력 작용 설명<br>\n· 이동 거리 계산",
        "낙하 운동 실험",
    )

    first = parse_assessment_section(source, "통합과학1").items[0]

    assert first.title == "낙하 운동 실험"
    assert first.title_basis == "table"


def test_written_exam_scope_is_not_a_task_title() -> None:
    from scripts.biology_assessment_detail_parser import _valid_plan_title

    assert not _valid_plan_title(
        "1학기 중간고사 : [12생과01-01] ~ [12생과02-04] "
        "1학기 기말고사 : [12생과02-05] ~ [12생과03-05]"
    )
    assert not _valid_plan_title("1차 지필고사")
    assert not _valid_plan_title("학기말고사")
    assert not _valid_plan_title("\U000f02ef1차 지필평가 [12생과Ⅱ01-01]")
    assert _valid_plan_title("효소 활성 실험 보고서")


def test_a_checklist_question_is_a_rubric_line_not_a_title() -> None:
    from scripts.biology_assessment_detail_parser import is_rubric_criterion_sentence

    assert is_rubric_criterion_sentence(
        "의사소통 능력, 협동 능력을 활용하여 탐구활동을 수행하고, "
        "탐구활동의 결과를 설명할 수 있는가?"
    )
    assert is_rubric_criterion_sentence("다른 친구들과 협력하였는가?")
    assert is_rubric_criterion_sentence("문제 해결 활동에 적극적으로 참여하는가?")
    # 학생에게 던지는 질문형 과제명은 그대로 둔다.
    assert not is_rubric_criterion_sentence("유전자는 어떻게 켜지고 꺼지는가?")
    assert not is_rubric_criterion_sentence("친구들과 함께 마술 공연을 해 볼까?")


def test_field_label_lines_and_policy_fragments_are_not_task_headings() -> None:
    from scripts.biology_assessment_detail_parser import heading_is_policy_prose

    for line in (
        "평가 요소 및 방법 : 주제의 선정, 동료의 반응을 통해 융합적 사고력을 평가, 태도",
        "평가 요소 및 방법: 자료 해석 능력, 과학적 사고력 등",
        "대상 학년: 2학년",
        "평가 시기: 3월~6월",
        "관련단원 : Ⅰ. 생명 과학의 역사~ Ⅵ. 생명 공학 기술과 인간 생활",
        "반영 비율 및 배점 : 30점",
        "의 –1점을 부여한다.",
        "동점자 처리 순위는 기말고사(1순위) - 중간고사(2순위)",
        "수행평가 범위와 기준 및 반영 비율",
    ):
        assert heading_title_is_structural(line, policy_prose=False), line
    assert heading_is_policy_prose(
        "일제형의 서답형 평가는 정기시험에 포함하여 실시하며 "
        "18%를 반영한다. (단, 단답형 문항은 제외)"
    )
    assert not heading_title_is_structural("동시낙하 실험보고서")
    assert not heading_title_is_structural("평가 시기별 생물 관찰 일지")


def test_score_cells_and_document_sections_are_not_task_names() -> None:
    from scripts.biology_assessment_detail_parser import _valid_plan_title

    for value in ("70점 (이하)", "68점 (이하)", "30%", "30%(이상)", "미실시", "보통임"):
        assert not _valid_plan_title(value), value
    for line in (
        "평가 시 유의 사항 가. 공통사항",
        "평가의 기본 방향과 방침",
        "정의적 능력 평가의 목적",
        "평가의 종류‧방법‧시기‧반영비율",
        "평가 도구 제작의 원칙",
        "수행평가 시행 계획 및 세부 채점 기준",
        "재ㆍ전ㆍ편입 학생의 경우",
        "목적",
        "일반 원칙",
        "학기 단위(영역별) 성취수준",
        "평가 상황에서 인공지능(AI)활용이 금지되는 행위를 명확히 설정하고",
        "수행평가 채점 기준(예시)",
        "교수-학습 운영 계획",
        "수행평가 영역별 배점, 횟수, 실시 시기",
    ):
        assert heading_title_is_structural(line, policy_prose=False), line
    for name in ("생명윤리 원칙 토론", "실험 목적에 맞는 변인 설계", "70주년 과학 포스터"):
        assert _valid_plan_title(name), name
        assert not heading_title_is_structural(name), name


def test_an_area_score_row_does_not_name_a_task() -> None:
    # 전국 155개 사례: 요약표 '영역만점' 줄의 첫 값 "70점 (이하)"가 과제명이 됐다.
    source = """
# 2026학년도 (생명과학Ⅱ) 교수학습 및 평가계획
## 수행평가 세부 계획
<table>
<tr><td>평가종류</td><td colspan="2">정기시험</td><td colspan="3">수행평가</td></tr>
<tr><td>횟수/영역</td><td colspan="2">2차시험</td><td>자유탐구</td>
<td>융합 평가</td><td>배움기록 평가</td></tr>
<tr><td>영역만점</td><td>70점 (이하)</td><td>30점(이상)</td><td>30점</td>
<td>20점</td><td>20점</td></tr>
<tr><td>성취기준</td><td colspan="2">[12생과Ⅱ01-01]</td><td>[12생과Ⅱ01-02]</td>
<td>[12생과Ⅱ02-06]</td><td>[12생과Ⅱ01-01]</td></tr>
<tr><td>평가방법</td><td>선택형</td><td>서답형</td><td>보고서</td><td>논술</td><td>발표</td></tr>
</table>
"""

    titles = [item.title for item in parse_assessment_section(source, "생명과학Ⅱ").items]

    assert not any("이하" in title or "이상" in title for title in titles)


def test_a_cover_table_course_cell_identifies_a_single_course_plan() -> None:
    # 덕원여고: 과목 제목 줄 없이 첫 표의 "과목명 │ 생명과학Ⅱ"만 과목을 밝힌다.
    source = """
<table>
<tr><td>과목명</td><td>생명과학Ⅱ</td><td>학점</td><td>3</td><td>학년</td><td>3학년</td></tr>
</table>
## 수행평가 세부 계획
1. 유전자 재조합 모의실험 분석하기
<table>
<tr><th>평가영역</th><td>유전자 재조합 모의실험 분석하기</td></tr>
<tr><td>성취기준</td><td>[12생과Ⅱ04-01] 유전자 재조합 기술을 설명한다.</td></tr>
<tr><td>평가방법</td><td>☑ 실험･실습</td></tr>
<tr><td>채점기준</td><td>A 수준의 분석을 한다.</td></tr>
</table>
"""

    section = parse_assessment_section(source, "생명과학Ⅱ")

    assert not section.boundary_status.startswith("subject_heading_not_found")
    assert [item.title for item in section.items if item.extraction_status == "bounded"] == [
        "유전자 재조합 모의실험 분석하기"
    ]
    # 다른 과목의 표지 칸("생명과학")이나 머리 행("과목 │ 학급")은 이 과목이 아니다.
    other_cover = source.replace("생명과학Ⅱ</td><td>학점", "생명과학</td><td>학점")
    assert subject_local_markdown(other_cover, "생명과학Ⅱ")[3] == "subject_heading_not_found"
    # 그래도 행마다 이 과목 성취기준 코드만 있으면 그 코드가 경계다.
    assert parse_assessment_section(other_cover, "생명과학Ⅱ").boundary_status == (
        "subject_code_rows:assessment_anchor"
    )


def test_a_course_written_with_an_arabic_numeral_is_the_same_course() -> None:
    from scripts.biology_assessment_detail_parser import subject_local_markdown

    text = (
        "[zip:2026 교수학습 및 평가 운영 계획(화학2).hwp][ok]\n화학 내용\n"
        "[zip:2026 교수학습 및 평가 운영 계획(3학년 생명과학2).hwp][ok]\n생물 내용\n"
    )
    section, _, _, status = subject_local_markdown(text, "생명과학Ⅱ")

    assert status == "zip_member_subject"
    assert "생물 내용" in section and "화학 내용" not in section


def test_a_numbered_plan_part_or_a_split_title_does_not_end_the_course() -> None:
    from scripts.biology_assessment_detail_parser import subject_local_markdown

    text = "\n".join(
        [
            "2026학년도 3학년 1학기 [생명과학2]",
            "교수학습 및 평가 운영 계획",
            "1 평가 개요",
            "2 월별 교수학습 및 평가 방법",
            "생물 수행평가 세부 계획",
            "2026학년도 1학기 지구과학 과목 교수학습 및 평가 운영 계획",
            "지구과학 내용",
        ]
    )
    section, _, _, _ = subject_local_markdown(text, "생명과학Ⅱ")

    assert "생물 수행평가 세부 계획" in section
    assert "지구과학 내용" not in section


def test_a_grade_number_after_the_course_is_not_its_numeral() -> None:
    # 현화고: "(생명과학)_2학년"을 생명과학2(=생명과학Ⅱ)로 읽으면 다른 과목 파일을 고른다.
    from scripts.biology_assessment_detail_parser import subject_local_markdown

    text = (
        "[zip:2026 교수학습 및 평가 운영 계획(생명과학)_2학년.hwpx][ok]\n생명과학 내용\n"
        "[zip:2026 교수학습 및 평가 운영 계획(생명과학2교과)_3학년.hwp][ok]\n생명과학Ⅱ 내용\n"
    )
    section, _, _, status = subject_local_markdown(text, "생명과학Ⅱ")

    assert status == "zip_member_subject"
    assert "생명과학Ⅱ 내용" in section and "생명과학 내용" not in section


def test_the_department_title_does_not_close_its_own_course() -> None:
    # 성일고: "생명과학Ⅰ 교수학습·평가 계획" 아래의 학과 제목은 같은 과목 계열이다.
    from scripts.biology_assessment_detail_parser import subject_local_markdown

    text = "\n".join(
        [
            "# 2026학년도 1학기 생명과학Ⅰ 교수학습·평가 계획",
            "### 생명과학과 교수학습·평가 운영 계획",
            "생물 수행평가 세부 계획",
            "# 2026학년도 1학기 체육 교수학습·평가 계획",
            "체육 내용",
        ]
    )
    section, _, _, _ = subject_local_markdown(text, "생명과학Ⅰ")

    assert "생물 수행평가 세부 계획" in section
    assert "체육 내용" not in section


def test_a_course_title_split_over_two_heading_lines_closes_the_course() -> None:
    # 삼척여고: 다음 과목 제목이 "[프랑스어 독해와 작문Ⅰ]" 줄과 "교수학습·평가 계획서" 줄로 나뉜다.
    from scripts.biology_assessment_detail_parser import subject_local_markdown

    text = "\n".join(
        [
            "# 2026학년도 2학년 2학기 고급생명과학 교수학습·평가 계획서",
            "생물 수행평가 세부 계획",
            "# 2026학년도 [2]학년 2학기 [프랑스어 독해와 작문Ⅰ]",
            "",
            "# 교수학습·평가 계획서",
            "프랑스어 내용",
        ]
    )
    section, _, _, _ = subject_local_markdown(text, "고급생명과학")

    assert "생물 수행평가 세부 계획" in section
    assert "프랑스어" not in section


def test_a_rubric_under_a_task_heading_grades_that_task() -> None:
    # 삼척여고: "1) 배움 기록장 작성하기" 아래 채점표의 평가항목("내용 작성", "태도")은
    # 그 과제의 채점 요소다. 따로 과제가 되지 않는다.
    rubric = "".join(
        f"<tr><td>{element}</td><td>{detail}</td><td>{criterion}</td><td>{score}</td></tr>"
        for element, detail, criterion, score in (
            ("내용 작성", "배움 기록장 작성하기", "모두 올바르게 작성함", "50"),
            ("내용 작성", "배움 기록장 작성하기", "일부를 작성하지 못함", "30"),
            ("태도", "성실한 참여", "성실하게 참여함", "10"),
            ("태도", "성실한 참여", "참여가 부족함", "5"),
        )
    )
    source = f"""
# 2026학년도 2학기 고급생명과학 교수학습·평가 계획서
## 수행평가 세부 계획
# 1) 배움 기록장 작성하기
<table><tr><td>성취기준</td><td>[12고생01-01] 생명 현상을 탐구한다.</td></tr>
<tr><td>평가방법</td><td>☑ 포트폴리오</td></tr></table>
<table><tr><th>평가항목</th><th>평가요소</th><th>채점 기준</th><th>배점</th></tr>{rubric}</table>
# 2) 생명과학 세미나
<table><tr><td>성취기준</td><td>[12고생02-01] 세포를 탐구한다.</td></tr>
<tr><td>평가방법</td><td>☑ 구술·발표</td></tr></table>
"""
    section = parse_assessment_section(source, "고급생명과학")

    assert [item.title for item in section.items if item.extraction_status == "bounded"] == [
        "배움 기록장 작성하기",
        "생명과학 세미나",
    ]


def test_a_rubric_question_is_not_a_task_but_a_question_naming_one_is() -> None:
    from scripts.biology_assessment_detail_parser import is_rubric_criterion_sentence

    assert is_rubric_criterion_sentence("결과 해석에서 색소 분리와 관련된 문항을 옳게 설명하는가?")
    assert is_rubric_criterion_sentence("교과와 관련된 내용을 주제로 선정하여 자료 조사를 하는가")
    assert not is_rubric_criterion_sentence("심폐 조절: 우리 몸은 어떻게 항상성을 유지하는가?")
    assert not is_rubric_criterion_sentence("서술형평가: 수소와 헬륨, 그들은 어디에서 왔는가?")
    assert not is_rubric_criterion_sentence("인간은 진화하는가?")
    assert is_rubric_criterion_sentence(
        "동물들의 특징을 비교하여 제시된 동물이 어디에 속하는지 옳게 설명하였는가?"
    )


def test_exam_rows_and_exam_section_titles_are_not_tasks() -> None:
    # 동인고: 글머리 기호(사용자 정의 글자) 뒤 "중간고사 - [12고생01-01~13]".
    from scripts.biology_assessment_detail_parser import _valid_title, strip_title_decoration

    assert not _valid_title(strip_title_decoration("\U000f02ef중간고사 - [12고생01-01~13]"))
    assert not _valid_title(strip_title_decoration("\U000f02ef1차 지필고사 - [12생과01-01]~"))
    assert strip_title_decoration("\U000f02ef자유 탐구 보고서") == "자유 탐구 보고서"
    # 경동고·반여고: 지필·수행 비율 제목과 끝에 괄호 주석이 붙은 방침 문장.
    assert heading_title_is_structural("지필고사 및 수행평가 비율")
    assert heading_title_is_structural(
        "이 과목은 지필평가 없이 수행평가로 평가를 진행한다(영역별 반영 비율은 평가계획 참고)."
    )
    assert not heading_title_is_structural("실험 보고서 작성(관찰 일지 포함)")


def test_a_rubric_shared_with_other_courses_is_not_attached_to_the_row() -> None:
    # 고성고: 생명과학Ⅱ·지구과학Ⅱ·생활과 과학이 한 채점표를 같이 쓴다.
    source = """
<table>
<tr><th>평가 유형</th><th colspan="2">수행평가</th></tr>
<tr><td>반영비율(%)</td><td colspan="2">100%</td></tr>
<tr><td>횟수/영역</td><td>탐구 활동지</td><td>탐구보고서</td></tr>
<tr><td>만점</td><td>100점</td><td>100점</td></tr>
<tr><td>평가 시기</td><td>수시</td><td>수시</td></tr>
<tr><td>관련 성취 기준</td><td>[12생과Ⅱ03-01] ~ [12생과Ⅱ03-05]</td>
<td>[12생과Ⅱ06-01] ~ [12생과Ⅱ06-04]</td></tr>
</table>
<table>
<tr><th>영역</th><th>성취기준</th><th>채점기준</th></tr>
<tr><td>탐구보고서</td><td>[12생과Ⅱ06-01]</td><td>척도표에 따름</td></tr>
<tr><td>탐구보고서</td><td>[12지과Ⅱ05-01]</td><td>척도표에 따름</td></tr>
</table>
"""
    section = parse_assessment_section(source, "생명과학Ⅱ")
    bounded = {item.title: item for item in section.items if item.extraction_status == "bounded"}

    assert "탐구보고서" in bounded
    assert "12생과Ⅱ06-01" in bounded["탐구보고서"].source_html.replace(" ", "")
    assert "12지과" not in bounded["탐구보고서"].source_html
    assert section.boundary_status.startswith("subject_code_rows:")


def test_a_scored_heading_names_the_task_over_its_description_cell() -> None:
    # 전주해성고·청람고 모양: "가. ○○(총 10점)" 아래 수행 과제 칸이 할 일을 쓴 문장이다.
    source = """
# 2026학년도 1학기 통합과학1 교수학습·평가 계획
## 수행평가 세부 계획
가. 과학융합역량(총 20점)
<table>
<tr><td>수행 과제</td>
<td>생명과학의 주요 발견 중 하나를 선정하여 발견의 시기와 내용, 연구 방법을 조사하기</td></tr>
<tr><td>성취기준</td><td>[10통과1-01-01] 과학의 발전 과정을 설명한다.</td></tr>
<tr><td>평가방법</td><td>☑ 구술·발표</td></tr>
</table>
"""
    from scripts.biology_assessment_detail_parser import _reads_as_task_description

    section = parse_assessment_section(source, "통합과학1")
    bounded = [item for item in section.items if item.extraction_status == "bounded"]

    assert [item.title for item in bounded] == ["과학융합역량"]
    assert bounded[0].overview.startswith("생명과학의 주요 발견")
    # 평가 방식만 적은 제목줄("서·논술형 평가")이나 단원 제목은 칸 문장보다 못한 이름이다.
    sentence = "세포막을 통한 물질 출입 원리를 설명하는 글쓰기"
    assert not _reads_as_task_description(sentence, "서·논술형 평가")
    assert not _reads_as_task_description(sentence, "Ⅱ. 물질과 규칙성")
    assert _reads_as_task_description("· 세포막 모형 만들기 · 삼투 실험하기", "서·논술형 평가")


def test_a_named_area_cell_outranks_the_task_description_row() -> None:
    # 동탄고: 첫 행 "수행평가 영역명 │ 이름 │ 영역 만점 │ 25점", 다음 행 "수행과제 │ 문장".
    from scripts.biology_assessment_detail_parser import explicit_segment_title

    segment = (
        "<table><tr><td>수행평가 영역명</td><td>생물의 진화 과정 탐구 포트폴리오 제작하기</td>"
        "<td>영역 만점</td><td>25점</td></tr>"
        "<tr><td>수행과제</td>"
        "<td>세포내공생설을 탐구하고 학습한 내용을 재구성하여 표현하기</td></tr>"
        "</table>"
    )

    assert explicit_segment_title(segment) == "생물의 진화 과정 탐구 포트폴리오 제작하기"


def test_notes_and_labels_around_a_name_are_not_part_of_it() -> None:
    from scripts.biology_assessment_detail_parser import strip_title_decoration

    assert strip_title_decoration(
        "생물 진화 포트폴리오 (수행평가 과제명으로 교육정보시스템에 입력 사항임)"
    ) == "생물 진화 포트폴리오"
    assert strip_title_decoration("효모의 물질대사 탐구 (2순위)") == "효모의 물질대사 탐구"
    assert strip_title_decoration("조선의 과학기술 원리 찾기[35점]") == "조선의 과학기술 원리 찾기"
    assert strip_title_decoration("세포 관찰 (관련 성취기준: [12생과01-01])") == "세포 관찰"
    assert strip_title_decoration("평가과제1(통합과학A): 원소 카드 만들기") == "원소 카드 만들기"
    assert strip_title_decoration("평가과제(파스퇴르의 실험을 재연하고 분석하기)") == (
        "파스퇴르의 실험을 재연하고 분석하기"
    )
    assert strip_title_decoration("실험·실습 1 (K-POP 속 과학 개념 분석 탐구)") == (
        "K-POP 속 과학 개념 분석 탐구"
    )
    assert strip_title_decoration("탐구 보고서(관찰 일지 포함)") == "탐구 보고서(관찰 일지 포함)"
    assert strip_title_decoration("PCR (중합효소 연쇄 반응)") == "PCR (중합효소 연쇄 반응)"


def test_a_unit_path_is_a_name_only_when_it_ends_in_a_task() -> None:
    from scripts.biology_assessment_detail_parser import _valid_title, strip_title_decoration

    assert strip_title_decoration(
        "Ⅰ. 과학의 본성과 역사 속의 과학 탐구 / 03. 우리 선조들의 과학 기술 발전 사례 찾기"
    ) == "우리 선조들의 과학 기술 발전 사례 찾기"
    assert not _valid_title("Ⅲ. 시스템과 상호작용 / 3. 생명 시스템 / 02. 정보의 흐름")
    assert not _valid_title("Ⅱ. 물질의 규칙성 2. 원소의 규칙성 03. 화학 결합에 따른 물질의 성질")
    assert not _valid_title("Ⅰ-3. 생태계 02. 개체군과 군집의 특성(과학적 사고력, 과학적 탐구능력)")


def test_truncated_policy_lines_and_element_lists_are_not_names() -> None:
    from scripts.biology_assessment_detail_parser import _valid_plan_title

    for line in (
        "생명과학의 원리가 타 학문과 결합하여 현대 사회의 문제를 해결하거나 새로운 가치를 창출한",
        "‘생명과학’ 교육과정상의 내용 체계와의 관련성을 고려하여 지식⋅이해, 과정⋅기능,",
        "평가 방법의 공정성, 객관성이 유지되도록 하며 평가 기준을 사전에 공고하고 공개함으로써",
        "평가 세부 내용 : 실험, 조사, 발표 등의 방법을 활용하여 교사가 관찰하면서 포착되는 학생의",
        "학생의 자기주도적 학습 촉진: 학생이 자신의 학습 과정과 결과를 성찰하도록 지원",
        "과학에 대한 흥미와 가치 인식, 과학 학습 참여의 적극성, 협동성, 창의성",
        "병원학교 참여 학생 및 장기 결석이 예상되는 학생의 평가 처리 방안",
        "평가는 수행평가로 실시하고, 수행평가의 영역·방법·횟수·요소·반영 비율",
    ):
        # 제목줄로 오든 표 칸으로 오든 이름으로 받지 않는다.
        assert not _valid_plan_title(line) or heading_title_is_structural(line), line
    task = "효소의 작용 원리를 이해하고 일상생활에서 활용되는 효소의 사례를 조사하기"
    assert _valid_plan_title(task) and not heading_title_is_structural(task)


def test_a_summary_cell_naming_two_tasks_is_not_a_third_task() -> None:
    source = """
# 2026학년도 1학기 생명과학 교수학습·평가 계획
## 수행평가 세부 계획
1. 세포 관찰 보고서
<table><tr><td>성취기준</td><td>[12생과01-01] 세포를 관찰한다.</td></tr>
<tr><td>평가방법</td><td>☑ 실험·실습</td></tr></table>
2. 생명과학 성과 발표
<table><tr><td>성취기준</td><td>[12생과01-02] 성과를 발표한다.</td></tr>
<tr><td>평가방법</td><td>☑ 구술·발표</td></tr></table>
<table>
<tr><th>평가 영역</th><th>반영비율</th><th>평가방법</th></tr>
<tr><td>세포 관찰 보고서, 생명과학 성과 발표</td><td>40%</td><td>실험, 발표</td></tr>
</table>
"""
    section = parse_assessment_section(source, "생명과학")

    assert [item.title for item in section.items if item.extraction_status == "bounded"] == [
        "세포 관찰 보고서",
        "생명과학 성과 발표",
    ]


def test_an_unknown_course_title_split_over_two_plain_lines_closes_the_course() -> None:
    # 덕암정보고: "2026학년도 1학기 체육(2)과목" 다음 줄 "교수학습 및 평가 운영 계획".
    from scripts.biology_assessment_detail_parser import subject_local_markdown

    text = "\n".join(
        [
            "2026학년도 1학기 통합과학1",
            "교수학습 및 평가 운영 계획",
            "통합과학 수행평가 세부 계획",
            "2026학년도 1학기 정보 처리와 관리",
            "",
            "교수학습 및 평가 운영 계획",
            "워드프로세서 문서 작성하기",
        ]
    )
    section, _, _, _ = subject_local_markdown(text, "통합과학1")

    assert "통합과학 수행평가 세부 계획" in section
    assert "워드프로세서" not in section


def test_one_task_named_two_ways_is_read_once() -> None:
    from scripts.biology_assessment_detail_parser import _names_a_task_already_read, _title_key

    assert _title_key("탐구평가") == _title_key("탐구")
    assert _title_key("수행평가") == "수행평가"

    def item(title: str):
        return type("Item", (), {"title": title, "extraction_status": "bounded"})()

    read = [item("연역적 탐구 기반 실험 보고서 작성"), item("무척추동물 해부 실험 보고서 작성")]
    assert _names_a_task_already_read(read, item("연역적 탐구 기반 실험보고서 (1회)"))
    # 청도고: 요약표는 같은 과제를 문장으로 풀어 쓴다.
    assert _names_a_task_already_read(
        read,
        item("‘무척추 동물 해부를 통한 구조와 기능 탐구 실험’의 결과를 정리하고 보고서 작성하기"),
    )
    assert not _names_a_task_already_read(read, item("세포 관찰"))
    assert not _names_a_task_already_read(read, item("척추동물 해부 실험"))


def test_graded_elements_in_an_area_column_are_not_tasks() -> None:
    # 인천포스코고: "영역 │ 평가기준 │ 점수" 표의 첫 열은 채점 요소("주제 선정 (20점)")다.
    rows = "".join(
        f"<tr><td>{area}</td><td>{criterion}</td><td>{score}</td></tr>"
        for area, criterion, score in (
            ("주제 선정 (20점)", "적절한 주제를 선정함", "20"),
            ("주제 선정 (20점)", "주제 선정이 미흡함", "10"),
            ("과학적 분석 (30점)", "원리를 명확하게 이해함", "30"),
            ("과학적 분석 (30점)", "단편적으로 나열함", "10"),
        )
    )
    source = f"""
# 2026학년도 2학기 고급생명과학 교수학습·평가 계획
## 수행평가 영역별 세부 기준
[12고생04-01] 세포 공학 기술의 활용 사례를 조사한다.
<table><tr><th>영역</th><th>평가기준</th><th>점수</th></tr>{rows}</table>
"""
    section = parse_assessment_section(source, "고급생명과학")

    assert not [item.title for item in section.items if item.extraction_status == "bounded"]


def test_tasks_in_an_area_column_count_when_a_plan_table_names_them() -> None:
    # 대영고: 평가 계획 표와 채점표가 같은 과제명("탐구 보고서 1")을 쓴다.
    plan = (
        "<table><tr><th>평가항목</th><th>평가내용 및 방법</th><th>점수</th><th>평가시기</th></tr>"
        "<tr><td>탐구 보고서 1</td><td>보고서</td><td>10</td><td>4월</td></tr>"
        "<tr><td>식물도감 제작 프로젝트</td><td>제작</td><td>10</td><td>6월</td></tr></table>"
    )
    rubric = "".join(
        f"<tr><td>{area}</td><td>{criterion}</td><td>{score}</td></tr>"
        for area, criterion, score in (
            ("탐구 보고서 1 (10점)", "충실하게 작성함", "10"),
            ("탐구 보고서 1 (10점)", "미흡함", "5"),
            ("식물도감 제작 프로젝트 (10점)", "충실하게 제작함", "10"),
            ("식물도감 제작 프로젝트 (10점)", "미흡함", "5"),
        )
    )
    source = f"""
# 2026학년도 1학기 생명과학 교수학습·평가 계획
## 수행평가 세부 기준
[12생과01-01] 생명 현상을 탐구한다.
{plan}
<table><tr><th>평가항목</th><th>평가기준</th><th>배점</th></tr>{rubric}</table>
"""
    titles = [
        item.title
        for item in parse_assessment_section(source, "생명과학").items
        if item.extraction_status == "bounded"
    ]

    assert "탐구 보고서 1" in titles and "식물도감 제작 프로젝트" in titles


def test_a_label_value_detail_table_is_not_a_summary_list() -> None:
    # 조선대부고: "평가영역 │ 만점 │ │ 100점" 상세표의 첫 열(단원, 체크 칸, "방식")은 과제가 아니다.
    from scripts.biology_assessment_detail_parser import _summary_table_items, _valid_title

    table = (
        "<table><tr><td>평가영역</td><td>만점</td><td></td><td>100점</td></tr>"
        "<tr><td>Ⅱ.과학탐구의 과정과 절차</td><td>시기</td><td>3월 4주</td><td></td></tr>"
        "<tr><td>☑ 서술·논술 유형</td><td>☐ 구술·발표</td><td>☐ 토론·토의</td>"
        "<td>☐ 프로젝트</td></tr>"
        "<tr><td>방식</td><td>☑ 개별수행</td><td>☐ 모둠수행</td><td></td></tr></table>"
    )

    assert not _summary_table_items(table, "과학탐구실험1", "subject_heading_exact", 0)
    assert not _valid_title("☑ 서술·논술 유형")


def test_plan_titles_and_worked_example_headings_are_not_task_names() -> None:
    from scripts.biology_assessment_detail_parser import strip_title_decoration

    assert heading_title_is_structural("통합과학D 교수·학습 및 평가 운영 계획")
    assert heading_title_is_structural("통과A 수행평가 세부 계획")
    assert strip_title_decoration("교과심화탐구 평가의 실제") == "교과심화탐구"
    assert strip_title_decoration("1회/ 파스퇴르의 생물속생설 도출 과정 분석하기") == (
        "파스퇴르의 생물속생설 도출 과정 분석하기"
    )


def test_a_name_cell_outranks_the_area_cell_and_a_summary_row_repeats_the_heading() -> None:
    # 철성고: 상세표 "평가명 │ …"이 이름이고 "평가 영역 │ 과정평가"는 영역이다.
    # 요약표의 "과정평가1"은 제목줄 "(1) 과정평가 1"과 같은 과제다.
    def detail(name: str, code: str) -> str:
        return (
            f"<table><tr><td>평가명</td><td>{name}</td></tr>"
            f"<tr><td>성취기준</td><td>[12생과Ⅱ{code}]</td><td>평가 영역</td><td>과정평가</td></tr>"
            "<tr><td>평가방법</td><td>탐구 보고서 작성</td></tr></table>"
        )

    source = f"""
# 2026학년도 1학기 생명과학Ⅱ 교수학습·평가 계획
## 수행평가 세부 계획
<table>
<tr><td>평가 유형</td><td>수행 평가</td><td>수행 평가</td></tr>
<tr><td>횟수/영역</td><td>과정평가1</td><td>과정평가2</td></tr>
<tr><td>영역만점</td><td>100점</td><td>100점</td></tr>
<tr><td>교육과정 성취기준</td><td>[12생과Ⅱ03-04]</td><td>[12생과Ⅱ01-01]</td></tr>
</table>
(1) 과정평가 1
{detail("실생활 속에서의 발효 이용 사례 조사 및 발표하기", "03-04")}
(2) 과정평가 2
{detail("자유 주제 탐구 활동 및 토의하기", "01-01")}
"""
    titles = [
        item.title
        for item in parse_assessment_section(source, "생명과학Ⅱ").items
        if item.extraction_status == "bounded"
    ]

    assert titles == [
        "실생활 속에서의 발효 이용 사례 조사 및 발표하기",
        "자유 주제 탐구 활동 및 토의하기",
    ]


def test_kind_labels_and_numbered_area_labels_are_not_part_of_the_name() -> None:
    from scripts.biology_assessment_detail_parser import strip_title_decoration

    assert strip_title_decoration("생태계 변화 사례 분석 글쓰기 (서·논술형 평가)") == (
        "생태계 변화 사례 분석 글쓰기"
    )
    assert strip_title_decoration("모의 연역적 탐구 실험 설계 [서·논술형], [프로젝트형]") == (
        "모의 연역적 탐구 실험 설계"
    )
    assert strip_title_decoration("탐구 활동보고서평가1.우리 선조들의 과학 기술 찾기") == (
        "우리 선조들의 과학 기술 찾기"
    )
    assert strip_title_decoration("수행평가 영역별 세부기준 가. 과학 스피치") == "과학 스피치"
    assert strip_title_decoration("PCR (중합효소 연쇄 반응)") == "PCR (중합효소 연쇄 반응)"


def test_a_rubric_naming_one_task_or_a_plan_task_in_other_words_is_read() -> None:
    # 환일고: 채점표 하나에 과제 하나("평가영역 │ 채점 기준 │ 배점").
    # 성신고: 채점표는 "척추동물 해부", 평가 계획 표는 "척추동물 해부 탐구 보고서".
    one = "".join(
        f"<tr><td>원소의 규칙성과 결합 탐구 실험</td><td>{level}</td><td>{score}</td></tr>"
        for level, score in (("매우 잘함", "10"), ("잘함", "8"), ("보통", "6"))
    )
    plan = (
        "<table><tr><td>평가항목</td><td>척추동물 해부 탐구 보고서</td>"
        "<td>식물의 DNA추출 탐구 보고서</td></tr>"
        "<tr><td>반영비율</td><td>30</td><td>40</td></tr>"
        "<tr><td>평가시기</td><td>3월</td><td>4월</td></tr></table>"
    )
    two = "".join(
        f"<tr><td>{name}</td><td>{criterion}</td><td>{score}</td></tr>"
        for name, criterion, score in (
            ("척추동물 해부", "구조를 정확히 설명함", "50"),
            ("척추동물 해부", "구조를 일부 설명함", "30"),
            ("식물의 DNA 추출", "과정을 정확히 수행함", "50"),
            ("식물의 DNA 추출", "과정을 일부 수행함", "30"),
        )
    )
    first = f"""
# 2026학년도 1학기 통합과학1 교수학습·평가 계획
## 수행평가 세부 기준
[10통과1-02-04] 결합의 차이를 설명한다.
<table><tr><th>평가영역</th><th>채점 기준</th><th>배점</th></tr>{one}</table>
"""
    second = f"""
# 2026학년도 1학기 생명과학실험 교수학습·평가 계획
## 수행평가 세부 기준
[12생실01-07] 기관의 구조와 기능을 추론한다.
{plan}
<table><tr><th>평가항목</th><th>평가내용 및 채점기준</th><th>점수</th></tr>{two}</table>
"""

    def bounded(source: str, subject: str) -> list[str]:
        return [
            item.title
            for item in parse_assessment_section(source, subject).items
            if item.extraction_status == "bounded"
        ]

    assert bounded(first, "통합과학1") == ["원소의 규칙성과 결합 탐구 실험"]
    assert bounded(second, "생명과학실험") == ["척추동물 해부", "식물의 DNA 추출"]


def test_a_name_under_a_column_header_and_the_sole_table_under_a_task_heading() -> None:
    from scripts.biology_assessment_detail_parser import explicit_segment_title

    # 태성고: "평가영역명 │ 영역만점 │ 학기" 아래 행이 이름이다.
    header_table = (
        "<table><tr><td>평가영역명</td><td>영역만점</td><td>학기</td></tr>"
        "<tr><td>주기율표의 발전 과정을 탐색하고, 멘델레예프처럼 사고하기</td>"
        "<td>25</td><td>1학기</td></tr>"
        "<tr><td>수행과제</td><td>멘델레예프가 주기율표를 만든 과정을 사고하며 설명하기</td></tr>"
        "</table>"
    )
    assert explicit_segment_title(header_table) == (
        "주기율표의 발전 과정을 탐색하고, 멘델레예프처럼 사고하기"
    )

    # 인덕과기고: "(1) 탐구활동1" 아래 표 하나의 평가과제 문장은 같은 과제의 설명이다.
    source = """
# 2026학년도 1학기 통합과학1 교수학습·평가 계획
## 수행평가 세부 계획
(1) 탐구활동1
<table><tr><td>평가 과제</td><td>분광기를 활용한 물질의 스펙트럼 관찰 분석하기</td></tr>
<tr><td>성취기준</td><td>[10통과1-01-03] 스펙트럼을 분석한다.</td></tr>
<tr><td>평가방법</td><td>☑ 실험·실습</td><td>반영비율</td><td>20%</td></tr>
<tr><td>채점기준</td><td>분석이 정확함</td><td>배점</td><td>20</td></tr></table>
"""
    bounded = [
        item
        for item in parse_assessment_section(source, "통합과학1").items
        if item.extraction_status == "bounded"
    ]

    assert len(bounded) == 1
    assert "분광기를 활용한" in bounded[0].title + bounded[0].overview


@pytest.mark.parametrize(
    "title",
    [
        "생명공학 기술과 인간생활",
        "물질과 규칙성(화학 결합)",
        "세포의 특성, 4. 유전자의 발현과 조절",
        "생명과학의 역사 세포의 특성",
        "I ~III 단원",
        "수행영역2",
        "평가과제3",
        "5월 4주",
        "총 1회",
        "통합과학B",
        "중 (25∼20점)",
        "관찰법",
        "선다형",
        "1학기 수행평가 시행 계획 및 세부 채점 기준",
        "결과의 활용",
        "수행평가 세부 계획에 따름",
        "하단의 ‘Ⅲ. 수행평가 영역명’ 참고",
        "2차 시험(중간시험)",
        "실험 보고서의 체계적 작성 정도",
        "학습 참여도",
        "(1) 주제 선정하기",
        "1단계 탐구 계획 세우기",
        "지도교사: 홍길동",
        "주기율표 탐험. 2) 이온 결합의 세계",
        "성취기준에 기반한 일관성 있는 평가",
    ],
)
def test_plan_labels_units_steps_and_policy_lines_are_not_task_names(title: str) -> None:
    from scripts.biology_assessment_detail_parser import _not_a_task_name, strip_title_decoration

    assert _not_a_task_name(strip_title_decoration(title)), title


@pytest.mark.parametrize(
    "title",
    [
        "생활 속의 과학 탐구",
        "서술형 평가",
        "과학의 본성 탐구",
        "학생 선택형 융합 탐구 프로젝트",
        "GMO의 유전공학적 원리와 생명공학적 활용",
        "서술형평가: 수소와 헬륨, 그들은 어디에서 왔는가?",
        "탐구 보고서 1",
        "포트폴리오",
        "세포막을 통한 물질의 이동 실험",
    ],
)
def test_task_names_that_look_like_labels_are_kept(title: str) -> None:
    from scripts.biology_assessment_detail_parser import _not_a_task_name, strip_title_decoration

    assert not _not_a_task_name(strip_title_decoration(title)), title


def test_another_course_opens_on_its_title_line_whatever_its_level() -> None:
    from scripts.biology_assessment_detail_parser import _line_opens_other_course

    targets = ("통합과학1", "통합과학I")
    for line in (
        "2026학년도 1학기 3학년 체육전공 실기기초 교수·학습 및 평가 운영 계획",
        "## 2026학년도 2학년 1학기 [일본어회화] 교과 공주영명고등학교",
        "## 1 체육1 교수학습-평가 계획 및 방법",
        "Ⅰ ( 지구과학Ⅱ )과 교수학습 계획서",
        "[zip:양서고 1학년 논리와사고 교수학습 계획서.pdf][ok]",
        "<tr><th colspan=\"3\">2026학년도 1학기 진로와 직업과 평가 계획서</th></tr>",
    ):
        assert _line_opens_other_course(line, targets), line
    for line in (
        "2026학년도 1학기 [통합과학] 교수학습 및 평가 운영 계획",
        "2026학년도 1학기 교수학습 및 평가 운영 계획",
        "## 1 성취기준별 교수학습-평가 방법",
        "6. 범교과 주제 및 사회정서교육 교수학습 운영 계획",
        "1 ( 과학과 )과 교수학습-평가 방법",
        "( 통합과학-물리 ) 과 교수학습-평가 방법",
        "2026학년도 교수학습 및 평가 계획에 따라 출제한다.",
        "<tr><td>학습내용</td><td>성취기준</td><td>교수·학습<br>방법</td></tr>",
        "[zip:과학_2-1. 2026학년도 1학기 과학과 평가계획_0318제출.xlsx][ok]",
    ):
        assert not _line_opens_other_course(line, targets), line


def test_one_task_spelled_two_ways_but_not_two_tasks_alike() -> None:
    from scripts.biology_assessment_detail_parser import _same_task_named

    assert _same_task_named("충격을 줄이는 안정장치 고안하기", "충격을 줄이는 안전장치 고안하기")
    assert _same_task_named("원소의 주기성", "원소의 주기성 탐구")
    assert _same_task_named("3순위:과학 주제탐구 보고서 작성하기", "과학 주제탐구 보고서 작성하기")
    assert not _same_task_named("식물 세포 관찰 실험", "동물 세포 관찰 실험")
    assert not _same_task_named("탐구 보고서 1", "탐구 보고서 2")
    assert not _same_task_named("스스로 만드는 과학노트Ⅰ", "스스로 만드는 과학노트Ⅱ")
    assert not _same_task_named("생명과학 포트폴리오", "생명과학 독서 포트폴리오")
    assert not _same_task_named("카드뉴스 제작", "카드뉴스 제작 후속 탐구 보고서")


def test_a_reviewed_title_is_demoted_not_dropped() -> None:
    from scripts import build_biology_assessment_publish_db as build
    from scripts.biology_assessment_detail_parser import ParsedAssessmentItem

    item = ParsedAssessmentItem(
        order=1, title="실험 수행", title_raw="실험 수행", title_basis="table",
        extraction_status="bounded", source_start=0, source_end=1, source_markdown="",
        source_html="", rubric_html="", overview="", method="", timing="", score="",
        weight="", standards=(),
    )
    build._title_review.cache_clear()
    original = build.TITLE_REVIEW_PATH
    try:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            review = Path(folder) / "title_review.csv"
            review.write_text(
                "case_id,title,class,note,fixed_name\n"
                "case-1,실험 수행,SUBITEM,단계,\n"
                "case-3,실험 수행,RENAME,이름 칸,효소 실험\n",
                encoding="utf-8",
            )
            build.TITLE_REVIEW_PATH = review
            build._title_review.cache_clear()
            demoted = build._apply_title_review("case-1", (item,))
            untouched = build._apply_title_review("case-2", (item,))
            renamed = build._apply_title_review("case-3", (item,))
    finally:
        build.TITLE_REVIEW_PATH = original
        build._title_review.cache_clear()

    assert demoted[0].extraction_status == "bundle_review"
    assert untouched[0].extraction_status == "bounded"
    assert (renamed[0].title, renamed[0].overview) == ("효소 실험", "실험 수행")


def test_teacher_names_after_a_role_title_are_masked_and_nothing_else() -> None:
    from scripts.mask_teacher_names import mask_teacher_names, teacher_names_left

    # 이름은 지어낸 것이다.
    text = (
        "지도교사: 홍길동, 김철수 | 평가교사 이영희 | 공동 채점교사 : 윤서하, 김은정 | "
        "<td>교과담당교사</td><td>최가람</td> | 담당교사 전원이 공동 출제 | "
        "교사: 학생 간의 상호작용을 관찰 | 지도교사 허가 절차"
    )
    masked = mask_teacher_names(text)

    for name in ("홍길동", "김철수", "이영희", "윤서하", "김은정", "최가람"):
        assert name not in masked
    assert "담당교사 전원이" in masked
    assert "교사: 학생 간의 상호작용을 관찰" in masked
    assert "지도교사 허가 절차" in masked
    assert teacher_names_left(text) and not teacher_names_left(masked)


def test_teacher_names_in_a_teacher_column_or_row_are_masked() -> None:
    from scripts.mask_teacher_names import mask_teacher_names, teacher_names_left

    # 이름은 지어낸 것이다.
    cover = (
        "<table><tr><th>학교명</th><th>학년</th><th>지도교사</th></tr>"
        "<tr><td>○○고</td><td>3</td><td>홍길동, 김은정</td></tr></table>"
    )
    row = (
        "<table><tr><td>출제교사</td><td colspan=\"2\">김철수</td>"
        "<td colspan=\"3\">이영희/ 김철수</td></tr></table>"
    )
    plan = (
        "<table><tr><th>대상</th><th colspan=\"3\">담당 교사</th></tr>"
        "<tr><td>2</td><td colspan=\"3\">최가람, 장문수</td></tr>"
        "<tr><td>평가목표</td><td colspan=\"3\">자연 현상에 대한 탐구</td></tr></table>"
    )
    for table, names in (
        (cover, ("홍길동", "김은정")),
        (row, ("김철수", "이영희")),
        (plan, ("최가람", "장문수")),
    ):
        masked = mask_teacher_names(table)
        assert not any(name in masked for name in names)
        assert not teacher_names_left(masked)
    assert "자연 현상에 대한 탐구" in mask_teacher_names(plan)


def test_teacher_names_down_a_merged_column_and_in_flattened_tables_are_masked() -> None:
    from scripts.mask_teacher_names import mask_teacher_names, teacher_names_left

    # 이름은 지어낸 것이다. 과목 칸이 아래로 병합되고, 이미 가린 칸과
    # "홍길동(사)"처럼 과목 꼬리표가 붙은 이름이 섞인 표.
    merged = (
        "<table><tr><th>학년</th><th>과목</th><th>지도교사</th></tr>"
        "<tr><td rowspan=\"3\">1</td><td rowspan=\"2\">통합사회</td><td>○○○</td></tr>"
        "<tr><td>홍길동(사)</td></tr>"
        "<tr><td>한국사</td><td>김은정</td></tr></table>"
    )
    masked = mask_teacher_names(merged)
    assert "홍길동" not in masked and "김은정" not in masked
    assert "통합사회" in masked and "한국사" in masked
    assert not teacher_names_left(masked)

    # 사례 요약에는 표가 " · "(칸)와 " / "(행)로 풀려 있다.
    flat = (
        "대상 · 학기 · 주당 수업시수(학점) · 담당 교사 / 2 · 4 · 최가람, 장문수 / "
        "교과담당교사 · 이영희 · 대상 학년 · 3 / 담당교사 : / 윤서하 / "
        "학교명 · 학년 · 과목 · 지도교사 / ○○고 · 1학년 · 한국사 / "
        "대상 · 1학년 · 학점 · 1 · 담당 교사 · 김철수 / "
        "과목 유형 · 공통 · 석차 등급 · 없음 · 성취도 · 3단계 / "
        "학년 · 과목유형 · 담당 교사 · 교무부장 · 교장 / 담당교사 / 이수학점 · 4학점 · 편제 · 진로"
    )
    masked = mask_teacher_names(flat)
    for name in ("최가람", "장문수", "이영희", "윤서하", "김철수"):
        assert name not in masked
    for word in ("한국사", "성취도", "교무부장", "교장", "진로", "대상 학년"):
        assert word in masked
    assert teacher_names_left(flat) and not teacher_names_left(masked)
