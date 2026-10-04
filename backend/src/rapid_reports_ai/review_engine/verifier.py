"""Verifier (spec §8): code guards, then one Jev batch on each fix's post-edit text. It checks the FIX, never the
reading. A failed check removes the edit and keeps the item's class; an unsure `addressed` keeps the fix and marks
it unconfirmed (§6.5). Also the live probe loop's one-shot check (spec §12.4).

Ported from the lab (`scripts/review_labs/judgement.py`: `apply_edit`, `_remove_span`, `_mid_word`, `guard_failures`,
`_loses_negation`, `changed_sentence`, `_paragraph`, `_extra_source`, `verify`) with its tests, types adapted to
`Edit` / `ReviewItem`. Engine additions (spec §9, decided 2026-10-04):
- a removal is allowed only for kind `contradicted` (or the Task 14 negatives kind `removed`), and never removes
  text the radiologist dictated;
- an insert with no `after` appends to the end of `edit.section` (the `Edit` contract);
- section boundaries are the report's known sections (`sections`, top-level names) when given, else the lab's
  ALL-CAPS "NAME:" lines; a region sub-heading ("CHEST:") under known sections is a label, not a boundary;
- a remove takes out a whole sentence or a whole list item, never flips a polarity, and drops at most the one
  negative it targets (the removal kinds' exemption is scoped to that item, `target`);
- the live loop's negative fix is built through production's `remove_negative_clause`.
- only code-built edits are ever pre-applied (binding correction 12): `preapply_failures` / `insert_from_line`;
  model-written edits stay one-click with a diff.
The "conveys" veto (`Q_CONVEYS`) is deliberately absent (spec §7)."""
from __future__ import annotations

import asyncio
import math
import os
import re
from typing import Dict, Iterable, List, Optional, Tuple

from .. import report_reconcile as rc
from ..report_review import (_EMPTY_ITEM, _FILLER, CONTRA_FLAG, JEV_TIMEOUT_S, Q_CONTRA, _restates, is_negative,
                             remove_negative_clause)
from .alignment import ANATOMY, _ANATOMY_STEMS, align, levels_of, side_of
from .alignment import _lines as _dict_lines
from .alignment import stem as _al_stem
from .items import Candidate, Edit, ReviewInput, ReviewItem, Span

ADDRESSED_OK = 0.8           # provisional: Gate E (spec §8)
UNSURE_LO = 0.5              # provisional: Gate E (§6.5: 0.5–0.8 is the unsure band → "unconfirmed")
REMOVAL_KINDS = frozenset({"contradicted", "removed"})   # spec §9: removal only for these, never dictated text

# ── headings, sentences, paragraphs ─────────────────────────────────────────
_HEADING = re.compile(r"^([A-Z][A-Z /&()-]{2,}):\s*$")   # lab common._HEADING (per line)
# Sentence breaks (re-review of 431c96c): after . ; ! ? … before a capital, digit or "("; after . ! ? … before a
# lowercase word unless the full stop ends an abbreviation; a spaced em/en dash; newlines.
_SENT_END = re.compile(r"(?<=[.;!?…])\s+(?=[A-Z0-9(])|(?<=[.!?…])\s+(?=[a-z])|\s+[—–]\s+|\n+")
_ABBR_END = re.compile(r"\b(?:vs|e\.g|i\.e|eg|ie|approx|etc|cf|incl|al|fig|ca|cm|mm)\.$", re.I)


def _norm_name(s: str) -> str:
    return s.strip().rstrip(":").strip().lower()


def _is_heading(line: str, names: Iterable[str] = ()) -> bool:
    """A section boundary: a line naming one of the known sections, or (none known) an ALL-CAPS "NAME:" line."""
    s = line.strip()
    if not s:
        return False
    known = {_norm_name(n) for n in names if n}
    return _norm_name(s) in known if known else bool(_HEADING.fullmatch(s))


def _is_label(line: str, names: Iterable[str] = ()) -> bool:
    """Any heading-like line (a section heading or a region sub-heading): never a sentence; text goes below it."""
    s = line.strip()
    return bool(s) and (bool(_HEADING.fullmatch(s)) or _is_heading(s, names))


def _headings(report: str, names: Iterable[str] = (), pred=_is_heading) -> List[Tuple[str, int, int]]:
    """(name, line start, line end without the newline) for each heading line (`pred`: boundaries by default)."""
    names = list(names or [])
    out, i = [], 0
    for line in report.split("\n"):
        if pred(line, names):
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
        if "\n" not in m.group() and text[m.end():m.end() + 1].islower() \
                and _ABBR_END.search(text[s:m.start()]):
            continue                            # "e.g. small": an abbreviation, not a sentence end
        out.append((s, m.start()))
        s = m.end()
    out.append((s, len(text)))
    return [(a, b) for a, b in out if text[a:b].strip() and not _is_label(text[a:b], names)]


_MARKER = re.compile(r"^\s*(?:\d{1,2}[.)]|[-*•])\s+")


def _sentence_spans(text: str, names: Iterable[str] = ()) -> List[Tuple[int, int]]:
    """Sentence spans in `text`, trimmed of whitespace and of a leading list marker ("2. ", "- ")."""
    out = []
    for a, b in _sentences(text, names):
        s = text[a:b]
        m = _MARKER.match(s)
        lead = m.end() if m else len(s) - len(s.lstrip())
        a2, b2 = a + lead, a + len(s.rstrip())
        if a2 < b2 and not _EMPTY_ITEM.match(text[a2:b2]):   # "1." split off its item is not a sentence
            out.append((a2, b2))
    return out


_BLANK = re.compile(r"\n[ \t\r]*\n")


def _paragraph(report: str, pos: int, names: Iterable[str] = ()) -> Tuple[int, int]:
    """The text between blank lines / heading or sub-heading lines that contains `pos`."""
    breaks = sorted([(m.start(), m.end()) for m in _BLANK.finditer(report)] +
                    [(a, min(b + 1, len(report))) for _, a, b in _headings(report, names, _is_label)])
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


_NUMBERED = re.compile(r"^([ \t]*)(\d{1,2})([.)])([ \t]+)")
_EOL = re.compile(r"^\r?\n")


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s[:1].islower() else s


def _renumber(after: str, n: int) -> str:
    """Numbered lines directly following a removed item `n` move up one (n+1 → n, n+2 → n+1, …)."""
    lines = after.split("\n")
    for k, line in enumerate(lines):
        m = _NUMBERED.match(line)
        if not m or int(m.group(2)) != n + k + 1:
            break
        lines[k] = f"{m.group(1)}{n + k}{m.group(3)}{m.group(4)}" + line[m.end():]
    return "\n".join(lines)


