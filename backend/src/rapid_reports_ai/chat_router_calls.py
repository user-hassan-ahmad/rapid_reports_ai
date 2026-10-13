"""The chat-edit router's targeted calls (spec Flow 2): one lightweight Qwen call per tagged kind. Each reads the
whole instruction, is told to handle only its own kind and ignore the rest, sees only its part of the template
(chat_router_views), and answers with structured changes (chat_router_changes.OUTPUTS); style answers with edited
prose blocks. One retry on gpt-oss (another provider) if the call fails. Prompts are case-agnostic."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from pydantic import BaseModel
from pydantic_ai import PromptedOutput

from . import chat_router_changes as CH

logger = logging.getLogger(__name__)

CALL_TIMEOUT_S = 15.0
FALLBACK_TIMEOUT_S = 20.0
SETTINGS = {"temperature": 0, "max_tokens": 2500, "reasoning_effort": "low"}
STYLE_SETTINGS = {"temperature": 0, "max_tokens": 6000, "reasoning_effort": "low"}

COMMON = (
    "You change one part of a radiology report template by returning structured changes. The radiologist never "
    "sees the template; code applies your changes and writes the reply.\n"
    "Read the whole INSTRUCTION. Handle only SCOPE. Ignore every other part of the INSTRUCTION: other editors "
    "handle it. If nothing in the INSTRUCTION is about SCOPE, return no changes.\n"
    "Use only the names shown under CURRENT, copied exactly. Copy new wording exactly as the INSTRUCTION gives it. "
    "If the INSTRUCTION does not give the exact wording, write the wording you think is meant and set sure to false. "
    "Set sure to false whenever you are not certain what is meant.\n"
    "If the INSTRUCTION is about SCOPE but you cannot tell what to change, return no changes and put one short "
    'question for the radiologist in "question", in plain report language.\n\n')

_KIND = {
    "value": (
        "which values (measured quantities) every report must state",
        'Each change names a value and sets "to": "every" (every report must state it; it is flagged when missing), '
        '"relevant" (stated only when relevant, never flagged) or "not_needed" (no longer required). A value not '
        'listed under CURRENT may be added only with "every" or "relevant", using the name the INSTRUCTION gives.'),
    "concept": (
        "how the study-level statements listed under CURRENT are worded, or whether they are stated",
        'Each change names one statement by its key (the word before the brackets under CURRENT) and sets any of: '
        '"state" ("used"; "dictated": use whichever wording is dictated; "not_used": not stated), "default" (the '
        'usual sentence, printed unless the dictation says otherwise; it may reuse a sentence listed under '
        'CURRENT), "when_met" (the sentence printed when the dictation states the other state; it may hold {study} '
        'and {date} for values the dictation gives) and "condition" (that other state, one of the states listed '
        'for the statement; the default belongs to the remaining, usual state). Leave a field null to keep it as it '
        'is. If a statement has two states and you cannot tell which is usual, leave "condition" null.'),
    "fixed": (
        "the sentences printed in every report",
        '"to": "always" (printed in every report), "dictated" (printed only when the dictation says it), "remove" '
        '(no longer printed), "reword" ("line" is the current sentence, "text" the new wording) or "add" ("text" is '
        'the new sentence, "paragraph" the paragraph it goes in, from CURRENT). "line" is copied exactly from '
        'CURRENT.'),
    "normal": (
        "how a normal finding is worded for a part of the report, or whether it is stated",
        'Each change names the "paragraph", and either the "structure" of a normal line or the current text of a '
        'negative line ("negative"), copied exactly from CURRENT. "to": "reword" (with the new "text"), "removed" '
        '(no longer stated) or "add" (a new normal line for a structure, or, with "negative" set, a new negative '
        'sentence; "text" is the sentence).'),
    "layout": (
        "the sections and paragraphs of the report: adding, removing, renaming or reordering them",
        '"op" is one of rename_paragraph, move_paragraph, remove_paragraph, add_paragraph, rename_section, '
        'move_section, remove_section, add_section. "target" names the existing paragraph or section as shown '
        'under CURRENT. "name" is the new name (rename_paragraph, add_paragraph), the new printed heading '
        '(rename_section) or the new section\'s printed heading (add_section). "before" or "after" names the '
        'paragraph or section it goes next to. add_paragraph: "section" it belongs to and "covers", the structures '
        'it reports. add_section: "role" (one of findings, impression, history, technique, comparison, other), and '
        '"covers" when its role is findings.'),
}

STYLE = (
    "You edit the prose guidance of a radiology report template: how reports are written (voice, tone, length, "
    "phrasing). The radiologist never sees the template.\n"
    "Read the whole INSTRUCTION. Handle only style, tone, length or phrasing. Ignore every other part of the "
    "INSTRUCTION: other editors handle which values reports state, study-level statements, sentences printed in "
    "every report, normal findings, and sections and paragraphs.\n"
    "You get the template's prose BLOCKS under CURRENT, each with an id. Change only what the INSTRUCTION asks for: "
    "never delete or reword a line it is not about. Return only the blocks you change, each with its id, its "
    'complete new text and a "claim": one short specific sentence that names the block (its heading as shown '
    'under CURRENT) and what changed in it, for example "In <heading>: sentences are shorter." A claim that names '
    'no block, such as "the wording is changed", is not applied. Never add a line that tells reports to always state '
    "something. Never write a line that starts with an upper-case keyword.\n"
    '"summary": one sentence, in plain report language, saying what future reports will do differently (for '
    'example: "The impression will be shorter."). If nothing in the INSTRUCTION is about style, return no blocks. '
    'If it is about style but unclear, return no blocks and put one short question in "question".')

SYSTEM = {k: COMMON.replace("SCOPE", scope) + detail for k, (scope, detail) in _KIND.items()}
SYSTEM["style"] = STYLE


def user_prompt(instruction: str, view: str, context: str = "", rejection: Optional[dict] = None) -> str:
    s = f"INSTRUCTION:\n{(instruction or '').strip()}\n\nCURRENT:\n{(view or '').strip()}"
    if (context or "").strip():
        s += f"\n\nYOUR PREVIOUS REPLY (context only):\n{context.strip()}"
    if rejection:
        s += ("\n\nTHE RADIOLOGIST REJECTED THE LAST CHANGE.\n"
              f'They had asked: "{(rejection.get("original_instruction") or "").strip()}"\n'
              f'The change made was: "{(rejection.get("rejected_claim") or "").strip()}"\n'
              "Treat the INSTRUCTION as their clarification of that request.")
    return s


async def call_kind(kind: str, instruction: str, view: str, context: str = "",
                    rejection: Optional[dict] = None) -> BaseModel:
    """The kind's structured output (CH.OUTPUTS[kind]); raises when both models fail."""
    from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model
    out_type = CH.OUTPUTS[kind]
    settings = STYLE_SETTINGS if kind == "style" else SETTINGS
    prompt = user_prompt(instruction, view, context, rejection)

    async def call(model: str, timeout: float, output_type=out_type) -> BaseModel:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=model, output_type=output_type, system_prompt=SYSTEM[kind], user_prompt=prompt, api_key="",
            model_settings=dict(settings)), timeout)
        return r.output

    try:
        return await call(MODEL_CONFIG["SKILL_SHEET_REFINER"], CALL_TIMEOUT_S)
    except Exception as e:
        logger.warning("[chat-router.%s] %s: %s; fallback %s", kind, type(e).__name__, str(e)[:200],
                       MODEL_CONFIG["STACK_REVIEW_FALLBACK"])
        # gpt-oss gets prompted output (the JSON in its text), as the Rules step's decision-run fallback does
        # (3da534e7): with tool output it called a tool named "json" until its retries ran out. Qwen keeps tools.
        return await call(MODEL_CONFIG["STACK_REVIEW_FALLBACK"], FALLBACK_TIMEOUT_S, PromptedOutput(out_type))
