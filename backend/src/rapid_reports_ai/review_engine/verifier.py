"""Verifier (spec §8): code guards, then one Jev batch on each fix's post-edit text. It checks the FIX, never the
reading. A failed check removes the edit and keeps the item's class; an unsure `addressed` keeps the fix and marks
it unconfirmed (§6.5). Also the live probe loop's one-shot check (spec §12.4).

Ported from the lab (`scripts/review_labs/judgement.py`: `apply_edit`, `_remove_span`, `_mid_word`, `guard_failures`,
`_loses_negation`, `changed_sentence`, `_paragraph`, `_extra_source`, `verify`) with its tests, types adapted to
`Edit` / `ReviewItem`. Engine additions (spec §9, decided 2026-10-04):
- a removal is allowed only for kind `contradicted` (or the Task 14 negatives kind `removed`), and never removes
  text the radiologist dictated;
- an insert with no `after` appends to the end of `edit.section` (the `Edit` contract);
- headings are the lab's ALL-CAPS "NAME:" lines plus any line naming one of the report's sections.
The "conveys" veto (`Q_CONVEYS`) is deliberately absent (spec §7)."""
from __future__ import annotations

import asyncio
import re
from typing import Dict, Iterable, List, Optional, Tuple

from .. import report_reconcile as rc
from ..report_review import CONTRA_FLAG, JEV_TIMEOUT_S, Q_CONTRA, _drop_item, _restates, is_negative
from .alignment import align
from .items import Candidate, Edit, ReviewInput, ReviewItem, Span

ADDRESSED_OK = 0.8           # provisional: Gate E (spec §8)
UNSURE_LO = 0.5              # provisional: Gate E (§6.5: 0.5–0.8 is the unsure band → "unconfirmed")
REMOVAL_KINDS = frozenset({"contradicted", "removed"})   # spec §9: removal only for these, never dictated text

# ── headings, sentences, paragraphs ─────────────────────────────────────────
_HEADING = re.compile(r"^([A-Z][A-Z /&()-]{2,}):\s*$")   # lab common._HEADING (per line)
_SENT_END = re.compile(r"(?<=[.;])\s+(?=[A-Z])|\n+")       # lab common.SENT_END


def _norm_name(s: str) -> str:
    return s.strip().rstrip(":").strip().lower()


def _is_heading(line: str, names: Iterable[str] = ()) -> bool:
    s = line.strip()
    if not s:
        return False
    return bool(_HEADING.fullmatch(s)) or _norm_name(s) in {_norm_name(n) for n in names if n}


def _headings(report: str, names: Iterable[str] = ()) -> List[Tuple[str, int, int]]:
    """(name, line start, line end without the newline) for each heading line."""
    names = list(names or [])
    out, i = [], 0
    for line in report.split("\n"):
        if _is_heading(line, names):
            out.append((_norm_name(line), i, i + len(line)))
        i += len(line) + 1
    return out


def _section_of(report: str, pos: int, names: Iterable[str] = ()) -> Optional[str]:
    """The (normalised) heading governing `pos`; None when no heading precedes it."""
    hs = [h for h in _headings(report, names) if h[1] <= pos]
    return hs[-1][0] if hs else None


def _section_body(report: str, name: Optional[str], names: Iterable[str] = ()) -> Optional[Tuple[int, int]]:
    """(heading line end, next heading start or report end) for the first heading called `name`."""
    if not name:
        return None
    hs = _headings(report, names)
    for k, (n, _, end) in enumerate(hs):
        if n == _norm_name(name):
            return end, (hs[k + 1][1] if k + 1 < len(hs) else len(report))
    return None


def _sentences(text: str, names: Iterable[str] = ()) -> List[Tuple[int, int]]:
    out, s = [], 0
    for m in _SENT_END.finditer(text):
        out.append((s, m.start()))
        s = m.end()
    out.append((s, len(text)))
    return [(a, b) for a, b in out if text[a:b].strip() and not _is_heading(text[a:b], names)]


_BLANK = re.compile(r"\n[ \t]*\n")


def _paragraph(report: str, pos: int, names: Iterable[str] = ()) -> Tuple[int, int]:
    """The text between blank lines / headings that contains `pos`."""
    breaks = sorted([(m.start(), m.end()) for m in _BLANK.finditer(report)] +
                    [(a, min(b + 1, len(report))) for _, a, b in _headings(report, names)])
    lo, hi = 0, len(report)
    for a, b in breaks:
        if b <= pos:
            lo = max(lo, b)
        elif a > pos:
            hi = a
            break
    return lo, hi


