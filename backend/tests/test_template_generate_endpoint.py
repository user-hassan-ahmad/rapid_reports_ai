"""Template endpoints (spec §4): legacy (non skill-sheet) templates are retired —
hidden from lists, generation refused, rows never deleted."""
from __future__ import annotations

from rapid_reports_ai.database import crud
from rapid_reports_ai.database.models import Template


def _ids(client, headers, **params):
    body = client.get("/api/templates", headers=headers, params=params).json()
    assert body["success"] is True
    return {t["id"] for t in body["templates"]}


def test_list_hides_legacy_templates(client, auth_headers, legacy_template, guided_template):
    ids = _ids(client, auth_headers)
    assert str(guided_template.id) in ids and str(legacy_template.id) not in ids


def test_list_pagination_counts_only_visible_templates(client, auth_headers, legacy_template, guided_template):
    # The retired row must not consume the page slot of a visible one.
    assert _ids(client, auth_headers, limit=1) == {str(guided_template.id)}


def test_tag_filtered_list_hides_legacy(db_session, test_user, legacy_template, guided_template):
    # The endpoint's `tags` arg is not bound from the query string, so pin the crud tag path directly.
    assert crud.get_templates(db_session, str(test_user.id), tags=["legacy-tag"]) == []
    assert crud.get_templates(db_session, str(test_user.id), tags=["guided-tag"]) == [guided_template]


def test_tags_endpoint_omits_tags_only_on_retired_templates(client, auth_headers, legacy_template, guided_template):
    tags = client.get("/api/templates/tags", headers=auth_headers).json()["tags"]
    assert "guided-tag" in tags and "legacy-tag" not in tags


def test_legacy_template_is_refused(client, auth_headers, legacy_template, db_session):
    r = client.post(f"/api/templates/{legacy_template.id}/generate", json={"user_inputs": {"FINDINGS": "f"}},
                    headers=auth_headers).json()
    assert r["success"] is False
    assert "retired template format" in r["error"] and "skill-sheet" in r["error"]
    # Retired, never deleted.
    assert db_session.get(Template, legacy_template.id) is not None


def test_malformed_and_missing_configs_are_hidden_and_do_not_break_the_list(
        client, auth_headers, db_session, test_user, guided_template):
    bad = [Template(name=f"Bad{i}", template_config=cfg, user_id=test_user.id, tags=[], is_active=True)
           for i, cfg in enumerate([["skill_sheet_guided"], "skill_sheet_guided", None])]
    db_session.add_all(bad)
    db_session.commit()
    assert all(crud.is_retired_template(t) for t in bad)
    assert _ids(client, auth_headers) == {str(guided_template.id)}
