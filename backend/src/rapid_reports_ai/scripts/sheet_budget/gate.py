"""Free structural/integrity checks. Every run passes through these; only
survivors reach the (paid) v2.2 judge.

The contradiction pairs were derived from the 2026-08-12 bake-off, where a
Qwen generation asserted hilar lymphadenopathy at 14 mm and then denied it in
the same FINDINGS section - the defeasible normal-fill failure the report
integrity hardening exists to prevent.
"""
from __future__ import annotations

import re

REQUIRED_SECTIONS = ("TECHNIQUE", "FINDINGS", "IMPRESSION")

LEAK_MARKERS = (
    "[Done]", "Self-Correction", "Proceeds.", "Output Generation",
    "<think>", "</think>", "Matches all constraints", "I should ensure",
    "Final check",
)

# (positive assertion, blanket negation of the same entity)
CONTRADICTION_PAIRS = (
    (r"lymphadenopathy is present|lymphadenopathy[^.]*measur|enlarged .{0,20}node",
     r"[Nn]o (?:mediastinal or hilar |hilar |mediastinal |significant )?lymphadenopathy"),
    (r"\d+\s?mm[^.]*nodule|nodule[^.]*\d+\s?mm|spiculated nodule",
     r"[Nn]o (?:suspicious )?(?:pulmonary )?nodule(?![^.]*adrenal)"),
    (r"h(?:a)?emorrhage (?:is )?(?:present|identified|noted)",
     r"[Nn]o (?:acute |intracranial )?h(?:a)?emorrhage"),
    (r"effusion is (?:present|noted|identified)|moderate .{0,15}effusion",
     r"[Nn]o (?:pleural )?effusion"),
    (r"consolidation is (?:present|noted|identified)",
     r"[Nn]o (?:focal )?consolidation"),
    (r"free (?:intraperitoneal )?(?:fluid|gas) is (?:present|noted|identified)",
     r"[Nn]o free (?:intraperitoneal )?(?:fluid|gas)"),
)


def run_gate(report: str) -> dict:
    """Return {passed, failures, detail}. Failures are check names."""
    failures: list[str] = []
    detail: dict[str, list[str]] = {}

    missing = [s for s in REQUIRED_SECTIONS if s not in report]
    if missing:
        failures.append("missing_section")
        detail["missing_section"] = missing

    leaks = [m for m in LEAK_MARKERS if m in report]
    if leaks:
        failures.append("thinking_leak")
        detail["thinking_leak"] = leaks

    hits: list[str] = []
    for pos, neg in CONTRADICTION_PAIRS:
        if re.search(pos, report) and (m := re.search(neg, report)):
            hits.append(m.group(0))
    if hits:
        failures.append("self_contradiction")
        detail["self_contradiction"] = hits

    stripped = report.strip()
    if stripped and stripped[-1] not in '.)]”"':
        failures.append("truncation")
        detail["truncation"] = [stripped[-60:]]

    return {"passed": not failures, "failures": failures, "detail": detail}
