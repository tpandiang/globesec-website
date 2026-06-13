"""Central configuration. Values can be overridden via environment variables
(loaded from a .env file in development). Data source is CBOE delayed quotes —
no API key or account required."""
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


# --- Screen criteria ---
MAX_UNDERLYING_PRICE = _f("MAX_UNDERLYING_PRICE", 300.0)   # only stocks under this price
TOP_N = _i("TOP_N", 20)                                    # keep only the top N (by premium)
DTE_MIN = _i("DTE_MIN", 21)                                # "monthly" expiration window (days)
DTE_MAX = _i("DTE_MAX", 45)
NORMALIZE_DAYS = _i("NORMALIZE_DAYS", 30)                  # normalize yield to a 30-day basis
TARGET_YIELD_MIN = _f("TARGET_YIELD_MIN", 0.70)           # 30-day normalized yield band (percent)
TARGET_YIELD_MAX = _f("TARGET_YIELD_MAX", 1.00)
MAX_ABS_DELTA = _f("MAX_ABS_DELTA", 0.35)                  # only sell puts at/under this |delta| (OTM-ish)
MIN_OPEN_INTEREST = _i("MIN_OPEN_INTEREST", 50)           # liquidity floor
MIN_BID = _f("MIN_BID", 0.05)                             # ignore no-bid contracts

# --- Accounts (for per-account picks at the top of the page) ---
ACCOUNTS = [
    {"name": "OPT-J", "balance": 46000.0},
    {"name": "OPT-C", "balance": 34000.0},
    # add the third account here, e.g. {"name": "OPT-X", "balance": 25000.0},
]
ACCOUNT_WEEKS = _i("ACCOUNT_WEEKS", 2)                     # pick horizon: next N weeks

# --- Runtime ---
SCAN_WORKERS = _i("SCAN_WORKERS", 6)                      # concurrent underlyings
REQUESTS_PER_MINUTE = _i("REQUESTS_PER_MINUTE", 240)      # politeness limit for CBOE

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
RESULTS_FILE = os.path.join(DATA_DIR, "results.json")
SYMBOLS_FILE = os.path.join(DATA_DIR, "symbols.txt")
