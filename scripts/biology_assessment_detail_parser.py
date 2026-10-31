"""Loss-minimising parser for one biology subject's performance-assessment section.

The public catalogue used to collapse one source document and subject into a
single summary row.  This module keeps the source wording and table structure,
then identifies individual assessment headings only when the document itself
provides a usable boundary.  It never invents a task title.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from functools import lru_cache
from html.parser import HTMLParser as StdlibHTMLParser
from pathlib import Path

from scripts.build_biology_assessment_publish_db import html_tables

CONTEXT_JUMP_MARKERS = ("[...문맥 전환...]", "[…문맥 전환…]")
COURSE_HEADING_MARKERS = (
    "교수학습및평가운영계획",
    "교수·학습및평가운영계획",
    "교수학습및평가계획",
    "교수·학습및평가계획",
    "교수학습및평가계획서",
    "교수·학습및평가계획서",
    "교수학습-평가방법",
    "교수학습및평가방법",
)
# "교수학습·평가 계획(서)", "교수·학습 및 성취평가 운영 계획" -- the same
# cover title without 및, or with the 운영/성취 words schools add.  They only
# identify the requested course's own title line: a course section uses the
# same words in its sub-headings ("1. 교수·학습 평가 계획"), so they never end
# a section the way COURSE_HEADING_MARKERS do.
COURSE_TITLE_VARIANT_MARKERS = (
    "교수학습평가계획",
    "교수학습평가운영계획",
    "교수학습운영계획",
    "교수학습및성취평가운영계획",
    "학습지도및평가계획",
    "교과지도평가계획",
)
# A bare course name as a heading ("# 체육", "# 화학Ⅰ", "# 확률과 통계") opens
# the next course in a combined plan.  Only names are matched, never section
# words, so "# 교수·학습" or "# 나. 피드백 및 기록" inside a course never ends it.
OTHER_COURSE_HEADING_RE = re.compile(
    r"(?:국어|문학|독서와작문|화법과언어|언어와매체|독서|화법과작문|"
    r"수학|공통수학[12]?|기본수학[12]?|대수|미적분[ⅠⅡI]*|확률과통계|기하|경제수학|인공지능수학|실용수학|수학과제탐구|"
    r"영어|공통영어[12]?|기본영어[12]?|영어[ⅠⅡI]+|영어회화|영어독해와작문|영어독해|영어작문|심화영어[가-힣]*|"
    r"한국사[12]?|통합사회[12]?|사회|생활과윤리|윤리와사상|현대사회와윤리|도덕|세계사|동아시아사|동아시아역사기행|"
    r"한국지리|세계지리|세계시민과지리|여행지리|경제|정치와법|정치|법과사회|사회와문화|사회문화|사회문제탐구|"
    r"물리학[ⅠⅡI12]*|화학[ⅠⅡI12]*|지구과학[ⅠⅡI12]*|역학과에너지|전자기와양자|물질과에너지|화학반응의세계|"
    r"지구시스템과학|행성우주과학|융합과학|과학사|과학탐구실험[12]?|통합과학[12]?|"
    r"체육[12]?|운동과건강|스포츠생활[12]?|스포츠문화|스포츠과학|음악|음악연주|음악감상과비평|미술|미술창작|미술감상과비평|"
    r"연극|기술가정|기술·가정|정보|인공지능기초|프로그래밍|데이터과학|"
    r"일본어[ⅠⅡI]*|중국어[ⅠⅡI]*|독일어[ⅠⅡI]*|프랑스어[ⅠⅡI]*|스페인어[ⅠⅡI]*|러시아어[ⅠⅡI]*|아랍어[ⅠⅡI]*|베트남어[ⅠⅡI]*|한문[ⅠⅡI]*|"
    r"진로와직업|철학|심리학|논리학|논술|보건|환경|교육학|종교학|실용경제|"
    r"창의적체험활동|자율활동|동아리활동|봉사활동|진로활동)"
)
SECTION_WORD_RE = re.compile(
    r"평가|계획|방법|기준|유의|목적|방침|결과|활용|시기|절차|수행|개요|목차|성취|기타|운영|배점|"
    r"과제|영역|월|주|차시|단원|내용|안내|참고|비고|서식|양식|첨부|부록"
)
TOC_LINE_RE = re.compile(r"(?:[·‥…]{3,}|\.{4,})\s*\d{0,4}\s*$|\s\d{1,3}\s*$")
MIN_SUBJECT_SECTION_CHARS = 400
ZIP_MEMBER_RE = re.compile(r"^\[zip:(?P<name>.+?)\]\[(?P<status>[^\]]+)\]\s*$", re.I)
MAX_BOUNDED_ITEMS = 12
PIPE_SEPARATOR_RE = re.compile(r"\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*")
BLOCK_END_RE = re.compile(
    r"(?:결시자|미응시자|학적\s*변동|성적\s*처리|이의\s*신청|평가\s*결과의\s*활용|"
    r"교수\s*학습\s*운영\s*계획|성취도|성취기준별\s*성취수준|재응시|결과물\s*보존|"
    # The section listing standards the school does *not* assess by exam or
    # performance task ends the assessment block by definition.
    r"평가하지\s*않는\s*성취기준)"
)
ITEM_PREFIX_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:"
    r"(?P<letter>[가-하])\s*[.)]|"
    r"(?P<number>\d{1,2})\s*[.)]|"
    r"\((?P<paren>\d{1,2})\)|"
    r"(?P<circled>[①-⑳])"
    r")\s*(?P<title>.+?)\s*$"
)
ASSESSMENT_MARKER_RE = re.compile(
    r"성취기준|평가\s*개요|평가\s*방법|채점\s*기준|세부\s*기준|세부\s*평가\s*척도|"
    r"반영\s*비율|점수\s*/?\s*반영|평가\s*요소|배점|만점|실시\s*시기"
)
PERFORMANCE_MARKER_RE = re.compile(
    r"평가\s*개요|평가\s*방법|채점\s*기준|세부\s*기준|세부\s*평가\s*척도|"
    r"반영\s*비율|점수\s*/?\s*반영|평가\s*요소|배점|만점|실시\s*시기"
)
GENERIC_TITLE_RE = re.compile(
    # 단답형/서술형/선택형 are the 지필 columns of a school's 평가 종류 summary
    # table, not performance-assessment names (논술형 stays: schools do run
    # 논술형 수행평가).
    # A bare 수행 is what is left of "수행평가 기준" once the heading cleaner
    # takes its section word off.
    r"^(?:수행평가|수행|정기시험|지필(?:\s*평가)?|단답형|서술형|선택형|"
    r"평가\s*세부\s*계획|평가의?\s*(?:목적|방침|방향)|"
    r"성취기준(?:과\s*성취수준)?|채점\s*기준|평가\s*방법|성취도|"
    r"결시자.*|미응시자.*|학적\s*변동.*|성적\s*처리.*|평가\s*결과.*)$"
)
EXPLICIT_TITLE_LABEL_RE = re.compile(
    r"^(?:평가영역(?:명)?(?:[1-9])?|평가명|수행평가(?:명|영역(?:명)?|과제명|과제)|수행과제(?:명)?|"
    r"평가과제(?:명)?|과제명|(?:평가)?영역만점|영역명)$"
)
# The subset of those labels that names an assessment *area* rather than the
# task: schools fill these cells with a unit name about as often as a task name.
AREA_TITLE_LABEL_RE = re.compile(r"^(?:평가영역(?:[1-9])?|수행평가영역|영역만점|평가영역만점)$")
# A heading may only outrank such a cell when it names an activity.  Section
# headings that merely repeat a course name ("통합과학 생물") or a document
# structure ("수행평가 영역별 세부기준") are worse titles than the cell.
TASK_ACTIVITY_RE = re.compile(
    r"보고서|실험|발표|프로젝트|포트폴리오|제작|조사|탐구|논술|서술|설계|작성|만들기|"
    r"분석|토론|글쓰기|캠페인|관찰|측정|모형|에세이|일지|"
    # A 영역명 written as a nominalised verb ("캘빈회로와 TCA회로 표현하기",
    # "유전자발현 추론하기") names an activity whatever the verb is; a unit
    # name in a 평가영역 cell never takes this form.
    r"하기"
)
# Names a task, not only an activity: the products and worksheets schools put
# in a heading ("가. 개념 확장 질문 노트", "1) 갈릴레이의 실험으로 낙하 운동
# 추론").  Kept apart from TASK_ACTIVITY_RE, which also decides policy prose.
TASK_NAME_RE = re.compile(
    TASK_ACTIVITY_RE.pattern
    + r"|노트|학습지|활동지|추론|해석|퀴즈|포스터|인포그래픽|영상|만화|신문|카드\s*뉴스"
)
# Labels whose cell says what the student does.  Schools write a sentence
# there as often as a name; 수행과제명/평가과제명 are names and stay out.
TASK_DESCRIPTION_LABEL_RE = re.compile(r"^(?:수행과제|평가과제|수행평가과제|과제내용)$")
TASK_DESCRIPTION_LIST_RE = re.compile(r"[·•⦁◦‣∘▪]|(?:^|\s)-\s")
# A numbered heading that carries its own score ("가. 포트폴리오(50점)") is the
# school naming a scored assessment area: a score is only ever written beside
# the name of something that is graded, never beside a section label.  Under
# such a heading the table's 수행과제 cell describes what the student does, so
# the heading is the name and the cell is the overview.  Values below 5 are
# excluded because "(1)" is source numbering, not a score -- the same
# threshold :func:`_clean_heading_title` already uses to strip score suffixes.
# The score may be written "(총 10점)", "[35점]" or "(반영비율 10%)".
SCORED_AREA_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:(?:[가-하]|\d{1,2}|[①-⑳])\s*[.)]|[(（]\s*\d{1,2}\s*[)）])\s*"
    r"(?P<name>[^()（）\[\]]*[^\s()（）\[\]])\s*"
    r"[(（\[]\s*(?:총\s*점?|배점|반영\s*비율)?\s*[:：]?\s*"
    r"(?:[5-9]|[1-9]\d|100)\s*(?:점|%)?\s*[)）\]]\s*$"
)
# A heading that only says how the work is graded ("가. 서·논술형 평가",
# "1차 수행평가") names a method, not the task; nor does a unit heading
# ("Ⅱ. 항상성과 몸의 조절") or a course name ("통합과학 생물").
METHOD_ONLY_NAME_RE = re.compile(
    r"^(?:제?\d+(?:차|회)?)?(?:서논술|서술논술|서술|논술|구술|발표|토의|토론|토의토론|실험|실습|실험실습|"
    r"프로젝트|포트폴리오|보고서|관찰|과정|자기|동료|수업참여|정의적능력|정의적영역|활동|탐구)?"
    r"형?(?:수행)?(?:평가)?(?:\d+)?$"
)
UNIT_HEADING_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:[ⅠⅡⅢⅣⅤⅥ]|[IVX]{1,3}\s*[.．])|단원")
COURSE_NAME_ONLY_RE = re.compile(
    r"^(?:(?:통합과학|과학탐구실험|생명과학|고급생명과학|생명과학실험|세포와물질대사|생물의유전|"
    r"생물|화학|물리학?|지구과학)"
    r"(?:[12ⅠⅡI]|II)?)+$"
)
TITLE_VALUE_STOP_LABELS = {
    "영역만점",
    "만점",
    "총점",
    "학기",
    "반영비율",
    "평가시기",
    "평가방법",
    "평가단원",
    "성취기준",
    "평가요소",
    "채점기준",
    "기본점수",
}
TITLE_VALUE_STOP_LABEL_RE = re.compile(
    r"^(?:영역?만점(?:점)?|총점|학기|반영비율|평가시기(?:횟수)?|평가방법\d*|"
    r"평가단원|관련?성취기준|교육과정성취기준|"
    r"평가요소(?:배점|채점요소)?|채점기준|세부기준|기본점수|배점|"
    r"평가항목|평가내용(?:점수|및요소|평가방법)?|평가방식|평가만점|"
    r"성취수준|처리기준|동점자처리기준순위|평가수준채점기준|"
    r"점수부여기준|기준영역|구분|시기)$"
)
NON_TASK_TITLE_RE = re.compile(
    r"^(?:(?:제?[12]|중간|기말)\s*(?:차|회)?\s*(?:정기)?\s*(?:고사|시험)|"
    r"[12]\s*(?:차|회)|정기\s*(?:고사|시험)(?:\s*\(\s*\d+%\s*\))?|"
    r"선택형|서[·‧ㆍ]?논술형)$"
)
# Cell values and labels from score and status columns that table scans
# offered as names ("미실시", "보통임", "부여점수", "평가수준").
NON_TASK_LABEL_TITLE_RE = re.compile(r"미실시|보통임|부여점수|평가수준|기본점수|만점")
# A written exam and its scope ("1학기 중간고사 : [12생과01-01] ~ …",
# "1차 지필고사", "학기말고사") sits in the same 평가영역 cells as a task but
# is never a performance assessment.
WRITTEN_EXAM_TITLE_RE = re.compile(
    r"^\W*(?:\d\s*학기\s*)?(?:중간|기말|학기말)\s*고사(?:\s*[:：(\[\-–—]|\s*$)|"
    r"^\W*(?:제?\s*\d\s*(?:차|회)\s*)?지필\s*(?:평가|고사|시험)?(?:\s*[:：(\[\-–—]|\s*$)|"
    r"^\W*학기말\s*고사"
)
# Private-use glyphs are a word processor's bullet symbols ("󰋯중간고사"), not text.
PRIVATE_USE_GLYPH_RE = re.compile("[-\U000f0000-\U0010ffff]")
ACHIEVEMENT_CODE_TITLE_RE = re.compile(r"^\[?\s*(?:10|12)[가-힣A-Za-zⅠ-Ⅹ]{1,6}\s*\d")
SCORE_ONLY_TITLE_RE = re.compile(r"^[\d\s.,()%점배분/~-]+$")
RUBRIC_SENTENCE_ENDING_RE = re.compile(r"(?:다|음|함|됨|경우)$")
RUBRIC_QUESTION_RE = re.compile(r"는가\s*\??$")
RUBRIC_QUESTION_PERFORMANCE_RE = re.compile(r"수\s*있는가|[였었했]는가")
# A task named as a question asks about nature with a question word ("우리 몸은
# 어떻게 항상성을 유지하는가?"); a checklist line asks whether the student did
# something ("… 발표를 명확하게 하는가").
TITLE_QUESTION_WORD_RE = re.compile(r"어떻게|어디|무엇|왜|누구|언제|얼마|어느|어떤|무슨|몇")
# …unless it grades the answer ("… 어디에 속하는지 옳게 설명하였는가?").
RUBRIC_QUESTION_GRADING_RE = re.compile(
    r"옳게|바르게|정확하게|명확하게|적절하게|타당하게|논리적으로|충실하게|충실히|성실하게|성실히"
)
RUBRIC_QUESTION_MIN_CHARS = 15
RUBRIC_SENTENCE_VOCABULARY_RE = re.compile(
    r"부족|미흡|충족|만족|참여|제출|응시|모호|불명확|불충분|없음|않음|못함|요함|"
    r"우수|노력|결석|보통|충분|정확|적절|근거|논리|오류|누락"
)


def is_rubric_criterion_sentence(title: str) -> bool:
    """Detect a rubric grading-scale descriptor mis-captured as a task title.

    Performance-level tables ("A 수준: ...", "미흡함") sit in the same cells a
    real task name would occupy when a school's table has no explicit label
    row, so the parser sometimes has nothing else to offer as a title. These
    never carry the sentence-final ending the case-level legacy path already
    filters on a literal period ("...한다."); table cells routinely drop the
    period, so the same ending is checked with or without one. A short title
    ending this way (a teacher's own stylised phrase, e.g. "과학을 찾다") is
    only rejected when it also uses grading vocabulary, to avoid mistaking a
    genuine title for a rubric line just because both end in the same syllable.
    """

    stripped = title.strip()
    # Checklist rubrics ask the grader a question ("탐구활동의 결과를 설명할 수
    # 있는가?", "다른 친구들과 협력하였는가?").  A task title may be a question
    # too ("유전자는 어떻게 켜지는가?"), so the question must also be about the
    # student's performance.
    if RUBRIC_QUESTION_RE.search(stripped):
        if RUBRIC_QUESTION_PERFORMANCE_RE.search(stripped) or RUBRIC_QUESTION_GRADING_RE.search(
            stripped
        ):
            return True
        if TITLE_QUESTION_WORD_RE.search(stripped):
            return False
        return bool(
            RUBRIC_SENTENCE_VOCABULARY_RE.search(stripped)
            or len(compact_text(stripped)) >= RUBRIC_QUESTION_MIN_CHARS
        )
    if not RUBRIC_SENTENCE_ENDING_RE.search(stripped):
        return False
    compact = compact_text(stripped)
    return len(compact) > 12 or bool(RUBRIC_SENTENCE_VOCABULARY_RE.search(stripped))
STRUCTURAL_HEADING_RE = re.compile(
    r"^(?:평가\s*개요(?:표)?|채점\s*기준표?|공통\s*(?:사항|유의\s*사항)|개요|영역|"
    r"세부\s*내용\s*및\s*평가\s*척도표|세부\s*(?:채점\s*)?기준|피드백\s*및\s*기록|"
    r"(?:수행)?평가\s*(?:세부\s*)?(?:계획|기준|기준안|운영)|"
    r"수행\s*평가\s*세부\s*기준\s*\([^)]*\)|"
    r"수행평가\s*(?:개요|분할\s*점수(?:\s*산출)?|성취율과\s*원점수)|"
    r"(?:수행)?평가\s*영역\s*및\s*(?:평가\s*기준|반영\s*비율)|"
    r"수행평가\s*영역\s*및\s*배점|"
    r"수행평가\s*영역별\s*(?:평가\s*요소\s*및\s*채점\s*기준|성취기준\s*및\s*평가\s*척도)|"
    r"(?:평가\s*)?영역별\s*(?:세부\s*)?(?:평가\s*)?(?:기준|채점\s*기준|반영\s*비율)|"
    r"영역별\s*평가\s*방법과\s*채점\s*기준|평가\s*영역\s*및\s*배점|"
    r"세부\s*(?:시행\s*)?계획|"
    r"평가\s*(?:요소\s*및\s*(?:채점\s*기준|배점|성취\s*기준)|항목과\s*배점|과제)|"
    r"평가\s*방법\s*및\s*내용|"
    r"(?:수행)?\s*평가\s*(?:의\s*)?범위\s*(?:와|및)\s*기준(?:\s*및\s*반영\s*비율)?|"
    r"(?:관련\s*)?성취기준|성취\s*기준과\s*평가\s*기준|"
    r"성취기준\s*및\s*(?:평가기준|성취수준|평가\s*방법)|"
    r"교육과정\s*성취기준\s*및\s*평가\s*기준(?:,\s*평가\s*요소\s*및\s*배점)?|"
    r"\[?\s*(?:평가\s*)?유의\s*사항\s*\]?|출제\s*계획표?|학기\s*단위\s*성취수준|최소\s*성취수준\s*진술문|"
    r"결시생?\s*처리기준|동점자\s*처리\s*기준|"
    r"(?:사회정서학습\s*연계\s*)?정의적\s*(?:능력|영역)\s*평가(?:의\s*실제|\s*(?:방안|계획|세부\s*사항|요소와\s*평가\s*방법))?|"
    r"(?:(?:통합|생명)?과학\s*)?학습\s*과정\s*평가|서(?:술)?[·‧ㆍ]?\s*논술형\s*평가(?:\s*계획)?|세부\s*평가\s*척도|"
    r"평가\s*방법\s*및\s*결과의\s*활용|정기시험\s*및\s*수행평가\s*세부계획|"
    r"기타\s*사항|(?:평가과제|수행과제|평가영역|수행)\s*[12]|"
    r"평가의?\s*종류\s*(?:와|및)\s*반영\s*비율|시행\s*계획|영역별\s*세부\s*계획|"
    r"기준\s*성취율\s*(?:와|및)\s*성취도[^\n]*|"
    # 이 절은 "평가하지 않는" 성취기준을 다룬다 -- 수행평가명이 아니다.
    r"[^\n]*평가하지\s*않는\s*성취기준[^\n]*|"
    r"(?:세부\s*)?평가\s*계획|평가\s*세부\s*계획|"
    r"수행평가\s*성취기준)$"
)
STRUCTURAL_EXACT_COMPACT = {
    "항목별계획",
    "평가영역",
    "평가요소별세부채점기준",
    "평가항목별채점기준",
    "기본점수부여여부및방법",
    "평가방법및활용",
    "고사별배점",
    "수행평가의세부기준평가과제별로작성",
    "수행평가세부기준및배점",
    "수행평가영역별세부기준",
    "수행평가세부계획",
    "수업참여도세부기준",
    "방침",
    "수행평가과제별개요",
    "수행평가범위와기준",
    "평가과제별세부계획",
    "AI활용금지범위",
    "수행평가인정점산출기준",
    "수행평가평가기준",
    "과정중심수행평가세부계획",
    "평가방법및반영비율",
    "수업계획",
    "수행평가영역및평가항목배점및채점기준",
    "수행평가요소및성취기준",
    "평가과제별반영비율및성취수준",
    "평가과제별채점기준",
    "수행평가1",
    "수행평가2",
    "세부평가내용",
    "평가방법및평가내용",
    "정기시험세부계획",
    "과제별배점",
    "최종배점",
    "수행평가내용및평가세부기준",
    "수행평가인정점부여기준",
    "수행평가세부기준영역별배점및채점기준",
    "수행평가세부계획과목특성에따라양식변경",
    "기본방향",
    "평가방법과반영비율",
    "수행평가세부계획교과사정에따라변경될수있음",
    "수행평가세부계획1",
    "수행평가세부계획2",
    "수행평가세부계획평가과제별로작성",
    "항목별평가기준",
    "항목별",
    "영역별세부",
    "영역별",
    "일반사항",
    "학기단위성취수준설정",
    "최소성취수준설정",
    "최소성취수준설정공통과목",
    "1학기",
    "2학기",
    "성취기준과",
    "통계",
    "벡터",
    "행렬",
}
# Sibling code prefixes of the same course across curriculum revisions.
# A 2022 course also cites its numbered sibling ("[10통과1-01-01] [10통과2-01-01]"
# in one 통합과학1 task); with one of its own codes beside them that is the
# school's citation, not another course.
SUBJECT_CODE_FAMILY = {
    "통합과학1": ("10통과", "10통과2"),
    "과학탐구실험1": ("10과탐", "10과탐2"),
    "통합과학2": ("10통과", "10통과1"),
    "과학탐구실험2": ("10과탐", "10과탐1"),
}
REVISED_CODE_FAMILY = {"생명과학": ("12생과Ⅰ", "12생과Ⅱ")}
EXPECTED_STANDARD_PREFIXES = {
    # 2015 개정 과학과
    "통합과학": ("10통과",),
    "과학탐구실험": ("10과탐",),
    "생명과학Ⅰ": ("12생과Ⅰ",),
    "생명과학Ⅱ": ("12생과Ⅱ",),
    # 2022 개정 과학과.  ``12생과`` is a strict prefix of the 2015 ``12생과Ⅰ``
    # and ``10통과``/``10과탐`` of the 2022 ``10통과1``/``10과탐1``;
    # ``subjects_for_standard_codes`` keeps only the longest matching prefix,
    # so the shorter name never absorbs the numbered course.
    "통합과학1": ("10통과1",),
    "통합과학2": ("10통과2",),
    "과학탐구실험1": ("10과탐1",),
    "과학탐구실험2": ("10과탐2",),
    "생명과학": ("12생과",),
    # 2022 진로 선택.  2026학년도 학교알리미 원문의 성취기준 코드로 확인했다
    # ("[12세포01-01] 탄수화물과 지질의 종류와 주요 기능…",
    # "[12유전01-01] 유전 형질이 유전자를 통해 자손에게 유전됨을…").
    "세포와 물질대사": ("12세포",),
    "생물의 유전": ("12유전",),
    # 과학계열 전문교과.  Prefixes independently re-verified 2026-08-16 against
    # the actual bracket-code achievement-standard listings for each subject's
    # curriculum reference page (2022 개정): "[12생실01-01]"~"[12생실05-08]"
    # 생명과학실험, "[12고생01-01]"~"[12고생04-04]" 고급생명과학. No official
    # NCIC PDF was checked directly; treat as reference-grade, not gazette-grade.
    "생명과학실험": ("12생실",),
    "고급생명과학": ("12고생",),
}
FIELD_LABELS = {
    "overview": ("평가개요", "평가내용", "수행과제", "과제내용"),
    # 평가유형/평가주체/평가방식 are the sub-rows a merged "평가 방법" cell spans;
    # treating them as method labels keeps the label itself out of the value
    # and reads the value cell that actually names the method.
    "method": ("평가방법", "방법", "평가유형", "평가주체", "평가방식"),
    "timing": ("평가시기", "실시시기", "평가일시횟수", "시기"),
    "weight": ("점수반영비율", "반영비율", "평가비율"),
    # A bare "점수/배점" is normally a rubric column, not the task total.
    "score": ("영역만점", "만점", "총점"),
}
ALL_FIELD_LABELS = {label for labels in FIELD_LABELS.values() for label in labels} | {
    "성취기준",
    "평가기준",
    "평가요소",
    "세부기준",
    "부여점수",
    "관련단원",
    "영역",
}


@dataclass(frozen=True)
class ParsedAssessmentItem:
    order: int
    title: str
    title_raw: str
    title_basis: str
    extraction_status: str
    source_start: int
    source_end: int
    source_markdown: str
    source_html: str
    rubric_html: str
    overview: str
    method: str
    timing: str
    score: str
    weight: str
    standards: tuple[str, ...]


def _already_read_under_a_heading(
    items: list[ParsedAssessmentItem], candidate: ParsedAssessmentItem
) -> bool:
    """True when a scored-area heading already covers this table's source span.

    Such a heading keeps the name and demotes the table's 수행과제 cell to the
    overview, so the table scan later finds that sentence and offers it as a
    separate assessment.  It is the same assessment, and the titles no longer
    match, so the source span is what still identifies it.

    Only headings that carry their own 배점 count, or a heading whose overview
    *is* the candidate's title (the short task-name heading that demoted its
    수행과제 sentence).  Any wider rule swallowed real assessments: an ordinary
    section heading can span several detail tables, and each of those is its
    own assessment.
    """

    candidate_key = _title_key(candidate.title)

    def covers_span(item: ParsedAssessmentItem) -> bool:
        return (
            item.source_start <= candidate.source_start
            and candidate.source_end <= item.source_end
        )

    def demoted_into_overview(item: ParsedAssessmentItem) -> bool:
        # The same 수행과제 sentence also turns up in a summary table outside
        # the heading's span; a sentence that long names one task only.
        return bool(
            len(candidate_key) >= 12 and candidate_key in _title_key(item.overview)
        )

    return any(
        item.extraction_status == "bounded"
        and item.title_basis == "heading"
        and (
            (SCORED_AREA_HEADING_RE.match(item.title_raw) and covers_span(item))
            or demoted_into_overview(item)
        )
        for item in items
    )


def _table_under_a_task_heading(
    items: list[ParsedAssessmentItem], candidate: ParsedAssessmentItem
) -> bool:
    """True when a rubric table sits inside a heading already read as one task.

    "1) 배움 기록장 작성하기" followed by ``평가항목 │ 평가요소 │ 채점 기준 │
    배점`` rows "내용 작성", "내용 구성": the rows grade that one task.  Only
    rubric splits are held back: under a heading such as "생명공학" a plan
    table can still list several tasks of its own.
    """

    return any(
        item.extraction_status == "bounded"
        and item.title_basis == "heading"
        and item.source_start <= candidate.source_start
        and candidate.source_end <= item.source_end
        for item in items
    )


@dataclass(frozen=True)
class ParsedAssessmentSection:
    subject: str
    boundary_status: str
    source_start: int
    source_end: int
    source_markdown: str
    detected_titles: tuple[str, ...]
    items: tuple[ParsedAssessmentItem, ...]


def compact_text(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣ⅠⅡ]", "", unicodedata.normalize("NFKC", value))


def subject_code_key(value: str) -> str:
    """Normalize a curriculum-code token without collapsing Roman numerals.

    Ordinary title comparison uses NFKC, but NFKC turns the course numerals
    ``Ⅰ`` and ``Ⅱ`` into ``I`` and ``II``.  A prefix comparison could then read
    a ``생명과학Ⅱ`` achievement code as ``생명과학Ⅰ``.  Course identity is a safety
    boundary, so curriculum-code matching preserves those original numerals.
    """

    key = re.sub(r"[^0-9A-Za-z가-힣ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]", "", unicodedata.normalize("NFC", value))
    # "[12생과II01-02]": a 2015 생명과학Ⅱ code typed with Latin letters.  2022
    # 생명과학 codes put the area digits right after 생과, so the letters
    # always mean the course numeral.
    return re.sub(r"(생과)(II|I)(?=\d|$)", lambda match: match.group(1) + (
        "Ⅱ" if match.group(2) == "II" else "Ⅰ"
    ), key)


def subjects_for_standard_codes(codes: list[str]) -> set[str]:
    """Map codes to subjects using only the most specific matching prefix."""

    matched: set[str] = set()
    normalized_prefixes = {
        subject: tuple(subject_code_key(prefix) for prefix in prefixes)
        for subject, prefixes in EXPECTED_STANDARD_PREFIXES.items()
    }
    for raw_code in codes:
        code = subject_code_key(raw_code)
        candidates = [
            (len(prefix), subject)
            for subject, prefixes in normalized_prefixes.items()
            for prefix in prefixes
            if code.startswith(prefix)
        ]
        if not candidates:
            continue
        longest = max(length for length, _ in candidates)
        matched.update(subject for length, subject in candidates if length == longest)
    return matched


CHECKED_BOX_ARTIFACT_RE = re.compile(r"gfedcb")
UNCHECKED_BOX_ARTIFACT_RE = re.compile(r"gfedc(?!b)")


SEAL_NAME_RE = re.compile(r"(?<![가-힣])[가-힣]{2,4}(\s*)\(인\)")


def mask_seal_names(value: str) -> str:
    """Hide a teacher's name written before a seal mark ("담당교사: 강여은(인)").

    The school publishes the plan, but the archive has no need for a named
    person; the cell keeps its shape as "○○○(인)".
    """

    return SEAL_NAME_RE.sub(lambda match: f"○○○{match.group(1)}(인)", value)


def normalize_checkbox_glyphs(value: str) -> str:
    """Restore a Hangul checkbox that HWP/PDF text extraction flattened.

    Source plans draw checkboxes with a symbol font whose five box-outline
    strokes and one checkmark stroke sit at the Latin-letter code points
    g,f,e,d,c(,b). Extraction reads those code points as literal text, so a
    checked box survives as "gfedcb" and an unchecked one as "gfedc". This is
    confirmed against several source documents, not a guess: the letters
    never occur elsewhere in these plans, and "gfedcb" always precedes the
    option a school marked, "gfedc" the ones it did not.
    """

    value = CHECKED_BOX_ARTIFACT_RE.sub("☑", value)
    return UNCHECKED_BOX_ARTIFACT_RE.sub("□", value)


def visible_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    # "※ <교수학습 및 평가방법>은 …"처럼 학교가 꺾쇠로 쓴 글도 지운다: 남기면 그 줄이
    # 다음 과목 계획서 제목으로 읽혀 구간이 끊긴다. 꺾쇠가 지운 이름의 나머지
    # ("과 관련된 주제를 …")는 POLICY_FRAGMENT_START_RE가 과제명에서 거른다.
    value = re.sub(r"<[^>]+>", " ", value)
    value = normalize_checkbox_glyphs(value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip(" |#*:-")


def _line_offsets(text: str) -> list[tuple[int, int, str]]:
    result: list[tuple[int, int, str]] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        result.append((cursor, cursor + len(line), line.rstrip("\r\n")))
        cursor += len(line)
    if not result or result[-1][1] < len(text):
        result.append((cursor, len(text), text[cursor:]))
    return result


STANDALONE_TITLE_MAX_CHARS = 60
LEADING_SECTION_NUMBER_RE = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|\d{1,3}|[가-하])\s*[.)]?\s+")
COURSE_TITLE_BRACKET_RE = re.compile(
    r"[\[(（]\s*([^\[\]()（）]{2,20}?)\s*[\])）]\s*(?:과|교과)?\s*"
    r"(?:교수\s*[·ㆍ‧･・]?\s*학습.*|평가\s*(?:운영\s*)?계획.*)?$"
)


TITLE_PERIOD_PREFIX_RE = re.compile(
    r"^\s*(?:(?:20\d{2}\s*학년도|\(?\s*[1-3]\s*\)?\s*학년|[12]\s*학기)\s*)*"
)
# "생명과학II과 교수ㆍ학습 및 평가 운영 계획": the course name, then "과" and the
# plan words.  Without "교수학습" the "과" stays: "생명과학과 평가계획" is a
# department's plan, not the 생명과학 course ("(생명과학)과 …" is matched by
# COURSE_TITLE_BRACKET_RE instead).
TITLE_PLAN_SUFFIX_RE = re.compile(
    r"(?:\s*(?:과|교과))?\s+교수\s*[·ㆍ‧･・․-]?\s*학습\s*(?:(?:및|과)\s*평가\s*)?"
    r"(?:운영\s*)?(?:계획|방법)\s*(?:서|\(안\))?\s*$"
    r"|\s+평가\s*(?:운영\s*)?(?:계획|방법)\s*(?:서|\(안\))?\s*$"
)


GENERIC_PLAN_TITLE_RE = re.compile(r"(?:교수학습)?(?:및|과)?(?:평가)?(?:운영)?(?:계획|방법)(?:서|안)?")


def title_course_part(shown: str) -> str:
    """The course name a plan title carries, without number, period and plan words.

    "## 40 생명과학" (a numbered title box), "2026학년도 1학기 생명과학Ⅱ" and
    "생명과학Ⅱ 교수학습 및 평가 운영 계획" all leave "생명과학Ⅱ"; a sentence
    leaves itself and so never equals a course name.
    """

    shown = LEADING_SECTION_NUMBER_RE.sub("", shown)
    shown = TITLE_PERIOD_PREFIX_RE.sub("", shown)
    shown = TITLE_PLAN_SUFFIX_RE.sub("", shown)
    return re.sub(r"\s*\([^)]*(?:학기|개정)[^)]*\)\s*$", "", shown).strip()


def _standalone_course_heading(raw: str) -> str:
    """Return a canonical course name from a source-authored Markdown heading.

    Combined Schoolinfo plans commonly use a short H1 such as ``# 기하`` or
    ``# 확률과 통계 (2학기)``.  Requiring the much longer phrase
    ``교수학습 및 평가계획`` made the parser start at the table of contents
    and then absorb every following course.  Only an exact, standalone heading
    is accepted here; ordinary prose mentions and table cells are ignored.
    """

    match = re.match(r"^\s*#{1,3}\s+(.+?)\s*$", raw)
    stripped = raw.strip()
    if match:
        shown = visible_text(match.group(1))
    elif _plain_title_line(raw):
        # kordoc reads many PDF title lines as plain paragraphs ("2026학년도
        # 3학년 ( 생명과학II )"), so a short line outside any table counts too.
        shown = visible_text(stripped)
    else:
        return ""
    if TOC_LINE_RE.search(shown):
        return ""
    bracketed = COURSE_TITLE_BRACKET_RE.search(shown)
    key = compact_text(title_course_part(shown))
    for course in EXPECTED_STANDARD_PREFIXES:
        if key == compact_text(course):
            return course
        # "( 생명과학II )", "2026학년도 1학기 (생명과학Ⅱ)과 교수학습 및 평가 계획":
        # the bracketed name must be exactly this course, so "(고급 생명과학)"
        # never opens a 생명과학 section.
        if bracketed and compact_text(bracketed.group(1)) == compact_text(course):
            return course
    return ""


def subject_local_markdown(full_text: str, subject: str) -> tuple[str, int, int, str]:
    """Return a raw-markdown subject section without flattening its tables."""

    target = compact_text(subject)
    lines = _line_offsets(full_text)

    # A Schoolinfo attachment is often one ZIP containing every subject.  The
    # extractor deliberately preserves a member boundary before each embedded
    # document.  Prefer that source-authored boundary over text heuristics so a
    # biology case can never absorb the neighbouring chemistry/English plan.
    zip_members: list[tuple[int, str]] = []
    for index, (_, _, raw) in enumerate(lines):
        match = ZIP_MEMBER_RE.match(raw.strip())
        if match:
            zip_members.append((index, match.group("name")))
    targets = _subject_targets(subject)
    matching_members = [
        position
        for position, (line_index, name) in enumerate(zip_members)
        if target
        and _names_course(name, targets)
        and "평가" in compact_text(name)
    ]
    if matching_members:
        # Prefer the filename with the least text beyond the requested course.
        # This keeps a generic "생명과학" case from selecting "고급 생명과학" merely
        # because that member happened to appear first in the ZIP.
        position = min(
            matching_members,
            key=lambda value: (
                len(compact_text(Path(zip_members[value][1]).stem)) - len(target),
                value,
            ),
        )
        start_index = zip_members[position][0]
        end_index = zip_members[position + 1][0] if position + 1 < len(zip_members) else len(lines)
        start = lines[start_index][0]
        end = lines[end_index][0] if end_index < len(lines) else len(full_text)
        return full_text[start:end].strip(), start, end, "zip_member_subject"

    # PDF/HWP converters preserve document headings even when the original
    # attachment contains many biology courses.  Use those exact headings
    # before the looser cover-table rules below.  Consecutive semester sections
    # for the same course remain in one local block; the next *different*
    # biology course closes it.
    course_headings = [
        (index, course)
        for index, (_, _, raw) in enumerate(lines)
        if (course := _standalone_course_heading(raw))
    ]
    matching_headings = [
        position
        for position, (_, course) in enumerate(course_headings)
        if course == subject
    ]
    if matching_headings:
        # A cover-sheet cell rendered as ``## 생명과학`` opens a stub section;
        # try each exact heading and keep the first that holds real content.
        chosen: tuple[int, int, int] | None = None
        for position in matching_headings:
            candidate_start, candidate_end, candidate_level = _exact_section_bounds(
                lines, course_headings, position, subject, target
            )
            span_end = lines[candidate_end][0] if candidate_end < len(lines) else len(full_text)
            span = full_text[lines[candidate_start][0]: span_end]
            if chosen is None or (
                len(span) >= MIN_SUBJECT_SECTION_CHARS
                and lines[chosen[1]][0] - lines[chosen[0]][0] < MIN_SUBJECT_SECTION_CHARS
            ):
                chosen = (candidate_start, candidate_end, candidate_level)
                if len(span) >= MIN_SUBJECT_SECTION_CHARS:
                    break
        start_index, end_index, _level = chosen
        start = lines[start_index][0]
        end = lines[end_index][0] if end_index < len(lines) else len(full_text)
        exact = (full_text[start:end].strip(), start, end, "subject_heading_exact")
        # Only a contents entry ("# 목 차 … # 생명과학실험") may have been
        # exact; the course's plan can open further on under a fuller title.
        if end - start >= MIN_SUBJECT_SECTION_CHARS:
            return exact
        stub = visible_text(exact[0])
        if "수행평가" in compact_text(stub) or re.search(r"\[\s*(?:10|12)\S{1,8}\s*-\s*\d", stub):
            return exact
        return _subject_section_by_mentions(full_text, lines, subject, targets)
    return _subject_section_by_mentions(full_text, lines, subject, targets)


def _subject_section_by_mentions(
    full_text: str, lines: list[tuple[int, int, str]], subject: str, targets: tuple[str, ...]
) -> tuple[str, int, int, str]:
    target = targets[0]

    bracketed_subject = re.compile(
        r"[\[(‘'\"]\s*(?:[1-3]\s*학년\s*)?(?:"
        + "|".join(_subject_spellings(subject))
        + r")\s*[\])’'\"]"
    )
    mentions: list[int] = []
    heading_mentions: list[int] = []
    toc_mentions: list[int] = []
    for index, (_, _, raw) in enumerate(lines):
        shown = visible_text(raw)
        compact = compact_text(shown)
        # Course identity must occur on a cover/heading line.  Substring-only
        # matching made the short course name "대수" match "기대수행" in every
        # rubric and caused a whole multi-subject ZIP to be treated as 대수.
        title_marker = any(
            marker in compact for marker in (*COURSE_HEADING_MARKERS, *COURSE_TITLE_VARIANT_MARKERS)
        )
        course_identity = bool(
            target
            and _names_course(shown, targets)
            and (title_marker or bool(bracketed_subject.search(shown)))
        )
        # A single-subject plan may name its course only in the cover table
        # ("과목명 │ 생명과학Ⅱ │ 학점 │ 3").  The cell must hold the course
        # alone: "생명과학" in a 과목명 cell does not identify 생명과학Ⅱ.
        if not course_identity and any(value in targets for value in _cover_subject_values(raw)):
            mentions.append(index)
            continue
        if course_identity:
            mentions.append(index)
            if title_marker or _bracketed_course_h1(raw, shown):
                # A table-of-contents entry ("…평가계획 ·········· 55") names
                # the course but opens nothing; it is tried last.
                if TOC_LINE_RE.search(shown):
                    toc_mentions.append(index)
                else:
                    heading_mentions.append(index)
    heading_mentions.extend(toc_mentions)
    start_index: int | None = None
    if heading_mentions:
        # Prefer the first heading whose section is more than a stub: a cover
        # sheet or a repeated running title can also carry the course name.
        for candidate in heading_mentions:
            candidate_end = _subject_section_end(lines, candidate + 1, targets)
            section_stop = lines[candidate_end][0] if candidate_end < len(lines) else len(full_text)
            section_text = full_text[lines[candidate][0]: section_stop]
            if len(section_text) >= MIN_SUBJECT_SECTION_CHARS or "<table" in section_text or "\n|" in section_text:
                start_index = candidate
                break
        if start_index is None:
            start_index = heading_mentions[0]
    if start_index is None:
        if not mentions:
            return full_text, 0, len(full_text), "subject_heading_not_found"
        # A single-subject source often names the subject only in a cover table.
        # Start at that source-authored identity instead of copying unrelated
        # front matter before it.
        start_index = mentions[0]
        search_from = mentions[0] + 1
        status = "subject_mention_only"
    else:
        search_from = start_index + 1
        status = "subject_heading"

    end_index = _subject_section_end(lines, search_from, targets)
    start = lines[start_index][0] if lines else 0
    end = lines[end_index][0] if end_index < len(lines) else len(full_text)
    return full_text[start:end].strip(), start, end, status


COURSE_TITLE_LEAD_RE = re.compile(r"^\s*(?:#{1,6}\s*)?\d{4}\s*학년도")
MISLABELLED_FORM_LINES = 6


def _lines_of_text_between(lines: list[tuple[int, int, str]], start: int, end: int) -> int:
    return sum(1 for index in range(start + 1, end) if visible_text(lines[index][2]).strip())


def _split_course_title_start(
    lines: list[tuple[int, int, str]], index: int, floor: int, targets: tuple[str, ...]
) -> int | None:
    """Where another course's title begins when it is split over two lines.

    "2026학년도 1학기 체육(2)과목" then "교수학습 및 평가 운영 계획", or
    "# 2026학년도 [2]학년 2학기 [프랑스어 독해와 작문Ⅰ]" then "# 교수학습·평가
    계획서": the second line is a bare plan title, the line above it names the
    course.  Any course counts, known or not ("공통국어1", "정보 처리와 관리").
    """

    shown = visible_text(lines[index][2])
    compact = compact_text(shown)
    if not (
        "교수학습" in compact
        and GENERIC_PLAN_TITLE_RE.fullmatch(compact_text(TITLE_PERIOD_PREFIX_RE.sub("", shown)))
    ):
        return None
    previous = next(
        (
            back
            for back in range(index - 1, max(floor, index - 3) - 1, -1)
            if visible_text(lines[back][2]).strip()
        ),
        None,
    )
    if previous is None or previous < floor:
        return None
    previous_raw = lines[previous][2]
    joined = visible_text(previous_raw) + " " + shown
    if _mentions_course(joined, targets):
        return None
    if (
        COURSE_TITLE_LEAD_RE.match(previous_raw)
        or _bracketed_course_h1(previous_raw, joined)
        or _course_in_title(joined)
    ):
        return previous
    return None


PLAN_TITLE_WORDS_RE = re.compile(
    r"\d{4}\s*학년도|\d\s*학년|\d\s*학기|교수\s*[·‧․・\-]?\s*학습|및|평가|운영|계획서?|방법|교과|과목|"
    r"[\[\]()（）#\s·‧․,]"
)


def _line_opens_other_course(raw: str, targets: tuple[str, ...]) -> bool:
    """A title line opening another course's plan, whatever its heading level.

    "2026학년도 1학기 3학년 체육전공 실기기초 교수·학습 및 평가 운영 계획",
    "## 2026학년도 2학년 1학기 [일본어회화] 교과 공주영명고등학교",
    "## 1 체육1 교수학습-평가 계획 및 방법".  The course may be one the
    parser does not know; a line naming none ("2026학년도 1학기 교수학습 및
    평가 운영 계획") is this course's own title.
    """

    stripped = raw.strip()
    zip_member = ZIP_MEMBER_RE.match(stripped)
    if zip_member:
        # "[zip:양서고 1학년 논리와사고 교수학습 계획서.pdf][ok]" -- another
        # course's file; "[zip:과학_2-1. … 과학과 평가계획 …]" is the
        # department's, which holds this course too.
        member = zip_member.group("name")
        return not (
            _mentions_course(member, targets)
            or re.search(r"과학\s*(?:과|교과)(?!목)|과학_|과학\s*평가", member)
        )
    shown = visible_text(raw).strip()
    compact = compact_text(shown)
    if not 6 <= len(compact) <= 90 or _mentions_course(shown, targets):
        return False
    # A sentence about the plan ("… 계획에 따라 출제한다.") is not its title.
    if re.search(r"(?:다|함|음)\s*[.。]?$|따라|의거", shown):
        return False
    # The next course's cover table ("과목명 │ 미술 감상과 비평"); not a header
    # row ("학년 │ 대상 학급 │ 과목명 │ 학점수").
    if len(re.findall(r"<th\b", raw, flags=re.I)) < 3 and any(
        len(re.findall(r"[가-힣A-Za-z]", value)) >= 2
        and not re.search(r"(?:학점|시수|시간|학급|교사|학년|학기|구분|단위)\w*$", value)
        and not (_mentions_course(value, targets) or any(value in name for name in targets))
        for value in _cover_subject_values(raw)
    ):
        return True
    plan = "교수학습" in compact and bool(re.search(r"계획|방법", compact))
    bracket = re.search(r"\[\s*([^\[\]]{2,20})\s*\]", shown)
    # …also a title cell ("2026학년도 1학기 진로와 직업과 평가 계획서").
    if COURSE_TITLE_LEAD_RE.match(raw) or COURSE_TITLE_LEAD_RE.match(shown):
        plan = plan or bool(re.search(r"평가계획서?$|평가운영계획서?$", compact))
    if (COURSE_TITLE_LEAD_RE.match(raw) or COURSE_TITLE_LEAD_RE.match(shown)) and (plan or bracket):
        residual = re.sub(r"\S*(?:고등학교|학교)(?=\s|$)", "", shown)
        residual = re.sub(r"\d+|학년도|년도|학년|학기", "", PLAN_TITLE_WORDS_RE.sub("", residual))
        residual = re.sub(r"(?:과목|교과|과)+$", "", compact_text(residual))
        # "[통합과학]" is 통합과학1 written short, not another course.
        return len(residual) >= 2 and not any(
            name.startswith(residual) or residual.startswith(name) for name in targets
        )
    table_cells = len(re.findall(r"<t[hd]\b", raw, flags=re.I))
    if plan and table_cells < 2 and len(compact) <= 40 and re.search(r"(?:계획|계획서|방법)$", compact):
        unnumbered = re.sub(
            r"^\s*(?:#{1,6}\s*)?(?:\d{1,2}|[ⅠⅡⅢⅣⅤⅥ]|[IVX]{1,3})\s*[.)]?\s+", "", shown
        )
        head = re.split(r"교\s*수", unnumbered, maxsplit=1)[0]
        # "( 통합과학-물리 ) 과" is one part of 통합과학.
        head = re.split(r"\s*[-–_]\s*", head, maxsplit=1)[0]
        head = re.sub(r"[\[\]()（）〔〕【】<>]", " ", head)
        head = re.sub(r"\d{4}\s*(?:학)?년도|\d\s*학년|\d\s*학기|\d+|학년|학기", " ", head)
        named = re.sub(r"(?:과목|교과|과)+$", "", compact_text(head))
        # "AP일반생물학Ⅰ 교수학습 및 평가계획서", "논리와 사고과 교수·학습 운영 계획";
        # not "본교 교수학습 계획" or "월별 교수학습 계획".
        # A course name is short and joins no topics with "및" ("범교과 주제 및
        # 사회정서교육", "수업 목표 및" are sections of this plan).
        # Nor is the department ("과학"), the template's placeholder ("과목명")
        # or a breakdown ("성취기준별", "단원별") a course.
        return (
            2 <= len(named) <= 12
            and "및" not in named
            and not named.endswith("별")
            and not re.search(r"성취기준|단원|평가|과목명|교과목", named)
            and named not in {"본교", "우리학교", "학교", "과학", "과목", "교과", "연간"}
            and not any(name.startswith(named) or named.startswith(name) for name in targets)
        )
    return False


def _exact_section_bounds(
    lines: list[tuple[int, int, str]],
    course_headings: list[tuple[int, str]],
    position: int,
    subject: str,
    target: str,
) -> tuple[int, int, int]:
    """Start/end line indexes of the section an exact course heading opens."""

    start_index = course_headings[position][0]
    end_index = len(lines)
    start_heading = re.match(r"^\s*(#{1,3})\s+", lines[start_index][2])
    start_level = len(start_heading.group(1)) if start_heading else 3
    for next_position in range(position + 1, len(course_headings)):
        line_index, next_course = course_headings[next_position]
        if next_course != subject:
            end_index = line_index
            break
    # A combined plan can place biology next to English, arts, or a
    # vocational course.  The canonical list above intentionally knows
    # only biology, so also stop at a peer-level heading that visibly
    # opens another course plan.  Without this boundary, a short
    # ``# 통합과학1`` heading could absorb every following subject.
    for line_index in range(start_index + 1, end_index):
        raw = lines[line_index][2]
        split_title = _split_course_title_start(lines, line_index, start_index + 1, (target,))
        if split_title is not None:
            end_index = split_title
            break
        # A school that reused another course's form may leave its name in a
        # plain line right under this course's title ("1 공통국어1과 교수학습
        # 운영 계획"); the plan that follows is still this course's.  A heading
        # naming another course ("## 1 화학실험 …") is that course.
        if (
            (
                re.match(r"^\s*#", raw)
                or _lines_of_text_between(lines, start_index, line_index) > MISLABELLED_FORM_LINES
            )
            and _line_opens_other_course(raw, _subject_targets(subject))
        ):
            end_index = line_index
            break
        heading = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", raw)
        if not heading:
            # kordoc reads many PDF title lines as plain paragraphs; a short
            # one naming another course still opens that course
            # ("2026학년도 1학기 지구과학Ⅱ", "(체육1)과 교수학습 계획서").
            if _plain_title_line(raw):
                shown = visible_text(raw)
                other = compact_text(title_course_part(shown))
                if _opens_other_bracketed_course(shown, target) or (
                    other != target and OTHER_COURSE_HEADING_RE.fullmatch(other)
                ):
                    end_index = line_index
                    break
            continue
        if len(heading.group(1)) > start_level:
            continue
        shown = visible_text(heading.group(2))
        compact = compact_text(shown)
        if target in compact:
            continue
        if _opens_other_bracketed_course(shown, target):
            end_index = line_index
            break
        opens_course_plan = (
            "교수학습" in compact
            and "평가" in compact
            and any(term in compact for term in ("계획", "운영", "방법"))
            # "# 교수학습 평가계획" right under "# 생명과학" is this plan's own
            # title box split into lines; only a title naming something opens
            # another course's plan.
            and not GENERIC_PLAN_TITLE_RE.fullmatch(
                compact_text(TITLE_PERIOD_PREFIX_RE.sub("", shown))
            )
        )
        # ``# 체육`` / ``# 화학`` after ``# 생명과학``: a peer heading as
        # short as a course name, with none of the words a section inside
        # one course plan would carry, opens the next course.
        opens_other_course = (
            len(heading.group(1)) <= start_level
            and bool(OTHER_COURSE_HEADING_RE.fullmatch(compact_text(title_course_part(shown))))
        )
        if opens_course_plan or opens_other_course:
            end_index = line_index
            break
    return start_index, end_index, start_level


_NON_COURSE_BRACKET_RE = re.compile(r"학기|학년|\d+\s*(?:점|%|회|차)|예시|공통|선택|필수")


def _plain_title_line(raw: str) -> bool:
    """A short paragraph line that may be a title kordoc did not mark as one.

    Numbered lines ("2. 생명과학") are list or table-of-contents entries and
    never count; only a ``#`` heading may carry a section number.
    """

    stripped = raw.strip()
    return (
        bool(stripped)
        and len(stripped) <= STANDALONE_TITLE_MAX_CHARS
        and not stripped.startswith(("<", "|", "[zip:", "#"))
        and not LEADING_SECTION_NUMBER_RE.match(stripped)
    )


def _opens_other_bracketed_course(shown: str, target: str) -> bool:
    """"2026학년도 1학기 (체육1)과 교수학습 계획서": a title naming a different course.

    The bracketed name must be a known course name, or the line must carry the
    words of a course-plan title; "(30%)", "(2학기)" or "(예시)" never qualify.
    """

    bracket = COURSE_TITLE_BRACKET_RE.search(shown)
    if not bracket:
        return False
    name = compact_text(bracket.group(1))
    if not name or name == target or target in name or _NON_COURSE_BRACKET_RE.search(bracket.group(1)):
        return False
    if OTHER_COURSE_HEADING_RE.fullmatch(name):
        return True
    compact = compact_text(shown)
    return len(re.findall(r"[가-힣]", name)) >= 2 and ("교수학습" in compact or "평가계획" in compact)


SUBJECT_NUMERAL_SWAP = {"II": "2", "I": "1", "2": "II", "1": "I"}
COVER_SUBJECT_CELL_RE = re.compile(
    r"<t[dh][^>]*>\s*(?:교\s*)?과\s*목\s*(?:명)?\s*</t[dh]>\s*<t[dh][^>]*>(.*?)</t[dh]>|"
    r"^\s*\|\s*(?:교\s*)?과\s*목\s*(?:명)?\s*\|\s*([^|]+?)\s*\|",
    re.S,
)
COVER_LABEL_VALUE_RE = re.compile(
    r"학점|학년|단위수?|시수|교과(?:군)?|담당(?:교사)?|학기|구분|영역|내용|시간|비고|"
    r"성취기준|이수학점|운영학기|과목유형|교과목명?|과목명?"
)


def _subject_targets(subject: str) -> tuple[str, ...]:
    """Compact spellings of a course name: 생명과학Ⅱ is also written 생명과학2."""

    target = compact_text(subject)
    match = re.fullmatch(r"(.+?)(II|I|2|1)", target)
    if not match:
        return (target,)
    return (target, match.group(1) + SUBJECT_NUMERAL_SWAP[match.group(2)])


def _subject_spellings(subject: str) -> list[str]:
    """Regex alternatives for a course name as printed, numeral either way."""

    # "세포와 물질대사" is also printed "세포와물질대사".
    spellings = [re.escape(subject).replace(r"\ ", r"\s*")]
    match = re.fullmatch(r"(.+?)\s*([ⅠⅡ12])", subject)
    if match:
        swap = {"Ⅰ": "1", "Ⅱ": "2", "1": "Ⅰ", "2": "Ⅱ"}[match.group(2)]
        spellings.append(re.escape(match.group(1)) + r"\s*" + swap)
    return spellings


def _cover_subject_values(raw: str) -> list[str]:
    """Compact values of 과목명 cells in one cover-table row.

    A header row ("교과 │ 과목 │ 학점") puts another label after the cell;
    that is a column header, not a course name.
    """

    values = []
    for first, second in COVER_SUBJECT_CELL_RE.findall(raw):
        value = compact_text(visible_text(first or second))
        if value and not COVER_LABEL_VALUE_RE.fullmatch(value) and not value.isdigit():
            values.append(value)
    return values


# An outline number opening a line ("2 월별 …", "Ⅱ. 평가 계획", "가) …"),
# never the four-digit year that opens a course title ("2026학년도 …").
SECTION_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\d{1,2}(?!\d)|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]|[IVX]{1,4}(?![A-Za-z])|[가-하](?=\s*[.)]))\s*[.)]?\s"
)


def _course_key_text(shown: str) -> str:
    """Compact text for finding a course name, without grade/semester numbers.

    "(생명과학)_2학년" must not read as 생명과학2 (= 생명과학Ⅱ).
    """

    # "(세포와 물질대사) (2)학년": 괄호 속 학년 숫자도 지운다.
    return compact_text(
        re.sub(r"[(（\[]?\s*\d\s*[)）\]]?\s*(?:학년|학기|차)", " ", shown)
    )


def _names_course(shown: str, targets: tuple[str, ...]) -> bool:
    """Whether ``shown`` names one of ``targets`` as a whole course name.

    Used where a line *opens* a course's section.  A substring test read
    "(생명과학Ⅱ)" as 생명과학, "통합과학 1" as the 2015 통합과학 and "고급
    생명과학" as 생명과학, and so opened the wrong course's section.  A course
    numeral right after the name (not the start of a longer number such as the
    year in "통합과학1(2026년 …)"), 실험 or a leading 고급 makes it another course.
    """

    # "(세포와 물질대사) (2)학년": 괄호 속 학년 숫자도 지운다. 문장부호는 남겨
    # "통합과학1,2"·"통합과학1(2026년"의 숫자 경계를 본다.
    key = re.sub(
        r"[\s~*_`]+",
        "",
        unicodedata.normalize(
            "NFKC", re.sub(r"[(（\[]?\s*\d\s*[)）\]]?\s*(?:학년|학기|차)", " ", shown)
        ),
    )
    for name in targets:
        start = 0
        while (at := key.find(name, start)) >= 0:
            after = key[at + len(name):]
            numeral = re.match(r"(?:II|I|[12])(?!\d)", after)
            if not numeral and not after.startswith("실") and not key[:at].endswith("고급"):
                return True
            start = at + 1
    return False


def _mentions_course(shown: str, targets: tuple[str, ...]) -> bool:
    """Whether a line still belongs to this course's section.

    Ending a section is judged loosely, as before: a school that reused a
    form ("과목명 │ 생명과학Ⅰ" over a 2022 생명과학 plan) must not lose the rest of
    its plan.  Another course's tasks that ride along are caught by their
    achievement codes (``_names_another_course``).
    """

    key = _course_key_text(shown)
    return any(name in key for name in targets)


def _course_in_title(shown: str) -> str:
    """The course a plan title line names before its 교수학습 words, or "".

    "2026학년도 1학기 지구과학 과목 교수학습·평가 계획" and "[체육]과
    교수·학습 평가 계획" name one; "1. 교수·학습 평가 계획" does not.
    """

    head = re.split(r"교\s*수", shown, maxsplit=1)[0]
    head = re.sub(r"[\[\]()（）〔〕【】<>『』「」]", " ", head)
    head = re.sub(r"^\s*(?:\d{4}\s*학년도|\d\s*학년|\d\s*학기|[,·\s])+", "", head)
    key = re.sub(r"(?:과목|교과|과)$", "", compact_text(head))
    return key if key and _names_a_course(key) else ""


def _names_a_course(value: str) -> bool:
    """Whether a compact cell value is a course name this parser knows."""

    return bool(OTHER_COURSE_HEADING_RE.fullmatch(value)) or any(
        value == compact_text(course) for course in EXPECTED_STANDARD_PREFIXES
    )


def _subject_section_end(
    lines: list[tuple[int, int, str]], search_from: int, target: str | tuple[str, ...]
) -> int:
    targets = (target,) if isinstance(target, str) else target
    for index in range(search_from, len(lines)):
        raw = lines[index][2]
        # The next course's own cover table closes this one.  Only a value
        # that is a course name counts: header rows ("과목 │ 학급") are common.
        if any(
            value not in targets and _names_a_course(value)
            for value in _cover_subject_values(raw)
        ):
            return index
        shown = visible_text(raw)
        compact = compact_text(shown)
        if _mentions_course(shown, targets) or not 3 <= len(compact) <= 120:
            continue
        if _bracketed_course_h1(raw, shown):
            return index
        # Plans that title every course "<과목> 교수학습·평가 계획" close one
        # course where the next one's title names another course.  The
        # department's own title ("생명과학과 교수학습·평가 운영 계획") names
        # the family the course belongs to, not a different course.
        named = _course_in_title(shown)
        if (
            named
            and any(marker in compact for marker in COURSE_TITLE_VARIANT_MARKERS)
            and not SECTION_NUMBER_PREFIX_RE.match(shown)
            and not any(name.startswith(named) for name in targets)
        ):
            return index
        split_title = _split_course_title_start(lines, index, search_from, targets)
        if split_title is not None:
            return split_title
        if (
            re.match(r"^\s*#", raw)
            or _lines_of_text_between(lines, search_from - 1, index) > MISLABELLED_FORM_LINES
        ) and _line_opens_other_course(raw, targets):
            return index
        if any(marker in compact for marker in COURSE_HEADING_MARKERS):
            # "2 월별 교수학습 및 평가 방법" is a numbered part of this course's
            # plan, and a bare "교수학습 및 평가 운영 계획" right under the
            # title line is the rest of that title, split over two lines.
            if SECTION_NUMBER_PREFIX_RE.match(shown) or index <= search_from + 1:
                continue
            return index
    return len(lines)


BRACKETED_COURSE_RE = re.compile(r"[\[(（]\s*[가-힣ⅠⅡ0-9A-Za-z·\s]{2,20}\s*[\])）]\s*(?:과|교과)?")


def _bracketed_course_h1(raw: str, shown: str) -> bool:
    """``# 2026학년도 1학기 (체육1)과 교수학습 계획서``: a per-course H1 in a combined plan."""

    if not re.match(r"^\s*#\s", raw):
        return False
    compact = compact_text(shown)
    return bool(BRACKETED_COURSE_RE.search(shown)) and ("교수학습" in compact or "평가계획" in compact)


PROSE_SENTENCE_END_RE = re.compile(r"(?:다|음|함|됨|것|바람)\s*[.。]?\s*$")


def _is_source_heading(line: str) -> bool:
    """Return true only for a line the source itself presents as a heading.

    Korean plans number both section headings and 평가 방침 prose with 가/나/다,
    so the numbering alone proves nothing.  Two things separate them: a prose
    item is written as a Markdown list bullet (``- 나. …``), and it ends like a
    sentence (``…배점 등을 사전에 알리고 충분히 설명하여 준비하게 한다.``).
    Treating those as headings anchored whole assessment blocks to a policy
    paragraph, which then published the plan's summary table as if it were one
    performance assessment.
    """

    if re.match(r"^\s*[-*•▪]\s", line):
        return False
    shown = visible_text(line)
    # The ``#`` marker is not by itself proof either: PDF-to-Markdown extraction
    # promotes every wrapped 평가 방침 line to ``## …`` ("## 도에는 활용하되
    # 수행평가 배점에는 포함되지 않도록 유의한다."), and such a line then
    # anchored the whole block above the real 세부 기준 section.  A sentence
    # ending is what still separates the two.
    if re.match(r"^\s*#{1,6}\s+", line):
        return not PROSE_SENTENCE_END_RE.search(shown)
    if not re.match(r"^\s*(?:\d{1,2}|[가-하])\s*[.)]\s*", shown):
        return False
    return not PROSE_SENTENCE_END_RE.search(shown)


# One assessment's detail table names its own achievement standard and rubric.
# A whole-plan summary table instead lines the exams up against the
# performance assessments, so it names 정기시험/지필평가 and a 합계 column.
DETAIL_TABLE_REQUIRED = ("성취기준",)
DETAIL_TABLE_RUBRIC = ("평가기준", "채점기준", "성취수준")
DETAIL_TABLE_WEIGHT = ("만점", "반영비율", "배점")
PLAN_SUMMARY_MARKERS = ("정기시험", "지필평가", "합계", "고사명", "평가종류", "평가유형")


def _table_after_heading(lines: list[tuple[int, int, str]], index: int) -> str:
    """Return the table that a heading introduces, or "" when none follows."""

    cursor = index + 1
    seen = 0
    while cursor < len(lines) and seen < 3:
        raw = lines[cursor][2]
        if not raw.strip():
            cursor += 1
            continue
        if re.search(r"<table\b", raw, flags=re.I):
            chunk: list[str] = []
            depth = 0
            while cursor < len(lines):
                current = lines[cursor][2]
                chunk.append(current)
                depth += len(re.findall(r"<table\b", current, flags=re.I))
                depth -= len(re.findall(r"</table>", current, flags=re.I))
                cursor += 1
                if depth <= 0:
                    break
            return "\n".join(chunk)
        seen += 1
        cursor += 1
    return ""


def _introduces_assessment_detail_table(
    lines: list[tuple[int, int, str]], index: int
) -> bool:
    """True when this heading is followed by one assessment's own detail table.

    Some plans drop the ``4. 수행평가 세부 계획`` line during PDF extraction, so
    the only remaining evidence that the detail section started is the table
    itself.  Reading the table lets the block start at the right place instead
    of falling back to a 평가 방침 paragraph further up.
    """

    raw = lines[index][2]
    if not _is_source_heading(raw):
        return False
    title = _clean_heading_title(visible_text(raw))[0]
    # 여기서 찾는 것은 과제명이 아니라 세부 계획 구간의 시작 헤딩이다. 그 헤딩은
    # 원래 문서 구조 라벨이므로("평가 영역 및 반영 비율") 방침 문장 판정을 끄고
    # 본다 -- 켜면 정상 앵커까지 사라져 케이스 전체가 unbounded 로 떨어진다.
    if not title or heading_title_is_structural(title, policy_prose=False):
        return False
    table = _table_after_heading(lines, index)
    if not table:
        return False
    compact = compact_text(visible_text(table))
    if any(marker in compact for marker in PLAN_SUMMARY_MARKERS):
        return False
    return (
        all(marker in compact for marker in DETAIL_TABLE_REQUIRED)
        and any(marker in compact for marker in DETAIL_TABLE_RUBRIC)
        and any(marker in compact for marker in DETAIL_TABLE_WEIGHT)
    )


def _anchor_score(line: str) -> int:
    shown = visible_text(line)
    compact = compact_text(shown)
    if "수행평가" not in compact:
        return 0
    if any(
        term in compact
        for term in (
            "참고할것",
            "기본점수",
            "미응시",
            "재응시",
            "결시자",
            "공통적용",
            "유의사항",
            "인정점",
        )
    ):
        return 0
    if "수행평가영역별성취기준" in compact:
        return 110
    if (
        "수행평가세부기준" in compact
        or "수행평가세부계획" in compact
        or "수행평가과제별세부계획" in compact
    ):
        return 105
    if re.fullmatch(r"(?:나|다)?수행평가", compact):
        return 75
    # Many plans use a short source heading such as ``라. 수행평가 영역 및
    # 배점``.  It is a reliable block anchor only when it is visibly a heading,
    # not when the same words occur in prose or a schedule table.
    if len(compact) <= 60 and any(
        term in compact for term in ("세부", "계획", "기준", "영역", "과제", "배점")
    ):
        # A section heading is short.  PDF line wrapping cuts a 평가 방침
        # sentence mid-word ("…실시 가능한 수행평"), so it can slip past the
        # sentence-ending test -- length is the signal that survives wrapping.
        if _is_source_heading(line) and len(compact) <= 30:
            return 90
        # Demoted, not discarded, and only for a line the source numbered:
        # a 평가 방침 item such as ``- 다. 수행평가의 세부 계획과 … 한다.`` must
        # never outrank the real detail section, but where a plan offers no
        # other candidate it still marks a better start than the document top.
        # Free-running prose stays unanchorable, as it was before.
        if re.match(r"^\s*[-*•▪]?\s*(?:\d{1,2}|[가-하])\s*[.)]\s*", visible_text(line)):
            return 10
    return 0


def assessment_block(subject_markdown: str) -> tuple[str, int, int, str]:
    lines = _line_offsets(subject_markdown)
    anchors = [(_anchor_score(raw), index) for index, (_, _, raw) in enumerate(lines)]
    anchors = [value for value in anchors if value[0] > 0]
    # Deliberately ranked *below* every textual anchor (90/105): this is a
    # last-resort anchor for plans whose own "수행평가 세부 계획" heading was
    # lost in extraction. Ranking it higher moved the block start past
    # assessments that a weaker-but-earlier heading had introduced correctly.
    anchors.extend(
        (85, index)
        for index in range(len(lines))
        if _introduces_assessment_detail_table(lines, index)
    )
    ranked = sorted(anchors, key=lambda value: (-value[0], value[1]))
    # Policy prose ("나. 수행평가 … 객관성을 유지한다") outranks nothing when
    # the block it opens holds no assessment table: try each anchor in score
    # order and keep the first whose block actually contains one.
    fallback: tuple[int, int] | None = None
    for _score, anchor_index in ranked:
        end_index = _block_end_index(lines, anchor_index)
        start = lines[anchor_index][0]
        end = lines[end_index][0] if end_index < len(lines) else len(subject_markdown)
        block = subject_markdown[start:end]
        if _has_assessment_table(block) or _heading_candidates(block):
            return block.strip(), start, end, "assessment_anchor"
        if fallback is None:
            fallback = (start, end)
    table_index = _first_assessment_table_line(lines)
    if table_index is not None:
        anchor_index = table_index
        for back in range(1, 5):
            candidate = table_index - back
            if candidate < 0:
                break
            raw = lines[candidate][2]
            if not raw.strip():
                continue
            if _is_source_heading(raw):
                anchor_index = candidate
            break
        end_index = _block_end_index(lines, anchor_index)
        start = lines[anchor_index][0]
        end = lines[end_index][0] if end_index < len(lines) else len(subject_markdown)
        # A block opened by its table rather than by a source heading: good
        # enough to bound headed items and matrix/rubric tables inside it, but
        # not evidence enough to publish a bare summary table's titles.
        return subject_markdown[start:end].strip(), start, end, "assessment_table_anchor"
    if fallback is not None:
        start, end = fallback
        return subject_markdown[start:end].strip(), start, end, "assessment_anchor"
    return subject_markdown, 0, len(subject_markdown), "assessment_anchor_not_found"


def _block_end_index(lines: list[tuple[int, int, str]], anchor_index: int) -> int:
    for index in range(anchor_index + 1, len(lines)):
        raw = lines[index][2]
        if "<" in raw:
            continue
        shown = visible_text(raw)
        if not BLOCK_END_RE.search(shown):
            continue
        if re.match(r"^(?:#{1,6}\s*)?(?:\|\s*)?(?:\d+|[가-하])\s*[.)|]", raw.strip()):
            return index
    return len(lines)


ASSESSMENT_TABLE_MARKER_RE = re.compile(
    r"성취기준|평가요소|채점기준|평가기준|배점|반영비율|영역만점|평가척도|수행평가"
)


def _has_assessment_table(block: str) -> bool:
    for _start, _end, fragment in _table_fragments_with_spans(block):
        if ASSESSMENT_TABLE_MARKER_RE.search(compact_text(visible_text(fragment))):
            return True
    return False


def _first_assessment_table_line(lines: list[tuple[int, int, str]]) -> int | None:
    """Line index of the first table that visibly belongs to a performance assessment."""

    for index, (_, _, raw) in enumerate(lines):
        if not (re.search(r"<table\b", raw, flags=re.I) or (
            raw.strip().startswith("|") and index + 1 < len(lines)
            and PIPE_SEPARATOR_RE.fullmatch(lines[index + 1][2])
        )):
            continue
        chunk = _table_after_heading(lines, index - 1) if "<table" in raw.lower() else "\n".join(
            line[2] for line in lines[index: index + 40]
        )
        compact = compact_text(visible_text(chunk))
        if "수행평가" in compact and (
            "성취기준" in compact or "평가요소" in compact or "반영비율" in compact or "채점기준" in compact
        ):
            return index
        if ("평가요소" in compact or "채점기준" in compact) and ("배점" in compact or "점수" in compact):
            return index
    return None


# A meta-label that a <br>-joined source cell appends after the real name.
# The numbering is required: it is the evidence that a *new* source line was
# glued on. Without it, "수행평가 영역별 평가 요소 및 채점 기준" is one heading,
# not a name with a label stuck to it.
GLUED_META_LABEL_RE = re.compile(
    r"\s+(?:\d+\s*[).]|[가-하]\s*[).])\s*"
    r"(?:평가\s*단원|영역별\s*성취\s*기준|성취\s*기준|평가\s*요소|채점\s*기준|"
    r"평가\s*방법)\s*[:：]?.*$"
)


def strip_title_decoration(title: str) -> str:
    """Drop source decoration that is not part of the name the school wrote.

    Two artefacts ride along with an otherwise correct title: a list glyph the
    plan uses to bullet the cell (``• 과학 페임랩 발표하기``), and -- in HWP
    documents whose table markup arrives double-escaped -- the next ``<br>``
    line of field labels glued onto the end of the name.  Both are formatting,
    so they are removed from the displayed title while ``title_raw`` keeps the
    exact source string.
    """

    cleaned = _rejoin_split_syllables(PRIVATE_USE_GLYPH_RE.sub("", title))
    # "가. . 실험활동 평가", "⚪우리나라로 유입된 외래생물 탐구하기"
    cleaned = re.sub(r"^[\s•·∙‣▪▫◦●○⚪⚫◯◎◆◇▶▷►➢※*・ㆍ・.．]+", "", cleaned).strip()
    cleaned = GLUED_META_LABEL_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:|·")
    # 다듬기 전 모양이 문서 구조 제목이면 그대로 둔다: "교육과정 성취기준 및"(평가 기준을
    # 뗀 소제목)에서 "및"을 지우면 구조 제목 판정을 비켜 과제 머리글로 잡힌다.
    unmended = _strip_name_affixes(cleaned)
    if heading_title_is_structural(unmended, policy_prose=False) or (
        NOT_A_TASK_DOCUMENT_SECTION_RE.search(unmended)
    ):
        return unmended
    return _close_cut_title(_strip_name_affixes(_close_cut_title(cleaned)))


def _close_cut_title(title: str) -> str:
    """Mend a name the source cell cut off: "산과 염기의 중화 반응(",
    "식물군집 분석(방형구법", "효소 활성 영향 요인 실험 및"."""

    cleaned = title
    for _ in range(3):
        before = cleaned
        # 쉼표로 끝난 줄은 그대로 둔다: 방침 문장이 잘린 표시라 구조 제목 판정이 본다.
        cleaned = re.sub(r"\s*[(（\[]\s*$|\s+(?:및|또는|와|과)$", "", cleaned).strip()
        if cleaned.count("(") + cleaned.count("（") > cleaned.count(")") + cleaned.count("）"):
            cleaned += ")"
        if cleaned == before:
            break
    return cleaned if len(compact_text(cleaned)) >= 2 else title


def _rejoin_split_syllables(title: str) -> str:
    """"우주 배 경 복사의 발 견 과정 알 아보 기" -> "우주배경복사의발견과정알아보기".

    A PDF converter that spaced syllables apart leaves many one-syllable
    pieces; joining them is closer to the school's name than the broken
    spacing.
    """

    pieces = title.split()
    single = sum(1 for piece in pieces if re.fullmatch(r"[가-힣]", piece) and piece not in {"및", "등"})
    average = sum(len(piece) for piece in pieces) / len(pieces) if pieces else 0
    if (single >= 3 and single * 5 >= len(pieces) * 2) or (
        single >= 2 and len(pieces) >= 6 and average <= 3.2
    ):
        return "".join(pieces)
    return title


# Notes and labels a school writes around the name in the same cell.  Each
# is removed only where it sits: a trailing note, a leading label.
NAME_TRAILING_NOTE_RES = (
    # "(각 15점, 총 30점)", "(모둠 평가, 10%, 100점)" -- a whole bracket of
    # scores, taken before the "30점)" rule below can cut it in half.
    re.compile(r"\s*[(（][^()（）]*\d+\s*(?:점|%)[^()（）]*[)）]\s*$"),
    # "- 반영비율 20%", ": 100점, 40%", "- 2회차", "(심화탐구영역)", "… 평가 영역"
    re.compile(r"\s*[-–:：]\s*반영\s*비율\s*\d+(?:\.\d+)?\s*%\s*$"),
    re.compile(r"\s*[:：]\s*\d+\s*점\s*[,，]\s*\d+(?:\.\d+)?\s*%\s*$"),
    re.compile(r"\s*[-–]\s*\d+\s*회\s*차\s*$"),
    re.compile(r"\s*[(（][^()（）]{0,8}영역[)）]\s*$"),
    re.compile(r"(?<=\S)\s+평가\s*영역(?:별)?\s*$"),
    re.compile(r"(?<=[)）])\s*영역별?\s*$"),
    # "(수행평가 과제명으로 교육정보시스템에 입력 사항임)", "(관련 성취기준: …)"
    re.compile(r"\s*[(（][^()（）]*(?:입력|기재)\s*(?:사항|함|됨)[^()（）]*[)）]\s*$"),
    re.compile(r"\s*[(（]\s*(?:관련\s*)?성취\s*기준[^()（）]*[)）]?\s*$"),
    # "(서·논술형 평가)", "(논술형)", "(PBL 평가)", "(융합적 탐구 역량 평가)",
    # "[서·논술형], [프로젝트형]" -- the kind of assessment, which the method
    # field already shows.
    re.compile(
        r"(?:\s*[,，]?\s*[(（\[][^()（）\[\]]{1,24}(?:형|평가)\s*[)）\]])+\s*$"
    ),
    # "(2순위)" -- the tie-break rank of the task
    re.compile(r"\s*[(（]\s*(?:동점자\s*)?\d+\s*순위\s*[)）]\s*$"),
    # "… 탐구 프로젝트- 1회"
    re.compile(r"\s*[-–:：]\s*\d+\s*회(?:\s*실시)?\s*$"),
    # "(20%)", "[40점]", "(총 10점)", "(100점 만점)"
    re.compile(
        r"\s*[(（\[]\s*(?:총\s*점?|배점|반영\s*비율)?\s*[:：]?\s*\d+(?:\.\d+)?\s*(?:점|%)"
        r"(?:\s*만점)?\s*[)）\]]\s*$"
    ),
    # "… 비교 분석) : 100점, 25% ⦁성취기준 및 평가요소" -- only after a
    # bracketed name; "반영 비율 및 배점 : 10점" is a label line, kept whole.
    re.compile(r"(?<=[)）])\s*[:：]\s*\d+\s*점\s*(?:[,，]\s*\d+(?:\.\d+)?\s*%)?.*$"),
)
NAME_TRAILING_NOTE_RES += (
    # "교과심화탐구 평가의 실제" -- the heading of the worked example under a task
    re.compile(r"\s*평가의\s*실제\s*$"),
)
NAME_TRAILING_NOTE_RES += (
    # "(2종)", "(총 30점) (3회 실시 후 합산)", "10점)", "〔40%〕", "〔100점, 30%〕",
    # "(논술2)", "(수행평가1)", "(구술, 발표)" -- counts, scores and the kind of
    # assessment written after the name
    re.compile(
        r"(?:\s*(?:[(（]\s*(?:\d+\s*종|총\s*\d+\s*점|\d+\s*회\s*실시[^()（）]*|논술형?\s*\d*|"
        r"수행\s*평가\s*\d+|(?:구술|발표|논술|서술|실험|실습|토론|토의|보고서|포트폴리오)"
        r"(?:\s*[,，·]\s*(?:구술|발표|논술|서술|실험|실습|토론|토의|보고서|포트폴리오))*)\s*[)）]"
        r"|〔[^〔〕]*〕|\d+\s*점\s*\)))+\s*$"
    ),
)
NAME_LEADING_COUNT_RE = re.compile(
    r"^(?:\d+\s*회\s*/\s*|"
    # "(영역2)", "(2순위)", "3순위 :", "1/", "이해 /", "지식/"
    r"[(（]\s*(?:영역\s*\d+|\d+\s*순위)\s*[)）]\s*|\d+\s*순위\s*[:：]\s*|\d\s*/\s*|"
    r"(?:이해|지식|적용|기능|태도|가치)\s*/\s*|"
    # "탐구 활동보고서평가1.국립 과천 과학관 …" -- a numbered area label
    r"[^\s.]{0,12}\s?[^\s.]{1,12}평가\s*\d+\s*[.．]\s*|"
    # "수행평가 영역별 세부기준 가. 현상을 꿰뚫는 …" -- the section heading above
    r"수행\s*평가\s*(?:영역별\s*)?세부\s*(?:계획|기준)\s*(?:[가-하]|\d{1,2})\s*[.)]\s*|"
    # "과정중심 수행평가 영역1:", "수행평가 3차 :", "수행평가 세부 기준 :",
    # "수행평가 세부계획 5-1.", "수행과제 1 -", "항목1 :", "영역1 포트폴리오",
    # "서술형평가 [20점] -", and a table cell's own "2. " -- labels and
    # numbering around the name, not the name.
    r"(?:과정\s*중심\s*)?수행\s*평가\s*(?:영역\s*)?\d+\s*(?:차\s*)?[:：]\s*|"
    r"수행\s*평가\s*세부\s*(?:기준|계획)\s*(?:\d+(?:\s*-\s*\d+)?\s*[.)]|[:：])\s*|"
    r"수행\s*과제\s*\d+\s*[-–:：]\s*|항목\s*\d+\s*[:：]\s*|영역\s*\d+\s+|"
    r"[^\[\]\s]{0,10}\s?\[\s*\d+\s*점\s*\]\s*[-–:：]\s*|"
    r"\d{1,2}\s*[.．](?!\d)\s*|"
    # "(심화탐구영역) 심화 탐구", "(심화탐구) 주제 탐구"
    r"[(（][^()（）]{0,8}(?:영역|탐구)[)）]\s*)(?=\S)"
)
NAME_LEADING_LABEL_RE = re.compile(
    # "평가과제:", "평가과제1(통합과학A):", "수행평가 영역명:", "영역명 :", "[프로젝트명]"
    r"^(?:(?:수행\s*)?(?:평가\s*)?(?:과제|영역)\s*명?\s*\d*\s*(?:[(（][^()（）]{1,15}[)）])?\s*[:：]"
    r"|\[[^\[\]]{1,12}\])\s*(?=\S)"
)
# "평가과제(파스퇴르의 … 구상하기)", "서·논술형수행평가(생물 특성과 …)",
# "실험·실습 1 (K-POP 속 과학 개념 분석 …)": a label naming only the kind
# of assessment, with the task itself in brackets.
# "수행평가 영역1", "평가 과제 2", "4순위 수행평가", "수행평가 3" -- a numbered
# label whose bracket holds the task.
NUMBERED_TASK_LABEL_RE = re.compile(
    r"(?:과정중심)?수행평가(?:영역)?\d+차?|(?:평가|수행)과제\d+|\d+순위수행평가"
)
NAME_IN_BRACKETS_RE = re.compile(r"^(?P<label>[^()（）]{1,16}?)\s*[(（](?P<inner>[^()（）]{4,})[)）]$")
# "Ⅰ. 과학의 본성과 역사 속의 과학 탐구 / 03. 우리 선조들의 과학 기술 발전
# 사례 찾기": a unit path ending in the task.  The path is the curriculum's;
# only the last step, when it names an activity, is the school's task.
UNIT_PATH_START_RE = re.compile(r"^\s*[ⅠⅡⅢⅣⅤⅥ](?:\s*[-.．]\s*\d*)?\s*[.．]?\s*")
UNIT_PATH_STEP_RE = re.compile(
    r"\s*(?:/|\s[-–—]\s|[-–—]\s*(?=[(（]?\d)|(?<!\d)(?=\b\d{1,2}\s*[.．]\s))\s*"
)


def _unit_path_task(title: str) -> str | None:
    """The task at the end of a unit path, "" when the path names no task.

    Returns None when the title is not a unit path at all.
    """

    if not UNIT_PATH_START_RE.match(title):
        return None
    last = UNIT_PATH_STEP_RE.split(title)[-1]
    last = re.sub(r"^\s*[(（]?\s*\d{1,2}\s*[.．)）]\s*", "", last).strip()
    # "개체군과 군집의 특성(과학적 사고력, 과학적 탐구능력)": the brackets
    # list competencies, not an activity.
    named = re.sub(r"\s*[(（][^()（）]*[)）]", "", last).strip()
    if named and last != title.strip() and (TASK_NAME_RE.search(named) or re.search(r"기$", named)):
        return last
    return ""


def _open_brackets(text: str) -> int:
    return text.count("(") + text.count("（") - text.count(")") - text.count("）")


def _strip_name_affixes(title: str) -> str:
    cleaned = title
    for _ in range(3):
        before = cleaned
        for note in NAME_TRAILING_NOTE_RES:
            stripped = note.sub("", cleaned).strip()
            # A note rule must not cut a bracket in half ("(1회당 20점, 총 40점)"
            # losing only "40점)").
            if len(compact_text(stripped)) >= 2 and _open_brackets(stripped) <= max(
                0, _open_brackets(cleaned)
            ):
                cleaned = stripped
        # "탐구 과정 포트폴리오: 15점", "탐구 활동 보고서- 100점", "(20점)," --
        # not "반영 비율 및 배점 : 10점", which is a label line kept whole.
        if not POLICY_LABEL_LINE_RE.match(cleaned):
            scored = re.sub(
                r"\s*(?:[:：\-–—]\s*\d+\s*점|[(（]\s*\d+\s*점\s*[)）])\s*[,，]?\s*$", "", cleaned
            ).strip()
            if len(compact_text(scored)) >= 2:
                cleaned = scored
        labelled = NAME_LEADING_LABEL_RE.sub("", NAME_LEADING_COUNT_RE.sub("", cleaned)).strip()
        if len(compact_text(labelled)) >= 2:
            cleaned = labelled
        # "수행평가 채점 기준(희토류 활용 사례 글쓰기)", "수행1 (탐구 주제 예비
        # 보고서) 세부 기준": the task named inside a rubric's heading.
        rubric_of = re.fullmatch(
            r"(?:수행\s*평가\s*\d*|수행\s*\d+)?\s*(?:채점\s*기준)?\s*[(（]\s*([^()（）]{4,}?)\s*[)）]"
            r"\s*(?:세부\s*(?:기준|계획)|채점\s*기준|구체\s*내용\s*및\s*기준)",
            cleaned,
        ) or re.fullmatch(
            r"(?:수행\s*평가\s*\d*|수행\s*\d+)\s*(?:채점\s*기준)?\s*[(（]\s*([^()（）]{4,}?)\s*[)）]",
            cleaned,
        )
        if rubric_of:
            cleaned = rubric_of.group(1).strip()
        # "(연역적 탐구방법 응용실험) 영역", "포트폴리오1 세부", "분류 체계 탐구 세부 기준"
        trimmed = re.sub(
            r"^[(（]([^()（）]{4,})[)）]\s*영역$|\s*(?:영역|세부(?:\s*(?:평가\s*)?(?:기준|척도))?)$",
            lambda match: match.group(1) or "",
            cleaned,
        ).strip()
        if (
            len(compact_text(trimmed)) >= 3
            and not re.search(r"(?:평가|과제별|계획|기준)$", trimmed)
            and not heading_title_is_structural(trimmed)
        ):
            cleaned = trimmed
        # "탐구 보고서 세부 계획" -- a task's own plan
        planned = re.fullmatch(r"(.+?)\s*세부\s*계획", cleaned)
        if planned and TASK_NAME_RE.search(planned.group(1)) and not heading_title_is_structural(
            planned.group(1)
        ):
            cleaned = planned.group(1).strip()
        bracketed = NAME_IN_BRACKETS_RE.fullmatch(cleaned)
        if bracketed and not re.search(r"\d+\s*(?:점|%)", bracketed.group("inner")) and (
            METHOD_ONLY_NAME_RE.fullmatch(compact_text(bracketed.group("label")))
            or compact_text(bracketed.group("label")) in {"평가과제", "수행과제", "과제"}
            or NUMBERED_TASK_LABEL_RE.fullmatch(compact_text(bracketed.group("label")))
        ):
            cleaned = bracketed.group("inner").strip()
        unit_task = _unit_path_task(cleaned)
        if unit_task:
            cleaned = unit_task
        wrapped = re.fullmatch(r"[(（]\s*([^()（）]{4,})\s*[)）]", cleaned)
        if wrapped:
            cleaned = wrapped.group(1).strip()
        # "…산의 성질 탐구자기 주도적 …산의 성질 탐구": a cell read twice.
        repeated = re.fullmatch(r"(.{6,}?)\s*\1", cleaned)
        if repeated:
            cleaned = repeated.group(1).strip()
        # A name cell that goes on to list the steps ("뉴턴의 프리즘 실험 구현 ·
        # 실험 결과 …", "… 비교 분석하기 - 분류 형질을 …", "… 비교하기 생식세포
        # 형성 …"): the first activity is the name, the rest is the overview.
        steps = re.split(r"\s+[·•\-–]\s+", cleaned)
        first_activity = re.match(
            r"(.{6,}?하기)\s+(?!및|와|과|후|또는|하고|위한|위해|위하여|위함|통한|통해|전에|후에|[,，(（])\S",
            cleaned,
        )
        # 문장으로 끝나는 방침 줄("…균형 있게 평가한다.")은 자르지 않는다: 앞 조각만
        # 남으면 방침 문장 판정을 비켜 과제명으로 나간다.
        sentence = re.search(r"[가-힣](?:다|함|음)\s*[.。]", cleaned)
        if sentence:
            pass
        elif len(steps) == 2 and re.search(r"평가\d*$", compact_text(steps[0])) and len(
            compact_text(steps[1])
        ) >= 6:
            # "과정중심평가 - 자신의 DNA 추출하여 관찰 …", "과정형평가1 - 세포 에너지 …":
            # 앞은 평가 종류 라벨이고 뒤가 과제다.
            cleaned = steps[1].strip()
        elif (
            len(cleaned) > 40
            and len(steps) >= 2
            and len(compact_text(steps[0])) >= 6
            # 앞 조각이 활동으로 끝날 때만 단계 나열이다. "냉철한 몽상가 프로젝트: 만약의
            # 과학 – 가정적 질문을 …"의 " – "는 부제를 잇는다.
            and re.search(r"(?:하기|보고서|만들기|제작|실험|구현|조사|발표|분석|관찰)$", steps[0].strip())
        ):
            cleaned = steps[0].strip()
        elif first_activity and re.search(r"(?:하기|보고서|만들기)$", cleaned):
            cleaned = first_activity.group(1).strip()
        if cleaned == before:
            break
    return cleaned


def _clean_heading_title(raw: str) -> tuple[str, str]:
    title_raw = visible_text(raw)
    match = ITEM_PREFIX_RE.match(title_raw)
    title = match.group("title").strip() if match else title_raw
    # Headings are often wrapped in brackets, or prefixed with the course name
    # in brackets ("[과학탐구실험1]수행평가 영역별 세부기준").  Neither is part
    # of the task name.
    title = re.sub(r"^\[\s*([^\[\]]{2,60})\s*\]$", r"\1", title.strip())
    title = re.sub(r"^\(\s*([^()]{2,60})\s*\)$", r"\1", title.strip())
    title = re.sub(r"^\[[^\[\]]{1,20}\]\s*(?=\S)", "", title)
    title = re.sub(r"^수행평가\s*\(\s*\d+\s*\)\s*[-:–—]?\s*", "", title)
    title = re.sub(
        r"\s*\([^)]*(?:\d+(?:\.\d+)?\s*(?:점|%)|만점|반영\s*비율)[^)]*\)\s*$",
        "",
        title,
    )
    # Some plans append the area score without the word '점' (e.g. '(20)')
    # or as '20(점) (논술형)'.  Values 1-4 are often source numbering, so only
    # strip score-sized values while preserving the exact source in title_raw.
    title = re.sub(
        r"\s*\(\s*(?:[5-9]|[1-9]\d|100)\s*\)\s*$",
        "",
        title,
    )
    title = re.sub(
        r"\s+(?:[5-9]|[1-9]\d|100)\s*\(\s*점\s*\)"
        r"(?=\s*(?:\([^)]*\))?\s*$)",
        "",
        title,
    )
    # PDF-to-Markdown conversion often collapses a section heading and the
    # following lettered task name onto one line. Keep only the source-authored
    # task portion instead of publishing "수행평가 세부 계획 가." as its name.
    title = re.sub(
        r"^수행\s*평가\s*세부\s*(?:계획|기준)"
        r"(?:\s*\([^)]*\))?\s*(?:[가-하]\s*[.)]|\([가-하]\))\s*",
        "",
        title,
    )
    title = re.sub(r"^수행\s*평가\s*\d+\s*[:：]\s*", "", title)
    title = re.sub(r"^수행\s*평가\s*영역\s*\d+\s*[:：]\s*", "", title)
    # "영역 : 삼투 현상 탐구 보고서", "B영역: …", "평가영역 4 : …" -- 라벨과 값이
    # 한 줄로 합쳐진 헤딩이다. 라벨을 떼면 학교가 쓴 과제명이 그대로 남는다.
    title = re.sub(
        r"^(?:[A-Z]\s*)?(?:평가\s*)?영역\s*\d*\s*[:：]\s*(?=\S)", "", title
    )
    # "수행평가 세부기준 (1) 별의 진화와 원소의 생성 인포그래픽",
    # "항목별 채점기준안 1) 수행평가명: 과제 연구" -- 구조 헤딩 뒤에 실제
    # 과제명이 붙어 한 줄이 된 경우. 이름 부분만 남긴다.
    title = re.sub(
        r"^.*?(?:수행\s*평가|평가)\s*(?:과제)?명\s*[:：]\s*(?=\S)", "", title
    )
    title = re.sub(
        r"^수행\s*평가\s*세부\s*(?:기준|계획|내용)\s*"
        r"[(（]\s*\d{1,2}\s*[)）]\s*(?=\S)",
        "",
        title,
    )
    # 실제 과제명에 성적 처리 규정 표기가 따라붙은 경우("… 탐구 (동점자 1순위)").
    title = re.sub(r"\s*[(（]\s*동점자\s*\d*\s*순위\s*[)）]\s*$", "", title)
    title = re.sub(r"^\d+\s*순위\s*\([^)]*반영\s*비율[^)]*\)\s*[:：]\s*", "", title)
    title = re.sub(r"^\[\s*(?:서[·ㆍ]?논술형|서술형|논술형)\s*\]\s*", "", title)
    title = re.sub(r"\s*\(\s*평가\s*시기\b.*$", "", title)
    scored_description = re.fullmatch(
        r"(.{2,}?)\s*\([^)]*(?:\d+(?:\.\d+)?\s*(?:점|%))[^)]*\)\s*[:：]\s*.+",
        title,
    )
    if scored_description:
        title = scored_description.group(1)
    task_with_rubric_suffix = re.fullmatch(r"(.+?)\s*수행\s*평가\s*기준", title)
    if task_with_rubric_suffix:
        candidate = task_with_rubric_suffix.group(1)
        if (
            len(compact_text(candidate)) >= 2
            and compact_text(candidate) not in STRUCTURAL_EXACT_COMPACT
        ):
            title = candidate
    task_with_criteria_suffix = re.fullmatch(r"(.+?)\s*평가\s*기준", title)
    if task_with_criteria_suffix:
        candidate = task_with_criteria_suffix.group(1)
        if (
            len(compact_text(candidate)) >= 2
            and compact_text(candidate) not in STRUCTURAL_EXACT_COMPACT
        ):
            title = candidate
    return strip_title_decoration(title), title_raw


# A connective verb ending followed by a comma is the middle of a sentence.
# PDF extraction wraps a 평가 방침 paragraph and marks each line as a heading,
# so without this a policy clause is published as a task name ("가. 2022 개정
# 교육과정 성취기준 및 성취수준을 바탕으로 실시하며, 수행평가에서 …").  It is
# checked on headings only: a 수행과제 cell legitimately spells a long task out
# as one sentence, and there the school did write that as the name.
PROSE_CLAUSE_RE = re.compile(r"(?:하며|되며|이며|으며|하고자)\s*,")

# 수행평가 과제명은 명사구다. 학교가 계획서에 적는 평가 방침·채점 지침·유의사항은
# 완결된 서술문이고, PDF/HWP 추출이 그 문단의 줄들을 전부 헤딩으로 만들기 때문에
# 과제명 자리에 올라온다. 어떤 문장이 오는지 하나씩 열거하는 대신 종결형 자체를
# 본다 -- 종결어미로 끝나면 이름이 아니라 문장이다.
SENTENCE_FINAL_HEADING_RE = re.compile(r"(?:다|음|함|됨|짐|것|바람)\s*[.。]?$")
# 같은 문단이 셀 너비에서 잘리면 종결어미 대신 조사나 연결어미로 끝난다
# ("… 조치가 완료된 후 당해연도에"). 과제명은 이런 형태로 끝나지 않는다.
# 조사 한 글자가 실제 낱말의 끝 글자와 겹칠 수 있어(진로·교과·자료) 잘린 방침
# 문단의 실제 길이인 20자 이상에서만 본다.
# 와/과는 제외한다 -- 결과·효과·교과·성과처럼 명사의 끝 글자와 너무 자주 겹친다.
# 의도 토의·논의·회의·합의·정의·협의로 끝나는 제목이 있어 그 앞 글자를 배제한다.
TRUNCATED_CLAUSE_HEADING_RE = re.compile(
    r"(?:은|는|을|를|(?<![토논회합정협주강])의|에|에서|으로|로|및|에게|부터|까지|"
    r"하여|하고|하며|되어|되며|이며|으며|지만|면서|"
    # …or mid-list ("지식⋅이해, 과정⋅기능,"), or on a modifier whose noun
    # went to the next cell line ("… 새로운 가치를 창출한", "… 위한 이론적").
    r"한|된|으로서|으로써|"
    r"(?:과학|이론|논리|창의|체계|합리|비판|구체|적극|주도|협력|통합|종합)적)\s*$"
)
# "흥미와 가치 인식, 참여의 적극성, 협동성, …, 창의성" and "생물의 구조와
# 에너지, 자극과 반응, …" list what is graded or covered; a name lists no
# such run of items without naming an activity.
ELEMENT_LIST_MIN_COMMAS = 3
# 평가 운영 어휘로만 이루어진 헤딩은 문서 구조 라벨이다("평가 요소",
# "수행평가 영역별 배점 및 채점 기준"). 활동어가 하나도 없고 이 어휘를 모두
# 지웠을 때 남는 글자가 없으면 학교가 이름 붙인 과제가 아니다. 리터럴 목록을
# 계속 늘리는 대신 어휘 자체를 본다.
ADMIN_VOCABULARY_RE = re.compile(
    r"수행평가|정기시험|지필평가|평가|채점|배점|점수|만점|합계|총점|비율|반영|"
    r"영역|요소|항목|내용|방법|기준안|기준|세부|계획|안내|운영|시기|횟수|단원|개요|표|"
    r"성취기준|성취수준|성취율|성취도|등급|학기|학년|과목|교과|문항|고사|중간|기말|"
    r"공통|일반|기타|사항|구분|순위|기본|합계|합|별|등|회|차|[0-9]|"
    r"[.,()（）\[\]/·ㆍ‧、:：;※'\"~\-–—및와과의는은이가을를에서로]"
)
# 평가 결과 처리 규정은 과제가 아니다. 활동어가 함께 있으면 실제 과제명에
# 동점자 표기가 따라붙은 것뿐이므로(효모의 물질대사 탐구 (동점자 1순위))
# 활동어가 없을 때만 규정으로 본다.
GRADING_POLICY_VOCABULARY_RE = re.compile(
    r"이의\s*신청|이의신청|인정점|결시|동점자|미응시|미제출|분할\s*점수|"
    r"학적\s*변동|성적\s*처리|재평가|전입생|부정행위"
)
# 로마숫자 대단원이 둘 이상 나열되면 평가 범위이지 과제명이 아니다
# ("Ⅰ. 생명과학의 역사 Ⅱ. 세포의 특성", "Ⅰ.생명의 시스템 ~ Ⅲ.생명의 다양성").
# 대단원 하나로 시작하는 제목("Ⅰ. 과학의 본성 / 01.동시 발견 추적하기")은
# 학교가 단원을 앞에 붙여 쓴 실제 과제명이라 건드리지 않는다.
UNIT_RANGE_TITLE_RE = re.compile(r"[ⅠⅡⅢⅣⅤ]\s*[.．].*[ⅠⅡⅢⅣⅤ]\s*[.．]")
# "… 의사소통 능력을 평가" -- 무엇을 평가하는지 쓴 채점 서술이다. 명사구 제목은
# 목적격 조사 뒤에 '평가'로 끝나지 않는다.
GRADED_ABILITY_TAIL_RE = re.compile(r"(?:을|를)\s*평가\s*\.?$")
# "평가 요소 및 방법 : 주제의 선정, …을 평가, 태도", "대상 학년: 2학년",
# "평가 시기: 3월~6월" -- a field label and its value on one line; the label
# says it is not a name.
POLICY_LABEL_LINE_RE = re.compile(
    r"^(?:평가\s*(?:요소|방법|내용|기준|시기|대상)"
    r"(?:\s*및\s*(?:요소|방법|내용|기준|시기))?|"
    r"대상\s*(?:학년|독서|도서)|학년|학기|시기(?:\s*및\s*내용)?|(?:담당|지도|수업)?\s*교사\s*\w?|담당|"
    r"단위\s*수|시수|"
    r"반영\s*비율(?:\s*및\s*배점)?|배점|관련\s*단원|평가\s*세부\s*내용|문항\s*채점\s*기준|"
    r"평가\s*영역\s*[(（][^()（）]*[)）]|[^:：]{2,20}\s*촉진)\s*[:：]"
)
# Section headings of the plan document itself that the exact lists above
# missed in their spelled-out variants ("평가 시 유의 사항 가. 공통사항",
# "정의적 능력 평가의 목적", "평가의 종류‧방법‧시기‧반영비율").
DOCUMENT_SECTION_HEADING_RE = re.compile(
    r"유의\s*사항|"
    r"^(?:수행\s*)?평가의?\s*(?:기본\s*)?(?:방향|방침|원칙|총괄|목적)|"
    r"^평가\s*도구\s*제작의\s*원칙|^(?:평가의?\s*)?목적$|^방향$|"
    r"^정의적\s*(?:능력|영역)|^평가의?\s*(?:종류|유형)|"
    r"^수행\s*평가\s*(?:시행\s*계획|과제별|세부\s*기준\s*참고)|"
    r"^수행\s*과제\s*(?:세부\s*내용|흐름)|^성취\s*수준별|^성취\s*기준에\s*따른$|"
    r"^학교생활기록부|^학기\s*초에|^재\s*[ㆍ·‧]?\s*전\s*[ㆍ·‧]?\s*편입|제출\s*기한\s*준수|"
    r"^(?:일반|기본|공통)\s*원칙$|^학기\s*단위|"
    r"^(?:수행\s*)?평가\s*영역별\s*배점|채점\s*기준\s*[(（]\s*예시\s*[)）]|"
    r"^교수\s*[-·‧]?\s*학습\s*(?:및\s*평가\s*)?(?:운영\s*)?계획$|"
    r"^평가\s*관점$|^대체\s*평가$|^분량(?:\s*[(（]\s*\d+\s*점\s*[)）])?$|"
    r"^(?:교육과정\s*)?성취\s*기준\s*및$|"
    r"^지필\s*(?:고사|평가)\s*(?:및|와|과|/)\s*수행\s*평가|"
    # "통합과학D 교수·학습 및 평가 운영 계획", "통과A 수행평가 세부 계획"
    r"(?:교수\s*[-·‧]?\s*학습\s*(?:및\s*)?(?:평가\s*)?(?:운영\s*)?계획서?|"
    r"수행\s*평가\s*세부\s*(?:계획|기준))$|"
    r"처리\s*방안$|평가할\s*때\s*[,，]|(?:AI|인공지능)\S*\s*(?:를|을)?\s*활용한\s*경우|"
    r"(?:AI|인공지능).*(?:활용|사용)\s*(?:이|을|를)?\s*(?:가능|금지|허용)"
)
# A sentence cut off at its first particle ("의 –1점을 부여한다.") or a
# tie-break/absence rule ("동점자 처리 순위는 …") is a policy line however it ends.
POLICY_FRAGMENT_START_RE = re.compile(
    # "과 학 인포그래픽"은 PDF가 "과학"을 띄워 쓴 것이라 조사 조각이 아니다.
    r"^(?:(?:의|을|를|은|는|에|에서|과(?!\s*학)|와)(?:\s+|\s*[-–—])|동점자|결시자|미응시자|평가는\s)"
)


def heading_is_policy_prose(title: str) -> bool:
    """Return true when a heading is a policy/rubric sentence, not a task name.

    Every branch requires the heading to be long enough that a school could not
    have meant it as a name: the shortest real 과제명 in the corpus that ends in
    a nominalising ending ("탐구 일지 모음") stays well under these lengths.
    """

    # A long line that stops on a comma was cut mid-list.
    if len(compact_text(title)) >= 20 and re.search(r"[,，]\s*$", title):
        return True
    clean = re.sub(r"\s+", " ", title).strip().strip(" ,，:：;；")
    clean = re.sub(r"^(?:\d+|[가-하]|[①-⑳])\s*[.)]\s*", "", clean)
    # "… 18%를 반영한다. (단, … 제외)" -- the sentence ends before its proviso.
    clean = re.sub(r"\s*[(（]\s*(?:단|※)[^()（）]*[)）]?\s*[.。]?$", "", clean)
    compact = compact_text(clean)
    if len(compact) >= 12 and SENTENCE_FINAL_HEADING_RE.search(clean):
        return True
    if len(compact) >= 15 and re.search(r"[가-힣](?:다|함|음)\.\s+\S", clean):
        return True
    # "… 평가를 진행한다(수행평가 영역별 반영 비율은 평가계획 참고)" -- any
    # trailing note, not only 단/※, can follow the sentence's end.
    sentence = re.sub(r"\s*[(（][^()（）]*[)）]\s*[.。]?$", "", clean)
    if len(compact_text(sentence)) >= 12 and SENTENCE_FINAL_HEADING_RE.search(sentence):
        return True
    if len(compact) >= 20 and TRUNCATED_CLAUSE_HEADING_RE.search(clean):
        return True
    if len(compact) >= 15 and GRADED_ABILITY_TAIL_RE.search(clean):
        return True
    if UNIT_RANGE_TITLE_RE.search(clean):
        return True
    if len(re.findall(r"[,，]", clean)) >= ELEMENT_LIST_MIN_COMMAS and not TASK_NAME_RE.search(
        clean
    ):
        return True
    if TASK_ACTIVITY_RE.search(clean):
        return False
    if GRADING_POLICY_VOCABULARY_RE.search(clean):
        return True
    return bool(compact) and not ADMIN_VOCABULARY_RE.sub("", compact).strip()


def _valid_title(title: str) -> bool:
    compact = compact_text(title)
    if not 2 <= len(compact) <= 100:
        return False
    if NON_ASSESSMENT_TITLE_RE.search(compact):
        return False
    if GENERIC_TITLE_RE.fullmatch(title) or re.fullmatch(r"[0-9점%./~\s]+", title):
        return False
    if WRITTEN_EXAM_TITLE_RE.search(title.strip()):
        return False
    if _unit_path_task(title) == "":
        return False
    # "☑ 서술·논술 유형" -- a checkbox cell of the 평가방법 row.
    if re.match(r"^\s*[☑☐□■▣✓✔]", title):
        return False
    # "70점 (이하)", "30%(이상)" -- the value of a 영역만점 or 반영비율 cell.
    if re.fullmatch(r"[0-9점%％./~\s()（）]*\d[0-9점%％./~\s()（）]*(?:이하|이상|미만|초과)?[\s)）]*", title):
        return False
    if NON_TASK_LABEL_TITLE_RE.fullmatch(compact):
        return False
    return not (len(compact) > 4 and bool(re.search(r"(?:상|중|하)\s*$", title)))


def heading_title_is_structural(title: str, *, policy_prose: bool = True) -> bool:
    """Return true when a numbered heading describes document structure, not a task.

    These strings are common subheadings *inside* one assessment. Publishing
    them as assessment names made a rubric or policy sentence appear to be a
    separate task. Long imperative/policy sentences are also kept only as raw
    source unless an explicit title cell confirms a real task name.
    """

    clean = re.sub(r"\s+", " ", title).strip()
    # "…탐구하는 능력을 신장시키기 위하여 지식," -- a sentence cut mid-list.
    if policy_prose and len(compact_text(clean)) >= 20 and re.search(r"[,，]$", clean):
        return True
    structural_clean = re.sub(r"^(?:\d+|[가-하])\s*[.)]\s*", "", clean)
    structural_clean = re.sub(r"\s*\(※[^)]*\)\s*$", "", structural_clean)
    # PDF/HWP converters frequently leave the comma from a numbered outline
    # (for example ``12. 학기 단위 성취수준 설정,``) or collapse the next
    # numbered heading onto the same line.  Punctuation is not evidence that a
    # document-structure heading became an assessment title.
    structural_clean = structural_clean.strip(" ,，:：;；.-")
    compact = compact_text(structural_clean)
    return bool(
        (policy_prose and heading_is_policy_prose(structural_clean))
        or POLICY_LABEL_LINE_RE.match(structural_clean)
        or POLICY_FRAGMENT_START_RE.match(structural_clean)
        or DOCUMENT_SECTION_HEADING_RE.search(structural_clean)
        or compact in STRUCTURAL_EXACT_COMPACT
        or STRUCTURAL_HEADING_RE.fullmatch(structural_clean)
        or re.match(
            r"^(?:교육과정\s*)?성취\s*기준\s*[:：]?\s*\[(?:10|12)",
            structural_clean,
        )
        or re.match(
            r"^(?:학기\s*단위\s*)?성취\s*수준(?:\s*설정.*)?$|"
            r"^최소\s*성취\s*수준(?:\s*(?:설정|진술).*)?$",
            structural_clean,
        )
        or re.fullmatch(r"(?:일반|공통|기타)\s*사항|영역별", structural_clean)
        or re.match(r"^\[(?:10|12)[^\]]+\](?:\s*[~\\-].*)?$", structural_clean)
        or re.match(
            r"^(?:성취\s*기준\s*및\s*성취\s*수준|수강생.*통합\s*산출\s*여부)",
            structural_clean,
        )
        or re.search(
            r"(?:동일\s*학년\s*동일\s*교과|신체\s*장애\s*학생|"
            r"통합반\s*선생님|채점\s*기준표)",
            structural_clean,
        )
        or re.fullmatch(
            r"(?:수행평가\s*과제별\s*세부\s*계획|평가\s*방법\s*및\s*채점\s*기준\s*배점|"
            r"채점\s*기준\s*및\s*배점|성취\s*기준\s*및\s*평가\s*기준|"
            r"평가\s*내용\s*및\s*방법|실시\s*시기\s*및\s*횟수|"
            r"평가\s*관점[·ㆍ]?\s*요소|수행\s*수준\s*\(채점\s*기준\)\s*및\s*배점)",
            structural_clean,
        )
        or re.match(
            r"^(?:수행평가에서\s*인공지능|수행평가\s*유형은|"
            r"수행평가\s*결과물에\s*AI|"
            r"수행평가\s*세부\s*계획과\s*채점|수행평가의\s*영역|"
            r"전[·ㆍ]?편입생|영역\s*만점은|질병\s*결석|최소\s*성취수준|기준\s*성취율)",
            structural_clean,
        )
        or re.search(
            r"(?:AI|인공지능).*(?:활용\s*(?:가능|금지|허용)|사용\s*금지|"
            r"힌트\s*요청|활용\s*내역)",
            structural_clean,
            re.I,
        )
        or re.search(
            r"(?:교과협의회|학업성적(?:관리)?|관리위원회|심의\s*후|"
            r"평가\s*관련\s*제반\s*문제|평가\s*결과의?\s*활용)",
            structural_clean,
        )
        or re.match(
            r"^평소\s*수업\s*활동이\s*자연스럽게\s*평가로\s*이어지도록",
            structural_clean,
        )
        or re.match(
            r"^(?:수행평가\s*(?:결시자의|영역별\s*특성|시간에|에\s*참여한|"
            r"의\s*(?:목표|반영\s*비율)|를\s*할\s*때|는|인공지능|결과물은)|"
            r"결석의\s*경우|결시(?:생|\s*\()|영역의\s*특성|질병\s*및\s*인정\s*결석|"
            r"특수교육\s*대상자|AI(?:는|의\s*활용|를\s*활용)|교과의\s*특성을|"
            r"전입생이|성취기준에\s*근거한\s*평가의|정기시험(?:은|에서)|"
            r"내용\s*영역,\s*성취기준|모둠토의|포트폴리오에서|"
            r"성취기준별\s*성취수준에\s*따른\s*수행\s*정도|출제\s*원안에는|"
            r"모든\s*출제\s*원안|객관적이고\s*공정한\s*채점\s*기준|"
            r"학생이\s*성취기준에|학생의\s*수업\s*시간\s*활동|원안\s*제출\s*시|"
            r"5지\s*선다형|평가\s*\(정기시험\s*및\s*수행평가\)의|"
            r"성취기준을\s*분석하여|비고\s*[:：]|평가\s*요소\s*[:：])",
            structural_clean,
        )
        or re.match(
            r"^(?:최하\s*\d+점부터|[「『]?공교육\s*정상화\s*촉진)",
            structural_clean,
        )
        or re.search(
            r"(?:제출\s*금지|구분하여\s*명시|해당\s*없음)$",
            structural_clean,
        )
        or re.search(
            r"(?:수행하였는가|활동하고\s*있는가|명확하게.*있는가)\s*\?$",
            structural_clean,
        )
        or (
            len(compact) >= 10
            and re.search(
                r"(?:한다|된다|따른다|바란다|않는다|서술함|"
                r"할수있다|부여할수있다)$",
                compact,
            )
        )
    )


# 생명과학 교과군 코드의 한글 뼈대만 남긴 집합("10통과1" -> "통과").  학교가 코드를
# 자기 식으로 적어도("고생1201-01", "통과1-03-05") 뼈대는 그대로라, 학년 숫자 자리에
# 기대지 않고 교과군 소속을 판별할 수 있다.
BIOLOGY_CODE_CORES = frozenset(
    re.sub(r"[^가-힣]", "", prefix)
    for prefixes in EXPECTED_STANDARD_PREFIXES.values()
    for prefix in prefixes
)
_BRACKET_CODE_RE = re.compile(r"\[\s*([^\[\]]{2,24})\s*-\s*\d")


def foreign_subject_codes(shown: str) -> list[str]:
    """Return achievement codes in ``shown`` that belong to another subject.

    ``segment_subject_alignment`` used to look only for codes spelled ``10…``
    or ``12…``, so a 전문교과 code (``[프로02-01]`` 정보, ``[자구01-02]``
    자료구조) or a middle-school one (``[9음03-01]``) was not seen as a code at
    all: the segment scored "unknown" and a whole other subject's assessment
    was published inside a biology case.  A code is recognised by its shape --
    a bracketed token carrying the subject's Hangul name and a two-digit area
    number -- and then judged by that Hangul name, which is what actually
    identifies the subject.  ``[기본점수 - 4]`` and ``[영역2-1]`` carry no
    two-digit area number and are not codes.
    """

    foreign = []
    for token in _BRACKET_CODE_RE.findall(shown):
        code = subject_code_key(token)
        if not re.search(r"[가-힣]", code) or not re.search(r"\d{2}", code):
            continue
        core = re.sub(r"[^가-힣]", "", code)
        if any(
            core.startswith(known) or known.startswith(core)
            for known in BIOLOGY_CODE_CORES
            if known
        ):
            continue
        foreign.append(code)
    return foreign


def segment_subject_alignment(segment: str, subject: str) -> str:
    """Classify achievement-code evidence for a short-name subject boundary."""

    prefixes = EXPECTED_STANDARD_PREFIXES.get(subject)
    if not prefixes:
        return "unknown"
    shown = unicodedata.normalize("NFC", visible_text(segment))
    # 다른 교과의 코드는 그 자체로 경계가 깨졌다는 증거다. 생명과학 코드가 함께
    # 있어도 마찬가지 -- 두 교과 표가 한 구간에 섞여 들어온 것이다.
    if foreign_subject_codes(shown):
        return "other"
    codes = [
        subject_code_key(match)
        for match in re.findall(r"\[\s*((?:10|12)[^\]\-]{1,20})\s*-\s*\d", shown)
    ]
    # Each code belongs to the course of its longest matching prefix: a
    # ``[12생과Ⅱ…]`` code starts with ``12생과`` but is 생명과학Ⅱ, and
    # ``[10통과1-…]`` starts with ``10통과`` but is 통합과학1.  A plain prefix
    # test passed whole 생명과학Ⅱ plans as 2022 생명과학.
    owners = [subjects_for_standard_codes([code]) for code in codes]
    if codes and all(subject in owner for owner in owners):
        return "expected"
    # A 2022 course plan often abbreviates its own codes in the 2015 shape
    # ("이외 [10통과01-02~04]" next to "[10통과1-01-01]").  Once at least one
    # code names the requested course exactly, its curriculum-family sibling
    # codes are the same course, not another subject.
    family = subjects_for_standard_codes(list(SUBJECT_CODE_FAMILY.get(subject, ())))
    if codes and family and any(subject in owner for owner in owners) and all(
        owner & ({subject} | family) for owner in owners
    ):
        return "expected"
    # 2022 생명과학 계획서에 옛 생명과학Ⅰ·Ⅱ 코드가 섞인 것은 학교의 오기일 수 있다.
    # 자기 코드가 절반 이상일 때만 같은 과목으로 본다(Ⅱ 코드가 대부분이면 Ⅱ 계획서다).
    revised = subjects_for_standard_codes(list(REVISED_CODE_FAMILY.get(subject, ())))
    own_count = sum(subject in owner for owner in owners)
    if codes and revised and own_count * 2 >= len(codes) and all(
        owner & ({subject} | revised) for owner in owners
    ):
        return "expected"
    # An explicit achievement-standard code is stronger boundary evidence than
    # a short subject-name mention.  If the code cannot confirm the requested
    # biology course, keep the section out of the public catalogue even
    # when the code belongs to a non-biology subject that is intentionally
    # absent from ``EXPECTED_STANDARD_PREFIXES``.
    return "other" if codes else "unknown"


OTHER_PLAN_HEADING_RE = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.S)


