"""Propose -> approve -> apply -> verify -> rollback on a client's live website.

`site_access` holds the key; this is what Titan does with it. It's also where
Titan could do real damage to a customer's business, so the module is built on
one assumption: a write that returned HTTP 200 is not a change that happened.

- Nothing is applied without an explicit approval with a name on it. A
  proposal stays `proposed` until someone approves it, and `apply` on an
  unapproved fix is refused, not queued. There's no auto-apply flag here.
- Stale proposals are refused. The field is read again right before the write
  and compared with its value when the fix was proposed. If the owner edited
  the page in between, Titan doesn't overwrite them: the fix fails and says
  the page changed.
- Every write is read back. WordPress runs `wp_kses_post` on content for any
  user without `unfiltered_html`, which silently strips `<script>`, so a schema
  fix can return 200 and change nothing. After every write the field is
  fetched again and compared with what was sent; if it doesn't match, the fix
  is `failed` with the readback quoted, never `applied`.
- The exact previous value is snapshotted before the write, so rollback
  restores a value instead of reconstructing one. Rollback is read back and
  verified the same way.

Known limits:

* Rollback depends on Titan's own storage. The snapshot lives in the state
  database, which a free Hugging Face Space wipes on rebuild, so a fix applied
  before a rebuild may no longer be undoable from Titan's side. Every fix
  record carries `durable` from `db.stats()`. WordPress revisions remain a
  backstop for content, but media alt text has no revision history.
* Meta descriptions can't be written through core WordPress. There's no such
  field: SEO plugins store it as post meta, which is only reachable over REST
  if the plugin registered it with `show_in_rest`. So a missing meta
  description stays advice, and `propose` says why.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
from typing import Optional

from . import db, events, site_access

# --------------------------------------------------------------- lifecycle --
PROPOSED = "proposed"
APPROVED = "approved"
APPLIED = "applied"
FAILED = "failed"
ROLLED_BACK = "rolled_back"
REJECTED = "rejected"
# Titan applied and verified it, but the site no longer holds it - someone
# edited the page back, or a plugin overwrote it. This is reported, not
# corrected: the owner is allowed to disagree with a change, and Titan never
# silently reinstates an edit a person removed.
DRIFTED = "drifted"

STATUSES = (PROPOSED, APPROVED, APPLIED, FAILED, ROLLED_BACK, REJECTED,
            DRIFTED)

# A failed fix may be approved again - the cause is usually on the site (a
# plugin stripped the markup, the page moved). Nothing leaves `rolled_back` or
# `rejected`: re-applying a reverted change silently would make the tool
# untrustworthy. Propose it again and get it approved again.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    PROPOSED:    (APPROVED, REJECTED),
    APPROVED:    (APPLIED, FAILED, REJECTED),
    APPLIED:     (ROLLED_BACK, DRIFTED),
    FAILED:      (APPROVED, REJECTED),
    ROLLED_BACK: (),
    REJECTED:    (),
    # Nothing leaves `drifted` either. Re-applying needs a new proposal against
    # what the page says now, approved again by a person.
    DRIFTED:     (),
}

# ------------------------------------------------------------------- kinds --
# Only what core WordPress accepts over REST and returns on a read. Anything
# else goes in `skipped` with a reason.
KIND_TITLE = "title"
KIND_ALT = "alt_text"
KIND_SCHEMA = "schema"

KINDS = (KIND_TITLE, KIND_ALT, KIND_SCHEMA)

_lock = threading.RLock()
_fixes: dict[str, dict] = {}
_counter = 0

TIMEOUT = 20.0

# A filename isn't a description. WordPress derives a media title from the
# uploaded file name, so "IMG_4821" or "DSC00013" would become alt text that
# tells a screen reader nothing while looking filled in.
_JUNK_NAME = re.compile(r"""^(?:
    img | dsc | dscn | pxl | photo | image | pic | picture | screenshot |
    untitled | unnamed | download | copy | final | scan | capture | wa
)?[\W_]*\d[\d\W_]*$|^[0-9a-f]{8,}$""", re.I | re.X)

# A placeholder in generated schema, e.g. "<street address>". Publishing one
# would tell Google the business is literally called "<city>".
_PLACEHOLDER = re.compile(r"<[^<>]{1,40}>")


# ------------------------------------------------------------- WordPress IO --
def _auth(cred: dict) -> dict:
    import base64
    token = base64.b64encode(
        f"{cred['username']}:{cred['secret']}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _wp(cred: dict, method: str, path: str, *, params: Optional[dict] = None,
        body: Optional[dict] = None):
    """One authenticated REST call. Returns the httpx response, or raises.

    Redirects are followed on GET (a site whose canonical host differs from the
    stored one would otherwise fail every read) but never on a write. httpx
    drops the Authorization header across hosts, and a security plugin
    redirecting writes to a login page could answer 200 with HTML. Refusing the
    redirect turns that into a reportable error.
    """
    import httpx
    from . import safe_fetch

    safe_fetch.check(cred["site_url"])
    url = f"{cred['site_url']}{path}"
    follow = method.upper() == "GET"
    with httpx.Client(timeout=TIMEOUT, follow_redirects=follow) as c:
        return c.request(method, url, params=params, json=body,
                         headers=_auth(cred))


def _json(resp):
    """Parse a REST response body, or None. WordPress error pages are HTML."""
    try:
        return resp.json()
    except Exception:
        return None


def _raw(value) -> str:
    """WordPress returns {'raw': ..., 'rendered': ...} under context=edit.

    `raw` is what was stored and what a write is compared against; `rendered`
    has been through shortcodes and filters and will never match.
    """
    if isinstance(value, dict):
        return str(value.get("raw", "") or "")
    return str(value or "")


def _norm(url: str) -> str:
    u = (url or "").split("#")[0].split("?")[0].strip().rstrip("/").lower()
    return u.replace("https://", "").replace("http://", "").replace("www.", "")


def find_object(cred: dict, url: str) -> dict:
    """Find the WordPress page or post that serves `url`.

    Slug first (one indexed query), then a scan of published pages and posts
    comparing WordPress's own `link`. The scan is what finds a front page: it
    has no slug in the URL, and core REST doesn't expose `page_on_front`
    without `manage_options`, which Titan doesn't ask for.
    """
    target = _norm(url)
    path = urllib.parse.urlparse(
        url if "://" in url else "https://" + url).path.strip("/")
    slug = path.rsplit("/", 1)[-1] if path else ""

    for kind in ("pages", "posts"):
        try:
            if slug:
                r = _wp(cred, "GET", f"/wp-json/wp/v2/{kind}",
                        params={"slug": slug, "context": "edit",
                                "per_page": 10})
                rows = _json(r)
                if isinstance(rows, list):
                    for row in rows:
                        if _norm(row.get("link", "")) == target:
                            return _object(kind, row)
            r = _wp(cred, "GET", f"/wp-json/wp/v2/{kind}",
                    params={"context": "edit", "per_page": 100,
                            "status": "publish"})
            rows = _json(r)
            if isinstance(rows, list):
                for row in rows:
                    if _norm(row.get("link", "")) == target:
                        return _object(kind, row)
        except Exception as e:
            return {"found": False,
                    "error": f"Could not read the site ({type(e).__name__})."}

    return {"found": False, "error": (
        f"No published page or post on the site has the address {url}. It may "
        f"be generated by a theme or a page builder rather than stored as a "
        f"WordPress page, in which case Titan cannot edit it over the REST "
        f"API.")}


def _object(kind: str, row: dict) -> dict:
    return {"found": True, "type": kind, "id": row.get("id"),
            "link": row.get("link", ""),
            "title": _raw(row.get("title")),
            "content": _raw(row.get("content"))}


def _read_field(cred: dict, target: dict, field: str) -> tuple[Optional[str], str]:
    """Current value of one field, straight from the site. (value, error)."""
    try:
        r = _wp(cred, "GET", f"/wp-json/wp/v2/{target['type']}/{target['id']}",
                params={"context": "edit"})
    except Exception as e:
        return None, f"Could not read the page ({type(e).__name__})."
    if r.status_code >= 400:
        return None, f"WordPress replied {r.status_code} reading the page."
    row = _json(r)
    if not isinstance(row, dict):
        return None, "WordPress did not return JSON for that page."
    return _raw(row.get(field)), ""


def _write_field(cred: dict, target: dict, field: str,
                 value: str) -> tuple[bool, str]:
    """Write one field. (accepted, error) - accepted doesn't mean verified."""
    try:
        r = _wp(cred, "POST", f"/wp-json/wp/v2/{target['type']}/{target['id']}",
                body={field: value})
    except Exception as e:
        return False, f"The write could not be sent ({type(e).__name__})."
    if r.status_code in (301, 302, 303, 307, 308):
        return False, (
            "The site redirected the write instead of accepting it. That is "
            "usually a security plugin blocking REST writes, or the stored "
            "address differing from the site's real one.")
    if r.status_code == 403:
        return False, ("WordPress refused the change (403). The connected user "
                       "may no longer have permission to edit this page.")
    if r.status_code >= 400:
        body = _json(r)
        detail = (body or {}).get("message") if isinstance(body, dict) else None
        return False, f"WordPress replied {r.status_code}" + (
            f": {detail}" if detail else ".")
    return True, ""


