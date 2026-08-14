# Competitor monetization research — and what Titan should actually do

Researched 2026-08-14.

**Source honesty.** `openai.com/chatgpt/pricing` returns **HTTP 403** to
automated fetch, so the figures below come from third-party aggregators, not
from the official pages the brief asked for. They agree with each other, which
is weak corroboration, not proof. **Verify every price on the vendor's own page
before it goes into Titan's marketing.** Marked `[3P]` throughout.

## The headline finding, and it contradicts the plan

You asked for "free days on each subscription". **The market has moved the
other way.** None of the big three run a time-limited trial as the front door
any more — all three use a **permanently free tier with usage limits** `[3P]`.

| Product | Free entry | Mid tier | Budget tier | Premium |
|---|---|---|---|---|
| ChatGPT | Free, permanent (GPT-5.3, with ads) | Plus **$20** | **Go $8** | Pro **$200** |
| Claude | Free, permanent (Sonnet 4.5, Projects, Memory) | Pro **$20** ($17 annual) | — | Max **$100 / $200** |
| Gemini | Free, permanent (2.5 Flash, 100 credits) | AI Pro **$19.99** | **AI Plus $4.99** | Ultra **$249.99** |

Three things follow.

**1. $20 is the anchor.** Three independent companies landed on the same
number. Pricing a serious tier far above $20 needs a reason a buyer can state
in one sentence.

**2. Budget tiers are now normal, not a discount hack.** ChatGPT Go at $8 and
Google AI Plus at $4.99 exist because the $20 anchor excludes most of the
world. This is the precedent for Pakistan pricing — you are not asking for
special treatment, you are doing what OpenAI and Google already do.

**3. A time-limited trial creates a cliff the market has decided against.**
Day 8 with a trial is a locked-out user who has to make a purchase decision
under pressure. Day 8 with a free tier is a working user who hits a limit while
getting value. The second converts better and churns less.

## The referral warning — the most valuable single data point

Perplexity's referral programme **stacked to 24 free months** and was
**terminated on 31 May 2026** `[3P]`. A referral reward generous enough to be
worth gaming will be gamed, and the fix is always retroactive and ugly.

If Titan ships referrals: cap total earnable benefit, require the referred
account to reach a real activation event (a completed audit, not a signup), and
never let referral credit exceed a fraction of one paid month.

## Where the real acquisition lever is: students

- **Cursor Pro: free for a year** for verified students `[3P]`
- **Perplexity Education Pro: $10/mo**, 50% off, plus one free Pro month `[3P]`
- A `.edu` address unlocks a stack: Copilot, Cursor, Google AI Pro, Perplexity,
  JetBrains, Figma `[3P]`

This is a real channel, but **it is not Titan's channel yet**. Titan sells to
businesses that own a website. A student with no client has nothing to audit.
Revisit if an agency/freelancer tier appears.

## What Titan can actually afford — measured, not guessed

This is the part no competitor analysis can give you, and Titan now can,
because the model catalogue work made cost measurable:

| Model | Per audit-summary call | Per 1,000 |
|---|---|---|
| `openai/gpt-4o-mini` | $0.000720 | **$0.72** |
| `meta-llama/llama-3.3-70b-instruct` | $0.000424 | **$0.42** |

**A 100-audit free tier costs about 7 cents in inference.** The LLM is not the
constraint. The real costs are the crawl (bandwidth, and the renderer host if
you deploy it) and storage.

That means Titan can afford to be genuinely generous where competitors are
stingy, which is the only way a new product gets tried.

## Recommendation

**FREE — permanent, no card.** 1 business, 5 audits/month, full findings with
evidence, the legal compliance check. Fix proposals visible but **not
appliable**. Costs ~$0.004/user/month in inference.

*Why:* the compliance finding priced as a fine is the reason to pay. Show it
for free. Withholding the finding hides the value; withholding the *fix* keeps
the reason to upgrade.

**STARTER — $9/mo.** 3 businesses, 50 audits, fix apply + rollback, 24/7
monitoring. Sits at the ChatGPT Go / Google AI Plus budget anchor.

**PRO — $29/mo.** 15 businesses, unlimited audits, voice agent, client-ready
PDF reports, API. Above the $20 anchor because it is priced per *client
business*, not per seat — an agency billing 15 clients has an obvious ROI
sentence.

**Regional pricing for Pakistan/India** at roughly a third, following the
Google AI Plus precedent. Gate on payment-method country, not IP.

**No time-limited trial.** If you want urgency, run a *first-month* discount on
Starter, which does not lock anyone out when it ends.

## Do not ship

- Anything that fabricates urgency, scarcity, or user counts. Titan's entire
  differentiator is that it does not invent numbers; a fake "37 people are
  viewing this" would destroy the one thing that makes it credible.
- An uncapped referral programme. See Perplexity.
- A free tier so thin nobody experiences the product.

## The blocker, unchanged

**None of this can be charged for.** There is no payment processor connected.
This document is a plan, not revenue, until Paddle keys exist.
