"""The one writer (template pipeline spec, block 1): example reports -> grammar sheet, vetted by the save function;
the creator's /skill-sheet/analyze uses it."""
import json

import pytest

from rapid_reports_ai import template_sheet_lab_prompts as P
from rapid_reports_ai import template_writer as W
from rapid_reports_ai.template_sheet_save import VetOutcome
from tests.template_sheet_fixtures import GOOD

SUMMARY = {"structure": {"sections": [{"name": "FINDINGS", "paragraphs": []}]},
           "voice": {"description": "terse", "phrases": ["x"]}}
QUESTIONS = [{"question": "q?", "suggestions": ["a", "b"]}]


def _answer(sheet=GOOD):
    return f"{P.SHEET_OPEN}\n{sheet}\n{P.SHEET_CLOSE}\n" + json.dumps({"summary": SUMMARY, "questions": QUESTIONS})


@pytest.fixture
def calls(monkeypatch):
    seen = {}

    async def call(system, user, settings):
        seen["system"], seen["user"], seen["settings"] = system, user, settings
        return _answer()

    async def vet(sheet, origin, previous=""):
        seen["vetted"], seen["origin"] = sheet, origin
        return VetOutcome("saved", sheet, message="Saved, with 1 statement reworded so the template stays consistent.",
                          dropped=[{"text": "VOICE x", "reason": "lint"}], coverage_sections=["FINDINGS"])

    monkeypatch.setattr(W, "model_call", call)
    monkeypatch.setattr(W, "vet_sheet", vet)
    return seen


async def test_write_returns_a_vetted_sheet_summary_and_questions(calls):
    out = await W.write_sheet([{"label": "", "content": "r1"}], "MRI knee", "notes here")
    assert out["skill_sheet"] == GOOD.strip() and out["summary"] == SUMMARY and out["questions"] == QUESTIONS
    assert out["dropped"] == [{"text": "VOICE x", "reason": "lint"}]
    assert out["notice"] == "Saved, with 1 statement reworded so the template stays consistent."
    assert out["analyser_version"] == W.ANALYSER_VERSION
    assert calls["system"] == P.ANALYSER_SYSTEM_PROMPT and calls["settings"] == P.ANALYSER_SETTINGS
    assert "MRI knee" in calls["user"] and "notes here" in calls["user"] and "r1" in calls["user"]
    assert calls["origin"] == "analyser" and calls["vetted"] == GOOD.strip()


async def test_write_raises_the_refusal_message(calls, monkeypatch):
    async def refuse(sheet, origin, previous=""):
        return VetOutcome("refused", "", message="The sheet failed its checks, try again")

    monkeypatch.setattr(W, "vet_sheet", refuse)
    with pytest.raises(ValueError, match="try again"):
        await W.write_sheet([{"label": "", "content": "r1"}], "MRI knee")


async def test_write_survives_a_broken_summary_json(calls, monkeypatch):
    async def call(system, user, settings):
        return f"{P.SHEET_OPEN}\n{GOOD}\n{P.SHEET_CLOSE}\n{{not json"

    monkeypatch.setattr(W, "model_call", call)
    out = await W.write_sheet([{"label": "", "content": "r1"}], "MRI knee")
    assert out["skill_sheet"] == GOOD.strip() and out["summary"] == {} and out["questions"] == []


def _analyze(client, auth_headers):
    return client.post("/api/templates/skill-sheet/analyze", headers=auth_headers, json={
        "scan_type": "MRI knee", "protocol_notes": "",
        "examples": [{"label": "", "content": f"report {i}"} for i in range(3)]}).json()


@pytest.fixture
def endpoint(monkeypatch):
    from rapid_reports_ai import main
    from rapid_reports_ai.template_manager import TemplateManager

    async def test_case(self, examples, scan_type, api_key):
        return {"sample_clinical_history": "h", "sample_findings": "f"}

    monkeypatch.setattr(main, "get_system_api_key", lambda *a, **k: "key")
    monkeypatch.setattr(TemplateManager, "generate_test_case", test_case)

    async def legacy(*a, **k):
        raise AssertionError("the free-form analyser must not run")

    monkeypatch.setattr(TemplateManager, "analyze_examples_to_skill_sheet", legacy)


def test_analyze_returns_the_grammar_sheet_and_the_creator_keys(client, auth_headers, endpoint, monkeypatch):
    async def write(examples, scan_type, protocol_notes=""):
        assert [e["content"] for e in examples] == ["report 0", "report 1", "report 2"]
        return {"skill_sheet": GOOD, "summary": SUMMARY, "questions": QUESTIONS, "dropped": [],
                "analyser_version": W.ANALYSER_VERSION}

    monkeypatch.setattr(W, "write_sheet", write)
    r = _analyze(client, auth_headers)
    assert r["success"] and r["skill_sheet"] == GOOD and r["summary"] == SUMMARY and r["questions"] == QUESTIONS
    assert r["sample_clinical_history"] == "h" and r["sample_findings"] == "f"
    assert r["analyser_version"] == W.ANALYSER_VERSION


def test_analyze_returns_the_refusal_as_an_error(client, auth_headers, endpoint, monkeypatch):
    async def write(examples, scan_type, protocol_notes=""):
        raise ValueError("The sheet failed its checks, try again")

    monkeypatch.setattr(W, "write_sheet", write)
    r = _analyze(client, auth_headers)
    assert r == {"success": False, "error": "The sheet failed its checks, try again"}
