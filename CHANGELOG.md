# Changelog

Notable changes, newest first. The full history is in `git log`; this starts
where the product began taking payments.

## 2026-09-28

**Every subscriber gets the whole cockpit.** Signing up now opens the same
sixteen-tab cockpit the founder uses, scoped to the subscriber's own data and
served through `/api/me`:

- Private workspaces; Clients, SEO and CRM for their own businesses.
- Voice sessions and Ask Titan, owned by whoever started them.
- Finance, Customers (their won leads) and an Executive report of their own.
- War Room, Growth Studio, next post and publishing, written for their own
  business. Nothing is posted or sent for them.
- Telegram through Titan's own bot, linked by a one-time code; Job Radar from
  the profile they write.
- The public demo is now that cockpit, on a read-only demo account.

**Fixed**

- The founder's live figures (`/api/voice-report`) and his AI quota
  (`/api/assistant`) were reachable without signing in.
- The period report named every business on the platform and counted every
  account's leads.
- Signup gave a paid plan before any payment; paid plans now come only from a
  confirmed payment.
- Voice: the first "thinking" of a conversation was never measured, and a
  reloaded page left its session "live" for ever.
- Negative money read "$-12".

**Pricing:** Student $5 (3-day trial), Individual $10 (7 days), Enterprise $20
(30 days) and a new Agency plan at $50.

## 2026-09-27

- Paddle checkout end to end in sandbox: a free customer can upgrade, and
  webhooks set the plan.
- Refund policy linked from every page, as Paddle's review requires.

## 2026-09-26

- A customer could pay and stay on Free; the webhook now applies the plan.
- Terms of service published for Paddle's review.
