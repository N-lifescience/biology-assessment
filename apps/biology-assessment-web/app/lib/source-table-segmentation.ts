export type SegmentedSourceHtml = {
  html: string;
  splitTableCount: number;
  sectionCount: number;
  mergedFragmentCount: number;
  reconstructedCellCount: number;
  orphanStandardGroupCount: number;
  recoveredNoteGroupCount: number;
  clampedRowspanCount: number;
  gradeContinuationRowCount: number;
  prunedTrailingColumnCount: number;
  normalizedLongHeaderCellCount: number;
  flattenedNestedTableCount: number;
  removedEmptyTableCount: number;
  prunedBlankRowCount: number;
  headerSplitCount: number;
  unwrappedHeadingTableCount: number;
};

type SectionKey = "overview" | "standards" | "method" | "rubric";

type SectionRange = {
  key: SectionKey;
  start: number;
  end: number;
  /**
   * True when this range begins at a converter header row inside the same
   * logical section: it is rendered as a second table under the previous
   * heading instead of repeating the heading.
   */
  continues: boolean;
};

type CellPlacement = {
  cell: HTMLTableCellElement;
  rowStart: number;
  rowEnd: number;
  columnStart: number;
  columnSpan: number;
};

const SECTION_META: Record<SectionKey, { label: string; rank: number }> = {
  overview: { label: "평가 개요·수행과제", rank: 0 },
  standards: { label: "성취기준·성취수준", rank: 1 },
  method: { label: "평가 방법·운영", rank: 2 },
  rubric: { label: "채점 기준·배점", rank: 3 },
};

function compact(value: string) {
  return value.replace(/\s+/g, "").replace(/[·･ㆍ:：]/g, "");
}

/**
 * Labels a source table uses in its first column to open the overview block
 * of one assessment.  Converters spell them many ways (평가영역, 평가 영역(단원),
 * 평가영역1, 영역명, 수행평가명 ...), so match the compacted prefix only.
 */
const OVERVIEW_FIRST_CELL_RE = (
  /^(평가영역|영역명|수행평가영역|수행평가명|평가명|평가주제|평가단원|단원명|반영비율|영역만점|수행과제|평가과제|과제명|평가내용|평가문항|평가항목|평가종류)/
);

function isRubricHeaderText(all: string) {
  return (
    /평가요소/.test(all)
    && /(채점기준|수행수준|평가척도|평가기준|세부기준|세부평가기준)/.test(all)
    && /(배점|점수|척도)/.test(all)
  );
}

/** A converter header row: every cell is a ``th`` and at least one has text. */
function isHeaderRow(row: HTMLTableRowElement) {
  const cells = Array.from(row.cells);
  return (
    cells.length >= 2
    && cells.every((cell) => cell.tagName === "TH")
    && cells.some((cell) => compact(cell.textContent || ""))
  );
}

function rowSection(row: HTMLTableRowElement): SectionKey | null {
  const cells = Array.from(row.cells).map((cell) => compact(cell.textContent || ""));
  const leading = cells.filter(Boolean).slice(0, 3);
  const first = leading[0] || "";
  const early = leading.join(" ");
  const all = cells.join(" ");

  // A rubric header ("평가 영역 | 평가 요소 | 채점 기준 | 배점") also starts with
  // 평가영역, so it must be recognised before the overview labels.
  if (isRubricHeaderText(all)) return "rubric";
  if (
    isHeaderRow(row)
    && /(배점|점수|척도)/.test(all)
    && /(등급|수준|기준|요소|척도)/.test(all)
    && !/성취기준/.test(all)
  ) return "rubric";
  if (OVERVIEW_FIRST_CELL_RE.test(first) || /(?:^| )(평가영역명|수행과제|평가과제|과제명)/.test(early)) {
    return "overview";
  }
  if (/성취기준/.test(early) || /성취기준별성취수준/.test(early)) return "standards";
  if (/(?:^| )평가(방법|방식|유형|시기)/.test(early)) return "method";
  if (
    /^(평가요소|채점기준|세부평가기준|수행수준)/.test(first)
    || (/평가요소/.test(all) && /(수행수준|채점기준)/.test(all) && /(배점|척도)/.test(all))
  ) return "rubric";
  return null;
}

