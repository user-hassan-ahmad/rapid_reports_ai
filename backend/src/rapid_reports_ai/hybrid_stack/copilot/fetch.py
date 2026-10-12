"""The targeted fetch (spec §5.3): source first, the case's branch first. Search by identity, Jev checks the
branch is covered, gpt-oss structures it with a quote per output, Jev checks every quote that is not an exact
match, the entry is upserted as a draft; the other skeleton branches fill in the background."""
from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...database import SessionLocal
from ...enhancement_utils import MODEL_CONFIG, _run_agent_with_model
from . import jev as J
from . import registry as R
from . import search as S
from . import tnm
from .types import Branch, Card, Chunk, Entry, GuidelineContent, Source

logger = logging.getLogger(__name__)

STRUCTURE_TIMEOUT_S = 30.0
OVERVIEW = "Overview"   # the branch a branchless (ask-originated) card resolves into; never a branch named ""
_OVERVIEW_LABEL = "the guideline as a whole"
_LOCKS: dict[str, asyncio.Lock] = {}
_FILLING: set[str] = set()
_TASKS: set[asyncio.Task] = set()

STRUCTURE_SYS = """You turn source text about one published radiology classification system or management guideline into a structured entry for ONE branch of it. Use only what the SOURCE states.
- branch.inputs: the features or facts the branch's decision needs (each with an id, a short question and its options exactly as the source names them; settled_by: how a radiology report would state it).
- branch.rule: the decision rule for this branch in compact plain text, citing every threshold, size band and interval exactly as the source states it.
- branch.outputs: one per category or recommendation the source gives for this branch: when (the condition over the inputs), classification (the category label the source uses, or "" when the branch only sets management), recommendation (the action or interval as the source states it, "" when none), quote (a verbatim span of the SOURCE, 5-40 words, that states this output).
- summary: two plain sentences on what the whole system is for. applies_to: one line on which findings it classifies. aliases: other names and abbreviations the source uses for the system.
Never add a threshold, interval or category the SOURCE does not state; leave a list empty rather than guess."""


class Structured(BaseModel):
    summary: str = ""
    applies_to: str = ""
    aliases: list[str] = Field(default_factory=list)
    branch: Branch


async def _structure(name: str, version: str, branch: str, text: str) -> Structured:
    prompt = f"SYSTEM: {name} {version}\nBRANCH: {branch}\n\nSOURCE:\n{text[:J.SOURCE_MAX]}"   # the cap Jev's windows cover
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=MODEL_CONFIG["GUIDELINE_PREFETCH"], output_type=Structured, system_prompt=STRUCTURE_SYS,
        user_prompt=prompt, api_key="", model_settings={"temperature": 0, "max_tokens": 6000,
                                                        "reasoning_effort": "low"}), STRUCTURE_TIMEOUT_S)
    return r.output


def _text(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"[{c.url}]\n{c.text}" for c in chunks)


def to_fill(skeleton: list[str], content: GuidelineContent) -> list[str]:
    done = {b.name for b in content.branches if b.state != "pending"}
    return [b for b in skeleton if b not in done]


def _term(branch: str) -> str:
    """The branch as a search term: Overview searches by identity alone."""
    return "" if branch == OVERVIEW else branch


async def _fetch_branch(card: Card, branch: str, queries: list[str]) -> tuple[Structured | None, Branch, list[Chunk], list[Source]]:
    """One branch: gather → coverage (one extra query below the bar) → structure → evidence."""
    term = _term(branch)
    label = term or _OVERVIEW_LABEL   # what Jev and the structure step are asked about
    chunks, sources = await S.gather(queries, branch, focus=term)
    if not chunks:
        return None, Branch(name=branch, state="pending"), [], []
    cover = (await J.coverage(_text(chunks), [label])).get(label, 0.0)
    if cover < J.COVER_MIN:   # one retry on new pages only (review: the same URLs re-extract the same chunks)
        more, more_src = await S.gather([S.branch_query(card.name, card.version, term)], branch, focus=term,
                                        exclude={c.url for c in chunks})
        chunks, sources = chunks + more, sources + more_src
        cover = (await J.coverage(_text(chunks), [label])).get(label, 0.0) if more else cover
    if cover < J.COVER_MIN:
        return None, Branch(name=branch, state="not_available"), chunks, sources
    st = await _structure(card.name, card.version, label, _text(chunks))
    claims = [(o.quote, f"{o.when} → {o.classification}; {o.recommendation}".strip()) for o in st.branch.outputs]
    scores = await J.evidence(_text(chunks), claims) if claims else []
    kept = [o for o, s in zip(st.branch.outputs, scores) if s >= J.EVIDENCE_MIN]
    b = st.branch.model_copy(update={"name": branch, "outputs": kept,
                                     "state": "checked" if kept else "not_available"})
    return st, b, chunks, sources


