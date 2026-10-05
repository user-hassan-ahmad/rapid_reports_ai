# tests/test_review_engine_api.py
"""Review endpoints (spec §10.3): owner-scoped; probe/reprepare/rerun need the engine on. Correction 13: the events
route takes user commands only (engine statuses → 422); reprepare never LLM-rewrites a negative; the GET hides
assumed_normal rows unless ?include=normals."""
import uuid

import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.database.models import Report, User
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine import engine, store
from rapid_reports_ai.review_engine.items import Edit, ReviewItem, Span

from tests.review_engine_fakes import jev, model

REPORT = "FINDINGS:\nThe liver is normal. A 14 mm left renal cyst.\nIMPRESSION:\nLeft renal cyst."
DICT = "- 14 mm left renal cyst with a thin septation"


@pytest.fixture
def seeded(db_session, test_user):
    r = Report(report_type="quick", model_used="m", report_content=REPORT, user_id=test_user.id,
               input_data={"variables": {"FINDINGS": DICT, "SCAN_TYPE": "CT abdomen"}},
               candidate_reports=[{"content": REPORT, "sections": ["FINDINGS", "IMPRESSION"], "options": []}])
    db_session.add(r)
    db_session.commit()
    rid = str(r.id)
    run_id = store.create_run(db_session, rid, "shadow", "0.1.0", "quick")
    it = ReviewItem(key="k1", report_id=rid, run_id=run_id, lane="coverage", detectors=["jev.classify_first"],
                    kind="partial", cls="minor", section="FINDINGS", label="Septation missing",
                    anchor=Span(start=0, end=10, text="A 14 mm left renal cyst."),
                    edit=Edit(mode="replace", find="A 14 mm left renal cyst.",
                              replace="A 14 mm left renal cyst with a thin septation."),
                    probe="The FINDINGS section describes the cyst's septation.", source_line=DICT[2:])
    store.save_items(db_session, [it])
    return rid, it


def _neg_items(rid, run_id):
    normal = ReviewItem(key="n1", report_id=rid, run_id=run_id, lane="accuracy", detectors=["negatives.v5"],
                        kind="assumed_normal", cls="info", section="FINDINGS", label="Assumed normal",
                        anchor=Span(start=10, end=30, text="The liver is normal."))
    removal = ReviewItem(key="n2", report_id=rid, run_id=run_id, lane="accuracy", detectors=["negatives.v5"],
                         kind="removed", cls="action", section="FINDINGS", label="Negative contradicted",
                         anchor=Span(start=10, end=30, text="The liver is normal."),
                         edit=Edit(mode="remove", find="The liver is normal."), probe="p")
    acc = ReviewItem(key="n3", report_id=rid, run_id=run_id, lane="accuracy", detectors=["jev.contradiction"],
                     kind="contradicted", cls="action", section="FINDINGS", label="Contradicted negative",
                     anchor=Span(start=10, end=30, text="The liver is normal."), evidence={"negative": True},
                     edit=Edit(mode="remove", find="The liver is normal."), probe="p")
    return normal, removal, acc


def _other_headers(db_session):
    from rapid_reports_ai.auth import create_access_token
    other = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="O", is_active=True,
                 is_verified=True, is_approved=True)
    db_session.add(other)
    db_session.commit()
    return {"Authorization": f"Bearer {create_access_token({'sub': str(other.id)})}"}


def test_get_review(client, auth_headers, seeded, monkeypatch):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    rid, it = seeded
    body = client.get(f"/api/reports/{rid}/review", headers=auth_headers).json()
    assert body["success"] and body["mode"] == "shadow" and body["rail"] is False
    assert [i["id"] for i in body["items"]] == [it.id] and body["run"]["mode"] == "shadow"


def test_get_review_hides_normals_unless_asked(client, auth_headers, seeded, db_session):
    rid, it = seeded
    normal, _, _ = _neg_items(rid, it.run_id)
    store.save_items(db_session, [normal])
    ids = [i["id"] for i in client.get(f"/api/reports/{rid}/review", headers=auth_headers).json()["items"]]
    assert ids == [it.id]
    ids = [i["id"] for i in client.get(f"/api/reports/{rid}/review?include=normals",
                                        headers=auth_headers).json()["items"]]
    assert set(ids) == {it.id, normal.id}


