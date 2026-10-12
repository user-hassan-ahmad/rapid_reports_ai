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


async def test_every_region_is_checked_dictated_normal_regions_assume_nothing(monkeypatch):
    seen = []
    monkeypatch.setattr(N, "ask_rows", _checks({"The ovaries are normal.": (0.0, 0.9, 0.0),
                                                 "No adnexal mass.": (0.4, 0.0, 0.0)}, seen))
    out = await N.assumed("A right ovarian cyst. Kidneys normal.", NORMALS, ["Pelvic organs"], ["Kidneys"], [])
    assert out.assumed == {"Liver": ["The liver is normal."], "Kidneys": [], "Pelvic organs": ["The uterus is normal."]}
    assert sorted(sum(seen, [])) == sorted(["The liver is normal.", "The uterus is normal.", "The ovaries are normal.",
                                             "No adnexal mass."])


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
        assert "No previous MRI." in state and "Headache." in state
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
                           "Pelvic organs": [{"sentence": "The uterus is normal.", "reason": "hedged"},
                                             {"sentence": "The ovaries are normal.", "reason": "removed"}]}
    assert out.assumed["Pelvic organs"] == ["No adnexal mass."]


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