# ----------------------------------------------------------------- proposal --
def _new_id() -> str:
    global _counter
    _counter += 1
    return f"fix-{int(time.time())}-{_counter:04d}"


def _record(client_id: str, kind: str, target: dict, field: str, *,
            finding_id: str, title: str, why: str, current: str,
            proposed: str, weight: Optional[int] = None,
            risk: str = "") -> dict:
    fix = {
        "id": _new_id(),
        "client_id": client_id,
        "kind": kind,
        "status": PROPOSED,
        "target": {"type": target["type"], "id": target["id"],
                   "link": target.get("link", "")},
        "field": field,
        "finding_id": finding_id,
        "title": title,
        "why": why,
        # What the site said when the proposal was made. `apply` refuses if it no
        # longer says this.
        "current": current,
        "proposed": proposed,
        # The weight this check has in Titan's own audit score. Not a traffic
        # prediction and never presented as one; Titan can't measure ranking changes.
        "audit_weight": weight,
        "risk": risk,
        "created_at": time.time(),
        "approved_by": None,
        "approved_at": None,
        "applied_at": None,
        "verified": None,
        "verify_note": "",
        "snapshot": None,
        "rolled_back_at": None,
        "error": "",
        "durable": _durable(),
    }
    with _lock:
        _fixes[fix["id"]] = fix
    return fix


