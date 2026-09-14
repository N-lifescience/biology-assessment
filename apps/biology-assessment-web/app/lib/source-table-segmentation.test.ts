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
      flattenedNestedTableCount: 0,
      removedEmptyTableCount: 0,
      prunedBlankRowCount: 0,
      headerSplitCount: 0,
      unwrappedHeadingTableCount: 0,
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

  it("strips script tags, inline event handlers, and javascript: URLs before rendering", () => {
    const html = `<table>${row("평가영역명", "탐구")}${row("수행과제", "보고서")}</table>
      <script>alert(1)</script>
      <img src="x" onerror="alert(2)">
      <a href="javascript:alert(3)">링크</a>`;

    const result = segmentSourceTables(html);

    expect(result.html).not.toContain("<script");
    expect(result.html).not.toContain("onerror");
    expect(result.html).not.toContain("javascript:");
  });

  function th(...cells: string[]) {
    return `<tr>${cells.map((cell) => `<th>${cell}</th>`).join("")}</tr>`;
  }

  function headings(html: string) {
    return Array.from(parse(html).querySelectorAll("section.sourceTableSection h3"))
      .map((heading) => heading.textContent);
  }

  it("reads 평가영역 / 영역명 style first cells as the overview block, not as standards", () => {
    for (const label of ["평가 영역", "평가영역(단원)", "평가영역1", "영역명", "수행평가 영역"]) {
      const html = `<table>${[
        row(label, "생명 시스템 탐구"),
        row("수행 과제", "세포 관찰 보고서 작성"),
        row("성취기준", "[12생과Ⅰ01-01] 세포의 구조를 설명할 수 있다"),
        row("A", "세포의 구조와 기능을 연결해 설명할 수 있다"),
        row("B", "세포의 구조를 설명할 수 있다"),
        row("평가방법", "관찰 및 보고서"),
      ].join("")}</table>`;

      expect(headings(segmentSourceTables(html).html), label).toEqual([
        "평가 개요·수행과제",
        "성취기준·성취수준",
        "평가 방법·운영",
      ]);
    }
  });

  it("treats a summary header row followed by 반영 비율 as the overview block", () => {
    const html = `<table>${[
      th("평가 종류", "정기 시험", "수행평가", "합계"),
      row("반영 비율", "40%", "60%", "100%"),
      row("횟수/영역", "2차", "탐구 보고서", "-"),
      row("영역만점", "100점", "20점", ""),
      row("성취기준", "[12생과Ⅰ01-01]", "", ""),
      row("A", "설명할 수 있다", "", ""),
    ].join("")}</table>`;

    expect(headings(segmentSourceTables(html).html)).toEqual([
      "평가 개요·수행과제",
      "성취기준·성취수준",
    ]);
  });

  it("starts a new table at a converter header row that fused two source tables", () => {
    const html = `<table>${[
      row("평가영역", "생명과학의 역사", "반영비율", "20 %"),
      row("수행과제", "탐구 보고서", "", ""),
      row("성취기준", "[12생과Ⅱ01-01]", "상", "설명할 수 있다"),
      row("", "", "중", "나열할 수 있다"),
      th("평가요소", "횟수", "배점", "채점기준", "평정점"),
      row("내용의 적절성", "1", "80", "객관적이고 논리적으로 표현한 경우", "80"),
      row("글의 양식", "1", "20", "글의 양식을 잘 지킨 경우", "20"),
    ].join("")}</table>`;

    const result = segmentSourceTables(html);

    // The header row opens a differently labelled section, so it gets its own
    // heading rather than a same-heading continuation.
    expect(result.headerSplitCount).toBe(0);
    expect(headings(result.html)).toEqual([
      "평가 개요·수행과제",
      "성취기준·성취수준",
      "채점 기준·배점",
    ]);
    const rubric = tables(result.html).at(-1)!;
    expect(rowTexts(rubric)[0]).toBe("평가요소|횟수|배점|채점기준|평정점");
    // The fused rubric keeps its own 5-column grid: no placeholder cells were added.
    expect(rubric.rows[1].cells).toHaveLength(5);
  });

  it("puts a repeated header row inside one section under the same heading", () => {
    const html = `<table>${[
      th("평가요소", "채점기준", "배점"),
      row("근거", "과학적 근거가 타당함", "10"),
      row("표현", "논리적으로 표현함", "10"),
      th("평가요소", "채점기준", "배점"),
      row("태도", "적극적으로 참여함", "5"),
      row("제출", "기한 내 제출함", "5"),
    ].join("")}</table>`;

    const result = segmentSourceTables(html);

    expect(result.headerSplitCount).toBe(1);
    expect(headings(result.html)).toEqual(["채점 기준·배점"]);
    expect(tables(result.html)).toHaveLength(2);
    expect(tables(result.html).flatMap(rowTexts)).toHaveLength(6);
  });

  it("flattens a table nested inside a cell into that cell's text", () => {
    const html = `<table>${[
      row("평가영역명", "탐구"),
      `<tr><td>평가유형</td><td><table><tr><th>( 탐구보고서 )</th></tr><tr><td>개인</td><td>모둠</td></tr></table></td></tr>`,
    ].join("")}</table>`;

    const result = segmentSourceTables(html);

    expect(result.flattenedNestedTableCount).toBe(1);
    expect(tables(result.html)).toHaveLength(1);
    const cell = parse(result.html).querySelector("[data-source-flattened-table]")!;
    expect(cell.innerHTML).toBe("( 탐구보고서 )<br>개인 · 모둠");
  });

  it("removes tables with no text and rows that are blank in every cell", () => {
    const html = `
      <table></table>
      <table><tr><td></td><td></td></tr></table>
      <table>${[
        row("평가요소", "채점기준", "배점"),
        row("", "", ""),
        row("근거", "타당함", "10"),
        `<tr><td rowspan="2">표현</td><td>논리적임</td><td>10</td></tr>`,
        row("", ""),
      ].join("")}</table>`;

    const result = segmentSourceTables(html);

    expect(result.removedEmptyTableCount).toBe(2);
    expect(result.prunedBlankRowCount).toBe(1);
    const [table] = tables(result.html);
    expect(tables(result.html)).toHaveLength(1);
    // The row spanned by 표현 stays: it is a continuation, not a blank row.
    expect(rowTexts(table)).toEqual([
      "평가요소|채점기준|배점",
      "근거|타당함|10",
      "표현|논리적임|10",
      "|",
    ]);
  });

  it("turns a boxed section-number heading table back into a heading", () => {
    const html = `
      <table><thead><tr><th>Ⅴ</th><th></th><th>평가의 종류와 반영 비율</th></tr></thead><tbody></tbody></table>
      <table>${row("평가 종류", "정기 시험", "수행평가")}${row("반영 비율", "40%", "60%")}</table>`;

    const result = segmentSourceTables(html);

    expect(result.unwrappedHeadingTableCount).toBe(1);
    const document = parse(result.html);
    expect(document.querySelector("[data-source-unwrapped-heading]")?.textContent).toBe(
      "Ⅴ 평가의 종류와 반영 비율",
    );
    // A one-row label/value table with a score stays a table.
    expect(tables(result.html)).toHaveLength(1);
  });
});
