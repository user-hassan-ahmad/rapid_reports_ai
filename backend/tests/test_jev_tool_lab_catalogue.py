from rapid_reports_ai.scripts.jev_tool_lab.catalogue import Case, QuestionSpec, validate

CASE = Case(scan_type="CT abdomen",
            dictation="Left renal lesion 3 cm with a thin wall and two thin septa. No enhancement.",
            report="FINDINGS:\nLeft renal cyst 3 cm with thin septa.\nIMPRESSION:\nBosniak II cyst.")


def q(**kw):
    return QuestionSpec(id="q1", **kw)


def test_t1_needs_verbatim_item():
    assert validate(q(type="T1", source="dictation", item="Left renal cyst 3 cm"), CASE) is None
    assert validate(q(type="T1", source="dictation", item="left  renal CYST 3 cm"), CASE) is None  # whitespace/case
    assert validate(q(type="T1", source="dictation", item="a cyst in the kidney"), CASE) == "item not verbatim"


def test_t1_needs_source():
    assert validate(q(type="T1", item="Left renal cyst 3 cm"), CASE) == "missing source"


def test_t2_topic_rules():
    assert validate(q(type="T2", source="dictation", topic="wall thickness of the lesion"), CASE) is None
    assert validate(q(type="T2", source="dictation", topic="no enhancement"), CASE) == "topic carries a negation"
    assert validate(q(type="T2", source="dictation", topic="septa over 2 mm"), CASE) == "topic carries a number"
    assert validate(q(type="T2", source="dictation", topic="a b c d e f g"), CASE) == "topic must be 1-6 words"
    assert validate(q(type="T2", source="report", topic="septa"), CASE) == "T2 on the report needs a section"
    assert validate(q(type="T2", source="report", section="FINDINGS", topic="septa"), CASE) is None
    assert validate(q(type="T2", source="history", topic="septa"), CASE) == "T2 source must be dictation or report"


def test_t3_clause_must_be_in_report():
    assert validate(q(type="T3", clause="Left renal cyst 3 cm with thin septa."), CASE) is None
    assert validate(q(type="T3", clause="No enhancement."), CASE) == "clause not verbatim in the report"


def test_t4_options():
    ok = q(type="T4", source="dictation", item="two thin septa", options=["thin septa", "thick septa"])
    assert validate(ok, CASE) is None
    one = q(type="T4", source="dictation", item="two thin septa", options=["thin septa"])
    assert validate(one, CASE) == "T4 needs 2-5 options"
    neg = q(type="T4", source="dictation", item="two thin septa", options=["septa enhance", "septa do not enhance"])
    assert validate(neg, CASE) == "an option negates another"


def test_t5_property_must_be_known():
    assert validate(q(type="T5", item="No enhancement.", property="abnormal"), CASE) is None
    assert validate(q(type="T5", item="No enhancement.", property="hedged"), CASE) == "unknown property"


def test_t6_spans_verbatim():
    assert validate(q(type="T6", a="Left renal lesion 3 cm", b="Left renal cyst 3 cm"), CASE) is None
    assert validate(q(type="T6", a="Left renal lesion 3 cm", b="right kidney"), CASE) == "span not verbatim"


def test_empty_source_text_rejected():
    case = Case(dictation="Normal study.")
    assert validate(q(type="T2", source="report", section="FINDINGS", topic="septa"), case) == "source text is empty"
