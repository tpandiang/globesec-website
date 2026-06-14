"""Finnhub: earnings calendar + sector. Free API key required (finnhub.io).

- Earnings: ONE bulk call for the lookahead window -> {symbol: earliest upcoming date}.
- Sector: per-symbol company profile (finnhubIndustry), cached to data/sectors.json since
  sectors rarely change (only missing symbols are fetched on later runs).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time

import requests

import config

_BASE = "https://finnhub.io/api/v1"


def earnings_before(symbols, today: dt.date) -> dict:
    """Return {symbol: 'YYYY-MM-DD'} for the next earnings date within the lookahead window.
    Empty dict if the key is missing or the call fails (caller treats unknown as 'clear')."""
    if not config.FINNHUB_API_KEY:
        return {}
    frm = today.isoformat()
    to = (today + dt.timedelta(days=config.EARNINGS_LOOKAHEAD_DAYS)).isoformat()
    try:
        r = requests.get(
            f"{_BASE}/calendar/earnings",
            params={"from": frm, "to": to, "token": config.FINNHUB_API_KEY},
            timeout=20,
        )
        r.raise_for_status()
        cal = (r.json() or {}).get("earningsCalendar") or []
    except (requests.RequestException, ValueError):
        return {}
    wanted = set(symbols)
    out: dict = {}
    for e in cal:
        s, d = e.get("symbol"), e.get("date")
        if s in wanted and d:
            if s not in out or d < out[s]:
                out[s] = d
    return out


def _load_cache() -> dict:
    try:
        with open(config.SECTORS_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(config.SECTORS_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=0, sort_keys=True)


def sectors(symbols) -> dict:
    """Return {symbol: sector}. Cached; only fetches symbols not already cached."""
    cache = _load_cache()
    if not config.FINNHUB_API_KEY:
        return cache
    missing = [s for s in symbols if s not in cache]
    for i, s in enumerate(missing):
        try:
            r = requests.get(
                f"{_BASE}/stock/profile2",
                params={"symbol": s, "token": config.FINNHUB_API_KEY},
                timeout=15,
            )
            if r.status_code == 429:        # rate limited -> wait and retry once
                time.sleep(2)
                r = requests.get(
                    f"{_BASE}/stock/profile2",
                    params={"symbol": s, "token": config.FINNHUB_API_KEY},
                    timeout=15,
                )
            data = r.json() or {}
            cache[s] = data.get("finnhubIndustry") or "Unknown"
        except (requests.RequestException, ValueError):
            cache[s] = cache.get(s, "Unknown")
        time.sleep(1.05)                    # stay under 60/min free limit
    _save_cache(cache)
    return cache
