# CSP Scanner (globesec.ai/csp/)

A cash-secured-put scanner that runs on a schedule and publishes results to a
static page — no live server required, so it fits GitHub Pages.

## How it works

1. `.github/workflows/csp-scan.yml` runs on a cron (every 30 min during US market
   hours) and on manual dispatch.
2. It runs `csp/scanner/run.py`, which calls the **Tradier** API, scans optionable
   stocks under $300, keeps puts with a **30-day normalized yield of 0.7%–1.0%**,
   and writes `csp/results.json`.
3. The Action commits `results.json` back to the repo; GitHub Pages serves it.
4. `csp/index.html` fetches `results.json` and renders the sortable table.

### Yield formula
```
raw_yield     = bid / strike
yield_30d (%) = raw_yield * (30 / days_to_expiration) * 100   # keep if 0.70–1.00
```
Defaults (override via repo Variables / env): OTM puts only, |delta| ≤ 0.35,
open interest ≥ 50, expiration 21–45 days out.

## One-time setup

1. **Add your Tradier token** as a repository secret:
   GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `TRADIER_TOKEN`  ·  Value: *your Tradier access token*
2. *(Optional)* To test with free delayed data first, add a repository **Variable**
   `TRADIER_BASE_URL` = `https://sandbox.tradier.com`. Remove it (or set
   `https://api.tradier.com`) for live data.
3. Trigger the first run: repo → **Actions → CSP Scan → Run workflow**.
4. Visit **https://globesec.ai/csp/**.

## Widen the universe

`csp/scanner/data/symbols.txt` ships with a liquid starter set. Replace it with a
full optionable list (one ticker per line) for complete coverage — the `< $300`
filter is applied automatically from live quotes.

## Run locally

```powershell
cd csp\scanner
py -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:TRADIER_TOKEN="your_token"
python run.py        # writes ..\results.json
```
