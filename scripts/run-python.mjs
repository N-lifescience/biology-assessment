#!/usr/bin/env node
// Cross-platform python launcher for the package.json scripts.
// Every argument is forwarded verbatim, so both call shapes work unchanged:
//   node scripts/run-python.mjs -m pytest
//   node scripts/run-python.mjs scripts/audit_....py --database ...
// ponytail: no argument parsing, no venv creation -- pick an interpreter, exec, mirror the exit code.

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const isWindows = process.platform === "win32";

function venvPython(root) {
  const candidate = isWindows
    ? join(root, ".venv", "Scripts", "python.exe")
    : join(root, ".venv", "bin", "python");
  return existsSync(candidate) ? candidate : null;
}

function interpreters() {
  const explicit = process.env.PYTHON?.trim();
  const found = [];
  if (explicit) found.push(explicit);
  // A project virtualenv holds the pinned requirements, so it wins over PATH.
  const venv = venvPython(projectRoot);
  if (venv) found.push(venv);
  // "py" first on Windows: a bare "python" on PATH is often the Microsoft Store
  // stub, which exists but exits 9009 without running anything.
  found.push(...(isWindows ? ["py", "python", "python3"] : ["python3", "python"]));
  return found;
}

function usable(python) {
  const probe = spawnSync(python, ["-c", "import sys; sys.exit(0)"], { stdio: "ignore" });
  return !probe.error && probe.status === 0;
}

const args = process.argv.slice(2);
if (!args.length) {
  console.error("usage: node scripts/run-python.mjs <python arguments...>");
  process.exit(2);
}

for (const python of interpreters()) {
  if (!usable(python)) continue;
  const result = spawnSync(python, args, {
    stdio: "inherit",
    cwd: projectRoot,
    // pyproject.toml sets pythonpath for pytest only. Direct script runs need the
    // project root (for "from scripts.x import ...") and scripts/ (for bare sibling
    // imports) on the path as well.
    env: {
      ...process.env,
      PYTHONPATH: [projectRoot, join(projectRoot, "scripts"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(isWindows ? ";" : ":"),
      PYTHONIOENCODING: process.env.PYTHONIOENCODING ?? "utf-8",
    },
  });
  if (result.error) throw result.error;
  process.exit(result.status ?? 1);
}

console.error(
  `no python interpreter found (tried: ${interpreters().join(", ")}). ` +
    "Install Python 3.12+ or set the PYTHON environment variable.",
);
process.exit(127);
