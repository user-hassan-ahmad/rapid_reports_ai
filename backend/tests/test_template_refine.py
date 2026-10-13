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


def test_refine_unchanged_non_question_reply_says_no_change_was_needed(client, auth_headers, monkeypatch,
                                                                       refine_returns):
    refine_returns({"skill_sheet": GOOD, "response": "Reports will now always state it.", "behavioral_claim": "c"})

    async def vet(sheet, origin, previous=""):
        return S.VetOutcome("unchanged", previous)

    monkeypatch.setattr(S, "vet_sheet", vet)
    r = client.post(URL, headers=auth_headers, json={"skill_sheet": GOOD, "message": "m"}).json()
    assert r["applied"] is False and r["response"] == "No change was needed." and r["behavioral_claim"] == ""


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
    assert "does not clearly cover" in s and "unchanged" in s  # fit check: ask, don't edit
    assert "orig ask" in seen["user"] and "bad claim" in seen["user"]


# ── chat turns stored with the template (Task D5) ─────────────────────────────────────────────────────────────────
def _turns(db_session):
    from rapid_reports_ai.database.models import TemplateChatTurn
    db_session.expire_all()
    return db_session.query(TemplateChatTurn).all()


def test_refine_with_a_template_records_the_turn(client, auth_headers, guided_template, db_session, monkeypatch,
                                                 refine_returns):
    sheet = guided_template.template_config["skill_sheet"]
    refine_returns({"skill_sheet": sheet, "response": "No change needed", "behavioral_claim": ""})

    async def vet(sheet, origin, previous=""):
        return S.VetOutcome("unchanged", sheet, "")
    monkeypatch.setattr(S, "vet_sheet", vet)
    client.post(URL, headers=auth_headers, json={"skill_sheet": sheet, "message": "keep it short",
                                                 "template_id": str(guided_template.id)})
    (turn,) = _turns(db_session)
    assert turn.instruction == "keep it short" and turn.applied is True and turn.response
    assert turn.sheet_hash_before == turn.sheet_hash_after and turn.template_id == guided_template.id


def test_refused_write_records_applied_false_with_equal_hashes(client, auth_headers, guided_template, db_session,
                                                               monkeypatch, refine_returns):
    refine_returns({"skill_sheet": EDITED, "response": "Done", "behavioral_claim": "c"})

    async def vet(sheet, origin, previous=""):
        return S.VetOutcome("refused", previous, "Couldn't apply that.")
    monkeypatch.setattr(S, "vet_sheet", vet)
    client.post(URL, headers=auth_headers, json={"skill_sheet": GOOD, "message": "m",
                                                 "template_id": str(guided_template.id)})
    (turn,) = _turns(db_session)
    assert turn.applied is False and turn.sheet_hash_after == turn.sheet_hash_before
    assert turn.response == "Couldn't apply that."


def test_applied_edit_records_changed_hash(client, auth_headers, guided_template, db_session, monkeypatch,
                                           refine_returns):
    refine_returns({"skill_sheet": EDITED, "response": "Done", "behavioral_claim": "c"})

    async def vet(sheet, origin, previous=""):
        return S.VetOutcome("saved", sheet, "")
    monkeypatch.setattr(S, "vet_sheet", vet)
    client.post(URL, headers=auth_headers, json={"skill_sheet": GOOD, "message": "m",
                                                 "template_id": str(guided_template.id)})
    (turn,) = _turns(db_session)
    assert turn.applied is True and turn.sheet_hash_after != turn.sheet_hash_before


def test_refine_without_a_template_records_nothing(client, auth_headers, db_session, monkeypatch, refine_returns):
    refine_returns({"skill_sheet": GOOD, "response": "ok", "behavioral_claim": ""})

    async def vet(sheet, origin, previous=""):
        return S.VetOutcome("saved", sheet, "")
    monkeypatch.setattr(S, "vet_sheet", vet)
    assert client.post(URL, headers=auth_headers, json={"skill_sheet": GOOD, "message": "m"}).json()["success"]
    assert _turns(db_session) == []


def test_refine_on_another_users_template_records_nothing(client, auth_headers, db_session, monkeypatch,
                                                          refine_returns):
    import uuid
    from rapid_reports_ai.database.models import Template, User
    other = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="O",
                 is_active=True, is_verified=True, is_approved=True)
    db_session.add(other)
    db_session.commit()
    t = Template(name="Theirs", template_config={"skill_sheet": GOOD}, user_id=other.id, tags=[], is_active=True)
    db_session.add(t)
    db_session.commit()
    refine_returns({"skill_sheet": GOOD, "response": "ok", "behavioral_claim": ""})

    async def vet(sheet, origin, previous=""):
        return S.VetOutcome("saved", sheet, "")
    monkeypatch.setattr(S, "vet_sheet", vet)
    assert client.post(URL, headers=auth_headers, json={"skill_sheet": GOOD, "message": "m",
                                                        "template_id": str(t.id)}).json()["success"]
    assert _turns(db_session) == []


def test_a_db_failure_while_recording_never_fails_the_refine(client, auth_headers, guided_template, monkeypatch,
                                                             refine_returns):
    refine_returns({"skill_sheet": GOOD, "response": "ok", "behavioral_claim": ""})

    async def vet(sheet, origin, previous=""):
        return S.VetOutcome("saved", sheet, "")
    monkeypatch.setattr(S, "vet_sheet", vet)

    def boom(self, *a, **k):
        raise RuntimeError("db gone")
    monkeypatch.setattr("sqlalchemy.orm.Session.commit", boom)
    r = client.post(URL, headers=auth_headers, json={"skill_sheet": GOOD, "message": "m",
                                                     "template_id": str(guided_template.id)}).json()
    assert r["success"] is True and r["applied"] is True
