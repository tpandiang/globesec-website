# csp-scan Worker — live CSP scanner

Runs the whole cash-secured-put scan **on request** at the edge (CBOE delayed
quotes), edge-cached for 10 minutes, and returns the same JSON shape the old
`csp/results.json` had. The page at `/csp/` fetches this instead of a committed
file — so there's **no GitHub Action, no committed data, and no cache-purge dance.**

## One-time deploy (same as the `csp-market` Worker)
1. Cloudflare dashboard → **Workers & Pages → Create → Workers → Connect to Git**.
2. Pick `tpandiang/globesec-website`, set **Root directory = `workers/csp`**.
3. Deploy. It publishes to `https://csp-scan.<your-subdomain>.workers.dev/`
   (the page expects `csp-scan.ptmtek4.workers.dev`; change the URL in
   `csp/index.html` → `loadResults()` if your subdomain differs).
4. After this, every push to `main` auto-deploys the Worker.

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
