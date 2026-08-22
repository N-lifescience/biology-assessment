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
    balance_table_tags,
    heading_title_is_structural,
    markdown_fragment_to_html,
    normalize_checkbox_glyphs,
    parse_assessment_section,
    segment_subject_alignment,
    visible_text,
)


def test_subject_code_alignment_does_not_confuse_math_one_and_two() -> None:
    math_two = "<table><tr><td>[12생과Ⅱ01-04] 연속함수의 성질</td></tr></table>"
    math_one = "<table><tr><td>[12생과Ⅰ01-01] 지수함수와 로그함수</td></tr></table>"

    assert segment_subject_alignment(math_two, "생명과학Ⅰ") == "other"
    assert segment_subject_alignment(math_two, "생명과학Ⅱ") == "expected"
    assert segment_subject_alignment(math_one, "생명과학Ⅰ") == "expected"
    assert segment_subject_alignment(math_one, "생명과학Ⅱ") == "other"


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
            "이차곡선의 활용 탐구보고서(논술형)",
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
    ],
)
def test_policy_and_standard_headings_are_structural(title: str) -> None:
    assert heading_title_is_structural(title)


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


def test_page_break_split_table_is_rendered_as_one_table() -> None:
    """A source page break can close a <table> mid-rowspan and reopen a new
    <table> for the remaining rows. Nothing legitimate separates two tables
    by blank lines alone, so the renderer fuses them back into one table."""

    fragment = """<table>
<tr><th>평가 영역명</th><th>혈액형 판정[논술형]</th></tr>
<tr><td rowspan="5">[12생과02-05] 병원체</td><td>A</td></tr>
</table>

<table>
<tr><th>체 반응의 특이성을 이해</th><th>반응의 특이성에 대해</th></tr>
<tr><td>B</td><td>혈액 응집 반응의 원리</td></tr>
</table>
"""

    rendered = markdown_fragment_to_html(fragment)

    assert rendered.count("<table") == rendered.count("</table>") == 1
    assert "체 반응의 특이성을 이해" in rendered


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
