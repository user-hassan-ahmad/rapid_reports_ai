import json
import os
from pathlib import Path

import pytest

from rapid_reports_ai.scripts.review_labs import additions_map as AM
from rapid_reports_ai.scripts.review_labs import gate_c as GC

CARD = {"finding_number": 1, "finding": "12 mm left renal lesion", "finding_short_label": "Left renal lesion",
        "classifications": [{"system": "Bosniak 2019", "grade": "II", "criteria": "Thin septa ...", "management": "x"}],
        "thresholds": [{"parameter": "size", "threshold": "4 cm", "significance": "s", "context": "c"}],
        "follow_up_actions": [{"modality": "US", "timing": "6 months", "indication": "i", "urgency": "routine",
                               "guideline_source": "g"}, {"modality": "MRI", "timing": "", "indication": "j"}],
        "differentials": [{"diagnosis": "d1"}], "imaging_flags": ["f1"], "sources": [{"url": "u", "title": "t"}]}


def test_map_card_kinds_and_citation():
    cands = AM.map_card(CARD)
    kinds = [c["kind"] for c in cands]
    assert kinds == ["grade", "threshold", "follow_up", "option", "option", "option"]
    g = cands[0]
    assert g["lane"] == "additions" and g["detector"] == "s4.classification"
    assert g["evidence"]["system"] == "Bosniak 2019" and "criteria" not in g["evidence"]
    assert g["citation"] == {"card": 1, "source": "u", "label": "t"}


def test_map_card_with_criteria_arm():
    g = AM.map_card(CARD, with_criteria=True)[0]
    assert g["evidence"]["criteria"] == "Thin septa ..."


def test_system_key_normalises():
    assert AM.system_key("Bosniak classification v2019") == AM.system_key("Bosniak 2019") == "bosniak"
    assert AM.system_key("LI-RADS v2018") == "lirads"
    assert AM.system_key("C-RADS v2") == AM.system_key("C-RADS")
    assert AM.system_key("2019 Bosniak") == AM.system_key("Bosniak 2019") == AM.system_key("The Bosniak classification") == "bosniak"
    assert AM.system_key("O-RADS US") != AM.system_key("O-RADS MRI")
    assert AM.system_key("O-RADS US") == "orads_us" and AM.system_key("LI-RADS US") == "lirads_us"
    assert AM.system_key("AAST 2018 splenic") == "aast_spleen"


def test_cand_keeps_zero_grade_and_citation_guards_sources():
    card = {"finding": "f", "sources": ["not a dict"], "classifications": [{"system": "Garden", "grade": 0}]}
    c = AM.map_card(card)[0]
    assert c["evidence"]["grade"] == 0
    assert c["citation"]["source"] is None


def test_system_key_covers_s1_phase3_systems():
    path = Path(__file__).resolve().parent.parent / "test_cases" / "jev_tool_lab" / "s1_phase3.json"
    systems = sorted({c["system"] for c in json.loads(path.read_text())})
    keys = {s: AM.system_key(s) for s in systems}
    assert all(keys.values()), {s: k for s, k in keys.items() if not k}
    aast = [s for s in systems if s.startswith("AAST 2018")]
    print("AAST systems collapsing to one key:", {s: keys[s] for s in aast})
    assert len(aast) == 3 and {keys[s] for s in aast} == {"aast_kidney", "aast_liver", "aast_spleen"}


def test_candidate_text_kinds():
    from rapid_reports_ai.scripts.review_labs import gate_c as G
    assert G.candidate_text({"kind": "grade", "anchor": "lesion", "evidence": {"system": "Bosniak"}}) == "a Bosniak category for the lesion"
    assert "4 cm" in G.candidate_text({"kind": "threshold", "anchor": "a", "evidence": {"parameter": "size", "threshold": "4 cm"}})
    assert G.candidate_text({"kind": "follow_up", "anchor": "a", "evidence": {"modality": "US", "timing": "6 months"}}) == "US follow-up 6 months for the a"
    assert G.candidate_text({"kind": "option", "anchor": "a", "evidence": {"text": "adenoma"}}) == "adenoma (for the a)"


