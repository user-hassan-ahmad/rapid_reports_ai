"""CLINICAL HISTORY section for templates whose sheet defines one (spec §4, L-36 as refined
2026-09-30): a near-extractive restatement of the platform's clinical-history input, written by a
small call, checked fact-by-fact in code, placed by code. When the restatement fails its check (or the
call fails) the input itself is used, whitespace-tidied. Nothing from the history goes anywhere else."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import List, Optional, Set, Tuple

from pydantic import BaseModel

from . import report_reconcile as rc
from .enhancement_utils import _run_agent_with_model
from .report_review import ReportSection

logger = logging.getLogger(__name__)

HISTORY_SYS = ("Restate a referral's clinical history for the CLINICAL HISTORY section of a radiology report, in terse "
               "referral format: age and sex as e.g. 61M or 52F, then the input's facts as short phrases separated by "
               "full stops, the clinical question last prefixed '?'. Keep the referrer's own words, abbreviations and "
               "spelling: do not expand, abbreviate, translate or rephrase any term. Only drop connecting words. Keep "
               "every negation, question mark, uncertainty and time qualifier attached to the fact it belongs to. Add "
               "nothing. Return JSON {\"text\": \"...\"}.")

# ---------------------------------------------------------------------------------------------------
# Provenance: every output fragment is one input clause with only connecting words dropped, carrying
# every negation/query/past marker of that clause that governs it. Age/sex is checked on its own.

# Words the restatement may drop from inside (or at the edge of) an input clause.
_CONNECTIVES = {"with", "and", "or", "of", "the", "a", "an", "in", "on", "at", "to", "for", "has", "had", "is",
                "was", "are", "also", "who", "which", "patient", "pt"}
# Equivalences (applied to both sides): the query marker, and past-history markers.
_EQUIV = {"query": "?", "hx": "PAST", "history": "PAST", "previous": "PAST", "prior": "PAST", "pmh": "PAST"}
# Markers that govern the words after them in their clause ...
_PREFIX_MARKERS = {"no", "not", "without", "nil", "denies", "negative", "excluded", "?", "possible", "suspected",
                   "PAST", "known"}
# ... and markers that govern the words before them ("PE excluded", "D-dimer -ve", "appendicitis?").
_POSTFIX_MARKERS = {"negative", "excluded", "ve"}
_AGE_UNITS = {"y", "o", "yo", "yr", "yrs", "year", "years", "old", "aged", "-", "/"}
# 'fsex'/'msex' are the letter of an age/sex token such as 67F or '67 yo M'; a lone m/f, mr/ms and
# pronouns are never sex evidence.
_SEX = {"f": {"female", "woman", "lady", "girl", "fsex"}, "m": {"male", "man", "gentleman", "boy", "msex"}}
_SEX_WORDS = _SEX["f"] | _SEX["m"]
_UNIT_RE = r"(?:y/o|yo|yrs?|years?|y)(?:[\s-]*old)?"
_AGESEX_LETTER = re.compile(rf"(\b\d{{1,3}}(?:[\s-]*{_UNIT_RE})?[\s-]*)([mf])\b")
_OUT_AGE = re.compile(rf"^\s*(\d{{1,3}})(?P<unit>[\s-]*{_UNIT_RE})?[\s-]*(?P<sex>female|male|woman|man|f|m)?\b\s*")
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+(?:'[a-z]+)?|[?<>+\-/]")
_CLAUSE_SPLIT = re.compile(r"(?<!\d)\.|\.(?!\d)|[;,\n]")


def _tokens(s: str) -> List[str]:
    s = _AGESEX_LETTER.sub(lambda m: m.group(1) + " " + m.group(2) + "sex", s.lower())
    return [_EQUIV.get(t, t) for t in _TOKEN.findall(s)]


def _clauses(s: str) -> List[List[str]]:
    return [t for t in (_tokens(c) for c in _CLAUSE_SPLIT.split(s)) if t]


def _age_span(clause: List[str]) -> Set[int]:
    """Indices of the age/sex expression(s) in an input clause: a number with an age unit or sex word
    within 2 tokens, extended over the adjoining unit/sex tokens."""
    span: Set[int] = set()
    for i, t in enumerate(clause):
        if not t[0].isdigit():
            continue
        near = clause[max(0, i - 2):i] + clause[i + 1:i + 3]
        if not any(w in _AGE_UNITS - {"-", "/"} or w in _SEX_WORDS for w in near):
            continue
        span.add(i)
        for step in (-1, 1):
            j = i + step
            while 0 <= j < len(clause) and (clause[j] in _AGE_UNITS or clause[j] in _SEX_WORDS):
                span.add(j)
                j += step
    return span


def _is_postfix(clause: List[str], k: int) -> bool:
    t = clause[k]
    return t in _POSTFIX_MARKERS or (t == "?" and k == len(clause) - 1)


def _is_prefix(clause: List[str], k: int) -> bool:
    t = clause[k]
    return t in _PREFIX_MARKERS and not (t == "?" and k == len(clause) - 1)


def _match_fragment(frag: List[str], clause: List[str], age: Set[int]) -> bool:
    skippable = lambda j: clause[j] in _CONNECTIVES or j in age  # noqa: E731
    for s in range(len(clause)):
        if clause[s] != frag[0]:
            continue
        i, j = 0, s
        while i < len(frag) and j < len(clause):
            if clause[j] == frag[i]:
                i += 1
            elif not skippable(j):
                break
            j += 1
        if i < len(frag):
            continue
        end = j
        # The dropped remainder must be separated from the fragment by a connecting word, the age/sex
        # expression, or a marker that opens the next fact ("RIF pain ?appendicitis"): "pre-op" may not
        # be cut out of "pre-op CT normal".
        if s > 0 and not (skippable(s - 1) or _is_postfix(clause, s - 1) or _is_prefix(clause, s)):
            continue
        if end < len(clause) and not (skippable(end) or _is_prefix(clause, end) or _is_postfix(clause, end - 1)):
            continue
        # Every marker governing the fragment must be in it.
        if any(_is_prefix(clause, k) for k in range(s) if k not in age):
            continue
        if any(_is_postfix(clause, k) for k in range(end, len(clause))):
            continue
        return True
    return False


def _check_age(num: str, sex: Optional[str], clauses: List[List[str]]) -> Optional[str]:
    for clause in clauses:
        for i, t in enumerate(clause):
            if t != num:
                continue
            near = clause[max(0, i - 2):i] + clause[i + 1:i + 3]
            if not any(w in _AGE_UNITS - {"-", "/"} or w in _SEX_WORDS for w in near):
                continue
            if sex is None:
                return None
            words = set(clause)
            other = "m" if sex == "f" else "f"
            if (_SEX[sex] & words) and not (_SEX[other] & words):
                return None
            return f"sex {sex.upper()} not stated with age {num}"
    return f"age {num} not stated as an age"


def _why_ungrounded(text: str, history: str) -> Optional[str]:
    """None when `text` is grounded in `history`; else the first failing fragment and reason."""
    src = _clauses(history)
    ages = [_age_span(c) for c in src]
    frags = [f for f in _CLAUSE_SPLIT.split(text) if f.strip()]
    for n, frag in enumerate(frags):
        body = frag
        if n == 0:
            m = _OUT_AGE.match(frag.lower())
            if m and (m.group("unit") or m.group("sex")):
                sex = {"female": "f", "woman": "f", "f": "f", "male": "m", "man": "m", "m": "m"}.get(m.group("sex") or "")
                why = _check_age(m.group(1), sex, src)
                if why:
                    return f"{frag.strip()!r}: {why}"
                body = frag[m.end():]
        toks = _tokens(body)
        if not toks:
            continue
        if not any(_match_fragment(toks, c, a) for c, a in zip(src, ages)):
            return f"{frag.strip()!r}: not one input clause with only connecting words dropped and its markers kept"
    return None


def grounded(text: str, history: str) -> bool:
    return _why_ungrounded(text, history) is None


def _tidy(history: str) -> str:
    lines = (re.sub(r"[ \t]+", " ", ln).strip() for ln in history.splitlines())
    return "\n".join(ln for ln in lines if ln)


class _History(BaseModel):
    text: str


async def write_history(history: str) -> Optional[Tuple[str, str]]:
    """(text, mode) for the section: mode 'restated' when the model's restatement passes provenance,
    'verbatim' (the tidied input) when the call fails, returns nothing, or fails provenance.
    None only for empty input."""
    verbatim = _tidy(history)
    if not verbatim:
        return None
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

def _header_re(header: str) -> re.Pattern:
    """A header line: 'HEADER' alone (optional colon) or inline 'HEADER: text'."""
    h = re.escape(header.strip().rstrip(":").strip())
    return re.compile(rf"^[ \t]*{h}[ \t]*(?::[^\n]*)?[ \t]*$", re.M | re.I)


def _remove_written_history(report: str, hist: ReportSection, sections: List[ReportSection]) -> str:
    """Drop any history block the generator wrote under the history header, up to the next known
    header (or the end)."""
    if not hist.header:
        return report
    others = [_header_re(s.header) for s in sections if s is not hist and s.header]
    while True:
        m = _header_re(hist.header).search(report)
        if not m:
            return report
        nxt = [o.search(report, m.end()) for o in others]
        end = min((x.start() for x in nxt if x), default=len(report))
        report = (report[:m.start()] + report[end:]).strip("\n")
        report = re.sub(r"\n{3,}", "\n\n", report)


def insert_history(report: str, text: str, sections: List[ReportSection]) -> str:
    """Place the section under its header, before the next section (in sheet order) whose header is
    in the report; at the top when the next section is implicit or absent. Any history block the
    generator wrote is removed first; a sheet with no history section leaves the report unchanged."""
    hist = next((s for s in sections if s.role == "history"), None)
    if hist is None:
        return report
    report = _remove_written_history(report, hist, sections)
    block = f"{hist.header or hist.name}\n{text}\n\n"
    idx = sections.index(hist)
    for s in sections[idx + 1:]:
        if s.header is None:
            break
        m = _header_re(s.header).search(report)
        if m:
            return report[:m.start()] + block + report[m.start():]
    before = sections[:idx]
    if before and all(s.header for s in before):
        return report.rstrip() + "\n\n" + block.rstrip() + "\n"
    return block + report