def test_get_review_owner_scoped(client, seeded, db_session):
    h = _other_headers(db_session)
    rid, _ = seeded
    assert client.get(f"/api/reports/{rid}/review", headers=h).json() == {"success": False, "error": "Report not found"}


def test_post_routes_owner_scoped(client, seeded, db_session, monkeypatch):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    seen = []
    monkeypatch.setattr(engine, "schedule_review", lambda rid, text=None: seen.append(rid))
    h = _other_headers(db_session)
    rid, it = seeded
    nf = {"success": False, "error": "Report not found"}
    assert client.post(f"/api/reports/{rid}/review/items/{it.id}/events", headers=h,
                       json={"command": "apply"}).json() == nf
    assert client.post(f"/api/reports/{rid}/review/probe", headers=h,
                       json={"text": REPORT, "text_hash": "h", "changed_ranges": []}).json() == nf
    assert client.post(f"/api/reports/{rid}/review/reprepare", headers=h,
                       json={"item_ids": [it.id], "text": REPORT, "text_hash": "h"}).json() == nf
    assert client.post(f"/api/reports/{rid}/review/rerun", headers=h, json={}).json() == nf
    assert seen == [] and store.get_item(db_session, rid, it.id).status == "open"


def test_item_event(client, auth_headers, seeded):
    rid, it = seeded
    r = client.post(f"/api/reports/{rid}/review/items/{it.id}/events", headers=auth_headers,
                    json={"command": "apply", "text_hash": "h", "detail": {}}).json()
    assert r["success"] and r["item"]["status"] == "applied"
    bad = client.post(f"/api/reports/{rid}/review/items/{it.id}/events", headers=auth_headers,
                      json={"command": "explode"})
    assert bad.status_code == 422 and not bad.json()["success"]


@pytest.mark.parametrize("command", ["pre_applied", "addressed", "stale", "prepared"])
def test_item_event_rejects_engine_statuses(client, auth_headers, seeded, db_session, command):
    rid, it = seeded
    r = client.post(f"/api/reports/{rid}/review/items/{it.id}/events", headers=auth_headers,
                    json={"command": command})
    assert r.status_code == 422 and r.json()["success"] is False
    got = store.get_item(db_session, rid, it.id)
    assert got.status == "open" and got.history == []


def test_item_event_wrong_report(client, auth_headers, seeded, db_session, test_user):
    rid, it = seeded
    r2 = Report(report_type="quick", model_used="m", report_content=REPORT, user_id=test_user.id)
    db_session.add(r2)
    db_session.commit()
    r = client.post(f"/api/reports/{r2.id}/review/items/{it.id}/events", headers=auth_headers,
                    json={"command": "dismiss"}).json()
    assert r == {"success": False, "error": "Item not found"}


def test_probe_requires_engine(client, auth_headers, seeded, monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    rid, _ = seeded
    r = client.post(f"/api/reports/{rid}/review/probe", headers=auth_headers,
                    json={"text": REPORT, "text_hash": "h", "changed_ranges": []}).json()
    assert r == {"success": False, "error": "review engine off"}


def test_probe_marks_addressed(client, auth_headers, seeded, monkeypatch, db_session):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(rc, "_jev", jev({"p0": {"noul": 0.9}}))
    rid, it = seeded
    r = client.post(f"/api/reports/{rid}/review/probe", headers=auth_headers,
                    json={"text": REPORT, "text_hash": "h2", "changed_ranges": []}).json()
    assert r["success"] and r["addressed"] == [it.id] and r["text_hash"] == "h2"
    assert store.get_item(db_session, rid, it.id).status == "addressed"


def test_probe_never_writes_report(client, auth_headers, seeded, monkeypatch, db_session):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(rc, "_jev", jev({"p0": {"noul": 0.9}}))
    rid, _ = seeded
    client.post(f"/api/reports/{rid}/review/probe", headers=auth_headers,
                json={"text": "FINDINGS:\nchanged", "text_hash": "h2", "changed_ranges": [[10, 17]]})
    row = db_session.get(Report, uuid.UUID(rid))
    db_session.refresh(row)
    assert row.report_content == REPORT and row.candidate_reports[0]["content"] == REPORT


def test_reprepare(client, auth_headers, seeded, monkeypatch, db_session):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(rc, "_jev", jev({"a": {"noul": 0.9}}))
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(
        cls="minor", kind="partial", label="New label", reason="r", edit_mode="none")))
    rid, it = seeded
    r = client.post(f"/api/reports/{rid}/review/reprepare", headers=auth_headers,
                    json={"item_ids": [it.id], "text": REPORT, "text_hash": "h3"}).json()
    assert r["success"] and r["items"][0]["label"] == "New label"
    got = store.get_item(db_session, rid, it.id)
    assert got.label == "New label" and got.history[-1]["event"] == "prepared"


