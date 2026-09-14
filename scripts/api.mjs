#!/usr/bin/env node
// Start the FastAPI catalogue API on 127.0.0.1:8010 with the project interpreter.
// ponytail: same interpreter choice as run-python.mjs, no extra options.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const venv = process.platform === "win32"
  ? join(projectRoot, ".venv", "Scripts", "python.exe")
  : join(projectRoot, ".venv", "bin", "python");
const python = process.env.PYTHON?.trim() || (existsSync(venv) ? venv : "python3");
const port = process.env.API_PORT || "8010";

const child = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port, ...process.argv.slice(2)],
  { cwd: join(projectRoot, "services", "biology-assessment-api"), stdio: "inherit" },
);
child.on("exit", (code) => process.exit(code ?? 1));