function inferredInitialSection(rows: HTMLTableRowElement[]): SectionKey {
  const explicit = rowSection(rows[0]);
  if (explicit) return explicit;
  // "평가 종류 | 정기시험 | 수행평가 | 합계" followed by "반영 비율 | 40% | ..." is
  // the summary block of an assessment plan, not an achievement-level table.
  if (rows.length > 1 && isHeaderRow(rows[0]) && rowSection(rows[1]) === "overview") return "overview";
  const sample = compact(rows.slice(0, 8).map((row) => row.textContent || "").join(" "));
  if (/\[12[A-Za-z가-힣ⅠⅡ]{1,16}\d{2}[-‐‑‒–—]\d{2}\]/u.test(sample)) return "standards";
  if (/(?:^|[^A-Za-z])A(?:[^A-Za-z]|$)/.test(sample) && /수있다/.test(sample)) return "standards";
  if (/평가요소|채점기준|수행수준|배점/.test(sample)) return "rubric";
  return "overview";
}

function rowCellSignature(row: HTMLTableRowElement) {
  return Array.from(row.cells)
    .map((cell) => `${cell.tagName}:${cell.colSpan}:${compact(cell.textContent || "")}`)
    .join("|");
}

function knownRepeatedHeader(row: HTMLTableRowElement) {
  const text = compact(row.textContent || "");
  return (
    (/성취기준/.test(text) && /(평가기준|성취수준)/.test(text))
    || (/평가요소/.test(text) && /(채점기준|수행수준|배점)/.test(text))
  );
}

/**
 * PDF converters sometimes emit every page of one table as a separate table,
 * repeating an identical header row.  Merge only directly adjacent fragments
 * whose header cells and spans are exactly identical.
 */
const DANGEROUS_ELEMENT_SELECTOR = "script, iframe, object, embed";
const JAVASCRIPT_URL_RE = /^\s*javascript:/i;

/**
 * The source HTML comes from an automated PDF/HWP-to-table conversion of
 * official documents, not from a live user, but nothing downstream verifies
 * that conversion never emits a stray ``<script>``/``onerror=`` fragment
 * before this reaches ``dangerouslySetInnerHTML``. Strip anything that could
 * execute before this function does any other transform.
 */
function sanitizeDangerousMarkup(document: Document) {
  for (const element of Array.from(document.body.querySelectorAll(DANGEROUS_ELEMENT_SELECTOR))) {
    element.remove();
  }
  for (const element of Array.from(document.body.querySelectorAll("*"))) {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on")) {
        element.removeAttribute(attribute.name);
      } else if (
        (name === "href" || name === "src") && JAVASCRIPT_URL_RE.test(attribute.value)
      ) {
        element.removeAttribute(attribute.name);
      }
    }
  }
}

function mergeRepeatedHeaderTables(document: Document) {
  let mergedFragmentCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    if (!table.isConnected || table.rows.length < 2) continue;
    const header = table.rows[0];
    if (!knownRepeatedHeader(header)) continue;
    const signature = rowCellSignature(header);
    let tableMerged = false;
    let next = table.nextElementSibling;
    while (next instanceof HTMLTableElement && next.rows.length >= 2) {
      const nextHeader = next.rows[0];
      if (!knownRepeatedHeader(nextHeader) || rowCellSignature(nextHeader) !== signature) break;
      const body = table.tBodies.item(table.tBodies.length - 1) || table.createTBody();
      for (const row of Array.from(next.rows).slice(1)) {
        body.append(row.cloneNode(true));
      }
      const following = next.nextElementSibling;
      next.remove();
      next = following;
      mergedFragmentCount += 1;
      tableMerged = true;
    }
    if (tableMerged) table.setAttribute("data-source-merged-fragments", "true");
  }
  return mergedFragmentCount;
}

function rowGrade(row: HTMLTableRowElement) {
  const grades = Array.from(row.cells)
    .map((cell) => compact(cell.textContent || ""))
    .filter((value) => /^[A-E]$/.test(value));
  return grades.length === 1 ? grades[0] : null;
}

function visibleRowWidth(row: HTMLTableRowElement) {
  return Array.from(row.cells).reduce((total, cell) => total + Math.max(1, cell.colSpan), 0);
}

