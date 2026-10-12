"""The matcher (spec §5.2): which published systems apply to each dictated abnormal finding, from model knowledge.
It also returns each system's publication and skeleton (branch names, never thresholds) and the branch this finding
falls into: the one case-aware output, which decides what the targeted fetch reads first.

Caches (_CACHE, _GATE, _PICK, _BRANCH) hold normalised clinical text (finding, history) in their keys, at most
_CACHE_MAX (512) entries each; they are process-local, never persisted, and never logged."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import OrderedDict

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, defer

from ...database.models import GuidelineRegistry
from ...enhancement_utils import MODEL_CONFIG, _run_agent_with_model
from ...jev_client import JEV_MODEL, jev_post
from ..schemas import scan_key
from . import jev as J
from . import registry as R
from . import tnm
from .types import Card, Publication

logger = logging.getLogger(__name__)

TNM_GATE_MIN = 0.7   # provisional: Jev "a primary malignancy of this site that would be staged"; set by the Task 13 lab
MAX_PER_FINDING = 2
MAX_PER_CASE = 6
CANDIDATES_PER_FINDING = 3   # resolved per finding (a candidate may resolve to nothing; the next one fills in)
TIMEOUT_S = 8.0
JEV_TIMEOUT_S = 4.0  # the edition pick and the TNM site gate; both fail closed (no pick, no card)
PICK_MIN = 0.6
KNOWN_MAX = 200      # registry rows offered to the model, verified first then most recent
_CACHE_MAX = 512
_CACHE: "OrderedDict[tuple, list]" = OrderedDict()        # (scan, history, finding) -> the model's systems
_GATE: "OrderedDict[tuple, float]" = OrderedDict()        # (history, finding, site) -> Jev score (successes only)
_PICK: "OrderedDict[tuple, str | None]" = OrderedDict()   # (finding, history, name, row keys) -> picked key (successes only)
_BRANCH: "OrderedDict[tuple, str | None]" = OrderedDict()  # (finding, row key, model branch) -> registry branch (successes only)

MATCH_SYS = """You recognise which published radiology classification systems, scoring systems, staging systems or management guidelines apply to findings a radiologist has dictated. Practice is in the UK: where several systems exist for the same finding, prefer the one used in UK radiology.

