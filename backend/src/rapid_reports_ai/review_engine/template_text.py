"""The template's own words in a templated report (fixes violet "AI synthesis" on FIXED template text).

A guided grammar sheet quotes the text the report is written from: FIXED, NORMAL and NEGATIVE lines, rule wordings
(USE, REPLACE ... WITH, ASK yes / no) and section / paragraph headers. That text is the radiologist's own, so it is
never "not in your dictation". `unit_texts` lists it from the parsed structure; `match` finds it in the report:
verbatim after light normalisation (case, whitespace, spacing around punctuation, hyphen vs space), each `{slot}` a
short value on one line. A multi-sentence unit also matches sentence by sentence (a rule may have replaced or
dropped one sentence). Exact text matching against the radiologist's template, never meaning matching.

Only the template's literal words are owned: a slot VALUE ("58" in "Average HR: 58 bpm.") is not in the spans, so
provenance still judges it. `unmatched` (unit texts, or the sentences of a partly matched unit, absent from the
report) is not used yet; a later gap-detection step reads it."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

_SLOT = re.compile(r"\{[^{}\n]*\}")
_SLOT_VALUE = r"([^\n]{1,60}?)"          # a slot inside a unit: a short value on one line, non-greedy
_WORD = re.compile(r"[A-Za-z0-9]+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9{])")
MIN_WORDS = 2                            # a unit with fewer literal words owns nothing (too generic to be the template's)


@dataclass
class TemplateMatch:
    spans: List[Tuple[int, int]] = field(default_factory=list)     # report spans of the template's literal words
    unmatched: List[str] = field(default_factory=list)            # unit texts (or sentences) not found in the report


def unit_texts(st) -> List[str]:
    """Every quoted report text of a grammar structure (a `SheetStructure`), de-duplicated, in structure order."""
    out: List[str] = []
    for s in st.sections:
        out += [s.header or "", *(s.alt_headers or [])]
    out += [p.header or "" for p in st.paragraphs]
    out += [f.text for f in st.fixed_blocks]
    out += [n.text for n in st.normals]
    out += [n.text for n in st.negatives]
    out += [n.text for ip in st.if_present for n in ip.negatives]
    for r in st.rules:
        out += [r.target or "", r.then_text or "", r.else_text or ""]   # REPLACE target, USE / WITH / YES, NO
    seen, texts = set(), []
    for t in out:
        t = " ".join((t or "").split())
        if t and t not in seen:
            seen.add(t)
            texts.append(t)
    return texts


def template_texts(config: Optional[dict]) -> List[str]:
    """`unit_texts` of a template config's grammar structure; [] when it has none (not a guided grammar sheet, or
    the sheet does not parse clean)."""
    from ..hybrid_stack.template import template_structure
    try:
        st = template_structure(config or {})
    except Exception:  # noqa: BLE001 - no structure: the review runs as for a quick report
        return []
    return unit_texts(st) if st is not None else []


def _literal(piece: str) -> str:
    """Pattern for a literal piece: whitespace / hyphen runs match any whitespace / hyphen run, punctuation may have
    spacing around it, case is ignored (by the caller's flag)."""
    out = []
    for tok in re.findall(r"[\s\-‐-–]+|[A-Za-z0-9]+|.", piece):
        if re.fullmatch(r"[\s\-‐-–]+", tok):
            out.append(r"[\s\-‐-–]+")
        elif tok[0].isalnum():
            out.append(re.escape(tok))
        else:
            out.append(r"\s*" + re.escape(tok) + r"\s*")
    return "".join(out)


def _pattern(text: str) -> Optional[re.Pattern]:
    """The unit's pattern; edge slots are dropped (their value is not the template's and bounds nothing), the
    closing punctuation is optional. None when the literal has fewer than MIN_WORDS words."""
    t = text.strip()
    t = _SLOT.sub("{}", t)
    t = re.sub(r"^(?:\{\}\s*)+", "", t)
    t = re.sub(r"(?:\s*\{\})+[.;:!?]?$", "", t).rstrip(" .;:!?")
    if len(_WORD.findall(t.replace("{}", " "))) < MIN_WORDS:
        return None
    pieces = t.split("{}")
    body = _SLOT_VALUE.join(_literal(p) for p in pieces)
    pre = r"(?<![A-Za-z0-9])" if pieces[0][:1].isalnum() else ""
    post = r"(?![A-Za-z0-9])" if pieces[-1][-1:].isalnum() else ""
    return re.compile(pre + body + post, re.I)


def _find(report: str, text: str) -> List[Tuple[int, int]]:
    """The literal spans of every occurrence of `text` in the report (slot values cut out); [] when absent."""
    pat = _pattern(text)
    if pat is None:
        return []
    out: List[Tuple[int, int]] = []
    for m in pat.finditer(report):
        cur = m.start()
        for g in range(1, (m.lastindex or 0) + 1):
            if m.start(g) >= 0:
                out.append((cur, m.start(g)))
                cur = m.end(g)
        out.append((cur, m.end()))
    return [(s, e) for s, e in out if e > s and report[s:e].strip()]


def match(report: str, texts: List[str]) -> TemplateMatch:
    """The template's literal spans in the report (sorted, merged) and the texts not found."""
    spans: List[Tuple[int, int]] = []
    unmatched: List[str] = []
    for t in texts:
        if _pattern(t) is None:
            continue
        hit = _find(report, t)
        if hit:
            spans += hit
            continue
        parts = [p for p in _SENTENCE.split(t) if p.strip()]
        if len(parts) < 2:
            unmatched.append(t)
            continue
        found = [(p, _find(report, p)) for p in parts]
        if not any(h for _, h in found):
            unmatched.append(t)
            continue
        for p, h in found:
            if h:
                spans += h
            elif _pattern(p) is not None:
                unmatched.append(p)
    merged: List[Tuple[int, int]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return TemplateMatch(spans=merged, unmatched=unmatched)


def cut(s: int, e: int, spans: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """[s, e) minus the template spans: the pieces left (possibly empty)."""
    out, cur = [], s
    for a, b in sorted(spans):
        if b <= cur or a >= e:
            continue
        if a > cur:
            out.append((cur, a))
        cur = max(cur, b)
    if cur < e:
        out.append((cur, e))
    return out


__all__ = ["TemplateMatch", "unit_texts", "template_texts", "match", "cut", "MIN_WORDS"]