function withoutLeadingBlankPlaceholders(
  row: HTMLTableRowElement,
  maximumWidth: number,
) {
  while (
    visibleRowWidth(row) > maximumWidth
    && row.cells.length > 1
    && !compact(row.cells[0].textContent || "")
  ) {
    row.cells[0].remove();
    row.setAttribute("data-source-leading-placeholder-removed", "true");
  }
}

/**
 * A page break can leave A-C achievement levels at the bottom of one table
 * and D-E at the top of the next.  Join only that exact A,B,C -> D,E sequence.
 * Empty leading cells in the new page are converter placeholders for rowspans
 * that began on the previous page, so they are removed from the cloned rows.
 */
function mergeAchievementLevelContinuations(document: Document) {
  let mergedRowCount = 0;
  const tables = Array.from(document.body.querySelectorAll("table"));
  for (const [tableIndex, table] of tables.entries()) {
    if (!table.isConnected || table.rows.length < 3) continue;
    const previousRows = Array.from(table.rows);
    const previousGrades = previousRows.map(rowGrade).filter((grade) => grade !== null);
    if (previousGrades.slice(-3).join("") !== "ABC") continue;
    const next = tables.slice(tableIndex + 1).find((candidate) => candidate.isConnected);
    if (!(next instanceof HTMLTableElement) || next.rows.length < 2) continue;
    const nextRows = Array.from(next.rows);
    const nextGradeEntries = nextRows
      .map((row, rowIndex) => ({ grade: rowGrade(row), rowIndex }))
      .filter((entry) => entry.grade !== null);
    if (
      nextGradeEntries.length < 2
      || nextGradeEntries[0].rowIndex > 4
      || `${nextGradeEntries[0].grade}${nextGradeEntries[1].grade}` !== "DE"
    ) continue;
    const secondGradeIndex = nextGradeEntries[1].rowIndex;
    const evidence = compact(`${table.textContent || ""} ${next.textContent || ""}`);
    const hasAchievementEvidence = (
      /(성취기준|성취수준|수준진술문|\[(?:10|12)[A-Za-z가-힣ⅠⅡ])/u.test(evidence)
      && /(수있|수준|뜻을안|이해|작성)/.test(evidence)
    );
    const hasRubricEvidence = (
      /(평가요소|수행수준|채점기준|배점)/.test(evidence)
      && /(점수|점|기준|수준)/.test(evidence)
    );
    if (!hasAchievementEvidence && !hasRubricEvidence) continue;

    let continuationEnd = secondGradeIndex + 1;
    while (continuationEnd < nextRows.length) {
      const row = nextRows[continuationEnd];
      if (rowGrade(row) || rowSection(row)) break;
      const text = compact(row.textContent || "");
      if (/^(평가방법|평가요소|평가유형|교과역량|채점|기본점수|미제출|장기)/.test(text)) break;
      continuationEnd += 1;
    }

    const body = table.tBodies.item(table.tBodies.length - 1) || table.createTBody();
    const maximumWidth = visibleRowWidth(previousRows.at(-1)!);
    for (const sourceRow of nextRows.slice(0, continuationEnd)) {
      const row = sourceRow.cloneNode(true) as HTMLTableRowElement;
      withoutLeadingBlankPlaceholders(row, maximumWidth);
      if (rowGrade(row)) {
        row.setAttribute("data-source-grade-continuation", "true");
        mergedRowCount += 1;
      } else {
        row.setAttribute("data-source-page-continuation", "true");
      }
      body.append(row);
      sourceRow.remove();
    }
    table.setAttribute("data-source-merged-grade-continuation", "true");
    if (!next.rows.length) {
      const scroll = next.parentElement?.classList.contains("sourceTableScroll")
        ? next.parentElement
        : null;
      const section = scroll?.parentElement?.classList.contains("sourceTableSection")
        ? scroll.parentElement
        : null;
      const wrapper = section?.parentElement?.classList.contains("sourceTableSections")
        ? section.parentElement
        : null;
      if (section) section.remove();
      else next.remove();
      if (wrapper && !wrapper.querySelector("table")) wrapper.remove();
    }
  }
  return mergedRowCount;
}

function lastNonEmptyCell(row: HTMLTableRowElement) {
  return Array.from(row.cells).reverse().find((cell) => compact(cell.textContent || ""));
}

function shortGapElements(table: HTMLTableElement) {
  const gap: Element[] = [];
  let previous = table.previousElementSibling;
  while (
    previous
    && !(previous instanceof HTMLTableElement)
    && /^H[2-6]$/.test(previous.tagName)
    && compact(previous.textContent || "").length <= 32
  ) {
    gap.unshift(previous);
    previous = previous.previousElementSibling;
  }
  return { previousTable: previous instanceof HTMLTableElement ? previous : null, gap };
}

/**
 * Repair the narrow continuation fragment visible when a PDF page split sends
 * only the final words of several rubric cells to a second mostly-empty table.
 * The repair is accepted only when row counts match a unique consecutive run
 * of visibly unfinished cells in the preceding table.
 */
function mergeSuffixContinuationTables(document: Document) {
  let reconstructedCellCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    if (!table.isConnected || table.rows.length < 4 || table.rows.length > 24) continue;
    const [blankHeader, ...suffixRows] = Array.from(table.rows);
    if (Array.from(blankHeader.cells).some((cell) => compact(cell.textContent || ""))) continue;
    const suffixCells = suffixRows.map((row) => {
      const nonEmpty = Array.from(row.cells).filter((cell) => compact(cell.textContent || ""));
      return nonEmpty.length === 1 ? nonEmpty[0] : null;
    });
    if (suffixCells.some((cell) => !cell)) continue;
    const suffixTexts = suffixCells.map((cell) => compact(cell?.textContent || ""));
    if (suffixTexts.some((text) => !text || text.length > 32)) continue;

    const { previousTable, gap } = shortGapElements(table);
    if (!previousTable) continue;
    const previousRows = Array.from(previousTable.rows);
    const matchingRuns: HTMLTableCellElement[][] = [];
    for (let start = 0; start + suffixRows.length <= previousRows.length; start += 1) {
      const cells = previousRows.slice(start, start + suffixRows.length).map(lastNonEmptyCell);
      if (
        cells.every(Boolean)
        && cells.every((cell) => /(?:기준을|충족하지|수준을|이상을|미만)$/.test(compact(cell?.textContent || "")))
      ) {
        matchingRuns.push(cells as HTMLTableCellElement[]);
      }
    }
    if (matchingRuns.length !== 1) continue;

    for (const [index, target] of matchingRuns[0].entries()) {
      target.append(document.createTextNode(` ${suffixCells[index]!.textContent || ""}`));
      target.setAttribute("data-source-reconstructed-cell", "true");
      reconstructedCellCount += 1;
    }

    if (gap.length) {
      const note = document.createElement("aside");
      note.className = "sourceRecoveredFragmentNotes";
      const label = document.createElement("strong");
      label.textContent = "원문 변환 중 표 밖에 남은 문구";
      note.append(label);
      for (const element of gap) {
        const span = document.createElement("span");
        span.textContent = element.textContent || "";
        note.append(span);
        element.remove();
      }
      previousTable.after(note);
    }
    table.remove();
  }
  return reconstructedCellCount;
}

