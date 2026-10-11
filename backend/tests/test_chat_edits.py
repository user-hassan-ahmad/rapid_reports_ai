"""Spec §12.5 (Plan 3 D1): the report chat reply gains verified `edits[]` alongside prose.

The model emits edits as a decoded JSON string (`edits_json`, flat schema); each edit runs through
`review_engine.verifier.guard_failures` against the current report text; failed edits come back with
`verified: false` and their codes. The request's `open_items` go into the model context so chat doesn't
duplicate them. The old `edit_proposal` stays for one release."""
import json
from types import SimpleNamespace

import pytest

from rapid_reports_ai import chat_edits as ce
from rapid_reports_ai.database.models import Report
from rapid_reports_ai.review_engine import store
from rapid_reports_ai.review_engine.items import ReviewItem, Span

REPORT = "FINDINGS:\nThe liver is normal. A 14 mm left renal cyst.\nIMPRESSION:\nLeft renal cyst."
DICT = "- 14 mm left renal cyst with a thin septation"
SECTIONS = ["FINDINGS", "IMPRESSION"]
GOOD = {"section": "FINDINGS", "find": "A 14 mm left renal cyst.",
        "replace": "A 14 mm left renal cyst with a thin septation."}
BAD_NUMBER = {"section": "FINDINGS", "find": "A 14 mm left renal cyst.", "replace": "A 22 mm left renal cyst."}


# ── pure service ────────────────────────────────────────────────────────────

def test_parse_edits_json_accepts_string_and_drops_malformed():
    raw = json.dumps([GOOD, {"find": "x"}, "junk", {"section": "IMPRESSION", "replace": "y"}])
    out = ce.parse_edits_json(raw)
    assert out[0] == GOOD
    assert out[1] == {"section": "", "find": "x", "replace": ""}
    assert out[2] == {"section": "IMPRESSION", "find": "", "replace": "y"}
    assert len(out) == 3


@pytest.mark.parametrize("raw", [None, "", "not json", "{\"a\": 1}", 5])
def test_parse_edits_json_fails_open_to_empty(raw):
    assert ce.parse_edits_json(raw) == []


def test_parse_edits_json_takes_a_wrapped_list():
    assert ce.parse_edits_json(json.dumps({"edits": [GOOD]})) == [GOOD]


def test_verify_marks_good_edit_verified_and_bad_edit_failed():
    out = ce.verify_chat_edits(REPORT, [GOOD, BAD_NUMBER], DICT, "", SECTIONS)
    assert out[0] == {**GOOD, "verified": True, "failed": []}
    assert out[1]["verified"] is False and "ungrounded_number" in out[1]["failed"]


def test_verify_refuses_missing_find_and_no_change():
    out = ce.verify_chat_edits(REPORT, [{"section": "FINDINGS", "find": "", "replace": "x"},
                                        {"section": "FINDINGS", "find": "Left renal cyst.",
                                         "replace": "Left renal cyst."}], DICT, "", SECTIONS)
    assert out[0]["verified"] is False and out[0]["failed"] == ["missing_find"]
    assert out[1]["verified"] is False and out[1]["failed"] == ["no_change"]


def test_verify_refuses_absent_anchor_and_dropped_negation():
    report = "FINDINGS:\nNo ascites. A 14 mm left renal cyst.\nIMPRESSION:\nLeft renal cyst."
    out = ce.verify_chat_edits(report, [{"section": "FINDINGS", "find": "Not in the report.", "replace": "x"},
                                        {"section": "FINDINGS", "find": "No ascites.", "replace": "Ascites."}],
                               DICT, "", SECTIONS)
    assert "anchor_not_unique" in out[0]["failed"]
    assert "drops_negation" in out[1]["failed"]


def test_open_items_block_lists_compact_items_and_is_empty_without_items():
    assert ce.format_open_items_block([]) == ""
    block = ce.format_open_items_block([{"id": "i1", "section": "FINDINGS", "kind": "partial",
                                         "label": "Septation missing"}])
    assert "Septation missing" in block and "FINDINGS" in block and "do not propose" in block.lower()


def test_resolve_open_items_looks_up_ids_and_keeps_compact_dicts():
    stored = [SimpleNamespace(id="i1", section="FINDINGS", kind="partial", label="Septation missing",
                              reason="r", status="open")]
    out = ce.resolve_open_items(["i1", "missing", {"label": "Adrenal", "section": "FINDINGS"}], stored)
    assert out == [{"id": "i1", "section": "FINDINGS", "kind": "partial", "label": "Septation missing"},
                   {"id": "", "section": "FINDINGS", "kind": "", "label": "Adrenal"}]


# ── endpoint, mocked model ──────────────────────────────────────────────────

def _tool_call(args: dict):
    return SimpleNamespace(id="tc1", type="function",
                           function=SimpleNamespace(name="apply_structured_actions", arguments=json.dumps(args)))


