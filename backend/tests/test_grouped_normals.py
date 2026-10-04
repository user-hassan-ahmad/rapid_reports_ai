"""Grouped normals: analyser directive (opt-in), split / subtract / self-check, dictated guard, brief wiring."""
from __future__ import annotations

import pytest

from rapid_reports_ai import normal_groups as ng
from rapid_reports_ai import quick_report_analyser as qa
from rapid_reports_ai import quick_report_brief as qb


# ── analyser directive ──────────────────────────────────────────────────────

def test_directive_off_leaves_the_production_prompt_byte_identical(monkeypatch):
    monkeypatch.delenv("RR_GROUPED_NORMALS", raising=False)
    model = "qwen-3.8-27b"
    assert qa.production_directives() == qa.PRODUCTION_DIRECTIVES
    base = qa.ANALYSER_SYSTEM_PROMPT_OPEN_WEIGHTS + qa.PRUNE_V1 + qa.FINDING_NEGATIVES
    assert qa.get_analyser_prompt(model, directives=qa.production_directives()) == base
    assert "linked atoms and prose" not in base


def test_directive_on_appends_the_grouped_block_once(monkeypatch):
    monkeypatch.setenv("RR_GROUPED_NORMALS", "1")
    assert qa.production_directives() == qa.PRODUCTION_DIRECTIVES + ("grouped_normals",)
    p = qa.get_analyser_prompt("qwen-3.8-27b", directives=qa.production_directives())
    assert p.endswith(qa.GROUPED_NORMALS) and p.count("Normal-study path as linked atoms and prose") == 1
    # Case-agnostic: structural placeholders only.
    assert "P1 | N1 N2 N3 | The A, B and C are unremarkable." in qa.GROUPED_NORMALS


def test_prompt_version_unchanged_when_off(monkeypatch):
    monkeypatch.delenv("RR_GROUPED_NORMALS", raising=False)
    off = qa.analyser_prompt_version("qwen-3.8-27b")
    monkeypatch.setenv("RR_GROUPED_NORMALS", "1")
    assert qa.analyser_prompt_version("qwen-3.8-27b") != off


# ── split ───────────────────────────────────────────────────────────────────

def test_parse_lists_structures_descriptor_and_tail():
    g = ng.parse_grouped("The liver, spleen, pancreas and adrenal glands are unremarkable.")
    assert g.structures == ["liver", "spleen", "pancreas", "adrenal glands"]
    assert (g.verb, g.descriptor, g.tail) == ("are", "unremarkable", [])
    g = ng.parse_grouped("The kidneys are unremarkable with no hydronephrosis or calculus.")
    assert g.structures == ["kidneys"] and g.tail == ["hydronephrosis", "calculus"] and g.tail_conj == "or"
    g = ng.parse_grouped("The stomach, small bowel and colon are unremarkable; no wall thickening, dilatation or obstruction.")
    assert g.tail == ["wall thickening", "dilatation", "obstruction"]


@pytest.mark.parametrize("s", [
    "No free fluid.",
    "The visualised osseous structures show no aggressive lesion.",
    "The common bile duct measures 6 mm.",
    "The kidneys are normal apart from a simple cyst.",
    "The liver is normal in size, contour and attenuation.",
])
def test_unparseable_sentences_pass_through(s):
    assert ng.parse_grouped(s) is None


def test_atoms_are_one_stated_line_each_with_agreement():
    g = ng.parse_grouped("The spleen, kidneys and pancreas are unremarkable with no free fluid.")
    assert g.atoms() == [("structure", "The spleen is unremarkable."), ("structure", "The kidneys are unremarkable."),
                         ("structure", "The pancreas is unremarkable."), ("tail", "No free fluid.")]


# ── subtract ────────────────────────────────────────────────────────────────

def test_all_kept_is_verbatim_with_spans():
    g = ng.parse_grouped("The A, B and C are unremarkable.")
    r = ng.subtract(g, [True, True, True])
    assert r.mode == "verbatim" and r.text == g.text
    assert [r.text[a:b] for a, b in r.spans] == ["A", "B", "C"]


