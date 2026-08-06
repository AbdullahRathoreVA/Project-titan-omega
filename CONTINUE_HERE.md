# Continuation brief — Titan Omega / Aether / Career Mind

**Paste the "PROMPT FOR NEXT SESSION" block at the bottom into a fresh session.**
Everything above it is the state that prompt refers to.

Rewritten 2026-08-06. Supersedes the 2026-08-01 version.

---

## 1. Machine — read this first

**There are TWO drives.** Always `Get-PSDrive -PSProvider FileSystem`, never
`Get-PSDrive C` alone.

| Drive | State |
|---|---|
| C: | 133.9 GB total, ~8 GB free, chronically tight |
| D: | 103.7 GB, ~84 GB free — **use this for everything** |

- All projects live on `D:\projects\`.
- **Podman VM is on D:** (`D:\wsl\podman-machine-default`), moved 2026-08-02.
  It was on C: despite the old doc claiming otherwise. To move it again:
  `podman machine stop` → `wsl --shutdown` (terminate alone is NOT enough) →
  `wsl --manage podman-machine-default --move "D:\..."`.
  The `2 GiB` in `podman machine inspect` is **not enforced** under WSL; the VM
  actually gets ~7 GB.
- Hardware: i5-1135G7, 15.8 GB RAM, **Intel Iris Xe only — no CUDA**.
- **His connection drops large downloads.** Use resumable loops.
- PowerShell is **5.1**: no `&&`, no `??`, no ternary.
- **His router (192.168.1.1) negative-caches DNS.** `titanomega-ai.com` failed
  from his machine for hours while resolving fine on 1.1.1.1 and 8.8.8.8.
  Always check a public resolver before debugging an app.

---

## 2. Projects

```
D:\projects\project-titan-omega     flagship — FastAPI + Next.js 14, LIVE
D:\projects\triad-thread-studio     CURRENT CLIENT's site (leather) — Next 16
D:\projects\aether-engine           SEO/traffic engine, stdlib only
D:\projects\career-mind             school platform (FastAPI + Streamlit)
D:\projects\AI-Job-Search-Toolkit   the $14 product (10 uncommitted changes)
D:\stacks\                          container compose files
```

**Git:** `gh` is NOT authenticated. Use the cached credential:
```bash
printf "protocol=https\nhost=github.com\n\n" | git credential fill
```
Push Titan to the `github` remote, NOT `origin` (origin is the HF Space).

---

## 3. CLIENT STATUS — CHANGED

**The German restaurant client is LOST.** The current client is his **cousin's
leather wholesale / manufacturing business**, and he is building their site at
`D:\projects\triad-thread-studio` ("leather goods and sublimated apparel
manufacturer", Next 16 + R3F + Prisma, local only, not deployed).

Consequences:
- Do **not** assume restaurant anywhere. Titan now has 16 verticals; `wholesale`
  and `manufacturer` are `local_business=False` because a B2B buyer finds a
  supplier by searching the product, never by proximity.
- The German Impressum / §5 DDG check is still the sharpest differentiator for
  any EU client and still leads the demo — it is just not this client's need.

---

## 4. Titan is LIVE

**https://titanomega-ai.com** — Cloudflare Worker reverse-proxy → HF Space.
HF's own custom domain is PRO-only ($9/mo ≈ 2× the annual budget), so the
Worker does it on the free plan. Source: `deploy/cloudflare-worker.js`,
config `wrangler.toml` at repo root. Pushing to `github` main auto-deploys the
Worker AND triggers the HF sync.

Verified live: HTTPS forced (http 301s), HSTS/CSP/nosniff set, SSE streams
through the proxy, PWA installs, `/pricing`, `/privacy`, `/sitemap.xml` all 200.

**www does not exist and Abdullah has said he does not want it.** A Worker
*Route* does not create DNS.

---

## 5. BLOCKED — needs Abdullah, not engineering

1. **HF write token.** GitHub Actions free minutes are EXHAUSTED (private repo,
   2,000/mo). Runs now queue ~15 min and die. Two commits deployed late because
   of this. Fix: huggingface.co → Settings → Access Tokens → **Write** token.
   Then push straight to `origin` (the Space) and bypass Actions. The stored HF
   credential is a **password**, which HF no longer accepts.
2. **Rotate the Firecrawl key** — `fc-8beba…` was pasted into a chat log.
   Also still open: rotate the Groq key from the earlier session.
3. **Payment processor.** He insists on **PayPal** (told twice; do not re-argue).
   PayPal does not support receiving payments in Pakistan — his call, noted.
   `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_PLAN_ID_{STUDENT,
   INDIVIDUAL,ENTERPRISE}` are unset, so checkout degrades honestly.
4. **Telephony** (Twilio/Vapi/Retell) for the calling agent — paid, his name.
5. **Cloudflare managed robots.txt** overrides Titan's at the edge and declares
   no sitemap. Disable it in the dashboard.

---

## 6. What this session built (19 commits, 8a9f297 → 44dcc67)

**130 tests pass. 124 endpoints. 27 engines.**

| Area | What |
|---|---|
| P6 | Measured model routing — ranks providers on evidence, never drops one, reliability beats latency |
| P2 | Typed event bus; planning engine (plan before execute); **reflection loop that genuinely closes** — 6 slow tasks moved the next plan's estimate 3.5s → 10.5s |
| P4C | BI reports + forecasting that **refuses** to project on thin data |
| P5B | Free/Student/Individual/Enterprise, `/pricing`, signup, quota refusals that name the upgrade |
| P8 | Tool layer + adapters + licence gate for all 11 named repos |
| P3 | PWA (installs on Android/iOS/Windows, $0 vs Apple's $99/yr); HTTPS + security headers |
| — | Self-serve onboarding: add business → first audit → PDF, plan-limited, ownership-checked |
| — | 24/7 per-client news watch (brand / industry / local), Google News RSS, no key |
| — | Evidence ledger — the trycompai/crm pattern |
| — | Titan audits ITSELF every 6h and publishes the score |

### Two real security bugs found and fixed
- **The public demo served real client data.** `/api/admin/clients` exposed his
  clients' names, websites and contacts to anyone clicking "View the live demo".
  The guard fails OPEN — anything not on a list leaks. There is now a test
  (`test_every_founder_endpoint_is_hidden_from_guests`) that walks the REAL
  route table and fails on any endpoint serving real data to a guest. **That
  test found `/api/admin`**, and has caught three more since. Never delete it.
- **Over-correction.** Fixing that, seven tabs were hidden when only three were
  broken — which removed the sales pitch. Only **Executive** is founder-only
  now; Clients and SEO show `[SAMPLE]` German businesses with the full
  Impressum finding, because those screens ARE the pitch.

### Titan's own audit: 58/100, grade D
Self-auditing found three real defects: no privacy policy (legal-critical, and
he now collects emails from EU users), it told **itself** to publish opening
hours (a SaaS is not a local business), and its homepage was an **empty shell**
to crawlers — `out/index.html` had zero `<h1>` because the app is fully
client-rendered.

---

## 7. Research already done — do NOT redo

**Licences measured from the GitHub API, not assumed:**

| Repo | Licence | Verdict |
|---|---|---|
| firecrawl | **AGPL-3.0** | **Wrap over HTTP only.** Embedding forces Titan's own source open — Titan is SOLD. Test enforces this. |
| PraisonAI, OpenWA, voicebox, floci, trycompai/crm | MIT | Safe |
| livekit/agents, OpenJarvis | Apache-2.0 | Safe, needs NOTICE |
| TencentDB-Agent-Memory | **NOASSERTION** | **Blocked.** Re-checked 2026-08-06, still no licence. |
| **multica-ai/multica** | **NOASSERTION** | **Blocked** — and it is a tool for assigning issues to coding agents (Go). Wrong domain entirely; nothing to do with client SEO. |
| public-apis/public-apis | MIT | A LIST. Mined already — see below. |
| free-for-dev, awesome-selfhosted | none / NOASSERTION | Reference only |

**public-apis findings (mined 2026-08-06, 1,695 rows):**
- **News:** GNews, Currents, MarketAux all want keys and cap free tiers.
  Titan already uses **Google News RSS — no key, no quota, no bill.** Adopting
  a keyed provider would be a monthly cost for nothing.
- **Photography:** the category is image *manipulation* (resize, optimise,
  templates), **not AI generation**.
- **Video:** the category is TV/film trivia APIs (Breaking Bad, Game of
  Thrones). **There is no video-generation API in the list at all.**
- Useful: Groq (already wired), DeepAI, Cloudmersive.

**So image/video generation is NOT solvable from that list.** Real options
(Replicate, fal.ai, Stability, Veo, Runway, Kling) are paid per-image or
per-second of video. That is a cost decision for Abdullah, not an engineering
gap.

**Auto-posting to social is against his own standing rule** — drafts queue for
approval, because a platform ban ends the service a client is paying for. There
is a test asserting the news watch cannot send anything.

---

## 8. Bugs — do not reintroduce

1. **reportlab took production down** — any new dependency goes in
   `requirements.txt` in the SAME commit, and imports defensively including
   module-level constants.
2. **A test that onboards a client writes to the real state file.** The client
   registry and `STORE.leads` are module-level and persisted; `fresh_store` does
   not reset them. Use the `isolated_clients` / `isolated_leads` /
   `isolated_billing` fixtures.
3. **The suite must pass with AND without a local `.env`.** `app.main` autoloads
   one; tests asserting "tool unconfigured" need the `no_ambient_config`
   fixture. A suite whose result depends on an untracked file trains you to
   ignore red.
4. **CRLF breaks local image builds, never production.** All four repos now pin
   `*.sh`/Dockerfile to LF via `.gitattributes`. `* text=auto` is NOT enough.
5. **`git add --renormalize .` + `rm` destroys untracked files.** Commit new
   files first.
6. **The browser automation pane stops compositing** when hidden — synthetic
   clicks silently do nothing and framer-motion transitions never finish.
   Element-level `.click()` via the JS tool still works; `read_page` and
   `get_page_text` stay reliable. Do not conclude the app is broken.
7. **Docker is unfixable on this machine.** Podman 5.8.3 replaces it.
8. **`podman compose` shells out to Docker's leftover `docker-compose.exe`** —
   works fine against Podman's socket.

---

## 9. Standing preferences

- Address him as **Abdullah**, never "Boss". (The master spec says
  `HELLO ABDULLAH BOSS` — the spec is wrong; "Boss" appears nowhere in the code.)
- **No Claude attribution** in commits or repos.
- **Never auto-post to social.** Drafts queue for approval.
- **Never invent numbers.** Say which tool would measure it.
- He asks for enormous scope in single messages ("world best ever", "billions").
  Build the highest-value piece properly and say plainly what was not done.
  Fifteen half-finished systems are worth less than one that has been run.
- **Revenue is still $0 and there are no paying customers.** The gap is not
  features.

---

## 10. The master spec

`TITAN OMEGA MASTER SPEC.md` (in his WhatsApp transfers folder) is a ~1,500-line
enterprise vision doc. `docs/SPEC_STATUS.md` in the Titan repo tracks it — a row
only says "built" when it has been RUN.

**Not started:** marketplace, plugin SDK, native mobile/desktop apps, SSO,
prompt library, voice mode with a 3D avatar, founder-only usage analytics.

---

# PROMPT FOR NEXT SESSION

> Continue my projects. Read `D:\projects\CONTINUE_HERE.md` FULLY first — it has
> the machine gotchas, every bug already found, the licence research already
> done, and what is blocked on me rather than on code. Do not redo research that
> is already recorded there.
>
> Key facts: TWO drives, use **D:** for everything. Projects in `D:\projects\`.
> `gh` is not logged in — get the token via `git credential fill`. Podman
> replaced Docker. Push Titan to the `github` remote, never `origin`.
>
> **Titan Omega is live at https://titanomega-ai.com** and is my flagship: a
> multi-tenant SEO + legal-compliance + social platform I sell to businesses.
> **My German restaurant client is gone; my current client is a leather
> wholesale/manufacturing business** whose site I am building at
> `D:\projects\triad-thread-studio`. Titan must work for ANY business, not just
> restaurants.
>
> Before writing code, tell me in one short list: what is blocked on me, and
> what you intend to do first and why.
>
> What I want next, in priority order:
> 1. **Founder-only analytics** — on my own login I want to see who signed up,
>    which plan they bought, and how they are actually using Titan. The
>    Executive tab is already founder-only; extend it.
> 2. **Finish the onboarding UX** — signup → pick plan → add business, website,
>    Instagram → first audit → PDF already works at the API level
>    (`POST /api/account/onboard`). It needs a real screen, and the demo and the
>    signup flow both need to be genuinely easy to use.
> 3. **Voice mode** — Titan speaking naturally in any language. LiveKit
>    (Apache-2.0) is already registered as a tool adapter. Design it free-tier
>    first and tell me honestly what it would cost before building.
> 4. Then: prompt library, marketplace/SDK, SSO.
>
> Rules: verify everything by RUNNING it, never claim something works without
> evidence, put any new dependency in requirements.txt in the same commit, run
> the test suite before every push (**130 tests must pass**), and tell me
> plainly when something cannot be done rather than working around it silently.
> If I ask for something that needs a paid account or a credential, say so
> immediately instead of building half of it.
