/**
 * Cloudflare Worker: live Tradier quote proxy for globesec.ai/csp/
 *
 * Holds the Tradier token server-side (as a Worker Secret) so the browser never
 * sees it. The /csp/ page calls this for real-time quotes on the contracts that
 * the scheduled scan already surfaced.
 *
 * Route (Cloudflare dashboard):  globesec.ai/api/*   ->  this Worker
 * Secrets/vars:
 *   TRADIER_TOKEN     (secret)  - your Tradier access token
 *   TRADIER_BASE_URL  (var)     - https://api.tradier.com  (or sandbox for delayed)
 *
 * Endpoint:
 *   GET /api/quotes?symbols=AAPL,AAPL260116P00150000,...
 *   -> { "ok": true, "asof": "<iso>", "quotes": { SYM: {last,bid,ask}, ... } }
 */

const MAX_SYMBOLS = 200;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (!url.pathname.endsWith("/quotes")) {
      return json({ ok: false, error: "not found" }, 404);
    }
    if (!env.TRADIER_TOKEN) {
      return json({ ok: false, error: "server not configured (no token)" }, 503);
    }

    const raw = (url.searchParams.get("symbols") || "").trim();
    if (!raw) return json({ ok: false, error: "missing ?symbols" }, 400);

    const symbols = [...new Set(raw.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean))];
    if (symbols.length === 0) return json({ ok: false, error: "no valid symbols" }, 400);
    if (symbols.length > MAX_SYMBOLS) symbols.length = MAX_SYMBOLS;

    const base = (env.TRADIER_BASE_URL || "https://api.tradier.com").replace(/\/+$/, "");
    const api = `${base}/v1/markets/quotes?symbols=${encodeURIComponent(symbols.join(","))}&greeks=false`;

    let resp;
    try {
      resp = await fetch(api, {
        headers: { Authorization: `Bearer ${env.TRADIER_TOKEN}`, Accept: "application/json" },
      });
    } catch (e) {
      return json({ ok: false, error: "upstream fetch failed" }, 502);
    }
    if (!resp.ok) return json({ ok: false, error: `tradier ${resp.status}` }, 502);

    const data = await resp.json();
    let node = data && data.quotes ? data.quotes.quote : null;
    if (!node) node = [];
    if (!Array.isArray(node)) node = [node];

    const quotes = {};
    for (const q of node) {
      if (!q || !q.symbol) continue;
      quotes[q.symbol] = {
        last: numOrNull(q.last),
        bid: numOrNull(q.bid),
        ask: numOrNull(q.ask),
      };
    }

    return json(
      { ok: true, asof: new Date().toISOString(), quotes },
      200,
      // brief edge cache to soften bursts; still effectively real-time
      { "Cache-Control": "public, max-age=5" }
    );
  },
};

function numOrNull(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function json(obj, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "https://globesec.ai",
      ...extraHeaders,
    },
  });
}
