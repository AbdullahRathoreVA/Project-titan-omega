# Continuation brief — Titan Omega / Aether / Career Mind

**Paste the "PROMPT FOR NEW SESSION" block at the bottom into a fresh Claude Code
session.** Everything above it is the state that prompt refers to.

Written 2026-08-01.

---

## 1. Machine — read this first

**There are TWO drives.** Always run `Get-PSDrive -PSProvider FileSystem`, never
`Get-PSDrive C` alone. I measured only C: for hours, repeatedly told Abdullah
installs were impossible, and broke Docker twice trying to free space — while
103 GB sat unused on D:. He had to send a screenshot to correct me.

| Drive | State |
|---|---|
| C: | 133.9 GB total, ~13 GB free, chronically tight |
| D: | 103.7 GB, ~100 GB free — **use this for everything** |

- **All projects live on `D:\projects\`** (moved 2026-08-01, `git fsck` clean).
- Hardware: i5-1135G7, 15.8 GB RAM, **Intel Iris Xe only — no NVIDIA, no CUDA**.
- **His connection drops large downloads.** Always use a resumable loop
  (`HttpWebRequest` + `AddRange`), never a single `Invoke-WebRequest`.
- PowerShell is **5.1**: no `&&`, no `??`, no ternary. Use `;` and `if/else`.

---

## 2. Project locations

```
D:\projects\project-titan-omega      flagship — FastAPI + Next.js 14
D:\projects\titan-omega-infinity     commercial fork
D:\projects\aether-engine            SEO/traffic engine, Python stdlib only
D:\projects\career-mind              school platform (FastAPI + Streamlit)
D:\projects\AI-Job-Search-Toolkit    the $14 product
D:\projects\claude-seo               SEO plugin (30+ skills, installed)
D:\stacks\                           container compose files
```

**Git:** `gh` is NOT authenticated. Use the cached credential instead:
```bash
printf "protocol=https\nhost=github.com\n\n" | git credential fill
```
That yields a PAT with `repo` + `workflow` scope for `AbdullahRathoreVA`.

**Titan deploy flow:** push to `github` remote (NOT `origin`, which is the stale
HF Space) → GitHub Action syncs to HF → Docker rebuild → live.
Live at `https://careermind2026-project-titan-omega.hf.space`.

---

## 3. What was built (all verified, all pushed)

