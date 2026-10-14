"""The session resolution as a signed token (spec D26, §8.1): what /stack/schema resolved (template, library entry or
free text), so /slim-sheet and Generate read it and never re-resolve from what the browser sends. No table, no
migration; a token is only trusted if this server signed it.

Payloads (all carry "v": 1):
  template: {"src": "template", "tid": str, "sh": sheet_hash at setup}
  library:  {"src": "library", "eid": str, "ph": list[str], "lat": str | None, "bv": bundle version, "sid": str}
  free:     {"src": "free", "scan": str, "sk": schema key, "sid": str | None (filled by /slim-sheet)}
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json


class TokenError(ValueError):
    """Not a token this server issued (forged, truncated, or signed with another secret)."""


def _secret() -> bytes:
    from ..auth import SECRET_KEY
    return ("rr-structure-key:" + SECRET_KEY).encode()


def _sign(body: str) -> str:
    return hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:32]


def mint(payload: dict) -> str:
    raw = json.dumps({**payload, "v": 1}, sort_keys=True, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{body}.{_sign(body)}"


def verify(token: str) -> dict:
    try:
        body, sig = token.split(".")
        ok = hmac.compare_digest(sig, _sign(body))
    except (AttributeError, ValueError, TypeError):
        raise TokenError("malformed") from None
    if not ok:
        raise TokenError("bad signature")
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:  # noqa: BLE001
        raise TokenError("bad body") from None
    if not isinstance(data, dict) or data.get("v") != 1 or data.get("src") not in ("template", "library", "free"):
        raise TokenError("unknown shape")
    return data
