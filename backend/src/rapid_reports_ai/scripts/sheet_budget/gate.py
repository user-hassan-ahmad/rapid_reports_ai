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
    # Mural gas in a bowel wall IS pneumatosis intestinalis - different words,
    # same finding. Measured at ~55% of generations on ct_tap (11/20 Groq draws)
    # and missed entirely until 2026-08-13 because no pair covered it. The
    # negated-clause guard keeps "No pneumatosis intestinalis" from counting as
    # its own positive.
    (r"mural gas|intramural gas|pneumatosis intestinalis",
     r"[Nn]o pneumatosis"),
)


# A positive-assertion pattern can match inside an already-negated clause:
# "No pleural effusion is present" contains "effusion is present". Treating that
# as a positive finding made a single clean sentence trip both halves of a pair.
# Look back to the start of the sentence and skip the match if it sits under a
# negation. (Found in REASONING_CAPFIX on_on/ct_thorax_smoker_lung_nodule.)
_NEGATED_CLAUSE = re.compile(r"\bno\b[^.]{0,60}$", re.I)


def _sentence_start(text: str, pos: int) -> int:
    """Offset of the start of the sentence containing `pos`."""
    return text.rfind(".", 0, pos) + 1


def _positive_sentences(pattern: str, text: str) -> set[int]:
    """Sentence offsets holding a genuine positive assertion.

    A match inside an already-negated clause is not a positive finding.
    """
    found = set()
    for m in re.finditer(pattern, text):
        start = _sentence_start(text, m.start())
        if _NEGATED_CLAUSE.search(text[start:m.start()]):
            continue
        found.add(start)
    return found


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
        pos_sentences = _positive_sentences(pos, report)
        if not pos_sentences:
            continue
        # The negation must sit in a different sentence from the positive
        # finding; in the same sentence it is one statement, not two.
        for m in re.finditer(neg, report):
            if _sentence_start(report, m.start()) not in pos_sentences:
                hits.append(m.group(0))
                break
    if hits:
        failures.append("self_contradiction")
        detail["self_contradiction"] = hits

    stripped = report.strip()
    if stripped and stripped[-1] not in '.)]”"':
        failures.append("truncation")
        detail["truncation"] = [stripped[-60:]]

    return {"passed": not failures, "failures": failures, "detail": detail}
