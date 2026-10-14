"""Removed sentences (D12, integration spec §7 steps 0 and 3): dictation wins over an earlier removal (reconcile), and
a report clause that asserts a removed sentence is cut only in the safe case (exactly a removed sentence, not stated
by the radiologist), else a high-severity review item. One Jev call per step in the ask_rows shape; it runs whatever
RR_QUALITY_CHECK says, and a Jev failure never edits the report."""
from __future__ import annotations

import logging
import re

from .jev_stack import REMOVED_MIN, STATED_MIN, ask_rows

logger = logging.getLogger(__name__)
_SENT = re.compile(r"(?<=[.!?])\s+")
_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _norm(s: str) -> str:
    """Case, whitespace, a list marker and a final full stop ignored."""
    return re.sub(r"\s+", " ", _MARKER.sub("", s)).strip().rstrip(".").lower()


def _sentences(text: str) -> list[str]:
    return [x for line in text.splitlines() for x in _SENT.split(line) if x.strip()]


def _cut(report: str, clause: str) -> str:
    """Remove one clause: its whole line when it is the line (list item included), else the clause and one space."""
    lines = report.split("\n")
    for i, line in enumerate(lines):
        if clause in line and _norm(line) == _norm(clause):
            return "\n".join(lines[:i] + lines[i + 1:])
    out = re.sub(r"[ \t]+" + re.escape(clause), "", report, count=1)
    return out if out != report else re.sub(re.escape(clause) + r"[ \t]*", "", report, count=1)


def _clauses(report: str) -> list[str]:
    """Report sentences, line by line; an all-caps heading line is not a clause."""
    out: list[str] = []
    for line in report.splitlines():
        out += [s.strip() for s in _SENT.split(line) if s.strip() and not s.strip().isupper()]
    return out


async def reconcile(removed: list[str], plain: str) -> tuple[list[str], list[str]]:
    """(still removed, dropped because the statements state them). Jev down: every removal stands."""
    if not removed:
        return [], []
    # An exact re-dictation wins in code, with no Jev call (and whatever Jev says)
    said = {_norm(x) for x in _sentences(plain)}
    exact = [r for r in removed if _norm(r) in said]
    rest = [r for r in removed if r not in exact]
    for d in exact:
        logger.info("[stack.removed] dictation wins over a removal (exact): %s", d[:80])
    if not rest:
        return [], exact
    removed = rest
    try:
        rows = await ask_rows(plain, removed, [], stated=True, contra=False)
        if len(rows) != len(removed):
            raise ValueError("short Jev reply")
    except Exception as e:  # noqa: BLE001
        logger.warning("[stack.removed] reconcile failed: %s", type(e).__name__)
        return list(removed), exact
    still = [r for r, c in zip(removed, rows) if c.stated < STATED_MIN]
    dropped = [r for r, c in zip(removed, rows) if c.stated >= STATED_MIN]
    for d in dropped:
        logger.info("[stack.removed] dictation wins over a removal: %s", d[:80])
    return still, exact + dropped


async def guard(report: str, removed: list[str], plain: str) -> tuple[str, list[dict], list[dict]]:
    """(report, applied removals, review items) for each report clause that says the same as a removed sentence."""
    if not removed:
        return report, [], []
    clauses = _clauses(report)
    if not clauses:
        return report, [], []
    try:
        rows = await ask_rows(plain, clauses, removed, stated=True, contra=False)
        if len(rows) != len(clauses):
            raise ValueError("short Jev reply")
    except Exception as e:  # noqa: BLE001
        logger.warning("[stack.removed] guard failed: %s", type(e).__name__)
        return report, [], [{"kind": "removed_unverified", "severity": "medium",
                             "message": "Couldn't verify removed sentences"}]
    exact = {_norm(r) for r in removed}
    edits: list[dict] = []
    items: list[dict] = []
    for clause, c in zip(clauses, rows):
        if c.removed < REMOVED_MIN:
            continue
        if _norm(clause) in exact and c.stated < STATED_MIN and report.count(clause) == 1:
            report = _cut(report, clause)
            edits.append({"type": "removal", "clause": clause})
        else:
            items.append({"kind": "removed_asserted", "severity": "high", "text": clause,
                          "message": "Asserts a removed sentence; not auto-removed"})
    return report, edits, items