def _names_other_course_plan(heading: str, subject: str) -> bool:
    """"과학탐구실험1과 평가계획", "생명과학 실험 평가 계획 (3학년)", "[통합과학2_A]"."""

    shown = visible_text(heading)
    if not (re.search(r"계획|교수|평가", shown) or re.fullmatch(r"\[[^\[\]]{2,20}\]", shown)):
        return False
    own = _subject_targets(subject)
    if _names_course(shown, own):
        return False
    return any(
        _names_course(shown, _subject_targets(course))
        for course in EXPECTED_STANDARD_PREFIXES
        if course != subject
    )


def _cut_at_other_course_title(
    item: ParsedAssessmentItem, subject: str
) -> ParsedAssessmentItem:
    """End an item where the next course's plan title shows up inside it.

    The loose end-of-section check keeps a school's reused form together, so
    the next course's title page ("2026학년도 1학년 1학기" / "과학탐구실험1과
    평가계획") or its first task ("[통합과학2_A]") can ride at the end of the
    last item.  The item stops at the first heading of that run, outside tables.
    """

    if item.extraction_status != "bounded":
        return item
    html_text = item.source_html
    headings = list(OTHER_PLAN_HEADING_RE.finditer(html_text))
    for position, match in enumerate(headings):
        if match.start() == 0 or not _names_other_course_plan(match.group(1), subject):
            continue
        before = html_text[: match.start()]
        if before.count("<table") != before.count("</table>"):
            continue
        start = match.start()
        # 바로 앞에 붙은 제목줄("2026학년도 1학년 1학기")도 같은 제목 묶음이다.
        for previous in reversed(headings[:position]):
            if html_text[previous.end(): start].strip() or previous.start() == 0:
                break
            start = previous.start()
        cut_html = html_text[:start].rstrip()
        if len(visible_text(cut_html)) < 20:
            return item
        title_line = visible_text(html_text[start: start + 200])[:20]
        markdown = item.source_markdown
        at = markdown.find(title_line[:12]) if title_line else -1
        return replace(
            item,
            source_html=cut_html,
            source_markdown=markdown[:at].rstrip() if at > 0 else markdown,
        )
    return item


