# 👋 Start Here — Titan Omega in Plain English

You don't need to be technical to run this. Follow the steps and you'll have your
own AI company dashboard open in your browser.

---

## What this is

Titan Omega is a **command center for a team of 100+ AI agents** that work on
your business. You type what you want ("grow my traffic", "find new revenue"),
and the right agents pick it up, surface the best opportunities, and **produce
real things you can use** — outreach emails, SEO plans, growth strategies.

It runs **completely free** out of the box. If you later add an AI key (see the
last section), the agents get noticeably smarter — but you don't need one to
start.

---

## Run it (about 5 minutes)

You need two free tools installed first: **Python** and **Node.js**. If you
don't have them, install Python from python.org and Node from nodejs.org, then
come back.

### Windows (easiest — just double-click)

After installing **Python** (python.org) and **Node.js** (nodejs.org),
**double-click `run-windows.bat`** in this folder. Two windows open, and your
browser opens the dashboard at **http://localhost:3000**. Local runs need no
login. Close the two windows to stop.

### Mac / Linux

Open a terminal **in this folder** and run:

```bash
make install   # one time only — sets everything up
make dev        # starts the whole thing
```

Then open **http://localhost:3000** in your browser. That's your command center.
To stop it, press `Ctrl + C` in the terminal.

### Want to open it from anywhere (phone, other computers)?

Deploy it free and get a real URL with a login — see **[DEPLOY.md](DEPLOY.md)**.
You set your own username and password as host settings (never in the code).

### If `make` isn't available

Run these in **two separate terminals**:

```bash
# Terminal 1 — the brain (AI agents)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# Terminal 2 — the dashboard
cd frontend
npm install
npm run dev
```

Then open **http://localhost:3000**.

---

## What you'll see

- **Top numbers** — revenue, traffic, how many agents are working right now.
- **Divisions** — your AI departments (Marketing, Growth, Finance…), each with a
  health bar.
- **Command bar** — type anything in plain English and press Dispatch. The right
  division picks it up.
- **Opportunity Radar** — growth ideas the agents found, scored by how valuable
  they are. Click **Execute** on any one and an agent will **draft a real
  document** for you.
- **Agent Deliverables** — the actual artifacts your agents produced. Click one
  to read it.
- **Live feed** — everything the agents are doing, in real time.

Try this first: click **Execute** on the top opportunity in the radar, then open
the **Agent Deliverables** panel and read what the agent made for you.

---

## Make the agents smarter (optional, costs money)

By default the agents are free and use built-in templates. To have them think
with **Claude** (much higher quality writing and planning):

1. Get an API key from <https://console.anthropic.com>.
2. In the `backend` folder, set it before starting:

   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   uvicorn app.main:app --port 8000
   ```

The dashboard badge will switch from **Free mode** to **Claude online**, and new
deliverables will be marked with a ✨. Everything you generate this way is billed
to your Anthropic account, so you stay in control of spending.

---

## Common questions

**Is it really doing things on its own?** It analyzes, finds opportunities, and
drafts real work for you to approve. It does **not** secretly touch your real
accounts — connecting live systems (GitHub, email, ad platforms) is a deliberate,
opt-in step that isn't wired up yet (see the roadmap in `README.md`).

**Will it run without internet / without a key?** Yes. Free mode needs nothing.

**Where did my data go?** Everything runs on your own machine. Nothing is sent
anywhere unless you add an AI key (then only your prompts go to Anthropic).
