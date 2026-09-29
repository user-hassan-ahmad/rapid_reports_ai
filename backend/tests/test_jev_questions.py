"""The question registry is a move, not a rewording: this digest was computed from the
wording as it stood before the move (2026-09-26) and must not change unless the wording
is changed on purpose, in which case QSET_VERSION changes with it."""
from __future__ import annotations

import hashlib
import json

from rapid_reports_ai import dictation_triage, section_coverage, utterance_bundle
from rapid_reports_ai.jev_questions import (
    ACTION_DESCRIPTIONS,
    ASR_RISK_THRESHOLD,
    BINARY_THRESHOLD,
    BOUNDARY_QUESTIONS,
    COMMAND_THRESHOLD,
    COMPLETE_THRESHOLD,
    COVERAGE_CRITERIA,
    JEV_MODEL,
    PLACEMENT_THRESHOLD,
    QSET_VERSION,
    ROUTE_THRESHOLD_DEFAULT,
    STANDALONE_QUESTION,
    TRIAGE_QUESTIONS,
    bundle_questions,
    coverage_questions,
)

# 2026-09-29: the retired Qwen triage prompt left the payload; no Jev wording changed, so
# QSET_VERSION stands (it is logged with every live decision).
QSET_DIGEST_2026_09_29 = "dd4ce5b20dfd000ced0c5c0e8c230f21dc64a2cb3d08ef76b8fbe8bc853ddfa1"


def qset_digest() -> str:
    payload = {
        "model": JEV_MODEL,
        "action_descriptions": ACTION_DESCRIPTIONS,
        "triage": TRIAGE_QUESTIONS,
        "boundary": BOUNDARY_QUESTIONS,
        "standalone_bundle": STANDALONE_QUESTION,
        "coverage_criteria": COVERAGE_CRITERIA,
        "coverage_questions": coverage_questions(["SECTION A", "SECTION B"]),
        "bundle_questions": bundle_questions(["SECTION A", "SECTION B"]),
        "thresholds": {
            "coverage_binary": BINARY_THRESHOLD,
            "boundary_complete": COMPLETE_THRESHOLD,
            "boundary_command": COMMAND_THRESHOLD,
            "asr_risk": ASR_RISK_THRESHOLD,
            "placement": PLACEMENT_THRESHOLD,
            "route_default": ROUTE_THRESHOLD_DEFAULT,  # read directly since the route config was retired
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def test_qset_digest_pins_wording():
    assert qset_digest() == QSET_DIGEST_2026_09_29


def test_old_modules_reexport_the_registry_objects():
    assert dictation_triage.TRIAGE_QUESTIONS is TRIAGE_QUESTIONS
    assert dictation_triage.ACTION_DESCRIPTIONS is ACTION_DESCRIPTIONS
    assert section_coverage.COVERAGE_CRITERIA is COVERAGE_CRITERIA
    assert section_coverage.coverage_questions is coverage_questions
    assert utterance_bundle.bundle_questions is bundle_questions


def test_qset_version_is_named():
    assert isinstance(QSET_VERSION, str) and QSET_VERSION


def test_fast_append_bands_are_pinned_to_the_qset_version():
    """Step 5 provisional bands. Changing any value means a new QSET_VERSION."""
    from rapid_reports_ai import jev_questions as jq

    assert jq.QSET_VERSION == "2026-09-27.5"
    assert jq.FAST_APPEND_BANDS == {
        "append_act": 0.90,
        "append_max_is_correction": 0.50,
        "append_min_asr_conf": 0.80,
        "command_act": 0.80,
        "line_close_standalone": 0.50,
        "line_close_silence_s": 2.0,
        "line_close_hard_limit_s": 5.0,
    }


def test_word_sense_bands_and_wording_are_pinned():
    from rapid_reports_ai import jev_questions as jq

    assert jq.WORD_SENSE_BANDS == {"word_sense_flag": 0.6, "word_sense_underline": 0.35, "word_fix_accept": 0.65}
    assert jq.WORD_SENSE_MAX_WORDS == 12
    q = jq.word_sense_question("renal")
    assert q["type"] == "noul" and "'renal'" in q["instructions"] and "makes clinical sense as heard" in q["instructions"]
    c = jq.word_fix_question({"as_heard": "The renal glands are normal.", "candidate_1": "The adrenal glands are normal."})
    assert c["type"] == "choice" and c["criteria"]["as_heard"] == "The renal glands are normal."
