"""Lab copy of the review-engine adjudicator (spec §7) and verifier (spec §8).

Flat schema on purpose (L-50). One Qwen call per candidate group. The verifier checks the FIX, never the reading.

The shared runner (_run_agent_with_model) uses pydantic-ai retries=2, so a validation failure can cost up to
3 calls; usage.requests records it (lab deviation from spec §7, fixed in Plan 2)."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel

from rapid_reports_ai.report_review import CONTRA_FLAG, Q_CONTRA, _restates
from rapid_reports_ai.scripts.jev_tool_lab import calls
from rapid_reports_ai.scripts.review_labs import common

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
    lines = [f"- Flag kind \"{c.get('kind')}\" (from the {c.get('lane')} check, detector {c.get('detector')}). "
             f"{_KIND_TEXT.get(c.get('kind'), '')}"]
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
        if ev.get(k) not in (None, ""):          # grade 0 is a real grade
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


def _remove_span(report: str, i: int, n: int) -> str:
    """Splice out [i, i+n) and tidy only the seam; the rest of the report is never touched."""
    a, b = report[:i], report[i + n:]
    at, bt = a.rstrip(" \t"), b.lstrip(" \t")
    if not at or at.endswith("\n"):            # seam at a line start
        a, b = at, bt
        if b.startswith("\n"):                 # the line is now empty: drop it
            b = b[1:]
        elif not b and a.endswith("\n"):
            a = a[:-1]
    elif not bt or bt.startswith("\n"):        # seam at a line end
        a, b = at, bt
    elif a != at and b != bt:                  # spaces on both sides: one space at the seam
        a, b = at + " ", bt
    return a + b


def _mid_word(report: str, i: int) -> bool:
    """True when position i splits a word (alphanumerics on both sides)."""
    return 0 < i < len(report) and report[i - 1].isalnum() and report[i].isalnum()


def apply_edit(report: str, j: Judgement) -> Optional[str]:
    m = j.edit_mode
    if m in ("replace", "upgrade") and _once(report, j.edit_find) and j.edit_replace is not None:
        return report.replace(j.edit_find, j.edit_replace, 1)
    if m == "remove" and _once(report, j.edit_find):
        i, n = report.index(j.edit_find), len(j.edit_find)
        if _mid_word(report, i) or _mid_word(report, i + n):
            return None                         # find starts or ends mid-word
        return _remove_span(report, i, n)
    anchor = (j.edit_after or "").strip()
    new = (j.edit_replace or "").strip()
    if m == "insert" and _once(report, anchor) and new:
        i = report.index(anchor) + len(anchor)
        if i < len(report) and not report[i].isspace():
            return None                         # anchor ends mid-word
        if common._HEADING.fullmatch(anchor):
            return report[:i] + "\n" + new + report[i:]
        return report[:i] + " " + new + report[i:]
    return None


def _edit_pos(report: str, j: Judgement) -> Optional[int]:
    """Where the edit lands in the original report (start of find, or end of the insert anchor)."""
    if j.edit_mode == "insert":
        anchor = (j.edit_after or "").strip()
        return report.index(anchor) + len(anchor) if anchor and anchor in report else None
    return report.index(j.edit_find) if j.edit_find and j.edit_find in report else None


_BLOCK_BREAK = re.compile(r"\n[ \t]*\n|" + common._HEADING.pattern, re.M)


def _paragraph(report: str, pos: int) -> Tuple[int, int]:
    """The text between blank lines / headings that contains `pos`."""
    lo, hi = 0, len(report)
    for m in _BLOCK_BREAK.finditer(report):
        if m.end() <= pos:
            lo = m.end()
        elif m.start() > pos:
            hi = m.start()
            break
    return lo, hi


_NUM = re.compile(r"\d+(?:\.\d+)?")
_SIDE = re.compile(r"\b(left|right|bilateral)\b", re.I)
_NEG = re.compile(r"\b(no|not|without|absent|negative for)\b", re.I)
_NEGATOR = re.compile(r"\b(no|not|without)\b", re.I)
_NEG_SKIP = {"a", "an", "the", "any", "evidence", "of", "is", "are", "was", "were", "seen", "identified"}
_VERB = {"is", "are", "was", "were", "seen", "identified", "noted", "demonstrated"}
_LIST_SEP = re.compile(r",|\b(?:or|and|nor)\b", re.I)
_SENT_STOP = re.compile(r"[.;!?\n]")
_CLAUSE_BREAK = {"but", "however", "although", "though", "with", "which", "while", "whereas", "except"}
_POST_NEG = {"not", "absent", "negative"}


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z]+", text.lower())


def _negated_phrases(text: str) -> List[List[str]]:
    """Each listed item after a negator (no / not / without), up to the sentence end: its first 2 content words.
    Items split on ',', 'or', 'and', 'nor'; the list ends after an item carrying a verb ("... is seen")."""
    out = []
    for m in _NEGATOR.finditer(text):
        rest = text[m.end():]
        stop = _SENT_STOP.search(rest)
        for item in _LIST_SEP.split(rest[:stop.start()] if stop else rest):
            ws = _words(item)
            words = [w for w in ws if w not in _NEG_SKIP][:2]
            if words:
                out.append(words)
            if _VERB & set(ws):
                break
    return out


def _is_negated(new: str, a: int, b: int) -> bool:
    """The phrase at [a, b) of `new` is negated within its own sentence: a negator governs the list it sits in,
    or not / absent / negative follows within 4 words."""
    starts = [m.end() for m in _SENT_STOP.finditer(new, 0, a)]
    before = new[starts[-1] if starts else 0:a]
    negs = list(_NEGATOR.finditer(before))
    if negs and not (_CLAUSE_BREAK & set(_words(before[negs[-1].end():]))):
        return True
    stop = _SENT_STOP.search(new, b)
    after = _words(new[b:stop.start() if stop else len(new)])[:4]
    return bool(_POST_NEG & set(after))


def _loses_negation(old: str, new: str) -> bool:
    for words in _negated_phrases(old):
        for m in re.finditer(r"\b" + r"\W+".join(map(re.escape, words)) + r"\b", new, re.I):
            if not _is_negated(new, m.start(), m.end()):
                return True
    return False


def _sides(text: str) -> set:
    return {s.lower() for s in _SIDE.findall(text)}


def _side_grounded(side: str, source: str) -> bool:
    src = _sides(source)
    if side == "bilateral":
        return "bilateral" in src or bool(re.search(r"\bboth\b", source, re.I)) or {"left", "right"} <= src
    return side in src


def guard_failures(report: str, j: Judgement, dictation: str, history: str, extra_source: str = "") -> List[str]:
    """Spec §8 code guards. An empty list means the fix may be shown with Apply.
    `extra_source` (additions lane: the guideline evidence) also grounds numbers and sides."""
    if j.edit_mode == "none":
        return []
    fails = []
    if apply_edit(report, j) is None:
        fails.append("anchor_not_unique")
    source = f"{dictation}\n{history}\n{extra_source}"
    new, old = j.edit_replace or "", j.edit_find or ""
    if set(_NUM.findall(new)) - set(_NUM.findall(old)) - set(_NUM.findall(source)):
        fails.append("ungrounded_number")
    if any(not _side_grounded(s, source) for s in _sides(new) - _sides(old)):
        fails.append("ungrounded_side")
    if j.edit_mode in ("replace", "upgrade") and (
            len(_NEG.findall(old)) > len(_NEG.findall(new)) or _loses_negation(old, new)):
        fails.append("drops_negation")
    if j.edit_mode == "remove" and j.kind != "contradicted":
        fails.append("remove_not_allowed")
    pos = _edit_pos(report, j)
    if pos is not None and j.edit_section:
        sec = common.section_of(report, pos)
        if sec != "Report" and sec.lower() != j.edit_section.strip().rstrip(":").strip().lower():
            fails.append("outside_section")
    if pos is not None and j.edit_mode in ("insert", "upgrade", "replace") and new.strip():
        lo, hi = _paragraph(report, pos)
        para = report[lo:hi]
        own = pos - lo                         # a replace is checked against its neighbours, not its own sentences
        own_end = own + max(len(old), 1)
        neighbours = [para[a:b] for a, b in common.sentences(para)
                      if j.edit_mode == "insert" or not (a < own_end and own < b)]
        if any(_restates(new, s) for s in neighbours):
            fails.append("duplicate")
    return fails


def changed_sentence(report: str, after: str, j: Judgement) -> str:
    """Every sentence of `after` overlapping the new text, located by position (never by text search)."""
    pos = _edit_pos(report, j)
    if pos is None:
        return (j.edit_replace or "").strip()
    if j.edit_mode == "insert":
        pos += 1
        n = len((j.edit_replace or "").strip())
    else:
        n = len(j.edit_replace or "")
    end = pos + max(n, 1)
    hit = [after[a:b].strip() for a, b in common.sentences(after) if a < end and pos < b]
    return " ".join(hit) if hit else (j.edit_replace or "").strip()


_EVIDENCE_KEYS = ("threshold", "timing", "grade", "criteria", "parameter", "system", "text")


def _extra_source(group: Optional[List[dict]]) -> str:
    if not group or not any(c.get("lane") == "additions" for c in group):
        return ""
    return "\n".join(str(ev[k]) for c in group for ev in [c.get("evidence") or {}] for k in _EVIDENCE_KEYS
                     if ev.get(k) not in (None, ""))


async def verify(case: dict, j: Judgement, group: Optional[List[dict]] = None, jev_fn=calls.jev) -> Dict:
    """Code guards, then one batched Jev call: the probe on the edited report, contradiction on the changed text."""
    fails = guard_failures(case["report"], j, case.get("dictation", ""), case.get("history", ""), _extra_source(group))
    res = {"code": not fails, "failed": fails, "addressed": None, "contra": None, "unconfirmed": False}
    if fails or j.edit_mode == "none":
        return res
    after = apply_edit(case["report"], j)
    by_state: Dict[str, dict] = {}
    if j.edit_mode != "remove":
        by_state[f"SCAN TYPE: {case.get('scan', '')}\nDICTATED FINDINGS:\n{case.get('dictation', '')}"] = \
            {"contra": {"type": "noul", "instructions": Q_CONTRA + changed_sentence(case["report"], after, j)}}
    if j.probe:
        by_state[f"REPORT:\n{after}"] = {"addressed": {"type": "noul", "instructions": j.probe}}
    else:
        res["unconfirmed"] = True               # nothing checks that the fix addresses the item
    if not by_state:
        return res
    try:
        answers, _, _ = await jev_fn(by_state)
        if j.edit_mode != "remove":            # asked: a missing answer is a Jev error, like "addressed"
            res["contra"] = float(answers["contra"]["noul"])
        if j.probe:
            res["addressed"] = float(answers["addressed"]["noul"])
            if res["addressed"] < UNSURE_LO:
                res["code"] = False
                res["failed"].append("not_addressed")
            else:
                res["unconfirmed"] = res["addressed"] < ADDRESSED_OK
    except Exception as e:   # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        res["code"] = False
        res["failed"].append("jev_error")
    if res["contra"] is not None and res["contra"] >= CONTRA_FLAG:
        res["code"] = False
        res["failed"].append("fix_contradicts_dictation")
    return res


async def judge_and_verify(case: dict, group: List[dict], sem: asyncio.Semaphore, system: Optional[str] = None) -> dict:
    async with sem:
        j, usage, err = await adjudicate(case, group, system)
    if j is None:
        fallback = Judgement(cls="minor", kind=(group[0].get("kind") if group else None) or "unknown",
                             label="", reason="", edit_mode="none").model_dump()
        kind = "validation" if any(t in (err or "").split(":")[0] for t in ("Validation", "UnexpectedModelBehavior")) \
            else "transport"
        return {**fallback, "error": err, "error_kind": kind, "usage": usage, "verified": None}
    v = await verify(case, j, group)
    return {**j.model_dump(), "usage": usage, "verified": v, "error": None}


__all__ = ["Judgement", "prompt", "render_candidate", "user_message", "adjudicate", "apply_edit",
           "guard_failures", "changed_sentence", "verify", "judge_and_verify"]
