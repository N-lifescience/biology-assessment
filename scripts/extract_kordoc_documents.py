"""Convert 학교알리미 평가계획 원문 to kordoc block structure (HWP·HWPX·PDF·Office·ZIP).

The previous extractors flattened tables into text before anything could read
them (Windows ``kordoc-fixed`` 2025 build, then pyhwp/pdfplumber on the Mac):
merged cells were collapsed into one cell ("A<br>B<br>C", "302826"), checked
boxes (□ overlaid with V) were lost, and some tables were escaped into text.
This stage keeps every table as a cell grid instead.  ``tools/kordoc/worker.mjs``
(kordoc pinned in ``tools/kordoc/package.json``) does the parsing; this driver
finds the files, unpacks ZIP members, feeds a pool of workers and writes

* ``<store>/<sha[:2]>/<sha>/doc.json`` – member list and status per document,
* ``<store>/<sha[:2]>/<sha>/<n>.json.gz`` – ``{kordoc, markdown, blocks}`` per member,
* ``--output`` JSONL – ``{sha256, source, extract_status, char_count, text}`` rows in
  the shape the evidence index and ``refresh_biology_assessment_details.py`` read
  (ZIP members are marked ``[zip:<name>][<status>]`` exactly like the old source).

Documents already in the store are not parsed again, so an interrupted run
resumes where it stopped.

Usage:
    python scripts/extract_kordoc_documents.py --from-db data/publish/biology_assessment_catalog_detail.sqlite \
        --output data/derived/kordoc_evidence_source.jsonl --workers 8
    python scripts/extract_kordoc_documents.py --manifest <manifest.csv> --output <jsonl> --workers 8
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import queue
import re
import select
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.extract_biology_candidate_text import curriculum_code_hints, subject_hits  # noqa: E402
from scripts.build_biology_assessment_evidence_index import mask_sensitive  # noqa: E402
from scripts.kordoc_flow import document_flow_text  # noqa: E402

WORKER = PROJECT_ROOT / "tools/kordoc/worker.mjs"
DEFAULT_STORE = PROJECT_ROOT / "data/derived/kordoc"
DRIVE_RAW_ROOT = PROJECT_ROOT / "data/drive/학교알리미_원문추출본/03_학교알리미_원문_4가/4ga"
LOCAL_RAW_ROOT = PROJECT_ROOT / "data/raw/schoolinfo/4ga"
SHORT_TEXT_CHARS = 200
JOB_TIMEOUT_SECONDS = 240
DOCUMENT_SUFFIXES = {".hwp", ".hwpx", ".pdf", ".docx", ".xlsx", ".xls", ".pptx", ".hwpml"}
SKIPPED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".txt", ".db", ".ini", ".lnk"}


# ------------------------------------------------------------- sources ---
def resolve_saved_path(saved_path: str) -> Path | None:
    """Manifest paths say ``data/raw/schoolinfo/4ga/…``; 1학기 files live in the drive copy."""

    if not saved_path:
        return None
    path = Path(saved_path)
    candidates = [path] if path.is_absolute() else [PROJECT_ROOT / path]
    marker = "data/raw/schoolinfo/4ga/"
    if marker in saved_path:
        tail = saved_path.split(marker, 1)[1]
        candidates += [DRIVE_RAW_ROOT / tail, LOCAL_RAW_ROOT / tail]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def index_by_sha_prefix(roots: list[Path]) -> dict[str, list[Path]]:
    """Raw files are saved as ``<school>_<sha256[:12]>_<name>``."""

    index: dict[str, list[Path]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            parts = path.name.split("_", 2)
            if len(parts) >= 3 and len(parts[1]) == 12:
                index.setdefault(parts[1], []).append(path)
    return index


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sources_from_db(database: Path) -> list[dict]:
    connection = sqlite3.connect(database)
    shas = [row[0] for row in connection.execute("SELECT DISTINCT source_sha256 FROM cases WHERE source_sha256 != ''")]
    connection.close()
    index = index_by_sha_prefix([DRIVE_RAW_ROOT, LOCAL_RAW_ROOT])
    sources = []
    for sha in shas:
        found = None
        for path in index.get(sha[:12], []):
            if sha256_of(path) == sha:
                found = path
                break
        sources.append({"sha256": sha, "path": str(found) if found else "", "source": {"saved_path": str(found or "")}})
    return sources


# A file whose name names only another department's plan ("수학과 교수학습 및
# 평가 운영 계획", "학업성적관리규정") cannot hold a biology-family plan.  School
# names, "교수학습" (contains 수학) and "정보공시" (contains 정보) are removed
# before matching; any science/biology/whole-school word keeps the file.
OTHER_DEPARTMENT_NAME_RE = re.compile(
    r"국어|수학|영어|사회|역사|한국사|도덕|윤리|지리|체육|음악|미술|예술|정보|기술|가정|외국어|"
    r"일본어|중국어|한문|독일어|프랑스어|스페인어|러시아어|아랍어|베트남어|진로|보건|교양|철학|"
    r"심리|논술|경제|정치|법과|문학|독서|화법|작문|물리|화학|지구과학|성적\s*관리|규정|방과후|"
    r"창체|창의적\s*체험|상업|예체능"
)
SCIENCE_NAME_RE = re.compile(
    r"과학|생명|세포\s*와\s*물질\s*대사|생물\s*의\s*유전|전\s*과목|전교과|모든\s*교과|공동\s*교육\s*과정|소인수"
)


def names_only_another_department(row: dict) -> bool:
    name = str(row.get("candidate_name") or "")
    school = str(row.get("school_name") or "")
    for spelling in (school, school.replace("등학교", ""), school.replace("고등학교", "고")):
        if spelling:
            name = name.replace(spelling, " ")
    name = re.sub(r"교수\s*[·ㆍ‧･・-]?\s*학습|정보\s*공시|공시용", " ", name)
    return not SCIENCE_NAME_RE.search(name) and bool(OTHER_DEPARTMENT_NAME_RE.search(name))


def sources_from_manifest(manifest: Path, skip_other_departments: bool = False) -> list[dict]:
    sources = []
    seen: set[str] = set()
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if skip_other_departments and names_only_another_department(row):
                continue
            path = resolve_saved_path(str(row.get("saved_path") or ""))
            key = str(path or row.get("saved_path") or "")
            if key in seen:
                continue
            seen.add(key)
            sources.append({"sha256": "", "path": str(path) if path else "", "source": dict(row)})
    return sources


# ---------------------------------------------------------------- zips ---
def sniff_suffix(name: str, data: bytes) -> str:
    suffix = Path(name).suffix.lower()
    if data.startswith(b"%PDF"):
        return ".pdf"
    if data.startswith(b"PK\x03\x04"):
        if suffix in (".hwpx", ".docx", ".xlsx", ".pptx", ".zip"):
            return suffix
        try:
            names = zipfile.ZipFile(__import__("io").BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return suffix
        if any(n.startswith("Contents/") for n in names):
            return ".hwpx"
        if any(n.startswith("word/") for n in names):
            return ".docx"
        if any(n.startswith("xl/") for n in names):
            return ".xlsx"
        return ".zip"
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        return suffix if suffix in (".xls", ".doc", ".ppt") else ".hwp"
    return suffix


def open_zip(path_or_bytes) -> zipfile.ZipFile:
    """Korean archives store member names in CP949 without the UTF-8 flag."""

    try:
        return zipfile.ZipFile(path_or_bytes, metadata_encoding="cp949")
    except (UnicodeDecodeError, ValueError):
        if hasattr(path_or_bytes, "seek"):
            path_or_bytes.seek(0)
        return zipfile.ZipFile(path_or_bytes)


def unpack_members(path: Path, workdir: Path, depth: int = 0, prefix: str = "") -> list[dict]:
    """Write each document member of a ZIP to ``workdir``; nested ZIPs are flattened."""

    import io

    members: list[dict] = []
    try:
        archive = open_zip(path if isinstance(path, Path) else io.BytesIO(path))
    except zipfile.BadZipFile as exc:
        return [{"name": prefix or "archive", "status": "failed", "error": f"BadZipFile: {exc}"}]
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename
            base = Path(name).name
            if name.startswith("__MACOSX") or base.startswith(".") or base.startswith("~$"):
                continue
            data = archive.read(info)
            suffix = sniff_suffix(base, data)
            shown = f"{prefix}{base}"
            if suffix == ".zip":
                if depth < 2:
                    members.extend(unpack_members(data, workdir, depth + 1, prefix=f"{shown}/"))
                continue
            if suffix in SKIPPED_SUFFIXES or suffix not in DOCUMENT_SUFFIXES:
                members.append({"name": shown, "status": "skipped", "error": f"unsupported {suffix or 'type'}"})
                continue
            target = workdir / f"m{len(list(workdir.iterdir())):03d}{suffix}"
            target.write_bytes(data)
            members.append({"name": shown, "file": str(target), "status": "pending"})
    return members


# -------------------------------------------------------------- workers ---
class Worker:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.start()

    def start(self) -> None:
        self.process = subprocess.Popen(
            ["node", str(WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            cwd=str(WORKER.parent),
        )

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait()

    def run(self, job: dict) -> dict:
        assert self.process and self.process.stdin and self.process.stdout
        if self.process.poll() is not None:
            self.start()
        self.process.stdin.write(json.dumps(job, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        ready, _, _ = select.select([self.process.stdout], [], [], JOB_TIMEOUT_SECONDS)
        if not ready:
            self.stop()
            self.start()
            return {"id": job["id"], "ok": False, "error": f"timeout {JOB_TIMEOUT_SECONDS}s", "code": "TIMEOUT"}
        line = self.process.stdout.readline()
        if not line:
            self.stop()
            self.start()
            return {"id": job["id"], "ok": False, "error": "worker exited", "code": "CRASH"}
        return json.loads(line)


@dataclass
class Document:
    sha256: str
    path: Path
    source: dict
    format: str = ""
    members: list[dict] = field(default_factory=list)


def doc_dir(store: Path, sha: str) -> Path:
    return store / sha[:2] / sha


def convert_document(document: Document, store: Path, worker: Worker, version: str) -> dict:
    target = doc_dir(store, document.sha256)
    target.mkdir(parents=True, exist_ok=True)
    suffix = sniff_suffix(document.path.name, document.path.read_bytes()[:8192])
    document.format = suffix.lstrip(".")
    workdir = Path(tempfile.mkdtemp(prefix="kordoc-"))
    try:
        if suffix == ".zip":
            members = unpack_members(document.path, workdir)
        else:
            members = [{"name": document.path.name, "file": str(document.path), "status": "pending"}]
        for index, member in enumerate(members):
            member["index"] = index
            if member["status"] != "pending":
                continue
            reply = worker.run({"id": f"{document.sha256}:{index}", "path": member["file"], "out": str(target / f"{index}.json.gz")})
            if reply.get("ok"):
                chars = int(reply.get("chars") or 0)
                member.update(status="ok" if chars >= SHORT_TEXT_CHARS else "short", chars=chars,
                              pages=reply.get("pages"), warnings=reply.get("warnings") or [], ms=reply.get("ms"))
            else:
                member.update(status="failed", error=f"{reply.get('code', '')} {reply.get('error', '')}".strip())
            member.pop("file", None)
        for member in members:
            member.pop("file", None)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    record = {"sha256": document.sha256, "name": document.path.name, "format": document.format,
              "kordoc": version, "members": members}
    (target / "doc.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return record


def _legacy_member_body(legacy: str, name: str) -> str:
    """One ZIP member's text from the archived extraction (``[zip:<name>][…]`` markers)."""

    marker = f"[zip:{name}]"
    start = legacy.find(marker)
    if start < 0:
        return ""
    end = legacy.find("\n[zip:", start + len(marker))
    chunk = legacy[start: end if end >= 0 else len(legacy)]
    return chunk.split("\n", 1)[1].strip() if "\n" in chunk else ""


