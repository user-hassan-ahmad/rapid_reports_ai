# backend/src/rapid_reports_ai/scripts/review_labs/clinical_pass.py
"""The one clinical pass (spec §6.4): characterisation, safety, urgency, plus the Gate B1 arm-2 inconsistencies."""
from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Tuple

from pydantic import BaseModel, field_validator

from rapid_reports_ai.scripts.jev_tool_lab import calls

from .common import decode_json_list

PROMPTS = Path(__file__).parent / "prompts"
CLINICAL_PROMPT_VERSION = "clinical_pass_v1_1"   # v1 stays loadable by name for comparison


def prompt(version: str = CLINICAL_PROMPT_VERSION) -> str:
    return (PROMPTS / f"{version}.txt").read_text().strip()


PROMPT = prompt()


class ClinicalPass(BaseModel):
    characterise: List[str] = []
    safety: List[str] = []
    inconsistencies: List[str] = []
    unsupported: List[str] = []
    urgency: Literal["routine", "soon", "urgent", "critical"]
    urgency_reason: str = ""

    @field_validator("characterise", "safety", "inconsistencies", "unsupported", mode="before")
    @classmethod
    def _decode(cls, v):
        return [str(x) for x in decode_json_list(v)]


def split_item(s: str) -> Tuple[str, str]:
    if "::" not in s:
        return "", s.strip()
    a, b = s.split("::", 1)
    return a.strip().strip('"'), b.strip()


def user_message(case: dict) -> str:
    return (f"STUDY TITLE: {case.get('scan', '')}\n\nCLINICAL HISTORY:\n{case.get('history') or '(none)'}"
            f"\n\nDICTATION:\n{case.get('dictation', '')}\n\nREPORT:\n{case.get('report', '')}")


async def run(case: dict, qwen_fn=calls.qwen, version: str = CLINICAL_PROMPT_VERSION):
    try:
        out, usage = await qwen_fn(ClinicalPass, prompt(version), user_message(case), True)
        return out, usage.model_dump(), None
    except Exception as e:   # noqa: BLE001
        return None, {}, f"{type(e).__name__}: {str(e)[:300]}"
