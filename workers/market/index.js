/**
 * GlobeSec CSP — "Market Today" Worker (csp-market), deployed from GitHub via Workers Builds.
 *
 * Sources (all optional/graceful, never throws):
 *   - indices ........ CBOE delayed quotes                       [keyless]
 *   - gainers/losers .. FMP (if FMP_API_KEY) else Yahoo          [FMP recommended; Yahoo blocks CF IPs]
 *   - earnings_week ... Finnhub earnings calendar (Mon-Fri)      [needs FINNHUB_API_KEY]
 *   - news ........... Finnhub general market news               [needs FINNHUB_API_KEY]
 *
 * Routes:
 *   /           -> Market Today brief
 *   /scan       -> full CSP scan (shared with the csp Worker)
 *   /watchlist  -> tracked-ticker portfolio: quote, 52wk, market cap, volume, options open interest
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

/* ------------------------------------------------------------------ *
 *  WATCHLIST
 *  Quote/fundamentals come from FMP in ONE batched call. Options open
 *  interest comes from the same keyless CBOE delayed feed the CSP
 *  scanner already uses (one request per underlying), summed inline so
 *  we never hold a full chain longer than we must.
 * ------------------------------------------------------------------ */

const WATCHLIST = [
  { symbol: "VRT",  name: "Vertiv Holdings",         group: "Data-Center Power & Cooling" },
  { symbol: "MOD",  name: "Modine Manufacturing",    group: "Data-Center Power & Cooling" },
  { symbol: "FIX",  name: "Comfort Systems USA",     group: "Data-Center Power & Cooling" },
  { symbol: "TT",   name: "Trane Technologies",      group: "Data-Center Power & Cooling" },
  { symbol: "NVDA", name: "NVIDIA",                  group: "Mega-Cap Tech" },
  { symbol: "GOOG", name: "Alphabet (Class C)",      group: "Mega-Cap Tech" },
  { symbol: "AAPL", name: "Apple",                   group: "Mega-Cap Tech" },
  { symbol: "TSLA", name: "Tesla",                   group: "Mega-Cap Tech" },
  { symbol: "AMZN", name: "Amazon",                  group: "Mega-Cap Tech" },
  { symbol: "TSM",  name: "Taiwan Semiconductor",    group: "Semiconductors & Memory" },
  { symbol: "SKHY", name: "SK hynix (ADR)",          group: "Semiconductors & Memory" },
  { symbol: "MU",   name: "Micron Technology",       group: "Semiconductors & Memory" },
];

const OCC_RE = /^([A-Z]+)(\d{6})([CP])(\d{8})$/;

function r2(x) { return x == null ? null : Math.round(Number(x) * 100) / 100; }

// One FMP call for every symbol -> price, market cap, volume, 52wk, moving averages.
async function watchlistQuotes(env, dbg) {
  const bySym = {};
  if (!(env && env.FMP_API_KEY)) { dbg.push("watchlist: no FMP_API_KEY (price-only via CBOE)"); return bySym; }
  try {
    const syms = WATCHLIST.map((w) => w.symbol).join(",");
    const d = await jget(`https://financialmodelingprep.com/api/v3/quote/${syms}?apikey=${env.FMP_API_KEY}`);
    if (Array.isArray(d) && d.length) { for (const q of d) if (q && q.symbol) bySym[q.symbol] = q; }
    else dbg.push("fmp quote: empty/unauthorized");
  } catch (e) { dbg.push(`fmp quote: ${e}`); }
  return bySym;
}

// Sum open interest across the whole CBOE chain for one underlying.
async function optionInterest(symbol, dbg) {
  try {
    const data = (await jget(`${CBOE}/${symbol}.json`))?.data;
    if (!data) return null;
    let callOI = 0, putOI = 0, optVol = 0, contracts = 0;
    for (const o of data.options || []) {
      const m = OCC_RE.exec(o.option || "");
      if (!m) continue;
      const oi = Number(o.open_interest) || 0;
      optVol += Number(o.volume) || 0;
      contracts++;
      if (m[3] === "P") putOI += oi; else callOI += oi;
    }
    const chg = data.price_change_percent;
    // CBOE reports open_interest/volume as floats; keep the published totals whole.
    return {
      price: Number(data.current_price || data.close || 0) || null,
      change_pct: chg == null || isNaN(Number(chg)) ? null : r2(chg),
      call_oi: Math.round(callOI),
      put_oi: Math.round(putOI),
      total_oi: Math.round(callOI + putOI),
      pc_ratio: callOI > 0 ? Math.round((putOI / callOI) * 100) / 100 : null,
      option_volume: Math.round(optVol),
      contracts,
    };
  } catch (e) { dbg.push(`cboe ${symbol}: ${e}`); return null; }
}