def _remove_span(report: str, i: int, n: int) -> str:
    """Splice out [i, i+n) and tidy only the seam; the rest of the report is never touched (but a removed numbered
    item renumbers the items below it). CRLF-safe."""
    a, b = report[:i], report[i + n:]
    at, bt = a.rstrip(" \t"), b.lstrip(" \t")
    ls = at.rfind("\n") + 1
    le = bt.find("\n")
    if at[ls:].strip() and _EMPTY_ITEM.match(at[ls:] + (bt if le < 0 else bt[:le]).rstrip("\r")):
        # a numbered or bulleted item left holding only its marker loses its line too (production's _EMPTY_ITEM)
        before, after = at[:ls], ("" if le < 0 else bt[le + 1:])
        m = _NUMBERED.match(at[ls:] + " ")
        if m:
            after = _renumber(after, int(m.group(2)))
        if not after and before.endswith("\n"):
            before = before[:-2] if before.endswith("\r\n") else before[:-1]
        return before + after
    eol = _EOL.match(bt)
    if not at or at.endswith("\n"):            # seam at a line start
        a, b = at, bt
        if eol:                                # the line is now empty: drop it
            b = b[eol.end():]
            nxt = _EOL.match(b)
            if nxt and re.search(r"(?:^|\n)[ \t\r]*\n$", a):   # a whole paragraph went: keep one blank line
                b = b[nxt.end():]
        elif not b and a.endswith("\n"):
            a = a[:-2] if a.endswith("\r\n") else a[:-1]
        else:
            b = _cap(b)                        # a leading item went: the sentence starts here
    elif not bt or eol or bt == "\r":          # seam at a line end
        a, b = at, bt
        if a.endswith((",", ";")):             # a dangling list separator closes the sentence
            a = a[:-1] + "."
    else:
        if bt[:1] in ".,;:" and at[-1:] in ".,;:!?":   # the removed text left its punctuation behind
            if at[-1] in ",;:" and bt[0] in ".;":
                at, sp = at[:-1], ""
            else:
                bt, sp = bt[1:].lstrip(" \t"), " "
        else:
            sp = " " if (a != at and b != bt) else (a[len(at):] + b[:len(b) - len(bt)])[:1]
        if at[-1:] in ".!?":
            bt = _cap(bt)
        a, b = at + sp, bt
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
    if not body.strip():
        return a, "\n"
    m = _NUMBERED.match(body[body.rfind("\n") + 1:])
    if m:                                       # a numbered list (IMPRESSION): the insert is the next item
        nl = "\r\n" if "\r\n" in report else "\n"
        return a + len(body), f"{nl}{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}{m.group(4)}"
    return a + len(body), " "


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
        if _is_label(anchor, sections or []):
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
# Negation lexicon (re-review of 431c96c): nil, free of, neither / nor, no evidence of, not seen. "Unremarkable" is
# not a negator. Longest alternatives first so each negation counts once.
_NEG = re.compile(r"\b(no evidence of|not seen|negative for|free of|without|neither|absent|none|nil|nor|not|no)\b",
                  re.I)
_NEGATOR = re.compile(r"\b(free of|without|neither|nil|nor|not|no)\b", re.I)
# A negator that negates no finding ("no doubt", "no interval change in the left effusion", "not only").
_NEG_IDIOM = re.compile(r"\b(?:no|not)(?=\s+(?:doubt|(?:significant\s+)?(?:interval\s+)?change|only)\b)", re.I)
_NEG_SKIP = {"a", "an", "the", "any", "evidence", "of", "is", "are", "was", "were", "seen", "identified",
             "no", "not", "nil", "nor", "neither", "without"}
_VERB = {"is", "are", "was", "were", "seen", "identified", "noted", "demonstrated"}
_LIST_SEP = re.compile(r",|\b(?:or|and|nor)\b", re.I)
_SENT_STOP = re.compile(r"[.;!?\n…—–]")
_CLAUSE_BREAK = {"but", "however", "although", "though", "with", "which", "while", "whereas", "except"}
_POST_NEG = {"not", "absent", "negative"}


def _mask(text: str) -> str:
    """`text` with idiomatic negators ("no doubt", "no interval change") blanked, positions kept."""
    return _NEG_IDIOM.sub(lambda m: "x" * len(m.group()), text)


def _has_neg(text: str) -> bool:
    return bool(_NEG.search(_mask(text or "")))


def _neg_count(text: str) -> int:
    return len(_NEG.findall(_mask(text or "")))


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z]+", text.lower())


def _negated_phrases(text: str) -> List[List[str]]:
    """Each listed item after a negator (no / nil / not / without / neither / nor / free of), up to the sentence end
    or the next negator: its first 2 content words. Items split on ',', 'or', 'and', 'nor'; the list ends after an
    item carrying a verb ("... is seen")."""
    out = []
    text = _mask(text)
    negs = list(_NEGATOR.finditer(text))
    for k, m in enumerate(negs):
        rest = text[m.end():negs[k + 1].start() if k + 1 < len(negs) else len(text)]
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
    new = _mask(new)
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


