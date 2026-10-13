"""/skill-sheet/decide: the Rules step's cards; fail-soft (Rules-step spec, "Failure behaviour")."""
import pytest

from rapid_reports_ai import template_decision_run as R
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_ledger_apply as tla
from rapid_reports_ai.database.models import TemplateExample
from tests.conftest import _make_template
from tests.template_sheet_fixtures import LEDGER_SHEET

URL = "/api/templates/skill-sheet/decide"
EX = [{"content": "Findings: LVEF 55%. ECV 28%."}, {"content": "Findings: LVEF 60%."},
      {"content": "Findings: LVEF 50%. ECV 30%."}]


@pytest.fixture
def run_returns(monkeypatch):
    seen = {}

    def set_run(run):
        async def fake(examples, scan_type):
            seen.update(examples=examples, scan_type=scan_type)
            return run
        monkeypatch.setattr(R, "run_decisions", fake)
    return set_run, seen


def _run():
    out = R.RunOutput(values=[
        R.ValueCandidate(name="LVEF", quotes=[R.Quote(report=i, text=t) for i, t in
                                              [(1, "LVEF 55%"), (2, "LVEF 60%"), (3, "LVEF 50%")]]),
        R.ValueCandidate(name="ECV", quotes=[R.Quote(report=1, text="ECV 28%"), R.Quote(report=3, text="ECV 30%")])])
    run = R.check_quotes(out, [e["content"] for e in EX])
    run.states = {n: [] for n in td.CONCEPTS}
    return run


def test_decide_returns_cards_kept_defaults_and_the_run_record(client, auth_headers, run_returns):
    set_run, seen = run_returns
    set_run(_run())
    r = client.post(URL, headers=auth_headers, json={"scan_type": "<scan>", "examples": EX}).json()
    assert r["success"] and r["ran"] and r["notice"] == ""
    assert [c["id"] for c in r["cards"]] == ["value:ecv"] and [c["id"] for c in r["kept"]] == ["value:lvef"]
    assert r["defaults"] == [{"kind": "value", "key": "LVEF", "choice": {"need": "every"}}]
    assert r["run"]["version"] == R.RUN_VERSION and r["run"]["cards"] == 1
    assert seen["scan_type"] == "<scan>" and len(seen["examples"]) == 3


def test_a_failed_run_gives_no_cards_and_the_notice(client, auth_headers, run_returns):
    set_run, _ = run_returns
    set_run(R.DecisionRun(ok=False, error="TimeoutError"))
    r = client.post(URL, headers=auth_headers, json={"scan_type": "<scan>", "examples": EX}).json()
    assert r["success"] and r["ran"] is False and r["cards"] == []
    assert r["notice"] == "We couldn't pre-check your rules; review them on the Style step."


def test_an_exception_is_still_fail_soft(client, auth_headers, monkeypatch):
    async def boom(examples, scan_type):
        raise RuntimeError("x")
    monkeypatch.setattr(R, "run_decisions", boom)
    r = client.post(URL, headers=auth_headers, json={"scan_type": "<scan>", "examples": EX}).json()
    assert r["success"] and r["cards"] == [] and r["notice"]


def test_a_saved_template_uses_its_stored_examples_and_shows_its_current_values(
        client, auth_headers, db_session, test_user, run_returns):
    set_run, seen = run_returns
    set_run(_run())
    led, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation")
    # an upgraded template: LIST_MISSING in the sheet, no decisions and no decision-run record yet
    t = _make_template(db_session, test_user, "T", {"generation_mode": "skill_sheet_guided", "scan_type": "<scan>",
                                                    "skill_sheet": tla.apply_ledger(LEDGER_SHEET, led).sheet})
    for i, e in enumerate(EX):
        db_session.add(TemplateExample(template_id=t.id, text=e["content"], sha256=str(i) * 64, source="pasted"))
    db_session.commit()
    r = client.post(URL, headers=auth_headers, json={"template_id": str(t.id)}).json()
    assert r["success"] and r["ran"] and len(seen["examples"]) == 3 and seen["scan_type"] == "<scan>"
    assert [(c["id"], c["selected"]) for c in r["cards"]] == [("value:lvef", "every"), ("value:ecv", None)]
    assert r["kept"] == [] and r["defaults"] == []      # LVEF is already shown as the template's current value


def test_the_first_use_review_is_stamped_on_the_server_and_never_repeats(client, auth_headers, db_session, test_user,
                                                                          run_returns):
    set_run, seen = run_returns
    set_run(_run())
    t = _make_template(db_session, test_user, "T", {"generation_mode": "skill_sheet_guided",
                                                    "skill_sheet": LEDGER_SHEET})
    for i, e in enumerate(EX):
        db_session.add(TemplateExample(template_id=t.id, text=e["content"], sha256=str(i) * 64, source="pasted"))
    db_session.commit()
    assert client.post(URL, headers=auth_headers, json={"template_id": str(t.id)}).json()["ran"] is True
    db_session.refresh(t)
    assert t.template_config["rules_step"]["version"] == R.RUN_VERSION and t.template_config["rules_step"]["first_use"]
    seen.clear()
    r = client.post(URL, headers=auth_headers, json={"template_id": str(t.id)}).json()
    assert r["ran"] is False and "examples" not in seen               # not run again, saved or not


def test_a_saved_template_without_examples_shows_only_its_values(client, auth_headers, db_session, test_user,
                                                                  run_returns):
    set_run, seen = run_returns
    set_run(_run())
    t = _make_template(db_session, test_user, "T", {"generation_mode": "skill_sheet_guided",
                                                    "skill_sheet": LEDGER_SHEET})
    r = client.post(URL, headers=auth_headers, json={"template_id": str(t.id)}).json()
    assert r["success"] and r["ran"] is False and r["cards"] == [] and "examples" not in seen


def test_a_reviewed_template_is_not_re_run(client, auth_headers, db_session, test_user, run_returns):
    set_run, seen = run_returns
    set_run(_run())
    t = _make_template(db_session, test_user, "T", {"generation_mode": "skill_sheet_guided",
                                                    "skill_sheet": LEDGER_SHEET, "rules_step": {"version": "v"}})
    for i, e in enumerate(EX):
        db_session.add(TemplateExample(template_id=t.id, text=e["content"], sha256=str(i) * 64, source="pasted"))
    db_session.commit()
    r = client.post(URL, headers=auth_headers, json={"template_id": str(t.id)}).json()
    assert r["success"] and r["ran"] is False and "examples" not in seen


def test_another_users_template_is_not_found(client, auth_headers, db_session, run_returns):
    import uuid
    r = client.post(URL, headers=auth_headers, json={"template_id": str(uuid.uuid4())}).json()
    assert r == {"success": False, "error": "Template not found"}
