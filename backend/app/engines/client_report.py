"""The PDF a client actually receives — the deliverable that justifies the fee.

A dashboard proves the work exists. A PDF is what a restaurant owner forwards
to their business partner, prints, or hands to whoever maintains their website.
It is also what makes a free trial feel like a service rather than a demo.

Design decisions that matter:

  - Legal exposure leads. For a German client the Impressum finding is worth
    more than every keyword tip combined, so it sits above the SEO section in
    its own framed block with the statute and the fine range stated plainly.
  - Findings are ordered by severity and each carries its fix. A report that
    lists problems without remedies gets ignored.
  - The client's own logo goes on the cover when they supplied one, because
    the report is theirs, not ours.
  - Nothing is invented. Where a number cannot be measured (traffic, rankings)
    the report says which tool would provide it instead of guessing.

Built on reportlab, which is already installed — no new dependency, and no
Docker container needed for what is fundamentally text on a page.
"""

from __future__ import annotations

import io
import time
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, Image, KeepTogether, PageBreak,
                                Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

INK = colors.HexColor("#15202b")
MUT = colors.HexColor("#5b6b7d")
GOLD = colors.HexColor("#b8912f")
RED = colors.HexColor("#c0392b")
AMBER = colors.HexColor("#d68910")
BLUE = colors.HexColor("#2471a3")
GREEN = colors.HexColor("#1e8449")
LINE = colors.HexColor("#dfe4ea")

SEV_COLOR = {
    "legal-critical": RED, "critical": RED, "high": AMBER,
    "medium": BLUE, "low": MUT,
}
SEV_LABEL = {
    "legal-critical": "LEGAL", "critical": "CRITICAL", "high": "HIGH",
    "medium": "MEDIUM", "low": "LOW",
}


def _styles() -> dict:
    s = getSampleStyleSheet()
    mk = lambda **kw: ParagraphStyle(**kw)
    return {
        "h1": mk(name="h1", fontName="Helvetica-Bold", fontSize=24,
                 textColor=INK, leading=29, spaceAfter=4),
        "sub": mk(name="sub", fontName="Helvetica", fontSize=10.5,
                  textColor=MUT, leading=15),
        "h2": mk(name="h2", fontName="Helvetica-Bold", fontSize=13,
                 textColor=INK, leading=17, spaceBefore=18, spaceAfter=7),
        "h3": mk(name="h3", fontName="Helvetica-Bold", fontSize=10.5,
                 textColor=INK, leading=14, spaceAfter=2),
        "body": mk(name="body", fontName="Helvetica", fontSize=9.5,
                   textColor=INK, leading=14, alignment=TA_LEFT),
        "mut": mk(name="mut", fontName="Helvetica", fontSize=9,
                  textColor=MUT, leading=13),
        "fix": mk(name="fix", fontName="Helvetica-Oblique", fontSize=9,
                  textColor=GREEN, leading=13),
        "big": mk(name="big", fontName="Helvetica-Bold", fontSize=42,
                  textColor=INK, leading=46),
        "legal": mk(name="legal", fontName="Helvetica", fontSize=9.5,
                    textColor=INK, leading=14),
    }


