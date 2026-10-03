"""Lab copy of the review-engine adjudicator (spec §7) and verifier (spec §8).

Flat schema on purpose (L-50). One Qwen call per candidate group. The verifier checks the FIX, never the reading."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel

from rapid_reports_ai.report_reconcile import Q_CONVEYS
from rapid_reports_ai.report_review import CONTRA_FLAG, Q_CONTRA
from rapid_reports_ai.scripts.jev_tool_lab import calls

PROMPTS = Path(__file__).parent / "prompts"
ADDRESSED_OK = 0.8          # spec §8; confirmed or re-set in Gate E
UNSURE_LO = 0.5             # §6.5: 0.5–0.8 = unsure → "unconfirmed"


class Judgement(BaseModel):
    cls: Literal["action", "minor", "info", "suppress"]
    kind: str
    label: str
    reason: str
    edit_mode: Literal["none", "replace", "insert", "upgrade", "remove"]
    edit_find: Optional[str] = None
    edit_replace: Optional[str] = None
    edit_after: Optional[str] = None
    edit_section: Optional[str] = None
    probe: Optional[str] = None


def prompt(name: str = "adjudicator_v4") -> str:
    return (PROMPTS / f"{name}.txt").read_text().strip()


_KIND_TEXT = {
    "partial": "The report seems to cover this dictated line but leave out part of it.",
    "absent": "The report seems not to cover this dictated line at all.",
    "differs": "The report seems to say something different from this dictated line.",
    "laterality": "A side in this dictated line seems missing from the report.",
    "contradicted": "The dictation seems to contradict this report statement.",
    "unsupported": "This report statement seems not to be supported by the dictation or history.",
    "overstated": "This report statement seems more certain than the dictation.",
    "misattributed": "A measurement seems attached to a different structure than dictated.",
    "inconsistent": "This report statement seems internally inconsistent (modality wording or size word).",
    "grade": "A guideline classification may be assignable for this finding.",
    "characterise": "A guideline classification may need an input that is not described.",
    "threshold": "A guideline threshold may apply to this finding.",
    "follow_up": "The guideline may change the existing recommendation.",
    "option": "A guideline point the radiologist may want to add.",
}


def render_candidate(c: dict) -> str:
    """One candidate as prompt text. An unsure Jev answer is named, never its leaning (§6.5)."""
    lines = [f"- [{c.get('lane')}/{c.get('kind')}, detector {c.get('detector')}] {_KIND_TEXT.get(c.get('kind'), '')}"]
    if c.get("line"):
        lines.append(f'  Dictated line: "{c["line"]}"')
    if c.get("anchor"):
        lines.append(f'  Report statement: "{c["anchor"]}"')
    ev = c.get("evidence") or {}
    if ev.get("jev_unsure"):
        lines.append(f"  The detector question {ev['jev_unsure'].get('question')} was unsure here; read it fresh.")
    if ev.get("missing_detail"):
        lines.append(f"  Possibly missing detail: {ev['missing_detail']}")
    for k in ("system", "grade", "parameter", "threshold", "significance", "modality", "timing", "indication", "text"):
        if ev.get(k):
            lines.append(f"  {k}: {ev[k]}")
    if ev.get("criteria"):
        lines.append(f"  Criteria text for this system: {ev['criteria']}")
    return "\n".join(lines)


def user_message(case: dict, group: List[dict]) -> str:
    return ("FLAGS (one group, same place in the report):\n" + "\n".join(render_candidate(c) for c in group) +
            f"\n\nSTUDY TITLE: {case.get('scan', '')}\n\nCLINICAL HISTORY:\n{case.get('history') or '(none)'}"
            f"\n\nDICTATION:\n{case.get('dictation', '')}\n\nREPORT:\n{case.get('report', '')}")


async def adjudicate(case: dict, group: List[dict], system: Optional[str] = None,
                     qwen_fn=calls.qwen) -> Tuple[Optional[Judgement], dict, Optional[str]]:
    """One Qwen reasoning call. A validation failure returns (None, usage, error); the caller logs it as minor/no fix."""
    try:
        out, usage = await qwen_fn(Judgement, system or prompt(), user_message(case, group), True)
        return out, usage.model_dump(), None
    except Exception as e:   # noqa: BLE001 — lab: record and move on (retries at T=0 are futile, L-50)
        return None, {}, f"{type(e).__name__}: {str(e)[:300]}"


def _once(text: str, needle: Optional[str]) -> bool:
    return bool(needle) and text.count(needle) == 1


def apply_edit(report: str, j: Judgement) -> Optional[str]:
    m = j.edit_mode
    if m in ("replace", "upgrade") and _once(report, j.edit_find) and j.edit_replace is not None:
        return report.replace(j.edit_find, j.edit_replace, 1)
    if m == "remove" and _once(report, j.edit_find):
        return re.sub(r"[ \t]{2,}", " ", report.replace(j.edit_find, "", 1))
    if m == "insert" and _once(report, j.edit_after) and j.edit_replace:
        i = report.index(j.edit_after) + len(j.edit_after)
        return report[:i] + " " + j.edit_replace.strip() + report[i:]
    return None


_NUM = re.compile(r"\d+(?:\.\d+)?")
_SIDE = re.compile(r"\b(left|right|bilateral)\b", re.I)
_NEG = re.compile(r"\b(no|not|without|absent|negative for)\b", re.I)


def guard_failures(report: str, j: Judgement, dictation: str, history: str) -> List[str]:
    """Spec §8 code guards. An empty list means the fix may be shown with Apply."""
    if j.edit_mode == "none":
        return []
    fails = []
    if apply_edit(report, j) is None:
        fails.append("anchor_not_unique")
    source = f"{dictation}\n{history}"
    new, old = j.edit_replace or "", j.edit_find or ""
    if set(_NUM.findall(new)) - set(_NUM.findall(old)) - set(_NUM.findall(source)):
        fails.append("ungrounded_number")
    added_sides = {s.lower() for s in _SIDE.findall(new)} - {s.lower() for s in _SIDE.findall(old)}
    if added_sides - {s.lower() for s in _SIDE.findall(source)}:
        fails.append("ungrounded_side")
    if j.edit_mode in ("replace", "upgrade") and len(_NEG.findall(old)) > len(_NEG.findall(new)):
        fails.append("drops_negation")
    if j.edit_mode == "remove" and j.kind != "contradicted":
        fails.append("remove_not_allowed")
    return fails


def changed_sentence(after: str, j: Judgement) -> str:
    key = (j.edit_replace or "").strip() or (j.edit_after or "")
    for s in re.split(r"(?<=[.;])\s+|\n+", after):
        if key and key[:40] in s:
            return s.strip()
    return key


async def verify(case: dict, j: Judgement, jev_fn=calls.jev) -> Dict:
    """Code guards, then one batched Jev call: the probe on the edited report, contradiction on the changed text."""
    fails = guard_failures(case["report"], j, case.get("dictation", ""), case.get("history", ""))
    res = {"code": not fails, "failed": fails, "addressed": None, "contra": None, "unconfirmed": False}
    if fails or j.edit_mode == "none":
        return res
    after = apply_edit(case["report"], j)
    by_state = {f"SCAN TYPE: {case.get('scan', '')}\nDICTATED FINDINGS:\n{case.get('dictation', '')}":
                    {"contra": {"type": "noul", "instructions": Q_CONTRA + changed_sentence(after, j)}}}
    if j.probe:
        by_state[f"REPORT:\n{after}"] = {"addressed": {"type": "noul", "instructions": j.probe}}
    try:
        answers, _, _ = await jev_fn(by_state)
        res["contra"] = float(answers["contra"]["noul"])
        if j.probe:
            res["addressed"] = float(answers["addressed"]["noul"])
            res["unconfirmed"] = UNSURE_LO <= res["addressed"] < ADDRESSED_OK
    except Exception as e:   # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    if res["contra"] is not None and res["contra"] >= CONTRA_FLAG:
        res["code"] = False
        res["failed"].append("fix_contradicts_dictation")
    return res


async def judge_and_verify(case: dict, group: List[dict], sem: asyncio.Semaphore, system: Optional[str] = None) -> dict:
    async with sem:
        j, usage, err = await adjudicate(case, group, system)
    if j is None:
        return {"cls": "minor", "kind": group[0].get("kind"), "label": "", "edit_mode": "none", "error": err,
                "usage": usage, "verified": None}
    v = await verify(case, j)
    return {**j.model_dump(), "usage": usage, "verified": v, "error": None}


__all__ = ["Judgement", "prompt", "render_candidate", "user_message", "adjudicate", "apply_edit",
           "guard_failures", "verify", "judge_and_verify", "Q_CONVEYS"]
