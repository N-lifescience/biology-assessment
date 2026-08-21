"use client";

import Link from "../SiteLink";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  apiParameters,
  fetchCatalog,
  type CuratedAssessmentItem,
  type FacetResponse,
  type ReferencePageResponse,
  type SubjectItem,
} from "../lib/catalog-api";

const CURATED_SIZE = 30;
// 동국대 「수행평가 영역명 활용 가이드북」 과학 교과의 방법 축 10종.
// 영역명은 "주제(내용) × 방법"으로 설계하므로 주제 축(TOPICS)과 짝을 이룬다.
// API의 category/topic 패턴과 값을 맞춘다.
const CATEGORIES = [
  { id: "inquiry", label: "탐구" },
  { id: "experiment", label: "실험평가" },
  { id: "writing", label: "작성" },
  { id: "production", label: "제작" },
  { id: "analysis", label: "분석" },
  { id: "reasoning", label: "추론·설명" },
  { id: "discussion", label: "발표·토론" },
  { id: "measurement", label: "계산·측정" },
  { id: "process", label: "과정평가" },
  { id: "problem", label: "문제해결" },
] as const;

// 같은 가이드북의 주제(내용) 축 16종. 물리·화학·지구과학 주제도 포함되는데,
// 통합과학1·과학탐구실험1이 그 내용을 실제로 다루기 때문이다.
const TOPICS = [
  { id: "cell", label: "세포와 물질대사" },
  { id: "genetics", label: "유전" },
  { id: "environment", label: "환경" },
  { id: "nos", label: "과학적 사고" },
  { id: "history", label: "과학사" },
  { id: "ethics", label: "연구 윤리와 안전" },
  { id: "matter", label: "물질의 구성" },
  { id: "reaction", label: "화학 반응" },
  { id: "motion", label: "운동과 힘" },
  { id: "wave", label: "빛과 파동" },
  { id: "electromagnetism", label: "전자기" },
  { id: "earth", label: "지구" },
  { id: "space", label: "우주·천체" },
  { id: "everyday", label: "실생활" },
  { id: "career", label: "진로" },
  { id: "data", label: "자료" },
] as const;

type CategoryId = (typeof CATEGORIES)[number]["id"];
type TopicId = (typeof TOPICS)[number]["id"];

function safeCurriculum(value: string | null) {
  return value === "2015" || value === "2022" ? value : "";
}

function safeTopic(value: string | null): TopicId | "" {
  return TOPICS.some((topic) => topic.id === value) ? value as TopicId : "";
}

function safeCategory(value: string | null): CategoryId {
  return CATEGORIES.some((category) => category.id === value) ? value as CategoryId : "inquiry";
}

function uniqueSubjectOptions(subjects: SubjectItem[], curriculum: string) {
  const totals = new Map<string, number>();
  for (const item of subjects) {
    if (curriculum && item.curriculum !== curriculum) continue;
    totals.set(item.subject, (totals.get(item.subject) ?? 0) + item.documents);
  }
  return [...totals.entries()].map(([subject, documents]) => ({ subject, documents }));
}