def document_text(record: dict, store: Path, legacy_text=None) -> tuple[str, str]:
    """Flattened parser input (``kordoc_flow``), not kordoc's own Markdown: frame tables unwrapped.

    ``legacy_text(sha)`` may supply the archived 2025 extraction for the few
    files kordoc cannot open (배포용 암호화 HWPX, a PDF that crashes it): a whole
    failed document takes the legacy text, a failed ZIP member its own chunk.
    """

    members = record.get("members") or []
    statuses = [m.get("status") for m in members]
    text = document_flow_text(record, store)
    # A scanned or partly unreadable file can come back "short" with no text at
    # all (a 245-page PDF with only PARTIAL_PARSE warnings); treat it as failed.
    failed = [m for m in members if m.get("status") == "failed"
              or (m.get("status") == "short" and not m.get("chars"))]
    if failed and legacy_text is not None:
        legacy = legacy_text(str(record.get("sha256") or ""))
        if legacy and record.get("format") != "zip" and len(legacy) > len(text):
            text, statuses = legacy, ["legacy"]
        elif legacy:
            for member in failed:
                body = _legacy_member_body(legacy, member["name"])
                if body:
                    text = text.replace(f"[zip:{member['name']}][{member.get('status')}]",
                                        f"[zip:{member['name']}][legacy]\n{body}", 1)
                    statuses = [*statuses, "legacy"]
    # Contact and ID strings are masked here, not only in the evidence index,
    # because the detail refresh reads this text directly.
    text = mask_sensitive(text)
    if not members or all(s in ("failed", "skipped") for s in statuses):
        status = "failed"
    else:
        status = "ok" if len(text) >= SHORT_TEXT_CHARS else "short"
    return status, text


