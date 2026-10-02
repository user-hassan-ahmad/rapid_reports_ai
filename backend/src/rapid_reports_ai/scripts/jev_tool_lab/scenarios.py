# backend/src/rapid_reports_ai/scripts/jev_tool_lab/scenarios.py
"""Scenario S1, grade grounding (spec §4): is the finding gradable with the named system from what was dictated?"""
from __future__ import annotations

import json
from typing import Any, List, Literal

from pydantic import BaseModel, field_validator

from .catalogue import Case

JUDGEMENT_S1 = ("Decide whether the finding can be graded with the named classification system using only what the "
                "dictation states. It is gradable only if every input the system needs for this finding is described "
                "in the dictation; an input stated as absent or normal counts as described. Never assume an input "
                "that is not dictated. Grade means the system's core category: ignore optional modifiers and "
                "eligibility criteria unless they change that category. Read the dictation literally: an input "
                "counts only if it is stated, never inferred from radiological convention (for example, an "
                "unqualified nodule is not assumed solid). Read each descriptor by its standard meaning in the system's "
                "lexicon (a "
                "synonym or a relative description counts), and treat a criterion as described when the dictation covers "
                "the features radiologists ordinarily dictate to assess it; do not demand finer sub-features that are not "
                "normally dictated. If it is not gradable, list each missing input in a few "
                "words.")


class S1Item(BaseModel):
    id: str
    origin: Literal["synthetic", "production"]
    seed: str = ""            # production report id prefix the item was seeded from
    scan_type: str
    dictation: str
    finding: str              # verbatim from the dictation
    system: str               # e.g. "Bosniak 2019"
    gradable: bool            # the label
    missing: List[str] = []   # the label's missing inputs, for the hand read

    def case(self) -> Case:
        return Case(scan_type=self.scan_type, dictation=self.dictation)


class Decision(BaseModel):
    gradable: bool
    missing: List[str] = []
    reason: str = ""


def s1_user(item: S1Item) -> str:
    return (f"SCAN TYPE: {item.scan_type}\n\nDICTATED FINDINGS:\n{item.dictation}\n\n"
            f"FINDING (identifies which finding; its description may continue elsewhere in the dictation): "
            f"{item.finding}\nCLASSIFICATION SYSTEM: {item.system}\n"
            "AVAILABLE TEXTS: the dictation only (there is no report and no clinical history).")


def _loads_if_str(v: Any) -> Any:
    """Qwen sometimes JSON-encodes a nested list as a string inside a tool call (pilot, 2026-10-02)."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


class InputCheck(BaseModel):
    input: str
    stated: bool
    quote: str = ""          # the dictation's own words stating it; empty when not stated


class Checklist(BaseModel):
    """Arm E1's one-call output: the system's inputs checked one by one, then the verdict."""
    inputs: List[InputCheck]
    gradable: bool
    missing: List[str] = []
    reason: str = ""

    @field_validator("inputs", "missing", mode="before")
    @classmethod
    def _decode(cls, v: Any) -> Any:
        return _loads_if_str(v)
