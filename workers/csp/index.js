/**
 * GlobeSec CSP — live cash-secured-put scanner Worker (csp-scan).
 * Deployed from GitHub via Workers Builds (root dir = workers/csp).
 *
 * Replaces the GitHub Action + committed results.json: this computes the whole
 * scan on request, straight from CBOE's free delayed-quotes feed, and edge-caches
 * it for CACHE_SECONDS so page loads are instant and CBOE isn't hammered. The page
 * just fetches this endpoint — no commit, no Pages rebuild, no cache purge.
 *
 * Port of csp/scanner/{cboe,scanner,fundamentals,market}.py. Output JSON shape is
 * identical to the old results.json so csp/index.html renders it unchanged.
 *
 * Subrequest budget (Workers cap: 50 free / 1000 paid per invocation):
 *   3 indices + N chains + 1 FMP batch.  Keep UNIVERSE under ~46 on the free plan.
 *   A full CSP scan also does real CPU work parsing N option chains — if you want a
 *   much larger universe, run on Workers Paid (30s CPU) and raise UNIVERSE.
 */

// ---- screen criteria (mirror of scanner/config.py) ----
const MAX_UNDERLYING_PRICE = 300.0;
const DTE_MIN = 21, DTE_MAX = 45;
const NORMALIZE_DAYS = 30;
const TARGET_YIELD_MIN = 0.70, TARGET_YIELD_MAX = 1.00;   // 30-day normalized yield band (%)
const MAX_ABS_DELTA = 0.35;
const MIN_OPEN_INTEREST = 50;
const MIN_BID = 0.05;
const TOP_N = 20;
const ACCOUNT_WEEKS = 2;                                   // pick horizon for buckets

// ---- capital buckets ($300K split; amounts are internal, never published) ----
const TOTAL_CAPITAL = 300000.0;
const BUCKETS = [
  { name: "Bucket 1", balance: 22000.0 },
  { name: "Bucket 2", balance: 100000.0 },
  { name: "Bucket 3", balance: 50000.0 },
];
BUCKETS.push({ name: "Bucket 4", balance: round2(TOTAL_CAPITAL - BUCKETS.reduce((a, b) => a + b.balance, 0)) });

// stocks you're happy to own if assigned (wheel) — always evaluated for picks
const PREFERRED = new Set(["DAL", "NVDA", "AMZN", "ORCL", "INTC", "OSS", "SMCI"]);

// Curated "Top Picks" buy ideas (under $80, diversified beaten-up sectors + growth).
// Each gets a ~30-delta cash-secured-put entry computed live. Edit this list to
// change what shows in the Top Picks section.
const TOP_PICKS = [
  { symbol: "PFE", sector: "Healthcare", thesis: "Pharma value; high dividend, low P/E" },
  { symbol: "BAC", sector: "Financials", thesis: "Quality diversified bank; rate beneficiary" },
  { symbol: "GM", sector: "Autos", thesis: "Deep value; very low P/E, big buybacks" },
  { symbol: "KMI", sector: "Energy", thesis: "Pipeline fee cash flows; steady income" },
  { symbol: "NU", sector: "Fintech", thesis: "LatAm digital bank; profitable growth" },
];

// Curated liquid, optionable, usually-sub-$300 universe (watchlist first). The
// <$300 filter is applied live, so a name that pops above $300 is simply dropped.
const UNIVERSE = [
  "DAL", "NVDA", "AMZN", "ORCL", "INTC", "OSS", "SMCI",
  "AAPL", "AMD", "MU", "PLTR", "SOFI", "F", "BAC", "T", "NIO", "MARA", "HOOD",
  "SNAP", "PFE", "CSCO", "KO", "DIS", "UBER", "CCL", "AAL", "GM", "WBD", "RIVN",
  "LCID", "COIN", "BABA", "NU", "ET", "KMI", "VZ", "WBA", "GME", "AMC", "WMT",
];

const CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/options";
const UA = "Mozilla/5.0 (globesec-csp-worker)";
const CACHE_SECONDS = 600;
const INDICES = [["S&P 500", "_SPX", 1], ["Dow Jones", "_DJX", 100], ["Nasdaq 100", "_NDX", 1]];
const OCC = /^([A-Z]+)(\d{6})([CP])(\d{8})$/;

function round2(x) { return Math.round(x * 100) / 100; }
function round3(x) { return Math.round(x * 1000) / 1000; }

