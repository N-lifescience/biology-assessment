"""Detect biology-scope subject mentions inside extracted assessment-plan text.

Unlike ``build_biology_assessment_manifest.ALIASES`` (which classifies one
filename into a single best label), this module scans a whole document body
and reports every distinct in-scope subject it finds, because one combined
plan can cover several courses (e.g. 통합과학1 and 생명과학 in the same file).

Bare-subject patterns intentionally require the collision suffix (Roman
numeral, arabic course-number digit, 실험, or a 고급 prefix) to be *directly*
attached with no space before excluding it. A real teacher-written 학기
mention ("생명과학 1학기") always has a space or an unrelated token in
between, so it never trips the exclusion; only the attached course-number
form ("생명과학1", no space) does. Verified empirically against
data/source/all_subject_evidence_v2_source.jsonl: no case of a digit
immediately followed by "학기" exists in the corpus, and the attached-digit
course-number form is real and common (예: 통합과학1 13104 hits, 생명과학2 259
hits).
"""

from __future__ import annotations

import re
from typing import Any

_LIFE = r"생명\s*과학"
_INTEGRATED = r"통합\s*과학"
_SCI_INQUIRY = r"과학\s*탐구\s*실험"

# Roman Ⅰ and Latin "II" must be tried as their own literal alternatives
# rather than folded into a character class: a naive [ⅠⅡI12] class lets a
# lone Latin "I" match inside "II", mislabelling a Ⅱ course as Ⅰ.
#
# The Roman/Latin marker may be preceded by whitespace (extraction noise),
# but the arabic digit may not: a space before the digit means "생명과학
# 1학기" (semester marker), not the "생명과학1" attached course-number form.
_ROMAN1 = r"(?:\s*Ⅰ|\s*I(?!I))"
_ROMAN2 = r"(?:\s*Ⅱ|\s*II)"
_DIGIT1 = r"1(?!\d)"
_DIGIT2 = r"2(?!\d)"
_NUM1 = rf"(?:{_ROMAN1}|{_DIGIT1})"
_NUM2 = rf"(?:{_ROMAN2}|{_DIGIT2})"
_NOT_NUM1 = rf"(?!{_ROMAN1})(?!{_DIGIT1})"
_NOT_NUM2 = rf"(?!{_ROMAN2})(?!{_DIGIT2})"

SUBJECT_PATTERNS: list[tuple[Any, str, str]] = [
    ("2015", "통합과학", rf"{_INTEGRATED}{_NOT_NUM1}{_NOT_NUM2}"),
    ("2015", "과학탐구실험", rf"{_SCI_INQUIRY}{_NOT_NUM1}{_NOT_NUM2}"),
    ("2015", "생명과학Ⅰ", rf"{_LIFE}{_NUM1}"),
    ("2015", "생명과학Ⅱ", rf"{_LIFE}{_NUM2}"),
    ("2022", "통합과학1", rf"{_INTEGRATED}{_DIGIT1}"),
    ("2022", "과학탐구실험1", rf"{_SCI_INQUIRY}{_DIGIT1}"),
    (
        "2022",
        "생명과학",
        rf"(?<!고급)(?<!고급\s){_LIFE}{_NOT_NUM1}{_NOT_NUM2}(?!\s*실험)",
    ),
    ("specialized", "생명과학실험", rf"{_LIFE}\s*실험"),
    ("specialized", "고급생명과학", rf"고급\s*{_LIFE}"),
]


def subject_hits(text: str) -> list[dict[str, str]]:
    """Return one {subject, curriculum_hint} dict per in-scope subject present."""
    hits: list[dict[str, str]] = []
    for curriculum_hint, subject, pattern in SUBJECT_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append({"subject": subject, "curriculum_hint": curriculum_hint})
    return hits


if __name__ == "__main__":
    # ponytail: smallest runnable check, not a full test suite.
    cases: list[tuple[str, set[str]]] = [
        ("2026학년도 1학기 [통합과학1] 교수학습 및 평가 운영 계획", {"통합과학1"}),
        ("통합과학1 과목 성취도는 단위학교 분할점수로 산출한다", {"통합과학1"}),
        ("‘통합과학1’과 ‘통합과학2’의 교수 목표 도달 여부", {"통합과학1"}),
        ("2026학년도 1학기 2학년 [생명과학II] 교수학습 및 평가운영계획", {"생명과학Ⅱ"}),
        ("생명과학1에서 배운 개념을 연상하도록", {"생명과학Ⅰ"}),
        ("생명과학Ⅰ 교수학습 및 평가 계획", {"생명과학Ⅰ"}),
        ("생명과학 1학기 수행평가 계획", {"생명과학"}),
        ("2026학년도 범서고 1학기 소인수 (생명과학실험)", {"생명과학실험"}),
        ("2026학년도-부산진여고-[고급생명과학]-교수학습및평가운영계획", {"고급생명과학"}),
        ("2026학년도 1학기 [과학탐구실험1] 교수학습 및 평가 운영 계획", {"과학탐구실험1"}),
        ("과학탐구실험2 교수학습 운영 계획", set()),
        ("통합과학2 교육과정 성취기준을 고려하여", set()),
        (
            "생명과학Ⅰ과 생명과학Ⅱ, 생명과학, 생명과학실험, 고급생명과학을 모두 개설한다",
            {"생명과학Ⅰ", "생명과학Ⅱ", "생명과학", "생명과학실험", "고급생명과학"},
        ),
    ]
    failures = 0
    for text, expected in cases:
        found = {hit["subject"] for hit in subject_hits(text)}
        if found != expected:
            failures += 1
            print(f"FAIL: {text!r}\n  expected={expected} got={found}")
    if failures:
        raise SystemExit(f"{failures} case(s) failed")
    print(f"ok {len(cases)} cases")
