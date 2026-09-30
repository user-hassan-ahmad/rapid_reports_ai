"""The generation contract the Review rail reads, whichever pathway produced the report
(spec 2026-09-30-template-pipeline-mirror-design §4)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class GenerationArtifacts(BaseModel):
    report: str
    dictated_findings: str
    sections: List[str]                 # ordered output headings
    options: List[dict]                 # {id, kind, section, sentence, reason, source, finding?}
    brief: Optional[dict] = None        # {"decisions": {...}} — routing rows
    quality_check: Optional[dict] = None

    @classmethod
    def from_candidate(cls, record: dict, dictated_findings: str) -> "GenerationArtifacts":
        sections = list(record.get("sections") or [])
        brief = record.get("brief")
        return cls(report=record.get("content", ""), dictated_findings=dictated_findings, sections=sections,
                   options=[o for o in record.get("options") or [] if o.get("section") in sections],
                   brief={"decisions": brief.get("decisions")} if brief else None,
                   quality_check=record.get("quality_check"))
