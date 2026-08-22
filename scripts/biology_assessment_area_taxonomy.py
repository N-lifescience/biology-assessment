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
        "중력", "구조물", "충격", "경사면", "관성",
    )),
    ("wave", "빛과 파동", ("빛", "파동", "스펙트럼", "백색광", "굴절", "간섭")),
    ("electromagnetism", "전자기", (
        "에너지", "전기", "전류", "전압", "전력", "회로", "변환", "전자",
        "트랜지스터", "엔탈피", "반도체",
    )),
    ("matter", "물질의 구성", (
        # "구조"/"성질" dropped: 세포의 구조, 염색체 구조 dominate this corpus.
        "물질", "원자", "분자", "결합", "원소", "주기율표", "광물",
        "알칼리금속", "알칼리 금속", "할로젠", "이온", "전자배치", "전자 배치",
        "밀도", "신소재",
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
        # 미검출 표본에서 실제로 쓰인 관찰 도구·재료·기관 어휘. 「물벼룩의 심장
        # 박동 관찰」, 「시금치 잎의 색소 분리 실험」처럼 다루는 내용이 분명한데도
        # 가이드북 예시 단어에 없어서 미분류로 남던 것들이다.
        "현미경", "프레파라트", "표본", "혈구", "물벼룩", "시금치", "양파", "효모",
        "색소", "심장", "박동", "소화제", "영양소", "아밀레이스", "카탈레이스",
        "과산화수소", "항생", "리포솜", "배양", "혈장", "적혈구", "백혈구", "혈관",
        # 한 글자 어휘(간·위·장·폐)는 넣지 않는다. 공백을 지우고 부분 문자열로
        # 맞추므로 "인간", "단위", "문장"에까지 걸린다.
        "콩팥", "근육", "인체", "약물", "영양",
    )),
    ("genetics", "유전", (
        # "정보" dropped: 자료·정보 is generic wording across every topic.
        "유전", "진화", "형질", "변이", "핵산", "DNA", "염색체", "생식세포",
        "돌연변이", "유전자", "분류", "계통",
        "감수분열", "체세포분열", "가계도", "유전병", "전사", "번역", "복제",
        "형질전환", "혈액형", "생명공학", "유전체", "rna",
        "핵형", "계통수", "유연관계", "멘델", "우열", "대립유전자",
    )),
    ("earth", "지구", (
        "지구", "기후", "대기", "해양", "판 경계", "관측", "지진", "지질", "판의 경계",
        "지권", "암석", "화산", "지층", "화석", "기온", "강수", "태풍", "빙하",
    )),
    ("space", "우주·천체", ("우주", "천체", "태양", "행성", "별", "은하")),
    ("environment", "환경", (
        "환경", "생태", "지속가능", "탄소중립", "미세먼지", "오염", "토양", "멸종",
        "외래종", "생물다양성", "생태계", "평형", "보호", "적정 기술", "군집", "개체군",
        "천이", "먹이사슬", "먹이그물", "물질순환", "에너지흐름", "방형구", "기후변화",
    )),
    ("history", "과학사", (
        "역사", "과학사", "발전", "과학자", "패러다임",
        # 코퍼스가 과학사 과제를 인물 이름으로 부르는 경우가 많다.
        "갈릴레이", "파스퇴르", "멘델레예프", "뉴턴", "다윈", "허시", "메셀슨",
        "라부아지에", "자격루", "선조", "도량형", "속생설",
    )),
    ("nos", "과학적 사고", (
        "과학의 본성", "과학적 탐구 방법", "귀납적", "연역적", "탐구 방법", "본성",
        "귀납", "연역", "가설 설정", "변인", "탐구 과정", "탐구 절차",
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
    ("data", "자료", (
        "데이터", "AI", "MBL", "시뮬레이션", "그래프", "통계", "빅데이터", "센서",
    )),
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


def _normalize(value: str) -> str:
    """Fold to a spacing-insensitive form.

    Schools write the same term both ways ("과학적 탐구방법" / "과학적 탐구 방법",
    "판 경계" / "판경계"), so keeping spaces made the guidebook's own example
    words miss the source wording they were taken from.
    """

    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).lower()


def declared_method_axes(method: str) -> list[str]:
    """Map the school's own ticked 평가 방법 onto the method axis.

    Only ticked options count: a source cell normally prints the entire menu,
    so reading it whole would credit every school with every method.
    """

    text = re.sub(r"\s+", " ", method).strip()
    if not text:
        return []
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
    return found


# 주제 축의 17번째 값. 어휘가 모자라서 못 찾은 것이 아니라, 이름이 방법·과정
# 어휘로만 되어 있어 다룰 내용을 학생이 정하는 과제다(「포트폴리오」, 「자유 주제
# 탐구」, 「주제 탐구 보고서」). 주제를 정하는 방식 자체가 설계 참고가 되므로
# 미분류로 숨기지 않고 고를 수 있는 항목으로 둔다.
FREE_TOPIC = "free"

TOPIC_LABELS = {key: label for key, label, _ in TOPIC_CATEGORIES}
TOPIC_LABELS[FREE_TOPIC] = "자유 주제"
METHOD_LABELS = {key: label for key, label, _ in METHOD_CATEGORIES}

# 탐구는 나머지 아홉 개와 같은 층위가 아니다. 실험도 조사도 프로젝트도 탐구라서,
# 「탐구 실험」·「탐구 보고서」처럼 구체적인 방법과 나란히 적힌 이름이 코퍼스의
# 대부분이다. 구체적인 방법이 함께 잡히면 탐구는 뺀다 — 그러지 않으면 탐구 탭이
# 사실상 전체 목록이 되어 아무것도 좁혀주지 못한다.
UMBRELLA_METHOD = "inquiry"

# 이름을 이루는 단어가 이것뿐이면 다룰 내용이 이름에 없다. 방법 축 예시 단어에
# 더해, 어느 주제에나 붙는 일반 명사를 함께 센다.
CONTENT_FREE_EXTRA_WORDS = (
    "과학", "과학적", "수행평가", "평가", "활동", "주제", "자유", "자율", "심화",
    "학습", "수업", "교과", "내용", "결과", "과정", "능력", "자료", "개념", "질문",
    "영역", "차시", "단원", "개별", "모둠", "협력", "학습지", "형성평가", "만들기",
    "쓰기", "하기", "수행", "및", "평가지",
)
_CONTENT_FREE_WORDS = {
    _normalize(word)
    for _, _, words in METHOD_CATEGORIES
    for word in words
} | {_normalize(word) for word in CONTENT_FREE_EXTRA_WORDS}


def is_content_free_name(title: str) -> bool:
    """True when every word in the name is a method or a filler noun."""

    tokens = re.findall(r"[가-힣A-Za-z]{2,}", unicodedata.normalize("NFKC", title))
    if not tokens:
        return False
    return all(_normalize(token) in _CONTENT_FREE_WORDS for token in tokens)


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
) -> list[str]:
    """Return every category the name genuinely supports, best-supported first.

    A longer matched word is stronger evidence than a merely more frequent
    one: "생물다양성" (환경) says more than the single character "빛" happening
    to appear.  Categories tied at the top are all kept rather than one being
    picked: the guidebook gives no rule for a 영역명 that spans two, and in
    this corpus it usually spans them for real -- 「중화 반응 실험 및 해석」 is
    both 실험평가 and 추론·설명.  A teacher looking for either should find it.
    """

    normalized = _normalize(text)
    if not normalized:
        return []
    scored = []
    for key, _, words in categories:
        hits, longest = _score(normalized, words)
        if hits:
            scored.append((longest, hits, key))
    if not scored:
        return []
    scored.sort(reverse=True)
    best_longest, best_hits, _ = scored[0]
    return [
        key
        for longest, hits, key in scored
        if longest == best_longest and hits == best_hits
    ]


def classify_area_name(
    title: str, overview: str = "", declared_method: str = ""
) -> dict[str, object]:
    """Classify one 영역명 onto the topic × method matrix.

    Both axes carry a list, not one value.  The title carries the school's own
    naming of the task and is what the guidebook categorises, so it is scored
    first; the overview and the school's ticked 평가 방법 only fill an axis the
    title left empty rather than competing with it.
    """

    topics = _classify(title, TOPIC_CATEGORIES)
    methods = _classify(title, METHOD_CATEGORIES)
    if not topics and overview:
        topics = _classify(overview, TOPIC_CATEGORIES)
    if not methods:
        methods = declared_method_axes(declared_method)
    if not methods and overview:
        methods = _classify(overview, METHOD_CATEGORIES)
    concrete = [key for key in methods if key != UMBRELLA_METHOD]
    methods = concrete or methods
    if not topics and is_content_free_name(title):
        topics = [FREE_TOPIC]
    return {
        "topics": topics,
        "methods": methods,
        # Kept as the single value used for display and ordering; the lists
        # above are what a filter matches against.
        "topic": topics[0] if topics else "",
        "method": methods[0] if methods else "",
        "ambiguous": len(topics) > 1 or len(methods) > 1 or not topics or not methods,
    }