const ORPHAN_STANDARD_RE = /^\s*(?:\[\s*12[A-Za-z가-힣ⅠⅡ]{1,16}\s*\d{2}\s*[-‐‑‒–—]\s*\d{2}\s*\]\s*)+$/u;

function groupOrphanAchievementStandards(document: Document) {
  let groupCount = 0;
  const children = Array.from(document.body.children);
  let index = 0;
  while (index < children.length) {
    const current = children[index];
    if (!ORPHAN_STANDARD_RE.test(current.textContent || "") || current.querySelector("table")) {
      index += 1;
      continue;
    }
    const run: Element[] = [];
    while (
      index < children.length
      && ORPHAN_STANDARD_RE.test(children[index].textContent || "")
      && !children[index].querySelector("table")
    ) {
      run.push(children[index]);
      index += 1;
    }
    if (run.length < 2) continue;
    const section = document.createElement("aside");
    section.className = "sourceOrphanStandards";
    const heading = document.createElement("strong");
    heading.textContent = "원문에 별도 표기된 성취기준";
    section.append(heading);
    for (const element of run) {
      const code = document.createElement("span");
      code.textContent = element.textContent || "";
      section.append(code);
      element.remove();
    }
    const anchor = children[index] || null;
    document.body.insertBefore(section, anchor);
    groupCount += 1;
  }
  return groupCount;
}

