/**
 * Cloudflare Pages Functions middleware — access gate for /csp/*.
 *
 * Rules (first match wins):
 *   1. Visitor IP is in CSP_ALLOWED_IPS  -> allowed, no password (your home).
 *   2. Valid auth cookie present         -> allowed (set by #3 or #4).
 *   3. URL has ?key=<CSP_DEVICE_KEY>     -> set a 1-year cookie, then allowed.
 *                                           (Your iPhone: open the link once, bookmark /csp/.)
 *   4. Correct password POSTed           -> set cookie, allowed (everyone else).
 *   5. Otherwise                         -> show the password page (HTTP 401).
 *
 * Configure in Cloudflare dashboard -> Pages project -> Settings -> Variables and
 * Secrets (Production):
 *   CSP_PASSWORD     shared password for "others"   (required to arm the gate)
 *   CSP_ALLOWED_IPS  your home IP(s), comma-separated
 *   CSP_DEVICE_KEY   long random string for the iPhone bookmark link
 *
 * SAFETY: if CSP_PASSWORD is unset the gate fails OPEN (page stays public), so a
 * deploy can't lock you out before you've configured it.
 */

const COOKIE = "csp_auth";
const ONE_YEAR = 60 * 60 * 24 * 365;

async function authToken(secret) {
  const data = new TextEncoder().encode("globesec-csp|v1|" + secret);
  const buf = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function parseCookies(header) {
  const out = {};
  (header || "").split(/;\s*/).forEach((kv) => {
    const i = kv.indexOf("=");
    if (i > 0) out[kv.slice(0, i).trim()] = kv.slice(i + 1);
  });
  return out;
}

function setCookie(value) {
  return `${COOKIE}=${value}; Path=/csp; Max-Age=${ONE_YEAR}; HttpOnly; Secure; SameSite=Lax`;
}

function loginPage(msg) {
  const body = `<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>GlobeSec CSP — Restricted</title>
<style>
 body{font-family:system-ui,"Segoe UI",Arial,sans-serif;background:#0b1220;color:#e6edf6;display:grid;place-items:center;min-height:100vh;margin:0}
 form{background:#121a2b;padding:2rem;border-radius:14px;box-shadow:0 10px 40px rgba(0,0,0,.45);width:min(92vw,340px)}
 h1{font-size:1.15rem;margin:0 0 .25rem}
 p{color:#9fb0c8;font-size:.85rem;margin:.25rem 0 1.1rem}
 input{width:100%;box-sizing:border-box;padding:.75rem;border-radius:9px;border:1px solid #2a3a55;background:#0b1220;color:#e6edf6;font-size:1rem}
 button{width:100%;margin-top:.85rem;padding:.75rem;border:0;border-radius:9px;background:#2f6df6;color:#fff;font-size:1rem;cursor:pointer}
 button:hover{background:#255fe0}
 .err{color:#ff6b6b;font-size:.82rem;min-height:1.1em;margin-top:.4rem}
</style></head><body>
<form method="POST" autocomplete="on">
 <h1>Restricted page</h1>
 <p>This page is private. Enter the access password to continue.</p>
 <input type="password" name="password" autofocus autocomplete="current-password" placeholder="Password" aria-label="Password">
 <div class="err">${msg || ""}</div>
 <button type="submit">Enter</button>
</form></body></html>`;
  return new Response(body, {
    status: 401,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
  });
}

export async function onRequest(context) {
  const { request, env, next } = context;

  // Gate not armed yet -> let everyone through (don't lock out before setup).
  if (!env.CSP_PASSWORD) return next();

  const url = new URL(request.url);
  const expected = await authToken(env.CSP_PASSWORD);

  // 1. Home IP allowlist
  const ip = request.headers.get("CF-Connecting-IP") || "";
  const allowed = (env.CSP_ALLOWED_IPS || "").split(",").map((s) => s.trim()).filter(Boolean);
  if (ip && allowed.includes(ip)) return next();

  // 2. Valid auth cookie
  const cookies = parseCookies(request.headers.get("Cookie"));
  if (cookies[COOKIE] === expected) return next();

  // 3. Device-key link (iPhone): /csp/?key=...  -> set cookie, redirect to clean URL
  if (env.CSP_DEVICE_KEY && url.searchParams.get("key") === env.CSP_DEVICE_KEY) {
    url.searchParams.delete("key");
    const dest = url.pathname + (url.search ? url.search : "");
    return new Response(null, { status: 302, headers: { Location: dest, "Set-Cookie": setCookie(expected) } });
  }

  // 4. Password submitted
  if (request.method === "POST") {
    let pw = "";
    if ((request.headers.get("Content-Type") || "").includes("application/x-www-form-urlencoded")) {
      const form = await request.formData();
      pw = form.get("password") || "";
    }
    if (pw && pw === env.CSP_PASSWORD) {
      return new Response(null, { status: 303, headers: { Location: "/csp/", "Set-Cookie": setCookie(expected) } });
    }
    return loginPage("Incorrect password.");
  }

  // 5. Show the password page
  return loginPage("");
}
