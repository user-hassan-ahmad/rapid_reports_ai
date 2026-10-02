# backend/src/rapid_reports_ai/scripts/jev_tool_lab/prompts.py
"""What Qwen is told in each arm (spec §2.3, §3). Examples are structural, never clinical (case-agnostic rule)."""
from __future__ import annotations

from .scenarios import JUDGEMENT_S1

ROLE = "You are a consultant radiologist checking a report draft against the radiologist's dictation."

CATALOGUE = """QUESTION TYPES. These are the only questions you may ask. Give each an id: q1, q2, ...
T1 STATED: is a quoted piece of text stated in a source text? Slots: source (dictation | report | history), item (an exact quote copied from the case).
T2 TOPIC COVERED: does the source say anything at all about a topic? Slots: source (dictation | report), section (report only: its heading), topic (1-6 plain words, general terms, no negation, no numbers).
T3 CONTRADICTED: does the dictation contradict a report clause? Slots: clause (an exact quote from the report).
T4 WHICH ONE: which of 2-5 clearly different descriptions fits a quoted text, judged from the source? Slots: source, item (an exact quote), options (2-5 short descriptions, clearly different, none the negation of another). A "can't tell" option is added for you.
T5 PROPERTY: does the quoted text itself report an abnormality or a limitation? Slots: source, item (an exact quote), property ("abnormal").
T6 SAME THING: do two quoted texts describe the same structure or finding? Slots: source, a, b (exact quotes).

RULES FOR QUESTIONS
- Ask only about what a text STATES. Never ask what imaging would show, what is expected or likely, or what a grade, system or guideline requires: you know that, so work it out yourself, then ask only whether each input is stated.
- Copy quotes exactly from the case. Never paraphrase inside a quote.
- One judgement per question. Never join two with "or" or "and also".
- For coverage, ask about the topic in general terms (for example "property P of finding X"), never about a claim or its polarity (not "no P").
- A topic must not contain negation words (no, not, without, absent, negative, normal, unremarkable, nil, none, non) or digits.
- Never ask about numbers, sizes, dates or counts.
- Ask the fewest questions that settle the judgement, at most 8.

STRUCTURAL EXAMPLE (not a clinical one): to decide whether finding X can be classified, where the system needs inputs P, Q and R for X, ask three T2 questions on the dictation, one per input, each topic naming that input of X in general terms.

THE RULE
Declare, before seeing any answer, how the answers decide the judgement. all_of is a list of conditions {q, want, label}. want is "yes" or "no" for T1, T2, T3, T5 and T6, or an option key ("o1", "o2", ...) for T4. label names what the condition checks in a few words; it becomes the missing-input text. The judgement holds only if every condition holds."""

FREE = """Write your own questions for a fast classifier (Jev) that reads the dictation and answers each question. Give each an id: q1, q2, ... Each question has: type ("noul" for a yes/no statement, answered with a probability that it is true; "choice" for picking one option), instructions (the question or statement), and criteria (for a choice: option key -> description; for a noul: optional "true" and "false" descriptions). Ask the fewest questions that settle the judgement, at most 8.

THE RULE
Declare, before seeing any answer, how the answers decide the judgement. all_of is a list of conditions {q, want, label}. want is "yes" or "no" for a noul, or an option key for a choice. label names what the condition checks in a few words; it becomes the missing-input text. The judgement holds only if every condition holds."""


def baseline_system() -> str:
    return f"{ROLE}\n\n{JUDGEMENT_S1}\n\nReturn gradable, missing and a one-sentence reason."


def author_system() -> str:
    return f"{ROLE}\n\n{JUDGEMENT_S1}\n\nDo not decide yet. Plan questions for a fast classifier and declare the rule.\n\n{CATALOGUE}"


def free_author_system() -> str:
    return f"{ROLE}\n\n{JUDGEMENT_S1}\n\nDo not decide yet. Plan questions for a fast classifier and declare the rule.\n\n{FREE}"


def decide_system() -> str:
    return (f"{ROLE}\n\n{JUDGEMENT_S1}\n\nYou asked a fast classifier some questions about the case text. Its answers "
            "are listed below the case as yes / no / unsure (or \"not asked\"), or the chosen option, with the raw probability. Treat them "
            "as evidence about what the text states, not as verdicts: check each against the case yourself, and "
            "overrule an answer you can see is wrong. Return gradable, missing and a one-sentence reason.")
