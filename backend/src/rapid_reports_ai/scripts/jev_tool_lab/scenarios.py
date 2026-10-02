# backend/src/rapid_reports_ai/scripts/jev_tool_lab/scenarios.py
"""Scenario S1, grade grounding (spec §4): is the finding gradable with the named system from what was dictated?"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel

from .catalogue import Case

JUDGEMENT_S1 = ("Decide whether the finding can be graded with the named classification system using only what the "
                "dictation states. It is gradable only if every input the system needs for this finding is described "
                "in the dictation; an input stated as absent or normal counts as described. Never assume an input "
                "that is not dictated. If it is not gradable, list each missing input in a few words.")


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
            f"FINDING: {item.finding}\nCLASSIFICATION SYSTEM: {item.system}")
