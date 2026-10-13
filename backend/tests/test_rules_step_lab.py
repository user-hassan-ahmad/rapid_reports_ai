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


def test_score_sheet_counts_values_patient_lines_and_gold_normals():
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai import template_ledger_apply as tla
    from tests.template_sheet_fixtures import LEDGER_SHEET
    led, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation")
    led, _ = td.set_decision(led, "value", "Other", {"need": "every"}, source="creation")
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet
    s = {"slug": "s", "kind": "base", "truth": {
        "values": [{"name": "LVEF", "aliases": [], "reports": [1], "need": "every"},
                   {"name": "RVEF", "aliases": [], "reports": [1], "need": "every"}],
        "patient_specific_fixed": ["No previous imaging available."]}}
    out = L.score_sheet(s, sheet, gold=LEDGER_SHEET)
    assert out["usable"] == 1 and out["required_values_listed"] == 1 and out["required_values_total"] == 2
    assert out["extra_values_listed"] == 1 and out["patient_fixed_present"] == 1
    assert out["gold_normals_hit"] == 1 and out["gold_normals_total"] == 1 and out["duplicate_normals"] == 0
    assert out["comparison_rule"] == 0 and out["context_rules"] == 0 and out["multi_structure_normals"] == 0
    assert L.score_sheet(s, "# free")["usable"] == 0


def test_writer_arms_use_the_next_prompts_and_the_decisions_only_when_decided(monkeypatch):
    import asyncio
    from rapid_reports_ai import template_sheet_lab_prompts as P
    from rapid_reports_ai import template_sheet_model, template_sheet_save
    from rapid_reports_ai.template_sheet_save import VetOutcome
    from tests.template_sheet_fixtures import LEDGER_SHEET
    seen = []

    async def call(system, user, settings):
        seen.append((system, user, settings["temperature"]))
        return f"{P.SHEET_OPEN}\n{LEDGER_SHEET}\n{P.SHEET_CLOSE}\n" + '{"summary": {}}'

    async def vet(sheet, origin, previous="", ledger=None):
        return VetOutcome("saved", sheet, ledger=list(ledger or []), ledger_drift=len(ledger or []))
    monkeypatch.setattr(template_sheet_model, "model_call", call)
    monkeypatch.setattr(template_sheet_save, "vet_sheet", vet)
    s = {"slug": "s", "examples": ["r1"], "scan_type": "<scan>"}
    answers = [{"kind": "value", "key": "Value A", "choice": {"need": "every"}}]
    a = asyncio.run(L._write_one(s, answers, *L.ARMS["A"]))
    c = asyncio.run(L._write_one(s, answers, *L.ARMS["C"]))
    (sys_a, user_a, t_a), (sys_c, user_c, t_c) = seen
    assert sys_a == P.analyser_system_prompt(False) and P.DECIDED_HEADING not in user_a and t_a == 0.8
    assert sys_c == P.analyser_system_prompt(True) and P.DECIDED_HEADING in user_c and t_c == 0.4
    assert '"questions"' not in user_a + user_c
    assert a["status"] == "saved" and a["drift"] == 0 and c["drift"] == 1 and c["sheet"] == LEDGER_SHEET.strip()


_GIVEN = 'the dictation states a contrast agent was given'
_NOT_GIVEN = 'the dictation states no contrast agent was given'
_PRIOR = 'the dictation names a previous imaging study for comparison'


def _with_technique(*lines):
    from tests.template_sheet_fixtures import LEDGER_SHEET
    return LEDGER_SHEET.replace('FIXED "Axial images were acquired."\n',
                                'FIXED "Axial images were acquired."\n' + "".join(f"{x}\n" for x in lines), 1)


def _truth(usual="not_given", default="", when_met=""):
    return {"slug": "s", "kind": "variant", "truth": {"values": [], "patient_specific_fixed": [], "concepts": {
        "comparison": {"default": "No previous imaging available.", "when_met": "", "usual_state": "none"},
        "contrast": {"default": default, "when_met": when_met, "usual_state": usual}}}}


