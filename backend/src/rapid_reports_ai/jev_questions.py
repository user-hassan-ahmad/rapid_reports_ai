"""Every Jev question, criteria map and decision threshold, in one place (D-10).

QSET_VERSION names this exact wording. It is logged with every decision (shadow
included), so a week of data is attributable to one question set. Change any text or
threshold here and QSET_VERSION changes with it; tests/test_jev_questions.py pins the
wording by digest so an accidental edit fails loudly.

Moved verbatim on 2026-09-26 from dictation_triage, utterance_boundary,
section_coverage and utterance_bundle (they re-export these names), and the route
threshold default from canvas_routes.
"""
from __future__ import annotations

from typing import Any

from .jev_client import JEV_MODEL  # noqa: F401  (the wording is written for this model)

QSET_VERSION = "2026-09-26.1"

# --- triage (dictation_triage) ------------------------------------------------------

# One sentence per option. Both candidates receive exactly these words, so they
# answer the same question. Edit here, nowhere else.
ACTION_DESCRIPTIONS: dict[str, str] = {
    "append_new_finding": "The utterance states a new clinical observation or normality claim that is not yet in the scratchpad",
    "correct_previous_finding": "The utterance revises, replaces or retracts a value or descriptor of something already in the scratchpad",
    "restate_existing_finding": "The utterance repeats something already captured in the scratchpad, with no new information",
    "delete_previous_utterance": "The utterance asks to remove the immediately preceding statement, such as scratch that or delete that",
    "formatting_command": "The utterance is a formatting instruction such as new line, new paragraph or full stop",
    "ignore_noise": "The utterance is filler, hesitation or thinking aloud with no clinical content",
}

TRIAGE_QUESTIONS: dict[str, dict[str, Any]] = {
    "action": {
        "type": "choice",
        "instructions": "What should the dictation scratchpad system do with the latest utterance?",
        "criteria": ACTION_DESCRIPTIONS,
    },
    "is_correction": {
        "type": "noul",
        "instructions": "The latest utterance revises or corrects something said earlier.",
    },
    "needs_committed_edit": {
        "type": "noul",
        "instructions": "Applying the latest utterance requires changing text in the COMMITTED (frozen) section rather than the ACTIVE section.",
    },
}

# Default confidence floor for lab route mode (canvas_routes.TriageRouteConfig).
ROUTE_THRESHOLD_DEFAULT = 0.9

# --- boundary / front door (utterance_boundary) -------------------------------------

PLACEMENT_THRESHOLD = 0.5  # below this, the cheap error: a new line
# Bake-off run 1 (38 cases): the raw choice is right 0.868 of the time; every threshold
# above 0.4 only converted correct answers into stalls (the three wrong sends are the same
# three at any setting). Thresholds are therefore a floor against near-uniform
# distributions, not a precision lever. Waiting is bounded by the frontend backstop.
# Run 2 (mic): a 0.4 floor demoted three correct completes at 0.26-0.38 into 1.5 s waits.
# On a three-way choice confidence sits low whenever two options are plausible; the floor
# is a near-uniform guard only.
COMPLETE_THRESHOLD = 0.2
COMMAND_THRESHOLD = 0.2
# Not acted on yet. On the same run 0.7 separated the three true ASR cases from every
# clean one (baseline noul sits ~0.5–0.65 on clean text).
ASR_RISK_THRESHOLD = 0.7

