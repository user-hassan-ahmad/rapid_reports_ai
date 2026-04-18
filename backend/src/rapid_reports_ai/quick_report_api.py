"""
Quick Report Production API — Phases 2 + 3.

Production endpoints for the ephemeral-skill-sheet pipeline. Deliberately
separated from three adjacent paths:

- ``/api/chat`` radiology_report (legacy auto-report path) — UNTOUCHED. Remains
  the production quick-report generator today and is the fallback if this
  pipeline needs to be rolled back.
- ``/api/quick-report-proto/*`` (stress-test surface) — UNTOUCHED. Still used
  for prompt iteration, model A/B, and new-scan-type validation.
- ``/api/templates/skill-sheet/*`` (offline template creation) — UNTOUCHED.

This module self-contains every production endpoint under a single APIRouter
mounted at ``/api/quick-report``. Removing the mount removes the feature
cleanly — no entanglement with other flows.

Endpoints:
  POST   /api/quick-report/analyse                            — persist ephemeral sheet, return sheet_id
  POST   /api/quick-report/generate                           — SSE stream, fires GLM-4.7 + Claude Sonnet 4.6 in parallel,
                                                                emits candidate events progressively, then done event
  PATCH  /api/quick-report/reports/{report_id}/select         — record user's candidate selection
  PATCH  /api/quick-report/reports/{report_id}/finalise       — record final edited content + diff

See project_quick_report_analyser.md → "Production plan" for the full spec.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from .auth import get_current_user
from .database import (
    create_ephemeral_skill_sheet,
    create_quick_report_with_candidates,
    get_db,
    get_ephemeral_skill_sheet,
    get_report,
    set_quick_report_selection,
)
from .database.models import User
from .encryption import get_system_api_key
from .enhancement_utils import MODEL_CONFIG
from .quick_report_analyser import (
    ANALYSER_PROMPT_VERSION,
    generate_ephemeral_skill_sheet,
    log_analyser_run,
    log_generator_run,
    new_run_id,
)
from .quick_report_hardening import QUICK_REPORT_HARDENING_PREAMBLE
from .template_manager import TemplateManager


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quick-report", tags=["quick-report"])


# ─────────────────────────────────────────────────────────────────────────────
# Dual-model configuration for Phase 3 SSE
# ─────────────────────────────────────────────────────────────────────────────
# When dual-model is enabled, both models run in parallel for every generate
# call; the radiologist sees whichever arrives first as the primary report and
# can toggle to the alternative once it lands. See project_quick_report_analyser.md
# — model choices validated across four stress-test cases:
#   - GLM-4.7: fast (~5s), fidelity-strict, filler floor ~7/run
#   - Claude Sonnet 4.6: richer narrative (~10s), near-zero filler with the lean
#     user prompt, light clinical inference sometimes surfaces

# Primary (always used). Single model when dual-model is disabled.
PRIMARY_MODEL = "zai-glm-4.7"
# Secondary (only used when dual-model is enabled). Claude costs ~3× GLM per
# token, so the env flag below lets you run single-model for cost savings.
SECONDARY_MODEL = "claude-sonnet-4-6"


def _dual_model_enabled() -> bool:
    """Runtime-readable toggle for dual-model generation.

    Default is enabled. To disable (cost-save, GLM-only):
        export QUICK_REPORT_DUAL_MODEL_ENABLED=false
        # restart uvicorn

    Read inside each request (not at module import) so a server restart after
    editing .env is enough — no code deploy required to flip the cost lever.
    """
    raw = os.environ.get("QUICK_REPORT_DUAL_MODEL_ENABLED", "true").strip().lower()
    return raw not in ("false", "0", "no", "off", "")


def _active_models() -> list[str]:
    """Models to fire for this request, respecting the dual-model toggle."""
    if _dual_model_enabled():
        return [PRIMARY_MODEL, SECONDARY_MODEL]
    return [PRIMARY_MODEL]


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────


class AnalyseRequest(BaseModel):
    scan_type: str
    clinical_history: str


class GenerateRequest(BaseModel):
    findings: str
    # Either sheet_id (preferred — sheet already persisted by /analyse) OR
    # scan_type + clinical_history (one-shot; /generate runs the analyser inline).
    sheet_id: Optional[str] = None
    scan_type: Optional[str] = None
    clinical_history: Optional[str] = None


class SelectCandidateRequest(BaseModel):
    selected_model: str
    selection_ms_since_ready: Optional[int] = None


class FinaliseRequest(BaseModel):
    final_report_content: str
    # If not provided, the server computes a unified diff against the selected
    # candidate's content (or the first candidate if none selected).
    final_edit_diff: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/analyse")
async def analyse(
    request: AnalyseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate an ephemeral skill sheet and persist it. Returns sheet_id which
    the subsequent /generate call should pass through.

    Designed to run in parallel with radiologist dictation — the scan context
    is captured at workspace creation time, so the sheet is ready by the time
    findings are submitted.
    """
    run_id = new_run_id()
    try:
        if not request.scan_type.strip():
            return {"success": False, "error": "Scan type is required"}

        api_key = get_system_api_key("cerebras", "CEREBRAS_API_KEY")
        if not api_key:
            return {"success": False, "error": "Cerebras API key not configured"}

        result = await generate_ephemeral_skill_sheet(
            scan_type=request.scan_type,
            clinical_history=request.clinical_history,
            api_key=api_key,
        )

        # Persist — this is the whole point of Phase 1, now load-bearing
        # for Phase 2's /generate lookup path.
        sheet_row = create_ephemeral_skill_sheet(
            db=db,
            user_id=str(current_user.id),
            scan_type=request.scan_type,
            clinical_history=request.clinical_history,
            skill_sheet_markdown=result.get("skill_sheet", ""),
            analyser_model=result.get("model_used", ""),
            analyser_latency_ms=result.get("latency_ms"),
            analyser_prompt_version=ANALYSER_PROMPT_VERSION,
            run_id=run_id,
        )

        log_analyser_run(
            run_id=run_id,
            scan_type=request.scan_type,
            clinical_history=request.clinical_history,
            result=result,
        )

        return {
            "success": True,
            "sheet_id": str(sheet_row.id),
            "run_id": run_id,
            "skill_sheet": result.get("skill_sheet", ""),
            "model_used": result.get("model_used"),
            "latency_ms": result.get("latency_ms"),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        log_analyser_run(
            run_id=run_id,
            scan_type=request.scan_type,
            clinical_history=request.clinical_history,
            result={},
            error=str(e),
        )
        return {"success": False, "error": str(e), "run_id": run_id}


async def _run_one_generator(
    *,
    tm: TemplateManager,
    template_config: dict,
    user_inputs: dict,
    model_name: str,
    run_id: str,
    scan_type: str,
    clinical_history: str,
    skill_sheet_markdown: str,
) -> dict:
    """Run a single generator and return a candidate-record dict.

    Wraps every exception into the candidate record so one model's failure
    doesn't propagate — the other model's result still streams to the client
    and both are persisted (the failed one with its error message).
    """
    t0 = time.time()
    try:
        result = await tm.generate_report_from_config(
            template_config=template_config,
            user_inputs=user_inputs,
            user_signature=None,
            model_override=model_name,
        )
        latency_ms = int((time.time() - t0) * 1000)
        result["latency_ms"] = latency_ms
        # Fire-and-forget: log to proto log for debugging. Non-blocking.
        try:
            log_generator_run(
                run_id=run_id,
                scan_type=scan_type,
                clinical_history=clinical_history,
                findings=(user_inputs or {}).get("FINDINGS", ""),
                skill_sheet=skill_sheet_markdown,
                result=result,
            )
        except Exception:
            pass
        return {
            "model": model_name,
            "content": result.get("report_content", ""),
            "latency_ms": latency_ms,
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
            "description": result.get("description"),
        }
    except Exception as e:
        logger.warning("generator %s failed: %s", model_name, e)
        return {
            "model": model_name,
            "content": "",
            "latency_ms": int((time.time() - t0) * 1000),
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
            "description": None,
        }


def _sse(event: str, payload: dict) -> dict:
    """Format an event for sse-starlette's EventSourceResponse."""
    return {"event": event, "data": json.dumps(payload)}


@router.post("/generate")
async def generate(
    request: GenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a report against the ephemeral skill sheet via SSE streaming.

    Fires GLM-4.7 and Claude Sonnet 4.6 in parallel against the same skill
    sheet. Emits a ``candidate`` event as each model completes (progressive
    disclosure — user sees the first-arriving report immediately and the
    alternative becomes available when the second lands). Emits a ``done``
    event with the persisted ``report_id`` once both candidates have completed
    and been written to the DB.

    Accepts either ``sheet_id`` (preferred; skill sheet already persisted by a
    prior /analyse call) or ``scan_type`` + ``clinical_history`` as a one-shot
    fallback that runs the analyser inline before the dual-model generate.

    Event stream:
      event: candidate  data: {model, content, latency_ms, run_id, ...}
      event: candidate  data: {model, content, latency_ms, run_id, ...}
      event: done       data: {report_id, sheet_id, both_succeeded}

      event: error      data: {error}           (on upstream failure before models fire)
    """
    # Resolve user_id now — SSE generator body closes over Session which is
    # scoped to the request; current_user.id stays valid within the generator.
    user_id_str = str(current_user.id)

    async def event_stream():
        run_id_base = new_run_id()
        try:
            if not request.findings.strip():
                yield _sse("error", {"error": "Findings are required"})
                return

            api_key = get_system_api_key("cerebras", "CEREBRAS_API_KEY")
            if not api_key:
                yield _sse("error", {"error": "Cerebras API key not configured"})
                return

            # ── Resolve the skill sheet ───────────────────────────────────
            sheet_row = None
            skill_sheet_markdown = ""
            scan_type = ""
            clinical_history = ""

            if request.sheet_id:
                sheet_row = get_ephemeral_skill_sheet(
                    db, request.sheet_id, user_id=user_id_str
                )
                if sheet_row is None:
                    yield _sse("error", {"error": f"sheet_id {request.sheet_id} not found"})
                    return
                skill_sheet_markdown = sheet_row.skill_sheet_markdown
                scan_type = sheet_row.scan_type
                clinical_history = sheet_row.clinical_history
            elif request.scan_type and request.clinical_history is not None:
                # One-shot fallback: analyser inline, persist sheet, then generate.
                analyser_result = await generate_ephemeral_skill_sheet(
                    scan_type=request.scan_type,
                    clinical_history=request.clinical_history,
                    api_key=api_key,
                )
                sheet_row = create_ephemeral_skill_sheet(
                    db=db,
                    user_id=user_id_str,
                    scan_type=request.scan_type,
                    clinical_history=request.clinical_history,
                    skill_sheet_markdown=analyser_result.get("skill_sheet", ""),
                    analyser_model=analyser_result.get("model_used", ""),
                    analyser_latency_ms=analyser_result.get("latency_ms"),
                    analyser_prompt_version=ANALYSER_PROMPT_VERSION,
                    run_id=run_id_base,
                )
                skill_sheet_markdown = sheet_row.skill_sheet_markdown
                scan_type = request.scan_type
                clinical_history = request.clinical_history
            else:
                yield _sse(
                    "error",
                    {"error": "Either sheet_id (preferred) or (scan_type + clinical_history) is required"},
                )
                return

            # ── Fire both models in parallel ──────────────────────────────
            tm = TemplateManager()
            template_config = {
                "generation_mode": "skill_sheet_guided",
                "skill_sheet": QUICK_REPORT_HARDENING_PREAMBLE + skill_sheet_markdown,
                "scan_type": scan_type,
            }
            user_inputs = {
                "FINDINGS": request.findings,
                "CLINICAL_HISTORY": clinical_history,
            }

            models_to_run = _active_models()
            logger.info(
                "quick-report generate firing models=%s (dual_enabled=%s)",
                models_to_run,
                _dual_model_enabled(),
            )
            tasks = [
                asyncio.create_task(
                    _run_one_generator(
                        tm=tm,
                        template_config=template_config,
                        user_inputs=user_inputs,
                        model_name=model_name,
                        # Per-model run_id so proto logs tell candidates apart
                        run_id=f"{run_id_base}-{model_name[:8].replace('/', '-')}",
                        scan_type=scan_type,
                        clinical_history=clinical_history,
                        skill_sheet_markdown=skill_sheet_markdown,
                    )
                )
                for model_name in models_to_run
            ]

            candidates: list = []
            # asyncio.as_completed yields each future in completion order, so
            # whichever model returns first gets emitted first — progressive UX.
            for future in asyncio.as_completed(tasks):
                candidate = await future
                candidates.append(candidate)
                logger.info(
                    "[SSE] yielding candidate event model=%s content_chars=%d latency=%sms error=%s",
                    candidate.get("model"),
                    len(candidate.get("content") or ""),
                    candidate.get("latency_ms"),
                    candidate.get("error"),
                )
                yield _sse("candidate", candidate)

            # ── Persist both candidates to one reports row ────────────────
            # Use the candidate with non-null content as primary for the legacy
            # model_used/report_content columns (matters for reports-list views
            # that don't know about candidate_reports).
            primary_candidate = next(
                (c for c in candidates if c.get("content")), candidates[0]
            )
            # Any non-null description from either model (GLM generally supplies one)
            description = next(
                (c.get("description") for c in candidates if c.get("description")),
                None,
            )

            # Reorder so the primary sits at index 0 in candidate_reports
            ordered_candidates = [primary_candidate] + [
                c for c in candidates if c is not primary_candidate
            ]

            report_row = create_quick_report_with_candidates(
                db=db,
                user_id=user_id_str,
                ephemeral_skill_sheet_id=str(sheet_row.id),
                findings_dictation=request.findings,
                clinical_history=clinical_history,
                scan_type=scan_type,
                candidate_reports=ordered_candidates,
                description=description,
            )

            logger.info(
                "[SSE] yielding done event report_id=%s sheet_id=%s both_succeeded=%s",
                report_row.id,
                sheet_row.id,
                all(c.get("error") is None for c in candidates),
            )
            yield _sse(
                "done",
                {
                    "report_id": str(report_row.id),
                    "sheet_id": str(sheet_row.id),
                    "run_id": run_id_base,
                    "both_succeeded": all(c.get("error") is None for c in candidates),
                    "description": description,
                },
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.exception("[SSE] generator raised; yielding error event")
            yield _sse("error", {"error": str(e)})

    return EventSourceResponse(event_stream())


@router.patch("/reports/{report_id}/select")
async def select_candidate(
    report_id: str,
    request: SelectCandidateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record which candidate the radiologist picked as the base for editing.

    In Phase 2 with single-model generation there is only one candidate, so
    this endpoint is mostly a no-op but records the selection for consistency
    with the dual-model UX arriving in Phase 3.
    """
    # Ownership check — user can only select candidates on their own reports
    report = get_report(db, report_id, user_id=str(current_user.id))
    if report is None:
        return {"success": False, "error": f"report {report_id} not found"}

    updated = set_quick_report_selection(
        db=db,
        report_id=report_id,
        selected_model=request.selected_model,
        selection_ms_since_ready=request.selection_ms_since_ready,
    )
    if updated is None:
        return {"success": False, "error": "Failed to record selection"}

    return {
        "success": True,
        "report_id": str(updated.id),
        "selected_model": updated.selected_model,
        "selection_ms_since_ready": updated.selection_ms_since_ready,
    }


@router.patch("/reports/{report_id}/finalise")
async def finalise_report(
    report_id: str,
    request: FinaliseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record the radiologist's final edited report content and a diff against
    the selected candidate. If no diff is provided, compute a unified diff
    server-side from the selected (or first) candidate.

    The ``final_edit_diff`` is the feedback signal that will eventually feed
    into learning about what the radiologist corrects and what they accept.
    """
    report = get_report(db, report_id, user_id=str(current_user.id))
    if report is None:
        return {"success": False, "error": f"report {report_id} not found"}

    # Compute diff if not provided
    diff_text = request.final_edit_diff
    if diff_text is None:
        # Find the content to diff against — selected candidate if set, else
        # the first candidate in the list
        baseline_content = ""
        candidates = report.candidate_reports or []
        if report.selected_model:
            for cand in candidates:
                if cand.get("model") == report.selected_model:
                    baseline_content = cand.get("content", "")
                    break
        if not baseline_content and candidates:
            baseline_content = candidates[0].get("content", "")

        diff_lines = list(difflib.unified_diff(
            baseline_content.splitlines(keepends=True),
            request.final_report_content.splitlines(keepends=True),
            fromfile="candidate",
            tofile="final",
            n=1,
        ))
        diff_text = "".join(diff_lines)

    updated = set_quick_report_selection(
        db=db,
        report_id=report_id,
        selected_model=report.selected_model or (
            (report.candidate_reports or [{}])[0].get("model", "unknown")
        ),
        final_report_content=request.final_report_content,
        final_edit_diff=diff_text,
    )

    if updated is None:
        return {"success": False, "error": "Failed to finalise report"}

    return {
        "success": True,
        "report_id": str(updated.id),
        "final_report_chars": len(updated.final_report_content or ""),
        "diff_chars": len(updated.final_edit_diff or ""),
    }
