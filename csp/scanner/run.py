"""Scan entry point for the scheduled GitHub Action.

Runs the CSP scan and writes csp/results.json (one level up from this folder),
which the static page at /csp/ fetches. Data source is CBOE (no token needed).
"""
import json
import os
import sys

import scanner
import universe

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "results.json"))


def main() -> int:
    symbols = universe.load_symbols()
    print(f"Universe: {len(symbols)} symbols")

    def progress(done, total, stage):
        if total and done % 25 == 0:
            print(f"  {stage}: {done}/{total}", flush=True)

    payload = scanner.run_scan(symbols, progress=progress)

    # Carry forward fundamentals per symbol if this run couldn't fetch them
    # (e.g. Yahoo/Nasdaq temporarily blocked the CI runner), so P/E etc. don't vanish.
    try:
        if os.path.exists(OUT):
            with open(OUT, encoding="utf-8") as f:
                prev = {r["symbol"]: r for r in json.load(f).get("results", [])}
            for r in payload["results"]:
                p = prev.get(r["symbol"])
                if not p:
                    continue
                for k in ("company_name", "pe", "week52_low", "week52_high"):
                    if r.get(k) is None and p.get(k) is not None:
                        r[k] = p[k]
    except Exception:
        pass

    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, OUT)

    print(
        f"Wrote {OUT}: {payload['result_count']} contracts "
        f"from {payload['scanned_under_price']} underlyings under "
        f"${payload['params']['max_underlying_price']:.0f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
