// 시드 목록이다. 실제 생명과학 평가계획을 분석한 뒤 유형이 늘어날 수 있다
// (프로젝트·보고서·토론·제작·실험 등). API의 category 패턴과 값을 맞춘다.
export type PatternId = "inquiry" | "ecology" | "problem" | "presentation" | "portfolio" | "reading";

export type DesignPattern = {
  id: PatternId;
  label: string;
  description: string;
  actionTag: string;
  searchQuery?: string;
  product: string;
  methodPhrase: string;
  phases: Array<{ title: string; evidence: string }>;
  criteria: Array<{ label: string; weight: number; focus: string }>;
};

export type DesignInputs = {
  curriculum: "2015" | "2022";
  subject: string;
  grade: number;
  semester: number;
  topic: string;
  patternId: PatternId;
  lessons: number;
  collaboration: "개인" | "짝" | "모둠";
  totalScore: number;
  aiPolicy: "사용하지 않음" | "자료 조사만 허용" | "활용 내역을 밝히고 허용";
};

export type DesignDraft = {
  title: string;
  taskBrief: string;
  achievementStandards: string;
  sourceCheck: string;
  product: string;
  lessonPlan: Array<{ lesson: string; title: string; evidence: string }>;
  rubric: Array<{ label: string; points: number; focus: string }>;
  evidenceChecklist: string[];
  aiGuidance: string;
  fairnessChecklist: string[];
};

