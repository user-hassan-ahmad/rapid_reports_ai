"""Guards for the v2 parallel pipeline."""
from __future__ import annotations

import pathlib

from rapid_reports_ai import report_v2 as v2


def test_production_does_not_import_v2():
    """v2 is a parallel development track; nothing live may depend on it
    until the deliberate swap."""
    src = pathlib.Path(v2.__file__).parent
    offenders = []
    for f in src.rglob("*.py"):
        if f.name in {"report_v2.py"} or "scripts" in f.parts or "test" in f.name:
            continue
        if "report_v2" in f.read_text(errors="replace"):
            offenders.append(f.name)
    assert not offenders, f"production modules import report_v2: {offenders}"


def test_analyser_v2_forbids_assertion_and_requires_typed_output():
    p = v2.ANALYSER_V2
    assert "may not assert any finding" in p
    assert "UNASSESSABLE-IF" in p and "NOT:" in p           # near-miss exclusions
    assert "SUPPRESS-IF-HISTORY" in p                        # history defeasibility
    assert "T-NEG" in p and "T-IND" in p                     # templates are the only prose
    assert "QUESTION or COMPLETENESS" in p                   # tiering
    assert "physiotherapy" in p                              # remit exclusion inline


def test_generator_v2_carries_the_input_integrity_and_gate_rules():
    p = v2.GENERATOR_V2
    assert "is NOT completed" in p                           # truncation
    assert "Never silently harmonise" in p                   # laterality conflict
    assert "does not fire" in p                              # strict clause matching
    assert "new facts are fabrication" in p                  # fact gate
    assert "exactly one branch fires" in p                   # slot execution
    assert "Grade I" in p                                    # grading fabrication rule


def test_validator_counts_and_flags_stray_prose():
    sheet = """# DECISION SHEET
## OBLIGATIONS
- OB1 | QUESTION | talar dome
  OBSERVES: fragment-parent interface
  T-NEG: "No fluid signal undermines the osteochondral fragment."
  UNASSESSABLE-IF: adjacent marrow oedema ; NOT: joint effusion
  T-IND: "Fragment stability is indeterminate owing to {obscurant}."
- OB2 | COMPLETENESS | tendons
  OBSERVES: tendon calibre and signal
  T-NEG: "The peroneal and posterior tendon groups are intact."
"""
    v = v2.validate_sheet_v2(sheet)
    assert v["obligations"] == 2 and v["question_tier"] == 1
    assert v["unassessable"] == 1 and v["t_ind"] == 1 and v["ind_paired"]
    assert v["stray_prose"] == []
    bad = sheet + '\n- NOTE: "The talar dome is entirely normal in this patient today."\n'
    assert v2.validate_sheet_v2(bad)["stray_prose"], "emittable prose outside templates must flag"


def test_prompt_budget_holds():
    """The point of v2 is a typed contract instead of instruction bulk. If these
    creep toward the old sizes (42k + 33k), the rewrite has failed its premise."""
    assert len(v2.ANALYSER_V2) < 12000, f"analyser v2 at {len(v2.ANALYSER_V2)}"
    assert len(v2.GENERATOR_V2) < 10000, f"generator v2 at {len(v2.GENERATOR_V2)}"


def test_generator_v2_carries_format_and_impression_discipline():
    """Ported from v1 after radiologist review: headers drifted (principle 9's
    job) and impressions ran verbose (principles 3/10 + no-restatement). These
    constrain form, not the fact-freedom the v2 architecture requires."""
    p = v2.GENERATOR_V2
    assert "on its own line, terminated by a colon" in p
    # 2026-08-17 re-anchor: the impression is epistemic - a framework of the
    # consultant's questions frames synthesis; action is one OUTPUT of
    # understanding, and RECOMMEND is vocabulary, not quota. The action-menu
    # anchor was the shared root of the staging-descriptor loss, the inventory
    # tails, and (by making "what happens next" the central question) the
    # treatment trespass.
    flat = " ".join(p.split())
    assert "What do we now know that we did not?" in flat
    assert "characteristics ARE the conclusion" in flat
    assert '"no cause identified" is a complete answer' in flat
    assert "not a quota to spend" in flat
    assert "no recommendation is a strong impression" in flat
    assert "Your domain ends at understanding" in flat
    flat = " ".join(p.split())
    assert "carries an answer the referrer needs" in flat
    assert "treatment, procedures, monitoring" in flat and "never yours" in flat


def test_structure_topology_is_declared_in_phase_one_and_rendered_in_phase_two():
    """Macro-structure (radiologist, 2026-08-15): multi-region and multi-level
    studies need organised FINDINGS. The DECISION lives in the sheet - phase 1
    knows the scan type and declares FLAT / COMPARTMENTS / UNITS as a typed
    field - and phase 2 carries only the rendering contract. Generator-side
    derivation would be per-draw improvisation; scan-type hardcoding would not
    generalise. Stated from topology, not worked clinical examples."""
    a, g = v2.ANALYSER_V2, v2.GENERATOR_V2
    for token in ("## STRUCTURE", "FLAT", "COMPARTMENTS", "UNITS", "GLOBAL", "PER-UNIT"):
        assert token in a
    assert "from topology, not from habit" in a
    # 2026-08-17: the flow is computed in phase 1 (v1's "Sweep order:" field,
    # reconciled back in). Sheet declares blocks/stations in render order -
    # anatomical convention for COMPARTMENTS, question-directed for FLAT;
    # the generator renders, never re-derives. Scope can never delete dictation
    # (an L1 fracture was dropped when the sheet mis-scoped the TL spine OUT).
    af = " ".join(a.split()); gf = " ".join(g.split())
    assert "IN THE ORDER THE REPORT WILL RENDER THEM" in af
    assert "cranio-caudal" in af
    assert "question-directed" in af
    assert "never a region another modality would merely show better" in af
    assert "never re-derived here" in gf
    assert "never opens on a peripheral normal" in gf
    assert "never delete a dictated finding" in gf
    assert "most consequential compartment" not in gf
    # 2026-08-17 radiologist review: FLAT reports rendered as dense monoliths
    # (v1's paragraph consolidation lost in translation) and impressions opened
    # on a findings recap. FINDINGS owns detail; the impression opens at the
    # unifying diagnosis and keeps a value only as a decision determinant.
    assert "never one solid block" in gf
    assert "index paragraph" in gf
    assert "unifying diagnostic statement" in gf
    assert "never a recap of findings" in gf
    assert "deleted, not compressed" in gf
    # 2026-08-17: "unifying statement" was drawing a compressed findings recap
    # as sentence 1, whose facts the argument sentences then repeated. The
    # impression is an argument - each fact appears exactly once, where it
    # earns its conclusion.
    assert "an argument, not an inventory" in gf
    assert "appears exactly once" in gf
    assert "no later sentence reintroduces it" in gf
    assert "no fact appears twice within the impression" in gf
    for token in ("COMPARTMENTS", "UNITS", "Never enumerate normal units"):
        assert token in g
    flat = " ".join(g.split())
    assert "reel into one or two sentences" in flat
