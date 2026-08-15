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
import subprocess
import sys

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
]


def _digest(path: str) -> str:
    return hashlib.sha256(io.open(path, "rb").read()).hexdigest()


def run(only: str = "") -> int:
    survived: list[str] = []
    skipped: list[str] = []

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
        if anchor not in original:
            print(f"SKIP     {label}: anchor no longer in {path}")
            skipped.append(label)
            continue

        io.open(path, "wb").write(
            original.replace(anchor, replacement, 1).encode("utf-8"))
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
