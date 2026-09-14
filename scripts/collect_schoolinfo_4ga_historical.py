"""Download 학교알리미 4-가 (교과별 교수·학습 및 평가계획) attachments for one disclosure round.

학교알리미 publishes 4-가 four times a year; the first-semester plans arrive
in 정시 1차 (April, ``JG_CHASU=1``) and the second-semester plans in 정시 3차
(September, ``JG_CHASU=3``).  The item page keeps every round in its
``select_trans_dt`` selector as ``<year><chasu>`` (``20263`` = 2026 3차), and
switching rounds is a plain re-POST of the same form with ``JG_YEAR``/
``JG_CHASU`` changed, which is what this script does per school.

Request flow (verified 2026-09-14):
  1. GET  /ei/ss/pneiss_a03_s0.do                      -- session cookie
  2. POST /ei/ss/pneiss_a04_s0/getSchoolList.do        -- SHL_IDF_CD by name
  3. POST /ei/ss/pneiss_a03_s0_hangmok_json.do         -- item codes for 4-가
  4. POST /ei/pp/Pneipp_b43_s0p.do  (+JG_CHASU)        -- attachment list
  5. GET  /servlets/EiFileDownLoad.do?...&FILE_SEQ=n   -- each attachment
A direct GET of step 4 returns the site's "서비스 일시 중단" page; that is a
missing-parameter response, not an outage.

Usage:
  python scripts/collect_schoolinfo_4ga_historical.py --check-only \\
      --school 천안쌍용고등학교 --year 2026 --chasu 3
  python scripts/collect_schoolinfo_4ga_historical.py --schools data/derived/schoolinfo_schools.csv \\
      --year 2026 --chasu 3 --output-root data/raw/schoolinfo \\
      --log data/derived/schoolinfo_4ga_download_log_2026_3.csv

The log CSV feeds ``build_biology_assessment_manifest.py --log``.  Reruns skip
files already on disk (same SHA-256 prefix in the stored name) and merge the
log, so an interrupted run can simply be started again.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENDOR = PROJECT_ROOT / "scripts" / "schoolinfo_vendor"
sys.path.insert(0, str(VENDOR))

from pilot_2ga_http import (  # noqa: E402
    HANGMOK_URL,
    ItemRequest,
    download,
    fetch_item_html,
    opener,
    params_from_item,
    post_with_retry,
    resolve_shl_idf,
)
from schoolinfo_2ga_request_audit import (  # noqa: E402
    classify_download_payload,
    classify_response_html,
    html_title,
)
from schoolinfo_documents_core import (  # noqa: E402
    BASE_URL,
    School,
    clean_html_text,
    parse_attachments,
)

ITEM_NO = "4-가"
ITEM_NAME = "교과별(학년별) 교수ㆍ학습 및 평가계획에 관한 사항"
ITEM_SLUG = "4ga"
FILE_ANCHOR_RE = re.compile(r"<a[^>]+class=[\"'][^\"']*file_name[^\"']*[\"'][^>]*>.*?</a>", re.I | re.S)
FILE_SEQ_RE = re.compile(r"getEiFile\d+\('([^']+)'\)")
ROUND_OPTION_RE = re.compile(r"<option\s+value=[\"'](\d{5})[\"']", re.I)
SIZE_SUFFIX_RE = re.compile(r"\([0-9,]+\s*KB\)\s*$")


@dataclass(frozen=True, slots=True)
class DownloadLog:
    item_no: str
    item_name: str
    year: str
    chasu: str
    school_code: str
    school_name: str
    region: str
    district: str
    file_seq: str
    candidate_name: str
    result: str
    status_detail: str
    saved_path: str
    content_type: str
    size_bytes: int
    source_url: str
    final_url: str
    failure_reason: str
    collected_at: str


LOG_FIELDS = tuple(DownloadLog.__dataclass_fields__)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value).strip("_")[:140] or "schoolinfo_attachment"


def load_schools(path: Path, wanted: set[str]) -> list[School]:
    schools: list[School] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = str(row.get("school_name") or "").strip()
            if not name or (wanted and name not in wanted):
                continue
            schools.append(School(
                school_id=str(row.get("school_id") or row.get("school_code") or ""),
                school_name=name,
                region_sido=str(row.get("region_sido") or row.get("region") or ""),
                region_sgg=str(row.get("region_sgg") or row.get("district") or ""),
                school_code=str(row.get("school_code") or ""),
                neis_school_code=str(row.get("neis_school_code") or ""),
                education_office_code=str(row.get("education_office_code") or ""),
            ))
    return schools


def item_request(browser, shl_idf_cd: str, year: int, chasu: int) -> ItemRequest | str:
    try:
        result = post_with_retry(browser, HANGMOK_URL, {"SHL_IDF_CD": shl_idf_cd}, 10)
        payload = json.loads(result.body)
    except (TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return f"hangmok_json_failed: {type(exc).__name__}: {exc}"
    matches = [row for row in payload if isinstance(row, dict) and row.get("GS_HANGMOK_NO") == ITEM_NO]
    if len(matches) != 1:
        return f"hangmok_json_missing_item: {ITEM_NO}"
    found = matches[0]
    params = params_from_item(found, str(year), shl_idf_cd)
    params["JG_CHASU"] = str(chasu)
    return ItemRequest(str(found.get("GS_URL") or "/ei/pp/Pneipp_b43_s0p.do"), params)


def round_options(item_html: str) -> list[str]:
    return ROUND_OPTION_RE.findall(item_html)


def original_file_names(item_html: str) -> dict[str, str]:
    names: dict[str, str] = {}
    for anchor in FILE_ANCHOR_RE.findall(item_html):
        match = FILE_SEQ_RE.search(anchor)
        if match is None:
            continue
        label = clean_html_text(anchor)
        names[match.group(1)] = html.unescape(SIZE_SUFFIX_RE.sub("", label).strip())
    return names


def named_attachments(item_html: str, request: ItemRequest):
    names = original_file_names(item_html)
    ordered = tuple(names.items())
    rows = []
    for index, item in enumerate(parse_attachments(item_html, request.params)):
        fallback_seq, fallback_name = ordered[index] if index < len(ordered) else (item.file_seq, item.filename)
        file_seq = item.file_seq or fallback_seq
        rows.append((file_seq, names.get(file_seq, fallback_name), item.download_url))
    return rows


def store_payload(root: Path, school: School, file_name: str, body: bytes) -> tuple[str, Path, bool]:
    digest = hashlib.sha256(body).hexdigest()
    suffix = Path(file_name).suffix or ".bin"
    target_dir = root / ITEM_SLUG / school.region_sido / school.school_name
    existing = sorted(target_dir.glob(f"{school.school_code}_{digest[:12]}_*"))
    if existing:
        return digest, existing[0], False
    target = target_dir / f"{school.school_code}_{digest[:12]}_{safe_name(Path(file_name).stem)}{suffix}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return digest, target, True


def log_row(school: School, year: int, chasu: int, **values) -> DownloadLog:
    base = {
        "item_no": ITEM_NO, "item_name": ITEM_NAME, "year": str(year), "chasu": str(chasu),
        "school_code": school.school_code, "school_name": school.school_name,
        "region": school.region_sido, "district": school.region_sgg,
        "file_seq": "", "candidate_name": "", "result": "failed", "status_detail": "",
        "saved_path": "", "content_type": "", "size_bytes": 0, "source_url": "",
        "final_url": "", "failure_reason": "", "collected_at": now_iso(),
    }
    base.update(values)
    return DownloadLog(**base)


def collect_school(browser, school: School, year: int, chasu: int, root: Path,
                   check_only: bool) -> tuple[list[DownloadLog], dict]:
    shl_idf_cd, lookup_error = resolve_shl_idf(browser, school)
    source_url = f"{BASE_URL}/ei/pp/Pneipp_b43_s0p.do?SHL_IDF_CD={shl_idf_cd}"
    if lookup_error:
        return [log_row(school, year, chasu, source_url=source_url, failure_reason=lookup_error)], {}
    request = item_request(browser, shl_idf_cd, year, chasu)
    if isinstance(request, str):
        return [log_row(school, year, chasu, source_url=source_url, failure_reason=request)], {}
    # The round selector is only rendered on the school's current-round page;
    # a POST for a round that does not exist yet comes back without it (and
    # without attachments), so read the selector first and then switch rounds.
    default_request = ItemRequest(
        request.path, {k: v for k, v in request.params.items() if k != "JG_CHASU"}
    )
    try:
        page = fetch_item_html(browser, default_request)
        options = round_options(page.body)
        wanted = f"{year}{chasu}"
        if wanted in options:
            page = fetch_item_html(browser, request)
    except (TimeoutError, urllib.error.URLError) as exc:
        reason = f"item_fetch_failed: {type(exc).__name__}: {exc}"
        return [log_row(school, year, chasu, source_url=source_url, failure_reason=reason)], {}
    probe = {"school": school.school_name, "rounds": options, "wanted": wanted}
    if wanted not in options:
        row = log_row(school, year, chasu, source_url=source_url, result="missing",
                      failure_reason=f"round_not_published: available={','.join(options)}")
        return [row], probe
    attachments = named_attachments(page.body, request)
    probe["attachments"] = [name for _, name, _ in attachments]
    if check_only:
        return [], probe
    if not attachments:
        classification = classify_response_html(int(page.status_code or "0"), page.body)
        reason = classification.error_pattern or f"no_attachment: {html_title(page.body)}"
        return [log_row(school, year, chasu, source_url=source_url, result="missing",
                        failure_reason=reason)], probe
    rows = []
    for file_seq, file_name, download_url in attachments:
        try:
            result = download(browser, download_url)
        except (TimeoutError, urllib.error.URLError) as exc:
            rows.append(log_row(school, year, chasu, file_seq=file_seq, candidate_name=file_name,
                                source_url=source_url, final_url=download_url,
                                failure_reason=f"download_failed: {type(exc).__name__}: {exc}"))
            continue
        validation = classify_download_payload(result.body, result.content_type)
        if not validation.is_valid:
            rows.append(log_row(school, year, chasu, file_seq=file_seq, candidate_name=file_name,
                                source_url=source_url, final_url=download_url,
                                failure_reason=f"download_validation_failed: {validation.reason}"))
            continue
        _digest, target, _new = store_payload(root, school, file_name, result.body)
        rows.append(log_row(
            school, year, chasu, file_seq=file_seq, candidate_name=file_name, result="downloaded",
            status_detail=validation.detected_type, saved_path=target.relative_to(PROJECT_ROOT).as_posix()
            if target.is_relative_to(PROJECT_ROOT) else str(target),
            content_type=result.content_type, size_bytes=len(result.body),
            source_url=source_url, final_url=download_url,
        ))
    return rows, probe


def write_log(path: Path, rows: list[DownloadLog]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[tuple[str, str, str, str, str], dict] = {}
    if path.is_file():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                normalized = {field: row.get(field, "") for field in LOG_FIELDS}
                key = (normalized["year"], normalized["chasu"], normalized["school_code"],
                       normalized["file_seq"], normalized["candidate_name"])
                merged[key] = normalized
    for row in rows:
        merged[(row.year, row.chasu, row.school_code, row.file_seq, row.candidate_name)] = asdict(row)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        writer.writeheader()
        writer.writerows(merged[key] for key in sorted(merged))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--schools", type=Path, default=PROJECT_ROOT / "data/derived/schoolinfo_schools.csv")
    parser.add_argument("--school", action="append", default=[], help="restrict to these names")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--chasu", type=int, default=3, help="1=1차(4월, 1학기) 3=3차(9월, 2학기)")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data/raw/schoolinfo")
    parser.add_argument("--log", type=Path, default=None)
    parser.add_argument("--sleep-seconds", type=float, default=0.8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--check-only", action="store_true",
                        help="only report whether the round is published (no downloads)")
    args = parser.parse_args()

    wanted = set(args.school)
    if wanted and not args.schools.is_file():
        schools = [School("", name, "", "", "", "", "") for name in sorted(wanted)]
    else:
        schools = load_schools(args.schools, wanted)
    if args.limit:
        schools = schools[: args.limit]
    if not schools:
        raise SystemExit("no schools selected")
    log_path = args.log or (
        PROJECT_ROOT / "data/derived" / f"schoolinfo_4ga_download_log_{args.year}_{args.chasu}.csv"
    )
    browser = opener()
    rows: list[DownloadLog] = []
    probes: list[dict] = []
    for index, school in enumerate(schools, 1):
        school_rows, probe = collect_school(
            browser, school, args.year, args.chasu, args.output_root, args.check_only
        )
        rows.extend(school_rows)
        if probe:
            probes.append(probe)
        if index % 25 == 0 and not args.check_only:
            write_log(log_path, rows)
            print(f"progress {index}/{len(schools)} rows={len(rows)}", flush=True)
        time.sleep(args.sleep_seconds)
    if args.check_only:
        published = [p for p in probes if p.get("wanted") in p.get("rounds", [])]
        print(json.dumps({
            "year": args.year, "chasu": args.chasu, "checked": len(probes),
            "published_for": len(published), "probes": probes,
        }, ensure_ascii=False, indent=2))
        return 0 if published else 2
    write_log(log_path, rows)
    downloaded = sum(1 for row in rows if row.result == "downloaded")
    missing = sum(1 for row in rows if row.result == "missing")
    print(json.dumps({
        "schools": len(schools), "rows": len(rows), "downloaded": downloaded,
        "missing": missing, "failed": len(rows) - downloaded - missing, "log": str(log_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
