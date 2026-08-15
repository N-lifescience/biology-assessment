"use client";

import Link from "../SiteLink";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import {
  apiParameters,
  fetchCatalog,
  type CaseItem,
  type CaseListResponse,
  type SubjectItem,
  type SubjectListResponse,
} from "../lib/catalog-api";
import {
  buildDesignDraft,
  DESIGN_PATTERNS,
  type DesignDraft,
  type DesignInputs,
  draftAsText,
  getPattern,
  type PatternId,
} from "./design-draft";

const STORAGE_KEY = "biology-assessment-designer-draft-v1";

function safeCurriculum(value: string | null): "2015" | "2022" {
  return value === "2015" ? "2015" : "2022";
}

function safePattern(value: string | null): PatternId {
  return DESIGN_PATTERNS.some((pattern) => pattern.id === value) ? (value as PatternId) : "inquiry";
}

function initialInputs(parameters: URLSearchParams): DesignInputs {
  return {
    curriculum: safeCurriculum(parameters.get("curriculum")),
    subject: parameters.get("subject") || "생명과학",
    grade: 2,
    semester: 1,
    topic: "수업에서 다룬 핵심 개념을 활용한 생명 현상 탐구",
    patternId: safePattern(parameters.get("pattern")),
    lessons: 4,
    collaboration: "개인",
    totalScore: 20,
    aiPolicy: "자료 조사만 허용",
  };
}

export function selectReferenceCases(items: CaseItem[]) {
  const titleCandidates = items.filter((item) => {
    const bulletCount = (item.primary_task_name.match(/[▪•]/g) || []).length;
    return (
      item.primary_task_name !== "구체적 과제명 미탐지" &&
      item.primary_task_name.length <= 100 &&
      bulletCount < 3
    );
  });
  const pool = titleCandidates.length ? titleCandidates : items;
  const seenSources = new Set<string>();
  return pool.filter((item) => {
    const sourceKey = item.source_sha256 || item.case_id;
    if (seenSources.has(sourceKey)) return false;
    seenSources.add(sourceKey);
    return true;
  }).slice(0, 3);
}

