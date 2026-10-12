"""Types shared by the Copilot's modules and routes (spec §5). The registry caches a guideline; nothing here holds
how it applied to a case except Preview, which is never stored."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

BranchState = Literal["checked", "not_available", "pending"]
CardState = Literal["applies", "check_first", "does_not_apply"]


class Input(BaseModel):
    id: str
    question: str
    options: list[str] = Field(default_factory=list)
    settled_by: str = ""


class Output(BaseModel):
    when: str = ""
    classification: str = ""
    recommendation: str = ""
    quote: str = ""               # verbatim evidence from the fetched chunks


class Branch(BaseModel):
    name: str
    state: BranchState = "pending"
    inputs: list[Input] = Field(default_factory=list)
    rule: str = ""
    outputs: list[Output] = Field(default_factory=list)
    fetched_at: str = ""          # UTC ISO, set on save: a stale not_available is fetched again


class Supplement(BaseModel):
    """An ask-time find kept with its source page: case-free (question is the vocabulary-filtered search phrase,
    answer empty; spec §2.15). A draft (never material for a later answer) until verified; reviewers only."""
    question: str
    answer: str = ""
    quote: str = ""
    url: str = ""
    verified: bool = False


class GuidelineContent(BaseModel):
    applies_to: str = ""
    summary: str = ""
    branches: list[Branch] = Field(default_factory=list)
    supplements: list[Supplement] = Field(default_factory=list)

    def branch(self, name: str) -> Branch | None:
        return next((b for b in self.branches if b.name == name), None)

    def checked(self) -> list[Branch]:
        return [b for b in self.branches if b.state == "checked"]


class Publication(BaseModel):
    title: str = ""
    body: str = ""
    year: str = ""


class Source(BaseModel):
    url: str
    title: str = ""
    tier: int = 3
    fetched_at: str = ""


class Chunk(BaseModel):
    url: str
    text: str
    branch: str = ""              # the branch whose query found it ("" for the publication query)


class Entry(BaseModel):
    """The API view of one registry row."""
    key: str
    name: str
    version: str = ""
    locale: str = "uk"
    publication: Publication = Field(default_factory=Publication)
    status: Literal["draft", "verified"] = "draft"
    content: GuidelineContent = Field(default_factory=GuidelineContent)
    sources: list[Source] = Field(default_factory=list)


class Card(BaseModel):
    key: str
    name: str
    version: str = ""
    finding_id: str               # the abnormal item it applies to (frontend id: "u<unit>" or "u<unit>.<part>")
    why: str = ""
    branch: str = ""              # the skeleton branch this finding falls into
    skeleton: list[str] = Field(default_factory=list)
    publication: Publication = Field(default_factory=Publication)
    known: bool = False           # already in the registry
    status: Literal["draft", "verified", "new"] = "new"
    siblings: list[str] = Field(default_factory=list)   # library packs: other bodies' packs on the same topic

    @property
    def id(self) -> str:
        return f"{self.key}|{self.finding_id}"


class Settled(BaseModel):
    input: str
    value: str
    quote: str = ""
    fact: str = ""                # library packs: the shared patient fact this input carries ("" for none)


class Proposal(BaseModel):
    classification: str
    line: str
    recommendation: str = ""
    caveats: list[str] = Field(default_factory=list)       # library packs: the outcome's caveats, rendered
    citations: list[dict[str, Any]] = Field(default_factory=list)   # library packs: where the fired steps come from


class Preview(BaseModel):
    settled: list[Settled] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    proposal: Proposal | None = None
    state: CardState = "applies"  # library packs (spec §7.4): does_not_apply (an eligibility input excludes), check_first
                                  # (an unknown eligibility input could change the outcome), else applies
    exclusion: Proposal | None = None   # does_not_apply: the reason and the scope clause's citations; never Applied
    possible: list[str] = Field(default_factory=list)   # library packs: outcomes still possible, rendered
    bounded: bool = True          # library packs: False when `possible` may be incomplete (an unknown number feeds a
                                  # formula); `missing` then lists every unknown input that reaches the result
    asks: list[dict[str, Any]] = Field(default_factory=list)   # library packs: one per missing input (label,
    # definition, options, the outcomes it decides between with their citations, and the citations of its steps)
    trace: dict[str, Any] | None = None                 # library packs: the engine trace behind the proposal
    degraded: bool = False        # library packs: the settle model or a Jev check failed, so inputs it could have
                                  # settled are asked; never served from the preview cache again
