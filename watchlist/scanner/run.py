"""Watchlist data builder -> watchlist/watchlist.json

Sources (all graceful -- one bad symbol never fails the run):
  - Yahoo chart v8 [keyless] ... price, day change, volume, average volume,
        52-week high/low, and a TRUE 52-week average + 200-day average
        computed from a year of daily closes.
  - Finnhub profile2 ........... market cap [needs FINNHUB_API_KEY]
  - CBOE delayed quotes ........ total options open interest, call/put split,
        put/call ratio [keyless, same feed the CSP scanner uses]

Why this runs in GitHub Actions instead of the Cloudflare Worker: Yahoo blocks
Cloudflare egress IPs (see the note in workers/market/index.js), and the free
Workers plan caps subrequests. An Action runner has neither limit and already
holds FINNHUB_API_KEY as a repo secret.

The Worker's /watchlist route stays as a live fallback for price + open
interest when this JSON is stale or missing.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (globesec-watchlist)"}
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart"
FINNHUB = "https://finnhub.io/api/v1"
CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/options"
OCC = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "watchlist.json")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

WATCHLIST = [
    ("VRT",  "Vertiv Holdings",      "Data-Center Power & Cooling"),
    ("MOD",  "Modine Manufacturing", "Data-Center Power & Cooling"),
    ("FIX",  "Comfort Systems USA",  "Data-Center Power & Cooling"),
    ("TT",   "Trane Technologies",   "Data-Center Power & Cooling"),
    ("NVDA", "NVIDIA",               "Mega-Cap Tech"),
    ("GOOG", "Alphabet (Class C)",   "Mega-Cap Tech"),
    ("AAPL", "Apple",                "Mega-Cap Tech"),
    ("TSLA", "Tesla",                "Mega-Cap Tech"),
    ("AMZN", "Amazon",               "Mega-Cap Tech"),
    ("TSM",  "Taiwan Semiconductor", "Semiconductors & Memory"),
    ("SKHY", "SK hynix (ADR)",       "Semiconductors & Memory"),
    ("MU",   "Micron Technology",    "Semiconductors & Memory"),
]


def _r2(x):
    return None if x is None else round(float(x), 2)


def _get(url, **kw):
    r = requests.get(url, headers=UA, timeout=25, **kw)
    r.raise_for_status()
    return r.json()


def yahoo(symbol: str) -> dict:
    """Price, volume and a year of daily closes -> real averages."""
    try:
        d = _get(f"{YAHOO}/{symbol}", params={"range": "1y", "interval": "1d"})
        res = ((d.get("chart") or {}).get("result") or [None])[0]
        if not res:
            return {}
        meta = res.get("meta") or {}
        quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        closes = [c for c in (quote.get("close") or []) if c is not None]
        vols = [v for v in (quote.get("volume") or []) if v is not None]
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose")
        # Day change: prefer the previous close from the same series.
        chg = None
        if price is not None and len(closes) >= 2:
            chg = (float(price) / float(closes[-2]) - 1.0) * 100.0
        elif price is not None and prev:
            chg = (float(price) / float(prev) - 1.0) * 100.0
        return {
            "price": _r2(price),
            "change_pct": _r2(chg),
            "name": meta.get("longName") or meta.get("shortName"),
            "volume": meta.get("regularMarketVolume"),
            "avg_volume": int(sum(vols) / len(vols)) if vols else None,
            "year_high": _r2(meta.get("fiftyTwoWeekHigh")),
            "year_low": _r2(meta.get("fiftyTwoWeekLow")),
            # The number actually asked for: mean of every daily close in the window.
            "year_avg": _r2(sum(closes) / len(closes)) if closes else None,
            # Only publish a moving average when there is enough history to fill
            # the window -- a recently listed name (e.g. SKHY) would otherwise
            # show a 25-day mean in a column labelled "200-day".
            "avg_200": _r2(sum(closes[-200:]) / 200) if len(closes) >= 200 else None,
            "avg_50": _r2(sum(closes[-50:]) / 50) if len(closes) >= 50 else None,
            "sessions": len(closes),
            "partial_history": len(closes) < 200,
        }
    except (requests.RequestException, ValueError, ZeroDivisionError, TypeError) as e:
        print(f"  yahoo {symbol}: {e}")
        return {}


def market_cap(symbol: str) -> float | None:
    """Finnhub reports market cap in millions."""
    if not FINNHUB_API_KEY:
        return None
    try:
        d = _get(f"{FINNHUB}/stock/profile2", params={"symbol": symbol, "token": FINNHUB_API_KEY})
        mc = (d or {}).get("marketCapitalization")
        return float(mc) * 1e6 if mc else None
    except (requests.RequestException, ValueError, TypeError) as e:
        print(f"  finnhub {symbol}: {e}")
        return None


def option_interest(symbol: str) -> dict | None:
    """Sum open interest across every listed expiration."""
    try:
        data = (_get(f"{CBOE}/{symbol}.json") or {}).get("data") or {}
        call_oi = put_oi = opt_vol = 0.0
        contracts = 0
        for o in data.get("options") or []:
            m = OCC.match(o.get("option") or "")
            if not m:
                continue
            oi = float(o.get("open_interest") or 0)
            opt_vol += float(o.get("volume") or 0)
            contracts += 1
            if m.group(3) == "P":
                put_oi += oi
            else:
                call_oi += oi
        return {
            "total_oi": round(call_oi + put_oi),
            "call_oi": round(call_oi),
            "put_oi": round(put_oi),
            "pc_ratio": round(put_oi / call_oi, 2) if call_oi > 0 else None,
            "option_volume": round(opt_vol),
            "contracts": contracts,
        }
    except (requests.RequestException, ValueError, TypeError) as e:
        print(f"  cboe {symbol}: {e}")
        return None


def build() -> dict:
    rows = []
    for sym, name, group in WATCHLIST:
        print(f"{sym} ...")
        y = yahoo(sym)
        cap = market_cap(sym)
        opts = option_interest(sym)

        hi, lo, px = y.get("year_high"), y.get("year_low"), y.get("price")
        pos = None
        if None not in (hi, lo, px) and hi > lo:
            pos = max(0, min(100, round((px - lo) / (hi - lo) * 100)))

        rows.append({
            "symbol": sym,
            "name": y.get("name") or name,
            "group": group,
            "price": y.get("price"),
            "change_pct": y.get("change_pct"),
            "market_cap": cap,
            "volume": y.get("volume"),
            "avg_volume": y.get("avg_volume"),
            "year_high": hi,
            "year_low": lo,
            "year_avg": y.get("year_avg"),
            "year_mid": _r2((hi + lo) / 2) if None not in (hi, lo) else None,
            "avg_50": y.get("avg_50"),
            "avg_200": y.get("avg_200"),
            "range_pos_pct": pos,
            "sessions": y.get("sessions"),
            "partial_history": y.get("partial_history", False),
            "options": opts,
        })
        time.sleep(0.4)          # be polite to the free endpoints

    groups: list[dict] = []
    for r in rows:
        g = next((x for x in groups if x["name"] == r["group"]), None)
        if g is None:
            g = {"name": r["group"], "rows": []}
            groups.append(g)
        g["rows"].append(r)

    priced = sum(1 for r in rows if r["price"] is not None)
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "count": len(rows),
        "priced": priced,
        "has_market_cap": bool(FINNHUB_API_KEY),
        "source": "yahoo+finnhub+cboe",
        "rows": rows,
        "groups": groups,
    }


if __name__ == "__main__":
    payload = build()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    print(f"\nwrote {OUT} — {payload['priced']}/{payload['count']} priced, "
          f"market_cap={'yes' if payload['has_market_cap'] else 'no key'}")
