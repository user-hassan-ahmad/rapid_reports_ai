import pytest  # noqa: F401

from rapid_reports_ai.scripts.review_labs import judgement as J

REPORT = "FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst."


def J_(**kw):
    base = dict(cls="action", kind="partial", label="l", reason="r", edit_mode="none",
                edit_find=None, edit_replace=None, edit_after=None, edit_section=None, probe=None)
    base.update(kw)
    return J.Judgement(**base)


def test_judgement_is_flat():
    for name, f in J.Judgement.model_fields.items():
        assert f.annotation not in (dict, list), name


def test_apply_replace_and_remove_and_insert():
    j = J_(edit_mode="replace", edit_find="a cyst", edit_replace="a 12 mm cyst")
    assert "a 12 mm cyst in the left kidney" in J.apply_edit(REPORT, j)
    j = J_(edit_mode="remove", edit_find="The liver is normal. ")
    assert "liver" not in J.apply_edit(REPORT, j)
    j = J_(edit_mode="insert", edit_after="The liver is normal.", edit_replace="The spleen is normal.")
    assert "The liver is normal. The spleen is normal. There is a cyst" in J.apply_edit(REPORT, j)


def test_apply_returns_none_when_find_not_unique_or_absent():
    rep = "The liver is normal. The spleen is normal."
    assert J.apply_edit(rep, J_(edit_mode="replace", edit_find="normal", edit_replace="x")) is None
    assert J.apply_edit(REPORT, J_(edit_mode="replace", edit_find="pancreas", edit_replace="x")) is None


def test_guards_grounding_numbers_and_side():
    j = J_(edit_mode="replace", edit_find="a cyst", edit_replace="a 12 mm cyst")
    assert "ungrounded_number" in J.guard_failures(REPORT, j, dictation="cyst left kidney", history="")
    assert J.guard_failures(REPORT, j, dictation="12 mm cyst left kidney", history="") == []
    j = J_(edit_mode="replace", edit_find="a cyst in the left kidney", edit_replace="a cyst in the right kidney")
    assert "ungrounded_side" in J.guard_failures(REPORT, j, dictation="cyst left kidney", history="")


def test_guards_negation_drop():
    rep = "FINDINGS:\nNo free fluid. The liver is normal."
    j = J_(edit_mode="replace", edit_find="No free fluid.", edit_replace="Free fluid.")
    assert "drops_negation" in J.guard_failures(rep, j, dictation="free fluid", history="")


def test_guards_remove_only_for_contradicted():
    j = J_(kind="partial", edit_mode="remove", edit_find="The liver is normal.")
    assert "remove_not_allowed" in J.guard_failures(REPORT, j, dictation="", history="")
    j = J_(kind="contradicted", edit_mode="remove", edit_find="The liver is normal.")
    assert "remove_not_allowed" not in J.guard_failures(REPORT, j, dictation="", history="")


def test_render_candidate_marks_unsure_without_leaning():
    c = {"lane": "coverage", "kind": "partial", "detector": "jev.classify_first", "line": "Cyst left kidney",
         "evidence": {"jev_unsure": {"question": "classify_first", "band": "0.4-0.6"}, "missing_detail": "12 mm"}}
    s = J.render_candidate(c)
    assert "unsure" in s and "classify_first" in s and "0.4" not in s and "12 mm" in s
