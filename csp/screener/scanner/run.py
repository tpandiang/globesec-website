"""Entry point: run the wheel screener and write csp/screener/screener.json."""
import datetime as dt
import json
import os
import sys

import config
import finnhub_data
import market
import screener


def load_symbols():
    out, seen = [], set()
    with open(config.SYMBOLS_FILE, encoding="utf-8") as f:
        for line in f:
            t = line.strip().upper()
            if t and not t.startswith("#") and t not in seen:
                seen.add(t)
                out.append(t)
    return out


def main() -> int:
    symbols = load_symbols()
    today = dt.date.today()
    print(f"Universe: {len(symbols)} symbols")
    if not config.FINNHUB_API_KEY:
        print("WARNING: FINNHUB_API_KEY not set — earnings filter disabled, sectors limited.")

    earnings = finnhub_data.earnings_before(symbols, today)
    print(f"Earnings calendar: {len(earnings)} names reporting within {config.EARNINGS_LOOKAHEAD_DAYS}d")
    sectors = finnhub_data.sectors(symbols)
    print(f"Sectors cached: {len(sectors)}")

    def progress(d, t, stage):
        if t and d % 25 == 0:
            print(f"  {stage}: {d}/{t}", flush=True)

    payload = screener.run_screen(symbols, earnings, sectors, progress=progress)
    payload["indices"] = market.get_indices()

    os.makedirs(os.path.dirname(config.OUT_FILE), exist_ok=True)
    tmp = config.OUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, config.OUT_FILE)
    print(f"Wrote {config.OUT_FILE}: {payload['result_count']} candidates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
