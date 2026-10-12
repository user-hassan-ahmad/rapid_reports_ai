"""The matcher (spec §5.2): which published systems apply to each dictated abnormal finding, from model knowledge.
It also returns each system's publication and skeleton (branch names, never thresholds) and the branch this finding
falls into: the one case-aware output, which decides what the targeted fetch reads first."""
from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...enhancement_utils import MODEL_CONFIG, _run_agent_with_model
from ...jev_client import JEV_MODEL, jev_post
from ..schemas import scan_key
from . import registry as R
from . import tnm
from .types import Card, Publication

logger = logging.getLogger(__name__)

TNM_GATE_MIN = 0.7   # provisional: Jev "a primary malignancy of this site that would be staged"; set by the Task 13 lab
MAX_PER_FINDING = 2
MAX_PER_CASE = 6
TIMEOUT_S = 8.0
JEV_TIMEOUT_S = 4.0  # the edition pick and the TNM site gate; both fail closed (no pick, no card)
PICK_MIN = 0.6
_CACHE: "OrderedDict[tuple, list]" = OrderedDict()
_CACHE_MAX = 512

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
- skeleton: the system's branches or categories by name only (the groups its rules are organised by), never thresholds or intervals
- branch: the skeleton branch this finding falls into ("" when the finding does not yet say enough to tell)
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


def _prompt(scan_type: str, history: str, findings: list[Finding], known: list[tuple[str, str, str]]) -> str:
    s = f"SCAN TYPE: {scan_type}\nCLINICAL HISTORY: {history or 'none given'}\n\nFINDINGS:\n"
    s += "\n".join(f"- [{f.id}] {f.text}" for f in findings)
    if known:
        s += "\n\nKNOWN SYSTEMS (key: name version):\n" + "\n".join(f"- {k}: {n} {v}".rstrip() for k, n, v in known)
    s += "\n\nTNM SITES:\n" + "\n".join(f"- {x}" for x in tnm.sites())
    return s


async def _call(prompt: str) -> RawMatch:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=MODEL_CONFIG["GUIDELINE_PREFETCH"], output_type=RawMatch, system_prompt=MATCH_SYS,
        user_prompt=prompt, api_key="", model_settings={"temperature": 0, "max_tokens": 4000,
                                                        "reasoning_effort": "low"}), TIMEOUT_S)
    return r.output


async def _jev_pick(finding: str, name: str, rows) -> str | None:
    """Several registry versions of one system: Jev chooses between distinct entries, or none."""
    crit = {r.key: f"{r.name} {r.version}".strip() for r in rows}
    crit["none"] = "None of these editions applies."
    q = {"type": "choice", "instructions": f"Which edition of {name} should be applied to the FINDING?", "criteria": crit}
    r = await jev_post({"model": JEV_MODEL, "state": f"FINDING:\n{finding}", "questions": {"pick": q}},
                       os.environ.get("OPENROUTER_API_KEY", ""), JEV_TIMEOUT_S)
    r.raise_for_status()
    a = r.json()["answers"]["pick"]
    return a["choice"] if a["choice"] != "none" and float(a.get("confidence") or 0) >= PICK_MIN else None


def _same_branch(branch: str, skeleton: list[str]) -> str:
    """The registry's own name for the model's branch: exact, then the same normalised name, then one name's words
    within the other's (whole words: "solid" is not a word of "subsolid"); else the model's name (a new branch,
    fetched on open). A one-branch skeleton is always that branch."""
    if branch in skeleton or not skeleton:
        return branch
    nb = R.norm(branch)
    same = [b for b in skeleton if nb and R.norm(b) == nb]
    if len(same) == 1:
        return same[0]
    wb = set(nb.split())
    hits = [b for b in skeleton if wb and (wb <= set(R.norm(b).split()) or set(R.norm(b).split()) <= wb)
            and R.norm(b)]
    if len(hits) == 1:
        return hits[0]
    return skeleton[0] if len(skeleton) == 1 else branch


