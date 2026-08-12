"""Tier definitions for the sheet-budget experiment.

The integer fields do double duty: they render into the prompt directive AND
become the expected counts the compliance checker asserts against the produced
sheet. T1 is the unbudgeted control - every field null, directive empty.
"""
from __future__ import annotations

import json
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[4]
TIERS_PATH = BACKEND_ROOT / "test_cases" / "qwen_sheet_budget.json"

BUDGETED_INTS = (
    "findings",
    "variants_per_finding",
    "impression_exemplars",
    "interpretive_clauses",
    "mandatory_negatives",
)


def load_tiers(path: Path | None = None) -> list[dict]:
    return json.loads((path or TIERS_PATH).read_text())


def validate_tiers(tiers: list[dict]) -> None:
    """Every budgeted integer must be non-increasing down the ladder.

    A tier that budgets *more* than the tier above it breaks the monotonic
    reading of the curve, so it is a config error rather than a warning.
    """
    for field in BUDGETED_INTS:
        seen = [(t["id"], t[field]) for t in tiers if t.get(field) is not None]
        for (prev_id, prev), (cur_id, cur) in zip(seen, seen[1:]):
            if cur > prev:
                raise ValueError(
                    f"{field} increases from {prev_id}={prev} to {cur_id}={cur}; "
                    "budgets must be non-increasing down the ladder"
                )


def render_directive(tier: dict) -> str:
    """Turn a tier's integers into prompt text. Empty string for the control."""
    if all(tier.get(f) is None for f in BUDGETED_INTS):
        return ""
    lines = []
    if tier.get("findings") is not None and tier.get("variants_per_finding") is not None:
        lines.append(
            f"- **Style Exemplars:** cover exactly {tier['findings']} findings, "
            f"with exactly {tier['variants_per_finding']} severity-graded "
            f"variant(s) each."
        )
    if tier.get("impression_exemplars") is not None:
        lines.append(
            f"- **Impression Exemplars:** emit exactly "
            f"{tier['impression_exemplars']} exemplar(s)."
        )
    if tier.get("interpretive_clauses") is not None:
        lines.append(
            f"- **Interpretive Clause Rules:** emit exactly "
            f"{tier['interpretive_clauses']} clause(s)."
        )
    if tier.get("mandatory_negatives") is not None:
        lines.append(
            f"- **Mandatory negatives:** emit exactly "
            f"{tier['mandatory_negatives']} negative(s)."
        )
    if tier.get("normal_study_path") == "primary_only":
        lines.append(
            "- **Normal-study path:** cover the primary system only. Omit the "
            "per-system sweep and the Canonical default-normal lines list."
        )
    return "\n".join(lines)
