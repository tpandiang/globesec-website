"""CSP wheel screener core.

For each underlying: enforce hard filters on the put side, run the wheelability check on
the call chain (25-45 DTE), score survivors by weekly_yield / assignment_probability, pick
the best put per name, and tier them (green = clean pass, yellow = marginal).
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from cboe import Cboe


def _dte(expiration: str, today: dt.date) -> int:
    return (dt.date.fromisoformat(expiration) - today).days


def _weekly_yield(premium_per_share: float, strike: float, dte: int) -> float:
    if strike <= 0 or dte <= 0:
        return 0.0
    return (premium_per_share / strike) * (7.0 / dte) * 100.0


def _liquid(o: dict) -> tuple[bool, float]:
    """Liquidity check -> (ok, spread_pct)."""
    bid, ask = o.get("bid"), o.get("ask")
    if bid is None or ask is None:
        return False, 999.0
    bid, ask = float(bid), float(ask)
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return False, 999.0
    spread_pct = (ask - bid) / mid * 100.0
    ok = (
        (o.get("open_interest") or 0) >= config.MIN_OI
        and (o.get("volume") or 0) >= config.MIN_VOL
        and spread_pct <= config.MAX_SPREAD_PCT
    )
    return ok, spread_pct


def _find_covered_call(chain: list[dict], cost_basis: float, today: dt.date):
    """Find a call 25-45 DTE with strike >= cost_basis paying >= CC_MIN_WEEKLY_YIELD weekly
    and meeting liquidity. Return the best (highest weekly yield) or None."""
    best = None
    for o in chain:
        if o.get("type") != "call":
            continue
        strike, bid = o.get("strike"), o.get("bid")
        if strike is None or bid is None:
            continue
        strike, bid = float(strike), float(bid)
        if strike < cost_basis or bid < config.MIN_BID:
            continue
        d = _dte(o["expiration"], today)
        if not (config.CC_DTE_MIN <= d <= config.CC_DTE_MAX):
            continue
        ok, _ = _liquid(o)
        if not ok:
            continue
        wy = _weekly_yield(bid, cost_basis, d)   # yield on effective cost basis
        if wy < config.CC_MIN_WEEKLY_YIELD:
            continue
        cand = {
            "cc_strike": round(strike, 2),
            "cc_premium": round(bid * 100, 2),
            "cc_expiration": o["expiration"],
            "cc_dte": d,
            "cc_weekly_yield": round(wy, 3),
        }
        if best is None or wy > best["cc_weekly_yield"]:
            best = cand
    return best


def _eval_symbol(client: Cboe, symbol: str, today: dt.date,
                 earnings_date: str | None, sector: str) -> dict | None:
    chain = client.get_chain(symbol)
    if not chain:
        return None
    spot = chain["price"]
    if spot <= 0:
        return None
    opts = chain["options"]

    # underlying must have weekly options
    near_exps = {o["expiration"] for o in opts if 0 < _dte(o["expiration"], today) <= 45}
    if len(near_exps) < config.MIN_EXPIRATIONS_WEEKLY:
        return None

    otm_ceiling = spot * (1 - config.MIN_OTM_PCT / 100.0)
    ed = dt.date.fromisoformat(earnings_date) if earnings_date else None

    best = None
    for o in opts:
        if o.get("type") != "put":
            continue
        strike, bid, ask = o.get("strike"), o.get("bid"), o.get("ask")
        delta = o.get("delta")
        if strike is None or bid is None or ask is None or delta is None:
            continue
        strike, bid = float(strike), float(bid)
        if bid < config.MIN_BID:
            continue

        dte = _dte(o["expiration"], today)
        if not (config.PUT_DTE_MIN <= dte <= config.PUT_DTE_MAX):
            continue

        # 2) >= 5% OTM
        if strike > otm_ceiling:
            continue
        # 1) weekly yield
        wy = _weekly_yield(bid, strike, dte)
        if wy < config.MIN_WEEKLY_YIELD:
            continue
        # 3) assignment probability via |delta|
        assign = abs(float(delta)) * 100.0
        if assign > config.MAX_ASSIGN_PROB:
            continue
        # 4) no earnings on/before expiry
        if ed and today < ed <= dt.date.fromisoformat(o["expiration"]):
            continue
        # 5) put liquidity
        liq_ok, spread_pct = _liquid(o)
        if not liq_ok:
            continue
        # 6) wheelability: covered call at/above effective cost basis
        cost_basis = strike - bid
        cc = _find_covered_call(opts, cost_basis, today)
        if not cc:
            continue

        score = wy / max(assign, config.ASSIGN_FLOOR)
        marginal = (
            wy < config.MARGINAL_YIELD
            or assign > config.MARGINAL_ASSIGN
            or spread_pct > config.MARGINAL_SPREAD
            or cc["cc_weekly_yield"] < config.MARGINAL_CC_YIELD
        )
        row = {
            "symbol": symbol,
            "sector": sector,
            "spot": round(spot, 2),
            "strike": round(strike, 2),
            "otm_pct": round((spot - strike) / spot * 100.0, 1),
            "expiration": o["expiration"],
            "dte": dte,
            "premium": round(bid * 100, 2),
            "weekly_yield": round(wy, 3),
            "assign_pct": round(assign, 1),
            "earnings_clear": True,
            "next_earnings": earnings_date,
            "wheel_ok": True,
            "cost_basis": round(cost_basis, 2),
            **cc,
            "open_interest": int(o.get("open_interest") or 0),
            "volume": int(o.get("volume") or 0),
            "spread_pct": round(spread_pct, 1),
            "iv": round(float(o["iv"]) * 100, 1) if o.get("iv") is not None else None,
            "collateral": round(strike * 100, 2),
            "score": round(score, 3),
            "tier": "yellow" if marginal else "green",
        }
        if best is None or row["score"] > best["score"]:
            best = row
    return best


def run_screen(symbols, earnings, sectors, progress=None) -> dict:
    client = Cboe()
    today = dt.date.today()
    rows, done = [], 0
    with ThreadPoolExecutor(max_workers=config.SCAN_WORKERS) as ex:
        futs = {
            ex.submit(_eval_symbol, client, s, today, earnings.get(s), sectors.get(s, "Unknown")): s
            for s in symbols
        }
        for fut in as_completed(futs):
            try:
                r = fut.result()
                if r:
                    rows.append(r)
            except Exception:
                pass
            done += 1
            if progress:
                progress(done, len(symbols), "screen")

    rows.sort(key=lambda r: r["score"], reverse=True)   # risk-adjusted, descending
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "data_source": "CBOE delayed (~15 min) + Finnhub (earnings/sector)",
        "config": {
            "min_weekly_yield": config.MIN_WEEKLY_YIELD,
            "min_otm_pct": config.MIN_OTM_PCT,
            "max_assign_prob": config.MAX_ASSIGN_PROB,
            "liquidity": {"min_oi": config.MIN_OI, "min_vol": config.MIN_VOL, "max_spread_pct": config.MAX_SPREAD_PCT},
            "cc_dte": [config.CC_DTE_MIN, config.CC_DTE_MAX],
            "cc_min_weekly_yield": config.CC_MIN_WEEKLY_YIELD,
            "total_collateral": config.TOTAL_COLLATERAL,
            "per_name_cap_pct": config.PER_NAME_CAP_PCT,
            "per_sector_cap_pct": config.PER_SECTOR_CAP_PCT,
            "single_expiry_flag_pct": config.SINGLE_EXPIRY_FLAG_PCT,
        },
        "universe_size": len(symbols),
        "earnings_source_ok": bool(earnings),
        "result_count": len(rows),
        "results": rows,
    }
