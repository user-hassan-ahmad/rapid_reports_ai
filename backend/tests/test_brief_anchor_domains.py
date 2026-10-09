"""brief_anchor across domains (the stored replay cases are nearly all pancreas): sides, levels, "additional",
a contradicted generic label beside a kept specific one. Synthetic, deterministic, no model (Jev is faked).

Code proposes, Jev confirms. Expectations per label ref: "term" is proposed on the label's own words inside a negative
unit, and anchors there ("term+jev") once Jev confirms; "shadowed" means its only hit is held by a longer / kept label,
so it is never proposed, never asked and never anchored; "left" means no term proposal at all (Jev decides among the
units sharing its words, never on another label's words)."""
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
def test_proposals_across_domains(name, report, negs, expect):
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
            assert a.how == "proposed" and report[a.span[0]:a.span[1]] == a.span_text, (name, ref, a)
            # on the right words: the span is the label's own key term, inside a negative unit
            assert a.span_text.lower() == by_ref[ref].term.lower(), (name, ref, a.span_text, by_ref[ref].term)
            assert a.unit.lower().startswith(("no ", "nil ", "without ")), (name, ref, a.unit)


@pytest.mark.parametrize("name,report,negs,expect", CASES, ids=[c[0] for c in CASES])
async def test_confirmed_anchors_across_domains(name, report, negs, expect):
    """Even when Jev confirms every question it is asked, a shadowed label is never asked and never anchors, and a
    term anchor sits only on the label's own proposed words."""
    fake = _jev_says(None)
    anchors = {a.ref: a for a in await ba.anchor(report, {"negatives": negs}, jev=fake)}
    labels = {l.ref: l for l in ba.brief_labels({"negatives": negs})}
    asked = {q["instructions"] for _, qs in fake.calls for q in qs.values()}
    for ref, want in expect.items():
        a = anchors[ref]
        if want == "shadowed":
            assert a.how == "none" and a.shadowed_by and ba.anchored(anchors[a.shadowed_by]), (name, ref, a)
            assert not any(f'"{labels[ref].text}"' in q for q in asked), (name, ref)
        elif want == "term":
            assert a.how == "term+jev" and a.span_text.lower() == labels[ref].term.lower(), (name, ref, a)
        else:
            assert a.how != "term+jev", (name, ref, a)          # never a term anchor on another label's words


def test_positive_sentences_are_never_units():
    report = ("FINDINGS:\nComplete tear of the anterior cruciate ligament. Moderate joint effusion. Pathological "
              "collapse of T7 with retropulsion and cord compression.\n\nIMPRESSION:\nComplete ACL tear.\n")
    assert ba.units(report) == []


def test_level_is_never_proposed_on_another_level():
    report = "FINDINGS:\nNo retropulsion at T8.\n\nIMPRESSION:\nNormal.\n"
    got, left = ba.match_terms(report, ba.brief_labels({"negatives": [neg("No retropulsion at T7", "keep")]}),
                               ba.units(report))
    assert "neg:0" not in got and [l.ref for l in left] == ["neg:0"]


async def test_level_never_anchors_on_another_level_when_jev_says_no():
    report = "FINDINGS:\nNo retropulsion at T8.\n\nIMPRESSION:\nNormal.\n"
    [a] = await ba.anchor(report, {"negatives": [neg("No retropulsion at T7", "keep")]},
                          jev=_jev_says([("T7", "T7")]))
    assert a.how == "none"


# A key term made by dropping a place phrase ("No calculus identified in the common bile duct" -> "calculus") may
# hit the same words in another organ's sentence: the hit is only a proposal until Jev confirms it in context.

def _jev_says(yes):
    """Fake rc._jev: P=0.95 when (the LAST sentence of the state contains key, label text contains value) for any
    pair in `yes`, else an explicit no; `yes=None` confirms every question."""
    calls = []

    async def fake(state, qs):
        calls.append((state, qs))
        last = state.split("\n")[-1]
        return {k: {"noul": 0.95 if yes is None or any(s in last and t in q["instructions"] for s, t in yes)
                    else 0.05} for k, q in qs.items()}
    fake.calls = calls
    return fake


CBD = "No calculus identified in the common bile duct"


async def test_place_stripped_hit_on_another_organ_is_not_anchored():
    report = ("FINDINGS:\nThe common bile duct is dilated to 12 mm. Both kidneys are normal with no calculus."
              "\n\nIMPRESSION:\nBiliary dilatation.\n")
    fake = _jev_says([])
    [a] = await ba.anchor(report, {"negatives": [neg(CBD, "keep")]}, jev=fake)
    assert a.how == "none" and not a.span
    assert [s for s, _ in fake.calls] == [                     # asked of that sentence only, with its context
        "The common bile duct is dilated to 12 mm.\nBoth kidneys are normal with no calculus."]


async def test_place_stripped_hit_confirmed_by_jev_anchors_as_term_jev():
    report = ("FINDINGS:\nThe common bile duct is dilated to 12 mm, with no calculus in the duct. The liver is "
              "unremarkable.\n\nIMPRESSION:\nBiliary dilatation.\n")
    [a] = await ba.anchor(report, {"negatives": [neg(CBD, "keep")]},
                          jev=_jev_says([("no calculus", "common bile duct")]))
    assert a.how == "term+jev" and ba.anchored(a) and report[a.span[0]:a.span[1]] == "calculus" and a.p == 0.95


async def test_place_stripped_omit_label_never_anchors_on_another_organ():
    report = "FINDINGS:\nA pancreatic head mass. The bowel is normal with no mass.\n\nIMPRESSION:\nMass.\n"
    [a] = await ba.anchor(report, {"negatives": [neg("No mass identified in the head of the pancreas",
                                                     "contradicted")]}, jev=_jev_says([]))
    assert a.how == "none"


async def test_a_jev_failure_leaves_a_place_stripped_hit_unanchored():
    async def boom(state, qs):
        raise RuntimeError("jev down")
    report = "FINDINGS:\nThe duct is dilated, with no calculus in the common bile duct.\n\nIMPRESSION:\nX.\n"
    [a] = await ba.anchor(report, {"negatives": [neg(CBD, "keep")]}, jev=boom)
    assert a.how == "none"
