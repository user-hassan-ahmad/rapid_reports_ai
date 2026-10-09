"""brief_anchor (spec 2026-10-09-negatives-one-owner-design §3.1): brief labels tied to the clauses the generator
wrote. Synthetic cases only, no live model calls."""
import pytest

from rapid_reports_ai import brief_anchor as ba


@pytest.mark.parametrize("text,term", [
    ("No mediastinal invasion identified", "mediastinal invasion"),
    ("No osseous lesion identified in the visualised thoracic skeleton", "osseous lesion"),
    ("No definite chest wall invasion by the right upper lobe mass", "chest wall invasion"),
    ("No contralateral pleural nodularity on CT thorax", "contralateral pleural nodularity"),
    ("There is no free fluid.", "free fluid"),
    ("The mass abuts the oblique fissure with no definite chest wall involvement", "chest wall involvement"),
    ("No pulmonary emboli", "pulmonary emboli"),
    ("No retropulsion at T7", "retropulsion at T7"),               # a level is part of the claim
    ("No fracture in the left distal radius", "fracture in the left distal radius"),   # so is a side
])
def test_key_term_strips_boilerplate(text, term):
    assert ba.key_term(text) == term


DECISIONS = {
    "negatives": [
        {"text": "No pleural effusion identified", "action": "contradicted", "source": "sheet",
         "dictated_finding": "Small right pleural effusion"},
        {"text": "No contralateral pleural effusion identified", "action": "keep",
         "source": "finding:Pleural effusion", "dictated_finding": ""},
    ],
    "normals": [
        {"linked": True, "pid": "P1", "rendered": "No mediastinal lymphadenopathy.", "atoms": [
            {"id": "N1", "term": "Mediastinal lymphadenopathy", "text": "No mediastinal lymphadenopathy.",
             "label": "implicated", "action": "implicated", "pointer": "right hilar nodes 14 mm"}]},
        {"text": "The bones are unremarkable.", "action": "keep"},          # not linked: no label
    ],
    "dictated_negatives": ["No pulmonary emboli"],
}


def test_brief_labels_flattens_every_source_with_stable_refs():
    labs = ba.brief_labels(DECISIONS)
    assert [(l.ref, l.term, l.action, l.source) for l in labs] == [
        ("neg:0", "pleural effusion", "contradicted", "sheet"),
        ("neg:1", "contralateral pleural effusion", "keep", "finding:Pleural effusion"),
        ("atom:P1:N1", "Mediastinal lymphadenopathy", "implicated", "atom"),
        ("dict:0", "pulmonary emboli", "dictated", "dictated"),
    ]
    assert labs[0].pointer == "Small right pleural effusion"
    assert labs[1].pointer == "Pleural effusion"          # a finding-linked negative points at its finding
    assert labs[2].pointer == "right hilar nodes 14 mm"


def test_brief_labels_empty_without_decisions():
    assert ba.brief_labels(None) == [] and ba.brief_labels({}) == []
