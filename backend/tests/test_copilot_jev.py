import json

import httpx

from rapid_reports_ai.hybrid_stack.copilot import jev as J


def _jev(scores: dict[str, float], seen: dict):
    def handler(req):
        body = json.loads(req.content)
        seen.update(body)
        return httpx.Response(200, json={"answers": {k: {"noul": scores.get(k, 0.0)} for k in body["questions"]}})
    return httpx.MockTransport(handler)


async def test_coverage_one_call_one_question_per_branch(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}
    out = await J.coverage("chunk text", ["Solid", "Subsolid"], transport=_jev({"b_0": 0.9, "b_1": 0.2}, seen))
    assert out == {"Solid": 0.9, "Subsolid": 0.2}
    assert "Subsolid" in seen["questions"]["b_1"]["instructions"] and seen["state"].startswith("SOURCE:")


def test_exact_quote_normalises_whitespace_and_case():
    assert J.quote_in("Nodules  <6   mm:\n  No   routine follow-up noted.", "nodules <6 mm no routine follow-up noted")
    assert not J.quote_in("Nodules <6 mm", "Nodules <8 mm")
    assert not J.quote_in("x", "")


def test_exact_quote_respects_token_boundaries_not_just_substring():
    # a short number/unit must not match inside a longer one ("6 mm" inside "16 mm"), a longer quote carries this
    assert not J.quote_in("solid nodules measuring up to 16 mm in diameter were noted",
                           "solid nodules measuring up to 6 mm in diameter")
    assert not J.quote_in("follow-up recommended at 13 months for this nodule",
                           "follow-up recommended at 3 months for this nodule")
    assert not J.quote_in("the lesion measured 11.5 cm across the widest axis",
                           "the lesion measured 1.5 cm across the widest axis")
    assert not J.quote_in("repeat CT in 3–6 months is advised for this lesion",
                           "repeat CT in 6 months is advised for this lesion")


def test_exact_quote_has_a_minimum_length():
    assert not J.quote_in("the lesion was large", "mm")


def test_exact_quote_matches_across_symbol_spellings_and_trailing_stop():
    assert J.quote_in("solid nodule >=6mm diameter seen.", "solid nodule ≥ 6 mm diameter")


async def test_evidence_sends_every_claim_to_jev_even_exact_quotes(monkeypatch):
    """Code never approves a claim on exact match alone: an exact quote still goes to Jev, because a verbatim
    quote can belong to the wrong branch, edition or guideline — only Jev's strict wording can tell."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}
    claims = [("No routine follow-up advised", "exact"), ("CT at 3 months", "reworded claim")]
    scores = await J.evidence("SOURCE … No routine follow-up advised …", claims,
                              transport=_jev({"c_0": 0.9, "c_1": 0.85}, seen))
    assert scores == [0.9, 0.85]
    assert list(seen["questions"]) == ["c_0", "c_1"]
    assert "exactly the guideline, edition and category named" in seen["questions"]["c_0"]["instructions"]


async def test_evidence_drops_a_verbatim_sibling_branch_quote_scored_low_by_jev(monkeypatch):
    """A verbatim quote from a sibling branch's row passes the exact-match fast path, but it is still sent to
    Jev, and a low score drops it — the fast path cannot see branch context."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}
    source = "SOURCE … No routine follow-up advised …"
    quote = "No routine follow-up advised"
    claim = "In Fleischner, for Subsolid: No routine follow-up advised"   # wrong branch, same wording
    assert J.exact_signals(source, [(quote, claim)]) == [True]   # the fast path would have passed it
    scores = await J.evidence(source, [(quote, claim)], transport=_jev({"c_0": 0.1}, seen))
    assert scores == [0.1]
    assert list(seen["questions"]) == ["c_0"]


async def test_evidence_empty_claims_makes_no_call():
    assert await J.evidence("abc def ghi jkl", []) == []


def test_exact_signals_reports_the_exact_match_fast_path():
    source = "Nodules <6 mm: No routine follow-up noted."
    assert J.exact_signals(source, [("No routine follow-up noted", "No routine follow-up noted")]) == [True]
    assert J.exact_signals(source, [("CT at 3 months", "CT at 3 months")]) == [False]


async def test_answers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}
    assert await J.answers("material", "Does X change it?", transport=_jev({"q": 0.75}, seen)) == 0.75


async def test_evidence_finds_a_claim_beyond_the_first_window(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(J, "STATE_MAX", 40)

    def handler(req):
        body = json.loads(req.content)
        hit = "needle claim text" in body["state"]
        return httpx.Response(200, json={"answers": {k: {"noul": 0.9 if hit else 0.0} for k in body["questions"]}})
    source = "[a]\nfiller filler text\n\n[b]\nneedle claim text"
    scores = await J.evidence(source, [("no exact quote present here", "needle claim text")],
                               transport=httpx.MockTransport(handler))
    assert scores == [0.9]


def test_windows_split_on_chunk_markers_and_are_capped():
    source = "\n\n".join(f"[u{i}]\n" + ("x" * 30) for i in range(10))
    windows = J._windows(source)
    assert len(windows) <= J.WINDOW_CAP
    assert all(len(w) <= J.STATE_MAX for w in windows)


def test_windows_falls_back_to_paragraph_split_without_markers():
    assert J._windows("one paragraph\n\nanother paragraph") == ["one paragraph\n\nanother paragraph"]


async def test_ask_raises_on_a_malformed_answer_after_one_retry(monkeypatch):
    """A 200 without answers, without an asked key, or with a non-numeric noul is an outage, never a low score."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    for body in ({}, {"answers": {}}, {"answers": {"q": {"noul": None}}}, {"answers": {"q": {"noul": "0.9"}}},
                 {"answers": {"q": {}}}):
        n = {"calls": 0}

        def handler(req, body=body, n=n):
            n["calls"] += 1
            return httpx.Response(200, json=body)
        try:
            await J._ask("SOURCE:\nx", {"q": {"type": "noul", "instructions": "i"}}, transport=httpx.MockTransport(handler))
        except ValueError:
            pass
        else:
            raise AssertionError(f"no raise for {body}")
        assert n["calls"] == 2, body


async def test_ask_retries_once_then_succeeds(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    n = {"calls": 0}

    def handler(req):
        n["calls"] += 1
        if n["calls"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"answers": {"q": {"noul": 0.4}}})
    got = await J._ask("SOURCE:\nx", {"q": {"type": "noul", "instructions": "i"}}, transport=httpx.MockTransport(handler))
    assert got == {"q": 0.4} and n["calls"] == 2


def test_choice_is_strict():
    assert J.choice({"answers": {"p": {"choice": "a", "confidence": 0.7}}}, "p") == ("a", 0.7)
    for body in ({}, {"answers": {}}, {"answers": {"p": {"choice": "a"}}}, {"answers": {"p": {"confidence": 0.7}}}):
        try:
            J.choice(body, "p")
        except ValueError:
            continue
        raise AssertionError(body)
