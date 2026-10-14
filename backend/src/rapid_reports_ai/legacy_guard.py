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


_STACK_FIELDS = ("stack_removed", "stack_declined", "stack_conclusion", "stack_sheet_id", "stack_values_na",
                 "stack_values_filled")


def is_stale_stack_request(req) -> bool:
    """A tab from before the switch to /api/canvas/stack/generate (spec §5 Old endpoints): refuse it rather than
    write a report that ignores removed sentences. Empty fields are not a stack request."""
    return bool(getattr(req, "stack", False)) or any(getattr(req, f, None) for f in _STACK_FIELDS)
