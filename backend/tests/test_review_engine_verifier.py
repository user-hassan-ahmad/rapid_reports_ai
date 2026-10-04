# tests/test_review_engine_verifier.py
"""Verifier (spec §8) and probe (spec §12.4): the fix is checked, never the reading.

The apply / guard / changed-sentence / verify tests are ported from tests/test_review_labs_judgement.py (binding
corrections 2–5), with types adapted to `Edit` / `ReviewItem`; the §9 removal and additions-grounding rules
(2026-10-04) are engine additions."""
import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.generation_artifacts import GenerationArtifacts
from rapid_reports_ai.report_review import quick_section_names
from rapid_reports_ai.review_engine import verifier as V
from rapid_reports_ai.review_engine.items import Candidate, Edit, ReviewInput, ReviewItem, Span

REPORT = "FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst."
SECTIONS = ["FINDINGS", "IMPRESSION"]


# Local copies of the shared fakes (tests/review_engine_fakes.py lands with Task 6).
def inp(report, dictation, history="", scan="CT abdomen", title=None):
    art = GenerationArtifacts(report=report, dictated_findings=dictation, sections=quick_section_names(report),
                              options=[], brief=None, quality_check=None)
    return ReviewInput(report_id="00000000-0000-0000-0000-000000000001", pathway="quick", artifacts=art,
                       clinical_history=history, scan_type=scan, study_title=title)


def jev(answers, seen=None):
    """Fake rc._jev: answers each asked qid present in `answers` ({qid: {"noul": x}})."""
    async def fake(state, qs):
        if seen is not None:
            seen.append((state, qs))
        return {k: answers[k] for k in qs if k in answers}
    return fake


def jev_stub(addressed=0.9, contra=0.0, raise_exc=None, seen=None):
    async def fake(state, qs):
        if seen is not None:
            seen.append((state, qs))
        if raise_exc:
            raise raise_exc
        return {k: {"noul": addressed if k == "addressed" else contra} for k in qs}
    return fake


