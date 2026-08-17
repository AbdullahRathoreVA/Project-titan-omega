/**
 * titanomega-ai.com  ->  the Hugging Face Space, on Cloudflare's free plan.
 *
 * WHY THIS EXISTS
 * Hugging Face supports custom domains natively, but only on PRO / Team /
 * Enterprise (docs: "This feature is part of PRO or Team & Enterprise plans").
 * PRO is $9/month, roughly 30,000 PKR a year — about twice the entire project
 * budget. This Worker does the same job on the free plan: 100,000 requests/day,
 * free SSL, no HF upgrade.
 *
 * WHAT IT DOES
 * Reverse-proxies every request to the Space and streams the response straight
 * back. It is deliberately a proxy, not a redirect: a 301 to *.hf.space would
 * show visitors the Hugging Face URL in the address bar, which defeats the
 * point of buying a domain.
 *
 * THINGS THAT WOULD BREAK IF DONE NAIVELY, AND ARE HANDLED HERE
 *
 *  - Server-Sent Events. Titan's live dashboard uses /api/stream via
 *    EventSource. Buffering it would make the feed arrive in one lump when the
 *    connection closes, i.e. never. Response bodies are passed through
 *    unbuffered so streaming survives.
 *
 *  - The Host header. HF routes by Host; forwarding titanomega-ai.com makes it
 *    404. The upstream host is set explicitly.
 *
 *  - Automatic decompression. Rewriting or re-encoding the body would corrupt
 *    the Next.js chunks. The body is never touched.
 *
 *  - Redirect loops. `redirect: "manual"` keeps HF's own redirects intact
 *    rather than following them to the .hf.space origin and leaking it.
 *
 * DEPLOY
 *   Cloudflare dashboard -> Workers & Pages -> Create -> Worker
 *   Paste this file, Deploy, then Settings -> Domains & Routes -> Add custom
 *   domain -> titanomega-ai.com  (and again for www.titanomega-ai.com).
 *   Cloudflare issues the certificate automatically; no DNS record to add by
 *   hand, because adding a Worker custom domain creates it for you.
 *
 * COST: 0. Free plan allows 100k requests/day.
 */

const UPSTREAM = "careermind2026-project-titan-omega.hf.space";

/**
 * Security headers.
 *
 * Titan is sold on legal compliance. A padlock-less address bar on the product
 * that tells other businesses to fix their security is not survivable, and
 * before this the site served real content over plain HTTP with none of these
 * headers set.
 *
 * The CSP is only this strict because the app was measured to be entirely
 * same-origin: no CDN, no external script, no eval, no WebAssembly.
 *
 * Two allowances are deliberate, not laziness:
 *
 *  - 'unsafe-inline' for script/style. Next.js static export inlines its
 *    hydration payload, and Tailwind injects styles at runtime. Nonces would be
 *    the correct fix, but issuing one requires rewriting the HTML body in this
 *    Worker — and rewriting the body breaks the streaming pass-through that
 *    keeps Server-Sent Events working. Blocking EXTERNAL script injection is
 *    the majority of the value and costs nothing.
 *
 *  - frame-ancestors permits huggingface.co. The Space is legitimately viewed
 *    inside HF's iframe; 'none' would have broken the existing deployment while
 *    looking like a security win.
 *
 * img-src allows any https origin because client logos are supplied by the
 * clients themselves and live on their own domains.
 */
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  // Audio was blocked in production and nobody noticed, because a blocked
  // media load fails silently — the boot chime, speak(), speakPremium() and
  // the Urdu voice assistant all went quiet. `media-src` was simply absent, so
  // it fell back to `default-src 'self'`, and Titan generates its audio as
  // `data:audio/wav` (browser speech) and `blob:` (fetched TTS) — neither of
  // which is 'self'. Same two schemes img-src already allows, and for the same
  // reason: the bytes are produced by this page, not fetched from a stranger.
  // Found in the browser console, not by a test: no test can see a CSP header
  // that the Worker adds in front of the app.
  "media-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "worker-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'self' https://huggingface.co https://*.hf.space",
  "upgrade-insecure-requests",
].join("; ");

const SECURITY_HEADERS = {
  // One year. No `preload` on purpose: preloading is a one-way door that
  // requires a browser-vendor submission to undo, and this domain is days old.
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  // Microphone stays enabled for same-origin: the Urdu voice assistant needs
  // it. Everything else is switched off.
  "Permissions-Policy":
    "camera=(), geolocation=(), payment=(), usb=(), microphone=(self)",
  "Content-Security-Policy": CSP,
};

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // Serving real content over plain HTTP is exactly why browsers showed
    // "Not secure". Cloudflare terminates TLS, so the client's original scheme
    // arrives in cf-visitor rather than in request.url; check both.
    let scheme = url.protocol.replace(":", "");
    try {
      const visitor = request.headers.get("cf-visitor");
      if (visitor) scheme = JSON.parse(visitor).scheme || scheme;
    } catch {
      /* header absent or malformed — fall back to the URL scheme */
    }
    if (scheme === "http") {
      url.protocol = "https:";
      return Response.redirect(url.toString(), 301);
    }

    // Send www to the apex once, permanently, so the two do not compete as
    // separate origins in search results.
    if (url.hostname.startsWith("www.")) {
      url.hostname = url.hostname.slice(4);
      return Response.redirect(url.toString(), 301);
    }

    const upstreamUrl = new URL(request.url);
    upstreamUrl.hostname = UPSTREAM;
    upstreamUrl.protocol = "https:";
    upstreamUrl.port = "";

    const headers = new Headers(request.headers);
    headers.set("Host", UPSTREAM);
    // Let the app know the real scheme/host it is being served on, so any
    // absolute URL it builds points at the custom domain rather than the Space.
    headers.set("X-Forwarded-Host", url.hostname);
    headers.set("X-Forwarded-Proto", "https");

    const upstreamRequest = new Request(upstreamUrl.toString(), {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD"
        ? undefined
        : request.body,
      redirect: "manual",
    });

    let response;
    try {
      response = await fetch(upstreamRequest);
    } catch (err) {
      // A free-tier Space sleeps after inactivity and takes ~30s to wake. Say
      // that plainly instead of showing a bare Cloudflare error page.
      return new Response(
        "Titan Omega is starting up. Hugging Face free-tier Spaces sleep when " +
        "idle and take about 30 seconds to wake. Please refresh shortly.",
        { status: 503, headers: { "Content-Type": "text/plain", "Retry-After": "30" } },
      );
    }

    // Pass the body through untouched and unbuffered so SSE keeps streaming.
    const out = new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: new Headers(response.headers),
    });

    for (const [k, v] of Object.entries(SECURITY_HEADERS)) out.headers.set(k, v);

    // Never let an intermediary buffer the live feed.
    if ((response.headers.get("content-type") || "").includes("event-stream")) {
      out.headers.set("Cache-Control", "no-cache, no-transform");
      out.headers.set("X-Accel-Buffering", "no");
      // A CSP on an event stream buys nothing and some proxies choke on large
      // header sets for long-lived connections.
      out.headers.delete("Content-Security-Policy");
    }
    return out;
  },
};