def _durable() -> bool:
    """Whether the snapshot that makes rollback possible survives a rebuild."""
    try:
        return bool(db.stats().get("durable"))
    except Exception:
        return False


def _clean_schema(raw: str) -> tuple[Optional[dict], list[str]]:
    """Strip every placeholder out of generated JSON-LD.

    Returns (node, missing). A partial but true node is worth publishing; one
    containing "<street address>" isn't, and neither is one so empty it says
    nothing. A None node means we don't know enough about the business yet.
    """
    try:
        node = json.loads(raw)
    except Exception:
        return None, ["the generated markup was not valid JSON"]
    missing: list[str] = []

    # `suggested_schema` fills these with template defaults (priceRange "$$",
    # 09:00-18:00 every day). They aren't placeholders, so nothing below would
    # catch them, but they aren't observations either - nobody measured this
    # business's opening hours. They're dropped here and stay in the audit as
    # advice.
    for invented in ("priceRange", "openingHoursSpecification"):
        if node.pop(invented, None) is not None:
            missing.append(f"{invented} (not measured — left out deliberately)")

    def walk(value, path=""):
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                cleaned = walk(v, f"{path}.{k}" if path else k)
                if cleaned is not None:
                    out[k] = cleaned
            # A nested object holding nothing but its own @type is noise.
            return out if [k for k in out if not k.startswith("@")] or not path else None
        if isinstance(value, list):
            out = [walk(v, path) for v in value]
            out = [v for v in out if v is not None]
            return out or None
        text = str(value)
        if _PLACEHOLDER.search(text):
            missing.append(path)
            return None
        return value

    node = walk(node)
    if not isinstance(node, dict) or not node.get("name") or not node.get("@type"):
        return None, missing or ["the business name"]
    # Name, type and URL alone tell a search engine nothing it didn't already know
    # from the page. Require at least one real fact beyond them.
    substantive = [k for k in node
                   if k not in ("@context", "@type", "name", "url", "priceRange")]
    if not substantive:
        return None, missing or ["an address, a phone number or opening hours"]
    return node, missing