def test_middle_structure_removed():
    g = ng.parse_grouped("The liver, spleen and pancreas are unremarkable.")
    r = ng.subtract(g, [True, False, True])
    assert (r.mode, r.text) == ("subtracted", "The liver and pancreas are unremarkable.")
    assert r.spans[1] is None and r.text[slice(*r.spans[2])] == "pancreas"


def test_plural_agreement_after_subtraction():
    g = ng.parse_grouped("The spleen and kidneys are unremarkable.")
    assert ng.subtract(g, [True, False]).text == "The spleen is unremarkable."
    assert ng.subtract(g, [False, True]).text == "The kidneys are unremarkable."
    g = ng.parse_grouped("The pancreas and adrenal glands appear normal.")
    assert ng.subtract(g, [True, False]).text == "The pancreas appears normal."


def test_tail_negatives_subtracted_and_kept():
    g = ng.parse_grouped("The kidneys are unremarkable with no hydronephrosis, calculus or perinephric stranding.")
    r = ng.subtract(g, [True, True, False, True])
    assert r.text == "The kidneys are unremarkable with no hydronephrosis or perinephric stranding."
    # Structure affected, tail kept: the tail alone.
    r = ng.subtract(g, [False, True, True, True])
    assert (r.mode, r.text) == ("tail_only", "No hydronephrosis, calculus or perinephric stranding.")
    # Everything affected: nothing rendered.
    assert ng.subtract(g, [False] * 4).mode == "none"


def test_self_check_failure_falls_back_to_per_structure(monkeypatch):
    g = ng.parse_grouped("The liver, spleen and pancreas are unremarkable.")
    monkeypatch.setattr(ng, "parse_grouped", lambda s: None)   # the rebuilt sentence fails to re-parse
    r = ng.subtract(g, [True, False, True])
    assert r.mode == "per_structure"
    assert r.text == "The liver is unremarkable. The pancreas is unremarkable."
    assert r.text[slice(*r.spans[2])] == "pancreas" and r.spans[1] is None


def test_dictated_overlap_on_structure_and_tail_words():
    assert ng.dictated_overlap(["kidneys"], ["Right kidney 2 cm cyst"]) == ["Right kidney 2 cm cyst"]
    assert ng.dictated_overlap(["hydronephrosis"], ["no hydronephrosis"]) == ["no hydronephrosis"]
    assert ng.dictated_overlap(["small bowel"], ["small left pleural effusion"]) == []


def test_shared_modifier_items_join_their_head_noun():
    g = ng.parse_grouped("The remaining metacarpal bases and dorsal and volar soft tissues are unremarkable.")
    assert g.structures == ["remaining metacarpal bases", "dorsal and volar soft tissues"]
    assert ng.subtract(g, [True, False]).text == "The remaining metacarpal bases are unremarkable."
    assert ng.parse_grouped("The left and right kidneys are unremarkable.").structures == ["left and right kidneys"]
    g = ng.parse_grouped("The carpal bones, radiocarpal, midcarpal and distal radioulnar joints, flexor and extensor "
                         "tendons, and median and ulnar nerves are unremarkable.")
    assert g.structures == ["carpal bones", "radiocarpal, midcarpal and distal radioulnar joints",
                            "flexor and extensor tendons", "median and ulnar nerves"]
    r = ng.subtract(g, [False, True, True, True])
    assert r.mode == "subtracted" and r.text == ("The radiocarpal, midcarpal and distal radioulnar joints, flexor and "
                                                 "extensor tendons, and median and ulnar nerves are unremarkable.")
    assert ng.parse_grouped("The spinal canal and conus are unremarkable.").structures == ["spinal canal", "conus"]
    assert ng.parse_grouped("The gluteal, adductor, iliopsoas and hamstring musculature are unremarkable.") is None
    assert ng.is_plural("thalami") and ng.is_plural("basal ganglia")
    assert ng.parse_grouped("The distal radius, ulna and distal radioulnar joint are unremarkable.").structures == [
        "distal radius", "ulna", "distal radioulnar joint"]


def test_positive_findings_leave_out_negatives_and_dictated_normals():
    items = ["Normal tendons", "No oedema of the ligaments", "3 mm effusion in the joint", "The bones look fine"]
    assert ng.positive_findings(items) == ["3 mm effusion in the joint"]


