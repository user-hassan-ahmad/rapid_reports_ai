"""What the rail may surface (prod 2026-10-06, live Review rail):
- an additions suggestion is shown only with a verified, placeable edit (the verifier's code guards passed and the
  edit applies to the current text); otherwise it is `suppress` — never shown with Add and no edit (the client
  renders that as "out of date" immediately);
- an item that would be stale on creation (its anchor is not the report's text there) is never shown;
- brief option reasons ("finding borderline (p=0.74)", "contextual") stay internal evidence; the user-facing reason
  is a short plain phrase or empty, and never carries a p-value.
Synthetic cases only, no live model calls."""
from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine import engine
from rapid_reports_ai.review_engine.items import Edit, ReviewItem, Span
from rapid_reports_ai.review_engine.lanes.additions import brief_candidates
from rapid_reports_ai.review_engine.alignment import align

from tests.review_engine_fakes import inp, jev, model

REPORT = ("FINDINGS:\nThe left kidney contains a 4.1 cm enhancing mass, likely renal cell carcinoma. The mass abuts "
          "the left renal vein over a short segment. No encasement of the left renal vein or inferior vena cava, and "
          "no involvement of the adrenal gland. No lymphadenopathy.\nIMPRESSION:\nLeft renal mass.")
DICT = "- 4.1 cm enhancing left renal mass, likely RCC\n- abuts the left renal vein"
RUN = "00000000-0000-0000-0000-0000000000b1"


def _fn(i, text, finding, reason):
    return {"id": f"fn{i}", "kind": "finding_negative", "section": "FINDINGS", "sentence": text, "finding": finding,
            "reason": reason}


OPTIONS = [_fn(0, "No inferior vena cava thrombosis.", "Vascular involvement", "finding borderline (p=0.74)"),
           _fn(1, "No renal vein tumour thrombus.", "Renal vein", "finding borderline (p=0.69)")]


def _item(**kw):
    base = dict(key="k", report_id="00000000-0000-0000-0000-000000000001", run_id=RUN, lane="additions",
                detectors=["brief.option"], kind="option", cls="minor", section="FINDINGS", label="x", reason="",
                status="open", engine_version="t")
    return ReviewItem(**{**base, **kw})


# ── the gate itself ──────────────────────────────────────────────────────────

def test_additions_item_without_an_edit_is_suppressed():
    it = _item(edit=None, evidence={"sub_kind": "finding_negative"})
    engine.surface_gate(inp(REPORT, DICT), [it])
    assert it.cls == "suppress" and it.evidence["suppressed"] == "no_placeable_edit"
    assert it.evidence["cls_before"] == "minor" and it.history[-1]["event"] == "suppressed"


def test_additions_item_whose_edit_failed_the_code_guards_is_suppressed():
    it = _item(edit=Edit(mode="insert", replace="No ascites.", section="FINDINGS"),
               verified={"code": False, "failed": ["x"], "addressed": None, "contra": None, "unconfirmed": False})
    engine.surface_gate(inp(REPORT, DICT), [it])
    assert it.cls == "suppress"


def test_additions_item_whose_edit_does_not_apply_is_suppressed():
    it = _item(edit=Edit(mode="insert", replace="No ascites.", after="A sentence not in the report.",
                         section="FINDINGS"),
               verified={"code": True, "failed": [], "addressed": 0.9, "contra": 0.1, "unconfirmed": False})
    engine.surface_gate(inp(REPORT, DICT), [it])
    assert it.cls == "suppress"


def test_verified_placeable_additions_item_is_kept():
    it = _item(edit=Edit(mode="insert", replace="No ascites.", section="FINDINGS"),
               verified={"code": True, "failed": [], "addressed": 0.9, "contra": 0.1, "unconfirmed": False})
    engine.surface_gate(inp(REPORT, DICT), [it])
    assert it.cls == "minor" and "suppressed" not in (it.evidence or {})


def test_unverified_additions_edit_is_suppressed():
    it = _item(edit=Edit(mode="insert", replace="No ascites.", section="FINDINGS"), verified=None)
    engine.surface_gate(inp(REPORT, DICT), [it])
    assert it.cls == "suppress"


def test_rail_card_without_an_edit_from_other_lanes_is_untouched():
    it = _item(lane="accuracy", kind="unsupported", detectors=["jev.supported"], edit=None,
               anchor=Span(start=10, end=20, text=REPORT[10:20]))
    engine.surface_gate(inp(REPORT, DICT), [it])
    assert it.cls == "minor"