export const DESIGN_PATTERNS: DesignPattern[] = [
  {
    id: "inquiry",
    label: "주제 탐구",
    description: "질문을 세우고 과학적 근거로 답을 만드는 보고서형",
    actionTag: "탐구",
    product: "생명과학 탐구보고서와 3분 설명",
    methodPhrase: "탐구 질문을 만들고 개념·자료·관찰 결과를 연결해 설명합니다",
    phases: [
      { title: "질문 구체화", evidence: "주제 선정 이유와 탐구 질문 초안" },
      { title: "개념·자료 탐색", evidence: "출처가 표시된 자료와 사용할 생명과학 개념 정리" },
      { title: "자료 분석", evidence: "관찰 기록·표·그래프 중 두 가지 이상을 연결한 분석 과정" },
      { title: "결론·성찰", evidence: "질문에 대한 결론, 한계, 후속 질문" },
    ],
    criteria: [
      { label: "생명과학 개념의 정확성", weight: 30, focus: "핵심 개념과 용어를 정확히 사용했는가" },
      { label: "과학적 탐구 사고", weight: 30, focus: "질문·근거·결론이 일관되게 이어지는가" },
      { label: "자료의 표현", weight: 25, focus: "표·그래프·모식도를 목적에 맞게 연결했는가" },
      { label: "성찰과 의사소통", weight: 15, focus: "한계와 후속 질문을 자신의 말로 설명했는가" },
    ],
  },
  {
    id: "ecology",
    label: "생태 조사",
    description: "주변 생태계를 직접 조사하고 생물과 환경의 관계를 자료로 해석",
    actionTag: "생태조사",
    searchQuery: "생태 조사",
    product: "생태 조사 보고서와 조사 기록표·사진 자료",
    methodPhrase: "조사 지점과 방법을 정해 자료를 수집하고 생물과 환경의 관계를 해석합니다",
    phases: [
      { title: "조사 설계", evidence: "조사 목적, 지점 선정 이유, 조사 방법과 안전·생명윤리 계획" },
      { title: "현장 자료 수집", evidence: "방형구·개체수·환경 요인 기록표와 사진" },
      { title: "자료 정리·해석", evidence: "종 다양성·우점도 등 지표 계산과 그래프" },
      { title: "결론·제안", evidence: "조사 결과 해석, 한계, 보전 제안" },
    ],
    criteria: [
      { label: "조사 설계의 타당성", weight: 25, focus: "목적에 맞는 지점·방법·표본 수를 정했는가" },
      { label: "자료 수집의 정확성", weight: 30, focus: "관찰·측정 기록이 재현 가능하게 남았는가" },
      { label: "과학적 탐구 사고", weight: 30, focus: "자료를 근거로 생물과 환경의 관계를 해석했는가" },
      { label: "안전과 생명윤리", weight: 15, focus: "채집 최소화와 서식지 보호 수칙을 지켰는가" },
    ],
  },
  {
    id: "problem",
    label: "탐구 문제 설계",
    description: "검증 가능한 문제를 세우고 실험 설계를 비교하는 문제해결형",
    actionTag: "문제해결",
    searchQuery: "실험 설계",
    product: "탐구 문제, 실험 설계안, 변인 점검표",
    methodPhrase: "개념이 드러나는 탐구 문제를 만들고 변인 통제와 오차 가능성을 검토합니다",
    phases: [
      { title: "개념·문제 선정", evidence: "평가하려는 개념과 검증 가능한 문제 설계표" },
      { title: "실험 설계 초안", evidence: "조작·통제 변인, 절차, 예상 결과" },
      { title: "상호 검토", evidence: "동료 설계 검토 결과와 수정 전·후 기록" },
      { title: "최종화·성찰", evidence: "최종 설계안, 예상 오차와 대안" },
    ],
    criteria: [
      { label: "개념 적합성", weight: 30, focus: "의도한 개념을 문제와 설계가 정확히 드러내는가" },
      { label: "변인 통제의 타당성", weight: 30, focus: "조작 변인과 통제 변인이 논리적으로 구분됐는가" },
      { label: "설계의 실행가능성", weight: 25, focus: "절차가 구체적이며 학교 환경에서 수행 가능한가" },
      { label: "검토와 개선", weight: 15, focus: "동료 검토를 반영해 설계를 개선했는가" },
    ],
  },
  {
    id: "presentation",
    label: "설명·발표",
    description: "개념이나 탐구 결과를 청중에게 명료하게 설명하는 의사소통형",
    actionTag: "발표",
    product: "시각 자료와 5분 생명과학 설명",
    methodPhrase: "핵심 개념과 탐구 결과를 청중이 이해할 수 있는 순서와 표현으로 설명합니다",
    phases: [
      { title: "핵심 내용 선정", evidence: "설명할 개념과 청중 분석 메모" },
      { title: "설명 구조 설계", evidence: "도입·핵심·예시·정리 스토리보드" },
      { title: "시각화·리허설", evidence: "모식도·그래프 자료와 동료 피드백" },
      { title: "발표·성찰", evidence: "발표 자료와 질문 답변, 자기 성찰" },
    ],
    criteria: [
      { label: "개념의 정확성", weight: 30, focus: "생명과학 개념과 설명이 정확한가" },
      { label: "설명 구조", weight: 25, focus: "내용이 이해 가능한 순서로 이어지는가" },
      { label: "과학적 표현", weight: 25, focus: "용어·모식도·그래프를 명료하게 사용했는가" },
      { label: "상호작용과 성찰", weight: 20, focus: "질문에 근거로 답하고 피드백을 반영했는가" },
    ],
  },
  {
    id: "portfolio",
    label: "과정 포트폴리오",
    description: "관찰 기록·피드백·수정 이력을 누적해 성장 과정을 확인",
    actionTag: "포트폴리오",
    product: "학습 포트폴리오와 성장 성찰문",
    methodPhrase: "관찰 기록과 피드백, 수정 과정을 누적해 개념 이해의 변화를 설명합니다",
    phases: [
      { title: "목표·기준 설정", evidence: "개인 학습 목표와 성공 기준" },
      { title: "기록 누적", evidence: "대표 탐구·관찰 기록과 선택 이유" },
      { title: "피드백·수정", evidence: "수정 전·후 기록과 달라진 생각" },
      { title: "성장 설명", evidence: "개념 이해의 변화와 다음 목표" },
    ],
    criteria: [
      { label: "개념 이해", weight: 30, focus: "대표 기록에서 개념 이해가 드러나는가" },
      { label: "과정 기록", weight: 25, focus: "선택·관찰·검토 과정이 빠짐없이 기록됐는가" },
      { label: "피드백 반영", weight: 25, focus: "오류 원인을 찾고 수정한 근거가 있는가" },
      { label: "성찰", weight: 20, focus: "성장과 다음 학습 목표를 구체적으로 설명했는가" },
    ],
  },
  {
    id: "reading",
    label: "독서 연계",
    description: "책의 사례를 생명과학 개념으로 재해석하는 독서 탐구형",
    actionTag: "탐구",
    searchQuery: "독서",
    product: "독서 기반 생명과학 탐구보고서",
    methodPhrase: "책의 주장이나 사례를 생명과학 개념으로 다시 해석하고 근거를 검토합니다",
    phases: [
      { title: "도서·질문 선정", evidence: "선정 이유, 인용 위치, 과학적 질문" },
      { title: "개념 연결", evidence: "책의 내용과 생명과학 개념 연결 지도" },
      { title: "분석·재해석", evidence: "자료·모식도·그래프를 활용한 재해석" },
      { title: "비판·확장", evidence: "책의 설명에 대한 검토와 후속 탐구" },
    ],
    criteria: [
      { label: "독서 근거", weight: 20, focus: "도서의 내용과 출처를 정확히 제시했는가" },
      { label: "생명과학 개념 연결", weight: 30, focus: "책의 사례를 적절한 생명과학 개념과 연결했는가" },
      { label: "분석과 재해석", weight: 30, focus: "과학적 표현으로 새로운 해석을 만들었는가" },
      { label: "비판과 확장", weight: 20, focus: "설명의 한계를 검토하고 후속 질문을 제안했는가" },
    ],
  },
];

