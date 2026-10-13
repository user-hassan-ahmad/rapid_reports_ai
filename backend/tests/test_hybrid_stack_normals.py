import pytest

from rapid_reports_ai.hybrid_stack import jev_stack as J
from rapid_reports_ai.hybrid_stack import normals as N

NORMALS = {"Liver": ["The liver is normal."], "Kidneys": ["The kidneys are normal."],
           "Pelvic organs": ["The uterus is normal.", "The ovaries are normal.", "No adnexal mass."]}


def _checks(table, seen=None):
    async def fake(dictation, sentences, removed):
        if seen is not None:
            seen.append(list(sentences))
        return [J.RowCheck(*table.get(s, (0.0, 0.0, 0.0))) for s in sentences]
    return fake


async def test_every_region_is_checked_dictated_normal_regions_included(monkeypatch):
    # review R2: a dictated-normal region is asked like an abnormal one; the stated check removes what was said
    seen = []
    monkeypatch.setattr(N, "ask_rows", _checks({"The ovaries are normal.": (0.0, 0.9, 0.0),
                                                 "No adnexal mass.": (0.4, 0.0, 0.0),
                                                 "The kidneys are normal.": (0.9, 0.0, 0.0)}, seen))
    out = await N.assumed("A right ovarian cyst. Kidneys normal.", NORMALS, ["Pelvic organs"], ["Kidneys"], [])
    assert out.assumed == {"Liver": ["The liver is normal."], "Kidneys": [],
                           "Pelvic organs": ["The uterus is normal.", "No adnexal mass."]}
    assert out.dropped["Kidneys"] == [{"sentence": "The kidneys are normal.", "reason": "covered"}]
    assert out.flagged == {"Liver": [], "Kidneys": [], "Pelvic organs": ["No adnexal mass."]}
    assert sorted(sum(seen, [])) == sorted(["The liver is normal.", "The kidneys are normal.", "The uterus is normal.",
                                             "The ovaries are normal.", "No adnexal mass."])


async def test_a_dictated_normal_keeps_its_regions_other_sentences(monkeypatch):
    # review R2: dictating "ACL intact" must not lose the PCL sentence
    calls = []
    said = "The anterior cruciate ligament is intact."
    knee = {"Ligaments": ["The anterior cruciate ligament is intact.", "The posterior cruciate ligament is intact."],
            "Menisci": ["The menisci are intact."]}
    table = {(said, "The anterior cruciate ligament is intact."): (0.97, 0.0, 0.0),
             (said, "The posterior cruciate ligament is intact."): (0.05, 0.0, 0.0)}
    monkeypatch.setattr(N, "ask_rows", _by_dictation(table, calls))
    out = await N.assumed(said, knee, [], ["Ligaments"], [], region_text={"Ligaments": said})
    assert out.assumed == {"Ligaments": ["The posterior cruciate ligament is intact."],
                           "Menisci": ["The menisci are intact."]}
    assert out.dropped["Ligaments"] == [{"sentence": "The anterior cruciate ligament is intact.", "reason": "covered"}]
    assert [c["sentences"] for c in calls if c["stated"]] == [knee["Ligaments"]]


async def test_an_untouched_region_contradicted_by_a_misplaced_finding_assumes_nothing(monkeypatch):
    # the grouper filed "a splenic laceration" under another region: the spleen looks untouched
    normals = {"Spleen": ["The spleen is normal."], "Liver": ["The liver is normal."]}
    monkeypatch.setattr(N, "ask_rows", _checks({"The spleen is normal.": (0.0, 0.85, 0.0)}))
    out = await N.assumed("Small splenic laceration.", normals, ["Liver"], [], [])
    assert out.assumed == {"Spleen": [], "Liver": ["The liver is normal."]}


