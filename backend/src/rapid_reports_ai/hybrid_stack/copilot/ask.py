"""Ask (spec §5.5), written as structured steps rather than native tool use. With a card in scope: Jev decides
whether the stored material answers the question, and the answer is grounded on the window Jev found it in; if not,
one targeted query within that guideline (in its own vocabulary, no case details), and a supported answer is kept as
a draft supplement (never material for a later answer). With no card: route the question to a guideline (normalised
and resolved like a matched card) or answer it as a general question."""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...enhancement_utils import _run_agent_with_model
from ...report_reconcile import QWEN
from . import jev as J
from . import matcher as M
from . import registry as R
from . import search as S
from . import tnm
from .fetch import OVERVIEW, resolve_guideline
from .types import Card, Chunk, Entry, GuidelineContent, Supplement

logger = logging.getLogger(__name__)

TIMEOUT_S = 12.0
GAP_URLS = 2           # pages the gap search reads
NOT_IN_GUIDELINE = "The guideline does not address this."
FROM_GENERAL = "From general knowledge:"

ROUTE_SYS = """A radiologist reporting a scan asks you a question. Decide what it is about.
- When answering it means applying, classifying, staging, scoring or managing something with a published radiology classification system or guideline (named or implied), set guideline to that system's usual name and version to its edition or year ("" if none), and leave answer empty: it is answered from the guideline itself. When KNOWN GUIDELINES lists it, reuse the listed name and version exactly.
- For TNM staging of a primary malignant tumour, set guideline "TNM", version "9" and site to exactly one name from TNM SITES.
- Otherwise set guideline to "" and answer in 2-4 plain sentences of British English, using the CASE for context. Say when something is uncertain or varies by local practice."""

GROUNDED_SYS = """Answer a radiologist's question about one published guideline in 2-4 plain sentences of British English. Use only the MATERIAL for any criterion, category, threshold or interval, and say which part of the guideline it comes from. Use the CASE only to make the answer specific. If the MATERIAL does not answer the question, say so in one sentence."""

PHRASE_SYS = """Write one web search phrase (at most 10 words) that would find the part of the named guideline answering the radiologist's question. Use the guideline's name, version and its own terms; never patient details, ages, sizes, measurements, sides, dates or anything specific to the case. Reply with the phrase only."""

GENERAL_SYS = """Answer a radiologist's question in 2-3 plain sentences of British English from general radiology knowledge, using the CASE for context. Say when something is uncertain or varies by local practice."""

# The gap phrase's backstop, after the vocabulary filter: never a number, a unit, an age, a side or a demographic.
_NUMBER_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                 "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
                 "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "half", "quarter"}
_UNITS = {"mm", "cm", "m", "ml", "kg", "millimetre", "millimetres", "millimeter", "millimeters", "centimetre",
          "centimetres", "centimeter", "centimeters", "yo", "yrs", "yr", "year", "years", "old", "aged", "months",
          "month", "weeks", "week"}
_CASEY = S._CASEY_WORDS | _NUMBER_WORDS | _UNITS


def _vocab(e: Entry, chunks: list[Chunk]) -> set[str]:
    """Every normalised token the registry holds for this guideline: the gap phrase may only use these."""
    parts = [e.name, e.version, e.content.summary, e.content.applies_to]
    for b in e.content.branches:
        parts += [b.name, b.rule] + [f"{o.when} {o.classification} {o.recommendation}" for o in b.outputs]
    parts += [c.text for c in chunks]
    return set(R.norm(" ".join(parts)).split())


def _safe_phrase(phrase: str, name: str, version: str, vocab: set[str] | None = None) -> str:
    """The search API never sees case text (spec §2.18): the identity goes through S.safe_identity; a phrase token
    is kept only when it is in the guideline's own vocabulary (`vocab`), is not a number other than the version and
    is not a unit, age, side or demographic word. Fewer than 2 tokens left: the bare identity."""
    name, version = S.safe_identity(name, version)
    ident = " ".join(f"{name} {version}".split())
    id_toks = set(R.norm(ident).split())
    ver_toks = set(R.norm(version).split())
    kept, keywords = 0, []
    for t in R.norm(phrase).split():
        if any(ch.isdigit() for ch in t) and t not in ver_toks:
            continue
        if t in _CASEY or (vocab is not None and t not in vocab and t not in id_toks):
            continue
        kept += 1
        if t not in id_toks and t not in keywords:
            keywords.append(t)
    if kept < 2 or not keywords:
        return ident
    return f"{ident} {' '.join(keywords)}"