function groupShortDisplacedHeadings(document: Document) {
  let groupCount = 0;
  const children = Array.from(document.body.children);
  let index = 0;
  while (index < children.length) {
    const current = children[index];
    const isShortHeading = (
      /^H[4-6]$/.test(current.tagName)
      && compact(current.textContent || "").length > 0
      && compact(current.textContent || "").length <= 32
    );
    if (!isShortHeading) {
      index += 1;
      continue;
    }
    const run: Element[] = [];
    while (
      index < children.length
      && /^H[4-6]$/.test(children[index].tagName)
      && compact(children[index].textContent || "").length > 0
      && compact(children[index].textContent || "").length <= 32
    ) {
      run.push(children[index]);
      index += 1;
    }
    if (run.length < 2) continue;
    const note = document.createElement("aside");
    note.className = "sourceRecoveredFragmentNotes";
    const label = document.createElement("strong");
    label.textContent = "원문 변환 중 표 밖에 남은 문구";
    note.append(label);
    for (const element of run) {
      const span = document.createElement("span");
      span.textContent = element.textContent || "";
      note.append(span);
      element.remove();
    }
    const anchor = children[index] || null;
    document.body.insertBefore(note, anchor);
    groupCount += 1;
  }
  return groupCount;
}

/**
 * Converters nest a one-cell table inside a cell for boxed text such as
 * "( 탐구보고서 )".  A table inside a table renders as a broken grid, so the
 * inner rows are flattened to text (cells joined with " · ", rows on their own
 * line).  Nothing is dropped and nothing is invented.
 */
function flattenNestedTables(document: Document) {
  let flattenedCount = 0;
  const nested = Array.from(document.body.querySelectorAll("table table")).reverse();
  for (const inner of nested) {
    if (!inner.isConnected) continue;
    const lines = Array.from(inner.rows)
      .map((row) => Array.from(row.cells)
        .map((cell) => (cell.textContent || "").replace(/\s+/g, " ").trim())
        .filter(Boolean)
        .join(" · "))
      .filter(Boolean);
    const replacement = document.createElement("span");
    replacement.className = "sourceFlattenedTable";
    replacement.setAttribute("data-source-flattened-table", "true");
    for (const [index, line] of lines.entries()) {
      if (index) replacement.append(document.createElement("br"));
      replacement.append(document.createTextNode(line));
    }
    inner.replaceWith(replacement);
    flattenedCount += 1;
  }
  return flattenedCount;
}

const SECTION_NUMBER_RE = /^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[0-9]{1,2}|[가-힣])[.)]?$/u;

/**
 * Converters turn a boxed section heading ("Ⅴ | | 평가의 종류와 반영 비율")
 * into a one-row table.  When the only content is a section number plus a
 * short title, show it as the heading it was instead of an empty grid.
 */
function unwrapHeadingTables(document: Document) {
  let unwrappedCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    const rows = Array.from(table.rows).filter((row) => compact(row.textContent || ""));
    if (rows.length !== 1 || table.querySelector("table")) continue;
    const texts = Array.from(rows[0].cells)
      .map((cell) => (cell.textContent || "").replace(/\s+/g, " ").trim())
      .filter(Boolean);
    if (!texts.length || texts.length > 3) continue;
    const joined = texts.join(" ");
    const numbered = texts.length >= 2 && SECTION_NUMBER_RE.test(compact(texts[0]));
    if (!(numbered || texts.length === 1) || joined.length > 60 || /\d+\s*[점%]/.test(joined)) continue;
    const heading = document.createElement("p");
    heading.className = "sourceUnwrappedHeading";
    heading.setAttribute("data-source-unwrapped-heading", "true");
    heading.textContent = joined;
    table.replaceWith(heading);
    unwrappedCount += 1;
  }
  return unwrappedCount;
}

/** Drop tables that carry no text at all (leftover converter wrappers). */
function removeEmptyTables(document: Document) {
  let removedCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    if (compact(table.textContent || "") || table.querySelector("img")) continue;
    table.remove();
    removedCount += 1;
  }
  return removedCount;
}

/**
 * Remove rows that are blank in every cell they start, unless a cell from an
 * earlier row spans through them (then the row is a real continuation) or a
 * blank cell itself spans downward (removing it would shift the grid).
 */
