"""Which courses a plan document is filed under (case creation, before parsing).

The shapes are from 2026 1학년 plans that were filed only under the 2015
통합과학/과학탐구실험 and so never reached the site's 2022 course lists.
"""

import re

from scripts.biology_subject_aliases import (
    SUBJECT_PATTERNS,
    mention_pattern,
    numbered_code_subjects,
    subject_hits,
)


def _subjects(text: str) -> set[str]:
    return {hit["subject"] for hit in subject_hits(text)}


def test_spaced_and_roman_course_numbers_name_the_2022_course() -> None:
    assert _subjects("( 통합과학 1, 2 )과 교수학습 및 평가 계획") == {"통합과학1"}
    assert _subjects("‘통합과학 1’에서는 물질과 규칙성을") == {"통합과학1"}
    assert _subjects("[과학탐구실험Ⅰ]과 교수학습 및 평가 계획") == {"과학탐구실험1"}
    assert _subjects("과학탐구실험 II 평가 계획") == {"과학탐구실험2"}


def test_spaced_semester_or_grade_is_not_a_course_number() -> None:
    assert _subjects("통합과학 2학기 수행평가") == {"통합과학"}
    assert _subjects("과학탐구실험 1 학년 평가 계획") == {"과학탐구실험"}


def test_short_name_in_a_2022_plan_is_its_numbered_course() -> None:
    # 학익고: "(과학탐구실험) 과 교수학습" beside "| 과학탐구실험1 | 1학기".
    assert _subjects("(과학탐구실험) 과 교수학습 | 과학탐구실험1 | 1학기") == {"과학탐구실험1"}
    # 순심고·둔내고: only the short name, with 2022 codes.
    assert _subjects("[과학탐구실험]과 교수학습 [10과탐1-01-01] [10과탐1-02-03]") == {
        "과학탐구실험1"
    }
    assert _subjects("[과학탐구실험]과목 교수학습 [10과탐2-01-02]") == {"과학탐구실험2"}
    assert _subjects("( 과학탐구실험 )과 [10과탐1-02-01] [10과탐2<br>-01-01]") == {
        "과학탐구실험1",
        "과학탐구실험2",
    }
    assert _subjects("통합과학 교수학습 [10통과Ⅰ01-02]") == {"통합과학1"}


def test_2015_codes_alone_keep_the_2015_course() -> None:
    # 3학년(2015 교육과정) plans and 2025 2학년 plans.
    assert _subjects("통합과학과 평가 계획 [10통과01-01] [10통과-02-03] [10통과10-01]") == {
        "통합과학"
    }
    assert numbered_code_subjects("[10과탐01-01] [10과탐02-04] [10통과10-02]") == set()


def test_numbered_course_is_found_at_its_short_heading() -> None:
    pattern = mention_pattern("통합과학1")
    assert pattern is not None
    assert re.search(pattern, "# 통합과학\n\n수행평가 계획")
    assert re.search(pattern, "통합과학2 평가") is None
    # Other courses keep their own pattern.
    assert mention_pattern("생명과학Ⅱ") == dict(
        (name, pattern) for _, name, pattern in SUBJECT_PATTERNS
    )["생명과학Ⅱ"]
