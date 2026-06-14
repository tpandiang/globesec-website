"""CSP WHEEL SCREENER — CONFIG BLOCK (tune everything here).

Priority: (1) avoid assignment, (2) if assigned, be able to sell a covered call at/above
effective cost basis for good premium. Data: CBOE delayed (~15 min) + Finnhub (earnings/sector).
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _f(name, d):
    try: return float(os.getenv(name, d))
    except (TypeError, ValueError): return d

def _i(name, d):
    try: return int(os.getenv(name, d))
    except (TypeError, ValueError): return d


# ── HARD FILTERS (a contract failing ANY of these is excluded) ──────────────
MIN_WEEKLY_YIELD      = _f("MIN_WEEKLY_YIELD", 0.7)    # % weekly yield on collateral
MIN_OTM_PCT           = _f("MIN_OTM_PCT", 5.0)         # strike <= spot*(1 - MIN_OTM_PCT/100)
MAX_ASSIGN_PROB       = _f("MAX_ASSIGN_PROB", 20.0)    # |put delta|*100 (%)

# put-side liquidity
MIN_OI                = _i("MIN_OI", 500)             # open interest
MIN_VOL               = _i("MIN_VOL", 50)            # volume
MAX_SPREAD_PCT        = _f("MAX_SPREAD_PCT", 10.0)    # (ask-bid)/mid * 100
MIN_BID               = _f("MIN_BID", 0.05)

# put expiration window to consider
PUT_DTE_MIN           = _i("PUT_DTE_MIN", 5)
PUT_DTE_MAX           = _i("PUT_DTE_MAX", 45)
# "underlying has weekly options": need >= this many distinct expirations within 45 DTE
MIN_EXPIRATIONS_WEEKLY = _i("MIN_EXPIRATIONS_WEEKLY", 4)

# ── WHEELABILITY (covered-call check on the call chain) ─────────────────────
CC_DTE_MIN            = _i("CC_DTE_MIN", 25)
CC_DTE_MAX            = _i("CC_DTE_MAX", 45)
CC_MIN_WEEKLY_YIELD   = _f("CC_MIN_WEEKLY_YIELD", 0.5)  # % weekly on effective cost basis
# the covered-call strike must be >= effective cost basis (put_strike - put_premium/share)

# ── EARNINGS ───────────────────────────────────────────────────────────────
EARNINGS_LOOKAHEAD_DAYS = _i("EARNINGS_LOOKAHEAD_DAYS", 50)

# ── RANKING ────────────────────────────────────────────────────────────────
# score = weekly_yield / assignment_probability  (premium per unit of assignment risk)
ASSIGN_FLOOR          = _f("ASSIGN_FLOOR", 0.5)        # floor for the divisor (avoid /0)

# ── TIERS (green = clean pass, yellow = marginal, fails are hidden) ─────────
MARGINAL_YIELD        = _f("MARGINAL_YIELD", 0.8)      # weekly yield < this = marginal
MARGINAL_ASSIGN       = _f("MARGINAL_ASSIGN", 15.0)    # assign % > this = marginal
MARGINAL_SPREAD       = _f("MARGINAL_SPREAD", 8.0)     # spread % > this = marginal
MARGINAL_CC_YIELD     = _f("MARGINAL_CC_YIELD", 0.6)   # wheel call weekly yield < this = marginal

# ── PORTFOLIO GUARDRAILS (defaults; the page lets you change collateral live) ─
TOTAL_COLLATERAL      = _f("TOTAL_COLLATERAL", 120000.0)
PER_NAME_CAP_PCT      = _f("PER_NAME_CAP_PCT", 25.0)
PER_SECTOR_CAP_PCT    = _f("PER_SECTOR_CAP_PCT", 30.0)
SINGLE_EXPIRY_FLAG_PCT = _f("SINGLE_EXPIRY_FLAG_PCT", 50.0)

# ── RUNTIME ────────────────────────────────────────────────────────────────
SCAN_WORKERS          = _i("SCAN_WORKERS", 6)
REQUESTS_PER_MINUTE   = _i("REQUESTS_PER_MINUTE", 240)   # CBOE politeness limit
FINNHUB_API_KEY       = os.getenv("FINNHUB_API_KEY", "")

DATA_DIR    = os.path.join(os.path.dirname(__file__), "data")
SYMBOLS_FILE = os.path.join(DATA_DIR, "symbols.txt")
SECTORS_CACHE = os.path.join(DATA_DIR, "sectors.json")
OUT_FILE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "screener.json"))