def propose(client_id: str, audit: dict, *,
            business: Optional[dict] = None) -> dict:
    """Turn audit findings into concrete, appliable changes. Never raises.

    Only findings that map to a field core WordPress accepts and returns become
    proposals. Everything else comes back under `skipped` with the reason:
    "found 9 problems, can fix 2" is accurate, "will fix your site" isn't.
    """
    # The kill switch, since this edits a page on someone else's live website.
    #
    # Returned rather than raised because this function promises never to raise
    # and callers rely on that.
    from . import flags
    if not flags.is_enabled("site_fix"):
        return {"ok": False, "error": (
            "Website fixes are switched off for this deployment "
            "(feature flag: site_fix)."), "proposed": [], "skipped": []}
    cred = site_access.credential(client_id)
    if not cred:
        return {"ok": False, "error": (
            "No website credential is connected for this business, so there is "
            "nothing Titan can change. Connect the site first."),
            "proposed": [], "skipped": []}
    if cred["provider"] != "wordpress":
        return {"ok": False,
                "error": f"Titan can only apply fixes to WordPress, not "
                         f"{cred['provider']}.",
                "proposed": [], "skipped": []}
    if not isinstance(audit, dict) or not audit.get("ok"):
        return {"ok": False, "error": (
            "That audit did not complete, so there are no findings to turn "
            "into fixes."), "proposed": [], "skipped": []}

    business = business or {}
    url = audit.get("url") or cred["site_url"]
    found = find_object(cred, url)
    if not found.get("found"):
        return {"ok": False, "error": found.get("error", "Page not found."),
                "proposed": [], "skipped": []}

    findings = {f["id"]: f for f in audit.get("findings", [])
                if isinstance(f, dict) and f.get("id")}
    proposed: list[dict] = []
    skipped: list[dict] = []

    try:
        from ..engines.client_seo import WEIGHTS
    except Exception:
        WEIGHTS = {}

    # ------------------------------------------------------------- title ----
    if "title" in findings:
        new_title = _suggest_title(business, audit)
        if new_title:
            proposed.append(_record(
                client_id, KIND_TITLE, found, "title",
                finding_id="title",
                title="Rewrite the page title",
                why=findings["title"]["detail"],
                current=found["title"], proposed=new_title,
                weight=WEIGHTS.get("title"),
                risk="Low. The title is one field and rollback restores the "
                     "exact previous text."))
        else:
            skipped.append({
                "finding_id": "title",
                "reason": ("Titan does not know this business's trade or city "
                           "well enough to write a title for it, and a title "
                           "invented from nothing is worse than a weak one. "
                           "Fill in the business name and city.")})

    # --------------------------------------------------------- meta desc ----
    if "meta_description" in findings:
        skipped.append({
            "finding_id": "meta_description",
            "reason": (
                "Core WordPress has no meta description field. Every site gets "
                "one from an SEO plugin (Yoast, Rank Math, SEOPress) which "
                "stores it as post meta, and that meta is only writable over "
                "the REST API if the plugin registered it. Titan will not "
                "claim to fix something it cannot reach — this one stays a "
                "recommendation for now.")})

    # ------------------------------------------------------------ schema ----
    if "schema" in findings or "local_business" in findings:
        finding = findings.get("schema") or findings["local_business"]
        node, missing = _schema_for(business, audit)
        if node is None:
            skipped.append({
                "finding_id": finding["id"],
                "reason": (
                    "Schema is the highest-value fix in the audit, but Titan "
                    "will not publish markup containing placeholders — telling "
                    "Google the business is called '<city>' is worse than "
                    "having no markup. Missing: "
                    + ", ".join(missing or ["the business details"]) + ".")})
        else:
            block = ('<script type="application/ld+json">\n'
                     + json.dumps(node, indent=2, ensure_ascii=False)
                     + '\n</script>')
            proposed.append(_record(
                client_id, KIND_SCHEMA, found, "content",
                finding_id=finding["id"],
                title="Add structured data (schema) to the page",
                why=finding["detail"],
                current=found["content"],
                proposed=found["content"].rstrip() + "\n\n" + block,
                weight=WEIGHTS.get("schema"),
                risk=(
                    "Medium. This appends to the page content, so the whole "
                    "content field is rewritten and rollback restores it "
                    "exactly. WordPress strips <script> from content for users "
                    "without the unfiltered_html capability — if that happens "
                    "the read-back check will catch it and the fix will be "
                    "reported as failed, not applied.")))

    # -------------------------------------------------------- image alts ----
    if "images_alt" in findings:
        alts, alt_skipped = _propose_alt_text(client_id, cred,
                                              WEIGHTS.get("images_alt"))
        proposed.extend(alts)
        skipped.extend(alt_skipped)

    return {
        "ok": True,
        "client_id": client_id,
        "url": url,
        "target": {"type": found["type"], "id": found["id"],
                   "link": found.get("link", "")},
        "proposed": [public(f["id"]) for f in proposed],
        "skipped": skipped,
        "durable": _durable(),
        "note": (
            f"{len(proposed)} change(s) are ready to apply and "
            f"{len(skipped)} finding(s) cannot be fixed automatically. "
            f"Nothing has been changed on the site — each fix needs approval "
            f"by name first."),
    }