# ── apply ───────────────────────────────────────────────────────────────────
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


def _append_point(report: str, edit: Edit, names: Iterable[str]) -> Optional[Tuple[int, str]]:
    """Insert with no `after`: (position, separator) at the end of `edit.section`'s body."""
    b = _section_body(report, edit.section, names)
    if b is None:
        return None
    a, e = b
    body = report[a:e].rstrip()
    return (a, "\n") if not body.strip() else (a + len(body), " ")


def apply_edit(report: str, edit: Optional[Edit], sections: Optional[List[str]] = None) -> Optional[str]:
    """The report with `edit` applied, or None when it cannot be placed exactly once."""
    if edit is None:
        return None
    m = edit.mode
    if m in ("replace", "upgrade") and _once(report, edit.find) and edit.replace is not None:
        return report.replace(edit.find, edit.replace, 1)
    if m == "remove" and _once(report, edit.find):
        i, n = report.index(edit.find), len(edit.find)
        if _mid_word(report, i) or _mid_word(report, i + n):
            return None                         # find starts or ends mid-word
        return _remove_span(report, i, n)
    new = (edit.replace or "").strip()
    if m != "insert" or not new:
        return None
    anchor = (edit.after or "").strip()
    if anchor:
        if not _once(report, anchor):
            return None
        i = report.index(anchor) + len(anchor)
        if i < len(report) and not report[i].isspace():
            return None                         # anchor ends mid-word
        if _is_heading(anchor, sections or []):
            return report[:i] + "\n" + new + report[i:]
        return report[:i] + " " + new + report[i:]
    if edit.after is not None:                  # a blank anchor is not "append to the section"
        return None
    pt = _append_point(report, edit, sections or [])
    if pt is None:
        return None
    pos, sep = pt
    return report[:pos] + sep + new + report[pos:]


def _edit_pos(report: str, edit: Edit, names: Iterable[str] = ()) -> Optional[int]:
    """Where the edit lands in the original report (start of find, or the insert point; the new text starts one
    separator later)."""
    if edit.mode == "insert":
        anchor = (edit.after or "").strip()
        if anchor:
            return report.index(anchor) + len(anchor) if anchor in report else None
        pt = _append_point(report, edit, names)
        return pt[0] if pt else None
    return report.index(edit.find) if edit.find and edit.find in report else None


# ── guards ──────────────────────────────────────────────────────────────────
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


def _drops_negative_item(old: str, new: str) -> bool:
    """A negated item of `old` is absent from `new`, reworded or negated. Kept when its 2 content words or its
    head noun (last content word) still appear negated in `new`."""
    def negated(words: List[str]) -> bool:
        pat = r"\b" + r"\W+".join(map(re.escape, words)) + r"\b"
        return any(_is_negated(new, m.start(), m.end()) for m in re.finditer(pat, new, re.I))
    return any(not (negated(words) or negated(words[-1:])) for words in _negated_phrases(old))


def _sides(text: str) -> set:
    return {s.lower() for s in _SIDE.findall(text)}


def _side_grounded(side: str, source: str) -> bool:
    src = _sides(source)
    if side == "bilateral":
        return "bilateral" in src or bool(re.search(r"\bboth\b", source, re.I)) or {"left", "right"} <= src
    return side in src


_MANAGEMENT = re.compile(r"\b(?:treat|therapy|conservative|physio|surgery|surgical|refer to (?!radiology)|prescrib|"
                         r"commence|anticoagul|antibiotic)", re.I)
_ADD_STOP = {"with", "this", "that", "these", "those", "there", "which", "from", "into", "also", "than", "then",
             "within", "after", "would", "should", "could", "further", "recommend", "recommended", "suggest",
             "suggested", "consider", "imaging", "follow", "interval", "months", "weeks", "week", "month", "year",
             "years", "days", "urgent", "urgently", "discussed", "communicated", "referrer", "clinical", "grade",
             "category", "classification", "appearances", "appearance", "finding", "findings"}


