"""Self-checks for the biology subject scope: filename aliases and curriculum buckets.

Run with ``py -3 scripts/test_biology_assessment_scope.py`` or under pytest.
"""

from __future__ import annotations

import build_biology_assessment_manifest as manifest
import build_school_subject_assessment_catalog as catalog


def test_roman_and_latin_course_numerals_do_not_swap() -> None:
    for name in ("생명과학1", "생명과학I", "생명과학Ⅰ"):
        assert manifest.classify(f"{name} 평가계획.hwp")[1] == "생명과학Ⅰ", name
    for name in ("생명과학2", "생명과학II", "생명과학Ⅱ"):
        assert manifest.classify(f"{name} 평가계획.hwp")[1] == "생명과학Ⅱ", name


def test_specific_alias_wins_over_generic() -> None:
    expected = {
        "고급생명과학": "고급생명과학",
        "생명과학실험": "생명과학실험",
        "생명과학": "생명과학",
        "과학탐구실험1": "과학탐구실험1",
        "과학탐구실험": "과학탐구실험",
        "통합과학1": "통합과학1",
        "통합과학": "통합과학",
        # Outside the published scope: falls through to the generic bucket
        # rather than being mislabelled as the 2015 single-course 통합과학.
        "통합과학2": "과학",
    }
    for name, canonical in expected.items():
        assert manifest.classify(f"{name} 평가계획.hwp")[1] == canonical, name
    assert manifest.classify("화학Ⅰ 평가계획.hwp")[1] == "unknown"


def test_manifest_canonicals_agree_with_catalog_subjects() -> None:
    emitted = {
        manifest.classify(f"{subject} 평가계획.hwp")[1]
        for names in catalog.SUBJECTS.values()
        for subject in names
    }
    assert emitted == {s for names in catalog.SUBJECTS.values() for s in names}


def test_specialized_bucket_is_not_forced_into_a_revision() -> None:
    assert set(catalog.SUBJECTS) == {"2015", "2022", "specialized"}
    # No biology subject is carried by two buckets, so nothing is ambiguous.
    assert catalog.SHARED_SUBJECTS == set()
    for subject in catalog.SUBJECTS["specialized"]:
        resolved, basis = catalog.resolve_curriculum({"subject": subject}, [2026], [1])
        assert (resolved, basis) == ("specialized", "subject_unique_to_curriculum"), subject
    assert catalog.resolve_curriculum({"subject": "생명과학Ⅰ"}, [], [])[0] == "2015"
    assert catalog.resolve_curriculum({"subject": "생명과학"}, [], [])[0] == "2022"
    assert catalog.resolve_curriculum({"subject": "화학Ⅰ"}, [], [])[0] == "shared"


if __name__ == "__main__":
    for name, case in sorted(globals().items()):
        if name.startswith("test_"):
            case()
            print(f"ok {name}")