// Chains are large; fetch a few at a time so we never parse 12 at once.
async function inBatches(items, size, fn) {
  const out = [];
  for (let i = 0; i < items.length; i += size) {
    out.push(...(await Promise.all(items.slice(i, i + size).map(fn))));
  }
  return out;
}

async function buildWatchlist(env, dbg) {
  const quotes = await watchlistQuotes(env, dbg);
  const chains = await inBatches(WATCHLIST, 4, (w) => optionInterest(w.symbol, dbg));

  const rows = WATCHLIST.map((w, i) => {
    const q = quotes[w.symbol] || {};
    const oi = chains[i];
    const last = q.price != null ? Number(q.price) : oi && oi.price != null ? oi.price : null;
    const hi = q.yearHigh != null ? Number(q.yearHigh) : null;
    const lo = q.yearLow != null ? Number(q.yearLow) : null;
    // Position of the last trade inside the 52-week band, 0% = at the low.
    const pos = last != null && hi != null && lo != null && hi > lo
      ? Math.max(0, Math.min(100, Math.round(((last - lo) / (hi - lo)) * 100)))
      : null;
    return {
      symbol: w.symbol,
      name: q.name || w.name,
      group: w.group,
      price: r2(last),
      change_pct: q.changesPercentage != null ? r2(q.changesPercentage) : oi ? oi.change_pct : null,
      market_cap: q.marketCap != null ? Number(q.marketCap) : null,
      volume: q.volume != null ? Number(q.volume) : null,
      avg_volume: q.avgVolume != null ? Number(q.avgVolume) : null,
      year_high: r2(hi),
      year_low: r2(lo),
      year_mid: hi != null && lo != null ? r2((hi + lo) / 2) : null,   // 52-week midpoint
      avg_50: q.priceAvg50 != null ? r2(q.priceAvg50) : null,
      avg_200: q.priceAvg200 != null ? r2(q.priceAvg200) : null,       // closest true "52wk average"
      range_pos_pct: pos,
      pe: q.pe != null ? r2(q.pe) : null,
      options: oi
        ? { total_oi: oi.total_oi, call_oi: oi.call_oi, put_oi: oi.put_oi, pc_ratio: oi.pc_ratio, option_volume: oi.option_volume, contracts: oi.contracts }
        : null,
    };
  });

  const groups = [];
  for (const r of rows) {
    let g = groups.find((x) => x.name === r.group);
    if (!g) { g = { name: r.group, rows: [] }; groups.push(g); }
    g.rows.push(r);
  }

  return {
    generated_at: new Date().toISOString(),
    count: rows.length,
    has_fmp: !!(env && env.FMP_API_KEY),
    rows,
    groups,
    debug: dbg,
  };
}

/* ------------------------------------------------------------------ *
 *  SYMBOL STORE (Workers KV)
 *  The watchlist ticker list lives in KV so it can be edited from the
 *  website instead of requiring a commit. The Python data job reads this
 *  same endpoint at build time, so KV is the single source of truth and
 *  symbols.txt is only the seed/fallback.
 *
 *  Reads are public (it is just a list of tickers). Writes require
 *  ADMIN_KEY, because the site itself is public.
 * ------------------------------------------------------------------ */

const SYMBOLS_KEY = "watchlist:symbols";
const TICKER_RE = /^[A-Z][A-Z0-9.-]{0,9}$/;
const MAX_SYMBOLS = 40;   // keeps the data job inside its subrequest budget

const DEFAULT_SYMBOLS = WATCHLIST.map((w) => ({ ticker: w.symbol, name: w.name, group: w.group }));

async function readSymbols(env) {
  if (!env || !env.WATCHLIST_KV) return { symbols: DEFAULT_SYMBOLS, source: "default", kv: false };
  try {
    const raw = await env.WATCHLIST_KV.get(SYMBOLS_KEY);
    if (raw) {
      const list = JSON.parse(raw);
      if (Array.isArray(list) && list.length) return { symbols: list, source: "kv", kv: true };
    }
  } catch (_e) { /* fall through to defaults */ }
  return { symbols: DEFAULT_SYMBOLS, source: "default", kv: true };
}

