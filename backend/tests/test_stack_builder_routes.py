"""The Copilot routes and /stack/draft build their findings text from units + groups with the one builder
(integration spec §5 Builder), so the text /match prewarms and the text /open reads are the same by construction."""
from rapid_reports_ai.hybrid_stack.copilot.routes import AskRequest, CalculateRequest, MatchRequest, OpenRequest, \
    RecsRequest
from rapid_reports_ai.hybrid_stack.findings import findings_text
from rapid_reports_ai.hybrid_stack.routes import DraftRequest
from rapid_reports_ai.hybrid_stack.units import StackUnit

U = [{"id": 1, "text": "Liver normal.", "group": "Liver", "structure": None, "attach_to": None, "parts": None,
      "covers": [], "abnormal": False, "pinned": False, "heading": False}]   # SYNTHETIC
CARD = {"key": "k@1", "name": "K", "version": "1", "finding_id": "u1"}


def test_match_and_open_build_the_same_text_from_units():
    m = MatchRequest(scan_type="CT", units=U, groups=["Liver"], dictation="ignored")
    o = OpenRequest.model_validate({"card": CARD, "units": U, "groups": ["Liver"], "findings": "ignored"})
    expect = findings_text([StackUnit.model_validate(u) for u in U], ["Liver"])
    assert m.dictation == o.findings == expect == "Liver: Liver normal."


def test_calculate_ask_and_recs_build_from_units():
    c = CalculateRequest.model_validate({"card": CARD, "units": U, "groups": ["Liver"]})
    a = AskRequest(question="q", units=U, groups=["Liver"], findings="ignored")
    r = RecsRequest(units=U, groups=["Liver"])
    assert c.findings == a.findings == r.findings == "Liver: Liver normal."


def test_draft_builds_its_findings_from_units():
    assert DraftRequest(units=U, groups=["Liver"]).findings == "Liver: Liver normal."


def test_old_string_fields_still_work():
    assert DraftRequest(findings="Liver: x.").findings == "Liver: x."
    assert MatchRequest(dictation="d").dictation == "d"
    assert OpenRequest.model_validate({"card": CARD, "findings": "f"}).findings == "f"
