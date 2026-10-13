"""Example reports stored with a template (template pipeline spec, block 4): scrubbed, Jev-checked, deduped, never
failing the save, deleted with the template."""
import pytest

from rapid_reports_ai import template_examples as E
from rapid_reports_ai import template_sheet_save as S
from rapid_reports_ai.database import crud
from rapid_reports_ai.database.models import TemplateChatTurn, TemplateExample
from tests.template_sheet_fixtures import GOOD


def test_code_backstop_removes_identifier_shapes():
    t = "Name: John Smith\nDOB: 01/02/1960\nNHS 943 476 5919\nMRN A1234567\nThe liver is normal."
    out = E.scrub(t)
    assert "John Smith" not in out and "01/02/1960" not in out and "943 476 5919" not in out and "A1234567" not in out
    assert "The liver is normal." in out


def test_code_backstop_removes_titled_names():
    out = E.scrub("Discussed with Dr Sarah O'Neill on 3 May 2025.\nReported by Dr. A. Kumar\nGMC 7012345\nMRI shows MS plaques.")
    assert "Sarah" not in out and "O'Neill" not in out and "Kumar" not in out and "2025" not in out and "7012345" not in out
    assert "MRI shows MS plaques." in out


def test_code_backstop_keeps_clinical_shorthand():
    t = ("Disc protrusion at L4/5 and L5/S1. T2/FLAIR hyperintensity. BI-RADS 4. Ratio 1.2/3.4. "
         "Lesion 12 x 8 mm. Grade 3/4 chondral loss. 1/2 of the gland.")
    assert E.scrub(t) == t


def test_code_backstop_removes_uk_phone_numbers():
    out = E.scrub("Call 020 7946 0958 or 07700 900123. Pleural effusion.")
    assert "7946" not in out and "0958" not in out and "900123" not in out and "Pleural effusion." in out


class _Reply:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


@pytest.mark.parametrize("body", [{}, {"answers": {}}, {"answers": {"q": {}}}, {"answers": {"q": {"noul": None}}},
                                  {"answers": {"q": {"noul": float("nan")}}}, {"answers": {"q": {"noul": "inf"}}}])
async def test_a_malformed_jev_reply_stores_nothing(db_session, guided_template, monkeypatch, body):
    async def post(b, key, timeout, transport=None):
        return _Reply(body)
    monkeypatch.setattr(E, "jev_post", post)
    assert await E.store_examples(db_session, guided_template.id, ["Normal study."]) == 0
    assert db_session.query(TemplateExample).count() == 0


async def test_a_jev_score_is_clamped(monkeypatch):
    async def post(b, key, timeout, transport=None):
        return _Reply({"answers": {"q": {"noul": 1.7}}})
    monkeypatch.setattr(E, "jev_post", post)
    assert await E._identifier_scores(["x"]) == [1.0]


async def _low(texts):
    return [0.1 for _ in texts]


async def test_store_skips_an_example_jev_still_flags(db_session, guided_template, monkeypatch):
    async def flags(texts):
        return [0.9 if "Thompson" in t else 0.1 for t in texts]
    monkeypatch.setattr(E, "_identifier_scores", flags)
    n = await E.store_examples(db_session, guided_template.id, ["Normal study.", "The patient, Margaret Thompson, was seen."])
    assert n == 1
    rows = db_session.query(TemplateExample).filter_by(template_id=guided_template.id).all()
    assert [r.text for r in rows] == ["Normal study."] and rows[0].source == "pasted" and len(rows[0].sha256) == 64


async def test_stored_text_is_the_scrubbed_text(db_session, guided_template, monkeypatch):
    monkeypatch.setattr(E, "_identifier_scores", _low)
    await E.store_examples(db_session, guided_template.id, ["DOB: 01/02/1960\nThe liver is normal."])
    (row,) = db_session.query(TemplateExample).filter_by(template_id=guided_template.id).all()
    assert "1960" not in row.text and "The liver is normal." in row.text


async def test_jev_failure_stores_nothing(db_session, guided_template, monkeypatch):
    async def down(texts):
        raise RuntimeError("jev down")
    monkeypatch.setattr(E, "_identifier_scores", down)
    assert await E.store_examples(db_session, guided_template.id, ["Normal study."]) == 0
    assert db_session.query(TemplateExample).count() == 0


async def test_short_answer_from_jev_stores_nothing(db_session, guided_template, monkeypatch):
    async def short(texts):
        return [0.1]
    monkeypatch.setattr(E, "_identifier_scores", short)
    assert await E.store_examples(db_session, guided_template.id, ["Normal study.", "Normal liver."]) == 0


async def test_same_text_is_stored_once(db_session, guided_template, monkeypatch):
    monkeypatch.setattr(E, "_identifier_scores", _low)
    assert await E.store_examples(db_session, guided_template.id, ["Normal study.", "Normal study.", "  "]) == 1
    assert await E.store_examples(db_session, guided_template.id, ["Normal study."]) == 0
    assert db_session.query(TemplateExample).count() == 1


async def test_identifier_scores_asks_jev_once_per_text(monkeypatch):
    seen = []

    class R:
        def __init__(self, s):
            self.s = s

        def raise_for_status(self):
            pass

        def json(self):
            return {"answers": {"q": {"noul": self.s}}}

    async def post(body, key, timeout, transport=None):
        seen.append(body)
        return R(0.8 if "Patel" in body["state"] else 0.2)
    monkeypatch.setattr(E, "jev_post", post)
    assert await E._identifier_scores(["Normal.", "Mrs Patel"]) == [0.2, 0.8]
    assert len(seen) == 2 and all(b["questions"]["q"]["type"] == "noul" for b in seen)


def test_delete_template_removes_its_examples_and_chat_turns(db_session, guided_template, test_user):
    db_session.add(TemplateExample(template_id=guided_template.id, text="x", sha256="0" * 64))
    db_session.add(TemplateChatTurn(template_id=guided_template.id, instruction="shorter"))
    db_session.commit()
    assert crud.delete_template(db_session, str(guided_template.id), user_id=str(test_user.id))
    assert db_session.query(TemplateExample).count() == 0
    assert db_session.query(TemplateChatTurn).count() == 0


@pytest.fixture
def quiet_save(monkeypatch):
    async def none(st, sheet=""):
        return []
    monkeypatch.setattr(S, "check_units", none)
    monkeypatch.setattr("rapid_reports_ai.template_sheet_structure.store_parsed", lambda tid, st: True)


def test_save_stores_the_examples(client, auth_headers, quiet_save, monkeypatch, db_session):
    got = {}

    async def store(db, template_id, texts):
        got["texts"] = texts
        return len(texts)
    monkeypatch.setattr(E, "store_examples", store)
    r = client.post("/api/templates/skill-sheet/save", headers=auth_headers, json={
        "skill_sheet": GOOD, "scan_type": "MRI knee", "template_name": "Knee",
        "examples": [{"label": "1", "content": "Normal knee."}], "chat_turns": [{"role": "user", "content": "x"}]}).json()
    assert r["success"] and got["texts"] == ["Normal knee."]


def test_save_succeeds_when_storing_examples_raises(client, auth_headers, quiet_save, monkeypatch):
    async def boom(db, template_id, texts):
        raise RuntimeError("db gone")
    monkeypatch.setattr(E, "store_examples", boom)
    r = client.post("/api/templates/skill-sheet/save", headers=auth_headers, json={
        "skill_sheet": GOOD, "scan_type": "MRI knee", "template_name": "Knee",
        "examples": [{"content": "Normal knee."}]}).json()
    assert r["success"] and r["template_id"]
