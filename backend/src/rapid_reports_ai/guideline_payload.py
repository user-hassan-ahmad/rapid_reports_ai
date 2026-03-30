"""Applicable-guideline request validation — no Firecrawl dependency (safe for audit import path)."""

from __future__ import annotations

from typing import Any, List, Optional

MAX_GUIDELINE_SYSTEM_LEN = 60
MAX_APPLICABLE_GUIDELINES_PER_REPORT = 4


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
