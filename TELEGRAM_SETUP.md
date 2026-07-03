# Telegram Command Center — working setup (10 minutes, free)

**Why the bot didn't answer:** Hugging Face's servers block outbound
connections to Telegram's API (verified: persistent SSL handshake timeouts),
so the Space can never poll or reply directly — no token fixes that. The
working architecture is a free Cloudflare Worker relay:

```
You on Telegram → Telegram webhook → Cloudflare Worker → Titan /api/telegram/handle
                                            │                        │
             Telegram ◀── sendMessage ◀─────┘◀───────── reply ◀──────┘
```

## Step 1 — Create the Worker (free)
1. Sign up / log in at **dash.cloudflare.com** (free plan is plenty: 100k requests/day).
2. Left menu → **Workers & Pages → Create → Create Worker** → name it `titan-relay` → **Deploy**.
3. Click **Edit code**, delete everything, paste the whole contents of
   [`docs/telegram-worker.js`](docs/telegram-worker.js) from this repo → **Deploy**.

## Step 2 — Worker variables
Worker → **Settings → Variables and Secrets** → add these four (type: Secret):

| Name | Value |
|---|---|
| `BOT_TOKEN` | your token from @BotFather |
| `TITAN_URL` | `https://careermind2026-project-titan-omega.hf.space` |
| `TITAN_SECRET` | the SAME value as your Space's `TITAN_WEBHOOK_SECRET` secret |
| `TG_SECRET` | any random string you invent (e.g. 20 random letters) |

Click **Deploy** again after saving.

## Step 3 — Point Telegram at the Worker
Open this URL in your browser (replace the three placeholders):

```
https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://titan-relay.<your-subdomain>.workers.dev/&secret_token=<TG_SECRET>
```

(Your worker's exact URL is shown on its overview page.) You should see
`{"ok":true,...,"description":"Webhook was set"}`.

## Step 4 — Test
Message your bot `/start` → it should reply with the command list within ~2s.
Every command also appears on the dashboard's **Telegram** tab. Then:
1. Copy your chat id from that log.
2. Space → Settings → Secrets → add `TELEGRAM_CHAT_ID` = that id (locks the
   bot to you). Applies on the next Space restart/deploy.

## Known limitation (honest)
Outbound pushes FROM Titan (e.g. war-room decisions arriving proactively)
still can't leave HF's network. Commands and replies work fully through the
relay; proactive pushes will arrive when you next send any command (use
`/decision` to pull the latest pending decision).
