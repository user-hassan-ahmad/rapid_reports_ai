"""P1 integration guards: one migration chain that reaches prod's revision, flag defaults, and the stack log
keeping both branches' fields."""
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import DictationStackLog, Template, User
from rapid_reports_ai.hybrid_stack import routes as R
from rapid_reports_ai.hybrid_stack.copilot import routes as CR
from rapid_reports_ai.main import app

PROD_REVISION = "20261005120000"   # prod main's head (spec §9.3)


@pytest.fixture
def user(db_session):
    u = User(id=uuid.uuid4(), email="rad@nhs.net", password_hash="x", full_name="T",
             is_active=True, is_verified=True, is_approved=True)
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def authed(client, user, monkeypatch):
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    monkeypatch.delenv("RR_HYBRID_STACK", raising=False)
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")))


def test_one_head():
    assert len(_scripts().get_heads()) == 1


def test_chain_reaches_prod_revision():
    assert PROD_REVISION in [s.revision for s in _scripts().walk_revisions("base", "heads")]


def test_flag_defaults(monkeypatch):
    for k in ("RR_HYBRID_STACK", "RR_STACK_COPILOT", "RR_CHAT_ROUTER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    assert R.stack_allowed() is True
    assert CR.copilot_allowed() is True          # D24: on unless RR_STACK_COPILOT=0
    from rapid_reports_ai import chat_router
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert chat_router.enabled() is False         # ships dark: off unless RR_CHAT_ROUTER=1


def test_stack_log_keeps_template_stamp_and_copilot(authed, db_session, user):
    t = Template(name="T", template_config={"skill_sheet": "## FINDINGS\nx", "analyser_version": "a1"},
                 user_id=user.id, tags=[], is_active=True)
    db_session.add(t)
    db_session.commit()
    r = authed.post("/api/canvas/stack/log",
                    json={"session_id": "s1", "template_id": str(t.id), "copilot": {"applied": ["k@1"]}})
    assert r.status_code == 200
    row = db_session.query(DictationStackLog).filter_by(session_id="s1").one()
    assert row.template_id == str(t.id) and row.stamp["sheet_hash"]
    assert row.copilot == {"applied": ["k@1"]}
