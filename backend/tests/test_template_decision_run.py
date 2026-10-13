"""The decision run (Rules-step spec, "New flow" step 2): Qwen proposes, code checks every quote, Jev decides."""
import pytest

from rapid_reports_ai import template_decision_run as R
from tests.test_template_sheet_lab_prompts import CLINICAL

EX = ["Findings: LVEF 55%. ECV 28%. No previous imaging.",
      "Findings: LVEF 60%. Compared with CT of 01/01/2020.",
      "Findings: LVEF 50%. ECV 30%. No previous imaging."]


def test_prompt_is_case_agnostic():
    # "contrast" is one of the four standard study-level concepts the spec names (every modality); nothing else
    for word in CLINICAL:
        if word == "contrast":
            continue
        assert word not in R.SYSTEM.lower(), word


def test_user_prompt_numbers_the_reports():
    u = R.user_prompt(["A.", "B."], "<scan>")
    assert "SCAN TYPE: <scan>" in u and "### Report 1\nA." in u and "### Report 2\nB." in u


def test_verified_ignores_case_and_spacing_and_checks_the_cited_report():
    assert R.verified(R.Quote(report=1, text="ecv  28%"), EX)
    assert not R.verified(R.Quote(report=2, text="ECV 28%"), EX)      # not in report 2
    assert not R.verified(R.Quote(report=9, text="LVEF"), EX)
    assert not R.verified(R.Quote(report=1, text="  "), EX)


def test_check_quotes_drops_unverifiable_quotes_and_empty_candidates():
    out = R.RunOutput(
        values=[R.ValueCandidate(name="LVEF", quotes=[R.Quote(report=1, text="LVEF 55%"), R.Quote(report=2, text="LVEF 99%")]),
                R.ValueCandidate(name="Invented", quotes=[R.Quote(report=1, text="never written")]),
                R.ValueCandidate(name='Bad "name"', quotes=[R.Quote(report=1, text="LVEF 55%")])],
        concepts=[R.ConceptWording(concept="comparison", state="none", text="No previous imaging.",
                                   quotes=[R.Quote(report=1, text="No previous imaging.")]),
                  R.ConceptWording(concept="comparison", state="compared", text="Compared with {study}.",
                                   quotes=[R.Quote(report=3, text="Compared with CT")])],
        habits=[R.HabitCandidate(finding="x", habit="y", reports=[1, 3]), R.HabitCandidate(finding="z", habit="w", reports=[2])])
    run = R.check_quotes(out, EX)
    assert [v.name for v in run.values] == ["LVEF"] and len(run.values[0].quotes) == 1
    assert [c.state for c in run.concepts] == ["none"]
    assert [h.finding for h in run.habits] == ["x"]
    assert run.dropped_quotes == 3 and run.ok
    bad = R.RunOutput(concepts=[R.ConceptWording(concept="contrast", state="none", text="x.",
                                                 quotes=[R.Quote(report=1, text="LVEF 55%")])])
    assert R.check_quotes(bad, EX).concepts == []                     # a state the concept does not have


import httpx

from rapid_reports_ai import template_decisions as td


def _jev(scores_by_report):
    """A transport answering each report's concept questions with the given scores (by concept order)."""
    def handler(request):
        import json
        body = json.loads(request.content)
        report = next(i for i, ex in enumerate(EX) if ex in body["state"])
        return httpx.Response(200, json={"answers": {f"c{i}": {"noul": s}
                                                     for i, s in enumerate(scores_by_report[report])}})
    return httpx.MockTransport(handler)


async def test_ask_states_lists_the_reports_jev_says_state_each_concept():
    t = _jev([[0.9, 0.1, 0.0, 0.0], [0.8, 0.6, 0.0, 0.2], [0.4, 0.0, 0.0, 0.0]])
    states = await R.ask_states(EX, transport=t)
    assert states == {"comparison": [1, 2], "contrast": [2], "sequences": [], "limitation": []}


async def test_ask_states_raises_on_incomplete_answers():
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"answers": {"c0": {"noul": 0.9}}}))
    with pytest.raises(ValueError):
        await R.ask_states(EX, transport=t)


async def test_run_decisions_combines_qwen_and_jev(monkeypatch):
    async def qwen(examples, scan_type):
        return R.RunOutput(values=[R.ValueCandidate(name="LVEF", quotes=[R.Quote(report=1, text="LVEF 55%")])])

    async def states(examples, transport=None):
        return {n: [] for n in td.CONCEPTS}
    monkeypatch.setattr(R, "_qwen", qwen)
    monkeypatch.setattr(R, "ask_states", states)
    run = await R.run_decisions(EX, "<scan>")
    assert run.ok and [v.name for v in run.values] == ["LVEF"] and run.states == {n: [] for n in td.CONCEPTS}


async def test_a_failed_qwen_call_gives_no_run_and_a_failed_jev_call_gives_no_states(monkeypatch):
    async def boom(*a, **k):
        raise TimeoutError()

    async def qwen(examples, scan_type):
        return R.RunOutput()
    monkeypatch.setattr(R, "_qwen", boom)
    monkeypatch.setattr(R, "ask_states", boom)
    run = await R.run_decisions(EX, "<scan>")
    assert run.ok is False and run.error == "TimeoutError"
    monkeypatch.setattr(R, "_qwen", qwen)
    run = await R.run_decisions(EX, "<scan>")
    assert run.ok and run.states is None


def test_evidence_record_is_small_and_names_the_version():
    run = R.DecisionRun(ok=True, habits=[R.HabitCandidate(finding="f", habit="h", reports=[1, 2])], dropped_quotes=2)
    ev = R.evidence(run, {"cards": [1, 2], "more": [], "kept": [3]})
    assert ev["version"] == R.RUN_VERSION and ev["dropped_quotes"] == 2 and ev["cards"] == 2 and ev["kept"] == 1
    assert ev["habits"] == [{"finding": "f", "habit": "h", "reports": [1, 2]}]