function pruneBlankRows(document: Document) {
  let prunedCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    const rows = Array.from(table.rows);
    if (rows.length < 2) continue;
    const placements = tableCellPlacements(rows);
    const removable: HTMLTableRowElement[] = [];
    for (const [rowIndex, row] of rows.entries()) {
      const starting = placements.filter((placement) => placement.rowStart === rowIndex);
      if (!starting.length) continue;
      const blank = starting.every((placement) => !compact(placement.cell.textContent || ""));
      const spansDown = starting.some((placement) => placement.rowEnd - placement.rowStart > 1);
      const covered = placements.some(
        (placement) => placement.rowStart < rowIndex && placement.rowEnd > rowIndex,
      );
      if (blank && !spansDown && !covered) removable.push(row);
    }
    if (removable.length === rows.length) continue;
    for (const row of removable) {
      row.remove();
      prunedCount += 1;
    }
    if (removable.length) table.setAttribute("data-source-pruned-blank-rows", String(removable.length));
  }
  return prunedCount;
}

function clampOverflowingRowspans(document: Document) {
  let clampedCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    const rows = Array.from(table.rows);
    for (const [rowIndex, row] of rows.entries()) {
      const maximum = rows.length - rowIndex;
      for (const cell of Array.from(row.cells)) {
        const raw = Number.parseInt(cell.getAttribute("rowspan") || "1", 10);
        if (!Number.isFinite(raw) || raw <= maximum) continue;
        if (maximum > 1) cell.setAttribute("rowspan", String(maximum));
        else cell.removeAttribute("rowspan");
        cell.setAttribute("data-source-rowspan-clamped", "true");
        clampedCount += 1;
      }
    }
  }
  return clampedCount;
}

function sectionRanges(rows: HTMLTableRowElement[]): SectionRange[] {
  let currentKey: SectionKey = inferredInitialSection(rows);
  const sections: SectionRange[] = [{ key: currentKey, start: 0, end: rows.length, continues: false }];

  for (const [rowIndex, row] of rows.entries()) {
    const candidate = rowSection(row);
    const beginsNewCycle = (
      candidate === "overview"
      || (currentKey === "rubric" && candidate === "standards")
    );
    if (
      candidate
      && candidate !== currentKey
      && (beginsNewCycle || SECTION_META[candidate].rank > SECTION_META[currentKey].rank)
    ) {
      sections.at(-1)!.end = rowIndex;
      currentKey = candidate;
      sections.push({ key: currentKey, start: rowIndex, end: rows.length, continues: false });
      continue;
    }
    // PDF/HWP converters often drop the ``</table><table>`` boundary between
    // two source tables, so a second table's header row lands in the middle of
    // the first.  Start a new table there (same heading) so each keeps its own
    // column grid instead of the rubric being squeezed into the overview grid.
    if (rowIndex > 0 && rowIndex > sections.at(-1)!.start && isHeaderRow(row)) {
      sections.at(-1)!.end = rowIndex;
      if (candidate && candidate !== currentKey) currentKey = candidate;
      sections.push({ key: currentKey, start: rowIndex, end: rows.length, continues: true });
    }
  }
  return sections;
}

function positiveSpan(value: string | null, maximum: number) {
  const parsed = Number.parseInt(value || "1", 10);
  return Number.isFinite(parsed) && parsed > 0 ? Math.min(parsed, maximum) : 1;
}

function tableCellPlacements(rows: HTMLTableRowElement[]): CellPlacement[] {
  const occupied: boolean[][] = Array.from({ length: rows.length }, () => []);
  const placements: CellPlacement[] = [];

  for (const [rowIndex, row] of rows.entries()) {
    let columnIndex = 0;
    for (const cell of Array.from(row.cells)) {
      while (occupied[rowIndex][columnIndex]) columnIndex += 1;
      const rowSpan = positiveSpan(cell.getAttribute("rowspan"), rows.length - rowIndex);
      const columnSpan = positiveSpan(cell.getAttribute("colspan"), 50);
      const placement = {
        cell,
        rowStart: rowIndex,
        rowEnd: rowIndex + rowSpan,
        columnStart: columnIndex,
        columnSpan,
      };
      placements.push(placement);
      for (let targetRow = placement.rowStart; targetRow < placement.rowEnd; targetRow += 1) {
        for (
          let targetColumn = placement.columnStart;
          targetColumn < placement.columnStart + placement.columnSpan;
          targetColumn += 1
        ) {
          occupied[targetRow][targetColumn] = true;
        }
      }
      columnIndex += columnSpan;
    }
  }
  return placements;
}

