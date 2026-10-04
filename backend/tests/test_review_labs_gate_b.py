import json

from rapid_reports_ai.scripts.review_labs import gate_b


def _w(p, obj):
    p.write_text(json.dumps(obj))


def test_gold_candidates_dedupe_and_stable_ids(tmp_path):
    _w(tmp_path / "gold_candidates_B.json", [{"id8": "bbb", "span": "s3", "kind": "other"}])
    _w(tmp_path / "gold_candidates_A.json", [{"id8": "aaa", "span": "s1", "kind": "invented_finding"},
                                              {"id8": "aaa", "span": "s2", "kind": "other"}])
    # duplicate of A's first, in a later file
    _w(tmp_path / "gold_candidates_C.json", [{"id8": "aaa", "span": "s1", "kind": "other"}])
    res = gate_b.gold_candidates(tmp_path)
    assert [(x["id8"], x["span"], x["gid"]) for x in res] == [
        ("aaa", "s1", "g0"), ("aaa", "s2", "g1"), ("bbb", "s3", "g2")]


def test_confirmed_gold_keeps_unsupported_and_overrides_kind(tmp_path):
    _w(tmp_path / "gold_candidates_A.json", [{"id8": "a", "span": "x", "kind": "other"},
                                              {"id8": "a", "span": "y", "kind": "other"},
                                              {"id8": "a", "span": "z", "kind": "other"}])
    _w(tmp_path / "gold.json", {"g0": {"verdict": "unsupported", "kind": "invented_prior"},
                                "g1": {"verdict": "supported"}, "g2": {"verdict": "unsupported"}})
    res = gate_b.confirmed_gold(tmp_path)
    assert [(x["gid"], x["kind"]) for x in res] == [("g0", "invented_prior"), ("g2", "other")]


def test_b2_questions_shapes():
    q = gate_b.b2_question("W1n", "A 5 mm nodule.")
    assert q["type"] == "noul" and q["instructions"].endswith('"A 5 mm nodule."')
    q = gate_b.b2_question("W3c", "A 5 mm nodule.")
    assert q["type"] == "choice" and set(q["criteria"]) == {"stated", "not_stated", "cant_tell"}
    assert "W3n" not in gate_b.B2_ARMS


def test_b2_p_stated_from_answers():
    assert gate_b.p_stated("W1n", {"noul": 0.8}) == 0.8
    assert gate_b.p_stated("W1c", {"choice": "stated", "probabilities": {"stated": 0.7, "not_stated": 0.2, "cant_tell": 0.1}}) == 0.7
    assert gate_b.is_cant_tell("W1c", {"choice": "cant_tell", "probabilities": {"cant_tell": 0.5}})