def _suggest_title(business: dict, audit: dict) -> str:
    """A title built only from facts we hold. Empty when we hold none."""
    name = (business.get("business_name") or "").strip()
    city = (business.get("city") or "").strip()
    industry = (business.get("industry") or "").strip()
    if not name:
        return ""
    try:
        from ..engines import verticals
        vert = verticals.profile(verticals.detect("", industry))
        trade = vert.title_example
    except Exception:
        trade = industry
    if not trade and not city:
        return ""
    parts = [p for p in (trade, city) if p]
    title = f"{name} — {' in '.join(parts) if len(parts) == 2 else parts[0]}"
    # The audit fails a title outside 15-65 characters, so a proposal must pass
    # that same check.
    return title if 15 <= len(title) <= 65 else title[:62].rstrip(" -—") + ""


# The client record stores a country name ("Pakistan"); schema wants an ISO
# code. Guessing one would publish a false statement (`addressCountry: "DE"`
# on a Lahore business), so an unmapped country becomes a placeholder and is
# stripped.
_COUNTRY_CODES = {
    "pakistan": "PK", "germany": "DE", "deutschland": "DE",
    "united kingdom": "GB", "uk": "GB", "england": "GB",
    "united states": "US", "usa": "US", "us": "US",
    "united arab emirates": "AE", "uae": "AE", "canada": "CA",
    "australia": "AU", "india": "IN", "france": "FR", "spain": "ES",
    "italy": "IT", "netherlands": "NL", "austria": "AT", "switzerland": "CH",
    "saudi arabia": "SA", "turkey": "TR", "türkiye": "TR",
}


def _country_code(business: dict) -> str:
    explicit = (business.get("country_code") or "").strip().upper()
    if len(explicit) == 2:
        return explicit
    name = (business.get("country") or "").strip().lower()
    return _COUNTRY_CODES.get(name, "<country>")


def _schema_for(business: dict, audit: dict) -> tuple[Optional[dict], list[str]]:
    try:
        from ..engines import client_seo
        raw = client_seo.suggested_schema(
            business_name=business.get("business_name", ""),
            city=business.get("city", ""),
            website=audit.get("url", ""),
            industry=business.get("industry", ""),
            phone=business.get("phone", ""),
            country_code=_country_code(business))
    except Exception:
        return None, ["the business details"]
    return _clean_schema(raw)


def _propose_alt_text(client_id: str, cred: dict,
                      weight: Optional[int]) -> tuple[list[dict], list[dict]]:
    """One proposal per image whose file name actually describes it.

    WordPress derives a media title from the uploaded file name.
    `black-leather-biker-jacket.jpg` is a real description worth using as alt
    text; `IMG_4821.jpg` isn't, and Titan hasn't seen the image, so that one is
    left for a person instead of filled with a guess.
    """
    proposals: list[dict] = []
    skipped: list[dict] = []
    try:
        r = _wp(cred, "GET", "/wp-json/wp/v2/media",
                params={"context": "edit", "per_page": 100,
                        "media_type": "image"})
        rows = _json(r)
    except Exception as e:
        return [], [{"finding_id": "images_alt",
                     "reason": f"Could not read the media library "
                               f"({type(e).__name__})."}]
    if not isinstance(rows, list):
        return [], [{"finding_id": "images_alt",
                     "reason": "The site did not return a media library."}]

    unnamed = 0
    for row in rows:
        if str(row.get("alt_text") or "").strip():
            continue
        name = _raw(row.get("title")).strip()
        words = re.split(r"[\s\-_]+", name)
        if (not name or _JUNK_NAME.match(name) or len(name) < 8
                or len([w for w in words if w]) < 2):
            unnamed += 1
            continue
        alt = " ".join(w for w in words if w).strip()
        proposals.append(_record(
            client_id, KIND_ALT,
            {"type": "media", "id": row.get("id"),
             "link": row.get("source_url", "")},
            "alt_text",
            finding_id="images_alt",
            title=f"Describe the image {name}",
            why=("An image with no alt text cannot rank in image search and "
                 "is invisible to a screen reader."),
            current="", proposed=alt, weight=weight,
            risk="Low. Alt text is a single media field. Note that WordPress "
                 "keeps no revision history for it, so Titan's own snapshot "
                 "is the only way back."))
    if unnamed:
        skipped.append({
            "finding_id": "images_alt",
            "reason": (
                f"{unnamed} image(s) have no alt text and a file name that "
                f"describes nothing (IMG_4821 and the like). Titan has not "
                f"seen these images, so anything it wrote would be invented. "
                f"They need a person to describe them.")})
    return proposals, skipped