def test_reprepare_never_rewrites_negatives(client, auth_headers, seeded, monkeypatch, db_session):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(rc, "_jev", jev({"a": {"noul": 0.9}}))
    calls = []
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(
        cls="minor", kind="partial", label="Rewritten", reason="r", edit_mode="replace",
        edit_find="The liver is normal.", edit_replace="The liver is abnormal."), calls))
    rid, it = seeded
    _, removal, acc = _neg_items(rid, it.run_id)
    store.save_items(db_session, [removal, acc])
    r = client.post(f"/api/reports/{rid}/review/reprepare", headers=auth_headers,
                    json={"item_ids": [removal.id, acc.id], "text": REPORT, "text_hash": "h4"}).json()
    assert r["success"] and calls == []
    by_id = {i["id"]: i for i in r["items"]}
    for orig in (removal, acc):
        got = store.get_item(db_session, rid, orig.id)
        assert got.label == orig.label and got.edit == orig.edit and got.cls == orig.cls
        assert by_id[orig.id]["edit"] == orig.edit.model_dump()


def test_rerun_requires_engine(client, auth_headers, seeded, monkeypatch):
    monkeypatch.delenv("RR_REVIEW_ENGINE", raising=False)
    rid, _ = seeded
    r = client.post(f"/api/reports/{rid}/review/rerun", headers=auth_headers, json={}).json()
    assert r == {"success": False, "error": "review engine off"}


def test_rerun_schedules(client, auth_headers, seeded, monkeypatch):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    seen = []
    monkeypatch.setattr(engine, "schedule_review", lambda rid, text=None: seen.append((rid, text)))
    rid, _ = seeded
    r = client.post(f"/api/reports/{rid}/review/rerun", headers=auth_headers, json={"text": "X"}).json()
    assert r == {"success": True, "status": "running"} and seen == [(rid, "X")]


def test_reprepare_never_rewrites_brief_linked_normals(client, auth_headers, seeded, monkeypatch, db_session):
    """Gate G: the brief's linked-normal items (green assumed normals, amber implicated checks) are negatives too;
    an edit elsewhere must not let the adjudicator relabel them (it suppressed amber checks as "passed")."""
    from rapid_reports_ai.review_engine import brief_normals
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(rc, "_jev", jev({"a": {"noul": 0.9}}))
    calls = []
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(
        cls="suppress", kind="assumed_normal", label="Listed as unremarkable", reason="r",
        edit_mode="none"), calls))
    rid, it = seeded
    green = ReviewItem(key="b1", report_id=rid, run_id=it.run_id, lane="accuracy",
                       detectors=[brief_normals.DETECTOR], kind="assumed_normal", cls="info", section="FINDINGS",
                       label="Assumed normal", anchor=Span(start=10, end=30, text="The liver is normal."))
    amber = ReviewItem(key="b2", report_id=rid, run_id=it.run_id, lane="accuracy",
                       detectors=[brief_normals.DETECTOR], kind="check", cls="minor", section="FINDINGS",
                       label="Check: may not hold given “cyst”", evidence={"check_reason": "uncertain"},
                       anchor=Span(start=10, end=30, text="The liver is normal."))
    store.save_items(db_session, [green, amber])
    r = client.post(f"/api/reports/{rid}/review/reprepare", headers=auth_headers,
                    json={"item_ids": [green.id, amber.id], "text": REPORT, "text_hash": "h5"}).json()
    assert r["success"] and calls == []
    for orig in (green, amber):
        got = store.get_item(db_session, rid, orig.id)
        assert got.cls == orig.cls and got.label == orig.label and got.kind == orig.kind


