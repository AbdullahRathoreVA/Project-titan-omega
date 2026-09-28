"""Mutation testing: check that a guard's test fails when the guard is removed.

A passing test proves nothing on its own - it might assert on a comment
instead of the code, or never reach the branch at all. This removes each
guard in turn and checks that the suite goes red.

Every mutation is restored and then verified byte-for-byte, and the run
aborts loudly if a file doesn't come back exactly.

Run:   python -m evaluation.mutation_check
       python -m evaluation.mutation_check --only backup
"""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
from typing import Optional

# (label, file, anchor, replacement, pytest -k selector)
MUTANTS: list[tuple[str, str, str, str, str]] = [
    # --- site fix loop ----------------------------------------------------
    ("sitefix: readback verification", "app/core/site_fix.py",
     'if after != fix["proposed"]:', "if False:",
     "discard or apply_writes"),
    ("sitefix: staleness check", "app/core/site_fix.py",
     'if live != fix["current"]:', "if False:",
     "proposal_is_refused"),
    ("sitefix: approval gate", "app/core/site_fix.py",
     'if fix["status"] != APPROVED:', "if False:",
     "cannot_be_applied_without"),
    ("sitefix: invented-fact strip", "app/core/site_fix.py",
     'for invented in ("priceRange", "openingHoursSpecification"):',
     "for invented in ():", "schema_never_publishes"),
    # --- queue ------------------------------------------------------------
    ("queue: attempt cap", "app/core/queue.py",
     "if attempts >= cap:", "if False:", "backs_off"),
    ("queue: retry backoff", "app/core/queue.py",
     "delay = min(BACKOFF_CAP, BACKOFF_BASE * (2 ** max(0, attempts - 1)))",
     "delay = 0.0", "backs_off"),
    ("queue: unhandled job waits", "app/core/queue.py",
     '_requeue_unhandled(job["id"])', "fail(job['id'], 'x')", "no_handler"),
    # --- rendering --------------------------------------------------------
    ("render: shell verdict", "app/core/render.py",
     "empty_mount or noscript or (thin and (frameworks or scripts >= 3))",
     "False", "shell or unreliable"),
    ("render: browser only on a shell", "app/core/render.py",
     'if not evidence["client_rendered"]:', "if False:", "browser"),
    ("audit: marks a shell unreliable", "app/engines/client_seo.py",
     'unreliable = rendering.get("reliable") is False', "unreliable = False",
     "unreliable"),
    # --- untrusted content ------------------------------------------------
    ("untrusted: detection", "app/core/untrusted.py",
     'suspicious": bool(hits) or invisible > 0,', 'suspicious": False,',
     "injection or untrusted"),
    ("untrusted: nonce fence", "app/core/untrusted.py",
     'nonce = secrets.token_hex(8)\n    marker = f"UNTRUSTED_{nonce}"',
     'nonce = "FIXED"\n    marker = f"UNTRUSTED_{nonce}"', "fence"),
    ("untrusted: invisible stripping", "app/core/untrusted.py",
     'out = _INVISIBLE.sub("", text or "")', 'out = text or ""', "invisible"),
    ("knowledge: fences crawled text", "app/core/knowledge.py",
     "built = untrusted.safe_prompt(", "built = _nope(",
     "voice_answer_path"),
    # --- observability ----------------------------------------------------
    ("obs: credential redaction", "app/core/obs.py",
     "if any(marker in lowered for marker in _REDACT_KEYS):\n        return REDACTED",
     "if False:\n        return REDACTED", "credential_never"),
    ("obs: email hashing", "app/core/obs.py",
     'return "email:" + hashlib.sha256(value.encode()).hexdigest()[:12]',
     "return value", "email_is_hashed"),
    ("obs: null not zero", "app/core/obs.py",
     '"slowest_ms": max(measured) if measured else None,',
     '"slowest_ms": max(measured) if measured else 0.0,', "log_stats"),
    # --- backup -----------------------------------------------------------
    ("backup: verification gate", "app/core/backup.py",
     'if not checked["ok"]:\n                # A backup that does not restore',
     'if False:\n                # A backup that does not restore',
     "fails_verification"),
    ("backup: restore confirm gate", "app/core/backup.py",
     "if not confirm:", "if False:", "refuses_without_confirmation"),
    ("backup: keeps replaced database", "app/core/backup.py",
     "shutil.copy2(live, aside)", "aside = aside", "disaster"),
    # --- retrieval --------------------------------------------------------
    ("retrieval: semantic floor", "app/core/knowledge.py",
     "COS_FLOOR = 0.60", "COS_FLOOR = 0.52", "semantic_floor"),
    ("retrieval: backfill is wired", "app/main.py",
     "await asyncio.to_thread(knowledge.backfill)", "pass",
     "backfill_is_actually"),
    ("retrieval: small-site IDF floor", "app/core/knowledge.py",
     "n_idf = max(n, IDF_MIN_PASSAGES)", "n_idf = n",
     "relative_to_the_corpus or small_sites"),
    ("retrieval: short sentences are kept", "app/core/knowledge.py",
     "if not _SENTENCE_END.search(part):", "if True:",
     "short_sentence or small_sites"),
    ("retrieval: question words are not topics", "app/core/knowledge.py",
     "and not (query and w in _QUESTION)]", "]",
     "question_words or small_sites"),
    ("retrieval: plurals match their stem", "app/core/knowledge.py",
     "return [_stem(w) for w in", "return [w for w in",
     "question_words or small_sites"),
    ("knowledge: a benchmark gets a private store", "app/core/knowledge.py",
     "_local.store, _local.no_embed = {}, not use_embeddings",
     "_local.no_embed = not use_embeddings", "never_touches_a_real_client"),
    ("benchmark: runs in the sandbox", "evaluation/retrieval_benchmark.py",
     "with knowledge.sandbox(use_embeddings=use_embeddings):", "if True:",
     "never_touches_a_real_client"),
    # --- Paddle webhook: the only unauthenticated write to a customer's plan --
    ("paddle webhook: signature is checked", "app/core/billing.py",
     "return any(hmac.compare_digest(expected, s) for s in sigs)", "return True",
     "forged_stale_or_unsigned"),
    ("paddle webhook: a stale request is refused", "app/core/billing.py",
     "if abs((now if now is not None else time.time()) - int(ts)) > WEBHOOK_TOLERANCE_S:",
     "if False:", "forged_stale_or_unsigned"),
    ("paddle webhook: a redelivery is not re-applied", "app/core/billing.py",
     "if event_id and event_id in seen:", "if False:", "late_events"),
    ("paddle webhook: a late event cannot undo a newer one", "app/core/billing.py",
     'if occurred and occurred <= last.get(sub_id, ""):', "if False:",
     "late_events"),
    # --- tenancy ----------------------------------------------------------
    # The half the ownership gate does NOT cover: the caller owns the client
    # id in the URL, and the resource id belongs to somebody else.
    ("tenancy: a resource id from another business is refused",
     "app/api/router.py",
     '    if not fix or fix["client_id"] != cid:',
     '    if not fix:',
     "fix_id_from_another_business"),
    ("tenancy: ownership gate", "app/core/tenancy.py",
     "if not email or not owns(email, client_id):", "if False:",
     "another_subscribers or owner_lookup"),
    ("tenancy: owns() actually checks", "app/core/tenancy.py",
     "return client_id in billing.owned_clients(email)", "return True",
     "another_subscribers or owner_lookup"),
    ("tenancy: gate binds the tenant", "app/core/tenancy.py",
     "obs.bind(tenant=client_id)", "pass", "ownership_gate_binds"),
    # --- model catalogue --------------------------------------------------
    ("catalog: negative price is unknown", "app/core/model_catalog.py",
     "return None if value < 0 else value", "return value",
     "negative_sentinel"),
    ("catalog: unknown price is not free", "app/core/model_catalog.py",
     "and completion_price is not None else None),",
     "and completion_price is not None else True),",
     "unknown_pricing or negative_sentinel"),
    ("catalog: cost is None without tokens", "app/core/model_catalog.py",
     "if prompt_tokens is None and completion_tokens is None:", "if False:",
     "cost_is_none"),
    # --- verification layer -----------------------------------------------
    ("verify: ungrounded figures rejected", "app/core/verify.py",
     "if digits and digits not in grounded:", "if False:",
     "invented_figure or hallucinated_voice"),
    ("verify: prohibited claims rejected", "app/core/verify.py",
     "prohibited = [why for pattern, why in _COMPILED_PROHIBITED\n                  if pattern.search(output)]",
     "prohibited = []", "prohibited_claims"),
    ("verify: is wired into the voice answer", "app/core/knowledge.py",
     "if reply and checked and checked[\"ok\"]:",
     "if reply:", "hallucinated_voice"),
    # --- billing / trials -------------------------------------------------
    ("billing: paddle needs a price id too", "app/core/billing.py",
     'return any(paddle_price_id(k) for k in ORDER if k != "free")',
     "return True", "paddle_was_invisible"),
    ("billing: paddle counts as a processor", "app/core/billing.py",
     "if paddle_configured():\n        return \"paddle\"",
     "if False:\n        return \"paddle\"", "paddle_was_invisible"),
    ("billing: trial not billable without processor", "app/core/billing.py",
     '"trial_billable": bool(days) and processor_configured(),',
     '"trial_billable": bool(days),', "not_advertised_as_billable"),
    ("billing: signup never grants a paid plan", "app/core/billing.py",
     '"plan": "free",\n            "requested_plan": plan,',
     '"plan": plan,\n            "requested_plan": plan,',
     "choosing_a_paid_plan_at_signup"),
    ("billing: an unpaid plan drops to free on restore", "app/core/billing.py",
     'if acct.get("status") == "pending_payment":', "if False:",
     "unpaid_paid_plan_saved_before_the_fix"),
    ("portal: a subscriber's business shows its plan", "app/core/billing.py",
     'if client_id and client_id in acct.get("client_ids", []):', "if False:",
     "shows_its_plan_not_a_trial_clock"),
    # --- customer cockpit: a customer only ever sees their own workspace ---
    ("cockpit: STORE follows the bound workspace", "app/store.py",
     "return bound if bound is not None else _FOUNDER", "return _FOUNDER",
     "store_proxy_follows or never_shows_founder_data"),
    ("cockpit: a customer request binds their own workspace", "app/main.py",
     "store_token = _store.bind(workspaces.for_account(email))",
     "store_token = _store.bind(_store.founder_store())",
     "never_shows_founder_data or reads_their_own_workspace"),
    ("cockpit: only allowlisted routes open to customers", "app/main.py",
     "if not cockpit_scope.allowed(request.method, inner):", "if False:",
     "not_on_the_allowlist_is_closed or refuses_everything"),
    ("cockpit UI: customers never get founder sample data",
     "../frontend/lib/api.ts",
     'get<EmpireStatus | null>("/status", fb<EmpireStatus | null>(MOCK.status, null))',
     'get<EmpireStatus | null>("/status", MOCK.status)',
     "never_shown_the_founder_sample_data"),
    ("cockpit UI: customers only see their tabs",
     "../frontend/components/CommandCenter.tsx",
     ".filter(([v]) => !customer || CUSTOMER_TABS.has(v))",
     ".filter(() => true)",
     "never_shown_the_founder_sample_data"),
    ("cockpit UI: the founder's live stream stays off for customers",
     "../frontend/components/CommandCenter.tsx",
     "useTitanStream(!customer)", "useTitanStream()",
     "never_shown_the_founder_sample_data"),
    ("cockpit: a subscriber's business route refuses anyone else's",
     "app/api/mine.py",
     "if cid not in billing.owned_clients(email) or not clients.get(cid):",
     "if not clients.get(cid):", "businesses_are_theirs_alone"),
    ("cockpit: no subscriber bound, nothing served", "app/api/mine.py",
     'if not email:\n        raise HTTPException(status_code=404, detail="Not found")',
     'if False:\n        raise HTTPException(status_code=404, detail="Not found")',
     "businesses_are_theirs_alone"),
    ("cockpit: the Clients overview lists only their own", "app/api/mine.py",
     "**clients.admin_overview(only=set(billing.owned_clients(email))),",
     "**clients.admin_overview(),", "businesses_are_theirs_alone"),
    ("cockpit: a re-audit spends the plan's audits", "app/api/mine.py",
     'verdict = billing.consume(email, "audits")',
     'verdict = {"allowed": True}', "re_audit_spends"),
    ("cockpit: the CRM owner comes from the session", "app/api/finance.py",
     "return cockpit_scope.customer_email() or crm.FOUNDER",
     "return crm.FOUNDER", "crm_is_theirs_alone"),
    ("cockpit: saving pins the founder store", "app/persistence.py",
     "if store is STORE:\n        store = founder_store()",
     "if False:\n        store = founder_store()",
     "saves_the_founder_not_the_customer"),
    ("cockpit voice: the session owner comes from the session", "app/api/voice.py",
     "return cockpit_scope.customer_email() or vs.FOUNDER", "return vs.FOUNDER",
     "voice_sessions_belong"),
    ("cockpit voice: someone else's session does not exist",
     "app/core/voice_sessions.py",
     'if not s or s.get("account", FOUNDER) != account:', "if not s:",
     "voice_sessions_belong or never_shows_founder_data"),
    ("cockpit voice: lists are only the caller's sessions",
     "app/core/voice_sessions.py",
     'if s.get("account", FOUNDER) == account]', "]",
     "voice_sessions_belong or never_shows_founder_data"),
    ("cockpit voice: a subscriber approves as themselves", "app/api/voice.py",
     "approver = owner or req.approver", "approver = req.approver",
     "voice_sessions_belong"),
    ("cockpit voice: the founder's keys are never ready for a subscriber",
     "app/api/voice.py",
     'return not customer and all(os.getenv(n, "").strip() for n in names)',
     'return all(os.getenv(n, "").strip() for n in names)',
     "voice_sessions_belong"),
    ("cockpit voice: one subscriber cannot evict everyone's calls",
     "app/core/voice_sessions.py",
     "for stale in own[:max(0, len(own) - MAX_PER_ACCOUNT)]:",
     "for stale in []:", "push_everyone_elses"),
    ("approvals: the voice link is the route that approves",
     "app/core/approvals.py",
     "f\"/tool/{call['call_id']}/approve\"",
     "f\"/tools/{call['call_id']}/approve\"",
     "points_at_the_route_that_approves"),
    ("cockpit assistant: a subscriber is briefed with their own data",
     "app/api/router.py",
     'is_urdu = lang == "ur"\n    subscriber = cockpit_scope.customer_email()',
     'is_urdu = lang == "ur"\n    subscriber = ""',
     "answers_a_subscriber"),
    ("cockpit assistant: the no-AI fallback is theirs too", "app/api/router.py",
     "if not raw and subscriber:", "if False:", "answers_a_subscriber"),
    ("cockpit UI: Ask Titan asks the subscriber's own door",
     "../frontend/components/AskTitan.tsx",
     "fetch(`${apiBase()}/assistant`", 'fetch("/api/assistant"',
     "use_the_subscribers_own_door"),
    ("cockpit UI: the Voice screen reads the subscriber's own sessions",
     "../frontend/components/VoiceAgents.tsx",
     "fetch(`${apiBase()}/voice${path}`", "fetch(`/api/voice${path}`",
     "use_the_subscribers_own_door"),
    ("cockpit UI: a subscriber's cockpit never drafts the founder's next post",
     "../frontend/components/CommandCenter.tsx",
     "customer && !hasBusinessRef.current ? none<NextPostType | null>(null) : api.nextPost(),",
     "api.nextPost(),", "never_shown_the_founder_sample_data"),
    ("cockpit executive: the report names only the caller's businesses",
     "app/engines/bi.py",
     'rows = [c for c in rows if c["id"] in own]', "rows = rows",
     "names_only_the_callers"),
    ("cockpit executive: the funnel counts only the caller's leads",
     "app/engines/bi.py",
     "f = _funnel(crm.visible_to(_leads(), _owner()))",
     "f = _funnel(list(_leads().values()))", "names_only_the_callers"),
    ("cockpit executive: the SEO panel lists only their businesses",
     "app/api/mine.py",
     "rows, scored = seo_rows(only=_mine())", "rows, scored = seo_rows()",
     "names_only_the_callers"),
    ("cockpit finance: a subscriber's sale is not cheered as the founder's",
     "app/api/router.py",
     'cheer = ("Your business is earning!" if cockpit_scope.is_customer()',
     'cheer = ("Your business is earning!" if False', "money_is_their_own"),
    ("cockpit UI: a subscriber's Customers tab is their won leads",
     "../frontend/components/CommandCenter.tsx",
     '(customer ? <MyCustomers onOpenCrm={() => setView("crm")} /> : <Customers />)',
     "<Customers />", "money_screens_show_a_subscriber"),
    ("cockpit UI: Executive never asks for the founder's analytics",
     "../frontend/components/ExecutiveCommand.tsx",
     'customer ? none<Analytics>() : api<Analytics>("/founder/analytics"),',
     'api<Analytics>("/founder/analytics"),', "money_screens_show_a_subscriber"),
    ("cockpit war room: the engines know when a subscriber is asking",
     "app/engines/owner.py",
     "if not email:\n        return None\n    from ..core import billing, clients",
     "return None\n    from ..core import billing, clients",
     "war_room_works_for"),
    ("cockpit war room: a subscriber's debate never reaches the founder's phone",
     "app/engines/autonomous.py",
     "    if not subscriber:\n        store.pending_decision",
     "    if True:\n        store.pending_decision", "war_room_works_for"),
    ("cockpit war room: no business, nothing spent researching it",
     "app/engines/autonomous.py",
     "    if not businesses:\n        intel = {**_empty()",
     "    if False:\n        intel = {**_empty()", "war_room_works_for"),
    ("cockpit war room: the content team writes for the subscriber",
     "app/engines/repurpose.py",
     "system=_team() + _PROMPT", "system=_FOUNDER_TEAM + _PROMPT",
     "war_room_works_for"),
    ("cockpit war room: a subscriber's runs are rate-limited", "app/api/growth.py",
     'verdict = ratelimit.check("warroom", email)', 'verdict = {"allowed": True}',
     "war_room_is_rate_limited"),
    ("cockpit: a subscriber is never told to set an API key", "app/core/quota.py",
     "    email = current()\n    if not email:\n        return founder_text",
     "    email = current()\n    return founder_text",
     "never_told_to_set_an_api_key"),
    ("cockpit UI: the auto-PR panel stays founder-only",
     "../frontend/components/WarRoomView.tsx",
     "{/* Auto-PR to Career Mind */}\n      {!customer && (",
     "{/* Auto-PR to Career Mind */}\n      {true && (",
     "war_room_screen_keeps"),
    ("cockpit: a subscriber's content packs survive a restart",
     "app/core/workspaces.py",
     '"deliverables": dict(list(ws.deliverables.items())[-_KEEP_DELIVERABLES:]),',
     '"deliverables": {},', "research_and_content_survive"),
    ("cockpit: a subscriber's War Room research survives a restart",
     "app/core/workspaces.py",
     '    if isinstance(snap.get("intel"), dict):\n        ws.intel = snap["intel"]',
     '    if False:\n        ws.intel = snap["intel"]', "research_and_content_survive"),
    ("cockpit posts: a subscriber's post never uses the founder's webhook",
     "app/engines/publisher.py",
     "url = None if customer else _webhook_url()", "url = _webhook_url()",
     "never_goes_through_the_founders_webhook"),
    ("cockpit posts: a subscriber is told Titan does not post for them",
     "app/api/actions.py",
     "    if cockpit_scope.is_customer():\n        return {\"ready\": False,",
     "    if False:\n        return {\"ready\": False,",
     "never_goes_through_the_founders_webhook"),
    ("cockpit posts: a placeholder draft cannot be approved", "app/api/actions.py",
     'if post.get("unavailable"):', "if False:",
     "never_goes_through_the_founders_webhook"),
    ("cockpit growth: lead finding shares the War Room's limit", "app/api/actions.py",
     "        limit_subscriber()\n        where =", "        where =",
     "war_room_is_rate_limited"),
    ("cockpit dashboard: agent chat works for the subscriber", "app/api/router.py",
     "    if businesses is not None:\n        company = (",
     "    if False:\n        company = (", "speaks_for_the_subscriber"),
    ("cockpit dashboard: the Urdu briefing is the subscriber's", "app/api/router.py",
     "    if subscriber:\n        return _subscriber_voice_report(subscriber)",
     "    if False:\n        return _subscriber_voice_report(subscriber)",
     "speaks_for_the_subscriber"),
    ("cockpit dashboard: founder-only studio kinds are not offered", "app/api/router.py",
     'kind = req.kind if req.kind in _SUBSCRIBER_INTEL else "market_analysis"',
     "kind = req.kind", "speaks_for_the_subscriber"),
    ("cockpit dashboard: the command bar reports to the owner", "app/core/executive.py",
     'boss = "the owner" if cockpit_scope.is_customer() else "the founder"',
     'boss = "the founder"', "speaks_for_the_subscriber"),
    ("security: the founder's figures and AI are not public", "app/main.py",
     '    "/api/intelligence",\n',
     '    "/api/voice-report",\n    "/api/assistant",\n    "/api/intelligence",\n',
     "no_longer_public"),
    ("telegram: the founder's chat is never linked to a subscriber",
     "app/core/telegram_links.py",
     "if not chat_id or (founder_chat and str(chat_id) == founder_chat):",
     "if not chat_id:", "linked_by_a_one_time_code"),
    ("telegram: a link code works once", "app/core/telegram_links.py",
     'entry = _codes.pop((code or "").strip(), None)',
     'entry = _codes.get((code or "").strip())', "linked_by_a_one_time_code"),
    ("telegram: a link code expires", "app/core/telegram_links.py",
     "if not entry or time.time() - entry[1] > CODE_TTL:", "if not entry:",
     "expires_and_cannot_be_guessed"),
    ("telegram: link codes cannot be guessed", "app/engines/telegram_subscribers.py",
     '        if not limited["allowed"]:\n            return "Too many tries.',
     '        if False:\n            return "Too many tries.',
     "expires_and_cannot_be_guessed"),
    ("telegram: the relay answers a linked chat from its own workspace",
     "app/api/comms.py",
     "theirs = telegram_subscribers.handle(req.chat_id, req.text, req.sender)",
     "theirs = None", "linked_by_a_one_time_code"),
    ("telegram: polling answers a linked chat from its own workspace",
     "app/engines/telegram_bot.py",
     "theirs = telegram_subscribers.handle(chat_id, text, sender)",
     "theirs = None", "polling_never_answers"),
    ("telegram: a subscriber's status is theirs", "app/api/comms.py",
     "    if email:\n        bot = telegram_links.bot_username()",
     "    if False:\n        bot = telegram_links.bot_username()",
     "linked_by_a_one_time_code"),
    ("job radar: a subscriber's hunt uses their profile", "app/engines/jobs.py",
     '    if _subscriber():\n        return str((store.jobs or {}).get("profile") or "")',
     '    if False:\n        return str((store.jobs or {}).get("profile") or "")',
     "own_profile"),
    ("job radar: a scan keeps the subscriber's profile", "app/engines/jobs.py",
     '**({"profile": profile} if subscriber else {})}', "}", "own_profile"),
    ("job radar: a subscriber's scan shares the hourly limit", "app/api/comms.py",
     "        limit_subscriber()\n    return jobs.scan(req.query, STORE)",
     "    return jobs.scan(req.query, STORE)", "war_room_is_rate_limited"),
    ("job radar: a subscriber's profile survives a restart", "app/core/workspaces.py",
     '                "jobs": ws.jobs,\n', "", "own_profile"),
    ("cockpit dashboard: the command bar acts for the subscriber",
     "app/api/actions.py",
     "    if businesses is not None:\n        return _subscriber_act(text, businesses)",
     "    if False:\n        return _subscriber_act(text, businesses)",
     "command_bar_acts_for_the_subscriber"),
    ("cockpit: every client call a subscriber makes reaches an open route",
     "app/core/cockpit_scope.py",
     '    ("POST", r"/api/agent/act"),\n', "",
     "every_client_call_a_subscriber"),
    ("demo: the demo account changes nothing, on any door", "app/main.py",
     'if request.method not in ("GET", "HEAD", "OPTIONS") and _is_demo_request(request):',
     "if False:", "demo_is_the_subscriber_cockpit"),
    ("demo: the demo account sees only Titan's demo businesses", "app/core/billing.py",
     "    if is_demo(email):\n        # Titan's own",
     "    if False:\n        # Titan's own", "demo_is_the_subscriber_cockpit"),
    ("demo: the demo account is nobody in the founder's figures", "app/core/analytics.py",
     '        if acct.get("is_demo"):\n            continue',
     "        if False:\n            continue", "demo_is_the_subscriber_cockpit"),
    ("demo: no AI is spent drafting posts for visitors", "app/api/actions.py",
     "if billing.is_demo(cockpit_scope.customer_email()):", "if False:",
     "demo_is_the_subscriber_cockpit"),
    ("demo: no demo business, no demo", "app/api/router.py",
     "if not demo_workspace.business_ids():", "if False:",
     "refused_rather_than_shown"),
    ("voice UI: a closed page ends its session",
     "../frontend/components/AskTitan.tsx",
     'window.addEventListener("pagehide", leave);', "",
     "use_the_subscribers_own_door"),
    # --- mobile information architecture ----------------------------------
    # Frontend files are CRLF in the working tree; the byte-preserving restore
    # above is what makes mutating them safe.
    ("mobile IA: numbers before the roster",
     "../frontend/components/CommandCenter.tsx",
     '<div className="min-w-0 space-y-4 lg:col-start-2 lg:row-start-1">',
     '<div className="min-w-0 space-y-4 lg:col-start-2 lg:row-start-1">'
     "<Sidebar channels={channels} agents={agents} />",
     "phone_reaches_the_numbers"),
    ("mobile IA: rail stays in the left column on desktop",
     "../frontend/components/CommandCenter.tsx",
     'className="lg:sticky lg:top-4 lg:col-start-1 lg:row-start-1',
     'className="lg:sticky lg:top-4 lg:row-start-1',
     "desktop_rail_is_still_pinned"),
    ("mobile IA: tab strip scroller stays live above sm",
     "../frontend/components/CommandCenter.tsx",
     'overflow-x-auto px-3 pb-1 sm:mx-0 sm:px-0',
     'overflow-x-auto px-3 pb-1 sm:mx-0 sm:overflow-visible sm:px-0',
     "tab_strip_cannot_overflow"),
    ("mobile IA: collapsed rail counts stay guarded",
     "../frontend/components/Sidebar.tsx",
     "if (channels.length > 0) {", "if (true) {",
     "collapsed_rail_summary"),
    # --- agent tool surface ------------------------------------------------
    ("tools: a self-reported failure is a failure", "app/core/tools.py",
     'if isinstance(payload, dict) and payload.get("ok") is False:',
     "if False:", "reports_its_own_failure"),
    ("tools: weather refuses without a location",
     "app/engines/adapters.py",
     "if latitude is None or longitude is None:", "if False:",
     "refuses_rather_than_guessing"),
    ("tools: the keyless capabilities stay registered",
     "app/engines/adapters.py",
     'name="weather.current",', 'name="weather.unregistered",',
     "sialkot or keyless_capabilities"),
    # --- independent security grade ---------------------------------------
    ("observatory: called with POST", "app/core/api_adapters.py",
     'method="POST")', 'method="GET")', "called_with_post"),
    ("observatory: no grade is not a zero", "app/core/api_adapters.py",
     'if d.get("grade") is None:', "if False:", "no_grade_is_not_reported"),
    ("runtime: method allowlist", "app/core/api_runtime.py",
     'if method not in ("GET", "POST"):', "if False:",
     "hardened_path_allows_only"),
    ("observatory: private names are never sent out",
     "app/core/api_adapters.py",
     'if name.endswith(".local") or name.endswith(".internal"):',
     "if False:", "private_name"),
    # --- Titan's own published contact details -----------------------------
    ("contact: a partial address is not published", "app/core/contact.py",
     "if not all(parts.values()):", "if False:", "postcode_on_its_own"),
    ("contact: <address> only when there IS an address", "app/core/contact.py",
     'tag = "address" if a else "p"', 'tag = "address"',
     "phone_only_block_never_emits"),
    # --- self-improvement engine -------------------------------------------
    # The approval gate is the key decision here. If any of these survive, Titan
    # could change its own behaviour without the founder's approval.
    ("improve: activate requires APPROVED", "app/core/improve.py",
     'if row["status"] != APPROVED:', "if False:",
     "cannot_activate_its_own"),
    ("improve: approve requires a measurement", "app/core/improve.py",
     'if row["status"] != EVALUATED:', "if False:",
     "unmeasured_proposal_cannot"),
    ("improve: approve requires a name", "app/core/improve.py",
     'if not (approver or "").strip():', "if False:",
     "approval_must_carry_a_name"),
    ("improve: a regression cannot be approved", "app/core/improve.py",
     'if row["regression"]:', "if False:", "measures_worse_cannot"),
    ("improve: only registered parameters", "app/core/improve.py",
     "if param not in params.PARAMS:", "if False:",
     "only_registered_parameters"),
    ("improve: measurement restores the value", "app/core/improve.py",
     "setattr(module, spec.attr, original)", "pass",
     "never_leaves_it_applied or explodes_still_puts"),
    ("improve: rollback restores what was RUNNING", "app/core/improve.py",
     "previous = float(params.current(row[\"param\"]))",
     "previous = float(params.PARAMS[row['param']].low)",
     "restores_what_was_running"),
    ("improve: auto-rollback on regression", "app/core/improve.py",
     "if worse:", "if False:", "rolled_back_automatically"),
    ("improve: a guard metric that got worse is a regression",
     "app/core/improve.py",
     "regression = regression or bool(broken)", "regression = regression",
     "guard_metric_cannot"),
    ("improve: auto-rollback watches the guards", "app/core/improve.py",
     'spec.higher_is_better) or bool(broken)', "spec.higher_is_better)",
     "watches_the_guard"),
    ("improve: a guard the benchmark omits cannot pass", "app/core/improve.py",
     "missing = [m for m in (spec.metric, *(g for g, _ in spec.guards))",
     "missing = [m for m in (spec.metric,)", "does_not_report_a_guard"),
    ("params: bounds are enforced", "app/core/params.py",
     "if not (param.low <= cast <= param.high):", "if False:",
     "outside_its_registered_bounds"),
    ("params: overrides are re-applied at boot", "app/main.py",
     "_params.apply_stored()", "pass", "actually_called_at_boot"),
    # --- approval centre ---------------------------------------------------
    ("approvals: a measured regression is never queued", "app/core/approvals.py",
     'if row.get("regression"):', "if False:", "never_offered_for_approval"),
    ("approvals: an empty queue reports None not zero", "app/core/approvals.py",
     '"oldest_seconds": max(ages) if ages else None,',
     '"oldest_seconds": max(ages) if ages else 0.0,',
     "empty_queue_reports_none"),
    # Single line on purpose: a multi-line anchor whose continuation indent
    # doesn't match the source reports "stale" instead of failing. Appending to a
    # throwaway list keeps the syntax valid and leaves `errors` empty.
    ("approvals: a broken surface is reported", "app/core/approvals.py",
     'errors.append({"surface": name,', '[].append({"surface": name,',
     "cannot_report_is_listed"),
    ("voice: pending tool calls are enumerable",
     "app/core/voice_sessions.py",
     'if call["status"] != "pending":', "if True:",
     "queue_shows_everything"),
    # --- cost-aware model routing ------------------------------------------
    ("router: high-risk keeps its tier floor", "app/core/model_router.py",
     "if self.high_risk and TIER_ORDER.index(self.tier) < TIER_ORDER.index(STANDARD):",
     "if False:", "high_risk_task_is_never"),
    ("router: tier floor is enforced", "app/core/model_router.py",
     "return [p for p in chain\n            if TIER_ORDER.index(provider_tier(p)) >= floor_idx]",
     "return list(chain)", "refuses_rather_than_silently or high_risk_task"),
    ("router: an unknown price is not free", "app/core/model_router.py",
     "cost_key = (cost is None, cost if cost is not None else 0.0)",
     "cost_key = (0, cost if cost is not None else 0.0)",
     "unknown_price_is_never"),
    ("router: catalogue 'measured' flag is honoured", "app/core/model_router.py",
     'if not isinstance(out, dict) or not out.get("measured"):',
     "if not isinstance(out, dict):", "catalogue_has_not_measured"),
    ("router: a cost ceiling refuses an unknown estimate",
     "app/core/model_router.py",
     "if cost is None or cost > task.max_cost_usd:",
     "if cost is not None and cost > task.max_cost_usd:",
     "cost_ceiling_refuses"),
    ("router: unpriced calls are not summed as zero", "app/core/model_router.py",
     '"estimated_cost_usd": (round(row["estimated_cost_usd"], 6)\n                               if row["priced_calls"] else None),',
     '"estimated_cost_usd": round(row["estimated_cost_usd"], 6),',
     "unpriced_calls"),
    # --- customers screen ---------------------------------------------------
    # The grant flag is the difference between a pilot seat and revenue. Both
    # halves are mutated: whether the flag is read at all, and whether reading it
    # changes the count.
    ("customers: a granted seat is not a paying customer",
     "app/core/analytics.py",
     "is_paying = on_paid_plan and not is_granted",
     "is_paying = on_paid_plan", "granted_seat_is_never_counted"),
    ("customers: the grant marker is actually read back",
     "app/core/analytics.py",
     'return str(acct.get("subscription_id", "")).startswith("granted")',
     "return False",
     "granted_seat_is_never_counted or bought_seat_is_still"),
    # --- identity ------------------------------------------------------------
    # Authorisation boundaries: "disabled" has to actually mean disabled.
    ("identity: a disabled account cannot sign in", "app/core/identity.py",
     'if row["status"] != ACTIVE:', "if False:",
     "disabled_account_cannot_sign_in"),
    ("identity: resolve re-checks the user is still active",
     "app/core/identity.py",
     'if not user or user["status"] != ACTIVE:', "if not user:",
     "revokes_a_session_they_already_hold"),
    ("identity: an unknown email still costs a hash", "app/core/identity.py",
     'verify_password(password or "", _dummy_hash())', "pass",
     "unknown_email_still_costs"),
    ("identity: roles are a closed set", "app/core/identity.py",
     "if role not in ROLES:", "if False:", "unknown_role_is_refused"),
    # --- the login cutover -------------------------------------------------
    # The environment gate in core/auth.py retires itself once a real founder
    # account exists. Anchors are single-line and unique because this tool
    # replaces the first match it finds.
    #
    # Not guarded: ensure_founder's weak-password refusal and its `if current:`
    # overwrite check. Removing either only changes the wording of the refusal,
    # because identity.create() independently enforces the password floor and the
    # UNIQUE constraint on email. A guard that can't fail isn't worth listing.
    ("cutover: a founder account retires the environment gate",
     "app/core/auth.py",
     "    if identity_retired_the_gate():", "    if False:",
     "retires_the_environment_gate"),
    ("cutover: a session from the old gate dies at the cutover",
     "app/core/auth.py",
     "if not sub or identity_retired_the_gate():", "if not sub:",
     "minted_by_the_old_gate_dies"),
    ("cutover: a member is never handed a founder session",
     "app/core/auth.py",
     '        if user and user["role"] == identity.FOUNDER:',
     '        if user:',
     "member_cannot_sign_in_at_the_founder"),
    ("cutover: a member session never opens the founder dashboard",
     "app/core/auth.py",
     '        if user is not None and user["role"] == identity.FOUNDER:',
     '        if user is not None:',
     "member_session_never_opens"),
    ("cutover: the host naming the founder actually promotes the account",
     "app/core/identity.py",
     "    if current:", "    if False:",
     "promoting_a_member_to_founder"),
    # --- organisations -----------------------------------------------------
    # Ranked authorisation, and the invariant that keeps an organisation
    # administerable. The last-owner rule is the one most likely to be
    # "simplified" away.
    ("orgs: roles are ranked, not just present", "app/core/orgs.py",
     "if role is None or RANK[role] < RANK[minimum]:", "if role is None:",
     "member_cannot_change_who_has_access"),
    ("orgs: a suspended organisation refuses everybody",
     "app/core/orgs.py",
     'if not org or org["status"] != ACTIVE:', "if not org:",
     "suspended_organisation_refuses"),
    ("orgs: the last owner cannot be demoted", "app/core/orgs.py",
     "if current == OWNER and role != OWNER and owner_count(org_id) <= 1:",
     "if False:", "never_lose_its_last_owner"),
    ("orgs: the last owner cannot be removed", "app/core/orgs.py",
     "if current == OWNER and owner_count(org_id) <= 1:", "if False:",
     "never_lose_its_last_owner"),
    ("orgs: an unknown role is refused, not stored", "app/core/orgs.py",
     "if role not in ROLES:", "if False:",
     "unknown_org_role_is_refused"),
    # --- audit log ---------------------------------------------------------
    # Redaction happens on the way in: once a secret reaches the table it's on
    # disk and in backups, and read-time filtering can't undo that.
    ("audit: a secret is never written to the table", "app/core/audit.py",
     "if any(hint in name for hint in _SECRET_HINTS):", "if False:",
     "never_stores_a_secret"),
    # --- executive metrics -------------------------------------------------
    # A measured zero vs null: $0 MRR looks like a business result, when really
    # nobody could pay and nothing was measured.
    ("metrics: revenue is null, not zero, when billing is not connected",
     "app/core/metrics.py", "    if not connected:", "    if False:",
     "revenue_is_not_measured_when_billing"),
    ("metrics: ARR is unmeasured for as long as MRR is",
     "app/core/metrics.py",
     '    if not base["measured"]:', "    if False:",
     "arr_stays_unmeasured"),
    ("metrics: churn over zero paid subscriptions is not zero percent",
     "app/core/metrics.py", "    if not at_risk:", "    if False:",
     "nothing_to_churn"),
    # --- the self-improvement loop's automatic half ------------------------
    ("improve: auto-rollback is actually driven by the heartbeat",
     "app/main.py",
     "await asyncio.to_thread(improve.check_active)", "pass",
     "auto_rollback_is_actually_driven"),
    # --- feature flags and onboarding --------------------------------------
    # A typo quietly meaning "off" makes a feature vanish for everyone, and an
    # unreadable check counted as a failure blames the customer for our outage.
    # Both are one deleted line away.
    ("flags: an unknown flag raises rather than reading as off",
     "app/core/flags.py", "    if flag is None:", "    if False:",
     "unknown_flag_raises"),
    ("onboarding: an unknown check is not counted as a failure",
     "app/core/onboarding.py", '        if state["done"] is None:',
     "        if False:", "unknown_check_is_not_counted"),
    # --- the Executive operations panel ------------------------------------
    # The operations APIs need a screen actually mounted in front of them.
    ("executive: the operations panel is actually mounted",
     "../frontend/components/ExecutiveCommand.tsx",
     "<ExecutiveOperations />", "<span />",
     "executive_view_mounts"),
    # --- durable state on a free Dataset repo ------------------------------
    # Two one-line ways to lose or expose data: restoring on top of a live
    # database, and creating the snapshot repo public when it holds every
    # account.
    ("remote_state: a pull never overwrites a live state file",
     "app/core/remote_state.py", "    if os.path.exists(dest):",
     "    if False:", "never_overwrites_a_state_file"),
    ("remote_state: the snapshot repo is created private",
     "app/core/remote_state.py",
     '        api.create_repo(repo_id=repo_id(), repo_type="dataset", private=True,',
     '        api.create_repo(repo_id=repo_id(), repo_type="dataset", private=False,',
     "push_is_recorded_as_proof"),
    # --- the two sign-in doors ---------------------------------------------
    # The sign-in box must try the subscriber door too, or a customer created from
    # the Executive screen is told a correct password is invalid.
    ("login: the sign-in box tries the subscriber door too",
     "../frontend/lib/api.ts",
     'await fetch("/api/account/login", {', 'await fetch("/api/__removed__", {',
     "tries_both_doors"),
    # --- the deployment secret ---------------------------------------------
    ("appsecret: production refuses to boot without a secret",
     "app/core/appsecret.py",
     "if enforced() and not configured():", "if False:",
     "production_refuses_to_start"),
    ("appsecret: a published default is not a secret",
     "app/core/appsecret.py",
     "return bool(value_) and value_ not in PUBLISHED_DEFAULTS",
     "return bool(value_)", "printed_in_the_repository"),
    ("appsecret: the check is called at boot", "app/main.py",
     "_appsecret.verify_at_startup()", "pass",
     "actually_wired_into_the_lifespan"),
    ("customers: the tab stays founder-only",
     "../frontend/components/CommandCenter.tsx",
     '["customers", "Customers", true],',
     '["customers", "Customers", false],',
     "customers_screen_is_reachable"),
    # --- the public demo opens the customer product ------------------------
    # This endpoint takes no credential. The only thing between a stranger and a
    # paying customer's audit findings is that the server picks the business and
    # only ever picks a demo one.
    ("demo: the showcase can only be a demo business",
     "app/engines/demo_workspace.py",
     "return [c for c in clients.all_clients() if is_demo_client(c)]",
     "return list(clients.all_clients())",
     "selects_on_the_demo_flag_not_on_the_url"),
    ("demo: an empty demo workspace refuses",
     "app/engines/demo_workspace.py",
     "rows = _demo_rows()\n    if not rows:\n        return None",
     "rows = _demo_rows()\n    if not rows:\n        pass",
     "refuses_rather_than_substituting"),
    ("demo: the route re-checks the flag itself",
     "app/api/router.py",
     "if not demo_workspace.is_demo_client(business):",
     "if False:",
     "refuses_a_business_that_is_not_marked_as_a_demo"),
    ("demo: the public demo is rate limited",
     "app/api/router.py",
     'if not portal_limit["allowed"]:',
     "if False:",
     "product_demo_is_rate_limited"),
    # --- portal sessions expire -------------------------------------------
    # --- the social playbook says what it was researched for --------------
    ("social: an uncovered industry gets no weekly plan", "app/api/router.py",
     'rec.get("city", ""), lang) if cover["covered"] else [],',
     'rec.get("city", ""), lang),',
     "wholesaler_is_not_handed_a_restaurant_week"),
    ("social: coverage is not everything", "app/engines/brand_playbook.py",
     "return key if key in COVERED_INDUSTRIES else \"\"",
     "return key",
     "measured_for"),
    ("social: the portal asks the server", "app/static/client.html",
     "const social = await api('/client/social');",
     "const social = {};",
     "portal_asks_the_server_instead_of_hardcoding"),
    # --- durable storage is checkable from outside the Space --------------
    ("doctor: intent is not proof", "app/api/actions.py",
     'durable["state_backup_proven"] = bool((st.get("last_push") or {}).get("ok"))',
     'durable["state_backup_proven"] = bool(st.get("configured"))',
     "separates_intending_to_back_up_from_having_backed_up"),
    # --- Paddle keys alone don't make a sale possible ---------------------
    ("paddle: billable means a card can be charged", "app/core/billing.py",
     "    if paddle_configured():\n        return paddle_checkout_ready()",
     "    if paddle_configured():\n        return True",
     "trial_is_not_billable_until_a_card_can_be_charged"),
    # processor_name() and checkout() must agree: when Paddle is configured,
    # checkout has to use it rather than fall through to PayPal.
    ("paddle: checkout actually uses Paddle", "app/core/billing.py",
     "    if paddle_configured():\n        return _paddle_checkout(email, plan_key, plan)",
     "    if False:\n        return _paddle_checkout(email, plan_key, plan)",
     "makes_a_sale_possible"),
    ("paddle: the api key stays server-side", "app/core/billing.py",
     '"client_token": token,',
     '"client_token": os.getenv("PADDLE_API_KEY", ""),',
     "api_key_never_reaches_the_browser"),
    ("paddle: a missing client token is named", "app/core/billing.py",
     "    token = paddle_client_token()\n    if not token:",
     "    token = paddle_client_token() or 'assumed'\n    if False:",
     "client_token_it_says_so_by_name"),
    ("paddle: sandbox unless told otherwise", "app/core/billing.py",
     'return "production" if os.getenv("PADDLE_LIVE", "").strip() else "sandbox"',
     'return "production"',
     "defaults_to_the_sandbox"),
    # --- a customer's own leads -------------------------------------------
    # A leads table shared by every customer is one missing filter away from
    # showing a business its competitor's pipeline.
    ("crm: the one filter that scopes a pipeline", "app/core/crm.py",
     "return [dict(lead) for lead in leads.values() if owns(lead, account)]",
     "return [dict(lead) for lead in leads.values()]",
     "never_sees_anothers_leads"),
    ("crm: a lead by id is checked for ownership", "app/core/crm.py",
     "if not lead or not owns(lead, account):",
     "if not lead:",
     "cannot_touch_anothers_lead"),
    ("crm: a legacy lead stays the founder's", "app/core/crm.py",
     'return str((lead or {}).get("account") or FOUNDER)',
     'return str((lead or {}).get("account") or "somebody@example.com")',
     "no_owner_stays_the_founders"),
    ("crm: a rate over nothing is not zero", "app/core/crm.py",
     "\"value\": round(won / closed, 4) if closed else None,",
     "\"value\": round(won / closed, 4) if closed else 0.0,",
     "win_rate_over_nothing_is_not_zero_percent"),
    ("crm: the founder screen is scoped too", "app/api/finance.py",
     "items = sorted(crm.visible_to(_leads(), _owner()),",
     "items = sorted(list(_leads().values()),",
     "founders_pipeline_is_not_the_customers or crm_is_theirs_alone"),
    # --- the plan's AI-call limit ------------------------------------------
    ("quota: llm.complete honours the plan limit", "app/core/llm.py",
     'if not verdict["allowed"]:', "if False:",
     "llm_complete_refuses_when_the_account_is_out"),
    ("quota: an ai call is actually charged", "app/core/quota.py",
     "verdict = billing.consume(email, kind, cost)",
     "verdict = {'allowed': True}",
     "an_ai_call_is_charged_to_the_account_that_asked"),
    ("quota: unbound work is charged to nobody", "app/core/quota.py",
     'return {"metered": False, "allowed": True,\n                "reason": "no billing account is bound to this request"}',
     'return {"metered": True, "allowed": True, "reason": ""}',
     "titans_own_work_is_charged_to_nobody"),
    ("quota: the middleware binds the account", "app/main.py",
     "quota.bind(_billing.resolve(token) or \"\")", "pass",
     "see_what_they_have_spent"),
    ("signup: an undeliverable address is refused", "app/core/billing.py",
     "problem = emailaddr.reason_invalid(email)",
     "problem = None",
     "nobody_could_receive_mail_at_is_refused"),
    ("signup: nothing claims an address is verified", "app/core/emailaddr.py",
     '"verified": False,', '"verified": True,',
     "claims_an_address_is_verified"),
    ("signup: deliverability fails open", "app/core/emailaddr.py",
     'return {"checked": False, "deliverable": None,\n                "reason": "MX checking is off (set TITAN_VERIFY_EMAIL_MX=1)"}',
     'return {"checked": True, "deliverable": False, "reason": "off"}',
     "deliverability_is_off_by_default_and_fails_open"),
    # --- password changes --------------------------------------------------
    ("password: the portal setter is owner-gated", "app/api/router.py",
     '    email = _owned(cid, x_account_token)\n    if not clients.set_password(cid, req.password):',
     '    email = "nobody"\n    if not clients.set_password(cid, req.password):',
     "cannot_set_another_businesss_portal_password"),
    ("password: the current one is required", "app/core/billing.py",
     'if not hmac.compare_digest(_hash(current, acct["_salt"]),',
     "if False:",
     "requires_the_current_one"),
    ("password: changing it ends other sessions", "app/core/billing.py",
     'sessions.invalidate_all(email, kind="account")', "pass",
     "signs_out_every_other_session"),
    ("sessions: the cutoff is honoured", "app/core/sessions.py",
     'if cutoff is not None and float(payload.get("iat", 0)) <= cutoff:',
     "if False:",
     "invalidate_all_ends_only_that_subjects_sessions"),
    ("sessions: a new token steps past the cutoff", "app/core/sessions.py",
     "if cutoff is not None and iat <= cutoff:", "if False:",
     "minted_after_the_cutoff_survives_it"),
    ("sessions: cutoffs are persisted", "app/core/sessions.py",
     'return {"revoked": dict(_revoked), "cutoffs": dict(_cutoffs)}',
     'return {"revoked": dict(_revoked)}',
     "cutoff_survives_a_restart"),
    # --- a kill switch has to kill -----------------------------------------
    ("flags: switching off site_fix stops proposing", "app/core/site_fix.py",
     'if not flags.is_enabled("site_fix"):\n        return {"ok": False, "error": (\n            "Website fixes are switched off for this deployment "\n            "(feature flag: site_fix)."), "proposed": [], "skipped": []}',
     "pass",
     "switching_off_site_fix_actually_stops_it"),
    ("flags: switching off site_fix stops applying", "app/core/site_fix.py",
     'if not flags.is_enabled("site_fix"):\n        return {"ok": False, "error": (\n            "Website fixes are switched off for this deployment "\n            "(feature flag: site_fix).")}',
     "pass",
     "switching_off_site_fix_actually_stops_it"),
    ("flags: switching off voice stops it", "app/core/voice_sessions.py",
     'flags.require("voice")', "pass",
     "switching_off_voice_actually_stops_it"),
    ("flags: an unenforced flag admits it", "app/core/flags.py",
     '"note": (None if flag.enforced_at else', '"note": (None if True else',
     "flag_nothing_consults_says_so"),
    ("plain: the audit does not assume a restaurant", "app/static/client.html",
     'images_alt: ["Label your images",',
     'images_alt: ["Label your food photos",',
     "plain_language_layer_does_not_assume"),
    ("restore: the lifespan records the boot outcome", "app/main.py",
     '_remote.record_restore("skipped_local_state_exists")',
     "pass",
     "lifespan_actually_records_the_restore"),
    ("restore: a failed restore is visible", "app/api/actions.py",
     'durable["state_restored_at_boot"] = restore.get("outcome") or "unknown"',
     'durable["state_restored_at_boot"] = "unknown"',
     "failed_restore_is_reported_as_failed"),
    ("doctor: a broken check reads unknown", "app/api/actions.py",
     'durable["state_backup_error"] = f"{type(exc).__name__}: {str(exc)[:80]}"',
     "pass", "reads_unknown_not_unconfigured"),
    ("clients: SESSION_TTL is enforced", "app/core/clients.py",
     "if time.time() - issued > SESSION_TTL:",
     "if False:", "portal_session_expires"),
    ("clients: an expired session is dropped", "app/core/clients.py",
     "_sessions.pop(token, None)\n            return None",
     "return None", "forgotten_not_merely_refused"),
    # --- the service worker never caches an error page ----------------------
    ("sw: a chunk is only cached when it is real",
     "../frontend/public/sw.js",
     "if (isGoodAsset(res)) {", "if (true) {",
     "never_caches_an_error_page"),
    ("sw: an error page is not an offline shell",
     "../frontend/public/sw.js",
     "if (res.ok) {", "if (true) {",
     "never_caches_an_error_page"),
    ("sw: old poisoned caches are deleted",
     "../frontend/public/sw.js",
     'const VERSION = "titan-v2";', 'const VERSION = "titan-v1";',
     "never_caches_an_error_page"),
    ("sw: the script itself is never cached", "app/main.py",
     'or request.url.path == "/sw.js"):', "or False):",
     "service_worker_script_is_never_cached"),
]


