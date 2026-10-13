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
                                                  "tagged_normal_but_not_labelled": 1, "habit_guard_yes": 0}
    scores["i1"]["habit"] = 0.9
    assert lab.habit_confusion(items, scores)["habit_guard_yes"] == 1


def test_the_default_root_is_the_private_lab_folder():
    assert str(lab.DEFAULT_ROOT).endswith("Code/rr-template-conversion-private/synthetic/chat_router")


def test_report_tag_includes_the_near_miss_rate_and_the_habit_placeholder(tmp_path):
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i1.json").write_text(json.dumps({**_item(1, value=1), "category": "habit"}))
    run = tmp_path / "runs" / "tag" / "run1"
    run.mkdir(parents=True)
    (run / "i1.json").write_text(json.dumps({"id": "i1", "scores": {k: 0.4 for k in KINDS}, "ms": 5}))
    text = lab.report_tag(tmp_path, [1])
    assert "near-miss band [0.35, 0.5), not routed" in text and "items with any kind in the near-miss band: 1/1" in text
    assert "habit vs normal (item 5 placeholder)" in text


# ── head-to-head arms: arm 1 (route_turn) vs arm 2 (propose, verify, apply) ─────────────────────────────────────
def test_touches_for_names_the_parts_a_truth_may_change():
    from tests.template_sheet_fixtures import ROUTER_SHEET
    truth = [{"kind": "value", "key": "Width", "choice": {"need": "not_needed"}},
             {"kind": "fixed", "key": "Axial images were acquired.", "choice": {"keep": "remove"}},
             {"kind": "normal", "key": "Upper :: alpha", "choice": {"text": ""}},
             {"kind": "layout", "op": {"op": "rename_paragraph", "paragraph": "Lower", "to": "Bottom"}}]
    assert lab.touches_for(truth, ROUTER_SHEET) == ["Bottom", "Lower", "Report Structure", "Report-wide", "Technique",
                                                    "Upper"]
    assert lab.touches_for([{"kind": "style"}], ROUTER_SHEET) is None          # prose anywhere: not counted
    assert lab.touches_for([{"kind": "concept", "key": "comparison", "choice": {}}], ROUTER_SHEET) is None


def test_arm_record_scores_a_turn_against_the_truth():
    from rapid_reports_ai import chat_router as R
    t = R.Turn("S2", [], True, "r", records=[
        {"type": "ledger", "change": {"kind": "value", "key": "Width", "new": {"need": "not_needed"}}, "claim": "W"},
        {"type": "ledger", "change": {"kind": "value", "key": "Depth", "new": {"need": "not_needed"}}, "claim": "D"}],
        cards=[{"ledger_kind": "normal", "key": "k"}],
        evidence={"ms": 120, "changes": [{"invented": True}, {"invented": False}],
                  "screen": {"habit": 0.1, "undo": 0.2, "misfit": 0.3}})
    item = {"id": "i1", "set": "synthetic", "truth": [{"kind": "value", "key": "Width", "choice": {"need": "not_needed"}}]}
    rec = lab.arm_record(item, t, qwen_calls=2, start="S", touches=None)
    assert rec == {"id": "i1", "set": "synthetic", "fallback": None, "applied_claims": ["W", "D"], "cards": 1,
                   "correct": 1, "unrequested": 1, "missing": 0, "invented": 1, "qwen_calls": 2, "ms": 120,
                   "unrelated": None, "style_checks": [], "state_correct": 1, "state_scored": 1,
                   "screen": {"habit": 0.1, "undo": 0.2, "misfit": 0.3}}
    fb = lab.arm_record(item, None, qwen_calls=0, start="S", touches=None, fallback="no_tag")
    assert fb["fallback"] == "no_tag" and fb["applied_claims"] == [] and fb["missing"] == 1


