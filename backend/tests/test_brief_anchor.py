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


async def test_a_tail_is_cut_at_a_turn_to_a_finding():
    r = ("FINDINGS:\nRight upper lobe mass without definite chest wall invasion, with ipsilateral hilar "
         "lymphadenopathy and a small ipsilateral pleural effusion.\n")
    us = ba.units(r)
    assert [u.text for u in us] == ["without definite chest wall invasion"]
    assert not any("pleural effusion" in u.text for u in us)
    lab = _lab("pleural effusion")                              # an OMIT "No pleural effusion"
    got, left = ba.match_terms(r, [lab], us)
    assert "x:1" not in got

    async def yes(state, qs):
        return {k: {"noul": 0.99} for k in qs}
    assert await ba.link(left, us, jev=yes) == {}


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


R2 = ("FINDINGS:\nA small right pleural effusion. No contralateral pleural effusion. No pleural effusion. "
      "There is no ascites.\n\nIMPRESSION:\nSmall right effusion.\n")


def _a(ref, action, text, how="term", source="sheet", pointer=""):
    i = R2.index(text)
    return ba.Anchor(ref, action, source, pointer, how, [i, i + len(text)], text, text)


def test_a_contradiction_on_a_kept_clause_is_protected_and_carded():
    anchors = [_a("neg:1", "keep", "contralateral pleural effusion", source="finding:Pleural effusion")]
    rules = ba.brief_rules(R2, anchors, {"No contralateral pleural effusion.": 0.7},
                           flagged=["No contralateral pleural effusion."], review_contra=[])
    assert rules["protect"] == ["No contralateral pleural effusion."] and rules["remove"] == []
    (c,) = rules["conflicts"]
    assert c["reason"] == "brief_kept" and c["refs"] == ["neg:1"] and c["source"] == "finding:Pleural effusion"


def test_an_omit_clause_is_removed_only_with_two_signals():
    i = R2.index("No pleural effusion.") + 3
    omit = ba.Anchor("neg:0", "contradicted", "sheet", "Small right pleural effusion", "term",
                     [i, i + len("pleural effusion")], "pleural effusion", "No pleural effusion.")
    sure = ba.brief_rules(R2, [omit], {"No pleural effusion.": 0.9}, flagged=[], review_contra=[])
    assert sure["remove"] == ["No pleural effusion."] and sure["conflicts"] == []
    weak = ba.brief_rules(R2, [omit], {"No pleural effusion.": 0.3}, flagged=[], review_contra=[])
    assert weak["remove"] == [] and weak["conflicts"][0]["reason"] == "brief_omitted"


def test_dictated_beats_omit_no_removal_no_card_logged_as_brief_error():
    anchors = [_a("dict:0", "dictated", "ascites"),
               ba.Anchor("neg:3", "contradicted", "sheet", "", "none", shadowed_by="dict:0")]
    rules = ba.brief_rules(R2, anchors, {"There is no ascites.": 0.9}, flagged=[], review_contra=[])
    assert rules == {"protect": [], "remove": [], "conflicts": []}
    log = ba.anchor_log(anchors, rules)
    assert log["brief_errors"] == [{"ref": "neg:3", "shadowed_by": "dict:0"}]


def test_anchor_log_counts_and_lists_unanchored():
    anchors = [_a("neg:1", "keep", "contralateral pleural effusion"),
               ba.Anchor("neg:6", "keep", "sheet"),
               ba.Anchor("atom:P1:N2", "implicated", "atom", how="jev", span=[0, 1], span_text="F", unit="F")]
    log = ba.anchor_log(anchors, {"protect": [], "remove": [], "conflicts": []})
    assert (log["labels"], log["by_term"], log["by_jev"]) == (3, 1, 1)
    assert log["unanchored"] == [{"ref": "neg:6", "source": "sheet", "action": "keep"}]


# ---- review follow-ups ----
def test_shadowed_keep_label_in_the_clause_blocks_removal():
    i = R2.index("No pleural effusion.") + 3
    omit = ba.Anchor("neg:0", "contradicted", "sheet", "", "term", [i, i + len("pleural effusion")],
                     "pleural effusion", "No pleural effusion.")
    shadowed = ba.Anchor("neg:9", "keep", "finding:Pleural effusion", how="none", shadowed_by="neg:0")
    rules = ba.brief_rules(R2, [omit, shadowed], {"No pleural effusion.": 0.9}, flagged=[], review_contra=[])
    assert rules["remove"] == [] and len(rules["conflicts"]) == 1
    # and a flagged clause held that way is protected and carded as kept
    r2 = ba.brief_rules(R2, [omit, shadowed], {"No pleural effusion.": 0.9},
                        flagged=["No pleural effusion."], review_contra=[])
    assert r2["protect"] == ["No pleural effusion."] and r2["remove"] == []
    assert r2["conflicts"][0]["reason"] == "brief_kept" and r2["conflicts"][0]["refs"] == ["neg:9"]


