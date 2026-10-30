"""kordoc 블록을 파서가 읽는 평평한 흐름으로 바꾸는 규칙.

블록 모양은 실제 학교 계획서를 kordoc 4.24.25로 읽은 결과를 줄여 옮겼다.
kordoc 의 ``table.cells`` 는 덮인 칸까지 빈 자리로 채운 완전 격자다.
"""

from scripts.kordoc_flow import anchor_rows, clean_text, flatten_blocks, flow_text


def cell(text="", rowspan=1, colspan=1, blocks=None, header=False):
    value = {"text": text, "rowSpan": rowspan, "colSpan": colspan}
    if blocks is not None:
        value["blocks"] = blocks
    if header:
        value["isHeader"] = True
    return value


def table(cells, classification=None, has_header=True):
    value = {"rows": len(cells), "cols": len(cells[0]), "cells": cells, "hasHeader": has_header}
    if classification:
        value["classification"] = classification
    return {"type": "table", "table": value}


def para(text):
    return {"type": "paragraph", "text": text}


RUBRIC = table([
    [cell("평가 요소", rowspan=2), cell("채점 기준", colspan=2), cell(""), cell("배점")],
    [cell(""), cell("수준"), cell("내용"), cell("100점")],
    [
        cell("보고서 작성\n(30점)", rowspan=2), cell("A"),
        cell("모든 항목을 구체적으로 작성함"), cell("30"),
    ],
    [cell(""), cell("B"), cell("누락된 부분이 1~2개 있음"), cell("28")],
])


def test_covered_placeholders_are_not_cells() -> None:
    rows = anchor_rows(RUBRIC["table"])

    assert [[c["text"] for _, _, c in row] for row in rows] == [
        ["평가 요소", "채점 기준", "배점"],
        ["수준", "내용", "100점"],
        ["보고서 작성\n(30점)", "A", "모든 항목을 구체적으로 작성함", "30"],
        ["B", "누락된 부분이 1~2개 있음", "28"],
    ]


def test_a_data_table_keeps_its_spans_and_rows() -> None:
    text = flow_text(flatten_blocks([RUBRIC]))

    assert text.count("<table>") == 1
    assert '<th rowspan="2">평가 요소</th><th colspan="2">채점 기준</th><th>배점</th>' in text
    assert "<tr><td>B</td><td>누락된 부분이 1~2개 있음</td><td>28</td></tr>" in text
    assert "<td rowspan=\"2\">보고서 작성<br>(30점)</td>" in text


def test_a_whole_plan_typed_inside_one_frame_is_unwrapped() -> None:
    # 경남 한 학교: 문서 전체가 1×1 틀 안에 있고 그 안에 문단과 표가 있다.
    frame = table(
        [[cell(blocks=[para("5. 수행평가 세부 계획"), RUBRIC, para("6. 평가 유의사항")])]],
        classification={"kind": "non-tabular-layout", "reasons": ["nested-structure-wrapper"]},
        has_header=False,
    )

    text = flow_text(flatten_blocks([frame]))

    assert text.splitlines()[0] == "5. 수행평가 세부 계획"
    assert text.count("<table>") == 1
    assert "<table><tr><td><table>" not in text.replace("\n", "")
    assert text.rstrip().endswith("6. 평가 유의사항")


def test_a_label_beside_a_nested_rubric_becomes_its_heading() -> None:
    # 부산 PDF: "평가방법\n및\n채점기준" 칸 옆 칸에 진짜 루브릭 표가 들어 있다.
    frame = table(
        [[
            cell("평가방법\n및\n채점기준"),
            cell(blocks=[para("1. 다음 항목으로 평가한다."), RUBRIC]),
        ]],
        classification={"kind": "uncertain", "reasons": ["low-evidence"]},
    )

    nodes = flatten_blocks([frame])

    assert (nodes[0].kind, nodes[0].text) == ("heading", "평가방법 및 채점기준")
    assert [node.kind for node in nodes[1:]] == ["para", "table"]


def test_a_one_row_section_box_is_a_heading() -> None:
    box = table([[cell("Ⅲ"), cell(""), cell("수행 평가 세부 계획")]], has_header=False)

    assert flow_text(flatten_blocks([box])) == "## Ⅲ 수행 평가 세부 계획"


def test_a_one_row_data_table_is_not_mistaken_for_a_heading() -> None:
    row = table([[cell("유의사항"), cell("표절 시 0점 처리")]], has_header=False)

    assert flow_text(flatten_blocks([row])).startswith("<table>")


