"""Mutation testing — prove a guard's test actually fails when the guard goes.

A passing test proves nothing on its own. Twice in this codebase a test looked
like it protected a behaviour and did not: one asserted on a *comment* rather
than the code it described, and one never exercised the branch at all. Both
were found by deleting the guard and watching the suite stay green.

So this is the tool, kept in the repo rather than as a scratch script, because
a scratch script already did real damage: it left `if False:` inside
`backup.py`'s verification gate after a run, silently disabling the check that
a backup actually restores. **Every mutation here is restored and then
VERIFIED restored**, and the run aborts loudly if a file does not come back
byte-for-byte.

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
    # The approval gate is the whole product decision here. If any of these
    # survive, Titan can change its own behaviour without Abdullah.
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
    # Single line on purpose. The first version of this anchor spanned two
    # lines and never matched — the continuation indent in the MUTANTS entry
    # did not equal the indent in the source, so it reported "stale" rather
    # than failing, and the guard silently went untested. Appending to a
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
    # The grant flag is the whole difference between a pilot seat and revenue.
    # Both halves are mutated: the reader (is the flag consulted at all) and the
    # consequence (does consulting it actually change the count).
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
    # Authorisation boundaries. Each one is the difference between "disabled"
    # meaning disabled and meaning nothing.
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
    # The environment gate in core/auth.py retires itself the moment a real
    # founder account exists. Each of these is the difference between that
    # being true and it being a comment. Anchors are single-line and unique
    # on purpose: this tool replaces the FIRST match it finds.
    #
    # Deliberately NOT guarded: ensure_founder's weak-password refusal and its
    # `if current:` overwrite check. Removing either changes only the wording
    # of the refusal, because identity.create() independently enforces the
    # password floor and the UNIQUE constraint on email. A guard that cannot
    # fail is theatre, and this file exists because two of those were found.
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
    # 'simplified' away by somebody who has not hit the broken state.
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
    # Redaction happens on the way IN. A secret that reaches the table has
    # already been persisted, and no read-time filter takes it back off the
    # disk or out of last night's backup.
    ("audit: a secret is never written to the table", "app/core/audit.py",
     "if any(hint in name for hint in _SECRET_HINTS):", "if False:",
     "never_stores_a_secret"),
    # --- executive metrics -------------------------------------------------
    # The line between a measured zero and a null. $0 MRR reads as a business
    # result; the truth today is that nobody COULD pay and nothing was
    # measured, and a dashboard that cannot tell those apart is believed
    # anyway.
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
    # A typo quietly meaning "off" is how a feature vanishes for everybody,
    # and an unreadable check counted as a failure blames the customer for
    # our outage. Both are one deleted line away.
    ("flags: an unknown flag raises rather than reading as off",
     "app/core/flags.py", "    if flag is None:", "    if False:",
     "unknown_flag_raises"),
    ("onboarding: an unknown check is not counted as a failure",
     "app/core/onboarding.py", '        if state["done"] is None:',
     "        if False:", "unknown_check_is_not_counted"),
    # --- the Executive operations panel ------------------------------------
    # Four APIs with no screen in front of them is the knowledge.backfill()
    # shape again: built, tested, and reaching nobody.
    ("executive: the operations panel is actually mounted",
     "../frontend/components/ExecutiveCommand.tsx",
     "<ExecutiveOperations />", "<span />",
     "executive_view_mounts"),
    # --- durable state on a free Dataset repo ------------------------------
    # Two ways this loses or exposes data, both one line each: restoring ON
    # TOP of a live database, and creating the snapshot repo public when it
    # holds every account.
    ("remote_state: a pull never overwrites a live state file",
     "app/core/remote_state.py", "    if os.path.exists(dest):",
     "    if False:", "never_overwrites_a_state_file"),
    ("remote_state: the snapshot repo is created private",
     "app/core/remote_state.py",
     '        api.create_repo(repo_id=repo_id(), repo_type="dataset", private=True,',
     '        api.create_repo(repo_id=repo_id(), repo_type="dataset", private=False,',
     "push_is_recorded_as_proof"),
    # --- the two sign-in doors ---------------------------------------------
    # The box advertised both and called one, so a customer created from the
    # Executive screen was told a correct password was invalid.
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
]


def _digest(path: str) -> str:
    return hashlib.sha256(io.open(path, "rb").read()).hexdigest()


# A run that COMPLETES restores byte-for-byte and proves it. A run that is
# KILLED does not — SIGKILL does not run `finally`, so the mutant stays in the
# source and the next run reports its anchor as merely "stale". That happened:
# a wait loop killed a run, `pass  # (` sat in approvals.py, and the only
# symptom was a SKIP line. This marker closes it. It names the file being
# mutated for the whole window the mutation exists, so an interrupted run is
# LOUD on the next start instead of silent.
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
        # Bytes, not text. Text mode reads CRLF as LF and writes LF back, so a
        # CRLF file would come back content-identical and byte-DIFFERENT — the
        # restore check would fire FATAL and the tool would have rewritten the
        # line endings of a file it promised not to touch. Every backend file
        # here is LF, but the frontend components are CRLF in the working tree
        # (`* text=auto` + core.autocrlf), and there are guards worth mutating
        # in them.
        raw = io.open(path, "rb").read()
        original = raw.decode("utf-8")
        # A multi-line anchor is written with "\n". The comment above says
        # every backend file is LF, and that was true of THIS working tree and
        # false in general: `core.autocrlf=true` means a fresh CLONE writes CRLF
        # for every file. Seven anchors span lines, so on a clean checkout seven
        # guards printed SKIP, the run still exited 0, and nobody was guarding
        # anything. Match against the line endings the file actually has.
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
                [sys.executable, "-m", "pytest", "tests/test_core.py", "-q",
                 "--no-header", "-p", "no:cacheprovider", "-k", selector],
                capture_output=True, text=True)
            caught = result.returncode != 0
        finally:
            # Restore, then PROVE the restore. A scratch version of this tool
            # once left a mutation in backup.py that disabled the check a
            # backup actually restores. Restoring the ORIGINAL BYTES rather
            # than a re-encode of the decoded text makes the digest check mean
            # what it says.
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
