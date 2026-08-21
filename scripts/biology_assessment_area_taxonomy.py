"""Classify a 수행평가 영역명 on the 주제(내용) × 방법 matrix.

Source of the taxonomy: 동국대학교 「수행평가 영역명 활용 가이드북」, 과학 교과
(pp. 12-13), which categorises published 영역명 into a topic axis and a method
axis and treats the pair as the unit a teacher designs with -- e.g.
「작용반작용 실험 및 보고서 작성하기」 reads as 운동과 힘 × 실험평가.

Two cautions carried from that document, which is why nothing here guesses:

* The guidebook analysed 물리/화학/지구과학 alongside 생명과학, so topic
  categories outside this project's 교과군 (전자기, 우주·천체 …) still occur
  here through 통합과학/과학탐구실험, but a 생명과학 plan should rarely land in
  them. They are kept rather than dropped so a wrong-looking classification is
  visible instead of silently folded into a biology topic.
* The guidebook's own word lists come from 2015 선택과목 and 2022 공통과목, so
  they can miss current wording. An unmatched 영역명 is reported as 미분류
  ("") -- the guidebook itself publishes a 미분류 row rather than forcing a
  category, and so do we.

Every category id here is also a published API/UI value, so ids are stable
even when a label is reworded.
"""

from __future__ import annotations

import re
import unicodedata

# (id, label, example words). The words are the guidebook's own 예시 단어 lists,
# kept verbatim so a reviewer can diff this file against page 13.
TOPIC_CATEGORIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("motion", "운동과 힘", (
        # "작용"/"법칙" are dropped from the guidebook's list: in a biology
        # corpus they match 효소의 작용, 방어 작용, 멘델의 법칙 far more often
        # than mechanics. "반작용" keeps the mechanics sense.
        "역학", "운동", "힘", "속도", "가속도", "반작용",
        "마찰", "낙하", "단진자", "충돌", "충격량", "운동량",
    )),
    ("wave", "빛과 파동", ("빛", "파동", "스펙트럼", "백색광", "굴절", "간섭")),
    ("electromagnetism", "전자기", (
        "에너지", "전기", "전류", "전압", "전력", "회로", "변환", "전자",
        "트랜지스터", "엔탈피", "반도체",
    )),
    ("matter", "물질의 구성", (
        # "구조"/"성질" dropped: 세포의 구조, 염색체 구조 dominate this corpus.
        "물질", "원자", "분자", "결합", "원소", "주기율표", "광물",
    )),
    ("reaction", "화학 반응", (
        # "변화" dropped: 기후 변화/개체수 변화 outnumber chemical change here.
        "화학", "반응", "산화", "환원", "산과 염기", "신소재", "화장품",
        "약품", "중화", "지시약", "용액", "산염기",
    )),
    ("cell", "세포와 물질대사", (
        "생명", "세포", "조직", "기관", "기능", "조절", "항상성", "효소", "생물",
        "식물", "동물", "세균", "광합성", "혈당", "호흡", "대사", "면역", "소화",
        "순환", "배설", "신경", "호르몬", "혈액", "막", "삼투", "발효",
        # 생명과학 교과군 어휘 보강: 가이드북 예시 단어는 2015 선택과목·2022
        # 공통과목 기준이라 이 코퍼스의 용어를 일부 놓친다(가이드북 각주 참고).
        "단백질", "아미노산", "미토콘드리아", "엽록체", "소기관", "atp", "확산",
        "항원", "항체", "백신", "병원체", "질병", "뉴런", "시냅스", "근수축",
        "자극", "감각", "인슐린", "체온", "물질대사", "생명시스템", "핵산합성",
    )),
    ("genetics", "유전", (
        # "정보" dropped: 자료·정보 is generic wording across every topic.
        "유전", "진화", "형질", "변이", "핵산", "DNA", "염색체", "생식세포",
        "돌연변이", "유전자", "분류", "계통",
        "감수분열", "체세포분열", "가계도", "유전병", "전사", "번역", "복제",
        "형질전환", "혈액형", "생명공학", "유전체", "rna",
    )),
    ("earth", "지구", (
        "지구", "기후", "대기", "해양", "판 경계", "관측", "지진", "지질", "판의 경계",
        "지권", "암석",
    )),
    ("space", "우주·천체", ("우주", "천체", "태양", "행성", "별", "은하")),
    ("environment", "환경", (
        "환경", "생태", "지속가능", "탄소중립", "미세먼지", "오염", "토양", "멸종",
        "외래종", "생물다양성", "생태계", "평형", "보호", "적정 기술", "군집", "개체군",
        "천이", "먹이사슬", "먹이그물", "물질순환", "에너지흐름", "방형구", "기후변화",
    )),
    ("history", "과학사", ("역사", "과학사", "발전", "과학자", "패러다임")),
    ("nos", "과학적 사고", (
        "과학의 본성", "과학적 탐구 방법", "귀납적", "연역적", "탐구 방법", "본성",
    )),
    ("ethics", "연구 윤리와 안전", (
        # "사고" dropped: it reads as both 안전사고 and 과학적 사고.
        "연구 윤리", "사회적 쟁점", "안전", "예방", "대처법", "안전장치",
        "생명윤리", "윤리",
    )),
    ("everyday", "실생활", ("실생활", "생활", "일상")),
    ("career", "진로", (
        "진로", "직업", "전공", "미래", "자유주제", "독서", "신문", "잡지", "기사",
        "도서", "독후",
    )),
    # "자료" alone is dropped: 자료 조사 appears in tasks of every topic.
    ("data", "자료", ("데이터", "AI", "MBL", "시뮬레이션", "그래프", "통계")),
]

