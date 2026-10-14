import json

import httpx

from rapid_reports_ai.hybrid_stack import jev_stack as J
from rapid_reports_ai.hybrid_stack import normals as N
from rapid_reports_ai.hybrid_stack.sides import side_label, side_pairs

R_K, L_K = "The right kidney is normal.", "The left kidney is normal."
R_H, L_H = "No right hydronephrosis.", "No left hydronephrosis."
KIDNEYS = {"Kidneys": [R_K, L_K, R_H, L_H, "The bladder is normal."], "Liver": ["The liver is normal."]}


def test_a_pair_is_two_sentences_that_match_once_the_side_word_is_swapped():
    assert side_pairs([R_K, L_K, R_H, L_H, "The bladder is normal."]) == [(0, 1), (2, 3)]
    assert side_pairs([L_H, "The liver is normal.", R_H]) == [(2, 0)]   # (right, left), whatever the order
    assert side_pairs(["The Right kidney is normal", L_K]) == [(0, 1)]   # case and the final stop aside


def test_no_pair_without_a_side_twin_or_with_both_sides_in_one_sentence():
    assert side_pairs([R_K, "The left kidney is small."]) == []
    assert side_pairs(["The right and left kidneys are normal.", "The left and right kidneys are normal."]) == []
    assert side_pairs(["The kidneys are normal.", "The ureters are normal."]) == []
    assert side_pairs([R_K, R_K]) == []


def test_side_label_names_both_sides():
    assert side_label(R_K) == "The right/left kidney is normal."
    assert side_label(R_H) == "No right/left hydronephrosis."


async def test_ask_sides_is_one_call_with_one_question_per_pair(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"answers": {"side_0": {"noul": 0.1}, "side_1": {"noul": 0.95}}})
    out = await J.ask_sides("Simple cyst in the kidney.", [(R_K, L_K), (R_H, L_H)], transport=httpx.MockTransport(handler))
    assert out == [0.1, 0.95]
    assert set(seen["questions"]) == {"side_0", "side_1"}
    assert seen["state"] == "DICTATION:\nSimple cyst in the kidney."
    q = seen["questions"]["side_0"]
    assert q["type"] == "noul" and R_K in q["instructions"] and L_K in q["instructions"] and set(q["criteria"]) == {"true", "false"}
    assert await J.ask_sides("x", []) == []


async def test_ask_sides_fails_on_a_missing_answer_rather_than_reading_it(monkeypatch):
    import pytest
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    t = httpx.MockTransport(lambda req: httpx.Response(200, json={"answers": {"side_0": {"noul": 0.2}}}))
    with pytest.raises(ValueError):
        await J.ask_sides("x", [(R_K, L_K), (R_H, L_H)], transport=t)


def _rows(table):
    async def fake(dictation, sentences, removed, **k):
        return [J.RowCheck(*table.get(s, (0.0, 0.0, 0.0))) for s in sentences]
    return fake


def _sides(scores, calls):
    async def fake(dictation, pairs):
        calls.append(list(pairs))
        return [scores.get(p[0], 0.0) for p in pairs]
    return fake


async def test_a_sideless_finding_drops_both_sides_and_asks_which_side(monkeypatch):
    calls = []
    monkeypatch.setattr(N, "ask_rows", _rows({R_K: (0.0, 0.9, 0.0), L_K: (0.0, 0.85, 0.0)}))
    monkeypatch.setattr(N, "ask_sides", _sides({R_K: 0.93}, calls))
    out = await N.assumed("Simple cyst in the kidney.", KIDNEYS, ["Kidneys"], [], sides=True,
                          region_text={"Kidneys": "Simple cyst in the kidney."})
    assert calls == [[(R_K, L_K), (R_H, L_H)]]   # every pair of a touched region, in one call
    assert out.side_asks == [{"region": "Kidneys", "sentences": [R_K, L_K], "label": "The right/left kidney is normal.",
                              "score": 0.93}]
    assert out.assumed["Kidneys"] == [R_H, L_H, "The bladder is normal."]
    assert [d["reason"] for d in out.dropped["Kidneys"]] == ["contradicted", "contradicted"]