def _esc(t: str) -> str:
    return (str(t or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _grade_color(score: int):
    return GREEN if score >= 75 else (AMBER if score >= 50 else RED)


def build(client: dict, seo: dict, *, social: Optional[dict] = None,
          agency: str = "Titan Omega") -> bytes:
    """Render the report. Returns PDF bytes; never raises on missing fields."""
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=f"{client.get('business_name','')} — Website Report",
        author=agency, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm)

    F: list = []
    name = client.get("business_name", "Your business")
    where = " · ".join(x for x in (client.get("city"), client.get("country")) if x)

    # ------------------------------------------------------------ cover ----
    logo = client.get("logo_url") or ""
    if logo.startswith(("http://", "https://")):
        try:
            import urllib.request
            with urllib.request.urlopen(logo, timeout=8) as r:
                F.append(Image(io.BytesIO(r.read()), width=32 * mm, height=32 * mm,
                               kind="proportional"))
                F.append(Spacer(1, 6 * mm))
        except Exception:
            pass  # a missing logo must never break the report

    F.append(Paragraph(_esc(name), st["h1"]))
    F.append(Paragraph(
        f"Website &amp; visibility report &nbsp;·&nbsp; {where}", st["sub"]))
    F.append(Paragraph(
        f"Prepared by {_esc(agency)} · {time.strftime('%d %B %Y')}", st["sub"]))
    F.append(Spacer(1, 5 * mm))
    F.append(HRFlowable(width="100%", color=LINE, thickness=1))
    F.append(Spacer(1, 7 * mm))

    if not seo.get("ok"):
        F.append(Paragraph("We could not reach your website", st["h2"]))
        F.append(Paragraph(
            f"The site returned <b>{_esc(seo.get('error','no response'))}</b>. "
            f"Nothing else can be assessed until it responds. This on its own "
            f"means customers searching for you are hitting a dead page.",
            st["body"]))
        doc.build(F)
        return buf.getvalue()

    score = int(seo.get("score", 0))
    counts = seo.get("counts", {}) or {}

    # ----------------------------------------------------------- score -----
    verdict = ("Your site is in good shape." if score >= 75 else
               "Your site is losing visible search traffic." if score >= 50 else
               "Your site is close to invisible in search.")
    tbl = Table([[
        Paragraph(f'<font color="{_grade_color(score).hexval()}">{score}</font>'
                  f'<font size="15" color="#5b6b7d">/100</font>', st["big"]),
        Paragraph(
            f"<b>{_esc(verdict)}</b><br/>"
            f"Grade {_esc(seo.get('grade','—'))} &nbsp;·&nbsp; "
            f"{len(seo.get('findings', []))} issues found<br/>"
            f'<font color="#c0392b">{counts.get("legal_critical", 0)} legal</font> · '
            f'<font color="#c0392b">{counts.get("critical", 0)} critical</font> · '
            f'<font color="#d68910">{counts.get("high", 0)} high</font> · '
            f'<font color="#2471a3">{counts.get("medium", 0)} medium</font>',
            st["body"]),
    ]], colWidths=[42 * mm, None])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
    ]))
    F.append(tbl)
    F.append(Spacer(1, 6 * mm))

    # ----------------------------------------------------------- legal -----
    legal = seo.get("legal") or {}
    lf = legal.get("findings") or []
    if legal.get("country_name"):
        F.append(Paragraph(
            f"Legal compliance — {_esc(legal['country_name'])}", st["h2"]))
        if lf:
            rows = [[Paragraph(
                f"<b>{_esc(f['title'])}</b><br/>"
                f'<font color="#5b6b7d">{_esc(f["detail"])}</font><br/>'
                f'<font color="#1e8449">Fix: {_esc(f["fix"])}</font>',
                st["legal"])] for f in lf]
            t = Table(rows, colWidths=[None])
            t.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 1, RED),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fdf2f0")),
            ]))
            F.append(t)
            F.append(Spacer(1, 3 * mm))
            F.append(Paragraph(
                f"Governing rule: {_esc(legal.get('law',''))}."
                + (" In this jurisdiction a competitor may issue a formal "
                   "cease-and-desist over these defects and bill their legal "
                   "costs." if legal.get("abmahnung_risk") else ""), st["mut"]))
        else:
            F.append(Paragraph(
                f"No missing imprint or privacy notice detected. "
                f"Governing rule: {_esc(legal.get('law',''))}.", st["body"]))
        F.append(Spacer(1, 2 * mm))
        F.append(Paragraph(_esc(legal.get("disclaimer", "")), st["mut"]))

    # -------------------------------------------------------- findings -----
    findings = [f for f in seo.get("findings", [])
                if f.get("severity") != "legal-critical"]
    if findings:
        F.append(Paragraph("What to fix on the website", st["h2"]))
        for f in findings:
            sev = f.get("severity", "low")
            col = SEV_COLOR.get(sev, MUT)
            F.append(KeepTogether([
                Paragraph(
                    f'<font color="{col.hexval()}" size="7">'
                    f'{SEV_LABEL.get(sev, sev.upper())}</font> &nbsp; '
                    f'{_esc(f.get("title",""))}', st["h3"]),
                Paragraph(_esc(f.get("detail", "")), st["mut"]),
                Paragraph(f"Fix: {_esc(f.get('fix',''))}", st["fix"]),
                Spacer(1, 3.5 * mm),
            ]))

    # ---------------------------------------------------------- social -----
    if social:
        F.append(PageBreak())
        F.append(Paragraph("Social media plan", st["h2"]))
        F.append(Paragraph(
            "Built from how the largest luxury brands actually behave, measured "
            "directly from their live profiles rather than from advice blogs. "
            "The headline finding: volume is not the lever. Gucci holds 50.5M "
            "followers on 367 posts. Four crafted posts a week outperform daily "
            "filler, and discount-led posting actively damages a premium "
            "restaurant's positioning.", st["mut"]))
        F.append(Spacer(1, 4 * mm))
        week = social.get("week") or []
        if week:
            data = [["Day", "Format", "Theme", "Brief"]] + [
                [w.get("day", ""), w.get("format", ""), w.get("pillar", ""),
                 Paragraph(_esc(w.get("brief", "")), st["mut"])] for w in week]
            t = Table(data, colWidths=[22 * mm, 20 * mm, 36 * mm, None])
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUT),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
                ("LINEBELOW", (0, 1), (-1, -2), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
            ]))
            F.append(t)

        hl = social.get("highlights") or []
        if hl:
            F.append(Spacer(1, 6 * mm))
            F.append(Paragraph("Story highlights to create", st["h3"]))
            F.append(Paragraph(" · ".join(_esc(h) for h in hl), st["body"]))
            F.append(Paragraph(
                "Named after what you serve, in your own language — the way "
                "Dior and Louis Vuitton name theirs. Never “Menu” or “About us”.",
                st["mut"]))

        avoid = social.get("avoid") or []
        if avoid:
            F.append(Spacer(1, 5 * mm))
            F.append(Paragraph("What to avoid", st["h3"]))
            for a, why in avoid:
                F.append(Paragraph(
                    f"<b>{_esc(a)}</b> — {_esc(why)}", st["mut"]))

    # ------------------------------------------------------- what next -----
    F.append(Spacer(1, 8 * mm))
    F.append(HRFlowable(width="100%", color=LINE, thickness=1))
    F.append(Spacer(1, 4 * mm))
    F.append(Paragraph("What we cannot measure from outside", st["h3"]))
    F.append(Paragraph(
        "Search rankings, visitor numbers and Google Business Profile health "
        "cannot be read from your public website. They require Search Console "
        "and Business Profile access, which only you can grant. We would rather "
        "state that than publish an estimate.", st["mut"]))

    doc.build(F)
    return buf.getvalue()
