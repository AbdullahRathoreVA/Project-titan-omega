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

Titan already implements steps 1, 2 and 4 behind one adapter seam
(`core/billing.py`). Only the account and its keys are missing.

## Setup checklist

- [ ] Payoneer account, verified, in Abdullah's own name
- [ ] Paddle seller account; add Payoneer as the payout method
- [ ] One **subscription price** per paid tier: Student $4, Individual $19,
      Enterprise $99
- [ ] Set as Space secrets: `PADDLE_API_KEY`,
      `PADDLE_PRICE_ID_STUDENT`, `PADDLE_PRICE_ID_INDIVIDUAL`,
      `PADDLE_PRICE_ID_ENTERPRISE`
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
- [ ] Point the processor's webhook at `POST /api/webhooks/billing`
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