async function jget(url) {
  const r = await fetch(url, { headers: { "User-Agent": UA, Accept: "application/json" }, cf: { cacheTtl: 60, cacheEverything: true } });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

// ---- CBOE chain: one request per underlying -> {price, change_pct, options[]} ----
async function getChain(symbol) {
  try {
    const data = (await jget(`${CBOE}/${symbol}.json`))?.data || {};
    const price = Number(data.current_price || data.close || 0) || 0;
    let chg = data.price_change_percent;
    chg = (chg === null || chg === undefined || isNaN(Number(chg))) ? null : Number(chg);
    const options = [];
    for (const o of data.options || []) {
      const m = OCC.exec(o.option || "");
      if (!m) continue;
      const ymd = m[2];
      options.push({
        option_symbol: o.option,
        type: m[3] === "P" ? "put" : "call",
        strike: parseInt(m[4], 10) / 1000.0,
        expiration: `20${ymd.slice(0, 2)}-${ymd.slice(2, 4)}-${ymd.slice(4, 6)}`,
        bid: o.bid,
        delta: o.delta,
        open_interest: o.open_interest || 0,
      });
    }
    return { symbol, price, change_pct: chg, options };
  } catch (_e) {
    return null;
  }
}

function dte(expISO, todayMs) {
  return Math.round((Date.parse(expISO + "T00:00:00Z") - todayMs) / 86400000);
}

// ISO-week key (isoYear*100 + week) so end-of-week expirations group/sort correctly.
function isoWeekKey(expISO) {
  const d = new Date(expISO + "T00:00:00Z");
  const day = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - day + 3);            // nearest Thursday
  const thursday = d.getTime();
  const isoYear = d.getUTCFullYear();
  const jan1 = new Date(Date.UTC(isoYear, 0, 1));
  const week = 1 + Math.round((thursday - jan1.getTime()) / 86400000 / 7);
  return isoYear * 100 + week;
}

// ---- main per-underlying screen (mirror of scanner._eval_underlying) ----
function evalUnderlying(chain, todayMs) {
  const price = chain.price;
  if (price <= 0 || price >= MAX_UNDERLYING_PRICE) return [];
  const rows = [];
  for (const o of chain.options) {
    if (o.type !== "put") continue;
    if (o.strike == null || o.bid == null) continue;
    const strike = Number(o.strike), bid = Number(o.bid);
    if (strike <= 0 || bid < MIN_BID) continue;
    if (strike >= price) continue;                  // OTM puts only
    const d = dte(o.expiration, todayMs);
    if (d <= 0 || d < DTE_MIN || d > DTE_MAX) continue;
    if (o.delta != null && Math.abs(Number(o.delta)) > MAX_ABS_DELTA) continue;
    const oi = o.open_interest || 0;
    if (oi < MIN_OPEN_INTEREST) continue;
    const rawYield = bid / strike;
    const yield30 = rawYield * (NORMALIZE_DAYS / d) * 100.0;
    if (yield30 < TARGET_YIELD_MIN || yield30 > TARGET_YIELD_MAX) continue;
    rows.push({
      symbol: chain.symbol,
      option_symbol: o.option_symbol,
      price: round2(price),
      expiration: o.expiration,
      dte: d,
      strike: round2(strike),
      bid: round2(bid),
      delta: o.delta != null ? round3(Number(o.delta)) : null,
      open_interest: Math.trunc(oi),
      collateral: round2(strike * 100),
      premium: round2(bid * 100),
      yield_30d_pct: round3(yield30),
      annualized_pct: round2(rawYield * (365.0 / d) * 100.0),
    });
  }
  return rows;
}

