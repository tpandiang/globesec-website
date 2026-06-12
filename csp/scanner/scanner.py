"""Core cash-secured-put (CSP) scanner.

For every optionable underlying priced under MAX_UNDERLYING_PRICE, look at put
options expiring in the monthly window (DTE_MIN..DTE_MAX) and keep the ones whose
**30-day-normalized yield** falls inside the target band (default 0.7%-1.0%).

    raw_yield      = bid / strike
    yield_30d (%)  = raw_yield * (NORMALIZE_DAYS / DTE) * 100

This makes weekly and monthly contracts comparable on a 30-day basis.
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from tradier import Tradier


def _dte(expiration: str, today: dt.date) -> int:
    exp = dt.date.fromisoformat(expiration)
    return (exp - today).days


def _eval_underlying(client: Tradier, symbol: str, price: float, today: dt.date) -> list[dict]:
    """Return all qualifying CSP rows for one underlying."""
    rows: list[dict] = []
    try:
        expirations = client.get_expirations(symbol)
    except Exception:
        return rows

    targets = [e for e in expirations if config.DTE_MIN <= _dte(e, today) <= config.DTE_MAX]
    for expiration in targets:
        dte = _dte(expiration, today)
        if dte <= 0:
            continue
        try:
            chain = client.get_chain(symbol, expiration)
        except Exception:
            continue

        for opt in chain:
            if opt.get("option_type") != "put":
                continue
            strike = opt.get("strike")
            bid = opt.get("bid")
            if strike is None or bid is None:
                continue
            strike = float(strike)
            bid = float(bid)
            if strike <= 0 or bid < config.MIN_BID:
                continue
            if strike >= price:            # only out-of-the-money puts (sell below spot)
                continue

            greeks = opt.get("greeks") or {}
            delta = greeks.get("delta")
            if delta is not None and abs(float(delta)) > config.MAX_ABS_DELTA:
                continue

            oi = opt.get("open_interest") or 0
            if oi < config.MIN_OPEN_INTEREST:
                continue

            raw_yield = bid / strike
            yield_30d = raw_yield * (config.NORMALIZE_DAYS / dte) * 100.0
            if not (config.TARGET_YIELD_MIN <= yield_30d <= config.TARGET_YIELD_MAX):
                continue

            rows.append(
                {
                    "symbol": symbol,
                    "option_symbol": opt.get("symbol"),  # OCC symbol, for live quotes
                    "price": round(price, 2),
                    "expiration": expiration,
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
    return rows


def run_scan(symbols: list[str], progress=None) -> dict:
    """Full scan. `progress(done, total, stage)` is an optional callback."""
    client = Tradier()
    today = dt.date.today()

    # 1) Cheap bulk price filter -------------------------------------------
    priced: dict[str, float] = {}
    batches = [
        symbols[i : i + config.QUOTE_BATCH_SIZE]
        for i in range(0, len(symbols), config.QUOTE_BATCH_SIZE)
    ]
    for n, batch in enumerate(batches, 1):
        try:
            priced.update(client.get_quotes(batch))
        except Exception:
            pass
        if progress:
            progress(n, len(batches), "quotes")

    candidates = {
        s: p for s, p in priced.items() if 0 < p < config.MAX_UNDERLYING_PRICE
    }

    # 2) Per-underlying option scan (concurrent) ---------------------------
    rows: list[dict] = []
    done = 0
    total = len(candidates)
    with ThreadPoolExecutor(max_workers=config.SCAN_WORKERS) as ex:
        futures = {
            ex.submit(_eval_underlying, client, sym, price, today): sym
            for sym, price in candidates.items()
        }
        for fut in as_completed(futures):
            try:
                rows.extend(fut.result())
            except Exception:
                pass
            done += 1
            if progress:
                progress(done, total, "chains")

    rows.sort(key=lambda r: r["yield_30d_pct"], reverse=True)

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "params": {
            "max_underlying_price": config.MAX_UNDERLYING_PRICE,
            "dte_window": [config.DTE_MIN, config.DTE_MAX],
            "yield_band_30d_pct": [config.TARGET_YIELD_MIN, config.TARGET_YIELD_MAX],
            "max_abs_delta": config.MAX_ABS_DELTA,
            "min_open_interest": config.MIN_OPEN_INTEREST,
        },
        "universe_size": len(symbols),
        "scanned_under_price": total,
        "result_count": len(rows),
        "results": rows,
    }
