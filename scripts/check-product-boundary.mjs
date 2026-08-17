#!/usr/bin/env node
// AGENTS.md: "원본은 docs/reference-math/에 읽기 전용으로 두고 수정하지 않으며,
// 수학 산출물과 결과를 섞지 않는다."
//
// ponytail: the only statically checkable half of that rule. docs/reference-math/ is
// gitignored, so a git-diff based "did anyone touch the reference copy" check can never
// see anything -- but product code reaching into it (import/require/fetch/open) is a
// plain text reference and greppable. That, and only that, is what this enforces.
//
// Usage: node scripts/check-product-boundary.mjs [--self-check]

import {
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const SELF = fileURLToPath(import.meta.url);
const PROJECT_ROOT = resolve(dirname(SELF), "..");
// Product code only. docs/ is where the read-only reference is allowed to be named.
const PRODUCT_ROOTS = ["apps", "services", "scripts"];
const SKIPPED_DIRECTORIES = new Set([
  "node_modules",
  ".next",
  ".git",
  ".venv",
  "data",
  "__pycache__",
  "dist",
  "build",
  "coverage",
]);
const SCANNED_EXTENSIONS = /\.(?:ts|tsx|js|jsx|mjs|cjs|py|json|ya?ml|toml|css|scss|html)$/i;
const REFERENCE_MATH = /reference[-_]math/i;

function* sourceFiles(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      if (SKIPPED_DIRECTORIES.has(entry.name)) continue;
      yield* sourceFiles(path);
    } else if (entry.isFile() && SCANNED_EXTENSIONS.test(entry.name)) {
      yield path;
    }
  }
}

/** @returns {{file: string, line: number, text: string}[]} */
export function findMathReferences(root, productRoots = PRODUCT_ROOTS) {
  const violations = [];
  for (const productRoot of productRoots) {
    let files;
    try {
      files = [...sourceFiles(join(root, productRoot))];
    } catch (error) {
      if (error.code === "ENOENT") continue;
      throw error;
    }
    for (const file of files) {
      if (resolve(file) === SELF) continue; // this checker names the path it forbids
      const lines = readFileSync(file, "utf8").split(/\r?\n/);
      for (const [index, text] of lines.entries()) {
        if (REFERENCE_MATH.test(text)) {
          violations.push({
            file: relative(root, file).split(sep).join("/"),
            line: index + 1,
            text: text.trim().slice(0, 160),
          });
        }
      }
    }
  }
  return violations;
}

function selfCheck() {
  const sandbox = mkdtempSync(join(tmpdir(), "product-boundary-"));
  try {
    const nested = join(sandbox, "apps", "web");
    mkdirSync(nested, { recursive: true });
    writeFileSync(join(nested, "clean.ts"), "export const ok = 1;\n");
    if (findMathReferences(sandbox).length !== 0) throw new Error("clean tree flagged");
    writeFileSync(
      join(nested, "leak.ts"),
      'import data from "../../docs/reference-math/topics.json";\n',
    );
    const hits = findMathReferences(sandbox);
    if (hits.length !== 1 || hits[0].line !== 1 || !hits[0].file.endsWith("leak.ts")) {
      throw new Error(`leak not detected: ${JSON.stringify(hits)}`);
    }
    console.log("ok check-product-boundary self-check");
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
}

if (process.argv.includes("--self-check")) {
  selfCheck();
  process.exit(0);
}

const violations = findMathReferences(PROJECT_ROOT);
if (violations.length) {
  console.error(
    `product boundary: ${violations.length} reference(s) to the read-only math archive ` +
      "(docs/reference-math/) found in product code. Move the data into this project instead.",
  );
  for (const { file, line, text } of violations) console.error(`  ${file}:${line}: ${text}`);
  process.exit(1);
}
console.log(
  `product boundary ok: no docs/reference-math reference in ${PRODUCT_ROOTS.join(", ")}`,
);
