"""Jurisdiction-aware website compliance checks.

For a German business a missing Impressum is a legal liability, not an SEO
weakness:

  - The Impressum duty is in §5 Digitale-Dienste-Gesetz (DDG), which replaced
    the Telemediengesetz (TMG) in May 2024. Many online checklists still cite
    TMG.
  - A missing or incomplete Impressum can draw fines up to €50,000; first
    offences with minor defects typically land at €500-1,500.
  - Any competitor can send an Abmahnung (formal cease-and-desist) over a
    deficient Impressum, demanding correction, a signed undertaking and their
    legal costs, commonly €500-1,000+.
  - A Datenschutzerklärung (GDPR privacy notice) is required separately, and
    GDPR penalties reach €20m or 4% of global turnover.

So legal exposure is reported in money, not points. Findings are based only
on what's missing from the served HTML. This isn't legal advice, and the
report says so.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------- profiles --
# What each jurisdiction requires on a commercial website.
JURISDICTIONS = {
    "DE": {
        "name": "Germany",
        "law": "§5 Digitale-Dienste-Gesetz (DDG, replaced TMG in May 2024)",
        "imprint_terms": ["impressum", "anbieterkennzeichnung"],
        "privacy_terms": ["datenschutz", "datenschutzerklärung",
                          "datenschutzerklaerung", "privacy"],
        "terms_terms": ["agb", "allgemeine geschäftsbedingungen"],
        "imprint_required": True,
        "imprint_fine": "up to €50,000 (typically €500–1,500 for a first, "
                        "minor defect)",
        "abmahnung_risk": True,
        "cookie_consent": True,
        "language": "de",
    },
    "AT": {
        "name": "Austria", "law": "§5 ECG / §25 MedienG",
        "imprint_terms": ["impressum", "offenlegung"],
        "privacy_terms": ["datenschutz", "privacy"],
        "terms_terms": ["agb"],
        "imprint_required": True,
        "imprint_fine": "up to €3,000 (ECG)", "abmahnung_risk": True,
        "cookie_consent": True, "language": "de",
    },
    "CH": {
        "name": "Switzerland", "law": "UWG Art. 3(1)(s)",
        "imprint_terms": ["impressum", "kontakt"],
        "privacy_terms": ["datenschutz", "privacy"],
        "terms_terms": ["agb"],
        "imprint_required": True, "imprint_fine": "UWG penalties apply",
        "abmahnung_risk": False, "cookie_consent": True, "language": "de",
    },
    "FR": {
        "name": "France", "law": "LCEN — mentions légales",
        "imprint_terms": ["mentions légales", "mentions legales"],
        "privacy_terms": ["confidentialité", "confidentialite",
                          "données personnelles", "privacy"],
        "terms_terms": ["cgv", "conditions générales"],
        "imprint_required": True,
        "imprint_fine": "up to €75,000 for individuals / €375,000 for companies",
        "abmahnung_risk": False, "cookie_consent": True, "language": "fr",
    },
    "IT": {
        "name": "Italy", "law": "D.Lgs. 70/2003",
        "imprint_terms": ["note legali", "informazioni legali"],
        "privacy_terms": ["privacy", "informativa"],
        "terms_terms": ["termini", "condizioni"],
        "imprint_required": True, "imprint_fine": "administrative penalties apply",
        "abmahnung_risk": False, "cookie_consent": True, "language": "it",
    },
    "ES": {
        "name": "Spain", "law": "LSSI-CE Art. 10",
        "imprint_terms": ["aviso legal", "información legal"],
        "privacy_terms": ["privacidad", "protección de datos"],
        "terms_terms": ["términos", "condiciones"],
        "imprint_required": True, "imprint_fine": "up to €30,000 (LSSI)",
        "abmahnung_risk": False, "cookie_consent": True, "language": "es",
    },
    "NL": {
        "name": "Netherlands", "law": "Dutch implementation of the e-Commerce Directive",
        "imprint_terms": ["colofon", "algemene informatie", "contact"],
        "privacy_terms": ["privacy", "privacyverklaring"],
        "terms_terms": ["algemene voorwaarden"],
        "imprint_required": True, "imprint_fine": "administrative penalties apply",
        "abmahnung_risk": False, "cookie_consent": True, "language": "nl",
    },
    "UK": {
        "name": "United Kingdom",
        "law": "Companies Act 2006 / E-Commerce Regulations 2002",
        "imprint_terms": ["legal", "company information", "about us", "terms"],
        "privacy_terms": ["privacy", "privacy policy"],
        "terms_terms": ["terms", "terms and conditions"],
        "imprint_required": True, "imprint_fine": "civil penalties apply",
        "abmahnung_risk": False, "cookie_consent": True, "language": "en",
    },
    "US": {
        "name": "United States", "law": "state privacy law (CCPA/CPRA et al.)",
        "imprint_terms": [], "privacy_terms": ["privacy", "privacy policy"],
        "terms_terms": ["terms", "terms of service"],
        "imprint_required": False, "imprint_fine": "n/a",
        "abmahnung_risk": False, "cookie_consent": False, "language": "en",
    },
}

EU_EEA = {"DE", "AT", "FR", "IT", "ES", "NL", "BE", "PL", "SE", "DK", "FI",
          "IE", "PT", "GR", "CZ", "HU", "RO", "SK", "SI", "HR", "BG", "LT",
          "LV", "EE", "LU", "MT", "CY", "NO", "IS", "LI"}

# Consent platforms and common self-hosted banner markers.
CONSENT_MARKERS = [
    "cookiebot", "onetrust", "usercentrics", "cookieyes", "termly",
    "iubenda", "klaro", "borlabs", "complianz", "cookie-consent",
    "cookieconsent", "cmp.", "didomi", "quantcast", "trustarc",
]


# The onboarding form and client record store a country name ("Germany"), not
# a code. Without this map the value wouldn't match JURISDICTIONS and we'd fall
# back to the TLD - a German business on a .com would be audited as US and skip
# the Impressum check. Aliases cover what a client would actually type.
COUNTRY_NAMES = {
    "germany": "DE", "deutschland": "DE",
    "austria": "AT", "österreich": "AT", "oesterreich": "AT",
    "switzerland": "CH", "schweiz": "CH", "suisse": "CH",
    "france": "FR",
    "italy": "IT", "italia": "IT",
    "spain": "ES", "españa": "ES", "espana": "ES",
    "netherlands": "NL", "the netherlands": "NL", "nederland": "NL",
    "united kingdom": "UK", "great britain": "UK", "england": "UK",
    "scotland": "UK", "wales": "UK", "gb": "UK",
    "united states": "US", "united states of america": "US", "usa": "US",
    "america": "US",
}


def code_for(declared: str) -> str:
    """A declared country code or NAME -> jurisdiction code, or '' if unknown."""
    d = (declared or "").strip()
    if not d:
        return ""
    if d.upper() in JURISDICTIONS:
        return d.upper()
    return COUNTRY_NAMES.get(d.lower(), "")


def detect_country(html: str, tld: str = "", declared: str = "") -> str:
    """Best-effort jurisdiction. A declared value always wins.

    An unrecognised declared value falls through to TLD and lang evidence
    instead of asserting a jurisdiction we can't support.
    """
    named = code_for(declared)
    if named:
        return named
    tld_map = {"de": "DE", "at": "AT", "ch": "CH", "fr": "FR", "it": "IT",
               "es": "ES", "nl": "NL", "uk": "UK", "co.uk": "UK"}
    if tld and tld.lower() in tld_map:
        return tld_map[tld.lower()]
    lang = re.search(r'<html[^>]+lang=["\']([a-z]{2})', html or "", re.I)
    if lang:
        return {"de": "DE", "fr": "FR", "it": "IT", "es": "ES",
                "nl": "NL"}.get(lang.group(1).lower(), "US")
    return "US"


def _has_link(html: str, terms: list[str]) -> bool:
    """Look for a link whose href or anchor text matches any term."""
    if not terms:
        return True
    low = (html or "").lower()
    for t in terms:
        slug = t.replace(" ", "-").replace("ä", "a").replace("ö", "o")
        if f">{t}" in low or f"{t}<" in low:
            return True
        if re.search(rf'href=["\'][^"\']*{re.escape(slug)}', low):
            return True
        if re.search(rf'href=["\'][^"\']*{re.escape(t.replace(" ", ""))}', low):
            return True
    return False


def check(html: str, *, country: str = "", tld: str = "",
          url: str = "") -> dict:
    """Return legal-exposure findings for the detected jurisdiction."""
    cc = detect_country(html, tld=tld, declared=country)
    profile = JURISDICTIONS.get(cc, JURISDICTIONS["US"])
    in_eu = cc in EU_EEA

    findings: list[dict] = []

    # ---------------------------------------------------------- imprint ----
    if profile["imprint_required"]:
        found = _has_link(html, profile["imprint_terms"])
        if not found:
            label = profile["imprint_terms"][0].title()
            detail = (
                f"No {label} link found. Required by {profile['law']}. "
                f"Exposure: {profile['imprint_fine']}.")
            if profile["abmahnung_risk"]:
                detail += (" In this jurisdiction any COMPETITOR can serve an "
                           "Abmahnung (cease-and-desist) over this, demanding "
                           "correction plus their legal costs — commonly "
                           "€500–1,000+. This is the single highest-risk item "
                           "on the site.")
            findings.append({
                "id": "imprint", "severity": "legal-critical",
                "title": f"Missing {label} — legal requirement, not an SEO tweak",
                "detail": detail,
                "fix": (f"Add a {label} page linked from every page footer, "
                        f"listing the operator's full legal name, physical "
                        f"address (no PO box), email, phone, and where "
                        f"applicable VAT ID and register entry."),
            })

    # ---------------------------------------------------------- privacy ----
    if not _has_link(html, profile["privacy_terms"]):
        findings.append({
            "id": "privacy", "severity": "legal-critical",
            "title": "No privacy policy linked",
            "detail": ("Required wherever personal data is processed — which "
                       "includes basic server logs and any contact form."
                       + (" Under GDPR, penalties reach €20m or 4% of global "
                          "annual turnover." if in_eu else "")),
            "fix": ("Publish a privacy notice covering what is collected, the "
                    "legal basis, retention, processors, and data-subject "
                    "rights. Link it from every page."),
        })

    # ------------------------------------------------------ cookie consent --
    if profile["cookie_consent"]:
        low = (html or "").lower()
        has_cmp = any(m in low for m in CONSENT_MARKERS)
        trackers = []
        # These are regexes, so literal parentheses must be escaped - an unescaped
        # "gtag(" raises PatternError and fails the whole audit.
        for name, sig in (
            ("Google Analytics", r"gtag\(|google-analytics|googletagmanager"),
            ("Meta Pixel", r"connect\.facebook\.net|fbq\("),
            ("Hotjar", r"static\.hotjar\.com|hotjar"),
            ("TikTok Pixel", r"tiktok\.com/i18n/pixel"),
            ("Matomo", r"matomo|piwik"),
        ):
            try:
                if re.search(sig, low):
                    trackers.append(name)
            except re.error:
                continue
        if trackers and not has_cmp:
            findings.append({
                "id": "cookie_consent", "severity": "legal-critical",
                "title": f"Tracking without a consent banner ({', '.join(trackers)})",
                "detail": ("Analytics and marketing trackers are loading with "
                           "no detectable consent platform. Under GDPR/ePrivacy "
                           "these require prior opt-in consent — loading them "
                           "before consent is the most commonly fined defect."),
                "fix": ("Install a consent manager (Cookiebot, Usercentrics, "
                        "Klaro or Borlabs) and block all non-essential scripts "
                        "until the visitor opts in."),
            })

    # -------------------------------------------------------- geo signals --
    hreflang = re.findall(r'hreflang=["\']([^"\']+)["\']', html or "", re.I)
    if hreflang:
        bad = [h for h in hreflang
               if not re.fullmatch(r"(x-default|[a-z]{2}(-[A-Za-z]{2})?)", h)]
        if bad:
            findings.append({
                "id": "hreflang", "severity": "high",
                "title": f"Invalid hreflang values: {', '.join(bad[:4])}",
                "detail": ("75% of international sites have hreflang errors, "
                           "which fragment rankings and surface the wrong "
                           "language version in the wrong country."),
                "fix": "Use valid ISO codes (de, de-AT, en-GB) plus x-default, "
                       "with self-referencing and symmetric annotations.",
            })

    lang_attr = re.search(r'<html[^>]+lang=["\']([^"\']+)', html or "", re.I)
    if not lang_attr:
        findings.append({
            "id": "html_lang", "severity": "medium",
            "title": "No lang attribute on <html>",
            "detail": ("Search engines and screen readers cannot reliably "
                       "determine the page language."),
            "fix": f'<html lang="{profile["language"]}">',
        })

    return {
        "country": cc,
        "country_name": profile["name"],
        "law": profile["law"],
        "in_eu_eea": in_eu,
        "abmahnung_risk": profile["abmahnung_risk"],
        "findings": findings,
        "legal_critical": sum(1 for f in findings
                              if f["severity"] == "legal-critical"),
        "disclaimer": ("This is an automated check of what the page serves, "
                       "not legal advice. A lawyer should confirm the final "
                       "wording for the client's specific entity."),
    }
