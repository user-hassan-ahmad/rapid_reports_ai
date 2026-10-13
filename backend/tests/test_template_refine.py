"""Chat-to-edit writes the grammar (template pipeline Task C5): the refine prompt carries the sheet grammar, and the
refine endpoint vets the edit with the save function so a refusal reaches the radiologist at the moment of the edit."""
import pytest

from rapid_reports_ai import template_sheet_save as S
from tests.template_sheet_fixtures import GOOD

URL = "/api/templates/skill-sheet/refine"
EDITED = GOOD + 'NORMAL [cartilage] "Mild thinning."\n'


@pytest.fixture
def refine_returns(monkeypatch):
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    def set_result(result=None, exc=None):
        async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
            if exc:
                raise exc
            return result

        monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)

    return set_result


def test_refine_refusal_keeps_the_sheet_and_says_why(client, auth_headers, monkeypatch, refine_returns):
    refine_returns({"skill_sheet": EDITED, "response": "Done", "behavioral_claim": "x should now y"})

    async def vet(sheet, origin, previous=""):
        assert origin == "chat" and previous == GOOD
        return S.VetOutcome("refused", previous, 'Couldn\'t apply: "Mild thinning." (states an abnormality as a normal).')

    monkeypatch.setattr(S, "vet_sheet", vet)
    r = client.post(URL, headers=auth_headers, json={"skill_sheet": GOOD, "message": "add cartilage thinning"}).json()
    assert r["success"] is True and r["skill_sheet"] == GOOD and r["response"].startswith("Couldn't apply")
    assert r["applied"] is False and r["behavioral_claim"] == ""


def test_refine_saved_returns_the_vetted_sheet(client, auth_headers, monkeypatch, refine_returns):
    refine_returns({"skill_sheet": EDITED, "response": "Reports will now say it.", "behavioral_claim": "c"})

    async def vet(sheet, origin, previous=""):
        return S.VetOutcome("saved", sheet + "\n", "")

    monkeypatch.setattr(S, "vet_sheet", vet)
    r = client.post(URL, headers=auth_headers, json={"skill_sheet": GOOD, "message": "m"}).json()
    assert r["success"] is True and r["applied"] is True and r["skill_sheet"] == EDITED + "\n"
    assert r["response"] == "Reports will now say it." and r["behavioral_claim"] == "c" and "notice" not in r


def test_refine_adjusted_edit_carries_the_notice(client, auth_headers, monkeypatch, refine_returns):
    refine_returns({"skill_sheet": EDITED, "response": "Reports will now say it.", "behavioral_claim": "c"})

    async def vet(sheet, origin, previous=""):
        return S.VetOutcome("saved", sheet, S.ADJUSTED)

    monkeypatch.setattr(S, "vet_sheet", vet)
    r = client.post(URL, headers=auth_headers, json={"skill_sheet": GOOD, "message": "m"}).json()
    assert r["applied"] is True and r["notice"] == S.ADJUSTED
    assert r["response"].startswith("Reports will now say it.") and S.ADJUSTED in r["response"]


def test_refine_question_turn_is_unchanged_and_applied_false(client, auth_headers, monkeypatch, refine_returns):
    refine_returns({"skill_sheet": GOOD, "response": "It already does. Want it changed?", "behavioral_claim": ""})

    async def vet(sheet, origin, previous=""):
        return S.VetOutcome("unchanged", previous)

    monkeypatch.setattr(S, "vet_sheet", vet)
    r = client.post(URL, headers=auth_headers, json={"skill_sheet": GOOD, "message": "does it?"}).json()
    assert r["success"] is True and r["skill_sheet"] == GOOD and r["applied"] is False
    assert r["response"] == "It already does. Want it changed?"


def test_refine_model_failure_is_a_friendly_message(client, auth_headers, refine_returns):
    refine_returns(exc=ValueError("Could not parse JSON: {'skill_sheet' ... traceback"))
    r = client.post(URL, headers=auth_headers, json={"skill_sheet": GOOD, "message": "m"}).json()
    assert r["success"] is False and "JSON" not in r["error"] and "try again" in r["error"]


async def test_refine_prompt_carries_the_grammar(monkeypatch):
    from rapid_reports_ai import enhancement_utils as eu
    from rapid_reports_ai import template_manager as tm_mod
    from rapid_reports_ai import template_sheet_lab_prompts as P
    seen = {}

    async def capture(model_name, output_type, system_prompt, user_prompt, api_key, **k):
        seen["system"], seen["user"] = system_prompt, user_prompt
        return type("R", (), {"output": '{"skill_sheet": "x", "response": "ok", "behavioral_claim": ""}'})()

    monkeypatch.setattr(eu, "_run_agent_with_model", capture)
    out = await tm_mod.TemplateManager().refine_skill_sheet(
        "## Report Structure\n", "shorter", [], "",
        rejection_context={"original_instruction": "orig ask", "rejected_claim": "bad claim"})
    assert out == {"skill_sheet": "x", "response": "ok", "behavioral_claim": ""}
    s = seen["system"]
    assert P.GRAMMAR[:60] in s and P.SHEET_LAYOUT[:60] in s and "report behaviour" in s
    assert "INTERPRET" in s and "behavioral_claim" in s  # three-phase behaviour and the claim are kept
    assert "orig ask" in seen["user"] and "bad claim" in seen["user"]
