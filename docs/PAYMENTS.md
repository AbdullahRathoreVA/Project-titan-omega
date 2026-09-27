# Getting paid from Pakistan

Researched 2026-08-08 against each processor's own published country lists.
This is the one blocker between Titan and revenue, so it is written down rather
than remembered.

## The short answer

**Use Paddle. Payouts go to Payoneer. The account must be in Abdullah's own
name.**

## Why not the obvious routes

| Route | Verdict |
|---|---|
| **Stripe** | Does not support Pakistan-based sellers. |
| **PayPal** | Cannot **receive** money in Pakistan. Sending works; receiving does not. A PayPal-only build can never be paid. |
| **Gumroad, Payhip, Etsy, Buy Me a Coffee** | All pay out via PayPal or Stripe. Same wall. |
| **Lemon Squeezy** | Requires a bank **or PayPal** payout in a supported country. Verify the Pakistan bank-payout path before committing. |
| **Paddle** | ✅ Pakistan is **not** on Paddle's unsupported-suppliers list (that list is Afghanistan, Belarus, Cuba, Iran, North Korea, Russia, Syria, and similar). Pays out by **Payoneer** or wire. ~5% + $0.50. |
| **Dodo Payments** | Same Merchant-of-Record model, pays to Payoneer and Wise. Confirm current Pakistan onboarding directly with them — availability was reported to have changed. |
| **Payoneer** | Not a checkout. It is the **receiving** account the processor pays into, and it works well in Pakistan. |

## Re-checked 2026-09-03 — what changed, and what did not

The table above was researched 2026-08-08. Re-checked against current sources
before Abdullah sets the keys. **The conclusion did not change: Paddle, paid out
through Payoneer.** What follows is the detail behind that, so the decision can
be re-argued rather than taken on trust.

### The five real options, in order of fit

| | Fee | Merchant of Record | Pakistan payout | Verdict for Titan |
|---|---|---|---|---|
| **Paddle** | ~5% + $0.50 | Yes | **Payoneer** or wire | ✅ **Use this.** Payoneer works well in Pakistan. Built for SaaS subscriptions specifically. |
| **Lemon Squeezy** | 5% + $0.50 | Yes | bank wire, or PayPal | ⚠️ PayPal cannot receive in Pakistan, so wire only — in practice via a Wise USD account. Now Stripe-owned; some countries have been moved to an invite system, so confirm at signup. |
| **Polar** | from 5% + $0.50 | Yes | varies | ⚠️ Newer. Rates fall with volume. Confirm Pakistan onboarding directly. |
| **Dodo Payments** | similar | Yes | Payoneer / Wise | ❌ Abdullah confirmed it is **not available in Pakistan**. The adapter exists and is demoted. |
| **Gumroad** | 10% + $0.50, plus card fees | Yes (since 2025) | PayPal / Stripe | ❌ ~13% effective, and built for one-off downloads rather than subscriptions. |
| **Stripe** | 2.9% + $0.30 | **No** | — | ❌ No Pakistan-based sellers. Would need a US LLC, and you would then owe the tax compliance an MoR handles for you. |

### Why Merchant of Record matters more than the fee

Paddle's ~5% looks expensive next to Stripe's 2.9%. It is not comparable.

A Merchant of Record is the legal seller. Paddle collects and remits sales tax
and VAT across 200+ jurisdictions, issues compliant invoices, and absorbs
chargebacks. With Stripe you are the seller of record, which means **you** are
liable for EU VAT registration, UK VAT, and US state sales tax the moment you
cross a threshold — from Pakistan, alone, with no accountant.

The difference between 2.9% and 5% is about $2 on a $99 sale. A single missed
VAT filing costs more than a year of that.

### What Paddle will ask for

Paddle's review is stricter than Lemon Squeezy's and specifically wants to see a
real product at a real address before approving. Titan is in good shape for
this — it is live, it has a working free tier, real pricing, a privacy policy,
and an audit that runs. Two things worth doing first:

- **Set `TITAN_STREET` / `TITAN_LOCALITY` / `TITAN_COUNTRY`.** Titan publishes a
  postal address on its own pages when these are set, and refuses to publish a
  partial one. A reviewer looking for a contactable business finds nothing today.
- Make sure `/pricing`, `/privacy`, `/terms` and `/refunds` are reachable.
  Paddle's review looks for terms of service and a refund policy; the last two
  pages were added on 2026-09-27 because Titan had neither.

Expect verification to take days, not minutes, and expect questions. That is
the process working, not a rejection.

### Payout mechanics

- **Paddle → Payoneer.** Payoneer is not a checkout; it is the receiving account
  Paddle pays into, and it is well supported in Pakistan.
- **Minimum payout is around $100** and is adjustable in Paddle's dashboard.
  Below the threshold the balance rolls over rather than being lost.
- The Payoneer account **must be in Abdullah's own name** — see the section
  below, which has not changed and is not negotiable.

### The order to do this in

1. Payoneer account, verified, own name.
2. Paddle seller account; add Payoneer as the payout method; complete verification.
3. One **subscription price** per paid tier: Student $5 (3-day trial),
   Individual $10 (7-day trial), Enterprise $20 (30-day trial), Agency $50 (no
   trial) — set by Abdullah on 2026-09-28, and the same as `billing.PLANS`.
   Note the **price id** for each (`pri_...`).
4. Copy the **client-side token** from Paddle > Developer tools > Authentication.
   This is a different credential from the API key — see the checklist below.
