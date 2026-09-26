"""The question registry is a move, not a rewording: this digest was computed from the
wording as it stood before the move (2026-09-26) and must not change unless the wording
is changed on purpose, in which case QSET_VERSION changes with it."""
from __future__ import annotations

import hashlib
import json

from rapid_reports_ai.canvas_routes import TriageRouteConfig
from rapid_reports_ai.dictation_triage import ACTION_DESCRIPTIONS, JEV_MODEL, QWEN_SYSTEM_PROMPT, TRIAGE_QUESTIONS
from rapid_reports_ai.section_coverage import BINARY_THRESHOLD, COVERAGE_CRITERIA, coverage_questions
from rapid_reports_ai.utterance_boundary import (
    ASR_RISK_THRESHOLD,
    BOUNDARY_QUESTIONS,
    COMMAND_THRESHOLD,
    COMPLETE_THRESHOLD,
    PLACEMENT_THRESHOLD,
)
from rapid_reports_ai.utterance_bundle import STANDALONE_QUESTION, bundle_questions

QSET_DIGEST_2026_09_26_1 = "8ff8ce5b46562f0bfebde4fcd3da31843de7a7c3e25b9e7c9ae07d8d27e9fb1b"


def qset_digest() -> str:
    payload = {
        "model": JEV_MODEL,
        "action_descriptions": ACTION_DESCRIPTIONS,
        "triage": TRIAGE_QUESTIONS,
        "qwen_triage_prompt": QWEN_SYSTEM_PROMPT,
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
            "route_default": TriageRouteConfig(candidate="jev").threshold,
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def test_qset_digest_pins_wording():
    assert qset_digest() == QSET_DIGEST_2026_09_26_1