BOUNDARY_QUESTIONS: dict[str, dict[str, Any]] = {
    "boundary": {
        "type": "choice",
        "instructions": (
            "Taking the buffered words and the chunk together as what the radiologist has said since the "
            "last statement was sent, which is true? silence_s is how many seconds of silence have followed "
            "the chunk so far (0 = the chunk has just arrived, no information). A long silence after words "
            "that could stand alone means the statement is complete; a short silence carries little weight."
        ),
        "criteria": {
            "complete": (
                "The buffered words plus the chunk form a finished clinical statement a radiologist would end "
                "here: a finding, a measurement, a normality claim, or a correction that is fully specified."
            ),
            "continues": (
                "The statement is still in progress: it ends on a preposition, article, conjunction, a verb "
                "without its object, an unfinished measurement, an unfinished correction such as 'actually' or "
                "'make that', or otherwise needs more words to be a claim."
            ),
            "command": (
                "The chunk is an instruction to the application or a dictation command rather than report "
                "content: scratch that, delete that, new paragraph, new line, full stop, generate report, "
                "switch mode, and similar."
            ),
        },
    },
    "placement": {
        "type": "choice",
        "instructions": (
            "If the buffered words plus the chunk are a finished statement, where does it belong in the "
            "scratchpad relative to the last line? The scratchpad captures dictation as it is spoken; it is "
            "not the report."
        ),
        "criteria": {
            "extend_previous_line": (
                "It adds to the same observation as the last line: a descriptor, a measurement, a qualifier, "
                "a consequence, or a clause such as 'with' or 'which' that continues that finding."
            ),
            "new_line": (
                "It is a separate finding or normality claim about the same region or system as the last line."
            ),
            "new_paragraph": (
                "It moves to a different anatomical region or system from the last line, or the last line is "
                "empty."
            ),
        },
    },
    "standalone": {
        "type": "noul",
        "instructions": (
            "Ignoring whether more words might follow, the buffered words plus the chunk can be read as a "
            "complete clinical statement as they stand: a finding, a measurement, a normality claim, or a "
            "fully specified correction."
        ),
    },
    "asr_risk": {
        "type": "noul",
        "instructions": (
            "The buffered words plus the chunk contain a likely speech-to-text error: a word that is "
            "phonetically close to a radiological term the scan type or the scratchpad makes expected, and "
            "that makes no clinical sense as heard."
        ),
    },
}

# --- section coverage (section_coverage) --------------------------------------------

BINARY_THRESHOLD = 0.5

COVERAGE_CRITERIA: dict[str, str] = {
    "true": (
        "The scratchpad contains a definitive clinical claim about {SECTION} or a standard radiological "
        "abbreviation of it: a finding, a measurement, a qualifier, or an explicit normality statement. "
        "The claim may be direct ({SECTION} is the grammatical subject, the location via a prepositional "
        "phrase, or an adjectival modifier of the subject) or collective (a definitive claim over a "
        "recognisable anatomical group that {SECTION} genuinely belongs to, such as normality or absence "
        "of pathology). A specific claim about {SECTION} counts even when a collective also exists."
    ),
    "false": (
        "There is no definitive claim about {SECTION}: only a bare mention with nothing asserted; a claim "
        "about an adjacent but distinct structure; a parent-structure claim that does not enumerate "
        "{SECTION} when the checklist lists it separately; an incidental co-mention inside a statement "
        "about another structure; a vague filler with no anatomical scope; or a collective whose group "
        "{SECTION} does not clearly belong to. When in doubt, this is the answer."
    ),
}


def coverage_questions(sections: list[str]) -> dict[str, dict[str, Any]]:
    """One noul per checklist section, keyed by the exact section string."""
    return {
        s: {
            "type": "noul",
            "instructions": f"The scratchpad meaningfully addresses the checklist section {s}.",
            "criteria": {
                "true": COVERAGE_CRITERIA["true"].replace("{SECTION}", s),
                "false": COVERAGE_CRITERIA["false"].replace("{SECTION}", s),
            },
        }
        for s in sections
    }

# --- one bundle per utterance (utterance_bundle) ------------------------------------

STANDALONE_QUESTION: dict[str, Any] = {
    **BOUNDARY_QUESTIONS["standalone"],
    "instructions": BOUNDARY_QUESTIONS["standalone"]["instructions"].replace(
        "the buffered words plus the chunk", "the open line plus the latest utterance"
    ),
}


def section_key(i: int) -> str:
    return f"section_{i}"


def bundle_questions(checklist: list[str]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {**TRIAGE_QUESTIONS, "standalone": STANDALONE_QUESTION}
    for i, (_, q) in enumerate(coverage_questions(checklist).items()):
        questions[section_key(i)] = {
            **q,
            "instructions": q["instructions"].replace("The scratchpad", "The scratchpad (COMMITTED plus ACTIVE)", 1),
        }
    return questions