def test_criteria_lookup_falls_back_to_unqualified_key():
    idx = {"lirads": ["LR-5: x"], "orads_us": ["3: y"]}
    assert AM.criteria_lookup(idx, "LI-RADS CT/MRI v2018") == ["LR-5: x"]
    assert AM.criteria_lookup(idx, "O-RADS US") == ["3: y"]
    assert AM.criteria_lookup(idx, "Bosniak 2019") == []
    assert "criteria_lookup" in dir(AM)


def test_hard_checks():
    rep = "FINDINGS:\nA 12 mm lesion.\nIMPRESSION:\nLesion. Recommend MRI."
    row = {"kind": "threshold", "edit_mode": "upgrade", "edit_find": "Recommend MRI.",
           "edit_replace": "Recommend MRI in 6 months; lesions over 40 mm need surgery referral.", "cls": "action"}
    v = GC.hard_violations(row, rep, dictation="12 mm lesion", history="")
    assert "ungrounded_number" in v and "management" in v
    row2 = {"kind": "option", "edit_mode": "insert", "edit_after": "Lesion.", "edit_replace": "Suggest follow-up CT.",
            "cls": "minor"}
    assert "second_recommendation" in GC.hard_violations(row2, rep, dictation="", history="")


def _adj(id8, k, arm="nocrit", cls="action", **kw):
    return {"id8": id8, "k": k, "arm": arm, "cls": cls, **kw}


def _s1(item, arm, run, kind, gradable, cat="a", **kw):
    return {"item_id": item, "arm": arm, "run": run, "kind": kind, "gradable": gradable, "category": cat, **kw}


def test_score_core_skips_and_gate_read():
    labels = {"a-0": {"correct": "yes", "violation": "none", "in_report": "no"},
              "a-1": {"correct": "no", "violation": "management", "in_report": "yes"},
              "a-2": {"correct": "yes", "in_report": "yes"},
              "a-3-dropped": {"in_report": "yes"}}
    adj = [_adj("a", 0), _adj("a", 1), _adj("a", 2, cls="minor"), _adj("a", 3, error="boom"),
           _adj("a", 4, arm="crit")]
    s1 = [_s1("s1", "nocrit", 1, "grade", True), _s1("s2", "nocrit", 1, "characterise", True),
          _s1("s3", "nocrit", 1, "grade", False), _s1("s1", "crit", 1, "grade", True),
          _s1("s2", "crit", 1, "grade", True), {"item_id": "s3", "arm": "crit", "run": 1, "skipped": "no_criteria"},
          _s1("s4", "nocrit", 1, "grade", True, error="x")]
    gate = [{"id8": "a", "k": 0, "run": 1, "noul": 0.1, "choice": {"choice": "not_stated"}},
            {"id8": "a", "k": 1, "run": 1, "noul": 0.9, "choice": {"choice": "stated"}},
            {"id8": "a", "k": 2, "run": 1, "noul": 0.2, "choice": {"choice": "stated"}},
            {"id8": "a", "k": 3, "run": 1, "noul": 0.8, "choice": {"choice": "stated"}}]
    r = GC.score(labels, adj, s1, gate)
    assert r["action_correct_share"] == 0.5 and r["n_action"] == 2     # error row and crit arm excluded
    assert r["hard_violations_hand"] == ["a-1"]
    n1 = r["s1_nocrit_run1"]
    assert n1["n"] == 3 and n1["false_cant_grade"] == 0.5 and n1["overcall"] == 1.0
    assert r["s1_crit_run1"]["n"] == 2
    assert r["crit_vs_nocrit_paired"]["n"] == 2 and r["crit_vs_nocrit_paired"]["gains"] == 1
    g = r["in_report_gate"]
    assert g["n_labelled"] == 4
    assert g["noul"]["recall"] == 2 / 3 and g["noul"]["false_alarm"] == 0.0     # a-2 missed (0.2)
    assert g["choice_stated"]["recall"] == 1.0 and g["choice_stated"]["false_alarm"] == 0.0
    assert set(g["noul_bands"]) == {"yes", "unsure", "no"}


def test_dropped_sample_spread():
    rows = [{"id8": i, "k": k, "run": 1, "choice": {"choice": "stated"}} for i in "ab" for k in range(5)]
    rows.append({"id8": "a", "k": 9, "run": 2, "choice": {"choice": "stated"}})
    s = GC.dropped_sample(rows, limit=4)
    assert [(r["id8"], r["k"]) for r in s] == [("a", 0), ("b", 0), ("a", 1), ("b", 1)]
