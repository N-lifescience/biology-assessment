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

통합과학 and 과학탐구실험 are the exception: 2026 plans print the 2022 course
"통합과학 1" and "과학탐구실험Ⅰ", and shorten it to "[과학탐구실험]" in headings.
There a spaced digit without a unit after it is the course number, and the
bare name counts as 2015 only when the document shows no 2022 course of that
family (name or "[10과탐1-…]" code).
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

# The 2022 통합과학·과학탐구실험 courses are also printed "통합과학 1" and
# "과학탐구실험Ⅰ" (2026 1학년 plans).  A spaced digit followed by a unit is a
# semester or grade ("통합과학 1학기"), not the course number.
_UNIT_AFTER = (
    r"\s*(?:학기|학년|학점|단위|차시|차|단원|회|번|명|점|월|주|시간|교시|반|개|부|장|절|%"
    r"|[.,]\d)"
)
_COURSE1 = rf"(?:{_ROMAN1}|{_DIGIT1}|\s+{_DIGIT1}(?!{_UNIT_AFTER}))"
_COURSE2 = rf"(?:{_ROMAN2}|{_DIGIT2}|\s+{_DIGIT2}(?!{_UNIT_AFTER}))"
_NOT_COURSE = rf"(?!{_COURSE1})(?!{_COURSE2})"

SUBJECT_PATTERNS: list[tuple[Any, str, str]] = [
    ("2015", "통합과학", rf"{_INTEGRATED}{_NOT_COURSE}"),
    ("2015", "과학탐구실험", rf"{_SCI_INQUIRY}{_NOT_COURSE}"),
    ("2015", "생명과학Ⅰ", rf"{_LIFE}{_NUM1}"),
    ("2015", "생명과학Ⅱ", rf"{_LIFE}{_NUM2}"),
    ("2022", "통합과학1", rf"{_INTEGRATED}{_COURSE1}"),
    ("2022", "통합과학2", rf"{_INTEGRATED}{_COURSE2}"),
    ("2022", "과학탐구실험1", rf"{_SCI_INQUIRY}{_COURSE1}"),
    ("2022", "과학탐구실험2", rf"{_SCI_INQUIRY}{_COURSE2}"),
    (
        "2022",
        "생명과학",
        rf"(?<!고급)(?<!고급\s){_LIFE}{_NOT_NUM1}{_NOT_NUM2}(?!\s*실험)",
    ),
    # 2022 진로 선택.  2학년 2학기에 주로 개설된다.
    ("2022", "세포와 물질대사", r"세포\s*와\s*물질\s*대사"),
    ("2022", "생물의 유전", r"생물\s*의\s*유전"),
    ("specialized", "생명과학실험", rf"{_LIFE}\s*실험"),
    ("specialized", "고급생명과학", rf"고급\s*{_LIFE}"),
]


# A 2022 plan shortens its course to "[과학탐구실험]" or "( 통합과학 )과" in
# headings, so the bare 2015 name alone does not make a 2015 course.
NUMBERED_SUCCESSORS = {
    "통합과학": ("통합과학1", "통합과학2"),
    "과학탐구실험": ("과학탐구실험1", "과학탐구실험2"),
}
# 2022 성취기준 코드 "[10통과1-01-01]", "[10과탐2-02-03]", "[10통과Ⅰ01-02]".
# The 2015 shape is "[10통과01-01]"; schools copy it into 2022 plans, so it
# does not prove a 2015 course.
_NUMBERED_CODE_RE = re.compile(
    r"\[\s*10\s*(통과|과탐)\s*(?:([12])\s*(?:<br\s*/?>\s*)?-|([ⅠⅡ])\s*-?\s*\d)"
)
_CODE_COURSE = {"통과": "통합과학", "과탐": "과학탐구실험"}


def numbered_code_subjects(text: str) -> set[str]:
    """2022 numbered courses whose achievement codes appear in ``text``."""

    return {
        _CODE_COURSE[match.group(1)] + (match.group(2) or {"Ⅰ": "1", "Ⅱ": "2"}[match.group(3)])
        for match in _NUMBERED_CODE_RE.finditer(text)
    }


def mention_pattern(subject: str) -> str | None:
    """Regex for where ``subject`` is written, the short form of a 2022 course included.

    ``subject_hits`` already decided that a short "[과학탐구실험]" in this
    document is the numbered course, so the evidence around it counts.
    """

    spellings = mention_patterns(subject)
    if not spellings:
        return None
    if len(spellings) == 1:
        return spellings[0]
    return "(?:" + "|".join(spellings) + ")"


