"""Privacy-preserving public visit counters backed by a durable remote counter."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Final
from urllib.parse import quote
from urllib.request import Request, urlopen

COUNTER_BASE: Final = "https://counterapi.com/api"
COUNTER_NAMESPACE: Final = "suhaeng-biology.vercel.app"
COUNTER_ACTION: Final = "visit-20260813"
KOREA_TIMEZONE: Final = timezone(timedelta(hours=9))


def korea_date() -> str:
    return datetime.now(KOREA_TIMEZONE).strftime("%Y-%m-%d")


def _counter_value(key: str, *, increment: bool) -> int | None:
    # CounterAPI's `any` action is the documented aggregate/read-only path.
    # Its `readOnly=true` option returned a per-event value in server-side
    # calls, which made existing counters appear as zero to visitors.
    action = COUNTER_ACTION if increment else "any"
    path = "/".join(
        quote(part, safe="")
        for part in (COUNTER_NAMESPACE, action, key)
    )
    request = Request(
        f"{COUNTER_BASE}/{path}",
        headers={"Accept": "application/json", "User-Agent": "suhaeng-biology/0.3"},
    )
    try:
        with urlopen(request, timeout=4) as response:  # noqa: S310 - fixed HTTPS origin
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    value = payload.get("value") if isinstance(payload, dict) else None
    return value if isinstance(value, int) and value >= 0 else None


def _counter_state(key: str, *, increment: bool) -> tuple[int | None, bool]:
    """Optionally record a visit, then read the shared aggregate value.

    CounterAPI's increment response is scoped to the concrete action name,
    whereas the ``any`` action returns the aggregate across deployed action
    versions.  Returning the increment response directly made different
    server instances show different totals after a release.
    """

    increment_succeeded = False
    if increment:
        increment_succeeded = _counter_value(key, increment=True) is not None
    value = _counter_value(key, increment=False)
    return value, increment and increment_succeeded and value is not None


def visitor_counts(*, increment_today: bool, increment_total: bool) -> dict[str, object]:
    date = korea_date()
    with ThreadPoolExecutor(max_workers=2) as executor:
        today_future = executor.submit(
            _counter_state,
            f"day-{date.replace('-', '')}",
            increment=increment_today,
        )
        total_future = executor.submit(
            _counter_state,
            "total",
            increment=increment_total,
        )
        today, today_incremented = today_future.result()
        total, total_incremented = total_future.result()
    return {
        "date": date,
        "today": today,
        "total": total,
        "today_incremented": today_incremented,
        "total_incremented": total_incremented,
        "available": today is not None and total is not None,
    }