def _finish_item(item: ParsedAssessmentItem) -> ParsedAssessmentItem:
    """Last checks on what a bounded item shows.

    * A section that holds only its own title and a sub-heading ("1. 과학의
      단위 … 프로젝트(30%)" / "평가방법 및 채점기준") or that points at "아래의
      채점 기준표" without any table was cut before its content: it is not
      shown as a confirmed assessment.
    * A rubric that kept only its header row ("평가 요소 │ 배점 │ 채점 기준")
      shows nothing; the source section still carries the school's table.
    * A 반영 비율 over 100 ("405" for "40%") is a typo, not a weight.
    """

    if item.extraction_status != "bounded":
        return item
    body = visible_text(item.source_markdown)
    body = body.replace(visible_text(item.title_raw), "", 1)
    has_table = bool(re.search(r"<table|^\s*\|", item.source_markdown, flags=re.M))
    # 짧아도 "반영 비율 및 배점 : 10점(10%) … 평가 시기 : 6월"처럼 학교가 적은
    # 값이 있으면 그대로 둔다.
    cut_short = len(compact_text(body)) < 40 and not re.search(
        r"\d+\s*(?:점|%)|[:：]\s*\S{4,}", body
    )
    if not has_table and (cut_short or re.search(r"아래(?:의)?\s*채점\s*기준\s*표", body)):
        return replace(item, extraction_status="bundle_review")
    rubric_html = item.rubric_html
    if (
        rubric_html
        and len(re.findall(r"<tr\b", rubric_html)) <= 1
        and RUBRIC_HEADER_WORDS_RE.fullmatch(compact_text(visible_text(rubric_html)))
    ):
        rubric_html = ""
    weight = item.weight
    values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", weight)]
    if values and all(value > 100 for value in values):
        weight = ""
    return replace(item, rubric_html=rubric_html, weight=weight)


