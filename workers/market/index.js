/**
 * GlobeSec CSP — "Market Today" Worker (csp-market), deployed from GitHub via Workers Builds.
 *
 * Sources (all optional/graceful, never throws):
 *   - indices ........ CBOE delayed quotes                       [keyless]
 *   - gainers/losers .. FMP (if FMP_API_KEY) else Yahoo          [FMP recommended; Yahoo blocks CF IPs]
 *   - earnings_week ... Finnhub earnings calendar (Mon-Fri)      [needs FINNHUB_API_KEY]
 *   - news ........... Finnhub general market news               [needs FINNHUB_API_KEY]
 *
 * Set FINNHUB_API_KEY / FMP_API_KEY under the Worker's Settings -> Variables and Secrets.
 */

import { runScan } from "../csp/index.js";   // /scan route -> full CSP scan (shares this Worker)

const CSP_CACHE_SECONDS = 600;
const CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/options";
const YH = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved";
const UA = "Mozilla/5.0 (globesec-csp-worker)";
const CACHE_SECONDS = 600;
const INDICES = [["S&P 500", "_SPX", 1], ["Dow Jones", "_DJX", 100], ["Nasdaq 100", "_NDX", 1]];

async function jget(url) {
  const r = await fetch(url, { headers: { "User-Agent": UA, Accept: "application/json" } });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

async function getIndices(dbg) {
  const out = await Promise.all(INDICES.map(async ([label, sym, mult]) => {
    try {
      const d = (await jget(`${CBOE}/${sym}.json`))?.data || {};
      if (!d.current_price) return null;
      const chg = d.price_change_percent;
      return { label, value: Math.round(Number(d.current_price) * mult * 100) / 100, change_pct: chg == null ? null : Math.round(Number(chg) * 100) / 100 };
    } catch (e) { dbg.push(`index ${sym}: ${e}`); return null; }
  }));
  return (out || []).filter(Boolean);
}

async function movers(kind, env, dbg) {
  if (env && env.FMP_API_KEY) {
    try {
      const d = await jget(`https://financialmodelingprep.com/api/v3/stock_market/${kind}?apikey=${env.FMP_API_KEY}`);
      if (Array.isArray(d) && d.length) {
        return d.slice(0, 10).map((x) => ({ symbol: x.symbol, name: x.name || x.symbol, price: x.price ?? null, change_pct: x.changesPercentage == null ? null : Math.round(Number(x.changesPercentage) * 100) / 100 }));
      }
      dbg.push(`fmp ${kind}: empty/unauthorized`);
    } catch (e) { dbg.push(`fmp ${kind}: ${e}`); }
  }
  try {
    const scr = kind === "gainers" ? "day_gainers" : "day_losers";
    const d = await jget(`${YH}?count=10&scrIds=${scr}`);
    const q = (d && d.finance && d.finance.result && d.finance.result[0] && d.finance.result[0].quotes) || [];
    if (q.length) {
      return q.slice(0, 10).map((x) => ({ symbol: x.symbol, name: x.shortName || x.longName || x.symbol, price: x.regularMarketPrice ?? null, change_pct: x.regularMarketChangePercent == null ? null : Math.round(Number(x.regularMarketChangePercent) * 100) / 100 }));
    }
    dbg.push(`yahoo ${kind}: empty (likely IP-blocked)`);
  } catch (e) { dbg.push(`yahoo ${kind}: ${e}`); }
  return [];
}

function isoDate(d) { return d.toISOString().slice(0, 10); }

async function earningsThisWeek(key, dbg) {
  if (!key) { dbg.push("earnings: no FINNHUB_API_KEY"); return []; }
  try {
    const now = new Date(); const day = now.getUTCDay();
    const monday = new Date(now); monday.setUTCDate(now.getUTCDate() - ((day + 6) % 7));
    const friday = new Date(monday); friday.setUTCDate(monday.getUTCDate() + 4);
    const d = await jget(`https://finnhub.io/api/v1/calendar/earnings?from=${isoDate(monday)}&to=${isoDate(friday)}&token=${key}`);
    const rows = ((d && d.earningsCalendar) || []).filter((e) => e.symbol && /^[A-Z]{1,5}$/.test(e.symbol))
      .map((e) => ({ symbol: e.symbol, date: e.date, hour: e.hour || "", eps_estimate: e.epsEstimate ?? null }));
    rows.sort((a, b) => (b.eps_estimate != null) - (a.eps_estimate != null) || a.date.localeCompare(b.date));
    return rows.slice(0, 40);
  } catch (e) { dbg.push(`earnings: ${e}`); return []; }
}

async function news(key, dbg) {
  if (!key) { dbg.push("news: no FINNHUB_API_KEY"); return []; }
  try {
    const d = await jget(`https://finnhub.io/api/v1/news?category=general&token=${key}`);
    return ((d || []).slice(0, 8)).map((n) => ({ headline: n.headline, source: n.source, url: n.url, datetime: n.datetime ? new Date(n.datetime * 1000).toISOString() : null }));
  } catch (e) { dbg.push(`news: ${e}`); return []; }
}

function summarize(ix) {
  const w = (ix || []).filter((i) => i && i.change_pct != null);
  if (!w.length) return "Market data is loading.";
  const up = w.filter((i) => i.change_pct > 0).length, down = w.filter((i) => i.change_pct < 0).length;
  if (up === w.length) return "U.S. markets are broadly higher today.";
  if (down === w.length) return "U.S. markets are broadly lower today.";
  return up >= down ? "U.S. markets are mostly higher today." : "U.S. markets are mostly lower today.";
}

function jsonResponse(obj, seconds) {
  return new Response(JSON.stringify(obj), {
    headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": `public, max-age=${seconds}` },
  });
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS" } });
    }

    // /scan -> live cash-secured-put scan (edge-cached); / -> Market Today (below).
    const url = new URL(request.url);
    if (url.pathname.replace(/\/+$/, "") === "/scan") {
      const cache = caches.default;
      const nocache = url.searchParams.has("nocache");
      const goodKey = new Request("https://globesec.ai/__cache/csp-scan", { method: "GET" });
      if (!nocache) { const hit = await cache.match(goodKey); if (hit) return hit; }
      const sdbg = [];
      let payload;
      try { payload = await runScan(env, sdbg); }
      catch (e) { payload = { error: String(e), results: [], indices: [], debug: sdbg }; }
      // Only cache a HEALTHY scan, so a CBOE 429 can't poison the 10-min cache.
      const healthy = Array.isArray(payload.results) && payload.results.length > 0 && (payload.indices || []).length > 0;
      if (healthy) {
        const resp = jsonResponse(payload, CSP_CACHE_SECONDS);
        if (ctx && ctx.waitUntil) ctx.waitUntil(cache.put(goodKey, resp.clone()));
        return resp;
      }
      // Throttled scan: serve the last good cached scan if we have one; otherwise flag
      // it degraded (short TTL) so the page falls back to the static results.json.
      const lastGood = await cache.match(goodKey);
      if (lastGood) return lastGood;
      return jsonResponse({ ...payload, degraded: true }, 30);
    }

    const dbg = [];
    try {
      const key = env && env.FINNHUB_API_KEY ? env.FINNHUB_API_KEY : "";
      const r = await Promise.all([
        getIndices(dbg), movers("gainers", env, dbg), movers("losers", env, dbg), earningsThisWeek(key, dbg), news(key, dbg),
      ]);
      const indices = r[0] || [], gainers = r[1] || [], losers = r[2] || [], earnings_week = r[3] || [], headlines = r[4] || [];
      return jsonResponse({
        build: "gh-1",
        generated_at: new Date().toISOString(),
        summary: summarize(indices),
        indices, gainers, losers, earnings_week, news: headlines,
        has_finnhub: !!key, has_fmp: !!(env && env.FMP_API_KEY),
        debug: dbg,
      }, CACHE_SECONDS);
    } catch (e) {
      return jsonResponse({ error: String(e), debug: dbg }, 30);
    }
  },
};