def _pre_applied_insert(rid, run_id, cls="action"):
    """A post-gen check insert the engine pre-applied (live.bridge_items shape)."""
    return ReviewItem(key="pa1", report_id=rid, run_id=run_id, lane="coverage", detectors=["post_check.insert"],
                      kind="absent", cls=cls, section="FINDINGS", label="Added from your dictation",
                      anchor=Span(start=10, end=30, text="The liver is normal."), probe="The liver is described.",
                      edit=Edit(mode="insert", find=None, replace="The liver is normal.", section="FINDINGS"),
                      status="pre_applied",
                      history=[{"event": "created", "actor": "engine"},
                               {"event": "pre_applied", "actor": "post_check", "detail": {"kind": "absent"}}])


def test_pre_applied_item_survives_undo_probe_reprepare_discard(client, auth_headers, seeded, monkeypatch,
                                                               db_session):
    """Gate G (F1 note B), decided: engine pre-applied items are never re-judged by the probe or reprepare and never
    hidden. Undo the pre-applied insert → probe (would address it / send it to reprepare) → reprepare (adjudicator
    says suppress) → Discard: the item is back to pre_applied, its cls untouched, and GET still returns it."""
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(rc, "_jev", jev({"p*": {"noul": 0.9}, "a": {"noul": 0.9}}))
    calls = []
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(
        cls="suppress", kind="absent", label="Redundant", reason="r", edit_mode="none"), calls))
    rid, it = seeded
    pa = _pre_applied_insert(rid, it.run_id)
    store.save_items(db_session, [pa])
    url = f"/api/reports/{rid}/review"
    assert client.post(f"{url}/items/{pa.id}/events", headers=auth_headers,
                       json={"command": "undo", "text_hash": "h1"}).json()["item"]["status"] == "open"
    r = client.post(f"{url}/probe", headers=auth_headers,
                    json={"text": REPORT, "text_hash": "h2", "changed_ranges": [[10, 30]]}).json()
    assert r["success"] and pa.id not in r["addressed"] and pa.id not in r["reprepare"]
    assert it.id in r["addressed"]                               # ordinary items are still probed
    assert store.get_item(db_session, rid, pa.id).status == "open"
    r = client.post(f"{url}/reprepare", headers=auth_headers,
                    json={"item_ids": [pa.id], "text": REPORT, "text_hash": "h3"}).json()
    assert r["success"] and calls == [] and [i["id"] for i in r["items"]] == [pa.id]
    got = store.get_item(db_session, rid, pa.id)
    assert got.cls == "action" and got.label == pa.label and got.history[-1]["event"] == "undo"
    client.post(f"{url}/items/{pa.id}/events", headers=auth_headers,
                json={"command": "apply", "text_hash": "h4", "detail": {"via": "discard", "reinstate": "pre_applied"}})
    items = {i["id"]: i for i in client.get(url, headers=auth_headers).json()["items"]}
    assert items[pa.id]["status"] == "pre_applied" and items[pa.id]["cls"] == "action"


@pytest.mark.parametrize("status", ["pre_applied", "open"])
def test_get_review_never_hides_pre_applied_items(client, auth_headers, seeded, db_session, status):
    """An engine pre-applied item already relabelled cls=suppress (before this fix) is still returned, cls as
    stored, whether it still holds the engine's write or the user undid it; other suppress items stay hidden."""
    rid, it = seeded
    pa = _pre_applied_insert(rid, it.run_id, cls="suppress")
    pa.status = status
    plain = ReviewItem(key="s1", report_id=rid, run_id=it.run_id, lane="coverage", detectors=["jev.classify_first"],
                       kind="partial", cls="suppress", section="FINDINGS", label="Hidden")
    store.save_items(db_session, [pa, plain])
    items = {i["id"]: i for i in client.get(f"/api/reports/{rid}/review", headers=auth_headers).json()["items"]}
    assert items[pa.id]["cls"] == "suppress" and items[pa.id]["status"] == status
    assert plain.id not in items


