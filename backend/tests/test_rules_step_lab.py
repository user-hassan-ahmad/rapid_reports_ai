"""Pure scorers of the Rules-step lab (no network)."""
from rapid_reports_ai.scripts import rules_step_lab as L

SET = {"slug": "s", "examples": ["a", "b", "c", "d"], "truth": {
    "values": [{"name": "LVEF", "aliases": ["ejection fraction"], "reports": [1, 2, 3, 4], "need": "every"},
               {"name": "ECV", "aliases": [], "reports": [1, 3], "need": "relevant"}],
    "concepts": {"comparison": {"stated_in": [2, 4]}, "contrast": {"stated_in": [], "usual_state": "not_given"}},
    "disagreements": ["contrast"], "patient_specific_fixed": [], "only_when_abnormal": []}}


def _card(cid, kind="value", key=None, evidence=()):
    return {"id": cid, "kind": kind, "key": key or cid.split(":")[1], "evidence": list(evidence)}


def test_score_decide_counts_values_concepts_disagreements_and_budget():
    contrast = {**_card("concept:contrast", "concept", "contrast"),
                "wording": {"condition": "the dictation states a contrast agent was given"}}
    payload = {"cards": [_card("value:ecv"), _card("value:heart rate"), _card("disagree:contrast", "disagree", "contrast"),
                         contrast],
               "more": [], "kept": [_card("value:ejection fraction", key="Ejection fraction")],
               "run": {"dropped_quotes": 2}, "states": {"comparison": [2, 4], "contrast": [1],
                                                         "sequences": [], "limitation": []}}
    s = L.score_decide(SET, payload)
    assert s["values_found"] == 2 and s["values_total"] == 2 and s["values_extra"] == 1
    assert s["every_kept"] == 1 and s["partial_carded"] == 1
    assert s["concept_cells"] == 8 and s["concept_correct"] == 7      # 2 truth concepts x 4 reports; contrast wrong in report 1
    assert s["disagreements_found"] == 1 and s["disagreements_total"] == 1
    assert s["polarity_correct"] == 1 and s["polarity_total"] == 1      # usual "not_given" -> condition "given"
    assert s["cards"] == 4 and s["over_budget"] is False and s["dropped_quotes"] == 2


def test_summarise_totals_by_kind():
    rows = [{"kind": "base", "values_found": 1, "values_total": 2, "cards": 3},
            {"kind": "base", "values_found": 2, "values_total": 2, "cards": 9},
            {"kind": "real", "values_found": 0, "values_total": 1, "cards": 1}]
    out = L.summarise(rows, ["values_found", "values_total", "cards"])
    assert out["base"] == {"n": 2, "values_found": 3, "values_total": 4, "cards": 12}
    assert out["real"]["n"] == 1


def test_score_decide_reads_values_inside_a_more_group():
    group = {"id": "group:one_report", "kind": "group", "key": "", "evidence": [],
             "cards": [_card("value:ecv")]}
    s = L.score_decide(SET, {"cards": [], "more": [group], "kept": [], "states": {}})
    assert s["values_found"] == 1