# ------------------------------------------------------------ state machine --
def _transition(fix: dict, to: str) -> Optional[str]:
    allowed = TRANSITIONS.get(fix["status"], ())
    if to not in allowed:
        return (f"A {fix['status']} fix cannot become {to}. "
                f"Allowed from here: {', '.join(allowed) or 'nothing'}.")
    fix["status"] = to
    return None


def approve(fix_id: str, approver: str) -> dict:
    """Approve a fix. An approval without a name isn't an approval."""
    approver = (approver or "").strip()
    if not approver:
        return {"ok": False, "error": (
            "An approval must record who gave it. Nothing is changed on a "
            "customer's website by an anonymous decision.")}
    with _lock:
        fix = _fixes.get(fix_id)
        if not fix:
            return {"ok": False, "error": "No such fix."}
        err = _transition(fix, APPROVED)
        if err:
            return {"ok": False, "error": err}
        fix["approved_by"] = approver
        fix["approved_at"] = time.time()
    events.emit("SiteFixApproved",
                {"fix": fix_id, "client": fix["client_id"],
                 "kind": fix["kind"]}, actor=approver, severity="warn")
    return {"ok": True, "fix": public(fix_id)}


def reject(fix_id: str, approver: str = "", reason: str = "") -> dict:
    with _lock:
        fix = _fixes.get(fix_id)
        if not fix:
            return {"ok": False, "error": "No such fix."}
        err = _transition(fix, REJECTED)
        if err:
            return {"ok": False, "error": err}
        fix["error"] = reason or "Rejected."
        fix["approved_by"] = (approver or "").strip() or None
    return {"ok": True, "fix": public(fix_id)}


def apply(fix_id: str) -> dict:
    """Apply an approved fix, then read the site back to see if it took.

    Order: read -> compare with the proposal -> write -> read again -> compare
    with what was sent. A failure at any step leaves the fix `failed` with the
    reason, and the caller is told what the site actually says.
    """
    # Checked here as well as in propose(): a fix proposed while the feature was
    # on mustn't still be appliable after someone switched it off, which is
    # exactly when they're trying to stop writes.
    from . import flags
    if not flags.is_enabled("site_fix"):
        return {"ok": False, "error": (
            "Website fixes are switched off for this deployment "
            "(feature flag: site_fix).")}
    with _lock:
        fix = _fixes.get(fix_id)
        if not fix:
            return {"ok": False, "error": "No such fix."}
        if fix["status"] != APPROVED:
            return {"ok": False, "error": (
                f"This fix is {fix['status']}. Only an approved fix can be "
                f"applied, and approval must name who gave it.")}

    cred = site_access.credential(fix["client_id"])
    if not cred:
        return _fail(fix, "The website credential for this business is no "
                          "longer connected, so nothing was changed.")

    # 1. What does the site say right now?
    live, err = _read_field(cred, fix["target"], fix["field"])
    if err:
        return _fail(fix, err)

    # 2. Is the proposal still about that?
    if live != fix["current"]:
        return _fail(fix, (
            "The page changed since this fix was proposed, so Titan did not "
            "overwrite it. Somebody edited it, or a plugin rewrote it. Run the "
            "audit again and propose the fix against what is there now."),
            stale=True, live=live)

    # 3. Snapshot the exact value we are about to replace.
    with _lock:
        fix["snapshot"] = live
        fix["durable"] = _durable()

    # 4. Write.
    ok, err = _write_field(cred, fix["target"], fix["field"], fix["proposed"])
    if not ok:
        return _fail(fix, err)

    # 5. Read it back. This is the only evidence that counts.
    after, err = _read_field(cred, fix["target"], fix["field"])
    if err:
        return _fail(fix, (
            f"The write was accepted but Titan could not read the page back to "
            f"confirm it: {err} The change may or may not be live."))

    if after != fix["proposed"]:
        note = _explain_mismatch(fix, after)
        return _fail(fix, note, live=after, verified=False)

    with _lock:
        _transition(fix, APPLIED)
        fix["applied_at"] = time.time()
        fix["verified"] = True
        fix["verify_note"] = ("Read back from the live site after writing and "
                              "matched exactly.")
        fix["error"] = ""
    events.emit("SiteFixApplied",
                {"fix": fix_id, "client": fix["client_id"],
                 "kind": fix["kind"], "target": fix["target"]},
                actor=fix.get("approved_by") or "system", severity="warn")
    return {"ok": True, "fix": public(fix_id)}