RUBRIC_HEADER_WORDS_RE = re.compile(
    r"(?:평가|채점|요소|배점|기준|세부|점수|수행|수준|등급|내용|척도|및|영역|항목|만점|비고|구분|부여)+"
)


def _names_another_course(segment: str, subject: str) -> bool:
    """Whether an item's own text places it in another course.

    Every table scan checks codes its own way; this is the last word for any
    bounded item.  Its achievement codes all belong to other courses (a 생명과학Ⅱ
    table filed under 2022 생명과학, a 통합과학1 table under the 2015 통합과학),
    or its own "과목 │ 과학탐구실험2" cell names another course.  Codes of both
    courses together are the school's own citation and stay.
    """

    shown = unicodedata.normalize("NFC", visible_text(segment))
    codes = [
        subject_code_key(match)
        for match in re.findall(r"\[\s*((?:10|12)[^\]\-]{1,20})\s*-\s*\d", shown)
    ]
    # 대괄호 없이 적은 코드도 본다: "교육과정 성취기준 10과탐1-01-03".
    codes += [
        subject_code_key(match)
        for match in re.findall(
            r"(?<![\[0-9A-Za-z가-힣])((?:10|12)[가-힣]{2,4}(?:Ⅰ|Ⅱ|II|I|[12])?\d{0,2})\s*-\s*\d{2}",
            shown,
        )
    ]
    own = {subject} | subjects_for_standard_codes(list(SUBJECT_CODE_FAMILY.get(subject, ())))
    owners = [owner for owner in (subjects_for_standard_codes([code]) for code in codes) if owner]
    if owners and not any(owner & own for owner in owners):
        return True
    targets = _subject_targets(subject)
    other_cover = any(
        _names_a_course(value)
        and value not in targets
        and not _names_course(value, targets)
        and not any(value in name for name in targets)
        for value in _cover_subject_values(segment)
    )
    # 2015 통합과학·과학탐구실험은 2026학년도에 거의 없다. 2022 번호 과목 코드나 "과목 │
    # 통합과학2" 칸이 하나라도 있으면 2015 꼴 코드("[10통과02-06]")가 있어도 2022 계획서다.
    if subject in NUMBERED_SUCCESSORS and (
        other_cover or any(owner & NUMBERED_SUCCESSORS[subject] for owner in owners)
    ):
        return True
    # 자기 과목 코드가 있으면 양식을 재사용한 "과목명 │ 생명과학Ⅰ" 칸보다 코드를 믿는다.
    if any(owner & own for owner in owners):
        return False
    return other_cover


