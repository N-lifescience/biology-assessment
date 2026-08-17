import { describe, expect, it, vi } from "vitest";

import { segmentSourceTables } from "./source-table-segmentation";

function parse(html: string) {
  return new DOMParser().parseFromString(html, "text/html");
}

function tables(html: string) {
  return Array.from(parse(html).body.querySelectorAll("table"));
}

function rowTexts(table: HTMLTableElement) {
  return Array.from(table.rows).map((row) =>
    Array.from(row.cells).map((cell) => (cell.textContent || "").trim()).join("|"),
  );
}

function row(...cells: string[]) {
  return `<tr>${cells.map((cell) => `<td>${cell}</td>`).join("")}</tr>`;
}

describe("segmentSourceTables", () => {
  it("splits one long table into labelled sections", () => {
    const html = `<table>${[
      row("평가영역명", "생명 시스템 탐구"),
      row("수행과제", "세포 관찰 보고서 작성"),
      row("성취기준", "세포의 구조를 설명한다"),
      row("평가방법", "관찰 및 보고서"),
      row("평가요소", "관찰 기록의 정확성"),
      row("배점", "20점"),
    ].join("")}</table>`;

    const result = segmentSourceTables(html);

    expect(result.splitTableCount).toBe(1);
    expect(result.sectionCount).toBe(4);

    const document = parse(result.html);
    const headings = Array.from(document.querySelectorAll("section.sourceTableSection h3"))
      .map((heading) => heading.textContent);
    expect(headings).toEqual([
      "평가 개요·수행과제",
      "성취기준·성취수준",
      "평가 방법·운영",
      "채점 기준·배점",
    ]);

    // Every source row survives the split exactly once, in order.
    expect(tables(result.html).flatMap(rowTexts)).toEqual([
      "평가영역명|생명 시스템 탐구",
      "수행과제|세포 관찰 보고서 작성",
      "성취기준|세포의 구조를 설명한다",
      "평가방법|관찰 및 보고서",
      "평가요소|관찰 기록의 정확성",
      "배점|20점",
    ]);
  });

  it("merges adjacent tables that repeat an identical header row", () => {
    const header = "<tr><th>성취기준</th><th>성취수준</th></tr>";
    const html = `
      <table>${header}${row("[12생과Ⅰ01-01]", "세포를 설명할 수 있다")}</table>
      <table>${header}${row("[12생과Ⅰ01-02]", "물질대사를 설명할 수 있다")}</table>
    `;

    const result = segmentSourceTables(html);

    expect(result.mergedFragmentCount).toBe(1);
    const merged = tables(result.html);
    expect(merged).toHaveLength(1);
    expect(merged[0].getAttribute("data-source-merged-fragments")).toBe("true");
    expect(rowTexts(merged[0])).toEqual([
      "성취기준|성취수준",
      "[12생과Ⅰ01-01]|세포를 설명할 수 있다",
      "[12생과Ⅰ01-02]|물질대사를 설명할 수 있다",
    ]);
  });

  it("joins an A-C table with the D-E table that continues it after a page break", () => {
    const html = `
      <table>
        <tr><th>성취수준</th><th>수준 진술문</th></tr>
        ${row("A", "구조와 기능을 연결해 설명할 수 있다")}
        ${row("B", "구조를 설명할 수 있다")}
        ${row("C", "구조를 나열할 수 있다")}
      </table>
      <table>
        ${row("D", "안내를 받아 구조를 찾을 수 있다")}
        ${row("E", "구조의 뜻을 안다")}
      </table>
    `;

    const result = segmentSourceTables(html);

    expect(result.gradeContinuationRowCount).toBe(2);
    const merged = tables(result.html);
    expect(merged).toHaveLength(1);
    expect(merged[0].getAttribute("data-source-merged-grade-continuation")).toBe("true");
    expect(rowTexts(merged[0]).map((text) => text.split("|")[0])).toEqual([
      "성취수준",
      "A",
      "B",
      "C",
      "D",
      "E",
    ]);
    expect(
      merged[0].querySelectorAll("[data-source-grade-continuation]"),
    ).toHaveLength(2);
  });

  it("leaves a short table untouched even when its labels name several sections", () => {
    const html = `<table>${[
      row("평가영역명", "생명 시스템 탐구"),
      row("성취기준", "세포의 구조를 설명한다"),
      row("평가방법", "관찰 및 보고서"),
      row("평가요소", "관찰 기록의 정확성"),
    ].join("")}</table>`;

    const result = segmentSourceTables(html);

    expect(result.splitTableCount).toBe(0);
    expect(result.sectionCount).toBe(0);
    expect(result.html).not.toContain("sourceTableSections");
    expect(tables(result.html)).toHaveLength(1);
    expect(rowTexts(tables(result.html)[0])).toEqual([
      "평가영역명|생명 시스템 탐구",
      "성취기준|세포의 구조를 설명한다",
      "평가방법|관찰 및 보고서",
      "평가요소|관찰 기록의 정확성",
    ]);
  });

  it("leaves a long table without section labels untouched", () => {
    const cells = [
      row("1차시", "탐구 주제 선정"),
      row("2차시", "실험 설계"),
      row("3차시", "자료 수집"),
      row("4차시", "결과 분석"),
      row("5차시", "발표 준비"),
      row("6차시", "상호 평가"),
    ];
    const result = segmentSourceTables(`<table>${cells.join("")}</table>`);

    expect(result.splitTableCount).toBe(0);
    expect(result.sectionCount).toBe(0);
    expect(result.mergedFragmentCount).toBe(0);
    expect(result.html).not.toContain("sourceTableSections");
    expect(rowTexts(tables(result.html)[0])).toEqual([
      "1차시|탐구 주제 선정",
      "2차시|실험 설계",
      "3차시|자료 수집",
      "4차시|결과 분석",
      "5차시|발표 준비",
      "6차시|상호 평가",
    ]);
  });

  it("returns the input unchanged for blank input or a missing DOMParser", () => {
    const zeroed = {
      splitTableCount: 0,
      sectionCount: 0,
      mergedFragmentCount: 0,
      reconstructedCellCount: 0,
      orphanStandardGroupCount: 0,
      recoveredNoteGroupCount: 0,
      clampedRowspanCount: 0,
      gradeContinuationRowCount: 0,
      prunedTrailingColumnCount: 0,
      normalizedLongHeaderCellCount: 0,
    };

    expect(segmentSourceTables("   ")).toEqual({ html: "   ", ...zeroed });

    const splittable = `<table>${[
      row("평가영역명", "생명 시스템 탐구"),
      row("수행과제", "세포 관찰 보고서 작성"),
      row("성취기준", "세포의 구조를 설명한다"),
      row("평가방법", "관찰 및 보고서"),
      row("평가요소", "관찰 기록의 정확성"),
    ].join("")}</table>`;
    // Guard: without the stub this very input is split, so the branch is real.
    expect(segmentSourceTables(splittable).splitTableCount).toBe(1);

    vi.stubGlobal("DOMParser", undefined);
    try {
      expect(segmentSourceTables(splittable)).toEqual({ html: splittable, ...zeroed });
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