def test_score_sheet_counts_concept_lines_beyond_one_fixed_and_one_rule():
    one = _with_technique('FIXED "No agent was given."', f'RULE WHEN [context: {_GIVEN}] SUPPRESS "No agent was given."')
    assert L.score_sheet(_truth(), one)["concept_duplicates"] == 0
    # a second FIXED line stating the same concept (a known wording from the truth) and a second rule
    two = _with_technique('FIXED "No agent was given."', f'RULE WHEN [context: {_GIVEN}] SUPPRESS "No agent was given."',
                          'FIXED "Contrast was not administered."',
                          f'RULE WHEN [context: {_GIVEN}] REPLACE "Contrast was not administered." WITH "Agent given."')
    assert L.score_sheet(_truth(when_met="Contrast was not administered."), two)["concept_duplicates"] == 2
    # comparison: the fixture's own FIXED line plus a second copy of the truth's wording elsewhere
    from tests.template_sheet_fixtures import LEDGER_SHEET
    s = _truth()
    s["truth"]["concepts"]["comparison"]["default"] = "No previous imaging available."
    rule = f'RULE WHEN [context: {_PRIOR}] REPLACE "No previous imaging available." WITH "Compared with {{date}}."'
    sheet = LEDGER_SHEET.replace('FIXED "No previous imaging available."\n',
                                 f'FIXED "No previous imaging available."\n{rule}\n', 1)
    assert L.score_sheet(s, sheet)["concept_duplicates"] == 0
    again = sheet.replace('FIXED "Axial images were acquired."\n',
                          'FIXED "Axial images were acquired."\nFIXED "No previous imaging available."\n', 1)
    assert L.score_sheet(s, again)["concept_duplicates"] == 1


def test_score_sheet_scores_contrast_presence_polarity_and_condition():
    right = _with_technique('FIXED "No agent was given."', f'RULE WHEN [context: {_GIVEN}] SUPPRESS "No agent was given."')
    out = L.score_sheet(_truth("not_given", default="No agent was given."), right)
    assert out["contrast_rule"] == 1 and out["contrast_condition_ok"] == 1 and out["contrast_default_ok"] == 1
    wrong = _with_technique('FIXED "Agent given."', f'RULE WHEN [context: {_NOT_GIVEN}] SUPPRESS "Agent given."')
    out = L.score_sheet(_truth("not_given", default="No agent was given."), wrong)
    assert out["contrast_rule"] == 1 and out["contrast_condition_ok"] == 0 and out["contrast_default_ok"] == 0
    # no known wording: polarity by condition only, default n/a; no contrast lines at all
    out = L.score_sheet(_truth("given"), wrong)
    assert out["contrast_condition_ok"] == 1 and out["contrast_default_ok"] == "n/a"
    from tests.template_sheet_fixtures import LEDGER_SHEET
    out = L.score_sheet(_truth("given"), LEDGER_SHEET)
    assert out["contrast_rule"] == 0 and out["contrast_condition_ok"] == 0
    # the radiologist's answer, when there is one, is the truth
    answers = [{"kind": "concept", "key": "contrast", "choice": {"use": True, "default": "Agent given.", "when_met": "",
                                                                 "condition": _NOT_GIVEN}}]
    out = L.score_sheet(_truth("not_given", default="No agent was given."), wrong, answers=answers)
    assert out["contrast_condition_ok"] == 1 and out["contrast_default_ok"] == 1
    assert L.score_sheet(_truth(), "# free").get("contrast_rule") is None


def test_score_sheet_counts_slots_in_normal_lines():
    from tests.template_sheet_fixtures import LEDGER_SHEET
    assert L.score_sheet(_truth(), LEDGER_SHEET)["normal_slots"] == 0
    slotted = LEDGER_SHEET.replace('NORMAL [liver] "The liver is normal in size."',
                                   'NORMAL [liver] "The liver measures {measurement}."')
    assert L.score_sheet(_truth(), slotted)["normal_slots"] == 1


def test_required_normals_without_a_gold_sheet_use_the_planted_truth_or_say_n_a():
    from tests.template_sheet_fixtures import LEDGER_SHEET
    out = L.score_sheet(_truth(), LEDGER_SHEET)
    assert out["gold_normals_hit"] == "n/a" and out["gold_normals_total"] == "n/a"
    s = _truth()
    s["truth"]["normals"] = ["Liver", "Spleen"]
    out = L.score_sheet(s, LEDGER_SHEET)
    assert out["gold_normals_hit"] == 1 and out["gold_normals_total"] == 2 and out["normals_source"] == "truth"
    assert L.score_sheet(s, LEDGER_SHEET, gold=LEDGER_SHEET)["normals_source"] == "gold"
    rows = [{"kind": "A:variant", "gold_normals_hit": "n/a", "normal_slots": 1},
            {"kind": "A:variant", "gold_normals_hit": 2, "normal_slots": 0}]
    assert L.summarise(rows, ["gold_normals_hit", "normal_slots"])["A:variant"] == {
        "n": 2, "gold_normals_hit": 2, "normal_slots": 1}