For each FINDING, list 0-2 systems a radiologist would apply to THAT finding on THIS scan, most useful first:
- only a system that classifies, scores, stages or sets the management of this finding as described: the finding already has the features the system works on (a size, a morphology, a density or signal, an enhancement pattern, a location), or is the kind of finding the system exists for;
- never a system for a different finding, for a diagnosis the dictation does not make, or a general reporting standard;
- most findings have none: return an empty list for them.
Each system:
- name: its usual name, without the version; when KNOWN SYSTEMS lists it, exactly that name
- version: the edition or year ("" if it has none); when KNOWN SYSTEMS lists it, that version
- why: one short clause, what about the finding makes it apply
- publication: the defining publication's title, issuing body and year, as best you know them (never a URL)
- skeleton: the system's branches or categories by name only (the groups its rules are organised by), never thresholds or intervals; when KNOWN SYSTEMS lists branches for it, exactly those names
- branch: the skeleton branch this finding falls into, spelled exactly as in skeleton ("" when the finding does not yet say enough to tell)
- site: "" except for TNM staging
TNM STAGING: for a primary malignant tumour (known or suspected) that would be staged, list name "TNM", version "9", site = exactly one name from TNM SITES, skeleton ["Staging"], branch "Staging". Never TNM for a metastasis, a benign lesion or an indeterminate incidental finding."""


class Finding(BaseModel):
    id: str
    text: str


class RawSystem(BaseModel):
    name: str = ""
    version: str = ""
    site: str = ""
    why: str = ""
    publication: Publication = Field(default_factory=Publication)
    skeleton: list[str] = Field(default_factory=list)
    branch: str = ""


class RawFinding(BaseModel):
    id: str
    systems: list[RawSystem] = Field(default_factory=list)


class RawMatch(BaseModel):
    findings: list[RawFinding] = Field(default_factory=list)


def clear_cache() -> None:
    _CACHE.clear()
    _GATE.clear()
    _PICK.clear()
    _BRANCH.clear()


def _put(cache: OrderedDict, k, v) -> None:
    cache[k] = v
    cache.move_to_end(k)
    while len(cache) > _CACHE_MAX:
        cache.popitem(last=False)


def _get(cache: OrderedDict, k):
    if k in cache:
        cache.move_to_end(k)
        return True, cache[k]
    return False, None


# --- the registry, loaded once per match() -------------------------------------------------------------------------

def _vnum(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def _nv(v: str) -> str:
    """A version compared loosely: "v2019" = "2019", "2nd edition" = "2nd"."""
    v = re.sub(r"\bedition\b", "", R.norm(v))
    return re.sub(r"[^0-9a-z.]+", "", v).lstrip("v")


class _Rows:
    """Every registry row (chunks deferred), so one match() reads the table once and resolves candidates in memory
    (and concurrently, without sharing the session across tasks)."""

    def __init__(self, db: Session):
        rows = db.query(GuidelineRegistry).options(defer(GuidelineRegistry.chunks)).all()
        rows.sort(key=lambda r: (r.status != "verified", -(r.updated_at.timestamp() if r.updated_at else 0)))
        self.rows = rows
        self.by_key = {r.key: r for r in rows}

    def alias(self, name: str) -> list[GuidelineRegistry]:
        """As registry.by_alias: name, alias or key slug, with a trailing version token stripped too."""
        n = R.norm(name)
        if not n:
            return []
        ns = R._strip_version(n)
        return [r for r in self.rows if R.alias_hit(r, n, ns)]

    def known_text(self) -> str:
        if len(self.rows) > KNOWN_MAX:
            logger.info("[copilot.match] registry has %d rows; offering the first %d", len(self.rows), KNOWN_MAX)
        lines = []
        for r in self.rows[:KNOWN_MAX]:
            branches = [b.get("name", "") for b in (r.content or {}).get("branches") or [] if b.get("name")]
            tail = f" [branches: {' | '.join(branches)}]" if branches else ""
            lines.append(f"- {r.key}: {r.name} {r.version or ''}".rstrip() + tail)
        return "\n".join(lines)


def _latest(rows: list[GuidelineRegistry]) -> GuidelineRegistry:
    return sorted(rows, key=lambda r: (r.status == "verified", _vnum(r.version)), reverse=True)[0]


def _prompt(scan_type: str, history: str, findings: list[Finding], known: str) -> str:
    s = f"SCAN TYPE: {scan_type}\nCLINICAL HISTORY: {history or 'none given'}\n\nFINDINGS:\n"
    s += "\n".join(f"- [{f.id}] {f.text}" for f in findings)
    if known:
        s += "\n\nKNOWN SYSTEMS (key: name version [branches]):\n" + known
    s += "\n\nTNM SITES:\n" + "\n".join(f"- {x}" for x in tnm.sites())
    return s


async def _call(prompt: str) -> RawMatch:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=MODEL_CONFIG["GUIDELINE_PREFETCH"], output_type=RawMatch, system_prompt=MATCH_SYS,
        user_prompt=prompt, api_key="", model_settings={"temperature": 0, "max_tokens": 4000,
                                                        "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


def _state(finding: str, history: str) -> str:
    return f"CLINICAL HISTORY:\n{history or 'none given'}\n\nFINDING:\n{finding}"


async def _jev_pick(finding: str, name: str, rows, history: str = "") -> str | None:
    """Several registry versions of one system: Jev chooses between distinct entries, or none. Choice keys are
    neutral (ed_0, ed_1, ...) and mapped back to row keys."""
    ids = {f"ed_{i}": r.key for i, r in enumerate(rows)}
    crit = {}
    for cid, r in zip(ids, rows):
        applies = ((r.content or {}).get("applies_to") or "").strip()
        year = ((r.publication or {}).get("year") or "").strip()
        crit[cid] = f"{r.name} {r.version}".strip() + (f" — {applies}" if applies else "") + (f" ({year})" if year else "")
    crit["none"] = "None of these editions applies."
    q = {"type": "choice", "instructions": f"Which edition of {name} should be applied to the FINDING?", "criteria": crit}
    r = await jev_post({"model": JEV_MODEL, "state": _state(finding, history), "questions": {"pick": q}},
                       os.environ.get("OPENROUTER_API_KEY", ""), JEV_TIMEOUT_S)
    r.raise_for_status()
    c, conf = J.choice(r.json(), "pick")   # malformed raises: a failure, never cached as "none"
    return ids[c] if c in ids and conf >= PICK_MIN else None


async def _pick(finding: str, name: str, rows, history: str) -> str | None:
    k = (R.norm(finding), R.norm(history), R.norm(name), tuple(r.key for r in rows))
    hit, v = _get(_PICK, k)
    if hit:
        return v
    try:
        v = await _jev_pick(finding, name, rows, history)
    except Exception as e:
        logger.info("[copilot.match] edition pick failed (%s): %s", name, type(e).__name__)
        return None
    _put(_PICK, k, v)
    return v


def _same_branch(branch: str, skeleton: list[str]) -> str:
    """The registry's own name for the model's branch: exact, or the same once normalised; else the model's name
    (a new branch, fetched on open). No containment: "Part-solid" is not "Solid" or "Subsolid"."""
    if branch in skeleton:
        return branch
    nb = R.norm(branch)
    same = [b for b in skeleton if nb and R.norm(b) == nb]
    return same[0] if len(same) == 1 else branch


async def _jev_branch(finding: str, name: str, skeleton: list[str], model_branch: str) -> str | None:
    """Which of the registry's existing branches this finding falls into, or none. Choice keys are neutral (br_0,
    br_1, ...) and mapped back to the branch names."""
    ids = {f"br_{i}": b for i, b in enumerate(skeleton)}
    crit = {**ids, "none": "None of these branches fits the FINDING."}
    q = {"type": "choice", "instructions": f"Which branch of {name} does the FINDING fall into?", "criteria": crit}
    r = await jev_post({"model": JEV_MODEL, "state": f"FINDING:\n{finding}\n\nMODEL BRANCH: {model_branch}",
                        "questions": {"branch": q}}, os.environ.get("OPENROUTER_API_KEY", ""), JEV_TIMEOUT_S)
    r.raise_for_status()
    c, conf = J.choice(r.json(), "branch")
    return ids[c] if c in ids and conf >= PICK_MIN else None


async def _branch(finding: str, row_key: str, name: str, skeleton: list[str], model_branch: str) -> str:
    """The registry's branch for the model's: exact or normalised; else Jev chooses among the registry's branches;
    "none" or a Jev failure keeps the model's name (a new branch, fetched on open). Successes are cached."""
    same = _same_branch(model_branch, skeleton)
    if same in skeleton or not model_branch.strip():
        return same
    k = (R.norm(finding), row_key, model_branch)
    hit, v = _get(_BRANCH, k)
    if not hit:
        try:
            v = await _jev_branch(finding, name, skeleton, model_branch)
        except Exception as e:
            logger.info("[copilot.match] branch pick failed (%s): %s", row_key, type(e).__name__)
            return model_branch
        _put(_BRANCH, k, v)
    return v or model_branch


