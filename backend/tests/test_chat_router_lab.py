"""The chat-edit router lab's pure scorers (the runners call models and are run by the controller)."""
import json

import pytest

from rapid_reports_ai.scripts import chat_router_lab as lab
from tests.template_sheet_fixtures import ROUTER_SHEET

KINDS = ("value", "concept", "fixed", "normal", "layout", "style", "misfit")


def _item(i, **labels):
    return {"id": f"i{i}", "set": "synthetic", "category": "single", "sheet": "s", "instruction": "x",
            "labels": {k: labels.get(k, 0) for k in KINDS}, "truth": []}


def test_prf_counts():
    out = lab.prf([(True, True), (True, False), (False, True), (False, False)])
    assert (out["p"], out["r"], out["tp"], out["fp"], out["fn"], out["n"]) == (0.5, 0.5, 1, 1, 1, 4)
    assert lab.prf([(False, False)])["p"] is None


def test_tag_table_and_band():
    items = [_item(1, value=1), _item(2), _item(3, value=1)]
    scores = {"i1": {k: 0.9 if k == "value" else 0.1 for k in KINDS},
              "i2": {k: 0.4 if k == "value" else 0.1 for k in KINDS},
              "i3": {k: 0.45 for k in KINDS}}
    t = lab.tag_table(items, scores, thresholds=(0.4, 0.5))
    assert t["value"][0.5]["tp"] == 1 and t["value"][0.5]["fn"] == 1
    assert t["value"][0.4]["fp"] == 1 and t["value"][0.4]["tp"] == 2
    assert lab.band(items, scores, 0.35, 0.5)["value"] == {"pos": 1, "neg": 1}


def test_match_ledger_layout_card_and_style():
    rec = {"kind": "value", "action": "ledger", "key": "width", "choice": {"need": "not_needed"}, "op": None}
    assert lab.match(rec, {"kind": "value", "key": "Width", "choice": {"need": "not_needed"}})
    assert not lab.match(rec, {"kind": "value", "key": "Width", "choice": {"need": "every"}})
    lay = {"kind": "layout", "action": "edit", "key": "", "choice": None,
           "op": {"op": "rename_paragraph", "paragraph": "Upper", "to": "Top"}}
    assert lab.match(lay, {"kind": "layout", "op": {"op": "rename_paragraph", "paragraph": "upper", "to": "Top."}})
    card = {"kind": "normal", "action": "card", "key": "k", "choice": {"text": "x"}, "op": None}
    assert lab.match(card, {"kind": "normal", "expect": "card"}) and not lab.match(card, {"kind": "normal",
                                                                                          "key": "k", "choice": {"text": "x"}})
    assert lab.match({"kind": "style", "action": "style"}, {"kind": "style"})
    cond = "the dictation states no contrast agent was given"
    rec_c = {"kind": "concept", "action": "ledger", "key": "contrast", "op": None,
             "choice": {"use": True, "dictated": False, "default": "Contrast was given.",
                        "when_met": "No contrast was given.", "condition": cond}}
    assert lab.match(rec_c, {"kind": "concept", "key": "contrast", "choice": {
        "use": True, "default": "contrast was given", "when_met": "No contrast was given.", "condition": "not_given"}})
    assert not lab.match(rec_c, {"kind": "concept", "key": "contrast", "choice": {
        "use": True, "default": "Contrast was given.", "when_met": "No contrast was given.", "condition": "given"}})
    dictated = {"kind": "concept", "action": "ledger", "key": "comparison", "op": None,
                "choice": {"use": False, "dictated": True, "default": "", "when_met": "", "condition": ""}}
    assert lab.match(dictated, {"kind": "concept", "key": "comparison", "choice": {"use": False, "dictated": True}})


def test_score_changes_counts_correct_missing_extra_cards_and_invented():
    truth = [{"kind": "value", "key": "Width", "choice": {"need": "not_needed"}},
             {"kind": "fixed", "key": "A.", "choice": {"keep": "remove"}}]
    recs = [{"kind": "value", "action": "ledger", "key": "Width", "choice": {"need": "not_needed"}},
            {"kind": "normal", "action": "ledger", "key": "P :: x", "choice": {"text": ""}},
            {"kind": "fixed", "action": "card", "key": "A.", "choice": {"keep": "remove"}, "invented": True}]
    assert lab.score_changes(truth, recs) == {"truth": 2, "correct": 1, "missing": 1, "extra_applied": 1, "cards": 1,
                                              "rejected": 0, "asked": 0, "invented": 1}


def test_unrelated_changes_counts_lines_outside_the_touched_parts():
    edited = ROUTER_SHEET.replace('NORMAL [alpha] "Alpha is normal."', 'NORMAL [alpha] "Alpha is fine."')
    assert lab.unrelated_changes(ROUTER_SHEET, edited, ["Upper"]) == 0
    assert lab.unrelated_changes(ROUTER_SHEET, edited, ["Lower"]) == 2


def test_unsure_counts_how_many_band_decisions_were_wrong():
    truth = [{"kind": "value", "key": "Width", "choice": {"need": "not_needed"}}]
    recs = [{"kind": "value", "action": "ledger", "key": "Width", "choice": {"need": "not_needed"}, "route": "llm_unsure"},
            {"kind": "normal", "action": "ledger", "key": "P :: x", "choice": {"text": ""}, "route": "llm_unsure"},
            {"kind": "fixed", "action": "ledger", "key": "A.", "choice": {"keep": "remove"}, "route": ""}]
    assert lab.unsure_counts(recs, truth) == {"unsure": 2, "unsure_wrong": 1}


def test_load_items_requires_every_label(tmp_path):
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "a.json").write_text(json.dumps({**_item(1), "labels": {"value": 1}}))
    with pytest.raises(ValueError):
        lab.load_items(tmp_path)


def test_md_table():
    assert lab.md_table(["a", "b"], [[1, None]]) == "| a | b |\n|---|---|\n| 1 | – |"


def test_habit_vs_normal_confusion_placeholder():
    """Item 5 (findings-triggered rows) later: how often a habit instruction is read as a normal-finding change."""
    items = [{**_item(1, normal=0), "category": "habit"}, {**_item(2, normal=1), "category": "habit"},
             {**_item(3, normal=1), "category": "single"}]
    scores = {"i1": {k: 0.8 if k == "normal" else 0.1 for k in KINDS},
              "i2": {k: 0.2 for k in KINDS}, "i3": {k: 0.9 for k in KINDS}}
    assert lab.habit_confusion(items, scores) == {"habit_items": 2, "tagged_normal": 1, "labelled_normal": 1,
                                                  "tagged_normal_but_not_labelled": 1}


def test_the_default_root_is_the_private_lab_folder():
    assert str(lab.DEFAULT_ROOT).endswith("Code/rr-template-conversion-private/synthetic/chat_router")


def test_report_tag_includes_the_unsure_rate_and_the_habit_placeholder(tmp_path):
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i1.json").write_text(json.dumps({**_item(1, value=1), "category": "habit"}))
    run = tmp_path / "runs" / "tag" / "run1"
    run.mkdir(parents=True)
    (run / "i1.json").write_text(json.dumps({"id": "i1", "scores": {k: 0.4 for k in KINDS}, "ms": 5}))
    text = lab.report_tag(tmp_path, [1])
    assert "unsure band" in text and "items with any kind in the unsure band: 1/1" in text
    assert "habit vs normal (item 5 placeholder)" in text
