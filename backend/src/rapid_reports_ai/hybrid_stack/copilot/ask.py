"""Ask (spec §5.5), written as structured steps rather than native tool use. With a card in scope: Jev decides
whether the stored material answers the question; if not, one targeted query within that guideline (phrased in its
own vocabulary, no case details), and a supported answer is kept as a supplement. With no card: route the question
to a guideline (normalised and resolved like a matched card) or answer it as a general question."""
from __future__ import annotations

import asyncio
import logging
import re
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
from .fetch import resolve_guideline
from .types import Card, Entry, GuidelineContent, Supplement

logger = logging.getLogger(__name__)

TIMEOUT_S = 12.0
MATERIAL_MAX = 16000   # chars of guideline material a grounded answer reads
NOT_IN_GUIDELINE = "The guideline does not address this."

ROUTE_SYS = """A radiologist reporting a scan asks you a question. Decide what it is about.
- When answering it means applying, classifying, staging, scoring or managing something with a published radiology classification system or guideline (named or implied), set guideline to that system's usual name and version to its edition or year ("" if none), and leave answer empty: it is answered from the guideline itself.
- For TNM staging of a primary malignant tumour, set guideline "TNM", version "9" and site to exactly one name from TNM SITES.
- Otherwise set guideline to "" and answer in 2-4 plain sentences of British English, using the CASE for context. Say when something is uncertain or varies by local practice."""

GROUNDED_SYS = """Answer a radiologist's question about one published guideline in 2-4 plain sentences of British English. Use only the MATERIAL for any criterion, category, threshold or interval, and say which part of the guideline it comes from. Use the CASE only to make the answer specific. If the MATERIAL does not answer the question, say so in one sentence."""

PHRASE_SYS = """Write one web search phrase (at most 10 words) that would find the part of the named guideline answering the radiologist's question. Use the guideline's name, version and its own terms; never patient details, ages, sizes, measurements, sides, dates or anything specific to the case. Reply with the phrase only."""

GENERAL_SYS = """Answer a radiologist's question in 2-3 plain sentences of British English from general radiology knowledge, using the CASE for context. Say when something is uncertain or varies by local practice."""

_CASEY = re.compile(r"\d|\b(left|right|bilateral|year[- ]old|yo|male|female|man|woman|patient)\b", re.I)


def _safe_phrase(phrase: str, name: str, version: str) -> str:
    """The search API never sees case text (spec §2.18): a phrase carrying digits other than the version, sides or
    demographics falls back to the guideline's identity alone; a phrase without the guideline's name gains it."""
    ident = " ".join(f"{name} {version}".split())
    phrase = " ".join(phrase.split())
    rest = phrase.replace(version, "") if version else phrase
    if not phrase or _CASEY.search(rest):
        return ident
    return phrase if R.norm(name) in R.norm(phrase) else f"{ident} {phrase}"


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