async def _tnm_gate(finding: str, site: str, history: str = "") -> float:
    q = {"type": "noul", "instructions": (f"The FINDING describes a primary malignant tumour (known or suspected) of this "
                                          f"site that would be staged: {site}")}
    r = await jev_post({"model": JEV_MODEL, "state": _state(finding, history), "questions": {"q": q}},
                       os.environ.get("OPENROUTER_API_KEY", ""), JEV_TIMEOUT_S)
    r.raise_for_status()
    return J.scores(r.json(), ["q"])["q"]   # malformed raises: the gate fails closed and caches nothing


async def _gate(finding: str, site: str, history: str) -> float | None:
    k = (R.norm(history), R.norm(finding), site)
    hit, v = _get(_GATE, k)
    if hit:
        return v
    try:
        v = await _tnm_gate(finding, site, history)
    except Exception as e:
        logger.info("[copilot.match] TNM gate failed closed (%s): %s", site, type(e).__name__)
        return None
    _put(_GATE, k, v)
    return v


async def _tnm_card(f: Finding, s: RawSystem, history: str) -> Card | None:
    """A TNM candidate: the site must be on the closed list (matched normalised) and pass the Jev gate (fails
    closed: no card)."""
    site = {R.norm(x): x for x in tnm.sites()}.get(R.norm(s.site))
    if site is None:
        return None
    score = await _gate(f.text, site, history)
    if score is None or score < TNM_GATE_MIN:
        return None
    e = tnm.entry(site)
    return Card(key=e.key, name=e.name, version="9", finding_id=f.id, why=s.why, branch="Staging",
                skeleton=["Staging"], publication=e.publication, known=True, status="verified")


async def _resolve(rows: _Rows, f: Finding, s: RawSystem, history: str) -> GuidelineRegistry | None:
    """The registry row this candidate is: exact key; else an alias row of the same version; else (one unversioned
    row) that row; else Jev picks between editions; a versionless candidate with several rows and no pick takes the
    latest (verified first), never a new unversioned key."""
    row = rows.by_key.get(R.make_key(s.name, s.version))
    if row is not None:
        return row
    cands = rows.alias(s.name)
    if not cands:
        return None
    if s.version:
        same = [r for r in cands if _nv(r.version) == _nv(s.version)]
        if same:
            return same[0]
        if len(cands) == 1:
            return cands[0] if not cands[0].version else None
    elif len(cands) == 1:
        return cands[0]
    picked = await _pick(f.text, s.name, cands, history)
    if picked:
        return rows.by_key.get(picked)
    return None if s.version else _latest(cands)


