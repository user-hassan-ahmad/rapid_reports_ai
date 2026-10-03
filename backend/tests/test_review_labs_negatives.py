from rapid_reports_ai.scripts.review_labs import negatives_lab as NL

REPORT = ("FINDINGS:\nA 3 cm mass in the left kidney. The renal veins are patent. No hydronephrosis. "
          "The liver is unremarkable.\nIMPRESSION:\nLeft renal mass.")


def test_candidates_pick_normals_and_negatives_only():
    got = [c["clause"] for c in NL.candidates(REPORT)]
    assert "A 3 cm mass in the left kidney." not in got and "Left renal mass." not in got
    assert any("patent" in c for c in got) and any("hydronephrosis" in c for c in got)
    assert any("unremarkable" in c for c in got)


def test_parse_labels():
    lines = ["1 | default | - | no", "2 | Implicated | dictated mass | no", "3 | weird | - | no", "9 | default | - | no",
             "x | default"]
    got = NL.parse_labels(lines, 3)
    assert got == {1: {"cls": "default", "pointer": "", "number": False},
                   2: {"cls": "implicated", "pointer": "dictated mass", "number": False}}


def test_labels_decodes_string_encoded_list():
    assert NL.Labels(labels='["1 | default | - | no"]').labels == ["1 | default | - | no"]


def test_code_number_flag():
    assert NL.code_number_flag("The duct measures 5 mm.", "duct normal", "")
    assert not NL.code_number_flag("A 3 cm mass.", "3 cm mass", "")


def test_score_unsafe_misses_and_recall():
    labels = {"rules": {}, "a-1": {"verdict": "implicated"}, "a-2": {"verdict": "default"},
              "a-3": {"verdict": "contradicted"}}
    results = [{"id8": "a", "run": 1, "labels": {"1": {"cls": "default"}, "2": {"cls": "default"},
                                                  "3": {"cls": "contradicted"}}},
               {"id8": "a", "run": 2, "labels": {"1": {"cls": "implicated"}, "2": {"cls": "default"},
                                                  "3": {"cls": "contradicted"}}}]
    s = NL.score(labels, results)
    assert s["run1"]["unsafe_misses"] == ["a-1"] and s["run1"]["implicated_recall"] == 0.0
    assert s["run2"]["implicated_recall"] == 1.0 and s["run_flip_share"] == 1 / 3


def test_prompts_load_and_v2_default():
    assert NL.DEFAULT_PROMPT == "negatives_v5"
    assert "When in doubt between default and implicated, choose implicated" in NL.prompt()
    assert "Classify each numbered statement" in NL.prompt("negatives_v1")


def test_v5_adds_history_contradiction_rule_only():
    v4, v5 = NL.prompt("negatives_v4"), NL.prompt("negatives_v5")
    assert "clinical history names as diseased" in v5 and "clinical history names as diseased" not in v4
    assert len(v5) - len(v4) < 250


def test_code_number_flag_ignores_sequence_and_level_names():
    assert not NL.code_number_flag("No T1 hypointensity at C7 or L4/5.", "cord compression", "")
    assert NL.code_number_flag("The junctional zone measures less than 12 mm.", "normal uterus", "")