class _FakeGroq:
    calls: list = []
    reply = None

    def __init__(self, api_key=None, **_):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        _FakeGroq.calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=_FakeGroq.reply)])


@pytest.fixture
def chat_env(monkeypatch, db_session, test_user):
    import groq
    from rapid_reports_ai import main
    _FakeGroq.calls = []
    monkeypatch.setattr(groq, "Groq", _FakeGroq)
    monkeypatch.setattr(main, "get_system_api_key", lambda *a, **k: "k")

    async def _regen(**_):
        return "WHOLE REPORT PROPOSAL"
    monkeypatch.setattr(main, "regenerate_report_with_actions", _regen)
    r = Report(report_type="quick", model_used="m", report_content=REPORT, user_id=test_user.id,
               input_data={"variables": {"FINDINGS": DICT, "SCAN_TYPE": "CT abdomen"}},
               candidate_reports=[{"content": REPORT, "sections": SECTIONS, "options": []}])
    db_session.add(r)
    db_session.commit()
    return str(r.id)


def _reply(content="", tool_calls=None):
    return SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls)


def test_reply_carries_verified_edits_and_keeps_edit_proposal(client, auth_headers, chat_env):
    _FakeGroq.reply = _reply("Added the septation.", [_tool_call({
        "actions": [{"title": "Add septation", "details": "Add the thin septation."}],
        "edits_json": json.dumps([GOOD, BAD_NUMBER]),
    })])
    body = client.post(f"/api/reports/{chat_env}/chat", json={"message": "add the septation"},
                       headers=auth_headers).json()
    assert body["success"] is True
    assert body["edit_proposal"] == "WHOLE REPORT PROPOSAL"
    assert body["edits"][0] == {**GOOD, "verified": True, "failed": []}
    assert body["edits"][1]["verified"] is False and "ungrounded_number" in body["edits"][1]["failed"]
    params = _FakeGroq.calls[0]["tools"][0]["function"]["parameters"]
    assert "edits_json" in params["properties"]      # flat: a decoded JSON string, not a nested array


def test_edits_verify_against_request_text_when_given(client, auth_headers, chat_env):
    text = REPORT.replace("A 14 mm left renal cyst.", "A 14 mm left renal cyst, simple.")
    _FakeGroq.reply = _reply("ok", [_tool_call({"actions": [{"title": "t", "details": "d"}],
                                                "edits_json": json.dumps([GOOD])})])
    body = client.post(f"/api/reports/{chat_env}/chat", json={"message": "m", "text": text},
                       headers=auth_headers).json()
    assert body["edits"][0]["verified"] is False and "anchor_not_unique" in body["edits"][0]["failed"]
    assert "A 14 mm left renal cyst, simple." in _FakeGroq.calls[0]["messages"][0]["content"]


def test_prose_only_reply_has_empty_edits(client, auth_headers, chat_env):
    _FakeGroq.reply = _reply("The cyst is Bosniak II.")
    body = client.post(f"/api/reports/{chat_env}/chat", json={"message": "what bosniak?"},
                       headers=auth_headers).json()
    assert body["success"] is True and body["edits"] == [] and body["edit_proposal"] is None


def test_open_items_reach_the_model_context(client, auth_headers, chat_env, db_session):
    run_id = store.create_run(db_session, chat_env, "shadow", "0.1.0", "quick")
    it = ReviewItem(key="k1", report_id=chat_env, run_id=run_id, lane="coverage", detectors=["d"], kind="partial",
                    cls="minor", section="FINDINGS", label="Septation missing",
                    anchor=Span(start=0, end=10, text="A 14 mm left renal cyst."))
    store.save_items(db_session, [it])
    _FakeGroq.reply = _reply("ok")
    client.post(f"/api/reports/{chat_env}/chat",
                json={"message": "m", "open_items": [it.id, {"label": "Adrenal not mentioned", "section": "FINDINGS"}]},
                headers=auth_headers)
    system = _FakeGroq.calls[0]["messages"][0]["content"]
    assert "Septation missing" in system and "Adrenal not mentioned" in system