// ---- click-to-expand weekly ladder (mirror of scanner.build_weeklies) ----
function buildWeeklies(chain, todayMs, weeksAhead = 3, perWeek = 3) {
  const byExp = {};
  for (const o of chain.options) {
    if (o.type !== "put") continue;
    if (dte(o.expiration, todayMs) < 1) continue;
    (byExp[o.expiration] = byExp[o.expiration] || []).push(o);
  }
  const weeks = {};
  for (const exp of Object.keys(byExp)) {
    const k = isoWeekKey(exp);
    if (!(k in weeks) || exp > weeks[k]) weeks[k] = exp;
  }
  const chosen = Object.keys(weeks).map(Number).sort((a, b) => a - b).slice(0, weeksAhead).map((k) => weeks[k]);
  const price = chain.price;
  const out = [];
  for (const exp of chosen) {
    const d = dte(exp, todayMs);
    let cands = [];
    for (const o of byExp[exp]) {
      if (o.strike == null || o.bid == null) continue;
      const strike = Number(o.strike), bid = Number(o.bid);
      if (bid <= 0 || strike >= price) continue;     // OTM only
      const pct = (bid / strike) * 100;
      if (pct < TARGET_YIELD_MIN || pct > TARGET_YIELD_MAX) continue;
      cands.push({
        strike: round2(strike),
        bid: round2(bid),
        premium: round2(bid * 100),
        pct_of_collateral: round3(pct),
        delta: o.delta != null ? round3(Number(o.delta)) : null,
        open_interest: Math.trunc(o.open_interest || 0),
        recommended: false,
      });
    }
    cands.sort((a, b) => (a.delta != null ? Math.abs(a.delta) : price - a.strike) - (b.delta != null ? Math.abs(b.delta) : price - b.strike));
    cands = cands.slice(0, perWeek);
    if (cands.length) cands[0].recommended = true;
    out.push({ expiration: exp, dte: d, puts: cands });
  }
  return out;
}

// ---- per-bucket pick (mirror of scanner.build_account_picks; no $ capital fields) ----
function buildAccountPicks(rows) {
  const cands = [];
  for (const r of rows) {
    for (const w of (r.weeklies || []).slice(0, ACCOUNT_WEEKS)) {
      for (const p of w.puts) {
        cands.push({
          symbol: r.symbol,
          preferred: !!r.preferred,
          company_name: r.company_name ?? null,
          price: r.price ?? null,
          expiration: w.expiration,
          dte: w.dte,
          strike: p.strike,
          bid: p.bid,
          premium: p.premium,
          pct_of_collateral: p.pct_of_collateral,
          delta: p.delta,
          open_interest: p.open_interest,
          collateral: round2(p.strike * 100),
        });
      }
    }
  }
  const risk = (p) => (p.delta != null ? Math.abs(p.delta) : 1.0);
  // Keep every bucket on a DIFFERENT stock so they don't all sour together.
  // Allocate the smallest bucket first (fewest affordable choices), reserve each
  // chosen symbol, and emit in the configured display order.
  const taken = new Set();
  const picks = new Array(BUCKETS.length).fill(null);
  const order = BUCKETS.map((b, i) => i).sort((a, b) => BUCKETS[a].balance - BUCKETS[b].balance);
  for (const bi of order) {
    const acct = BUCKETS[bi];
    const bal = acct.balance;
    const sized = [];
    for (const c of cands) {
      if (taken.has(c.symbol)) continue;          // distinct symbol per bucket
      if (c.collateral > bal) continue;
      const contracts = Math.floor(bal / c.collateral);
      if (contracts < 1) continue;
      const totalPremium = round2(contracts * c.premium);
      const used = contracts * c.collateral;
      sized.push({
        ...c,
        contracts,
        total_premium: totalPremium,
        utilization_pct: round2(used / bal * 100) > 100 ? 100 : Math.round(used / bal * 1000) / 10,
        // only percentages are published — absolute capital is intentionally omitted
        account_yield_pct: round3(totalPremium / bal * 100),
      });
    }
    const meeting = sized.filter((p) => p.account_yield_pct >= TARGET_YIELD_MIN);
    const prefMeeting = meeting.filter((p) => p.preferred);
    let best = null;
    if (prefMeeting.length) {
      best = prefMeeting.reduce((a, b) => (b.account_yield_pct > a.account_yield_pct || (b.account_yield_pct === a.account_yield_pct && risk(b) < risk(a)) ? b : a));
    } else if (meeting.length) {
      best = meeting.reduce((a, b) => (risk(b) < risk(a) || (risk(b) === risk(a) && b.account_yield_pct > a.account_yield_pct) ? b : a));
    } else if (sized.length) {
      best = sized.reduce((a, b) => (b.account_yield_pct > a.account_yield_pct ? b : a));
    }
    if (best) { best.meets_target = best.account_yield_pct >= TARGET_YIELD_MIN; taken.add(best.symbol); }
    picks[bi] = { account: acct.name, pick: best };
  }
  return picks;
}

