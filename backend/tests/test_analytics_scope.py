"""Tests for the shared in-scope report filter (organic + skill-sheet pipelines)."""
import uuid

from rapid_reports_ai.analytics_scope import in_scope_reports
from rapid_reports_ai.database.models import User, Report, EphemeralSkillSheet, Template


def _user(db, email):
    u = User(id=uuid.uuid4(), email=email, password_hash="x", full_name="U",
             is_active=True, is_verified=True, is_approved=True)
    db.add(u); db.flush()
    return u


def _quick(db, user):
    ess = EphemeralSkillSheet(id=uuid.uuid4(), scan_type="ct", scan_type_normalized="ct",
                              clinical_history="h", skill_sheet_markdown="-", analyser_model="m",
                              user_id=user.id)
    db.add(ess); db.flush()
    r = Report(id=uuid.uuid4(), report_type="auto", generation_mode="quick_ephemeral",
               model_used="m", report_content="c", ephemeral_skill_sheet_id=ess.id, user_id=user.id)
    db.add(r); db.flush()
    return r


def _template_report(db, user, generation_mode="skill_sheet_guided"):
    t = Template(id=uuid.uuid4(), name="T", user_id=user.id,
                 template_config={"generation_mode": generation_mode})
    db.add(t); db.flush()
    r = Report(id=uuid.uuid4(), report_type="templated", model_used="m",
               report_content="c", template_id=t.id, user_id=user.id)
    db.add(r); db.flush()
    return r


def test_scope_excludes_internal_legacy_and_nonskillsheet(db_session, monkeypatch):
    monkeypatch.setenv("ANALYTICS_EXCLUDE_EMAILS", "hassan@x.com")
    organic = _user(db_session, "organic@nhs.net")
    internal = _user(db_session, "hassan@x.com")

    _quick(db_session, organic)                                   # in scope
    _template_report(db_session, organic, "skill_sheet_guided")   # in scope
    _quick(db_session, internal)                                  # excluded: internal
    _template_report(db_session, organic, "sections")             # excluded: legacy template
    # legacy auto (no ephemeral pipeline tag)
    db_session.add(Report(id=uuid.uuid4(), report_type="auto", generation_mode=None,
                          model_used="m", report_content="c", user_id=organic.id))
    db_session.flush()

    rows = in_scope_reports(db_session).all()
    assert len(rows) == 2
    assert {r.report_type for r in rows} == {"auto", "templated"}

    assert len(in_scope_reports(db_session, "quick").all()) == 1
    assert len(in_scope_reports(db_session, "template").all()) == 1