METHOD_CATEGORIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("reasoning", "추론·설명", (
        "추론", "이유", "근거", "원리", "설명", "해석", "논증", "제안",
    )),
    ("measurement", "계산·측정", ("계산", "측정", "구하기", "산출")),
    ("experiment", "실험평가", (
        "실험", "문제인식", "가설", "변인 통제", "변인통제", "자료해석", "모델",
        "실습", "검출",
    )),
    ("problem", "문제해결", ("해결", "풀이", "전략", "판단")),
    ("analysis", "분석", ("분석", "비교")),
    ("discussion", "발표·토론", ("발표", "토론", "의견", "토의", "구술", "논의")),
    ("writing", "작성", (
        "작성", "쓰기", "감상문", "보고서", "서술", "논술", "정리", "기록",
        "활동지", "에세이", "일지", "일기", "글쓰기",
    )),
    ("production", "제작", (
        "제작", "설계", "만들기", "고안", "카드뉴스", "시나리오", "인포그래픽",
        "만화", "발명", "아이디어", "장치", "모형",
    )),
    ("process", "과정평가", ("포트폴리오", "스크랩", "과정평가", "누적")),
    ("inquiry", "탐구", ("탐구", "조사", "관찰", "프로젝트")),
]

# What a school ticks in its 평가 방법 checkbox row, mapped onto the guidebook's
# method axis. 교사 관찰/자기평가/동료평가 are deliberately absent: they say who
# judges, not what the student does, so they classify nothing.
DECLARED_METHOD_TO_AXIS: list[tuple[str, str]] = [
    ("실험", "experiment"),
    ("실습", "experiment"),
    ("프로젝트", "inquiry"),
    ("포트폴리오", "process"),
    ("토의", "discussion"),
    ("토론", "discussion"),
    ("구술", "discussion"),
    ("발표", "discussion"),
    ("조사", "inquiry"),
    ("관찰보고서", "inquiry"),
    ("논술", "writing"),
    ("서술", "writing"),
    ("보고서", "writing"),
    ("서답형", "writing"),
]
# "þ"/"■" are what HWP symbol fonts leave behind for a ticked box.
TICKED_BOX_RE = re.compile(r"[■☑☒✓✔þＶ]|□\s*[VvＶ]")


