"""Free CBOE delayed-quotes client (no account / API key required).

One request per underlying returns the entire option chain plus the underlying
price. Data is ~15 minutes delayed. This is an unofficial public endpoint
intended for personal use.

    https://cdn.cboe.com/api/global/delayed_quotes/options/<SYMBOL>.json
"""
import re
import threading
import time
from collections import deque

import requests

import config

# OCC option symbol, e.g. AAPL260612P00150000 -> root, YYMMDD, C/P, strike*1000
_OCC = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")
_BASE = "https://cdn.cboe.com/api/global/delayed_quotes/options"


class _RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = max(1, per_minute)
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._times and now - self._times[0] > 60.0:
                self._times.popleft()
            if len(self._times) >= self.per_minute:
                time.sleep(max(0.0, 60.0 - (now - self._times[0]) + 0.01))
            self._times.append(time.monotonic())


_limiter = _RateLimiter(config.REQUESTS_PER_MINUTE)


class Cboe:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (globesec-csp-scanner)",
                "Accept": "application/json",
            }
        )

    def get_chain(self, symbol: str) -> dict | None:
        """Return {'price': float, 'options': [ {...}, ... ]} or None on failure."""
        url = f"{_BASE}/{symbol.upper()}.json"
        for attempt in range(3):
            _limiter.acquire()
            try:
                r = self.session.get(url, timeout=25)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                data = (r.json() or {}).get("data") or {}
                return self._parse(data)
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    return None
                time.sleep(1.0 * (attempt + 1))
        return None

    @staticmethod
    def _parse(data: dict) -> dict:
        price = data.get("current_price") or data.get("close") or 0
        change_pct = data.get("price_change_percent")
        out = []
        for o in data.get("options") or []:
            occ = o.get("option") or ""
            m = _OCC.match(occ)
            if not m:
                continue
            _root, ymd, cp, strike8 = m.groups()
            out.append(
                {
                    "option_symbol": occ,
                    "type": "put" if cp == "P" else "call",
                    "strike": int(strike8) / 1000.0,
                    "expiration": f"20{ymd[0:2]}-{ymd[2:4]}-{ymd[4:6]}",
                    "bid": o.get("bid"),
                    "ask": o.get("ask"),
                    "delta": o.get("delta"),
                    "open_interest": o.get("open_interest") or 0,
                    "volume": o.get("volume") or 0,
                    "iv": o.get("iv"),
                    "last": o.get("last_trade_price"),
                }
            )
        try:
            change_pct = float(change_pct) if change_pct is not None else None
        except (TypeError, ValueError):
            change_pct = None
        return {"price": float(price) if price else 0.0, "change_pct": change_pct, "options": out}
