import uuid

from rapid_reports_ai.database.models import DictationStackLog, StackSchemaFamily


def test_family_and_log_round_trip(db_session):
    db_session.add(StackSchemaFamily(key="mri left ankle", scan_type="MRI left ankle",
                                     regions=[{"name": "Tendons", "includes": "x"}], source="reconciler:composed",
                                     status="provisional"))
    uid = uuid.uuid4()
    db_session.add(DictationStackLog(user_id=uid, session_id="s1", scan_type="MRI left ankle",
                                     schema_key="mri left ankle", schema_source="reconciled", provisional=True,
                                     units=[], pills_derived=["Tendons"], pills_jev=[], sections=[],
                                     structured_text="", manual_moves=0, latency_ms={}))
    db_session.commit()
    assert db_session.get(StackSchemaFamily, "mri left ankle").status == "provisional"
    assert db_session.query(DictationStackLog).filter_by(session_id="s1").one().pills_derived == ["Tendons"]
