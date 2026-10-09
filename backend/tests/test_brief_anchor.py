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
    assert any(t.startswith("no contralateral hilar lymphadenopathy") for t in texts)  # tail keeps its negator
    assert "No contralateral pleural effusion or pleural thickening." in texts
    for u in ba.units(REPORT):
        assert REPORT[u.start:u.end] == u.text


def test_a_tail_unit_keeps_its_negator():
    r = "FINDINGS:\nSuperior mesenteric vein abutment without SMA involvement. The mass abuts the vein; no SMA involvement."
    texts = [u.text for u in ba.units(r)]
    assert texts == ["without SMA involvement", "no SMA involvement"]
    for u in ba.units(r):
        assert r[u.start:u.end] == u.text


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


def _jev_says(yes):
    """Fake rc._jev: P=0.95 when (sentence contains key, label text contains value) for any pair in `yes`."""
    calls = []

    async def fake(state, qs):
        calls.append((state, qs))
        out = {}
        for k, q in qs.items():
            hit = any(s in state and t in q["instructions"] for s, t in yes)
            out[k] = {"noul": 0.95 if hit else 0.05}
        return out
    fake.calls = calls
    return fake


@pytest.fixture(autouse=True)
def _pass_two_on(monkeypatch):
    """The pass 2 tests exercise the linking logic at a working threshold; the shipped LINK_MIN may switch pass 2
    off (Task 4 gate), which test_shipped_link_min_can_switch_pass_two_off covers."""
    monkeypatch.setattr(ba, "LINK_MIN", 0.80)


async def test_shipped_link_min_can_switch_pass_two_off(monkeypatch):
    monkeypatch.setattr(ba, "LINK_MIN", 1.01)
    fake = _jev_says([("paratracheal", "mediastinal lymphadenopathy")])
    anchors = _by_ref(await ba.anchor(REPORT, DEC, jev=fake))
    assert anchors["atom:P1:N2"].how == "none"                 # P <= 1 never reaches 1.01


async def test_pass_two_links_a_reworded_atom_to_its_sentence():
    fake = _jev_says([("paratracheal", "mediastinal lymphadenopathy")])
    anchors = _by_ref(await ba.anchor(REPORT, DEC, jev=fake))
    a = anchors["atom:P1:N2"]
    assert a.how == "jev" and a.unit.startswith("No paratracheal") and a.p == 0.95
    assert anchors["neg:6"].how == "none"                      # "ascites" shares no word with any unit: not asked
    asked = {q["instructions"] for _, qs in fake.calls for q in qs.values()}
    assert not any("ascites" in q for q in asked)


async def test_pass_two_needs_one_clear_winner():
    fake = _jev_says([("paratracheal", "mediastinal"), ("contralateral hilar", "mediastinal")])
    anchors = _by_ref(await ba.anchor(REPORT, DEC, jev=fake))
    assert anchors["atom:P1:N2"].how == "none"                 # two sentences at P >= LINK_MIN: ambiguous


async def test_a_jev_failure_leaves_pass_two_labels_unanchored():
    async def boom(state, qs):
        raise RuntimeError("jev down")
    anchors = _by_ref(await ba.anchor(REPORT, DEC, jev=boom))
    assert anchors["atom:P1:N2"].how == "none" and anchors["neg:1"].how == "term"


def test_relocate_follows_an_earlier_removal_and_marks_a_removed_clause():
    got, _ = ba.match_terms(REPORT, ba.brief_labels(DEC), ba.units(REPORT))
    anchors = list(got.values())
    edited = REPORT.replace("The great vessels are patent with no pulmonary emboli.", "")
    moved = _by_ref(ba.relocate(anchors, edited))
    a = moved["neg:5"]
    assert edited[a.span[0]:a.span[1]] == a.span_text == "hepatic lesion"
    assert moved["dict:0"].how == "removed" and moved["dict:0"].span is None


