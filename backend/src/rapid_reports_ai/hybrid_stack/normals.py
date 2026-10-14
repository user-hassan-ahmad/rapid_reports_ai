"""Assumed normals (checklist spec §5): the slim sheet's region normals that reach the report unless the
radiologist removes them. Every region, untouched, dictated normal or abnormal, keeps the sentences the dictation
neither covers nor contradicts (Jev): a dictated-normal region keeps the radiologist's words and the sentences on its
other structures (review R2 2026-10-13: "ACL intact" kept the PCL sentence). A sentence in a region whose
dictation hedges or limits its assessment, or that the dictation may contradict (contra between 0.3 and its bar), is
kept and flagged for the radiologist (review R1, hedge question 2026-10-13). Sentences the
radiologist removed never return; a template's context rules hide their sentences. Seam 21 (Hassan 2026-10-13):
template_context_rules.condition_state is the one state every context rule is decided on, here as at Generate; the
once-per-session decision below is only a cache of its answer on the history."""
from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel

from .jev_stack import CONDITION_MIN, SIDE_MIN, RowCheck, ask_conditions, ask_rows, ask_sides, normal_fate
from .sides import side_label, side_pairs
from .template import jev_text, norm_key
from ..template_context_rules import condition_state

logger = logging.getLogger(__name__)


class AssumedResult(BaseModel):
    assumed: dict[str, list[str]]
    # region -> assumed sentences the dictation may conflict with (its region's dictation hedges, or a weak
    # contradiction): also in `assumed`, shown highlighted for the radiologist to confirm or remove (review R1)
    flagged: dict[str, list[str]] = {}
    dropped: dict[str, list[dict]] = {}   # region -> [{sentence, reason: covered|contradicted|removed|rule}]
    # The session's template context-rule decision (condition -> P(met), from the clinical history; review R5): the
    # client keeps the first one and sends it back as `rules`. None: not decided (a failure, or nothing to ask).
    rules: dict[str, float] | None = None
    confirm_recheck: bool = False   # the sheet has context rules: Confirm re-asks every one with the dictation
    # "Which side?" (side brief 2026-10-14): a right/left pair the dictation reports a finding for without giving its
    # side. Both sides are dropped until a side is dictated: {region, sentences: [right, left], label, score}
    side_asks: list[dict] = []
    side_failed: bool = False   # the side question failed: the pair's normals stand as Jev read them, nothing asked
    ms: int = 0
    error: str | None = None


BATCH = 15   # sentences per Jev call; batches run in parallel (one call over every sentence timed out)


async def _ask(dictation: str, sentences: list[str], gone: list[str], **parts):
    chunks = [sentences[i:i + BATCH] for i in range(0, len(sentences), BATCH)]
    got = await asyncio.gather(*(ask_rows(dictation, c, gone, **parts) for c in chunks))
    return [c for part in got for c in part]