// Constant-time compare so response timing can't leak the secret char by char.
function sameSecret(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function authorized(request, env) {
  const key = env && env.ADMIN_KEY;
  if (!key) return false;
  return sameSecret(request.headers.get("x-admin-key") || "", key);
}

async function handleSymbols(request, env) {
  const cors = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, x-admin-key",
  };

  if (request.method === "OPTIONS") return new Response(null, { headers: cors });

  if (request.method === "GET") {
    const { symbols, source, kv } = await readSymbols(env);
    return new Response(JSON.stringify({ symbols, source, kv_bound: kv, count: symbols.length }), {
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...cors },
    });
  }

  if (request.method !== "POST") {
    return new Response(JSON.stringify({ error: "method not allowed" }), { status: 405, headers: { "Content-Type": "application/json", ...cors } });
  }

  if (!(env && env.WATCHLIST_KV)) {
    return new Response(JSON.stringify({ error: "KV not bound — add the WATCHLIST_KV namespace to wrangler.toml" }), {
      status: 503, headers: { "Content-Type": "application/json", ...cors },
    });
  }
  if (!(env && env.ADMIN_KEY)) {
    return new Response(JSON.stringify({ error: "ADMIN_KEY is not set on this Worker — add it under Settings → Variables and Secrets" }), {
      status: 503, headers: { "Content-Type": "application/json", ...cors },
    });
  }
  if (!authorized(request, env)) {
    // A deliberately short secret is guessable, so make each wrong guess cost
    // a full second. Brute force stops being practical; a human never notices.
    await new Promise((r) => setTimeout(r, 1000));
    return new Response(JSON.stringify({ error: "wrong password" }), { status: 401, headers: { "Content-Type": "application/json", ...cors } });
  }

  let body;
  try { body = await request.json(); }
  catch (_e) { return new Response(JSON.stringify({ error: "invalid JSON" }), { status: 400, headers: { "Content-Type": "application/json", ...cors } }); }

  const action = String(body.action || "").toLowerCase();
  const ticker = String(body.ticker || "").trim().toUpperCase();
  if (!TICKER_RE.test(ticker)) {
    return new Response(JSON.stringify({ error: `"${ticker}" is not a valid ticker` }), { status: 400, headers: { "Content-Type": "application/json", ...cors } });
  }

  const current = (await readSymbols(env)).symbols.slice();
  let symbols, message;

  if (action === "add") {
    if (current.some((s) => s.ticker === ticker)) {
      return new Response(JSON.stringify({ error: `${ticker} is already on the watchlist` }), { status: 409, headers: { "Content-Type": "application/json", ...cors } });
    }
    if (current.length >= MAX_SYMBOLS) {
      return new Response(JSON.stringify({ error: `watchlist is full (${MAX_SYMBOLS} max)` }), { status: 409, headers: { "Content-Type": "application/json", ...cors } });
    }
    const name = String(body.name || "").trim().slice(0, 48);
    const group = String(body.group || "").trim().slice(0, 40) || "Watchlist";
    symbols = current.concat([{ ticker, name, group }]);
    message = `${ticker} added — prices appear after the next data refresh`;
  } else if (action === "remove") {
    symbols = current.filter((s) => s.ticker !== ticker);
    if (symbols.length === current.length) {
      return new Response(JSON.stringify({ error: `${ticker} is not on the watchlist` }), { status: 404, headers: { "Content-Type": "application/json", ...cors } });
    }
    message = `${ticker} removed`;
  } else {
    return new Response(JSON.stringify({ error: 'action must be "add" or "remove"' }), { status: 400, headers: { "Content-Type": "application/json", ...cors } });
  }

  await env.WATCHLIST_KV.put(SYMBOLS_KEY, JSON.stringify(symbols));
  return new Response(JSON.stringify({ ok: true, message, count: symbols.length, symbols }), {
    headers: { "Content-Type": "application/json", ...cors },
  });
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

    // /watchlist/symbols -> read (public) / edit (ADMIN_KEY) the ticker list.
    if (url.pathname.replace(/\/+$/, "") === "/watchlist/symbols") {
      return handleSymbols(request, env);
    }

    // /watchlist -> tracked-ticker portfolio (edge-cached like the scan).
    if (url.pathname.replace(/\/+$/, "") === "/watchlist") {
      const cache = caches.default;
      const nocache = url.searchParams.has("nocache");
      const wKey = new Request("https://globesec.ai/__cache/watchlist", { method: "GET" });
      if (!nocache) { const hit = await cache.match(wKey); if (hit) return hit; }
      const wdbg = [];
      let payload;
      try { payload = await buildWatchlist(env, wdbg); }
      catch (e) { return jsonResponse({ error: String(e), rows: [], groups: [], debug: wdbg }, 30); }
      // Only cache a run where we actually priced something.
      const healthy = (payload.rows || []).some((r) => r.price != null);
      if (!healthy) return jsonResponse({ ...payload, degraded: true }, 30);
      const resp = jsonResponse(payload, CACHE_SECONDS);
      if (ctx && ctx.waitUntil) ctx.waitUntil(cache.put(wKey, resp.clone()));
      return resp;
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
