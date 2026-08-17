"use client";

import { useEffect, useState } from "react";

import { fetchCatalog, type ProductMetadata } from "../lib/catalog-api";

export default function DataSnapshot() {
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

  if (error) {
    return (
      <div className="sourceRegistryError" role="alert">
        <strong>검증 스냅숏을 불러오지 못했습니다.</strong>
        <p>{error}</p>
      </div>
    );
  }

  const rows: Array<[string, number | undefined, string]> = [
    ["공개계획 확인 대상", meta?.plans_checked, "곳"],
    ["수집 정규화 사례", meta?.normalized_cases, "건"],
    ["공개 확정 학교", meta?.published_schools, "곳"],
    ["공개 확정 사례", meta?.published_cases, "건"],
    ["공개 수행평가", meta?.published_assessment_items, "건"],
  ];

  return (
    <dl>
      {rows.map(([label, value, unit]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>
            {value === undefined ? "…" : value.toLocaleString("ko-KR")}
            <small>{unit}</small>
          </dd>
        </div>
      ))}
    </dl>
  );
}
