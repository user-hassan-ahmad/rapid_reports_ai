from __future__ import annotations

import json
import logging
import uuid

import pytest

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.dictation_triage import TriageDecision, TriageError
from rapid_reports_ai.jev_questions import FAST_APPEND_BANDS, QSET_VERSION
from rapid_reports_ai.main import app
from rapid_reports_ai.utterance_bundle import BundleDecision, BundleState

BODY = {
    "scan_type": "CT chest",
    "active": "There is a 10 mm nodule.",
    "open_line": "",
    "latest_utterance": "um no pleural effusion.",
    "checklist": ["LUNGS", "PLEURA"],
}


@pytest.fixture
def authed_client(client, db_session):
    user = User(
        id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="T",
        is_active=True, is_verified=True, is_approved=True,
    )
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


class FakeBundle:
    def __init__(self, action="append_new_finding", conf=0.97, raise_=False):
        self.action, self.conf, self.raise_, self.states = action, conf, raise_, []

    async def classify(self, state: BundleState, word_sense: bool = False) -> BundleDecision:
        self.states.append(state)
        self.word_sense_asked = word_sense
        if self.raise_:
            raise TriageError("jev bundle http 502")
        return BundleDecision(
            triage=TriageDecision("jev", self.action, self.conf, {self.action: self.conf}, 0.04, 0.1, 240, 900, 3e-5),
            standalone=0.8, coverage={"LUNGS": 0.2, "PLEURA": 0.9}, latency_ms=240, n_questions=6,
            input_tokens=900, cost_usd=3e-5,
        )


@pytest.fixture
def lab(monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    def install(fake):
        monkeypatch.setattr(cr, "get_jev_bundle", lambda: fake)
        return fake
    return install


def test_404_without_the_lab_flag(authed_client, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    assert authed_client.post("/api/canvas/bundle", json=BODY).status_code == 404


def test_confident_append_is_fast_appended(authed_client, lab):
    fake = lab(FakeBundle())
    r = authed_client.post("/api/canvas/bundle", json=BODY)
    assert r.status_code == 200
    d = r.json()
    assert d["route"] == "fast_append" and d["reason"] == "append_confident"
    assert d["text"] == "no pleural effusion." and d["closes_line"] is True
    assert d["qset"] == QSET_VERSION and len(d["decision_id"]) == 12
    assert d["action"] == "append_new_finding" and d["confidence"] == 0.97
    assert d["standalone"] == 0.8 and d["close_on_silence"] is True
    assert d["coverage"] == {"LUNGS": 0.2, "PLEURA": 0.9}
    assert d["line_close"] == {
        "silence_s": FAST_APPEND_BANDS["line_close_silence_s"],
        "hard_limit_s": FAST_APPEND_BANDS["line_close_hard_limit_s"],
    }
    # the bundle is asked about the raw words, as Deepgram delivered them
    s = fake.states[0]
    assert (s.latest_utterance, s.active, s.open_line, s.checklist) == (
        "um no pleural effusion.", "There is a 10 mm nodule.", "", ["LUNGS", "PLEURA"])


def test_jev_error_fails_open_to_polish(authed_client, lab):
    lab(FakeBundle(raise_=True))
    d = authed_client.post("/api/canvas/bundle", json=BODY).json()
    assert (d["route"], d["reason"], d["error"]) == ("polish", "jev_error", "TriageError")
    assert d["decision_id"]


def test_unexpected_exception_also_fails_open(authed_client, lab):
    class Broken:
        async def classify(self, state, word_sense=False):
            raise RuntimeError("anything")
    lab(Broken())
    d = authed_client.post("/api/canvas/bundle", json=BODY).json()
    assert (d["route"], d["reason"], d["error"]) == ("polish", "jev_error", "RuntimeError")


def test_filler_only_skips_without_calling_jev(authed_client, lab):
    fake = lab(FakeBundle())
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": "um, uh"}).json()
    assert d["route"] == "skip" and fake.states == []


def test_command_returns_the_characters(authed_client, lab):
    lab(FakeBundle("formatting_command", 0.95))
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": "new paragraph"}).json()
    assert (d["route"], d["insert"]) == ("command", "\n\n")


def test_decision_log_line_carries_data_never_text(authed_client, lab, caplog):
    lab(FakeBundle())
    with caplog.at_level(logging.INFO, logger=cr.logger.name):
        d = authed_client.post("/api/canvas/bundle", json=BODY).json()
    lines = [r.getMessage() for r in caplog.records if "canvas.bundle.decision" in r.getMessage()]
    assert len(lines) == 1
    payload = json.loads(lines[0].split(" ", 1)[1])
    assert payload["event"] == "canvas.bundle.decision"
    assert payload["decision_id"] == d["decision_id"]
    assert payload["qset"] == QSET_VERSION and payload["route"] == "fast_append"
    assert payload["probabilities"] == {"append_new_finding": 0.97}
    assert payload["utterance_len"] == len(BODY["latest_utterance"])
    assert len(payload["utterance_sha8"]) == 8
    assert "pleural" not in lines[0] and "nodule" not in lines[0]


def test_deepgram_confidence_is_logged(authed_client, lab, caplog):
    lab(FakeBundle())
    body = {**BODY, "asr_conf": 0.91, "asr_min_conf": 0.61, "asr_word_confs": [0.99, 0.61, 0.97]}
    with caplog.at_level(logging.INFO, logger=cr.logger.name):
        d = authed_client.post("/api/canvas/bundle", json=body).json()
    assert d["route"] == "polish"  # 0.61 is under the 0.70 word-confidence gate
    line = next(r.getMessage() for r in caplog.records if "canvas.bundle.decision" in r.getMessage())
    p = json.loads(line.split(" ", 1)[1])
    assert (p["asr_conf"], p["asr_min_conf"], p["asr_n_words"]) == (0.91, 0.61, 3)


def test_without_deepgram_confidence_the_log_says_so(authed_client, lab, caplog):
    lab(FakeBundle())
    with caplog.at_level(logging.INFO, logger=cr.logger.name):
        authed_client.post("/api/canvas/bundle", json=BODY)
    line = next(r.getMessage() for r in caplog.records if "canvas.bundle.decision" in r.getMessage())
    p = json.loads(line.split(" ", 1)[1])
    assert (p["asr_conf"], p["asr_min_conf"], p["asr_n_words"]) == (None, None, None)


def test_a_bare_full_stop_is_a_command_without_asking_jev(authed_client, lab):
    fake = lab(FakeBundle())
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": ". "}).json()
    assert (d["route"], d["reason"], d["insert"]) == ("command", "punctuation_mark", ".")
    assert fake.states == []


def test_the_route_applies_the_deepgram_gate(authed_client, lab):
    lab(FakeBundle())
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "asr_min_conf": 0.62}).json()
    assert (d["route"], d["reason"]) == ("polish", "asr_low_confidence")