def _batches(n: int) -> int:
    return -(-n // BATCH)


def _text_regions(asked: list[tuple[str, str]], region_text: dict[str, str]) -> list[str]:
    # region_text keys must match the region names exactly: a mismatch finds no text, so it fails toward offering
    # more normals (nothing covers them), never toward dropping them.
    return list(dict.fromkeys(r for r, _ in asked if (region_text.get(r) or "").strip()))


def _jev_calls(asked: list[tuple[str, str]], region_text: dict[str, str] | None, rule_calls: int) -> int:
    """The Jev calls one refresh makes (logged, so fan-out can be watched live)."""
    n = _batches(len(asked)) + rule_calls
    if region_text is not None:
        n += sum(_batches(sum(1 for r, _ in asked if r == t)) for t in _text_regions(asked, region_text))
    return n


async def _ask_by_region(dictation: str, asked: list[tuple[str, str]], texts: list[str], gone: list[str],
                         region_text: dict[str, str]) -> list[RowCheck]:
    """Task A3b: a normal is covered only by the sentences grouped in its own region (one stated call per region
    with text, in parallel; a region with none is covered by nothing), and flagged when that region's text hedges
    or limits its assessment (asked once per region, in the same call); contradicted (and the same as a removed
    sentence) by the whole dictation, conclusion included."""
    regions = _text_regions(asked, region_text)
    idx = {r: [i for i, (ar, _) in enumerate(asked) if ar == r] for r in regions}
    whole, *per_region = await asyncio.gather(
        _ask(dictation, texts, gone, stated=False),
        *(_ask(region_text[r], [texts[i] for i in idx[r]], [], contra=False, hedge=r) for r in regions))
    stated = [0.0] * len(asked)
    hedge = [0.0] * len(asked)
    for r, checks in zip(regions, per_region):
        for i, c in zip(idx[r], checks):
            stated[i], hedge[i] = c.stated, c.hedge
    return [RowCheck(s, c.contra, c.removed, h) for s, h, c in zip(stated, hedge, whole)]


def _side_candidates(asked: list[tuple[str, str]], touched: set[str]) -> list[tuple[str, int, int]]:
    """(region, right index, left index) of each pair (hybrid_stack.sides, within one region) in a region the
    dictation touches: its grouped text or an abnormal region. An untouched region's pairs are never asked."""
    by_region: dict[str, list[int]] = {}
    for i, (r, _) in enumerate(asked):
        by_region.setdefault(r, []).append(i)
    return [(r, idx[a], idx[b]) for r, idx in by_region.items() if r in touched
            for a, b in side_pairs([asked[i][1] for i in idx])]


async def _side_scores(dictation: str, asked: list[tuple[str, str]], cands: list[tuple[str, int, int]]):
    """P(a finding for the pair with no side given) per candidate, asked alongside the rows (no added round trip);
    None when the call failed (nothing is asked then)."""
    if not cands:
        return []
    try:
        return await ask_sides(dictation, [(asked[i][1], asked[j][1]) for _, i, j in cands])
    except Exception as e:  # noqa: BLE001 -- the side question never fails the normals
        logger.warning("[stack.normals] side question %s: %s", type(e).__name__, str(e)[:200])
        return None


async def _session_rules(conds: list[str], scan_type: str, history: str,
                         rules: dict[str, float] | None) -> dict[str, float]:
    """The session's decision, condition -> P(met): condition_state on the scan type and the clinical history, with
    nothing dictated yet (review R5; seam 21). This is a cache of condition_state's answer, never a second decider:
    a cached one is reused as is; only conditions it lacks are asked, in one call."""
    cached = rules or {}
    todo = [c for c in conds if c not in cached]
    got = dict(zip(todo, await ask_conditions(condition_state(scan_type, history, ""), todo))) if todo else {}
    return {c: got[c] if c in got else float(cached[c]) for c in conds}


async def _confirm_rules(conds: list[str], scan_type: str, history: str, dictation: str) -> dict[str, float]:
    """At Confirm only: every condition, re-decided by condition_state on the scan type, the history and the
    dictation (one call, never cached), the same state template Generate decides on. Hassan 2026-10-13: no word
    filter decides which rule the dictation can settle ("if ascites is present" names no finding word)."""
    if not conds or not dictation.strip():
        return {}
    return dict(zip(conds, await ask_conditions(condition_state(scan_type, history, dictation), conds)))


async def _nothing():
    return {}


async def _no_rows():
    return None


async def assumed(dictation: str, region_normals: dict[str, list[str]], abnormal: list[str],
                  removed: list[str], owned: list[str] | None = None,
                  suppressions: list[tuple[str, str]] | None = None,
                  clinical_history: str = "", labels: dict[str, str] | None = None,
                  region_text: dict[str, str] | None = None, rules: dict[str, float] | None = None,
                  confirm: bool = False, scan_type: str = "", sides: bool = False) -> AssumedResult:
    """Every region of the sheet is answered (an empty list: nothing assumed), so the caller never falls back to
    the raw sheet. Every sentence is checked for contradiction against the whole dictation, untouched regions
    included: a finding the grouper filed under another region leaves its own region looking untouched (side review
    2026-10-12: "The spleen is normal" beside a misplaced splenic finding). A sentence is assumed unless the dictation
    covers (STATED_MIN) or contradicts (CONTRA_MIN) it or it says the same as a removed sentence or a row's (owned);
    one whose region's text hedges (HEDGE_MIN, region mode only) or that Jev half-reads as contradicted is assumed
    and listed in `flagged`.
    Every sentence not assumed is in `dropped` with its reason. `labels` (sentence ->
    structure label, template_normal_labels) names a subject-less sentence for the Jev check only; what is returned
    is always the template's own sentence. Labels are keyed by sentence: one sentence in two regions takes the first
    label (acceptable: the same words under two labels is rare and both labels name the sentence's structure).
    `region_text` (region -> its grouped sentences; Technique, General, Conclusion and unplaced excluded): a normal
    is covered (or flagged) only by its own region's sentences, so a conclusion or a bare "normal" covers nothing;
    contradiction is still asked on the whole dictation. None: the whole dictation answers both (older callers).

    A template's context rule (`suppressions`: condition, sentence) whose condition is met hides its sentence,
    empty dictation included (review R5). Every decision is condition_state's (seam 21), on the scan type: once per
    session on the clinical history alone, where `rules` is that decision as an earlier reply returned it (None:
    decide now, one call) and the reply's `rules` is what the caller keeps; `confirm`: at Confirm, every condition
    is re-decided on the history and the dictation, for this reply only. On a Jev failure nothing is assumed and no
    rules are returned.
    Every sentence is asked, a dictated-normal region's included.

    `sides` (quick sessions; templates are out of scope): each right/left pair in a region the dictation touches
    (its text, or an abnormal region) is asked, in a call made alongside the rows, whether the dictation reports a
    finding for it with no side given. Such a pair drops both sentences (ruling 1: a side-less finding is never
    left beside either side's normal, whatever Jev read as contradicted) and is returned in `side_asks`. A failure of
    that call changes nothing (side_failed)."""
    t0 = time.perf_counter()
    gone = list(dict.fromkeys(r for r in [*removed, *(owned or [])] if r.strip()))
    labels = labels or {}
    # A dictated-normal region is asked as an abnormal one is (review R2): the stated check removes what was said.
    asked = [(region, s) for region, sentences in region_normals.items() for s in sentences]
    out: dict[str, list[str]] = {r: [] for r in region_normals}
    flagged: dict[str, list[str]] = {r: [] for r in region_normals}
    dropped: dict[str, list[dict]] = {r: [] for r in region_normals}
    error = None
    asks: list[dict] = []
    side_failed = False
    cands: list[tuple[str, int, int]] = []
    conds = list(dict.fromkeys(c for c, _ in suppressions or []))
    blank = not dictation.strip()
    session = rules
    if asked:
        rule_calls = (1 if any(c not in (rules or {}) for c in conds) else 0) + \
            (1 if confirm and not blank and conds else 0)
        try:
            texts = [jev_text(s, labels[s]) if s in labels else s for _, s in asked]
            # Nothing dictated: Jev has no text to compare against and reads every sentence as hedged (live: an
            # empty dictation dropped them all), so no sentence is asked; a removed or owned sentence is matched by
            # its own words (no Jev same-meaning check).
            rows = _no_rows() if blank else (_ask(dictation, texts, gone) if region_text is None
                                             else _ask_by_region(dictation, asked, texts, gone, region_text))
            touched = set(abnormal) | {r for r, t in (region_text or {}).items() if t.strip()}
            cands = _side_candidates(asked, touched) if sides and not blank else []
            session, late, checks, side_p = await asyncio.gather(
                _session_rules(conds, scan_type, clinical_history, rules),
                _confirm_rules(conds, scan_type, clinical_history, dictation) if confirm else _nothing(), rows,
                _side_scores(dictation, asked, cands))
            met = {**session, **late}
            hidden = {norm_key(s) for c, s in suppressions or [] if met.get(c, 0.0) >= CONDITION_MIN}
            gone_keys = {norm_key(r) for r in gone}
            fates = [("removed" if norm_key(s) in gone_keys else "assumed") if checks is None else normal_fate(checks[i])
                     for i, (_, s) in enumerate(asked)]
            side_failed = side_p is None
            for (region, i, j), p in zip(cands, side_p or []):
                if p >= SIDE_MIN:
                    asks.append({"region": region, "sentences": [asked[i][1], asked[j][1]],
                                 "label": side_label(asked[i][1]), "score": round(p, 3)})
                    fates[i], fates[j] = (("side" if fates[k] in ("assumed", "flagged") else fates[k]) for k in (i, j))
            for i, (region, s) in enumerate(asked):
                fate = fates[i]
                if norm_key(s) in hidden:
                    dropped[region].append({"sentence": s, "reason": "rule"})
                elif fate in ("assumed", "flagged"):
                    out[region].append(s)
                    if fate == "flagged":
                        flagged[region].append(s)
                else:
                    dropped[region].append({"sentence": s, "reason": fate})
        except Exception as e:
            logger.warning("[stack.normals] %s: %s", type(e).__name__, str(e)[:200])
            error = f"{type(e).__name__}: {e}"
            session = None
            asks = []
            out = {r: [] for r in region_normals}
            flagged = {r: [] for r in region_normals}
            dropped = {r: [] for r in region_normals}
        calls = rule_calls if blank else _jev_calls(asked, region_text, rule_calls) + (1 if cands else 0)
        if calls:
            logger.log(logging.WARNING if error else logging.INFO,
                       "[stack.normals] jev_calls=%d failed=%s mode=%s side_asks=%d",
                       calls, error is not None, "whole" if region_text is None else "region", len(asks))
    return AssumedResult(assumed=out, flagged=flagged, dropped=dropped, rules=session,
                         confirm_recheck=bool(conds), side_asks=asks, side_failed=side_failed,
                         ms=int((time.perf_counter() - t0) * 1000), error=error)
