from rapid_reports_ai.review_engine import engine as E
from rapid_reports_ai.review_engine import live


def _inp(review=None, removed=None):
    cand = {"content": "FINDINGS\nLiver normal. 12 mm cyst.", "removed": removed or [], "stack": True,
            "quality_check": {"review": review or []}}
    return E.input_from_parts("r1", "auto", {"variables": {"FINDINGS": "Liver normal."}}, cand, None)


def test_input_carries_removed_and_plain_findings():
    inp = _inp(removed=["No ascites."])
    assert inp.removed == ["No ascites."] and inp.artifacts.dictated_findings == "Liver normal."


def test_removed_match_is_normalised_exact():
    assert E._is_removed("no ascites", ["No ascites."]) is True
    assert E._is_removed("  No   ascites. ", ["No ascites."]) is True
    assert E._is_removed("Liver normal.", ["No ascites."]) is False


def test_check_flags_become_open_rail_items():
    inp = _inp(review=[
        {"kind": "removed_asserted", "severity": "high", "text": "There is no free fluid.",
         "message": "Asserts a removed sentence; not auto-removed"},
        {"kind": "undictated_number", "text": "12", "sentence": "12 mm cyst."},
    ])
    items = live.check_flag_items(inp, "run1")
    assert [i.kind for i in items] == ["removed_asserted", "undictated_number"]
    assert all(i.status == "open" and i.edit is None for i in items)
    assert items[0].cls == "action" and items[0].reason == "Asserts a removed sentence; not auto-removed"
    assert items[1].cls == "info" and "12" in items[1].label
    assert items[1].anchor is not None and inp.artifacts.report[items[1].anchor.start:items[1].anchor.end] == "12 mm cyst."


def test_check_flags_only_for_stack_reports_and_known_kinds():
    review = [{"kind": "partial", "line": "x"}, {"kind": "undictated_number", "text": "12", "sentence": "12 mm cyst."},
              {"kind": "undictated_number", "text": "12", "sentence": "12 mm cyst."}]
    cand = {"content": "FINDINGS\n12 mm cyst.", "quality_check": {"review": review}}
    plain_inp = E.input_from_parts("r1", "auto", {"variables": {"FINDINGS": "x"}}, cand, None)
    assert live.check_flag_items(plain_inp, "run") == []
    stack_inp = E.input_from_parts("r1", "auto", {"variables": {"FINDINGS": "x"}}, {**cand, "stack": True}, None)
    assert [i.kind for i in live.check_flag_items(stack_inp, "run")] == ["undictated_number"]
