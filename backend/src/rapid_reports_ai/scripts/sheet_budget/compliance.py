"""Count structural elements in a produced skill sheet.

This is what makes structural budgets better than word budgets: compliance is
measurable. Counts are reported per-field so partial compliance (findings
honoured, variants ignored) stays visible instead of collapsing to pass/fail.

Parses the sheet output template defined in quick_report_analyser.py - the
Style Exemplars block (`- **<Finding>**` with `Normal:` / `Abnormal (...)`
sub-bullets), the quoted Mandatory negatives line, the `- IF ... THEN` clause
list, and the `- **<X> exemplar:**` impression block.
"""
from __future__ import annotations

import re

from .tiers import BUDGETED_INTS

_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.M)
_FINDING_BULLET = re.compile(
    r"^-\s+\*\*(?!Mandatory|In-scope|Out-of-scope)[^*]+\*\*\s*$", re.M
)
_VARIANT_BULLET = re.compile(r"^\s{2,}-\s+(Normal|Abnormal)[^:]*:", re.M)
_CLAUSE = re.compile(r"^-\s+IF\b", re.M)
_IMPRESSION_EX = re.compile(r"^-\s+\*\*\w+ exemplar:\*\*", re.M)
# The model emits negatives either inline on one line or as an indented
# sub-list (both forms occur across the bake-off corpus), so capture the whole
# block up to the next top-level `- **` bullet and count quoted strings in it.
# Sub-bullets are indented, so the lookahead does not terminate on them.
_NEGATIVES_BLOCK = re.compile(
    r"^-\s+\*\*Mandatory negatives:\*\*(.*?)(?=^-\s+\*\*|\Z)", re.M | re.S
)


def _section_body(sheet: str, title: str) -> str:
    """Return the text between `## <title>` and the next `## ` heading."""
    matches = list(_SECTION.finditer(sheet))
    for i, m in enumerate(matches):
        if m.group(1).strip().lower() == title.lower():
            end = matches[i + 1].start() if i + 1 < len(matches) else len(sheet)
            return sheet[m.end():end]
    return ""


def count_sheet(sheet: str) -> dict[str, int]:
    """Count each budgeted element. variants_per_finding is the max observed.

    Max rather than mean because the budget is an upper bound: the prompt
    allows omitting the complicated variant where no meaningful complicated
    form exists, so a mean would penalise legitimate clinical judgement.
    """
    exemplars = _section_body(sheet, "Style Exemplars")
    findings = _FINDING_BULLET.findall(exemplars)

    # Split on the finding bullets and count variant sub-bullets in each block.
    chunks = _FINDING_BULLET.split(exemplars)[1:]
    per_finding = [len(_VARIANT_BULLET.findall(c)) for c in chunks]

    neg_match = _NEGATIVES_BLOCK.search(sheet)
    negatives = len(re.findall(r'"[^"]+"', neg_match.group(1))) if neg_match else 0

    return {
        "findings": len(findings),
        "variants_per_finding": max(per_finding) if per_finding else 0,
        "mandatory_negatives": negatives,
        "interpretive_clauses": len(
            _CLAUSE.findall(_section_body(sheet, "Interpretive Clause Rules"))
        ),
        "impression_exemplars": len(
            _IMPRESSION_EX.findall(_section_body(sheet, "Impression Exemplars"))
        ),
    }


def check(sheet: str, tier: dict) -> dict[str, dict]:
    """Compare counts against a tier's budget, one verdict per field."""
    got = count_sheet(sheet)
    out: dict[str, dict] = {}
    for field in BUDGETED_INTS:
        want = tier.get(field)
        if want is None:  # unbudgeted (control tier, or field not budgeted)
            out[field] = {"want": None, "got": got[field], "ok": True}
        else:
            out[field] = {"want": want, "got": got[field], "ok": got[field] == want}
    return out


# ── Defeasibility pairing (ledger L-19) ─────────────────────────────────────
# The prose form of this requirement complies at ~40% even though the base
# analyser prompt already states it twice. The countable form demands one
# `SUPPRESS IF:` clause per canonical default-normal line, which is checkable.

_CANONICAL_BLOCK = re.compile(
    r"^-\s+\*\*Canonical default-normal lines:\*\*(.*?)(?=^-\s+\*\*|^##|\Z)", re.M | re.S
)
_CANONICAL_ENTRY = re.compile(r"^\s+-\s+\*\*?[^:*]+\*?\*?:", re.M)
_SUPPRESS_IF = re.compile(r"SUPPRESS IF\s*:", re.I)


def defeasibility_pairing(sheet: str) -> dict:
    """Count canonical default-normal lines against paired suppression conditions.

    `paired` is True only when every canonical line carries its own condition —
    a shared or blanket condition does not satisfy the requirement.
    """
    m = _CANONICAL_BLOCK.search(sheet)
    block = m.group(1) if m else ""
    lines = len(_CANONICAL_ENTRY.findall(block))
    supp = len(_SUPPRESS_IF.findall(block))
    return {
        "canonical_lines": lines,
        "suppress_conditions": supp,
        "paired": lines > 0 and supp >= lines,
    }