def test_a_small_menu_inside_a_data_cell_is_written_as_text_rows() -> None:
    menu = table([
        [cell("□V 서술·논술"), cell("□ 구술·발표")],
        [cell("□ 실험･실습"), cell("□V 포트폴리오")],
    ], has_header=False)
    item = table([
        [cell("평가 과제"), cell("생태 지도 만들기")],
        [cell("성취기준"), cell("[12생과05-01] 생태계 구성 요소를 설명한다.")],
        [cell("평가 방법"), cell(blocks=[menu])],
        [cell("채점 기준"), cell("관찰 기록 6종 이상 30점, 3종 이하 10점")],
    ])

    text = flow_text(flatten_blocks([item]))

    assert text.count("<table>") == 1
    assert "<td>☑ 서술·논술 | □ 구술·발표<br>□ 실험･실습 | ☑ 포트폴리오</td>" in text


def test_a_box_overlaid_with_a_check_mark_reads_as_ticked() -> None:
    assert clean_text("□V 교사 관찰 및 기록 □ 자기평가 □√ 동료평가") == (
        "☑ 교사 관찰 및 기록 □ 자기평가 ☑ 동료평가"
    )
    assert clean_text("배점 \\$10") == "배점 $10"


def test_a_title_box_broken_over_lines_is_one_heading() -> None:
    # 경기 산본고: 1×1 상자 안 제목이 두 줄로 나뉘어 있다.
    box = table(
        [[cell("2026학년도 1학기 3학년 생명과학II과 교수ㆍ학습 및\n평가 운영 계획")]],
        has_header=False,
    )

    nodes = flatten_blocks([box])

    assert [node.kind for node in nodes] == ["heading"]
    assert nodes[0].text == "2026학년도 1학기 3학년 생명과학II과 교수ㆍ학습 및 평가 운영 계획"


def test_a_rubric_inside_a_task_table_follows_it_and_the_task_table_stays() -> None:
    # 대전고: 과제 표의 "평가 기준" 행 칸에 루브릭 표가 통째로 들어 있다.
    rubric = table([
        [cell("평가요소"), cell("채점 기준"), cell("배점")],
        [cell("사전 보고서", rowspan=4), cell("3가지 준거를 모두 만족함"), cell("10점")],
        [cell(""), cell("2가지 준거만을 만족함"), cell("8점")],
        [cell(""), cell("1가지 준거만을 만족함"), cell("6점")],
        [cell(""), cell("실시하지 않음"), cell("4점")],
    ])
    menu = table([[cell("□ 서‧논술형"), cell("□V 실험‧실습")]], has_header=False)
    task = table([
        [cell("평가영역1"), cell("광합성 탐구 실험", colspan=3), cell(""), cell("")],
        [cell("반영비율"), cell("30%"), cell("만점 점수"), cell("30점")],
        [cell("평가유형"), cell(blocks=[menu], colspan=3), cell(""), cell("")],
        [cell("평가 기준"), cell(blocks=[rubric], colspan=3), cell(""), cell("")],
    ])

    nodes = flatten_blocks([task])

    assert [node.kind for node in nodes] == ["table", "para", "table"]
    task_text = flow_text(nodes[:1])
    assert "<td>평가영역1</td>" in task_text or "<th>평가영역1</th>" in task_text
    assert "<td>반영비율</td><td>30%</td><td>만점 점수</td><td>30점</td>" in task_text
    assert "□ 서‧논술형 | ☑ 실험‧실습" in task_text
    assert nodes[1].text == "평가 기준"
    assert "<td>2가지 준거만을 만족함</td><td>8점</td>" in flow_text(nodes[2:])


def test_a_frame_with_one_dominant_cell_is_unwrapped() -> None:
    # 인천 부개고: 제목 행, 지도교사 행, 계획서 전체가 든 칸 하나.
    body = [para("5. 수행평가 세부 계획"), para("1) 수행평가명: 과제 연구"), RUBRIC]
    frame = table([
        [cell("2026학년도 2학년 1학기 ( 생명과학실험 ) 평가 계획", colspan=3), cell(""), cell("")],
        [cell(""), cell("지도교사 :"), cell("주OO")],
        [
            cell(blocks=[*body, para("가. 평가 결과를 누가 기록하여 성장 수준을 파악한다." * 3)],
                 colspan=3),
            cell(""), cell(""),
        ],
    ])

    text = flow_text(flatten_blocks([frame]))

    assert "1) 수행평가명: 과제 연구\n\n<table>" in text
    assert text.count("<table>") == 1