def _stem(w: str) -> str:
    """Light plural strip: masses → mass, collections → collection; -ss / -us / -is words kept."""
    if w.endswith("sses"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def _item_match(a: List[str], b: List[str]) -> bool:
    """Two negative-list items name the same thing: equal (singular or plural), or one is the other with a
    qualifier ("significant lymphadenopathy" / "lymphadenopathy"). "pleural effusion" ≠ "pericardial effusion"."""
    sa, sb = [_stem(w) for w in a], [_stem(w) for w in b]
    return sa == sb or (sa[-1] == sb[-1] and (set(sa) <= set(sb) or set(sb) <= set(sa)))


def _lost_negatives(old: str, new: str) -> List[List[str]]:
    """The negated items of `old` that `new` no longer negates, by item count (re-review #6): each negated item of
    `new` keeps at most one matching item of `old`, so two items sharing a head noun are two items."""
    left = _negated_phrases(new)
    lost = []
    for words in _negated_phrases(old):
        k = next((i for i, n in enumerate(left) if _item_match(words, n)), None)
        if k is None:
            lost.append(words)
        else:
            left.pop(k)
    return lost


def _matches(words: List[str], target: Optional[str]) -> bool:
    """A lost negative item is the target (the item's evidence clause or anchor text): its head noun is there."""
    return bool(target) and words[-1] in set(_words(target))


def _sanctioned(lost: List[List[str]], target: Optional[str]) -> bool:
    """The removal kinds' exemption (spec §9): at most one negative dropped, and it is the target when one is known."""
    return len(lost) <= 1 and (not lost or target is None or _matches(lost[0], target))


def _drops_sentence(old: str, new: str, lost: List[List[str]], target: Optional[str]) -> bool:
    """A removal-kind replace deletes a neighbouring sentence: every sentence of `old` but the edited one must still
    be said by `new`."""
    sents = [old[a:b] for a, b in _sentences(old)]
    missing = [s for s in sents if not _restates(s, new)]
    if len(sents) < 2 or not missing:
        return False
    if len(missing) > 1:
        return True
    s = set(_words(missing[0]))
    if lost:
        return not any(p[-1] in s for p in lost)
    return bool(target) and not (set(_words(target)) & s - _NEG_SKIP)


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


# Dictation shorthand expanded before comparison, so a dictated "No PTX." protects "No pneumothorax." (over-
# protection is the safe side; the abbreviation stays alongside its expansion).
_ABBREV = {"ptx": "pneumothorax", "pe": "pulmonary embolism", "dvt": "deep vein thrombosis",
           "cbd": "common bile duct", "aaa": "abdominal aortic aneurysm", "sol": "space occupying lesion",
           "lad": "lymphadenopathy", "ln": "lymph node", "lns": "lymph nodes", "ich": "intracranial haemorrhage",
           "sah": "subarachnoid haemorrhage", "sdh": "subdural haematoma", "edh": "extradural haematoma",
           "ff": "free fluid", "gb": "gallbladder", "ihd": "intrahepatic duct dilatation",
           # common dictation shorthand (t11): "No bone mets", "No hydro", "No fx", "No nodes", "No SBO"
           "mets": "metastases", "hydro": "hydronephrosis", "fx": "fracture", "fxs": "fractures",
           "nodes": "lymph nodes lymphadenopathy", "sbo": "small bowel obstruction",
           "lbo": "large bowel obstruction", "consol": "consolidation", "ptxs": "pneumothoraces",
           "ivh": "intraventricular haemorrhage", "hcc": "hepatocellular carcinoma"}
_ABBREV_RE = re.compile(r"\b(" + "|".join(sorted(_ABBREV, key=len, reverse=True)) + r")\b", re.I)
_SHORT_STOP = {"no", "or", "and", "the", "of", "is", "are", "in", "at", "to", "an", "as", "by", "on", "be", "it",
               "was", "has", "nor", "not", "nil", "but", "for", "any", "all", "may", "can", "mm", "cm", "ml", "yes",
               "see", "had", "per", "via", "its", "few", "new", "old", "x", "s", "a"}


def _acronyms(text: str) -> set:
    """Short upper-case tokens (2–3 letters: PE, DVT, CBD) that are words in their own right."""
    return {t.lower() for t in re.findall(r"\b[A-Z]{2,3}\b", text or "")} - _SHORT_STOP


def _content(text: str, acr: Iterable[str] = ()) -> set:
    """Content words: 4+ letters (light plural strip) less filler, plus short acronyms (upper case here, or known as
    acronyms from the other side of the comparison)."""
    acr = set(acr)
    long = {_stem(w) for w in re.findall(r"[a-z]{4,}", text.lower())} - _FILLER
    short = {t.lower() for t in re.findall(r"\b[A-Za-z]{2,3}\b", text)
             if (t.isupper() or t.lower() in acr) and t.lower() not in _SHORT_STOP}
    return long | short


def _says(new: str, existing: str, acr: Iterable[str] = ()) -> bool:
    """`new` says nothing `existing` does not (production's `_restates`, with short acronyms counted as content
    words and plurals folded)."""
    w = _content(new, acr)
    nums = set(_NUM.findall(new))
    return bool(w) and len(w & _content(existing, acr)) >= 0.8 * len(w) and nums <= set(_NUM.findall(existing))


_POLARITY_SPLIT = re.compile(
    r"\s*(?:[,;:]|\b(?:but|however|whereas|while|although|though|and|with)\b)\s*"
    r"(?=(?:there (?:is|are) )?(?:no|nil|not|without|neither|free of)\b)"
    r"|\s*\b(?:but|however|whereas|although|though)\b\s*|\s*[;:]\s*|\s+[—–]\s+", re.I)


def _clauses(text: str) -> List[str]:
    """A sentence split where its polarity can change ("Small left effusion, no pneumothorax.")."""
    return [p for p in _POLARITY_SPLIT.split(text) if p and p.strip(" .")]


def _dictated_sentences(dictation: str) -> List[str]:
    out = []
    for raw in (dictation or "").replace("\r", "").split("\n"):
        line = _MARKER.sub("", raw).strip()
        out += [line[a:b] for a, b in (_sentences(line) or [(0, len(line))]) if line[a:b].strip()]
    return out


def _dictated_pieces(dictation: str) -> List[str]:
    """Each dictated sentence (shorthand expanded), its polarity clauses and its comma pieces: what the radiologist
    said, at every grain."""
    out = []
    for raw in _dictated_sentences(dictation):
        for s in dict.fromkeys((raw, _expand(raw))):
            out += [s] + _clauses(s) + [p for p in s.split(",") if p.strip(" .")]
    return list(dict.fromkeys(out))


def _expand(s: str) -> str:
    return _ABBREV_RE.sub(lambda m: f"{m.group()} {_ABBREV[m.group().lower()]}", s)


def _dictated_text(text: str, dictation: str) -> bool:
    """`text` (or one of its polarity clauses) and a dictated line (or clause) say the same thing (either restates
    the other: a short dictated line inside a longer removed sentence counts) with the same polarity: the
    radiologist said it, so it is never removed (spec §9; PR #6). Over-protection is the safe side. Polarity
    matters: a generated "No X." beside a dictated "X" is not dictated text."""
    t = (text or "").strip()
    if not t:
        return False
    acr = _acronyms(dictation) | _acronyms(t)
    pieces = [t] + _clauses(t)
    return any(_has_neg(p) == _has_neg(s) and (_says(p, s, acr) or _says(s, p, acr))
               for p in pieces for s in _dictated_pieces(dictation))


_ITEM_SEP = re.compile(r",\s*(?:(?:or|and|nor)\s+)?|\s+(?:or|and|nor)\s+", re.I)


def _trim(report: str, i: int, j: int) -> Tuple[int, int]:
    f = report[i:j]
    return i + len(f) - len(f.lstrip()), j - len(f) + len(f.rstrip())


def _whole_sentences(report: str, i: int, j: int, names: Iterable[str]) -> Optional[List[Tuple[int, int]]]:
    """The sentences [i, j) consists of, when it starts and ends on sentence boundaries; else None."""
    a, b = _trim(report, i, j)
    spans = _sentence_spans(report, names)
    if a in {s for s, _ in spans} and b in {e for _, e in spans}:
        return [(s, e) for s, e in spans if a <= s and e <= b]
    return None


def _whole_item(report: str, i: int, j: int, names: Iterable[str]) -> bool:
    """[i, j) is one or more whole items of a list inside one sentence ("No a, b or c": "a,", ", b", "b")."""
    a, b = _trim(report, i, j)
    for s, e in _sentence_spans(report, names):
        if s <= a and b <= e:
            body = e - 1 if report[e - 1] in ".;!?" else e
            seps = list(_ITEM_SEP.finditer(report, s, body))
            if not seps:
                return False
            starts = {s} | {m.end() for m in seps} | {m.start() for m in seps}
            ends = {body, e} | {m.start() for m in seps} | {m.end() for m in seps} | \
                {m.start() + 1 for m in seps if report[m.start()] == ","}
            return a in starts and b in ends
    return False


_NEG_FORM = re.compile(r"^(?:there (?:is|are|was|were) )?(?:no evidence of|no|nil|without|neither|free of)\b", re.I)
_NOT_FORM = re.compile(r"^[^,;:]*\b(?:is|are|was|were) not(?: [a-z]+){1,2}$", re.I)
_POS_MARK = re.compile(r"\d|[:()?!…—–.]|\b(?:but|however|although|though|whereas|while|which|with|except|small|large|"
                       r"mild|moderate|severe|marked|tiny|trace|minimal|extensive|measur\w*|shows?|has|have|"
                       r"contains?|normal|unremarkable)\b", re.I)
_COPULA_TAIL = re.compile(r"\b(?:is|are|was|were)\b(.*)$", re.I)
_SEEN_TAIL = re.compile(r"^\s*(?:(?:seen|identified|demonstrated|noted|evident|present)\s*)?$", re.I)
_FIXED_TERM = re.compile(r"\b(?:small|large)(?=\s+(?:bowel|intestine)s?\b)", re.I)   # anatomy, not a size word


def _pos_mark(text: str) -> bool:
    """`text` carries a positive marker (`_POS_MARK`), "small bowel" / "large bowel" aside."""
    return bool(_POS_MARK.search(_FIXED_TERM.sub("x", text)))


def _negative_only(text: str, names: Iterable[str] = ()) -> bool:
    """Every clause of `text` is a plain negative ("No a, b or c (is seen).", "There is no X.", "Nil X.", "Neither
    X nor Y.", "The X is not dilated."): no number, size or severity word, clause break, colon, dash or second
    sentence. Strict by design: anything else is not negative-only."""
    sents = [text[a:b] for a, b in _sentence_spans(text, names)]
    if not sents:
        return False
    for s in sents:
        for c in _mask(s.strip().rstrip(".;").strip()).split(";"):
            c = c.strip()
            if not c or _pos_mark(c):
                return False
            m = _NEG_FORM.match(c)
            if m:
                tail = _COPULA_TAIL.search(c[m.end():])
                if tail and not _SEEN_TAIL.match(tail.group(1)):
                    return False
            elif not _NOT_FORM.match(c):
                return False
    return True


def _tokens(s: str) -> List[str]:
    return re.findall(r"\d+(?:\.\d+)?|[a-z]+", (s or "").lower())


_CONJ = {"or", "and", "nor"}


def _only_deletes(old: str, new: str) -> bool:
    """`new` is `old` with words deleted: its tokens are a subsequence of `old`'s, list conjunctions aside (a list
    re-joined after dropping an item moves its "or"), and it brings in no conjunction `old` lacks."""
    a, b = _tokens(old), _tokens(new)
    it = iter([t for t in a if t not in _CONJ])
    return all(t in it for t in b if t not in _CONJ) and {t for t in b if t in _CONJ} <= set(a)


_DEFAULT_SECTIONS = ("findings", "impression", "conclusion", "comparison", "technique", "clinical history",
                     "history", "indication", "report", "summary")
_CAPS_LABEL = re.compile(r"\b[A-Z][A-Z /&()-]{2,}:")


def _structure(report: str, edit: Edit, names: Iterable[str]) -> bool:
    """The edit changes the report's structure: new text carries a line break or a section heading (a known
    section name as a label, or an ALL-CAPS "NAME:" label, not already in the replaced text), or the replaced /
    removed text takes in a heading or sub-heading line."""
    names = list(names or [])
    secs = [_norm_name(n) for n in names if n] or list(_DEFAULT_SECTIONS)
    new, old = edit.replace or "", edit.find or ""

    def labels(t: str) -> int:
        return len(_CAPS_LABEL.findall(t)) + sum(
            len(re.findall(r"(?<![A-Za-z])" + re.escape(n) + r"\s*:", t, re.I)) +
            len(re.findall(r"\b" + re.escape(n.upper()) + r"\b", t)) for n in secs)
    if edit.mode in ("insert", "replace", "upgrade") and new.strip():
        if "\n" in new.strip() or "\r" in new.strip() or labels(new) > labels(old if edit.mode != "insert" else ""):
            return True
    if edit.mode in ("replace", "upgrade", "remove") and _once(report, old):
        i = report.index(old)
        j = i + len(old)
        if any(a < j and i < b for _, a, b in _headings(report, names, _is_label)):
            return True
    return False


def _anchor_mid_sentence(anchor: str, names: Iterable[str]) -> bool:
    """An insert anchor must end a sentence (or be a label line): text placed mid-sentence splits it."""
    a = (anchor or "").strip()
    return bool(a) and not _is_label(a, names) and not re.search(r"[.!?…][\"')\]]*$", a)


def _contexts(report: str, edit: Edit, names: Iterable[str]) -> Tuple[str, str]:
    """(old, new) text of the sentence(s) a replace touches; the bare find / replace when the find is not unique."""
    old, new = edit.find or "", edit.replace or ""
    if not _once(report, old):
        return old, new
    i = report.index(old)
    j = i + len(old)
    cover = [(s, e) for s, e in _sentence_spans(report, names) if s < j and i < e] or [(i, j)]
    lo, hi = min(cover[0][0], i), max(cover[-1][1], j)
    return report[lo:hi], report[lo:i] + new + report[j:hi]


def _alters_dictated(report: str, edit: Edit, dictation: str, names: Iterable[str]) -> bool:
    """A replace touching a sentence that says a dictated line (same polarity) keeps that line's sides and numbers
    exactly: it may not drop one the sentence shares with the line, nor bring in one the line lacks. A correction
    towards the dictated line (report "right", dictated "left") is not an alteration."""
    old, new = edit.find or "", edit.replace or ""
    if not _once(report, old) or not (dictation or "").strip():
        return False
    i = report.index(old)
    j = i + len(old)
    cover = [(s, e) for s, e in _sentence_spans(report, names) if s < j and i < e] or [(i, j)]
    lo, hi = min(cover[0][0], i), max(cover[-1][1], j)
    old_ctx, new_ctx = report[lo:hi], report[lo:i] + new + report[j:hi]
    so, sn = _sides(old_ctx), _sides(new_ctx)
    no, nn = set(_NUM.findall(old_ctx)), set(_NUM.findall(new_ctx))
    if so == sn and no == nn:
        return False
    acr = _acronyms(dictation) | _acronyms(old_ctx)
    lines = []
    for raw in _dictated_sentences(dictation):
        for s in dict.fromkeys((raw, _expand(raw))):
            lines += [s] + _clauses(s)
    for a, b in cover:
        p = report[a:b]
        for s in dict.fromkeys(lines):
            if _has_neg(s) != _has_neg(p) or not (_says(p, s, acr) or _says(s, p, acr)):
                continue
            ss, sm = _sides(s), set(_NUM.findall(s))
            if (_sides(p) & ss) - sn or (set(_NUM.findall(p)) & sm) - nn or (sn - so) - ss or (nn - no) - sm:
                return True
    return False


def _remove_failures(report: str, edit: Edit, kind: str, dictation: str, names: Iterable[str],
                     target: Optional[str]) -> List[str]:
    """A remove takes out a whole sentence or a whole list item (`partial_remove`), never leaves a negated phrase
    un-negated (`drops_negation`), drops at most the one negative it targets (`drops_negative_item`), one sentence
    at most (`drops_sentence`), and never dictated text (`remove_dictated`). Its containing sentence is compared
    before and after."""
    fails = [] if kind in REMOVAL_KINDS else ["remove_not_allowed"]
    if not _once(report, edit.find):
        return fails
    i = report.index(edit.find)
    j = i + len(edit.find)
    whole = _whole_sentences(report, i, j, names)
    if whole is None and not _whole_item(report, i, j, names):
        fails.append("partial_remove")
    cover = [(s, e) for s, e in _sentence_spans(report, names) if s < j and i < e] or [(i, j)]
    lo, hi = cover[0][0], cover[-1][1]
    old_s, new_s = report[lo:hi], report[lo:max(lo, i)] + report[min(hi, j):hi]
    lost = _lost_negatives(old_s, new_s)
    if _loses_negation(old_s, new_s):
        fails.append("drops_negation")
    if not _sanctioned(lost, target):
        fails.append("drops_negative_item")
    if kind in REMOVAL_KINDS:
        if whole and len(whole) > 1:
            fails.append("drops_sentence")
        # a negative's removal takes nothing positive with it ("No effusion: small 4 mm nodule.")
        negative_target = kind == "removed" or (target is not None and _has_neg(target))
        if negative_target and _has_neg(old_s) and not _negative_only(old_s):
            fails.append("removes_positive")
        texts = [report[s:e] for s, e in whole] if whole else []
        if not whole:
            a, b = _trim(report, i, j)
            piece = re.sub(r"^(?:,|\s|or\b|and\b|nor\b)+|(?:[,.;]|\s|\bor|\band|\bnor)+$", "", report[a:b], flags=re.I)
            texts.append(("No " + piece) if _is_negated(report, a, b) else piece)
        texts += ["No " + " ".join(p) for p in lost]
        if any(_dictated_text(t, dictation) for t in texts):
            fails.append("remove_dictated")
    return fails


def _replace_removes_dictated(old: str, new: str, loses: bool, lost: List[List[str]], dictation: str) -> bool:
    """A removal-kind replace takes out dictated text: a dictated negation or negative-list item, or a dictated
    line the old text said and the new one no longer does."""
    if loses and _dictated_text(old, dictation):
        return True
    if any(_dictated_text("No " + " ".join(p), dictation) for p in lost):
        return True
    acr = _acronyms(dictation) | _acronyms(old)
    olds = [old[a:b] for a, b in _sentences(old)] or [old]
    olds += [c for o in olds for c in _clauses(o)]
    return any(_has_neg(s) == _has_neg(o) and _says(s, o, acr) and not _says(s, new, acr)
               for o in olds for s in _dictated_pieces(dictation))


def guard_failures(report: str, edit: Optional[Edit], kind: str, dictation: str, history: str, *,
                   extra_source: str = "", additions: bool = False, sections: Optional[List[str]] = None,
                   item_section: Optional[str] = None, target: Optional[str] = None) -> List[str]:
    """Spec §8 code guards. An empty list means the fix may be shown with Apply.
    `extra_source` (additions lane: the candidate's guideline evidence) also grounds numbers and sides.
    `additions`: the item comes from the additions lane, so new content and management are refused.
    `sections`: the report's top-level section names; only they bound sections (else the ALL-CAPS fallback).
    `item_section` is used for the section check when the edit names none.
    `target`: what a removal kind removes (the item's evidence clause or anchor text); its exemption covers that
    one negative only."""
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
    removal = kind in REMOVAL_KINDS
    if edit.mode == "remove":
        fails += _remove_failures(report, edit, kind, dictation, names, target)
    elif edit.mode in ("replace", "upgrade"):
        old_ctx, new_ctx = _contexts(report, edit, names)   # negation is read in the whole sentence(s) touched
        lost = _lost_negatives(old_ctx, new_ctx)
        flips = _loses_negation(old_ctx, new_ctx)
        loses = _neg_count(old_ctx) > _neg_count(new_ctx) or flips
        # L-47: an edit never drops a negation, except the sanctioned removal of one contradicted negative (a
        # negative-list item dropped from its line arrives as a line-level replace). Outside the removal kinds a
        # negated phrase left standing un-negated ("No X." → "X.") always fails (re-review #9; `flips`).
        ok = removal and _sanctioned(lost, target)
        if (loses or flips) and not ok:
            fails.append("drops_negation")
        if lost and not ok:
            fails.append("drops_negative_item")
        if removal and _has_neg(old_ctx) and not _only_deletes(old, new):
            fails.append("removal_adds_content")     # a negative's removal only deletes words (re-review #1)
        if removal and _drops_sentence(old, new, lost, target):
            fails.append("drops_sentence")
        if removal and _replace_removes_dictated(old, new, loses, lost, dictation):
            fails.append("remove_dictated")
        if _alters_dictated(report, edit, dictation, names):
            fails.append("alters_dictated")
    if edit.mode == "insert" and _anchor_mid_sentence(edit.after or "", names):
        fails.append("anchor_mid_sentence")
    if _structure(report, edit, names):
        fails.append("structure")
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


# ── pre-apply (binding correction 12) ───────────────────────────────────────
_LINE_MARKER = re.compile(r"^(?:\d{1,2}[.)](?=\s)|[-*•–—])\s*")


def _tidy_line(line: str) -> str:
    """A dictated line tidied only: list marker / dash / bullet stripped, whitespace collapsed, first letter
    capitalised when the first word is all lower case ("eGFR", "pT2", "CT" are kept), a full stop added when it has
    no terminal punctuation. No rewording."""
    s = re.sub(r"\s+", " ", line or "").strip()
    s = _LINE_MARKER.sub("", s).strip()
    if not s:
        return ""
    first = s.split(" ", 1)[0]
    if first == first.lower():
        s = s[:1].upper() + s[1:]
    if s[-1] not in ".!?":
        s = s.rstrip(",;: ") + "."
    return s if s.strip(" .!?") else ""


_SENT_CLOSE = re.compile(r"[.!?…][\"')\]]*$")


def insert_from_line(report: str, line_text: str, section: str = "FINDINGS",
                     sections: Optional[List[str]] = None) -> Optional[Edit]:
    """Code's insert of a dictated line (correction 12): the line tidied only (`_tidy_line`), placed after the last
    complete sentence of `section`'s body (a closing label line is the anchor instead), or appended when the body is
    empty. None when it cannot be placed safely: no such section, an empty line, a body ending mid-sentence or on a
    list item, or an anchor that is not unique."""
    names = sections or []
    text = _tidy_line(line_text)
    body = _section_body(report, section, names) if text else None
    if body is None:
        return None
    a, e = body
    chunk = report[a:e]
    if not chunk.strip():
        return Edit(mode="insert", after=None, replace=text, section=section)
    last = chunk.rstrip().split("\n")[-1].strip()
    if _is_label(last, names):
        anchor = last
    elif _MARKER.match(last):
        return None
    else:
        spans = _sentence_spans(chunk, names)
        if not spans or chunk[spans[-1][1]:].strip():
            return None
        anchor = chunk[spans[-1][0]:spans[-1][1]]
        if not _SENT_CLOSE.search(anchor):
            return None
    if not _once(report, anchor):
        return None
    return Edit(mode="insert", after=anchor, replace=text, section=section)


# ── pre-apply helpers (t11 re-review of ddcb88a): prefer refusing (one-click) over clever guards ──────────────
_GENERIC = {"small", "large", "tiny", "mild", "moderate", "severe", "marked", "normal", "clear", "unremarkable",
            "evidence", "significant", "acute", "seen", "there", "identified", "noted", "present", "within", "both",
            "size", "focal", "definite", "obvious", "further", "other", "also", "appearance", "limit", "left", "right",
            "bilateral", "measure", "measuring", "possible", "probable", "likely", "unlikely", "none", "without",
            "free", "demonstrated", "visible", "simple", "minor", "slight", "some", "multiple", "single", "is", "are"}
_NORMALISH = re.compile(r"\b(?:clear|normal|unremarkable|nad|satisfactory|preserved)\b", re.I)


def _wkeys(text: str) -> Tuple[set, set]:
    """(content-word stems, acronyms) of `text` with shorthand expanded, generic words dropped."""
    t = _expand(text or "")
    words = {_stem(w) for w in re.findall(r"[a-z]{4,}", t.lower())} - _FILLER - _GENERIC
    acr = _acronyms(t) | {m.group().lower() for m in _ABBREV_RE.finditer(text or "")}
    return words, acr


def _wmatch(a: str, b: str) -> bool:
    """Prefix match of two content words: the shorter (4+ letters) begins the longer, or they share 6 letters."""
    s, lng = sorted((a, b), key=len)
    return len(s) >= 4 and (lng.startswith(s) or len(os.path.commonprefix([a, b])) >= 6)


def _shares(a: str, b: str) -> bool:
    (wa, ca), (wb, cb) = _wkeys(a), _wkeys(b)
    return bool(ca & cb) or any(_wmatch(x, y) for x in wa for y in wb)


def _dictated_statements(dictation: str) -> List[str]:
    """Each dictated sentence split at polarity changes: the finest piece that has one polarity."""
    out = []
    for s in _dictated_sentences(dictation):
        out += _clauses(s) or [s]
    return list(dict.fromkeys(out))


def _near_dictated_negative(text: str, dictation: str) -> bool:
    """A dictated negative or normal statement ("No bone mets.", "Lungs clear.") shares a content word (prefix
    match, shorthand expanded on both sides) or an acronym with `text`: removing `text` may remove what the
    radiologist said, so it is never pre-applied."""
    return any((_has_neg(s) or _NORMALISH.search(s)) and _shares(text, s) for s in _dictated_statements(dictation))


def _ungrounded_contradiction(text: str, dictation: str) -> Optional[str]:
    """Why the removed negative's contradiction is not plainly in the dictation, or None. No dictated positive
    shares a content word or acronym with it while the dictation states something normal or clear ("Lungs clear."
    beside a removed "No consolidation.": the normal statement may be about the same organ) → "ungrounded_normal".
    The removed negative names a side that no sharing dictated positive has ("No effusion on the left." beside a
    dictated right effusion) → "side_mismatch". A semantic contradiction with no shared word ("No pneumoperitoneum."
    vs "Free gas under the diaphragm.") stays eligible when nothing normal is dictated."""
    stmts = _dictated_statements(dictation)
    pos = [s for s in stmts if not (_has_neg(s) or _NORMALISH.search(s)) and _shares(text, s)]
    if not pos and any(_NORMALISH.search(s) and not _has_neg(s) for s in stmts):
        return "ungrounded_normal"
    sides = _sides(text)
    if pos and sides and not any(sides <= _sides(s) for s in pos):
        return "side_mismatch"
    return None


_ABNORMAL_NEG = re.compile(r"\b(?:flow|enhanc\w*|excret\w*|perfus\w*|filling|opacif\w*|visuali[sz]\w*)\b", re.I)
_NOT_SEEN = re.compile(r"^(?:the\s+)?(.*?[a-z])\s+(?:is|are|was|were)\s+(?:not\s+(?:seen|identified|demonstrated|"
                       r"visuali[sz]ed|present)|absent)\b", re.I)


def _abnormal_negative(text: str, names: Iterable[str] = ()) -> bool:
    """An abnormal finding phrased as a negative: no flow / enhancement / excretion / perfusion / filling /
    opacification / visualisation, or an organ or structure that "is not seen" (an absent kidney, not a finding)."""
    if _ABNORMAL_NEG.search(text or ""):
        return True
    for a, b in _sentence_spans(text or "", names):
        m = _NOT_SEEN.match(text[a:b].strip())
        if m:
            head = re.findall(r"[a-z]+", m.group(1).lower())[-1]
            if head in ANATOMY or _al_stem(head) in _ANATOMY_STEMS:
                return True
    return False


def _list_item_drop(report: str, edit: Edit, names: Iterable[str]) -> Optional[List[List[str]]]:
    """A `_negative_fix` replace that is a pure deletion: one whole plain-negative sentence whose replacement is
    its own tokens less exactly one negative list item (the list connective re-joined), itself a plain negative.
    The lost item; None for anything else."""
    old, new = edit.find or "", edit.replace or ""
    if not (new.strip() and _once(report, old)):
        return None
    i = report.index(old)
    whole = _whole_sentences(report, i, i + len(old), names)
    if not whole or len(whole) != 1 or len(_sentence_spans(new, names)) != 1:
        return None
    if not (_only_deletes(old, new) and _negative_only(old, names) and _negative_only(new, names)):
        return None
    lost = _lost_negatives(old, new)
    return lost if len(lost) == 1 else None


def _empties_section(report: str, i: int, j: int, names: Iterable[str]) -> bool:
    """Removing [i, j) leaves its section or sub-section (between label lines) with no sentence."""
    labels = _headings(report, names, _is_label)
    lo = max([b for _, _, b in labels if b <= i], default=0)
    hi = min([a for _, a, _ in labels if a >= j], default=len(report))
    a, b = _trim(report, i, j)
    return all(a <= s and e <= b for s, e in _sentence_spans(report[lo:hi], names) for s, e in [(s + lo, e + lo)])


def _preapply_removal(report: str, edit: Edit, dictation: str, code_built: bool, names: List[str]) -> List[str]:
    fails = [] if code_built else ["not_code_built"]
    drop = _list_item_drop(report, edit, names) if edit.mode == "replace" else None
    if edit.mode != "remove" and drop is None:
        return fails + ["not_remove"]
    if not _once(report, edit.find):
        return fails + ["anchor_not_unique"]
    i = report.index(edit.find)
    j = i + len(edit.find)
    if _section_of(report, i, names) not in ("findings", "impression"):
        fails.append("outside_findings")         # never TECHNIQUE, HISTORY, COMPARISON or an unheaded report
    whole = _whole_sentences(report, i, j, names)
    cover = [(s, e) for s, e in _sentence_spans(report, names) if s < j and i < e] or [(i, j)]
    sent = report[cover[0][0]:cover[-1][1]]
    if drop is not None:
        texts = ["No " + " ".join(drop[0])]
    else:
        if whole is None and not _whole_item(report, i, j, names):
            fails.append("partial_remove")
        a, b = _trim(report, i, j)
        piece = re.sub(r"^(?:,|\s|or\b|and\b|nor\b)+|(?:[,.;]|\s|\bor|\band|\bnor)+$", "", report[a:b], flags=re.I)
        # negative-only: the whole sentence(s) touched are plain negatives, and so is the removed text itself
        if not _negative_only(sent, names) or (whole is None and _pos_mark(piece.replace(".", ""))):
            fails.append("not_negative_only")
        texts = [report[s:e] for s, e in whole] if whole else ["No " + piece]
        texts += ["No " + " ".join(p) for p in _lost_negatives(sent, report[cover[0][0]:i] + report[j:cover[-1][1]])]
        if _empties_section(report, i, j, names):
            fails.append("empties_section")
    if _abnormal_negative(sent, names):
        fails.append("not_negative_only")
    if any(_dictated_text(t, dictation) for t in texts):
        fails.append("remove_dictated")
    if any(_near_dictated_negative(t, dictation) for t in texts):
        fails.append("near_dictated_negative")
    fails += [w for w in dict.fromkeys(_ungrounded_contradiction(t, dictation) for t in texts) if w]
    return fails


_LABEL_PREFIX = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 /&()'-]{0,40}:")
_NON_FINDING = re.compile(r"\b(?:histor\w*|clinical\w*|indications?|recommend\w*|suggest(?!ive)\w*|advis\w*|"
                          r"follow[\s-]?up|correlat\w*|discuss\w*|communicat\w*|inform\w*|phoned|telephon\w*|dr|"
                          r"compar\w*|previous\w*|prior)\b", re.I)


def _line_key(s: str) -> str:
    s = _LINE_MARKER.sub("", re.sub(r"\s+", " ", s or "").strip()).strip().lower()
    return s.rstrip(" .;,:!?…").strip()


def _dictated_line_context(dictation: str, line_text: str) -> Optional[dict]:
    """The block context (block_side / block_levels, as `alignment` reads it) of the dictated line equal to
    `line_text`; None when no whole dictated line equals it."""
    texts = [t.strip() for t in (dictation or "").replace("\r", "").split("\n") if t.strip()]
    key = _line_key(line_text)
    if not key:
        return None
    for dl in _dict_lines(texts, "d", set()):
        if _line_key(dl.text) == key:
            return {"block_side": dl.block_side, "block_levels": list(dl.block_levels)}
    return None


def _block_unstated(line_text: str, ctx: Optional[dict]) -> bool:
    """The line sits under a dictated side or level block it does not itself state."""
    if not ctx:
        return False
    side, levels = ctx.get("block_side"), ctx.get("block_levels") or []
    if isinstance(levels, str):
        levels = [levels]
    if side and side not in (_sides(line_text) | {side_of(line_text)}):
        return True
    own = set(levels_of(line_text))
    return any(lv not in own for lv in levels)


def _findings_sub_headed(report: str, names: Iterable[str]) -> bool:
    """FINDINGS has region sub-headings or label lines ("LEFT KIDNEY:", "Liver: normal."): placement is ambiguous."""
    body = _section_body(report, "FINDINGS", names)
    if body is None:
        return False
    return any(_is_label(ln.strip(), names) or _LABEL_PREFIX.match(ln)
               for ln in report[body[0]:body[1]].split("\n") if ln.strip())


def _findings_conflict(report: str, text: str, names: Iterable[str]) -> Optional[str]:
    """A FINDINGS sentence restates `text` ("duplicate"), or names its head finding (a content word or acronym)
    with a different side, number or polarity ("conflicts_findings")."""
    body = _section_body(report, "FINDINGS", names)
    if body is None:
        return None
    chunk = report[body[0]:body[1]]
    acr = _acronyms(text) | _acronyms(chunk)
    for a, b in _sentence_spans(chunk, names):
        s = chunk[a:b]
        if _says(text, s, acr) or _restates(text, s):
            return "duplicate"
        if _shares(text, s) and (_sides(s) != _sides(text) or set(_NUM.findall(s)) != set(_NUM.findall(text))
                                 or _has_neg(s) != _has_neg(text)):
            return "conflicts_findings"
    return None


def _preapply_insert(report: str, edit: Edit, dictation: str, line_text: Optional[str], names: List[str],
                     line_context: Optional[dict] = None) -> List[str]:
    if not (line_text or "").strip():
        return ["no_line"]
    if edit.mode != "insert":
        return ["not_insert"]
    fails = []
    if _norm_name(edit.section or "") != "findings":
        fails.append("outside_findings")
    built = insert_from_line(report, line_text, edit.section or "FINDINGS", names)
    if built is None or (edit.replace, edit.after) != (built.replace, built.after):
        fails.append("not_code_built")
    anchor = (edit.after or "").strip()
    if anchor:
        if _anchor_mid_sentence(anchor, names):
            fails.append("anchor_mid_sentence")
        pos = report.index(anchor) if _once(report, anchor) else None
        if pos is None or _section_of(report, pos, names) != "findings":
            fails.append("outside_findings")
    text = edit.replace or ""
    if _structure(report, edit, names):
        fails.append("structure")
    if set(_NUM.findall(text)) - set(_NUM.findall(line_text)):
        fails.append("ungrounded_number")
    if _sides(text) - _sides(line_text):
        fails.append("ungrounded_side")
    if {n.lower() for n in _NEG.findall(text)} - {n.lower() for n in _NEG.findall(line_text)}:
        fails.append("adds_negation")
    # the line is one whole dictated line (never a fragment, nor a span across lines), one sentence long
    ctx = _dictated_line_context(dictation, line_text)
    if ctx is None:
        fails.append("line_not_dictated")
    if len(_sentences(text, names)) > 1:
        fails.append("multi_sentence")
    if _block_unstated(line_text, line_context) or _block_unstated(line_text, ctx):
        fails.append("block_context")
    if _findings_sub_headed(report, names):
        fails.append("findings_sub_headed")
    clash = _findings_conflict(report, text, names)
    if clash:
        fails.append(clash)
    if _LABEL_PREFIX.match(_LINE_MARKER.sub("", line_text.strip())) or _NON_FINDING.search(line_text):
        fails.append("not_a_finding")
    return fails


def preapply_failures(report: str, edit: Optional[Edit], kind: str, dictation: str, *, code_built: bool,
                      line_text: Optional[str] = None, sections: Optional[List[str]] = None,
                      line_context: Optional[dict] = None) -> List[str]:
    """Binding correction 12 (spec §9): [] only when `edit` may be applied before the radiologist sees the report.
    Only code-built edits qualify:
    - removal (`kind` in REMOVAL_KINDS): `code_built`, inside FINDINGS or IMPRESSION, mode `remove` of whole sentence(s) or list
      item(s) of plain negatives (or `_negative_fix`'s pure-deletion replace dropping exactly one list item);
      nothing dictated removed, no dictated negative or normal statement sharing a content word / acronym with the
      removed text, no ungrounded contradiction beside a dictated normal statement and no side mismatch with the
      dictated positive (`_ungrounded_contradiction`), no abnormal finding phrased as a negative
      ("no flow", "the kidney is not seen"), and the section is not left empty;
    - insert (`kind == "absent"`): exactly `insert_from_line(report, line_text)`, where `line_text` equals one whole
      dictated line of one sentence, states its dictated block's side / level (`line_context`: block_side,
      block_levels; else read from the dictation), is a finding (no "Label:" prefix, history, recommendation,
      communication or comparison), and FINDINGS has no sub-headings and no sentence restating it or naming its
      finding with another side, number or polarity;
    - positive correction (`kind == "contradicted"`, mode `replace`, a positive `find`): never (deferred to Gate F:
      ["correction_one_click"]).
    The §8 code guards must also pass. Anything else: ["not_preapply_eligible"]. Pure code, no model calls."""
    if edit is None:
        return ["no_edit"]
    names = list(sections or [])
    positive = edit.mode == "replace" and not _has_neg(edit.find or "") and not is_negative(edit.find or "")
    if kind == "absent":
        fails = _preapply_insert(report, edit, dictation, line_text, names, line_context)
    elif kind == "contradicted" and positive:
        return ["correction_one_click"]          # spec §9: measured in Gate F before any correction goes live
    elif kind in REMOVAL_KINDS:
        fails = _preapply_removal(report, edit, dictation, code_built, names)
    else:
        return ["not_preapply_eligible"]
    fails += guard_failures(report, edit, kind, dictation, "", sections=names, item_section=edit.section)
    return list(dict.fromkeys(fails))


def changed_sentence(report: str, after: str, edit: Edit, sections: Optional[List[str]] = None) -> str:
    """Every sentence of `after` overlapping the new text, located by position (never by text search)."""
    names = sections or []
    pos = _edit_pos(report, edit, names)
    if pos is None:
        return (edit.replace or "").strip()
    if edit.mode == "insert":
        pt = None if (edit.after or "").strip() else _append_point(report, edit, names)
        pos += len(pt[1]) if pt else 1
        n = len((edit.replace or "").strip())
    else:
        n = len(edit.replace or "")
    end = pos + max(n, 1)
    hit = [after[a:b].strip() for a, b in _sentences(after, names) if a < end and pos < b]
    return " ".join(hit) if hit else (edit.replace or "").strip()


_EVIDENCE_KEYS = ("threshold", "timing", "grade", "criteria", "parameter", "system", "modality", "text",
                  "sentence")   # the brief option's own sentence grounds its insert (one-click only)


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
        v = float(ans[k]["noul"])
    except Exception:  # noqa: BLE001 - a missing or unreadable answer
        return None
    return v if math.isfinite(v) else None


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {str(e)[:200]}"


def _target(it: ReviewItem) -> Optional[str]:
    """What a removal-kind item removes: its evidence clause, else its anchor text."""
    clause = (it.evidence or {}).get("clause")
    if isinstance(clause, str) and clause.strip():
        return clause
    return it.anchor.text if it.anchor and it.anchor.text.strip() else None


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
                               extra_source=_extra_source(it, group), additions=_is_additions(it, group),
                               sections=names, item_section=it.section, target=_target(it))
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
                    errors.append("contra: missing or unreadable answer")
        if it.probe:
            ans = probe_ans[k]
            if isinstance(ans, BaseException):
                errors.append(_err(ans))
            else:
                v["addressed"] = _f(ans, "addressed")
                if v["addressed"] is None:
                    errors.append("addressed: missing or unreadable answer")
                elif v["addressed"] < UNSURE_LO:
                    v["failed"].append("not_addressed")
                else:
                    v["unconfirmed"] = v["addressed"] < ADDRESSED_OK
        else:
            v["unconfirmed"] = True            # nothing checks that the fix addresses the item
        if errors:
            v["error"] = "; ".join(dict.fromkeys(errors))
            v["failed"].append("jev_error")
        if v["contra"] is not None and v["contra"] >= CONTRA_FLAG:
            v["failed"].append("fix_contradicts_dictation")
        if v["failed"]:
            v["code"] = False
            it.edit = None