export default function ReferenceExplorer() {
  const parameters = useSearchParams();
  const router = useRouter();
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [curriculum, setCurriculum] = useState(safeCurriculum(parameters.get("curriculum")));
  const [subject, setSubject] = useState(parameters.get("subject") || "");
  const [region, setRegion] = useState(parameters.get("region") || "");
  const [district, setDistrict] = useState(parameters.get("district") || "");
  const [category, setCategory] = useState<CategoryId>(safeCategory(parameters.get("category")));
  const [topic, setTopic] = useState<TopicId | "">(safeTopic(parameters.get("topic")));
  const [facets, setFacets] = useState<FacetResponse>({ regions: [], districts: [], action_tags: [] });
  const [items, setItems] = useState<CuratedAssessmentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [interpretation, setInterpretation] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog<ReferencePageResponse>(`references?${apiParameters({ curriculum, subject, region, district, category, topic: topic || undefined, limit: CURATED_SIZE })}`, controller.signal)
      .then((payload) => {
        setSubjects(payload.subjects.filter((item) => item.curriculum !== "shared"));
        setFacets(payload.facets);
        setItems(payload.items);
        setTotal(payload.total);
        setInterpretation(payload.interpretation);
      })
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [curriculum, subject, region, district, category, topic]);

  useEffect(() => {
    const query = apiParameters({ curriculum, subject, region, district, category: category === "inquiry" ? undefined : category, topic: topic || undefined });
    router.replace(query ? `/references?${query}` : "/references", { scroll: false });
  }, [curriculum, subject, region, district, category, topic, router]);

  const courseOptions = useMemo(() => uniqueSubjectOptions(subjects, curriculum), [curriculum, subjects]);
  const activeFilterCount = [curriculum, subject, region, district].filter(Boolean).length;

  function beginReload() { setLoading(true); setError(""); }
  function changeCurriculum(value: string) {
    const next = uniqueSubjectOptions(subjects, value);
    beginReload(); setCurriculum(value); setSubject(next.some((item) => item.subject === subject) ? subject : ""); setRegion(""); setDistrict("");
  }
  function clearFilters() { beginReload(); setCurriculum(""); setSubject(""); setRegion(""); setDistrict(""); }

  return <main id="main-content" className="catalogPage referencePage">
    <header className="pageHeaderCompact">
      <div><p className="breadcrumb"><Link href="/">홈</Link><span>/</span>유형별 설계 참고</p><h1>유형별 원문 근거 확인도</h1></div>
      <p><strong>{total.toLocaleString()}</strong><span>조건 내 참고 후보<br />상위 {items.length.toLocaleString()}건 표시</span></p>
    </header>

    <section className="referenceBoundary" aria-label="원문 근거 확인도 기준">
      <div><strong>학교·교사 순위가 아닙니다.</strong><span>원문 표 제목, 평가 방법·배점, 성취기준, 루브릭이 함께 확인되는 정도로 설계 참고 순서를 정리했습니다.</span></div>
      <Link href="/cases">전체 라이브러리에서 찾기 →</Link>
    </section>

    <section className="caseFilterPanel referenceFilterPanel" aria-label="유형별 설계 참고 필터">
      <div className="caseFilterTopline"><div><span className="stepPill">필터</span><h2>과목·지역 좁히기</h2></div><button type="button" onClick={clearFilters}>전체로 초기화{activeFilterCount ? ` (${activeFilterCount})` : ""}</button></div>
      <div className="filterControls caseCourseControls">
        <label><span>교육과정</span><select value={curriculum} onChange={(event) => changeCurriculum(event.target.value)}><option value="">전체 교육과정</option><option value="2015">2015 개정</option><option value="2022">2022 개정</option></select></label>
        <label className="wideControl"><span>생명과학 교과군 과목</span><select value={subject} onChange={(event) => { beginReload(); setSubject(event.target.value); setRegion(""); setDistrict(""); }}><option value="">전체 과목</option>{courseOptions.map((item) => <option key={item.subject} value={item.subject}>{item.subject} · {item.documents.toLocaleString()}건</option>)}</select></label>
        <label><span>시·도</span><select value={region} onChange={(event) => { beginReload(); setRegion(event.target.value); setDistrict(""); }}><option value="">전국</option>{facets.regions.map((item) => <option key={item.value} value={item.value}>{item.value} · {item.count}</option>)}</select></label>
        <label><span>시·군·구</span><select value={district} disabled={!region} onChange={(event) => { beginReload(); setDistrict(event.target.value); }}><option value="">{region ? "전체 시·군·구" : "시·도를 먼저 선택"}</option>{region ? facets.districts.map((item) => <option key={item.value} value={item.value}>{item.value} · {item.count}</option>) : null}</select></label>
      </div>
    </section>

    <section className="curatedSection referenceCuratedSection" aria-labelledby="curated-title">
      <div className="sectionTopline"><div><span className="stepPill">유형</span><div><h2 id="curated-title">설계 방식 선택</h2><p>수행평가 영역명은 <strong>주제(내용) × 방법</strong>으로 설계합니다(동국대 「수행평가 영역명 활용 가이드북」 기준). 방법을 고르고 주제를 좁히면 그 조합의 실제 사례를 최대 30건 봅니다. 분류는 원문의 영역명과 학교가 표시한 평가 방법을 근거로 자동 판정하며, 같은 근거 점수 안의 순서에는 품질 의미가 없습니다.</p></div></div></div>
      <div className="categoryTabs" role="tablist" aria-label="평가 방법">{CATEGORIES.map((item) => <button type="button" role="tab" aria-selected={category === item.id} className={category === item.id ? "selected" : ""} key={item.id} onClick={() => { beginReload(); setCategory(item.id); }}>{item.label}</button>)}</div>
      <div className="topicFilterRow">
        <label htmlFor="reference-topic">주제(내용)</label>
        <select id="reference-topic" value={topic} onChange={(event) => { beginReload(); setTopic(safeTopic(event.target.value)); }}>
          <option value="">전체 주제</option>
          {TOPICS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </div>
      {loading ? <div className="compactLoading" role="status">설계 참고 순서를 정리하고 있습니다.</div> : null}
      {error ? <div className="errorPanel" role="alert"><strong>자료를 불러오지 못했습니다.</strong><p>{error}</p></div> : null}
      {!loading && !error && items.length ? <div className="tableScroll"><table className="curatedTable"><thead><tr><th>표시 순서</th><th>수행평가명</th><th>과목·학교</th><th>확인된 근거</th><th>확인</th></tr></thead><tbody>{items.map((item, index) => <tr key={item.item_id}><td data-label="표시 순서"><strong className="rankNumber">{index + 1}</strong></td><td data-label="수행평가명"><strong>{item.title}</strong>{item.overview ? <p>{item.overview}</p> : null}</td><td data-label="과목·학교"><span>{item.curriculum} 개정 · {item.subject}</span><small>{item.school_name}<br />{item.region}{item.district ? ` ${item.district}` : ""}</small></td><td data-label="확인된 근거"><div className="signalChips">{item.priority_signals.map((signal) => <span key={signal}>{signal}</span>)}</div></td><td data-label="확인"><Link href={`/cases/${item.case_id}?item=${item.item_id}`}>원문 표 보기 →</Link></td></tr>)}</tbody></table></div> : null}
      {!loading && !error && items.length === 0 ? <p className="compactEmpty">이 조건에서 원문 표 제목·구조까지 확인된 설계 참고 사례가 아직 없습니다. 전체 라이브러리에서 원문 묶음도 함께 찾아볼 수 있습니다.</p> : null}
      {interpretation ? <p className="rankingBoundary">{interpretation}</p> : null}
    </section>
  </main>;
}
