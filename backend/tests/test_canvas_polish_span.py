from __future__ import annotations

import json
import logging
import uuid

import pytest

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.lean_polish import LEAN_SYSTEM_PROMPT
from rapid_reports_ai.main import app

BODY = {"scan_type": "CT head", "context": "Basal cisterns are patent.",
        "span": "Mild mass effect with 3 mm of midline shift.", "new": "Actually make that 7 mm."}


@pytest.fixture
def authed_client(client, db_session):
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="T",
                is_active=True, is_verified=True, is_approved=True)
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def lab(monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    calls = []

    async def fake(primary, fallback, *, output_type, system_prompt, user_prompt, model_settings,
                   use_thinking=False, label="canvas", usage_out=None):
        calls.append({"system": system_prompt, "user": user_prompt, "label": label})
        if usage_out is not None:
            usage_out.update(model="m", input_tokens=410, output_tokens=30)
        return output_type(active_scratchpad="Mild mass effect with 7 mm of midline shift.",
                           committed_edits=[{"original": "Basal cisterns are patent.", "corrected": "x"}])
    monkeypatch.setattr(cr, "_run_canvas_with_fallback", fake)
    return calls


def test_404_without_the_lab_flag(authed_client, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    assert authed_client.post("/api/canvas/polish-span", json=BODY).status_code == 404


def test_rewrites_the_span_with_the_lean_prompt(authed_client, lab):
    d = authed_client.post("/api/canvas/polish-span", json=BODY).json()
    assert d["active_scratchpad"] == "Mild mass effect with 7 mm of midline shift."
    assert d["committed_edits"] == [{"original": "Basal cisterns are patent.", "corrected": "x"}]
    assert d["usage"]["input_tokens"] == 410 and d["skipped"] is False and d["error"] is None
    assert lab[0]["system"] == LEAN_SYSTEM_PROMPT
    assert "SPAN:\nMild mass effect with 3 mm of midline shift." in lab[0]["user"]
    assert "NEW:\nActually make that 7 mm." in lab[0]["user"]


def test_code_decided_utterances_skip_the_model(authed_client, lab):
    d = authed_client.post("/api/canvas/polish-span", json={**BODY, "new": "Conclusion."}).json()
    assert d["skipped"] is True and lab == []


def test_a_model_failure_is_an_answer_not_an_error(authed_client, lab, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(cr, "_run_canvas_with_fallback", boom)
    r = authed_client.post("/api/canvas/polish-span", json=BODY)
    assert r.status_code == 200 and r.json()["error"] == "RuntimeError"


def test_log_line_is_data_only(authed_client, lab, caplog):
    with caplog.at_level(logging.INFO, logger=cr.logger.name):
        authed_client.post("/api/canvas/polish-span", json=BODY)
    line = next(r.getMessage() for r in caplog.records if "canvas.polish_span" in r.getMessage())
    p = json.loads(line.split(" ", 1)[1])
    assert p["span_len"] == len(BODY["span"]) and p["input_tokens"] == 410
    assert "midline" not in line and "cisterns" not in line


def test_a_trailing_command_is_code_not_words_and_survives(authed_client, lab):
    # lab: "…make that 14 millimetres. New paragraph." as one final lost its paragraph break
    body = {**BODY, "new": "Actually make that 14 mm. New paragraph."}
    d = authed_client.post("/api/canvas/polish-span", json=body).json()
    assert "New paragraph" not in lab[0]["user"] and "NEW:\nActually make that 14 mm." in lab[0]["user"]
    assert d["active_scratchpad"].endswith("\n\n")  # the model's output had no break; code adds it


def test_no_break_is_added_when_none_was_said(authed_client, lab):
    d = authed_client.post("/api/canvas/polish-span", json=BODY).json()
    assert not d["active_scratchpad"].endswith("\n")


def test_the_prompt_keeps_finished_sentences_and_places_dangling_cues():
    assert "never join it onto the finished sentence" in LEAN_SYSTEM_PROMPT
    assert "dangling" in LEAN_SYSTEM_PROMPT


def test_the_prompt_says_a_correction_is_never_also_added():
    assert "never also add it as a new sentence" in LEAN_SYSTEM_PROMPT


def _model_returning(monkeypatch, active, edits):
    async def fake(primary, fallback, *, output_type, system_prompt, user_prompt, model_settings,
                   use_thinking=False, label="canvas", usage_out=None):
        return output_type(active_scratchpad=active, committed_edits=edits)
    monkeypatch.setattr(cr, "_run_canvas_with_fallback", fake)


def test_a_correction_applied_to_an_earlier_line_is_not_also_appended(authed_client, lab, monkeypatch):
    # lab + live check: the edit (14 → 15 mm) was made AND the sentence was added again
    _model_returning(monkeypatch,
                     "No free fluid. The spleen measures 10 centimetres. The common bile duct measures 15 millimetres.",
                     [{"original": "measuring 14 millimetres.", "corrected": "measuring 15 millimetres."}])
    d = authed_client.post("/api/canvas/polish-span", json={
        **BODY, "span": "No free fluid. The spleen measures 10 centimetres. Correction.",
        "new": "The common bowel duct measures 15 millimetres."}).json()
    assert d["active_scratchpad"] == "No free fluid. The spleen measures 10 centimetres."
    assert len(d["committed_edits"]) == 1


def test_without_an_earlier_edit_the_new_sentence_stays(authed_client, lab, monkeypatch):
    _model_returning(monkeypatch, "The spleen measures 10 centimetres. The common bile duct measures 6 mm.", [])
    d = authed_client.post("/api/canvas/polish-span", json={
        **BODY, "span": "The spleen measures 10 centimetres.", "new": "The common bile duct measures 6 mm."}).json()
    assert d["active_scratchpad"].endswith("The common bile duct measures 6 mm.")


def test_an_unrelated_last_sentence_is_kept_even_with_an_edit(authed_client, lab, monkeypatch):
    _model_returning(monkeypatch, "The spleen measures 10 centimetres. No free fluid.",
                     [{"original": "measuring 14 mm", "corrected": "measuring 15 mm"}])
    d = authed_client.post("/api/canvas/polish-span", json={
        **BODY, "span": "The spleen measures 10 centimetres.", "new": "Actually the duct is 15 mm. No free fluid."}).json()
    assert d["active_scratchpad"].endswith("No free fluid.")


def test_a_repeated_correction_in_the_middle_is_dropped_and_the_new_finding_kept(authed_client, lab, monkeypatch):
    # re-test session: 'Correction. The liver lesion measures 18 millimetres. There is a 6 mm nodule in the left'
    _model_returning(monkeypatch,
                     "The spleen is normal. The adrenal glands are normal. The liver lesion measures 18 millimetres. "
                     "There is a 6 mm nodule in the left",
                     [{"original": "a 14 millimetre", "corrected": "an 18 millimetre"}])
    d = authed_client.post("/api/canvas/polish-span", json={
        **BODY, "span": "The spleen is normal. The adrenal glands are normal.",
        "new": "Correction. The liver lesion measures 18 millimetres. There is a 6 mm nodule in the left"}).json()
    assert d["active_scratchpad"] == "The spleen is normal. The adrenal glands are normal. There is a 6 mm nodule in the left"


def test_a_cue_led_correction_sentence_is_dropped_and_the_rest_kept(authed_client, lab, monkeypatch):
    _model_returning(monkeypatch, "The kidneys are normal. The nodule is in the right lower lobe. No pneumothorax.",
                     [{"original": "the left lower lobe", "corrected": "the right lower lobe"}])
    d = authed_client.post("/api/canvas/polish-span", json={
        **BODY, "span": "The kidneys are normal.",
        "new": "Correction, the nodule is in the right lower lobe. No pneumothorax."}).json()
    assert d["active_scratchpad"] == "The kidneys are normal. No pneumothorax."


def test_a_sentence_already_in_the_span_is_never_dropped(authed_client, lab, monkeypatch):
    _model_returning(monkeypatch, "The liver lesion measures 18 mm. No free fluid.",
                     [{"original": "a 14 mm", "corrected": "an 18 mm"}])
    d = authed_client.post("/api/canvas/polish-span", json={
        **BODY, "span": "The liver lesion measures 18 mm.", "new": "Correction. The liver lesion measures 18 mm. No free fluid."}).json()
    assert d["active_scratchpad"] == "The liver lesion measures 18 mm. No free fluid."