def _additions_failures(old: str, new: str, source: str) -> List[str]:
    """Additions lane (guideline-derived): a fix may only upgrade the recommendation or add the grade. It never adds
    a negative, a descriptor or a finding (content words grounded nowhere), or management."""
    fails = []
    old_neg = {tuple(p) for p in _negated_phrases(old)}
    grounded = set(_words(f"{old}\n{source}"))
    if any(tuple(p) not in old_neg for p in _negated_phrases(new)) or any(
            len(w) >= 4 and w not in _ADD_STOP and w not in grounded for w in _words(new)):
        fails.append("additions_new_content")
    if {m.lower() for m in _MANAGEMENT.findall(new)} - {m.lower() for m in _MANAGEMENT.findall(old)}:
        fails.append("management")
    return fails


_MARKER = re.compile(r"^\s*(?:\d{1,2}[.)]|[-*•])\s+")


def _dictated_text(text: str, dictation: str) -> bool:
    """`text` restates a dictated line with the same polarity: the radiologist said it, so it is never removed
    (spec §9; PR #6). Polarity matters: a generated "No X." beside a dictated "X" is not dictated text."""
    t = (text or "").strip()
    if not t:
        return False
    neg = bool(_NEG.search(t))
    for raw in (dictation or "").split("\n"):
        line = _MARKER.sub("", raw).strip()
        for a, b in _sentences(line) or [(0, len(line))]:
            s = line[a:b]
            if s.strip() and bool(_NEG.search(s)) == neg and _restates(t, s):
                return True
    return False


def _removes_dictated(edit: Edit, old: str, new: str, loses: bool, dictation: str) -> bool:
    """A removal (or a line-level replace that drops a negative-list item or a negation) takes out dictated text."""
    if edit.mode == "remove":
        return _dictated_text(old, dictation)
    if edit.mode not in ("replace", "upgrade"):
        return False
    kept = {tuple(p) for p in _negated_phrases(new)}
    dropped = [p for p in _negated_phrases(old) if tuple(p) not in kept]
    if loses and _dictated_text(old, dictation):
        return True
    return any(_dictated_text("No " + " ".join(p), dictation) for p in dropped)


def guard_failures(report: str, edit: Optional[Edit], kind: str, dictation: str, history: str,
                   extra_source: str = "", additions: bool = False, sections: Optional[List[str]] = None,
                   item_section: Optional[str] = None) -> List[str]:
    """Spec §8 code guards. An empty list means the fix may be shown with Apply.
    `extra_source` (additions lane: the candidate's guideline evidence) also grounds numbers and sides.
    `additions`: the item comes from the additions lane, so new content and management are refused.
    `item_section` is used for the section check when the edit names none."""
    if edit is None:
        return []
    names = sections or []
    fails = []
    if apply_edit(report, edit, names) is None:
        fails.append("anchor_not_unique")
    source = f"{dictation}\n{history}\n{extra_source}"
    new, old = edit.replace or "", edit.find or ""
    if set(_NUM.findall(new)) - set(_NUM.findall(old)) - set(_NUM.findall(source)):
        fails.append("ungrounded_number")
    if any(not _side_grounded(s, source) for s in _sides(new) - _sides(old)):
        fails.append("ungrounded_side")
    loses = edit.mode in ("replace", "upgrade") and (
        len(_NEG.findall(old)) > len(_NEG.findall(new)) or _loses_negation(old, new))
    # L-47: an edit never drops a negation, except the sanctioned removal of a contradicted negative (a
    # negative-list item dropped from its line arrives as a line-level replace).
    if loses and kind not in REMOVAL_KINDS:
        fails.append("drops_negation")
    if edit.mode in ("replace", "upgrade") and kind not in REMOVAL_KINDS and _drops_negative_item(old, new):
        fails.append("drops_negative_item")
    if edit.mode == "remove" and kind not in REMOVAL_KINDS:
        fails.append("remove_not_allowed")
    if kind in REMOVAL_KINDS and _removes_dictated(edit, old, new, loses, dictation):
        fails.append("remove_dictated")
    if additions and edit.mode in ("insert", "replace", "upgrade"):
        fails += _additions_failures(old, new, source)
    pos = _edit_pos(report, edit, names)
    want = edit.section or item_section
    if pos is not None and want:
        sec = _section_of(report, pos, names)
        if sec is not None and sec != _norm_name(want):
            fails.append("outside_section")
    if pos is not None and edit.mode in ("insert", "upgrade", "replace") and new.strip():
        lo, hi = _paragraph(report, pos, names)
        para = report[lo:hi]
        own = pos - lo                         # a replace is checked against its neighbours, not its own sentences
        own_end = own + max(len(old), 1)
        neighbours = [para[a:b] for a, b in _sentences(para, names)
                      if edit.mode == "insert" or not (a < own_end and own < b)]
        if any(_restates(new, s) for s in neighbours):
            fails.append("duplicate")
    return fails


