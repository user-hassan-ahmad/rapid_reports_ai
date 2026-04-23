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
    analyser_prompt_version,
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
# Generator configuration
# ─────────────────────────────────────────────────────────────────────────────
# Single GLM-4.7 generator. The earlier dual-model pattern (GLM + Sonnet) was
# retired because Sonnet's narrative lean fought the consultant-handover voice
# we want, and the richer Haiku skill sheet (running in the analyser tier) now
# delivers the clinical depth Sonnet used to contribute.

GENERATOR_MODEL = "zai-glm-4.7"


# ─────────────────────────────────────────────────────────────────────────────
# Analyser configuration
# ─────────────────────────────────────────────────────────────────────────────
# Production default: /analyse fires the FAST (GLM) analyser only. Evaluation
# confirmed GLM→GLM is the optimal stylistic path on the majority of cases;
# Haiku's depth advantage concentrates on a narrow aetiology-branching subset
# that Path B (tightening the GLM analyser prompt) aims to close.
#
# The Haiku (BEST) infrastructure is preserved: MODEL_CONFIG entry, analyser
# prompt, test suite invocation via generate_ephemeral_skill_sheet(model_override=...)
# — all untouched. Flip this flag on to restore the speculative parallel
# pattern for production A/B testing:
#     export QUICK_REPORT_ANALYSE_PARALLEL=true
#     # restart uvicorn
# Read inside each request so a server restart is enough — no code deploy.

def _parallel_analyse_enabled() -> bool:
    """Runtime toggle for parallel FAST+BEST analyser firing on /analyse.

    Default: false (GLM-only production path). Set to true to re-enable
    the speculative parallel pattern (FAST GLM + BEST Haiku in parallel).
    """
    raw = os.environ.get("QUICK_REPORT_ANALYSE_PARALLEL", "false").strip().lower()
    return raw in ("true", "1", "yes", "on")


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


