"""The post-generation check's applied edits become `pre_applied` review items on the FINAL text the user is shown
(spec §10.4: automatic edits happen only before render; the engine never rewrites the report). Synthetic cases only,
no live model calls."""
import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai import report_review as rr
from rapid_reports_ai.report_review import checked_clauses_in_context
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine import engine, live, negatives
from rapid_reports_ai.review_engine.items import ReviewItem, Span, text_hash

from tests.review_engine_fakes import inp, jev, model
import tests.test_review_engine_engine as te

PRE = "FINDINGS:\nThe liver is normal. No ascites. A 14 mm left renal cyst.\nIMPRESSION:\nLeft renal cyst."
DICT = "- 14 mm left renal cyst\n- Small volume ascites\n- Small left pleural effusion"
INSERTED = "Small left pleural effusion."


@pytest.fixture
def qc_stubs(monkeypatch):
    """The post-gen check flags "No ascites." (a contradicted negative: removed in code) and an absent dictated line
    (inserted by construction after the cyst sentence)."""
    monkeypatch.setenv("RR_REVIEW_ENGINE", "live")
    monkeypatch.setenv("RR_QUALITY_CHECK", "1")

    async def fake_check(report, findings, scan_type, options, **kw):
        return rr.CheckResult(flags=[rr.Flag(kind="contradiction", text="No ascites.", score=0.95),
                                     rr.Flag(kind="omission", text="Small left pleural effusion", score=0.1)],
                              sentence_type={"No ascites.": "normal"})

    async def fake_insert(report, findings, items, **kw):
        anchor = "A 14 mm left renal cyst."
        return rr.RepairResult(report=report.replace(anchor, f"{anchor} {INSERTED}", 1), applied=1, added=[INSERTED])
    monkeypatch.setattr(rr, "check", fake_check)
    monkeypatch.setattr(rr, "insert_findings", fake_insert)


async def _post_gen():
    final, _, tel = await rr.run_quality_check(PRE, DICT, "CT abdomen", [])
    return final, tel


async def test_run_quality_check_records_the_applied_edits(qc_stubs):
    final, tel = await _post_gen()
    assert final == "FINDINGS:\nThe liver is normal. A 14 mm left renal cyst. Small left pleural effusion.\n" \
                    "IMPRESSION:\nLeft renal cyst."
    assert tel["pre_edit_report"] == PRE
    assert tel["applied_edits"] == [{"type": "removal", "clause": "No ascites."},
                                    {"type": "insertion", "sentence": INSERTED}]


async def test_applied_edits_follow_a_protected_revert(monkeypatch):
    """A repair that broke protected text is reverted: the reverted edits are not recorded as applied."""
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setenv("RR_QUALITY_CHECK", "1")

    async def fake_check(report, findings, scan_type, options, **kw):
        return rr.CheckResult(flags=[rr.Flag(kind="omission", text="x", score=0.1)])

    async def fake_insert(report, findings, items, **kw):
        return rr.RepairResult(report=report.replace("KEEP", "kept"), applied=1, added=["Bad."])
    monkeypatch.setattr(rr, "check", fake_check)
    monkeypatch.setattr(rr, "insert_findings", fake_insert)
    report, _, tel = await rr.run_quality_check("FINDINGS:\nKEEP.", "- x", "CT", [], protected=["KEEP"])
    assert report == "FINDINGS:\nKEEP." and tel.get("applied_edits", []) == []


async def test_insert_findings_lists_the_sentences_it_added(monkeypatch):
    monkeypatch.setattr(rc, "_jev", jev())
    monkeypatch.setattr(rr, "_run_agent_with_model", model(rr.Insertions(items=[
        rr.Insertion(after="A 14 mm left renal cyst.", sentence="Small left pleural effusion")])))
    rep = await rr.insert_findings(PRE, DICT, ["Small left pleural effusion"])
    assert rep.applied == 1 and rep.added == [INSERTED] and INSERTED in rep.report


def _engine_stubs(monkeypatch, report, flag_inserted=False):
    over = {"addressed": {"noul": 0.9}}
    if flag_inserted:                      # the accuracy lane flags the inserted sentence itself
        cls = list(checked_clauses_in_context(report, None))
        k = cls.index(next(c for c in cls if "effusion" in c))
        over.update({f"c{k}": {"noul": 0.95}, f"r{k}": {"noul": 0.95}, f"d{k}": {"noul": 0.05}})
    monkeypatch.setattr(rc, "_jev", jev(over))
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(
        cls="action", kind="contradicted", label="Effusion contradicted", reason="r", edit_mode="none",
        probe="The FINDINGS section reports an effusion.")))
    monkeypatch.setattr(negatives, "_run_agent_with_model", te.labels(te._all_default))


def _undo(text: str, u: dict) -> str:
    j1, j2 = u["final_span"]
    assert text[j1:j2] == u["final_text"]
    return text[:j1] + u["original_text"] + text[j2:]


