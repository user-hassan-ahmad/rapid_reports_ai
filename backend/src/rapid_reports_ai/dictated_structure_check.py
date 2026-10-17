"""A dictated value written against another structure (spec 2026-10-17, dictated fidelity step 3).

Dictated "aortic sinus 4.1 cm", report "aortic root 4.1 cm": the number check passes, the site changed. Each dictated
chain with a unit is paired with the FINDINGS sentences that hold it (`dictated_number_check.pairs`). A pair whose
report sentence contains the dictated sentence (normalised) passes in code; the rest go to Jev in one request (W1
wording, at most MAX_PAIRS, in report order; any beyond are logged `structure_name_unchecked` and give no item). A
pair is a different site when P(yes) < SAME_SITE_MIN; a chain passes when any of its sentences is the same site.
A failing chain is one review flag (severity high: an action card), anchored on its first FINDINGS sentence, with
a replace edit back to the dictated sentence only when that cannot lose or repeat content. Never applied here, never
raises; a Jev error, timeout or partial answer gives no item and logs `structure_name_check_unavailable`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Awaitable, Callable, Dict, Iterable, List, Optional, Set

from . import dictated_number_check as dnc

logger = logging.getLogger(__name__)

KIND = "dictated_structure_changed"
FLAG = "RR_DICTATED_STRUCTURES"
SAME_SITE_MIN = 0.7    # P(yes) below this: a different site (lab 2026-10-17 §7)
MAX_PAIRS = 12
TIMEOUT_S = 3.0        # as jev_stack.TIMEOUT_S
LABEL = "Different site from your dictation? Apply puts your sentence back."
LABEL_NO_EDIT = "Different site from your dictation? Check this sentence."

# "/" counts spaced or between words ("10 cm / hydronephrosis", "cm/hydronephrosis"), never in a unit or a level
# ("ml/m2", "L4/5": fewer than 2 letters on a side, or a digit)
_JOINER = re.compile(r"(?i)\b(?:and|with|without|but|whereas|which|while|although|except|otherwise)\b|[;,()\u2014]"
                     r"| - | / |(?<=[A-Za-z]{2})/(?=[A-Za-z]{3})")
NEW_WORDS_MAX = 2   # more content words than this not in the dictated sentence: the edit is withheld
_LETTERS = re.compile(r"[a-z][a-z']+")   # digits never count: a level ("L4/5", "C5-6") is never a content word
_STOP = frozenset("""a an the of in at on to is are was were be been with and or there this that its it as by for from
into measures measure measuring measured measurement seen present noted demonstrated identified shows has have no not
without other up than less more over about approx approximately""".split())
_SIDE = frozenset({"left", "right", "bilateral", "bilaterally"})   # what the check corrects: never "merged content"


Ask = Callable[[List[dnc.Pair]], Awaitable[List[float]]]


def enabled() -> bool:
    """Off unless RR_DICTATED_STRUCTURES is 1/true/on (read per call)."""
    return os.environ.get(FLAG, "0").strip().lower() in ("1", "true", "on")


# The lab wording W1, verbatim, plus the region sentence (end review 2026-10-17). `{key}` is the pair's state key.
QUESTION = ("In {key}, the REPORT sentence gives the value for exactly the same anatomical structure, site, side and "
            "level as the DICTATED sentence; synonyms and rewording count as the same, a broader or narrower site does "
            "not. The DICTATED sentence was said under the region named in dictated_region; read it as about that "
            "region when it names no structure itself.")


def question(key: str) -> dict:
    return {"type": "noul", "instructions": QUESTION.format(key=key)}


def state(ps: List[dnc.Pair]) -> Dict[str, dict]:
    """{"pair_N": {"dictated", "dictated_region" ("" when none), "report"}}, numbered from 1 in the given order."""
    return {f"pair_{i + 1}": {"dictated": p.dictated, "dictated_region": p.region, "report": p.report}
            for i, p in enumerate(ps)}


async def ask_same_site(ps: List[dnc.Pair]) -> List[float]:
    """P(same site) per pair, in order: one Jev request."""
    from .jev_client import JEV_MODEL, jev_post
    qs = {f"pair_{i + 1}": question(f"pair_{i + 1}") for i in range(len(ps))}
    r = await jev_post({"model": JEV_MODEL, "state": state(ps), "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    out: List[float] = []
    for i in range(len(ps)):
        p = (ans.get(f"pair_{i + 1}") or {}).get("noul")
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            raise ValueError("jev: incomplete answers")   # a missing answer is never "different site"
        out.append(float(p))
    return out


def code_pass(p: dnc.Pair) -> bool:
    """The report sentence holds the dictated sentence word for word (case, whitespace, punctuation aside) and, when
    the dictated sentence was said under a region, every word of that region too; otherwise Jev decides."""
    if dnc.norm(p.dictated) not in dnc.norm(p.report):
        return False
    return (_words(p.region) - _STOP) <= _words(p.report)


def _words(text: str) -> Set[str]:
    return set(_LETTERS.findall(text.lower()))


def _statements(sources: Iterable[dnc.Source]) -> List[str]:
    texts = [dnc.source_text(src) for src in sources]
    return [dnc.strip_prefix(t[s:e]) for t in texts if t for s, e in dnc.sentence_spans(t)]


def edit_for(p: dnc.Pair, report: str, sources: Iterable[dnc.Source], assumed: Iterable[str] = ()) -> Optional[dict]:
    """A replace edit putting the dictated sentence back, or None when replacing the whole sentence could lose or
    repeat content (spec §3.5): more than one sentence (a joined fragment), a line label naming something the
    dictated sentence does not, other values in it, a different number of clause joiners, a word merged in from
    another dictated statement or a confirmed assumed normal (side words aside), more than NEW_WORDS_MAX content
    words the dictated sentence lacks, a region or stripped dictated label whose words the dictated sentence lacks,
    a dictated word (side words aside) missing from `find` but said in another FINDINGS sentence, or a find that
    does not occur exactly once. `find` is the report sentence without its line label; the replace is the dictated
    sentence as said (no region prefix)."""
    find = dnc.strip_prefix(p.report)
    if len(dnc.sentence_spans(find)) > 1:
        return None
    own = _words(p.dictated)
    stems = {w[:4] for w in own if len(w) >= 4}
    named = _words(f"{p.region} {p.label}") - _STOP   # the region, and a line label stripped from the dictated sentence
    if any(w not in own and (len(w) < 4 or w[:4] not in stems) for w in named):
        return None   # "Cyst 2 cm." said under Left kidney: Apply would drop the structure ("Aorta" ~ "aortic" holds)
    if (_words(p.report[:len(p.report) - len(find)]) - _STOP) - own:   # "RIGHT KIDNEY:" kept above a left-kidney value
        return None
    if dnc.chain_keys(find) != dnc.chain_keys(p.dictated):
        return None
    if len(_JOINER.findall(find)) != len(_JOINER.findall(p.dictated)):
        return None   # a clause merged in, or a dictated clause the writer split off into another sentence
    if report.count(find) != 1:
        return None
    other: Set[str] = set()
    for s in _statements(sources):
        if s != p.dictated:
            other |= _words(s)
    for s in assumed:
        other |= _words(s or "")
    if any(w in other and w not in own for w in _words(find) - _STOP - _SIDE):
        return None
    # backstop: side words count unless the dictated sentence names a side itself (then the side is the correction)
    new = _words(find) - _STOP - own - (_SIDE if own & _SIDE else frozenset())
    if len(new) > NEW_WORDS_MAX:
        return None
    rest = _words(dnc.findings_only(report).replace(p.report, " "))   # the other FINDINGS sentences, label and all
    if any(w in rest for w in own - _words(find) - _STOP - _SIDE):
        return None   # a dictated word the writer moved to another sentence ("It is septated."): Apply would drop it
    rep = p.dictated.strip()
    rep = rep[:1].upper() + rep[1:]
    if not rep.endswith((".", "!", "?")):
        rep += "."
    return {"mode": "replace", "find": find, "replace": rep}


async def changed_structures(report: Optional[str], sources: Iterable[dnc.Source], removed: Iterable[str] = (),
                             ask: Optional[Ask] = None, assumed: Iterable[str] = ()) -> List[dict]:
    """[{"kind", "severity": "high", "text", "sentence", "dictated_quote", "message", "edit"}], one per dictated
    chain whose every FINDINGS sentence Jev reads as a different site. `sources`: the radiologist's own statements
    (as for the number check), each optionally (region, text); `removed`: the sentences the radiologist removed;
    `assumed`: the confirmed assumed normals, read by the edit guard only (never paired). Never raises."""
    try:
        report = report or ""
        sources = [s for s in sources if dnc.source_text(s)]
        assumed = [a for a in assumed if a]
        ps = dnc.pairs(report, sources, removed)
        asked = [p for p in ps if not code_pass(p)]
        if len(asked) > MAX_PAIRS:
            logger.info("structure_name_unchecked: %d pairs over the cap of %d", len(asked) - MAX_PAIRS, MAX_PAIRS)
        asked = asked[:MAX_PAIRS]
        same: Dict[dnc.Pair, Optional[bool]] = {p: (True if code_pass(p) else None) for p in ps}
        if asked:
            try:
                probs = await asyncio.wait_for((ask or ask_same_site)(asked), TIMEOUT_S)
                if len(probs) != len(asked):
                    raise ValueError("jev: answer count mismatch")
            except Exception as e:  # noqa: BLE001 - fail open: no item
                logger.info("structure_name_check_unavailable (%s: %s)", type(e).__name__, str(e)[:200])
                return []
            for p, pr in zip(asked, probs):
                same[p] = pr >= SAME_SITE_MIN
        groups: Dict[tuple, List[dnc.Pair]] = {}
        for p in ps:   # report order: a chain's first pair is its first FINDINGS sentence
            groups.setdefault((p.region, p.dictated, p.chain), []).append(p)
        out: List[dict] = []
        for (_, dictated, chain), gp in groups.items():
            if any(same[p] is not False for p in gp):   # passes if any sentence is the same site; unasked: unknown
                continue
            edit = edit_for(gp[0], report, sources, assumed)
            out.append({"kind": KIND, "severity": "high", "text": chain, "sentence": gp[0].report,
                        "dictated_quote": dictated, "message": LABEL if edit else LABEL_NO_EDIT, "edit": edit})
        return out
    except Exception as e:  # noqa: BLE001 - a flag is never worth a failed report
        logger.info("structure_name_check_unavailable (%s: %s)", type(e).__name__, str(e)[:200])
        return []


__all__ = ["KIND", "FLAG", "SAME_SITE_MIN", "MAX_PAIRS", "TIMEOUT_S", "LABEL", "LABEL_NO_EDIT", "QUESTION", "NEW_WORDS_MAX",
           "enabled", "question",
           "state", "ask_same_site", "code_pass", "edit_for", "changed_structures"]