def test_whole_sentence_with_a_positive_turn_is_split():
    rep = "FINDINGS:\nNodule in the left lobe with no lymphadenopathy, but a 6 mm nodule in the right lobe.\n"
    us = ba.units(rep)
    assert us and all("6 mm nodule" not in u.text for u in us)
    assert all(rep[u.start:u.end] == u.text for u in us)
    lab = ba.Label("neg:0", "No nodule in the right lobe", "nodule in the right lobe", "contradicted", "sheet")
    got, left = ba.match_terms(rep, [lab], us)
    assert "neg:0" not in got or got["neg:0"].how != "term"


def test_semicolon_part_turns_are_split_too():
    rep = "FINDINGS:\nNo ascites, but a 6 mm nodule in the right lobe; no effusion.\n"
    us = ba.units(rep)
    assert all("6 mm nodule" not in u.text for u in us)
    assert all(rep[u.start:u.end] == u.text for u in us)
    assert any(u.text == "no effusion." for u in us)


def test_nil_is_a_tail_negator():
    rep = "FINDINGS:\nThe nodes measure 14 mm; nil contralateral lymphadenopathy.\n"
    us = ba.units(rep)
    assert [u.text for u in us] == ["nil contralateral lymphadenopathy."]


@pytest.mark.parametrize("s", ["Pneumothorax is not entirely excluded.", "Metastasis cannot be ruled out."])
def test_more_hedges_are_not_normal(s):
    assert ba.units("FINDINGS:\n" + s + "\n") == []


def test_relocate_removes_when_the_duplicate_count_changed():
    rep = "FINDINGS:\nNo ascites. No effusion. No ascites.\n"
    us = ba.units(rep)
    i = us[0].start
    a = ba.Anchor("neg:0", "keep", "sheet", "", "term", [i + 3, i + 10], "ascites", us[0].text, 3, dupes=2)
    after = "FINDINGS:\nNo effusion. No ascites.\n"
    (r,) = ba.relocate([a], after)
    assert r.how == "removed"
    (same,) = ba.relocate([a], rep)
    assert same.how == "term"


def test_match_terms_records_the_duplicate_count():
    rep = "FINDINGS:\nNo ascites. No effusion. No ascites.\n"
    lab = ba.Label("neg:0", "No effusion", "effusion", "keep", "sheet")
    got, _ = ba.match_terms(rep, [lab], ba.units(rep))
    assert got["neg:0"].dupes == 1


# ---- removal guards ----
R3 = "FINDINGS:\nNo effusion seen around a 3 cm mass. No effusion.\n\nIMPRESSION:\nNo effusion.\n"


def _span(text, nth=0):
    i = -1
    for _ in range(nth + 1):
        i = R3.index(text, i + 1)
    return [i, i + len(text)]


def test_clause_resolves_at_whole_sentence_occurrences_only():
    spans = ba._clause_spans(R3, "No effusion.")
    assert [R3[a:b] for a, b in spans] == ["No effusion", "No effusion"]
    assert spans[0][0] > R3.index("3 cm mass")


def test_keep_at_the_real_clause_blocks_an_omit_at_the_wrong_match():
    first = _span("No effusion seen")
    omit = ba.Anchor("neg:0", "contradicted", "sheet", "", "term", first, "No effusion", "No effusion seen around a 3 cm mass.")
    k = _span("No effusion.")
    keep = ba.Anchor("neg:1", "keep", "sheet", "", "term", [k[0], k[1] - 1], "No effusion", "No effusion.")
    r = ba.brief_rules(R3, [omit, keep], {"No effusion.": 0.9}, flagged=[], review_contra=[])
    assert r["remove"] == []


def test_keep_in_the_impression_copy_blocks_removal_of_the_findings_copy():
    f, imp = _span("No effusion.", 0), _span("No effusion.", 1)
    omit = ba.Anchor("neg:0", "contradicted", "sheet", "", "term", [f[0], f[1] - 1], "No effusion", "No effusion.")
    keep = ba.Anchor("neg:1", "keep", "sheet", "", "term", [imp[0], imp[1] - 1], "No effusion", "No effusion.")
    r = ba.brief_rules(R3, [omit, keep], {"No effusion.": 0.9}, flagged=[], review_contra=[])
    assert r["remove"] == []


def test_a_foreign_keep_in_a_longer_sentence_is_not_a_holder():
    f = _span("No effusion.", 0)
    omit = ba.Anchor("neg:0", "contradicted", "sheet", "", "term", [f[0], f[1] - 1], "No effusion", "No effusion.")
    keep = ba.Anchor("neg:1", "keep", "sheet", "", "term", _span("No effusion seen"), "No effusion",
                     "No effusion seen around a 3 cm mass.")
    r = ba.brief_rules(R3, [omit, keep], {"No effusion.": 0.9}, flagged=[], review_contra=[])
    assert r["remove"] == ["No effusion."]