async def test_engine_turns_applied_edits_into_pre_applied_items(qc_stubs, monkeypatch):
    final, tel = await _post_gen()
    _engine_stubs(monkeypatch, final)
    res = await engine.run_review(inp(final, DICT, quality_check=tel, pre_edit=PRE),
                                  run_id="00000000-0000-0000-0000-0000000000b1")
    h = text_hash(final)
    bridge = [i for i in res.items if any(d.startswith("post_check.") for d in i.detectors)]
    assert len(bridge) == 2 and all(i.status == "pre_applied" and i.cls == "action" for i in bridge)
    rem = next(i for i in bridge if i.kind == "removed")
    ins = next(i for i in bridge if i.kind == "absent")
    assert rem.lane == "accuracy" and rem.detectors == ["post_check.removal"]
    assert ins.lane == "coverage" and ins.detectors == ["post_check.insert"]
    # removal: zero-width anchor at the removal point on the final text
    assert rem.anchor.start == rem.anchor.end and rem.anchor.text == "" and rem.anchor.text_hash == h
    assert final[:rem.anchor.start].endswith("The liver is normal.") or \
        final[:rem.anchor.start].endswith("The liver is normal. ")
    assert rem.evidence["removed_text"] == "No ascites." and rem.edit.mode == "remove"
    # insertion: anchor = the inserted text
    assert final[ins.anchor.start:ins.anchor.end] == INSERTED == ins.anchor.text and ins.anchor.text_hash == h
    assert ins.edit.mode == "insert" and ins.edit.replace == INSERTED
    for it in (rem, ins):
        u = it.evidence["undo"]
        j1, j2 = u["final_span"]
        assert u["left"] == final[max(0, j1 - 16):j1] and u["right"] == final[j2:j2 + 16]
        assert final.count(u["left"] + u["final_text"] + u["right"]) == 1
        assert it.history[0]["event"] == "created" and it.history[-1]["event"] == "pre_applied"
        assert it.engine_version == engine.ENGINE_VERSION and it.section == "FINDINGS"
    # each undo restores exactly its edit; both (later span first) restore the pre-edit report
    assert "No ascites." in _undo(final, rem.evidence["undo"]) and INSERTED in _undo(final, rem.evidence["undo"])
    assert INSERTED not in _undo(final, ins.evidence["undo"])
    first, second = sorted((rem, ins), key=lambda i: -i.evidence["undo"]["final_span"][0])
    assert _undo(_undo(final, first.evidence["undo"]), second.evidence["undo"]) == PRE
    assert [e["type"] for e in res.run["post_check"]] == ["removal", "insertion"]


async def test_no_duplicate_item_on_a_bridged_span(qc_stubs, monkeypatch):
    final, tel = await _post_gen()
    _engine_stubs(monkeypatch, final, flag_inserted=True)
    res = await engine.run_review(inp(final, DICT, quality_check=tel, pre_edit=PRE),
                                  run_id="00000000-0000-0000-0000-0000000000b2")
    ins = next(i for i in res.items if i.detectors == ["post_check.insert"])
    on_span = [i for i in res.items if i.anchor is not None and i.anchor.end > i.anchor.start
               and i.anchor.start < ins.anchor.end and ins.anchor.start < i.anchor.end]
    assert on_span == [ins]                                        # the bridge item wins
    assert any((d.get("anchor") or {}).get("text", "").startswith("Small left pleural") for d in res.run["deduped"])


async def test_no_bridge_without_applied_edits(monkeypatch):
    _engine_stubs(monkeypatch, PRE)
    res = await engine.run_review(inp(PRE, DICT, quality_check={"flags": []}),
                                  run_id="00000000-0000-0000-0000-0000000000b3")
    assert not any(any(d.startswith("post_check.") for d in i.detectors) for i in res.items)


def test_bridge_skips_an_edit_it_cannot_locate():
    pre = "FINDINGS:\nNo ascites. Normal liver.\nIMPRESSION:\nNormal."
    final = "FINDINGS:\nNormal liver.\nIMPRESSION:\nNormal."
    qc = {"applied_edits": [{"type": "removal", "clause": "No ascites."},
                            {"type": "insertion", "sentence": "Not in the report."}]}
    items, log = live.bridge_items(inp(final, "- x", quality_check=qc, pre_edit=pre), "r1")
    assert [i.kind for i in items] == ["removed"] and [e["located"] for e in log] == [True, False]


def test_bridge_dedupe_drops_engine_items_on_the_inserted_span():
    final = "FINDINGS:\nA cyst. Small effusion.\nIMPRESSION:\nCyst."
    k = final.index("Small effusion.")
    br = ReviewItem(key="b", report_id="r", run_id="x", lane="coverage", kind="absent", cls="action",
                    status="pre_applied", detectors=["post_check.insert"],
                    anchor=Span(start=k, end=k + 15, text="Small effusion."))
    dup = ReviewItem(key="d", report_id="r", run_id="x", lane="accuracy", kind="contradicted", cls="action",
                     anchor=Span(start=k, end=k + 15, text="Small effusion."))
    other = ReviewItem(key="o", report_id="r", run_id="x", lane="accuracy", kind="check", cls="minor",
                       anchor=Span(start=10, end=17, text="A cyst."))
    kept, dropped = live.dedupe([dup, other], [br])
    assert kept == [other] and dropped == [dup]