5. Create the webhook destination (checklist below) and set all seven variables
   as Space secrets — the API key, the client-side token, four price ids and
   `PADDLE_WEBHOOK_SECRET` — then restart the Space.
6. **Prove it with the curl in the checklist.** Do not skip this. On 2026-09-03
   `processor_name()` reported "paddle" while every customer was being told to
   configure PayPal, so that string is not evidence of anything.
7. Make one real purchase against the **sandbox** first (the default), with the
   browser console open. Only then set `PADDLE_LIVE=1`.

## Using somebody else's account — do not

The idea of routing payments through a relative's PayPal in Canada, or any
account not in the seller's own name, comes up because it looks like a
shortcut. It is not, and it fails in expensive ways:

1. **It breaks the user agreement of every processor.** Accounts must belong to
   the person or business receiving the funds. This is not a technicality they
   ignore — it is the core of their KYC obligation.
2. **Their fraud systems are built to catch exactly this.** A Canadian personal
   account suddenly taking recurring international subscription revenue, with
   logins from Pakistan, is the textbook pattern. The usual outcome is a freeze
   with funds held for 180 days, then permanent closure.
3. **The money legally becomes the account holder's income.** The brother would
   owe Canadian tax on Titan's revenue, and would have to explain payments he
   did not earn.
4. **Sustained, it is the structure of money laundering** — moving business
   income through a third party's account to bypass a jurisdiction restriction
   — regardless of intent.

The risk lands on the family member, not on the person who suggested it. There
is a legitimate route that takes about the same effort, so there is no reason
to take this one.

**A company incorporated abroad is different and legal** — a real UK or US
entity, with its own bank account, that Abdullah owns and declares. That is a
genuine option later. It costs money and needs an accountant; it is not a
shortcut for today.

## What "attach a card and I get paid" actually looks like

This is what Abdullah described, and it is exactly what a Merchant of Record
does:

1. Customer clicks **Upgrade** on titanomega-ai.com.
2. Titan calls the processor and receives a hosted `checkout_url`. **Titan never
   sees the card.**
3. The customer enters their card on the processor's page. The processor is the
   legal seller of record and handles US sales tax and EU VAT.
4. A webhook tells Titan the subscription is active, and `set_plan()` lifts the
   account's quotas.
5. The processor pays out on a schedule to **Payoneer**, and Payoneer withdraws
   to a Pakistani bank in PKR.

Titan implements steps 1, 2 and 4 behind one adapter seam (`core/billing.py`).
**Step 4 did not exist until 2026-09-27**, although this document said it did:
there was no webhook route, and `set_plan()` had no caller but the founder's
manual grant, so a customer who paid stayed on Free. It is now
`POST /api/webhooks/billing`, verified with `PADDLE_WEBHOOK_SECRET`.

## Setup checklist

- [ ] Payoneer account, verified, in Abdullah's own name
- [ ] Paddle seller account; add Payoneer as the payout method
- [ ] One **subscription price** per paid tier: Student $5 / 3-day trial,
      Individual $10 / 7-day trial, Enterprise $20 / 30-day trial, Agency $50 /
      no trial
- [ ] Set as Space secrets: `PADDLE_API_KEY`,
      `PADDLE_PRICE_ID_STUDENT`, `PADDLE_PRICE_ID_INDIVIDUAL`,
      `PADDLE_PRICE_ID_ENTERPRISE`, `PADDLE_PRICE_ID_AGENCY`
- [ ] **`PADDLE_CLIENT_TOKEN`** — Paddle > Developer tools > Authentication.
      **This is a different credential from the API key and the checkout
      cannot open without it.** The API key configures the server; the browser
      opens Paddle's overlay with a *client-side* token, which Paddle
      documents as safe to publish in frontend code. This line was missing
      from the checklist until 2026-09-03, so following the old version left
      you server-ready and still unable to sell.
- [ ] Optionally `PADDLE_LIVE=1`. **Without it the checkout runs against
      Paddle's SANDBOX**, deliberately: a deployment that defaults to live is
      one typo away from taking a real card during a test.
- [ ] Paddle > Developer tools > Notifications > **New destination**:
      URL `https://titanomega-ai.com/api/webhooks/billing`, events
      `subscription.created`, `subscription.activated`, `subscription.updated`,
      `subscription.canceled`, `subscription.paused`, `subscription.resumed`,
      `subscription.past_due`, `subscription.trialing`. Copy the destination's
      **secret key** into the Space secret **`PADDLE_WEBHOOK_SECRET`** —
      without it the endpoint refuses everything (503), by design.
- [ ] Restart the Space — HF injects secrets only on restart

### Check it worked, before trusting it

`processor_name()` saying "paddle" is NOT proof a sale can complete. It was
saying exactly that on 2026-09-03 while `checkout()` returned
`Set PAYPAL_PLAN_ID_INDIVIDUAL.` to every customer, because the checkout path
had no Paddle branch at all — only the detector did.

Sign in as a subscriber and call it:

```bash
curl -s -X POST https://titanomega-ai.com/api/checkout/individual \
     -H "X-Account-Token: <a real account token>"
```

`"ready": true` with a `price_id` and a `client_token` means a customer can
complete a purchase. `"ready": false` names the exact variable still missing.
Anything else is not a working payment path, whatever the dashboard says.

Until that is done, signup and the free tier work normally and every checkout
refusal names exactly which variable is missing. Nothing is silently broken.