class Context(BaseModel):
    scan_type: str = ""
    history: str = ""
    findings: str = ""


class QA(BaseModel):
    question: str
    answer: str


class RawRoute(BaseModel):
    guideline: str = ""
    version: str = ""
    site: str = ""
    answer: str = ""


class AskResult(BaseModel):
    kind: Literal["card", "general"]
    answer: str
    key: str | None = None
    card: Card | None = None
    entry: Entry | None = None
    searched: bool = False        # a targeted query ran for this question
    supported: bool = True        # the answer is grounded in guideline material
    loading: bool = False         # the route timed out: a general answer now, the guideline still resolving
    error: str | None = None


def _ctx(ctx: Context, history: list[QA]) -> str:
    s = f"CASE:\nScan: {ctx.scan_type}\nClinical history: {ctx.history or 'none given'}\nFindings:\n{ctx.findings}"
    if history:
        s += "\n\nEARLIER QUESTIONS:\n" + "\n".join(f"Q: {h.question}\nA: {h.answer}" for h in history[-3:])
    return s


async def _text(system: str, user: str) -> str:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=str, system_prompt=system, user_prompt=user, api_key="",
        model_settings={"temperature": 0.2, "max_tokens": 2000, "reasoning_effort": "low"}), TIMEOUT_S)
    return str(r.output).strip()


