"""Dictated gate (spec 2026-10-10): one Jev question per report clause against the raw dictation decides whether
the clause is dictated; a tier rule decides what is highlighted. Synthetic cases only, no model calls."""
import pytest

from rapid_reports_ai.review_engine import dictated_gate as dg

from tests.review_engine_fakes import inp


def test_mode_defaults_off_and_reads_env(monkeypatch):
    monkeypatch.delenv("RR_DICTATED_GATE", raising=False)
    assert dg.mode() == "off"
    for v, want in (("shadow", "shadow"), (" LIVE ", "live"), ("off", "off"), ("bogus", "off")):
        monkeypatch.setenv("RR_DICTATED_GATE", v)
        assert dg.mode() == want


def test_question_is_the_frozen_lab_wording():
    q = dg.q_gate("The liver is normal.")
    assert q["type"] == "choice"
    assert q["instructions"].startswith('The report says: "The liver is normal.". Compare every detail in it')
    assert set(q["criteria"]) == {"all_stated", "some_details_added", "not_stated"}


def test_state_labels_history_as_context_only():
    i = inp("FINDINGS:\nX.", "- X", history="Fall.", scan="CT head")
    s = dg.state(i)
    assert s.startswith("SCAN TYPE: CT head\n")
    assert "CLINICAL HISTORY (context only; it is NOT part of the dictated findings): Fall." in s
    assert s.endswith("DICTATED FINDINGS:\n- X")
    assert "CLINICAL HISTORY" not in dg.state(inp("FINDINGS:\nX.", "- X"))


def test_questions_are_batched_four_clauses_per_request_with_a_type_question_each():
    batches = dg.questions(["a", "b", "c", "d", "e"])
    assert [sorted(b) for b in batches] == [["g0", "g1", "g2", "g3", "t0", "t1", "t2", "t3"], ["g4", "t4"]]
    assert batches[0]["t1"]["type"] == "choice" and batches[0]["t1"] != batches[0]["g1"]
    assert dg.questions([]) == []


@pytest.mark.parametrize("ans,want", [
    ({"probabilities": {"all_stated": 0.8, "some_details_added": 0.15, "not_stated": 0.05}}, 0.8),
    ({"choice": "all_stated"}, 1.0),
    ({"choice": "not_stated"}, 0.0),
    ({"noul": 0.4}, None),
    (None, None),
    ({"probabilities": {"all_stated": "x"}}, None),
])
def test_p_all_stated(ans, want):
    assert dg.p_all_stated(ans) == want


from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.review_engine import jev_pass

from tests.review_engine_fakes import jev

R = ("FINDINGS:\nThere is a 2 cm mass in the right kidney. The liver is normal. The spleen is normal.\n"
     "IMPRESSION:\nRight renal mass.\n")
D = "- 2 cm right renal mass\n- Liver normal"


@pytest.mark.asyncio
async def test_off_asks_no_gate_questions(monkeypatch):
    monkeypatch.delenv("RR_DICTATED_GATE", raising=False)
    calls = []
    monkeypatch.setattr(rc, "_jev", jev(calls=calls))
    jp = await jev_pass.run(inp(R, D), R, gate_texts=["The liver is normal."])
    assert not any(k.startswith("g") for _, qs in calls for k in qs)
    assert jp.gate == {} and jp.gate_error is None


@pytest.mark.asyncio
async def test_shadow_asks_every_clause_in_batches_with_the_gate_state(monkeypatch):
    monkeypatch.setenv("RR_DICTATED_GATE", "shadow")
    calls = []
    monkeypatch.setattr(rc, "_jev", jev({"g*": {"choice": "all_stated"}}, calls=calls))
    texts = ["There is a 2 cm mass in the right kidney.", "The liver is normal.", "The spleen is normal.",
             "Right renal mass.", "Right renal mass."]            # a duplicate is asked twice
    jp = await jev_pass.run(inp(R, D), R, gate_texts=texts)
    gate_calls = [(s, qs) for s, qs in calls if any(k.startswith("g") for k in qs)]
    want = sorted([f"g{i}" for i in range(5)] + [f"t{i}" for i in range(5)])
    assert sorted(k for _, qs in gate_calls for k in qs) == want
    assert all(len(qs) <= 8 for _, qs in gate_calls)
    assert all(s.endswith("DICTATED FINDINGS:\n" + D) for s, _ in gate_calls)
    assert set(jp.gate) == set(want) and jp.gate_texts == texts


