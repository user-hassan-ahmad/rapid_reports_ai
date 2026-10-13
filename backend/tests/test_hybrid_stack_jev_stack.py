import json

import httpx

from rapid_reports_ai.hybrid_stack import jev_stack as J


def test_decide_accept_needs_a_named_chip_and_an_accept_command():
    assert J.decide_command({"command": "accept_suggestion", "confidence": 0.3, "region": None, "chip": "No free gas."}) == {
        "action": "accept", "region": None, "chip": "No free gas."}
    # a correction that names a chip is dictation: the radiologist's words are never replaced
    assert J.decide_command({"command": "correct", "confidence": 0.9, "region": None, "chip": "No free gas."})["action"] == "dictate"
    assert J.decide_command({"command": "dictate", "confidence": 0.9, "region": None, "chip": "No free gas."})["action"] == "dictate"
    assert J.decide_command({"command": "accept_suggestion", "confidence": 0.9, "region": None, "chip": None})["action"] == "dictate"


def test_decide_delete_at_threshold_keeps_the_region():
    d = J.decide_command({"command": "delete", "confidence": 0.6, "region": "Liver", "chip": None})
    assert d == {"action": "delete", "region": "Liver", "chip": None}
    assert J.decide_command({"command": "delete", "confidence": 0.59, "region": "Liver", "chip": None})["action"] == "dictate"


def test_decide_correct_and_send_to_region_are_dictation():
    for c in ("correct", "send_to_region", None):
        assert J.decide_command({"command": c, "confidence": 1.0, "region": "Liver", "chip": None})["action"] == "dictate"


async def test_ask_command_payload_and_parse(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"answers": {
            "command": {"choice": "accept_suggestion", "confidence": 0.8},
            "target_region": {"choice": "none"}, "target_chip": {"choice": "chip_1"}}})
    out = await J.ask_command("The liver is normal.", "Accept no ascites.", ["Liver", "Peritoneum"],
                              ["No free gas.", "No ascites."], transport=httpx.MockTransport(handler))
    assert set(seen["questions"]) == {"command", "target_region", "target_chip"}
    assert "LATEST UTTERANCE:\nAccept no ascites." in seen["state"]
    assert out == {"command": "accept_suggestion", "confidence": 0.8, "region": None, "chip": "No ascites."}


async def test_ask_stated_returns_one_score_per_chip(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    def handler(req):
        body = json.loads(req.content)
        assert list(body["questions"]) == ["chip_0", "chip_1"]
        return httpx.Response(200, json={"answers": {"chip_0": {"noul": 0.9}, "chip_1": {"noul": 0.1}}})
    assert await J.ask_stated("No free gas.", ["No free gas.", "No ascites."],
                              transport=httpx.MockTransport(handler)) == [0.9, 0.1]
    assert await J.ask_stated("x", []) == []


async def test_ask_conditions_reads_each_conditions_score(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"answers": {"cond_0": {"noul": 0.8}}})   # cond_1 missing
    out = await J.ask_conditions("CLINICAL HISTORY:\nx", ["no prior study", "contrast given"],
                                 transport=httpx.MockTransport(handler))
    assert out == [0.8, 0.0]
    assert list(seen["questions"]) == ["cond_0", "cond_1"]
    assert seen["questions"]["cond_0"]["instructions"].endswith("Condition: no prior study")

    def fail(req):
        raise AssertionError("no call without conditions")
    assert await J.ask_conditions("x", [], transport=httpx.MockTransport(fail)) == []


async def test_ask_values_asks_stated_and_where_per_item_in_one_call(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"answers": {
            "value_0": {"noul": 0.9}, "where_0": {"choice": "s_1", "probabilities": {"s_0": 0.2, "s_1": 0.7, "none": 0.1}},
            "value_1": {"noul": 0.2}, "where_1": {"choice": "none"},
            "value_2": {"noul": 0.8}, "where_2": {"choice": "s_7"}}})
    out = await J.ask_values("LVEF 45%. RVEF 50%.", ["LVEF", "RVEF", "LV mass"], ["LVEF 45%.", "RVEF 50%."],
                             transport=httpx.MockTransport(handler))
    assert out == [(0.9, 1, [0.2, 0.7]), (0.2, None, None), (0.8, None, None)]   # out-of-range names no clause; scores
    # are the where-choice's per-clause probabilities (None when Jev sent none)
    assert set(seen["questions"]) == {"value_0", "where_0", "value_1", "where_1", "value_2", "where_2"}
    assert seen["state"] == "DICTATION:\nLVEF 45%. RVEF 50%."
    assert seen["questions"]["value_0"]["type"] == "noul"
    assert seen["questions"]["value_0"]["instructions"].endswith("LVEF")      # template_brief.q_stated
    w = seen["questions"]["where_1"]
    assert w["type"] == "choice" and w["instructions"].endswith("RVEF")
    assert w["criteria"] == {"s_0": "LVEF 45%.", "s_1": "RVEF 50%.", "none": "No SENTENCE gives this item's value."}


