# Make.com Automation — Complete From-Zero Setup (Abdullah's Titan Omega)

This turns your dashboard from "I click buttons" into "it runs itself":
Fiverr orders auto-update revenue, posts go out daily, customer emails get
auto-replies. You have **no Make.com account yet** — start at Step 0.

---

## Key facts you'll need (copy these)

- **Your dashboard base URL:**
  `https://careermind2026-project-titan-omega.hf.space`
- **Webhook secret header** (for metric pushes): header name `X-Webhook-Secret`,
  value = your `TITAN_WEBHOOK_SECRET` (already set in your Space secrets).
- All requests are **HTTP POST** with `Content-Type: application/json`.

### Endpoints Make.com will call
| Purpose | Method + URL | Body (JSON) | Needs secret header? |
|---|---|---|---|
| Log a real order | `POST /api/revenue/log` | `{"amount":10,"source":"fiverr","note":"AI resume gig"}` | No |
| Push metrics | `POST /api/metrics/bulk` | `{"metrics":{"cm_traffic":120},"source":"make"}` | Yes |
| Draft a DM reply | `POST /api/inbox/auto-reply` | `{"message":"...","platform":"fiverr","lang":"en"}` | No |
| Schedule a post | `POST /api/posts` | `{"content":"...","channels":["linkedin"]}` | No |

---

## Step 0 — Create your Make.com account (2 min)
1. Go to **make.com** → **Get started free**.
2. Sign up with Google (`rathoreabdullah816@gmail.com`) — easiest.
3. Pick the **Free** plan (1,000 operations/month — plenty to start).
4. You land on the dashboard. Left menu → **Scenarios** is where everything lives.

> A "scenario" = one automation. You'll build 4. Each is a chain of **modules**
> (boxes). The first box is a **trigger** (when X happens), the rest are **actions**.

---

## Scenario 1 — Fiverr order email → auto-update revenue ⭐ (do this first)

**Goal:** when Fiverr emails "You received an order!", your dashboard's Total
Revenue goes up automatically.

1. **Scenarios → Create a new scenario.**
2. Click the big **+** → search **Gmail** → choose **Watch emails**.
3. Click **Create a connection** → sign in with your Gmail → **Allow**.
4. Configure the trigger:
   - Folder: **INBOX**
   - Filter: **Subject contains** → `order` (or `You received an order`)
   - Sender: `do-not-reply@fiverr.com` (optional, more precise)
   - Max results: 1
5. Click **+** to add the next module → search **HTTP** → **Make a request**.
   - URL: `https://careermind2026-project-titan-omega.hf.space/api/revenue/log`
   - Method: **POST**
   - Headers: add one → name `Content-Type`, value `application/json`
   - Body type: **Raw** → Content type **JSON (application/json)**
   - Request content:
     ```json
     { "amount": 10, "source": "fiverr", "note": "Fiverr order" }
     ```
   - (Advanced later: parse the real amount from the email body instead of 10.)
6. Bottom-left **Run once** to test, then toggle the scenario **ON** and set
   the schedule to every **15 minutes**.

✅ Now every Fiverr order email bumps your real revenue with zero clicks.

---

## Scenario 2 — Auto-post to your socials daily

**Goal:** post about Career Mind AI / your Fiverr gig automatically each morning.

### First, connect your social accounts (one-time)
- **Facebook + Instagram:** make Instagram a **Business/Creator** account, create a
  **Facebook Page**, link them (FB Page → Settings → Linked accounts → Instagram).
- **LinkedIn / Pinterest:** you just authorize them inside Make when you add the module.

### Build it
1. **Create a new scenario.**
2. First module → **Schedule** → every day at **09:00**.
3. Add module → **HTTP → Make a request** (pull a fresh AI-written post):
   - URL: `https://careermind2026-project-titan-omega.hf.space/api/posts`
   - Method: POST, header `Content-Type: application/json`
   - Body:
     ```json
     { "content": "🚀 Career Mind AI — free AI career guidance for students. Try it: <your link>", "channels": ["linkedin"] }
     ```
   - (Or hard-code your own caption here.)
4. Add module → **LinkedIn → Create a post** (or **Instagram for Business → Create a Photo Post**, or **Pinterest → Create a Pin**).
   - Connect the account → map the post text → add your gig/website link.
5. **Run once**, then turn **ON**.

> Tip: for images, add a **Canva** or **Google Drive** module before the social
> module to attach a daily image, or use a fixed image URL.

---

## Scenario 3 — Customer-care auto-reply (Gmail)

**Goal:** incoming customer email → AI drafts a warm reply → sent (or saved as draft).

1. **Create a new scenario.**
2. **Gmail → Watch emails** (INBOX; optionally filter by a label like `support`).
3. **HTTP → Make a request** (get the AI reply):
   - URL: `https://careermind2026-project-titan-omega.hf.space/api/inbox/auto-reply`
   - POST, `Content-Type: application/json`
   - Body (map the email text into `message`):
     ```json
     { "message": "{{the email body from step 2}}", "platform": "email", "lang": "en" }
     ```
4. **Gmail → Create a draft** (SAFE) **or Send an email** (full auto).
   - To: the original sender · Body: map `reply` from step 3.
   - **Start with Create a draft** so you approve before sending. Switch to
     **Send** once you trust it.
5. **Run once**, then **ON**.

> Honest note: keep Fiverr buyer replies as **drafts you approve** — Fiverr's
> rules forbid bots auto-messaging buyers, and full-auto can get you banned.

---

## Scenario 4 — Push real analytics (optional, later)

If you wire Google Analytics / Career Mind stats into Make, send them to your
dashboard:
- **HTTP → Make a request** → `POST /api/metrics/bulk`
- Headers: `Content-Type: application/json` **and** `X-Webhook-Secret: <your TITAN_WEBHOOK_SECRET>`
- Body: `{ "metrics": { "cm_traffic": 120, "cm_signups": 4 }, "source": "make" }`

---

## Order to do it in
1. **Scenario 1** (revenue) — instant value, lowest risk.
2. **Scenario 3** as **drafts** (customer care).
3. **Scenario 2** (social posting) once your IG/FB/LinkedIn are connected.
4. **Scenario 4** when you have analytics.

## Safety rules
- Never put passwords/keys in the post body — only the `X-Webhook-Secret` header.
- Start every "send"/"post" scenario in **draft/manual** mode, watch it once,
  then switch to auto.
- Free plan = 1,000 ops/month. Each scenario run uses a few ops — fine to start.
