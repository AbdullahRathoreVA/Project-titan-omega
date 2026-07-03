"""Live web research via Tavily (free tier: ~1,000 searches/month).

Powers real lead-finding and market intelligence. Set ``TAVILY_API_KEY`` (free
at tavily.com) to enable. With no key it returns [] and callers fall back to an
LLM brainstorm, so the app never breaks.
"""

from __future__ import annotations

import os
from typing import List, Optional


def available() -> bool:
    return bool(os.getenv("TAVILY_API_KEY", "").strip())


def search(query: str, max_results: int = 8) -> List[dict]:
    """Return live web results [{title, url, content}]. Never raises."""
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        return []
    try:
        import httpx

        with httpx.Client(timeout=20.0, trust_env=True) as client:
            resp = client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                    "include_answer": False,
                },
            )
        if resp.status_code != 200:
            return []
        data = resp.json()
        out: List[dict] = []
        for r in data.get("results", []):
            out.append(
                {
                    "title": (r.get("title") or "").strip(),
                    "url": (r.get("url") or "").strip(),
                    "content": (r.get("content") or "").strip()[:400],
                }
            )
        return out
    except Exception:
        return []
