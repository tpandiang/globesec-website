# CSP Scanner (globesec.ai/csp/)

A cash-secured-put scanner that runs on a schedule and publishes results to a
static page — no live server, **no API key, and no account required.**

## How it works

1. `.github/workflows/csp-scan.yml` runs on a cron (every 15 min during US market
   hours) and on manual dispatch.
2. It runs `csp/scanner/run.py`, which pulls option chains from the free **CBOE
   delayed-quotes** endpoint, scans optionable stocks under $300, keeps puts with a
   **30-day normalized yield of 0.7%–1.0%**, and writes `csp/results.json`.
3. The Action commits `results.json` back to the repo; GitHub Pages serves it.
4. `csp/index.html` fetches `results.json` and renders the sortable table.

Data is **~15 minutes delayed** (free public CBOE feed). Real-time options data
requires a paid/entitled brokerage account, which this deliberately avoids.

### Yield formula
```
raw_yield     = bid / strike
yield_30d (%) = raw_yield * (30 / days_to_expiration) * 100   # keep if 0.70–1.00
```
Defaults (override via env): OTM puts only, |delta| ≤ 0.35, open interest ≥ 50,
expiration 21–45 days out.

## No setup needed
The scheduled scan runs automatically — there are no secrets or tokens to configure.
To trigger a run immediately: repo → **Actions → CSP Scan → Run workflow**.

> Note: globesec.ai is behind Cloudflare, which caches HTML. After deploying page
> changes, purge the Cloudflare cache (or purge `/csp/`) to see them immediately.

## Widen the universe
`csp/scanner/data/symbols.txt` ships with a liquid starter set. Replace it with a
full optionable list (one ticker per line) for complete coverage — the `< $300`
filter is applied automatically from the live (delayed) underlying price.

## Run locally
```powershell
cd csp\scanner
py -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py        # writes ..\results.json
```

> Caveat: the CBOE endpoint is unofficial and intended for personal use — it can
> change or rate-limit, and redistribution may conflict with its terms of use.
