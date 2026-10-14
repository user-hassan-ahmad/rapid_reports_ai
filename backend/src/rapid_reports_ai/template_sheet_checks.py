"""Save-time checks on a grammar sheet's NORMAL / NEGATIVE units (template pipeline spec, block 2). Code checks
placeholders; Jev asks, per unit, whether it states something normal or absent and whether it covers more than one
structure (one call per sheet, chunked at CHUNK units). The saving code repairs or drops what fails."""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple, Union

from .jev_client import JEV_MODEL, jev_post
from .template_sheet_structure import Negative, Normal, SheetStructure

PLACEHOLDER = "placeholder in a normal"
NOT_NORMAL = "states an abnormality as a normal"
MULTI_STRUCTURE = "normal covers more than one structure"

# Thresholds from the conversion-lab units (274 NORMAL/NEGATIVE units of the 31 hand-fixed sheets, 2 Jev runs):
# abnormal-as-normal units score <= 0.13 (one outlier, the ACL "cystic degeneration" sentence, 0.38-0.43 is missed);
# kept units score >= 0.23; run-to-run drift <= 0.05. NORMAL_MIN sits mid-gap.
NORMAL_MIN = 0.18
# Off: Jev's multi score has no clean gap. Named multi-structure normals score 0.78-0.87, but single-structure units
# listing several findings ("No aneurysm or dissection identified." 0.83) score as high, and ~25% of kept units are
# >= 0.8. Multi-structure normals stay a prompt rule; the code path is kept for a better question.
MULTI_MIN = 1.1
TIMEOUT_S = 6.0           # a save waits on this; a slow Jev refuses the write rather than hanging the editor
CHUNK = 40                # units per Jev call (two questions each)
_SLOT = re.compile(r"\{[^}]*\}")

Q_NORMAL = ("The SENTENCE states that a structure is normal, or that a finding is absent, with no abnormality, "
            "measurement or grade of disease: {s}")
Q_MULTI = ("The SENTENCE makes a normal or negative statement about more than one distinct anatomical structure, "
           "so one of them could be abnormal while the others are normal: {s}")


@dataclass(frozen=True)
class UnitFailure:
    line: int              # 1-based sheet line when check_units is given the sheet text, else 0
    text: str
    reason: str
    source_line: str = ""  # the sheet line the unit came from (the grammar stores the line itself)


Unit = Union[Normal, Negative]


def _units(st: SheetStructure) -> List[Unit]:
    return [*st.normals, *st.negatives]


def _api_key() -> str:
    """The OpenRouter key; raises when no Jev route has a key (jev_client._route uses JEV_API_KEY when direct)."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    direct = os.environ.get("RR_JEV_ROUTE") == "direct" and os.environ.get("JEV_API_KEY", "")
    if not key and not direct:
        raise RuntimeError("OPENROUTER_API_KEY unset: sheet checks cannot run")
    return key


def _score(ans: dict, k: str) -> float:
    v = (ans.get(k) or {}).get("noul") if isinstance(ans.get(k), dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("jev: incomplete answers")
    return float(v)


async def _jev_chunk(units: Sequence[Unit], key: str) -> Dict[str, Tuple[float, float]]:
    multi = MULTI_MIN <= 1.0  # no multi questions while the check is off
    qs = {}
    for i, u in enumerate(units):
        qs[f"n{i}"] = {"type": "noul", "instructions": Q_NORMAL.format(s=u.text)}
        if multi:
            qs[f"m{i}"] = {"type": "noul", "instructions": Q_MULTI.format(s=u.text)}
    r = await jev_post({"model": JEV_MODEL, "state": "Statements from a radiology report template.", "questions": qs},
                       key, TIMEOUT_S)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    return {u.text: (_score(ans, f"n{i}"), _score(ans, f"m{i}") if multi else 0.0) for i, u in enumerate(units)}


async def _jev_scores(units: Sequence[Unit]) -> Dict[str, Tuple[float, float]]:
    """text -> (normal score, multi-structure score). Raises on a missing key, an HTTP error or incomplete answers."""
    key = _api_key()
    chunks = [units[i:i + CHUNK] for i in range(0, len(units), CHUNK)]
    out: Dict[str, Tuple[float, float]] = {}
    for part in await asyncio.gather(*(_jev_chunk(c, key) for c in chunks)):
        out.update(part)
    return out


def _source(u: Unit) -> str:
    ref = getattr(u, "source_line", None) or (getattr(u, "source_lines", None) or [""])[0]
    return ref if isinstance(ref, str) else ""


def _number(src: str, lines: List[str], used: set) -> int:
    """1-based number of the first unused sheet line equal to src (identical lines map to successive ones), else 0."""
    s = src.strip()
    n = next((i + 1 for i, ln in enumerate(lines) if s and i + 1 not in used and ln.strip() == s), 0)
    if n:
        used.add(n)
    return n


async def check_units(st: SheetStructure, sheet: str = "") -> List[UnitFailure]:
    """Failures for the sheet's NORMAL / NEGATIVE units; pass the sheet text to get line numbers.
    Raises on a Jev error (the caller refuses the write)."""
    units = _units(st)
    lines = sheet.splitlines()
    used: set = set()

    def fail(u: Unit, reason: str) -> UnitFailure:
        src = _source(u)
        return UnitFailure(_number(src, lines, used), u.text, reason, src)

    fails = [fail(u, PLACEHOLDER) for u in units if _SLOT.search(u.text)]
    rest = [u for u in units if not _SLOT.search(u.text)]
    if not rest:
        return fails
    scores = await _jev_scores(rest)
    for u in rest:
        normal, multi = scores[u.text]
        if normal < NORMAL_MIN:
            fails.append(fail(u, NOT_NORMAL))
        elif multi >= MULTI_MIN:
            fails.append(fail(u, MULTI_STRUCTURE))
    return fails