def mention_patterns(subject: str) -> list[str]:
    """Where ``subject`` is written, the most telling spelling first.

    "통합과학1" names the course; "통합과학 1" and "통합과학Ⅰ" also turn up in a
    whole-school table of contents ("# 6. 통합과학 1") or an appendix heading,
    and the short "[통합과학]" is shared by both numbered courses.  A caller
    looking for the plan itself takes the first spelling that occurs.
    """

    patterns = {name: pattern for _, name, pattern in SUBJECT_PATTERNS}
    if subject not in patterns:
        return []
    short = next(
        (bare for bare, numbered in NUMBERED_SUCCESSORS.items() if subject in numbered), None
    )
    if short is None:
        return [patterns[subject]]
    attached = (_INTEGRATED if short == "통합과학" else _SCI_INQUIRY) + (
        _DIGIT1 if subject.endswith("1") else _DIGIT2
    )
    return [attached, patterns[subject], patterns[short]]


def subject_hits(text: str) -> list[dict[str, str]]:
    """Return one {subject, curriculum_hint} dict per in-scope subject present."""
    found = {
        subject: curriculum_hint
        for curriculum_hint, subject, pattern in SUBJECT_PATTERNS
        if re.search(pattern, text, flags=re.IGNORECASE)
    }
    coded = numbered_code_subjects(text)
    for bare, numbered in NUMBERED_SUCCESSORS.items():
        if bare not in found or not (found.keys() | coded) & set(numbered):
            continue
        # The bare name is the numbered course written short; its codes say which.
        del found[bare]
        for subject in numbered:
            if subject in coded:
                found.setdefault(subject, "2022")
    return [
        {"subject": subject, "curriculum_hint": found[subject]}
        for _, subject, _ in SUBJECT_PATTERNS
        if subject in found
    ]


if __name__ == "__main__":
    # ponytail: smallest runnable check, not a full test suite.
    cases: list[tuple[str, set[str]]] = [
        ("2026학년도 1학기 [통합과학1] 교수학습 및 평가 운영 계획", {"통합과학1"}),
        ("통합과학1 과목 성취도는 단위학교 분할점수로 산출한다", {"통합과학1"}),
        ("‘통합과학1’과 ‘통합과학2’의 교수 목표 도달 여부", {"통합과학1", "통합과학2"}),
        ("2026학년도 1학기 2학년 [생명과학II] 교수학습 및 평가운영계획", {"생명과학Ⅱ"}),
        ("생명과학1에서 배운 개념을 연상하도록", {"생명과학Ⅰ"}),
        ("생명과학Ⅰ 교수학습 및 평가 계획", {"생명과학Ⅰ"}),
        ("생명과학 1학기 수행평가 계획", {"생명과학"}),
        ("2026학년도 범서고 1학기 소인수 (생명과학실험)", {"생명과학실험"}),
        ("2026학년도-부산진여고-[고급생명과학]-교수학습및평가운영계획", {"고급생명과학"}),
        ("2026학년도 1학기 [과학탐구실험1] 교수학습 및 평가 운영 계획", {"과학탐구실험1"}),
        ("과학탐구실험2 교수학습 운영 계획", {"과학탐구실험2"}),
        ("통합과학2 교육과정 성취기준을 고려하여", {"통합과학2"}),
        ("2026학년도 2학기 [세포와 물질대사] 교수학습 및 평가 운영 계획", {"세포와 물질대사"}),
        ("(세포와물질대사)과 수행 평가 계획", {"세포와 물질대사"}),
        ("2026학년도 2학년 생물의 유전 교수·학습 및 평가 계획", {"생물의 유전"}),
        ("통합과학 2학기 수행평가", {"통합과학"}),
        ("( 통합과학 1, 2 )과 교수학습 및 평가 계획", {"통합과학1"}),
        ("통합과학 1’에서는 물질과 규칙성을", {"통합과학1"}),
        ("[과학탐구실험Ⅰ]과 교수학습 및 평가 계획", {"과학탐구실험1"}),
        ("[ 과학탐구실험 ] 교수 학습 계획 | 과학탐구실험Ⅰ | 1학기", {"과학탐구실험1"}),
        ("[과학탐구실험]과 교수학습 [10과탐1-01-01] [10과탐1-02-03]", {"과학탐구실험1"}),
        ("[과학탐구실험]과목 교수학습 [10과탐2-01-02]", {"과학탐구실험2"}),
        (
            "( 과학탐구실험 )과 [10과탐1-02-01] [10과탐2<br>-01-01]",
            {"과학탐구실험1", "과학탐구실험2"},
        ),
        ("통합과학 교수학습 [10통과Ⅰ01-02]", {"통합과학1"}),
        ("통합과학과 평가 계획 [10통과01-01] [10통과-02-03]", {"통합과학"}),
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
