"""Scan entry point for the scheduled GitHub Action.

Runs the CSP scan and writes csp/results.json (one level up from this folder),
which the static page at /csp/ fetches. Reads TRADIER_TOKEN from the environment.
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
