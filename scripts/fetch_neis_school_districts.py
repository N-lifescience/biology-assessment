"""Pull NEIS 학교기본정보 and derive a school_code -> district(시군구) CSV.

``cases.district`` has no source in the collected schoolinfo data (saved_path
only encodes 시도, not 시군구), so this cross-references the public NEIS Open
API instead. district is parsed from the road address (ORG_RDNMA) second
whitespace-separated token, e.g. "서울특별시 송파구 송이로 42" -> "송파구".

Requires a free NEIS Open API key (open.neis.go.kr, email signup only, no
approval wait) in the ``NEIS_API_KEY`` env var -- unauthenticated requests are
capped at 5 rows/page, too slow for the ~12,700-school national roster.

Some schools (2026 전남·광주교육청 통합 predecessor codes) have no current
NEIS record; those simply get no district rather than a guessed one.
"""

from __future__ import annotations

import csv
import json
import os
import time
import urllib.request
from pathlib import Path

API_URL = "https://open.neis.go.kr/hub/schoolInfo"
PAGE_SIZE = 1000


def fetch_all(api_key: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    page = 1
    total = None
    while total is None or (page - 1) * PAGE_SIZE < total:
        url = f"{API_URL}?KEY={api_key}&Type=json&pIndex={page}&pSize={PAGE_SIZE}"
        with urllib.request.urlopen(url, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        block = payload["schoolInfo"]
        if total is None:
            total = block[0]["head"][0]["list_total_count"]
        for row in block[1]["row"]:
            road_addr = str(row.get("ORG_RDNMA") or "")
            parts = road_addr.split()
            rows.append(
                {
                    "school_code": str(row.get("SD_SCHUL_CODE") or ""),
                    "school_name": row.get("SCHUL_NM", ""),
                    "region_sido": row.get("LCTN_SC_NM", ""),
                    "region_sgg": parts[1] if len(parts) >= 2 else "",
                }
            )
        page += 1
        time.sleep(0.2)
    return rows


def main() -> None:
    api_key = os.environ.get("NEIS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("set NEIS_API_KEY (free key from open.neis.go.kr)")

    output = Path("data/derived/biology_assessment_school_district.csv")
    rows = fetch_all(api_key)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["school_code", "school_name", "region_sido", "region_sgg"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {output}")


if __name__ == "__main__":
    main()
