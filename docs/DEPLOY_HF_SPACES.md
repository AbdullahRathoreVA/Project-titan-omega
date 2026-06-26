# Deploy Titan Omega to Hugging Face Spaces

Free, always-on hosting at `https://huggingface.co/spaces/careermind2026/project-titan-omega`.
Takes about 10 minutes.

---

## Step 1 — Create the Space

1. Go to https://huggingface.co/new-space
2. Fill in:
   - **Owner:** `careermind2026`
   - **Space name:** `project-titan-omega`
   - **SDK:** `Docker`
   - **Visibility:** Private (recommended — you have login auth built in)
3. Click **Create Space**

---

## Step 2 — Connect your GitHub repo

1. In the Space settings → **Repository** tab
2. Link `AbdullahRathoreVA/Project-titan-omega` as the source
3. HF will build the Docker image automatically on every push to `main`

**OR** push directly to the HF Space remote:

```bash
git remote add hf https://huggingface.co/spaces/careermind2026/project-titan-omega
git push hf main
```

---

## Step 3 — Set secrets (NEVER in code)

In the Space → **Settings** → **Repository secrets**, add these:

| Secret name | Value | Required? |
|---|---|---|
| `TITAN_USERNAME` | your login username (e.g. `abdullah`) | Yes |
| `TITAN_PASSWORD` | a strong password | Yes |
| `TITAN_SECRET` | any random string (JWT signing key) | Yes |
| `GROQ_API_KEY` | your Groq key from console.groq.com | Recommended (free AI) |
| `TITAN_WEBHOOK_SECRET` | any random string | Recommended (secures Make.com) |
| `CAREERMIND_API_KEY` | your Career Mind admin token | Optional (live user stats) |
| `GITHUB_TOKEN` | a GitHub PAT (read-only) | Optional (live repo stats) |

> ⚠️ Never paste secrets into files or chat. Set them only in the Secrets panel.

---

## Step 4 — Watch it build

1. Go to your Space URL — you'll see a build log
2. First build takes ~3-5 minutes (npm install + pip install)
3. When done, the dashboard appears at your Space URL
4. Log in with the username/password you set in Step 3

---

## Step 5 — Get your webhook URL for Make.com

Once deployed, your Make.com webhook URL is:

```
https://careermind2026-project-titan-omega.hf.space/api/metrics/bulk
```

Add it to Make.com HTTP modules with header:
```
X-Webhook-Secret: <your TITAN_WEBHOOK_SECRET>
```

---

## Updating the deployment

Every `git push` to `main` triggers a rebuild automatically. Or manually:
1. Go to Space → **Settings** → **Factory reboot**

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Build fails | Check the build log — usually a missing npm or pip dep |
| Dashboard shows "Core offline" | The backend crashed — check Runtime logs |
| Login screen but wrong password | Check `TITAN_USERNAME` / `TITAN_PASSWORD` secrets |
| AI shows "Free mode" | `GROQ_API_KEY` secret is missing or misspelled |