def test_tail_covered_by_a_dictated_negative():
    negs = ["No bone marrow oedema or fractures", "No free fluid"]
    assert ng.covered_by_dictation("bone marrow oedema", negs) == "No bone marrow oedema or fractures"
    assert ng.covered_by_dictation("fluid collection", negs) is None
    # A one-word tail needs the negative to be about this sentence's structures.
    assert ng.covered_by_dictation("oedema", negs, ["labrum"]) is None
    assert ng.covered_by_dictation("effusion", ["No effusion"], ["right hip joint"]) == "No effusion"
    assert ng.covered_by_dictation("fracture", ["No fracture of the hook of hamate"], ["hamate"]) is None


def test_part_nouns_and_trailing_adjectives_and_of_phrases():
    assert ng.parse_grouped("The femoral head, neck and acetabulum are unremarkable.") is None
    assert ng.parse_grouped("The lower thoracic and lumbar spine are unremarkable.").structures == [
        "lower thoracic and lumbar spine"]
    assert ng.parse_grouped("The aorta and its major branches are patent.") is None
    g = ng.parse_grouped("The bones and soft tissues of the imaged volume are unremarkable.")
    assert ng.subtract(g, [False, True]).text == "The soft tissues of the imaged volume are unremarkable."


# ── brief wiring ────────────────────────────────────────────────────────────

SHEET = '''# Skill Sheet: CT abdomen — test

## Structural Pattern
- **Sections:** FINDINGS, IMPRESSION
- **Normal-study path:** "The liver, spleen and pancreas are unremarkable. The kidneys are unremarkable with no hydronephrosis. The bladder and pelvic viscera are unremarkable. The visualised osseous structures show no aggressive lesion."

## Companion Matrix
- **Mandatory negatives:** (one line each)
  - "No free fluid" (perforation)
'''


def _stub(monkeypatch, affected: set, qaff: set = frozenset()):
    seen = {}

    async def fake_jev(state, questions):
        seen["q"] = questions
        return {k: {"noul": 0.9 if k in affected else 0.1} for k in questions}

    async def fake_qwen(state, negs, normals, measurements):
        seen["normals"] = normals
        return qb.QwenDecisions(negatives=[qb.NegativeDecision(index=i, action="keep") for i in range(len(negs))],
                                affected_normals=sorted(qaff), applicable_measurements=[])

    async def no_split(negs):
        return [[n] for n in negs]

    async def no_plan(*a):
        raise RuntimeError("no plan")

    async def no_fallback(*a):
        return None
    monkeypatch.setattr(qb, "_jev", fake_jev)
    monkeypatch.setattr(qb, "_qwen", fake_qwen)
    monkeypatch.setattr(qb, "_split_bundled", no_split)
    monkeypatch.setattr(qb, "_plan", no_plan)
    monkeypatch.setattr(qb, "_fallback", no_fallback)
    return seen


@pytest.mark.asyncio
async def test_brief_off_asks_one_question_per_sentence(monkeypatch):
    monkeypatch.delenv("RR_GROUPED_NORMALS", raising=False)
    seen = _stub(monkeypatch, {"n0"})
    b = await qb.compile_brief(SHEET, "CT", "3 cm pancreatic head mass")
    assert sorted(k for k in seen["q"] if k.startswith("n")) == ["n0", "n1", "n2", "n3"]
    assert "Dictated negatives" not in b.text
    assert 'Do not assert as normal (a dictated finding acts on these):** "The liver, spleen and pancreas are unremarkable."' in b.text


@pytest.mark.asyncio
async def test_brief_on_without_atoms_takes_the_per_line_path(monkeypatch):
    monkeypatch.setenv("RR_GROUPED_NORMALS", "1")
    _stub(monkeypatch, set())
    sheet = SHEET.replace('- **Normal-study path:** "The liver, spleen and pancreas are unremarkable. The kidneys are '
                          'unremarkable with no hydronephrosis. The bladder and pelvic viscera are unremarkable. The '
                          'visualised osseous structures show no aggressive lesion."',
                          "- **Normal-study path:**\n  - The liver and spleen are unremarkable.\n  - The bladder is unremarkable.")
    b = await qb.compile_brief(sheet, "CT", "Appendicitis")
    assert '**Normal-study path:** "The liver and spleen are unremarkable. The bladder is unremarkable."' in b.text
