"""CLINICAL HISTORY section for templates whose sheet defines one (spec §4, L-36 as refined
2026-09-30): the platform's clinical-history input, placed by code under the sheet's header. Nothing
from the history goes anywhere else.

By default the section is the input VERBATIM (whitespace-tidied); no model call is made.

A near-extractive restatement (HISTORY_SYS, a small Qwen call, fact-level provenance in `grounded`,
verbatim fallback) is kept here behind RR_HISTORY_RESTATE=1 and is OFF pending the segmentation fixes
from the round-3 review (2026-09-30). Fix these before enabling:
- comma-listed markers: a marker's scope over a comma-separated list ("no fever, cough or rash" ->
  "Cough or rash." is accepted because the comma makes separate clauses);
- abbreviation periods ("e.g.", "o.e.", "y.o.") split clauses mid-fact;
- thousands commas ("1,200") split a number into two clauses;
- had/was/is/has as droppable connectives can change tense or polarity ("was on X", "had X");
- unit letters: a lone m/f after a number ("5 m") is read as an age/sex token.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import List, Optional, Set, Tuple

from pydantic import BaseModel

from . import report_reconcile as rc
from .enhancement_utils import _run_agent_with_model
from .report_review import ReportSection

logger = logging.getLogger(__name__)

RESTATE = os.environ.get("RR_HISTORY_RESTATE", "0").strip().lower() in ("1", "true", "on")

HISTORY_SYS = ("Restate a referral's clinical history for the CLINICAL HISTORY section of a radiology report, in terse "
               "referral format: age and sex as e.g. 61M or 52F, then the input's facts as short phrases separated by "
               "full stops, the clinical question last prefixed '?'. Keep the referrer's own words, abbreviations and "
               "spelling: do not expand, abbreviate, translate or rephrase any term. Only drop connecting words. Keep "
               "every negation, question mark, uncertainty and time qualifier attached to the fact it belongs to. Add "
               "nothing. Return JSON {\"text\": \"...\"}.")

# ---------------------------------------------------------------------------------------------------
# Provenance, whole-clause: an input clause is either left out entirely or restated completely by one
# or more consecutive output fragments, in order, with only connecting words (and the age/sex
# expression) dropped. A clause may be split into fragments only immediately before a marker that
# opens the next fact ("RIF pain ?appendicitis" -> "RIF pain. ?Appendicitis."), never where and/or
# was dropped in a clause that carries any marker. Age/sex is checked on its own, from real age forms.

# Words the restatement may drop from an input clause.
_CONNECTIVES = {"with", "and", "or", "of", "the", "a", "an", "in", "on", "at", "to", "for", "has", "had", "is",
                "was", "are", "also", "who", "which", "patient", "pt"}
# Equivalences (applied to both sides): the query marker, and past-history markers.
_EQUIV = {"query": "?", "hx": "PAST", "history": "PAST", "previous": "PAST", "prior": "PAST", "pmh": "PAST"}
# Markers that govern the words after them in their clause ...
_PREFIX_MARKERS = {"no", "not", "without", "nil", "denies", "negative", "excluded", "?", "possible", "suspected",
                   "PAST", "known"}
# ... and markers that govern the words before them ("PE excluded", "D-dimer -ve", "appendicitis?").
_POSTFIX_MARKERS = {"negative", "excluded", "ve"}
_MARKERS = _PREFIX_MARKERS | _POSTFIX_MARKERS
# 'fsex'/'msex' are the letter of an age/sex token such as 67F or '67 yo M'; a lone m/f, mr/ms and
# pronouns are never sex evidence.
_SEX = {"f": {"female", "woman", "lady", "girl", "fsex"}, "m": {"male", "man", "gentleman", "boy", "msex"}}
_SEX_WORDS = _SEX["f"] | _SEX["m"]
_UNIT_SEQS = (("y", "/", "o"), ("yo",), ("year", "old"), ("years", "old"), ("yr", "old"), ("yrs", "old"))
_NOT_AGE_BEFORE = {"for", "since", "over"}
_UNIT_RE = r"(?:y/o|yo|(?:yrs?|years?)[\s-]*old)"
_AGESEX_LETTER = re.compile(rf"(\b\d{{1,3}}(?:[\s-]*{_UNIT_RE})?[\s-]*)([mf])\b")
_OUT_AGE = re.compile(rf"^\s*(\d{{1,3}})(?P<unit>[\s-]*{_UNIT_RE})?[\s-]*(?P<sex>female|male|woman|man|f|m)?\b\s*")
_OUT_SEX = {"female": "f", "woman": "f", "f": "f", "male": "m", "man": "m", "m": "m"}
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+(?:'[a-z]+)?|[?<>+\-/]")
_CLAUSE_SPLIT = re.compile(r"(?<!\d)\.|\.(?!\d)|[;,\n]")


def _tokens(s: str) -> List[str]:
    s = _AGESEX_LETTER.sub(lambda m: m.group(1) + " " + m.group(2) + "sex", s.lower())
    return [_EQUIV.get(t, t) for t in _TOKEN.findall(s)]


def _clauses(s: str) -> List[List[str]]:
    return [t for t in (_tokens(c) for c in _CLAUSE_SPLIT.split(s)) if t]


def _skip_dash(clause: List[str], j: int) -> int:
    while j < len(clause) and clause[j] == "-":
        j += 1
    return j


def _ages(clause: List[str]) -> List[Tuple[str, Optional[str], Set[int]]]:
    """(number, sex or None, token indices) for each real age form in a clause: N y/o|yo|year(s) old,
    'aged N', or N next to a sex word/letter (67F, 67 M, 67 year old female, woman aged 67). The sex
    counts only inside the span. A number after for/since/over, or followed by 'ago', is not an age."""
    out = []
    for i, t in enumerate(clause):
        if not t[0].isdigit() or (i > 0 and clause[i - 1] in _NOT_AGE_BEFORE):
            continue
        span, has_unit = {i}, False
        j = _skip_dash(clause, i + 1)
        for seq in _UNIT_SEQS:
            k, idx = j, []
            for w in seq:
                k = _skip_dash(clause, k)
                if k < len(clause) and clause[k] == w:
                    idx.append(k)
                    k += 1
                else:
                    break
            else:
                span |= set(range(i, k))
                has_unit, j = True, k
                break
        if j < len(clause) and clause[j] == "ago":
            continue
        aged = i > 0 and clause[i - 1] == "aged"
        if aged:
            span.add(i - 1)
            has_unit = True
        sex = None
        j = _skip_dash(clause, j)
        if j < len(clause) and clause[j] in _SEX_WORDS:
            sex = "f" if clause[j] in _SEX["f"] else "m"
            span |= set(range(min(span), j + 1))
        elif aged and i > 1 and clause[i - 2] in _SEX_WORDS:
            sex = "f" if clause[i - 2] in _SEX["f"] else "m"
            span.add(i - 2)
        if has_unit or sex:
            out.append((t, sex, span))
    return out


def _is_postfix(clause: List[str], k: int) -> bool:
    t = clause[k]
    return t in _POSTFIX_MARKERS or (t == "?" and k == len(clause) - 1)


def _is_prefix(clause: List[str], k: int) -> bool:
    t = clause[k]
    return t in _PREFIX_MARKERS and not (t == "?" and k == len(clause) - 1)


def _covers(group: List[List[str]], clause: List[str], age: Set[int]) -> bool:
    """`group` (consecutive output fragments) restates the whole `clause`: every token of the clause
    appears in order except connecting words and the age/sex span, and fragments break only
    immediately before a prefix marker (never where and/or was dropped in a clause with markers)."""
    has_markers = any(t in _MARKERS for t in clause)
    skippable = lambda j: clause[j] in _CONNECTIVES or j in age  # noqa: E731
    j = 0
    for n, frag in enumerate(group):
        gap_start = j
        for m, tok in enumerate(frag):
            while j < len(clause) and clause[j] != tok:
                if not skippable(j):
                    return False
                j += 1
            if j == len(clause):
                return False
            if m == 0 and n > 0:
                if not _is_prefix(clause, j) or _is_postfix(clause, j):
                    return False
                if has_markers and any(clause[k] in ("and", "or") for k in range(gap_start, j)):
                    return False
            j += 1
    return all(skippable(k) for k in range(j, len(clause)))


def _why_ungrounded(text: str, history: str) -> Optional[str]:
    """None when `text` is grounded in `history`; else the first failing fragment and reason."""
    src = _clauses(history)
    ages = [_ages(c) for c in src]
    spans = [set().union(*(s for _, _, s in a)) if a else set() for a in ages]
    raw = [f for f in _CLAUSE_SPLIT.split(text) if f.strip()]
    frags: List[Tuple[str, List[str]]] = []
    for n, frag in enumerate(raw):
        body = frag
        if n == 0:
            m = _OUT_AGE.match(frag.lower())
            if m and (m.group("unit") or m.group("sex")):
                num, sex = m.group(1), _OUT_SEX.get(m.group("sex") or "")
                if not any(a_num == num for a in ages for a_num, _, _ in a):
                    return f"{frag.strip()!r}: age {num} not stated as an age"
                if sex and not any(a_num == num and a_sex == sex for a in ages for a_num, a_sex, _ in a):
                    return f"{frag.strip()!r}: sex {sex.upper()} not stated with age {num}"
                body = frag[m.end():]
        toks = _tokens(body)
        if toks:
            frags.append((frag.strip(), toks))

    # Partition the fragments into consecutive groups, each restating one whole input clause.
    fail: List[int] = [0]

    def ok(i: int) -> bool:
        if i == len(frags):
            return True
        fail[0] = max(fail[0], i)
        for k in range(1, len(frags) - i + 1):
            group = [t for _, t in frags[i:i + k]]
            if any(_covers(group, c, a) for c, a in zip(src, spans)) and ok(i + k):
                return True
        return False

    if not ok(0):
        return (f"{frags[fail[0]][0]!r}: not a whole input clause with only connecting words dropped "
                "(or split other than before a marker)")
    return None


def grounded(text: str, history: str) -> bool:
    return _why_ungrounded(text, history) is None


def _tidy(history: str) -> str:
    lines = (re.sub(r"[ \t]+", " ", ln).strip() for ln in history.splitlines())
    return "\n".join(ln for ln in lines if ln)


class _History(BaseModel):
    text: str


async def write_history(history: str) -> Optional[Tuple[str, str]]:
    """(text, mode) for the section, or None for empty input. By default (text, 'verbatim'): the tidied
    input, no model call. With RESTATE on: 'restated' when the model's restatement passes provenance,
    else 'verbatim' (call failed, returned nothing, or failed provenance)."""
    verbatim = _tidy(history)
    if not verbatim:
        return None
    if not RESTATE:
        return verbatim, "verbatim"
    try:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=rc.QWEN, output_type=_History, system_prompt=HISTORY_SYS, user_prompt=history, api_key="",
            model_settings={"temperature": 0, "max_tokens": 400, "reasoning_effort": "none"}), rc.QWEN_TIMEOUT_S)
        text = r.output.text.strip()
    except Exception as e:
        logger.warning("history section call failed (%s: %s); verbatim input used", type(e).__name__, str(e)[:200])
        return verbatim, "verbatim"
    if not text:
        logger.warning("history section empty; verbatim input used")
        return verbatim, "verbatim"
    why = _why_ungrounded(text, history)
    if why:
        logger.warning("history section not grounded (%s); verbatim input used", why[:300])
        return verbatim, "verbatim"
    return text, "restated"


# ---------------------------------------------------------------------------------------------------
# Placement

def _find_header(report: str, header: str) -> Optional[re.Match]:
    """The header's line: a standalone 'HEADER' (optional colon) anywhere first, else the first
    inline 'HEADER: text'."""
    h = re.escape(header.strip().rstrip(":").strip())
    m = re.search(rf"^[ \t]*{h}[ \t]*:?[ \t]*$", report, re.M | re.I)
    return m or re.search(rf"^[ \t]*{h}[ \t]*:[^\n]*$", report, re.M | re.I)


def _remove_written_history(report: str, hist: ReportSection, sections: List[ReportSection],
                             text: str) -> str:
    """Drop a history block the generator wrote: only a STANDALONE history header line sitting where
    the section belongs (after every sheet-earlier header present, before the first sheet-later header
    present), up to that later header; to the end when history is the sheet's last section; to the
    first paragraph break when an implicit section follows or no later header is present. When unsure, keep the text: a
    duplicate is cosmetic, deleting dictated text is not."""
    if not hist.header:
        return report
    idx = sections.index(hist)
    earlier = [m for m in (_find_header(report, s.header) for s in sections[:idx] if s.header) if m]
    lo = max((m.end() for m in earlier), default=0)
    # The first sheet-later section whose header is present, and whether an implicit (headerless)
    # section sits between it and the history section.
    hi, implicit_between = None, False
    for s in sections[idx + 1:]:
        if s.header is None:
            implicit_between = True
            continue
        m = _find_header(report, s.header)
        if m:
            hi = m.start()
            break
    h = re.escape(hist.header.strip().rstrip(":").strip())
    cand = next((m for m in re.finditer(rf"^[ \t]*{h}[ \t]*:?[ \t]*$", report, re.M | re.I)
                 if m.start() >= lo and (hi is None or m.start() < hi)), None)
    if cand is None:
        return report
    if hi is not None and not implicit_between:
        end = hi
    elif idx == len(sections) - 1:
        end = len(report)
    else:
        body = re.search(r"\S", report[cand.end():])
        brk = re.compile(r"\n[ \t]*\n").search(report, cand.end() + body.start()) if body else None
        if brk is None or (hi is not None and brk.end() > hi):
            return report
        # Without a following header the block's end is a guess: take it only when the block is one
        # line, or exactly the text being inserted (so insertion is idempotent).
        written = report[cand.end():brk.start()].strip()
        if "\n" in written and written != text.strip():
            return report
        end = brk.end()
    out = (report[:cand.start()] + report[end:]).strip("\n")
    return re.sub(r"\n{3,}", "\n\n", out)


def _neutralise_headers(text: str, sections: List[ReportSection]) -> str:
    """No line of the history text may read as a standalone sheet header (it would start a section):
    such a line is folded into the next non-empty line as the inline form 'HEADER: next line', or, when
    it is the last line, ends with a full stop instead."""
    pats = [re.compile(rf"^[ \t]*{re.escape(s.header.strip().rstrip(':').strip())}[ \t]*:?[ \t]*\r?$", re.I)
            for s in sections if s.header]
    lines = text.split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if any(p.match(ln) for p in pats):
            head = ln.strip().rstrip(":").strip()
            j = next((k for k in range(i + 1, len(lines)) if lines[k].strip()), None)
            if j is None:
                out.append(head + ".")
                break
            lines[j] = f"{head}: {lines[j].strip()}"
            i = j
            continue
        out.append(ln)
        i += 1
    return "\n".join(out)


def insert_history(report: str, text: str, sections: List[ReportSection]) -> str:
    """Place the section under its header, before the next section (in sheet order) whose header is
    in the report; at the top when the next section is implicit or absent. A history block the
    generator wrote in the section's place is removed first; a sheet with no history section leaves
    the report unchanged."""
    hist = next((s for s in sections if s.role == "history"), None)
    if hist is None:
        return report
    text = _neutralise_headers(text, sections)
    report = _remove_written_history(report, hist, sections, text)
    block = f"{hist.header or hist.name}\n{text}\n\n"
    idx = sections.index(hist)
    for s in sections[idx + 1:]:
        if s.header is None:
            break
        m = _find_header(report, s.header)
        if m:
            return report[:m.start()] + block + report[m.start():]
    before = sections[:idx]
    if before and all(s.header for s in before):
        return report.rstrip() + "\n\n" + block.rstrip() + "\n"
    return block + report
