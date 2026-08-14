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
        original = io.open(path, encoding="utf-8").read()
        if anchor not in original:
            print(f"SKIP     {label}: anchor no longer in {path}")
            skipped.append(label)
            continue

        io.open(path, "w", encoding="utf-8", newline="").write(
            original.replace(anchor, replacement, 1))
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/test_core.py", "-q",
                 "--no-header", "-p", "no:cacheprovider", "-k", selector],
                capture_output=True, text=True)
            caught = result.returncode != 0
        finally:
            # Restore, then PROVE the restore. A scratch version of this tool
            # once left a mutation in backup.py that disabled the check a
            # backup actually restores.
            io.open(path, "w", encoding="utf-8", newline="").write(original)
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
