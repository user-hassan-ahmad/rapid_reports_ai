"""Template gap flags: what the radiologist's own template says the report holds, but the report does not.

Pure code over the grammar structure (`ReviewInput.template_structure`), the template matcher (`template_text`) and,
for stack template reports, the gate's confirmed normals (`assumed_normals`). No model call. Each gap is an open rail
flag shaped like the post-gen check's `value_missing` (`live.check_flag_items`: lane accuracy, cls info, no edit; the
radiologist decides). Kinds:
- `template_slot_empty`: a fill-in wording printed with an empty slot ("Average HR:  bpm."), or a literal `{word}`
  placeholder left in the report.
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
    return [(m.start(), m.end(), field) for m in pat.finditer(report) if m.end() > m.start()]


def _rule_texts(st: dict, effect: str) -> List[dict]:
    return [r for r in st.get("rules") or [] if isinstance(r, dict) and r.get("effect") == effect]


def _found(report: str, text: str) -> List[Tuple[int, int]]:
    return _find(report, text) if text else []


def gaps(inp: ReviewInput) -> List[Tuple[str, str, Optional[Tuple[int, int]]]]:
    """(kind, text, anchor span or None) of every gap, in KINDS order."""
    st = inp.template_structure
    if not isinstance(st, dict):
        return []
    report = inp.artifacts.report or ""
    removed = {_key(x) for x in inp.removed or [] if isinstance(x, str)}
    out: List[Tuple[str, str, Optional[Tuple[int, int]]]] = []

    # template_slot_empty
    seen = set()
    for m in _PLACEHOLDER.finditer(report):
        out.append(("template_slot_empty", m.group(), (m.start(), m.end())))
        seen.add(m.start())
    for t in inp.template_text or []:
        for s, e, field in _empty_slots(report, t):
            if s not in seen:
                seen.add(s)
                out.append(("template_slot_empty", field, (s, e)))

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
        if any(_found(report, w) for w in replaces.get(_key(text), [])):
            continue
        sents = [p for p in _SENTENCE.split(text) if p.strip() and _pattern(p) is not None]
        missing = [p for p in sents if not _found(report, p) and _key(p) not in removed]
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
    for n in inp.assumed_normals or []:
        if isinstance(n, str) and _pattern(n) is not None and _key(n) not in removed and not _found(report, n):
            out.append(("assumed_normal_missing", n, None))
    return out


def gap_items(inp: ReviewInput, run_id: str) -> Tuple[List[ReviewItem], Optional[dict]]:
    """(open rail flags, log); ([], None) for a report with no grammar structure (quick reports)."""
    if not isinstance(inp.template_structure, dict):
        return [], None
    log: dict = {k: 0 for k in KINDS}
    log.update(capped=0, error=None)
    try:
        found = gaps(inp)
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
    return out, log


__all__ = ["DETECTOR", "MAX_GAPS", "KINDS", "gaps", "gap_items"]