# ── live probe loop (spec §12.4) ────────────────────────────────────────────
_FIX_HEAD = "FINDINGS:\n"


def _oxford(s: str) -> str:
    """'No a, b or c' / 'No a or b' → 'No a, b, or c' / 'No a, or b': production's list split needs that comma."""
    return re.sub(r"(?<!,)\s+(or|and)\s+(?=[^,]*$)", r", \1 ", s, count=1)


def _negative_fix(text: str, start: int, end: int, clause: str, names: Iterable[str] = ()) -> Optional[Edit]:
    """Code's fix for a contradicted negative, built by production's `remove_negative_clause` on the sentence that
    holds [start, end): a whole-sentence remove when the sentence is the clause, else a replace of the sentence by
    its form with the item dropped (first, middle or last item; with or without an Oxford comma). None when the
    item cannot be removed cleanly: the adjudicator handles it."""
    hit = [(a, b) for a, b in _sentence_spans(text, names) if a < max(end, start + 1) and start < b]
    if len(hit) != 1:
        return None
    sent = text[hit[0][0]:hit[0][1]]
    target = clause.strip().rstrip(".").strip()
    if not target or text.count(sent) != 1:
        return None
    if sent.rstrip(".").strip() == target:
        return Edit(mode="remove", find=sent)
    for cand in dict.fromkeys((sent, _oxford(sent))):
        out = remove_negative_clause(_FIX_HEAD + cand, target)
        new = out[len(_FIX_HEAD):].strip() if out.startswith(_FIX_HEAD) else ""
        if out != _FIX_HEAD + cand and new and new != sent:
            return Edit(mode="replace", find=sent, replace=new)
    return None


