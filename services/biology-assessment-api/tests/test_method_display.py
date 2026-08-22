"""평가 방법 칸을 읽는 규칙.

학교마다 HWP 서식이 달라 체크 표시가 ■ ☑ ▣ √ ∨ þ ✅ ⍌ ◼ ⟏ ▪ ü, "(√)", "□V"로
제각각 나오고, 빈칸도 □ ☐ ◻ 와 "( )", 홀로 선 o 로 나온다. 코퍼스에서 실제로
확인한 형태만 다룬다.
"""

import pytest

from app.repository import display_methods, normalize_method_boxes


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("□ 서술·논술 ☑ 실험･실습 □ 기타", ["실험･실습"]),
        ("□ 서술·논술 þ 구술·발표 □ 토의･토론 þ 포트폴리오", ["구술·발표", "포트폴리오"]),
        ("▣ 서술·논술 · □ 구술·발표 · □ 토의･토론", ["서술·논술"]),
        ("∨서술·논술 · □ 구술·발표 · □ 토의·토론", ["서술·논술"]),
        ("(√)논술 ( )구술 발표 (√)프로젝트", ["논술", "프로젝트"]),
        ("☐ 논술 ✅ 구술‧발표 ✅ 토의‧토론 □ 프로젝트", ["구술‧발표", "토의‧토론"]),
        ("■ 서술･논술 ■ 구술･발표 o 토의･토론 o 포트폴리오", ["서술･논술", "구술･발표"]),
        ("◼ 서술·논술 □ 구술·발표 ◼ 프로젝트", ["서술·논술", "프로젝트"]),
        # 표시가 하나도 없는 평범한 목록은 학교가 적어 넣은 값이라 그대로 둔다.
        ("보고서, 프로젝트", ["보고서, 프로젝트"]),
    ],
)
def test_only_the_ticked_options_are_published(cell: str, expected: list[str]) -> None:
    assert display_methods([cell]) == expected


def test_a_menu_with_nothing_ticked_publishes_nothing() -> None:
    # 전부 빈칸이면 학교가 고르지 않았거나 표시가 추출에서 유실된 것이다.
    # 메뉴 전체를 내보내면 모든 방법을 선택한 것처럼 보인다.
    assert display_methods(["□ 서술·논술 · □ 구술·발표 · □ 토의·토론"]) == []


def test_text_before_the_first_box_keeps_its_option() -> None:
    # "교사 관찰 및 기록"의 표시만 유실된 모양이라, 앞부분은 살린다.
    assert display_methods(["교사 관찰 및 기록 ☐ 자기평가 ☐ 동료평가"]) == ["교사 관찰 및 기록"]


def test_normalisation_collapses_every_spelling_to_two_glyphs() -> None:
    normalised = normalize_method_boxes("■ 가 □ 나 þ 다 ☐ 라 (√) 마 ( ) 바")

    assert set(normalised) & {"■", "þ", "☐", "("} == set()
    assert normalised.count("☑") == 3
    assert normalised.count("□") == 3
