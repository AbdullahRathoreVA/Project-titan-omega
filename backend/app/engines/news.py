"""Live news headlines from Google News RSS (no API key needed).

Used by Growth Studio's "Latest news" to ground market analysis in today's
headlines. Returns [] on any error so the dashboard keeps working.
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
