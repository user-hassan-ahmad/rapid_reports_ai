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


# --- review fixes (spec §7–§8) ---------------------------------------------------------------

import asyncio  # noqa: E402


def _jev_stub(addressed=0.9, contra=0.0, raise_exc=None, seen=None):
    async def fn(by_state):
        if seen is not None:
            seen.append(by_state)
        if raise_exc:
            raise raise_exc
        out = {}
        for qs in by_state.values():
            for k in qs:
                out[k] = {"noul": addressed if k == "addressed" else contra}
        return out, {}, None
    return fn


CASE = {"scan": "CT", "dictation": "12 mm cyst left kidney", "history": "", "report": REPORT}
FIX = dict(edit_mode="replace", edit_find="a cyst", edit_replace="a 12 mm cyst")


def test_verify_low_addressed_fails_not_addressed():
    v = asyncio.run(J.verify(CASE, J_(**FIX, probe="Is the size given?"), jev_fn=_jev_stub(addressed=0.3)))
    assert v["code"] is False and "not_addressed" in v["failed"] and v["unconfirmed"] is False
    v = asyncio.run(J.verify(CASE, J_(**FIX, probe="Is the size given?"), jev_fn=_jev_stub(addressed=0.6)))
    assert v["code"] is True and v["unconfirmed"] is True


def test_verify_jev_error_fails_code():
    v = asyncio.run(J.verify(CASE, J_(**FIX, probe="p"), jev_fn=_jev_stub(raise_exc=RuntimeError("boom"))))
    assert v["code"] is False and "jev_error" in v["failed"] and "boom" in v["error"]


def test_verify_edit_without_probe_is_unconfirmed():
    v = asyncio.run(J.verify(CASE, J_(**FIX), jev_fn=_jev_stub()))
    assert v["code"] is True and v["unconfirmed"] is True


def test_verify_remove_skips_contradiction():
    seen = []
    j = J_(kind="contradicted", edit_mode="remove", edit_find="The liver is normal. ", probe="p")
    v = asyncio.run(J.verify(CASE, j, jev_fn=_jev_stub(seen=seen)))
    assert v["contra"] is None and v["addressed"] == 0.9
    assert all("contra" not in qs for st in seen for qs in st.values())


def test_guard_outside_section():
    j = J_(**FIX, edit_section="Impression")
    assert "outside_section" in J.guard_failures(REPORT, j, CASE["dictation"], "")
    j = J_(**FIX, edit_section="FINDINGS")
    assert "outside_section" not in J.guard_failures(REPORT, j, CASE["dictation"], "")
    j = J_(edit_mode="replace", edit_find="a cyst", edit_replace="a 12 mm cyst", edit_section="Impression")
    assert "outside_section" not in J.guard_failures("The liver is normal. There is a cyst.", j, CASE["dictation"], "")


def test_guard_duplicate_insert():
    j = J_(edit_mode="insert", edit_after="The liver is normal.", edit_replace="There is a cyst in the left kidney.")
    assert "duplicate" in J.guard_failures(REPORT, j, "cyst left kidney", "")
    j = J_(edit_mode="insert", edit_after="The liver is normal.", edit_replace="The spleen is normal.")
    assert "duplicate" not in J.guard_failures(REPORT, j, "", "")


def test_guard_extra_source_grounds_additions():
    j = J_(edit_mode="upgrade", edit_find="Left renal cyst.", edit_replace="Left renal cyst. Follow-up in 6 months.")
    assert "ungrounded_number" in J.guard_failures(REPORT, j, "cyst left kidney", "")
    assert "ungrounded_number" not in J.guard_failures(REPORT, j, "cyst left kidney", "", extra_source="timing: 6 months")


def test_verify_group_additions_supplies_extra_source():
    j = J_(edit_mode="upgrade", edit_find="Left renal cyst.", edit_replace="Left renal cyst. Follow-up in 6 months.")
    case = {**CASE, "dictation": "cyst left kidney"}
    group = [{"lane": "additions", "kind": "follow_up", "evidence": {"timing": "6 months"}}]
    v = asyncio.run(J.verify(case, j, group=group, jev_fn=_jev_stub()))
    assert "ungrounded_number" not in v["failed"]
    group = [{"lane": "coverage", "kind": "partial", "evidence": {"timing": "6 months"}}]
    v = asyncio.run(J.verify(case, j, group=group, jev_fn=_jev_stub()))
    assert "ungrounded_number" in v["failed"]


def test_q_conveys_not_exported():
    assert "Q_CONVEYS" not in J.__all__ and not hasattr(J, "Q_CONVEYS")