def _anchor_at(it: ReviewItem, text: str) -> Optional[int]:
    """The item's anchor start in `text`: its offsets when they still hold the anchor text, else the anchor text's
    one occurrence; None when it is lost (absent or ambiguous). -1 when the item has no anchor."""
    an = it.anchor
    if an is None or not an.text:
        return -1
    if text[an.start:an.end] == an.text:
        return an.start
    return text.index(an.text) if text.count(an.text) == 1 else None


async def probe(inp: ReviewInput, items: List[ReviewItem], text: str, changed_ranges: List[List[int]]) -> Dict:
    """One check of the current text (spec §12.4): each open item's probe, plus contradiction on the changed clauses.
    Returns item ids addressed (≥ 0.8) and to re-prepare (probe 0.5–0.8, anchor lost, or its paragraph touched by
    a changed range), new contradiction candidates (a negative carries code's removal when it can be made
    cleanly), and `error` (None, or what failed when Jev did; the code checks still run)."""
    names = inp.artifacts.sections
    ranges = [(min(r[0], r[1]), max(r[0], r[1])) for r in (changed_ranges or []) if len(r) >= 2]

    def touches(lo: int, hi: int) -> bool:   # a zero-width range (a pure deletion) touches where it sits
        return any((a < hi and lo < b) if a < b else lo <= a <= hi for a, b in ranges)

    probe_qs = {f"p{k}": {"type": "noul", "instructions": it.probe} for k, it in enumerate(items) if it.probe}
    changed = []
    if ranges:
        al = align(text, inp.artifacts.dictated_findings, inp.clinical_history, names)
        changed = [c for c in al.clauses if touches(c.start, c.end)]
    contra_qs = {f"x{k}": {"type": "noul", "instructions": Q_CONTRA + c.text} for k, c in enumerate(changed)}
    pa, ca = await asyncio.gather(_ask(f"REPORT:\n{text}", probe_qs), _ask(_dict_state(inp), contra_qs),
                                  return_exceptions=True)
    errors = []
    if isinstance(pa, BaseException):
        errors.append(f"probe: {_err(pa)}")
        pa = {}
    if isinstance(ca, BaseException):
        errors.append(f"contradiction: {_err(ca)}")
        ca = {}
    addressed, reprepare = [], []
    for k, it in enumerate(items):
        p = _f(pa, f"p{k}")
        at = _anchor_at(it, text)
        if p is not None and p >= ADDRESSED_OK:
            addressed.append(it.id)
        elif (p is not None and p >= UNSURE_LO) or at is None or (at >= 0 and touches(*_paragraph(text, at, names))):
            reprepare.append(it.id)
    contradictions = []
    for k, c in enumerate(changed):
        s = _f(ca, f"x{k}")
        if s is not None and s >= CONTRA_FLAG:
            neg = c.negative or is_negative(c.text)
            fix = _negative_fix(text, c.start, c.end, c.text, names) if neg else None
            if fix is not None and guard_failures(text, fix, "contradicted", inp.artifacts.dictated_findings,
                                                  inp.clinical_history, sections=names, target=c.text):
                fix = None
            contradictions.append(Candidate(
                lane="accuracy", kind="contradicted", section=c.section,
                anchor=Span(start=c.start, end=c.end, text=text[c.start:c.end]),
                evidence={"negative": neg, "score": s, "clause": c.text}, code_fix=fix is not None,
                proposed=fix, detector="loop.contradiction"))
    return {"addressed": addressed, "reprepare": reprepare, "contradictions": contradictions,
            "error": "; ".join(dict.fromkeys(errors)) or None}


__all__ = ["ADDRESSED_OK", "UNSURE_LO", "REMOVAL_KINDS", "apply_edit", "guard_failures", "preapply_failures",
           "insert_from_line", "changed_sentence", "verify", "probe"]
