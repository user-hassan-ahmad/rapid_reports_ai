"""Protocol matching (spec §3; matcher lab 2026-10-13): a local index of display names and aliases on every keystroke,
Jev re-ranks the local top 10 after a pause. The local order stands; Jev only promotes its pick at >= 0.9."""
from __future__ import annotations

import asyncio
import logging
import os
import re

from pydantic import BaseModel, Field

from ...jev_client import JEV_MODEL, jev_post
from .bundle import Bundle, Entry

logger = logging.getLogger(__name__)
PROMOTE_MIN = 0.9
NONE_MIN = 0.9
JEV_TIMEOUT_S = 3.0
TIER = {"high": 2, "medium": 1, "low": 0}
_LAT = re.compile(r"\b(lt|rt|left|right|bilateral|both|bilat)\b|\s[lr]$")
AGENT = {"none": "No contrast", "iv_iodinated": "IV contrast", "gadolinium": "Gadolinium",
         "gadolinium_hepatobiliary": "Hepatobiliary gadolinium", "oral_only": "Oral contrast",
         "iv_and_oral": "IV and oral contrast", "intra_articular": "Intra-articular contrast",
         "intrathecal": "Intrathecal contrast", "rectal_or_luminal": "Luminal contrast", "air": "Air"}
PHASE_WORDS = {"non_contrast": "unenhanced", "dce": "DCE", "lge": "LGE", "t1_t2_mapping": "T1 and T2 mapping",
               "t2star": "T2*", "ecg_gated_arterial": "ECG-gated arterial", "hepatobiliary_20min": "hepatobiliary (20 min)",
               "pre_contrast": "pre-contrast", "dynamic_arterial": "arterial", "dynamic_portal_venous": "portal venous",
               "dynamic_delayed": "delayed", "post_contrast": "post-contrast", "angiographic": "angiographic"}


def norm(s: str) -> str:
    s = (s or "").lower().replace("+c", " with contrast ").replace("w/", "with ").replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def phase_words(phases: list[str]) -> str:
    return ", ".join(PHASE_WORDS.get(p, p.replace("_", " ")) for p in phases)


def agent_words(agent: str) -> str:
    """The agent mid-sentence: lowercase except abbreviations ("gadolinium", "IV contrast", "intra-articular contrast")."""
    return " ".join(w if w.isupper() and len(w) > 1 else w.lower() for w in AGENT.get(agent, agent).split())


def protocol_line(entry: Entry, phases: list[str] | None = None) -> str:
    ph = entry.phases_default if phases is None else phases
    words = phase_words(ph)
    return AGENT.get(entry.agent, entry.agent) + (f" · {words}" if words else "")


def _edit1(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        d = [i for i in range(len(a)) if a[i] != b[i]]
        return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]])
    s, t = (a, b) if len(a) < len(b) else (b, a)
    return any(t[:i] + t[i + 1:] == s for i in range(len(t)))


def _grams(s: str) -> set[str]:
    s = s.replace(" ", "")
    return {s[i:i + 3] for i in range(len(s) - 2)}


def _text_score(q: str, qt: list[str], qg: set[str], t: str, tt: list[str], tg: set[str]) -> float:
    if q == t:
        return 100.0
    if t.startswith(q):
        return 88.0 + 10 * len(q) / len(t)
    match = lambda x, y: y.startswith(x) or (len(x) >= 4 and _edit1(x, y))  # noqa: E731
    hit = sum(any(match(x, y) for y in tt) for x in qt)
    cov = sum(any(match(x, y) for x in qt) for y in tt) / len(tt)
    tok = 70 * hit / len(qt) + 15 * cov
    tri = 75 * len(qg & tg) / len(qg | tg) if qg and tg else 0.0
    return max(tok, tri)


_INDEX: dict[str, list[tuple[Entry, list[tuple[str, list[str], set[str]]]]]] = {}


def _index(bundle: Bundle):
    if bundle.version not in _INDEX:
        _INDEX.clear()
        _INDEX[bundle.version] = [
            (e, [(t, t.split(), _grams(t)) for t in {norm(e.display_name), *(norm(a) for a in e.aliases)} if t])
            for e in bundle.entries]
    return _INDEX[bundle.version]


def local_search(bundle: Bundle, q: str, k: int = 10) -> list[tuple[float, Entry]]:
    raw = (q or "")[:200]
    qn = norm(_LAT.sub(" ", raw.lower())) or norm(raw)
    if not qn:
        return []
    qt, qg = qn.split(), _grams(qn)
    scored = [(max(_text_score(qn, qt, qg, t, tt, tg) for t, tt, tg in texts) + 2 * TIER.get(e.tier, 0), e)
              for e, texts in _index(bundle) if texts]
    scored.sort(key=lambda x: (-x[0], x[1].display_name))
    return scored[:k]


async def rerank(q: str, cands: list[Entry], transport=None) -> tuple[str | None, float]:
    crit = {e.id: f"{e.display_name} ({protocol_line(e)}); also typed as: {'; '.join(e.aliases[:3])}" for e in cands}
    crit["none"] = "None of these: the scan typed is a different examination, another modality, or not a scan"
    body = {"model": JEV_MODEL, "state": f"Scan type typed by the radiologist: {q[:200]}",
            "questions": {"pick": {"type": "choice", "instructions": "Which examination did the radiologist mean?",
                                   "criteria": crit}}}
    try:
        r = await asyncio.wait_for(jev_post(body, os.environ.get("OPENROUTER_API_KEY", ""), JEV_TIMEOUT_S, transport),
                                   JEV_TIMEOUT_S + 0.5)
        r.raise_for_status()
        a = (r.json().get("answers") or {}).get("pick") or {}
        return a.get("choice"), float(a.get("confidence") or 0.0)
    except Exception as e:  # never blocks the picker
        logger.warning("[protocol_library.rerank] %s: %s", type(e).__name__, str(e)[:200])
        return None, 0.0


class Variant(BaseModel):
    phases: list[str]
    line: str
    default: bool = False


class Option(BaseModel):
    id: str
    display_name: str
    protocol_line: str
    laterality: str
    variants: list[Variant] = Field(default_factory=list)


class SearchResult(BaseModel):
    options: list[Option] = Field(default_factory=list)
    not_listed_hint: bool = False
    promoted: str | None = None


def _option(e: Entry) -> Option:
    return Option(id=e.id, display_name=e.display_name, protocol_line=protocol_line(e), laterality=e.laterality,
                  variants=[Variant(phases=ph, line=protocol_line(e, ph), default=i == 0)
                            for i, ph in enumerate(e.phase_sets())])


async def search(bundle: Bundle, q: str, rerank_on: bool = False, transport=None) -> SearchResult:
    top = [e for _, e in local_search(bundle, q)]
    if not top:
        return SearchResult()
    promoted, hint = None, False
    if rerank_on:
        choice, conf = await rerank(q, top, transport)
        if choice == "none" and conf >= NONE_MIN:
            hint = True
        elif choice and conf >= PROMOTE_MIN and any(e.id == choice for e in top):
            top = [e for e in top if e.id == choice] + [e for e in top if e.id != choice]
            promoted = choice
    return SearchResult(options=[_option(e) for e in top], not_listed_hint=hint, promoted=promoted)
