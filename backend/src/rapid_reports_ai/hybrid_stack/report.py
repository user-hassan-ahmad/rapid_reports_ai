"""The one stack Generate (integration spec §5, D27 P2a): verify, build the statements, write with today's quick or
template writer, guard removed sentences, save, schedule the review. Never falls back to the old flow."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy.orm import Session

from .. import template_sheet_structure as tss
from ..database.crud import create_report, get_template, increment_template_usage, is_retired_template
from ..quick_report_api import _slim_markdown
from ..quick_report_generator import _describe, generate_quick_report
from ..review_engine.engine import schedule_review
from ..template_lean import generate_template_report_lean
from ..template_number_check import undictated_numbers
from .findings import findings_block
from .gate_model import findings_hash
from .removed_guard import guard, reconcile
from .resolution import TokenError, verify as verify_token
from .template import template_structure

logger = logging.getLogger(__name__)


class StackError(Exception):
    """A plain message for the radiologist; the request never falls back to the old flow."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run(req, user, db: Session) -> AsyncIterator[dict]:
    t0 = time.time()
    # 0 verify: the session resolution (D26: read from the signed token, never re-resolved), ownership, the template
    # unchanged since setup and usable, the library unchanged, and a gate that still matches the units
    try:
        tok = verify_token(req.structure_key)
    except TokenError:
        raise StackError("Set up the workspace again.") from None
    if (req.kind == "template") != (tok["src"] == "template"):
        raise StackError("Set up the workspace again.")
    template = None
    if req.kind == "template":
        if tok["tid"] != (req.template_id or ""):
            raise StackError("Set up the workspace again.")
        template = get_template(db, req.template_id or "", user_id=str(user.id))
        if template is None:
            raise StackError("Template not found.")
        if tss.sheet_hash((template.template_config or {}).get("skill_sheet", "") or "") != tok["sh"]:
            raise StackError("The template changed. Set up the workspace again.")
        if is_retired_template(template) or template_structure(template.template_config or {}) is None:
            raise StackError("This template can't be used with the scratchpad. Create a fresh one.")
    if tok["src"] == "library":
        from .protocol_library.bundle import get_bundle
        b = get_bundle()
        if b is None or b.version != tok.get("bv"):
            raise StackError("The protocol library was updated. Set up the workspace again.")
    if req.gate.findings_hash is not None and req.gate.findings_hash != findings_hash(req.units):
        raise StackError("The scratchpad changed after Confirm. Confirm again.")
    # 1 removals the dictation has since stated go first (dictation wins), then the statements on the reconciled list
    said = findings_block(req.units, req.groups, req.gate, removed=[]).said()   # units and taps only
    removed, kept_by_dictation = await reconcile(list(req.gate.removed), said)
    st = findings_block(req.units, req.groups, req.gate, removed=removed)
    plain = st.plain()
    # 2–4 write: today's writers (slots, check, values backstop and template numbers run inside the template writer)
    if req.kind == "quick":
        out = await generate_quick_report(
            skill_sheet="", scan_type=req.scan_type, findings=st.block, clinical_history=req.history,
            user_signature=None, stack=True, declined=removed, conclusion=st.conclusion,
            stack_sheet=_slim_markdown(db, tok.get("sid")), check_findings=plain)
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
    if req.kind == "template":   # the template writer describes the labelled block; the description reads plain
        (report, removals, guard_items), description = await asyncio.gather(
            guard(generated, removed, plain), _describe(plain, req.history, req.scan_type))
    else:
        (report, removals, guard_items), description = await guard(generated, removed, plain), out.get("description")
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
                 "run_id": str(uuid.uuid4()), "generated_at": _now(), "description": description,
                 "quality_check": quality, "signature": signature, "options": [], "options_status": "skipped",
                 "removed": removed, "kept_by_dictation": kept_by_dictation, "fixed_lines": [], "stack": True,
                 # the region normals the radiologist confirmed, minus what was removed: the review reads these at
                 # once (the browser links the session log to the report only after `done`)
                 "assumed_confirmed": list(dict.fromkeys(
                     x for v in req.gate.assumed.values() for x in v
                     if x.strip() and " ".join(x.split()).lower() not in {" ".join(r.split()).lower() for r in removed}))}
    # 7 save, always (D19), before anything is shown: a report on screen always has its row
    stamp = ({**(tss.generation_stamp(str(template.id), template.template_config, "stack") or {}),
              "structure_key": req.structure_key} if template
             else {"path": "stack", "structure_key": req.structure_key})
    variables = {**{k: v for k, v in req.variables.items() if k != "FINDINGS"},
                 "FINDINGS": plain, "CLINICAL_HISTORY": req.history, "SCAN_TYPE": req.scan_type}
    description = description or ""
    try:
        row = create_report(
            db, str(user.id), "templated" if template else "auto", content, candidate["model"] or "",
            input_data={"variables": variables, "extracted_scan_type": req.scan_type},
            template_id=str(template.id) if template else None,
            description=f"{template.name} - {description}" if template else description,
            candidate_reports=[candidate], generation_stamp=stamp, generation_mode="stack")
        if template:
            increment_template_usage(db, str(template.id))
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.exception("[stack.generate] save failed")
        raise StackError("The report couldn't be saved. Please try again.") from e
    yield {"event": "candidate", "payload": candidate}
    try:
        schedule_review(str(row.id))
    except Exception as e:  # noqa: BLE001 -- the review never blocks the report
        logger.warning("[stack.generate] schedule_review failed: %s", type(e).__name__)
    yield {"event": "done", "payload": {"report_id": str(row.id), "run_id": candidate["run_id"], "succeeded": True,
                                        "description": description}}
