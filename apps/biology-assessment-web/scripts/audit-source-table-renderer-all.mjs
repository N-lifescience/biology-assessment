#!/usr/bin/env node
// Regression gate for app/lib/source-table-segmentation.ts.
//
// The renderer rewrites converter-mangled source tables with DOM surgery
// (rowspan clamping, page-break merges, column pruning). A single row whose
// markup violates an assumption throws in the browser and blanks the detail
// page, so every published row is put through it here before a deploy.
//
// ponytail: no new dependency. Node 24 imports the .ts renderer directly
// (type stripping) and node:sqlite reads the publish DB; jsdom is already a
// devDependency and supplies the DOM the renderer expects.
//
// Usage:
//   node apps/biology-assessment-web/scripts/audit-source-table-renderer-all.mjs
//   ... --database <path> --limit <n> --self-check

import { DatabaseSync } from "node:sqlite";
import { inflateSync } from "node:zlib";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const SCRIPT_DIRECTORY = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(SCRIPT_DIRECTORY, "..", "..", "..");
const DEFAULT_DATABASE = resolve(
  PROJECT_ROOT,
  "data/publish/biology_assessment_catalog_detail.sqlite",
);
const SAMPLE_SIZE = 5;

function argument(name) {
  const index = process.argv.indexOf(`--${name}`);
  return index === -1 ? null : process.argv[index + 1];
}

// The renderer is browser code: give it a real DOM before importing it, or its
// `typeof DOMParser === "undefined"` guard would make every row trivially pass.
const window = new JSDOM("<!doctype html><body></body>").window;
for (const name of ["DOMParser", "HTMLTableElement", "HTMLTableCellElement", "Node"]) {
  globalThis[name] = window[name];
}
if (typeof globalThis.DOMParser === "undefined") {
  throw new Error("DOM setup failed: the renderer would no-op and pass every row");
}

const { segmentSourceTables } = await import("../app/lib/source-table-segmentation.ts");

/** Decompress one archived HTML blob and run it through the renderer. */
function auditItem(itemId, blob) {
  try {
    const html = inflateSync(blob).toString("utf8");
    const result = segmentSourceTables(html);
    if (typeof result?.html !== "string") {
      throw new TypeError(`renderer returned no html for ${itemId}`);
    }
    return null;
  } catch (error) {
    return { itemId, message: error instanceof Error ? error.message : String(error) };
  }
}

function auditDatabase(databasePath, limit) {
  const database = new DatabaseSync(databasePath, { readOnly: true });
  const failures = [];
  let audited = 0;
  try {
    const rows = database
      .prepare(
        "SELECT item_id, source_html_zlib FROM assessment_items "
          + "WHERE extraction_status = 'bounded' AND source_html_zlib IS NOT NULL "
          + "ORDER BY item_id",
      )
      .iterate();
    for (const row of rows) {
      const failure = auditItem(row.item_id, row.source_html_zlib);
      if (failure) failures.push(failure);
      audited += 1;
      if (limit && audited >= limit) break;
    }
  } finally {
    database.close();
  }
  return { audited, failures };
}

if (process.argv.includes("--self-check")) {
  const { deflateSync } = await import("node:zlib");
  const healthy = auditItem("healthy", deflateSync(Buffer.from(
    "<table><tr><th>평가영역명</th></tr><tr><td>탐구 보고서</td></tr></table>",
    "utf8",
  )));
  if (healthy) throw new Error(`a valid row was reported as failing: ${healthy.message}`);

  // A row the renderer cannot process must surface as a failure, never as a pass.
  const corrupt = auditItem("corrupt", Buffer.from("not a zlib stream", "utf8"));
  if (!corrupt) throw new Error("a corrupt payload passed the audit");

  console.log(`ok audit-source-table-renderer self-check (caught: ${corrupt.message})`);
  process.exit(0);
}

const databasePath = resolve(PROJECT_ROOT, argument("database") ?? DEFAULT_DATABASE);
if (!existsSync(databasePath)) {
  console.error(
    `source table renderer audit: ${databasePath} is missing.\n`
      + "Build the publish pipeline first (scripts/run_final_biology_assessment_pipeline.py), "
      + "then re-run this audit. Refusing to report a pass on zero rows.",
  );
  process.exit(1);
}

const limit = Number.parseInt(argument("limit") ?? "0", 10) || 0;
const { audited, failures } = auditDatabase(databasePath, limit);

if (!audited) {
  console.error(
    "source table renderer audit: no bounded rows with source_html_zlib were found. "
      + "The database is empty or the pipeline did not populate it.",
  );
  process.exit(1);
}

if (failures.length) {
  console.error(
    `source table renderer audit: ${failures.length} of ${audited} bounded item(s) threw.`,
  );
  for (const failure of failures.slice(0, SAMPLE_SIZE)) {
    console.error(`  ${failure.itemId}: ${failure.message}`);
  }
  process.exit(1);
}

console.log(`source table renderer audit ok: ${audited} bounded item(s) segmented cleanly`);
