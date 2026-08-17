import pytest
from scripts.audit_biology_assessment_titles_full import audit_flags, confidence


@pytest.mark.parametrize(
    "title",
    [
        "생태계와 개체군 사이의 상호작용을 예시를 들어 설명하기",
        "생태 조사 결과를 그래프로 구조화하기",
        "생명과학 주제 탐구 발표",
        "생명과학 용어 탐구 보고서 (2)",
        "주제 선정 및 관찰 계획서 작성",
    ],
)
def test_source_grounded_task_titles_are_supported(title: str) -> None:
    assert confidence(audit_flags(title, "table"), "table") == "supported"


@pytest.mark.parametrize(
    "title",
    [
        "탐구 과정이 적절한가?",
        "평가 항목을 만족하는 포트폴리오가 7 ~ 8쪽",
        "탐구설계",
        "보고서 작성 (50)",
        "논·서술형, 포트폴리오, 교사 관찰 및 기록",
    ],
)
def test_rubric_rows_are_not_supported_as_task_titles(title: str) -> None:
    assert confidence(audit_flags(title, "table"), "table") == "reject"


def test_unit_name_without_a_task_signal_requires_review() -> None:
    assert confidence(audit_flags("광합성", "table"), "table") == "review"


def test_exact_explicit_source_label_can_confirm_a_short_official_name() -> None:
    flags = audit_flags("광합성", "table")
    assert (
        confidence(flags, "table", explicit_source_label=True) == "supported"
    )


@pytest.mark.parametrize("title", ["영역별", "보고서 작성 (50)"])
def test_explicit_source_label_does_not_override_hard_rejections(title: str) -> None:
    flags = audit_flags(title, "table")
    assert confidence(flags, "table", explicit_source_label=True) == "reject"


@pytest.mark.parametrize(
    "title",
    [
        "평소",
        "단원",
        "수준",
        "점수(점)",
        "정기1차시험",
        "중간",
        "기말",
        "학습",
        "직무",
        "수행평가",
        "II",
        "생명과학Ⅱ 전체",
    ],
)
def test_field_values_and_period_labels_cannot_be_confirmed_as_titles(title: str) -> None:
    flags = audit_flags(title, "table")
    assert confidence(flags, "table", explicit_source_label=True) == "reject"


def test_another_subjects_assessment_title_is_rejected() -> None:
    flags = audit_flags("기본권 쟁점 파악", "table")
    assert confidence(flags, "table", explicit_source_label=True) == "reject"


def test_exact_task_dimension_is_allowed_only_with_an_explicit_source_label() -> None:
    flags = audit_flags("탐구 주제 선정", "table")
    assert confidence(flags, "table") == "reject"
    assert confidence(flags, "table", explicit_source_label=True) == "supported"
