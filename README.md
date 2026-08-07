---
title: Project Titan Omega
emoji: 🏢
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: other
short_description: SEO, local ranking and legal compliance audits
---

<div align="center">

# TITAN Ω

**SEO, local ranking and legal compliance — audited for any business, in any jurisdiction.**
Multi-tenant platform with a voice-agent layer, built solo on a $0 stack.

[**titanomega-ai.com**](https://titanomega-ai.com) · [Start free](https://titanomega-ai.com/join) · [Pricing](https://titanomega-ai.com/pricing)
Built by [Abdullah Rathore](https://github.com/AbdullahRathoreVA)

![Titan Omega — Neural Command Universe](docs/media/demo.gif)

</div>

---

## What it sells

Add a website. Titan crawls it and returns a technical, local and **legal** audit —
scored separately, never averaged — then a client-ready PDF.

The legal check is the differentiator: **Impressum / §5 DDG, GDPR consent, and
cookie disclosure across 9 jurisdictions**. It is a defect a business owner
cannot argue with, and it is included **in full on the free tier** — hiding the
one finding that proves the product's value would sell nothing.

16 verticals. `wholesale` and `manufacturer` are correctly `local_business=False`,
because a B2B buyer finds a supplier by searching the product, never by proximity.

## The rule the whole codebase is built on

**No number is shown unless it was measured.**

- Cost is `null`, never `$0.00` — a zero under a currency symbol claims a
  measurement nobody took.
- Latency is `null` when no session passed through `thinking`; `0 ms` would read
  as instantaneous.
- An unaudited client site shows *not audited*, never `0` beside a real `58`.
- The funnel labels each step by **source** — steps rebuilt from durable account
  state are true for every account ever created; steps that can only come from
  the activity log say so, because a zero there means *not observed*, not
  *never happened*.
- Forecasting **refuses** to project on thin data.

## Voice Agent OS

![Voice Agents](docs/media/voice-agents.png)

A validated state machine — `idle · listening · thinking · speaking ·
interrupted · escalated · ended` — that **refuses illegal transitions** (409).
A dashboard cannot honestly animate a state the agent was never in.

- **Sensitive tools block on human approval.** Booking, paying, emailing,
  calling and deleting land `pending`; executing one without an approver
  returns **403**. Not a convention — a state the store enforces.
- **Session replay** — transcript, tool-call timeline, state history.
- **Speech reactivity is honest.** Browsers don't expose synthesized speech to
  the audio graph, so while Titan speaks the avatar is driven by real
  `onboundary` word events. The microphone path is a true FFT. The UI says
  which is driving. Faking a waveform would be inventing a measurement.
- The particle avatar uses **no 3D library** — plain canvas and arithmetic, so
  it adds nothing to the bundle and runs on integrated graphics.

## Founder-only intelligence

Who signed up, which plan, what they actually did — plus visitor analytics
measured **in-process**: no Google Analytics, no third-party script, no cookie,
no consent banner, no bill.

Privacy is the design constraint, not a footnote: Titan sells legal compliance,
so **visitor IPs are never stored** — only a hash with a salt that rotates every
24h. Referrers are reduced to a host before storage. Crawler hits are counted
separately and never folded into human traffic.

That costs something, and the report admits it: unique visitors is a **per-day**
figure only, so there is no honest all-time total to divide signups by. It ships
**no conversion percentage** rather than inventing the denominator.

## Lead discovery → audit → draft

Search the web, drop the junk, file real businesses as CRM leads, audit their
sites, draft outreach citing what was actually found.

The value is in what gets thrown away. Directories are not leads — filed as one,
Titan would audit `alibaba.com` and draft outreach about Alibaba's SEO. A
certifier's supplier-profile page is not the supplier. Deduplication is by
registrable domain, because one company appears three times in a single search.

**Nothing is ever sent.** A test asserts the module has no send capability at all.

## Titan audits itself

Every 6 hours, with the same engine it sells, and publishes the score at
`/api/self-seo` — **currently 94/100, grade A**, up from 58/D. Anyone can claim
their SEO tool is good; a score produced by the code the customer is buying can
be checked by the reader in seconds. If Titan regresses, that number falls in
public.

## Security

A test walks the **real route table** and fails on any endpoint serving real
data to a public demo visitor. It was written after `/api/admin/clients` was
found exposing real client names and contacts to anyone clicking "View the live
demo" — the guard fails *open*, so anything unregistered leaks. That test has
caught four endpoints since. It is never to be deleted.

Founder analytics and voice transcripts are refused outright to guests rather
than substituted: there is no demo-safe version of a subscriber's email address
or a caller's own words.

## Payments

Behind one adapter seam. **Dodo Payments** is preferred — a Merchant of Record
that handles US sales tax and EU VAT and pays out to **Payoneer and Wise**,
which is what makes it usable from Pakistan, where **PayPal cannot receive
money at all**. PayPal remains supported for other markets.

With neither configured, signup and the free tier work normally and the refusal
names exactly which variables are missing. Titan never sees a card number.

## Engineering

- **182 tests**, run before every push.
- **Self-healing AI layer** — Groq → Gemini → OpenRouter with live model-catalog
  discovery, so provider retirements can't silence it. Every credential
  whitespace-hardened. `/api/doctor` reports what the running container actually
  sees.
- **Measured model routing** — ranks providers on evidence, never drops one,
  reliability beats latency.
- **Reflection loop that closes** — six slow tasks moved the next plan's
  estimate from 3.5 s to 10.5 s.
- **One container** — Next.js static export served by FastAPI; GitHub Actions →
  Hugging Face Spaces auto-deploy behind a free Cloudflare Worker on the custom
  domain.
- **PWA** — installs on Android, iOS and Windows. $0 versus Apple's $99/yr.
- Every engine degrades honestly when a key is missing; no paid service is a
  hard dependency.

## Stack

`Python` `FastAPI` `Next.js 14` `TypeScript` `Tailwind` `three.js / react-three-fiber`
`framer-motion` `Web Speech API` `Web Audio` `SSE` `Tavily` `Dodo Payments` `Docker` `HF Spaces`

## Run it yourself

```bash
# backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend (dev)
cd frontend && npm install && npm run dev

# frontend (production build served by FastAPI)
cd frontend && TITAN_STATIC=1 npm run build
```

`TITAN_STATIC=1` is required for the static export — a plain `npm run build`
produces the dev variant and leaves a stale `out/` in place.

Runs with no keys at all. Add `GROQ_API_KEY` for conversational AI,
`TAVILY_API_KEY` for lead discovery, `DODO_PAYMENTS_API_KEY` for checkout.

## Status

Live, tested, and **earning nothing yet**. The gap is distribution and a
connected payment processor — not features.