async def _tnm_gate(finding: str, site: str) -> float:
    q = {"type": "noul", "instructions": (f"The FINDING describes a primary malignant tumour (known or suspected) of this "
                                          f"site that would be staged: {site}")}
    r = await jev_post({"model": JEV_MODEL, "state": f"FINDING:\n{finding}", "questions": {"q": q}},
                       os.environ.get("OPENROUTER_API_KEY", ""), JEV_TIMEOUT_S)
    r.raise_for_status()
    return float(((r.json().get("answers") or {}).get("q") or {}).get("noul") or 0.0)


async def _tnm_card(f: Finding, s: RawSystem) -> Card | None:
    """A TNM candidate: the site must be on the closed list and pass the Jev gate (fails closed: no card)."""
    if s.site not in tnm.sites():
        return None
    try:
        if await _tnm_gate(f.text, s.site) < TNM_GATE_MIN:
            return None
    except Exception as e:
        logger.info("[copilot.match] TNM gate failed closed (%s): %s", s.site, type(e).__name__)
        return None
    e = tnm.entry(s.site)
    return Card(key=e.key, name=e.name, version="9", finding_id=f.id, why=s.why, branch="Staging",
                skeleton=["Staging"], publication=e.publication, known=True, status="verified")


async def _card(db: Session, f: Finding, s: RawSystem) -> Card | None:
    if not s.name.strip():
        return None
    if s.name.strip().upper() == "TNM":
        return await _tnm_card(f, s)
    key = R.make_key(s.name, s.version)
    row = R.by_key(db, key)
    if row is None:
        rows = R.by_alias(db, s.name)
        if len(rows) == 1 and (not s.version or rows[0].version == s.version or not rows[0].version):
            row = rows[0]
        elif len(rows) > 1:
            try:
                picked = await _jev_pick(f.text, s.name, rows)
            except Exception:
                picked = None
            row = R.by_key(db, picked) if picked else None
    if row is not None:
        e = R.entry(row)
        skeleton = [b.name for b in e.content.branches] or s.skeleton
        branch = _same_branch(s.branch, skeleton)
        return Card(key=e.key, name=e.name, version=e.version, finding_id=f.id, why=s.why, branch=branch,
                    skeleton=skeleton, publication=e.publication if e.publication.title else s.publication,
                    known=True, status=e.status)
    return Card(key=key, name=s.name.strip(), version=s.version.strip(), finding_id=f.id, why=s.why, branch=s.branch,
                skeleton=s.skeleton, publication=s.publication, known=False, status="new")


async def match(db: Session, scan_type: str, history: str, findings: list[Finding]) -> list[Card]:
    """Cards for these findings, ranked and capped. Only findings whose text the cache has not seen call the model.
    Fails open: no cards (and one candidate that fails to resolve is skipped, not the whole match)."""
    sk = scan_key(scan_type)
    keyf = lambda f: (sk, R.norm(f.text))
    todo = [f for f in findings if keyf(f) not in _CACHE]
    if todo:
        try:
            raw = await _call(_prompt(scan_type, history, todo, R.known(db)))
        except Exception as e:
            logger.warning("[copilot.match] %s: %s", type(e).__name__, str(e)[:200])
            return []
        got = {rf.id: rf.systems for rf in raw.findings}
        for f in todo:
            _CACHE[keyf(f)] = got.get(f.id, [])
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
    cards: list[Card] = []
    for f in findings:
        per = 0
        for s in _CACHE.get(keyf(f), []):
            if per >= MAX_PER_FINDING or len(cards) >= MAX_PER_CASE:
                break
            try:
                c = await _card(db, f, s)
            except Exception as e:
                logger.warning("[copilot.match] candidate %r skipped: %s", s.name, type(e).__name__)
                continue
            if c is not None and all(x.id != c.id for x in cards):
                cards.append(c)
                per += 1
    return cards
