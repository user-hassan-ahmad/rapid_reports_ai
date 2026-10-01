from __future__ import annotations

import json

import httpx
import pytest

from rapid_reports_ai.dictation_triage import JEV_MODEL, TRIAGE_QUESTIONS, TriageError
from rapid_reports_ai.jev_questions import QSET_VERSION
from rapid_reports_ai.section_coverage import coverage_questions
from rapid_reports_ai.jev_questions import BOUNDARY_QUESTIONS
from rapid_reports_ai.utterance_bundle import BundleState, JevBundle, bundle_questions

STATE = BundleState(scan_type="CT chest", committed="- 6 mm nodule RUL", active="- no effusion",
                    open_line="there is a", latest_utterance="small pneumothorax",
                    checklist=["LUNGS", "PLEURA"])


def _resp(action="append_new_finding", sections=(0.9, 0.2)):
    probs = {a: 0.0 for a in TRIAGE_QUESTIONS["action"]["criteria"]}
    probs[action] = 1.0
    answers = {
        "action": {"type": "choice", "choice": action, "confidence": 0.97, "probabilities": probs},
        "is_correction": {"type": "noul", "noul": 0.03},
        "needs_committed_edit": {"type": "noul", "noul": 0.02},
        "standalone": {"type": "noul", "noul": 0.81},
    }
    for i, p in enumerate(sections):
        answers[f"section_{i}"] = {"type": "noul", "noul": p}
    return {"answers": answers, "usage": {"input_tokens": 900, "cost": 3.6e-05}}


def test_questions_reuse_component_texts():
    q = bundle_questions(["LUNGS", "PLEURA"])
    assert set(q) == {"action", "is_correction", "needs_committed_edit", "standalone", "section_0", "section_1"}
    for k in ("action", "is_correction", "needs_committed_edit"):
        assert q[k] == TRIAGE_QUESTIONS[k]
    assert "open line plus the latest utterance" in q["standalone"]["instructions"]
    assert q["standalone"]["instructions"].replace(
        "the open line plus the latest utterance", "the buffered words plus the chunk"
    ) == BOUNDARY_QUESTIONS["standalone"]["instructions"]
    ref = coverage_questions(["PLEURA"])["PLEURA"]
    assert q["section_1"]["criteria"] == ref["criteria"]
    assert "COMMITTED plus ACTIVE" in q["section_1"]["instructions"] and "PLEURA" in q["section_1"]["instructions"]


def test_questions_without_checklist():
    assert set(bundle_questions([])) == {"action", "is_correction", "needs_committed_edit", "standalone"}


async def test_request_and_parse():
    captured = {}

    def handler(req):
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json=_resp())

    d = await JevBundle(api_key="k", transport=httpx.MockTransport(handler)).classify(STATE)
    body = captured["body"]
    assert body["model"] == JEV_MODEL
    assert body["state"] == {"scan_type": "CT chest", "committed": "- 6 mm nodule RUL", "active": "- no effusion",
                             "open_line": "there is a", "latest_utterance": "small pneumothorax",
                             "checklist": ["LUNGS", "PLEURA"]}
    assert set(body["questions"]) == set(bundle_questions(["LUNGS", "PLEURA"]))
    assert d.triage.action == "append_new_finding" and d.triage.confidence == 0.97
    assert d.standalone == 0.81
    assert d.coverage == {"LUNGS": 0.9, "PLEURA": 0.2}
    assert d.n_questions == 6 and d.cost_usd == 3.6e-05 and d.latency_ms >= 0
    assert d.qset == QSET_VERSION


async def test_missing_section_answer_raises():
    data = _resp()
    del data["answers"]["section_1"]
    t = httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    with pytest.raises(TriageError, match="section_1"):
        await JevBundle(api_key="k", transport=t).classify(STATE)


async def test_http_error_raises():
    t = httpx.MockTransport(lambda req: httpx.Response(502, text="bad gateway"))
    with pytest.raises(TriageError, match="502"):
        await JevBundle(api_key="k", transport=t).classify(STATE)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(TriageError):
        JevBundle()


async def test_word_sense_questions_are_asked_and_parsed_when_requested():
    state = BundleState(scan_type="CT", committed="", active="The spleen is normal.", open_line="",
                        latest_utterance="The renal glands are also normal.", checklist=[])
    captured = {}

    def handler(req):
        captured["body"] = json.loads(req.content)
        data = _resp(sections=())
        for k in captured["body"]["questions"]:
            if k.startswith("word_sense_"):
                data["answers"][k] = {"type": "noul", "noul": 0.37 if k == "word_sense_1" else 0.9}
        return httpx.Response(200, json=data)

    d = await JevBundle(api_key="k", transport=httpx.MockTransport(handler)).classify(state, word_sense=True)
    qs = captured["body"]["questions"]
    assert "'renal'" in qs["word_sense_0"]["instructions"] and "'glands'" in qs["word_sense_1"]["instructions"]
    assert d.word_sense == (("renal", 0.9), ("glands", 0.37), ("normal", 0.9))  # "also" is a function word


async def test_word_sense_is_not_asked_by_default():
    captured = {}

    def handler(req):
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json=_resp())

    d = await JevBundle(api_key="k", transport=httpx.MockTransport(handler)).classify(STATE)
    assert not any(k.startswith("word_sense_") for k in captured["body"]["questions"]) and d.word_sense == ()
