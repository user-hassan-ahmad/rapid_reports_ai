"""The tripwire (integration spec §9.5): every legacy entry point calls mark(name) in its route or scheduling
function (never at import: the Copilot imports legacy helpers). With the stack on, a call is logged at WARNING; P3
fails on any. With the stack off (the old flow) it is silent."""
from __future__ import annotations

import logging
from typing import Optional

from .stack_switch import stack_allowed

logger = logging.getLogger("rapid_reports_ai.legacy")

MARKS = (
    "quick.analyse", "quick.analyse.proto", "quick.generate", "canvas.sections", "canvas.sections_from_template",
    "canvas.process.structured", "canvas.review.coverage", "canvas.bundle.checklist", "template.prepare",
    "template.generate", "template.mirror", "template.structure_validation", "options.schedule",
    "prefetch.schedule", "report.validation_status", "report.enhance", "audit", "audit.phase2", "audit.criteria",
    "chat.tavily",
)


def mark(name: str, user_id: Optional[object] = None, route: Optional[str] = None) -> None:
    """Never raises into the caller: a tripwire must not break the legacy path it watches."""
    if stack_allowed():
        logger.warning("[legacy.call] %s user=%s route=%s", name, user_id or "-", route or "-")
