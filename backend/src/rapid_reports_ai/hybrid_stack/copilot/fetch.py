"""The targeted fetch (spec §5.3): source first, the case's branch first. Search by identity, Jev checks the
branch is covered, gpt-oss structures it with a quote per output, Jev judges every output and the branch rule in
one batch (the exact-match signal is logged only, never a shortcut), the entry is upserted as a draft; the other
skeleton branches fill in the background."""
from __future__ import annotations

import asyncio
import logging
import weakref
from datetime import datetime, timedelta, timezone

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
NOT_AVAILABLE_RETRY_DAYS = 7   # a branch no source covered is searched again after this long
FILL_CONCURRENCY = 3           # background branch fetches in flight at once, per event loop
# Locks and the fill semaphore bind to an event loop, so they are kept per loop (a lab calling asyncio.run
# repeatedly gets fresh ones). Weak keys: a closed loop's entry goes with it, and a reused id() cannot alias it.
_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = weakref.WeakKeyDictionary()
_SEMS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()
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
    prompt = f"SYSTEM: {name} {version}\nBRANCH: {branch}\n\nSOURCE:\n{text}"   # text is already capped (_text)
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=MODEL_CONFIG["GUIDELINE_PREFETCH"], output_type=Structured, system_prompt=STRUCTURE_SYS,
        user_prompt=prompt, api_key="", model_settings={"temperature": 0, "max_tokens": 6000,
                                                        "reasoning_effort": "low"}), STRUCTURE_TIMEOUT_S)
    return r.output


def _text(chunks: list[Chunk]) -> str:
    """The chunks joined and capped at what Jev's windows cover, on chunk boundaries (one oversized first chunk is
    cut). Built once per pass; structure and every Jev check read the same string."""
    parts, size = [], 0
    for c in chunks:
        part = f"[{c.url}]\n{c.text}"
        if size + len(part) + 2 * bool(parts) > J.SOURCE_MAX:
            if not parts:
                parts.append(part[:J.SOURCE_MAX])
            break
        parts.append(part)
        size += len(part) + 2 * (len(parts) > 1)
    return "\n\n".join(parts)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stale(b: Branch) -> bool:
    if b.state != "not_available":
        return False
    try:
        at = datetime.fromisoformat(b.fetched_at)
    except ValueError:
        return True   # no timestamp (seeded or older row): treat as due
    return _now() - at > timedelta(days=NOT_AVAILABLE_RETRY_DAYS)


def _resolved(b: Branch | None) -> bool:
    return b is not None and b.state != "pending" and not _stale(b)


def to_fill(skeleton: list[str], content: GuidelineContent) -> list[str]:
    done = {b.name for b in content.branches if _resolved(b)}
    return [b for b in skeleton if b not in done]


def _term(branch: str) -> str:
    """The branch as a search term: Overview searches by identity alone."""
    return "" if branch == OVERVIEW else branch


def _ident(card: Card) -> str:
    return " ".join(f"{card.name} {card.version}".split())


def _cover_label(card: Card, branch: str) -> str:
    """What Jev's coverage question names: the guideline, and the branch unless it is the overview."""
    term = _term(branch)
    return f"{_ident(card)}: {term}" if term else _ident(card)


def _claim(card: Card, branch: str, o) -> str:
    """One output as a plain sentence with its context, for Jev's evidence check; empty parts are left out."""
    term = _term(branch)
    head = f"In {_ident(card)}" + (f", for {term}" if term else "")
    body = "; ".join(p for p in (f"when {o.when}" if o.when else "", o.classification,
                                  f"recommendation: {o.recommendation}" if o.recommendation else "") if p)
    return f"{head}: {body}" if body else head


def _rule_claim(card: Card, branch: str, rule: str) -> str:
    """The branch's decision rule as a plain sentence with the same context as _claim, so Jev judges it in the
    same batch as the outputs (it has no quote of its own to exact-match against)."""
    term = _term(branch)
    head = f"In {_ident(card)}" + (f", for {term}" if term else "")
    return f"{head}: rule: {rule}"


def _loop_locks() -> dict[str, asyncio.Lock]:
    return _LOCKS.setdefault(asyncio.get_running_loop(), {})


def _lock(key: str, branch: str) -> asyncio.Lock:
    """One lock per key and branch: different branches of one guideline fetch in parallel; the same branch, from a
    foreground open or the background fill, fetches once."""
    return _loop_locks().setdefault(f"{key}|{branch}", asyncio.Lock())


def _sem() -> asyncio.Semaphore:
    return _SEMS.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(FILL_CONCURRENCY))


