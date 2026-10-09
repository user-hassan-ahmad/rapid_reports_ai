"""brief_anchor pass 1 across domains (the stored replay cases are nearly all pancreas): sides, levels, "additional",
a contradicted generic label beside a kept specific one. Synthetic, deterministic, no model.

Expectations per label ref: "term" anchors on the label's own words inside a negative unit; "shadowed" means its only
hit is held by a longer / kept label (never anchored there itself); "left" means pass 1 did not anchor it (pass 2 or
unanchored), never a term anchor on another label's words."""
import pytest

from rapid_reports_ai import brief_anchor as ba


def neg(text, action, source="sheet"):
    return {"text": text, "action": action, "source": source}


CASES = [
    ("neuro",
     "FINDINGS:\nA large right cerebellar haemorrhage effaces the fourth ventricle. The lateral ventricles are mildly "
     "prominent. No supratentorial haemorrhage. No skull fracture.\n\nIMPRESSION:\nCerebellar haemorrhage.\n",
     [neg("No supratentorial haemorrhage identified", "keep"), neg("No haemorrhage identified", "contradicted"),
      neg("No hydrocephalus identified", "implicated"), neg("No skull fracture identified", "keep")],
     {"neg:0": "term", "neg:1": "shadowed", "neg:2": "left", "neg:3": "term"}),
    ("renal sides",
     "FINDINGS:\nModerate left hydronephrosis to an obstructing 6 mm left ureteric calculus. No right hydronephrosis. "
     "The bladder is unremarkable.\n\nIMPRESSION:\nObstructing left ureteric calculus.\n",
     [neg("No right hydronephrosis identified", "keep", "finding:Hydronephrosis"),
      neg("No hydronephrosis identified", "contradicted")],
     {"neg:0": "term", "neg:1": "shadowed"}),
    ("chest additional",
     "FINDINGS:\nA 9 mm solid nodule in the right lower lobe. No additional pulmonary nodule. The airways are clear."
     "\n\nIMPRESSION:\nIndeterminate right lower lobe nodule.\n",
     [neg("No additional pulmonary nodule identified", "keep", "finding:Pulmonary nodule"),
      neg("No pulmonary nodule identified", "contradicted")],
     {"neg:0": "term", "neg:1": "shadowed"}),
    ("spine levels",
     "FINDINGS:\nPathological collapse of T7 with retropulsion and cord compression. No retropulsion at T8. "
     "\n\nIMPRESSION:\nT7 pathological collapse with cord compression.\n",
     [neg("No retropulsion at T7", "contradicted"), neg("No retropulsion at T8", "keep")],
     {"neg:0": "left", "neg:1": "term"}),          # T7 must never anchor on the T8 sentence
    ("msk",
     "FINDINGS:\nComplete tear of the anterior cruciate ligament. Moderate joint effusion. The posterior cruciate "
     "ligament is intact.\n\nIMPRESSION:\nComplete ACL tear.\n",
     [neg("No joint effusion identified", "contradicted"), neg("No PCL tear identified", "keep")],
     {"neg:0": "left", "neg:1": "left"}),          # a positive sentence is never a unit; PCL is pass 2's job
]


@pytest.mark.parametrize("name,report,negs,expect", CASES, ids=[c[0] for c in CASES])
def test_pass_one_across_domains(name, report, negs, expect):
    labels = ba.brief_labels({"negatives": negs})
    by_ref = {l.ref: l for l in labels}
    got, left = ba.match_terms(report, labels, ba.units(report))
    left_refs = {l.ref for l in left}
    for ref, want in expect.items():
        if want == "left":
            assert ref in left_refs and ref not in got, (name, ref, got.get(ref))
        elif want == "shadowed":
            assert got[ref].how == "none" and got[ref].shadowed_by, (name, ref, got.get(ref))
        else:
            a = got[ref]
            assert a.how == "term" and report[a.span[0]:a.span[1]] == a.span_text, (name, ref, a)
            # on the right words: the span is the label's own key term, inside a negative unit
            assert a.span_text.lower() == by_ref[ref].term.lower(), (name, ref, a.span_text, by_ref[ref].term)
            assert a.unit.lower().startswith(("no ", "nil ", "without ")), (name, ref, a.unit)


def test_positive_sentences_are_never_units():
    report = ("FINDINGS:\nComplete tear of the anterior cruciate ligament. Moderate joint effusion. Pathological "
              "collapse of T7 with retropulsion and cord compression.\n\nIMPRESSION:\nComplete ACL tear.\n")
    assert ba.units(report) == []


def test_level_never_anchors_on_another_level():
    report = "FINDINGS:\nNo retropulsion at T8.\n\nIMPRESSION:\nNormal.\n"
    got, left = ba.match_terms(report, ba.brief_labels({"negatives": [neg("No retropulsion at T7", "keep")]}),
                               ba.units(report))
    assert "neg:0" not in got and [l.ref for l in left] == ["neg:0"]