def test_a_clause_with_a_positive_turn_is_never_removed():
    rep = "FINDINGS:\nNo pleural effusion, but a 6 mm nodule in the right lobe.\n"
    us = ba.units(rep)
    lab = ba.Label("neg:0", "No pleural effusion", "pleural effusion", "contradicted", "sheet")
    got, _ = ba.match_terms(rep, [lab], us)
    clause = "No pleural effusion, but a 6 mm nodule in the right lobe."
    r = ba.brief_rules(rep, [got["neg:0"]], {clause: 0.95}, flagged=[], review_contra=[])
    assert r["remove"] == [] and r["conflicts"][0]["reason"] == "brief_omitted"


def test_an_omit_unit_that_does_not_cover_the_clause_blocks_removal():
    rep = "FINDINGS:\nNo effusion or mass.\n"
    i = rep.index("No effusion")
    omit = ba.Anchor("neg:0", "contradicted", "sheet", "", "term", [i, i + 11], "No effusion", "No effusion")
    r = ba.brief_rules(rep, [omit], {"No effusion or mass.": 0.9}, flagged=[], review_contra=[])
    assert r["remove"] == [] and r["conflicts"][0]["reason"] == "brief_omitted"


def test_keep_shadowed_by_dictated_protects_but_makes_no_card():
    i = R2.index("There is no ascites.")
    d = ba.Anchor("dict:0", "dictated", "dictated", "", "term", [i, i + 19], "ascites", "There is no ascites.")
    sh = ba.Anchor("neg:2", "keep", "sheet", "", "none", shadowed_by="dict:0")
    r = ba.brief_rules(R2, [d, sh], {"There is no ascites.": 0.9},
                       flagged=["There is no ascites."], review_contra=[])
    assert r == {"protect": ["There is no ascites."], "remove": [], "conflicts": []}


def test_omit_with_a_keep_holder_is_a_split_card_with_both_refs():
    i = R2.index("No pleural effusion.")
    omit = ba.Anchor("neg:0", "contradicted", "sheet", "", "term", [i, i + 19], "No pleural effusion", "No pleural effusion.")
    keep = ba.Anchor("neg:9", "keep", "sheet", "", "none", shadowed_by="neg:0")
    r = ba.brief_rules(R2, [omit, keep], {"No pleural effusion.": 0.9}, flagged=[], review_contra=[])
    (c,) = r["conflicts"]
    assert r["remove"] == [] and c["reason"] == "brief_split" and set(c["refs"]) == {"neg:0", "neg:9"}


def test_brief_kept_score_is_none_when_the_clause_has_no_score():
    k = R2.index("No contralateral pleural effusion.")
    keep = ba.Anchor("neg:1", "keep", "sheet", "", "term", [k, k + 33], "x", "No contralateral pleural effusion.")
    r = ba.brief_rules(R2, [keep], {}, flagged=["No contralateral pleural effusion."], review_contra=[])
    assert r["conflicts"][0]["score"] is None


def test_whole_sentence_unit_starts_at_the_negator_when_the_head_is_positive():
    rep = "FINDINGS:\nNodule in the left lobe with no lymphadenopathy.\n"
    us = ba.units(rep)
    assert [u.text for u in us] == ["no lymphadenopathy"]
    assert rep[us[0].start:us[0].end] == us[0].text


@pytest.mark.parametrize("c", ["No pleural effusion.", "No pleural effusion or pneumothorax.",
                               "No ascites, free air or collection.", "No pleural effusion identified.",
                               "No focal lesion in the liver.", "There is no ascites.",
                               "No effusion and no atelectasis."])
def test_simple_negative_clauses_are_removable(c):
    assert ba._removable_negative(c)


@pytest.mark.parametrize("c", ["No effusion with mild atelectasis.", "No effusion and mild atelectasis.",
                               "No effusion, but a 6 mm nodule.", "No effusion; small nodule.",
                               "No change in the 6 mm nodule.", "No effusion although trace fluid persists.",
                               "No effusion except a small nodule.", "No effusion, apart from atelectasis.",
                               "Mild atelectasis."])
def test_other_clauses_are_never_removable(c):
    assert not ba._removable_negative(c)


def test_brief_rules_cards_a_negative_with_a_joined_finding():
    rep = "FINDINGS:\nNo effusion with mild atelectasis.\n"
    i = rep.index("No effusion")
    omit = ba.Anchor("neg:0", "contradicted", "sheet", "", "term", [i, i + 11], "No effusion",
                     "No effusion with mild atelectasis.")
    r = ba.brief_rules(rep, [omit], {"No effusion with mild atelectasis.": 0.95}, flagged=[], review_contra=[])
    assert r["remove"] == [] and r["conflicts"][0]["reason"] == "brief_omitted"