async def _fetch_branch(card: Card, branch: str, queries: list[str]) -> tuple[Structured | None, Branch, list[Chunk], list[Source]]:
    """One branch: gather → coverage (one extra query below the bar) → structure → evidence. Only a checked branch
    carries inputs, rule and outputs."""
    term = _term(branch)
    label = _cover_label(card, branch)
    chunks, sources = await S.gather(queries, branch, focus=term)
    if not chunks:
        return None, Branch(name=branch, state="pending"), [], []
    text = _text(chunks)
    cover = (await J.coverage(text, [label])).get(label, 0.0)
    if cover < J.COVER_MIN:   # one retry on new pages only (review: the same URLs re-extract the same chunks)
        more, more_src = await S.gather([S.branch_query(card.name, card.version, term)], branch, focus=term,
                                        exclude={c.url for c in chunks})
        chunks, sources = chunks + more, sources + more_src
        if more:
            text = _text(chunks)
            cover = (await J.coverage(text, [label])).get(label, 0.0)
    if cover < J.COVER_MIN:
        return None, Branch(name=branch, state="not_available"), chunks, sources
    st = await _structure(card.name, card.version, term or _OVERVIEW_LABEL, text)
    outputs = st.branch.outputs
    rule = st.branch.rule
    claims = [(o.quote, _claim(card, branch, o)) for o in outputs]
    # The rule has no quote of its own; it rides in the same Jev batch as the outputs rather than a call on its
    # own, and is judged by the same strict wording (context included) as everything else.
    if rule:
        claims = claims + [(rule, _rule_claim(card, branch, rule))]
    if claims:
        exact = J.exact_signals(text, claims)
        scores = await J.evidence(text, claims)
        logger.debug("[copilot.fetch] %s/%s exact=%s scores=%s", card.key, branch, exact, scores)
    else:
        scores = []
    output_scores, rule_score = scores[:len(outputs)], (scores[len(outputs)] if rule else None)
    kept = [o for o, s in zip(outputs, output_scores) if s >= J.EVIDENCE_MIN]
    if not kept:
        return st, Branch(name=branch, state="not_available"), chunks, sources
    rule = rule if rule_score is not None and rule_score >= J.EVIDENCE_MIN else ""
    b = st.branch.model_copy(update={"name": branch, "outputs": kept, "rule": rule, "state": "checked"})
    return st, b, chunks, sources


def _save(db: Session, card: Card, st: Structured | None, b: Branch, chunks, sources) -> None:
    b = b.model_copy(update={"fetched_at": _now().isoformat(timespec="seconds")})
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
    Never raises: a failure is logged and returns what the registry already holds (or None).

    Ends the caller session's transaction (it is rolled back before every long await, so the pooled connection is
    not held through the fetch): the caller must have no pending writes."""
    try:
        if tnm.is_tnm(card.key):   # offline provider: never searched, never stored
            site = tnm.site_for(card.key)
            return tnm.entry(site) if site else None
        row = R.by_key(db, card.key)
        if row is not None:
            held = R.entry(row)
            if _resolved(held.content.branch(card.branch)) or not card.branch:
                _spawn_fill(card, held.content)
                return held
        branch = card.branch or OVERVIEW
        # Release the request's transaction before every long await (lock wait, network fetch): nothing is pending,
        # and holding it would keep a pooled connection checked out for up to ~100 s. Rollback also expires the
        # identity map, so the reads below see what sibling sessions committed meanwhile.
        db.rollback()
        async with _lock(card.key, branch):   # a branch the background fill is fetching: wait for it, then re-read
            row = R.by_key(db, card.key)
            held = R.entry(row) if row is not None else None
            if held is not None and _resolved(held.content.branch(branch)):
                _spawn_fill(card, held.content)
                return held
            db.rollback()
            st, b, chunks, sources = await _fetch_branch(
                card, branch, S.first_pass_queries(card.name, card.version, card.publication, card.branch))
            if not chunks:
                return held
            _save(db, card, st, b, chunks, sources)   # inside the try: upsert raises on a bad key or a DB error; it re-reads the row fresh
        entry = R.entry(R.by_key(db, card.key))
        _spawn_fill(card, entry.content)
        return entry
    except Exception as e:
        logger.warning("[copilot.fetch] %s %s: %s", card.key, type(e).__name__, str(e)[:200])
        return _held(db, card.key)


def _spawn_fill(card: Card, content: GuidelineContent) -> None:
    rest = [b for b in to_fill(card.skeleton, content) if f"{card.key}|{b}" not in _FILLING]
    if not rest:
        return
    claims = {f"{card.key}|{b}" for b in rest}
    _FILLING.update(claims)   # claimed before the task first runs, so a second open in the same tick does not double-fill
    t = asyncio.get_running_loop().create_task(_fill(card, rest))
    _TASKS.add(t)
    t.add_done_callback(lambda task: _fill_done(task, card.key, claims))


def _fill_done(task: asyncio.Task, key: str, claims: set[str]) -> None:
    """Runs however the fill ends, cancellation included: the claims are released so the next open can retry."""
    _TASKS.discard(task)
    _FILLING.difference_update(claims)
    if not task.cancelled() and task.exception() is not None:
        e = task.exception()
        logger.warning("[copilot.fill] %s %s: %s", key, type(e).__name__, str(e)[:200])


async def _fill(card: Card, branches: list[str]) -> None:
    """Background: each remaining branch with its own query, saved as it finishes, in its own DB sessions (none held
    through the fetch). Each branch takes the same lock a foreground open would, and re-reads first: a branch the
    foreground resolved meanwhile is skipped. A failure leaves the branch pending; the next open retries it."""
    async def one(branch: str) -> None:
        try:
            # Slot first, then the branch lock: a queued branch holds no lock, so a foreground open fetches it
            # at once (and this then skips it); a branch already fetching makes that open wait and re-read.
            async with _sem(), _lock(card.key, branch):
                with SessionLocal() as db:
                    row = R.by_key(db, card.key)
                    if row is not None and _resolved(R.entry(row).content.branch(branch)):
                        return
                st, br, chunks, sources = await _fetch_branch(
                    card, branch, [S.branch_query(card.name, card.version, _term(branch))])
                if chunks:
                    with SessionLocal() as db:
                        _save(db, card, st, br, chunks, sources)
        except Exception as e:
            logger.warning("[copilot.fill] %s/%s %s: %s", card.key, branch, type(e).__name__, str(e)[:200])
    await asyncio.gather(*(one(b) for b in branches))
