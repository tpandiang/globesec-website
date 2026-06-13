"""Core cash-secured-put (CSP) scanner — CBOE delayed-quotes edition (no account).

For every optionable underlying priced under MAX_UNDERLYING_PRICE, look at put
options expiring in the monthly window (DTE_MIN..DTE_MAX) and keep the ones whose
**30-day-normalized yield** falls inside the target band (default 0.7%-1.0%).

    raw_yield      = bid / strike
    yield_30d (%)  = raw_yield * (NORMALIZE_DAYS / DTE) * 100

Data is ~15 minutes delayed (CBOE public endpoint).
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from cboe import Cboe


def _dte(expiration: str, today: dt.date) -> int:
    return (dt.date.fromisoformat(expiration) - today).days


def _eval_underlying(client: Cboe, symbol: str, today: dt.date) -> dict:
    """Return {'under': bool, 'rows': [...]} for one underlying."""
    chain = client.get_chain(symbol)
    if not chain:
        return {"under": False, "rows": []}
    price = chain["price"]
    if price <= 0 or price >= config.MAX_UNDERLYING_PRICE:
        return {"under": False, "rows": []}

    rows: list[dict] = []
    for o in chain["options"]:
        if o["type"] != "put":
            continue
        strike, bid = o["strike"], o["bid"]
        if strike is None or bid is None:
            continue
        strike, bid = float(strike), float(bid)
        if strike <= 0 or bid < config.MIN_BID:
            continue
        if strike >= price:                      # OTM puts only (sell below spot)
            continue

        dte = _dte(o["expiration"], today)
        if dte <= 0 or not (config.DTE_MIN <= dte <= config.DTE_MAX):
            continue

        delta = o.get("delta")
        if delta is not None and abs(float(delta)) > config.MAX_ABS_DELTA:
            continue

        oi = o.get("open_interest") or 0
        if oi < config.MIN_OPEN_INTEREST:
            continue

        raw_yield = bid / strike
        yield_30d = raw_yield * (config.NORMALIZE_DAYS / dte) * 100.0
        if not (config.TARGET_YIELD_MIN <= yield_30d <= config.TARGET_YIELD_MAX):
            continue

        rows.append(
            {
                "symbol": symbol,
                "option_symbol": o["option_symbol"],
                "price": round(price, 2),
                "expiration": o["expiration"],
                "dte": dte,
                "strike": round(strike, 2),
                "bid": round(bid, 2),
                "delta": round(float(delta), 3) if delta is not None else None,
                "open_interest": int(oi),
                "collateral": round(strike * 100, 2),
                "premium": round(bid * 100, 2),
                "yield_30d_pct": round(yield_30d, 3),
                "annualized_pct": round(raw_yield * (365.0 / dte) * 100.0, 2),
            }
        )
    return {"under": True, "rows": rows}


def run_scan(symbols: list[str], progress=None) -> dict:
    """Full scan. `progress(done, total, stage)` is an optional callback."""
    client = Cboe()
    today = dt.date.today()

    rows: list[dict] = []
    under = 0
    done = 0
    total = len(symbols)
    with ThreadPoolExecutor(max_workers=config.SCAN_WORKERS) as ex:
        futures = {ex.submit(_eval_underlying, client, s, today): s for s in symbols}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res["under"]:
                    under += 1
                rows.extend(res["rows"])
            except Exception:
                pass
            done += 1
            if progress:
                progress(done, total, "chains")

    # Rank by premium ($ received), highest first.
    rows.sort(key=lambda r: (r["premium"], r["yield_30d_pct"]), reverse=True)
    total_found = len(rows)

    # One row per symbol (its best/highest-premium contract), then keep top N symbols.
    best_per_symbol: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        if r["symbol"] in seen:
            continue
        seen.add(r["symbol"])
        best_per_symbol.append(r)
    rows = best_per_symbol[: config.TOP_N]

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "data_source": "CBOE delayed (~15 min)",
        "params": {
            "max_underlying_price": config.MAX_UNDERLYING_PRICE,
            "dte_window": [config.DTE_MIN, config.DTE_MAX],
            "yield_band_30d_pct": [config.TARGET_YIELD_MIN, config.TARGET_YIELD_MAX],
            "max_abs_delta": config.MAX_ABS_DELTA,
            "min_open_interest": config.MIN_OPEN_INTEREST,
            "top_n": config.TOP_N,
            "sorted_by": "premium",
        },
        "universe_size": len(symbols),
        "scanned_under_price": under,
        "total_qualifying": total_found,
        "result_count": len(rows),
        "results": rows,
    }
