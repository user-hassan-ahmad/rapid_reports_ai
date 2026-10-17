"""The confirmed gate as the server reads it, and the findings hash the browser records at Confirm (integration
spec §5 Trust). Mirrors frontend/src/lib/hybrid-stack/types.ts GateRecord and regionState.findingsHash."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .schemas import CONCLUSION
from .units import StackUnit


class GateItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = ""
    kind: str = "finding"
    region: str = ""
    question: str = ""
    sentences: list[str] = Field(default_factory=list)
    answered_by: Literal["dictation", "tap", "skip", "not_assessed"] = "dictation"


class ValueChip(BaseModel):
    model_config = ConfigDict(extra="allow")
    item: str
    state: str
    value: Optional[str] = None
    quote: Optional[str] = None   # the dictated sentence a filled value was read from


class AppliedValue(BaseModel):
    model_config = ConfigDict(extra="allow")
    input: str = ""
    value: str = ""
    state: str = ""
    quote: str = ""


class AppliedRec(BaseModel):
    """A recommendation applied from a guideline card (spec 2026-10-14 §7.2); `text` is what reaches the report."""
    model_config = ConfigDict(extra="allow")
    key: str = ""
    finding_id: str = ""
    pack: str = ""
    version: str = ""
    bundle: str = ""
    source: str = ""
    outcome: str = ""
    verdict: str = ""
    chosen_from: Optional[int] = None
    sentence: str = ""
    text: str = ""
    values: list[AppliedValue] = Field(default_factory=list)
    stale: Optional[Literal["values", "finding"]] = None


class GateRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    confirmed_at: str = ""
    conclusion_text: str = ""
    conclusion_source: str = "dictated"
    assumed_normal: list[str] = Field(default_factory=list)
    remainder_normal: list[str] = Field(default_factory=list)
    items: list[GateItem] = Field(default_factory=list)
    assumed: dict[str, list[str]] = Field(default_factory=dict)
    removed: list[str] = Field(default_factory=list)
    recommendations: list[AppliedRec] = Field(default_factory=list)   # no cap: a 422 would block Generate (D24)
    values: Optional[list[ValueChip]] = None
    units_hash: str = ""
    findings_hash: Optional[str] = None   # recorded by the browser at Confirm (P2c); verified when present


def findings_hash(units: list[StackUnit]) -> str:
    """TS findingsHash: a 31-multiplier hash over UTF-16 code units, unsigned 32-bit, '<length>:<hex>'."""
    s = "\u0002".join(
        f"{u.text}\u0001{u.group or ''}\u0001{1 if u.abnormal else 0}\u0001"
        + ",".join(f"{p.group}:{1 if p.abnormal else 0}" for p in (u.parts or []))
        for u in units if u.group != CONCLUSION and not u.heading)
    data = s.encode("utf-16-le")
    h = 0
    for i in range(0, len(data), 2):
        h = (31 * h + (data[i] | data[i + 1] << 8)) & 0xFFFFFFFF
    return f"{len(data) // 2}:{h:x}"