// ---- biggest decliners among the scanned universe (mirror of build_losers) ----
function buildLosers(chains, fund, topN = 10) {
  let movers = [];
  for (const c of chains) {
    if (c.change_pct == null || c.change_pct >= 0 || c.price <= 0) continue;
    movers.push({ symbol: c.symbol, price: round2(c.price), change_pct: round2(c.change_pct) });
  }
  movers.sort((a, b) => a.change_pct - b.change_pct);
  movers = movers.slice(0, topN);
  for (const m of movers) {
    const f = fund[m.symbol] || {};
    const hi = f.week52_high ?? null;
    m.company_name = f.name ?? null;
    m.pe = f.pe ?? null;
    m.week52_high = hi;
    m.week52_low = f.week52_low ?? null;
    m.pct_below_high = hi ? round2((hi - m.price) / hi * 100) : null;
    m.preferred = PREFERRED.has(m.symbol);
  }
  return movers;
}

// ---- "Top Picks": a ~30-delta CSP entry for each curated buy idea ----
function buildTopPicks(chainBySym, todayMs) {
  const out = [];
  for (const tp of TOP_PICKS) {
    const ch = chainBySym[tp.symbol];
    if (!ch || ch.price <= 0) { out.push({ ...tp, available: false }); continue; }
    const spot = ch.price;
    const cands = [];
    for (const o of ch.options) {
      if (o.type !== "put" || o.strike == null || o.bid == null) continue;
      const k = Number(o.strike), bid = Number(o.bid);
      const d = dte(o.expiration, todayMs);
      if (d < 25 || d > 50 || k >= spot || bid <= 0) continue;     // OTM, ~monthly
      const dl = o.delta != null ? Math.abs(Number(o.delta)) : null;
      cands.push({ k, bid, dl, d, exp: o.expiration, oi: Math.trunc(o.open_interest || 0) });
    }
    if (!cands.length) { out.push({ ...tp, price: round2(spot), available: false }); continue; }
    // pick the strike nearest ~0.30 delta (fallback: ~7% OTM by distance)
    const target = (x) => Math.abs((x.dl != null ? x.dl : (spot - x.k) / spot) - 0.30);
    cands.sort((a, b) => target(a) - target(b));
    const c = cands[0];
    const buyin = c.k - c.bid;
    const yld = (c.bid / c.k) * 100;
    out.push({
      ...tp, available: true,
      price: round2(spot), strike: round2(c.k), expiration: c.exp, dte: c.d,
      bid: round2(c.bid), premium: round2(c.bid * 100),
      delta: c.dl != null ? round3(c.dl) : null, open_interest: c.oi,
      collateral: round2(c.k * 100), buyin: round2(buyin),
      discount_pct: round2(((spot - buyin) / spot) * 100),
      yield_pct: round3(yld), annualized_pct: round2(yld * (365 / c.d)),
    });
  }
  return out;
}

async function getIndices(dbg) {
  const out = await Promise.all(INDICES.map(async ([label, sym, mult]) => {
    try {
      const d = (await jget(`${CBOE}/${sym}.json`))?.data || {};
      if (!d.current_price) return null;
      const chg = d.price_change_percent;
      return { label, value: round2(Number(d.current_price) * mult), change_pct: chg == null ? null : round2(Number(chg)) };
    } catch (e) { dbg.push(`index ${sym}: ${e}`); return null; }
  }));
  return out.filter(Boolean);
}

// ---- fundamentals via FMP batch quote (one subrequest); graceful without a key ----
async function getFundamentals(symbols, env, dbg) {
  const empty = {};
  for (const s of symbols) empty[s] = { name: null, pe: null, week52_low: null, week52_high: null };
  if (!env || !env.FMP_API_KEY || !symbols.length) return empty;
  try {
    const d = await jget(`https://financialmodelingprep.com/api/v3/quote/${symbols.join(",")}?apikey=${env.FMP_API_KEY}`);
    for (const q of Array.isArray(d) ? d : []) {
      if (!q.symbol) continue;
      empty[q.symbol] = {
        name: q.name || null,
        pe: q.pe != null ? round2(Number(q.pe)) : null,
        week52_low: q.yearLow ?? null,
        week52_high: q.yearHigh ?? null,
      };
    }
  } catch (e) { dbg.push(`fmp: ${e}`); }
  return empty;
}