@pytest.mark.asyncio
async def test_gate_requests_in_flight_are_capped_at_eight(monkeypatch):
    import asyncio
    monkeypatch.setenv("RR_DICTATED_GATE", "shadow")
    live = {"n": 0, "max": 0}

    async def slow(state, qs):
        if not any(k.startswith("g") for k in qs):
            return {k: {"noul": 0.1} for k in qs}
        live["n"] += 1
        live["max"] = max(live["max"], live["n"])
        await asyncio.sleep(0.01)
        live["n"] -= 1
        return {k: {"choice": "all_stated"} for k in qs}
    monkeypatch.setattr(rc, "_jev", slow)
    await jev_pass.run(inp(R, D), R, gate_texts=[f"Clause {i}." for i in range(60)])    # 15 requests
    assert live["max"] == 8


@pytest.mark.asyncio
async def test_a_failed_gate_request_sets_gate_error(monkeypatch):
    monkeypatch.setenv("RR_DICTATED_GATE", "shadow")
    base = jev()

    async def flaky(state, qs):
        if any(k.startswith("g") for k in qs):
            raise TimeoutError("slow")
        return await base(state, qs)
    monkeypatch.setattr(rc, "_jev", flaky)
    jp = await jev_pass.run(inp(R, D), R, gate_texts=["The liver is normal."])
    assert jp.gate_error and "TimeoutError" in jp.gate_error
    assert jp.contra_error is None            # the other requests are unaffected


from rapid_reports_ai.review_engine.alignment import align
from rapid_reports_ai.review_engine.jev_pass import JevPass


def _jp(clauses, p, types):
    """A JevPass asked about `clauses` (the alignment's report clauses), gate answers p[i], statement types types[i]."""
    jp = JevPass(gate_texts=list(clauses))
    jp.gate = {f"g{i}": {"probabilities": {"all_stated": v, "some_details_added": 1 - v, "not_stated": 0.0}}
               for i, v in enumerate(p) if v is not None}
    jp.gate.update({f"t{i}": {"choice": t} for i, t in enumerate(types) if t})
    return jp


def _classify(report, dictation, clauses, p, types):
    i = inp(report, dictation)
    al = align(report, dictation, "", i.artifacts.sections)
    return dg.classify(i, report, al, _jp(clauses, p, types))


def test_negative_list_and_repeated_sentence_each_get_a_placed_clause():
    r = ("FINDINGS:\nThere is no pleural effusion, pneumothorax or consolidation. The liver is normal.\n"
         "IMPRESSION:\nThe liver is normal.\n")
    i = inp(r, "- Liver normal")
    al = align(r, "- Liver normal", "", i.artifacts.sections)
    texts = [c.text for c in sorted(al.clauses, key=lambda c: c.start)]
    assert texts == ["No pleural effusion", "No pneumothorax", "No consolidation", "The liver is normal.",
                     "The liver is normal."]
    g = dg.classify(i, r, al, _jp(texts, [0.1, 0.1, 0.1, 0.9, 0.1], ["normal"] * 5))
    assert all(x.start is not None for x in g)
    assert [x.section for x in g] == ["FINDINGS"] * 4 + ["IMPRESSION"]
    assert [x.tier for x in g] == ["quiet", "quiet", "quiet", "dictated", "quiet"]


def test_classify_refuses_a_jev_pass_asked_about_other_clauses():
    i = inp(RPT, DIC)
    al = align(RPT, DIC, "", i.artifacts.sections)
    with pytest.raises(ValueError):
        dg.classify(i, RPT, al, _jp(["something else"], [0.1], ["abnormal"]))


