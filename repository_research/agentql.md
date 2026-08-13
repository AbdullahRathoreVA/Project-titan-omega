# AgentQL (TinyFish) — research artifact

Source: https://github.com/tinyfish-io/agentql
Researched: 2026-08-13
**Research depth: repository README, docs.agentql.com, and pricing sources.**

## 1. Purpose
Connects LLM agents to live websites using **natural-language selectors** —
"queries work regardless of how a page's structure changes over time"
(self-healing). Extracts structured data from public, private and authenticated
pages.

## 2. Architecture
A thin SDK (Python and JavaScript) that **drives Playwright locally** but sends
the page and the query to **AgentQL's hosted service** to resolve selectors.
There is also a REST API for use without the SDK, plus an MCP server, a Chrome
debugger extension, and LangChain/Zapier integrations.

## 3. Important modules
Query language parser, Playwright integration layer, REST client, MCP server.

## 4. Dependencies
`agentql` from PyPI, plus **Playwright** — the same browser dependency that
already forced Titan's renderer into a separate service.

## 5. APIs
`page.query_data(query)` / `page.query_elements(query)` over a Playwright page;
plus a standalone REST endpoint.

## 6. Useful abstractions
Declarative, schema-shaped extraction: you describe the shape of the data you
want in a query and get structured output back, instead of writing per-site
selectors. This is genuinely better than regex for **variable** markup.

## 7. Useful algorithms
Selector resolution is server-side and proprietary. Not inspectable.

## 8. Security implications — significant
- **Page content leaves Titan's infrastructure.** AgentQL receives the DOM of
  whatever is being scraped. For a client's *authenticated* site that is a
  third-party data-processing relationship, which for an EU client is a GDPR
  processor question Abdullah would have to answer in a DPA.
- It is a natural-language selector engine reading **untrusted page content** —
  it belongs behind Titan's untrusted-content boundary, not in front of it.

## 9. Licence
**MIT** on the SDK. But the SDK is a *client for a paid hosted service*; the
MIT licence does not make the capability free.

## 10. Resource requirements / cost — **THE DECIDING FACTOR**
Requires `AGENTQL_API_KEY`. Pricing as researched 2026-08-13:
- **Starter: free, 50 API calls/month**, then **$0.02 per call**
- **Professional: $99/month**, 10,000 calls, then $0.015/call
- Search and Fetch (a different, simpler product) are free-tier generous.

Titan's 24/7 cycle re-audits every connected site every 6 hours, multiple pages
each. **Three clients would exhaust 50 calls/month in about a day**, after
which every audit silently costs money — against a product that currently
cannot take payment.

## 11. Production limitations for Titan
Metered per call, external dependency on the request path, and no offline mode.
A hosted selector service is also a new availability dependency for a core
customer-facing feature.

## 12. Relevant code patterns
Declarative extraction queries; structured output contracts.

## 13. Titan integration opportunities
Genuine and narrow: extracting **variable, per-site structured data** that regex
cannot generalise over — product catalogues, opening hours, menus, price lists,
staff/contact blocks — for the evidence ledger. Titan's own audit reads *fixed*
SEO elements (title, h1, canonical, JSON-LD), which regex already handles well
and which do not need self-healing selectors.

## 14. Titan incompatibilities
Cost model versus a $0-capital, pre-revenue product; data egress of client page
content; hosted dependency in the audit path.

## 15. Recommendation
**ADAPT — as an OPTIONAL, feature-flagged, off-by-default adapter.**

Specifically: do **not** clone the repository into Titan and do **not** put it
on the default audit path. Titan already solves the JS-rendering problem for
$0 with its own `services/renderer/` (Playwright, self-hosted). AgentQL solves
a *different* problem — variable structured extraction — that Titan does not
have a paying use for yet.

Correct sequencing: ship the free renderer, get revenue, then enable AgentQL
per-tenant for extraction work that a customer is actually paying for, with the
per-call cost recorded against that tenant. Wiring it in now would burn the
free tier during development and then bill Abdullah for his own testing.
