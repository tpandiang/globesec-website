"""Current US index levels from the free CBOE delayed-quotes endpoint (no API key).

S&P 500 (_SPX), Dow Jones (_DJX x 100 — DJX quotes the Dow at 1/100 scale),
Nasdaq 100 (_NDX). Data is ~15 min delayed. get_indices() never raises: a symbol
that fails to fetch is simply omitted so it can't break the scan.
"""
import requests

_BASE = "https://cdn.cboe.com/api/global/delayed_quotes/options"
_HEADERS = {"User-Agent": "Mozilla/5.0 (globesec-csp-scanner)", "Accept": "application/json"}

# (display label, CBOE symbol, multiplier to convert to the headline index level)
_INDICES = [
    ("S&P 500", "_SPX", 1.0),
    ("Dow Jones", "_DJX", 100.0),   # DJX is the Dow at 1/100 scale
    ("Nasdaq 100", "_NDX", 1.0),
]


def _quote(symbol: str):
    r = requests.get(f"{_BASE}/{symbol}.json", headers=_HEADERS, timeout=20)
    r.raise_for_status()
    d = (r.json() or {}).get("data") or {}
    price = d.get("current_price")
    if not price:
        return None
    chg = d.get("price_change_percent")
    return float(price), (float(chg) if chg is not None else None)


def get_indices() -> list:
    """Return [{label, value, change_pct}, ...] for the major US indices."""
    out = []
    for label, sym, mult in _INDICES:
        try:
            q = _quote(sym)
        except Exception:
            q = None
        if not q:
            continue
        price, chg = q
        out.append({
            "label": label,
            "value": round(price * mult, 2),
            "change_pct": round(chg, 2) if chg is not None else None,
        })
    return out
