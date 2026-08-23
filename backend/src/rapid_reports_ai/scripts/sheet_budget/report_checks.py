"""Deterministic report defect checks, independent of sheet version.

These run on a report alone and work on v1, v2 and v3 output identically. They
exist because rubric v2.2 scored 24/24 dimensions at 5.00 on six reports that a
manual read found four real defects in (ledger L-30), and because a hand-written
contradiction pair list only finds modes someone already thought of (L-28).

Screen, not gate: a false positive costs a glance, a false negative costs a
signed report. Never optimise a model against these scores (L-14).

Nothing in production imports this module - it runs over harness output.
"""
from __future__ import annotations

import re

# The report-level sections, which are the same across v1, v2 and v3 - that is
# what makes this module version-agnostic. LIMITATIONS is a v1-era section that
# still appears in the corpus.
#
# Splitting on *these names only* is load-bearing. Validated against 223 real
# reports: ten of them render compartment blocks as headers (HEAD:, CHEST:,
# ABDOMEN:, VERTEBRAL COLUMN:), and a splitter that promoted those to top-level
# sections left FINDINGS holding only the text before the first compartment.
# Every closure check downstream would then compare the impression against a
# near-empty body and flag every multi-region report. Compartment headers belong
# inside the FINDINGS body, which is where they render.
REPORT_SECTIONS: tuple[str, ...] = (
    "COMPARISON", "TECHNIQUE", "FINDINGS", "IMPRESSION", "LIMITATIONS",
)

# A header is uppercase, colon-terminated, and alone on its line. That is the
# format contract. Trailing whitespace is tolerated - models emit it, and losing
# a section over a stray space is worse than the layout defect itself.
_HEADER = re.compile(
    r"^(" + "|".join(REPORT_SECTIONS) + r"):[ \t]*$", re.M
)


def sections(report: str) -> dict[str, str]:
    """Map report-section name -> section body.

    Sub-headers inside a section (compartment blocks) stay in the body.

    Returns an empty dict when no conforming header is found, rather than
    raising: these checks run on generator output including output that broke
    the contract. **Callers must treat an empty result as a failure, not a
    pass.** 19 reports in the current corpus parse to nothing - 15 emitting
    `COMPARISON` with no colon and 4 putting content on the header line - and a
    check that silently passes on them is the L-28 failure mode one layer down.
    `layout_ok` exists for exactly that.
    """
    marks = [(m.group(1), m.start(), m.end()) for m in _HEADER.finditer(report)]
    out: dict[str, str] = {}
    for i, (name, _start, end) in enumerate(marks):
        stop = marks[i + 1][1] if i + 1 < len(marks) else len(report)
        out[name] = report[end:stop].strip()
    return out


def layout_ok(report: str) -> bool:
    """True when the report is parseable as sections at all.

    Separate from the per-section checks so that a report which breaks the
    format contract fails loudly instead of passing every check vacuously.
    """
    return bool(sections(report))
