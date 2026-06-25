# Deploy Titan Omega — open your dashboard from anywhere

This gets you a real URL (e.g. `https://titan-omega.onrender.com`) with a login,
for **free**. The whole app — dashboard + 102 agents — runs as one service.

> You do this part yourself because it needs **your** login on the host. It takes
> about 5 minutes and no coding.

---

## Option A — Render (recommended, gives you a URL)

1. Make sure this project is on **your** GitHub (it already is:
   `AbdullahRathoreVA/Project-titan-omega`).
2. Go to <https://render.com> → sign up (free) → **New → Web Service**.
3. **Connect your GitHub** and pick the `Project-titan-omega` repo, branch
   `claude/brave-lovelace-knzpcz` (or `main` once merged).
4. Render detects `render.yaml` + the `Dockerfile` automatically. Plan: **Free**.
5. Before you click Create, open **Environment** and set:
   - `TITAN_USERNAME` → your email (e.g. `abdullahrathore.va@gmail.com`)
   - `TITAN_PASSWORD` → **a brand-new password** (NOT one you've shared anywhere)
   - *(optional)* `ANTHROPIC_API_KEY` → to make agents think with Claude
   - *(optional)* `TITAN_PUBLISH_WEBHOOK` → your Make/Zapier hook for auto-posting
6. Click **Create Web Service**. Wait ~3–5 min for the first build.
7. Open the URL Render gives you → **log in** with the username/password above.
   Open it on your phone, laptop, anywhere.

> **Honest notes about the free tier:** Render free services **sleep after 15
> min idle** (first visit then takes ~30s to wake), and the dashboard's data
> **resets when the service restarts** (it re-seeds and re-syncs live data on
> boot). That's fine for using and showing it. For data that survives restarts,
> add a database later (the store is built to swap in Postgres).

---

## Option B — Hugging Face Spaces (you already use HF)

1. <https://huggingface.co/new-space> → **Docker** → blank.
2. Push this repo's contents into the Space (it has a `Dockerfile`).
3. In the Space **Settings → Variables and secrets**, add `TITAN_USERNAME`,
   `TITAN_PASSWORD`, `TITAN_SECRET`, and set the Space **app_port** to `8000`
   (add `app_port: 8000` to the Space README metadata).
4. The Space builds and gives you a public URL with login.

---

## Keep it updated

Every time you push changes to the connected branch, Render/HF **rebuilds and
redeploys automatically** — so the dashboard stays up to date. The data inside
(agents, opportunities, live connectors) refreshes on every boot and on the
heartbeat while running.
