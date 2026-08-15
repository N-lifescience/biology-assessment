# TODO(biology-fork): 이 파일은 scripts/의 생명과학 파이프라인 규칙(과제명 정규화·제목 감사·상세 파서)을
# 검증한다. 픽스처와 기대값이 아직 수학 규칙 그대로다. scripts/ 재작성이 끝난 뒤
# 생명과학 과제명·과목 표현으로 다시 작성한다. 통과시키려고 규칙을 느슨하게 바꾸지 않는다.

from scripts.audit_unresolved_biology_assessment_titles import (
    TITLE_FRAGMENT_RE,
    explicit_name_label,
)
from scripts.promote_recovered_biology_assessment_titles import candidates_by_case


def test_assessment_task_field_is_an_explicit_title_field() -> None:
    """2022 plan tables use 평가 과제 for the original task name."""

    assert explicit_name_label("평가 과제")
    assert explicit_name_label("평가과제")
    # A long 수행 과제 cell frequently describes directions, not the title.
    assert not explicit_name_label("수행 과제")
    assert TITLE_FRAGMENT_RE.fullmatch("・포트폴리오")


def test_title_recovery_promotes_only_direct_source_verified_titles() -> None:
    audit = {
        "candidates": [
            {
                "case_id": "case-1",
                "candidate": "실생활 함수 모델링 보고서",
                "confidence": "high",
                "detection": "table_row",
                "subject_alignment": "expected",
                "explicit_name_label": True,
                "title_looks_complete": True,
                "other_subject_signal": False,
            },
            {
                "case_id": "case-1",
                "candidate": "실생활 함수 모델링 보고서",
                "confidence": "high",
                "detection": "table_row",
                "subject_alignment": "expected",
                "explicit_name_label": True,
                "title_looks_complete": True,
                "other_subject_signal": False,
            },
            {
                "case_id": "case-2",
                "candidate": "문학 비평문 작성",
                "confidence": "high",
                "detection": "table_row",
                "subject_alignment": "expected",
                "explicit_name_label": True,
                "title_looks_complete": True,
                "other_subject_signal": True,
            },
            {
                "case_id": "case-3",
                "candidate": "수행평가 원문 구간",
                "confidence": "high",
                "detection": "table_row",
                "subject_alignment": "expected",
                "explicit_name_label": True,
                "title_looks_complete": True,
                "other_subject_signal": False,
            },
            {
                "case_id": "case-4",
                "candidate": "표가 무너진 후보",
                "confidence": "review",
                "detection": "flattened_line",
                "subject_alignment": "unknown",
                "explicit_name_label": False,
                "title_looks_complete": False,
                "other_subject_signal": False,
            },
        ]
    }

    selected, skipped = candidates_by_case(audit)

    assert selected == {"case-1": ["실생활 함수 모델링 보고서"]}
    assert skipped == {
        "missing_case_or_title": 1,
        "not_source_verified_high": 1,
        "other_subject_signal": 1,
    }