NUMBERED_SUCCESSORS = {
    "통합과학": {"통합과학1", "통합과학2"},
    "과학탐구실험": {"과학탐구실험1", "과학탐구실험2"},
}


def explicit_segment_title(segment: str) -> str:
    """Return only the title from :func:`explicit_segment_title_with_label`."""

    return explicit_segment_title_with_label(segment)[0]


def explicit_segment_title_with_label(segment: str) -> tuple[str, str]:
    """Read an assessment name only from an explicit source-table label.

    The first non-empty cell after labels such as ``평가 영역명`` or
    ``수행평가명`` is source-authored evidence. Metadata cells (score, timing,
    method, and so on) terminate the search so merged tables cannot leak a
    neighbouring field into the title.

    Returns the title and the compacted label that produced it, because the
    label decides how much the title can be trusted: ``평가영역`` cells hold a
    unit name as often as a task name, while ``수행과제``/``과제명`` cells name
    the task itself.
    """

    def clean_candidate(candidate: str) -> str:
        return re.split(
            r"\s+(?:(?:영역\s*)?만점|학기)(?:\s|$)",
            candidate,
            maxsplit=1,
        )[0].strip(" |")

    def usable(candidate: str) -> bool:
        compact = compact_text(candidate)
        return bool(
            candidate
            and 2 <= len(compact) <= 120
            and not re.search(r"^(?:10|12)[0-9A-Za-z가-힣ⅠⅡ]", compact)
            and not TITLE_VALUE_STOP_LABEL_RE.fullmatch(compact)
            and not NON_TASK_TITLE_RE.fullmatch(candidate.strip())
            and not EXPLICIT_TITLE_LABEL_RE.fullmatch(compact)
            and not heading_title_is_structural(candidate)
            and _valid_plan_title(candidate)
        )

    def source_spelling(candidate: str) -> str:
        """Restore exact source glyphs lost by normalized table parsing."""

        candidate_key = compact_text(candidate)
        for match in re.finditer(
            r"<(?:th|td)\b[^>]*>(.*?)</(?:th|td)>",
            segment,
            flags=re.I | re.S,
        ):
            source_candidate = visible_text(match.group(1)).strip(" |")
            if compact_text(source_candidate) == candidate_key and usable(source_candidate):
                return source_candidate
        return candidate

    for rows in _source_tables(segment):
        for row_index, row in enumerate(rows[:8]):
            values = [visible_text(cell) for cell in row]
            labels = [compact_text(value) for value in values]
            for index, label in enumerate(labels):
                if not EXPLICIT_TITLE_LABEL_RE.fullmatch(label):
                    continue
                # Detailed item tables usually place the title immediately to
                # the right of the label. Stop if the next populated cell is
                # another metadata header; that row is a column header, not a
                # title/value pair.
                has_horizontal_value = False
                for following in range(index + 1, len(values)):
                    candidate = clean_candidate(values[following])
                    candidate_label = labels[following]
                    if not candidate:
                        continue
                    has_horizontal_value = True
                    if (
                        candidate_label in TITLE_VALUE_STOP_LABELS
                        or TITLE_VALUE_STOP_LABEL_RE.fullmatch(candidate_label)
                        or EXPLICIT_TITLE_LABEL_RE.fullmatch(candidate_label)
                    ):
                        # "평가영역명 │ 영역만점 │ 학기" is a column header; the
                        # name is the one cell below the label, before the
                        # next label row.  A rubric header ("평가영역 │ 평가요소
                        # │ 채점기준") heads graded elements, not a name.
                        if not any(
                            re.search(r"평가요소|채점기준|평가기준|세부기준|수행수준|채점요소", cell)
                            for cell in labels
                        ):
                            below_values: list[str] = []
                            for below in rows[row_index + 1 :]:
                                if index >= len(below):
                                    break
                                value_below = clean_candidate(visible_text(below[index]))
                                below_key = compact_text(value_below)
                                if not below_key or (
                                    EXPLICIT_TITLE_LABEL_RE.fullmatch(below_key)
                                    or TITLE_VALUE_STOP_LABEL_RE.fullmatch(below_key)
                                    or below_key in TITLE_VALUE_STOP_LABELS
                                    or not usable(value_below)
                                ):
                                    break
                                below_values.append(value_below)
                            if len(below_values) == 1:
                                return source_spelling(below_values[0]), label
                        break
                    if usable(candidate):
                        return source_spelling(candidate), label
                    break

                # A label/value row can contain a generic assessment area
                # (for example, '학습과정평가') followed by a later explicit
                # '수행과제' row.  It is not a summary-table column header,
                # so do not scan its unrelated first-column values vertically.
                if has_horizontal_value:
                    continue

                # In a summary table the label is a column header. Accept a
                # vertical value only when exactly one distinct performance
                # task remains after excluding written exams and field labels;
                # multiple values are deliberately left as a review bundle.
                vertical: list[str] = []
                seen: set[str] = set()
                for following_row in rows[row_index + 1 :]:
                    if index >= len(following_row):
                        continue
                    candidate = clean_candidate(visible_text(following_row[index]))
                    key = compact_text(candidate)
                    if usable(candidate) and key not in seen:
                        seen.add(key)
                        vertical.append(candidate)
                if len(vertical) == 1:
                    return source_spelling(vertical[0]), label

        # A common rubric layout names the assessment in the first data cell
        # under an explicit '영역(만점)' header.  This differs from an ordinary
        # 평가요소 table: the same header row also names the item, criterion,
        # and score columns.  The first populated area cell is therefore a
        # source-authored assessment name, not a rubric dimension inferred by
        # the parser.
        for row_index, row in enumerate(rows[:-1]):
            labels = [compact_text(visible_text(value)) for value in row]
            if not labels or labels[0] not in {"영역만점", "평가영역만점"}:
                continue
            support = sum(
                any(marker in label for marker in ("평가항목", "평가요소", "채점기준", "배점"))
                for label in labels[1:]
            )
            if support < 2:
                continue
            for following_row in rows[row_index + 1 :]:
                if not following_row:
                    continue
                candidate = clean_candidate(visible_text(following_row[0]))
                if usable(candidate):
                    return source_spelling(candidate), labels[0]
                if candidate:
                    break
    return "", ""


def _heading_candidates(block: str) -> list[tuple[int, int, str, str]]:
    lines = _line_offsets(block)
    preliminary: list[tuple[int, int, str, str]] = []
    table_depth = 0
    for index, (start, _, raw) in enumerate(lines):
        opens = len(re.findall(r"<table\b", raw, flags=re.I))
        closes = len(re.findall(r"</table>", raw, flags=re.I))
        outside_table = table_depth == 0
        # Markdown pipe rows are tables too.  Their numbered rubric cells are
        # never source headings, even though they may begin with "1." or "가.".
        if outside_table and not raw.lstrip().startswith("|"):
            title, title_raw = _clean_heading_title(raw)
            if (
                ITEM_PREFIX_RE.match(visible_text(raw))
                and _valid_title(title)
                and not PROSE_CLAUSE_RE.search(title)
                # kordoc keeps a sub-heading's number on its line ("1) 평가 개요",
                # "2) 채점 기준"); such a section word must not cut the task
                # heading above it ("가. 영역 : 유전 정보의 흐름 탐구") short.
                and not heading_title_is_structural(title, policy_prose=False)
            ):
                preliminary.append((index, start, title, title_raw))
        table_depth += opens - closes
        table_depth = max(0, table_depth)

    accepted: list[tuple[int, int, str, str]] = []
    for position, candidate in enumerate(preliminary):
        line_index, start, title, title_raw = candidate
        next_start = preliminary[position + 1][1] if position + 1 < len(preliminary) else len(block)
        segment = block[start:next_start]
        markers = set(match.group(0) for match in ASSESSMENT_MARKER_RE.finditer(segment))
        performance_markers = set(
            match.group(0) for match in PERFORMANCE_MARKER_RE.finditer(segment)
        )
        # A curriculum unit followed only by a standards/achievement-level
        # table is not a performance assessment.  The former rule accepted
        # these headings merely because a table was present, publishing unit
        # names such as "다항식" or "수열" as task names.
        if not performance_markers:
            continue
        if len(markers) >= 2 or ("<table" in segment.lower() and explicit_segment_title(segment)):
            accepted.append((line_index, start, title, title_raw))
    return accepted


def _markdown_pipe_table_fragments(value: str) -> list[str]:
    lines = value.splitlines()
    fragments: list[str] = []
    index = 0
    while index + 1 < len(lines):
        if not (
            lines[index].strip().startswith("|") and PIPE_SEPARATOR_RE.fullmatch(lines[index + 1])
        ):
            index += 1
            continue
        start = index
        index += 2
        while index < len(lines) and lines[index].strip().startswith("|"):
            index += 1
        fragments.append("\n".join(lines[start:index]))
    return fragments


class _SpanTableExtractor(StdlibHTMLParser):
    """Collect top-level table cells with their rowspan/colspan (nested tables flatten to text)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[tuple[str, int, int]]]] = []
        self._depth = 0
        self._rows: list[list[tuple[str, int, int]]] = []
        self._cell: list[str] | None = None
        self._span = (1, 1)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        elif self._depth == 1 and tag == "tr":
            self._rows.append([])
        elif self._depth == 1 and tag in ("td", "th") and self._rows:
            values = {name.lower(): (value or "") for name, value in attrs}
            self._cell = []
            self._span = (
                max(1, int(values.get("rowspan") or 1) if str(values.get("rowspan") or "1").isdigit() else 1),
                max(1, int(values.get("colspan") or 1) if str(values.get("colspan") or "1").isdigit() else 1),
            )
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._depth == 1 and tag in ("td", "th") and self._cell is not None and self._rows:
            self._rows[-1].append(("".join(self._cell).strip(), *self._span))
            self._cell = None
        elif tag == "table":
            if self._depth == 1 and self._rows:
                self.tables.append(self._rows)
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _expand_spans(rows: list[list[tuple[str, int, int]]]) -> list[list[str]]:
    """Expand rowspan/colspan into a rectangular grid, repeating the spanning cell's text."""

    grid: list[list[str]] = []
    carry: dict[int, tuple[str, int]] = {}
    for row in rows:
        out: list[str] = []
        col = 0
        cells = iter(row)
        cell = next(cells, None)
        while cell is not None or any(key >= col for key in carry):
            if col in carry:
                text, remaining = carry[col]
                out.append(text)
                if remaining > 1:
                    carry[col] = (text, remaining - 1)
                else:
                    del carry[col]
                col += 1
                continue
            if cell is None:
                break
            text, rowspan, colspan = cell
            for offset in range(colspan):
                out.append(text)
                if rowspan > 1:
                    carry[col + offset] = (text, rowspan - 1)
            col += colspan
            cell = next(cells, None)
        grid.append(out)
    return grid


@lru_cache(maxsize=64)
def _grid_tables(value: str) -> list[list[list[str]]]:
    """Like ``_source_tables`` but with rowspan/colspan expanded so columns line up."""

    extractor = _SpanTableExtractor()
    extractor.feed(value)
    extractor.close()
    tables = [_expand_spans(rows) for rows in extractor.tables]
    for fragment in _markdown_pipe_table_fragments(value):
        rows = fragment.splitlines()
        parsed = [_split_pipe_row(rows[0])]
        parsed.extend(_split_pipe_row(row) for row in rows[2:])
        if parsed:
            tables.append(parsed)
    return tables


@lru_cache(maxsize=64)
def _source_tables(value: str) -> list[list[list[str]]]:
    """Return HTML and PDF-style Markdown tables with their source cells."""

    tables = html_tables(value)
    for fragment in _markdown_pipe_table_fragments(value):
        rows = fragment.splitlines()
        parsed = [_split_pipe_row(rows[0])]
        parsed.extend(_split_pipe_row(row) for row in rows[2:])
        if parsed:
            tables.append(parsed)
    return tables


PLAN_TITLE_COLUMN_LABELS = {
    "평가내용",
    "수행평가명",
    "수행평가영역",
    "수행평가과제",
    "평가영역",
    "평가과제",
    "과제명",
}


def _row_answers_label_horizontally(row: list[str], index: int) -> bool:
    """True when the label at ``index`` is answered to its right, in its own row.

    School plans use the same words in two opposite layouts, and only the
    surrounding row says which one this is:

    * label/value row -- ``평가과제 | 우리학교 생태지도 만들기`` names one
      assessment to the right of the label.  The cells *below* it are the next
      plan fields (성취기준, 평가내용, 평가요소, then the rubric dimensions),
      so reading that column downwards invents an assessment per rubric row.
    * column header -- ``평가영역 | 반영비율 | 평가방법 | 시기`` is a row of
      sibling field labels, and the assessments really are listed underneath.

    The distinguishing evidence is the next populated cell in the same row:
    a sibling field label means column header, anything else means the row
    already answered itself.  The answer is deliberately not required to look
    like a task name -- ``평가내용``'s answer is a full sentence, and demanding
    a title-shaped value there would send the scan back down the column and
    invent one assessment per rubric row.
    """

    for cell in row[index + 1 :]:
        compact = compact_text(visible_text(cell))
        if not compact:
            continue
        return not (
            compact in ALL_FIELD_LABELS
            or compact in PLAN_TITLE_COLUMN_LABELS
            or bool(TITLE_VALUE_STOP_LABEL_RE.fullmatch(compact))
            or bool(EXPLICIT_TITLE_LABEL_RE.fullmatch(compact))
        )
    return False