def _save(db: Session, card: Card, st: Structured | None, b: Branch, chunks, sources) -> None:
    R.upsert(db, key=card.key, name=card.name, version=card.version, aliases=(st.aliases if st else []) + [card.name],
             publication=card.publication if card.publication.title else None,
             content=GuidelineContent(summary=st.summary if st else "", applies_to=st.applies_to if st else "",
                                      branches=[b]), sources=sources, chunks=chunks)


def _held(db: Session, key: str) -> Entry | None:
    """What the registry holds now, for the fail-open paths. Rolls back first: a failed upsert leaves the session
    unusable until it does."""
    try:
        db.rollback()
        row = R.by_key(db, key)
        return R.entry(row) if row is not None else None
    except Exception as e:
        logger.warning("[copilot.fetch] %s re-read %s: %s", key, type(e).__name__, str(e)[:200])
        return None


async def resolve_guideline(db: Session, card: Card) -> Entry | None:
    """The entry with the card's branch resolved (checked or not_available), or None when nothing could be fetched.
    Never raises: a failure is logged and returns what the registry already holds (or None)."""
    try:
        if tnm.is_tnm(card.key):   # offline provider: never searched, never stored
            site = tnm.site_for(card.key)
            return tnm.entry(site) if site else None
        row = R.by_key(db, card.key)
        if row is not None:
            b = R.entry(row).content.branch(card.branch)
            if b is not None and b.state != "pending" or not card.branch:
                _spawn_fill(card, R.entry(row).content)
                return R.entry(row)
        branch = card.branch or OVERVIEW
        # Release the request's transaction before every long await (lock wait, network fetch): nothing is pending,
        # and holding it would keep a pooled connection checked out for up to ~100 s. Rollback also expires the
        # identity map, so the reads below see what sibling sessions committed meanwhile.
        db.rollback()
        lock = _LOCKS.setdefault(card.key, asyncio.Lock())
        async with lock:
            row = R.by_key(db, card.key)
            held = R.entry(row) if row is not None else None
            if held is not None and (b := held.content.branch(branch)) is not None and b.state != "pending":
                return held
            db.rollback()
            st, b, chunks, sources = await _fetch_branch(
                card, branch, S.first_pass_queries(card.name, card.version, card.publication, card.branch))
            if not chunks:
                return held
            _save(db, card, st, b, chunks, sources)   # inside the try: upsert raises on a bad key or a DB error; it re-reads the row fresh
        entry = R.entry(R.by_key(db, card.key))
    except Exception as e:
        logger.warning("[copilot.fetch] %s %s: %s", card.key, type(e).__name__, str(e)[:200])
        return _held(db, card.key)
    _spawn_fill(card, entry.content)
    return entry


def _spawn_fill(card: Card, content: GuidelineContent) -> None:
    rest = [b for b in to_fill(card.skeleton, content) if f"{card.key}|{b}" not in _FILLING]
    if not rest:
        return
    for b in rest:   # claimed before the task first runs, so a second open in the same tick does not double-fill
        _FILLING.add(f"{card.key}|{b}")
    t = asyncio.get_running_loop().create_task(_fill(card, rest))
    _TASKS.add(t)
    t.add_done_callback(_TASKS.discard)


async def _fill(card: Card, branches: list[str]) -> None:
    """Background: each remaining branch with its own query, saved as it finishes, in its own DB session. A failure
    leaves the branch pending; the next open retries it."""
    async def one(branch: str) -> None:
        try:
            st, br, chunks, sources = await _fetch_branch(card, branch, [S.branch_query(card.name, card.version, _term(branch))])
            if chunks:
                with SessionLocal() as db:
                    _save(db, card, st, br, chunks, sources)
        except Exception as e:
            logger.warning("[copilot.fill] %s/%s %s: %s", card.key, branch, type(e).__name__, str(e)[:200])
        finally:
            _FILLING.discard(f"{card.key}|{branch}")
    await asyncio.gather(*(one(b) for b in branches))
