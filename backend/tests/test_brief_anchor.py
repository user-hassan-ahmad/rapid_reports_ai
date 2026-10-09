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


# A synthetic thorax report mirroring the worked case's shapes (spec §1).
REPORT = (
    "FINDINGS:\n"
    "A 3 cm spiculated mass in the right upper lobe abuts the fissure with no definite chest wall involvement and no "
    "mediastinal invasion. A small right pleural effusion accompanies the mass. The right hilar nodes measure up to "
    "1.4 cm; no contralateral hilar lymphadenopathy or vascular encasement.\n\n"
    "No paratracheal, subcarinal or para-aortic lymphadenopathy. The great vessels are patent with no pulmonary "
    "emboli.\n\n"
    "No contralateral pleural effusion or pleural thickening. The liver is unremarkable with no hepatic lesion.\n\n"
    "IMPRESSION:\n"
    "Right upper lobe malignancy with ipsilateral hilar nodes and a small effusion.\n")

DEC = {
    "negatives": [
        {"text": "No pleural effusion identified", "action": "contradicted", "source": "sheet",
         "dictated_finding": "Small right pleural effusion"},
        {"text": "No contralateral pleural effusion identified", "action": "keep",
         "source": "finding:Pleural effusion"},
        {"text": "No pleural thickening identified", "action": "keep", "source": "finding:Pleural effusion"},
        {"text": "No mediastinal invasion identified", "action": "keep", "source": "finding:Lung mass"},
        {"text": "No contralateral hilar lymphadenopathy identified", "action": "keep",
         "source": "finding:Hilar lymphadenopathy"},
        {"text": "No hepatic lesion identified", "action": "keep", "source": "sheet"},
        {"text": "No ascites identified", "action": "keep", "source": "sheet"},          # never written
    ],
    "normals": [
        {"linked": True, "pid": "P1", "atoms": [
            {"id": "N1", "term": "Hilar lymphadenopathy", "text": "No hilar lymphadenopathy.",
             "action": "do_not_assert"},
            {"id": "N2", "term": "Mediastinal lymphadenopathy", "text": "No mediastinal lymphadenopathy.",
             "action": "implicated", "pointer": "right hilar nodes 1.4 cm"}]},
        {"linked": True, "pid": "P2", "atoms": [
            {"id": "N3", "term": "Liver", "text": "The liver is unremarkable.", "action": "keep"}]},
    ],
    "dictated_negatives": ["No pulmonary emboli"],
}


def _by_ref(anchors):
    return {a.ref: a for a in anchors}


def test_units_are_normal_sentences_and_negative_tails_never_positive_heads():
    texts = [u.text for u in ba.units(REPORT)]
    assert "A small right pleural effusion accompanies the mass." not in texts
    assert any(t.startswith("contralateral hilar lymphadenopathy") for t in texts)     # tail of a finding sentence
    assert "No contralateral pleural effusion or pleural thickening." in texts
    for u in ba.units(REPORT):
        assert REPORT[u.start:u.end] == u.text


def test_pass_one_longest_term_wins_and_the_shorter_omit_is_shadowed():
    got, left = ba.match_terms(REPORT, ba.brief_labels(DEC), ba.units(REPORT))
    keep = got["neg:1"]
    assert keep.how == "term" and keep.span_text.lower() == "contralateral pleural effusion"
    omit = got["neg:0"]                       # its only hit sits inside "contralateral pleural effusion"
    assert omit.how == "none" and omit.shadowed_by == "neg:1"
    assert got["neg:2"].how == "term" and got["neg:5"].how == "term" and got["atom:P2:N3"].how == "term"
    assert got["neg:4"].span_text.lower() == "contralateral hilar lymphadenopathy"
    assert got["atom:P1:N1"].shadowed_by == "neg:4"     # "hilar lymphadenopathy" lives inside the kept negative
    assert got["dict:0"].how == "term"
    assert {l.ref for l in left} == {"neg:6", "atom:P1:N2"}    # never written / reworded: pass 2's job


def test_two_labels_with_disjoint_terms_share_one_sentence():
    got, _ = ba.match_terms(REPORT, ba.brief_labels(DEC), ba.units(REPORT))
    assert got["neg:5"].unit == got["atom:P2:N3"].unit == "The liver is unremarkable with no hepatic lesion."
