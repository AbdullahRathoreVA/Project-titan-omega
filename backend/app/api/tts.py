"""Premium text-to-speech via ElevenLabs — optional, founder-only, $0-safe.

Design decisions that keep this free and un-abusable:
  * Only runs when ELEVENLABS_API_KEY is set AND the caller is the authenticated
    founder. Public guest visitors NEVER trigger it, so the small free monthly
    quota (~10k chars) is never burned by demo traffic — the demo just uses the
    browser's built-in voice.
  * The API key lives only in the backend (a Space secret) and is never exposed
    to the browser.
  * Identical lines are cached in-process so repeated boots/briefings cost 0.
  * Any failure returns 204 so the front end silently falls back to browser TTS.
"""

from __future__ import annotations

import hashlib
import os

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..core import auth

router = APIRouter(prefix="/api", tags=["tts"])

# A calm, clear default voice ("Adam"); override with ELEVENLABS_VOICE_ID.
_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB").strip()
# turbo = fastest + cheapest credits; multilingual handles Urdu/Hindi too.
_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2_5").strip()
_cache: dict[str, bytes] = {}


def _authed(request: Request) -> bool:
    """Founder only. If auth is disabled entirely (local dev) allow it; if it's a
    guest demo deploy, never allow it."""
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
        return Response(status_code=204)  # → browser falls back to native TTS

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
