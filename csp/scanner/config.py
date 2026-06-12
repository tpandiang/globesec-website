"""Central configuration. All values can be overridden via environment variables
(loaded from a .env file in development)."""
import os
from dotenv import load_dotenv

load_dotenv()


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# --- Tradier API ---
TRADIER_TOKEN = os.getenv("TRADIER_TOKEN", "")
# Production: https://api.tradier.com  |  Sandbox (delayed): https://sandbox.tradier.com
TRADIER_BASE_URL = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com").rstrip("/")

# --- Screen criteria ---
MAX_UNDERLYING_PRICE = _f("MAX_UNDERLYING_PRICE", 300.0)   # only stocks under this price
DTE_MIN = _i("DTE_MIN", 21)                                # "monthly" expiration window (days)
DTE_MAX = _i("DTE_MAX", 45)
NORMALIZE_DAYS = _i("NORMALIZE_DAYS", 30)                  # normalize yield to a 30-day basis
TARGET_YIELD_MIN = _f("TARGET_YIELD_MIN", 0.70)           # 30-day normalized yield band (percent)
TARGET_YIELD_MAX = _f("TARGET_YIELD_MAX", 1.00)
MAX_ABS_DELTA = _f("MAX_ABS_DELTA", 0.35)                  # only sell puts at/under this |delta| (OTM-ish)
MIN_OPEN_INTEREST = _i("MIN_OPEN_INTEREST", 50)           # liquidity floor
MIN_BID = _f("MIN_BID", 0.05)                             # ignore no-bid contracts

# --- Runtime ---
SCAN_WORKERS = _i("SCAN_WORKERS", 4)                      # concurrent underlyings
REQUESTS_PER_MINUTE = _i("REQUESTS_PER_MINUTE", 110)      # Tradier rate limit guard
QUOTE_BATCH_SIZE = _i("QUOTE_BATCH_SIZE", 100)            # symbols per quotes call

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
RESULTS_FILE = os.path.join(DATA_DIR, "results.json")
SYMBOLS_FILE = os.path.join(DATA_DIR, "symbols.txt")
