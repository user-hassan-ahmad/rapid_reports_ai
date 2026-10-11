"""Checklist rows (checklist spec §4): the questions a dictated finding sets off, and the referral question.

The chain on every update (spec §4.2): Qwen writes the rows (arm D of the checklist lab); the production splitter
splits multi-claim sentences; one Jev call drops what the dictation already says or contradicts and what the
radiologist removed; code applies the limits. Finding rows are asked, never assumed: nothing here reaches the
report until the radiologist answers it."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict

from pydantic import BaseModel

from ..enhancement_utils import _run_agent_with_model
from ..report_reconcile import QWEN, _MEASUREMENT, _split_bundled
from .jev_stack import CONTRA_MIN, ask_rows, row_fate
from .schemas import scan_key

logger = logging.getLogger(__name__)

MAX_SENTENCES = 2          # per row: each is read before a tap asserts it (spec §3.3)
MAX_ROWS_PER_REGION = 2    # open finding rows
MAX_ROWS = 4               # open rows per case, referral rows included
MAX_REFERRALS = 2          # one per question the history asks ("rule out haemorrhage and solid organ injury")
WRITER_TIMEOUT_S = 8.0
_CACHE: "OrderedDict[tuple, RawOutput]" = OrderedDict()   # the writer's rows only: checks run per dictation
_CACHE_MAX = 256

# Arm D of the checklist lab (spec §10.1), in two sections decoded in order (hand read 2026-10-12): the questions
# the history asks first, then the checks each finding sets off. The section is the tag: a referral question can
# only appear in referral_questions, so no code heuristic decides it.
WRITER_SYS = """You are a radiology decision-support assistant reading a radiologist's dictation while they report the scan, with the images in front of them. Work in two steps and fill the two sections in this order.

