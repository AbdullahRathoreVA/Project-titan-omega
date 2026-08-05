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

export default {
  async fetch(request) {
    const url = new URL(request.url);

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
    // Never let an intermediary buffer the live feed.
    if ((response.headers.get("content-type") || "").includes("event-stream")) {
      out.headers.set("Cache-Control", "no-cache, no-transform");
      out.headers.set("X-Accel-Buffering", "no");
    }
    return out;
  },
};