def _explain_mismatch(fix: dict, after: str) -> str:
    """Say what the site did with the write, not just that it differed."""
    if after == fix["snapshot"]:
        if fix["kind"] == KIND_SCHEMA:
            return (
                "WordPress accepted the write and then discarded it — the page "
                "is byte-for-byte what it was. This is almost always "
                "wp_kses_post stripping the <script> tag, which WordPress does "
                "for any user without the unfiltered_html capability. The "
                "schema is NOT live. Add it through an SEO plugin or a theme "
                "header instead; nothing on the site was changed.")
        return ("WordPress accepted the write and then discarded it — the "
                "field is exactly what it was before. The change is NOT live "
                "and nothing on the site was changed.")
    if fix["kind"] == KIND_SCHEMA and "application/ld+json" not in after:
        return ("The page content changed but the schema block is not in it — "
                "the markup was filtered out on the way in. The schema is NOT "
                "live. The page now holds neither the old content nor what "
                "Titan sent; roll this back.")
    return (f"The site was written to but does not hold what Titan sent. It "
            f"now starts with: {after[:160]!r}. Treat this fix as not applied "
            f"and check the page.")


def _fail(fix: dict, message: str, *, stale: bool = False,
          live: Optional[str] = None, verified: Optional[bool] = None) -> dict:
    with _lock:
        _transition(fix, FAILED)
        fix["error"] = message
        fix["verified"] = verified if verified is not None else False
        fix["verify_note"] = message
        if stale:
            fix["stale"] = True
        if live is not None:
            fix["live_value"] = live
    events.emit("SiteFixFailed",
                {"fix": fix["id"], "client": fix["client_id"],
                 "kind": fix["kind"], "reason": message[:200]},
                actor="system", severity="error")
    return {"ok": False, "error": message, "fix": public(fix["id"])}


def mark_drifted(fix_id: str, live_value: str) -> dict:
    """Record that an applied fix is no longer live. Changes nothing on the site.

    Called by the 24/7 verify pass. There's deliberately no counterpart that
    puts the value back: the owner editing Titan's change is a legitimate
    decision, and reversing it automatically would overrule them.
    """
    with _lock:
        fix = _fixes.get(fix_id)
        if not fix:
            return {"ok": False, "error": "No such fix."}
        err = _transition(fix, DRIFTED)
        if err:
            return {"ok": False, "error": err}
        fix["live_value"] = live_value
        fix["verified"] = False
        fix["drifted_at"] = time.time()
        fix["verify_note"] = (
            "Titan applied and verified this, and the site no longer holds it. "
            "Somebody edited the page or a plugin overwrote it. Nothing was "
            "changed back — re-propose it if it should be reinstated.")
    return {"ok": True, "fix": public(fix_id)}


