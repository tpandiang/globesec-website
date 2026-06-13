"""Best-effort fundamentals (company name, P/E, 52-week range) for a handful of symbols.

Primary source: Yahoo Finance quote API (needs a cookie + crumb, no account).
Fallback: Nasdaq public quote API (name + 52-week range only).
Everything is best-effort — fields are None if a source is unavailable (e.g. blocked
from a CI runner), and the page just shows "—".
"""
from __future__ import annotations

import requests

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _empty(sym: str) -> dict:
    return {"name": None, "pe": None, "week52_low": None, "week52_high": None}


def _yahoo(symbols: list[str]) -> dict:
    s = requests.Session()
    # NB: do NOT force Accept: application/json — the crumb endpoint returns text/plain
    # and 406s otherwise.
    s.headers.update({"User-Agent": _UA, "Accept": "*/*"})
    # prime cookies, then fetch a crumb
    for url in ("https://fc.yahoo.com/", "https://finance.yahoo.com/"):
        try:
            s.get(url, timeout=10)
        except requests.RequestException:
            pass
    crumb = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10).text.strip()
    if not crumb or "<" in crumb:
        raise RuntimeError("no crumb")

    out: dict = {}
    for i in range(0, len(symbols), 50):
        batch = symbols[i : i + 50]
        r = s.get(
            "https://query1.finance.yahoo.com/v7/finance/quote",
            params={"symbols": ",".join(batch), "crumb": crumb},
            timeout=15,
        )
        r.raise_for_status()
        for q in (r.json().get("quoteResponse") or {}).get("result") or []:
            sym = q.get("symbol")
            if not sym:
                continue
            out[sym] = {
                "name": q.get("longName") or q.get("shortName"),
                "pe": round(q["trailingPE"], 2) if q.get("trailingPE") is not None else None,
                "week52_low": q.get("fiftyTwoWeekLow"),
                "week52_high": q.get("fiftyTwoWeekHigh"),
            }
    return out


def _nasdaq_one(sym: str) -> dict:
    r = requests.get(
        f"https://api.nasdaq.com/api/quote/{sym}/info",
        params={"assetclass": "stocks"},
        headers={"User-Agent": _UA, "Accept": "application/json"},
        timeout=12,
    )
    d = (r.json() or {}).get("data") or {}
    name = (d.get("companyName") or "").replace(" Common Stock", "").strip() or None
    low = high = None
    rng = ((d.get("keyStats") or {}).get("fiftyTwoWeekHighLow") or {}).get("value")
    if rng and "-" in rng:
        try:
            lo, hi = rng.split("-")
            low = float(lo.replace("$", "").replace(",", "").strip())
            high = float(hi.replace("$", "").replace(",", "").strip())
        except ValueError:
            pass
    return {"name": name, "pe": None, "week52_low": low, "week52_high": high}


def fetch_fundamentals(symbols: list[str]) -> dict:
    """Return {symbol: {name, pe, week52_low, week52_high}}; best-effort."""
    result = {s: _empty(s) for s in symbols}
    try:
        result.update({k: v for k, v in _yahoo(symbols).items() if k in result})
    except Exception:
        pass
    # Nasdaq fallback for anything still missing a name
    for sym, f in result.items():
        if not f.get("name"):
            try:
                result[sym] = _nasdaq_one(sym)
            except Exception:
                pass
    return result