async def _route(question: str, ctx: Context, history: list[QA]) -> RawRoute:
    sites = "\n".join(f"- {x}" for x in tnm.sites())
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=RawRoute, system_prompt=ROUTE_SYS,
        user_prompt=f"{_ctx(ctx, history)}\n\nTNM SITES:\n{sites}\n\nQUESTION: {question}", api_key="",
        model_settings={"temperature": 0, "max_tokens": 2000, "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


async def _grounded(question: str, material: str, ctx: Context, history: list[QA]) -> str:
    return await _text(GROUNDED_SYS, f"MATERIAL:\n{material[:MATERIAL_MAX]}\n\n{_ctx(ctx, history)}\n\nQUESTION: {question}")


async def _search_phrase(question: str, name: str, version: str) -> str:
    out = await _text(PHRASE_SYS, f"GUIDELINE: {name} {version}\nQUESTION: {question}")
    return (out.splitlines() or [""])[0].strip().strip('"')[:120]


async def _general_answer(question: str, ctx: Context, history: list[QA]) -> str:
    return await _text(GENERAL_SYS, f"{_ctx(ctx, history)}\n\nQUESTION: {question}")


def _material(e: Entry, chunks) -> str:
    """Everything the registry holds for one guideline: summary, checked branches, supplements, source chunks."""
    parts = [e.content.summary]
    for b in e.content.checked():
        parts.append(f"{b.name}: {b.rule}\n" + "\n".join(
            f"- {o.when}: {o.classification} {o.recommendation}".rstrip() for o in b.outputs))
    parts += [f"Q: {s.question}\nA: {s.answer}" for s in e.content.supplements]
    parts += [c.text for c in chunks]
    return "\n\n".join(p for p in parts if p)


async def _in_card(db: Session, question: str, key: str, ctx: Context, history: list[QA]) -> AskResult:
    if tnm.is_tnm(key):   # offline staging data: grounded in it, never gated or gap-searched
        site = tnm.site_for(key)
        if site is None:
            return AskResult(kind="card", key=key, answer="", supported=False, error="unknown guideline")
        return AskResult(kind="card", key=key, entry=tnm.entry(site),
                         answer=await _grounded(question, tnm.material(site), ctx, history))
    row = R.by_key(db, key)
    if row is None:
        return AskResult(kind="card", key=key, answer="", supported=False, error="unknown guideline")
    e = R.entry(row)
    stored = R.chunks(row)
    material = _material(e, stored)
    db.rollback()   # nothing pending: release the connection before the Jev and model awaits
    if material and await J.answers(material, question) >= J.ANSWERS_MIN:
        return AskResult(kind="card", key=key, entry=e, answer=await _grounded(question, material, ctx, history))
    phrase = _safe_phrase(await _search_phrase(question, e.name, e.version), e.name, e.version)
    chunks, sources = await S.gather([phrase], branch="", exclude={c.url for c in stored}, name=e.name,
                                     version=e.version, title=e.publication.title)
    new = "\n\n".join(c.text for c in chunks)
    if new and await J.answers(new, question) >= J.ANSWERS_MIN:
        answer = await _grounded(question, new, ctx, history)
        R.upsert(db, key=key, name=e.name, version=e.version, aliases=[], publication=None,
                 content=GuidelineContent(supplements=[Supplement(question=question, answer=answer,
                                                                  quote=chunks[0].text[:300], url=chunks[0].url)]),
                 sources=sources, chunks=chunks)
        return AskResult(kind="card", key=key, entry=R.entry(R.by_key(db, key)), answer=answer, searched=True)
    general = await _general_answer(question, ctx, history)
    return AskResult(kind="card", key=key, entry=e, answer=f"{NOT_IN_GUIDELINE} {general}".strip(), searched=True,
                     supported=False)


async def ask(db: Session, question: str, key: str | None, ctx: Context, history: list[QA],
              finding_id: str = "") -> AskResult:
    """Never raises: a failure (model, Jev outage, search, DB) returns an error the panel shows with a retry.
    Ends the caller session's transaction (resolve_guideline does too): the caller must have no pending writes."""
    try:
        if key:
            return await _in_card(db, question, key, ctx, history)
        raw = await _route(question, ctx, history)
        if not raw.guideline.strip():
            return AskResult(kind="general", answer=raw.answer.strip())
        finding = f"{question}\n{ctx.findings}".strip()
        card = await M.card_for(db, raw.guideline, raw.version, finding_id or "q", finding, ctx.history, raw.site)
        entry = await resolve_guideline(db, card) if card else None
        if card is None or entry is None:
            return AskResult(kind="general", answer=await _general_answer(question, ctx, history), supported=False)
        res = await _in_card(db, question, entry.key, ctx, history)
        card = card.model_copy(update={"key": entry.key, "known": True, "status": entry.status})
        return res.model_copy(update={"card": card})
    except Exception as ex:
        logger.warning("[copilot.ask] %s: %s", type(ex).__name__, str(ex)[:200])
        try:
            db.rollback()
        except Exception:
            pass
        return AskResult(kind="card" if key else "general", key=key, answer="", supported=False,
                         error=type(ex).__name__)
