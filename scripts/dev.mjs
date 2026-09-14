#!/usr/bin/env node
// Run the API (127.0.0.1:8010) and the Next.js web app (127.0.0.1:3100) together.
// Stops both when either exits or on Ctrl-C.
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const npm = process.platform === "win32" ? "npm.cmd" : "npm";

const api = spawn("node", [resolve(projectRoot, "scripts", "api.mjs")], { stdio: "inherit" });
const web = spawn(npm, ["run", "dev:web"], { cwd: projectRoot, stdio: "inherit" });

function stop(code) {
  for (const child of [api, web]) {
    if (child.exitCode === null) child.kill("SIGTERM");
  }
  process.exit(code);
}
api.on("exit", (code) => stop(code ?? 1));
web.on("exit", (code) => stop(code ?? 1));
process.on("SIGINT", () => stop(130));
process.on("SIGTERM", () => stop(143));