def declared_method_axis(method: str) -> tuple[str, list[str]]:
    """Map the school's own ticked 평가 방법 onto the method axis.

    Only ticked options count: a source cell normally prints the entire menu,
    so reading it whole would credit every school with every method.
    """

    text = re.sub(r"\s+", " ", method).strip()
    if not text:
        return "", []
    if TICKED_BOX_RE.search(text):
        picked = [
            TICKED_BOX_RE.sub("", segment).strip(" ·|")
            for segment in re.split(r"(?=[■☑☒✓✔þ□])", text)
            if TICKED_BOX_RE.match(segment.strip())
        ]
    else:
        picked = [text]
    found: list[str] = []
    for value in picked:
        compact = _normalize(value)
        for needle, axis in DECLARED_METHOD_TO_AXIS:
            if needle in compact and axis not in found:
                found.append(axis)
                break
    if not found:
        return "", []
    return found[0], found[1:]


TOPIC_LABELS = {key: label for key, label, _ in TOPIC_CATEGORIES}
METHOD_LABELS = {key: label for key, label, _ in METHOD_CATEGORIES}


def _normalize(value: str) -> str:
    """Fold to a spacing-insensitive form.

    Schools write the same term both ways ("과학적 탐구방법" / "과학적 탐구 방법",
    "판 경계" / "판경계"), so keeping spaces made the guidebook's own example
    words miss the source wording they were taken from.
    """

    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).lower()


def _score(text: str, words: tuple[str, ...]) -> tuple[int, int]:
    """Return (hit count, longest matched word length) for one category."""

    hits = 0
    longest = 0
    for word in words:
        needle = _normalize(word)
        if needle and needle in text:
            hits += 1
            longest = max(longest, len(needle))
    return hits, longest


def _classify(
    text: str, categories: list[tuple[str, str, tuple[str, ...]]]
) -> tuple[str, list[str]]:
    """Pick the best-supported category, and report every close rival.

    A longer matched word wins over a merely more frequent one: "생물다양성"
    (환경) is more specific evidence than the single character "빛" happening
    to appear. Ties are not broken by list order -- they are returned as
    rivals so a human can settle them, because the guidebook gives no rule
    for a 영역명 that genuinely spans two categories.
    """

    normalized = _normalize(text)
    if not normalized:
        return "", []
    scored = []
    for key, _, words in categories:
        hits, longest = _score(normalized, words)
        if hits:
            scored.append((longest, hits, key))
    if not scored:
        return "", []
    scored.sort(reverse=True)
    best_longest, best_hits, best_key = scored[0]
    rivals = [
        key
        for longest, hits, key in scored[1:]
        if longest == best_longest and hits == best_hits
    ]
    return best_key, rivals


def classify_area_name(
    title: str, overview: str = "", declared_method: str = ""
) -> dict[str, object]:
    """Classify one 영역명 into topic × method.

    The title carries the school's own naming of the task and is what the
    guidebook categorises, so it is scored first; the overview only fills an
    axis the title left empty rather than competing with it.
    """

    topic, topic_rivals = _classify(title, TOPIC_CATEGORIES)
    method, method_rivals = _classify(title, METHOD_CATEGORIES)
    if not topic and overview:
        topic, topic_rivals = _classify(overview, TOPIC_CATEGORIES)
    # The guidebook categorises the 영역명 itself, so the title keeps priority;
    # the school's ticked 평가 방법 fills an axis the title left empty rather
    # than overruling a name that already states its method.
    if not method:
        method, method_rivals = declared_method_axis(declared_method)
    if not method and overview:
        method, method_rivals = _classify(overview, METHOD_CATEGORIES)
    return {
        "topic": topic,
        "method": method,
        "topic_rivals": topic_rivals,
        "method_rivals": method_rivals,
        "ambiguous": bool(topic_rivals or method_rivals) or not topic or not method,
    }
