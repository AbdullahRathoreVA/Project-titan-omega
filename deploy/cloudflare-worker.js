/**
 * titanomega-ai.com  ->  the Hugging Face Space, on Cloudflare's free plan.
 *
 * Hugging Face only supports custom domains on its paid plans. This Worker
 * does the same job on Cloudflare's free plan (100,000 requests/day, free SSL).
 *
 * It reverse-proxies every request to the Space and streams the response
 * straight back. A proxy, not a redirect: a 301 to *.hf.space would put the
 * Hugging Face URL in the visitor's address bar.
 *
 * Things a naive proxy would break, handled here:
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
 * A product that tells other businesses to fix their security has to get its
 * own right, so every response gets HSTS, a CSP and the usual hardening
 * headers.
 *
 * The CSP can be this strict because the app is entirely same-origin: no CDN,
 * no external script, no eval, no WebAssembly.
 *
 * Two deliberate allowances:
 *
 *  - 'unsafe-inline' for script/style. Next.js static export inlines its
 *    hydration payload, and Tailwind injects styles at runtime. Nonces would
 *    be better, but issuing one means rewriting the HTML body here, which
 *    breaks the streaming pass-through that Server-Sent Events rely on.
 *    Blocking external script injection is most of the value anyway.
 *
 *  - frame-ancestors permits huggingface.co, since the Space is also viewed
 *    inside HF's iframe.
 *
 * img-src allows any https origin because client logos are supplied by the
 * clients themselves and live on their own domains.
 */
// Paddle's domain, allowed by wildcard. Paddle loads Paddle.js from
// cdn.paddle.com but doesn't publish a CSP allowlist, so exact checkout hosts
// would be guesses that break silently if they change.
//
// The only third-party domain allowed, because it's the payment processor.
const PADDLE = "https://*.paddle.com";

const CSP = [
  "default-src 'self'",
  // cdn.paddle.com serves Paddle.js. Without this the checkout script never
  // loads and the Upgrade button silently does nothing.
  `script-src 'self' 'unsafe-inline' ${PADDLE}`,
  "style-src 'self' 'unsafe-inline'",
  // Paddle's checkout is an iframe; without frame-src it would fall back to
  // default-src 'self' and the overlay would be blocked.
  `frame-src 'self' ${PADDLE}`,
  // Paddle.js talks to Paddle's API from the browser.
  `connect-src 'self' ${PADDLE}`,
  "img-src 'self' data: blob: https:",
  // Titan generates its audio as `data:audio/wav` (browser speech) and `blob:`
  // (fetched TTS), neither of which is 'self'. Without media-src the boot
  // chime and every voice would be silently blocked. Same two schemes as
  // img-src, for the same reason: the bytes are produced by this page.
  "media-src 'self' data: blob:",
  "font-src 'self' data:",
  "worker-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'self' https://huggingface.co https://*.hf.space",
  "upgrade-insecure-requests",
].join("; ");

const SECURITY_HEADERS = {
  // One year. No `preload` on purpose: preloading is hard to undo (it needs a
  // browser-vendor submission), and the domain is new.
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  // Microphone and payment stay enabled for same-origin (the voice assistant
  // and the Payment Request API). Everything else is switched off.
  //
  // Not verified: card wallets (Apple Pay, Google Pay) run inside Paddle's
  // cross-origin iframe, and Permissions-Policy origin lists don't accept
  // wildcards, so delegating to Paddle would need its exact (undocumented)
  // checkout host. Card payments work without it; if a wallet button is
  // missing, check the browser console and add the origin it names.
  "Permissions-Policy":
    "camera=(), geolocation=(), payment=(self), usb=(), microphone=(self)",
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