class FinaliseRequest(BaseModel):
    final_report_content: str
    # If not provided, the server computes a unified diff against the persisted
    # candidate content.
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
    """Analyser SSE endpoint. Production default: fires the FAST (GLM) sheet
    only. Set env QUICK_REPORT_ANALYSE_PARALLEL=true to restore the speculative
    parallel pattern (FAST GLM + BEST Haiku concurrently).

    Designed to run in parallel with radiologist dictation — scan context is
    captured at workspace creation time, so the FAST sheet (~9s) is ready
    before dictation completes. The frontend enables the Generate button on
    the first ready event and uses whichever sheet_id is available at click.

    Event stream — single mode (default):
      event: analyser_ready  data: {variant: "fast", sheet_id, model_used, latency_ms, skill_sheet}
      event: done            data: {succeeded, fast_sheet_id, best_sheet_id=None}

    Event stream — parallel mode (flag on):
      event: analyser_ready  data: {variant: "fast"|"best", ...}   × 2
      event: done            data: {both_succeeded, fast_sheet_id, best_sheet_id}

      event: error           data: {error}   (on upstream failure)
    """
    user_id_str = str(current_user.id)

    async def event_stream():
        run_id_base = new_run_id()

        if not request.scan_type.strip():
            yield _sse("error", {"error": "Scan type is required"})
            return

        # Cerebras key is only meaningful for the GLM (FAST) path; the
        # Anthropic (BEST) path fetches ANTHROPIC_API_KEY inside the call.
        api_key = get_system_api_key("cerebras", "CEREBRAS_API_KEY") or ""

        fast_model = MODEL_CONFIG.get("QUICK_REPORT_ANALYZER_FAST", "zai-glm-4.7")
        best_model = MODEL_CONFIG.get("QUICK_REPORT_ANALYZER_BEST", "claude-haiku-4-5-20251001")

        async def _run_variant(variant: str, model_name: str) -> dict:
            run_id = f"{run_id_base}-{variant}"
            try:
                result = await generate_ephemeral_skill_sheet(
                    scan_type=request.scan_type,
                    clinical_history=request.clinical_history,
                    api_key=api_key,
                    model_override=model_name,
                )
                sheet_row = create_ephemeral_skill_sheet(
                    db=db,
                    user_id=user_id_str,
                    scan_type=request.scan_type,
                    clinical_history=request.clinical_history,
                    skill_sheet_markdown=result.get("skill_sheet", ""),
                    analyser_model=result.get("model_used", ""),
                    analyser_latency_ms=result.get("latency_ms"),
                    analyser_prompt_version=result.get("prompt_version") or analyser_prompt_version(model_name),
                    run_id=run_id,
                )
                try:
                    log_analyser_run(
                        run_id=run_id,
                        scan_type=request.scan_type,
                        clinical_history=request.clinical_history,
                        result=result,
                    )
                except Exception:
                    pass
                return {
                    "variant": variant,
                    "sheet_id": str(sheet_row.id),
                    "model_used": result.get("model_used"),
                    "latency_ms": result.get("latency_ms"),
                    "skill_sheet": result.get("skill_sheet", ""),
                    "error": None,
                }
            except Exception as e:
                logger.warning("analyser variant=%s model=%s failed: %s", variant, model_name, e)
                try:
                    log_analyser_run(
                        run_id=run_id,
                        scan_type=request.scan_type,
                        clinical_history=request.clinical_history,
                        result={},
                        error=str(e),
                    )
                except Exception:
                    pass
                return {
                    "variant": variant,
                    "sheet_id": None,
                    "model_used": model_name,
                    "latency_ms": None,
                    "skill_sheet": "",
                    "error": str(e),
                }

        parallel = _parallel_analyse_enabled()
        logger.info(
            "quick-report /analyse firing variants: %s",
            "fast+best (parallel)" if parallel else "fast only (single)",
        )

        fast_task = asyncio.create_task(_run_variant("fast", fast_model))
        tasks = [fast_task]
        if parallel:
            best_task = asyncio.create_task(_run_variant("best", best_model))
            tasks.append(best_task)

        results_by_variant: dict[str, dict] = {}
        for coro in asyncio.as_completed(tasks):
            record = await coro
            results_by_variant[record["variant"]] = record
            yield _sse("analyser_ready", record)

        fast_rec = results_by_variant.get("fast", {})
        best_rec = results_by_variant.get("best", {})
        done_payload = {
            "fast_sheet_id": fast_rec.get("sheet_id"),
            "best_sheet_id": best_rec.get("sheet_id"),  # None in single mode
        }
        if parallel:
            done_payload["both_succeeded"] = (
                not fast_rec.get("error") and not best_rec.get("error")
            )
        else:
            done_payload["succeeded"] = not fast_rec.get("error")
        yield _sse("done", done_payload)

    return EventSourceResponse(event_stream())


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
    user_signature: str | None = None,
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
            user_signature=user_signature,
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

    Fires a single GLM-4.7 generator against the skill sheet, emits the
    ``candidate`` event when it completes, then a ``done`` event once the
    report has been persisted.

    Accepts either ``sheet_id`` (preferred; skill sheet already persisted by a
    prior /analyse call) or ``scan_type`` + ``clinical_history`` as a one-shot
    fallback that runs the analyser inline before generation.

    Event stream:
      event: candidate  data: {model, content, latency_ms, run_id, ...}
      event: done       data: {report_id, sheet_id, succeeded, description}

      event: error      data: {error}           (on upstream failure before the generator fires)
    """
    # Resolve user_id now — SSE generator body closes over Session which is
    # scoped to the request; current_user.id stays valid within the generator.
    user_id_str = str(current_user.id)
    user_signature = current_user.signature

    async def event_stream():
        run_id_base = new_run_id()
        try:
            if not request.findings.strip():
                yield _sse("error", {"error": "Findings are required"})
                return

            # Cerebras key passes through for Cerebras-backed analysers;
            # Anthropic-backed analysers fetch ANTHROPIC_API_KEY inline.
            # An empty cerebras key is fine if the active analyser is Anthropic,
            # but the generator dual-model path still needs model-specific keys
            # at its own call sites.
            api_key = get_system_api_key("cerebras", "CEREBRAS_API_KEY") or ""

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
                    analyser_prompt_version=analyser_result.get("prompt_version") or analyser_prompt_version(analyser_result.get("model_used", "zai-glm-4.7")),
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

            # ── Fire the GLM generator ────────────────────────────────────
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

            logger.info("quick-report generate firing model=%s", GENERATOR_MODEL)
            candidate = await _run_one_generator(
                tm=tm,
                template_config=template_config,
                user_inputs=user_inputs,
                model_name=GENERATOR_MODEL,
                run_id=f"{run_id_base}-{GENERATOR_MODEL[:8]}",
                scan_type=scan_type,
                clinical_history=clinical_history,
                skill_sheet_markdown=skill_sheet_markdown,
                user_signature=user_signature,
            )

            logger.info(
                "[SSE] yielding candidate event model=%s content_chars=%d latency=%sms error=%s",
                candidate.get("model"),
                len(candidate.get("content") or ""),
                candidate.get("latency_ms"),
                candidate.get("error"),
            )
            yield _sse("candidate", candidate)

            description = candidate.get("description")

            report_row = create_quick_report_with_candidates(
                db=db,
                user_id=user_id_str,
                ephemeral_skill_sheet_id=str(sheet_row.id),
                findings_dictation=request.findings,
                clinical_history=clinical_history,
                scan_type=scan_type,
                candidate_reports=[candidate],
                description=description,
            )

            logger.info(
                "[SSE] yielding done event report_id=%s sheet_id=%s succeeded=%s",
                report_row.id,
                sheet_row.id,
                candidate.get("error") is None,
            )
            yield _sse(
                "done",
                {
                    "report_id": str(report_row.id),
                    "sheet_id": str(sheet_row.id),
                    "run_id": run_id_base,
                    "succeeded": candidate.get("error") is None,
                    "description": description,
                },
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.exception("[SSE] generator raised; yielding error event")
            yield _sse("error", {"error": str(e)})

    return EventSourceResponse(event_stream())


@router.patch("/reports/{report_id}/finalise")
async def finalise_report(
    report_id: str,
    request: FinaliseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record the radiologist's final edited report content and a diff against
    the generated candidate. If no diff is provided, compute a unified diff
    server-side.

    The ``final_edit_diff`` is the feedback signal that will eventually feed
    into learning about what the radiologist corrects and what they accept.
    """
    report = get_report(db, report_id, user_id=str(current_user.id))
    if report is None:
        return {"success": False, "error": f"report {report_id} not found"}

    # Compute diff if not provided. With a single generator there is one
    # candidate — diff against it.
    diff_text = request.final_edit_diff
    if diff_text is None:
        candidates = report.candidate_reports or []
        baseline_content = candidates[0].get("content", "") if candidates else ""

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
        selected_model=GENERATOR_MODEL,
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
