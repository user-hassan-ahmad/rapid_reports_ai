from rapid_reports_ai.scripts import template_sheet_lab as lab
from rapid_reports_ai.scripts.template_sheet_lab_score import score, sim

KEY = {
    "sections": [{"name": "FINDINGS", "header": "Findings:"}, {"name": "CONCLUSION", "header": "Conclusion:"}],
    "planted": [
        {"id": "P1", "kind": "NEGATIVE", "text": "No alpha beta collection."},
        {"id": "P2", "kind": "NEGATIVE", "text": "No gamma delta."},
        {"id": "P3", "kind": "NORMAL", "text": "The epsilon zeta is unremarkable."},
        {"id": "P4", "kind": "RULE", "effect": "replace", "target": "No alpha beta collection.",
         "then_text": "Small alpha beta collection.", "condition": {"source": "findings", "statement": "an alpha beta collection is reported"}},
        {"id": "P5", "kind": "RULE", "effect": "list_missing", "items": ["eta size", "theta volume"]},
        {"id": "P6", "kind": "IF_PRESENT", "text": "No iota kappa.", "grammar": 'IF_PRESENT [lambda mu] "No iota kappa." (core)'},
        {"id": "P7", "kind": "TERM", "text": "unremarkable"},
    ],
}

SHEET = """# Skill Sheet: <scan>

## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
TERM PREFER "unremarkable"
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["eta size" | "omega ratio"] AT TOP | section: FINDINGS

## Paragraph: Findings (FINDINGS)
NEGATIVE "No alpha beta collection."
NORMAL [epsilon zeta] "The epsilon zeta is unremarkable. No gamma delta."
NEGATIVE "No pi rho sigma."
RULE WHEN [findings: alpha beta collection is reported] REPLACE "No alpha beta collection." WITH "Small alpha beta collection."
IF_PRESENT [lambda mu] "No iota kappa." (core)

## Paragraph: Conclusion (CONCLUSION)
RULE WHEN [findings: no abnormal finding is reported anywhere in the study] USE "Normal study of the region."
"""


def test_sim_needs_real_overlap():
    assert sim("No alpha beta collection.", "No alpha beta collection") == 1.0
    assert sim("No ascites.", "No ascites or free fluid.") < 0.5
    assert sim("{value} mm", "{other}") == 0.0


def test_score_counts_matches_misses_cross_kind_and_spurious():
    structure, errs = lab.parse(SHEET, mode="v1")
    assert errs == []
    s = score(structure, KEY)
    pk = s["per_kind"]
    assert pk["NEGATIVE"]["planted"] == 2 and pk["NEGATIVE"]["matched"] == 1 and pk["NEGATIVE"]["precision"] == 0.5
    assert pk["NORMAL"]["matched"] == 1 and pk["RULE replace"]["matched"] == 1
    assert pk["LIST_MISSING item"] == {"planted": 2, "emitted": 2, "matched": 1, "recall": 0.5, "precision": 0.5}
    assert pk["IF_PRESENT"]["matched"] == 1 and pk["TERM"]["matched"] == 1
    assert pk["SECTION"]["recall"] == 1.0
    miss = {m["id"]: m for m in s["misses"]}
    assert miss["P2"]["cross_kind"] is True  # the negative sits inside the NORMAL sentence
    assert {x["text"] for x in s["spurious"]} >= {"No pi rho sigma.", "Normal study of the region.", "omega ratio"}
    assert s["units_recall"] == 0.75  # 6 of 8 planted units


def test_load_synthetic_reads_sets_with_keys(tmp_path):
    d = tmp_path / "set_a"
    (d / "examples").mkdir(parents=True)
    (d / "examples" / "01.md").write_text("EXAMPLE")
    (d / "answer_key.json").write_text('{"scan_type": "<scan>", "planted": [], "sections": []}')
    (tmp_path / "set_b" / "examples").mkdir(parents=True)  # no key yet: skipped
    data = lab.load_synthetic(tmp_path)
    assert [t["slug"] for t in data["templates"]] == ["set_a"]
    assert data["templates"][0]["examples"][0]["content"] == "EXAMPLE"


def test_intrinsic_scoring_leaves_case_units_to_phase_1():
    from rapid_reports_ai.scripts.template_sheet_lab_score import is_intrinsic

    assert not is_intrinsic({"kind": "IF_PRESENT"})
    assert not is_intrinsic({"kind": "RULE", "effect": "append", "condition": {"source": "findings", "statement": "x y"}})
    assert is_intrinsic({"kind": "RULE", "effect": "replace",
                         "condition": {"source": "findings", "statement": "the <part> was not performed"}})
    assert is_intrinsic({"kind": "RULE", "effect": "list_missing", "items": ["a"]})
    assert not is_intrinsic({"kind": "NEGATIVE", "condition": {"source": "history", "statement": "x y"}})
    structure, _ = lab.parse(SHEET, mode="v1")
    pk = score(structure, KEY, intrinsic_only=True)["per_kind"]
    assert pk["IF_PRESENT"]["planted"] == 0 and pk["RULE replace"]["planted"] == 0
    assert pk["LIST_MISSING item"]["planted"] == 2 and pk["PARAGRAPH"]["planted"] == 0