async def _card(rows: _Rows, f: Finding, s: RawSystem, history: str) -> Card | None:
    if not s.name.strip():
        return None
    if s.name.strip().upper() == "TNM":
        return await _tnm_card(f, s, history)
    row = await _resolve(rows, f, s, history)
    if row is not None:
        e = R.entry(row)
        known = [b.name for b in e.content.branches]
        skeleton = known or s.skeleton
        branch = await _branch(f.text, e.key, e.name, known, s.branch) if known else _same_branch(s.branch, skeleton)
        return Card(key=e.key, name=e.name, version=e.version, finding_id=f.id, why=s.why, branch=branch,
                    skeleton=skeleton, publication=e.publication if e.publication.title else s.publication,
                    known=True, status=e.status)
    return Card(key=R.make_key(s.name, s.version), name=s.name.strip(), version=s.version.strip(), finding_id=f.id,
                why=s.why, branch=s.branch, skeleton=s.skeleton, publication=s.publication, known=False, status="new")


async def _safe_card(rows: _Rows, f: Finding, s: RawSystem, history: str) -> Card | None:
    try:
        return await _card(rows, f, s, history)
    except Exception as e:   # one candidate that fails to resolve is skipped, not the whole match
        logger.warning("[copilot.match] candidate %r skipped: %s", s.name, type(e).__name__)
        return None


async def card_for(db: Session, name: str, version: str, finding_id: str, finding_text: str, history: str = "",
                   site: str = "") -> Card | None:
    """One named system as a card through the matcher's own normalisation (exact key, alias, Jev edition pick, else a
    new key; "TNM" via the closed site list and the Jev gate). For ask's no-card path. Never raises: None on any
    failure."""
    try:
        rows = _Rows(db)
    except Exception as e:
        logger.warning("[copilot.match] registry read failed: %s", type(e).__name__)
        return None
    return await _safe_card(rows, Finding(id=finding_id, text=finding_text),
                            RawSystem(name=name, version=version, site=site), history)


def _rid(s: str) -> str:
    return s.strip().strip("[]").strip()


async def match(db: Session, scan_type: str, history: str, findings: list[Finding]) -> list[Card]:
    """Cards for these findings, ranked and capped. Only findings the cache has not seen (with this scan type and
    history) call the model; a model failure caches nothing and still returns the cached findings' cards."""
    sk, hk = scan_key(scan_type), R.norm(history)
    keyf = lambda f: (sk, hk, R.norm(f.text))
    try:
        rows = _Rows(db)
    except Exception as e:
        logger.warning("[copilot.match] registry read failed: %s", type(e).__name__)
        return []
    todo = [f for f in findings if keyf(f) not in _CACHE]
    if todo:
        try:
            raw = await _call(_prompt(scan_type, history, todo, rows.known_text()))
            got = {_rid(rf.id): rf.systems for rf in raw.findings}
            if any(_rid(f.id) in got for f in todo):
                for f in todo:
                    _put(_CACHE, keyf(f), got.get(_rid(f.id), []))
            else:
                logger.warning("[copilot.match] none of %d finding ids came back; nothing cached", len(todo))
        except Exception as e:
            logger.warning("[copilot.match] %s: %s", type(e).__name__, str(e)[:200])
    plan = [(f, s) for f in findings for s in (_CACHE.get(keyf(f)) or [])[:CANDIDATES_PER_FINDING]]
    resolved = await asyncio.gather(*(_safe_card(rows, f, s, history) for f, s in plan))
    per_finding: dict[str, list[Card]] = {f.id: [] for f in findings}
    for (f, _), c in zip(plan, resolved):
        if c is not None and all(x.id != c.id for x in per_finding[f.id]):
            per_finding[f.id].append(c)
    # Caps in rank order: every finding's first card before any finding's second.
    cards: list[Card] = []
    for rank in range(MAX_PER_FINDING):
        for f in findings:
            ranked = per_finding.get(f.id) or []
            if rank < len(ranked) and len(cards) < MAX_PER_CASE and all(x.id != ranked[rank].id for x in cards):
                cards.append(ranked[rank])
    return cards