function trimColgroup(table: HTMLTableElement, keepWidth: number) {
  for (const group of Array.from(table.querySelectorAll(":scope > colgroup"))) {
    let columnIndex = 0;
    for (const column of Array.from(group.querySelectorAll(":scope > col"))) {
      const span = positiveSpan(column.getAttribute("span"), 50);
      if (columnIndex >= keepWidth) {
        column.remove();
      } else if (columnIndex + span > keepWidth) {
        const retained = keepWidth - columnIndex;
        if (retained > 1) column.setAttribute("span", String(retained));
        else column.removeAttribute("span");
      }
      columnIndex += span;
    }
    if (!group.children.length) group.remove();
  }
}

/** Remove only columns that are empty in every row of the rendered table. */
function pruneTrailingBlankColumns(document: Document) {
  let prunedColumnCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    const rows = Array.from(table.rows);
    if (!rows.length) continue;
    const tableText = compact(table.textContent || "");
    if (/(학번|학생번호|이름|서명|확인자)/.test(tableText)) continue;
    const placements = tableCellPlacements(rows);
    const width = placements.reduce(
      (maximum, placement) => Math.max(maximum, placement.columnStart + placement.columnSpan),
      0,
    );
    if (width < 4) continue;
    const used = Array.from({ length: width }, () => false);
    for (const placement of placements) {
      if (!compact(placement.cell.textContent || "")) continue;
      for (
        let column = placement.columnStart;
        column < placement.columnStart + placement.columnSpan;
        column += 1
      ) used[column] = true;
    }
    const lastUsed = used.lastIndexOf(true);
    const keepWidth = lastUsed + 1;
    const trailing = width - keepWidth;
    if (keepWidth < 2 || trailing < 2 || (rows.length <= 2 && tableText.length < 120)) continue;

    for (const placement of placements) {
      const end = placement.columnStart + placement.columnSpan;
      if (placement.columnStart >= keepWidth) {
        placement.cell.remove();
      } else if (end > keepWidth) {
        const retained = keepWidth - placement.columnStart;
        if (retained > 1) placement.cell.setAttribute("colspan", String(retained));
        else placement.cell.removeAttribute("colspan");
      }
    }
    trimColgroup(table, keepWidth);
    table.setAttribute("data-source-pruned-trailing-columns", String(trailing));
    prunedColumnCount += trailing;
  }
  return prunedColumnCount;
}

