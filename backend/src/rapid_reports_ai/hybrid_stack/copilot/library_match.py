"""Library matching v2 (spec §5.2): which library packs a case and its findings bind, by Jev alone (no gpt-oss).

- Per case (case_facts): one Jev request reads SCAN TYPE and CLINICAL HISTORY for the imaging modality (a choice) and,
  for each exam-level pack, whether this study is its `exam` (a yes/no).
- Per abnormal finding (pick): one Jev choice over the finding-triggered topics (siblings and a shared `match_topic`
  are one option), plus TNM in the same request (a staging yes/no and a choice over the TNM sites).

Option text is built in code from the entries' own data (names, purpose, applies_to) only: never eligibility, never
hand-written clinical text. Failures raise to the caller and cache nothing; caches (_FACTS, _PICKS) hold normalised
clinical text in their keys, are bounded by matcher._CACHE_MAX, process-local, never persisted and never logged."""
from __future__ import annotations

import logging
import os
from collections import OrderedDict
from dataclasses import dataclass, field

from ...jev_client import JEV_MODEL, jev_post
from ..schemas import scan_key
from . import jev as J
from . import matcher as M   # _put/_get (bounded caches); matcher imports this module too (used at call time only)
from . import registry as R
from . import tnm
from .library import bundle as L

CHOICE_MIN = 0.6     # the finding's topic choice: below this it is "none"
EXAM_MIN = 0.7       # "this study is the pack's exam"
TNM_Q_MIN = 0.7      # "the FINDING describes a primary malignant tumour that would be staged"
JEV_TIMEOUT_S = 4.0
logger = logging.getLogger(__name__)

MODALITIES = ("CT", "MRI", "US", "XR", "other")
NAMES_MAX = 4
ALIASES_PER_ENTRY = 2
PURPOSE_MAX = 500

_FACTS: "OrderedDict[tuple, CaseFacts]" = OrderedDict()   # (bundle, scan, history) -> facts (successes only)
_PICKS: "OrderedDict[tuple, tuple]" = OrderedDict()       # (bundle, scan, history, finding) -> (entries, site)
_OPTIONS: dict[tuple, tuple] = {}                         # bundle identity -> (topics, options); one bundle per deploy
# The bundle identity is its version plus its current keys: an entry edited under the same version and keys reuses the
# old option text until the process restarts (acceptable: one bundle per deploy, the bundle is rebuilt with a release).


@dataclass
class CaseFacts:
    modality: str | None = None
    exams: set[str] = field(default_factory=set)   # keys of the exam-level entries this study binds


def clear_cache() -> None:
    _FACTS.clear()
    _PICKS.clear()
    _OPTIONS.clear()


def _bundle_id(lib) -> tuple:
    return (lib.version(), tuple(e.key for e in lib.list()))


def _u(xs) -> list[str]:
    """Order-preserving de-duplication, compared normalised (case and punctuation: "CAC-DRS" = "CAC DRS"); blanks
    dropped."""
    seen, out = set(), []
    for x in xs:
        k = R.norm(x or "")
        if k and k not in seen:
            seen.add(k)
            out.append(x.strip())
    return out


def topics(lib) -> list[list]:
    """The finding-triggered current entries grouped by matcher_topic, in the library's order (stable): choice ids
    t0..tn follow this order."""
    groups: dict[str, list] = {}
    for e in lib.list():
        if "finding" in e.trigger:
            groups.setdefault(e.matcher_topic, []).append(e)
    return list(groups.values())


def exam_entries(lib) -> list:
    return [e for e in lib.list() if "exam" in e.trigger]


def _cap(text: str, n: int = PURPOSE_MAX) -> str:
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut + "…"


def option(entries) -> str:
    """One topic's option text: names joined by " — " (every entry's display, then every system, then up to two
    aliases each, so a sibling's name is never crowded out; de-duplicated; at most four), the purpose (several:
    de-duplicated and joined), and the union of applies_to finding / region / imaging."""
    names = _u([*(e.display for e in entries), *(e.system for e in entries),
                *(a for e in entries for a in e.aliases[:ALIASES_PER_ENTRY])])[:NAMES_MAX]
    purpose = _cap(" ".join(_u(e.purpose.strip() for e in entries)))
    parts = [(label, _u(x for e in entries for x in getattr(e.applies_to, attr)))
             for label, attr in (("finding", "finding_type"), ("region", "region"), ("imaging", "modality"))]
    scope = "; ".join(f"{label}: {' / '.join(xs)}" for label, xs in parts if xs)
    return f"{' — '.join(names)}. {purpose}" + (f" ({scope})" if scope else "")