RPT = ("FINDINGS:\nAn 11 mm crescentic subdural haematoma over the left convexity. The liver is normal. "
       "Left ovary normal with no contralateral adnexal mass.\n"
       "IMPRESSION:\nAcute subdural haematoma. Repeat CT head in 6 hours is recommended.\n")
DIC = "- 11 mm left convexity subdural haematoma\n- Left ovary normal"
CL = ["An 11 mm crescentic subdural haematoma over the left convexity.", "The liver is normal.",
      "Left ovary normal with no contralateral adnexal mass.", "Acute subdural haematoma.",
      "Repeat CT head in 6 hours is recommended."]


def test_tiers():
    g = _classify(RPT, DIC, CL, [0.3, 0.1, 0.4, 0.75, 0.0],
                  ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"])
    assert [x.tier for x in g] == ["synth", "quiet", "quiet", "dictated", "rec"]
    assert [x.q_type for x in g][:2] == ["abnormal", "normal"]
    assert all(x.start is not None and RPT[x.start:x.end] == x.text for x in g)
    assert [x.section for x in g][:1] == ["FINDINGS"] and g[4].section == "IMPRESSION"


def test_synth_runs_are_the_added_words():
    g = _classify(RPT, DIC, CL, [0.3, 0.9, 0.9, 0.9, 0.9], ["abnormal"] * 5)
    assert [RPT[s:e] for s, e in g[0].runs] == ["crescentic"]


def test_unreadable_answer_is_unknown_and_threshold_is_inclusive():
    g = _classify(RPT, DIC, CL, [None, 0.7, 0.69, 0.9, 0.9], ["abnormal", "normal", "normal", "abnormal", None])
    assert [x.tier for x in g][:3] == ["unknown", "dictated", "quiet"]


def test_a_negated_recommendation_is_review_not_quiet():
    r = "IMPRESSION:\nFunctional cyst; no urgent surgical referral is indicated.\n"
    c = ["Functional cyst; no urgent surgical referral is indicated."]
    g = _classify(r, "- Right ovarian simple cyst 28 mm", c, [0.1], ["not_a_finding"])
    assert g[0].tier == "rec"


@pytest.mark.parametrize("clause,dictation", [
    ("No interval change in the liver lesion, but there is a new nodule.", "- Liver lesion"),
    ("No change; new 5 mm nodule.", "- Liver lesion"),
])
def test_a_negator_followed_by_a_contrast_or_new_sentence_is_not_a_bolted_on_negative(clause, dictation):
    r = f"FINDINGS:\n{clause}\n"
    i = inp(r, dictation)
    al = align(r, dictation, "", i.artifacts.sections)
    texts = [c.text for c in sorted(al.clauses, key=lambda c: c.start)]
    g = dg.classify(i, r, al, _jp(texts, [0.1] * len(texts), ["abnormal"] * len(texts)))
    assert [x.tier for x in g if x.runs][0] == "synth"


from rapid_reports_ai.review_engine.items import ReviewItem, Span, text_hash

RUN = "00000000-0000-0000-0000-0000000000f1"


def _item(kind, report, text, form=None, cls="info", pointer=None):
    s = report.index(text)
    ev = {} if form is None else {"form": form}
    if pointer is not None:
        ev["pointer"] = pointer
    return ReviewItem(key=f"k-{kind}-{s}", report_id="00000000-0000-0000-0000-000000000001", run_id=RUN,
                      lane="accuracy", detectors=["t"], kind=kind, cls=cls, section="FINDINGS",
                      anchor=Span(start=s, end=s + len(text), text=text, text_hash=text_hash(report)),
                      label="", reason="", evidence=ev, status="open", history=[])


def _apply(p, types, neg=(), brief=()):
    i = inp(RPT, DIC)
    al = align(RPT, DIC, "", i.artifacts.sections)
    g = dg.classify(i, RPT, al, _jp(CL, p, types))
    return dg.apply(i, RUN, al, g, list(neg), list(brief))


def test_live_builds_synthesis_on_the_added_words_and_a_recommendation():
    prov, neg, brief, log = _apply([0.3, 0.9, 0.9, 0.9, 0.0], ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"])
    syn = [it for it in prov if it.kind == "ai_generated"]
    rec = [it for it in prov if it.kind == "recommendation"]
    assert [it.anchor.text for it in syn] == ["crescentic"]
    assert syn[0].evidence["form"] == "synthesis" and syn[0].evidence["source"] == "dictated_gate"
    assert [it.anchor.text for it in rec] == ["Repeat CT head in 6 hours is recommended."]
    assert rec[0].edit is not None
    assert log["synthesis"] == 1 and log["recommendation"] == 1


def test_live_quiet_clause_without_an_item_gets_a_quiet_one_and_dictated_drops_ai_layer_items():
    green = _item("assumed_normal", RPT, "The liver is normal.", form="normal")
    prov, neg, brief, log = _apply([0.9, 0.9, 0.2, 0.9, 0.9], ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"],
                                   neg=[green])
    assert neg == []                                     # gate says dictated: the radiologist's own text
    quiet = [it for it in prov if it.kind == "assumed_normal"]
    assert [it.anchor.text for it in quiet] == ["no contralateral adnexal mass"]    # mixed type: the negation only
    assert quiet[0].evidence["form"] == "normal"
    assert log["dropped"] == [green.key]


def test_live_keeps_check_cards_on_dictated_clauses():
    card = _item("check", RPT, "The liver is normal.", cls="action")
    _, neg, _, _ = _apply([0.9] * 5, ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"], neg=[card])
    assert neg == [card]


def test_live_quiet_clause_already_covered_adds_nothing():
    amber = _item("assumed_normal", RPT, "The liver is normal.", form="negative", pointer="x")
    prov, neg, _, _ = _apply([0.9, 0.1, 0.9, 0.9, 0.9], ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"],
                             neg=[amber])
    assert neg == [amber] and [it for it in prov if it.kind == "assumed_normal"] == []


def test_apply_does_not_mutate_its_inputs():
    green = _item("assumed_normal", RPT, "The liver is normal.", form="normal")
    neg = [green]
    i = inp(RPT, DIC)
    al = align(RPT, DIC, "", i.artifacts.sections)
    g = dg.classify(i, RPT, al, _jp(CL, [0.9] * 5, ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"]))
    dg.apply(i, RUN, al, g, neg, [])
    assert neg == [green]


def test_shadow_log_records_tiers_and_what_tinted_each_clause_today():
    green = _item("assumed_normal", RPT, "The liver is normal.", form="normal")
    i = inp(RPT, DIC)
    al = align(RPT, DIC, "", i.artifacts.sections)
    g = dg.classify(i, RPT, al, _jp(CL, [0.3, 0.9, 0.2, 0.9, 0.0], ["abnormal", "normal", "mixed", "abnormal", "not_a_finding"]))
    log = dg.shadow_log(g, [green])
    assert log["mode"] == "shadow"
    assert [c["tier"] for c in log["clauses"]] == ["synth", "dictated", "quiet", "dictated", "rec"]
    assert log["clauses"][1]["old"] == ["assumed_normal:normal"]
    assert log["counts"] == {"synth": 1, "dictated": 2, "quiet": 1, "rec": 1}
    assert log["added_plain_today"] == 3                 # synth, quiet and rec clauses with no item today
    assert log["dictated_tinted_today"] == 1


def test_a_bolted_on_negative_is_quiet_and_its_quiet_item_covers_only_the_negation():
    r = "FINDINGS:\nRLL consolidation without cavitation.\n"
    c = ["RLL consolidation without cavitation."]
    i = inp(r, "- RLL consolidation")
    al = align(r, "- RLL consolidation", "", i.artifacts.sections)
    g = dg.classify(i, r, al, _jp(c, [0.1], ["abnormal"]))
    assert g[0].tier == "quiet"
    prov, *_ = dg.apply(i, RUN, al, g, [], [])
    assert [it.anchor.text for it in prov if it.kind == "assumed_normal"] == ["without cavitation"]


def test_state_with_no_dictated_findings_is_not_none():
    i = inp("FINDINGS:\nX.", "")
    i.artifacts.dictated_findings = None
    assert dg.state(i).endswith("DICTATED FINDINGS:\n")
