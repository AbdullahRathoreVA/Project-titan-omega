# Project Titan Omega — "Titan HUD" upgrade

Date: 2026-06-30
Owner: Abdullah
Status: Approved direction (mockup + two-question lock). Build mode: one push.

## Goal

Turn the existing Titan Omega command center into a Jarvis-class founder
cockpit: a live, futuristic HUD that does something visibly alive the moment it
opens, with a left sidebar for social channels + agents, a 3D centerpiece, and a
"next post" preview the founder can approve in one click. Reuse everything that
already works; do not rewrite the core.

## Non-goals

- No new auth model. Keep the existing token + webhook-secret gates.
- No paid services. Everything must run on the HF free tier with $0 keys.
- No fake live data. A channel shows a real number only once it has been pushed
  in; otherwise it shows a clear "connect" state.

## What already exists (reused, not replaced)

- FastAPI core with a 5s heartbeat (`backend/app/main.py`), in-memory `STORE`
  with JSON persistence, agents/divisions/opportunities/executions, a live feed
  (`/api/feed`), revenue ledger, Growth Studio, Ask Titan/voice, daily
  auto-content with free Flux images (`/api/content/daily`), Make.com webhooks
  (`/api/metrics/*`, `/api/revenue/log`, `/api/inbox/auto-reply`).
- Next.js dashboard (`frontend`) that polls every 5s (`CommandCenter.tsx`),
  HUD palette already in `tailwind.config.ts` (void/panel/edge + hud-cyan,
  blue, emerald, amber, rose, violet). Static-export deploy via `TITAN_STATIC=1`,
  served by FastAPI; auto-deploys to HF Spaces.

## New capabilities

### Backend (additive — existing contract untouched)

1. `GET /api/channels` — one row per channel (instagram, facebook, pinterest,
   linkedin, upwork, gmail). Each: `{id, name, status, value, label, href,
   accent}`. `value/label` come from `STORE.metrics` keys
   (`instagram_followers`, `facebook_followers`, `pinterest_followers`,
   `linkedin_followers`, `upwork_invites`, `gmail_unread`, …). `status` is
   `connected` when a metric exists, else `pending`. `href` is a deep link
   (env-overridable per channel).
2. `GET /api/next-post` — returns the cached "current next post" (caption +
   free Flux image URL + target + link). Generated lazily from the existing
   `content_daily` logic and cached on `STORE.next_post` so the card is stable.
3. `POST /api/next-post/approve` — schedules the cached post via `publisher`
   to its channels, emits a feed event, then regenerates a fresh next post.
4. `POST /api/next-post/regenerate` — discards the cached post and makes a new
   one (optional `topic`).
5. `GET /api/stream` — Server-Sent Events. Every ~1.5s yields a compact JSON
   frame: latest status snapshot, metric deltas, and any new feed events since
   the last frame, plus an `intensity` 0–1 derived from recent activity (drives
   the 3D core's spin/pulse). Auth: EventSource cannot set headers, so this
   endpoint accepts `?token=` (validated the same way as the Bearer token) and
   is whitelisted in the auth middleware for that query check.
6. Channel metric helper: reuse `/api/metrics/update` + `/api/metrics/bulk`
   (already webhook-gated) for Make.com to push channel stats — no new auth.

### Frontend

1. `Sidebar.tsx` — fixed left rail. Section "Channels": six rows (icon, name,
   status dot, value) each clicking through to the channel (`href`) or a draft
   action. Section "Agents": head agents with a status dot + current task,
   clicking opens the existing `AgentDetailModal`.
2. `TitanCore3D.tsx` — react-three-fiber scene: a wireframe globe + orbiting
   agent-network nodes in space; rotation speed + glow scale with the live
   `intensity` from the stream. Loaded via `next/dynamic` with `ssr:false` so
   static export is unaffected; a CSS fallback core renders if WebGL is absent.
3. `NextPost.tsx` — the next-post card (image, caption, target badge,
   "Approve & schedule" / "Regenerate"), wired to the new endpoints.
4. `useTitanStream.ts` — `EventSource` hook (token via query) feeding live
   counters, the feed ticker, and the core `intensity`; falls back to the
   existing 5s poll if the stream drops.
5. Re-layout `CommandCenter.tsx` into a HUD shell: left `Sidebar`, center
   column (metric row → 3D core → live feed → existing panels), right rail
   (`NextPost` + `OpportunityRadar`). All current panels (RevenueTracker,
   GrowthStudio, Publishing, ConnectedAssets, AskTitan, etc.) stay reachable.
6. `package.json`: add `three`, `@react-three/fiber`, `@react-three/drei`.

### Automation (Make.com)

Document two new scenarios in `MAKE_SETUP.md`:
- "Channel stats sync" — hourly: pull follower/invite/unread counts from each
  platform (or Google Sheet) → `POST /api/metrics/bulk` with the channel keys.
- "Auto-approve & post" — optional: when a new `next-post` is generated, push
  caption+image to the existing daily social scenario.

## Data flow

```
Make.com ──(channel stats)──▶ /api/metrics/bulk ──▶ STORE.metrics
                                                       │
heartbeat ──▶ STORE.feed / executions / metrics ──────┤
                                                       ▼
browser ◀── SSE /api/stream (status+deltas+intensity) ─┘
   │  └─ EventSource hook → counters, feed ticker, 3D core intensity
   └─ GET /api/channels, /api/next-post → Sidebar, NextPost card
```

## Risks / decisions

- SSE + EventSource header limit → token via query param, validated server-side.
- react-three-fiber bundle (~150KB) on free tier → dynamic import, ssr:false,
  CSS fallback; acceptable per user's "full 3D scene" choice.
- Static export must still build → all new components are client components.
- Don't lose existing features → re-layout, never delete working panels.

## Acceptance

- Opening the dashboard shows live motion within ~2s (core spins, counters tick,
  feed streams) with no manual refresh.
- Sidebar lists all six channels with real values when present, clear "connect"
  state otherwise, plus head agents with live current tasks.
- Next-post card shows a real generated image + caption; Approve schedules it and
  a fresh one appears.
- `frontend` static build succeeds; backend imports and `/api/stream`,
  `/api/channels`, `/api/next-post` respond.
