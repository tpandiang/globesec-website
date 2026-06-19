# csp-scan Worker — live CSP scanner

Runs the whole cash-secured-put scan **on request** at the edge (CBOE delayed
quotes), edge-cached for 10 minutes, and returns the same JSON shape the old
`csp/results.json` had. The page at `/csp/` fetches this instead of a committed
file — so there's **no GitHub Action, no committed data, and no cache-purge dance.**

## No new Worker to set up — it rides on `csp-market`
The scan is exported from `index.js` (`runScan`) and **imported by the existing
`csp-market` Worker** (`workers/market/index.js`), served at its `/scan` route:

    https://csp-market.ptmtek4.workers.dev/scan

`csp-market` is already connected to GitHub (Workers Builds, root `workers/market`),
so a normal push to `main` auto-deploys the scan too — no extra Cloudflare setup.
The page (`csp/index.html` → `loadResults()`) fetches that URL.

### Optional: run it as its own Worker instead
If you'd rather have a standalone `csp-scan` Worker, connect a new Workers-Builds
project with **Root directory = `workers/csp`** (it has its own `wrangler.toml` and a
default `fetch` handler), then point `loadResults()` at `csp-scan.<subdomain>.workers.dev`.

## Optional: company name / P/E / 52-week range
Set **`FMP_API_KEY`** under the Worker's *Settings → Variables and Secrets*
(same key the `csp-market` Worker uses). Without it the scan still works; those
fields just show "—".

## Tuning
- Universe and all thresholds are constants at the top of `index.js`.
- Subrequest budget is `3 + UNIVERSE.length + 1`. Keep `UNIVERSE` under ~46 on the
  **free** Workers plan (50-subrequest cap). On **Workers Paid** (1000 subrequests,
  30 s CPU) you can raise it substantially.
- Capital buckets ($22K / $100K / $50K / remaining of $300K) are in `BUCKETS`.
  Dollar amounts are used only to size each pick and are **never** put in the output.

## Local check
```bash
npx wrangler dev          # then open http://localhost:8787/?nocache=1
# or bundle-check only:
npx wrangler deploy --dry-run --outdir /tmp/csp-build
```
`?nocache=1` bypasses the edge cache for a fresh scan.
