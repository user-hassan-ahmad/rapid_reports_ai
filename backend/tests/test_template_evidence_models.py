from rapid_reports_ai.database.models import TemplateExample, TemplateChatTurn, Report, DictationStackLog


def test_evidence_columns_exist():
    assert "generation_stamp" in Report.__table__.columns
    assert {"template_id", "stamp"} <= set(DictationStackLog.__table__.columns.keys())
    assert {"template_id", "text", "sha256", "source"} <= set(TemplateExample.__table__.columns.keys())
    assert {"template_id", "instruction", "response", "applied"} <= set(TemplateChatTurn.__table__.columns.keys())
