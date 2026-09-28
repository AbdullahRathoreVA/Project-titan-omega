# Customer cockpit — Phase 2: the front door

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** A subscriber who signs in on `/` lands in the cockpit — the same boot, voice, Universe and tabs as the founder — reading only `/api/me`, with every founder-specific word replaced by theirs.

**Architecture:** A small session module decides founder / guest / customer. The API client prefixes `/me` and sends the account token for customers, and never falls back to the founder sample data (`MOCK`) for them. `CommandCenter` shows only the tabs whose routes are on `cockpit_scope.ALLOWED`.

## Global Constraints
- Spec and Phase 1 plan in `docs/superpowers/`.
- A customer never sees `MOCK` data, the founder's name, or his businesses (Career Mind, Upwork, Kindle, Fiverr).
- A customer never opens the founder's live stream (`/api/stream`) or premium voice (`/api/tts`).
- Frontend checks: `npm run typecheck`, `TITAN_STATIC=1 npm run build`; verified in a browser against an isolated local server.

### Task 1: session and API client (`frontend/lib/session.ts`, `frontend/lib/api.ts`)
- `session.ts`: `getCustomerToken()`, `setCustomerToken(t | null)` (localStorage `titan_customer`, mirrored to sessionStorage `titan_account` for /join), `isCustomer()`, `customerProfile()` / `setCustomerProfile({email, plan_name})`, `displayName()` (first word of the email's local part, capitalised).
- `api.ts`: `apiBase()` is `/api/me` for customers; `authHeaders()` sends `Authorization: Bearer <customer token>` for customers; every getter whose fallback is `MOCK.*` falls back to an empty value for customers; `verifyCustomer()` calls `/api/account` with `X-Account-Token` and stores the profile; `login()` returns `"account"` and stores the customer token instead of redirecting.

### Task 2: AuthGate
- `probe()`: a stored customer token that `verifyCustomer()` accepts → `ready` in customer mode, whether or not founder auth is required. An invalid one is cleared.
- Login success `"account"` → `ready` (cockpit), not `/join`.
- Sign-out clears both tokens.

### Task 3: CommandCenter and panels
- Tabs for customers: those with every route on the allowlist. Phase 2: Universe, Dashboard, Mission, Finance, CRM. Later phases add the rest.
- `useTitanStream` disabled for customers; online check uses the API base.
- Greeting, banner, footer, boot text, voice closer and Ask Titan prompt use `displayName()`; premium voice skipped for customers.
- Panels that call routes not yet allowlisted are hidden for customers (Publishing, Next post, Growth studio, Connected assets, Command bar, Ask Titan, Urdu voice, Revenue "log order", War Room auto-PR).
- A customer with no business sees a "Set up your first business" card linking to `/join`.

### Task 4: verify and ship
- Typecheck and static build.
- Isolated local server with founder auth ON: founder signs in → founder cockpit unchanged; subscriber signs in → cockpit with their name, zero figures, only the Phase 2 tabs, no `MOCK` text, no founder words anywhere in the page (checked by script over `document.body.innerText`).
- Full backend suite + mutation check, push, confirm live.