async def test_a_sideless_finding_drops_both_sides_whatever_jev_read_as_contradicted(monkeypatch):
    # ruling 1, side lab run 1: a side-less finding contradicted only the right (8 cases) or neither side (4)
    monkeypatch.setattr(N, "ask_rows", _rows({R_H: (0.0, 0.9, 0.0)}))
    monkeypatch.setattr(N, "ask_sides", _sides({R_K: 0.8, R_H: 0.9}, []))
    out = await N.assumed("Small cyst and hydronephrosis.", KIDNEYS, ["Kidneys"], [], sides=True)
    assert out.assumed["Kidneys"] == ["The bladder is normal."]
    assert out.dropped["Kidneys"] == [{"sentence": R_K, "reason": "side"}, {"sentence": L_K, "reason": "side"},
                                      {"sentence": R_H, "reason": "contradicted"}, {"sentence": L_H, "reason": "side"}]
    assert [a["sentences"][0] for a in out.side_asks] == [R_K, R_H]


async def test_a_sided_finding_asks_nothing_and_keeps_the_other_side(monkeypatch):
    monkeypatch.setattr(N, "ask_rows", _rows({L_K: (0.0, 0.9, 0.0)}))
    monkeypatch.setattr(N, "ask_sides", _sides({R_K: 0.1}, []))
    out = await N.assumed("Simple cyst in the left kidney.", KIDNEYS, ["Kidneys"], [], sides=True)
    assert out.side_asks == [] and out.side_failed is False
    assert out.assumed["Kidneys"] == [R_K, R_H, L_H, "The bladder is normal."]


async def test_only_pairs_in_a_region_the_dictation_touches_are_asked(monkeypatch):
    calls = []
    monkeypatch.setattr(N, "ask_rows", _rows({"The liver is normal.": (0.0, 0.9, 0.0)}))
    monkeypatch.setattr(N, "ask_sides", _sides({}, calls))
    out = await N.assumed("Liver lesion.", KIDNEYS, ["Liver"], [], sides=True, region_text={"Liver": "Liver lesion."})
    assert calls == [] and out.side_asks == []
    await N.assumed("Kidneys normal.", KIDNEYS, [], [], sides=True, region_text={"Kidneys": "Kidneys normal."})
    assert calls == [[(R_K, L_K), (R_H, L_H)]]   # a dictated-normal region is touched too
    await N.assumed("", KIDNEYS, ["Kidneys"], [], sides=True)
    assert len(calls) == 1   # nothing dictated: nothing asked


async def test_templates_never_ask_which_side(monkeypatch):
    calls = []
    monkeypatch.setattr(N, "ask_rows", _rows({R_K: (0.0, 0.9, 0.0), L_K: (0.0, 0.9, 0.0)}))
    monkeypatch.setattr(N, "ask_sides", _sides({R_K: 1.0}, calls))
    out = await N.assumed("Simple cyst in the kidney.", KIDNEYS, ["Kidneys"], [])
    assert calls == [] and out.side_asks == []


async def test_a_failed_side_question_leaves_the_normals_as_jev_read_them(monkeypatch):
    async def boom(dictation, pairs):
        raise TimeoutError("jev")
    monkeypatch.setattr(N, "ask_rows", _rows({L_K: (0.0, 0.9, 0.0)}))
    monkeypatch.setattr(N, "ask_sides", boom)
    out = await N.assumed("Simple cyst in the kidney.", KIDNEYS, ["Kidneys"], [], sides=True)
    assert out.error is None and out.side_asks == [] and out.side_failed
    assert out.assumed["Kidneys"] == [R_K, R_H, L_H, "The bladder is normal."]
