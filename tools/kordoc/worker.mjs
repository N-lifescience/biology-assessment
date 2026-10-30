// kordoc 상주 작업자.
//
// 표준입력으로 한 줄에 하나씩 {"id", "path", "out"} 를 받아 원문을 kordoc 로 읽고,
// {markdown, blocks} 를 gzip JSON 으로 `out` 에 쓴 뒤 표준출력에 결과 한 줄을 낸다.
// scripts/extract_kordoc_documents.py 가 이 작업자 여러 개를 띄워 일을 나눠 준다.
//
// blocks 는 표를 셀 격자(rowSpan·colSpan·셀 안 중첩 블록)로 그대로 담는다. 표 해석은
// 이 격자를 기준으로 하고, markdown 은 검색·근거 색인용으로만 쓴다.
import { parse, VERSION } from "kordoc";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { createInterface } from "node:readline";
import { gzipSync } from "node:zlib";

// 그림 바이트·좌표·글꼴은 표 해석에 쓰지 않으므로 버려 저장 크기를 줄인다.
const DROPPED_KEYS = new Set(["imageData", "bbox", "style", "spans", "regions", "indent"]);

function slim(key, value) {
  return DROPPED_KEYS.has(key) ? undefined : value;
}

async function handle(job) {
  const started = Date.now();
  const data = readFileSync(job.path);
  const result = await parse(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength), {
    filePath: job.path,
    ocr: false,
    // 표마다 의미표/틀(레이아웃) 판정을 붙인다. 문서 전체를 감싼 틀 표를 풀 때 쓴다.
    classifyTables: true,
  });
  if (!result.success) {
    return { id: job.id, ok: false, ms: Date.now() - started, error: String(result.error || ""), code: result.code || "" };
  }
  const payload = JSON.stringify({ kordoc: VERSION, markdown: result.markdown, blocks: result.blocks }, slim);
  mkdirSync(dirname(job.out), { recursive: true });
  writeFileSync(job.out, gzipSync(Buffer.from(payload, "utf8")));
  return {
    id: job.id,
    ok: true,
    ms: Date.now() - started,
    chars: result.markdown.length,
    pages: result.metadata?.pageCount ?? null,
    warnings: (result.warnings || []).map((w) => w.code || "").filter(Boolean),
  };
}

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  if (!line.trim()) continue;
  let job;
  try {
    job = JSON.parse(line);
  } catch {
    continue;
  }
  let reply;
  try {
    reply = await handle(job);
  } catch (error) {
    reply = { id: job.id, ok: false, error: String(error?.message || error).slice(0, 300), code: "EXCEPTION" };
  }
  process.stdout.write(JSON.stringify(reply) + "\n");
}