async def test_removed_and_owned_sentences_are_never_assumed(monkeypatch):
    normals = {"Kidneys": ["The kidneys are unremarkable."], "Bowel": ["The appendix is normal in calibre.", "No diverticula."]}
    table = {"The kidneys are unremarkable.": (0.0, 0.0, 0.7), "The appendix is normal in calibre.": (0.0, 0.0, 0.9)}
    monkeypatch.setattr(N, "ask_rows", _checks(table))
    out = await N.assumed("x", normals, [], [], ["No hydronephrosis."], owned=["The appendix is normal."])
    assert out.assumed == {"Kidneys": [], "Bowel": ["No diverticula."]}


async def test_sentences_are_asked_in_parallel_batches(monkeypatch):
    seen = []
    normals = {f"R{i}": [f"Normal {i} a.", f"Normal {i} b."] for i in range(20)}
    monkeypatch.setattr(N, "ask_rows", _checks({}, seen))
    out = await N.assumed("x", normals, [], [], [])
    assert [len(b) for b in seen] == [15, 15, 10] and sum(len(v) for v in out.assumed.values()) == 40


async def test_failure_assumes_nothing(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(N, "ask_rows", boom)
    out = await N.assumed("x", NORMALS, ["Pelvic organs"], [], [])
    assert out.assumed == {"Liver": [], "Kidneys": [], "Pelvic organs": []} and "RuntimeError" in out.error


async def test_a_met_context_condition_drops_its_target(monkeypatch):
    async def rows(dictation, sentences, removed, transport=None):
        return [J.RowCheck(0.0, 0.0, 0.0) for _ in sentences]

    async def conds(state, conditions):
        # review R5: the session's rules are decided from the clinical history, not the dictation
        assert "Headache." in state and "No previous MRI." not in state
        assert conditions == ["no previous study is available"]
        return [0.9 for _ in conditions]

    monkeypatch.setattr(N, "ask_rows", rows)
    monkeypatch.setattr(N, "ask_conditions", conds)
    out = await N.assumed(
        "No previous MRI.", {"Brain": ["No other interval changes compared with the previous MRI.",
                                       "The ventricles are normal in size."]}, [], [], [],
        suppressions=[("no previous study is available",
                       "No other interval changes compared with the previous MRI.")],
        clinical_history="Headache.")
    assert out.assumed == {"Brain": ["The ventricles are normal in size."]}
    assert out.dropped["Brain"] == [{"sentence": "No other interval changes compared with the previous MRI.",
                                     "reason": "rule"}]
    assert out.rules == {"no previous study is available": 0.9}


async def test_an_unmet_context_condition_keeps_its_target(monkeypatch):
    async def conds(state, conditions):
        return [0.1 for _ in conditions]

    monkeypatch.setattr(N, "ask_rows", _checks({}))
    monkeypatch.setattr(N, "ask_conditions", conds)
    out = await N.assumed("Stable since the previous MRI.", {"Brain": ["No other interval changes."]}, [], [], [],
                          suppressions=[("no previous study is available", "No other interval changes.")])
    assert out.assumed == {"Brain": ["No other interval changes."]} and out.dropped == {"Brain": []}


async def test_dropped_normals_carry_their_reason(monkeypatch):
    monkeypatch.setattr(N, "ask_rows", _checks({"The liver is normal.": (0.9, 0.0, 0.0),
                                                 "The kidneys are normal.": (0.0, 0.9, 0.0),
                                                 "The uterus is normal.": (0.4, 0.0, 0.0),
                                                 "The ovaries are normal.": (0.0, 0.0, 0.8)}))
    out = await N.assumed("x", NORMALS, [], [], ["Ovaries normal."])
    assert out.dropped == {"Liver": [{"sentence": "The liver is normal.", "reason": "covered"}],
                           "Kidneys": [{"sentence": "The kidneys are normal.", "reason": "contradicted"}],
                           "Pelvic organs": [{"sentence": "The ovaries are normal.", "reason": "removed"}]}
    # hedged is no longer a drop reason (review R1): the uterus is kept, flagged
    assert out.assumed["Pelvic organs"] == ["The uterus is normal.", "No adnexal mass."]
    assert out.flagged["Pelvic organs"] == ["The uterus is normal."]


# ── Three-state band (review R1 2026-10-13): only the bars drop; the 0.3–bar band is kept, flagged ───────────────
@pytest.mark.parametrize("stated,contra,fate", [
    (0.29, 0.0, "assumed"), (0.3, 0.0, "flagged"), (0.69, 0.0, "flagged"), (0.7, 0.0, "flagged"),
    (0.79, 0.0, "flagged"), (0.8, 0.0, "covered"),
    (0.0, 0.29, "assumed"), (0.0, 0.3, "flagged"), (0.0, 0.69, "flagged"), (0.0, 0.7, "contradicted"),
    (0.0, 0.79, "contradicted"), (0.0, 0.8, "contradicted"),
])
async def test_band_boundaries(monkeypatch, stated, contra, fate):
    s = "The liver is normal."
    monkeypatch.setattr(N, "ask_rows", _checks({s: (stated, contra, 0.0)}))
    out = await N.assumed("x", {"Liver": [s]}, ["Liver"], [], [])
    assert out.error is None
    assert J.normal_fate(J.RowCheck(stated, contra, 0.0)) == fate
    if fate in ("covered", "contradicted"):
        assert out.assumed == {"Liver": []} and out.flagged == {"Liver": []}
        assert out.dropped == {"Liver": [{"sentence": s, "reason": fate}]}
    else:
        assert out.assumed == {"Liver": [s]} and out.dropped == {"Liver": []}
        assert out.flagged == {"Liver": [s] if fate == "flagged" else []}


async def test_a_flagged_sentence_the_radiologist_removed_is_dropped_as_removed(monkeypatch):
    s = "The liver is normal."
    monkeypatch.setattr(N, "ask_rows", _checks({s: (0.5, 0.0, 0.6)}))
    out = await N.assumed("x", {"Liver": [s]}, ["Liver"], [], ["Liver normal."])
    assert out.assumed == {"Liver": []} and out.flagged == {"Liver": []}
    assert out.dropped == {"Liver": [{"sentence": s, "reason": "removed"}]}


async def test_an_empty_dictation_or_a_failure_flags_nothing(monkeypatch):
    out = await N.assumed("", NORMALS, [], [], [])
    assert out.flagged == {r: [] for r in NORMALS}

    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(N, "ask_rows", boom)
    out = await N.assumed("x", NORMALS, [], [], [])
    assert out.flagged == {r: [] for r in NORMALS}


async def test_a_labelled_normal_is_asked_with_its_label_and_returned_as_written(monkeypatch):
    seen = []
    monkeypatch.setattr(N, "ask_rows", _checks({}, seen))
    out = await N.assumed("Splenic cyst.", {"Liver": ["Unremarkable.", "The spleen is normal."]}, [], [], [],
                          labels={"Unremarkable.": "liver"})
    assert seen == [["Liver: Unremarkable.", "The spleen is normal."]]
    assert out.assumed == {"Liver": ["Unremarkable.", "The spleen is normal."]}


async def test_a_condition_check_failure_assumes_nothing(monkeypatch):
    async def boom(state, conditions):
        raise RuntimeError("jev down")

    monkeypatch.setattr(N, "ask_rows", _checks({}))
    monkeypatch.setattr(N, "ask_conditions", boom)
    out = await N.assumed("x", NORMALS, [], [], [], suppressions=[("no prior study", "The liver is normal.")])
    assert out.assumed == {r: [] for r in NORMALS} and out.dropped == {r: [] for r in NORMALS}
    assert out.error and "jev down" in out.error


def test_one_normaliser_matches_suppressions():
    from rapid_reports_ai.hybrid_stack import template as T
    assert N.norm_key is T.norm_key
    assert T.norm_key("  No  other changes. ") == T.norm_key("no other changes")


# ── Coverage only from the normal's own region (Task A3b) ──────────────────────────────────────────────────────
def _by_dictation(table, calls):
    """Jev as a table keyed by (dictation state, sentence); honours the stated/contra split."""
    async def fake(dictation, sentences, removed, *, stated=True, contra=True):
        calls.append({"dictation": dictation, "sentences": list(sentences), "removed": list(removed),
                      "stated": stated, "contra": contra})
        out = []
        for s in sentences:
            st, co, rm = table.get((dictation, s), (0.0, 0.0, 0.0))
            out.append(J.RowCheck(st if stated else 0.0, co if contra else 0.0, rm if removed else 0.0))
        return out
    return fake


BRAIN = {"Brain": ["The ventricles are normal in size.", "No intracranial haemorrhage."],
         "Lungs": ["No pneumothorax.", "The lungs are clear."]}


async def test_a_conclusion_only_dictation_keeps_the_region_normals(monkeypatch):
    calls = []
    d = "No acute intracranial abnormality."   # grouped Conclusion: no region text
    monkeypatch.setattr(N, "ask_rows", _by_dictation({(d, "No intracranial haemorrhage."): (0.9, 0.0, 0.0),
                                                       (d, "The ventricles are normal in size."): (0.5, 0.0, 0.0)},
                                                      calls))
    out = await N.assumed(d, BRAIN, [], [], [], region_text={})
    assert out.assumed == BRAIN and out.dropped == {"Brain": [], "Lungs": []}
    assert all(not c["stated"] for c in calls)   # nothing in any region: no coverage question asked
    assert all(c["dictation"] == d and c["contra"] for c in calls)


async def test_a_same_region_sentence_still_covers_its_normal(monkeypatch):
    calls = []
    d = "No pneumothorax.\nNo acute intracranial abnormality."
    table = {("No pneumothorax.", "No pneumothorax."): (0.95, 0.0, 0.0),
             (d, "The ventricles are normal in size."): (0.9, 0.0, 0.0)}   # the conclusion would cover it
    monkeypatch.setattr(N, "ask_rows", _by_dictation(table, calls))
    out = await N.assumed(d, BRAIN, ["Lungs"], [], [], region_text={"Lungs": "No pneumothorax."})
    assert out.assumed == {"Brain": BRAIN["Brain"], "Lungs": ["The lungs are clear."]}
    assert out.dropped["Lungs"] == [{"sentence": "No pneumothorax.", "reason": "covered"}]
    stated = [c for c in calls if c["stated"]]
    assert stated == [{"dictation": "No pneumothorax.", "sentences": BRAIN["Lungs"], "removed": [],
                       "stated": True, "contra": False}]


async def test_a_conclusion_that_contradicts_a_normal_still_drops_it(monkeypatch):
    calls = []
    d = "Acute right MCA infarct."
    monkeypatch.setattr(N, "ask_rows", _by_dictation({(d, "The ventricles are normal in size."): (0.0, 0.2, 0.0),
                                                       (d, "No intracranial haemorrhage."): (0.0, 0.85, 0.0)}, calls))
    out = await N.assumed(d, BRAIN, [], [], [], region_text={})
    assert out.dropped["Brain"] == [{"sentence": "No intracranial haemorrhage.", "reason": "contradicted"}]
    assert out.assumed["Brain"] == ["The ventricles are normal in size."]


async def test_a_general_normal_study_covers_nothing(monkeypatch):
    calls = []
    d = "Normal study."   # grouped General: no region text
    table = {(d, s): (0.85, 0.0, 0.0) for ss in BRAIN.values() for s in ss}
    monkeypatch.setattr(N, "ask_rows", _by_dictation(table, calls))
    out = await N.assumed(d, BRAIN, [], [], [], region_text={})
    assert out.assumed == BRAIN


async def test_region_mode_asks_removed_once_over_the_whole_dictation(monkeypatch):
    calls = []
    d = "Lungs clear. Brain fine."
    table = {(d, "The lungs are clear."): (0.0, 0.0, 0.8)}
    monkeypatch.setattr(N, "ask_rows", _by_dictation(table, calls))
    out = await N.assumed(d, BRAIN, [], [], ["Clear lungs."], region_text={"Lungs": "Lungs clear.", "Brain": ""})
    assert out.dropped["Lungs"] == [{"sentence": "The lungs are clear.", "reason": "removed"}]
    contra = [c for c in calls if c["contra"]]
    assert len(contra) == 1 and contra[0]["removed"] == ["Clear lungs."] and not contra[0]["stated"]
    assert [c["dictation"] for c in calls if c["stated"]] == ["Lungs clear."]   # an empty region asks nothing


async def test_region_mode_failure_assumes_nothing(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(N, "ask_rows", boom)
    out = await N.assumed("x", BRAIN, [], [], [], region_text={"Lungs": "x"})
    assert out.assumed == {"Brain": [], "Lungs": []} and "RuntimeError" in out.error


async def test_each_refresh_logs_its_jev_calls_and_failure(monkeypatch, caplog):
    import logging
    calls = []
    monkeypatch.setattr(N, "ask_rows", _by_dictation({}, calls))
    with caplog.at_level(logging.INFO, logger=N.__name__):
        await N.assumed("Lungs clear.", BRAIN, [], [], [], region_text={"Lungs": "Lungs clear."})
    line = [r for r in caplog.records if "jev_calls" in r.getMessage()][-1]
    assert f"jev_calls={len(calls)}" in line.getMessage() and "failed=False" in line.getMessage()
    assert len(calls) == 2 and line.levelno == logging.INFO

    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(N, "ask_rows", boom)
    with caplog.at_level(logging.INFO, logger=N.__name__):
        await N.assumed("x", BRAIN, [], [], [])
    line = [r for r in caplog.records if "jev_calls" in r.getMessage()][-1]
    assert "jev_calls=1" in line.getMessage() and "failed=True" in line.getMessage()
    assert line.levelno == logging.WARNING


async def test_an_empty_dictation_makes_no_jev_call_and_keeps_every_normal(monkeypatch):
    async def never(*a, **k):
        raise AssertionError("Jev must not be called for an empty dictation")

    monkeypatch.setattr(N, "ask_rows", never)
    monkeypatch.setattr(N, "ask_conditions", never)
    for blank in ("", "  \n"):
        out = await N.assumed(blank, NORMALS, [], [], ["The kidneys are normal."], owned=["The uterus is normal."],
                              suppressions=[("no prior study", "The liver is normal.")],
                              rules={"no prior study": 0.1})   # decided for the session: unmet
        assert out.assumed == {"Liver": ["The liver is normal."], "Kidneys": [],
                               "Pelvic organs": ["The ovaries are normal.", "No adnexal mass."]}
        assert out.dropped["Kidneys"] == [{"sentence": "The kidneys are normal.", "reason": "removed"}]
        assert out.error is None


# ── Template context rules decided once per session (review R5 2026-10-13) ────────────────────────────────────
PRIOR = "No other interval changes compared with the previous MRI."
BRAIN_R = {"Brain": [PRIOR, "The ventricles are normal in size."]}
NO_PRIOR = "no previous study is available"
NAMES_PRIOR = "the dictation names a previous imaging study for comparison"


def _conds(scores, calls):
    async def fake(state, conditions):
        calls.append({"state": state, "conditions": list(conditions)})
        return [scores[c] for c in conditions]
    return fake


async def test_an_empty_dictation_applies_the_sessions_suppressions(monkeypatch):
    async def never(*a, **k):
        raise AssertionError("no per-sentence check for an empty dictation")

    calls = []
    monkeypatch.setattr(N, "ask_rows", never)
    monkeypatch.setattr(N, "ask_conditions", _conds({NO_PRIOR: 0.9}, calls))
    out = await N.assumed("", BRAIN_R, [], [], [], suppressions=[(NO_PRIOR, PRIOR)], clinical_history="First scan.")
    assert out.assumed == {"Brain": ["The ventricles are normal in size."]}
    assert out.dropped["Brain"] == [{"sentence": PRIOR, "reason": "rule"}]
    assert out.rules == {NO_PRIOR: 0.9} and out.error is None
    assert calls == [{"state": "CLINICAL HISTORY:\nFirst scan.", "conditions": [NO_PRIOR]}]
    # the cached decision: no call at all
    calls.clear()
    out = await N.assumed("", BRAIN_R, [], [], [], suppressions=[(NO_PRIOR, PRIOR)], clinical_history="First scan.",
                          rules=out.rules)
    assert out.assumed == {"Brain": ["The ventricles are normal in size."]} and calls == []


async def test_the_rules_are_decided_once_per_session_not_per_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(N, "ask_rows", _checks({}))
    monkeypatch.setattr(N, "ask_conditions", _conds({NO_PRIOR: 0.9, NAMES_PRIOR: 0.1}, calls))
    sup = [(NO_PRIOR, PRIOR), (NAMES_PRIOR, PRIOR)]
    first = await N.assumed("", BRAIN_R, [], [], [], suppressions=sup, clinical_history="Headache.")
    rules = first.rules
    for d in ("Small left frontal meningioma.", "Small left frontal meningioma. Compared with the MRI of 2024."):
        out = await N.assumed(d, BRAIN_R, ["Brain"], [], [], suppressions=sup, clinical_history="Headache.", rules=rules)
        assert out.dropped["Brain"] == [{"sentence": PRIOR, "reason": "rule"}] and out.rules == rules
    assert len(calls) == 1


async def test_confirm_re_asks_only_the_conditions_that_mention_findings(monkeypatch):
    calls = []
    monkeypatch.setattr(N, "ask_rows", _checks({}))
    monkeypatch.setattr(N, "ask_conditions", _conds({NAMES_PRIOR: 0.95}, calls))
    sup = [(NO_PRIOR, PRIOR), (NAMES_PRIOR, "The ventricles are normal in size.")]
    rules = {NO_PRIOR: 0.1, NAMES_PRIOR: 0.1}   # decided from the history: neither met
    d = "Stable meningioma compared with the MRI of 2024."
    live = await N.assumed(d, BRAIN_R, ["Brain"], [], [], suppressions=sup, clinical_history="Headache.", rules=rules)
    assert live.assumed == BRAIN_R and calls == []     # live refreshes never re-ask
    assert live.confirm_recheck is True
    out = await N.assumed(d, BRAIN_R, ["Brain"], [], [], suppressions=sup, clinical_history="Headache.", rules=rules,
                          confirm=True)
    assert calls == [{"state": f"CLINICAL HISTORY:\nHeadache.\nDICTATED FINDINGS:\n{d}", "conditions": [NAMES_PRIOR]}]
    assert out.assumed == {"Brain": [PRIOR]}
    assert out.dropped["Brain"] == [{"sentence": "The ventricles are normal in size.", "reason": "rule"}]
    assert out.rules == rules     # the session's decision is unchanged


async def test_confirm_without_findings_conditions_makes_no_rule_call(monkeypatch):
    calls = []
    monkeypatch.setattr(N, "ask_rows", _checks({}))
    monkeypatch.setattr(N, "ask_conditions", _conds({}, calls))
    out = await N.assumed("Meningioma.", BRAIN_R, ["Brain"], [], [], suppressions=[(NO_PRIOR, PRIOR)],
                          clinical_history="x", rules={NO_PRIOR: 0.1}, confirm=True)
    assert calls == [] and out.assumed == BRAIN_R and out.confirm_recheck is False


def test_conditions_that_mention_findings():
    assert N.mentions_findings(NAMES_PRIOR) and N.mentions_findings("The dictated findings report a lesion")
    assert not N.mentions_findings(NO_PRIOR) and not N.mentions_findings("a short-form report is requested by the referrer")
