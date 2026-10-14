"""Quiet "area never mentioned" notes for templated reports with a grammar sheet (approved by Hassan 2026-10-14).

One Jev request per report: one noul question per COVERS structure of the FINDINGS paragraphs, in the lab's plain
wording (`question`), state `REPORT:\\n<report>`. A structure with P(yes) < NOT_MENTIONED is a quiet note: kind
`structure_not_mentioned`, cls info (the quietest class the rail shows, as the post-gen check's `value_missing`),
no edit. Lab (Hassan accepted): ~2% false alarms per structure, about 1 report in 6 with one false note, hence quiet
and capped (MAX_NOTES, separate from the gap flags' cap). A structure whose paragraph a SUPPRESS rule may have left
out, and that is absent from the report, is not asked; nor is one of a paragraph optional by design (no NORMAL,
NEGATIVE or FIXED unit, only conditional RULE ... USE fill-ins). A structure stored before FIXED units carried their
paragraph places none (re-parsed when the sheet or grammar version changes). Fails open: a Jev error, timeout or partial answer gives no
note and counts `structure_check_unavailable` in the log (no rail item)."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from .items import ReviewInput, ReviewItem, item_key, text_hash
from .template_text import _find

logger = logging.getLogger(__name__)

KIND = "structure_not_mentioned"
DETECTOR = "jev.structure_mentioned"
NOT_MENTIONED = 0.3          # P(yes) below this → not mentioned (lab threshold)
MAX_NOTES = 4
TIMEOUT_S = 6.0              # the stack value check's per-call budget (jev_stack TIMEOUT_S * 2)
_SUPPRESS = ("suppress", "suppress_section")

Ask = Callable[[str, List[str]], Awaitable[List[float]]]


def question(structure: str) -> Dict[str, Any]:
    """The lab wording, verbatim."""
    return {"type": "noul", "instructions": f"The REPORT states anything about the {structure}."}


def state(report: str) -> str:
    return f"REPORT:\n{report}"


def title(name: str) -> str:
    """Display form of a sheet structure name: an all-caps phrase is title-cased; an acronym word ("LMS", "CTCA")
    and any word already holding a capital are kept; other words get a capital first letter."""
    words = name.split()
    if len(words) > 1 and name.isupper():
        return name.title()
    return " ".join(w if any(ch.isupper() for ch in w) else w[:1].upper() + w[1:] for w in words)


async def ask_mentioned(report: str, names: List[str]) -> List[float]:
    """P(the report states anything about the structure) per name, in order: one Jev request."""
    from ..jev_client import JEV_MODEL, jev_post
    qs = {f"s{i}": question(n) for i, n in enumerate(names)}
    r = await jev_post({"model": JEV_MODEL, "state": state(report), "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    out: List[float] = []
    for i in range(len(names)):
        p = (ans.get(f"s{i}") or {}).get("noul")
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            raise ValueError("jev: incomplete answers")      # a missing answer is never "not mentioned"
        out.append(float(p))
    return out


def structures(inp: ReviewInput) -> List[str]:
    """The COVERS structures of the FINDINGS paragraphs, in sheet order, minus those of a paragraph a SUPPRESS rule
    may have left out and that is absent from the report (no header, none of its units)."""
    st = inp.template_structure
    if not isinstance(st, dict):
        return []
    report = inp.artifacts.report or ""
    roles = {s.get("name"): s.get("role") for s in st.get("sections") or [] if isinstance(s, dict)}
    rules = [r for r in st.get("rules") or [] if isinstance(r, dict)]
    units: Dict[str, List[str]] = {}
    for kind in ("normals", "negatives"):
        for u in st.get(kind) or []:
            if isinstance(u, dict) and u.get("paragraph"):
                units.setdefault(u["paragraph"], []).append(u.get("text") or "")
    for r in rules:
        if r.get("paragraph"):
            units.setdefault(r["paragraph"], []).extend([r.get("target") or "", r.get("then_text") or ""])
    stated = {u.get("paragraph") for kind in ("normals", "negatives") for u in st.get(kind) or [] if isinstance(u, dict)}
    stated |= {f.get("paragraph") for f in st.get("fixed_blocks") or [] if isinstance(f, dict) and f.get("paragraph")}
    fixed = {" ".join((f.get("text") or "").lower().split()) for f in st.get("fixed_blocks") or [] if isinstance(f, dict)}
    stated |= {r.get("paragraph") for r in rules       # structures stored before FIXED carried a paragraph
               if r.get("target") and " ".join(r["target"].lower().split()) in fixed}
    out: List[str] = []
    for p in st.get("paragraphs") or []:
        if not isinstance(p, dict) or roles.get(p.get("section")) != "findings":
            continue
        own = [r for r in rules if r.get("paragraph") == p.get("id")]
        if p.get("id") not in stated and own and all(r.get("effect") == "use" for r in own):
            continue                     # optional by design: only conditional fill-ins ("RULE WHEN ... USE")
        suppressible = any(r.get("effect") in _SUPPRESS and (r.get("paragraph") == p.get("id") or (
            r.get("effect") == "suppress_section" and r.get("target") == p.get("section"))) for r in rules)
        if suppressible:
            texts = [p.get("header") or ""] + units.get(p.get("id"), [])
            if not any(_find(report, t) for t in texts if t):
                continue
        out += [c for c in p.get("covers") or [] if isinstance(c, str) and c.strip()]
    return list(dict.fromkeys(out))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def mention_items(inp: ReviewInput, run_id: str, ask: Optional[Ask] = None
                        ) -> Tuple[List[ReviewItem], Optional[dict]]:
    """(quiet notes, log); ([], None) for a report with no grammar structure. Never raises."""
    if not isinstance(inp.template_structure, dict):
        return [], None
    if inp.template_sheet_changed:
        return [], {"sheet_changed": True}
    log: dict = {"structure_asked": 0, KIND: 0, "capped": 0, "structure_check_unavailable": 0, "error": None}
    try:
        names = structures(inp)
        if not names:
            return [], log
        log["structure_asked"] = len(names)
        report = inp.artifacts.report or ""
        ps = await asyncio.wait_for((ask or ask_mentioned)(report, names), TIMEOUT_S)
        if len(ps) != len(names):
            raise ValueError("jev: answer count mismatch")
    except Exception as e:  # noqa: BLE001 - fail open: no note
        log["structure_check_unavailable"] = 1
        log["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        logger.info("review engine: structure check unavailable (%s)", log["error"])
        return [], log
    h = text_hash(report)
    out: List[ReviewItem] = []
    for n, p in zip(names, ps):
        if p >= NOT_MENTIONED:
            continue
        log[KIND] += 1
        if len(out) >= MAX_NOTES:
            log["capped"] += 1
            continue
        label = f"Not mentioned: {title(n)} — worth a look"
        out.append(ReviewItem(
            key=item_key("accuracy", KIND, n), report_id=inp.report_id, run_id=run_id, lane="accuracy",
            detectors=[DETECTOR], kind=KIND, cls="info", anchor=None, label=label[:80], reason=label, edit=None,
            evidence={"source": DETECTOR, "structure": n, "p": round(float(p), 3)}, status="open",
            history=[{"at": _now(), "event": "created", "actor": "engine", "text_hash": h, "detail": {"kind": KIND}}]))
    return out, log


__all__ = ["KIND", "NOT_MENTIONED", "MAX_NOTES", "question", "state", "title", "structures", "ask_mentioned",
           "mention_items"]