@lru_cache(maxsize=16)
def _table_fragments_with_spans(value: str) -> list[tuple[int, int, str]]:
    fragments = [
        (match.start(), match.end(), match.group(0))
        for match in re.finditer(r"<table\b.*?</table>", value, flags=re.I | re.S)
    ]
    lines = _line_offsets(value)
    index = 0
    while index + 1 < len(lines):
        raw = lines[index][2]
        if not (raw.strip().startswith("|") and PIPE_SEPARATOR_RE.fullmatch(lines[index + 1][2])):
            index += 1
            continue
        start = lines[index][0]
        index += 2
        while index < len(lines) and lines[index][2].strip().startswith("|"):
            index += 1
        end = lines[index - 1][1]
        fragments.append((start, end, value[start:end]))
    return sorted(fragments, key=lambda fragment: (fragment[0], fragment[1]))


def _row_table_html(header: list[str], row: list[str]) -> str:
    width = max(len(header), len(row))
    header_values = [*header, *([""] * (width - len(header)))]
    row_values = [*row, *([""] * (width - len(row)))]

    def cell(value: str) -> str:
        return html.escape(visible_text(value)).replace("\n", "<br>")

    return (
        "<table><thead><tr>"
        + "".join(f"<th>{cell(value)}</th>" for value in header_values)
        + "</tr></thead><tbody><tr>"
        + "".join(f"<td>{cell(value)}</td>" for value in row_values)
        + "</tr></tbody></table>"
    )


def _source_spelling_for_table_value(fragment: str, candidate: str) -> str:
    key = compact_text(candidate)
    for match in re.finditer(r"<(?:th|td)\b[^>]*>(.*?)</(?:th|td)>", fragment, flags=re.I | re.S):
        source_value = visible_text(match.group(1))
        if compact_text(source_value) == key:
            return source_value
    for raw in fragment.splitlines():
        for value in _split_pipe_row(raw) if raw.strip().startswith("|") else []:
            source_value = visible_text(value)
            if compact_text(source_value) == key:
                return source_value
    return candidate


def _matched_rubric_html(block: str, title: str, subject: str = "") -> str:
    """Rubric rows elsewhere in the block that name this task.

    A rubric shared by several courses ("탐구보고서" rows for 생명과학Ⅱ,
    지구과학Ⅱ and 생활과 과학) keeps only rows that are not another course's.
    """

    title_key = compact_text(title)
    matched: list[str] = []
    for _, _, fragment in _table_fragments_with_spans(block):
        tables = _source_tables(fragment)
        if not tables:
            continue
        rows = tables[0]
        for header_index, header in enumerate(rows[:-1]):
            labels = [compact_text(value) for value in header]
            if not any(
                marker in label
                for label in labels
                for marker in ("채점기준", "평가기준", "평가척도", "점수부여기준")
            ):
                continue
            for source_row in rows[header_index + 1 :]:
                row_keys = [compact_text(value) for value in source_row]
                if not any(
                    key == title_key
                    or (len(title_key) >= 6 and title_key in key)
                    or (len(key) >= 6 and key in title_key)
                    for key in row_keys
                    if key
                ):
                    continue
                rendered = _row_table_html(header, source_row)
                if subject and segment_subject_alignment(rendered, subject) == "other":
                    continue
                if rendered not in matched:
                    matched.append(rendered)
            if matched:
                break
    return "\n".join(matched)


def _expected_code_table_items(full_text: str, subject: str) -> list[ParsedAssessmentItem]:
    """Recover explicit task tables when a combined document lost its headings.

    Achievement-standard codes are used only as a rejection/identity boundary:
    every code in the table must belong to the requested biology course.
    The title still has to come from an explicit source label.
    """

    output: list[ParsedAssessmentItem] = []
    seen: set[str] = set()
    for start, end, fragment in _table_fragments_with_spans(full_text):
        if segment_subject_alignment(fragment, subject) != "expected":
            continue
        title = explicit_segment_title(fragment)
        if not title:
            continue
        display_title, _ = _clean_heading_title(title)
        key = compact_text(display_title)
        if not key or key in seen:
            continue
        source_html = markdown_fragment_to_html(fragment)
        fields = _exact_fields(fragment)
        rubric_html = _rubric_html(fragment) or _matched_rubric_html(full_text, title, subject)
        output.append(
            ParsedAssessmentItem(
                order=len(output) + 1,
                title=display_title,
                title_raw=title,
                title_basis="table",
                extraction_status="bounded",
                source_start=start,
                source_end=end,
                source_markdown=fragment,
                source_html=source_html,
                rubric_html=rubric_html,
                overview=str(fields["overview"]),
                method=str(fields["method"]),
                timing=str(fields["timing"]),
                score=str(fields["score"]),
                weight=str(fields["weight"]),
                standards=tuple(str(value) for value in fields["standards"]),
            )
        )
        seen.add(key)
    return output


def _explicit_local_table_items(
    subject_markdown: str,
    subject: str,
    subject_status: str,
    source_offset: int,
) -> list[ParsedAssessmentItem]:
    """Recover a labelled assessment table inside a reliable course section."""

    if subject_status not in {
        "subject_heading",
        "subject_heading_exact",
        "zip_member_subject",
    }:
        return []
    output: list[ParsedAssessmentItem] = []
    seen: set[str] = set()
    for start, end, fragment in _table_fragments_with_spans(subject_markdown):
        alignment = segment_subject_alignment(fragment, subject)
        if alignment == "other":
            continue
        compact_fragment = compact_text(visible_text(fragment))
        strong_label = any(
            label in compact_fragment
            for label in (
                "평가영역명",
                "평가영역",
                "영역만점",
                "수행평가명",
                "수행평가과제",
                "평가과제",
                "수행과제",
                "과제명",
            )
        )
        evidence_markers = sum(
            marker in compact_fragment
            for marker in (
                "성취기준",
                "평가방법",
                "반영비율",
                "채점기준",
                "평가요소",
                "배점",
                "만점",
            )
        )
        if not strong_label or evidence_markers < 2:
            continue
        title = explicit_segment_title(fragment)
        if not title:
            continue
        display_title, _ = _clean_heading_title(title)
        key = compact_text(display_title)
        if not key or key in seen:
            continue
        source_html = markdown_fragment_to_html(fragment)
        fields = _exact_fields(fragment)
        rubric_html = _rubric_html(fragment) or _matched_rubric_html(subject_markdown, title, subject)
        output.append(
            ParsedAssessmentItem(
                order=len(output) + 1,
                title=display_title,
                title_raw=title,
                title_basis="table",
                extraction_status="bounded",
                source_start=source_offset + start,
                source_end=source_offset + end,
                source_markdown=fragment,
                source_html=source_html,
                rubric_html=rubric_html,
                overview=str(fields["overview"]),
                method=str(fields["method"]),
                timing=str(fields["timing"]),
                score=str(fields["score"]),
                weight=str(fields["weight"]),
                standards=tuple(str(value) for value in fields["standards"]),
            )
        )
        seen.add(key)
    return output


def _matrix_table_items(
    value: str,
    subject: str,
    subject_status: str,
    source_offset: int,
) -> list[ParsedAssessmentItem]:
    """Split a source matrix whose columns distinguish written/performance tests."""

    boundary_reliable = subject_status in {
        "subject_heading",
        "subject_heading_exact",
        "zip_member_subject",
    }
    output: list[ParsedAssessmentItem] = []
    seen: set[str] = set()
    for start, end, fragment in _table_fragments_with_spans(value):
        tables = _grid_tables(fragment)
        if not tables:
            continue
        rows = tables[0]
        category_row: list[str] | None = None
        title_row: list[str] | None = None
        for row in rows:
            if not row:
                continue
            first = compact_text(row[0])
            row_labels = [compact_text(cell) for cell in row]
            if (
                category_row is None
                and (
                    first in {"구분", "평가", "유형"}
                    or first.startswith(("평가종류", "평가구분", "평가유형", "평가방법", "반영비율", "평가종류및"))
                )
                and any("수행평가" in label for label in row_labels[1:])
            ):
                category_row = row
                continue
            if title_row is None and first in {
                "평가영역", "평가영역명", "평가내용", "수행평가명", "과제명", "횟수영역", "영역",
                "수행평가영역", "영역명", "평가명", "평가과제", "수행과제", "횟수및영역", "영역횟수",
            }:
                title_row = row
        if category_row is None or title_row is None:
            continue
        performance_columns = [
            index
            for index, cell in enumerate(category_row[1:], 1)
            if "수행평가" in compact_text(cell)
        ]
        for column in performance_columns:
            if column >= len(title_row):
                continue
            candidate = visible_text(title_row[column]).strip()
            key = compact_text(candidate)
            if not key or key in seen or not _valid_plan_title(candidate):
                continue
            if NON_ASSESSMENT_TITLE_RE.search(key) or heading_title_is_structural(candidate):
                continue
            pairs: list[tuple[str, str]] = []
            for row in rows:
                if not row or column >= len(row):
                    continue
                label = visible_text(row[0]).strip()
                cell_value = visible_text(row[column]).strip()
                if not label or not cell_value or len(compact_text(label)) > 40:
                    continue
                pairs.append((label, cell_value))
            if len(pairs) < 3:
                continue
            matrix_html = "<table><tbody>" + "".join(
                f"<tr><th>{html.escape(label)}</th><td>{html.escape(cell_value)}</td></tr>"
                for label, cell_value in pairs
            ) + "</tbody></table>"
            alignment = segment_subject_alignment(matrix_html, subject)
            if alignment == "other" or (alignment == "unknown" and not boundary_reliable):
                continue
            title = strip_title_decoration(_source_spelling_for_table_value(fragment, candidate))
            fields = _exact_fields(matrix_html)
            rubric_html = _matched_rubric_html(value, title, subject)
            source_html = (
                matrix_html
                if not rubric_html
                else matrix_html + "\n" + rubric_html
            )
            output.append(
                ParsedAssessmentItem(
                    order=len(output) + 1,
                    title=title,
                    title_raw=title,
                    title_basis="table",
                    extraction_status="bounded",
                    source_start=source_offset + start,
                    source_end=source_offset + end,
                    source_markdown=source_html,
                    source_html=source_html,
                    rubric_html=rubric_html,
                    overview=str(fields["overview"]),
                    method=str(fields["method"]),
                    timing=str(fields["timing"]),
                    score=str(fields["score"]),
                    weight=str(fields["weight"]),
                    standards=tuple(str(item) for item in fields["standards"]),
                )
            )
            seen.add(key)
    return output


# Cells that name a form or a plan attribute, never an assessment.
NON_ASSESSMENT_TITLE_RE = re.compile(
    r"담당교사|학점|시수|^\d+시간$|양식$|척도안$|척도및배점|^배점|^평가척도|^채점기준|^기본점수|^합계$|^총점"
)
RUBRIC_GROUP_AREA_LABEL_RE = re.compile(r"영역(?:명)?|평가영역|수행평가영역|평가항목")
RUBRIC_GROUP_TITLE_LABEL_RE = re.compile(
    r"^(?:수행평가(?:내용|명|영역|과제)?|평가(?:영역|내용|명|과제|항목)|영역(?:명)?|과제명|수행과제)$"
)


def _score_free_key(value: str) -> str:
    return compact_text(re.sub(r"[(（]\s*\d+\s*점?\s*[)）]", "", visible_text(value)))


def _same_name(rubric_name: str, plan_cell: str) -> bool:
    """"척추동물 해부 (50점)" in a rubric and "척추동물 해부 탐구 보고서" in the plan."""

    key = _score_free_key(rubric_name)
    cell = _score_free_key(plan_cell)
    if len(key) < 6 or len(cell) < 6:
        return key == cell and bool(key)
    return _begins_a_word_of(key, visible_text(plan_cell)) or _begins_a_word_of(
        cell, re.sub(r"[(（]\s*\d+\s*점?\s*[)）]", "", visible_text(rubric_name))
    )


def _table_cell_titles(value: str, skip: tuple[int, int]) -> list[str]:
    """Cells of every plan table outside the ``skip`` span.

    A plan table carries timing, weight or method columns and no rubric.
    """

    cells: list[str] = []
    for start, end, fragment in _table_fragments_with_spans(value):
        if (start, end) == skip:
            continue
        shown = compact_text(visible_text(fragment))
        if not re.search(r"평가시기|반영비율|백분비|평가방법|비율", shown) or re.search(
            r"평가기준|채점기준|수행수준", shown
        ):
            continue
        for match in re.finditer(r"<(?:th|td)\b[^>]*>(.*?)</(?:th|td)>", fragment, flags=re.I | re.S):
            if len(_score_free_key(match.group(1))) >= 2:
                cells.append(match.group(1))
    return cells


def _rubric_group_table_items(
    value: str,
    subject: str,
    subject_status: str,
    source_offset: int,
) -> list[ParsedAssessmentItem]:
    """Split one rubric table whose first column names each assessment.

    대구·서울 plans publish a single 세부 기준 table: ``수행평가 내용 | 평가요소
    | 채점기준 | 점수`` with a rowspan per assessment.  With spans expanded,
    every row carries its assessment name in column 0, so the rows group into
    one item per name, each keeping only its own rubric rows.
    """

    boundary_reliable = subject_status in {
        "subject_heading",
        "subject_heading_exact",
        "zip_member_subject",
    }
    output: list[ParsedAssessmentItem] = []
    seen: set[str] = set()
    for start, end, fragment in _table_fragments_with_spans(value):
        tables = _grid_tables(fragment)
        if not tables or len(tables[0]) < 3:
            continue
        rows = tables[0]
        header = [compact_text(visible_text(cell)) for cell in rows[0]]
        if not header or not RUBRIC_GROUP_TITLE_LABEL_RE.match(header[0]):
            continue
        if not any(re.search(r"채점기준|평가기준|평가척도|수행수준", cell) for cell in header[1:]):
            continue
        if not any(re.search(r"점수|배점", cell) for cell in header[1:]):
            continue
        # Under an area label ("영역", "평가항목") the first column holds the
        # graded elements ("주제 선정 (20점)", "과학적 분석 (30점)") unless a
        # column of its own carries them.
        element_column = any(re.search(r"요소|세부항목|채점항목", cell) for cell in header[1:])
        groups: dict[str, list[list[str]]] = {}
        order: list[str] = []
        for row in rows[1:]:
            if not row:
                continue
            title = visible_text(row[0]).strip()
            key = compact_text(title)
            if not key:
                continue
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(row)
        titles = {key: visible_text(groups[key][0][0]).strip() for key in order}
        candidates = [
            key for key in order
            if len(groups[key]) >= 2 and _valid_plan_title(titles[key])
            and not is_rubric_criterion_sentence(titles[key])
            and not heading_title_is_structural(titles[key])
            and not NON_ASSESSMENT_TITLE_RE.search(compact_text(titles[key]))
        ]
        # …a plan table elsewhere names the same tasks ("탐구 보고서 1" in
        # both the 평가 계획 table and this rubric) -- that is what a list of
        # graded elements never has.
        # A rubric holding one name grades that one task ("평가영역 │ 채점 기준
        # │ 배점" with "원소의 규칙성과 결합 탐구 실험" in every row) -- when
        # that name names a task at all ("주제 선정" is a graded step).
        if RUBRIC_GROUP_AREA_LABEL_RE.fullmatch(header[0]) and not element_column and (
            len(candidates) > 1
            or not (candidates and TASK_NAME_RE.search(titles[candidates[0]]))
        ):
            elsewhere = _table_cell_titles(value, skip=(start, end))
            candidates = [
                key
                for key in candidates
                if any(_same_name(titles[key], cell) for cell in elsewhere)
            ]
        if len(candidates) < 1 or len(candidates) > MAX_BOUNDED_ITEMS:
            continue
        alignment = segment_subject_alignment(fragment, subject)
        if alignment == "other" or (alignment == "unknown" and not boundary_reliable):
            continue
        # A rubric table carries no achievement codes of its own; the codes
        # around it say whose table it is.
        context = value[max(0, start - 2000): end + 400]
        if foreign_subject_codes(unicodedata.normalize("NFC", visible_text(context))):
            continue
        for key in candidates:
            if key in seen:
                continue
            title = strip_title_decoration(titles[key])
            body = "".join(
                "<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>"
                for row in groups[key]
            )
            head = "<tr>" + "".join(f"<th>{html.escape(visible_text(cell))}</th>" for cell in rows[0]) + "</tr>"
            table_html = f"<table>{head}{body}</table>"
            fields = _exact_fields(table_html)
            output.append(
                ParsedAssessmentItem(
                    order=len(output) + 1,
                    title=title,
                    title_raw=title,
                    title_basis="table",
                    extraction_status="bounded",
                    source_start=source_offset + start,
                    source_end=source_offset + end,
                    source_markdown=table_html,
                    source_html=table_html,
                    rubric_html=table_html,
                    overview=str(fields["overview"]),
                    method=str(fields["method"]),
                    timing=str(fields["timing"]),
                    score=str(fields["score"]),
                    weight=str(fields["weight"]),
                    standards=tuple(str(item) for item in fields["standards"]),
                )
            )
            seen.add(key)
    return output


def _hinted_table_items(
    value: str,
    subject: str,
    subject_status: str,
    source_offset: int,
    title_hints: tuple[str, ...],
) -> list[ParsedAssessmentItem]:
    """Validate prior source-table candidates against the full original table."""

    if not title_hints:
        return []
    boundary_reliable = subject_status in {
        "subject_heading",
        "subject_heading_exact",
        "zip_member_subject",
    }
    usable_hints = [
        hint.strip()
        for hint in title_hints
        if _valid_plan_title(hint.strip()) and not heading_title_is_structural(hint.strip())
    ]
    output: list[ParsedAssessmentItem] = []
    seen: set[str] = set()
    for start, end, fragment in _table_fragments_with_spans(value):
        tables = _source_tables(fragment)
        if not tables:
            continue
        cells = [cell for row in tables[0] for cell in row]
        compact_cells = [compact_text(cell) for cell in cells]
        compact_fragment = compact_text(visible_text(fragment))
        evidence_markers = sum(
            marker in compact_fragment
            for marker in (
                "성취기준",
                "평가방법",
                "반영비율",
                "채점기준",
                "평가요소",
                "배점",
                "만점",
            )
        )
        if evidence_markers < 2:
            continue
        alignment = segment_subject_alignment(fragment, subject)
        if alignment == "other" or (alignment == "unknown" and not boundary_reliable):
            continue
        for hint in usable_hints:
            key = compact_text(hint)
            if not key or key in seen:
                continue
            matching_cell = next(
                (
                    cell
                    for cell, cell_key in zip(cells, compact_cells, strict=False)
                    if cell_key == key
                    or (
                        len(key) >= 6
                        and key in cell_key
                        and len(cell_key) - len(key) <= 16
                    )
                ),
                "",
            )
            if not matching_cell:
                continue
            title = strip_title_decoration(_source_spelling_for_table_value(fragment, matching_cell))
            source_html = markdown_fragment_to_html(fragment)
            fields = _exact_fields(fragment)
            rubric_html = _matched_rubric_html(value, title, subject) or _rubric_html(fragment)
            output.append(
                ParsedAssessmentItem(
                    order=len(output) + 1,
                    title=title,
                    title_raw=title,
                    title_basis="table",
                    extraction_status="bounded",
                    source_start=source_offset + start,
                    source_end=source_offset + end,
                    source_markdown=fragment,
                    source_html=source_html,
                    rubric_html=rubric_html,
                    overview=str(fields["overview"]),
                    method=str(fields["method"]),
                    timing=str(fields["timing"]),
                    score=str(fields["score"]),
                    weight=str(fields["weight"]),
                    standards=tuple(str(item) for item in fields["standards"]),
                )
            )
            seen.add(key)
    return output


def _summary_table_items(
    block: str,
    subject: str,
    subject_status: str,
    source_offset: int,
) -> list[ParsedAssessmentItem]:
    """Recover individually source-bounded rows from explicit plan tables.

    This path never turns a nearby heading or prose phrase into a title.  It
    requires an explicit task-name column and retains only that source row plus
    its source header.  It is especially important for PDF plans whose two or
    three assessments are rows in one table rather than numbered subsections.
    """

    subject_boundary_reliable = subject_status in {
        "subject_heading",
        "subject_heading_exact",
        "zip_member_subject",
    }
    output: list[ParsedAssessmentItem] = []
    seen: set[str] = set()
    for start, end, fragment in _table_fragments_with_spans(block):
        tables = _source_tables(fragment)
        if not tables:
            continue
        rows = tables[0]
        for header_index, header in enumerate(rows[:-1]):
            labels = [compact_text(value) for value in header]
            plan_markers = any(
                marker in label
                for label in labels
                for marker in ("성취기준", "반영비율", "평가방법", "평가시기", "만점")
            )
            rubric_like_header = any(
                "채점기준" in label for label in labels
            ) or (
                any("평가요소" in label for label in labels) and not plan_markers
            )
            if rubric_like_header:
                # Rows under a rubric header are criteria/dimensions, not
                # additional performance-assessment names.  Real task names
                # are recovered from the plan table or their own heading.
                continue
            summary_markers = any(
                marker in label
                for label in labels
                for marker in ("반영비율", "평가방법", "평가시기", "만점")
            )
            title_columns = []
            for index, label in enumerate(labels):
                if label not in PLAN_TITLE_COLUMN_LABELS:
                    continue
                if label in {"평가영역", "수행평가영역"} and not summary_markers:
                    continue
                if _row_answers_label_horizontally(header, index):
                    continue
                title_columns.append(index)
            if not title_columns:
                continue
            evidence_columns = sum(
                bool(
                    label in ALL_FIELD_LABELS
                    or any(
                        marker in label
                        for marker in (
                            "성취기준",
                            "평가방법",
                            "평가요소",
                            "채점기준",
                            "배점",
                            "만점",
                            "반영비율",
                            "시기",
                        )
                    )
                )
                for label in labels
            )
            if evidence_columns < 1:
                continue
            # "평가영역 │ 만점 │ │ 100점" pairs labels with values; its first
            # column is not a list of task names.
            if any(
                re.fullmatch(r"[(（]?\s*\d+(?:\.\d+)?\s*(?:점|%)\s*[)）]?", visible_text(cell).strip())
                for cell in header
            ):
                continue
            for source_row in rows[header_index + 1 :]:
                for column in title_columns:
                    if column >= len(source_row):
                        continue
                    candidate = visible_text(source_row[column]).strip()
                    key = compact_text(candidate)
                    if not key or key in seen or not _valid_plan_title(candidate):
                        continue
                    row_html = _row_table_html(header, source_row)
                    alignment = segment_subject_alignment(row_html, subject)
                    if alignment == "other" or (
                        alignment == "unknown" and not subject_boundary_reliable
                    ):
                        continue
                    populated_other = sum(
                        bool(visible_text(value))
                        for index, value in enumerate(source_row)
                        if index != column
                    )
                    if populated_other < 1:
                        continue
                    title = strip_title_decoration(_source_spelling_for_table_value(fragment, candidate))
                    fields = _exact_fields(row_html)
                    matched_rubric = _matched_rubric_html(block, title, subject)
                    source_html = (
                        row_html
                        if not matched_rubric or matched_rubric == row_html
                        else row_html + "\n" + matched_rubric
                    )
                    output.append(
                        ParsedAssessmentItem(
                            order=len(output) + 1,
                            title=title,
                            title_raw=title,
                            title_basis="table",
                            extraction_status="bounded",
                            source_start=source_offset + start,
                            source_end=source_offset + end,
                            source_markdown=source_html,
                            source_html=source_html,
                            rubric_html=(
                                matched_rubric or row_html
                                if any(
                                    "채점기준" in label or "평가기준" in label
                                    for label in labels
                                )
                                else matched_rubric
                            ),
                            overview=str(fields["overview"]),
                            method=str(fields["method"]),
                            timing=str(fields["timing"]),
                            score=str(fields["score"]),
                            weight=str(fields["weight"]),
                            standards=tuple(str(value) for value in fields["standards"]),
                        )
                    )
                    seen.add(key)
    return output


def _plan_titles(subject_markdown: str) -> list[str]:
    """Read explicit assessment-name cells from plan tables without guessing."""

    titles: list[str] = []
    for rows in _source_tables(subject_markdown):
        for row_index, row in enumerate(rows):
            labels = [compact_text(cell) for cell in row]
            content_columns = [
                index
                for index, label in enumerate(labels)
                if label in {"평가내용", "수행평가명", "수행평가영역", "평가영역", "과제명"}
            ]
            for column in content_columns:
                for following in rows[row_index + 1 :]:
                    if column >= len(following):
                        continue
                    candidate = visible_text(following[column])
                    if _valid_plan_title(candidate):
                        titles.append(candidate)
            if "평가요소방법" in labels and any(label == "수행평가" for label in labels):
                for index, label in enumerate(labels):
                    if label != "수행평가" or index >= len(row):
                        continue
                    candidate = visible_text(row[index])
                    if _valid_plan_title(candidate):
                        titles.append(candidate)
            for index, label in enumerate(labels[:-1]):
                if label in {"수행평가명", "수행평가과제명", "평가과제명", "과제명"}:
                    for candidate_cell in row[index + 1 :]:
                        candidate = visible_text(candidate_cell)
                        if _valid_plan_title(candidate):
                            titles.append(candidate)
    output: list[str] = []
    seen: set[str] = set()
    for title in titles:
        key = compact_text(title)
        if key and key not in seen:
            seen.add(key)
            output.append(title)
    return output


def _valid_plan_title(value: str) -> bool:
    compact = compact_text(value)
    if not _valid_title(value):
        return False
    # 표 셀에서 온 제목도 헤딩과 같은 판정을 받아야 한다. 아래 리터럴 목록만
    # 두었을 때 "동점자 처리 1순위", "배점 및 만점", "장기 미인정 결시자"처럼
    # 목록에 없는 라벨이 그대로 과제명으로 올라왔다.
    if heading_is_policy_prose(value):
        return False
    return not bool(
        len(compact) > 60
        or re.search(r"[.。]$", value.strip())
        or
        compact
        in {
            "수행평가",
            "평가영역",
            "영역만점",
            "평가내용",
            "평가항목",
            "평가요소",
            "채점기준",
            "배점",
            "평소",
            "단원",
            "수준",
            "학습",
            "직무",
            "그외",
            "과학과",
            "점수점",
            "평가만점",
            "평가방법",
            "반영비율",
            "평가시기",
            "평가요소방법",
            "정기시험",
        }
        or re.search(r"(?:평가|반영)\s*비율|\d+\s*(?:점|%)$", value)
        or re.fullmatch(
            r"(?:통합과학[12]\s*전체|(?:정기\s*)?\d+\s*차\s*시험|중간|기말|"
            r"[IVⅠⅡⅢⅣ]+)",
            value.strip(),
        )
        or re.fullmatch(r"(?:프로젝트|포트폴리오|서술형|논술형|교사\s*관찰)\s*평가", value)
        # Written-exam names reach every table path, not only the explicit-label
        # one, so the gate belongs in this shared validator.  The published
        # title is the cleaned form ("1차고사(30%)" is displayed as "1차고사"),
        # so both spellings have to be checked.
        or NON_TASK_TITLE_RE.fullmatch(value.strip())
        or NON_TASK_TITLE_RE.fullmatch(_clean_heading_title(value)[0])
        or is_rubric_criterion_sentence(value)
        # An achievement-standard code identifies the curriculum statement the
        # task is assessed against, never the task. Some compact plan matrices
        # put nothing else in the 평가내용 cell, so the honest result is no
        # title rather than publishing the code as the assessment's name.
        or ACHIEVEMENT_CODE_TITLE_RE.match(strip_title_decoration(value))
        # A bare score/percentage is a shared matrix column header.
        or SCORE_ONLY_TITLE_RE.fullmatch(strip_title_decoration(value))
    )


def _unique_values(values: list[str], limit: int = 8) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = re.sub(r"\s+", " ", value).strip(" |")
        key = compact_text(clean)
        if not clean or not key or key in seen:
            continue
        seen.add(key)
        output.append(clean)
        if len(output) >= limit:
            break
    return output


_STANDARD_CODE_SHAPE_RE = re.compile(r"\[\s*(\d{0,2}[가-힣][^\]]{0,22})\]")