async def _route(question: str, ctx: Context, history: list[QA], known: str = "") -> RawRoute:
    sites = "\n".join(f"- {x}" for x in tnm.sites())
    prompt = _ctx(ctx, history)
    if known:
        prompt += f"\n\nKNOWN GUIDELINES (name version):\n{known}"
    prompt += f"\n\nTNM SITES:\n{sites}\n\nQUESTION: {question}"
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=RawRoute, system_prompt=ROUTE_SYS, user_prompt=prompt, api_key="",
        model_settings={"temperature": 0, "max_tokens": 2000, "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


async def _grounded(question: str, material: str, ctx: Context, history: list[QA]) -> str:
    return await _text(GROUNDED_SYS, f"MATERIAL:\n{material}\n\n{_ctx(ctx, history)}\n\nQUESTION: {question}")


async def _search_phrase(question: str, name: str, version: str) -> str:
    out = await _text(PHRASE_SYS, f"GUIDELINE: {name} {version}\nQUESTION: {question}")
    return (out.splitlines() or [""])[0].strip().strip('"')[:120]


async def _general_answer(question: str, ctx: Context, history: list[QA]) -> str:
    return await _text(GENERAL_SYS, f"{_ctx(ctx, history)}\n\nQUESTION: {question}")


def _known(db: Session) -> str:
    return "\n".join(f"- {n} {v or ''}".rstrip() for _, n, v in R.known(db))


def _head(e: Entry) -> str:
    """The structured part of an entry: summary and checked branches."""
    parts = [e.content.summary]
    for b in e.content.checked():
        parts.append(f"{b.name}: {b.rule}\n" + "\n".join(
            f"- {o.when}: {o.classification} {o.recommendation}".rstrip() for o in b.outputs))
    return "\n\n".join(p for p in parts if p)


def _chunks_text(chunks: list[Chunk]) -> str:
    """Chunks with their "[url]" markers, so Jev's windows break between pages and a window names its page."""
    return "\n\n".join(f"[{c.url}]\n{c.text}" for c in chunks)


def _material(e: Entry, chunks: list[Chunk]) -> str:
    """What Jev reads for a stored entry: the head, then the source chunks. A supplement's answer is never material
    (it is model text); only its quote, when it has one, is."""
    quotes = [f"[{s.url}]\n{s.quote}" for s in e.content.supplements if s.quote]
    return "\n\n".join(p for p in [_head(e), *quotes, _chunks_text(chunks)] if p)


def _ground(head: str, window: str) -> str:
    """The head plus the window Jev found the answer in, capped at one Jev window."""
    text = window if not head or window.startswith(head) else f"{head}\n\n{window}"
    return text[:J.STATE_MAX]


def _err(key: str | None, ex: Exception) -> AskResult:
    return AskResult(kind="card" if key else "general", key=key, answer="", supported=False, error=type(ex).__name__)


async def _in_card(db: Session, question: str, key: str, ctx: Context, history: list[QA]) -> AskResult:
    if tnm.is_tnm(key):   # offline staging data: grounded in it, never gated or gap-searched
        site = tnm.site_for(key)
        if site is None:
            return AskResult(kind="card", key=key, answer="", supported=False, error="unknown guideline")
        return AskResult(kind="card", key=key, entry=tnm.entry(site),
                         answer=await _grounded(question, tnm.material(site)[:J.STATE_MAX], ctx, history))
    row = R.by_key(db, key)
    if row is None:
        return AskResult(kind="card", key=key, answer="", supported=False, error="unknown guideline")
    e = R.entry(row)
    stored = R.chunks(row)
    head, material, vocab = _head(e), _material(e, stored), _vocab(e, stored)
    db.rollback()   # nothing pending: release the connection before the Jev and model awaits
    if material:
        score, window = await J.answers_best(material, question)
        if score >= J.ANSWERS_MIN:
            return AskResult(kind="card", key=key, entry=e,
                             answer=await _grounded(question, _ground(head, window), ctx, history))
    phrase = _safe_phrase(await _search_phrase(question, e.name, e.version), e.name, e.version, vocab)
    chunks, sources = await S.gather([phrase], branch="", exclude={c.url for c in stored}, name=e.name,
                                     version=e.version, title=e.publication.title, top=GAP_URLS)
    if chunks:
        about = " ".join(f"{e.name} {e.version}".split())
        score, window = await J.answers_best(_chunks_text(chunks), question, about=about)
        if score >= J.ANSWERS_MIN:
            answer = await _grounded(question, _ground(head, window), ctx, history)
            url = next((c.url for c in chunks if f"[{c.url}]" in window), chunks[0].url)
            entry = e
            try:   # storing is a bonus: a failure still returns the grounded answer
                R.upsert(db, key=key, name=e.name, version=e.version, aliases=[], publication=None,
                         content=GuidelineContent(supplements=[Supplement(question=question, answer=answer, url=url)]),
                         sources=sources, chunks=chunks)
                entry = R.entry(R.by_key(db, key))
            except Exception as ex:
                logger.warning("[copilot.ask] supplement not stored (%s): %s", key, type(ex).__name__)
                db.rollback()
            return AskResult(kind="card", key=key, entry=entry, answer=answer, searched=True)
    general = await _general_answer(question, ctx, history)
    return AskResult(kind="card", key=key, entry=e, answer=f"{NOT_IN_GUIDELINE} {FROM_GENERAL} {general}".strip(),
                     searched=True, supported=False)


async def _card_branch(card: Card, entry: Entry, finding: str, history: str) -> Card:
    """An ask card is openable: the entry's branches as its skeleton, and a branch (Jev's pick among the entry's
    branches, else the Overview when stored) when the route gave none."""
    names = [b.name for b in entry.content.branches]
    branch = card.branch
    if not branch and entry.content.checked():
        branch = await M.pick_branch(finding, entry, history) or (OVERVIEW if entry.content.branch(OVERVIEW) else "")
    return card.model_copy(update={"key": entry.key, "known": True, "status": entry.status, "branch": branch,
                                   "skeleton": names or card.skeleton})


async def ask(db: Session, question: str, key: str | None, ctx: Context, history: list[QA],
              finding_id: str = "") -> AskResult:
    """Never raises: a failure (model, Jev outage, search, DB) returns an error the panel shows with a retry.
    Ends the caller session's transaction (resolve_guideline does too): the caller must have no pending writes."""
    try:
        if key:
            return await _in_card(db, question, key, ctx, history)
        raw = await _route(question, ctx, history, _known(db))
        if not raw.guideline.strip():
            return AskResult(kind="general", answer=raw.answer.strip())
        is_tnm = "tnm" in R.norm(raw.guideline).split()
        name = "TNM" if is_tnm else raw.guideline
        finding = f"{question}\n{ctx.findings}".strip()
        # An explicit staging question needs no matching finding: the closed site list still applies, the case gate not.
        card = await M.card_for(db, name, raw.version, finding_id or "q", finding, ctx.history, raw.site,
                                gate=not is_tnm)
        entry = await resolve_guideline(db, card) if card else None
        if card is None or entry is None:
            return AskResult(kind="general", answer=await _general_answer(question, ctx, history), supported=False)
        card = await _card_branch(card, entry, finding, ctx.history)
        res = await _in_card(db, question, entry.key, ctx, history)
        return res.model_copy(update={"card": card})
    except Exception as ex:
        logger.warning("[copilot.ask] %s: %s", type(ex).__name__, str(ex)[:200])
        try:
            db.rollback()
        except Exception:
            pass
        return _err(key, ex)