STEP 1 - referral_questions: the questions the clinical history explicitly asks that the dictation does not yet answer (0-2, one per question, in the order asked). A history asks a question only when it names a suspected diagnosis to confirm or exclude ("?", "query", "rule out", "exclude", "assess for", "suspected"). A history that only describes symptoms, an injury mechanism, risk factors, or a known diagnosis being staged or followed up asks nothing here: return referral_questions empty (the findings' checks cover the rest). Never a complication the history does not name, never an alternative diagnosis. When REFERRAL QUESTIONS are listed in the case, they are already asked: return referral_questions empty. Each:
- question: at most 12 words, directed at the images, ending with "?"
- region: the region it belongs to, from REGIONS, or "" when it spans regions
- answers: first the one statement that answers this question itself (never a sign of something else), worded as the history asks it (a history asking to exclude injury to several organs is answered by one statement about that injury, not one per organ), then at most one more only when it adds a separate check.

STEP 2 - finding_checks: for each dictated abnormal finding, decide what a consultant checks on THIS scan once that finding is reported, and write the statements they make when those checks are normal. Never repeat a referral question, nor ask about the same structure and complication twice.
THRESHOLD: write a check only when all apply:
- a dictated finding implies a related structure, extension, spread or complication that this scan shows;
- its presence or absence changes the diagnosis, urgency, stage or next management step;
- the dictation has not already assessed it (a structure named with a qualifier, a measurement or a "no X" is assessed).
ONE CHECK PER ROOT FINDING: all checks stemming from one finding form one item; separate findings get separate items. Findings that together imply one check, in the same or different regions, form one item.
Order by clinical urgency, most critical first. Return no checks when nothing meets the threshold. Each:
- source_text: the shortest verbatim phrase of the triggering finding (3-6 words, an exact substring of the dictation)
- region: the region of that finding, from REGIONS
- question: at most 12 words, the check directed at the images, ending with "?"
- rationale: 1-2 sentences: why this check matters for this finding on this scan
- answers: 1-3 pertinent negatives, the most decisive first.

BOTH SECTIONS:
- MODALITY: only what this exact scan type and protocol can show; never an enhancement, phase or sequence the scan lacks.
- NEVER deny anything dictated, its expected consequence, or a feature of a dictated diagnosis (its typical signs, or its expected effect on neighbouring structures): those are already implied.
- Every answer is one short report sentence in British English that names one absent finding and nothing else: no reason clause (never "to suggest", "in keeping with" or "which"), never the word "or", no list.
- REMOVED BY THE RADIOLOGIST: never propose a statement listed there, or an equivalent."""


class RawReferral(BaseModel):
    question: str = ""
    region: str = ""
    answers: list[str] = []


class RawFinding(BaseModel):
    source_text: str = ""
    region: str = ""
    question: str = ""
    rationale: str = ""
    answers: list[str] = []


class RawOutput(BaseModel):
    referral_questions: list[RawReferral] = []   # decoded first
    finding_checks: list[RawFinding] = []


class Referral(BaseModel):
    """A referral row fixed for the session (the first reply's referral_questions), sent back on every update."""
    question: str
    region: str = ""
    sentences: list[str] = []


class Item(BaseModel):
    id: str
    kind: str              # finding | referral
    region: str
    question: str
    why: str = ""
    sentences: list[str]   # still to be answered (at most MAX_SENTENCES)
    answered: bool = False # the dictation answered every sentence: the UI folds the row


class ItemsResult(BaseModel):
    items: list[Item]
    capped: list[Item] = []
    contradicted: list[str] = []   # tapped sentences the dictation now contradicts: the radiologist re-answers
    cached: bool = False
    ms: int = 0
    error: str | None = None


def clear_cache() -> None:
    _CACHE.clear()


def _norm(s: str) -> str:
    return " ".join(s.lower().strip().rstrip(".").split())


def _sentence(s: str) -> str:
    s = " ".join(s.split()).strip()
    return s if not s or s.endswith((".", "?", "!")) else s + "."


def user_prompt(scan_type: str, history: str, regions: list[str], dictation: str, not_assessable: str,
                removed: list[str], referrals: list[Referral] | None = None) -> str:
    s = (f"SCAN TYPE: {scan_type}\nCLINICAL HISTORY: {history or 'none given'}\nREGIONS: {', '.join(regions)}\n\n"
         f"DICTATION:\n{dictation.strip() or '(nothing dictated yet)'}")
    if referrals:
        s += "\n\nREFERRAL QUESTIONS (already asked of the radiologist):\n" + "\n".join(f"- {r.question}" for r in referrals)
    if not_assessable.strip():
        s += f"\n\nNOT ASSESSABLE ON THIS SCAN:\n{not_assessable.strip()}"
    if removed:
        s += "\n\nREMOVED BY THE RADIOLOGIST:\n" + "\n".join(f"- {r}" for r in removed)
    return s


async def _write(scan_type, history, regions, dictation, not_assessable, removed, referrals) -> RawOutput:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=RawOutput, system_prompt=WRITER_SYS,
        user_prompt=user_prompt(scan_type, history, regions, dictation, not_assessable, removed, referrals), api_key="",
        model_settings={"temperature": 0, "max_tokens": 3000, "reasoning_effort": "none"}), WRITER_TIMEOUT_S)
    return r.output


def _key(scan_type, history, regions, abnormal, referrals) -> tuple:
    """Removed sentences are not in the key: Jev filters them on every update, so a × costs no new writer call."""
    return (scan_key(scan_type), _norm(history), tuple(_norm(a) for a in abnormal if a.strip()), tuple(regions),
            tuple(_norm(r.question) for r in referrals or []))


def _id(kind: str, region: str, question: str) -> str:
    return hashlib.sha1(f"{kind}|{region}|{_norm(question)}".encode()).hexdigest()[:12]


def _clean(sentences: list[str]) -> list[str]:
    # A row only ever carries normal statements: a number nobody measured is never offered
    # (lab p1: a writer slip offered "A 5 mm intrauterine gestational sac is seen").
    return [_sentence(n) for n in sentences if n.strip() and not _MEASUREMENT.search(n)]


def _rows(raw: RawOutput, referrals: list[Referral] | None = None) -> list[Item]:
    """Referral rows: the session's fixed referrals when given (the first reply's), otherwise this reply's
    referral_questions; then the finding rows. The section decides the kind; nothing is guessed."""
    refs = ([(r.question, r.region, r.sentences, "") for r in referrals] if referrals is not None
            else [(r.question, r.region, r.answers, "") for r in raw.referral_questions])
    out = [Item(id=_id("referral", region, q), kind="referral", region=region.strip(), question=q.strip(), why=why,
                sentences=_clean(sentences)) for q, region, sentences, why in refs[:MAX_REFERRALS] if q.strip()]
    out += [Item(id=_id("finding", f.region, f.question), kind="finding", region=f.region.strip(),
                 question=f.question.strip(), why=f.rationale.strip(), sentences=_clean(f.answers))
            for f in raw.finding_checks if f.question.strip()]
    return out


