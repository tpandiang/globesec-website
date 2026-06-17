/**
 * GlobeSec CSP — live market-index Worker (Stage 1).
 *
 * Serves the three headline US indices (S&P 500, Dow Jones, Nasdaq 100) fetched
 * live from CBOE's free delayed-quotes endpoint, with a 60-second edge cache so
 * page loads are instant and CBOE isn't hammered. No GitHub commit, no Pages
 * rebuild, no cache-purge dance — the page just calls this endpoint.
 *
 * Deploy: paste into a new Cloudflare Worker, then add a route
 *   globesec.ai/api/indices*  ->  this worker
 * (so the page can fetch same-origin "/api/indices" with no CORS).
 */

const BASE = "https://cdn.cboe.com/api/global/delayed_quotes/options";

// [display label, CBOE symbol, multiplier to the headline index level]
const INDICES = [
  ["S&P 500", "_SPX", 1],
  ["Dow Jones", "_DJX", 100], // DJX quotes the Dow at 1/100 scale
  ["Nasdaq 100", "_NDX", 1],
];

const CACHE_SECONDS = 60;

async function quote(sym) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const r = await fetch(`${BASE}/${sym}.json`, {
        headers: {
          "User-Agent": "Mozilla/5.0 (globesec-csp-worker)",
          Accept: "application/json",
        },
        cf: { cacheTtl: 30, cacheEverything: true },
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = (await r.json())?.data || {};
      if (!d.current_price) return null;
      return { price: Number(d.current_price), chg: d.price_change_percent };
    } catch (_e) {
      // brief backoff, then retry
      await new Promise((res) => setTimeout(res, 400 * (attempt + 1)));
    }
  }
  return null;
}

async function getIndices() {
  const results = await Promise.all(
    INDICES.map(async ([label, sym, mult]) => {
      const q = await quote(sym);
      if (!q) return null;
      return {
        label,
        value: Math.round(q.price * mult * 100) / 100,
        change_pct: q.chg == null ? null : Math.round(Number(q.chg) * 100) / 100,
      };
    })
  );
  return results.filter(Boolean);
}

export default {
  async fetch(request) {
    // CORS preflight (in case the page calls cross-origin from a *.workers.dev URL)
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, OPTIONS",
        },
      });
    }

    const cache = caches.default;
    const cacheKey = new Request("https://globesec.ai/__cache/indices", { method: "GET" });

    let resp = await cache.match(cacheKey);
    if (resp) return resp;

    const indices = await getIndices();
    const body = JSON.stringify({
      generated_at: new Date().toISOString(),
      data_source: "CBOE delayed (~15 min)",
      indices,
    });

    resp = new Response(body, {
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": `public, max-age=${CACHE_SECONDS}`,
      },
    });
    // store a clone in the edge cache for the next 60s of visitors
    await cache.put(cacheKey, resp.clone());
    return resp;
  },
};