function markLongHeaderCells(document: Document) {
  let normalizedCount = 0;
  for (const cell of Array.from(document.body.querySelectorAll("th"))) {
    const text = compact(cell.textContent || "");
    if (
      text.length < 180
      || !(/\[(?:10|12)[A-Za-z가-힣ⅠⅡ]/u.test(text) || cell.querySelectorAll("br").length >= 3)
    ) continue;
    cell.setAttribute("data-source-long-header-cell", "true");
    normalizedCount += 1;
  }
  return normalizedCount;
}

function sectionBody(
  document: Document,
  rows: HTMLTableRowElement[],
  placements: CellPlacement[],
  section: SectionRange,
) {
  const body = document.createElement("tbody");
  for (let rowIndex = section.start; rowIndex < section.end; rowIndex += 1) {
    const targetRow = rows[rowIndex].cloneNode(false) as HTMLTableRowElement;
    const startingCells = placements
      .filter((placement) => (
        Math.max(placement.rowStart, section.start) === rowIndex
        && placement.rowStart < section.end
        && placement.rowEnd > section.start
      ))
      .sort((left, right) => left.columnStart - right.columnStart);

    for (const placement of startingCells) {
      const cell = placement.cell.cloneNode(true) as HTMLTableCellElement;
      const visibleStart = Math.max(placement.rowStart, section.start);
      const visibleEnd = Math.min(placement.rowEnd, section.end);
      const visibleRowSpan = visibleEnd - visibleStart;
      if (visibleRowSpan > 1) cell.setAttribute("rowspan", String(visibleRowSpan));
      else cell.removeAttribute("rowspan");
      if (placement.rowStart < section.start) {
        cell.setAttribute("data-source-rowspan-continuation", "true");
      }
      targetRow.append(cell);
    }
    body.append(targetRow);
  }
  return body;
}

/**
 * Split only long source tables whose own row labels expose clear sections.
 * Cell text and rowspan/colspan values are preserved; this is a presentation
 * repair and never rewrites the archived source or invents a boundary.
 */
export function segmentSourceTables(value: string): SegmentedSourceHtml {
  if (typeof DOMParser === "undefined" || !value.trim()) {
    return {
      html: value,
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
  }

  const document = new DOMParser().parseFromString(value, "text/html");
  sanitizeDangerousMarkup(document);
  const flattenedNestedTableCount = flattenNestedTables(document);
  const removedEmptyTableCount = removeEmptyTables(document);
  const unwrappedHeadingTableCount = unwrapHeadingTables(document);
  const reconstructedCellCount = mergeSuffixContinuationTables(document);
  let gradeContinuationRowCount = mergeAchievementLevelContinuations(document);
  const mergedFragmentCount = mergeRepeatedHeaderTables(document);
  const orphanStandardGroupCount = groupOrphanAchievementStandards(document);
  const recoveredNoteGroupCount = groupShortDisplacedHeadings(document);
  const clampedRowspanCount = clampOverflowingRowspans(document);
  // Blank-row pruning runs after the page-break repairs above: those repairs
  // read blank placeholder rows as evidence of a split page.
  const prunedBlankRowCount = pruneBlankRows(document);
  let splitTableCount = 0;
  let sectionCount = 0;
  let headerSplitCount = 0;

  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    const rows = Array.from(table.rows);
    if (rows.length < 5) continue;
    const sections = sectionRanges(rows);
    if (sections.length < 2) continue;
    const placements = tableCellPlacements(rows);

    const wrapper = document.createElement("div");
    wrapper.className = "sourceTableSections";
    wrapper.setAttribute("role", "group");
    wrapper.setAttribute("aria-label", "원문 표 구획");

    let sectionElement: HTMLElement | null = null;
    let sectionKey: SectionKey | null = null;
    for (const [index, section] of sections.entries()) {
      const continuesPrevious = section.continues && sectionElement !== null && section.key === sectionKey;
      if (!continuesPrevious) {
        sectionElement = document.createElement("section");
        sectionElement.className = "sourceTableSection";
        const heading = document.createElement("h3");
        heading.textContent = SECTION_META[section.key].label;
        sectionElement.append(heading);
        wrapper.append(sectionElement);
        sectionKey = section.key;
        sectionCount += 1;
      } else {
        headerSplitCount += 1;
      }

      const scroll = document.createElement("div");
      scroll.className = "sourceTableScroll";
      const sectionTable = table.cloneNode(false) as HTMLTableElement;
      sectionTable.removeAttribute("id");
      sectionTable.setAttribute("aria-label", SECTION_META[section.key].label);
      if (section.continues) sectionTable.setAttribute("data-source-header-split", "true");
      sectionTable.append(sectionBody(document, rows, placements, section));
      scroll.append(sectionTable);
      sectionElement!.append(scroll);

      if (index === 0) {
        const caption = table.querySelector(":scope > caption");
        if (caption) sectionTable.prepend(caption.cloneNode(true));
      }
    }

    table.replaceWith(wrapper);
    splitTableCount += 1;
  }
  // Section splitting can expose a page-break continuation that was embedded
  // in one converter table. Repair that newly adjacent A-C / D-E pair too.
  gradeContinuationRowCount += mergeAchievementLevelContinuations(document);
  const prunedTrailingColumnCount = pruneTrailingBlankColumns(document);
  const normalizedLongHeaderCellCount = markLongHeaderCells(document);

  return {
    html: document.body.innerHTML,
    splitTableCount,
    sectionCount,
    mergedFragmentCount,
    reconstructedCellCount,
    orphanStandardGroupCount,
    recoveredNoteGroupCount,
    clampedRowspanCount,
    gradeContinuationRowCount,
    prunedTrailingColumnCount,
    normalizedLongHeaderCellCount,
    flattenedNestedTableCount,
    removedEmptyTableCount,
    prunedBlankRowCount,
    headerSplitCount,
    unwrappedHeadingTableCount,
  };
}
