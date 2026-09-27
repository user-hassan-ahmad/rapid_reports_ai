from __future__ import annotations

import asyncio
import json

import httpx

from rapid_reports_ai.jev_audit import JevAudit
from rapid_reports_ai.jev_questions import AUDIT_BANDS, audit_questions
from rapid_reports_ai.audit_candidates import candidates

TEXT = "No pleural effusion. The heart is normal in size. Small left pleural effusion."


def _transport(score_for):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        answers = {k: {"noul": score_for(q["instructions"])} for k, q in body["questions"].items()}
        return httpx.Response(200, json={"answers": answers, "usage": {"input_tokens": 500}})
    return httpx.MockTransport(handler)


def test_one_noul_per_candidate_with_structural_wording():
    cs = candidates(TEXT)
    qs = audit_questions(cs)
    assert len(qs) == len(cs) and all(q["type"] == "noul" for q in qs.values())
    assert all(set(q["criteria"]) == {"true", "false"} for q in qs.values())


def test_a_low_score_flags_the_later_statement_and_marks_the_earlier():
    audit = JevAudit(api_key="k", transport=_transport(lambda ins: 0.05 if "can both be true" in ins else 0.95))
    flags = asyncio.run(audit.check("CT chest", "", TEXT))
    [f] = [f for f in flags if f.kind == "internal_contradiction"]
    assert TEXT[f.start:f.end] == "Small left pleural effusion."
    assert TEXT[f.related_start:f.related_end] == "No pleural effusion."
    assert f.severity == "medium"


def test_scores_above_the_band_raise_nothing():
    audit = JevAudit(api_key="k", transport=_transport(lambda ins: AUDIT_BANDS["flag_max_noul"] + 0.01))
    assert asyncio.run(audit.check("CT chest", "", TEXT)) == []


def test_jev_failure_fails_open_to_no_flags():
    def boom(request):
        return httpx.Response(500, text="down")
    audit = JevAudit(api_key="k", transport=httpx.MockTransport(boom))
    assert asyncio.run(audit.check("CT chest", "", TEXT)) == []


def test_no_candidates_means_no_call():
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"answers": {}})
    audit = JevAudit(api_key="k", transport=httpx.MockTransport(handler))
    assert asyncio.run(audit.check("CT head", "", "The ventricles are normal.")) == [] and calls == []