export async function runScan(env, dbg) {
  const todayMs = Date.parse(new Date().toISOString().slice(0, 10) + "T00:00:00Z");

  // Fetch chains in small concurrent batches (not all at once) so CBOE doesn't
  // throttle the burst from a single Cloudflare colo and return partial data.
  const POOL = 8;
  const settled = [];
  for (let i = 0; i < UNIVERSE.length; i += POOL) {
    settled.push(...await Promise.all(UNIVERSE.slice(i, i + POOL).map(getChain)));
    if (i + POOL < UNIVERSE.length) await new Promise((r) => setTimeout(r, 120));
  }
  const chains = settled.filter((c) => c && c.price > 0 && c.price < MAX_UNDERLYING_PRICE);

  let allRows = [];
  for (const c of chains) allRows = allRows.concat(evalUnderlying(c, todayMs));
  const totalFound = allRows.length;

  // rank by premium ($), then yield; keep one (best) row per symbol, top N
  allRows.sort((a, b) => b.premium - a.premium || b.yield_30d_pct - a.yield_30d_pct);
  const seen = new Set();
  let rows = [];
  for (const r of allRows) { if (seen.has(r.symbol)) continue; seen.add(r.symbol); rows.push(r); }
  rows = rows.slice(0, TOP_N);

  const chainBySym = {};
  for (const c of chains) chainBySym[c.symbol] = c;

  // watchlist names that didn't crack the top-N are still evaluated for bucket picks
  const present = new Set(rows.map((r) => r.symbol));
  const extraWatch = [...PREFERRED].filter((s) => chainBySym[s] && !present.has(s));

  const fundSyms = [...new Set([...rows.map((r) => r.symbol), ...extraWatch, ...chains.map((c) => c.symbol)])];
  const fund = await getFundamentals(fundSyms, env, dbg);

  for (const r of rows) {
    r.preferred = PREFERRED.has(r.symbol);
    const f = fund[r.symbol] || {};
    r.company_name = f.name ?? null;
    r.pe = f.pe ?? null;
    r.week52_low = f.week52_low ?? null;
    r.week52_high = f.week52_high ?? null;
    r.weeklies = buildWeeklies(chainBySym[r.symbol], todayMs);
  }

  const extraRows = extraWatch.map((s) => {
    const c = chainBySym[s], f = fund[s] || {};
    return {
      symbol: s, preferred: true, price: round2(c.price),
      company_name: f.name ?? null, pe: f.pe ?? null,
      week52_low: f.week52_low ?? null, week52_high: f.week52_high ?? null,
      weeklies: buildWeeklies(c, todayMs),
    };
  });

  const accountPicks = buildAccountPicks(rows.concat(extraRows));
  const topPicks = buildTopPicks(chainBySym, todayMs);
  const losers = buildLosers(chains, fund);
  const indices = await getIndices(dbg);

  return {
    generated_at: new Date().toISOString().slice(0, 19),
    data_source: "CBOE delayed (~15 min)",
    account_picks: accountPicks,
    top_picks: topPicks,
    losers,
    indices,
    params: {
      max_underlying_price: MAX_UNDERLYING_PRICE,
      dte_window: [DTE_MIN, DTE_MAX],
      yield_band_30d_pct: [TARGET_YIELD_MIN, TARGET_YIELD_MAX],
      max_abs_delta: MAX_ABS_DELTA,
      min_open_interest: MIN_OPEN_INTEREST,
      top_n: TOP_N,
      sorted_by: "premium",
    },
    universe_size: UNIVERSE.length,
    scanned_under_price: chains.length,
    total_qualifying: totalFound,
    result_count: rows.length,
    results: rows,
    debug: dbg,
  };
}

function jsonResponse(obj, seconds) {
  return new Response(JSON.stringify(obj), {
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": `public, max-age=${seconds}`,
    },
  });
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS" } });
    }
    const cache = caches.default;
    const url = new URL(request.url);
    const nocache = url.searchParams.has("nocache");
    const cacheKey = new Request("https://globesec.ai/__cache/csp-scan", { method: "GET" });

    if (!nocache) {
      const hit = await cache.match(cacheKey);
      if (hit) return hit;
    }

    const dbg = [];
    let resp;
    try {
      resp = jsonResponse(await runScan(env, dbg), CACHE_SECONDS);
    } catch (e) {
      return jsonResponse({ error: String(e), debug: dbg, results: [] }, 30);
    }
    if (!nocache && ctx && ctx.waitUntil) ctx.waitUntil(cache.put(cacheKey, resp.clone()));
    return resp;
  },
};