# ── review fixes (Phase 2 review) ──────────────────────────────────────────────────────────────────────────────

def test_a_quote_needs_two_words_or_six_characters():
    assert not R.verified(R.Quote(report=1, text="LVEF"), EX)            # one short word
    assert not R.verified(R.Quote(report=1, text="55%"), EX)
    assert R.verified(R.Quote(report=1, text="ECV 28%"), EX)             # two words
    assert R.verified(R.Quote(report=1, text="Findings"), EX)            # six characters or more


def test_value_candidates_with_one_name_are_merged():
    out = R.RunOutput(values=[R.ValueCandidate(name="LVEF", quotes=[R.Quote(report=1, text="LVEF 55%")]),
                              R.ValueCandidate(name="lvef ", quotes=[R.Quote(report=2, text="LVEF 60%"),
                                                                     R.Quote(report=1, text="LVEF 55%")])])
    run = R.check_quotes(out, EX)
    assert [v.name for v in run.values] == ["LVEF"]
    assert [(q.report, q.text) for q in run.values[0].quotes] == [(1, "LVEF 55%"), (2, "LVEF 60%")]


def test_concept_wording_must_match_its_quotes_else_the_first_quote_is_used():
    good = R.ConceptWording(concept="comparison", state="compared", text="Compared with {study} of {date}.",
                            quotes=[R.Quote(report=2, text="Compared with CT of 01/01/2020.")])
    invented = R.ConceptWording(concept="comparison", state="none", text="No prior studies are available.",
                                quotes=[R.Quote(report=1, text="No previous imaging.")])
    run = R.check_quotes(R.RunOutput(concepts=[good, invented]), EX)
    assert [c.text for c in run.concepts] == ["Compared with {study} of {date}.", "No previous imaging."]


# ── after the decision-run lab (2026-10-13) ────────────────────────────────────────────────────────────────────

def test_the_prompt_counts_one_sentence_for_one_concept_and_asks_for_the_shortest_span():
    assert "one concept only" in R.SYSTEM and "shortest span" in R.SYSTEM


def test_sequences_and_limitation_questions_ask_whether_the_report_mentions_the_concept_at_all():
    for name in ("comparison", "contrast", "limitation"):
        assert "whether" in td.CONCEPTS[name].question.lower(), name
    # the follow-up lab's arm b: the report lists the acquisitions, or says the protocol was complete or incomplete
    assert td.CONCEPTS["sequences"].question == (
        "Does this report list the acquisitions performed (sequences, series, phases or views), or say the planned "
        "protocol was complete or incomplete?")
    for word in CLINICAL:
        if word == "contrast":
            continue
        for c in td.CONCEPTS.values():
            assert word not in c.question.lower(), (c.name, word)


def test_wording_made_of_slots_only_is_replaced_by_its_quote():
    w = R.ConceptWording(concept="comparison", state="compared", text="{study} {date}",
                         quotes=[R.Quote(report=2, text="Compared with CT of 01/01/2020.")])
    assert [c.text for c in R.check_quotes(R.RunOutput(concepts=[w]), EX).concepts] == \
        ["Compared with CT of 01/01/2020."]


def test_a_quote_with_braces_is_never_used_as_wording():
    ex = ["Findings: none. Compared with study {A} of today."]
    w = R.ConceptWording(concept="comparison", state="compared", text="Invented wording.",
                         quotes=[R.Quote(report=1, text="Compared with study {A} of today.")])
    assert R.check_quotes(R.RunOutput(concepts=[w]), ex).concepts == []


class _Result:
    def __init__(self, output):
        self.output = output


async def test_a_failed_qwen_call_falls_back_to_gpt_oss_with_room_for_its_output(monkeypatch):
    from rapid_reports_ai import enhancement_utils as eu
    calls = []

    async def fake(model_name, output_type, system_prompt, user_prompt, api_key, model_settings=None, **k):
        calls.append((model_name, model_settings))
        if model_name == eu.MODEL_CONFIG["SKILL_SHEET_ANALYZER"]:
            raise RuntimeError("Exceeded maximum output retries (2)")
        return _Result(R.RunOutput(values=[R.ValueCandidate(name="LVEF", quotes=[R.Quote(report=1, text="LVEF 55%")])]))
    monkeypatch.setattr(eu, "_run_agent_with_model", fake)
    out = await R._qwen(EX, "<scan>")
    assert [m for m, _ in calls] == [eu.MODEL_CONFIG["SKILL_SHEET_ANALYZER"], eu.MODEL_CONFIG["STACK_REVIEW_FALLBACK"]]
    assert calls[1][1]["max_tokens"] >= eu.TOKEN_CAP_FLOOR     # gpt-oss reasons into the same cap: 6000 truncated it
    assert out.values[0].name == "LVEF"


def test_timeouts_after_the_lab():
    assert R.QWEN_TIMEOUT_S == 40.0 and R.RUN_TIMEOUT_S <= 60.0


async def test_the_whole_run_is_bounded(monkeypatch):
    import asyncio

    async def slow(examples, scan_type):
        await asyncio.sleep(5)

    async def states(examples, transport=None):
        return {n: [] for n in td.CONCEPTS}
    monkeypatch.setattr(R, "_qwen", slow)
    monkeypatch.setattr(R, "ask_states", states)
    monkeypatch.setattr(R, "RUN_TIMEOUT_S", 0.05)
    run = await R.run_decisions(EX, "<scan>")
    assert run.ok is False and run.error == "TimeoutError" and run.ms < 2000
