"""Premium text-to-speech through ElevenLabs. Optional and founder-only.

- Runs only when ELEVENLABS_API_KEY is set and the caller is the signed-in
  founder. Guests never trigger it, so demo traffic can't use up the small
  free quota; the demo uses the browser's voice instead.
- The key stays on the server.
- Identical lines are cached in-process, so repeated briefings cost nothing.
- Any failure returns 204 and the frontend falls back to browser speech.
"""

from __future__ import annotations

import hashlib
import os

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..core import auth

router = APIRouter(prefix="/api", tags=["tts"])

# Cached result of the key check (costs no credits).
_health_cache: dict = {"ts": 0.0, "data": None}

# A calm, clear default voice ("Adam"); override with ELEVENLABS_VOICE_ID.
_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB").strip()
# turbo = fastest + cheapest credits; multilingual handles Urdu/Hindi too.
_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2_5").strip()
_cache: dict[str, bytes] = {}


def _authed(request: Request) -> bool:
    """Founder only. Allowed when auth is off entirely (local dev); never on a
    guest demo deploy.
    """
    if auth.guest_mode():
        return False
    if not auth.require_auth():
        return True
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    return auth.valid_token(token)


@router.post("/tts")
async def tts(request: Request) -> Response:
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key or not _authed(request):
        return Response(status_code=204)  # browser falls back to its own voice

    try:
        body = await request.json()
    except Exception:
        return Response(status_code=204)
    text = (body.get("text") or "").strip()[:800]
    if not text:
        return Response(status_code=204)

    cache_key = hashlib.sha1(f"{_VOICE}:{_MODEL}:{text}".encode()).hexdigest()
    if cache_key in _cache:
        return Response(content=_cache[cache_key], media_type="audio/mpeg")

    try:
        import httpx

        with httpx.Client(timeout=20.0) as c:
            r = c.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{_VOICE}",
                headers={
                    "xi-api-key": key,
                    "accept": "audio/mpeg",
                    "content-type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": _MODEL,
                    "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.3},
                },
            )
        if r.status_code == 200 and r.content:
            if len(_cache) < 128:
                _cache[cache_key] = r.content
            return Response(content=r.content, media_type="audio/mpeg")
    except Exception:
        pass
    return Response(status_code=204)


@router.get("/tts/health")
def tts_health() -> dict:
    """Diagnostic: is the ElevenLabs key present and valid, and how much free
    quota is left?

    Uses /user/subscription, which costs no TTS credits. Cached for 60s.
    """
    import time as _t

    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key:
        return {
            "key_present": False,
            "valid": False,
            "note": "No ELEVENLABS_API_KEY in this container. Add it as a Space SECRET and restart/redeploy.",
        }
    if _health_cache["data"] and _t.monotonic() - _health_cache["ts"] < 60:
        return _health_cache["data"]

    out: dict = {"key_present": True, "valid": False, "voice_id": _VOICE, "model": _MODEL}
    try:
        import httpx

        with httpx.Client(timeout=15.0) as c:
            r = c.get(
                "https://api.elevenlabs.io/v1/user/subscription",
                headers={"xi-api-key": key},
            )
            if r.status_code == 200:
                j = r.json()
                limit, used = j.get("character_limit"), j.get("character_count")
                out["valid"] = True
                out["tier"] = j.get("tier")
                if isinstance(limit, int) and isinstance(used, int):
                    out["characters_used"] = used
                    out["characters_limit"] = limit
                    out["characters_remaining"] = max(0, limit - used)
            else:
                # A 401/403 from /user can mean a scoped key (TTS allowed, account read not),
                # so confirm with a tiny 2-character TTS request.
                probe = c.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{_VOICE}",
                    headers={"xi-api-key": key, "accept": "audio/mpeg", "content-type": "application/json"},
                    json={"text": "OK", "model_id": _MODEL},
                )
                if probe.status_code == 200 and probe.content:
                    out["valid"] = True
                    out["tts_ok"] = True
                    out["note"] = "Key works for Text-to-Speech (account-read scope not granted, which is fine)."
                elif probe.status_code == 401:
                    out["error"] = "401 — key rejected. Recopy the FULL key (starts with 'sk_'); make sure it isn't truncated."
                else:
                    out["error"] = f"TTS probe returned {probe.status_code}: {probe.text[:120]}"
    except Exception as e:  # network blocked / timeout
        out["error"] = f"{type(e).__name__}: {e}"[:160]

    _health_cache["ts"] = _t.monotonic()
    _health_cache["data"] = out
    return out
