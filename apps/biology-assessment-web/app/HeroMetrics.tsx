"use client";

import { useEffect, useState } from "react";

import { fetchCatalog, type ProductMetadata } from "./lib/catalog-api";

export default function HeroMetrics() {
  const [meta, setMeta] = useState<ProductMetadata | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog<ProductMetadata>("meta", controller.signal)
      .then(setMeta)
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      });
    return () => controller.abort();
  }, []);

  const rows: Array<[string, number | undefined]> = [
    ["공개 확정 학교", meta?.published_schools],
    ["공개 수행평가", meta?.published_assessment_items],
    ["공개 확정 사례", meta?.published_cases],
  ];

  return (
    <aside className="evidencePanel" aria-label="현재 데이터 기준선">
      <div className="panelTopline">
        <span>검증된 데이터 기준선</span>
        <strong>{error ? "오류" : meta?.catalog_ready ? "공개 중" : "준비 중"}</strong>
      </div>
      <dl className="metricList">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value === undefined ? "—" : value.toLocaleString("ko-KR")}</dd>
          </div>
        ))}
      </dl>
      <p>
        {error
          ? error
          : "원문·과목 경계·개인정보 검토를 통과한 공개 자료 기준입니다. 전국 학교 전수나 과목 개설 현황을 뜻하지 않습니다."}
      </p>
    </aside>
  );
}