def rollback(fix_id: str) -> dict:
    """Put the snapshotted value back, and read the site to confirm it."""
    with _lock:
        fix = _fixes.get(fix_id)
        if not fix:
            return {"ok": False, "error": "No such fix."}
        if fix["status"] != APPLIED:
            return {"ok": False, "error": (
                f"Only an applied fix can be rolled back; this one is "
                f"{fix['status']}.")}
        if fix.get("snapshot") is None:
            return {"ok": False, "error": (
                "There is no snapshot of the previous value, so Titan cannot "
                "restore it and will not guess. Restore this one by hand — "
                "WordPress keeps revisions for page content under the editor's "
                "revision history.")}

    cred = site_access.credential(fix["client_id"])
    if not cred:
        return {"ok": False, "error": (
            "The website credential is no longer connected, so Titan cannot "
            "reach the site to undo this.")}

    ok, err = _write_field(cred, fix["target"], fix["field"], fix["snapshot"])
    if not ok:
        return {"ok": False, "error": f"The rollback write failed: {err}",
                "fix": public(fix_id)}

    after, err = _read_field(cred, fix["target"], fix["field"])
    if err:
        return {"ok": False, "error": (
            f"The rollback was sent but Titan could not read the page back to "
            f"confirm it: {err}"), "fix": public(fix_id)}
    if after != fix["snapshot"]:
        return {"ok": False, "error": (
            "The rollback was sent but the page does not hold the previous "
            "value. Restore it by hand from the WordPress revision history."),
            "fix": public(fix_id)}

    with _lock:
        _transition(fix, ROLLED_BACK)
        fix["rolled_back_at"] = time.time()
        fix["verify_note"] = ("Previous value restored and read back from the "
                              "live site.")
    events.emit("SiteFixRolledBack",
                {"fix": fix_id, "client": fix["client_id"]},
                actor="system", severity="warn")
    return {"ok": True, "fix": public(fix_id)}


# ------------------------------------------------------------------ reading --
def public(fix_id: str) -> Optional[dict]:
    """Safe to send over the wire. No credentials, nothing made up."""
    with _lock:
        fix = _fixes.get(fix_id)
        if not fix:
            return None
        out = {k: v for k, v in fix.items()}
    # Long fields are shown as a preview; the full text is available from the
    # detail endpoint, not the list.
    for key in ("current", "proposed", "snapshot"):
        val = out.get(key)
        if isinstance(val, str) and len(val) > 600:
            out[key] = val[:600] + f"… [{len(val)} chars]"
    return out


def for_client(client_id: str, status: str = "") -> list[dict]:
    with _lock:
        ids = [f["id"] for f in _fixes.values()
               if f["client_id"] == client_id and (not status
                                                   or f["status"] == status)]
    rows = [public(i) for i in ids]
    return sorted([r for r in rows if r], key=lambda r: r["created_at"],
                  reverse=True)


def get(fix_id: str) -> Optional[dict]:
    with _lock:
        fix = _fixes.get(fix_id)
        return dict(fix) if fix else None


def awaiting_approval() -> list[dict]:
    """Every proposed fix across every client, oldest first.

    For the approval centre, which needs the whole queue rather than one
    client's slice. Read-only: approving still goes through `approve()`, where
    the staleness check and the named-approver rule live.
    """
    with _lock:
        ids = [f["id"] for f in _fixes.values() if f["status"] == PROPOSED]
    rows = [public(i) for i in ids]
    return sorted([r for r in rows if r], key=lambda r: r["created_at"])


def summary(client_id: str = "") -> dict:
    """Counts by status. Never a success rate."""
    with _lock:
        rows = [f for f in _fixes.values()
                if not client_id or f["client_id"] == client_id]
    counts = {s: sum(1 for f in rows if f["status"] == s) for s in STATUSES}
    applied = counts[APPLIED]
    return {
        "total": len(rows),
        "counts": counts,
        # Verified means read back from the live site, not "the write returned 200".
        # Only this number is measured.
        "verified_live": sum(1 for f in rows
                             if f["status"] == APPLIED and f["verified"]),
        "durable": _durable(),
        "note": ("'Verified live' counts fixes whose new value was read back "
                 "from the site after writing. Fixes that were sent but not "
                 "confirmed are counted as failed, not applied."
                 + ("" if _durable() else
                    " Storage is not durable in this deployment: a rebuild "
                    "would lose the snapshots that make rollback possible.")),
        "applied": applied,
    }


# ------------------------------------------------------------ persistence --
def export_state() -> dict:
    with _lock:
        return {"fixes": {k: dict(v) for k, v in _fixes.items()},
                "counter": _counter}


def import_state(data: dict) -> None:
    global _counter
    if not isinstance(data, dict):
        return
    rows = data.get("fixes")
    if not isinstance(rows, dict):
        return
    with _lock:
        _fixes.clear()
        for fid, rec in rows.items():
            if isinstance(rec, dict) and rec.get("client_id") and rec.get("status"):
                _fixes[fid] = rec
        try:
            _counter = int(data.get("counter") or 0)
        except Exception:
            _counter = 0


def reset() -> None:
    """Test seam."""
    global _counter
    with _lock:
        _fixes.clear()
        _counter = 0