def _options(lib) -> tuple[list[list], dict[str, str]]:
    """(topics, {t<i>: option text}) for this bundle, built once."""
    k = _bundle_id(lib)
    if k not in _OPTIONS:
        if len(_OPTIONS) > 4:
            _OPTIONS.clear()
        ts = topics(lib)
        _OPTIONS[k] = (ts, {f"t{i}": option(g) for i, g in enumerate(ts)})
    return _OPTIONS[k]


def _state(scan: str, history: str, finding: str | None = None) -> str:
    s = f"SCAN TYPE:\n{scan or 'not given'}\n\nCLINICAL HISTORY:\n{history or 'none given'}"
    return s if finding is None else f"{s}\n\nFINDING:\n{finding}"


async def _post(state: str, questions: dict) -> dict:
    r = await jev_post({"model": JEV_MODEL, "state": state, "questions": questions},
                       os.environ.get("OPENROUTER_API_KEY", ""), JEV_TIMEOUT_S)
    r.raise_for_status()
    return r.json()


async def case_facts(scan: str, history: str) -> CaseFacts:
    """The study's modality and the exam-level entries it binds, from one Jev request. Raises on failure (nothing
    cached)."""
    lib = L.get()
    k = (_bundle_id(lib), scan_key(scan), R.norm(history))
    hit, v = M._get(_FACTS, k)
    if hit:
        return v
    exams = exam_entries(lib)
    qs = {"modality": {"type": "choice", "instructions": "Which imaging modality is the study in SCAN TYPE?",
                       "criteria": {m: (m if m != "other" else "Another modality, or SCAN TYPE does not say.")
                                    for m in MODALITIES}}}
    for i, e in enumerate(exams):
        qs[f"x_{i}"] = {"type": "noul",
                        "instructions": f"The study described in SCAN TYPE and CLINICAL HISTORY is: {e.exam}."}
    body = await _post(_state(scan, history), qs)
    c, _ = J.choice(body, "modality")
    if c not in MODALITIES:
        raise ValueError(f"jev modality {c!r} is not offered")
    got = J.scores(body, [f"x_{i}" for i in range(len(exams))])
    v = CaseFacts(modality=c, exams={e.key for i, e in enumerate(exams) if got[f"x_{i}"] >= EXAM_MIN})
    M._put(_FACTS, k, v)
    return v


async def pick(scan: str, history: str, finding: str) -> tuple[list, str | None]:
    """(the picked topic's entries, the TNM site) for one finding, from one Jev request. "none" or a choice below
    CHOICE_MIN is no entries; the site is set only when the staging score reaches TNM_Q_MIN and a site was chosen.
    Raises on failure (nothing cached)."""
    lib = L.get()
    k = (_bundle_id(lib), scan_key(scan), R.norm(history), R.norm(finding))
    hit, v = M._get(_PICKS, k)
    if hit:
        return v
    ts, opts = _options(lib)
    sites = {f"s{i}": s for i, s in enumerate(tnm.sites())}
    qs: dict = {}
    if opts:
        qs["pick"] = {"type": "choice", "instructions": "Which guideline is meant for the FINDING?",
                      "criteria": {**opts, "none": "None of these guidelines is meant for the FINDING."}}
    qs["tnm"] = {"type": "noul", "instructions": (
        "The FINDING describes a primary malignant tumour (known or suspected) that would be staged.")}
    qs["site"] = {"type": "choice", "instructions": "Which primary tumour site does the FINDING describe?",
                  "criteria": {**sites, "none": "None of these sites."}}
    body = await _post(_state(scan, history, finding), qs)
    entries: list = []
    if opts:
        c, conf = J.choice(body, "pick")
        if c not in opts and c != "none":
            raise ValueError(f"jev pick {c!r} is not offered")   # malformed: never cached as "none"
        if c in opts and conf >= CHOICE_MIN:
            entries = list(ts[int(c[1:])])
    score = J.scores(body, ["tnm"])["tnm"]
    sc, _ = J.choice(body, "site")
    if sc not in sites and sc != "none":     # a malformed site is no site; the topic pick stands (final review M5)
        logger.warning("[library.match] jev site %r is not offered: no TNM site", sc)
        sc = "none"
    site = sites.get(sc) if score >= TNM_Q_MIN else None
    v = (entries, site)
    M._put(_PICKS, k, v)
    return v


def modality_ok(entry, modality: str | None) -> bool:
    mods = entry.applies_to.modality
    return modality is None or modality == "other" or not mods or modality in mods


def needs_modality(entry) -> str:
    """The modality a "redirect" entry needs, as its card says it ("US", "CT / MRI")."""
    return " / ".join(entry.applies_to.modality)
