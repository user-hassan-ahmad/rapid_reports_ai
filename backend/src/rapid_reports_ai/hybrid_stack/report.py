"""The one stack Generate (integration spec §5, D27 P2a): verify, build the statements, write with today's quick or
template writer, guard removed sentences, save, schedule the review. Never falls back to the old flow."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy.orm import Session

from .. import template_sheet_structure as tss
from ..database.crud import create_report, get_template, increment_template_usage, is_retired_template
from ..quick_report_api import _slim_markdown
from ..quick_report_generator import generate_quick_report
from ..review_engine.engine import schedule_review
from ..template_lean import generate_template_report_lean
from ..template_number_check import undictated_numbers
from .findings import findings_block
from .gate_model import findings_hash
from .removed_guard import guard, reconcile
from .template import template_structure

logger = logging.getLogger(__name__)


class StackError(Exception):
    """A plain message for the radiologist; the request never falls back to the old flow."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run(req, user, db: Session) -> AsyncIterator[dict]:
    t0 = time.time()
    # 0 verify: ownership, a usable template, and a gate that still matches the units
    template = None
    if req.kind == "template":
        template = get_template(db, req.template_id or "", user_id=str(user.id))
        if template is None:
            raise StackError("Template not found.")
        if is_retired_template(template) or template_structure(template.template_config or {}) is None:
            raise StackError("This template can't be used with the scratchpad. Create a fresh one.")
    if req.gate.findings_hash is not None and req.gate.findings_hash != findings_hash(req.units):
        raise StackError("The scratchpad changed after Confirm. Confirm again.")
    # 1 statements, and removals the dictation has since stated (dictation wins)
    st = findings_block(req.units, req.groups, req.gate)
    plain = st.plain()
    removed, kept_by_dictation = await reconcile(list(req.gate.removed), plain)
    # 2–4 write: today's writers (slots, check, values backstop and template numbers run inside the template writer)
    if req.kind == "quick":
        out = await generate_quick_report(
            skill_sheet="", scan_type=req.scan_type, findings=st.block, clinical_history=req.history,
            user_signature=None, stack=True, declined=removed, conclusion=st.conclusion,
            stack_sheet=_slim_markdown(db, req.stack_sheet_id), check_findings=plain)
    else:
        cfg = template.template_config or {}
        stack = {"conclusion": st.conclusion, "declined": removed}
        if req.gate.values is not None:
            stack["values_na"] = [c.item for c in req.gate.values if c.state == "na"]
            stack["values_filled"] = [c.item for c in req.gate.values if c.state in ("filled", "picked")]
        out = await generate_template_report_lean(
            sheet=cfg.get("skill_sheet", ""), scan_type=req.scan_type, findings=st.block, history=req.history,
            case=None, signature=None, declined=removed, stack=stack, check_findings=plain)
    generated = out["report_content"]
    quality = dict(out.get("quality_check") or {"enabled": False})
    review = list(quality.get("review") or [])
    # 5 the removed guard (its own Jev call, whatever RR_QUALITY_CHECK says), quick numbers, recording
    report, removals, guard_items = await guard(generated, removed, plain)
    review += guard_items
    if req.kind == "quick":
        review += undictated_numbers(report, [*st.all_texts(), req.history, st.conclusion], "")
    if removals:
        quality.setdefault("pre_edit_report", generated)
        quality["applied_edits"] = [*(quality.get("applied_edits") or []), *removals]
    quality["review"] = review
    # 6 the signature, after every check
    signature = getattr(user, "signature", None) or ""
    content = report.rstrip() + ("\n\n" + signature if signature else "")
    candidate = {"model": out.get("model_used"), "content": content, "error": None,
                 "sections": out.get("sections") or [], "latency_ms": int((time.time() - t0) * 1000),
                 "run_id": str(uuid.uuid4()), "generated_at": _now(), "description": out.get("description"),
                 "quality_check": quality, "signature": signature, "options": [], "options_status": "skipped",
                 "removed": removed, "kept_by_dictation": kept_by_dictation, "fixed_lines": []}
    yield {"event": "candidate", "payload": candidate}
    # 7 save, always (D19)
    stamp = (tss.generation_stamp(str(template.id), template.template_config, "stack") if template
             else {"path": "stack", "stack_sheet_id": req.stack_sheet_id})
    variables = {**{k: v for k, v in req.variables.items() if k != "FINDINGS"},
                 "FINDINGS": plain, "CLINICAL_HISTORY": req.history, "SCAN_TYPE": req.scan_type}
    description = candidate["description"] or ""
    row = create_report(
        db, str(user.id), "templated" if template else "auto", content, candidate["model"] or "",
        input_data={"variables": variables, "extracted_scan_type": req.scan_type},
        template_id=str(template.id) if template else None,
        description=f"{template.name} - {description}" if template else description,
        candidate_reports=[candidate], generation_stamp=stamp)
    row.generation_mode = "stack"
    db.commit()
    if template:
        increment_template_usage(db, str(template.id))
    try:
        schedule_review(str(row.id))
    except Exception as e:  # noqa: BLE001 -- the review never blocks the report
        logger.warning("[stack.generate] schedule_review failed: %s", type(e).__name__)
    yield {"event": "done", "payload": {"report_id": str(row.id), "run_id": candidate["run_id"], "succeeded": True,
                                        "description": description}}