async def test_ask_values_splits_items_into_parallel_batches_keeping_global_keys(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    asked = []

    def handler(req):
        qs = json.loads(req.content)["questions"]
        asked.append(sorted(qs))
        return httpx.Response(200, json={"answers": {
            k: ({"noul": 0.9} if k.startswith("value_") else {"choice": "s_0"}) for k in qs}})
    items = ["A", "B", "C", "D", "E", "F"]
    out = await J.ask_values("A 1.", items, ["A 1."], transport=httpx.MockTransport(handler))
    assert out == [(0.9, 0, None)] * 6
    assert J.VALUE_BATCH == 4 and len(asked) == 2
    assert sorted(asked) == [sorted(f"{p}_{i}" for i in range(4) for p in ("value", "where")),
                             sorted(f"{p}_{i}" for i in (4, 5) for p in ("value", "where"))]


async def test_ask_values_without_clauses_asks_only_whether_stated(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"answers": {"value_0": {"noul": 0.7}}})
    assert await J.ask_values("Conus at L1.", ["Conus level"], [], transport=httpx.MockTransport(handler)) == [(0.7, None, None)]
    assert list(seen["questions"]) == ["value_0"]

    def fail(req):
        raise AssertionError("no call without items")
    assert await J.ask_values("x", [], ["x 1"], transport=httpx.MockTransport(fail)) == []


async def test_ask_values_takes_another_stated_wording(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"answers": {"value_0": {"noul": 0.6}}})
    plain = lambda item: {"type": "noul", "instructions": f"The DICTATION states the {item}."}   # noqa: E731
    await J.ask_values("EF 45.", ["LVEF"], [], transport=httpx.MockTransport(handler), stated=plain)
    assert seen["questions"]["value_0"]["instructions"] == "The DICTATION states the LVEF."


def test_the_value_cut_offs_after_the_lab():
    assert J.VALUE_UNQUOTED_MIN == J.STATED_MIN == 0.8     # an item no number maps to: the strict "stated?" bar
    assert not hasattr(J, "VALUE_STATED_MIN")              # Decision 10's clause rule is superseded by number -> item


def test_the_number_item_question_mirrors_the_lab_arm_n1():
    q = J.number_item_question("1010", "Native T1 [[1010]] ms.", ["LVEF", "Native T1 value"])
    assert q == {"type": "choice",
                 "instructions": ("Which required value does the number 1010 in this sentence give? The number is "
                                  "marked [[ ]] in the SENTENCE. SENTENCE: Native T1 [[1010]] ms."),
                 "criteria": {"item_0": "LVEF", "item_1": "Native T1 value",
                              "none": "None of these required values: the number gives something else."}}


async def test_ask_number_items_asks_one_choice_per_number_in_parallel_batches(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        ans = {}
        for k in body["questions"]:
            i = int(k[2:])
            ans[k] = ({"choice": "item_1", "confidence": 0.9, "probabilities": {"item_0": 0.05, "item_1": 0.9, "none": 0.05}}
                      if i == 0 else {"choice": "none", "confidence": 0.7}
                      if i == 1 else {"choice": "item_9", "confidence": 0.8} if i == 2 else {"choice": "item_0"})
        return httpx.Response(200, json={"answers": ans})
    mentions = [(str(n), f"A [[{n}]].") for n in range(12)]
    out = await J.ask_number_items("A 1.", mentions, ["LVEF", "RVEF"], transport=httpx.MockTransport(handler))
    assert out[:4] == [(1, 0.9, [0.05, 0.9]), (None, 0.7, None), (None, 0.8, None), (0, 0.0, None)]
    # none and out-of-range map to no item; the third element is P(each item) when Jev sends probabilities
    assert len(out) == 12 and J.NUMBER_BATCH == 10 and len(bodies) == 2
    assert sorted(len(b["questions"]) for b in bodies) == [2, 10]
    assert all(b["state"] == "DICTATION:\nA 1." for b in bodies)
    b0 = next(b for b in bodies if "n_0" in b["questions"])
    assert b0["questions"]["n_0"] == J.number_item_question("0", "A [[0]].", ["LVEF", "RVEF"])

    def fail(req):
        raise AssertionError("no call")
    assert await J.ask_number_items("x", [], ["LVEF"], transport=httpx.MockTransport(fail)) == []
    assert await J.ask_number_items("x", [("1", "[[1]]")], [], transport=httpx.MockTransport(fail)) == [(None, 0.0, None)]
    assert J.BACKSTOP_MIN == 0.5   # the post-generation backstop is recall-oriented


async def test_ask_report_values_asks_the_report_per_item_in_batches(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        return httpx.Response(200, json={"answers": {k: {"noul": 0.2 if k == "value_4" else 0.9} for k in body["questions"]}})
    items = ["A", "B", "C", "D", "E"]
    out = await J.ask_report_values("Findings:\nA 1.", items, transport=httpx.MockTransport(handler))
    assert out == [0.9, 0.9, 0.9, 0.9, 0.2] and len(bodies) == 2
    assert all(b["state"] == "REPORT:\nFindings:\nA 1." for b in bodies)
    assert bodies[0]["questions"]["value_0"]["instructions"].endswith("A")   # template_brief.q_stated

    def fail(req):
        raise AssertionError("no call without items")
    assert await J.ask_report_values("x", [], transport=httpx.MockTransport(fail)) == []
