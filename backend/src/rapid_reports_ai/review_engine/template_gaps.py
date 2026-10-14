"""Template gap flags: what the radiologist's own template says the report holds, but the report does not.

Pure code over the grammar structure (`ReviewInput.template_structure`), the template matcher (`template_text`) and,
for stack template reports, the gate's confirmed normals (`assumed_normals`). No model call. Each gap is an open rail
flag shaped like the post-gen check's `value_missing` (`live.check_flag_items`: lane accuracy, cls info, no edit; the
radiologist decides). Kinds:
- `template_slot_empty`: a fill-in wording printed with an empty slot ("Average HR:  bpm."), or a literal `{word}`
  placeholder left in the report. Not flagged when the post-gen backstop already flags that value (`value_missing`,
  stack reports): every content word of its item is in the slot's own wording (the matched text and its template
  unit, slot names included; for a `{word}` placeholder, its sentence), one item per slot. The rail shows the gap
  once, as the `value_missing` flag anchored on the slot (`anchor_value_flags`).
- `fixed_text_missing`: a FIXED unit (sentence by sentence) not in the report. Never flagged when a context rule may
  have settled it and which way is not knowable here: a SUPPRESS on it, a SUPPRESS_SECTION on its section, an
  optional section, or a REPLACE whose WITH wording is in the report (a REPLACE whose wording is absent too: both the
  line and its replacement are gone, so it is flagged). A sentence the radiologist removed on the stack is never
  flagged. The generation does not store its context-rule decisions with the report, so the sheet is the evidence.
- `assumed_normal_missing`: a normal confirmed at the stack gate (minus removed) not printed word for word.
- `heading_missing`: a findings paragraph's header absent while some of that paragraph's units are in the report
  (content present, header lost). A paragraph with no content is legitimately omitted: no flag.
At most MAX_GAPS flags per report; counts per kind are logged before the cap. Fails open: any missing or malformed
data gives no flag, never an error."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .claims import content_words
from .items import ReviewInput, ReviewItem, Span, item_key, text_hash
from .template_text import _SENTENCE, _SLOT, _WORD, MIN_WORDS, _find, _literal, _pattern

logger = logging.getLogger(__name__)

DETECTOR = "template_gap"
MAX_GAPS = 6
KINDS = ("template_slot_empty", "fixed_text_missing", "heading_missing", "assumed_normal_missing")
_LABEL = {
    "template_slot_empty": "Template field left empty: {text}",
    "fixed_text_missing": "Template text not in the report: {text}",
    "heading_missing": "Template heading missing: {text}",
    "assumed_normal_missing": "Confirmed normal not in the report: {text}",
}
_PLACEHOLDER = re.compile(r"\{[A-Za-z][\w /-]{0,30}\}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(t: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).split())


def _empty_slots(report: str, text: str) -> List[Tuple[int, int, str]]:
    """(start, end, field name) of each place `text` is printed with its slot(s) empty."""
    if not _SLOT.search(text):
        return []
    parts = _SLOT.split(text.strip())
    names = [m.group()[1:-1].strip() for m in _SLOT.finditer(text.strip())]
    lits = [p.strip() for p in parts]
    if len(_WORD.findall(" ".join(lits))) < MIN_WORDS:
        return []
    trail = not lits[-1] or bool(re.fullmatch(r"[.;:!?]", lits[-1]))     # the unit ends on its slot
    core = lits[:-1] if trail else lits
    body = r"[ \t]*".join(_literal(p) for p in core if p)
    pre = r"(?:^|(?<=\n))[ \t]*" if not lits[0] else ""
    post = r"[ \t]*[.;]?[ \t]*(?=\n|$)" if trail else ""
    field = re.sub(r"[\s:;,.(=-]+$", "", lits[0]).strip() or (names[0] if names else "")
    field = " ".join(field.split()[-4:]) or "field"
    pat = re.compile(pre + body + post, re.I | re.M)
    return [(m.start(), m.end(), field) for m in pat.finditer(report)
            if m.end() > m.start() and not (trail and _value_follows(report, m.end()))]


_LABELLED = re.compile(r"[^.:\n]{1,60}:")       # a heading or another "Field: value" line, never a field's value


def _value_follows(report: str, end: int) -> bool:
    """A field printed with its value on the next line ("Scan quality:\nGood diagnostic quality."): the next
    non-empty line is content, not a heading or another labelled field ("Coronary Findings:", "Average HR: 58 bpm.",
    an all-caps line)."""
    nxt = next((ln.strip() for ln in report[end:].split("\n")[1:] if ln.strip()), "")
    return bool(nxt) and not _LABELLED.match(nxt) and not (nxt.isupper() and len(nxt.split()) <= 6)


def _settled(report: str, with_text: str) -> bool:
    """A REPLACE wording is in the report, or whether it is cannot be told (no matchable wording, or a slot value
    longer than a matched slot allows: its literal parts in order, up to 400 characters apart)."""
    if _pattern(with_text) is None or _found(report, with_text):
        return True
    lits = [p.strip() for p in _SLOT.split(with_text.strip()) if p.strip(" .;:!?")]
    if len(lits) < 2 and not _SLOT.search(with_text):
        return False
    pat = r"[\s\S]{0,400}?".join(_literal(p.rstrip(" .;:!?")) for p in lits)
    return bool(pat) and re.search(pat, report, re.I) is not None


def _rule_texts(st: dict, effect: str) -> List[dict]:
    return [r for r in st.get("rules") or [] if isinstance(r, dict) and r.get("effect") == effect]


def _found(report: str, text: str) -> List[Tuple[int, int]]:
    return _find(report, text) if text else []


def _sentence(report: str, start: int, end: int) -> str:
    """The report sentence (or line) holding [start, end)."""
    a = max(report.rfind(c, 0, start) for c in ".!?\n") + 1
    ends = [k for k in (report.find(c, end) for c in ".!?\n") if k >= 0]
    return report[a:min(ends) if ends else len(report)]


def _value_flagged(inp: ReviewInput, used: set, *texts: str) -> Optional[str]:
    """The item of a post-gen backstop `value_missing` flag (stack reports) whose content words are all in `texts`
    (one empty slot's own wording), not already matched to another slot; None if there is none."""
    if not inp.stack:
        return None
    words = set().union(*(content_words(t) for t in texts))
    for e in (inp.artifacts.quality_check or {}).get("review") or []:
        if isinstance(e, dict) and e.get("kind") == "value_missing":
            name = str(e.get("text") or e.get("item") or "")
            item = content_words(name)
            if name not in used and item and item <= words:
                used.add(name)
                return name
    return None


def gaps(inp: ReviewInput, value_slots: Optional[Dict[str, Tuple[int, int]]] = None
         ) -> List[Tuple[str, str, Optional[Tuple[int, int]]]]:
    """(kind, text, anchor span or None) of every gap, in KINDS order. An empty slot the post-gen backstop already
    flags (`value_missing`) is not a gap: its span goes in `value_slots` under the flag's item instead, so the one
    flag the rail shows can point at it."""
    st = inp.template_structure
    if not isinstance(st, dict):
        return []
    report = inp.artifacts.report or ""
    removed = {_key(x) for x in inp.removed or [] if isinstance(x, str)}
    out: List[Tuple[str, str, Optional[Tuple[int, int]]]] = []

    # template_slot_empty
    seen = set()
    used: set = set()
    slots = value_slots if value_slots is not None else {}
    for m in _PLACEHOLDER.finditer(report):
        seen.add(m.start())
        name = _value_flagged(inp, used, _sentence(report, m.start(), m.end()))
        if name is None:
            out.append(("template_slot_empty", m.group(), (m.start(), m.end())))
        else:
            slots[name] = (m.start(), m.end())
    for t in inp.template_text or []:
        for s, e, field in _empty_slots(report, t):
            if s not in seen:
                seen.add(s)
                name = _value_flagged(inp, used, report[s:e], t)
                if name is None:
                    out.append(("template_slot_empty", field, (s, e)))
                else:
                    slots[name] = (s, e)

    # fixed_text_missing
    sections = {s.get("name"): s for s in st.get("sections") or [] if isinstance(s, dict)}
    suppress = {_key(r.get("target", "")) for r in _rule_texts(st, "suppress")}
    gone_sections = {r.get("target") for r in _rule_texts(st, "suppress_section")}
    replaces: Dict[str, List[str]] = {}
    for r in _rule_texts(st, "replace"):
        replaces.setdefault(_key(r.get("target", "")), []).append(r.get("then_text") or "")
    for f in st.get("fixed_blocks") or []:
        if not isinstance(f, dict):
            continue
        text, sec = f.get("text") or "", f.get("section")
        if (not text or _pattern(text) is None or _key(text) in suppress or sec in gone_sections
                or (sections.get(sec) or {}).get("optional")):
            continue
        if _found(report, text):
            continue
        if any(_settled(report, w) for w in replaces.get(_key(text), [])):
            continue
        sents = [p for p in _SENTENCE.split(text) if p.strip() and _pattern(p) is not None]
        missing = [p for p in sents if not _found(report, p) and _key(p) not in removed and _key(p) not in suppress
                   and not any(_settled(report, w) for w in replaces.get(_key(p), []))]   # a rule on one sentence
        if _key(text) in removed or not missing:
            continue
        if len(missing) == len(sents):
            out.append(("fixed_text_missing", text, None))
        else:
            out.extend(("fixed_text_missing", p, None) for p in missing)

    # heading_missing (findings paragraphs only)
    if not _rule_texts(st, "suppress_headers"):
        roles = {n: s.get("role") for n, s in sections.items()}
        fixed_para = {_key(r.get("target", "")): r.get("paragraph") for r in st.get("rules") or []
                      if isinstance(r, dict) and r.get("target")}
        units: Dict[str, List[str]] = {}
        for f in st.get("fixed_blocks") or []:
            if isinstance(f, dict) and fixed_para.get(_key(f.get("text", ""))):
                units.setdefault(fixed_para[_key(f["text"])], []).append(f["text"])
        for kind in ("normals", "negatives"):
            for u in st.get(kind) or []:
                if isinstance(u, dict) and u.get("paragraph"):
                    units.setdefault(u["paragraph"], []).append(u.get("text") or "")
        for r in st.get("rules") or []:
            if isinstance(r, dict) and r.get("paragraph"):
                units.setdefault(r["paragraph"], []).extend([r.get("then_text") or "", r.get("else_text") or ""])
        for p in st.get("paragraphs") or []:
            if not isinstance(p, dict) or not p.get("header") or roles.get(p.get("section")) != "findings":
                continue
            if _pattern(p["header"]) is None or _found(report, p["header"]):
                continue
            hits = sorted(h for u in units.get(p.get("id"), []) for h in _found(report, u))
            if hits:
                out.append(("heading_missing", p["header"], hits[0]))

    # assumed_normal_missing
    words = content_words(report)
    for n in inp.assumed_normals or []:
        # a normal merged with another ("No pleural or pericardial effusion.") keeps every content word: not missing
        if (isinstance(n, str) and _pattern(n) is not None and _key(n) not in removed and not _found(report, n)
                and not content_words(n) <= words):
            out.append(("assumed_normal_missing", n, None))
    return out


def gap_items(inp: ReviewInput, run_id: str) -> Tuple[List[ReviewItem], Optional[dict]]:
    """(open rail flags, log); ([], None) for a report with no grammar structure (quick reports)."""
    if not isinstance(inp.template_structure, dict):
        return [], None
    if inp.template_sheet_changed:       # written from another sheet: its gaps cannot be told from this one
        return [], {"sheet_changed": True}
    log: dict = {k: 0 for k in KINDS}
    log.update(capped=0, error=None)
    slots: Dict[str, Tuple[int, int]] = {}
    try:
        found = gaps(inp, slots)
    except Exception as e:  # noqa: BLE001 - fail open: no flag
        log["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        logger.warning("review engine: template gaps failed (%s)", log["error"])
        return [], log
    report = inp.artifacts.report or ""
    h = text_hash(report)
    out: List[ReviewItem] = []
    keys = set()
    for kind, text, span in found:
        key = item_key("accuracy", kind, text)
        if key in keys:
            continue
        keys.add(key)
        log[kind] += 1
        if len(out) >= MAX_GAPS:
            log["capped"] += 1
            continue
        label = _LABEL[kind].format(text=text)
        anchor = Span(start=span[0], end=span[1], text=report[span[0]:span[1]], text_hash=h) if span else None
        out.append(ReviewItem(
            key=key, report_id=inp.report_id, run_id=run_id, lane="accuracy", detectors=[DETECTOR], kind=kind,
            cls="info", anchor=anchor, label=label[:80], reason=label, edit=None,
            evidence={"source": DETECTOR, "kind": kind, "text": text}, status="open",
            history=[{"at": _now(), "event": "created", "actor": "engine", "text_hash": h, "detail": {"kind": kind}}]))
    if slots:
        log["value_slots"] = {k: list(v) for k, v in slots.items()}
    return out, log


def anchor_value_flags(flags: List[ReviewItem], log: Optional[dict], report: str) -> int:
    """Anchor each `value_missing` flag on the empty slot `gap_items` left to it (log "value_slots"), in place of
    the flag's own first-substring anchor (`live.check_flag_items`), which can land inside another word; the number
    anchored."""
    slots = (log or {}).get("value_slots") or {}
    h, n = text_hash(report), 0
    for it in flags:
        span = slots.get(str((it.evidence or {}).get("text") or (it.evidence or {}).get("item") or ""))
        if it.kind == "value_missing" and span:
            it.anchor = Span(start=span[0], end=span[1], text=report[span[0]:span[1]], text_hash=h)
            n += 1
    return n


__all__ = ["DETECTOR", "MAX_GAPS", "KINDS", "gaps", "gap_items", "anchor_value_flags"]
