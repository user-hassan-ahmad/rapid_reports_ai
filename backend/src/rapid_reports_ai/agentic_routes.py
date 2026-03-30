"""
Agentic report pipeline API routes — /api/v2/*

Runs in parallel to the existing /api/chat system.
Switch-over: when /api/v2/compare confirms quality, replace generate_auto_report
call in main.py with run_agentic_pipeline (see plan Section 10).
"""

import asyncio
import time
from typing import Tuple

from fastapi import APIRouter, Depends, HTTPException

from .auth import get_current_user
from .database.models import User
from .encryption import get_system_api_key
from .enhancement_utils import generate_auto_report, MODEL_CONFIG, _get_model_provider
from .prompt_manager import get_prompt_manager
from .agentic_pipeline import (
    generate_report_plan,
    run_agentic_pipeline,
)
from .agentic_models import (
    AgenticGenerateRequest,
    AgenticReportOutput,
    CompareResponse,
    MonolithicCompareResponse,
    PlanOnlyResponse,
)

agentic_router = APIRouter(prefix="/api/v2", tags=["agentic"])


# ---------------------------------------------------------------------------
# POST /api/v2/plan  — Phase 1 only; primary evaluation endpoint
# ---------------------------------------------------------------------------

@agentic_router.post("/plan", response_model=PlanOnlyResponse)
async def plan_only(
    request: AgenticGenerateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Run Phase 1 (planning agent) only.

    Returns the full ReportPlan (structured clinical fields + retrieval_intents).
    Use this endpoint to evaluate plan quality before enabling the full pipeline.
    The programmatic execution brief is built server-side from these fields in Phase 2.
    """
    cerebras_api_key = get_system_api_key("cerebras", "CEREBRAS_API_KEY")
    if not cerebras_api_key:
        raise HTTPException(
            status_code=503,
            detail="CEREBRAS_API_KEY not configured.",
        )

    start_ms = time.time()
    try:
        plan = await generate_report_plan(
            clinical_history=request.clinical_history,
            scan_type=request.scan_type,
            findings=request.findings,
            api_key=cerebras_api_key,
            prior_report=request.prior_report,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Planning phase failed: {exc}")

    plan_ms = int((time.time() - start_ms) * 1000)
    return PlanOnlyResponse(plan=plan, plan_ms=plan_ms)


# ---------------------------------------------------------------------------
# POST /api/v2/generate  — Full pipeline
# ---------------------------------------------------------------------------

@agentic_router.post("/generate", response_model=AgenticReportOutput)
async def generate_agentic(
    request: AgenticGenerateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Run the full agentic pipeline: Phase 1 → 1.5 → 2 → Phase 3 (if needed).

    Returns AgenticReportOutput — drop-in compatible with ReportOutput
    (report_content, description, scan_type, model_used are identical fields).
    """
    cerebras_api_key = get_system_api_key("cerebras", "CEREBRAS_API_KEY")
    groq_api_key = get_system_api_key("groq", "GROQ_API_KEY")

    if not cerebras_api_key:
        raise HTTPException(
            status_code=503,
            detail="CEREBRAS_API_KEY not configured.",
        )
    if (
        _get_model_provider(MODEL_CONFIG["REPORT_EXECUTOR"]) == "groq"
        and not (groq_api_key or "").strip()
    ):
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY not configured (required for agentic Phase 2 executor).",
        )

    signature = getattr(current_user, "signature", None)

    try:
        result = await run_agentic_pipeline(
            clinical_history=request.clinical_history,
            scan_type=request.scan_type,
            findings=request.findings,
            cerebras_api_key=cerebras_api_key,
            groq_api_key=groq_api_key or "",
            signature=signature,
            prior_report=request.prior_report,
            skip_guidelines=request.skip_guidelines,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agentic pipeline failed: {exc}")

    return result


# ---------------------------------------------------------------------------
# POST /api/v2/compare  — A/B: current system vs agentic pipeline
# ---------------------------------------------------------------------------

@agentic_router.post("/compare", response_model=CompareResponse)
async def compare_pipelines(
    request: AgenticGenerateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Run current generate_auto_report and the full agentic pipeline concurrently.

    Returns both outputs, the agentic plan, and per-pipeline timing.
    Use this endpoint to validate agentic quality before switch-over.
    """
    cerebras_api_key = get_system_api_key("cerebras", "CEREBRAS_API_KEY")
    groq_api_key = get_system_api_key("groq", "GROQ_API_KEY")
    anthropic_api_key = get_system_api_key("anthropic", "ANTHROPIC_API_KEY")

    if not cerebras_api_key:
        raise HTTPException(status_code=503, detail="CEREBRAS_API_KEY not configured.")
    if not anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured.")
    if (
        _get_model_provider(MODEL_CONFIG["REPORT_EXECUTOR"]) == "groq"
        and not (groq_api_key or "").strip()
    ):
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY not configured (required for agentic Phase 2 executor).",
        )

    signature = getattr(current_user, "signature", None)

    # Render prompts for the current pipeline — replicates main.py /api/chat logic
    # (lines 535-568: PromptManager load + render before passing to generate_auto_report)
    pm = get_prompt_manager()
    primary_model = MODEL_CONFIG.get("PRIMARY_REPORT_GENERATOR", "zai-glm-4.7")
    prompt_data = pm.load_prompt("radiology_report", "default", primary_model=primary_model)
    system_prompt = prompt_data.get("system_prompt", "")
    variables = {
        "CLINICAL_HISTORY": request.clinical_history,
        "SCAN_TYPE": request.scan_type,
        "FINDINGS": request.findings,
    }
    # render_prompt expects the full prompt_data dict (uses 'template' key internally)
    temp_prompt_data = {"template": prompt_data.get("template", "")}
    user_prompt = pm.render_prompt(temp_prompt_data, variables)

    current_start = time.time()
    agentic_start = time.time()

    current_task = asyncio.create_task(
        generate_auto_report(
            model="claude",
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            api_key=anthropic_api_key,
            signature=signature,
            clinical_history=request.clinical_history,
        )
    )
    agentic_task = asyncio.create_task(
        run_agentic_pipeline(
            clinical_history=request.clinical_history,
            scan_type=request.scan_type,
            findings=request.findings,
            cerebras_api_key=cerebras_api_key,
            groq_api_key=groq_api_key or "",
            signature=signature,
            prior_report=request.prior_report,
            skip_guidelines=request.skip_guidelines,
        )
    )

    try:
        current_result, agentic_result = await asyncio.gather(
            current_task, agentic_task, return_exceptions=True
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Compare pipeline error: {exc}")

    if isinstance(current_result, Exception):
        raise HTTPException(
            status_code=500,
            detail=f"Current pipeline failed: {current_result}",
        )
    if isinstance(agentic_result, Exception):
        raise HTTPException(
            status_code=500,
            detail=f"Agentic pipeline failed: {agentic_result}",
        )

    current_ms = int((time.time() - current_start) * 1000)
    agentic_ms = agentic_result.pipeline_ms or int((time.time() - agentic_start) * 1000)

    return CompareResponse(
        current_output=current_result.report_content,
        agentic_output=agentic_result.report_content,
        plan=agentic_result.plan,
        current_ms=current_ms,
        agentic_ms=agentic_ms,
    )


# ---------------------------------------------------------------------------
# POST /api/v2/compare-monolithic — classic zai-glm-4.7.json vs clinical-clusters variant
# ---------------------------------------------------------------------------


def _render_radiology_user_prompt(
    pm, primary_model: str, request: AgenticGenerateRequest
) -> Tuple[str, str]:
    """Load prompt for primary_model variant and return (system_prompt, user_prompt)."""
    prompt_data = pm.load_prompt(
        "radiology_report", "default", primary_model=primary_model
    )
    system_prompt = prompt_data.get("system_prompt", "")
    variables = {
        "CLINICAL_HISTORY": request.clinical_history,
        "SCAN_TYPE": request.scan_type,
        "FINDINGS": request.findings,
    }
    temp_prompt_data = {"template": prompt_data.get("template", "")}
    user_prompt = pm.render_prompt(temp_prompt_data, variables)
    return system_prompt, user_prompt


@agentic_router.post("/compare-monolithic", response_model=MonolithicCompareResponse)
async def compare_monolithic_prompts(
    request: AgenticGenerateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Run generate_auto_report twice in parallel: classic monolithic prompt vs
    zai-glm-4.7-clinical-clusters.json. Same PRIMARY_REPORT_GENERATOR model for both.
    """
    cerebras_api_key = get_system_api_key("cerebras", "CEREBRAS_API_KEY")
    anthropic_api_key = get_system_api_key("anthropic", "ANTHROPIC_API_KEY")

    if not cerebras_api_key:
        raise HTTPException(status_code=503, detail="CEREBRAS_API_KEY not configured.")
    if not anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured.")

    signature = getattr(current_user, "signature", None)
    pm = get_prompt_manager()

    classic_sys, classic_user = _render_radiology_user_prompt(pm, "zai-glm-4.7", request)
    clusters_sys, clusters_user = _render_radiology_user_prompt(
        pm, "zai-glm-4.7-clinical-clusters", request
    )

    async def run_variant(system_prompt: str, user_prompt: str):
        t0 = time.time()
        out = await generate_auto_report(
            model="claude",
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            api_key=anthropic_api_key,
            signature=signature,
            clinical_history=request.clinical_history,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        return out, elapsed_ms

    classic_task = asyncio.create_task(run_variant(classic_sys, classic_user))
    clusters_task = asyncio.create_task(run_variant(clusters_sys, clusters_user))

    try:
        classic_pair, clusters_pair = await asyncio.gather(
            classic_task, clusters_task, return_exceptions=True
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Compare-monolithic error: {exc}")

    if isinstance(classic_pair, Exception):
        raise HTTPException(
            status_code=500,
            detail=f"Classic monolithic prompt failed: {classic_pair}",
        )
    if isinstance(clusters_pair, Exception):
        raise HTTPException(
            status_code=500,
            detail=f"Clinical-clusters prompt failed: {clusters_pair}",
        )

    classic_result, classic_ms = classic_pair
    clusters_result, clusters_ms = clusters_pair

    return MonolithicCompareResponse(
        classic_output=classic_result.report_content,
        clinical_clusters_output=clusters_result.report_content,
        classic_ms=classic_ms,
        clusters_ms=clusters_ms,
        model_used=classic_result.model_used or clusters_result.model_used,
    )