def test_arm_summary_totals_and_rates():
    rows = [{"id": "a", "set": "synthetic", "fallback": None, "applied_claims": ["x"], "cards": 1, "correct": 1,
             "unrequested": 0, "missing": 0, "invented": 0, "qwen_calls": 1, "ms": 100, "unrelated": 0},
            {"id": "b", "set": "synthetic", "fallback": "no_tag", "applied_claims": [], "cards": 0, "correct": 0,
             "unrequested": 2, "missing": 1, "invented": 1, "qwen_calls": 3, "ms": 300, "unrelated": None}]
    rows[0].update(state_correct=1, state_scored=1)
    rows[1].update(state_correct=0, state_scored=2)
    assert lab.arm_summary(rows) == {"items": 2, "fallbacks": 1, "applied": 1, "correct": 1, "unrequested": 2,
                                     "missing": 1, "state_correct": 1, "state_scored": 3, "cards": 1,
                                     "card_rate": 0.5, "invented": 1, "qwen_calls_mean": 2.0, "ms_p50": 200.0,
                                     "ms_p90": 280.0, "unrelated": 0}


def test_qwen_calls_are_counted_per_item_task():
    import asyncio
    from rapid_reports_ai import enhancement_utils as eu

    async def main():
        async def fake(**kw):
            return None
        async def item():
            with lab.counting() as n:
                await eu._run_agent_with_model(model_name="m")
                await asyncio.gather(eu._run_agent_with_model(model_name="m"), eu._run_agent_with_model(model_name="m"))
                return n[0]
        orig = eu._run_agent_with_model
        eu._run_agent_with_model = fake
        try:
            with lab.patched_counter():
                return await asyncio.gather(item(), item())
        finally:
            eu._run_agent_with_model = orig
    assert asyncio.run(main()) == [3, 3]



def test_the_edit_check_is_scored_against_hand_labels():
    rows = {"i1": {"arms": {"arm1": {"style_checks": [{"block": "b4", "edit_score": 0.9}, {"block": "b1", "edit_score": 0.2}]},
                            "arm2": {"style_checks": [{"block": "b4", "edit_score": 0.7}]}}}}
    labels = {"i1:arm1:b4": 1, "i1:arm1:b1": 1, "i1:arm2:b4": 0}
    out = lab.edit_check_prf(rows, labels)
    assert (out["tp"], out["fp"], out["fn"], out["n"]) == (1, 1, 1, 3)      # honest = edit_score >= 0.5
    assert lab.edit_check_prf(rows, {})["n"] == 0



# ── three arms: arm 0 (today's refine), arm 1 (tag-then-route, reference), arm 2 (the hybrid) ───────────────────
def test_the_truth_is_scored_on_the_final_sheet_and_ledger():
    from tests.template_sheet_fixtures import ROUTER_SHEET
    end = ROUTER_SHEET.replace('LIST_MISSING ["Width" | "Depth"]', 'LIST_MISSING ["Depth"]').replace(
        'FIXED "No previous imaging available."\n', "").replace("## Paragraph: Lower (FINDINGS)", "## Paragraph: Bottom (FINDINGS)")
    truth = [{"kind": "value", "key": "Width", "choice": {"need": "not_needed"}},
             {"kind": "fixed", "key": "No previous imaging available.", "choice": {"keep": "remove"}},
             {"kind": "normal", "key": "Upper :: alpha", "choice": {"text": "Alpha is fine."}},
             {"kind": "layout", "op": {"op": "rename_paragraph", "paragraph": "Lower", "to": "Bottom"}},
             {"kind": "style"}]
    assert lab.state_score(truth, end, []) == (3, 4)          # style is not scored; the normal was not changed
    assert lab.state_score([{"kind": "value", "key": "Width", "choice": {"need": "relevant"}}], ROUTER_SHEET,
                           [{"kind": "value", "key": "Width", "choice": {"need": "relevant"}}]) == (1, 1)


async def test_arm_0_is_todays_refine_through_the_save_function(monkeypatch):
    from rapid_reports_ai import template_sheet_save as S
    from tests.template_sheet_fixtures import ROUTER_SHEET

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": skill_sheet.replace('LIST_MISSING ["Width" | "Depth"]', 'LIST_MISSING ["Depth"]'),
                "response": "Done.", "behavioral_claim": "c"}

    async def none(structure, sheet):
        return []
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    monkeypatch.setattr(S, "check_units", none)
    t = await lab.refine_turn(ROUTER_SHEET, [], "drop width")
    assert t.applied and 'LIST_MISSING ["Depth"]' in t.sheet and t.records == [] and t.evidence["route"] == "refine"
    assert set(lab.ARMS) == {"arm0", "arm1", "arm2"}