def test_bridge_locates_an_item_dropped_from_a_negative_list():
    pre = "FINDINGS:\nA cyst. No ascites, pneumothorax or effusion.\nIMPRESSION:\nCyst."
    final = "FINDINGS:\nA cyst. No ascites or effusion.\nIMPRESSION:\nCyst."   # remove_negative_clause's list drop
    qc = {"applied_edits": [{"type": "removal", "clause": "No pneumothorax"}]}
    items, _ = live.bridge_items(inp(final, "- x", quality_check=qc, pre_edit=pre), "r1")
    (rem,) = items
    u = rem.evidence["undo"]
    assert _undo(final, u) == pre and u["original_text"].strip(" ,") == "pneumothorax"
    assert rem.anchor.start == rem.anchor.end == u["final_span"][0] and final[:rem.anchor.start].endswith("ascites")


def test_bridge_edits_carry_section_and_insert_anchor():
    """Re-apply after undo (F2 I1): the bridge edits name their section, and the insertion names the sentence it
    followed (when that sentence occurs once), so the edit lands back where the check put it."""
    pre = "FINDINGS:\nThe liver is normal. No ascites. A 14 mm left renal cyst.\nIMPRESSION:\nLeft renal cyst."
    final = "FINDINGS:\nThe liver is normal. A 14 mm left renal cyst. Small left pleural effusion.\n" \
            "IMPRESSION:\nLeft renal cyst."
    qc = {"applied_edits": [{"type": "removal", "clause": "No ascites."},
                            {"type": "insertion", "sentence": INSERTED}]}
    items, _ = live.bridge_items(inp(final, DICT, quality_check=qc, pre_edit=pre), "r1")
    rem = next(i for i in items if i.kind == "removed")
    ins = next(i for i in items if i.kind == "absent")
    assert rem.edit.section == "FINDINGS" and ins.edit.section == "FINDINGS"
    assert ins.edit.after == "A 14 mm left renal cyst."


def test_bridge_insert_has_no_anchor_when_the_preceding_sentence_repeats():
    pre = "FINDINGS:\nNormal.\nIMPRESSION:\nNormal."
    final = "FINDINGS:\nNormal. Small effusion.\nIMPRESSION:\nNormal."
    qc = {"applied_edits": [{"type": "insertion", "sentence": "Small effusion."}]}
    (ins,) = live.bridge_items(inp(final, "- x", quality_check=qc, pre_edit=pre), "r1")[0]
    assert ins.edit.after is None and ins.edit.section == "FINDINGS"


async def test_live_gate_leaves_post_check_edits_and_the_bridged_span_alone(qc_stubs, monkeypatch):
    final, tel = await _post_gen()
    _engine_stubs(monkeypatch, final)
    base = rc._jev

    async def gate(state, qs):                       # the inserted effusion sentence is an added normal statement
        out = await base(state, qs)
        for k, q in qs.items():
            if k[:1] in "gt" and k[1:].isdigit():
                add = "pleural effusion" in q["instructions"]
                if k.startswith("g"):
                    p = 0.1 if add else 0.9
                    out[k] = {"probabilities": {"all_stated": p, "some_details_added": 1 - p, "not_stated": 0.0}}
                else:
                    t = "normal" if add else "abnormal"
                    out[k] = {"probabilities": {x: float(x == t) for x in ("abnormal", "normal", "mixed", "not_a_finding")}}
        return out
    monkeypatch.setattr(rc, "_jev", gate)

    def sig(res):
        return (res.report, [{k: v for k, v in e.items() if k != "item_id"} for e in res.run["pre_apply"]],
                sorted(i.key for i in res.items if i.status == "pre_applied" or i.kind == "removed"))
    monkeypatch.setenv("RR_DICTATED_GATE", "off")
    off = await engine.run_review(inp(final, DICT, quality_check=tel, pre_edit=PRE),
                                  run_id="00000000-0000-0000-0000-0000000000b3")
    monkeypatch.setenv("RR_DICTATED_GATE", "live")
    lv = await engine.run_review(inp(final, DICT, quality_check=tel, pre_edit=PRE),
                                 run_id="00000000-0000-0000-0000-0000000000b3")
    assert lv.run["dictated_gate"]["mode"] == "live"
    assert sig(off) == sig(lv)
    ins = next(i for i in lv.items if i.detectors == ["post_check.insert"])
    gate_items = [i for i in lv.items if (i.evidence or {}).get("source") == "dictated_gate"
                  and i.anchor is not None and i.anchor.start < ins.anchor.end and ins.anchor.start < i.anchor.end]
    assert gate_items == []
