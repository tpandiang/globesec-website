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

# No listed company is worth $10T. Anything above this is a units/currency bug,
# so drop it rather than publish a number that is obviously wrong.
MAX_PLAUSIBLE_CAP = 1e13

SYMBOLS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "symbols.txt")
SYMBOLS_API = "https://csp-market.ptmtek4.workers.dev/watchlist/symbols"


def load_watchlist() -> list:
    """Ticker list, preferring the live KV store over the checked-in file.

    KV is the source of truth so symbols can be added from the website. If the
    Worker is unreachable or KV is not bound yet, fall back to symbols.txt so a
    network blip never produces an empty watchlist.
    """
    try:
        d = _get(SYMBOLS_API, tries=2)
        syms = (d or {}).get("symbols") or []
        if syms:
            rows = [(str(s.get("ticker", "")).upper(), s.get("name") or "", s.get("group") or "Watchlist")
                    for s in syms if s.get("ticker")]
            if rows:
                print(f"symbols: {len(rows)} from {(d or {}).get('source')} (live)")
                return rows
    except (requests.RequestException, ValueError, TypeError, AttributeError) as e:
        print(f"  symbols API unavailable ({e}) — using symbols.txt")

    return load_watchlist_file()


def load_watchlist_file() -> list:
    """Read symbols.txt -> [(ticker, name, group)].

    Format is one ticker per line, optionally `TICKER | Display Name | Group`.
    Blank lines and # comments are ignored.
    """
    rows, seen = [], set()
    try:
        with open(SYMBOLS_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"!! {SYMBOLS_FILE} not found — nothing to build")
        return rows

    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        ticker = parts[0].upper()
        if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
            print(f"  skipping unparseable line: {raw.strip()!r}")
            continue
        if ticker in seen:
            print(f"  skipping duplicate: {ticker}")
            continue
        seen.add(ticker)
        name = parts[1] if len(parts) > 1 and parts[1] else ""
        group = parts[2] if len(parts) > 2 and parts[2] else "Watchlist"
        rows.append((ticker, name, group))
    return rows


def _r2(x):
    return None if x is None else round(float(x), 2)


def _get(url, tries=4, **kw):
    """GET with backoff on throttling.

    CBOE returns 429 when we hit it right after the CSP scanner has pulled ~46
    chains earlier in the same workflow run. Without retries every symbol fails
    at once and the whole options column silently goes null.
    """
    delay = 2.0
    for attempt in range(tries):
        last_attempt = attempt == tries - 1
        try:
            r = requests.get(url, headers=UA, timeout=45, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and not last_attempt:
                print(f"    HTTP {r.status_code}, retrying in {delay:.0f}s")
                time.sleep(delay)
                delay *= 2.5
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if last_attempt:
                raise
            time.sleep(delay)
            delay *= 2.5
    return None


def fx_to_usd() -> dict:
    """USD per one unit of each currency, keyless. Empty dict on failure."""
    try:
        d = _get("https://open.er-api.com/v6/latest/USD")
        return {c: 1.0 / v for c, v in ((d or {}).get("rates") or {}).items() if v}
    except (requests.RequestException, ValueError, TypeError, ZeroDivisionError) as e:
        print(f"  fx: {e}")
        return {}


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


def market_cap(symbol: str, fx: dict) -> float | None:
    """Market cap in USD.

    Finnhub reports marketCapitalization in MILLIONS of the company's *reporting*
    currency, not USD. Foreign listings therefore come back wildly inflated —
    TSM in TWD (~32x) and SKHY in KRW (~1415x) — so the raw value has to be
    converted using the `currency` field on the same response.
    """
    if not FINNHUB_API_KEY:
        return None
    try:
        d = _get(f"{FINNHUB}/stock/profile2", params={"symbol": symbol, "token": FINNHUB_API_KEY})
        mc = (d or {}).get("marketCapitalization")
        if not mc:
            return None
        val = float(mc) * 1e6
        cur = str((d or {}).get("currency") or "USD").upper()
        if cur != "USD":
            rate = fx.get(cur)
            if not rate:
                print(f"  {symbol}: cap reported in {cur}, no FX rate — dropping")
                return None
            val *= rate
        if val > MAX_PLAUSIBLE_CAP:
            print(f"  {symbol}: cap {val:.3g} exceeds sanity ceiling — dropping")
            return None
        return val
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
    watchlist = load_watchlist()
    if not watchlist:
        raise SystemExit("no symbols resolved from KV or symbols.txt — refusing to publish an empty watchlist")
    fx = fx_to_usd()
    print(f"fx rates loaded: {len(fx)}")
    rows = []
    for sym, name, group in watchlist:
        print(f"{sym} ...")
        y = yahoo(sym)
        cap = market_cap(sym, fx)
        opts = option_interest(sym)

        hi, lo, px = y.get("year_high"), y.get("year_low"), y.get("price")
        pos = None
        if None not in (hi, lo, px) and hi > lo:
            pos = max(0, min(100, round((px - lo) / (hi - lo) * 100)))

        rows.append({
            "symbol": sym,
            "name": name or y.get("name") or sym,
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
        time.sleep(1.2)          # CBOE throttles; the CSP scanner runs just ahead of us

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