@pytest.fixture(autouse=True)
def _no_live_models(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("unstubbed Jev call")
    monkeypatch.setattr(rc, "_jev", boom)


def item(edit, kind="partial", probe="The FINDINGS section states the size of the kidney lesion.", section="FINDINGS",
         lane="coverage", evidence=None):
    return ReviewItem(key="k", report_id="r", run_id="u", lane=lane, kind=kind, cls="action", edit=edit,
                      probe=probe, section=section, anchor=Span(start=0, end=1, text="x"), evidence=evidence)


def G(report, edit, kind="partial", d="", h="", **kw):
    return V.guard_failures(report, edit, kind, d, h, **kw)


R = lambda find, rep, **kw: Edit(mode="replace", find=find, replace=rep, **kw)   # noqa: E731


# ── apply_edit ──────────────────────────────────────────────────────────────
def test_apply_edit_modes():
    assert "a 14 mm cyst in the left kidney" in V.apply_edit(REPORT, R("a cyst", "a 14 mm cyst"), SECTIONS)
    assert "liver" not in V.apply_edit(REPORT, Edit(mode="remove", find="The liver is normal. "))
    assert "liver" not in V.apply_edit(REPORT, Edit(mode="remove", find="The liver is normal."), SECTIONS)
    out = V.apply_edit(REPORT, Edit(mode="insert", after="The liver is normal.", replace="The spleen is normal."))
    assert "The liver is normal. The spleen is normal. There is a cyst" in out
    out = V.apply_edit(REPORT, Edit(mode="insert", replace="Follow-up is suggested.", section="IMPRESSION"), SECTIONS)
    assert out == REPORT + " Follow-up is suggested."
    out = V.apply_edit(REPORT, Edit(mode="insert", replace="Spleen normal.", section="Findings"), SECTIONS)
    assert "There is a cyst in the left kidney. Spleen normal.\nIMPRESSION:" in out


def test_apply_returns_none_when_find_not_unique_or_absent():
    rep = "The liver is normal. The spleen is normal."
    assert V.apply_edit(rep, R("normal", "x")) is None
    assert V.apply_edit(REPORT, R("pancreas", "x")) is None
    assert V.apply_edit("normal normal", R("normal", "x"), []) is None
    assert V.apply_edit(REPORT, Edit(mode="insert", replace="X.", section="TECHNIQUE"), SECTIONS) is None


def test_append_to_empty_section_goes_on_next_line():
    rep = "FINDINGS:\nThe liver is normal.\nIMPRESSION:\n"
    out = V.apply_edit(rep, Edit(mode="insert", replace="Normal study.", section="IMPRESSION"), ["FINDINGS", "IMPRESSION"])
    assert out == "FINDINGS:\nThe liver is normal.\nIMPRESSION:\nNormal study.\n"


def test_remove_whole_line_leaves_no_blank_line_and_keeps_other_spacing():
    rep = "FINDINGS:\nThe liver is normal.\nThe  spleen is normal.\nIMPRESSION:\nNormal."
    assert V.apply_edit(rep, Edit(mode="remove", find="The liver is normal.")) == \
        "FINDINGS:\nThe  spleen is normal.\nIMPRESSION:\nNormal."
    rep = "FINDINGS:\nA.  B. C is here. D is there.\nIMPRESSION:\nNormal."
    assert V.apply_edit(rep, Edit(mode="remove", find="C is here.")) == "FINDINGS:\nA.  B. D is there.\nIMPRESSION:\nNormal."
    assert V.apply_edit(rep, Edit(mode="remove", find="D is there.")) == "FINDINGS:\nA.  B. C is here.\nIMPRESSION:\nNormal."


def test_remove_mid_sentence_collapses_seam_double_space():
    assert V.apply_edit("FINDINGS:\nOne. Two is here. Three.", Edit(mode="remove", find="Two is here.")) == \
        "FINDINGS:\nOne. Three."


def test_remove_rejects_mid_word_find():
    rep = "FINDINGS:\nThe liver is normal. No gallstones. The spleen is normal."
    assert V.apply_edit(rep, Edit(mode="remove", find="is normal. No gall")) is None
    assert V.apply_edit(rep, Edit(mode="remove", find="iver is normal. ")) is None
    assert V.apply_edit(rep, Edit(mode="remove", find="No gallstones. ")) is not None


def test_insert_after_heading_goes_on_next_line():
    out = V.apply_edit(REPORT, Edit(mode="insert", after="FINDINGS:", replace="The spleen is normal."))
    assert out.startswith("FINDINGS:\nThe spleen is normal.\nThe liver is normal.")
    rep = "Findings:\nThe liver is normal."
    out = V.apply_edit(rep, Edit(mode="insert", after="Findings:", replace="X."), ["Findings"])
    assert out == "Findings:\nX.\nThe liver is normal."


def test_insert_anchor_trailing_space_and_partial_word():
    out = V.apply_edit(REPORT, Edit(mode="insert", after="The liver is normal. ", replace="The spleen is normal."))
    assert "The liver is normal. The spleen is normal. There is a cyst" in out
    assert V.apply_edit(REPORT, Edit(mode="insert", after="The liver is norm", replace="X.")) is None


# ── guards ──────────────────────────────────────────────────────────────────
def test_guards_grounding_numbers_and_side():
    assert "ungrounded_number" in G(REPORT, R("a cyst", "a 12 mm cyst"), d="cyst left kidney")
    assert G(REPORT, R("a cyst", "a 12 mm cyst"), d="12 mm cyst left kidney") == []
    e = R("a cyst in the left kidney", "a cyst in the right kidney")
    assert "ungrounded_side" in G(REPORT, e, d="cyst left kidney")


def test_side_bilateral_grounding():
    rep = "FINDINGS:\nThere are renal cysts."
    e = R("renal cysts", "bilateral renal cysts")
    assert "ungrounded_side" not in G(rep, e, "differs", "cysts in both kidneys")
    assert "ungrounded_side" not in G(rep, e, "differs", "left and right renal cysts")
    assert "ungrounded_side" in G(rep, e, "differs", "left renal cyst")


def test_guards_negation_drop():
    rep = "FINDINGS:\nNo free fluid. The liver is normal."
    assert "drops_negation" in G(rep, R("No free fluid.", "Free fluid."), "differs", "free fluid", sections=["FINDINGS"])


def test_negation_moved_to_other_phrase_fails():
    rep = "FINDINGS:\nNo free fluid. The liver is normal."
    assert "drops_negation" in G(rep, R("No free fluid.", "Small free fluid, no collection."),
                                 d="small free fluid no collection")
    assert "drops_negation" not in G(rep, R("No free fluid.", "No free fluid or collection."),
                                     d="no free fluid or collection")


def _drops(old, new, rep=None, kind="differs"):
    rep = rep or f"FINDINGS:\n{old} The heart is normal."
    return "drops_negation" in G(rep, R(old, new), kind, "left pneumothorax")


def test_negation_list_items_each_checked():
    assert _drops("No pneumothorax or effusion.", "Pneumothorax, no effusion.")
    assert _drops("No pneumothorax or effusion.", "Small left pneumothorax. No effusion.")
    assert _drops("No pneumothorax or effusion.", "No effusion. Pneumothorax.")
    assert not _drops("No pneumothorax or effusion.", "No pneumothorax. No pleural effusion.")
    assert not _drops("No pneumothorax, effusion or consolidation.", "No pneumothorax, effusion or consolidation.")


def test_post_positioned_negators_count():
    assert not _drops("No free fluid is seen.", "Free fluid is not seen.")
    assert not _drops("There is no hydronephrosis.", "Hydronephrosis is absent.")
    assert not _drops("The liver is not enlarged.", "The liver is normal in size and not enlarged.")
    assert _drops("No free fluid is seen.", "Free fluid is seen. Collection is not seen.")


def test_contradicted_list_item_drop_is_exempt_from_drops_negation():
    # a negative-list item dropped from its line arrives as a line-level replace
    assert not _drops("No pneumothorax or effusion.", "No effusion.", kind="contradicted")
    assert not _drops("No pneumothorax.", "Small pneumothorax.", kind="contradicted")
    assert _drops("No pneumothorax.", "Small pneumothorax.", kind="partial")


def test_guards_remove_only_for_contradicted_or_removed():
    e = Edit(mode="remove", find="The liver is normal.")
    assert "remove_not_allowed" in G(REPORT, e, "partial")
    assert "remove_not_allowed" in G(REPORT, e, "unsupported")
    assert G(REPORT, e, "contradicted") == []
    assert G(REPORT, e, "removed") == []


def test_remove_never_removes_dictated_text():
    rep = "FINDINGS:\nNo free fluid. The liver is normal."
    e = Edit(mode="remove", find="No free fluid.")
    assert "remove_dictated" in G(rep, e, "contradicted", "- No free fluid\n- 14 mm cyst left kidney")
    assert "remove_dictated" in G(rep, e, "removed", "No free fluid in the abdomen or pelvis.")
    # a generated negative contradicted by a dictated positive is removable
    assert G(rep, e, "contradicted", "- Small volume free fluid in the pelvis") == []
    # same for a dropped list item (line-level replace)
    rep = "FINDINGS:\nNo free fluid or collection. The liver is normal."
    e = R("No free fluid or collection.", "No collection.")
    assert G(rep, e, "contradicted", "Free fluid in the pelvis.") == []
    assert "remove_dictated" in G(rep, e, "contradicted", "No free fluid or collection.")


def test_guard_outside_section():
    fix = dict(find="a cyst", replace="a 12 mm cyst")
    assert "outside_section" in G(REPORT, Edit(mode="replace", section="Impression", **fix), d="12 mm cyst left kidney")
    assert "outside_section" not in G(REPORT, Edit(mode="replace", section="FINDINGS", **fix), d="12 mm cyst left kidney")
    assert "outside_section" not in G("The liver is normal. There is a cyst.", Edit(mode="replace", section="Impression",
                                                                                   **fix), d="12 mm cyst left kidney")
    # the edit names no section: the item's section is used
    e = R("Left renal cyst.", "Left renal cyst, 14 mm.")
    assert "outside_section" in G(REPORT, e, d="14 mm left renal cyst", sections=SECTIONS, item_section="FINDINGS")
    assert "outside_section" not in G(REPORT, e, d="14 mm left renal cyst", sections=SECTIONS, item_section="IMPRESSION")


def test_guard_duplicate_insert():
    e = Edit(mode="insert", after="The liver is normal.", replace="There is a cyst in the left kidney.")
    assert "duplicate" in G(REPORT, e, d="cyst left kidney")
    e = Edit(mode="insert", after="The liver is normal.", replace="The spleen is normal.")
    assert "duplicate" not in G(REPORT, e)
    e = Edit(mode="insert", replace="There is a cyst in the left kidney.", section="FINDINGS")
    assert "duplicate" in G(REPORT, e, d="cyst left kidney", sections=SECTIONS)


def test_duplicate_guard_excludes_every_sentence_of_the_find():
    rep = "FINDINGS:\nThe spleen is normal. Kidneys normal. The liver is normal."
    e = R("The spleen is normal. Kidneys normal.", "Kidneys normal.")
    assert "duplicate" not in G(rep, e, "differs")
    e = R("The spleen is normal. Kidneys normal.", "The liver is normal.")
    assert "duplicate" in G(rep, e, "differs")


def test_guard_extra_source_grounds_additions():
    e = Edit(mode="upgrade", find="Left renal cyst.", replace="Left renal cyst. Follow-up in 6 months.")
    assert "ungrounded_number" in G(REPORT, e, d="cyst left kidney")
    assert "ungrounded_number" not in G(REPORT, e, d="cyst left kidney", extra_source="timing: 6 months")


def test_additions_guard_new_negative_fails():
    e = Edit(mode="insert", after="Left renal cyst.", replace="No hydronephrosis.")
    assert "additions_new_content" in G(REPORT, e, "option", "cyst left kidney", additions=True)
    assert "additions_new_content" not in G(REPORT, e, "option", "cyst left kidney")


def test_additions_guard_grade_from_evidence_passes():
    e = Edit(mode="upgrade", find="Left renal cyst.", replace="Left renal cyst, Bosniak 2.")
    assert G(REPORT, e, "grade", "cyst left kidney", extra_source="system: Bosniak\ngrade: 2", additions=True) == []


def test_additions_guard_new_content_word_fails():
    e = Edit(mode="upgrade", find="Left renal cyst.", replace="Left renal cyst with thickened septation, Bosniak 3.")
    assert "additions_new_content" in G(REPORT, e, "grade", "cyst left kidney", extra_source="system: Bosniak\ngrade: 3",
                                        additions=True)


def test_additions_guard_management_fails():
    e = Edit(mode="upgrade", find="Left renal cyst.", replace="Left renal cyst. Refer to urology for surgical treatment.")
    assert "management" in G(REPORT, e, "follow_up", "cyst left kidney", additions=True)
    assert "management" not in G(REPORT, e, "follow_up", "cyst left kidney")
    ok = Edit(mode="upgrade", find="Left renal cyst.", replace="Left renal cyst. Refer to radiology for follow-up.")
    assert "management" not in G(REPORT, ok, "follow_up", "cyst left kidney", additions=True)


def test_extra_source_only_for_additions_and_keeps_grade_zero():
    add = item(None, lane="additions", evidence={"system": "CAD-RADS", "grade": 0})
    assert "0" in V._extra_source(add).split("\n")
    assert V._extra_source(item(None, lane="additions", evidence={"grade": "", "system": None})) == ""
    assert V._extra_source(item(None, lane="coverage", evidence={"timing": "6 months"})) == ""
    grp = [Candidate(lane="additions", kind="follow_up", evidence={"timing": "6 months"}, detector="s4")]
    assert V._extra_source(item(None, lane="coverage"), grp) == "6 months"


# ── changed_sentence ────────────────────────────────────────────────────────
def test_changed_sentence_by_position():
    rep = "FINDINGS:\nA 12 mm nodule in the lung. The cyst measures 10 mm."
    e = R("10 mm", "12 mm")
    assert V.changed_sentence(rep, V.apply_edit(rep, e), e) == "The cyst measures 12 mm."
    e = Edit(mode="insert", after="A 12 mm nodule in the lung.", replace="No effusion.")
    assert V.changed_sentence(rep, V.apply_edit(rep, e), e) == "No effusion."


REP2 = "FINDINGS:\nThe liver is normal. No gallstones.\n\nIMPRESSION:\nNormal.\n"


def test_changed_sentence_returns_all_sentences_of_new_text():
    e = Edit(mode="upgrade", find="Normal.", replace="Normal. Follow up in 6 months.")
    assert V.changed_sentence(REP2, V.apply_edit(REP2, e), e) == "Normal. Follow up in 6 months."
    e = Edit(mode="insert", after="The liver is normal.", replace="Small effusion. Moderate ascites.")
    assert V.changed_sentence(REP2, V.apply_edit(REP2, e), e) == "Small effusion. Moderate ascites."
    e = Edit(mode="insert", replace="Small effusion.", section="FINDINGS")
    assert V.changed_sentence(REP2, V.apply_edit(REP2, e, ["FINDINGS", "IMPRESSION"]), e,
                              ["FINDINGS", "IMPRESSION"]) == "Small effusion."


# ── verify ──────────────────────────────────────────────────────────────────
I = inp(REPORT, "12 mm cyst left kidney")
FIX = dict(mode="replace", find="a cyst", replace="a 12 mm cyst")


async def test_verify_addressed_unconfirmed_and_contradiction(monkeypatch):
    i = inp(REPORT, "- 14 mm cyst left kidney")
    ok = item(R("a cyst", "a 14 mm cyst"))
    monkeypatch.setattr(rc, "_jev", jev({"x0": {"noul": 0.1}, "addressed": {"noul": 0.9}}))
    await V.verify(i, [ok])
    assert ok.verified == {"code": True, "failed": [], "addressed": 0.9, "contra": 0.1, "unconfirmed": False}
    assert ok.edit is not None
    unsure = item(R("Left renal cyst.", "Left renal cyst, 14 mm."), section="IMPRESSION")
    monkeypatch.setattr(rc, "_jev", jev({"x0": {"noul": 0.1}, "addressed": {"noul": 0.6}}))
    await V.verify(i, [unsure])
    assert unsure.verified["unconfirmed"] and unsure.verified["code"] and unsure.edit is not None
    bad = item(R("a cyst", "a 14 mm cyst"))
    monkeypatch.setattr(rc, "_jev", jev({"x0": {"noul": 0.8}, "addressed": {"noul": 0.9}}))
    await V.verify(i, [bad])
    assert not bad.verified["code"] and "fix_contradicts_dictation" in bad.verified["failed"] and bad.edit is None


async def test_verify_low_addressed_fails_not_addressed(monkeypatch):
    it = item(Edit(**FIX), probe="Is the size given?")
    monkeypatch.setattr(rc, "_jev", jev_stub(addressed=0.3))
    await V.verify(I, [it])
    assert it.verified["code"] is False and "not_addressed" in it.verified["failed"]
    assert it.verified["unconfirmed"] is False and it.edit is None and it.cls == "action"


async def test_verify_jev_error_fails_code(monkeypatch):
    it = item(Edit(**FIX), probe="p")
    monkeypatch.setattr(rc, "_jev", jev_stub(raise_exc=RuntimeError("boom")))
    await V.verify(I, [it])
    assert it.verified["code"] is False and "jev_error" in it.verified["failed"] and "boom" in it.verified["error"]
    assert it.edit is None


async def test_verify_missing_contra_key_is_jev_error(monkeypatch):
    it = item(Edit(**FIX), probe="p")
    monkeypatch.setattr(rc, "_jev", jev({"addressed": {"noul": 0.9}}))
    await V.verify(I, [it])
    assert it.verified["code"] is False and "jev_error" in it.verified["failed"]


async def test_verify_edit_without_probe_is_unconfirmed(monkeypatch):
    it = item(Edit(**FIX), probe=None)
    monkeypatch.setattr(rc, "_jev", jev_stub())
    await V.verify(I, [it])
    assert it.verified["code"] is True and it.verified["unconfirmed"] is True and it.edit is not None


async def test_verify_remove_skips_contradiction(monkeypatch):
    seen = []
    it = item(Edit(mode="remove", find="The liver is normal. "), kind="contradicted", probe="p")
    monkeypatch.setattr(rc, "_jev", jev_stub(seen=seen))
    await V.verify(I, [it])
    assert it.verified["contra"] is None and it.verified["addressed"] == 0.9 and it.verified["code"]
    assert all(not k.startswith("x") for _, qs in seen for k in qs)


async def test_verify_one_contradiction_call_for_all_items(monkeypatch):
    seen = []
    a = item(Edit(**FIX))
    b = item(Edit(mode="insert", after="The liver is normal.", replace="The spleen is normal."), probe=None)
    monkeypatch.setattr(rc, "_jev", jev_stub(seen=seen))
    await V.verify(inp(REPORT, "12 mm cyst left kidney. Spleen normal."), [a, b])
    dict_calls = [qs for st, qs in seen if st.startswith("SCAN TYPE")]
    assert len(dict_calls) == 1 and set(dict_calls[0]) == {"x0", "x1"}
    assert dict_calls[0]["x1"]["instructions"].endswith("The spleen is normal.")
    assert a.verified["code"] and b.verified["code"] and b.verified["unconfirmed"]


async def test_failed_guard_removes_edit_keeps_class():
    it = item(R("pancreas", "x"))
    await V.verify(inp(REPORT, "- a"), [it])
    assert it.edit is None and it.cls == "action" and it.verified["failed"] == ["anchor_not_unique"]


async def test_verify_skips_items_without_edit():
    it = item(None)
    await V.verify(I, [it])
    assert it.verified is None


async def test_verify_additions_grounding_from_item_or_group(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev_stub())
    i = inp(REPORT, "cyst left kidney")
    up = lambda: Edit(mode="upgrade", find="Left renal cyst.", replace="Left renal cyst. Follow-up in 6 months.")  # noqa: E731
    add = item(up(), kind="follow_up", lane="additions", section="IMPRESSION", evidence={"timing": "6 months"})
    cov = item(up(), kind="partial", lane="coverage", section="IMPRESSION", evidence={"timing": "6 months"})
    grp = item(up(), kind="follow_up", lane="coverage", section="IMPRESSION")
    group = [Candidate(lane="additions", kind="follow_up", evidence={"timing": "6 months"}, detector="s4")]
    await V.verify(i, [add, cov, grp], groups={grp.id: group})
    assert "ungrounded_number" not in add.verified["failed"]
    assert "ungrounded_number" in cov.verified["failed"]
    assert "ungrounded_number" not in grp.verified["failed"]


async def test_verify_threads_additions_new_content(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev_stub())
    i = inp(REPORT, "cyst left kidney")
    e = lambda: Edit(mode="insert", after="Left renal cyst.", replace="No hydronephrosis.")  # noqa: E731
    a = item(e(), kind="option", lane="additions", section="IMPRESSION")
    c = item(e(), kind="partial", lane="coverage", section="IMPRESSION")
    await V.verify(i, [a, c])
    assert "additions_new_content" in a.verified["failed"]
    assert "additions_new_content" not in c.verified["failed"]


def test_q_conveys_not_imported():
    assert not hasattr(V, "Q_CONVEYS")


# ── probe ───────────────────────────────────────────────────────────────────
async def test_probe(monkeypatch):
    i = inp(REPORT, "- 14 mm cyst left kidney\n- Free fluid")
    a = item(R("a cyst", "a 14 mm cyst"))
    a.anchor = Span(start=0, end=6, text="a cyst")
    b = item(None, probe="The FINDINGS section states the liver.")
    b.anchor = Span(start=0, end=6, text="The liver is normal.")
    c = item(None, probe="p3")
    c.anchor = Span(start=0, end=6, text="gone text")
    new = REPORT.replace("a cyst", "a 14 mm cyst") + " No free fluid."
    start = new.index("No free fluid.")
    monkeypatch.setattr(rc, "_jev", jev({"p0": {"noul": 0.9}, "p1": {"noul": 0.6}, "p2": {"noul": 0.1},
                                         "x0": {"noul": 0.8}}))
    res = await V.probe(i, [a, b, c], new, [[start, len(new)]])
    assert res["addressed"] == [a.id] and set(res["reprepare"]) == {b.id, c.id}
    assert len(res["contradictions"]) == 1
    cand = res["contradictions"][0]
    assert cand.kind == "contradicted" and cand.code_fix and cand.proposed.mode == "remove"
    assert cand.proposed.find.strip() == "No free fluid."


def _drops_item(old, new, kind="differs", mode="replace"):
    rep = f"FINDINGS:\n{old} The heart is normal."
    e = R(old, new)
    if mode != "replace":
        e = Edit(mode=mode, find=old, replace=new)
    return "drops_negative_item" in G(rep, e, kind, "left pneumothorax")


def test_drops_negative_item_fires_when_item_dropped():
    assert _drops_item("No pneumothorax or effusion.", "No effusion.")
    assert _drops_item("No pneumothorax or effusion.", "No effusion.", mode="upgrade")
    assert _drops_item("No pneumothorax or effusion.", "Small pneumothorax. No effusion.")


def test_drops_negative_item_kept_on_reword():
    assert not _drops_item("No pneumothorax or pleural effusion.", "No pneumothorax or effusion.")
    assert not _drops_item("No pneumothorax or effusion.", "No pneumothorax. No pleural effusion.")


def test_drops_negative_item_exempt_for_removal_kinds():
    assert not _drops_item("No pneumothorax or effusion.", "No effusion.", kind="contradicted")
    assert not _drops_item("No pneumothorax or effusion.", "No effusion.", kind="removed")


def test_drops_negative_item_insert_unaffected():
    rep = "FINDINGS:\nNo pneumothorax or effusion. The heart is normal."
    e = Edit(mode="insert", after="The heart is normal.", replace="Mild cardiomegaly.")
    assert "drops_negative_item" not in G(rep, e, "missing", "mild cardiomegaly")


# ── review fixes (T9 probes) ────────────────────────────────────────────────
from types import SimpleNamespace  # noqa: E402

LIST = "No pleural effusion, pneumothorax or consolidation."
RL = f"FINDINGS:\n{LIST}\nIMPRESSION:\nNormal."
RS = "FINDINGS:\nThe spleen is not enlarged. The liver is normal.\nIMPRESSION:\nNormal."
RP = "FINDINGS:\nThere is no free fluid in the pelvis. The liver is normal.\nIMPRESSION:\nNormal."
R3 = ("FINDINGS:\nThe liver is normal.\n\nThere is no free fluid. The spleen is normal.\n\n"
      "IMPRESSION:\n1. Normal liver.\n2. No free fluid.")
R3R = ("FINDINGS:\n\nHEAD:\nNo intracranial haemorrhage.\n\nCHEST:\nNo pneumothorax. Small left effusion.\n\n"
       "ABDOMEN:\nThe liver is normal.\n\nIMPRESSION:\nSmall left effusion.")


def test_remove_of_negator_flips_polarity_fails():
    assert "drops_negation" in G(RS, Edit(mode="remove", find="not "), "contradicted", "- liver lesion")


def test_remove_of_first_list_item_unnegates_the_rest_fails():
    assert "drops_negative_item" in G(RL, Edit(mode="remove", find="No pleural effusion,"), "contradicted",
                                      "- pleural effusion")


def test_remove_must_be_whole_sentence_or_list_item():
    assert "partial_remove" in G(RP, Edit(mode="remove", find="no "), "contradicted", "- free fluid in pelvis")
    assert "partial_remove" in G(RP, Edit(mode="remove", find="in the pelvis."), "contradicted", "- x")
    assert "partial_remove" not in G(RP, Edit(mode="remove", find="The liver is normal."), "contradicted", "- x")
    assert "partial_remove" not in G(RL, Edit(mode="remove", find=", pneumothorax"), "contradicted", "- x")
    assert "partial_remove" not in G(R3, Edit(mode="remove", find="No free fluid."), "contradicted", "- x",
                                     sections=SECTIONS)
    assert G(RL, Edit(mode="remove", find=", pneumothorax"), "contradicted", "- Small pneumothorax",
             target="No pneumothorax") == []


def test_remove_dictated_when_dictation_is_contained_in_removed_text():
    e = Edit(mode="remove", find="There is no free fluid in the pelvis.")
    assert "remove_dictated" in G(RP, e, "contradicted", "- No free fluid")
    assert "remove_dictated" in G(RP, e, "contradicted", "- Pelvis: no fluid")


def test_dropped_list_item_dictated_as_none_or_shorter_is_protected():
    e = R(LIST, "No pleural effusion or consolidation.")
    assert "remove_dictated" in G(RL, e, "contradicted", "- Pneumothorax: none", target="No pneumothorax")
    assert "remove_dictated" in G(RL, e, "contradicted", "- Lungs clear, no pneumothorax.", target="No pneumothorax")
    e = R(LIST, "No pneumothorax or consolidation.")
    assert "remove_dictated" in G(RL, e, "contradicted", "- No effusion", target="No pleural effusion")


def test_contradicted_replace_that_drops_a_dictated_positive_fails():
    rep = "FINDINGS:\nThere is a 12 mm nodule in the right upper lobe.\nIMPRESSION:\nNodule."
    e = R("There is a 12 mm nodule in the right upper lobe.", "There is a nodule.")
    assert "remove_dictated" in G(rep, e, "contradicted", "- 12 mm nodule right upper lobe")


def test_removal_exemption_is_scoped_to_one_matching_item():
    assert "drops_negative_item" in G(RL, R(LIST, "No pleural effusion."), "contradicted", "- Small pneumothorax",
                                      target="No pneumothorax")
    assert "drops_negative_item" in G(RL, R(LIST, "No pleural effusion or consolidation."), "contradicted",
                                      "- Small pneumothorax", target="No consolidation")
    assert G(RL, R(LIST, "No pleural effusion or consolidation."), "contradicted", "- Small pneumothorax",
             target="No pneumothorax") == []
    f = G(RS, R("The spleen is not enlarged. The liver is normal.", "The spleen is enlarged."), "contradicted",
          "- splenomegaly", target="The spleen is not enlarged.")
    assert "drops_sentence" in f


def test_region_subheadings_are_not_section_boundaries():
    secs = quick_section_names(R3R)
    e = R("No pneumothorax. Small left", "No pneumothorax. Small 2 cm left", section="FINDINGS")
    assert "outside_section" not in G(R3R, e, d="- 2 cm left effusion", sections=secs)
    e = Edit(mode="insert", after="No pneumothorax.", replace="Left rib fracture.")
    assert "outside_section" not in G(R3R, e, "absent", "- left rib fracture", sections=secs, item_section="FINDINGS")
    out = V.apply_edit(R3R, Edit(mode="insert", replace="Rib fracture on the left.", section="FINDINGS"), secs)
    assert out.index("ABDOMEN:") < out.index("Rib fracture") < out.index("IMPRESSION:")
    out = V.apply_edit(R3R, Edit(mode="insert", after="CHEST:", replace="Left rib fracture."), secs)
    assert "CHEST:\nLeft rib fracture.\nNo pneumothorax." in out
    # without known sections the ALL-CAPS heading fallback still bounds sections
    assert "outside_section" in G(R3R, e, "absent", "- left rib fracture", item_section="FINDINGS")


def test_remove_numbered_item_removes_line_and_renumbers():
    assert V.apply_edit(R3, Edit(mode="remove", find="No free fluid."), SECTIONS) == \
        "FINDINGS:\nThe liver is normal.\n\nThere is no free fluid. The spleen is normal.\n\nIMPRESSION:\n1. Normal liver."
    rep = "IMPRESSION:\n1. A is here.\n2. B is here.\n3. C is here."
    assert V.apply_edit(rep, Edit(mode="remove", find="B is here."), ["IMPRESSION"]) == \
        "IMPRESSION:\n1. A is here.\n2. C is here."


def test_remove_seam_tidy():
    assert V.apply_edit(R3, Edit(mode="remove", find="There is no free fluid. The spleen is normal."), SECTIONS) == \
        "FINDINGS:\nThe liver is normal.\n\nIMPRESSION:\n1. Normal liver.\n2. No free fluid."
    assert V.apply_edit("FINDINGS:\nLiver normal. No fluid . Spleen normal.", Edit(mode="remove", find="No fluid"),
                        []) == "FINDINGS:\nLiver normal. Spleen normal."
    assert V.apply_edit("FINDINGS:\nNo effusion, no pneumothorax.\n", Edit(mode="remove", find="No effusion,"),
                        []) == "FINDINGS:\nNo pneumothorax.\n"
    assert V.apply_edit("FINDINGS:\nNo effusion; no pneumothorax.\n", Edit(mode="remove", find="no pneumothorax."),
                        []) == "FINDINGS:\nNo effusion.\n"
    assert V.apply_edit("FINDINGS:\r\nA. B.\r\nC.\r\nIMPRESSION:\r\nD.", Edit(mode="remove", find="C."), []) == \
        "FINDINGS:\r\nA. B.\r\nIMPRESSION:\r\nD."


def test_insert_at_end_of_numbered_impression_starts_new_item():
    out = V.apply_edit(R3, Edit(mode="insert", replace="Follow-up advised.", section="IMPRESSION"), SECTIONS)
    assert out.endswith("1. Normal liver.\n2. No free fluid.\n3. Follow-up advised.")


def test_guard_failures_options_are_keyword_only():
    with pytest.raises(TypeError):
        V.guard_failures(REPORT, R("a cyst", "a 12 mm cyst"), "partial", "", "", "12 mm")


@pytest.mark.parametrize("sent,clause,expect", [
    ("No free fluid, pneumothorax or effusion.", "No free fluid", "No pneumothorax or effusion."),
    ("No free fluid, pneumothorax or effusion.", "No pneumothorax", "No free fluid or effusion."),
    ("No free fluid, pneumothorax or effusion.", "No effusion", "No free fluid or pneumothorax."),
    ("No free fluid, pneumothorax, or effusion.", "No free fluid", "No pneumothorax or effusion."),
    ("No free fluid, pneumothorax, or effusion.", "No pneumothorax", "No free fluid or effusion."),
    ("No free fluid, pneumothorax, or effusion.", "No effusion", "No free fluid or pneumothorax."),
    ("No free fluid or effusion.", "No effusion", "No free fluid."),
])
def test_negative_fix_drops_any_list_item_through_production(sent, clause, expect):
    text = f"FINDINGS:\nThe liver is normal. {sent} The spleen is normal.\nIMPRESSION:\nNormal."
    s = text.index(sent)
    for start, end in ((s, s + len(sent)), (s, s + len(clause))):   # a clause's own span, or its sentence
        e = V._negative_fix(text, start, end, clause)
        assert e is not None and e.mode == "replace" and e.find == sent and e.replace == expect
        out = V.apply_edit(text, e, SECTIONS)
        assert f"The liver is normal. {expect} The spleen is normal." in out
        assert G(text, e, "contradicted", "- x", target=clause, sections=SECTIONS) == []


def test_negative_fix_whole_sentence_and_unclean():
    text = "FINDINGS:\nThe liver is normal. No free fluid. The spleen is normal.\nIMPRESSION:\nNormal."
    s = text.index("No free fluid.")
    e = V._negative_fix(text, s, s + len("No free fluid"), "No free fluid")
    assert e.mode == "remove" and e.find == "No free fluid."
    assert V.apply_edit(text, e, SECTIONS) == "FINDINGS:\nThe liver is normal. The spleen is normal.\nIMPRESSION:\nNormal."
    text = "FINDINGS:\nThere is no free fluid but a small collection is seen.\nIMPRESSION:\nNormal."
    assert V._negative_fix(text, 10, len(text) - 20, "No free fluid") is None


def _fake_align(clauses):
    return lambda *a, **k: SimpleNamespace(clauses=[SimpleNamespace(negative=True, section="FINDINGS", **c)
                                                    for c in clauses])


async def test_probe_unclean_negative_goes_to_adjudicator(monkeypatch):
    text = "FINDINGS:\nThere is no free fluid but a small collection is seen.\nIMPRESSION:\nNormal."
    s = text.index("There")
    monkeypatch.setattr(V, "align", _fake_align([dict(text="No free fluid", start=s, end=text.index("\nIMP"))]))
    monkeypatch.setattr(rc, "_jev", jev_stub(contra=0.9))
    res = await V.probe(inp(text, "- free fluid"), [], text, [[s, s + 5]])
    (c,) = res["contradictions"]
    assert c.proposed is None and c.code_fix is False


async def test_probe_negative_list_candidate_is_clean(monkeypatch):
    sent = "No free fluid, pneumothorax or effusion."
    text = f"FINDINGS:\nThe liver is normal. {sent}\nIMPRESSION:\nNormal."
    s = text.index(sent)
    monkeypatch.setattr(V, "align", _fake_align([dict(text="No pneumothorax", start=s, end=s + len(sent))]))
    monkeypatch.setattr(rc, "_jev", jev_stub(contra=0.9))
    res = await V.probe(inp(text, "- pneumothorax"), [], text, [[s, s + len(sent)]])
    (c,) = res["contradictions"]
    assert c.code_fix and c.proposed.replace == "No free fluid or effusion."


async def test_probe_paragraph_touched_and_anchor_offsets(monkeypatch):
    text = "FINDINGS:\nThe liver is normal.\n\nThere is a cyst in the left kidney.\nIMPRESSION:\nA cyst. A cyst."
    monkeypatch.setattr(V, "align", _fake_align([]))
    monkeypatch.setattr(rc, "_jev", jev_stub(contra=0.0))
    touched = item(None, probe="p")
    touched.anchor = Span(start=text.index("a cyst"), end=text.index("a cyst") + 6, text="a cyst")
    calm = item(None, probe="p")
    calm.anchor = Span(start=text.index("The liver"), end=text.index("The liver") + 20, text="The liver is normal.")
    moved = item(None, probe="p")          # text unique, offsets stale: mapped, so kept
    moved.anchor = Span(start=0, end=20, text="The liver is normal.")
    ambiguous = item(None, probe="p")      # text present twice, offsets stale: anchor lost
    ambiguous.anchor = Span(start=0, end=6, text="A cyst")
    k = text.index("left")
    res = await V.probe(inp(text, "- x"), [touched, calm, moved, ambiguous], text, [[k, k + 4]])
    assert set(res["reprepare"]) == {touched.id, ambiguous.id} and res["addressed"] == []
    # a pure deletion is a zero-width range: it still touches its paragraph
    res = await V.probe(inp(text, "- x"), [touched, calm], text, [[k, k]])
    assert res["reprepare"] == [touched.id]


async def test_probe_jev_failure_reports_error(monkeypatch):
    async def down(state, qs):
        raise ConnectionError("down")
    monkeypatch.setattr(rc, "_jev", down)
    a = item(None, probe="p")
    a.anchor = Span(start=REPORT.index("a cyst"), end=REPORT.index("a cyst") + 6, text="a cyst")
    res = await V.probe(inp(REPORT, "- x"), [a], REPORT, [])
    assert res["addressed"] == [] and res["contradictions"] == [] and "ConnectionError" in res["error"]


async def test_verify_rejects_nan_and_dedupes_errors(monkeypatch):
    it = item(Edit(**FIX), probe="p")
    monkeypatch.setattr(rc, "_jev", jev({"x0": {"noul": 0.1}, "addressed": {"noul": float("nan")}}))
    await V.verify(I, [it])
    assert it.verified["code"] is False and "jev_error" in it.verified["failed"]
    it = item(Edit(**FIX), probe="p")
    monkeypatch.setattr(rc, "_jev", jev({"x0": {"noul": float("inf")}, "addressed": {"noul": 0.9}}))
    await V.verify(I, [it])
    assert "jev_error" in it.verified["failed"]
    it = item(Edit(**FIX), probe="p")
    monkeypatch.setattr(rc, "_jev", jev_stub(raise_exc=RuntimeError("boom")))
    await V.verify(I, [it])
    assert it.verified["error"] == "RuntimeError: boom"


async def test_verify_passes_item_clause_as_removal_target(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev_stub())
    wrong = item(R(LIST, "No pleural effusion or consolidation."), kind="contradicted",
                 evidence={"clause": "No consolidation"})
    right = item(R(LIST, "No pleural effusion or consolidation."), kind="contradicted",
                 evidence={"clause": "No pneumothorax"})
    await V.verify(inp(RL, "- Small pneumothorax"), [wrong, right])
    assert "drops_negative_item" in wrong.verified["failed"]
    assert right.verified["code"] is True
