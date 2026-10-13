"""Sex-specific sentence screen for shared normals made outside review (Jev lab 2026-10-13, wording C): >= 0.7 drops
the sentence, 0.5-0.7 keeps it and flags it for the reviewer. Replaces the regex whose `cervi\\w*` dropped every
"cervical" sentence. Library sheets are reviewed and never pass through here."""
from __future__ import annotations

import asyncio
import logging
import os
import re

from pydantic import BaseModel, Field

from ..jev_client import JEV_MODEL, jev_post

logger = logging.getLogger(__name__)
SEX_Q = ("The SENTENCE states something about a body part only one sex has (for example the uterus, endometrium, "
         "ovaries, adnexa, uterine cervix, vagina, prostate, seminal vesicles, testes, scrotum, penis).")
DROP_MIN, FLAG_MIN = 0.7, 0.5
TIMEOUT_S = 4.0
_BACKSTOP = re.compile(r"(?i)\b(?:prostat\w*|seminal|uter(?:us|ine)|endometri\w*|ovar\w*|adnex\w*|testis|testes|"
                       r"testic\w*|scrot\w*|vagin\w*|fallopian|myometri\w*|penis|penile)\b")
_SEM = asyncio.Semaphore(6)


class ScreenResult(BaseModel):
    kept: list[str] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)
    flagged: list[str] = Field(default_factory=list)


async def _score(s: str, transport=None) -> float | None:
    async with _SEM:
        try:
            r = await jev_post({"model": JEV_MODEL, "state": f"SENTENCE: {s}",
                                "questions": {"q": {"type": "noul", "instructions": SEX_Q}}},
                               os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
            r.raise_for_status()
            return float(((r.json().get("answers") or {}).get("q") or {}).get("noul") or 0.0)
        except Exception as e:
            logger.warning("[stack.sex_screen] %s: %s", type(e).__name__, str(e)[:200])
            return None


async def screen(sentences: list[str], transport=None) -> ScreenResult:
    scores = await asyncio.gather(*[_score(s, transport) for s in sentences])
    out = ScreenResult()
    for s, p in zip(sentences, scores):
        if p is None:
            (out.dropped if _BACKSTOP.search(s) else out.kept).append(s)
        elif p >= DROP_MIN:
            out.dropped.append(s)
        else:
            out.kept.append(s)
            if p >= FLAG_MIN:
                out.flagged.append(s)
    return out


async def screen_normals(normals: dict[str, list[str]], transport=None) -> tuple[dict[str, list[str]], list[str]]:
    flat = [s for v in normals.values() for s in v]
    r = await screen(flat, transport)
    gone = set(r.dropped)
    kept = {k: [s for s in v if s not in gone] for k, v in normals.items()}
    return {k: v for k, v in kept.items() if v}, r.flagged