async def _split(rows: list[Item]) -> None:
    flat = [s for r in rows for s in r.sentences]
    try:
        parts = await _split_bundled(flat)
    except Exception as e:  # keep the sentences as written
        logger.warning("[stack.items.split] %s: %s", type(e).__name__, str(e)[:200])
        return
    k = 0
    for r in rows:
        n = len(r.sentences)
        r.sentences = [_sentence(p) for ps in parts[k:k + n] for p in ps]
        k += n


def _dedupe(rows: list[Item]) -> list[Item]:
    seen: set = set()
    out = []
    for r in rows:
        keep = []
        for s in r.sentences:
            if _norm(s) not in seen:
                seen.add(_norm(s))
                keep.append(s)
        if keep:
            r.sentences = keep
            out.append(r)
    return out


async def _check(rows: list[Item], dictation: str, removed: list[str], tapped: list[str]) -> list[str]:
    """Row sentences: drop what the dictation says or contradicts and what was removed. Tapped sentences (already the
    radiologist's answers) are asked in the same call: those the dictation now contradicts are returned."""
    flat = [s for r in rows for s in r.sentences]
    contradicted: list[str] = []
    try:
        checks = await ask_rows(dictation, flat + tapped, removed)
        fates = [row_fate(c) for c in checks[:len(flat)]]
        contradicted = [t for t, c in zip(tapped, checks[len(flat):]) if c.contra >= CONTRA_MIN]
    except Exception as e:  # rows as written; removed by exact match only
        logger.warning("[stack.items.checks] %s: %s", type(e).__name__, str(e)[:200])
        gone = {_norm(r) for r in removed}
        fates = ["removed" if _norm(s) in gone else "keep" for s in flat]
    k = 0
    for r in rows:
        n = len(r.sentences)
        mine = fates[k:k + n]
        k += n
        r.sentences = [s for s, f in zip(r.sentences, mine) if f == "keep"]
        if n and not r.sentences and "answered" in mine:
            r.answered = True
    return contradicted


def _limit(rows: list[Item]) -> tuple[list[Item], list[Item]]:
    out, capped, per_region, total = [], [], {}, 0
    for r in rows:
        if r.answered:
            out.append(r)
            continue
        if not r.sentences:
            continue
        r.sentences = r.sentences[:MAX_SENTENCES]
        over_region = r.kind == "finding" and per_region.get(r.region, 0) >= MAX_ROWS_PER_REGION
        if over_region or total >= MAX_ROWS:
            capped.append(r)
            continue
        if r.kind == "finding":
            per_region[r.region] = per_region.get(r.region, 0) + 1
        total += 1
        out.append(r)
    return out, capped


async def update(scan_type: str, history: str, regions: list[str], dictation: str, abnormal: list[str],
                 not_assessable: str = "", removed: list[str] | None = None,
                 tapped: list[str] | None = None, referrals: list[Referral] | None = None) -> ItemsResult:
    """The open rows for this dictation. referrals: the session's fixed referral rows (None on the first call, whose
    referral_questions then become them). The writer's reply is cached per (scan, history, abnormal sentences,
    regions, referral questions); the splitter and the checks always run on the current dictation and removals."""
    t0 = time.perf_counter()
    removed = [r for r in (removed or []) if r.strip()]
    key = _key(scan_type, history, regions, abnormal, referrals)
    cached = key in _CACHE
    if cached:
        _CACHE.move_to_end(key)
        raw = _CACHE[key]
    else:
        try:
            raw = await _write(scan_type, history, regions, dictation, not_assessable, removed, referrals)
        except Exception as e:  # fail open: no rows
            logger.warning("[stack.items] %s: %s", type(e).__name__, str(e)[:200])
            return ItemsResult(items=[], ms=int((time.perf_counter() - t0) * 1000), error=f"{type(e).__name__}: {e}")
        _CACHE[key] = raw
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    rows = _rows(raw, referrals)
    await _split(rows)
    rows = _dedupe(rows)
    contradicted = await _check(rows, dictation, removed, [t for t in (tapped or []) if t.strip()])
    items, capped = _limit(rows)
    return ItemsResult(items=items, capped=capped, contradicted=contradicted, cached=cached,
                       ms=int((time.perf_counter() - t0) * 1000))