### Titan Omega — turned into a sellable agency product
| Module | What it does |
|---|---|
| `core/clients.py` | Multi-tenant: a login per business. PBKDF2, constant-time compare, **fails closed** — verified a client token returns 401 on every founder endpoint. |
| `engines/client_seo.py` | Audits any client website. Browser UA (bot UA gets 403'd). |
| `engines/compliance.py` | **The differentiator.** 9 jurisdictions. German Impressum = §5 DDG, fines to €50,000, competitor Abmahnung risk. Legal findings sit ALONGSIDE the SEO score, never averaged in. |
| `engines/local_seo.py` | Weighted on published 2026 factors: GBP 25, reviews 20, on-page 20, NAP 15, schema 10, authority 10. |
| `engines/client_watch.py` | **24/7 monitoring on the server heartbeat.** Diffs each audit against the last and alerts on regressions. |
| `engines/client_content.py` | Social captions, English + market-language twin. Validator rejects discounts/emoji/urgency. |
| `engines/client_report.py` | 2-page PDF. **reportlab imports defensively** — see §4. |
| `engines/discovery.py` | Turns recurring audit findings into priced offers (found €660 from 2 sites). |
| `core/learning.py` | Naive Bayes re-ranking opportunities by what he actually pursues. |
| `static/client.html` | `/portal` — client login, plain-language layer (22 finding ids translated). |
| `static/admin.html` | `/clients` — admin console. |
| `ClientCommand.tsx` | Clients tab **native in the 3D dashboard**. |

### Aether Engine
14 agents · 46 pages · **orphans 37→0** · FAQ schema + answer-first on every page ·
PORTFOLIO agent auto-discovers all GitHub repos + HF Spaces · Groq-powered ·
self-healing. Live at `https://abdullahrathoreva.github.io/aether-engine`.

---

## 4. Bugs found — do not reintroduce

1. **reportlab took down production.** Built against a locally-installed package,
   never added to `requirements.txt`; the container died at import and EVERY
   endpoint went down. Now pinned AND imported defensively **including the
   module-level `colors.HexColor()` constants** — guarding only the `import`
   line still crashes.
   → **Any new dependency must go in `requirements.txt` in the same commit.**
2. **Copied a code anchor between projects.** Used Aether's `const money =` as an
   insertion point in Titan's `client.html`; it does not exist there, so
   `plainFor()` shipped without its `PLAIN` dictionary — the page would render
   blank. **Verify anchors exist before scripted edits, and `node --check` any
   generated JS.**
3. **Orphan pages.** Relevance-based internal linking left stragglers; needed a
   deterministic ring. Also: the ring link was appended AFTER a `[:limit]` slice
   and silently truncated away.
4. **`related_links()` scoped to `published=1`** while a rebuild sets everything
   to 0 — the link graph computed against a shrinking set.
5. **Weak LLM teachers poison training.** groq(70B) and ollama(1B) disagreed on
   14/18 posts; mixing the 1B labels dropped accuracy 65%→53%. Weak teachers are
   now dropped when a strong one exists.
6. **browser-use broke Titan** by pulling starlette 1.3.1 (FastAPI 0.115.6 needs
   <0.42). Use `pip install <pkg> -c backend/constraints.txt`.
7. **Docker is unfixable on this machine.** Orphaned reparse points in
   `AppData\Local\Docker\run\` (dockerInference, dockerEthernetVfkit) cannot be
   deleted by `del`, `fsutil` or `rmdir` even with no Docker process running.
   Every version fails identically. **Podman 5.8.3 replaces it** — Docker-API
   compatible, `docker-compose.yml` works unchanged, VM on D:.
   Binary: `C:\Program Files\RedHat\Podman\podman.exe`.

8. **`podman compose` delegates to Docker's leftover `docker-compose.exe`** if it
   is still on PATH, which routes the pull through the broken Docker stack. Put
   Podman FIRST on PATH, or use `podman pull` / `podman play` directly.

9. **Large image pulls die on his connection** ("unexpected EOF" at ~558 MB).
   Always pull in a retry loop:
   ```bash
   for i in 1 2 3 4 5 6; do podman pull <image> && break; sleep 5; done
   ```
   Podman resumes partial layers, so retries make progress rather than restart.

10. **The Podman VM stops on its own** and every pull then fails with
    "connection actively refused" — which looks exactly like a bandwidth
    problem but is not. **Always check `podman machine list` first**; if LAST UP
    is in the past, run `podman machine start`. I wasted six retries and wrongly
    blamed the connection before checking this.

    Working sequence:
    ```bash
    export PATH="/c/Program Files/RedHat/Podman:$PATH"   # before Docker's leftovers
    podman machine start
    podman pull docker.io/library/nginx:alpine           # verified 63.7 MB OK
    ```

---

## 5. Blocked on Abdullah (nobody else can do these)

1. **Rotate the Groq key** — a command error printed it into the last session.
2. **Dodo Payments signup** — needs his CNIC. Aether's 46 pages still end at a
   dead `CHECKOUT_URL`. Copy ready in `AI-Job-Search-Toolkit\DODO_LISTING_COPY.md`.
   **Gumroad/Payhip/Lemon Squeezy CANNOT pay out to Pakistan** — verified twice.
   Dodo (Merchant of Record) → pays out to **Wise or Payoneer**. Wise alone is a
   bank account, not a checkout — good for the €1,200 service invoice, useless
   for the $14 product.
3. **Career Mind `/api/public/stats` is unreachable in production.**
   `scripts/start_all.sh` runs FastAPI on internal port 8000 and Streamlit on
   public 7860; only 7860 is exposed, so every FastAPI route returns Streamlit
   HTML. Needs a reverse proxy or FastAPI mounted on `$PORT`.

---

## 6. The business context

Friend's client: a **restaurant in Germany** (not Pakistan — clients are
worldwide). Wants SEO + social media, **2 months free** to evaluate. Call
expected within ~10 days of 2026-08-01. He has ~PKR 30,000 for hosting but
**does not need it yet** — HF free tier runs Titan, and the client is on a free
trial, so there is no revenue to protect.

**Onboarding is ~90 seconds:** Clients tab → Onboard → 6 fields → Create →
Audit → PDF. The country selector drives which legal rules get checked.

**Research that shapes strategy (do not re-derive):**
- SEO on a new domain in a competitive niche: **12–18 months**. Freelance AI
  automation converts a first client in **weeks**. Upwork "AI development"
  searches +847% YoY vs +23% growth in qualified freelancers, $60–150/hr.
- **ChatGPT does not read Google Business Profile.** It sources local answers
  from Bing, Yelp, TripAdvisor, Reddit. 45% of consumers now use AI for local
  picks (up from 6%), converting at 15.9% vs Google organic's 1.76%.
- **Review velocity beats count** — rankings drop after ~18 days without a new
  review.
- Luxury brands measured live: Chanel 7,446 posts / 59M followers / **following
  3**; Gucci **367 posts** / 50.5M; Tommy Hilfiger follows 347. Following count
  tracks prestige. Volume is not the lever. Bottega Veneta deleted all social in
  2021 and grew.

---

## 7. Standing preferences

- Address him as **Abdullah**, never "Boss".
- **No Claude attribution** in commits or repos.
- **Never auto-post to social** — drafts queue for approval. Banned accounts end
  the service a client is paying for.
- **Never invent numbers.** Where something cannot be measured (traffic, GBP
  insights, rankings) say which tool would provide it.
- When he asks for a new money-making tool, redirect to launching what exists.
  The pattern is: build more, never launch. Revenue is still $0.

---

# PROMPT FOR NEW SESSION

> Continue work on my projects. Read `D:\projects\CONTINUE_HERE.md` first —
> it has the full state, every bug already found, and the machine gotchas.
>
> Key facts: I have TWO drives, use **D:** for everything (C: is nearly full).
> All projects are in `D:\projects\`. `gh` is not logged in — get the GitHub
> token via `git credential fill`. Podman replaced Docker (Docker is
> permanently broken on this machine, the reason is in the doc).
>
> **Titan Omega** is my flagship: a multi-tenant SEO + social agency platform I
> sell to businesses. It is live on Hugging Face. **Aether Engine** drives SEO
> traffic to my $14 toolkit. **Career Mind** is a school platform.
>
> I have a **German restaurant client** starting a 2-month free trial. Titan's
> German legal compliance (Impressum / §5 DDG / Abmahnung risk) is my main
> differentiator — no competitor's SEO report flags a €50,000 fine.
>
> What I want next, in priority order:
> 1. Finish installing and wiring the container stacks in `D:\stacks\` via
>    Podman, and verify each one actually runs before telling me it works.
> 2. Add an SEO page to Titan's Next.js dashboard (the engines exist —
>    `local_seo.py`, `compliance.py`, `client_watch.py` — but there is no
>    dedicated SEO view yet).
> 3. Fix Career Mind's `/api/public/stats`, which is unreachable in production
>    (details in the doc).
> 4. Aether has no Projects page in its dashboard yet, though the PORTFOLIO
>    agent already collects the data.
>
> Rules: verify everything by running it, never claim something works without
> evidence, put any new dependency in requirements.txt in the same commit, and
> tell me plainly when something cannot be done rather than working around it
> silently. Run the test suite before every push (Titan: 38 tests must pass).