def biology_standard_codes(shown: str) -> list[str]:
    """Return only the achievement codes that belong to this 교과군.

    The old pattern took any bracket starting ``10``/``12``, so a 보건과 code
    (``[12보05-03]``) counted as a biology standard while a code the school
    spelled without the grade digits was missed.  A code has to carry a
    ``NN-NN`` area/item number to be one at all -- ``[12생과02~02]`` is an
    extraction artefact, ``[10통과1-01]`` names an area, not a standard -- and
    its Hangul name has to be one of this 교과군's.
    """

    codes = []
    for match in _STANDARD_CODE_SHAPE_RE.finditer(shown):
        body = match.group(1)
        if not re.search(r"\d{2}\s*-\s*\d{2}", body):
            continue
        core = re.sub(r"[^가-힣]", "", subject_code_key(body))
        if not any(
            core.startswith(known) or known.startswith(core)
            for known in BIOLOGY_CODE_CORES
            if known
        ):
            continue
        codes.append(f"[{body.strip()}]")
    return codes


# 점수·배점·비율 칸은 숫자가 없으면 값이 아니라 표 머리글이다("등급 · 평가 척도 ·
# 배점"). 시기 칸은 월·주 표기뿐이라, 다른 칸의 라벨이 섞여 있으면 표 행 전체가
# 통째로 들어온 것이다("단원명 · Ⅰ. 과학의 기초 · 평가영역 · Ⅱ-1 자연의 구성원소").
_FIELD_VALUE_MAX_LENGTH = {"timing": 40, "method": 120, "overview": 600}
_LEAKED_ROW_IN_TIMING_RE = re.compile(
    r"단원명|평가\s*영역|성취\s*기준|반영\s*비율|채점\s*기준|평가\s*요소|배점|만점"
)


