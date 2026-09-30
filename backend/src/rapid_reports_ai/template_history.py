"""CLINICAL HISTORY section for templates whose sheet defines one (spec §4, L-36 as refined
2026-09-30): a terse restatement of the platform's clinical-history input, written by a small call,
checked for provenance in code, placed by code. Nothing from the history goes anywhere else."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import List, Optional

from pydantic import BaseModel

from . import report_reconcile as rc
from .enhancement_utils import _run_agent_with_model
from .report_review import ReportSection

logger = logging.getLogger(__name__)

HISTORY_SYS = ("Restate a referral's clinical history for the CLINICAL HISTORY section of a radiology report, in terse "
               "referral format: age and sex abbreviated (e.g. 61M, 52F), key clinical facts as noun phrases separated "
               "by full stops, no connective prose, the clinical question last (prefixed '?'). Use only facts in the "
               "input and add nothing. Return JSON {\"text\": \"...\"}.")

# Words the restatement may use without the input containing them: pure connectives and age units.
# Negations ("no", "not") and certainty/time words ("known", "previous") are facts and are NOT here.
_CONNECTIVES = {"query", "with", "and", "for", "the", "of", "on", "in", "a", "an"}
_AGE_UNITS = {"y", "yo", "yr", "yrs", "year", "years", "old", "aged"}
# "History of X" / "Previous X" restate an input that marks X as past history in any common form.
_PAST_WORDS = {"history", "previous", "prior", "past"}
_PAST_SOURCE = _PAST_WORDS | {"hx", "pmh", "phx", "prev"}
_SEX = {"m": {"male", "man", "m", "boy", "gentleman", "gent", "mr", "he", "his", "him"},
        "f": {"female", "woman", "f", "girl", "lady", "mrs", "ms", "miss", "she", "her"}}
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+")


class _History(BaseModel):
    text: str


def grounded(text: str, history: str) -> bool:
    """Every word and number in `text` comes from `history`; '67F' needs 67 and a female word.

    Tokens are numbers and letter runs, so '72yo' is checked as 72 and 'yo', and every word counts
    regardless of length (a two-letter acronym is a fact)."""
    src_tokens = set(_TOKEN.findall(history.lower()))
    for tok in _TOKEN.findall(text.lower()):
        if tok in src_tokens or tok in _CONNECTIVES:
            continue
        if tok[0].isdigit():
            return False
        if tok in _SEX:
            if not (_SEX[tok] & src_tokens):
                return False
        elif tok in _AGE_UNITS:
            continue
        elif tok in _PAST_WORDS:
            if not (_PAST_SOURCE & src_tokens):
                return False
        else:
            return False
    return True


async def write_history(history: str) -> Optional[str]:
    """The section text, or None (section omitted) on empty input, call failure or failed provenance."""
    if not history.strip():
        return None
    try:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=rc.QWEN, output_type=_History, system_prompt=HISTORY_SYS, user_prompt=history, api_key="",
            model_settings={"temperature": 0, "max_tokens": 400, "reasoning_effort": "none"}), rc.QWEN_TIMEOUT_S)
        text = r.output.text.strip()
    except Exception as e:
        logger.warning("history section failed (%s: %s); omitted", type(e).__name__, str(e)[:200])
        return None
    if not text:
        logger.warning("history section empty; omitted")
        return None
    if not grounded(text, history):
        logger.warning("history section not grounded in the input; omitted: %r", text[:200])
        return None
    return text


def insert_history(report: str, text: str, sections: List[ReportSection]) -> str:
    """Place the section under its header, before the next section (in sheet order) whose header is
    in the report; at the top when the next section is implicit or absent."""
    hist = next(s for s in sections if s.role == "history")
    block = f"{hist.header or hist.name}\n{text}\n\n"
    after = sections[sections.index(hist) + 1:]
    for s in after:
        if s.header is None:
            break
        m = re.search(rf"^[ \t]*{re.escape(s.header.strip().rstrip(':'))}[ \t]*:?[ \t]*$", report, re.M | re.I)
        if m:
            return report[:m.start()] + block + report[m.start():]
    before = sections[:sections.index(hist)]
    if before and all(s.header for s in before):
        return report.rstrip() + "\n\n" + block.rstrip() + "\n"
    return block + report