def test_remove_whole_line_leaves_no_blank_line_and_keeps_other_spacing():
    rep = "FINDINGS:\nThe liver is normal.\nThe  spleen is normal.\nIMPRESSION:\nNormal."
    j = J_(kind="contradicted", edit_mode="remove", edit_find="The liver is normal.")
    assert J.apply_edit(rep, j) == "FINDINGS:\nThe  spleen is normal.\nIMPRESSION:\nNormal."
    rep = "FINDINGS:\nA.  B. C is here. D is there.\nIMPRESSION:\nNormal."
    j = J_(kind="contradicted", edit_mode="remove", edit_find="C is here.")
    assert J.apply_edit(rep, j) == "FINDINGS:\nA.  B. D is there.\nIMPRESSION:\nNormal."
    j = J_(kind="contradicted", edit_mode="remove", edit_find="D is there.")
    assert J.apply_edit(rep, j) == "FINDINGS:\nA.  B. C is here.\nIMPRESSION:\nNormal."


def test_remove_mid_sentence_collapses_seam_double_space():
    rep = "FINDINGS:\nOne. Two is here. Three."
    j = J_(kind="contradicted", edit_mode="remove", edit_find="Two is here.")
    assert J.apply_edit(rep, j) == "FINDINGS:\nOne. Three."


def test_insert_after_heading_goes_on_next_line():
    j = J_(edit_mode="insert", edit_after="FINDINGS:", edit_replace="The spleen is normal.")
    assert J.apply_edit(REPORT, j).startswith("FINDINGS:\nThe spleen is normal.\nThe liver is normal.")


def test_insert_anchor_trailing_space_and_partial_word():
    j = J_(edit_mode="insert", edit_after="The liver is normal. ", edit_replace="The spleen is normal.")
    assert "The liver is normal. The spleen is normal. There is a cyst" in J.apply_edit(REPORT, j)
    j = J_(edit_mode="insert", edit_after="The liver is norm", edit_replace="X.")
    assert J.apply_edit(REPORT, j) is None


def test_changed_sentence_by_position():
    rep = "FINDINGS:\nA 12 mm nodule in the lung. The cyst measures 10 mm."
    j = J_(edit_mode="replace", edit_find="10 mm", edit_replace="12 mm")
    after = J.apply_edit(rep, j)
    assert J.changed_sentence(rep, after, j) == "The cyst measures 12 mm."
    j = J_(edit_mode="insert", edit_after="A 12 mm nodule in the lung.", edit_replace="No effusion.")
    after = J.apply_edit(rep, j)
    assert J.changed_sentence(rep, after, j) == "No effusion."


def test_side_bilateral_grounding():
    rep = "FINDINGS:\nThere are renal cysts."
    j = J_(edit_mode="replace", edit_find="renal cysts", edit_replace="bilateral renal cysts")
    assert "ungrounded_side" not in J.guard_failures(rep, j, "cysts in both kidneys", "")
    assert "ungrounded_side" not in J.guard_failures(rep, j, "left and right renal cysts", "")
    assert "ungrounded_side" in J.guard_failures(rep, j, "left renal cyst", "")


def test_negation_moved_to_other_phrase_fails():
    rep = "FINDINGS:\nNo free fluid. The liver is normal."
    j = J_(edit_mode="replace", edit_find="No free fluid.", edit_replace="Small free fluid, no collection.")
    assert "drops_negation" in J.guard_failures(rep, j, "small free fluid no collection", "")
    j = J_(edit_mode="replace", edit_find="No free fluid.", edit_replace="No free fluid or collection.")
    assert "drops_negation" not in J.guard_failures(rep, j, "no free fluid or collection", "")


def test_judge_and_verify_fallback_dict(monkeypatch):
    class ValidationError(Exception):
        pass

    async def bad_qwen(*a, **k):
        raise ValidationError("bad")

    async def bad_transport(*a, **k):
        raise ConnectionError("down")

    real = J.adjudicate

    async def adj(case, group, system=None, qwen_fn=None):
        return await real(case, group, system, qwen_fn=state["fn"])

    state = {"fn": bad_qwen}
    monkeypatch.setattr(J, "adjudicate", adj)
    out = asyncio.run(J.judge_and_verify(CASE, [{"kind": "partial"}], asyncio.Semaphore(1)))
    assert set(J.Judgement.model_fields) <= set(out)
    assert out["cls"] == "minor" and out["kind"] == "partial" and out["edit_mode"] == "none"
    assert out["error_kind"] == "validation" and out["verified"] is None and "usage" in out
    state["fn"] = bad_transport
    out = asyncio.run(J.judge_and_verify(CASE, [{}], asyncio.Semaphore(1)))
    assert out["error_kind"] == "transport" and out["kind"] == "unknown"


def test_prompt_keeps_impression_brief():
    assert "never add restated findings or a second recommendation line" in J.prompt()


def test_render_candidate_names_kind_not_lane_as_kind():
    s = J.render_candidate({"lane": "coverage", "kind": "partial", "detector": "d", "line": "x", "evidence": {}})
    assert 'Flag kind "partial"' in s and "coverage/" not in s
