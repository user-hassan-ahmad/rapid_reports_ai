"""Review engine item contract (spec §5.1, §6.1, §10.1) and the merge step (spec §7)."""
from __future__ import annotations

import hashlib
import re
import uuid
from typing import Dict, Iterable, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from ..generation_artifacts import GenerationArtifacts

LaneName = Literal["coverage", "accuracy", "additions"]
ItemLane = Literal["coverage", "accuracy", "additions", "chat"]
Cls = Literal["action", "minor", "info", "suppress"]
Status = Literal["open", "pre_applied", "applied", "dismissed", "addressed", "stale"]


class Span(BaseModel):
    start: int
    end: int
    text: str
    text_hash: Optional[str] = None      # hash of the report the span was made on

    @model_validator(mode="after")
    def _check_bounds(self) -> "Span":
        if not 0 <= self.start <= self.end:
            raise ValueError(f"Span requires 0 <= start <= end, got {self.start}..{self.end}")
        return self


class Edit(BaseModel):
    mode: Literal["replace", "insert", "upgrade", "remove"]
    find: Optional[str] = None           # verbatim, occurs once (replace / upgrade / remove)
    replace: Optional[str] = None
    after: Optional[str] = None          # insert: verbatim anchor sentence; None = append to the end of `section`
    section: Optional[str] = None


class ReviewInput(BaseModel):
    report_id: str
    pathway: Literal["quick", "templated"]
    artifacts: GenerationArtifacts       # report, dictated_findings, sections, options, brief, quality_check
    clinical_history: str = ""
    scan_type: str = ""
    study_title: Optional[str] = None    # bounds laterality
    synthesis: Optional[dict] = None     # {"guidelines": [S4 cards]} when stored
    pre_edit_report: Optional[str] = None  # the report before today's automatic edits (Gate D shadow log)


class Candidate(BaseModel):
    lane: LaneName
    kind: str
    section: Optional[str] = None
    anchor: Optional[Span] = None
    line_id: Optional[str] = None        # dictated line id ("d3"), for coverage items
    line_text: Optional[str] = None
    evidence: dict = Field(default_factory=dict)
    proposed: Optional[Edit] = None      # only producers that already write (brief options, code removal)
    preclassed: Optional[Literal["minor"]] = None
    code_fix: bool = False               # the proposed edit is code's (a contradicted negative): Qwen never rewrites it
    probe: Optional[str] = None          # producers that know their probe (brief options: "already in report")
    citation: Optional[dict] = None
    # The engine applies this edit before render (spec §9: auto-insert of verified absent findings, auto-remove
    # of contradicted generated negatives). The item builder maps it to status="pre_applied" (a later task).
    pre_apply: bool = False
    detector: str                        # e.g. "jev.classify_first", "code.numbers"


class ReviewItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    key: str
    report_id: str
    run_id: str
    lane: ItemLane
    detectors: List[str] = Field(default_factory=list)
    kind: str
    cls: Cls
    section: Optional[str] = None
    anchor: Optional[Span] = None
    label: str = ""
    reason: str = ""
    edit: Optional[Edit] = None
    verified: Optional[dict] = None
    evidence: Optional[dict] = None      # lane evidence, e.g. {"check_reason": "uncertain"|"conflict"|"number", "pointer": "..."}
    probe: Optional[str] = None
    citation: Optional[dict] = None
    source_line: Optional[str] = None
    status: Status = "open"
    history: List[dict] = Field(default_factory=list)
    engine_version: str = ""


def text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def _norm(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def item_key(lane: str, kind: str, text: Optional[str]) -> str:
    """Stable across runs: the same lane, kind and anchor (or dictated line) text give the same key.

    Callers must pass the candidate's ORIGINAL kind (not a model-refined kind) so keys stay stable across runs."""
    return hashlib.sha1(f"{lane}|{kind}|{_norm(text)}".encode()).hexdigest()[:16]


def _overlap(a: Optional[Span], b: Optional[Span]) -> bool:
    if a is None or b is None:
        return False
    if a.start == a.end or b.start == b.end:   # zero-length: within or at the boundary of the other counts
        return a.start <= b.end and b.start <= a.end
    return a.start < b.end and b.start < a.end


def merge(cands: List[Candidate], links: Iterable[Tuple[int, int]] = ()) -> List[List[Candidate]]:
    """Group candidates whose anchors overlap or that share a dictated line (transitively), plus the given index
    `links` (one claim in FINDINGS and IMPRESSION). Groups keep first-seen order, and members keep input order."""
    parent = list(range(len(cands)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = root(i), root(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            a, b = cands[i], cands[j]
            if _overlap(a.anchor, b.anchor) or (a.line_id and a.line_id == b.line_id):
                union(i, j)
    for i, j in links:
        union(i, j)
    groups: Dict[int, List[Candidate]] = {}
    for i, c in enumerate(cands):
        groups.setdefault(root(i), []).append(c)
    return list(groups.values())


def report_body(inp: "ReviewInput") -> str:
    """The final report without the user signature appended after it (`report_review.report_body`; the persisted
    `artifacts.signature`, else the older-report fallback). A prefix of the report: positions are unchanged, so
    every clause splitter reads this and anchors stay on the full report."""
    from ..report_review import report_body as _body      # lazy: report_review is a heavy import
    return _body(inp.artifacts.report or "", inp.artifacts.signature)
