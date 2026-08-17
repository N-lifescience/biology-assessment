#!/usr/bin/env node
// ponytail: scanned a real `next build` output before writing this. Only .next/trace and
// .next/trace-build are both local-build-only and safe to delete, so that is the whole scope.
// What was checked and deliberately left alone:
//   - required-server-files.json/.js hold the build machine's absolute paths
//     (appDir, config.outputFileTracingRoot) but next-server reads them at runtime, and on
//     Vercel they are Vercel's paths, not a developer's. Rewriting them would break `next start`.
//   - prerender-manifest.json holds previewModeId/SigningKey/EncryptionKey. Real secrets, but
//     Next validates draft-mode cookies against them at runtime and Vercel regenerates them on
//     its own build, so this machine's keys never ship. Blanking them breaks draft mode.
//   - *.nft.json, BUILD_ID, routes-manifest.json, diagnostics/: scanned, no absolute paths,
//     no tokens. next.config.ts already sets poweredByHeader:false and
//     productionBrowserSourceMaps:false, so headers and source maps need nothing here.

import { rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
// Called as `next build && node ../../scripts/strip_next_protection_artifacts.mjs` from the
// web workspace, but stay usable from the repo root too.
const BUILD_DIRECTORY = [
  resolve(process.cwd(), ".next"),
  join(PROJECT_ROOT, "apps", "biology-assessment-web", ".next"),
].find((candidate) => {
  try {
    return statSync(candidate).isDirectory();
  } catch {
    return false;
  }
});

if (!BUILD_DIRECTORY) {
  console.error("strip: no .next build directory found. Run `next build` first.");
  process.exit(1);
}

// Build-time telemetry only: the server never reads these, and they describe this
// machine's build rather than the deployed app.
const LOCAL_BUILD_TRACES = ["trace", "trace-build"];

const removed = [];
for (const name of LOCAL_BUILD_TRACES) {
  const path = join(BUILD_DIRECTORY, name);
  let size;
  try {
    size = statSync(path).size;
  } catch {
    continue; // not every build emits both
  }
  rmSync(path, { recursive: true, force: true });
  removed.push(`${name} (${size} B)`);
}

console.log(
  removed.length
    ? `strip: removed local build traces from .next -- ${removed.join(", ")}`
    : "strip: no local build traces present in .next",
);
