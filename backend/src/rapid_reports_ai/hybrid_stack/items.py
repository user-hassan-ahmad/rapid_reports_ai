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
from .jev_stack import ask_rows, row_fate
from .schemas import scan_key

logger = logging.getLogger(__name__)

MAX_SENTENCES = 2          # per row: each is read before a tap asserts it (spec §3.3)
MAX_ROWS_PER_REGION = 2    # open finding rows
MAX_ROWS = 4               # open rows per case, the referral row included
WRITER_TIMEOUT_S = 8.0
_CACHE: "OrderedDict[tuple, list[RawItem]]" = OrderedDict()   # the writer's rows only: checks run per dictation
_CACHE_MAX = 256

# Arm D of the checklist lab (spec §10.1): the IntelliPrompts framing, trimmed to structural rules.
WRITER_SYS = """You are a radiology decision-support assistant reading a radiologist's dictation while they report the scan, with the images in front of them. For each dictated abnormal finding, decide what a consultant checks on THIS scan once that finding is reported, and write the statements they make when those checks are normal.

THRESHOLD: write an item only when all apply:
- a dictated finding implies a related structure, extension, spread or complication that this scan shows;
- its presence or absence changes the diagnosis, urgency, stage or next management step;
- the dictation has not already assessed it (a structure named with a qualifier, a measurement or a "no X" is assessed).

ONE ITEM PER ROOT FINDING: all checks stemming from one finding form one item; separate findings get separate items. Findings that together imply one check, in the same or different regions, form one item.

MODALITY: only what this exact scan type and protocol can show; never an enhancement, phase or sequence the scan lacks.

Order items by clinical urgency, most critical first. Return no items when nothing meets the threshold.

NEVER deny anything dictated, its expected consequence, or a feature of a dictated diagnosis (its typical signs, or its expected effect on neighbouring structures): those are already implied.

Each item:
- source_text: the shortest verbatim phrase of the triggering finding (3-6 words, an exact substring of the dictation)
- region: the region of that finding, from REGIONS
- question: at most 12 words, the check directed at the images, ending with "?"
- rationale: 1-2 sentences: why this check matters for this finding on this scan
- negatives: 1-3 pertinent negatives, the most decisive first; each one short report sentence that names one absent finding and nothing else: no reason clause, never the word "or", no list.

REFERRAL QUESTION: the clinical history may ask about a diagnosis the dictated findings do not answer. When the dictation does not address it, add one separate item for it (never merged into a finding's item) even though no dictated finding implies it: source_text empty, region the region it belongs to (it may be outside REGIONS), negatives the statements that answer it when normal. Only the diagnosis asked about and its complications that change management; never an alternative diagnosis the history does not raise.

REMOVED BY THE RADIOLOGIST: never propose a statement listed there, or an equivalent."""


class RawItem(BaseModel):
    source_text: str = ""
    region: str = ""
    question: str = ""
    rationale: str = ""
    negatives: list[str] = []


class RawItems(BaseModel):
    items: list[RawItem]


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
                removed: list[str]) -> str:
    s = (f"SCAN TYPE: {scan_type}\nCLINICAL HISTORY: {history or 'none given'}\nREGIONS: {', '.join(regions)}\n\n"
         f"DICTATION:\n{dictation.strip() or '(nothing dictated yet)'}")
    if not_assessable.strip():
        s += f"\n\nNOT ASSESSABLE ON THIS SCAN:\n{not_assessable.strip()}"
    if removed:
        s += "\n\nREMOVED BY THE RADIOLOGIST:\n" + "\n".join(f"- {r}" for r in removed)
    return s


async def _write(scan_type, history, regions, dictation, not_assessable, removed) -> list[RawItem]:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=RawItems, system_prompt=WRITER_SYS,
        user_prompt=user_prompt(scan_type, history, regions, dictation, not_assessable, removed), api_key="",
        model_settings={"temperature": 0, "max_tokens": 3000, "reasoning_effort": "none"}), WRITER_TIMEOUT_S)
    return r.output.items


def _key(scan_type, history, regions, abnormal) -> tuple:
    """Removed sentences are not in the key: Jev filters them on every update, so a × costs no new writer call."""
    return scan_key(scan_type), _norm(history), tuple(_norm(a) for a in abnormal if a.strip()), tuple(regions)


def _id(kind: str, region: str, question: str) -> str:
    return hashlib.sha1(f"{kind}|{region}|{_norm(question)}".encode()).hexdigest()[:12]


def _rows(raw: list[RawItem]) -> list[Item]:
    out, referral = [], False
    for it in raw:
        kind = "referral" if not it.source_text.strip() else "finding"
        if kind == "referral":
            if referral:
                continue
            referral = True
        out.append(Item(id=_id(kind, it.region, it.question), kind=kind, region=it.region.strip(),
                        question=it.question.strip(), why=it.rationale.strip(),
                        # A row only ever carries normal statements: a number nobody measured is never offered
                        # (lab p1: a writer slip offered "A 5 mm intrauterine gestational sac is seen").
                        sentences=[_sentence(n) for n in it.negatives if n.strip() and not _MEASUREMENT.search(n)]))
    return sorted(out, key=lambda i: i.kind != "referral")   # the referral row leads; finding order kept


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


async def _check(rows: list[Item], dictation: str, removed: list[str]) -> None:
    flat = [s for r in rows for s in r.sentences]
    try:
        fates = [row_fate(c) for c in await ask_rows(dictation, flat, removed)]
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
                 not_assessable: str = "", removed: list[str] | None = None) -> ItemsResult:
    """The open rows for this dictation. The writer's rows are cached per (scan, history, abnormal sentences,
    regions); the splitter and the checks always run on the current dictation and removed sentences."""
    t0 = time.perf_counter()
    removed = [r for r in (removed or []) if r.strip()]
    key = _key(scan_type, history, regions, abnormal)
    cached = key in _CACHE
    if cached:
        _CACHE.move_to_end(key)
        raw = list(_CACHE[key])
    else:
        try:
            raw = await _write(scan_type, history, regions, dictation, not_assessable, removed)
        except Exception as e:  # fail open: no rows
            logger.warning("[stack.items] %s: %s", type(e).__name__, str(e)[:200])
            return ItemsResult(items=[], ms=int((time.perf_counter() - t0) * 1000), error=f"{type(e).__name__}: {e}")
        _CACHE[key] = list(raw)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    rows = _rows(raw)
    await _split(rows)
    rows = _dedupe(rows)
    await _check(rows, dictation, removed)
    items, capped = _limit(rows)
    return ItemsResult(items=items, capped=capped, cached=cached, ms=int((time.perf_counter() - t0) * 1000))