def _field_value_is_usable(key: str, value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if key in {"score", "weight"} and not re.search(r"\d", text):
        return False
    return not (key == "timing" and _LEAKED_ROW_IN_TIMING_RE.search(text))


def _joined_field_value(key: str, values: list[str]) -> str:
    """Join a field's cells, dropping the join when it grew into a whole row.

    The length cap is applied after joining, not per cell: a 평가 시기 row that
    leaked in arrives as several short cells ("단원명", "Ⅰ. 과학의 기초 …",
    "평가영역"), each innocuous on its own.
    """

    joined = " · ".join(_unique_values(values, 4))
    limit = _FIELD_VALUE_MAX_LENGTH.get(key)
    if limit and len(compact_text(joined)) > limit:
        return ""
    return joined


_METHOD_BOX_SPLIT_RE = re.compile(r"(?=[☑□■])")


def _ticked_method_values(values: list[str]) -> list[str]:
    """Keep only the ticked options of a 평가 방법 checkbox menu.

    kordoc keeps the tick ("□V" → ``☑``), so a menu row is
    "☑ 서술·논술 □ 구술·발표 □ 토의･토론"; taking the whole row would read as if
    every option were chosen and soon overflows the field's length cap.  Rows
    without any box are values the school typed, kept as they are; a row of
    empty boxes contributes only the text before its first box (that option's
    own tick was lost), the same rule ``app.repository.display_methods`` uses.
    """

    if not any("☑" in value for value in values):
        out = []
        for value in values:
            if "□" in value:
                leading = value.split("□", 1)[0].strip(" ·|")
                if leading:
                    out.append(leading)
            else:
                out.append(value)
        return out
    ticked: list[str] = []
    for value in values:
        for segment in _METHOD_BOX_SPLIT_RE.split(value):
            segment = segment.strip(" ·|")
            if segment.startswith("☑") and segment.strip("☑ ·|"):
                ticked.append(segment)
    return ticked


def _exact_fields(segment: str) -> dict[str, object]:
    found: dict[str, list[str]] = {key: [] for key in FIELD_LABELS}
    # Spans expanded: a label merged over three rows (평가 방법 over a three-row
    # checkbox menu) labels every one of those rows, not only the first.
    for rows in _grid_tables(segment):
        for row_index, row in enumerate(rows):
            labels = [compact_text(cell) for cell in row]
            for key, wanted in FIELD_LABELS.items():
                for index, label in enumerate(labels):
                    if label not in wanted:
                        continue
                    # Header rows commonly contain "반영 비율 | 세부기준 |
                    # 점수".  Those are labels, not a value.  Exact field
                    # extraction therefore accepts only the first following
                    # non-label cell from a label/value-style row.
                    same_row: list[str] = []
                    for cell in row[index + 1 :]:
                        candidate = visible_text(cell)
                        candidate_label = compact_text(candidate)
                        # A new field label ends this field's merged-cell span.
                        if candidate_label in ALL_FIELD_LABELS:
                            break
                        if candidate and candidate_label != label:
                            same_row.append(candidate)
                    if same_row:
                        if key == "method":
                            # An all-empty menu yields nothing; it is still this
                            # row's value, not a header over the next row.
                            same_row = _ticked_method_values(same_row)
                        found[key].extend(same_row)
                    else:
                        # PDF extraction also produces a pure multi-field header
                        # row followed by values in the same columns.
                        for following in rows[row_index + 1 :]:
                            if index >= len(following):
                                continue
                            candidate = visible_text(following[index])
                            candidate_label = compact_text(candidate)
                            if not candidate or candidate_label in ALL_FIELD_LABELS:
                                continue
                            found[key].append(candidate)
                            break
    if any("☑" in value for value in found["method"]):
        # Once any row is a ticked menu, the 평가 방법 prose rows beside it
        # ("범위: 전범위 …") and stray labels are not the chosen methods.
        found["method"] = [value for value in found["method"] if "☑" in value]
    standards = _unique_values(biology_standard_codes(visible_text(segment)), 24)
    return {
        key: _joined_field_value(key, [v for v in values if _field_value_is_usable(key, v)])
        for key, values in found.items()
    } | {"standards": standards}


class _SafeTableParser(StdlibHTMLParser):
    allowed_tags = {"table", "thead", "tbody", "tfoot", "tr", "th", "td", "br", "caption"}
    allowed_attrs = {"rowspan", "colspan"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self.allowed_tags:
            return
        safe_attrs: list[str] = []
        for name, value in attrs:
            if name.lower() not in self.allowed_attrs or value is None:
                continue
            if value.isdigit() and 1 <= int(value) <= 50:
                safe_attrs.append(f' {name.lower()}="{int(value)}"')
        self.output.append(f"<{tag}{''.join(safe_attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br":
            self.output.append("<br>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.allowed_tags and tag != "br":
            self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.output.append(html.escape(mask_seal_names(normalize_checkbox_glyphs(data))))


def sanitize_table_html(value: str) -> str:
    parser = _SafeTableParser()
    parser.feed(value)
    parser.close()
    return "".join(parser.output)


def _split_pipe_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown_fragment_to_html(markdown: str) -> str:
    """Render the parser's restricted Markdown/HTML subset to safe HTML."""

    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.search(r"<table\b", line, flags=re.I):
            chunk: list[str] = []
            depth = 0
            while index < len(lines):
                current = lines[index]
                chunk.append(current)
                depth += len(re.findall(r"<table\b", current, flags=re.I))
                depth -= len(re.findall(r"</table>", current, flags=re.I))
                index += 1
                if depth <= 0:
                    break
            # Every source table is published as its own table.  The old
            # extractor split tables at page breaks and this function guessed
            # which neighbours to fuse; kordoc keeps a table whole, and the
            # back-to-back pairs it does emit are nearly always the next
            # assessment's table ("평가과제(영역)명 | …"), which fusing would
            # wrongly attach to the previous one.
            output.append(sanitize_table_html("\n".join(chunk)))
            continue
        if (
            line.strip().startswith("|")
            and index + 1 < len(lines)
            and PIPE_SEPARATOR_RE.fullmatch(lines[index + 1])
        ):
            headers = _split_pipe_row(line)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(_split_pipe_row(lines[index]))
                index += 1
            header_html = "".join(f"<th>{_inline_html(cell)}</th>" for cell in headers)
            output.append(f"<table><thead><tr>{header_html}</tr></thead><tbody>")
            for row in rows:
                row_html = "".join(f"<td>{_inline_html(cell)}</td>" for cell in row)
                output.append(f"<tr>{row_html}</tr>")
            output.append("</tbody></table>")
            continue
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            level = min(6, len(heading.group(1)) + 1)
            output.append(f"<h{level}>{_inline_html(heading.group(2))}</h{level}>")
        elif re.match(r"^[-*•▪]\s+", stripped):
            list_text = re.sub(r"^[-*•▪]\s+", "", stripped)
            output.append(f'<p class="source-list-item">• {_inline_html(list_text)}</p>')
        else:
            output.append(f"<p>{_inline_html(stripped)}</p>")
        index += 1
    return balance_table_tags("\n".join(output))


def balance_table_tags(value: str) -> str:
    """Close extractor-truncated table tags without changing source text."""

    opening = len(re.findall(r"<table\b", value, flags=re.I))
    closing = len(re.findall(r"</table>", value, flags=re.I))
    if opening > closing:
        return value + ("\n</table>" * (opening - closing))
    return value


def _inline_html(value: str) -> str:
    escaped = html.escape(mask_seal_names(normalize_checkbox_glyphs(html.unescape(value))))
    escaped = re.sub(r"&lt;br\s*/?&gt;", "<br>", escaped, flags=re.I)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def _rubric_html(segment: str) -> str:
    tables: list[str] = []
    for match in re.finditer(r"<table\b.*?</table>", segment, flags=re.I | re.S):
        shown = visible_text(match.group(0))
        if re.search(r"채점\s*기준|세부\s*기준|평가\s*요소", shown) and re.search(
            r"점수|배점|부여\s*점수", shown
        ):
            tables.append(sanitize_table_html(match.group(0)))
    for fragment in _markdown_pipe_table_fragments(segment):
        shown = visible_text(fragment)
        if re.search(r"채점\s*기준|세부\s*기준|평가\s*요소", shown) and re.search(
            r"점수|배점|부여\s*점수|척도", shown
        ):
            tables.append(markdown_fragment_to_html(fragment))
    return balance_table_tags("\n".join(tables))


# Unit names of the courses in scope (2015·2022 통합과학·과학탐구실험·생명과학
# 교과군), compact.  A title that is only one or more of these names the
# content assessed, not the task ("생명공학 기술과 인간생활", "물질과 규칙성
# (화학 결합)", "세포의 특성, 유전자의 발현과 조절").
CURRICULUM_UNIT_NAMES = frozenset(
    compact_text(name)
    for name in (
        # 통합과학(2015)·통합과학1·2(2022)
        "물질의 규칙성과 결합", "자연의 구성 물질", "역학적 시스템", "지구 시스템", "생명 시스템",
        "화학 변화", "생물 다양성과 유지", "생태계와 환경", "발전과 신재생 에너지",
        "과학의 기초", "물질과 규칙성", "시스템과 상호작용", "변화와 다양성", "환경과 에너지",
        "과학과 미래 사회", "기본량과 측정", "기본량과 유도단위", "측정 표준", "자연의 구성 원소",
        "원소의 생성", "원소의 형성", "우주의 형성", "우주와 원소의 진화", "원소의 규칙성",
        "원소의 규칙성과 결합", "원소의 주기성과 결합", "원소의 주기성과 화학 결합",
        "주기율표와 원소의 주기성", "물질의 규칙성과 성질", "화학 결합", "지구시스템",
        "지구시스템의 구성과 상호작용", "역학 시스템", "중력과 역학 시스템", "생명시스템",
        "생명 시스템의 구성", "생명체를 구성하는 물질", "지각과 생명체의 구성물질",
        "지각과 생명체를 구성하는 물질", "생명체에서 일어나는 화학 반응", "세포 내 정보의 흐름",
        "환경과 인간", "자원과 에너지", "산과 염기의 성질", "다양한 상호 작용",
        "지질시대 환경과 생물다양성", "생태계와 상호 작용", "생물과 환경", "물질의 규칙성",
        "환경과 생태계", "어림과 측정", "원소의 주기성", "고전 역학", "생물의 특성",
        "물질대사와 에너지",
        # 생명과학Ⅰ·Ⅱ(2015)
        "생명 과학의 이해", "사람의 물질대사", "항상성과 몸의 기능", "유전", "생명과학의 역사",
        "세포의 특성", "세포 호흡과 광합성", "유전자의 발현과 조절", "유전자 발현과 조절",
        "유전자 발현 조절", "생물의 진화와 다양성", "생명 공학 기술과 인간 생활",
        "생명공학 기술과 인간생활",
        # 생명과학·세포와 물질대사·생물의 유전(2022)
        "생명 시스템의 구성", "항상성과 몸의 조절", "생명의 연속성과 다양성", "생명의 연속성",
        "세포와 물질대사", "생물의 유전", "유전의 이해", "유전과 진화",
        # 고급생명과학·생명과학실험
        "생물의 구조와 에너지", "생명의 구조와 에너지", "생물의 조절과 방어", "세포의 조절과 방어",
        "생명공학기술과 미래", "현대 생물학과 인간의 미래", "생물의 분류와 다양성",
        "생물의 분류체계", "생명공학의 기술과 응용", "생명공학기술의 응용", "생명 공학 기술",
        "기관계의 통합적 작용", "병원체와 방어작용", "생태계의 구조",
        # 과학탐구실험1(2022).  2015 단원("생활 속의 과학 탐구")은 학교가
        # 과제명으로도 써서 넣지 않는다.
        "과학의 본성과 역사 속의 과학 탐구", "과학 탐구의 과정과 절차",
        # 주제 낱말
        "물질대사", "세포 호흡", "광합성", "효소", "신경", "근육", "군집", "분류", "생물 분류",
        "생명공학", "생명중심원리", "생명의 기원", "전사와 번역",
    )
)
UNIT_PREFIX_RE = re.compile(
    r"^\s*(?:학습\s*활동|내용\s*영역\s*[:：])?\s*(?:[(（]?\s*(?:[ⅠⅡⅢⅣⅤⅥ]|[IVX]{1,3}|\d{1,2})"
    r"\s*[)）.．]?\s*(?:-\s*\d+\s*[.．]?)?\s*)?"
)


def _names_only_units(title: str) -> bool:
    """True when every part of the title is a curriculum unit name."""

    text = re.sub(r"[(（]([^()（）]*)[)）]", r", \1", title)
    parts = re.split(
        r"\s*(?:[,，·⦁•/~∼]|\s및\s|\s(?=(?:[ⅠⅡⅢⅣⅤⅥ]|[IVX]{1,3}|\d{1,2})\s*[.．)]))\s*", text
    )
    keys = [
        compact_text(re.sub(r"\d+$", "", UNIT_PREFIX_RE.sub("", part)).strip())
        for part in parts
    ]
    keys = [key for key in keys if key]
    return bool(keys) and all(_joined_units(key) for key in keys)


def _joined_units(key: str) -> bool:
    """"생명과학의역사세포의특성": unit names written one after another."""

    if key in CURRICULUM_UNIT_NAMES:
        return True
    return any(
        key.startswith(name) and len(name) < len(key) and _joined_units(key[len(name) :])
        for name in CURRICULUM_UNIT_NAMES
        if len(name) >= 4
    )


# Cells that label a plan's columns, rows or values rather than name a task.
NOT_A_TASK_LABEL_RE = re.compile(
    r"^(?:"
    r"\d{1,2}\s*월(?:\s*\d\s*주)?|\d{1,2}\s*(?:월\s*)?[~∼-]\s*\d{1,2}\s*월|수시|누계|"
    r"(?:총\s*)?\d+\s*(?:회|개\s*항목)|(?:수행|탐구)\s*\d+\s*회|"
    r"(?:수행\s*평가|수행\s*영역|수행|평가\s*과제|활동지|영역)\s*\d+(?:\s*[(（][^()（）]{1,8}[)）])?|"
    r"제\s*\d+\s*영역|교사\s*[A-Z]|[A-Z]\s*/\s*[A-Z]|"
    r"(?:상|중|하|보통|우수|미흡|탁월|매우\s*우수)(?:\s*[(（].*)?|"
    r"평가\s*기준\s*\d\s*단계|\d+\s*[×x]\s*\d+\s*회|수준\s*[(（]\s*배점\s*[)）]|"
    r"(?:과정\s*중심|과정형)\s*수행\s*평가|\d\s*학년\s*[(（][^()（）]*[)）]|\d\s*학기\s*평가\s*과제|"
    r"[가-힣,\s]{1,12}반|[가-힣\s]{1,8}보고서형|[^()]*이외의\s*평가|"
    r"[IVX]{1,3}\s*(?:~\s*[IVX]{1,3}\s*)?단원|"
    r"(?:단답형|완성형|선다형|선택형|서답형|기타형|발표형)(?:\s*[,，]\s*"
    r"(?:단답형|완성형|선다형|선택형|서답형|서술형))*(?:\s*평가)?|"
    r"(?:관찰법|체크리스트|질문지|교사\s*관찰|동료\s*평가|자기\s*평가|의미\s*분석법|"
    r"체크리스트\s*질문지|의미\s*분석법\s*질문지)(?:\s*[,，∙·]\s*\S+){0,3}"
    r")$"
)
# Section and table titles of the plan ("1학기 수행평가 시행 계획 및 세부
# 채점 기준", "결과의 활용", "평가준거 성취기준 및 평가 요소").
NOT_A_TASK_SECTION_RE = re.compile(
    r"(?:평가\s*계획|세부\s*계획|시행\s*계획|운영\s*계획|평가\s*척도|세부\s*평가\s*척도|채점\s*기준|"
    r"평가\s*방식|평가\s*방법(?:\s*예시)?|실시\s*시기|운영\s*시기(?:\s*및\s*과정)?|평가\s*지침|"
    r"기본\s*방침|결과의?\s*활용|결과\s*처리|성적\s*산출(?:\s*방식|\s*개요.*)?|진술문|"
    r"점수\s*부여\s*기준|부여\s*등급\s*및\s*배점|반영\s*비율|평가\s*요소|평가\s*영역명|"
    r"성취\s*수준(?:\s*[(（][^()（）]*[)）])?|성취\s*기준(?:\s*및\s*(?:성취\s*수준|평가\s*(?:요소|방법)))?|"
    r"핵심\s*아이디어|주요\s*학습\s*내용|평가\s*내용|세부(?:\s*기준)?|구체\s*내용\s*및\s*기준|"
    r"특기\s*사항|진도표|방침)$|채점\s*기준\s*[-–]"
    r"|^(?:성취\s*기준\s*[:：]|내용\s*영역\s*[:：]|관련\s*교육과정|교육과정\s*성취\s*기준|전\s*단원$|"
    r"단원명$|정의적$|목표$|그\s*외(?:\s*영역)?$|활용$|탐구\s*영역$|평가\s*별)"
)
# What a rubric grades about the work, not the work ("실험 보고서의 체계적
# 작성 정도", "탐구 주제의 적합성", "학습 참여도", "(1) 주제 선정하기").
NOT_A_TASK_ELEMENT_RE = re.compile(
    r"(?:정도|능력|태도|참여도|준비도|적절성|정확성|타당성|연관성|적합성|충실성|충실도|체계성|"
    r"논리성|성실성|창의성|실천|이해도)$|^자기\s*성찰$"
    r"|-\s*\d$|[(（]\s*\d\s*회\s*당\s*[)）]$|^제출\s*기한|기본\s*점수|^많은\s*내용"
)
# Numbered steps of one task ("(1) 주제 선정하기", "1단계 탐구 계획 세우기").
NOT_A_TASK_STEP_RE = re.compile(r"^[(（]\s*\d\s*[)）]\s*\S|^\d\s*단계\s")
NOT_A_TASK_PROSE_RE = re.compile(
    # "성취기준에 기반한 일관성 있는 평가" -- a principle of the plan
    r"^.{8,}(?:있는|적인|기반한|위한)\s*평가$|해당\s*사항\s*없음|는\s+가\s*\??$|"
    r"^(?:학생(?:들)?(?:이|의|은|에게)\s|학생\s*활동을|학부모|평가의\s|평가\s*항목\s*[(（]|"
    r"수행\s*평가\s*[:：]|점\s*[(（]|전입)|^.{12,}(?:학생|기반)$|"
    r"(?:에\s*따름|참\s*[고조]|금지|발생\s*시|보관|해당\s*사항\s*없음|처리\s*기준|결석자|"
    r"정도로\s*배점|단계별\s*계획|입력\s*순\)?|실시함\.?.*)\s*\)?\.?$"
    r"|^하단의|^\d+\s*%\s*[(（]|^(?:이용한|및)\s|^실험\s*및\s*과학의$|^귀납적\s*및\s*연역적$"
)
NOT_A_TASK_EXAM_RE = re.compile(
    r"(?:\d\s*(?:차|회)|\d\s*학기)\s*(?:고사|시험)|정기\s*고사|(?:중간|기말)\s*시험|^Test\s"
)


GARBLED_TEXT_RE = re.compile("[\uA720-\uA7FF\uA960-\uA97F\uD7B0-\uD7FF\u3400-\u4DBF\u4E00-\u9FFF]")
MULTI_TASK_CELL_RE = re.compile(r"\S\s+(?:\d{1,2}\s*\)|\d{1,2}\s*[.．]\s|[②-⑳])\s*\S")


def _not_a_task_name(title: str) -> bool:
    """Plan labels, unit names, rubric elements, policy lines and exams.

    These reached the task list through table cells the scans read as
    names.  Each is checked on the title as displayed.
    """

    clean = title.strip()
    compact = compact_text(clean)
    if not compact:
        return True
    # A teacher's name ("지도교사: 홍길동") and text decoded from the wrong
    # code page ("솟駖 뙛Ꜯ됖") are never a task.
    if re.search(r"교사\s*[A-Za-z]?\s*[:：]", clean) or GARBLED_TEXT_RE.search(clean):
        return True
    # Several tasks written into one cell ("주기율표 탐험. 2) 이온 결합의 세계",
    # "⦁동식물 세포 관찰 ⦁해부 실험", "… 사례를 설명하기 ② 과학사에서 …").
    if MULTI_TASK_CELL_RE.search(clean) or len(re.findall(r"[⦁•◦▪]", clean)) >= 2:
        return True
    if NOT_A_TASK_LABEL_RE.fullmatch(clean) or COURSE_NAME_ONLY_RE.fullmatch(
        re.sub(r"[A-D]$", "", compact)
    ):
        return True
    if _names_only_units(clean):
        return True
    if NOT_A_TASK_SECTION_RE.search(clean) and not re.search(r"하기|탐구\s*보고서|실험\s*보고서", clean):
        return True
    if NOT_A_TASK_EXAM_RE.search(clean) or NOT_A_TASK_PROSE_RE.search(clean):
        return True
    if NOT_A_TASK_STEP_RE.search(clean):
        return True
    if NOT_A_TASK_ELEMENT_RE.search(clean) and not re.search(r"하기$|보고서$|프로젝트$|만들기$", clean):
        return True
    return _not_a_task_name_2026_11(clean, compact)


# 2026-11-01 전수 감사에서 과제명으로 나간 것들.
# 절 제목·방침 줄. 머리글 후보를 고를 때는 쓰지 않는다: "정기 시험, … 성적 처리"
# 같은 줄은 앞 과제 구간의 끝을 정하는 경계 노릇을 한다.
NOT_A_TASK_DOCUMENT_SECTION_RE = re.compile(
    # 2026-11-01 감사에서 과제명으로 나간 절 제목·방침 줄: "평가 목표", "평가 시
    # 유의점", "평가 주안점", "정기시험(미실시)", "정기시험과 수행평가의 성적 반영
    # 비율…", "환산 점수 (점)", "통합학급 참여 시", "디지털 환경 활용 평가",
    # "※교과특성에 맞춰 편집하여 작성※"(양식 안내), "문항 배점 : 다단계 배점".
    r"^평가\s*(?:목표|주안점)$|유의\s*점$|^정기\s*시험|^환산\s*점수|환산\s*점수\s*\d|"
    r"통합\s*학급|^디지털\s*(?:교수|환경|학습)|편집하여\s*작성|^※.*※$|^문항\s*배점|"
    r"^평가\s*요소\s*및\s*수행\s*수준|^성취\s*기준\s*기반\s*평가$|0\s*점\s*처리|"
    r"^가치\s*및\s*태도|^[‘'\"]?교수\s*[-·‧]?\s*학습\s*[-–]\s*평가\s*방법|없을\s*시|"
    r"^\d\s*학기\s*수행\s*평가\s*세부\s*계획|평가\s*과제별로\s*작성|"
    r"^수행\s*평가\s*영역별\s*세부\s*기준|세부\s*내용(?:\s*및(?:\s*평가\s*기준)?)?$|"
    # "이 외에 수행평가에 관한 세부 방침과 …", "매 수행평가 실시 전 학습자가 … 분명히 알 수
    # 있도록", "… 평가에 관한 준비", "수행평가에서 정의적 영역만 찾아 서술"
    r"방침과|평가\s*문제\s*인쇄|보안\s*관리|실시\s*전\s*학습자|분명히\s*알\s*수|"
    r"평가에\s*관한\s*준비|^수행\s*평가에서\s|^이\s*외에\s"
)

# 탐구 단계 이름("결론도출", "문제인식 및 가설설정", "탐구 설계")은 채점표의 줄이다.
# "자료해석", "탐구 설계"처럼 학교가 영역 이름으로도 쓰는 말은 넣지 않는다.
INQUIRY_STEP_COMPACT_RE = re.compile(
    r"문제인식(?:및|과|와)?가설설정|(?:실험)?결(?:과|론)도출|결과정리및결론도출|탐구및분석"
)
# 채점 문장: "~하는가?", "5가지 항목을 모두 적절하게 작성"
CRITERION_TEXT_RE = re.compile(
    # "어디에서 왔는가?"처럼 묻는 과제명은 남긴다: 채점 문장은 "~하였는가?"이거나
    # 물음 뒤에 다른 기준이 이어진다.
    r"(?:하였|했|되었)는\s*가\s*\?|는\s*가\s*\?\s*[-–]|"
    r"(?:적절하게|정확하게|올바르게|충실하게|모두)\s+\S*\s*(?:작성|제시|설명|표현)함?$"
)
# 평가 요소 명사: "관련성", "전달력", "내용 요소", "내용의 다양성"
ELEMENT_NOUN_RE = re.compile(
    r"^(?:관련성|전달력|독창성|구체성|명확성|표현력)$|완성도$|내용\s*의?\s*다양성$|^내용\s*요소$"
)
# 평가 능력 나열: "과학적 탐구 능력, 과학적 문제 해결 능력, 과학적 참여"
COMPETENCY_PART_RE = re.compile(
    r"(?:능력|역량|기능|태도|(?<![작구완형육합생편])성|력|참여|해석|쓰기)(?:\s*[(（][^()（）]*[)）])?$"
)
# 지필 요약표의 문항 유형: "서술형5)", "논서술형16)"
EXAM_ITEM_TYPE_RE = re.compile(r"(?:서|논|서논|논서|서[·･・]논)술형\s*\d+\s*\)")
# "서･논술형, 그 외" -- 쉼표로 늘어놓은 평가 방법뿐. "실험·실습" 하나는 영역 이름이다.
_METHOD_WORD = r"(?:서[·･・]?논술형?|논술형?|서술형?|구술|발표|토론|토의|실험|실습|그\s*외|기타)"
METHOD_LIST_RE = re.compile(_METHOD_WORD + r"(?:\s*[,，]\s*" + _METHOD_WORD + r")+")


def _top_level_parts(text: str) -> list[str]:
    parts, depth, current = [], 0, ""
    for char in text:
        depth += char in "(（"
        depth -= char in ")）"
        if char in ",，" and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    return [*parts, current.strip()]


def _not_a_task_name_2026_11(clean: str, compact: str) -> bool:
    if NOT_A_TASK_DOCUMENT_SECTION_RE.search(clean):
        return True
    if INQUIRY_STEP_COMPACT_RE.fullmatch(compact) or CRITERION_TEXT_RE.search(clean):
        return True
    if ELEMENT_NOUN_RE.search(clean) or EXAM_ITEM_TYPE_RE.search(clean):
        return True
    if METHOD_LIST_RE.fullmatch(clean.strip()):
        return True
    # 여러 과제를 한 칸에 적은 것: "수행1 유전 현상 분석 … 수행2 DNA 돌연변이 …"
    if re.search(r"수행\s*\d.+수행\s*\d", clean):
        return True
    # 교사별 시기표 "○○○ 교사(1/4)"
    if re.search(r"교사\s*[(（]\s*\d\s*/\s*\d", clean):
        return True
    parts = _top_level_parts(clean)
    return len(parts) >= 2 and all(COMPETENCY_PART_RE.search(part) for part in parts if part)



def _named_items(items: list[ParsedAssessmentItem]) -> list[ParsedAssessmentItem]:
    """Drop bounded table-scan items whose name is not a task name."""

    return [
        item
        for item in items
        if item.extraction_status != "bounded"
        or (
            _valid_title(item.title)
            and not heading_title_is_structural(item.title, policy_prose=False)
            and not is_rubric_criterion_sentence(item.title)
            and not _not_a_task_name(item.title)
            and not _written_exam_column(item)
            # 이름 칸에 채점 물음까지 붙은 줄("탐구 결과 공유 및 의사소통 - … 발표하는가?")
            and not CRITERION_TEXT_RE.search(item.title_raw)
        )
    ]


def _written_exam_column(item: ParsedAssessmentItem) -> bool:
    """"논술형" read from a 지필 summary table ("선택형 단답형 │ 논술형 │ 서술형")."""

    return bool(
        item.title_basis == "table"
        and re.fullmatch(r"(?:서|논|서논|논서|서[·･・]\s*논)술형", compact_text(item.title))
        and re.search(r"선택형|단답형|선다형", visible_text(item.source_markdown))
    )


def _reads_as_task_description(cell: str, heading: str) -> bool:
    """Whether a 수행과제 cell describes the work while the heading names it.

    "가. 과학융합역량(총 20점)" over "생명과학의 주요 발견 중 하나를 선정하여
    …": the heading is the school's title for the section and the cell says
    what the student does.  The heading must be the shorter of the two and
    name something other than a unit, a course or only the grading method.
    """

    heading_compact = compact_text(heading)
    cell_compact = compact_text(cell)
    if not 2 <= len(heading_compact) < len(cell_compact):
        return False
    if UNIT_HEADING_RE.search(heading) or COURSE_NAME_ONLY_RE.fullmatch(heading_compact):
        return False
    # A list of steps under any heading is the heading's work.
    if len(TASK_DESCRIPTION_LIST_RE.findall(cell)) >= 2:
        return True
    # A sentence is the better title than a heading that only names the
    # grading method ("서·논술형 평가" over "세포 분열 과정을 설명하기").
    return not METHOD_ONLY_NAME_RE.fullmatch(heading_compact)


def _names_a_task_already_read(
    items: list[ParsedAssessmentItem], candidate: ParsedAssessmentItem
) -> bool:
    """The candidate names, in other words, a task already read.

    "연역적 탐구 기반 실험보고서 (1회)" beside "… 실험 보고서 작성", and a
    summary row spelling the task out ("'무척추 동물 해부를 통한 …'의 과정 및
    결과를 정리하고 실험 보고서 작성하기") beside the detail table's short
    name whose every word it holds ("무척추동물 해부 실험 보고서 작성").
    """

    key = _title_key(candidate.title)
    for item in items:
        if item.extraction_status != "bounded":
            continue
        other = _title_key(item.title)
        if len(key) >= 8 and len(other) >= 8 and (
            _begins_a_word_of(key, item.title) or _begins_a_word_of(other, candidate.title)
        ):
            return True
        if _words_all_within(item.title, candidate.title) or _words_all_within(
            candidate.title, item.title
        ):
            return True
    return False


def _word_start_key(title: str) -> tuple[str, set[int]]:
    """Compact text of a title and the positions where its words begin."""

    key = ""
    starts: set[int] = set()
    for word in re.split(r"[\s·,/]+", title):
        compact = compact_text(word)
        if compact:
            starts.add(len(key))
            key += compact
    return key, starts


def _begins_a_word_of(key: str, title: str) -> bool:
    long_key, starts = _word_start_key(re.sub(r"\(\s*\d+\s*회\s*\)", "", title))
    return any(long_key.startswith(key, at) for at in starts)


def _words_all_within(short: str, long: str) -> bool:
    """Every word of ``short`` begins a word of ``long`` ("척추동물" ≠ "무척추동물")."""

    words = [compact_text(word) for word in re.split(r"[\s·,/]+", short)]
    words = [word for word in words if len(word) >= 2]
    long_key, starts = _word_start_key(long)
    return (
        len(words) >= 3
        and len("".join(words)) >= 8
        and len("".join(words)) < len(long_key)
        and all(any(long_key.startswith(word, at) for at in starts) for word in words)
    )


STANDARD_CODE_RE = re.compile(r"\[\s*((?:10|12)[^\]\s]{2,12}?\s*-\s*\d{1,2}(?:\s*-\s*\d{1,2})?)")


def _standard_codes(item: ParsedAssessmentItem) -> set[str]:
    shown = visible_text(" ".join(item.standards) + " " + item.source_markdown)
    return {re.sub(r"\s+", "", code) for code in STANDARD_CODE_RE.findall(shown)}


def _drop_summary_restatements(
    items: list[ParsedAssessmentItem], summary: list[ParsedAssessmentItem]
) -> list[ParsedAssessmentItem]:
    """A plan's summary table lists the tasks its detail sections then name.

    A summary row naming a detail task in other spelling ("혈액평 판정 실험"),
    or with the same achievement codes and a word in common ("천연항생제
    물질 찾기" / "우리 주변에서 천연 항생물질 찾기"), is that task.  Other
    rows stay: a summary can list a task no detail section describes.
    """

    summary_ids = {id(item) for item in summary}
    bounded = [item for item in items if item.extraction_status == "bounded"]
    rows = [item for item in bounded if id(item) in summary_ids]
    details = [item for item in bounded if id(item) not in summary_ids]
    if not rows or not details:
        return items
    drop: set[int] = set()
    renamed: dict[int, ParsedAssessmentItem] = {}
    for row in rows:
        # Rows spelled like a detail task are left to the final pass, which
        # keeps the spelling the source uses more often.
        twin = next(
            (
                detail
                for detail in details
                if (codes := _standard_codes(row))
                and codes == _standard_codes(detail)
                and _share_a_content_word(row.title, detail.title)
                and not _same_task_named(row.title, detail.title)
            ),
            None,
        )
        if twin is None:
            continue
        drop.add(id(row))
        # The summary's short name names the task the detail cell describes
        # ("세균 및 바이러스 탐구조사 보고서" for a sentence about both).
        if (
            twin.title_basis == "table"
            and len(compact_text(twin.title)) >= 25
            and len(compact_text(row.title)) * 2 <= len(compact_text(twin.title))
        ):
            renamed[id(twin)] = replace(
                twin, title=row.title, title_raw=row.title_raw, overview=twin.overview or twin.title
            )
    return [renamed.get(id(item), item) for item in items if id(item) not in drop]


COMMON_TASK_WORDS = frozenset({"관계", "과정", "원리", "사례", "이해", "비교", "조사", "활동", "과학"})


def _share_a_content_word(first: str, second: str) -> bool:
    """Two content words in common ("세균 및 바이러스 …" / "… 바이러스와 세균에 …")."""

    words = {
        compact_text(word)
        for word in re.split(r"[\s·‧,/()（）]+", first)
        if len(compact_text(word)) >= 2
        and not GENERIC_TASK_WORDS_RE.fullmatch(compact_text(word))
        and compact_text(word) not in COMMON_TASK_WORDS
    }
    other = compact_text(second)
    return sum(1 for word in words if word in other) >= 2


# Words that name a step or a graded aspect of some task, never a task of
# their own when the case names its tasks ("실험 수행", "결론도출", "자료정리").
GENERIC_STEP_WORDS_RE = re.compile(
    r"(?:과학적|실험|수행|작성|발표|자료|조사|정리|분석|결론|도출|계획|설계|개념|이해|가치|판단|산출물|"
    r"탐구|학습|협동|과정|측정|표현|참여|의사소통|역량|문제해결력|고찰|해석|적용|및|자기성찰|일반화|"
    r"[,·․\s()（）]|서술형)+"
)
PRODUCT_WORD_RE = re.compile(r"보고서|포트폴리오|프로젝트|논술|노트|일지|활동지|신문|포스터|모형|에세이")


def _drop_generic_parts(items: list[ParsedAssessmentItem]) -> list[ParsedAssessmentItem]:
    """Drop steps and area labels beside the tasks they belong to.

    A short title made only of step words ("실험 수행", "분석 및 결론") read
    from inside another task's source is a graded step of it; on its own the
    same words can be the school's name ("탐구 발표", "실험탐구").  An area
    name with numbered siblings ("탐구 실험" beside "탐구실험1", "탐구실험2")
    labels the group, not a task.
    """

    bounded = [item for item in items if item.extraction_status == "bounded"]

    def generic_step(item: ParsedAssessmentItem) -> bool:
        compact = compact_text(item.title)
        return (
            len(compact) <= 8
            and bool(GENERIC_STEP_WORDS_RE.fullmatch(item.title))
            and not PRODUCT_WORD_RE.search(item.title)
        )

    def inside_another(item: ParsedAssessmentItem) -> bool:
        return any(
            other is not item
            and other.source_start <= item.source_start
            and item.source_end <= other.source_end
            and (other.source_start, other.source_end) != (item.source_start, item.source_end)
            for other in bounded
        )

    keys = [_title_key(item.title) for item in bounded]

    def area_label(item: ParsedAssessmentItem) -> bool:
        key = _title_key(item.title)
        return not re.search(r"\d|I{1,3}$", key) and sum(
            1 for other in keys if other != key and re.fullmatch(re.escape(key) + r"\s*(?:\d+|I{1,3}|IV)", other)
        ) >= 1

    drop = {
        id(item)
        for item in bounded
        if (generic_step(item) and inside_another(item)) or area_label(item)
    }
    return [item for item in items if id(item) not in drop]


def _heading_covering(
    items: list[ParsedAssessmentItem], candidate: ParsedAssessmentItem
) -> ParsedAssessmentItem | None:
    for item in items:
        if (
            item.extraction_status == "bounded"
            and item.title_basis == "heading"
            and item.source_start <= candidate.source_start
            and candidate.source_end <= item.source_end
        ):
            return item
    return None


def _tables_under(
    heading: ParsedAssessmentItem, offered: list[ParsedAssessmentItem]
) -> set[str]:
    return {
        _title_key(item.title)
        for item in offered
        if heading.source_start <= item.source_start and item.source_end <= heading.source_end
    }


def _sole_table_under(
    items: list[ParsedAssessmentItem],
    candidate: ParsedAssessmentItem,
    offered: list[ParsedAssessmentItem],
) -> bool:
    """The one table task found under a task heading is that heading's task.

    "(1) 탐구활동1" over a table whose 평가과제 cell reads "분광기를 활용한
    … 구성원소를 비교": one task.  Under a heading spanning several table
    tasks ("생명공학" over four experiments) each table is its own task.
    """

    heading = _heading_covering(items, candidate)
    return heading is not None and len(_tables_under(heading, offered)) == 1


def _absorb_sole_tables(
    items: list[ParsedAssessmentItem], offered: list[ParsedAssessmentItem]
) -> list[ParsedAssessmentItem]:
    """Give a heading task with no overview the sole table task's sentence."""

    absorbed: list[ParsedAssessmentItem] = []
    for item in items:
        if item.extraction_status == "bounded" and item.title_basis == "heading" and not item.overview:
            under = [
                table
                for table in offered
                if item.source_start <= table.source_start and table.source_end <= item.source_end
            ]
            if len({_title_key(table.title) for table in under}) == 1 and _title_key(
                under[0].title
            ) != _title_key(item.title):
                item = replace(item, overview=under[0].title)
        absorbed.append(item)
    return absorbed


def _renames_the_heading_above(
    items: list[ParsedAssessmentItem], candidate: ParsedAssessmentItem
) -> bool:
    """"박테리오파지 모형제작" in the table right under "가. 모형제작": one task."""

    key = _title_key(candidate.title)
    for item in items:
        if not (
            item.extraction_status == "bounded"
            and item.title_basis == "heading"
            and item.source_start <= candidate.source_start
            and candidate.source_end <= item.source_end
        ):
            continue
        heading_key = _title_key(item.title)
        shorter = min(len(key), len(heading_key))
        if shorter >= 3 and (key in heading_key or heading_key in key):
            return True
    return False


_FUZZY_PREFIX_RE = re.compile(
    r"^\s*(?:\d+\s*(?:순위\s*[:：]|[./]|\))|[:：])\s*|\s*[(（]\s*논술형?\s*(?:포함)?\s*[)）]\s*$"
)


def _fuzzy_task_key(title: str) -> str:
    key = _title_key(_FUZZY_PREFIX_RE.sub("", title))
    return re.sub(r"(?:하기|평가|영역)$", "", key) or key


GENERIC_TASK_WORDS_RE = re.compile(
    r"(?:확인|탐구|실험|분석|작성|활동|하기|평가|보고서|학습|수행|및|하고|하여|의|를|을|와|과|에|"
    r"대한|통한|이용한)+"
)


def _same_task_named(first: str, second: str) -> bool:
    a, b = _fuzzy_task_key(first), _fuzzy_task_key(second)
    if a == b:
        return True
    # "탐구 보고서 1" and "탐구 보고서 2", "과학노트Ⅰ" and "과학노트Ⅱ" are two tasks.
    numbering = r"\d+|I{1,3}$|IV$"
    if re.findall(numbering, a) != re.findall(numbering, b):
        return False
    shorter, longer = sorted((a, b), key=len)
    longer_title = second if len(b) >= len(a) else first
    # "원소의 주기성" / "원소의 주기성 탐구": the longer name only adds a
    # generic word.  "카드뉴스 제작" / "카드뉴스 제작 후속 탐구 보고서" are two.
    if len(shorter) >= 4 and _begins_a_word_of(shorter, longer_title):
        extra = longer.replace(shorter, "", 1)
        if GENERIC_TASK_WORDS_RE.fullmatch(extra):
            return True
    if len(shorter) < 8:
        return False
    matcher = SequenceMatcher(None, a, b)
    if matcher.ratio() < (0.86 if len(shorter) < 15 else 0.8):
        return False
    _, word_starts = _word_start_key(_FUZZY_PREFIX_RE.sub("", first))
    # Only a typo ("안정장치") or a generic word ("확인", "탐구") may differ;
    # "생명과학 포트폴리오" and "생명과학 독서 포트폴리오" are two tasks.
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed = a[i1:i2] + b[j1:j2]
        # …but not a word's first syllable ("식물"/"동물" name two tasks).
        if tag == "replace" and max(i2 - i1, j2 - j1) <= 1 and i1 not in word_starts:
            continue
        if not GENERIC_TASK_WORDS_RE.fullmatch(changed):
            return False
    return True


def _title_key(title: str) -> str:
    """Dedup key: the same task listed with and without a trailing "(1회)" is one task.

    So is a task a heading calls "탐구평가" and the summary table "탐구".
    """

    key = compact_text(re.sub(r"\(\s*\d+\s*회\s*\)", "", title))
    trimmed = re.sub(r"(?:수행)?평가$", "", key)
    return trimmed if len(trimmed) >= 2 else key


def parse_assessment_section(
    full_text: str,
    subject: str,
    title_hints: tuple[str, ...] = (),
) -> ParsedAssessmentSection:
    if any(marker in full_text for marker in CONTEXT_JUMP_MARKERS):
        raise ValueError("full source text contains a context-jump marker")
    subject_markdown, subject_start, _, subject_status = subject_local_markdown(full_text, subject)
    block, block_start, block_end, block_status = assessment_block(subject_markdown)
    headings = _heading_candidates(block)
    # A heading printed over every task ("원소 특성 분석과 … 주기율표 제작
    # 계획" on each page) is a running title, not one task's name.
    heading_counts = Counter(_title_key(title) for _, _, title, _ in headings)
    repeated_headings = {key for key, count in heading_counts.items() if count > 1}
    # …except its first appearance: a task heading followed by its own rubric
    # heading of the same name ("수평으로 던진 물체 운동" twice) is one task.
    later_repeats: set[int] = set()
    first_seen: set[str] = set()
    for position, (_, _, title, _) in enumerate(headings):
        heading_key = _title_key(title)
        if heading_key in repeated_headings:
            if heading_key in first_seen:
                later_repeats.add(position)
            first_seen.add(heading_key)
    plan_titles = _plan_titles(subject_markdown)
    # A block opened by its table (no source heading) may still hold detail
    # tables worth reading; a bare summary table on its own is not enough.
    detail_evidence = "<table" in block.lower() and bool(
        re.search(r"채점\s*기준|평가\s*요소|성취\s*기준", block)
    )
    table_items = (
        _summary_table_items(
            block,
            subject,
            subject_status,
            subject_start + block_start,
        )
        if block_status == "assessment_anchor"
        or (block_status == "assessment_table_anchor" and detail_evidence)
        else []
    )
    local_table_items = _explicit_local_table_items(
        subject_markdown,
        subject,
        subject_status,
        subject_start,
    )
    matrix_items = _matrix_table_items(
        subject_markdown,
        subject,
        subject_status,
        subject_start,
    )
    hinted_items = _hinted_table_items(
        subject_markdown,
        subject,
        subject_status,
        subject_start,
        title_hints,
    )
    rubric_group_items = _rubric_group_table_items(
        subject_markdown,
        subject,
        subject_status,
        subject_start,
    )
    # Each table scan names items under its own rules; one shared check keeps
    # score cells, document-section labels and exam rows out whichever scan
    # offered them.
    table_items, local_table_items, matrix_items, hinted_items, rubric_group_items = (
        _named_items(found)
        for found in (table_items, local_table_items, matrix_items, hinted_items, rubric_group_items)
    )
    allow_bounded_items = bool(
        headings
        and len(headings) <= MAX_BOUNDED_ITEMS
        and subject_status != "subject_heading_not_found"
        and block_status in {"assessment_anchor", "assessment_table_anchor"}
    )
    items: list[ParsedAssessmentItem] = []
    if allow_bounded_items:
        for order, (_, start, title, title_raw) in enumerate(headings, 1):
            end = headings[order][1] if order < len(headings) else len(block)
            segment = block[start:end].strip()
            structural_heading = (
                heading_title_is_structural(title)
                or is_rubric_criterion_sentence(title)
                or (order - 1) in later_repeats
                or _not_a_task_name(title)
            )
            subject_alignment = segment_subject_alignment(segment, subject)
            subject_boundary_reliable = not (
                subject_alignment == "other"
                or (subject_status == "subject_mention_only" and subject_alignment == "unknown")
            )
            # An explicit source-table label outranks every numbered heading,
            # not only headings already classified as structural.  School
            # plans often number a generic subsection and put the real task
            # name in the first table row.
            table_title, table_label = explicit_segment_title_with_label(segment)
            # …except under a 평가영역 label, whose cell carries the unit being
            # assessed as often as the task ("생명과학의 역사" under a section
            # headed "1. 수행평가 ( 1 ) - 탐구 실험 보고서").  A source heading
            # that names a task outranks that cell.
            # …and except under a heading that carries its own 배점, which is
            # the school's own name for the scored area ("나. 생명과학 연구사례
            # 탐구(20점)").  There the 수행과제 cell holds a sentence describing
            # the work, which belongs in the overview, not in the name.
            if (
                table_title
                and not structural_heading
                and _valid_plan_title(title)
                and (
                    (
                        AREA_TITLE_LABEL_RE.fullmatch(table_label)
                        and TASK_NAME_RE.search(title)
                    )
                    or SCORED_AREA_HEADING_RE.match(title_raw)
                    # …and except where the 수행과제 cell describes the work
                    # ("· 자유 낙하와 … 분석 · … 설명 · … 계산") under a short
                    # heading naming the task ("1) 동시낙하 실험보고서").  The
                    # cell is still read, as the overview.
                    or (
                        TASK_DESCRIPTION_LABEL_RE.fullmatch(table_label)
                        and _reads_as_task_description(table_title, title)
                    )
                )
            ):
                table_title = ""
            table_display_title = (
                _clean_heading_title(table_title)[0] if table_title else ""
            )
            if table_display_title and _not_a_task_name(table_display_title):
                table_title = table_display_title = ""
            reliable_title = (
                bool(table_title) or not structural_heading
            ) and subject_boundary_reliable
            resolved_title = (
                table_display_title or title
                if reliable_title
                else "수행평가 원문 구간"
            )
            resolved_title_raw = table_title or title_raw if reliable_title else resolved_title
            resolved_title_basis = "table" if table_title else "heading"
            extraction_status = (
                "bounded"
                if reliable_title
                else "source_mismatch_review"
                if subject_alignment == "other"
                else "bundle_review"
            )
            fields = (
                _exact_fields(segment)
                if reliable_title
                else {
                    "overview": "",
                    "method": "",
                    "timing": "",
                    "score": "",
                    "weight": "",
                    "standards": [],
                }
            )
            items.append(
                ParsedAssessmentItem(
                    order=order,
                    title=resolved_title,
                    title_raw=resolved_title_raw,
                    title_basis=(resolved_title_basis if reliable_title else "unbounded_bundle"),
                    extraction_status=extraction_status,
                    source_start=subject_start + block_start + start,
                    source_end=subject_start + block_start + end,
                    source_markdown=segment,
                    source_html=markdown_fragment_to_html(segment),
                    rubric_html=_rubric_html(segment),
                    overview=str(fields["overview"]),
                    method=str(fields["method"]),
                    timing=str(fields["timing"]),
                    score=str(fields["score"]),
                    weight=str(fields["weight"]),
                    standards=tuple(str(value) for value in fields["standards"]),
                )
            )
        existing_titles = {
            _title_key(item.title)
            for item in items
            if item.extraction_status == "bounded"
        }
        # A summary row naming the task as its heading does ("과정평가1"
        # under "(1) 과정평가 1") is that task even when the detail table gave
        # it a fuller name.
        existing_titles |= {
            _title_key(title)
            for (_, _, title, _), item in zip(headings, items)
            if item.extraction_status == "bounded" and len(_title_key(title)) >= 2
        }
        offered = [*table_items, *local_table_items, *matrix_items, *hinted_items]
        items = _absorb_sole_tables(items, offered)
        for extras in (table_items, local_table_items, matrix_items, hinted_items, rubric_group_items):
            accepted = [
                item
                for item in extras
                if _title_key(item.title) not in existing_titles
                and not (extras is not rubric_group_items and _sole_table_under(items, item, offered))
                and not _names_a_task_already_read(items, item)
                and not _renames_the_heading_above(items, item)
                and not _already_read_under_a_heading(items, item)
                and not (
                    extras is rubric_group_items and _table_under_a_task_heading(items, item)
                )
            ]
            items.extend(accepted)
            existing_titles.update(_title_key(item.title) for item in extras)
        items = _drop_summary_restatements(items, [*table_items, *matrix_items])
        if not any(item.extraction_status == "bounded" for item in items):
            global_table_items = _named_items(_expected_code_table_items(full_text, subject))
            items.extend(
                item
                for item in global_table_items
                if compact_text(item.title) not in existing_titles
            )
    elif table_items or local_table_items or matrix_items or hinted_items or rubric_group_items:
        for item in [*table_items, *local_table_items, *matrix_items, *hinted_items, *rubric_group_items]:
            if _title_key(item.title) not in {_title_key(existing.title) for existing in items}:
                items.append(item)
        items = _drop_summary_restatements(items, [*table_items, *matrix_items])
    else:
        global_table_items = _named_items(_expected_code_table_items(full_text, subject))
        if global_table_items:
            items.extend(global_table_items)
        else:
            # Preserve the whole section when the source does not expose safe item
            # boundaries.  Multiple plan-table titles stay visible as one bundle;
            # duplicating the same rubric under guessed titles would be misleading.
            single_table_title = (
                plan_titles[0]
                if len(plan_titles) == 1 and subject_status != "subject_heading_not_found"
                else ""
            )
            title = single_table_title or "수행평가 원문 구간"
            fields = (
                _exact_fields(block)
                if single_table_title
                else {
                    "overview": "",
                    "method": "",
                    "timing": "",
                    "score": "",
                    "weight": "",
                    "standards": [],
                }
            )
            items.append(
                ParsedAssessmentItem(
                    order=1,
                    title=title,
                    title_raw=title,
                    title_basis="table_bundle" if single_table_title else "unbounded_bundle",
                    extraction_status="bundle_review",
                    source_start=subject_start + block_start,
                    source_end=subject_start + block_end,
                    source_markdown=block,
                    source_html=markdown_fragment_to_html(block),
                    rubric_html=_rubric_html(block),
                    overview=str(fields["overview"]),
                    method=str(fields["method"]),
                    timing=str(fields["timing"]),
                    score=str(fields["score"]),
                    weight=str(fields["weight"]),
                    standards=tuple(str(value) for value in fields["standards"]),
                )
            )
    # A summary row that writes two tasks in one cell ("생명과학 성과 발표,
    # 세포 관찰 보고서") repeats tasks already read one by one.
    bounded_keys = [
        _title_key(item.title) for item in items if item.extraction_status == "bounded"
    ]
    items = [
        item
        for item in items
        if item.extraction_status != "bounded"
        or sum(
            1
            for key in set(bounded_keys)
            if len(key) >= 4 and key != _title_key(item.title) and key in _title_key(item.title)
        )
        < 2
    ]
    # The same name twice is one task read twice (a heading and a table that
    # both resolved to "자유 탐구"), and so is a name spelled two ways by the
    # summary table and the detail section ("천연 항생물질 효과 확인 실험" /
    # "천연 항생물질 효과 실험", "안전장치"/"안정장치").
    items = _drop_generic_parts(items)
    # Of two spellings the source uses more often is the school's
    # ("핵심 질문" over a single "핵실질문").
    source_key = compact_text(visible_text(full_text))
    unique: list[ParsedAssessmentItem] = []
    for item in items:
        if item.extraction_status == "bounded":
            twin = next(
                (
                    index
                    for index, kept in enumerate(unique)
                    if kept.extraction_status == "bounded" and _same_task_named(item.title, kept.title)
                ),
                None,
            )
            if twin is not None:
                kept = unique[twin]
                if source_key.count(compact_text(item.title)) > source_key.count(
                    compact_text(kept.title)
                ):
                    unique[twin] = replace(kept, title=item.title, title_raw=item.title_raw)
                continue
        unique.append(item)
    items = [
        replace(item, extraction_status="source_mismatch_review")
        if item.extraction_status == "bounded" and _names_another_course(item.source_markdown, subject)
        else _finish_item(_cut_at_other_course_title(item, subject))
        for item in unique
    ]
    items = [replace(item, order=order) for order, item in enumerate(items, 1)]
    # Without a course heading or a 수행평가 heading, the table scans still
    # admit a row only on achievement codes that all belong to this course.
    # When every kept item carries such codes, they are the boundary: the
    # heading that was not found is no longer what places the item.
    bounded = [item for item in items if item.extraction_status == "bounded"]
    if bounded and all(
        segment_subject_alignment(item.source_markdown, subject) == "expected"
        for item in bounded
    ):
        if subject_status == "subject_heading_not_found":
            subject_status = "subject_code_rows"
        if block_status == "assessment_anchor_not_found":
            block_status = "assessment_code_rows"
    detected_titles: list[str] = []
    for item in items:
        if item.extraction_status == "bounded" and item.title not in detected_titles:
            detected_titles.append(item.title)
    return ParsedAssessmentSection(
        subject=subject,
        boundary_status=f"{subject_status}:{block_status}",
        source_start=subject_start + block_start,
        source_end=subject_start + block_end,
        source_markdown=block,
        detected_titles=tuple(detected_titles),
        items=tuple(items),
    )
