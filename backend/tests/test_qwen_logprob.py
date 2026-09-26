from __future__ import annotations

import json
from math import log

import httpx
import pytest

from rapid_reports_ai.dictation_triage import TRIAGE_QUESTIONS
from rapid_reports_ai.scripts.qwen_logprob import (
    QwenLogprob,
    QwenLogprobError,
    choice_messages,
    choice_probs,
    noul_messages,
    noul_prob,
)
from rapid_reports_ai.section_coverage import coverage_questions

STATE = {"scan_type": "CT chest", "latest_utterance": "no effusion"}


def lp(pairs):
    return [{"token": t, "logprob": log(p)} for t, p in pairs]


def test_choice_messages_use_the_question_text_verbatim():
    q = TRIAGE_QUESTIONS["action"]
    sys_msg, user_msg = choice_messages(STATE, q)
    assert q["instructions"] in sys_msg["content"]
    for i, (name, desc) in enumerate(q["criteria"].items(), start=1):
        assert f"{i}. {name}: {desc}" in sys_msg["content"]
    assert "option number only" in sys_msg["content"]
    assert json.loads(user_msg["content"]) == STATE


def test_noul_messages_include_criteria_when_present():
    q = coverage_questions(["PLEURA"])["PLEURA"]
    sys_msg, _ = noul_messages(STATE, q)
    assert q["instructions"] in sys_msg["content"]
    assert q["criteria"]["true"] in sys_msg["content"] and q["criteria"]["false"] in sys_msg["content"]
    bare, _ = noul_messages(STATE, TRIAGE_QUESTIONS["is_correction"])
    assert "True when" not in bare["content"]


def test_choice_probs_renormalises_over_valid_digits():
    got = choice_probs(lp([("2", 0.6), (" 1", 0.2), ("x", 0.1), ("2.", 0.05)]), ["a", "b", "c"])
    assert got == {"a": pytest.approx(0.25), "b": pytest.approx(0.75), "c": 0.0}
    with pytest.raises(QwenLogprobError):
        choice_probs(lp([("x", 0.9), ("7", 0.1)]), ["a", "b"])


def test_noul_prob_merges_case_and_space_variants():
    assert noul_prob(lp([("yes", 0.5), (" Yes", 0.1), ("no", 0.3)])) == pytest.approx(0.6 / 0.9)
    assert noul_prob(lp([("No", 0.99), ("maybe", 0.01)])) == 0.0
    with pytest.raises(QwenLogprobError):
        noul_prob(lp([("maybe", 1.0)]))


def _completion(pairs):
    return {"choices": [{"message": {"content": pairs[0][0]}, "logprobs": {"content": [
        {"token": pairs[0][0], "logprob": log(pairs[0][1]), "top_logprobs": lp(pairs)}]}}]}


async def test_answer_returns_jev_shaped_answers():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        if "option number" in body["messages"][0]["content"]:
            return httpx.Response(200, json=_completion([("1", 0.9), ("3", 0.1)]))
        return httpx.Response(200, json=_completion([("no", 0.8), ("yes", 0.2)]))

    qwen = QwenLogprob(api_key="k", transport=httpx.MockTransport(handler))
    ans = await qwen.answer(STATE, TRIAGE_QUESTIONS)
    assert ans["action"]["choice"] == "append_new_finding"
    assert ans["action"]["confidence"] == pytest.approx(0.9)
    assert ans["action"]["probabilities"]["restate_existing_finding"] == pytest.approx(0.1)
    assert ans["is_correction"]["noul"] == pytest.approx(0.2)
    assert len(seen) == 3
    b = seen[0]
    assert b["model"] == "qwen-3.8-27b" and b["reasoning_effort"] == "none" and b["logprobs"] is True
    assert b["temperature"] == 0
