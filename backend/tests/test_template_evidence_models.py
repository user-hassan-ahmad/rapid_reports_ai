from rapid_reports_ai.database.models import TemplateExample, TemplateChatTurn, Report, DictationStackLog


def test_evidence_columns_exist():
    assert "generation_stamp" in Report.__table__.columns
    assert {"template_id", "stamp"} <= set(DictationStackLog.__table__.columns.keys())
    assert {"template_id", "text", "sha256", "source"} <= set(TemplateExample.__table__.columns.keys())
    assert {"template_id", "instruction", "response", "applied"} <= set(TemplateChatTurn.__table__.columns.keys())


def test_evidence_rows_round_trip(db_session, guided_template):
    ex = TemplateExample(template_id=guided_template.id, text="Example report.", sha256="a" * 64)
    turn = TemplateChatTurn(template_id=guided_template.id, instruction="Add a line")
    db_session.add_all([ex, turn])
    db_session.commit()
    db_session.expire_all()
    got_ex = db_session.query(TemplateExample).one()
    got_turn = db_session.query(TemplateChatTurn).one()
    assert got_ex.source == "pasted" and got_ex.created_at is not None
    assert got_turn.applied is True and got_turn.response is None and got_turn.created_at is not None
