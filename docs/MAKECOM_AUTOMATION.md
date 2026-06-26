# Make.com Automation Scenarios for Titan Omega

Make.com (https://make.com) connects Titan Omega to the real world — it pushes
your actual Fiverr earnings, Career Mind signups, and income numbers directly
into the dashboard so the metrics you see are **your real numbers**, not seeds.

> **Pre-requisite:** Deploy Titan Omega to HF Spaces first (see DEPLOY_HF_SPACES.md)
> and set a `TITAN_WEBHOOK_SECRET`.

---

## Your webhook base URL

```
https://careermind2026-project-titan-omega.hf.space
```

All scenarios below POST to this base URL. Add this header to every HTTP module:
```
X-Webhook-Secret: <your TITAN_WEBHOOK_SECRET value>
```

---

## Scenario 1 — Push real Career Mind stats every hour

**What it does:** Reads live user counts from Career Mind and updates the
dashboard MRR, traffic and customer count with real numbers.

**Modules:**
1. **Schedule** — Every 1 hour
2. **HTTP: Make a request**
   - URL: `https://careermind2026-career-mind.hf.space/health`
   - Method: GET
3. **HTTP: Make a request** (update Titan Omega)
   - URL: `https://careermind2026-project-titan-omega.hf.space/api/metrics/bulk`
   - Method: POST
   - Headers: `X-Webhook-Secret: {{your_secret}}`, `Content-Type: application/json`
   - Body:
     ```json
     {
       "metrics": {
         "traffic": {{step2.body.daily_visits}},
         "customers": {{step2.body.total_users}}
       },
       "source": "career_mind"
     }
     ```

---

## Scenario 2 — Update MRR from your income manually each week

**What it does:** You fill in a simple Google Form with your weekly income,
Make.com pushes it to Titan Omega automatically.

**Modules:**
1. **Google Sheets: Watch rows** (or Google Forms: Watch responses)
2. **HTTP: Make a request**
   - URL: `.../api/metrics/bulk`
   - Method: POST
   - Body:
     ```json
     {
       "metrics": {
         "mrr": {{income_this_month}},
         "fiverr_orders": {{fiverr_orders}},
         "fiverr_revenue": {{fiverr_revenue}}
       },
       "source": "manual_income_update"
     }
     ```

---

## Scenario 3 — Daily opportunity digest to your email

**What it does:** Every morning at 8am, emails you the top 3 ranked
opportunities so you always know what to work on.

**Modules:**
1. **Schedule** — Every day at 08:00
2. **HTTP: Make a request**
   - URL: `.../api/opportunities`
   - Method: GET
3. **Array aggregator** — Take first 3 items
4. **Gmail / Email: Send an email**
   - To: `rathoreabdullah816@gmail.com`
   - Subject: `🎯 Today's Top 3 Titan Omega Opportunities`
   - Body (HTML):
     ```
     <h2>Your top 3 opportunities today:</h2>
     <ol>
       {{#each opportunities}}
       <li><strong>{{title}}</strong> — Score: {{priority_score}}<br>
       Expected revenue: ${{expected_revenue}}<br>
       {{description}}</li>
       {{/each}}
     </ol>
     ```

---

## Scenario 4 — Weekly empire report to your email

**What it does:** Every Monday at 9am, generates an AI-written weekly empire
report and emails it to you.

**Modules:**
1. **Schedule** — Every Monday at 09:00
2. **HTTP: Make a request**
   - URL: `.../api/report/weekly`
   - Method: POST
3. **Gmail / Email: Send an email**
   - To: `rathoreabdullah816@gmail.com`
   - Subject: `📊 Weekly Titan Omega Empire Report`
   - Body: `{{step2.body.content}}`

---

## Scenario 5 — Auto-post new deliverables to LinkedIn

**What it does:** When you generate a new deliverable in Titan Omega, it
automatically creates a LinkedIn post (for content marketing).

> Note: LinkedIn API access requires a LinkedIn Developer App.
> Alternative: use Make.com's LinkedIn module with your account.

**Modules:**
1. **Schedule** — Every 4 hours (checks for new deliverables)
2. **HTTP: Make a request**
   - URL: `.../api/deliverables`
   - Method: GET
3. **Filter** — Only continue if a deliverable was created in the last 4 hours
4. **LinkedIn: Create a post** (or HTTP to LinkedIn API)
   - Text: `{{latest_deliverable.title}}\n\n{{latest_deliverable.content | truncate(500)}}`

---

## Metric keys reference

These are the keys the dashboard reads from `STORE.metrics`:

| Key | What it controls on dashboard |
|---|---|
| `mrr` | Monthly Recurring Revenue card |
| `traffic` | Monthly Traffic card |
| `pipeline_value` | Pipeline Value card |
| `customers` | Total Customers card |
| `conversion_rate` | Conversion rate % |
| `brand_value` | Brand value score |

You can also push **any custom key** — it appears in `GET /api/metrics`
and the evolution engine can use it for scoring.

---

## Security checklist

- [x] Set `TITAN_WEBHOOK_SECRET` in HF Space secrets
- [x] Add `X-Webhook-Secret` header to every Make.com HTTP module
- [x] Keep your Space **Private** (login required)
- [x] Never put secrets in Make.com scenario names or descriptions