# ---- review fixes: anchors never land on positive findings ----

def _lab(term, text=None, action="contradicted"):
    return ba.Label("x:1", text or f"No {term}", term, action, "sheet")


def test_relocate_never_lands_on_a_positive_sentence():
    rep = "FINDINGS:\nSmall pleural effusion on the right is noted. Lung mass; no pleural effusion on the right.\n"
    got, _ = ba.match_terms(rep, [_lab("pleural effusion on the right")], ba.units(rep))
    a = got["x:1"]
    assert a.how == "term" and rep[a.span[0]:a.span[1]] == "pleural effusion on the right"
    assert a.span[0] > rep.index("Lung mass")
    edited = rep.replace("; no pleural effusion on the right", "")
    assert ba.relocate([a], edited)[0].how == "removed"


def test_relocate_picks_the_nearest_of_identical_units():
    rep = "FINDINGS:\nThe liver is unremarkable.\n\nThe spleen is enlarged. The liver is unremarkable.\n"
    us = [u for u in ba.units(rep) if u.text == "The liver is unremarkable."]
    assert len(us) == 2
    a = ba.Anchor("x:1", "keep", "sheet", how="term", span=[us[1].start, us[1].start + 9], span_text="The liver",
                  unit=us[1].text, offset=0)
    assert ba.relocate([a], rep)[0].span[0] == us[1].start


def test_tail_is_located_after_the_head():
    rep = "FINDINGS:\nMild hydronephrosis; no hydronephrosis.\n"
    us = ba.units(rep)
    assert [u.text for u in us] == ["no hydronephrosis"]          # the tail keeps its negator
    assert us[0].start > rep.index(";")


def test_positive_semicolon_part_is_never_a_unit():
    rep = "FINDINGS:\nThe kidney is not seen; left hydronephrosis.\n"
    assert [u.text for u in ba.units(rep)] == ["The kidney is not seen"]
    got, left = ba.match_terms(rep, [_lab("hydronephrosis")], ba.units(rep))
    assert "x:1" in {l.ref for l in left} and "x:1" not in got


def test_hedged_non_negatives_are_not_units():
    for t in ("Malignancy is not excluded.", "Infection cannot be excluded.", "Fracture is not ruled out.",
              "No interval change in the mass."):
        assert ba.units(f"FINDINGS:\n{t}\n") == [], t


async def test_a_failed_candidate_unit_leaves_the_label_unanchored():
    rep = "FINDINGS:\nNo paratracheal lymphadenopathy. No subcarinal lymphadenopathy.\n"
    lab = ba.Label("x:1", "No mediastinal lymphadenopathy", "mediastinal lymphadenopathy", "implicated", "atom")

    async def flaky(state, qs):
        if "subcarinal" in state:
            raise RuntimeError("down")
        return {k: {"noul": 0.95} for k in qs}
    assert await ba.link([lab], ba.units(rep), flaky) == {}


def test_idless_atoms_never_share_an_anchor():
    d = {"normals": [{"linked": True, "atoms": [{"term": "Liver"}, {"term": "Spleen"}]},
                     {"linked": True, "pid": "P1", "atoms": [{"term": "Kidney", "id": "N1"}]}]}
    refs = [l.ref for l in ba.brief_labels(d)]
    assert refs == ["atom:P1:N1"] and len(set(refs)) == len(refs)


def test_impression_found_after_findings_when_sentences_repeat():
    rep = "FINDINGS:\nNo pleural effusion.\n\nIMPRESSION:\nNo pleural effusion.\n"
    us = ba.units(rep)
    assert len(us) == 2 and us[1].start > rep.index("IMPRESSION")


def test_enabled_switch(monkeypatch):
    monkeypatch.delenv("RR_BRIEF_ANCHOR", raising=False)
    assert ba.enabled() is True
    monkeypatch.setenv("RR_BRIEF_ANCHOR", "0")
    assert ba.enabled() is False
