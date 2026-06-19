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

# --- Preferred watchlist: stocks you're happy to own if assigned (wheel) ---
# For these, account picks favor income (highest yield >=0.7%) since assignment is OK.
PREFERRED = [
    s.strip().upper()
    for s in os.getenv("PREFERRED", "DAL,NVDA,AMZN,ORCL,INTC,OSS,SMCI").split(",")
    if s.strip()
]

# Curated "Top Picks" buy ideas (under $80; diversified beaten-up sectors + growth).
# Each gets a ~30-delta cash-secured-put entry computed live in the scan.
TOP_PICKS = [
    {"symbol": "PFE", "sector": "Healthcare", "thesis": "Pharma value; high dividend, low P/E"},
    {"symbol": "BAC", "sector": "Financials", "thesis": "Quality diversified bank; rate beneficiary"},
    {"symbol": "GM", "sector": "Autos", "thesis": "Deep value; very low P/E, big buybacks"},
    {"symbol": "KMI", "sector": "Energy", "thesis": "Pipeline fee cash flows; steady income"},
    {"symbol": "NU", "sector": "Fintech", "thesis": "LatAm digital bank; profitable growth"},
]

# --- Capital buckets (for the cash-secured-put picks at the top of the page) ---
# Total deployable capital, split into four buckets. The first three are fixed
# sizes; the last ("Bucket 4") absorbs whatever is left over. These dollar amounts
# are used ONLY to size each pick (how many contracts fit) — they are deliberately
# NOT published to results.json or shown on the page.
TOTAL_CAPITAL = _f("TOTAL_CAPITAL", 300000.0)
_BUCKETS = [
    _f("BUCKET_1", 22000.0),
    _f("BUCKET_2", 100000.0),
    _f("BUCKET_3", 50000.0),
]
ACCOUNTS = [
    {"name": "Bucket 1", "balance": _BUCKETS[0]},
    {"name": "Bucket 2", "balance": _BUCKETS[1]},
    {"name": "Bucket 3", "balance": _BUCKETS[2]},
    {"name": "Bucket 4", "balance": round(TOTAL_CAPITAL - sum(_BUCKETS), 2)},  # remaining
]
ACCOUNT_WEEKS = _i("ACCOUNT_WEEKS", 2)                     # pick horizon: next N weeks

# --- Runtime ---
SCAN_WORKERS = _i("SCAN_WORKERS", 6)                      # concurrent underlyings
REQUESTS_PER_MINUTE = _i("REQUESTS_PER_MINUTE", 240)      # politeness limit for CBOE

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
RESULTS_FILE = os.path.join(DATA_DIR, "results.json")
SYMBOLS_FILE = os.path.join(DATA_DIR, "symbols.txt")