def _digest(path: str) -> str:
    return hashlib.sha256(io.open(path, "rb").read()).hexdigest()


# A run that completes restores byte-for-byte and verifies it. A run that is
# killed doesn't - SIGKILL skips `finally`, so the mutant stays in the source
# and the next run would only report its anchor as "stale". This marker names
# the file being mutated for as long as the mutation exists, so an
# interrupted run is loud on the next start.
_MARKER = os.path.join(os.path.dirname(__file__), ".mutation-in-progress")


def _claim(path: str) -> None:
    io.open(_MARKER, "w", encoding="utf-8").write(path)


def _release() -> None:
    try:
        os.remove(_MARKER)
    except OSError:
        pass


def _check_previous_run() -> Optional[str]:
    """The file a killed run was holding, if there was one."""
    if not os.path.isfile(_MARKER):
        return None
    return io.open(_MARKER, encoding="utf-8").read().strip() or "unknown"


def run(only: str = "") -> int:
    survived: list[str] = []
    skipped: list[str] = []

    held = _check_previous_run()
    if held:
        print(f"FATAL: a previous run was interrupted while mutating {held}.\n"
              f"That file may still contain a mutation — SIGKILL does not run\n"
              f"`finally`. Restore it (`git checkout -- {held}`), confirm\n"
              f"`git diff` is clean, then delete {_MARKER} and re-run.")
        return 2

    for label, path, anchor, replacement, selector in MUTANTS:
        if only and only not in label:
            continue
        before_digest = _digest(path)
        # Bytes, not text. Text mode reads CRLF as LF and writes LF back, so a CRLF
        # file would come back with different bytes, the restore check would fire,
        # and the tool would have rewritten line endings it promised not to touch.
        # Frontend components can be CRLF in the working tree (`* text=auto` +
        # core.autocrlf), and some guards live there.
        raw = io.open(path, "rb").read()
        original = raw.decode("utf-8")
        # A multi-line anchor is written with "\n", but with `core.autocrlf=true` a
        # fresh clone writes CRLF for every file, and those anchors would silently
        # never match. Match against the line endings the file actually has.
        needle, mutant = anchor, replacement
        if "\r\n" in original:
            needle = anchor.replace("\r\n", "\n").replace("\n", "\r\n")
            mutant = replacement.replace("\r\n", "\n").replace("\n", "\r\n")
        if needle not in original:
            print(f"SKIP     {label}: anchor no longer in {path}")
            skipped.append(label)
            continue

        _claim(path)
        io.open(path, "wb").write(
            original.replace(needle, mutant, 1).encode("utf-8"))
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/test_core.py",
                 "tests/test_cockpit.py", "-q",
                 "--no-header", "-p", "no:cacheprovider", "-k", selector],
                capture_output=True, text=True)
            # Exit 5 is "no tests collected". It must not count as caught, or a guard
            # whose test was renamed would look guarded while nothing ran.
            caught = result.returncode not in (0, 5)
        finally:
            # Restore, then prove the restore. Writing back the original bytes rather
            # than re-encoding decoded text makes the digest check mean what it says.
            io.open(path, "wb").write(raw)
            if _digest(path) != before_digest:
                print(f"\nFATAL: {path} was not restored byte-for-byte. "
                      f"Restore it from git before doing anything else.")
                return 2
            _release()

        print(f"{'CAUGHT  ' if caught else 'SURVIVED'} {label}")
        if not caught:
            survived.append(f"{label}  (selector: -k {selector!r})")

    print()
    if skipped:
        print(f"{len(skipped)} anchor(s) stale — update MUTANTS: {skipped}")
    if survived:
        print("GUARDS WITH NO TEST BEHIND THEM:")
        for s in survived:
            print(f"  - {s}")
        return 1
    print("every guard is backed by a test that fails without it")
    return 0


if __name__ == "__main__":
    only = ""
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    sys.exit(run(only))