def test_item_stale_on_creation_is_suppressed():
    it = _item(lane="accuracy", kind="unsupported", detectors=["jev.supported"], edit=None,
               anchor=Span(start=10, end=20, text="not there!"))
    engine.surface_gate(inp(REPORT, DICT), [it])
    assert it.cls == "suppress" and it.evidence["suppressed"] == "stale_on_creation"


def test_pre_applied_items_are_never_gated():
    it = _item(lane="accuracy", kind="contradicted", status="pre_applied", edit=None,
               anchor=Span(start=10, end=20, text="not there!"))
    engine.surface_gate(inp(REPORT, DICT), [it])
    assert it.cls == "minor"


# ── user-facing reason ───────────────────────────────────────────────────────

def test_brief_option_reason_is_plain_and_the_p_value_stays_internal():
    i = inp(REPORT, DICT, options=OPTIONS)
    c = brief_candidates(i, align(REPORT, DICT, "", i.artifacts.sections))[0]
    it = engine.build_item(i, RUN, adj.Outcome(group=[c]))
    assert "p=" not in it.reason and "borderline" not in it.reason and "p=" not in it.label
    assert it.reason == "Pertinent negative for vascular involvement"
    assert it.evidence["reason"] == "finding borderline (p=0.74)"          # kept as evidence


def test_written_option_note_is_the_internal_evidence():
    o = [{"id": "fn0", "kind": "finding_negative", "section": "FINDINGS", "sentence": "No ascites.",
          "finding": "Peritoneal disease", "reason": "", "note": "finding borderline (p=0.61)"}]
    i = inp(REPORT, DICT, options=o)
    c = brief_candidates(i, align(REPORT, DICT, "", i.artifacts.sections))[0]
    it = engine.build_item(i, RUN, adj.Outcome(group=[c]))
    assert it.reason == "Pertinent negative for peritoneal disease"
    assert it.evidence["reason"] == "finding borderline (p=0.61)"


def test_contextual_reason_is_not_user_facing():
    o = [{"id": "fn0", "kind": "finding_negative", "section": "FINDINGS", "sentence": "No ascites.",
          "reason": "contextual"}]
    i = inp(REPORT, DICT, options=o)
    c = brief_candidates(i, align(REPORT, DICT, "", i.artifacts.sections))[0]
    it = engine.build_item(i, RUN, adj.Outcome(group=[c]))
    assert it.reason == "" and it.evidence["reason"] == "contextual"


def test_adjudicated_reason_and_label_never_carry_p_values():
    i = inp(REPORT, DICT, options=OPTIONS)
    c = brief_candidates(i, align(REPORT, DICT, "", i.artifacts.sections))[0]
    j = adj.Judgement(cls="minor", kind="option", label="Vein thrombus (p=0.69)",
                      reason="Finding borderline (p = 0.74); worth stating.", edit_mode="none")
    it = engine.build_item(i, RUN, adj.Outcome(group=[c], judgement=j))
    assert "p=" not in it.label.replace(" ", "") and "p=" not in it.reason.replace(" ", "")
    assert it.label == "Vein thrombus" and it.reason == "Finding borderline; worth stating."


# ── end to end: the prod shape ───────────────────────────────────────────────

async def test_engine_suppresses_an_option_the_adjudicator_cannot_fix(monkeypatch):
    def judge(kw):
        return adj.Judgement(cls="minor", kind="option", label="Renal vein tumour thrombus not explicitly excluded",
                             reason="A guideline fix cannot add a new negative finding.", edit_mode="none")
    # g1 in the unsure band → adjudicated; g0 stays pre-classed; probes answer "addressed"
    monkeypatch.setattr(rc, "_jev", jev({"g1": {"noul": 0.4}, "addressed": {"noul": 0.95}}))
    monkeypatch.setattr(adj, "_run_agent_with_model", model(judge))
    monkeypatch.setenv("RR_REVIEW_LANES", "additions")
    res = await engine.run_review(inp(REPORT, DICT, options=OPTIONS), RUN)
    by_opt = {(it.evidence or {}).get("option_id"): it for it in res.items}
    kept, gone = by_opt["fn0"], by_opt["fn1"]
    assert kept.cls == "minor" and kept.edit is not None and kept.edit.mode == "insert"
    assert kept.edit.after == ("No encasement of the left renal vein or inferior vena cava, and no involvement of "
                               "the adrenal gland.")
    assert gone.cls == "suppress" and gone.edit is None and gone.evidence["suppressed"] == "no_placeable_edit"
    shown = [it for it in res.items if it.cls != "suppress" and it.lane == "additions"]
    assert all(it.edit is not None for it in shown)
