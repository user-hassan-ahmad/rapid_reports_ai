"""General recommendation suggestions (spec §4.4, §5.6): offered unticked; only ticked items reach the report.
Surveillance intervals and thresholds come only from applied guidelines, never from here."""
from __future__ import annotations

import asyncio
import logging
import re
import time

from pydantic import BaseModel, Field

from ...enhancement_utils import _run_agent_with_model
from ...report_reconcile import QWEN

logger = logging.getLogger(__name__)

MAX_ITEMS = 4
TIMEOUT_S = 10.0

RECS_SYS = """You suggest follow-up actions a radiologist may choose to add as recommendations at the end of a report. They tick the ones they want; the rest are dropped.
- 0-4 items, most important first; each one short sentence in British English.
- Only actions the findings or the clinical question call for: referral to a named specialty or multidisciplinary meeting, further imaging with a named modality, correlation with prior imaging or a named test.
- Never restate the clinical history.
- Never an item already APPLIED, never a surveillance interval, size threshold or classification (those come only from guidelines the radiologist applies), never "clinical correlation" on its own.
- Return an empty list when nothing is called for."""


class RawRecs(BaseModel):
    items: list[str] = Field(default_factory=list)


class RecsResult(BaseModel):
    items: list[str] = Field(default_factory=list)
    ms: int = 0
    error: str | None = None


async def _call(prompt: str) -> RawRecs:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=RawRecs, system_prompt=RECS_SYS, user_prompt=prompt, api_key="",
        model_settings={"temperature": 0, "max_tokens": 2000, "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


_BULLET = re.compile(r"^\s*(?:[-*•–—]+|\(?\d{1,2}[.)]|\(?[a-z][)])\s*", re.I)
# A number in a suggestion is an interval or threshold, which only an applied guideline may give: dropped.
_NUMBERISH = re.compile(r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
                        r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty(?:[- ](?:one|two|three|four))?|half|"
                        r"quarter)\b", re.I)


def _clean(item: str) -> str:
    return _BULLET.sub("", item.strip()).strip()


def _n(s: str) -> str:
    return " ".join(s.lower().strip().rstrip(".").split())


async def suggest(scan_type: str, history: str, findings: str, conclusion: str, applied: list[str]) -> RecsResult:
    """Never raises: a failure returns no suggestions (applied ones still show)."""
    t0 = time.perf_counter()
    prompt = (f"SCAN TYPE: {scan_type}\nCLINICAL HISTORY: {history or 'none given'}\n\nFINDINGS:\n{findings}\n\n"
              f"CONCLUSION:\n{conclusion or '(none yet)'}\n\nAPPLIED:\n" + ("\n".join(f"- {a}" for a in applied) or "(none)"))
    try:
        raw = await _call(prompt)
    except Exception as e:
        logger.warning("[copilot.recs] %s: %s", type(e).__name__, str(e)[:200])
        return RecsResult(ms=int((time.perf_counter() - t0) * 1000), error=type(e).__name__)
    seen = {_n(a) for a in applied}
    items = []
    for it in (_clean(x) for x in raw.items):
        if _NUMBERISH.search(it):
            logger.info("[copilot.recs] dropped a suggestion carrying a number")
            continue
        if it and _n(it) not in seen:
            seen.add(_n(it))
            items.append(it.strip())
    return RecsResult(items=items[:MAX_ITEMS], ms=int((time.perf_counter() - t0) * 1000))
