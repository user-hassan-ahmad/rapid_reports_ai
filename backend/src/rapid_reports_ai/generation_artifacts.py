"""The generation contract the Review rail reads, whichever pathway produced the report
(spec 2026-09-30-template-pipeline-mirror-design §4)."""
from __future__ import annotations

import logging
from typing import List, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class GenerationArtifacts(BaseModel):
    report: str
    dictated_findings: str
    sections: List[str]                 # ordered output headings
    options: List[dict]                 # {id, kind, section, sentence, reason, source, finding?}
    brief: Optional[dict] = None        # {"decisions": {...}} — routing rows
    quality_check: Optional[dict] = None

    @classmethod
    def from_candidate(cls, record: dict, dictated_findings: str) -> "GenerationArtifacts":
        """Fails open: every option is kept. One whose section is not a listed heading is marked
        section_known=False (the rail shows it unanchored) rather than dropped."""
        sections = list(record.get("sections") or [])
        options = [{**o, "section_known": o.get("section") in sections} for o in record.get("options") or []]
        unmatched = [o.get("section") for o in options if not o["section_known"]]
        if unmatched:
            logger.warning("generation artifacts: %d option(s) with unlisted section %s (sections=%s)",
                           len(unmatched), sorted({str(u) for u in unmatched}), sections)
        brief = record.get("brief")
        decisions = brief.get("decisions") if brief else None
        return cls(report=record.get("content", ""), dictated_findings=dictated_findings, sections=sections,
                   options=options, brief={"decisions": decisions} if decisions is not None else None,
                   quality_check=record.get("quality_check"))