def test_a_malformed_open_item_never_fails_the_chat(client, auth_headers, chat_env):
    """F2 M3: resolving open_items is inside the fail-open block: a malformed entry (an unhashable id) drops the
    open-items context, the chat still answers."""
    _FakeGroq.reply = _reply("ok")
    r = client.post(f"/api/reports/{chat_env}/chat",
                    json={"message": "m", "open_items": [{"id": ["not", "hashable"]}]}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["success"] is True
    assert "Open review items" not in _FakeGroq.calls[-1]["messages"][0]["content"]


# ── a whole-report rewrite becomes surgical edits (live b4e8e644: rewrite only, edits []) ─────────────────────────

CUR = ("FINDINGS:\nThe appendix is dilated to 11 mm. A 9 mm left adrenal nodule measures -5 HU. No hydronephrosis.\n\n"
       "IMPRESSION:\nPerforated acute appendicitis. Urgent surgical referral recommended.\n")


def test_diff_edits_turns_a_rewrite_into_sentence_edits_that_apply_once():
    new = CUR.replace("A 9 mm left adrenal nodule measures -5 HU.",
                      "A 9 mm left adrenal nodule measures -5 HU, in keeping with a lipid-rich adenoma.") \
             .replace("Perforated acute appendicitis.", "Perforated acute appendicitis without a drainable collection.")
    edits = ce.diff_edits(CUR, new)
    assert edits == [
        {"section": "FINDINGS", "find": "A 9 mm left adrenal nodule measures -5 HU.",
         "replace": "A 9 mm left adrenal nodule measures -5 HU, in keeping with a lipid-rich adenoma."},
        {"section": "IMPRESSION", "find": "Perforated acute appendicitis.",
         "replace": "Perforated acute appendicitis without a drainable collection."}]
    assert all(CUR.count(e["find"]) == 1 for e in edits)


def test_diff_edits_inserts_after_the_previous_sentence_and_deletes():
    new = CUR.replace("No hydronephrosis.\n", "No hydronephrosis. No follow-up is needed for the adrenal nodule.\n") \
             .replace(" Urgent surgical referral recommended.", "")
    edits = ce.diff_edits(CUR, new)
    assert {"section": "FINDINGS", "find": "No hydronephrosis.",
            "replace": "No hydronephrosis. No follow-up is needed for the adrenal nodule."} in edits
    assert {"section": "IMPRESSION", "find": "Urgent surgical referral recommended.", "replace": ""} in edits


def test_diff_edits_gives_nothing_for_an_identical_or_restructured_report():
    assert ce.diff_edits(CUR, CUR) == []
    assert ce.diff_edits(CUR, "") == []
    restructured = "\n".join(f"Line {i} entirely new." for i in range(30))
    assert ce.diff_edits(CUR, restructured) == []          # beyond MAX_DIFF_EDITS: a restructure, not surgery


def test_diff_edits_ignore_whitespace_only_changes():
    assert ce.diff_edits(CUR, CUR.replace("11 mm.", "11  mm.").replace("\n\n", "\n")) == []


def test_edits_for_reply_prefers_the_models_edits_then_the_rewrite():
    mine = [{"section": "FINDINGS", "find": "No hydronephrosis.", "replace": "No hydronephrosis or hydroureter."}]
    new = CUR.replace("No hydronephrosis.", "No hydronephrosis or hydroureter.")
    assert ce.edits_for_reply(mine, CUR, new) == mine
    assert ce.edits_for_reply([], CUR, new) == mine
    assert ce.edits_for_reply([], CUR, None) == []


def test_reply_text_never_promises_edits_that_are_not_there():
    ok = [{"verified": True}]
    assert ce.reply_text(ce.PROPOSAL_REPLY, ok) == ce.PROPOSAL_REPLY
    assert ce.reply_text(ce.PROPOSAL_REPLY, []) == ce.NO_EDIT_REPLY
    assert ce.reply_text(ce.PROPOSAL_REPLY, [{"verified": False}]) == ce.NO_EDIT_REPLY
    assert ce.reply_text("Here is my answer.", []) == "Here is my answer."


# ── a tool call with no prose still reads as a discussion (live 29de06f3) ─────────────────────────────────────────

def test_a_new_line_the_find_does_not_have_becomes_a_space():
    # live: the model appended an impression line with "\n" and the structure guard refused it
    e = ce.parse_edits_json('[{"section": "IMPRESSION", "find": "Urgent surgical referral recommended.", '
                            '"replace": "Urgent surgical referral recommended.\\nIncidental adrenal adenoma."}]')
    assert e[0]["replace"] == "Urgent surgical referral recommended. Incidental adrenal adenoma."


def test_reply_from_actions_lists_the_suggestions_with_their_reasons():
    acts = [{"title": "Comment on the adrenal nodule", "details": "Lipid-rich adenoma at -5 HU; no follow-up."},
            {"title": "Specify no drainable collection", "details": "The key surgical decision point."}]
    ok = ce.reply_from_actions(acts, [{"verified": True}])
    assert ok.startswith("Here's what I'd suggest:")
    assert "1. **Comment on the adrenal nodule**: Lipid-rich adenoma at -5 HU; no follow-up." in ok
    assert ok.endswith(ce.APPLY_BELOW)
    none = ce.reply_from_actions(acts, [{"verified": False}])
    assert "2. **Specify no drainable collection**" in none and none.endswith(ce.CANNOT_PLACE)
    assert ce.reply_from_actions([], []) == ""