def kordoc_version() -> str:
    package = json.loads((WORKER.parent / "package.json").read_text(encoding="utf-8"))
    return str(package["dependencies"]["kordoc"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-db", type=Path, help="convert every source document of this publish DB")
    group.add_argument("--manifest", type=Path, help="convert every saved_path of this source manifest")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--output", type=Path, required=True, help="evidence-source JSONL to write")
    parser.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) - 2))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true", help="re-parse documents already in the store")
    parser.add_argument("--legacy-fallback", action="store_true",
                        help="fill documents kordoc cannot open from the archived 2025 extraction")
    parser.add_argument("--skip-other-departments", action="store_true",
                        help="manifest mode: skip files named for another department only")
    args = parser.parse_args()

    if not (WORKER.parent / "node_modules/kordoc").is_dir():
        raise SystemExit("kordoc is not installed: run `npm ci` in tools/kordoc")
    version = kordoc_version()
    sources = (sources_from_db(args.from_db) if args.from_db
               else sources_from_manifest(args.manifest, args.skip_other_departments))
    if args.limit:
        sources = sources[: args.limit]

    documents: list[Document] = []
    missing: list[dict] = []
    for item in sources:
        if not item["path"]:
            missing.append(item)
            continue
        path = Path(item["path"])
        documents.append(Document(item["sha256"] or sha256_of(path), path, item["source"]))

    jobs: queue.Queue[Document] = queue.Queue()
    for document in documents:
        existing = doc_dir(args.store, document.sha256) / "doc.json"
        if args.force or not existing.is_file() or json.loads(existing.read_text("utf-8")).get("kordoc") != version:
            jobs.put(document)
    todo = jobs.qsize()
    done = [0]
    lock = threading.Lock()
    started = time.time()

    def run() -> None:
        worker = Worker()
        try:
            while True:
                try:
                    document = jobs.get_nowait()
                except queue.Empty:
                    return
                try:
                    convert_document(document, args.store, worker, version)
                except Exception as exc:  # noqa: BLE001 - one broken file must not stop the run
                    record = {"sha256": document.sha256, "name": document.path.name, "format": "",
                              "kordoc": version, "members": [{"index": 0, "name": document.path.name,
                                                              "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]}]}
                    target = doc_dir(args.store, document.sha256)
                    target.mkdir(parents=True, exist_ok=True)
                    (target / "doc.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
                with lock:
                    done[0] += 1
                    if done[0] % 100 == 0 or done[0] == todo:
                        rate = done[0] / max(1.0, time.time() - started)
                        print(f"progress {done[0]}/{todo} ({rate:.1f} docs/s)", flush=True)
        finally:
            worker.stop()

    threads = [threading.Thread(target=run, daemon=True) for _ in range(max(1, args.workers))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    legacy_text = None
    if args.legacy_fallback:
        from scripts.case_text import text_for_sha as legacy_text  # 6GB archive via offset index
    statuses: dict[str, int] = {}
    member_statuses: dict[str, int] = {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        for document in documents:
            record = json.loads((doc_dir(args.store, document.sha256) / "doc.json").read_text("utf-8"))
            status, text = document_text(record, args.store, legacy_text)
            statuses[status] = statuses.get(status, 0) + 1
            for member in record.get("members") or []:
                member_statuses[member.get("status", "")] = member_statuses.get(member.get("status", ""), 0) + 1
            # Same row shape as extract_biology_candidate_text.py, which the
            # evidence index reads (subject_hits, curriculum_code_hints).
            row = {"sha256": document.sha256, "source": document.source, "extract_status": status,
                   "extractor": f"kordoc {version}", "char_count": len(text),
                   "subject_hits": subject_hits(text), "curriculum_code_hints": curriculum_code_hints(text),
                   "text": text}
            out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"documents": len(documents), "converted_now": todo, "missing_files": len(missing),
                      "document_status": statuses, "member_status": member_statuses}, ensure_ascii=False))
    if missing:
        print(json.dumps({"missing_examples": missing[:5]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
