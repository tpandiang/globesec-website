"""Minimal Tradier REST client with a simple rate limiter.

Docs: https://documentation.tradier.com/brokerage-api/markets/get-quotes
"""
import threading
import time
from collections import deque
from typing import Iterable

import requests

import config


class _RateLimiter:
    """Token-bucket-ish limiter: at most N requests per rolling 60s."""

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
                sleep_for = 60.0 - (now - self._times[0]) + 0.01
                time.sleep(max(0.0, sleep_for))
            self._times.append(time.monotonic())


_limiter = _RateLimiter(config.REQUESTS_PER_MINUTE)


class TradierError(RuntimeError):
    pass


class Tradier:
    def __init__(self, token: str | None = None, base_url: str | None = None):
        self.token = token or config.TRADIER_TOKEN
        self.base_url = (base_url or config.TRADIER_BASE_URL).rstrip("/")
        if not self.token:
            raise TradierError(
                "No Tradier token set. Put TRADIER_TOKEN in your .env file."
            )
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        )

    def _get(self, path: str, params: dict) -> dict:
        _limiter.acquire()
        url = f"{self.base_url}{path}"
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=15)
                if r.status_code == 429:  # rate limited -> back off
                    time.sleep(2 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as e:
                if attempt == 2:
                    raise TradierError(f"GET {path} failed: {e}") from e
                time.sleep(1.5 * (attempt + 1))
        return {}

    @staticmethod
    def _as_list(node):
        """Tradier returns a single object when there is one item, a list otherwise."""
        if node is None:
            return []
        return node if isinstance(node, list) else [node]

    def get_quotes(self, symbols: Iterable[str]) -> dict[str, float]:
        """Return {symbol: last_price} for the given symbols (batched by caller)."""
        syms = ",".join(symbols)
        if not syms:
            return {}
        data = self._get("/v1/markets/quotes", {"symbols": syms, "greeks": "false"})
        quotes = self._as_list((data.get("quotes") or {}).get("quote"))
        out: dict[str, float] = {}
        for q in quotes:
            last = q.get("last")
            if last is not None:
                out[q["symbol"]] = float(last)
        return out

    def get_expirations(self, symbol: str) -> list[str]:
        data = self._get(
            "/v1/markets/options/expirations",
            {"symbol": symbol, "includeAllRoots": "true", "strikes": "false"},
        )
        exp = data.get("expirations")
        if not exp:
            return []
        return self._as_list(exp.get("date"))

    def get_chain(self, symbol: str, expiration: str) -> list[dict]:
        data = self._get(
            "/v1/markets/options/chains",
            {"symbol": symbol, "expiration": expiration, "greeks": "true"},
        )
        opts = data.get("options")
        if not opts:
            return []
        return self._as_list(opts.get("option"))
