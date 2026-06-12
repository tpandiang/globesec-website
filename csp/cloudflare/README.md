# Live quote proxy (Cloudflare Worker)

Gives globesec.ai/csp/ **real-time quotes** without exposing your Tradier token.
The page calls `https://globesec.ai/api/quotes?symbols=...`; this Worker holds the
token server-side, queries Tradier, and returns the quotes.

## Deploy (CLI — recommended)

From this folder (`csp/cloudflare`):

```powershell
npm install -g wrangler        # one time
wrangler login                 # opens browser, authorizes your Cloudflare account
wrangler secret put TRADIER_TOKEN   # paste your Tradier token when prompted
wrangler deploy                # publishes the Worker + the globesec.ai/api/* route
```

That's it — the `routes` line in `wrangler.toml` binds it to `globesec.ai/api/*`,
so the `/csp/` page picks it up automatically and the LIVE indicator turns green.

To test with **free delayed** data first, edit `wrangler.toml` and set
`TRADIER_BASE_URL = "https://sandbox.tradier.com"`, then `wrangler deploy` again.
Switch back to `https://api.tradier.com` for real-time.

## Deploy (dashboard — no CLI)

1. Cloudflare dashboard → **Workers & Pages → Create → Worker**.
2. Paste the contents of `tradier-proxy.js`, **Deploy**.
3. **Settings → Variables**:
   - Secret: `TRADIER_TOKEN` = your token
   - Variable: `TRADIER_BASE_URL` = `https://api.tradier.com`
4. **Settings → Triggers → Routes** → add `globesec.ai/api/*` (zone `globesec.ai`).

## Verify

```
https://globesec.ai/api/quotes?symbols=AAPL
```
should return JSON like `{"ok":true,"asof":"…","quotes":{"AAPL":{"last":…,"bid":…,"ask":…}}}`.

## Note on "real-time"

Tradier returns true real-time quotes only if your brokerage account is entitled to
them (production). Otherwise data is ~15 min delayed, and the sandbox is always
delayed — independent of this Worker.
