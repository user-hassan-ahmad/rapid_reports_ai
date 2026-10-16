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
    asked = [k for _, qs in gate_calls for k in qs]
    assert sorted(k for k in asked if k[0] in "gt") == want
    # log-only r{i}: clauses sharing any dictated content word ("normal" counts: a cost filter, not a decision)
    assert sorted(k for k in asked if k[0] == "r") == ["r0", "r1", "r2", "r3", "r4"]
    assert all(len(qs) <= 12 for _, qs in gate_calls)                  # CHUNK 4 clauses × up to 3 questions
    assert all(s.endswith("DICTATED FINDINGS:\n" + D) for s, _ in gate_calls)
    assert {k for k in jp.gate if k[0] in "gt"} == set(want) and jp.gate_texts == texts


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


def _unit_texts(r, d):
    i = inp(r, d)
    al = align(r, d, "", i.artifacts.sections)
    return i, al, [r[s:e] for s, e, _ in dg.units(al)]


def test_negative_list_is_one_unit_and_a_repeated_sentence_gets_two():
    r = ("FINDINGS:\nThere is no pleural effusion, pneumothorax or consolidation. The liver is normal.\n"
         "IMPRESSION:\nThe liver is normal.\n")
    i, al, texts = _unit_texts(r, "- Liver normal")
    assert texts == ["There is no pleural effusion, pneumothorax or consolidation.", "The liver is normal.",
                     "The liver is normal."]
    g = dg.classify(i, r, al, _jp(texts, [0.1, 0.9, 0.1], ["normal"] * 3))
    assert [x.text for x in g] == texts and all(r[x.start:x.end] == x.text for x in g)
    assert [x.section for x in g] == ["FINDINGS", "FINDINGS", "IMPRESSION"]
    assert [x.tier for x in g] == ["quiet", "dictated", "quiet"]


def test_units_hold_only_real_report_text():
    r = "FINDINGS:\nNo interval change in the liver lesion, but there is a new nodule.\n"
    i, al, texts = _unit_texts(r, "- Liver lesion")
    assert all(t in r for t in texts) and not any(t.startswith("No but") for t in texts)
    assert texts == ["No interval change in the liver lesion, but there is a new nodule."]   # nested head dropped


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
    texts = [r[s:e] for s, e, _ in dg.units(al)]
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


# ── reworded dictated negatives: log-only (lab gate_a/reworded_neg, 2026-10-10) ──────────────────────────────────

def test_reworded_question_only_for_clauses_sharing_a_dictated_word():
    batches = dg.questions(["No rim-enhancing periappendiceal collection.", "The spleen is unremarkable."],
                           "- No organised collection")
    keys = {k for b in batches for k in b}
    assert "r0" in keys and "r1" not in keys
    assert set(dg.q_reworded("x")["criteria"]) == {"restates_with_change", "adds_separate_items", "same_meaning"}
    assert not any(k.startswith("r") for b in dg.questions(["No collection."]) for k in b)   # no dictation given


def test_reworded_score_is_logged_and_never_changes_the_tier():
    r = "FINDINGS:\nNo rim-enhancing periappendiceal collection. The spleen is unremarkable.\n"
    d = "- No organised collection"
    i = inp(r, d)
    al = align(r, d, "", i.artifacts.sections)
    texts = [r[s:e] for s, e, _ in dg.units(al)]
    jp = JevPass(gate_texts=texts)
    for k, _ in enumerate(texts):
        jp.gate[f"g{k}"] = {"probabilities": {"all_stated": 0.1, "some_details_added": 0.9, "not_stated": 0.0}}
        jp.gate[f"t{k}"] = {"probabilities": {"abnormal": 0.0, "normal": 1.0, "mixed": 0.0, "not_a_finding": 0.0}}
    jp.gate["r0"] = {"probabilities": {"restates_with_change": 0.9, "adds_separate_items": 0.05, "same_meaning": 0.05}}
    g = dg.classify(i, r, al, jp)
    assert [x.tier for x in g] == ["quiet", "quiet"]
    assert g[0].reworded == 0.9 and g[1].reworded is None
    assert dg.shadow_log(g, [])["clauses"][0]["reworded"] == 0.9


