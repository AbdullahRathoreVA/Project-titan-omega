# Continuation brief — Titan Omega

**Paste the "PROMPT FOR NEXT SESSION" block at the bottom into a fresh session.**
Everything above it is the state that prompt refers to.

Rewritten 2026-08-09. Supersedes the 2026-08-06 version.

---

## 1. Machine — read this first

**There are TWO drives.** Always `Get-PSDrive -PSProvider FileSystem`.

| Drive | State |
|---|---|
| C: | 133.9 GB total, ~8 GB free, chronically tight |
| D: | 103.7 GB, ~84 GB free — **use this for everything** |

- All projects on `D:\projects\`. Titan: `D:\projects\project-titan-omega`.
- PowerShell is **5.1**: no `&&`, no `??`, no ternary. Here-strings break on
  inline quotes — **write long commit messages to a file and use `git commit -F`.**
- Podman replaced Docker (Docker is unfixable on this machine).
- His router negative-caches DNS — check a public resolver before debugging.
- Hardware: i5-1135G7, 15.8 GB RAM, **Intel Iris Xe, no CUDA**.

---

## 2. Git and deploy — THIS CHANGED, the old notes were wrong

**`gh` IS authenticated** (`AbdullahRathoreVA`, scopes repo/workflow).
`git credential fill` **HANGS** a non-interactive session — never use it.
`credential.helper` is `manager`, which needs a GUI and fails headless.

```bash
git -c credential.helper="!gh auth git-credential" push github main
```
A `fatal: Cannot prompt` line still prints first — **harmless noise**. Check the
last lines for `main -> main`.

**Push to `github`, never `origin`** (origin is the stale HF Space).

Deploy: push → Action `Sync to Hugging Face Hub` (~8s) → HF rebuild → live,
about 2 min total. **Always read the Action conclusion**, not the push output:
```bash
gh run watch $(gh run list --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status
```

### Two traps that cost real time
1. **HF rejects `short_description` over 60 chars** in README front matter. The
   whole push is declined at the pre-receive hook, GitHub still shows success,
   and the Space serves old code. Cost two silent deploys.
2. **`npm run build` does NOT produce `out/`.** It needs `TITAN_STATIC=1`,
   otherwise it builds the dev variant, prints "✓ Compiled successfully", and
   leaves a **stale `out/`**. Always:
   `cd frontend; $env:TITAN_STATIC="1"; npm run build`
   then grep `out/_next/static/chunks/*.js` for a string you just added.

**Verifying a deploy:** cache-bust (`?cb=<random>`), fetch `/` , extract chunk
URLs, grep them for a new string. `/health` returning 200 proves nothing.

---

## 3. Where Titan is now

**LIVE: https://titanomega-ai.com** · **264 tests pass** · self-audit **100/100 A**

26 commits shipped 2026-08-07→09, `5b5eca1..0688949`. Tests went 130 → 264.
Every commit was verified live in production before being called done.

### Shipped this session
- **Founder analytics** — who signed up, plan, what they did. Funnel steps
  labelled by SOURCE (account state = true for all accounts; activity log =
  only since it shipped, so a zero means *not observed*).
- **Visitor analytics** — in-process, no GA, no cookie, no consent banner.
  **IP is never stored**, only a hash with a 24h-rotating salt. Device/OS/
  browser/country (Cloudflare `CF-IPCountry`) /hour.
- **`/join`** — real signup → plan → business → audit → PDF.
- **Front door rewritten** — the login screen had NO signup link; `/join`
  existed and nothing pointed at it. Plans+prices now first.
- **Voice Agent OS** — validated state machine (409 on illegal transitions),
  enforced approval gate (403 without approver), session replay, transcripts.
- **VoiceSphere** — particle avatar, NO 3D library, plain canvas.
- **Knowledge retrieval** — BM25 + heading-aware chunking + optional fastembed.
- **Lead discovery** — search → drop directories/dupes → CRM → audit → draft.
- **25 landing pages** — `/compliance/{9}` and `/seo/{16}`, in the sitemap.
- **SQLite** replaced the single JSON file. **Signed expiring revocable sessions.**
  **SSRF guard.** **Rate limiting.** **Website credential vault (WordPress).**

---

## 4. BLOCKED — needs Abdullah, not engineering

1. **Payment. Nothing can be sold.** `PADDLE_API_KEY` +
   `PADDLE_PRICE_ID_{STUDENT,INDIVIDUAL,ENTERPRISE}`.
   - **Dodo is NOT available in Pakistan** (he confirmed) — adapter exists, demoted.
   - **PayPal cannot RECEIVE in Pakistan.** Told him repeatedly; do not re-argue.
   - **Paddle IS available** — verified against Paddle's own unsupported list
     2026-08-08. Pays out via Payoneer. See `docs/PAYMENTS.md`.
   - He asked about using **his brother's Canadian PayPal**. Answer is **no** —
     breaks every processor's ToS, fraud systems detect it, 180-day freeze, the
     money becomes the brother's taxable income. **Do not help wire this up.**
2. **`TITAN_PUBLISH_WEBHOOK`** — no social posting without it. The CONNECT
   buttons are placeholders; there is no OAuth behind them.
3. **HF persistent storage (paid)** — SQLite fixed corruption, NOT ephemerality.
   A rebuild still wipes `/tmp`. `db.stats()` reports `durable: false`.
4. **Telephony** — paid, his name, no free path.
5. Rotate the exposed Firecrawl + Groq keys.
6. Cloudflare managed robots.txt overrides Titan's at the edge.

---

## 5. Known real defects — measured, not guessed

- **Retrieval is 2/4** on natural questions. Semantic only leads above 0.68
  cosine; lowering to 0.60 was tested and changed nothing. Next lever is
  **better chunking, not a bigger model**.
- **Landing pages score 60/C and 70/C** against Titan's own engine — no schema
  markup. Found by the demo workspace.
- **"Career Mind" appears 58× across 13 backend files.** Only the next-post
  generator was fixed. The rest is a real cleanup with little test cover.
- **Crawler has no JS rendering** — single `httpx` GET. Most small-business
  sites are client-rendered, so **Titan audits empty shells for a large share
  of the market**. Most under-recognised functional gap. Needs Playwright in a
  SEPARATE service (browser binaries at Docker build time will break the free
  Space build).
- **102 agents are mostly presentation.** Either back them with behaviour or
  stop claiming them.
- Rate limiting is **in-process** — does not survive scaling to 2 containers.

---

## 6. Standing rules — he has stated these

- Address him as **Abdullah**, never "Boss".
- **No Claude attribution** in commits or repos.
- **Never auto-post to social.** Drafts queue for approval. There is a test.
- **Never invent a number.** This is the spine of the codebase: cost is `null`
  not `0.00`; latency `null` when unmeasured; unaudited sites show "not
  audited" not `0`; funnel steps carry their source. **Do not break this.**
- Verify by RUNNING it. Never claim something works without evidence.
- New dependency → `requirements.txt` in the SAME commit, imported **inside the
  function** (reportlab took production down at module level once).
- Run the full suite before every push.
- Say plainly when something cannot be done. He gets angry at hedging, and
  angrier at being told something works when it does not.
- He asks for enormous scope in one message ("world best ever", "billions").
  Build the highest-value piece properly and say what was not done.

---

## 7. Tests — never delete these

- `test_every_founder_endpoint_is_hidden_from_guests` walks the **real route
  table** and fails on any endpoint serving real data to a demo visitor. The
  guard **fails OPEN** — anything unregistered leaks. It has caught **five**
  endpoints, including `/api/admin/clients` exposing real client contacts.
- Outreach has **no send capability at all** — asserted by source inspection.
- Rate-limit buckets are module-level; `fresh_store` resets them or one test
  poisons another with a 429.

---

## 8. Architecture blueprint

Full forensic audit with scored baseline, verified research and a 25-item
checklist:
**https://claude.ai/code/artifact/18979618-2a79-45a4-b740-d08206669c70**

Items **001–004, 006 are DONE**. Remaining, in order:
- **007** durable task queue (crawls run on the request path today)
- **011** Playwright crawler service (the JS-rendering blind spot)
- **012** schema markup on the landing pages
- **013** verifier layer before customer-facing output

---

# PROMPT FOR NEXT SESSION

> Continue Titan Omega. Read `D:\projects\CONTINUE_HERE.md` FULLY first — it has
> the machine gotchas, the deploy traps that have already cost real time, the
> payment research, and what is blocked on me rather than on code. Do not redo
> research recorded there.
>
> Key facts: use **D:** for everything, projects in `D:\projects\`. `gh` IS
> authenticated — push with
> `git -c credential.helper="!gh auth git-credential" push github main`, to the
> `github` remote, never `origin`. `git credential fill` hangs. Frontend needs
> `TITAN_STATIC=1` or `out/` stays stale. HF rejects a `short_description` over
> 60 characters and the push fails silently.
>
> **Titan is live at https://titanomega-ai.com** — a multi-tenant SEO + legal
> compliance + voice platform I sell to businesses. 264 tests pass; it scores
> 100/100 on its own audit. My client is a leather wholesale/manufacturing
> business (`D:\projects\triad-thread-studio`). Titan must work for ANY
> business, not only restaurants.
>
> The rule the whole codebase is built on: **never show a number that was not
> measured.** Cost is null, not 0.00. Unmeasured latency is null. Unaudited
> sites show "not audited", not 0. Do not break this — it is the product's main
> credibility asset.
>
> Before writing code, tell me in one short list: what is blocked on me, and
> what you intend to do first and why.
>
> What I want next, in priority order:
> 1. **Make Titan actually FIX websites, not just audit them.** The WordPress
>    credential vault and setup guide are built (`core/site_access.py`). Next is
>    the propose → approve → apply → rollback loop, then a 24/7 cycle.
> 2. **Blueprint item 011** — a Playwright crawler in a separate service. Titan
>    currently audits empty shells on client-rendered sites, which is a large
>    share of my market.
> 3. **Item 007** — durable task queue; crawls run on the request path today.
> 4. **Item 012** — schema markup on the 25 landing pages (they score 60–70/C
>    against my own engine).
>
> Rules: verify everything by RUNNING it, never claim something works without
> evidence, put any new dependency in requirements.txt in the same commit and
> import it inside the function, run the full test suite before every push, and
> tell me plainly when something cannot be done instead of working around it
> silently. If something needs a paid account or a credential, say so
> immediately instead of building half of it.