def test_probe_skips_contradiction_on_a_restored_removal(client, auth_headers, seeded, monkeypatch, db_session):
    """Gate G (F1 note E): restoring a contradicted removal puts the clause back; the probe must not add a second
    "contradicted" card for it. The restored item is the one row for that span."""
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(rc, "_jev", jev({"x*": {"noul": 0.95}}))
    rid, it = seeded
    removal = ReviewItem(key="rm1", report_id=rid, run_id=it.run_id, lane="accuracy", detectors=["negatives.v5"],
                         kind="removed", cls="action", section="FINDINGS", label="Negative contradicted",
                         anchor=Span(start=10, end=10, text=""),
                         evidence={"removed_text": "The liver is normal.", "clause": "The liver is normal."},
                         edit=Edit(mode="remove", find="The liver is normal."), status="pre_applied",
                         history=[{"event": "pre_applied", "actor": "engine"}])
    store.save_items(db_session, [removal])
    client.post(f"/api/reports/{rid}/review/items/{removal.id}/events", headers=auth_headers,
                json={"command": "restore", "text_hash": "h1"})
    start = REPORT.index("The liver is normal.")
    r = client.post(f"/api/reports/{rid}/review/probe", headers=auth_headers,
                    json={"text": REPORT, "text_hash": "h2",
                          "changed_ranges": [[start, start + len("The liver is normal.")]]}).json()
    assert r["success"]
    assert not [i for i in r["new_items"] if "liver" in (i["anchor"] or {}).get("text", "")]


def test_probe_still_adds_contradictions_elsewhere(client, auth_headers, seeded, monkeypatch, db_session):
    """Control for the restored-removal dedupe: without a restored item on the clause, the contradiction is added."""
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(rc, "_jev", jev({"x*": {"noul": 0.95}}))
    rid, _ = seeded
    start = REPORT.index("The liver is normal.")
    r = client.post(f"/api/reports/{rid}/review/probe", headers=auth_headers,
                    json={"text": REPORT, "text_hash": "h2",
                          "changed_ranges": [[start, start + len("The liver is normal.")]]}).json()
    assert [i for i in r["new_items"] if "liver" in (i["anchor"] or {}).get("text", "")]


@pytest.mark.parametrize("restored", [False, True])
def test_probe_skips_contradiction_racing_a_restore(client, auth_headers, seeded, monkeypatch, db_session, restored):
    """Gate G re-check: the client posts Restore and the probe together, so the probe can read the removal still
    pre_applied. A removal item (pre_applied, or open after restore) already covers its clause either way; so does
    an open contradiction card from an earlier probe."""
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(rc, "_jev", jev({"x*": {"noul": 0.95}}))
    rid, it = seeded
    removal = ReviewItem(key="rm2", report_id=rid, run_id=it.run_id, lane="accuracy", detectors=["synthetic"],
                         kind="removed", cls="action", section="FINDINGS", label="Negative contradicted",
                         anchor=Span(start=10, end=10, text=""), evidence={"removed_text": "The liver is normal."},
                         status="open" if restored else "pre_applied",
                         history=[{"event": "pre_applied", "actor": "post_check"}])
    store.save_items(db_session, [removal])
    start = REPORT.index("The liver is normal.")
    body = {"text": REPORT, "text_hash": "h2", "changed_ranges": [[start, start + len("The liver is normal.")]]}
    r = client.post(f"/api/reports/{rid}/review/probe", headers=auth_headers, json=body).json()
    assert r["success"] and r["new_items"] == []


def test_probe_adds_one_contradiction_card_per_clause(client, auth_headers, seeded, monkeypatch, db_session):
    monkeypatch.setenv("RR_REVIEW_ENGINE", "shadow")
    monkeypatch.setattr(rc, "_jev", jev({"x*": {"noul": 0.95}}))
    rid, _ = seeded
    start = REPORT.index("The liver is normal.")
    body = {"text": REPORT, "text_hash": "h2", "changed_ranges": [[start, start + len("The liver is normal.")]]}
    first = client.post(f"/api/reports/{rid}/review/probe", headers=auth_headers, json=body).json()
    again = client.post(f"/api/reports/{rid}/review/probe", headers=auth_headers, json=body).json()
    assert len([i for i in first["new_items"] if "liver" in i["anchor"]["text"]]) == 1
    assert again["new_items"] == []