def changed_sentence(report: str, after: str, edit: Edit, sections: Optional[List[str]] = None) -> str:
    """Every sentence of `after` overlapping the new text, located by position (never by text search)."""
    names = sections or []
    pos = _edit_pos(report, edit, names)
    if pos is None:
        return (edit.replace or "").strip()
    if edit.mode == "insert":
        pos += 1
        n = len((edit.replace or "").strip())
    else:
        n = len(edit.replace or "")
    end = pos + max(n, 1)
    hit = [after[a:b].strip() for a, b in _sentences(after, names) if a < end and pos < b]
    return " ".join(hit) if hit else (edit.replace or "").strip()


_EVIDENCE_KEYS = ("threshold", "timing", "grade", "criteria", "parameter", "system", "modality", "text")


def _is_additions(item: ReviewItem, group: Optional[List[Candidate]] = None) -> bool:
    if group:
        return any(c.lane == "additions" for c in group)
    return item.lane == "additions"


def _extra_source(item: ReviewItem, group: Optional[List[Candidate]] = None) -> str:
    """Additions lane only: the candidate's evidence values ground numbers and sides (spec §9, 2026-10-04)."""
    if not _is_additions(item, group):
        return ""
    evs = [c.evidence or {} for c in group] if group else [item.evidence or {}]
    return "\n".join(str(ev[k]) for ev in evs for k in _EVIDENCE_KEYS if ev.get(k) not in (None, ""))


# ── Jev ─────────────────────────────────────────────────────────────────────
async def _ask(state: str, qs: dict) -> dict:
    return await asyncio.wait_for(rc._jev(state, qs), JEV_TIMEOUT_S) if qs else {}


def _dict_state(inp: ReviewInput) -> str:
    return f"SCAN TYPE: {inp.scan_type}\nDICTATED FINDINGS:\n{inp.artifacts.dictated_findings}"


def _f(ans, k) -> Optional[float]:
    try:
        return float(ans[k]["noul"])
    except Exception:  # noqa: BLE001 - a missing or unreadable answer
        return None


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {str(e)[:200]}"


async def verify(inp: ReviewInput, items: List[ReviewItem], report: Optional[str] = None,
                 groups: Optional[Dict[str, List[Candidate]]] = None) -> None:
    """Sets item.verified = {code, failed, addressed, contra, unconfirmed[, error]} on every item with an edit and
    removes the edit when `code` is False. `groups` (item id → its candidate group) supplies the additions lane's
    evidence; without it the item's own lane and evidence are used.

    One Jev batch: every contradiction question in one dictation-state call, each probe on its own post-edit state,
    all concurrent. Failure rules (binding correction 3): addressed < 0.5 fails (`not_addressed`); a Jev exception
    or a missing answer fails (`jev_error`); no probe → unconfirmed; 0.5 ≤ addressed < 0.8 → kept, unconfirmed.
    A removal is not contradiction-checked (nothing is left to contradict)."""
    report = inp.artifacts.report if report is None else report
    names = inp.artifacts.sections
    todo: List[Tuple[ReviewItem, str]] = []
    for it in items:
        if it.edit is None:
            continue
        group = (groups or {}).get(it.id)
        fails = guard_failures(report, it.edit, it.kind, inp.artifacts.dictated_findings, inp.clinical_history,
                               _extra_source(it, group), _is_additions(it, group), names, it.section)
        it.verified = {"code": not fails, "failed": fails, "addressed": None, "contra": None, "unconfirmed": False}
        if fails:
            it.edit = None
        else:
            todo.append((it, apply_edit(report, it.edit, names)))
    if not todo:
        return
    contra_qs = {f"x{k}": {"type": "noul", "instructions": Q_CONTRA + changed_sentence(report, after, it.edit, names)}
                 for k, (it, after) in enumerate(todo) if it.edit.mode != "remove"}
    probed = [k for k, (it, _) in enumerate(todo) if it.probe]
    results = await asyncio.gather(
        _ask(_dict_state(inp), contra_qs),
        *[_ask(f"REPORT:\n{todo[k][1]}", {"addressed": {"type": "noul", "instructions": todo[k][0].probe}})
          for k in probed], return_exceptions=True)
    contra_ans, probe_ans = results[0], dict(zip(probed, results[1:]))
    for k, (it, _) in enumerate(todo):
        v = it.verified
        errors = []
        if f"x{k}" in contra_qs:
            if isinstance(contra_ans, BaseException):
                errors.append(_err(contra_ans))
            else:
                v["contra"] = _f(contra_ans, f"x{k}")
                if v["contra"] is None:
                    errors.append("contra: missing answer")
        if it.probe:
            ans = probe_ans[k]
            if isinstance(ans, BaseException):
                errors.append(_err(ans))
            else:
                v["addressed"] = _f(ans, "addressed")
                if v["addressed"] is None:
                    errors.append("addressed: missing answer")
                elif v["addressed"] < UNSURE_LO:
                    v["failed"].append("not_addressed")
                else:
                    v["unconfirmed"] = v["addressed"] < ADDRESSED_OK
        else:
            v["unconfirmed"] = True            # nothing checks that the fix addresses the item
        if errors:
            v["error"] = "; ".join(errors)
            v["failed"].append("jev_error")
        if v["contra"] is not None and v["contra"] >= CONTRA_FLAG:
            v["failed"].append("fix_contradicts_dictation")
        if v["failed"]:
            v["code"] = False
            it.edit = None


