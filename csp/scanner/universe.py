"""Load the universe of optionable underlyings to scan.

Reads one ticker per line from data/symbols.txt (blank lines and lines starting
with '#' are ignored). The price-under-$300 filter is applied later by the scanner
using live quotes, so this list can be broad.

To get a *full* optionable list, replace data/symbols.txt with a complete set of
optionable tickers (e.g. exported from your broker or a market-data provider).
"""
import config


def load_symbols() -> list[str]:
    out: list[str] = []
    try:
        with open(config.SYMBOLS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                t = line.strip().upper()
                if t and not t.startswith("#"):
                    out.append(t)
    except FileNotFoundError:
        return []
    # de-dup, keep order
    seen = set()
    uniq = []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq
