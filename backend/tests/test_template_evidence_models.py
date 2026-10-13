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


def test_chat_turns_are_scrubbed_before_storing(db_session, guided_template):
    from rapid_reports_ai.template_chat_turns import record_turn, store_creator_turns
    leaky = "Add a line for Mr John Smith, NHS 943 476 5919, scanned 12/03/2024."
    record_turn(db_session, guided_template.id, leaky, "Done for Dr Jane Doe on 12 March 2024.", True, "a", "b")
    assert store_creator_turns(db_session, guided_template.id, [{"instruction": leaky, "response": leaky}]) == 1
    rows = db_session.query(TemplateChatTurn).all()
    assert len(rows) == 2
    for row in rows:
        for text in (row.instruction, row.response):
            assert "[removed]" in text
            assert not any(s in text for s in ("John Smith", "943 476 5919", "12/03/2024", "Jane Doe", "12 March 2024"))
    assert rows[0].instruction.startswith("Add a line for")