def test_an_added_clause_with_no_new_content_words_is_not_violet():
    # live 7d24e445: dictation + "is visualised" scored 0.67; no new content word to point at, so the whole
    # dictated sentence went violet. Nothing to highlight means it is the radiologist's own sentence.
    r = "FINDINGS:\nThe appendix is visualised, retrocaecal and mildly thickened. A crescentic mass is present.\n"
    d = "- appendix retrocaecal, mildly thickened\n- mass present"
    i = inp(r, d)
    al = align(r, d, "", i.artifacts.sections)
    texts = [r[s:e] for s, e, _ in dg.units(al)]
    jp = JevPass(gate_texts=texts)
    for k, _ in enumerate(texts):
        jp.gate[f"g{k}"] = {"probabilities": {"all_stated": 0.6, "some_details_added": 0.4, "not_stated": 0.0}}
        jp.gate[f"t{k}"] = {"probabilities": {"abnormal": 1.0, "normal": 0.0, "mixed": 0.0, "not_a_finding": 0.0}}
    g = dg.classify(i, r, al, jp)
    assert [x.tier for x in g] == ["dictated", "synth"]
    assert [r[a:b] for a, b in g[1].runs] == ["crescentic"]
    assert dg.tier_of(0.6, "abnormal", False, False, has_new_words=False) == "dictated"
    assert dg.tier_of(0.6, "not_a_finding", True, False, has_new_words=False) == "rec"   # recs keep their item


# A recommendation the radiologist dictated, reworded by the writer into the impression's last line (integration spec
# D22). The gate scores the rewording below GATE_MIN, so the clause is tier "rec"; the live items must still not call
# it undictated. Synthetic stand-ins for three P3 observations (stack plain(): the confirmed conclusion is one line).
REWORDED_RECS = [
    ("FINDINGS:\nThere is a 4 cm mass in the pancreatic head encasing the SMV.\n\n"
     "IMPRESSION:\nPancreatic head mass encasing the SMV, likely adenocarcinoma. MDT discussion is recommended.\n",
     "4 cm pancreatic head mass encasing the SMV.\n"
     "Pancreatic head mass encasing the SMV, likely adenocarcinoma. MDT discussion.", 0.66),
    ("FINDINGS:\nThere is a 2 cm nodule in the right thyroid lobe.\n\n"
     "IMPRESSION:\nRight thyroid nodule. Non-urgent thyroid ultrasound is recommended.\n",
     "2 cm nodule right thyroid lobe.\nIncidental right thyroid nodule. Thyroid nodule, suggest non-urgent ultrasound.",
     0.65),
    ("FINDINGS:\nThere is a 7 mm solid nodule in the right upper lobe.\n\n"
     "IMPRESSION:\n7 mm right upper lobe nodule. Follow-up CT in 12 months per guidelines.\n",
     "7 mm solid nodule right upper lobe.\n7 mm nodule, follow-up CT in 12 months per guidelines.", 0.55),
]


def _live_rec(report, dictation, rec_p, **kw):
    """Live apply where the gate calls every clause dictated except the recommendation (P(all_stated) `rec_p`)."""
    i, al, g = _rec_gate(report, dictation, rec_p)
    prov, _, _, log = dg.apply(i, RUN, al, g, [], [], **kw)
    return [it.anchor.text for it in prov if it.kind == "recommendation"], log


def _rec_gate(report, dictation, rec_p):
    from rapid_reports_ai.review_engine.provenance import is_recommendation
    i, al, texts = _unit_texts(report, dictation)
    recs = [is_recommendation(t, None, "IMPRESSION") for t in texts]
    jp = _jp(texts, [rec_p if r else 0.9 for r in recs], ["not_a_finding" if r else "abnormal" for r in recs])
    g = dg.classify(i, report, al, jp)
    assert [x.tier for x in g if x.tier == "rec"] == ["rec"]
    return i, al, g


async def _live_rec_jev(monkeypatch, report, dictation, answer):
    """Live: ask_recs (Jev answers every recommendation question with `answer`, or raises it) then apply."""
    i, al, g = _rec_gate(report, dictation, 0.2)
    sent = []

    async def fake(state, qs):
        sent.append((state, qs))
        if isinstance(answer, Exception):
            raise answer
        return {k: answer for k in qs}
    monkeypatch.setattr(rc, "_jev", fake)
    rec_jev, ask_log = await dg.ask_recs(i, al, g)
    prov, _, _, log = dg.apply(i, RUN, al, g, [], [], rec_jev=rec_jev)
    return [it.anchor.text for it in prov if it.kind == "recommendation"], log, ask_log, sent


DICTATED_ANS = {"probabilities": {"stated": 0.1, "synonym_or_equivalent": 0.8, "not_stated": 0.1}}
ADDED_ANS = {"probabilities": {"stated": 0.02, "synonym_or_equivalent": 0.03, "not_stated": 0.95}}
BLENDED = ("FINDINGS:\nThere is a 7 mm solid nodule in the right upper lobe.\n\n"
           "IMPRESSION:\n7 mm right upper lobe nodule. CT in 3 months and refer to MDT.\n",
           "7 mm solid nodule right upper lobe.\n7 mm nodule, suggest CT in 3 months.", "CT in 3 months and refer to MDT.")
TALK = ("FINDINGS:\nA pancreatic mass.\nIMPRESSION:\nPancreatic mass.\nDiscussed with the referring team.\n",
        "- Pancreatic mass\n- Result discussed by phone with Dr Jones, surgical registrar, read-back confirmed",
        "Discussed with the referring team.")


@pytest.mark.asyncio
async def test_jev_decides_a_recommendation_the_word_rule_would_flag(monkeypatch):
    # no pair and no shared words: only Jev knows it was dictated in other words
    r, d, talk = TALK
    recs, log, ask_log, _ = await _live_rec_jev(monkeypatch, r, d, DICTATED_ANS)
    assert recs == [] and log["rec_dictated"] == 1 and log["rec_by_jev"] == 1 and log["rec_by_backstop"] == 0
    recs, log, _, _ = await _live_rec_jev(monkeypatch, r, d, ADDED_ANS)
    assert recs == [talk] and log["rec_dictated"] == 0


@pytest.mark.asyncio
async def test_jev_decides_a_recommendation_the_word_rule_would_clear(monkeypatch):
    # every word is in a dictated line, but Jev says not stated: Jev wins, the item stays
    report, dictation, _ = REWORDED_RECS[2]
    recs, log, _, _ = await _live_rec_jev(monkeypatch, report, dictation, ADDED_ANS)
    assert recs == ["Follow-up CT in 12 months per guidelines."] and log["rec_dictated"] == 0


@pytest.mark.asyncio
async def test_jev_flags_a_blended_recommendation(monkeypatch):
    r, d, flagged = BLENDED
    recs, _, _, _ = await _live_rec_jev(monkeypatch, r, d, ADDED_ANS)
    assert recs == [flagged]


@pytest.mark.asyncio
async def test_ask_recs_sends_one_request_with_the_q3_question_per_recommendation(monkeypatch):
    from rapid_reports_ai.review_engine.provenance import q_synthesis
    r, d, flagged = BLENDED
    _, _, ask_log, sent = await _live_rec_jev(monkeypatch, r, d, ADDED_ANS)
    assert len(sent) == 1 and "DICTATED FINDINGS:" in sent[0][0]
    assert list(sent[0][1].values()) == [q_synthesis(flagged, flagged)]
    assert ask_log["asked"] == 1 and ask_log["error"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [RuntimeError("jev down"), {}, {"choice": "maybe"}])
async def test_the_word_rule_decides_only_when_jev_has_no_answer(monkeypatch, answer):
    report, dictation, _ = REWORDED_RECS[2]
    recs, log, ask_log, _ = await _live_rec_jev(monkeypatch, report, dictation, answer)
    assert recs == [] and log["rec_by_backstop"] == 1                 # the word rule clears the reworded one
    r, d, flagged = BLENDED
    recs, log, _, _ = await _live_rec_jev(monkeypatch, r, d, answer)
    assert recs == [flagged] and log["rec_dictated"] == 0             # and keeps the blended one
    if isinstance(answer, Exception):
        assert ask_log["error"]


@pytest.mark.asyncio
async def test_the_word_rule_never_clears_a_recommendation_the_radiologist_declined(monkeypatch):
    # Jev down; every content word of the report's recommendation is in the dictated line, but the line declines it
    r = ("FINDINGS:\nThere is a 4 mm solid nodule in the right upper lobe.\n\n"
         "IMPRESSION:\n4 mm right upper lobe nodule. Follow-up CT is recommended.\n")
    d = "4 mm solid nodule right upper lobe.\n4 mm nodule, no follow-up CT required."
    recs, log, _, _ = await _live_rec_jev(monkeypatch, r, d, RuntimeError("jev down"))
    assert recs == ["Follow-up CT is recommended."] and log["rec_by_backstop"] == 0


def test_apply_lets_jev_decide_the_answered_recommendations_and_the_word_rule_the_rest():
    r = ("FINDINGS:\nThere is a 7 mm solid nodule in the right upper lobe.\n\n"
         "IMPRESSION:\n7 mm right upper lobe nodule. Follow-up CT in 12 months per guidelines.\n"
         "Referral to the respiratory clinic is advised.\n")
    d = "7 mm solid nodule right upper lobe.\n7 mm nodule, follow-up CT in 12 months per guidelines."
    from rapid_reports_ai.review_engine.provenance import is_recommendation
    i, al, texts = _unit_texts(r, d)
    recs = [is_recommendation(t, None, "IMPRESSION") for t in texts]
    jp = _jp(texts, [0.2 if x else 0.9 for x in recs], ["not_a_finding" if x else "abnormal" for x in recs])
    g = dg.classify(i, r, al, jp)
    rec = [x for x in g if x.tier == "rec"]
    assert len(rec) == 2
    ct = r.index("Follow-up CT in 12 months per guidelines.")
    ref = r.index("Referral to the respiratory clinic is advised.")
    # Jev answered only the referral (added); the CT one is unanswered, so the word rule clears it
    rec_jev = {(ref, ref + len("Referral to the respiratory clinic is advised.")): 0.02,
               (ct, ct + len("Follow-up CT in 12 months per guidelines.")): None}
    prov, _, _, log = dg.apply(i, RUN, al, g, [], [], rec_jev=rec_jev)
    assert [it.anchor.text for it in prov if it.kind == "recommendation"] == [
        "Referral to the respiratory clinic is advised."]
    assert (log["rec_by_jev"], log["rec_by_backstop"]) == (0, 1)


@pytest.mark.asyncio
async def test_ask_recs_asks_nothing_without_a_recommendation(monkeypatch):
    called = []

    async def fake(state, qs):
        called.append(qs)
        return {}
    monkeypatch.setattr(rc, "_jev", fake)
    i, al, texts = _unit_texts("FINDINGS:\nA pancreatic mass.\n", "- Pancreatic mass")
    g = dg.classify(i, "FINDINGS:\nA pancreatic mass.\n", al, _jp(texts, [0.9] * len(texts), ["abnormal"] * len(texts)))
    assert await dg.ask_recs(i, al, g) == ({}, {"asked": 0, "error": None})
    assert called == []


# The word rule below is the backstop when Jev has no answer (no rec_jev): near-verbatim rewordings clear, partial
# overlap keeps the item.
@pytest.mark.parametrize("report,dictation,p", REWORDED_RECS)
def test_backstop_gives_no_item_for_a_reworded_dictated_recommendation(report, dictation, p):
    recs, log = _live_rec(report, dictation, p)
    assert recs == [] and log["recommendation"] == 0 and log["rec_dictated"] == 1


def test_backstop_still_flags_a_recommendation_the_radiologist_did_not_dictate():
    r = ("FINDINGS:\nThere is a 4 cm mass in the pancreatic head encasing the SMV.\n\n"
         "IMPRESSION:\nPancreatic head mass encasing the SMV, likely adenocarcinoma. MDT discussion is recommended.\n")
    for d in ("4 cm pancreatic head mass encasing the SMV.\nPancreatic head mass encasing the SMV, likely adenocarcinoma.",
              "4 cm pancreatic head mass encasing the SMV.\nLikely adenocarcinoma. Suggest follow-up CT in 3 months."):
        recs, log = _live_rec(r, d, 0.1)
        assert recs == ["MDT discussion is recommended."] and log["rec_dictated"] == 0


@pytest.mark.parametrize("report,dictation,flagged", [
    # an undictated referral carried in the same sentence as a dictated follow-up (one shared word, "CT")
    ("FINDINGS:\nThere is a 7 mm solid nodule in the right upper lobe.\n\n"
     "IMPRESSION:\n7 mm right upper lobe nodule. CT in 3 months and refer to MDT.\n",
     "7 mm solid nodule right upper lobe.\n7 mm nodule, suggest CT in 3 months.", "CT in 3 months and refer to MDT."),
    # a different, undictated study sharing only the modality word with the dictated one
    ("FINDINGS:\nThere is a 7 mm solid nodule in the right upper lobe.\n\n"
     "IMPRESSION:\n7 mm right upper lobe nodule. CT abdomen is recommended.\n",
     "7 mm solid nodule right upper lobe.\n7 mm nodule, suggest CT chest in 12 months.", "CT abdomen is recommended."),
    # the same study at a different, undictated interval
    ("FINDINGS:\nThere is a 7 mm solid nodule in the right upper lobe.\n\n"
     "IMPRESSION:\n7 mm right upper lobe nodule. CT in 12 months is recommended.\n",
     "7 mm solid nodule right upper lobe.\n7 mm nodule, suggest CT in 3 months.", "CT in 12 months is recommended."),
])
def test_backstop_flags_a_recommendation_that_only_shares_a_word_with_a_dictated_one(report, dictation, flagged):
    recs, log = _live_rec(report, dictation, 0.1)
    assert recs == [flagged] and log["rec_dictated"] == 0


@pytest.mark.parametrize("text", ["Follow-up CT isn't needed.", "CT needn't be repeated.", "We don't need follow-up.",
                                  "Further imaging cannot be justified.", "Avoid further CT.", "No further imaging.",
                                  "Follow-up not required.", "Nil further.", "Surveillance is unnecessary."])
def test_the_word_rule_sees_negation_and_contractions(text):
    assert dg._NEG.search(text)
