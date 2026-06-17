/**
 * GlobeSec CSP — "Market Today" Worker.
 *
 * Aggregates a daily market brief, served live with a ~10-minute edge cache:
 *   - indices ........ CBOE delayed quotes (S&P / Dow / Nasdaq)         [keyless]
 *   - gainers/losers .. Yahoo predefined screener (market-wide top 10)  [keyless]
 *   - earnings_week ... Finnhub earnings calendar (Mon-Fri)            [needs FINNHUB_API_KEY]
 *   - news ........... Finnhub general market news                     [needs FINNHUB_API_KEY]
 *
 * Works without any key (indices + movers). Set a Worker variable named
 * FINNHUB_API_KEY (Settings -> Variables) to enable earnings + news.
 *
 * Deploy: paste into a new Worker named e.g. "csp-market".
 */

const CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/options";
const YH = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved";
const UA = "Mozilla/5.0 (globesec-csp-worker)";
const CACHE_SECONDS = 600; // 10 min

const INDICES = [
  ["S&P 500", "_SPX", 1],
  ["Dow Jones", "_DJX", 100],
  ["Nasdaq 100", "_NDX", 1],
];

async function jget(url, opts = {}) {
  const r = await fetch(url, {
    headers: { "User-Agent": UA, Accept: "application/json" },
    cf: { cacheTtl: 60, cacheEverything: true },
    ...opts,
  });
  if (!r.ok) throw new Error("HTTP " + r.status + " " + url);
  return r.json();
}

async function getIndices() {
  const out = await Promise.all(
    INDICES.map(async ([label, sym, mult]) => {
      try {
        const d = (await jget(`${CBOE}/${sym}.json`))?.data || {};
        if (!d.current_price) return null;
        const chg = d.price_change_percent;
        return {
          label,
          value: Math.round(Number(d.current_price) * mult * 100) / 100,
          change_pct: chg == null ? null : Math.round(Number(chg) * 100) / 100,
        };
      } catch (_e) {
        return null;
      }
    })
  );
  return out.filter(Boolean);
}

async function movers(scrId) {
  try {
    const d = await jget(`${YH}?count=10&scrIds=${scrId}`);
    const quotes = d?.finance?.result?.[0]?.quotes || [];
    return quotes.slice(0, 10).map((q) => ({
      symbol: q.symbol,
      name: q.shortName || q.longName || q.symbol,
      price: q.regularMarketPrice ?? null,
      change_pct:
        q.regularMarketChangePercent == null
          ? null
          : Math.round(Number(q.regularMarketChangePercent) * 100) / 100,
    }));
  } catch (_e) {
    return [];
  }
}

function isoDate(d) {
  return d.toISOString().slice(0, 10);
}

async function earningsThisWeek(key) {
  if (!key) return [];
  try {
    const now = new Date();
    const day = now.getUTCDay(); // 0 Sun .. 6 Sat
    const monday = new Date(now);
    monday.setUTCDate(now.getUTCDate() - ((day + 6) % 7)); // back to Monday
    const friday = new Date(monday);
    friday.setUTCDate(monday.getUTCDate() + 4);
    const url = `https://finnhub.io/api/v1/calendar/earnings?from=${isoDate(monday)}&to=${isoDate(friday)}&token=${key}`;
    const d = await jget(url);
    const rows = (d?.earningsCalendar || [])
      .filter((e) => e.symbol && /^[A-Z]{1,5}$/.test(e.symbol)) // drop noisy/foreign tickers
      .map((e) => ({
        symbol: e.symbol,
        date: e.date,
        hour: e.hour || "",
        eps_estimate: e.epsEstimate ?? null,
      }));
    // keep names with an EPS estimate first (proxy for "followed" companies), cap the list
    rows.sort((a, b) => (b.eps_estimate != null) - (a.eps_estimate != null) || a.date.localeCompare(b.date));
    return rows.slice(0, 40);
  } catch (_e) {
    return [];
  }
}

async function news(key) {
  if (!key) return [];
  try {
    const d = await jget(`https://finnhub.io/api/v1/news?category=general&token=${key}`);
    return (d || []).slice(0, 8).map((n) => ({
      headline: n.headline,
      source: n.source,
      url: n.url,
      datetime: n.datetime ? new Date(n.datetime * 1000).toISOString() : null,
    }));
  } catch (_e) {
    return [];
  }
}

function summarize(indices) {
  const withChg = indices.filter((i) => i.change_pct != null);
  if (!withChg.length) return "Market data is loading.";
  const up = withChg.filter((i) => i.change_pct > 0).length;
  const down = withChg.filter((i) => i.change_pct < 0).length;
  if (up === withChg.length) return "U.S. markets are broadly higher today.";
  if (down === withChg.length) return "U.S. markets are broadly lower today.";
  return up >= down ? "U.S. markets are mostly higher today." : "U.S. markets are mostly lower today.";
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS" },
      });
    }

    const cache = caches.default;
    const cacheKey = new Request("https://globesec.ai/__cache/market", { method: "GET" });
    let hit = await cache.match(cacheKey);
    if (hit) return hit;

    const key = env && env.FINNHUB_API_KEY ? env.FINNHUB_API_KEY : "";
    const [indices, gainers, losers, earnings_week, headlines] = await Promise.all([
      getIndices(),
      movers("day_gainers"),
      movers("day_losers"),
      earningsThisWeek(key),
      news(key),
    ]);

    const body = JSON.stringify({
      generated_at: new Date().toISOString(),
      summary: summarize(indices),
      indices,
      gainers,
      losers,
      earnings_week,
      news: headlines,
      has_finnhub: !!key,
    });

    const resp = new Response(body, {
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": `public, max-age=${CACHE_SECONDS}`,
      },
    });
    await cache.put(cacheKey, resp.clone());
    return resp;
  },
};
