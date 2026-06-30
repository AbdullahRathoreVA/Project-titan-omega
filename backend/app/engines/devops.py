"""Autonomous code edits via REAL pull requests (never direct pushes).

The honest, safe way for an AI to "edit your app": it proposes an improvement to
a watched repo (default: Career Mind) by opening a PR you review and merge. It
touches a SINGLE text/markdown file by default so it can't break a build, and it
never merges anything itself. Requires GITHUB_TOKEN with repo (write) scope; with
no token or a read-only token it returns an honest error and changes nothing.
"""

from __future__ import annotations

import base64
import os
import time
from typing import Optional

from ..connectors.github import _verify
from ..core import llm
from ..store import STORE, Store

GH = "https://api.github.com"


def _headers() -> tuple[dict, bool]:
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers, bool(token)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def open_improvement_pr(
    owner: str,
    repo: str,
    instruction: str,
    path: str = "README.md",
    store: Store = STORE,
) -> dict:
    """Draft an improvement to one file and open a PR. Never raises."""
    headers, has_token = _headers()
    if not has_token:
        return {"ok": False, "pr_url": None, "error": "No GITHUB_TOKEN set on the server."}

    try:
        import httpx

        with httpx.Client(timeout=25.0, verify=_verify(), trust_env=True, follow_redirects=True) as c:
            info = c.get(f"{GH}/repos/{owner}/{repo}", headers=headers)
            if info.status_code != 200:
                return {"ok": False, "pr_url": None,
                        "error": f"Repo not reachable (HTTP {info.status_code}). Check the token has access to {owner}/{repo}."}
            base = info.json().get("default_branch", "main")

            ref = c.get(f"{GH}/repos/{owner}/{repo}/git/ref/heads/{base}", headers=headers)
            if ref.status_code != 200:
                return {"ok": False, "pr_url": None, "error": f"Couldn't read base branch '{base}' (HTTP {ref.status_code})."}
            base_sha = ref.json()["object"]["sha"]

            cur = c.get(f"{GH}/repos/{owner}/{repo}/contents/{path}", headers=headers, params={"ref": base})
            current = ""
            file_sha: Optional[str] = None
            if cur.status_code == 200:
                j = cur.json()
                file_sha = j.get("sha")
                try:
                    current = base64.b64decode(j.get("content", "")).decode("utf-8", "ignore")
                except Exception:
                    current = ""

            improved = llm.complete(
                system=(
                    f"You are improving the file '{path}' in the repo {owner}/{repo}. "
                    f"Apply this instruction: {instruction}. Return ONLY the full new file "
                    "content (valid markdown/text), with no commentary and no code fences. "
                    "Keep all important existing information; improve clarity, persuasiveness, "
                    "and SEO. Be truthful — invent no fake stats."
                ),
                prompt="CURRENT FILE CONTENT:\n" + (current or "(file does not exist yet — create it)"),
                max_tokens=2000,
            )
            if not improved:
                return {"ok": False, "pr_url": None, "error": "LLM produced no content (set a free GROQ_API_KEY)."}
            improved = _strip_fences(improved)

            branch = f"titan/auto-{int(time.time())}"
            mk = c.post(f"{GH}/repos/{owner}/{repo}/git/refs", headers=headers,
                        json={"ref": f"refs/heads/{branch}", "sha": base_sha})
            if mk.status_code not in (200, 201):
                return {"ok": False, "pr_url": None,
                        "error": f"Couldn't create a branch (HTTP {mk.status_code}). The token likely lacks write/repo scope."}

            payload = {
                "message": f"Titan: improve {path}",
                "content": base64.b64encode(improved.encode("utf-8")).decode("ascii"),
                "branch": branch,
            }
            if file_sha:
                payload["sha"] = file_sha
            put = c.put(f"{GH}/repos/{owner}/{repo}/contents/{path}", headers=headers, json=payload)
            if put.status_code not in (200, 201):
                return {"ok": False, "pr_url": None, "error": f"Couldn't commit the change (HTTP {put.status_code})."}

            pr = c.post(f"{GH}/repos/{owner}/{repo}/pulls", headers=headers, json={
                "title": f"Titan: improve {path}",
                "head": branch,
                "base": base,
                "body": (
                    "Automated improvement proposed by **Titan Omega**.\n\n"
                    f"**Instruction:** {instruction}\n\n"
                    "Safe by design: it edits a single file and is opened as a PR — "
                    "review and merge if it looks good. Nothing is auto-merged."
                ),
            })
            if pr.status_code not in (200, 201):
                return {"ok": False, "pr_url": None, "error": f"Couldn't open the PR (HTTP {pr.status_code})."}

            url = pr.json().get("html_url")
            store.emit("technology-head", "command",
                       f"Opened a pull request on {owner}/{repo}: improve {path}.", "success")
            return {"ok": True, "pr_url": url, "repo": f"{owner}/{repo}", "path": path, "branch": branch}

    except Exception as exc:  # network / API failure — honest, never crash
        return {"ok": False, "pr_url": None, "error": f"{type(exc).__name__}: {exc}"}