def test_the_colon_is_read_against_the_scratchpad_before_it(authed_client, lab):
    fake = lab(FakeBundle())
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "active": "Normal marrow.\n\nL5/S1",
                                                         "latest_utterance": "colon"}).json()
    assert (d["route"], d["insert"]) == ("command", ":") and fake.states == []


def test_the_response_says_when_a_paragraph_starts(authed_client, lab):
    lab(FakeBundle())
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": "L3 slash four mild desiccation"}).json()
    assert (d["text"], d["starts_paragraph"]) == ("L3/4 Mild desiccation", True)


def test_the_response_carries_the_cleaned_text_for_polish(authed_client, lab):
    lab(FakeBundle("correct_previous_finding", 0.99))
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": "L3 slash four, colon, mild"}).json()
    assert (d["route"], d["clean_text"]) == ("polish", "L3/4: mild")



class SenseBundle(FakeBundle):
    async def classify(self, state, word_sense=False):
        from dataclasses import replace
        d = await super().classify(state, word_sense)
        return replace(d, word_sense=(("renal", 0.81), ("glands", 0.37), ("normal", 0.9)))


def test_the_route_asks_word_sense_and_applies_a_confident_fix(authed_client, lab, monkeypatch):
    from rapid_reports_ai.asr_repair import RepairResult
    fake = lab(SenseBundle())
    seen = {}

    async def fake_repair(sentence, word_sense, **kw):
        seen["sentence"], seen["senses"] = sentence, word_sense
        return RepairResult(sentence.replace("renal", "adrenal"), [{"heard": "renal", "replacement": "adrenal", "confidence": 0.93}],
                            [], 1, 240, None)
    monkeypatch.setattr(cr, "repair", fake_repair)
    d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": "The renal glands are also normal."}).json()
    assert fake.word_sense_asked is True and seen["sentence"] == "The renal glands are also normal."
    assert d["route"] == "fast_append" and d["text"] == d["clean_text"] == "The adrenal glands are also normal."
    assert d["asr_fixes"] == [{"heard": "renal", "replacement": "adrenal", "confidence": 0.93}] and d["repair_ms"] == 240


def test_flags_are_returned_and_the_log_has_no_words(authed_client, lab, monkeypatch, caplog):
    from rapid_reports_ai.asr_repair import RepairResult
    lab(SenseBundle())

    async def fake_repair(sentence, word_sense, **kw):
        return RepairResult(sentence, [], [{"word": "glands", "score": 0.37}], 0, None, None)
    monkeypatch.setattr(cr, "repair", fake_repair)
    with caplog.at_level(logging.INFO, logger=cr.logger.name):
        d = authed_client.post("/api/canvas/bundle", json={**BODY, "latest_utterance": "The renal glands are also normal."}).json()
    assert d["asr_flags"] == [{"word": "glands", "score": 0.37}] and d["text"] == "The renal glands are also normal."
    line = next(r.getMessage() for r in caplog.records if "canvas.bundle.decision" in r.getMessage())
    p = json.loads(line.split(" ", 1)[1])
    assert p["asr_flag_count"] == 1 and p["asr_fix_count"] == 0 and p["word_sense_min"] == 0.37
    assert "glands" not in line and "renal" not in line
