"""The narrow fidelity check on lean polish output (no correction cue → nothing dictated lost)."""
from __future__ import annotations

import pytest

from rapid_reports_ai.lean_fidelity import fidelity_violation, verbatim_append


def test_tonights_deletion_is_caught():
    # lab 2026-09-27: "No disc extrusion." replaced "The extrusion measures 7 mm."
    span = "The extrusion measures 7 mm. Modic type 1 endplate change at L5/S1."
    new = "No disc extrusion."
    out = "No disc extrusion. Modic type 1 endplate change at L5/S1."
    assert fidelity_violation(span, new, out, []) is not None


def test_an_overwritten_measurement_is_caught():
    # replay: 27 mm (pulmonary artery) overwritten by the next fragment's 42 mm
    span = "Measuring 27 millimetres. The right ventricle meshes"
    new = "42 millimetres, and the left ventricle"
    out = "Measuring 42 millimetres. The right ventricle meshes, and the left ventricle"
    assert fidelity_violation(span, new, out, []) == "lost_number"


def test_a_lost_side_is_caught():
    assert fidelity_violation("Small left pleural effusion.", "No pneumothorax.",
                              "Small pleural effusion. No pneumothorax.", []) == "lost_side"


def test_an_earlier_line_edit_that_changes_a_fact_without_a_cue_is_caught():
    edit = {"original": "The duct measures 14 mm.", "corrected": "The duct measures 15 mm."}
    assert fidelity_violation("No effusion.", "The heart is normal.", "No effusion. The heart is normal.",
                              [edit]) == "edited_committed"


@pytest.mark.parametrize("original,corrected", [
    # replay: repairs of earlier lines the check must let through
    ("no contact on the exiting L5 nevirate", "no contact on the exiting L5 nerve root."),
    ("There are multiple gallstones", "There are multiple gallstones."),
])
def test_an_earlier_line_repair_that_keeps_the_facts_passes(original, corrected):
    assert fidelity_violation("No effusion.", "", "No effusion.", [{"original": original, "corrected": corrected}]) is None


@pytest.mark.parametrize("span,new,out", [
    # repairs of wording pass: a misheard level, a fragment joined, units and filler tidied
    ("Until 5/s 1, there is a right paracentral disc", "extrusion compressing the S1 nerve root.",
     "L5/S1, there is a right paracentral disc extrusion compressing the S1 nerve root."),
    ("The right ventricle meshes", "42 millimetres.", "The right ventricle measures 42 mm."),
    ("There is a 34 mm spiculated mass in the right upper lobe.", "Um, no pleural effusion.",
     "There is a 34 mm spiculated mass in the right upper lobe. No pleural effusion."),
    ("", "The conus terminates at L1/2.", "The conus terminates at L1/2."),
])
def test_good_polishes_pass(span, new, out):
    assert fidelity_violation(span, new, out, []) is None


@pytest.mark.parametrize("new", ["Actually, make that 7 mm.", "Sorry, that's the right lower lobe.",
                                 "Correction, the nodule is in the left lower lobe.", "Scratch that.", "I mean 14 mm."])
def test_a_correction_cue_lets_the_model_change_things(new):
    assert fidelity_violation("The extrusion measures 9 mm in the left lower lobe.", new,
                              "The extrusion measures 7 mm.", [{"original": "x", "corrected": "y"}]) is None


def test_the_safe_text_is_the_span_with_the_new_words_appended_as_said():
    assert verbatim_append("The extrusion measures 7 mm.", "No disc extrusion.") == \
        "The extrusion measures 7 mm. No disc extrusion."
    assert verbatim_append("Findings.", "\n\nConclusion: stable.") == "Findings.\n\nConclusion: stable."
    assert verbatim_append("", "No effusion.") == "No effusion."


def test_a_bare_cue_ending_the_span_counts_for_the_next_words():
    # "Correction." arrives as its own final; the corrected statement follows without a cue
    assert fidelity_violation("The spleen measures 10 cm. Correction.", "The common bile duct measures 15 mm.",
                              "The spleen measures 10 cm.", [{"original": "14 mm", "corrected": "15 mm"}]) is None


def test_a_cue_earlier_in_the_span_does_not():
    assert fidelity_violation("Actually, the spleen is normal. The duct measures 15 mm.", "No free fluid.",
                              "The spleen is normal. No free fluid.", []) is not None


def test_a_negative_replaced_by_its_positive_is_caught():
    # lab 2026-09-29: "Small left pleural effusion." replaced "No pleural effusion." — the
    # words overlap, so the statement looked kept; the negation did not survive.
    span = "The spleen measures 14 cm and the liver measures 18 cm. No pleural effusion."
    assert fidelity_violation(span, "Small left pleural effusion.",
                              "The spleen measures 14 cm and the liver measures 18 cm. Small left pleural effusion.",
                              []) == "lost_negation"


def test_negations_that_survive_rewording_pass():
    assert fidelity_violation("There is no pleural effusion.", "No pneumothorax.",
                              "No pleural effusion. No pneumothorax.", []) is None
