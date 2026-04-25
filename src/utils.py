from __future__ import annotations

from datetime import datetime, timezone


def now_utc_ts() -> float:
    return datetime.now(tz=timezone.utc).timestamp()


def fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def position_key(market_slug: str, outcome: str) -> str:
    return f"{market_slug}:{outcome.lower()}"