# ── live probe loop (spec §12.4) ────────────────────────────────────────────
def _negative_fix(text: str, start: int, end: int, clause: str) -> Optional[Edit]:
    """Code's fix for a contradicted negative: remove the clause when it is the span's verbatim text, else drop the
    list item from its sentence (a line-level replace)."""
    span = text[start:end]
    if span.strip().rstrip(".") == clause.strip().rstrip("."):
        return Edit(mode="remove", find=span)
    new = _drop_item(span.strip(), clause.strip().rstrip("."))
    return Edit(mode="replace", find=span.strip(), replace=new) if new else None


async def probe(inp: ReviewInput, items: List[ReviewItem], text: str, changed_ranges: List[List[int]]) -> Dict:
    """One check of the current text (spec §12.4): each open item's probe, plus contradiction on the changed clauses.
    Returns item ids addressed (≥ 0.8) and to re-prepare (0.5–0.8, or anchor lost), plus new contradiction
    candidates (a negative carries code's removal)."""
    probe_qs = {f"p{k}": {"type": "noul", "instructions": it.probe} for k, it in enumerate(items) if it.probe}
    changed = []
    if changed_ranges:
        al = align(text, inp.artifacts.dictated_findings, inp.clinical_history, inp.artifacts.sections)
        changed = [c for c in al.clauses if any(c.start < b and a < c.end for a, b in changed_ranges)]
    contra_qs = {f"x{k}": {"type": "noul", "instructions": Q_CONTRA + c.text} for k, c in enumerate(changed)}
    pa, ca = await asyncio.gather(_ask(f"REPORT:\n{text}", probe_qs), _ask(_dict_state(inp), contra_qs),
                                  return_exceptions=True)
    pa = {} if isinstance(pa, BaseException) else pa
    ca = {} if isinstance(ca, BaseException) else ca
    addressed, reprepare = [], []
    for k, it in enumerate(items):
        p = _f(pa, f"p{k}")
        if p is not None and p >= ADDRESSED_OK:
            addressed.append(it.id)
        elif (p is not None and p >= UNSURE_LO) or (it.anchor and it.anchor.text not in text):
            reprepare.append(it.id)
    contradictions = []
    for k, c in enumerate(changed):
        s = _f(ca, f"x{k}")
        if s is not None and s >= CONTRA_FLAG:
            neg = c.negative or is_negative(c.text)
            contradictions.append(Candidate(
                lane="accuracy", kind="contradicted", section=c.section,
                anchor=Span(start=c.start, end=c.end, text=text[c.start:c.end]),
                evidence={"negative": neg, "score": s, "clause": c.text}, code_fix=neg,
                proposed=_negative_fix(text, c.start, c.end, c.text) if neg else None, detector="loop.contradiction"))
    return {"addressed": addressed, "reprepare": reprepare, "contradictions": contradictions}


__all__ = ["ADDRESSED_OK", "UNSURE_LO", "REMOVAL_KINDS", "apply_edit", "guard_failures", "changed_sentence",
           "verify", "probe"]