export default function DesignStudio() {
  const searchParameters = useSearchParams();
  const router = useRouter();
  const referenceCaseId = searchParameters.get("reference") || "";
  const initial = useMemo(() => initialInputs(new URLSearchParams(searchParameters.toString())), [searchParameters]);
  const [inputs, setInputs] = useState<DesignInputs>(initial);
  const [draft, setDraft] = useState<DesignDraft>(() => buildDesignDraft(initial));
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [references, setReferences] = useState<CaseItem[]>([]);
  const [referenceLoading, setReferenceLoading] = useState(true);
  const [referenceError, setReferenceError] = useState("");
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog<SubjectListResponse>("subjects", controller.signal)
      .then((payload) => setSubjects(payload.items.filter((item) => item.curriculum !== "shared")))
      .catch((reason: Error) => { if (!controller.signal.aborted) setReferenceError(reason.message); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const pattern = getPattern(inputs.patternId);
    const request = referenceCaseId
      ? fetchCatalog<CaseItem>(`cases/${referenceCaseId}`, controller.signal).then((item) => [item])
      : fetchCatalog<CaseListResponse>(
          `cases?${apiParameters({
            curriculum: inputs.curriculum,
            subject: inputs.subject,
            tag: pattern.actionTag,
            query: pattern.searchQuery,
            include_ambiguous: true,
            limit: 12,
            offset: 0,
          })}`,
          controller.signal,
        ).then((payload) => selectReferenceCases(payload.items));
    request
      .then(setReferences)
      .catch((reason: Error) => { if (!controller.signal.aborted) setReferenceError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setReferenceLoading(false); });
    return () => controller.abort();
  }, [inputs.curriculum, inputs.subject, inputs.patternId, referenceCaseId]);

  useEffect(() => {
    const parameters = apiParameters({
      curriculum: inputs.curriculum,
      subject: inputs.subject,
      pattern: inputs.patternId,
      reference: referenceCaseId,
    });
    router.replace(`/design?${parameters}`, { scroll: false });
  }, [inputs.curriculum, inputs.subject, inputs.patternId, referenceCaseId, router]);

  const courseOptions = useMemo(
    () => subjects.filter((item) => item.curriculum === inputs.curriculum),
    [inputs.curriculum, subjects],
  );

  function updateInput<Key extends keyof DesignInputs>(key: Key, value: DesignInputs[Key]) {
    setInputs((current) => ({ ...current, [key]: value }));
    if (key === "subject" || key === "patternId") beginReferenceReload();
    setDirty(true);
    setNotice("");
  }

  function changeCurriculum(value: "2015" | "2022") {
    const nextCourses = subjects.filter((item) => item.curriculum === value);
    const nextSubject = nextCourses.some((item) => item.subject === inputs.subject)
      ? inputs.subject
      : (nextCourses[0]?.subject ?? "");
    setInputs((current) => ({ ...current, curriculum: value, subject: nextSubject }));
    beginReferenceReload();
    setDirty(true);
    setNotice("");
  }

  function createDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setDraft(buildDesignDraft(inputs));
    setDirty(false);
    setNotice("현재 조건으로 설계 초안을 새로 만들었습니다.");
  }

  async function copyDraft() {
    try {
      const text = draftAsText(inputs, draft);
      await navigator.clipboard.writeText(text);
      setNotice("설계 초안을 클립보드에 복사했습니다.");
    } catch {
      setNotice("브라우저가 복사를 허용하지 않았습니다. 인쇄 기능을 이용해 주세요.");
    }
  }

  function beginReferenceReload() {
    setReferenceLoading(true);
    setReferenceError("");
  }

  function saveDraft() {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ inputs, draft }));
    setNotice("이 브라우저에만 임시 저장했습니다.");
  }

  function loadDraft() {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (!stored) {
      setNotice("이 브라우저에 저장된 초안이 없습니다.");
      return;
    }
    try {
      const payload = JSON.parse(stored) as { inputs: DesignInputs; draft: DesignDraft };
      if (!payload.inputs?.subject || !Array.isArray(payload.draft?.rubric)) {
        throw new Error("invalid local draft");
      }
      setInputs(payload.inputs);
      setDraft({
        ...payload.draft,
        achievementStandards: payload.draft.achievementStandards ?? "",
        sourceCheck: payload.draft.sourceCheck ?? "교육부·NCIC 공식 원문 확인 필요",
      });
      beginReferenceReload();
      setDirty(false);
      setNotice("브라우저에 저장된 초안을 불러왔습니다.");
    } catch {
      setNotice("저장된 초안을 읽지 못했습니다. 새 초안을 만들어 주세요.");
    }
  }

  function updateDraft<Key extends keyof DesignDraft>(key: Key, value: DesignDraft[Key]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  return (
    <main id="main-content" className="designPage">
      <header className="pageHeaderCompact" aria-labelledby="design-title">
        <div>
          <p className="breadcrumb"><Link href="/">홈</Link><span>/</span>설계 스튜디오</p>
          <h1 id="design-title">수행평가 설계 스튜디오</h1>
        </div>
        <p><strong>로컬</strong><span>작성 내용은 이 브라우저에서만 처리</span></p>
      </header>

      <div className="designWorkspace">
        <form className="designControls" onSubmit={createDraft}>
          <div className="designPanelHeading"><span className="stepPill">1</span><div><h2>수업 조건</h2><p>먼저 바뀌면 안 되는 조건을 정합니다.</p></div></div>
          <div className="designFieldGrid">
            <label><span>교육과정</span><select value={inputs.curriculum} onChange={(event) => changeCurriculum(event.target.value as "2015" | "2022")}><option value="2015">2015 개정</option><option value="2022">2022 개정</option></select></label>
            <label><span>생명과학 교과군 과목</span><select value={inputs.subject} onChange={(event) => updateInput("subject", event.target.value)}>{courseOptions.map((item) => <option key={`${item.curriculum}-${item.subject}`} value={item.subject}>{item.subject} · {item.documents.toLocaleString()}건</option>)}</select></label>
            <label><span>학년</span><select value={inputs.grade} onChange={(event) => updateInput("grade", Number(event.target.value))}><option value={1}>1학년</option><option value={2}>2학년</option><option value={3}>3학년</option></select></label>
            <label><span>학기</span><select value={inputs.semester} onChange={(event) => updateInput("semester", Number(event.target.value))}><option value={1}>1학기</option><option value={2}>2학기</option></select></label>
            <label><span>차시</span><select value={inputs.lessons} onChange={(event) => updateInput("lessons", Number(event.target.value))}>{[4, 5, 6, 8].map((value) => <option key={value} value={value}>{value}차시</option>)}</select></label>
            <label><span>활동 방식</span><select value={inputs.collaboration} onChange={(event) => updateInput("collaboration", event.target.value as DesignInputs["collaboration"])}><option value="개인">개인</option><option value="짝">짝</option><option value="모둠">모둠</option></select></label>
            <label><span>총점</span><select value={inputs.totalScore} onChange={(event) => updateInput("totalScore", Number(event.target.value))}>{[20, 30, 40, 50, 100].map((value) => <option key={value} value={value}>{value}점</option>)}</select></label>
            <label><span>AI 활용 원칙</span><select value={inputs.aiPolicy} onChange={(event) => updateInput("aiPolicy", event.target.value as DesignInputs["aiPolicy"])}><option>사용하지 않음</option><option>자료 조사만 허용</option><option>활용 내역을 밝히고 허용</option></select></label>
          </div>
          <label className="topicField"><span>수행평가 주제 또는 맥락</span><input value={inputs.topic} onChange={(event) => updateInput("topic", event.target.value)} placeholder="예: 카페인 농도의 변화율과 적정 섭취 시간" /></label>

          <fieldset className="patternPicker"><legend><span className="stepPill">2</span><strong>학생이 하게 될 핵심 활동</strong></legend>{DESIGN_PATTERNS.map((pattern) => <label key={pattern.id} className={inputs.patternId === pattern.id ? "selected" : ""}><input type="radio" name="pattern" value={pattern.id} checked={inputs.patternId === pattern.id} onChange={() => updateInput("patternId", pattern.id)} /><span><strong>{pattern.label}</strong><small>{pattern.description}</small></span></label>)}</fieldset>
          <button className="createDraftButton" type="submit">{dirty ? "바뀐 조건으로 초안 다시 만들기" : "현재 조건으로 초안 만들기"}<span aria-hidden="true">→</span></button>
        </form>

        <aside className="referenceRail" aria-labelledby="reference-title">
          <div className="designPanelHeading"><span className="stepPill">3</span><div><h2 id="reference-title">구조 참고 후보</h2><p>{referenceCaseId ? "선택한 사례를 참고 후보로 표시합니다." : "같은 과목·활동 표현에서 자동 탐지한 후보입니다."}</p></div></div>
          {referenceLoading ? <div className="referenceLoading" role="status">근거 사례를 찾고 있습니다.</div> : null}
          {referenceError ? <div className="referenceError" role="alert">{referenceError}</div> : null}
          {!referenceLoading && !referenceError && references.length === 0 ? <p className="referenceEmpty">현재 조건의 근거 사례를 찾지 못했습니다. 초안은 만들 수 있지만 원문 검토가 더 필요합니다.</p> : null}
          <ol className="referenceCards">{references.map((item) => <li key={item.case_id}><span>{item.school_name || "학교명 미확인"}</span><h3>{item.primary_task_name}</h3><div>{item.action_tags.slice(0, 3).map((tag) => <small key={tag}>#{tag}</small>)}</div><Link href={`/cases/${item.case_id}`}>앱에서 원문 확인 →</Link>{item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">학교알리미 공개 페이지 <span aria-hidden="true">↗</span></a> : <em>공개 페이지 미확인</em>}</li>)}</ol>
          <p className="referenceNote">후보는 초안을 자동으로 채우지 않습니다. 사례 제목과 유형은 자동 탐지 결과이므로 상세 원문을 확인하고, 학교명이나 형식을 모방하지 말고 과제 구조와 근거만 비교하세요.</p>
        </aside>
      </div>

      <section className="draftCanvas" aria-labelledby="draft-title">
        <div className="draftToolbar"><div><span className="stepPill">4</span><div><h2 id="draft-title">설계 템플릿 초안</h2><p>제목·성취기준·과제 문장을 교사가 직접 확인하고 수정합니다.</p></div></div><div><button type="button" onClick={loadDraft}>불러오기</button><button type="button" onClick={saveDraft}>브라우저에 저장</button><button type="button" onClick={() => void copyDraft()}>텍스트 복사</button><button type="button" onClick={() => window.print()}>인쇄</button></div></div>
        {notice ? <p className="designNotice" role="status">{notice}</p> : null}
        {dirty ? <p className="draftStale" role="status">수업 조건이 바뀌었습니다. ‘초안 다시 만들기’를 누르면 아래 내용에 반영됩니다.</p> : null}
        <div className="draftPaper">
          <div className="draftIdentity"><span>{inputs.curriculum} 개정 · {inputs.subject} · {inputs.grade}학년 {inputs.semester}학기</span><label><span>수행평가 제목</span><input value={draft.title} onChange={(event) => updateDraft("title", event.target.value)} /></label></div>
          <section><h3>연결 성취기준 · 공식 원문 확인</h3><label><span>연결 성취기준</span><textarea value={draft.achievementStandards} onChange={(event) => updateDraft("achievementStandards", event.target.value)} rows={3} placeholder="교육부·NCIC 공식 원문을 확인해 성취기준 코드와 내용을 입력하세요." /></label><label><span>출처·규정 확인 메모</span><textarea value={draft.sourceCheck} onChange={(event) => updateDraft("sourceCheck", event.target.value)} rows={2} /></label></section>
          <section><h3>수행 과제</h3><textarea value={draft.taskBrief} onChange={(event) => updateDraft("taskBrief", event.target.value)} rows={4} /><p><strong>최종 산출물</strong>{draft.product}</p></section>
          <section><h3>차시별 과정 증거</h3><ol className="lessonPlan">{draft.lessonPlan.map((item) => <li key={`${item.lesson}-${item.title}`}><span>{item.lesson}</span><div><strong>{item.title}</strong><p>{item.evidence}</p></div></li>)}</ol></section>
          <section><h3>분석적 루브릭 초안</h3><div className="rubricTable" role="table" aria-label="루브릭 초안"><div role="row"><strong role="columnheader">평가 요소</strong><strong role="columnheader">배점</strong><strong role="columnheader">확인할 핵심</strong></div>{draft.rubric.map((item) => <div role="row" key={item.label}><span role="cell">{item.label}</span><b role="cell">{item.points}점</b><span role="cell">{item.focus}</span></div>)}</div><p className="rubricTotal">합계 <strong>{draft.rubric.reduce((sum, item) => sum + item.points, 0)}점</strong></p></section>
          <div className="draftTwoColumns"><section><h3>AI 활용 안내</h3><textarea value={draft.aiGuidance} onChange={(event) => updateDraft("aiGuidance", event.target.value)} rows={5} /></section><section><h3>공정성 점검</h3><ul>{draft.fairnessChecklist.map((item) => <li key={item}>{item}</li>)}</ul></section></div>
        </div>
        <p className="draftDisclaimer">이 문서는 자동 완성된 평가계획이 아니라 교사용 템플릿 초안입니다. 성취기준 원문 연결, 학생 수준, 학교 학업성적관리규정과 결시자 처리 기준은 최종 확정 전에 교사가 검토해야 합니다. 저장 내용은 이 브라우저에만 남으므로 공용 PC에서는 사용 후 브라우저 데이터를 삭제하세요.</p>
      </section>
    </main>
  );
}
