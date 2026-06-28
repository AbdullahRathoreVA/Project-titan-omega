"""Free live news headlines via Google News RSS (no API key required).

Used by the Growth Studio 'Latest news' feature to ground market analysis in
what's actually happening today. Degrades gracefully — returns [] on any error
so the dashboard never breaks.
"""

from __future__ import annotations

import os
import ssl
from typing import List
from urllib.parse import quote
from xml.etree import ElementTree


def _verify():
    bundle = os.getenv("TITAN_CA_BUNDLE") or "/root/.ccr/ca-bundle.crt"
    if os.path.exists(bundle):
        return ssl.create_default_context(cafile=bundle)
    return True


def fetch_headlines(query: str, limit: int = 8) -> List[dict]:
    """Return up to ``limit`` recent headlines for ``query``. Never raises."""
    try:
        import httpx

        url = (
            "https://news.google.com/rss/search?q="
            + quote(query)
            + "&hl=en-US&gl=US&ceid=US:en"
        )
        with httpx.Client(
            timeout=10.0, verify=_verify(), trust_env=True, follow_redirects=True
        ) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            return []
        root = ElementTree.fromstring(resp.content)
        out: List[dict] = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            if title:
                out.append({"title": title, "link": link, "published": pub})
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []
