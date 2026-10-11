import json

import httpx

from rapid_reports_ai.hybrid_stack import items as I
from rapid_reports_ai.hybrid_stack import jev_stack as J


def _raw(*items):
    async def fake(scan_type, history, regions, dictation, not_assessable, removed):
        return [I.RawItem(**it) for it in items]
    return fake


def _checks(table=None):
    """sentence -> (stated, contra, removed); everything else (0, 0, 0)."""
    table = table or {}

    async def fake(dictation, sentences, removed):
        return [J.RowCheck(*table.get(s, (0.0, 0.0, 0.0))) for s in sentences]
    return fake


async def _no_split(negs):
    return [[n] for n in negs]


def _setup(monkeypatch, raw, checks=None, split=_no_split):
    I.clear_cache()
    monkeypatch.setattr(I, "_write", raw)
    monkeypatch.setattr(I, "ask_rows", checks or _checks())
    monkeypatch.setattr(I, "_split_bundled", split)


CYST = {"source_text": "right ovarian cyst", "region": "Pelvic organs", "question": "Ovarian torsion?",
        "rationale": "A cyst with pain leaves torsion open.", "negatives": ["No features of torsion."]}
REF = {"source_text": "", "region": "Appendix", "question": "Appendix normal or inflamed?",
       "rationale": "The history asks it.", "negatives": ["The appendix is normal."]}


async def test_referral_detected_and_only_one_heuristic_kept(monkeypatch):
    _setup(monkeypatch, _raw(CYST, REF, {**REF, "question": "Periappendiceal collection?"}))
    out = await I.update("CT AP", "?appendicitis", ["Pelvic organs"], "A right ovarian cyst.", ["A right ovarian cyst."])
    kinds = [(i.kind, i.question) for i in out.items]
    # the second heuristic candidate stays a finding row; here it repeats the referral's sentence, so it drops
    assert kinds == [("referral", "Appendix normal or inflamed?"), ("finding", "Ovarian torsion?")]
    assert out.error is None and not out.cached


async def test_stated_contradicted_and_removed_sentences_drop_and_an_empty_row_is_answered(monkeypatch):
    item = {**CYST, "negatives": ["No features of torsion.", "No haemorrhage in the cyst.", "The left ovary is normal."]}
    checks = _checks({"No features of torsion.": (0.9, 0.0, 0.0), "No haemorrhage in the cyst.": (0.0, 0.8, 0.0),
                      "The left ovary is normal.": (0.0, 0.0, 0.7)})
    _setup(monkeypatch, _raw(item), checks)
    out = await I.update("CT AP", "", ["Pelvic organs"], "A cyst. No features of torsion.", ["A cyst."])
    [row] = out.items
    assert row.sentences == [] and row.answered is True


async def test_split_parts_stay_in_their_row_and_rows_keep_two_sentences(monkeypatch):
    item = {**CYST, "negatives": ["No torsion or rupture.", "No free fluid."]}

    async def split(negs):
        return [["No torsion", "No rupture"] if n == "No torsion or rupture." else [n] for n in negs]
    _setup(monkeypatch, _raw(item), split=split)
    out = await I.update("CT AP", "", ["Pelvic organs"], "A cyst.", ["A cyst."])
    assert out.items[0].sentences == ["No torsion.", "No rupture."]


async def test_caps_apply_after_the_checks(monkeypatch):
    rows = [{**CYST, "question": f"Q{i}?", "negatives": [f"No thing {i}."]} for i in range(4)]
    rows.append({**CYST, "region": "Liver", "question": "L1?", "negatives": ["No liver thing."]})
    rows.append({**CYST, "region": "Kidneys", "question": "K1?", "negatives": ["No kidney thing."]})
    # Q0 is answered by the dictation, so it frees a slot in its region
    _setup(monkeypatch, _raw(*rows), _checks({"No thing 0.": (0.95, 0.0, 0.0)}))
    out = await I.update("CT AP", "", ["Pelvic organs", "Liver", "Kidneys"], "A right ovarian cyst.", ["x"])
    open_rows = [i.question for i in out.items if not i.answered]
    assert open_rows == ["Q1?", "Q2?", "L1?", "K1?"]          # 2 per region, 4 per case
    assert [i.question for i in out.items if i.answered] == ["Q0?"]
    assert [i.question for i in out.capped] == ["Q3?"]


async def test_exact_repeats_drop_and_ids_are_stable(monkeypatch):
    item = {**CYST, "negatives": ["No free fluid.", "no free fluid"]}
    _setup(monkeypatch, _raw(item, {**CYST, "question": "Other?", "negatives": ["No free fluid."]}))
    a = await I.update("CT AP", "", ["Pelvic organs"], "A cyst.", ["A cyst."])
    assert a.items[0].sentences == ["No free fluid."]
    assert len(a.items) == 1                                   # the second row had only the repeat
    b = await I.update("CT AP", "", ["Pelvic organs"], "A cyst. More.", ["A cyst."])
    assert a.items[0].id == b.items[0].id


async def test_cache_reruns_the_checks_on_the_new_dictation(monkeypatch):
    calls = []

    async def raw(*a):
        calls.append(1)
        return [I.RawItem(**CYST)]
    _setup(monkeypatch, raw)
    a = await I.update("CT AP", "", ["Pelvic organs"], "A cyst.", ["A cyst."])
    monkeypatch.setattr(I, "ask_rows", _checks({"No features of torsion.": (0.9, 0.0, 0.0)}))
    b = await I.update("ct  ap", "", ["Pelvic organs"], "A cyst. No features of torsion.", [" A cyst. "])
    assert len(calls) == 1 and b.cached
    assert not a.items[0].answered and b.items[0].answered


async def test_failures(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    _setup(monkeypatch, boom)
    out = await I.update("CT AP", "", [], "x", ["x"])
    assert out.items == [] and "RuntimeError" in out.error

    # Jev down: rows as written, removed filtered by exact match only
    _setup(monkeypatch, _raw({**CYST, "negatives": ["No features of torsion.", "No free fluid."]}), boom)
    out = await I.update("CT AP", "", ["Pelvic organs"], "x", ["x"], removed=["no free fluid"])
    assert out.items[0].sentences == ["No features of torsion."]

    # splitter down: sentences kept
    _setup(monkeypatch, _raw(CYST), split=boom)
    out = await I.update("CT AP", "", ["Pelvic organs"], "x", ["x"])
    assert out.items[0].sentences == ["No features of torsion."]


def test_writer_prompt_carries_removed_and_not_assessable():
    u = I.user_prompt("CT AP", "?appendicitis", ["Liver", "Bowel"], "A cyst.", "Doppler flow", ["No free fluid."])
    assert "REGIONS: Liver, Bowel" in u and "DICTATION:\nA cyst." in u
    assert "NOT ASSESSABLE ON THIS SCAN:\nDoppler flow" in u
    assert "REMOVED BY THE RADIOLOGIST" in u and "- No free fluid." in u
    assert "REMOVED" not in I.user_prompt("CT AP", "", [], "", "", [])
    assert "(nothing dictated yet)" in I.user_prompt("CT AP", "", [], "", "", [])


async def test_ask_rows_payload_and_fates(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"answers": {
            "stated_0": {"noul": 0.9}, "contra_0": {"noul": 0.0}, "removed_0": {"noul": 0.1},
            "stated_1": {"noul": 0.0}, "contra_1": {"noul": 0.1}, "removed_1": {"noul": 0.65}}})
    out = await J.ask_rows("No free gas.", ["No free gas.", "No ascites."], ["No free fluid."],
                           transport=httpx.MockTransport(handler))
    assert set(seen["questions"]) == {"stated_0", "contra_0", "removed_0", "stated_1", "contra_1", "removed_1"}
    assert "REMOVED BY THE RADIOLOGIST:\n- No free fluid." in seen["state"]
    assert [J.row_fate(c) for c in out] == ["answered", "removed"]
    assert J.row_fate(J.RowCheck(0.1, 0.75, 0.0)) == "contradicted"
    assert J.row_fate(J.RowCheck(0.5, 0.5, 0.5)) == "keep"
    assert J.normal_assumed(J.RowCheck(0.29, 0.29, 0.59)) and not J.normal_assumed(J.RowCheck(0.3, 0.0, 0.0))


async def test_ask_rows_without_removed_asks_two_questions(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    def handler(req):
        body = json.loads(req.content)
        assert set(body["questions"]) == {"stated_0", "contra_0"} and "REMOVED" not in body["state"]
        return httpx.Response(200, json={"answers": {}})
    out = await J.ask_rows("x", ["No ascites."], [], transport=httpx.MockTransport(handler))
    assert out == [J.RowCheck(0.0, 0.0, 0.0)]
    assert await J.ask_rows("x", [], ["y"]) == []


async def test_a_sentence_with_a_measurement_is_never_offered(monkeypatch):
    _setup(monkeypatch, _raw({**CYST, "negatives": ["A 5 mm intrauterine gestational sac is seen.", "No free fluid."]}))
    out = await I.update("US pelvis", "?ectopic", ["Uterus"], "A fibroid.", ["A fibroid."])
    assert out.items[0].sentences == ["No free fluid."]


async def test_a_trigger_not_in_the_dictation_is_the_referral_row(monkeypatch):
    _setup(monkeypatch, _raw(CYST, {**REF, "source_text": "?appendicitis"}))
    out = await I.update("CT AP", "?appendicitis", ["Pelvic organs"], "A right ovarian cyst.", ["A right ovarian cyst."])
    assert [(i.kind, i.question) for i in out.items] == [("referral", "Appendix normal or inflamed?"), ("finding", "Ovarian torsion?")]


async def test_an_explicit_referral_kind_wins_even_with_a_dictated_trigger(monkeypatch):
    _setup(monkeypatch, _raw(CYST, {**REF, "kind": "referral", "source_text": "right ovarian cyst"}))
    out = await I.update("CT AP", "?appendicitis", ["Pelvic organs"], "A right ovarian cyst.", ["A right ovarian cyst."])
    assert out.items[0].kind == "referral" and out.items[0].question == "Appendix normal or inflamed?"


async def test_an_explicit_referral_beats_a_paraphrased_finding_which_stays_a_row(monkeypatch):
    para = {**CYST, "source_text": "an ovarian cyst on the right", "question": "Torsion?"}
    _setup(monkeypatch, _raw(para, {**REF, "kind": "referral"}))
    out = await I.update("CT AP", "?appendicitis", ["Pelvic organs"], "A right ovarian cyst.", ["A right ovarian cyst."])
    assert [(i.kind, i.question) for i in out.items] == [("referral", "Appendix normal or inflamed?"), ("finding", "Torsion?")]


async def test_tapped_sentences_the_dictation_now_contradicts_are_returned(monkeypatch):
    _setup(monkeypatch, _raw(CYST), _checks({"No perinephric stranding.": (0.0, 0.9, 0.0)}))
    out = await I.update("CT KUB", "", ["Pelvic organs"], "A right ovarian cyst. Mild perinephric stranding.",
                         ["A right ovarian cyst."], tapped=["No perinephric stranding.", "No hydronephrosis."])
    assert out.contradicted == ["No perinephric stranding."]


async def test_one_referral_row_per_question_the_history_asks(monkeypatch):
    bleed = {"kind": "referral", "source_text": "", "region": "", "question": "Active haemorrhage?",
             "rationale": "", "negatives": ["No active contrast extravasation."]}
    organ = {"kind": "referral", "source_text": "", "region": "", "question": "Solid organ injury?",
             "rationale": "", "negatives": ["No solid organ injury."]}
    _setup(monkeypatch, _raw(bleed, organ))
    out = await I.update("CT trauma", "rule out active haemorrhage and solid organ injury", ["Liver", "Spleen"], "", [])
    assert [(i.kind, i.sentences) for i in out.items] == [("referral", ["No active contrast extravasation."]),
                                                          ("referral", ["No solid organ injury."])]
