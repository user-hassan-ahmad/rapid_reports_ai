"""Applicable-guideline request validation — no Firecrawl dependency (safe for audit import path)."""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

MAX_GUIDELINE_SYSTEM_LEN = 60
MAX_APPLICABLE_GUIDELINES_PER_REPORT = 4


class DeploymentContext(str, Enum):
    """Product deployment; drives guideline ordering policy."""

    NHS_UK = "nhs_uk"


def validate_applicable_guidelines_payload(raw: Optional[List[Any]]) -> List[dict]:
    """
    Safety net: drop non-dicts, oversize system names, and cap list length.
    Does not enforce mutual exclusion between frameworks — model + prompts own that.
    """
    if not raw:
        return []
    out: List[dict] = []
    for g in raw:
        if not isinstance(g, dict):
            print(f"[GUIDELINE_PIPELINE] validate: skip non-dict {type(g).__name__}")
            continue
        sys_name = g.get("system")
        if sys_name is None:
            continue
        s = str(sys_name).strip()
        if len(s) > MAX_GUIDELINE_SYSTEM_LEN:
            print(
                f"[GUIDELINE_PIPELINE] validate: skip system len={len(s)} "
                f"(max {MAX_GUIDELINE_SYSTEM_LEN}) preview={s[:40]!r}…"
            )
            continue
        gg = dict(g)
        gg["system"] = s
        out.append(gg)
    if len(out) > MAX_APPLICABLE_GUIDELINES_PER_REPORT:
        print(
            f"[GUIDELINE_PIPELINE] validate: cap {MAX_APPLICABLE_GUIDELINES_PER_REPORT} "
            f"— truncated from {len(out)}"
        )
        out = out[:MAX_APPLICABLE_GUIDELINES_PER_REPORT]
    return out


def _canonicalize_type_on_dict(g: dict) -> dict:
    """Normalise ``type`` to schema literals when clearly intended; shallow copy."""
    t = g.get("type")
    if t is None:
        return dict(g)
    raw = str(t).strip().lower().replace(" ", "_")
    out = dict(g)
    if raw in ("uk_pathway",):
        out["type"] = "uk_pathway"
    elif raw in ("classification",):
        out["type"] = "classification"
    elif raw in ("other",):
        out["type"] = "other"
    return out


def normalize_applicable_guidelines_order(
    guidelines: List[dict],
    context: DeploymentContext = DeploymentContext.NHS_UK,
) -> List[dict]:
    """
    NHS UK: ``uk_pathway`` entries precede all other types when both are present.
    Preserves relative order within each group. Canonicalises ``type`` casing.

    Other deployment contexts: no reordering (future: context-keyed rules).
    """
    if not guidelines:
        return []
    canonicalized = [_canonicalize_type_on_dict(g) for g in guidelines]
    if context is not DeploymentContext.NHS_UK:
        return canonicalized
    uk = [g for g in canonicalized if g.get("type") == "uk_pathway"]
    rest = [g for g in canonicalized if g.get("type") != "uk_pathway"]
    reordered = uk + rest
    if reordered != canonicalized:
        print("  └─ [GUIDELINE] UK primacy normalisation applied")
    return reordered
