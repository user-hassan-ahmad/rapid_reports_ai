"""Findings-triggered habits in the scratchpad (spec 2026-10-13-findings-triggered-rows-design).

A template's confirmed habits are read from its grammar structure: a habit question (RULE WHEN [findings: …] ASK) and a
required statement (NEGATIVE … WHEN [findings: …]), each in a findings paragraph, active only with a confirmed ledger
entry (Hassan H3). At the end-of-dictation review one Jev call asks one noul question per distinct condition, on the
scan type and the dictated findings only, never the clinical history (Hassan H1); a score below TRIGGER_MIN is silent
(Hassan H2). Jev decides; items.py turns the met questions into rows and the met statements into the assumed tray;
code applies. Fail-soft: a failed call gives no template rows (the generic rows are as today), logged."""
from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable, Literal, Optional

from pydantic import BaseModel

from ..jev_client import JEV_MODEL, jev_post
from ..template_sheet_structure import SheetStructure
from .template import paragraph_regions

logger = logging.getLogger(__name__)

TIMEOUT_S = 3.0
TRIGGER_MIN = 0.5   # = jev_stack.CONDITION_MIN until the trigger lab reports (Hassan sets it)
# Two wordings labbed (scripts/triggered_rows_lab.py); B names what does not count. Case-agnostic.
TRIGGER_WORDINGS = {
    "A": "The DICTATION reports this: {condition}.",
    "B": ("The DICTATION reports this as present: {condition}. A finding the dictation negates, excludes or only raises "
          "as a question is not reported."),
}
TRIGGER_WORDING = TRIGGER_WORDINGS["B"]


class Habit(BaseModel):
    region: str                       # the paragraph-region it belongs to (template_regions' name)
    condition: str                    # the findings condition, as the sheet writes it
    mode: Literal["ask", "state"]
    question: str = ""                # ask: the template's question
    yes: str = ""                     # ask: the sentence a Yes writes
    no: str = ""                      # ask: the sentence a No writes; state: the required statement


def template_habits(st: SheetStructure, ledger: Optional[list[dict]] = None) -> list[Habit]:
    """The sheet's habits in sheet order, questions first, under their region names. With a ledger (every production
    caller), only habits it holds as "ask" or "state" are returned: a line nobody confirmed is inactive (Hassan H3).
    None (the labs' hand-written sheets): every habit in the sheet."""
    from ..template_decisions import _name
    from ..template_ledger_apply import confirmed_habits
    names = paragraph_regions(st)
    ok = None if ledger is None else confirmed_habits(st, ledger)

    def active(pid: str, cond: str) -> bool:
        return pid in names and (ok is None or (pid, _name(cond)) in ok)
    out = [Habit(region=names[r.paragraph], condition=r.condition, mode="ask", question=r.question,
                 yes=r.then_text, no=r.else_text)
           for r in st.rules if r.effect == "ask" and r.condition_source == "findings" and active(r.paragraph, r.condition)]
    out += [Habit(region=names[n.paragraph], condition=n.condition, mode="state", no=n.text)
            for n in st.negatives if n.origin == "template" and n.condition and n.condition_source == "findings"
            and active(n.paragraph, n.condition)]
    return out


def trigger_question(condition: str, wording: str = TRIGGER_WORDING) -> dict:
    return {"type": "noul", "instructions": wording.format(condition=" ".join(condition.split()).rstrip("."))}


async def ask_triggers(scan_type: str, findings: str, conditions: list[str], transport=None,
                       wording: str = TRIGGER_WORDING) -> list[float]:
    """P(the dictation reports it) per condition, in order, in one Jev call on the scan type and the dictated findings
    (item 1's condition_state with no history). Raises on any failure."""
    from ..template_context_rules import condition_state
    if not conditions:
        return []
    qs = {f"t{i}": trigger_question(c, wording) for i, c in enumerate(conditions)}
    r = await jev_post({"model": JEV_MODEL, "state": condition_state(scan_type, None, findings), "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    out = []
    for i in range(len(conditions)):
        v = (ans.get(f"t{i}") or {}).get("noul")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("jev: incomplete answers")
        out.append(float(v))
    return out


Ask = Callable[[str, str, list[str]], Awaitable[list[float]]]


async def met_habits(habits: list[Habit], scan_type: str, findings: str,
                     ask: Optional[Ask] = None) -> tuple[list[Habit], Optional[str]]:
    """(the habits whose condition the dictation meets, error). A score below TRIGGER_MIN is not met, however close
    (Hassan H2). Never raises: a failed call meets nothing."""
    if not habits or not (findings or "").strip():
        return [], None
    conds = list(dict.fromkeys(h.condition for h in habits))
    try:
        scores = await (ask or ask_triggers)(scan_type, findings, conds)
        if len(scores) != len(conds):
            raise ValueError("jev: answer count mismatch")
    except Exception as e:  # noqa: BLE001 -- fail-soft: no template rows, generic rows as today
        err = f"{type(e).__name__}: {e}"[:200]
        logger.warning("[stack.habits] trigger failed: %s", err)
        return [], err
    met = {c for c, s in zip(conds, scores) if s >= TRIGGER_MIN}
    logger.info("[stack.habits] conditions=%d met=%d", len(conds), len(met))
    return [h for h in habits if h.condition in met], None