export function getPattern(patternId: PatternId) {
  return DESIGN_PATTERNS.find((pattern) => pattern.id === patternId) ?? DESIGN_PATTERNS[0];
}

function allocatePoints(total: number, weights: number[]) {
  const points = weights.map((weight) => Math.floor((total * weight) / 100));
  let remainder = total - points.reduce((sum, value) => sum + value, 0);
  for (let index = 0; remainder > 0; index = (index + 1) % points.length) {
    points[index] += 1;
    remainder -= 1;
  }
  return points;
}

function lessonRange(index: number, phaseCount: number, lessons: number) {
  const start = Math.floor((index * lessons) / phaseCount) + 1;
  const end = Math.max(start, Math.floor(((index + 1) * lessons) / phaseCount));
  return start === end ? `${start}차시` : `${start}–${end}차시`;
}

export function buildDesignDraft(inputs: DesignInputs): DesignDraft {
  const pattern = getPattern(inputs.patternId);
  const topic = inputs.topic.trim() || "수업에서 다룬 핵심 개념";
  const points = allocatePoints(inputs.totalScore, pattern.criteria.map((item) => item.weight));
  const aiGuidance =
    inputs.aiPolicy === "사용하지 않음"
      ? "생성형 AI를 사용하지 않습니다. 검색·계산 도구의 허용 범위는 교사가 별도로 안내합니다."
      : inputs.aiPolicy === "자료 조사만 허용"
        ? "생성형 AI는 탐색어 제안과 기초 자료 조사에만 사용합니다. 최종 분석·표현은 학생이 작성하고, 사용한 질문과 결과를 부록에 남깁니다."
        : "생성형 AI 활용을 허용하되, 사용한 질문·결과·수정한 내용을 구분해 기록합니다. 학생의 과학적 탐구 사고와 검증 과정을 별도로 평가합니다.";

  return {
    title: `${topic} — ${pattern.label}`,
    taskBrief: `${inputs.grade}학년 ${inputs.subject} 수업에서 '${topic}'을 중심으로 ${pattern.methodPhrase}. ${inputs.collaboration} 활동으로 진행하며, 최종 결과뿐 아니라 선택·시도·수정의 과정 증거를 함께 제출합니다.`,
    achievementStandards: "",
    sourceCheck: "교육부·NCIC 공식 성취기준 원문과 학교 학업성적관리규정을 확인한 뒤 작성",
    product: pattern.product,
    lessonPlan: pattern.phases.map((phase, index) => ({
      lesson: lessonRange(index, pattern.phases.length, inputs.lessons),
      ...phase,
    })),
    rubric: pattern.criteria.map((criterion, index) => ({
      label: criterion.label,
      points: points[index],
      focus: criterion.focus,
    })),
    evidenceChecklist: pattern.phases.map((phase) => phase.evidence),
    aiGuidance,
    fairnessChecklist: [
      "과제·평가기준·제출 형식을 시작 전에 학생에게 공개한다.",
      `${inputs.collaboration} 활동에서도 개인별 판단과 기여가 드러나는 증거를 받는다.`,
      "기기·소프트웨어 접근이 어려운 학생에게 동등한 대체 경로를 제공한다.",
      "결시·전입·장기 미제출 학생의 재평가 방법을 사전에 정한다.",
      "해부·채집·시약을 쓰는 과제는 안전 지침과 생명윤리 대체 활동을 함께 안내한다.",
      "결과물의 화려함보다 과학적 탐구 사고와 수정 과정을 평가한다.",
    ],
  };
}

export function draftAsText(inputs: DesignInputs, draft: DesignDraft) {
  const rubric = draft.rubric
    .map((item) => `- ${item.label} (${item.points}점): ${item.focus}`)
    .join("\n");
  const process = draft.lessonPlan
    .map((item) => `- ${item.lesson} ${item.title}: ${item.evidence}`)
    .join("\n");
  return `${draft.title}\n\n[기본 조건]\n- ${inputs.curriculum} 개정 ${inputs.subject}\n- ${inputs.grade}학년 ${inputs.semester}학기 · ${inputs.lessons}차시 · ${inputs.collaboration}\n- 총 ${inputs.totalScore}점\n\n[연결 성취기준]\n${draft.achievementStandards || "교사 확인 후 입력"}\n\n[공식 원문 확인]\n${draft.sourceCheck}\n\n[수행 과제]\n${draft.taskBrief}\n\n[최종 산출물]\n${draft.product}\n\n[과정과 증거]\n${process}\n\n[루브릭 초안]\n${rubric}\n\n[AI 활용]\n${draft.aiGuidance}\n\n[공정성 점검]\n${draft.fairnessChecklist.map((item) => `- ${item}`).join("\n")}`;
}
