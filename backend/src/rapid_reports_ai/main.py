import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# Also log to file for debugging
_file_handler = logging.FileHandler("/tmp/radflow.log")
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger().addHandler(_file_handler)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, File, UploadFile, HTTPException
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Dict, Optional, List, Any, Literal
import copy
import hashlib
import os
import re
import time
import uuid
from dotenv import load_dotenv
from sqlalchemy.exc import IntegrityError
from .prompt_manager import get_prompt_manager
from .database import (
    get_db,
    SessionLocal,
    Base,
    Template,
    User,
    PasswordResetToken,
    Report,
    create_user,
    get_user_by_email,
    get_user_by_id,
    update_last_login,
    create_reset_token,
    get_valid_reset_token,
    mark_token_used,
    create_template,
    get_template,
    get_templates,
    update_template,
    delete_template,
    rename_tag,
    delete_tag,
    create_report,
    get_report,
    get_user_reports,
    delete_report,
    create_template_version,
    get_template_versions,
    get_template_version,
    restore_template_version,
    increment_template_usage,
    get_current_version_id,
    delete_template_version,
    toggle_template_pin,
    create_report_version,
    get_report_versions,
    get_report_version,
    set_current_report_version,
    create_report_audit,
    get_report_audits,
    acknowledge_criterion,
)
from .database.connection import engine
from .template_manager import TemplateManager
from .auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    SECRET_KEY,
    ALGORITHM,
)
from .email_utils import send_magic_link_email, send_admin_signup_notification
from .encryption import encrypt_api_key, decrypt_api_key, get_system_api_key
from .canvas_routes import canvas_router
from .agentic_routes import agentic_router
from .enhancement_utils import (
    generate_auto_report,
    generate_templated_report,
    build_chat_guideline_context,
    build_audit_guideline_references_memory_section,
    collect_guideline_sources_for_chat,
    format_audit_fix_context_for_system_prompt,
    format_audit_fix_holistic_workflow_instructions,
    run_perplexity_search_chat,
    normalize_evidence_url_for_dedupe,
)
from .enhancement_models import AuditFixContext
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from fastapi.security import OAuth2PasswordRequestForm
import secrets
import asyncio
import json
import aiohttp
import copy

# Load environment variables
load_dotenv()


# Lifespan handler for database initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migrations are handled by startCommand (fix_migration_state.py)
    # This ensures migrations run before the server starts and avoids conflicts
    # Only create tables as a fallback safety net (shouldn't be needed if migrations ran)
    try:
        Base.metadata.create_all(bind=engine)
        print("✓ Database tables verified/created (migrations handled by startCommand)")
    except Exception as e:
        print(f"⚠️  Warning: Could not create tables: {e}")
        # Don't fail startup - migrations should have handled this

    # Seed TNM staging reference data (idempotent — skips if already populated)
    try:
        from rapid_reports_ai.tnm_lookup import seed_tnm_if_empty
        db = SessionLocal()
        try:
            count = seed_tnm_if_empty(db)
            if count > 0:
                print(f"✓ TNM staging: seeded {count} tumour rows")
            else:
                print("✓ TNM staging: already populated")
        finally:
            db.close()
    except Exception as e:
        print(f"⚠️  Warning: TNM seeding skipped: {e}")

    # Start background TTL cleanup for in-memory prefetch store
    _cleanup_task = asyncio.create_task(_cleanup_prefetch_store())

    yield

    _cleanup_task.cancel()
    try:
        await _cleanup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Rapid Reports AI API", lifespan=lifespan)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev
        "http://localhost:4173",  # Vite preview
        "https://rad-flow.uk",  # Main domain (frontend)
        "https://api.rad-flow.uk",  # API subdomain (backend - for docs/swagger)
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",  # Vercel preview deployments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Enhancement cache (findings + guidelines for chat context)
# -----------------------------------------------------------------------------
ENHANCEMENT_RESULTS: Dict[str, Dict[str, Any]] = {}  # Stores findings + guidelines

# -----------------------------------------------------------------------------
# Prefetch pipeline stores
# In-memory cache (30-min TTL) for same-session fast lookup.
# Persisted to prefetch_results DB table for cross-session / post-restart reuse.
# -----------------------------------------------------------------------------
from .enhancement_models import PrefetchOutput  # noqa: E402 (after sys-path loads)

PREFETCH_STORE: Dict[str, PrefetchOutput] = {}  # prefetch_id → PrefetchOutput
PREFETCH_INDEX: Dict[str, str] = {}             # findings_hash → prefetch_id
PREFETCH_TASKS: Dict[str, asyncio.Task] = {}    # prefetch_id → background task (for enhance to await)
_PREFETCH_TTL_S = 1800  # 30 minutes


def _schedule_prefetch_task(
    prefetch_id: str,
    findings_hash: str,
    findings: str,
    scan_type: str,
    clinical_history: str,
    user_id: str,
) -> None:
    """Fire-and-forget prefetch; registers PREFETCH_TASKS for enhance to optionally await."""
    task = asyncio.create_task(
        _run_prefetch_and_store(
            prefetch_id=prefetch_id,
            findings_hash=findings_hash,
            findings=findings,
            scan_type=scan_type,
            clinical_history=clinical_history,
            user_id=user_id,
        )
    )
    PREFETCH_TASKS[prefetch_id] = task

    def _done(t: asyncio.Task) -> None:
        PREFETCH_TASKS.pop(prefetch_id, None)
        if not t.cancelled() and t.exception() is not None:
            print(f"[PREFETCH] background task failed: {t.exception()}")

    task.add_done_callback(_done)


async def _cleanup_prefetch_store():
    """Background task: evict in-memory prefetch entries older than TTL."""
    while True:
        await asyncio.sleep(300)
        now = time.time()
        stale = [k for k, v in list(PREFETCH_STORE.items()) if now - v.created_at > _PREFETCH_TTL_S]
        for k in stale:
            PREFETCH_STORE.pop(k, None)


async def _ensure_enhancement_loaded(report_id: str, db) -> None:
    """Re-populate ENHANCEMENT_RESULTS from DB if missing (handles history reload)."""
    if report_id not in ENHANCEMENT_RESULTS:
        from .database import get_report as _get_report
        row = _get_report(db, report_id)
        if row and row.enhancement_json:
            restored = dict(row.enhancement_json)
            _pj = restored.get("prefetch_output_json")
            if _pj and not restored.get("prefetch_output"):
                try:
                    from .enhancement_models import PrefetchOutput as _PO
                    restored["prefetch_output"] = _PO.model_validate(_pj)
                except Exception as _pe:
                    print(f"[PREFETCH] _ensure_enhancement_loaded: failed to reconstruct PrefetchOutput: {_pe}")
            ENHANCEMENT_RESULTS[report_id] = restored


async def _run_tavily_search_chat(queries: List[str]) -> tuple:
    """
    Tavily Search for the chat `search_external_guidelines` tool.
    Replaces the previous Perplexity-based run_perplexity_search_chat.
    Returns (evidence_text, sources_list) — same shape as the old function.
    """
    import logging
    _log = logging.getLogger(__name__)
    tavily_key = os.getenv("TAVILY_API_KEY", "")
    if not tavily_key:
        _log.warning("TAVILY_API_KEY not set — chat search skipped")
        return ("", [])

    from .guideline_prefetch import (
        DOMAIN_FILTER_PATHWAY, DOMAIN_FILTER_CLASSIFICATION, DOMAIN_FILTER_DIFFERENTIAL
    )
    all_domains = list({
        *DOMAIN_FILTER_PATHWAY,
        *DOMAIN_FILTER_CLASSIFICATION,
        *DOMAIN_FILTER_DIFFERENTIAL,
    })

    try:
        from tavily import AsyncTavilyClient
        client = AsyncTavilyClient(tavily_key)

        async def _one(query: str):
            try:
                resp = await asyncio.wait_for(
                    client.search(
                        query=query,
                        search_depth="advanced",
                        max_results=4,
                        chunks_per_source=3,
                        include_domains=all_domains,
                    ),
                    timeout=20.0,
                )
                return resp.get("results", [])
            except Exception as exc:
                _log.warning("Tavily chat search error: %s", exc)
                return []

        nested = await asyncio.gather(*[_one(q) for q in queries])
        seen: set = set()
        sources = []
        evidence_lines = []
        rank = 1
        for results in nested:
            for r in results:
                url = r.get("url", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                title = (r.get("title") or "").strip()
                content = (r.get("content") or "").strip()
                snippet = content[:400] if content else ""
                evidence_lines.append(
                    f"[{rank}] {title}\nURL: {url}\n{snippet}"
                )
                sources.append({"url": url, "title": title})
                rank += 1

        evidence = "\n\n".join(evidence_lines)
        return evidence, sources
    except Exception as exc:
        _log.error("Tavily chat search failed: %s", exc)
        return ("", [])


async def _run_prefetch_and_store(
    prefetch_id: str,
    findings_hash: str,
    findings: str,
    scan_type: str,
    clinical_history: str,
    user_id: str,
) -> None:
    """
    Background task: run the full prefetch pipeline and persist results to
    PREFETCH_STORE (in-memory) and the prefetch_results DB table.
    Errors are logged; callers proceed with the Perplexity fallback on miss.
    """
    import logging
    _log = logging.getLogger(__name__)
    _wall0 = time.perf_counter()
    try:
        from .guideline_prefetch import run_prefetch_pipeline
        output = await run_prefetch_pipeline(
            findings=findings,
            scan_type=scan_type,
            clinical_history=clinical_history,
            prefetch_id=prefetch_id,
            user_id=user_id,
        )
        _after_pipe = time.perf_counter()
        PREFETCH_STORE[prefetch_id] = output
        print(
            f"[FLOW_TIMING] prefetch_task: pipeline_done prefetch_id={prefetch_id} "
            f"reported_pipeline_ms={output.pipeline_ms} "
            f"wall_pipeline_ms={int((_after_pipe - _wall0) * 1000)}"
        )

        # Persist to DB (7-day TTL) — best-effort, non-blocking
        try:
            from datetime import timezone as _tz, timedelta as _td
            from .database import SessionLocal as _SL
            from .database.models import PrefetchResult as _PR
            _expires = datetime.now(timezone.utc) + timedelta(days=7)
            with _SL() as _db:
                _db.merge(_PR(
                    findings_hash=findings_hash,
                    user_id=uuid.UUID(user_id) if user_id else None,
                    output_json=output.model_dump(mode="json"),
                    pipeline_ms=output.pipeline_ms,
                    created_at=datetime.now(timezone.utc),
                    expires_at=_expires,
                ))
                _db.commit()
            _after_db = time.perf_counter()
            print(
                f"[FLOW_TIMING] prefetch_task: db_persist_ok prefetch_id={prefetch_id} "
                f"db_ms={int((_after_db - _after_pipe) * 1000)}"
            )
        except Exception as db_exc:
            _log.warning("Prefetch DB persist failed: %s", db_exc)

        # ── Knowledge graph reification (fire-and-forget) ─────────────
        try:
            from .knowledge_reify import reify_prefetch_output
            from .database import SessionLocal as _ReifySL
            with _ReifySL() as _reify_db:
                _reify_count = await reify_prefetch_output(
                    prefetch_output=output.model_dump(mode="json"),
                    user_id=user_id,
                    prefetch_id=prefetch_id,
                    db=_reify_db,
                )
                print(f"[FLOW_TIMING] prefetch_task: reify_ok prefetch_id={prefetch_id} items={_reify_count}")
        except Exception as reify_exc:
            _log.warning("Knowledge reification failed (non-blocking): %s", reify_exc)

    except Exception as exc:
        _log.error("Prefetch pipeline task failed: %s", exc, exc_info=True)
    finally:
        print(
            f"[FLOW_TIMING] prefetch_task: exit prefetch_id={prefetch_id} "
            f"total_wall_ms={int((time.perf_counter() - _wall0) * 1000)}"
        )

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def should_auto_save(current_user: User) -> bool:
    """Check if auto-save is enabled for the user"""
    settings = current_user.settings or {}
    return settings.get('auto_save', True)  # Default to True if not set


def build_actions_prompt(report: Report, actions: List[Dict[str, Any]], additional_context: Optional[str]) -> str:
    action_lines = []
    for index, action in enumerate(actions, start=1):
        title = action.get("title") or f"Action {index}"
        details = action.get("details") or ""
        block = [f"{index}. {title}"]
        if details:
            block.append(f"   What to do and why: {details}")
        action_lines.append("\n".join(block))

    context_section = (
        f"Additional context:\n{additional_context.strip()}\n\n" if additional_context else ""
    )

    prompt = (
        "CRITICAL: You MUST use British English spelling and terminology throughout all output.\n\n"
        "You are applying edits to an existing radiology report. Each action below describes an intent—what should change and why.\n"
        "Integrate each change naturally into the report so it reads as a coherent, contextually appropriate revision.\n\n"
        "EDITING PRINCIPLES:\n"
        "1. Understand the intent of each action (title + details) and implement it holistically\n"
        "2. Integrate changes so they flow naturally with surrounding text and clinical context\n"
        "3. Preserve ALL other content exactly as it appears in the original report\n"
        "4. Maintain the exact formatting, spacing, line breaks, and structure of unchanged sections\n"
        "5. Do NOT add separators, decorative lines, or markdown formatting (no '---', '====', '**' for section headers, etc.)\n"
        "6. Do NOT rewrite or rephrase content unless the action explicitly requests it\n"
        "7. Make targeted edits that satisfy the intent—adjust wording as needed for natural integration\n\n"
        f"{context_section}"
        "Original report:\n"
        "---------------------\n"
        f"{report.report_content}\n"
        "---------------------\n\n"
        "Actions to apply:\n"
        "---------------------\n"
        f"{chr(10).join(action_lines)}\n"
        "---------------------\n\n"
        "TASK: Apply each action's intent in a way that integrates naturally with the report. Keep all other content identical.\n"
        "Return the complete revised report. No separators, no markdown, just the report text."
    )
    return prompt


async def regenerate_report_with_actions(
    report: Report,
    actions: List[Dict[str, Any]],
    additional_context: Optional[str],
    current_user: User
) -> str:
    """
    Apply enhancement actions to a report using Pydantic AI.
    Uses configured primary model (Cerebras GPT-OSS-120B) with Qwen fallback.
    """
    if not actions:
        raise ValueError("No actions provided to apply.")

    # Build the prompt for applying actions
    user_prompt = build_actions_prompt(report, actions, additional_context)
    settings = current_user.settings or {}
    
    # Import enhancement utilities for model configuration
    from .enhancement_utils import (
        MODEL_CONFIG,
        _get_model_provider,
        _get_api_key_for_provider,
        _run_agent_with_model,
        _is_parsing_error,
    )
    from .enhancement_utils import with_retry
    
    system_prompt = (
        "CRITICAL: You MUST use British English spelling and terminology throughout all output.\n\n"
        "You are applying edits to a radiology report. Each action specifies an intent (what to change and why).\n\n"
        "EDITING STRATEGY:\n"
        "1. Read each action's title and details to understand the intent\n"
        "2. Locate the relevant section(s) in the report\n"
        "3. Implement the change in a way that integrates naturally with the surrounding text\n"
        "4. Preserve grammatical completeness and clinical coherence\n\n"
        "CRITICAL PRINCIPLES:\n"
        "1. Satisfy the intent of each action—integrate changes so they read naturally\n"
        "2. If removing text leaves a sentence incomplete, restructure grammatically\n"
        "3. If adding or modifying text, ensure it flows with the report's style and context\n"
        "4. Preserve formatting, spacing, and structure of unchanged sections\n"
        "5. Verify every sentence is grammatically complete after edits\n"
        "6. Do NOT add separators, markdown formatting, or decorative elements\n"
        "7. Do NOT rewrite sections not mentioned in the actions\n"
        "8. The report is the radiologist's own voice — it does NOT cite sources, name societies "
        "(NICE, ACR, Fleischner, RCR, etc.), include guideline numbers (e.g. NG147, 1.3.10), "
        "or use 'per X' / 'as per X' attribution phrases. When an action's details contain a "
        "quoted insertion string or prescribed text that includes any of those, STRIP the "
        "attribution from the text before integrating it. The substance stays (e.g. the clinical "
        "recommendation itself), the attribution does not. This rule overrides literal-quote "
        "fidelity to the details field — the details describe intent, the report body is your "
        "composition.\n\n"
        "Return ONLY the complete revised report text. No commentary, no thinking blocks, no tags—just the report."
    )
    
    # Get primary model and provider
    primary_model = MODEL_CONFIG["ACTION_APPLIER"]
    primary_provider = _get_model_provider(primary_model)
    
    # Try primary model first with retry logic
    try:
        primary_api_key = _get_api_key_for_provider(primary_provider)
        
        @with_retry(max_retries=3, base_delay=2.0)
        async def _try_primary():
            # Build model settings with conditional reasoning_effort for Cerebras
            model_settings = {
                "temperature": 0.3,
            }
            if primary_model == "gpt-oss-120b":
                model_settings["max_completion_tokens"] = 4096  # Generous token limit for Cerebras
                model_settings["reasoning_effort"] = "medium"
                print(f"regenerate_report_with_actions: Using Cerebras reasoning_effort=medium, max_completion_tokens=4096 for {primary_model}")
            else:
                model_settings["max_tokens"] = 4096
            
            result = await _run_agent_with_model(
                model_name=primary_model,
                output_type=str,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=primary_api_key,
                use_thinking=(primary_provider == 'groq'),  # Enable thinking for Groq models
                model_settings=model_settings
            )
            
            new_content = str(result.output).strip()
            
            # Clean up thinking tags if present (for Groq models)
            if new_content and primary_provider == 'groq':
                new_content = re.sub(
                    r'<think>.*?</think>',
                    '',
                    new_content,
                    flags=re.DOTALL | re.IGNORECASE
                ).strip()
            
            if not new_content:
                raise ValueError(f"{primary_model} returned an empty response when applying actions.")
            
            return new_content
        
        return await _try_primary()
        
    except Exception as e:
        # Primary failed - determine why and fallback
        fallback_model = MODEL_CONFIG["ACTION_APPLIER_FALLBACK"]
        fallback_provider = _get_model_provider(fallback_model)
        
        if _is_parsing_error(e):
            print(f"⚠️ {primary_model} parsing error detected - immediate fallback to {fallback_model}")
            print(f"  Error: {type(e).__name__}: {str(e)[:200]}")
        else:
            print(f"⚠️ {primary_model} failed after retries ({type(e).__name__}) - falling back to {fallback_model}")
            print(f"  Error: {str(e)[:200]}")
        
        # Fallback to configured fallback model
        try:
            fallback_api_key = _get_api_key_for_provider(fallback_provider)
            
            # Build model settings for fallback
            fallback_model_settings = {
                "temperature": 0.3,
                "max_tokens": 4096,
            }
            
            result = await _run_agent_with_model(
                model_name=fallback_model,
                output_type=str,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=fallback_api_key,
                use_thinking=(fallback_provider == 'groq'),  # Enable thinking for Groq fallback
                model_settings=fallback_model_settings
            )
            
            new_content = str(result.output).strip()
            
            # Clean up thinking tags if present (for Groq models)
            if new_content and fallback_provider == 'groq':
                new_content = re.sub(
                    r'<think>.*?</think>',
                    '',
                    new_content,
                    flags=re.DOTALL | re.IGNORECASE
                ).strip()
            
            if not new_content:
                raise ValueError(f"{fallback_model} returned an empty response when applying actions.")
            
            print(f"regenerate_report_with_actions: ✅ Completed with {fallback_model} (fallback)")
            return new_content
            
        except Exception as fallback_error:
            # Both models failed - raise error
            import traceback
            print(f"❌ Both primary ({primary_model}) and fallback ({fallback_model}) models failed")
            print(traceback.format_exc())
            raise ValueError(f"Failed to apply actions using both {primary_model} and {fallback_model}: {str(fallback_error)}")


# ============================================================================
# AUTH PYDANTIC MODELS
# ============================================================================

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    full_name: Optional[str] = None
    role: Literal[
        "consultant_radiologist",
        "registrar",
        "reporting_radiographer",
        "medical_student",
        "other_healthcare_professional",
        "other",
    ]
    institution: Optional[str] = Field(default=None, max_length=200)
    signup_reason: str = Field(min_length=10, max_length=1000)

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class VerifyEmailRequest(BaseModel):
    token: str

# ============================================================================
# API PYDANTIC MODELS
# ============================================================================

class MessageRequest(BaseModel):
    message: str
    model: str = "claude"  # Always uses Claude (kept for API compatibility, fallback handled automatically)
    use_case: Optional[str] = None  # Use case for prompt templates
    variables: Optional[Dict[str, str]] = Field(default_factory=dict)  # Variables for prompt templates


# Pydantic models for Template API
class TemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    template_config: Optional[Dict] = None
    is_pinned: Optional[bool] = False


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    template_config: Optional[Dict] = None
    is_active: Optional[bool] = None


class TemplateGenerateRequest(BaseModel):
    user_inputs: Dict[str, str]  # New format: user_inputs dict
    # Legacy format (deprecated)
    variables: Optional[Dict[str, str]] = None
    model: str = "zai-glm-4.7"  # Uses zai-glm-4.7 as primary


# Wizard assistance request models
class GenerateFindingsContentRequest(BaseModel):
    scan_type: str
    contrast: str
    protocol_details: Optional[str] = None
    content_style: str  # "guided_template", "checklist", "headers", "normal_template", or "structured_template"
    instructions: Optional[str] = None


class ExtractPlaceholdersRequest(BaseModel):
    template_content: str


class ValidateTemplateRequest(BaseModel):
    template_content: str


class SuggestPlaceholderFillRequest(BaseModel):
    placeholder_type: str  # 'measurement', 'variable', 'alternative', 'instruction'
    placeholder_text: str  # 'xxx', '~LV_EF~', 'Normal/increased'
    surrounding_context: str  # Text around the placeholder
    report_content: str  # Full report for context


class SuggestInstructionsRequest(BaseModel):
    section: str  # "FINDINGS" or "IMPRESSION"
    scan_type: str
    content_style: Optional[str] = None


class AnalyzeReportsRequest(BaseModel):
    scan_type: str
    contrast: str
    protocol_details: Optional[str] = None
    reports: List[Dict[str, str]]  # List of {type, context, content}


# Skill sheet request models
class SkillSheetExample(BaseModel):
    label: Optional[str] = None
    content: str

class SkillSheetAnalyzeRequest(BaseModel):
    scan_type: str
    examples: List[SkillSheetExample]  # 1-5 example reports
    protocol_notes: Optional[str] = ""

class SkillSheetGenerateTestCaseRequest(BaseModel):
    scan_type: str
    examples: List[SkillSheetExample]

class SkillSheetChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class SkillSheetRejectionContext(BaseModel):
    original_instruction: str
    rejected_claim: str

class SkillSheetRefineRequest(BaseModel):
    skill_sheet: str
    message: str
    chat_history: Optional[List[SkillSheetChatMessage]] = None
    rejection_context: Optional[SkillSheetRejectionContext] = None

class SkillSheetTestGenerateRequest(BaseModel):
    skill_sheet: str
    scan_type: str
    clinical_history: str
    findings_input: str

class SkillSheetDiversityCheckRequest(BaseModel):
    scan_type: str
    examples: List[SkillSheetExample]


class SkillSheetSaveRequest(BaseModel):
    skill_sheet: str
    scan_type: str
    template_name: str
    tags: List[str] = []


# Quick Report Proto — ephemeral skill sheet pipeline
class QuickReportProtoAnalyseRequest(BaseModel):
    scan_type: str
    clinical_history: str


class QuickReportProtoGenerateRequest(BaseModel):
    skill_sheet: str
    scan_type: str
    clinical_history: str
    findings: str
    run_id: Optional[str] = None   # links analyse+generate in the proto log
    model: Optional[str] = None    # optional model override for A/B testing
    sheet_id: Optional[str] = None # persisted ephemeral_skill_sheets.id from /analyse — links the report row to the sheet


# Feedback request models
class FeedbackCaptureRequest(BaseModel):
    report_id: Optional[str] = None
    template_id: str
    ai_output: str
    final_output: Optional[str] = None
    lifecycle: str = "generated"
    copy_count: int = 0
    rating: Optional[str] = None
    time_to_first_edit_ms: Optional[int] = None
    time_to_copy_ms: Optional[int] = None
    edit_distance: Optional[int] = None
    sections_modified: Optional[List[str]] = None


class FeedbackRatingRequest(BaseModel):
    feedback_id: str
    rating: str


# Audit / QA request models
class AuditRequest(BaseModel):
    report_content: str
    scan_type: Optional[str] = ""
    clinical_history: Optional[str] = ""
    report_id: Optional[str] = None
    applicable_guidelines: Optional[List[dict]] = None
    # For dual-candidate quick reports: which candidate draft this re-audit
    # targets. The persisted ReportAudit row is tagged with this so it lands
    # in the per-candidate slot in the audit store (keyed by model). NULL
    # for legacy single-candidate reports.
    audited_candidate_model: Optional[str] = None


class AcknowledgeRequest(BaseModel):
    resolution_method: Literal["manual", "ai_assisted", "dismissed"]


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "message": "Rapid Reports AI API is running"}


@app.get("/api/use-cases")
async def list_use_cases(model: str = None):
    """Get list of available prompt use cases, optionally filtered by model"""
    try:
        pm = get_prompt_manager()
        use_cases_list = pm.get_available_use_cases(model)
        use_cases = []
        for uc in use_cases_list:
            try:
                # Try to get description with model if provided
                if model:
                    details = pm.get_prompt_details(uc, model)
                    description = details.get('description', uc)
                else:
                    description = pm.get_use_case_description(uc)
                
                use_cases.append({
                    "name": uc,
                    "description": description
                })
            except Exception:
                # If we can't get description, just use the use case name
                use_cases.append({
                    "name": uc,
                    "description": uc
                })
        return {"success": True, "use_cases": use_cases}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/prompt-details/{use_case}")
async def get_prompt_details(use_case: str, model: str = "default"):
    """Get detailed information about a specific prompt including its variables"""
    try:
        pm = get_prompt_manager()
        details = pm.get_prompt_details(use_case, model)
        return {"success": True, "details": details}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/chat")
async def chat(
    request: MessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Endpoint to send a message to different AI models using Pydantic AI
    """
    try:
        # Refresh user object to ensure we have latest signature from database
        db.refresh(current_user)
        # Load and render prompt if use_case is provided
        user_prompt = request.message
        system_prompt = "You are an expert radiologist. Generate professional radiology reports."
        use_case_name = None
        
        if request.use_case:
            try:
                pm = get_prompt_manager()
                # Get primary model from MODEL_CONFIG for auto template selection
                from .enhancement_utils import MODEL_CONFIG
                primary_model = MODEL_CONFIG.get("PRIMARY_REPORT_GENERATOR")
                # Use "default" to load prompt, but pass primary_model to check for gptoss.json
                prompt_data = pm.load_prompt(request.use_case, "default", primary_model=primary_model)
                
                # Get the variables needed for this prompt
                variables = dict(request.variables) if request.variables else {}
                
                # Extract system prompt (persistent requirements) and user template (task-specific)
                system_prompt_from_data = prompt_data.get('system_prompt', None)
                user_template = prompt_data.get('template', '')
                
                # Use system_prompt from data if available, otherwise fallback to default
                if system_prompt_from_data:
                    system_prompt = system_prompt_from_data
                elif user_template:
                    # Fallback: extract first line from template if no system_prompt field
                    first_line = user_template.split('\n')[0].strip()
                    if first_line:
                        system_prompt = first_line
                
                # Render user prompt from template with variables
                if variables and user_template:
                    # Create temporary dict with template for rendering
                    temp_prompt_data = {'template': user_template}
                    user_prompt = pm.render_prompt(temp_prompt_data, variables)
                else:
                    # Fallback: if no variables provided but prompt expects them, use message as single variable
                    user_prompt = request.message
                
                use_case_name = request.use_case
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to load prompt for use case '{request.use_case}': {str(e)}"
                }
        
        # Primary model: zai-glm-4.7 (Cerebras), fallback: claude-sonnet-4-6 (Anthropic)
        # Require at least one key (primary or fallback)
        from .enhancement_utils import MODEL_CONFIG, _get_model_provider
        primary_model = MODEL_CONFIG["PRIMARY_REPORT_GENERATOR"]
        primary_provider = _get_model_provider(primary_model)
        provider_env = {"cerebras": "CEREBRAS_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "groq": "GROQ_API_KEY"}
        has_primary = bool(os.getenv(provider_env.get(primary_provider, "CEREBRAS_API_KEY")))
        has_fallback = bool(os.getenv("ANTHROPIC_API_KEY"))
        if not has_primary and not has_fallback:
            return {
                "success": False,
                "error": "No API keys configured. Please set CEREBRAS_API_KEY (primary) or ANTHROPIC_API_KEY (fallback) environment variable."
            }
        anthropic_api_key = get_system_api_key('anthropic', 'ANTHROPIC_API_KEY')
        
        # Generate report with primary model, fallback to Claude if primary fails
        # Debug: Log signature status
        signature_value = current_user.signature
        print(f"[DEBUG] Auto report - signature present: {signature_value is not None and signature_value.strip() != ''}")
        print(f"[DEBUG] Auto report - signature length: {len(signature_value) if signature_value else 0}")
        
        clinical_history = (request.variables or {}).get("CLINICAL_HISTORY", "")

        # ── Fire prefetch pipeline in parallel with report generation ─────────
        _chat_gen_t0 = time.perf_counter()
        _findings_text = (request.variables or {}).get("FINDINGS", "").strip()
        if _findings_text and request.use_case:
            _prefetch_id = str(uuid.uuid4())
            _findings_hash = hashlib.sha256(
                f"{str(current_user.id)}:{_findings_text}".encode()
            ).hexdigest()[:16]
            PREFETCH_INDEX[_findings_hash] = _prefetch_id
            _scan_type_hint = (request.variables or {}).get("SCAN_TYPE", "")
            print(
                f"[FLOW_TIMING] chat: prefetch_scheduled prefetch_id={_prefetch_id} "
                f"findings_hash={_findings_hash} findings_len={len(_findings_text)}"
            )
            _schedule_prefetch_task(
                prefetch_id=_prefetch_id,
                findings_hash=_findings_hash,
                findings=_findings_text,
                scan_type=_scan_type_hint,
                clinical_history=clinical_history,
                user_id=str(current_user.id),
            )
        # ─────────────────────────────────────────────────────────────────────

        report_output = await generate_auto_report(
            model="claude",  # Model param kept for API compatibility; actual model from MODEL_CONFIG
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            api_key=anthropic_api_key,
            signature=signature_value,
            clinical_history=clinical_history
        )
        print(
            f"[FLOW_TIMING] chat: generate_auto_report_done "
            f"wall_since_chat_start_ms={int((time.perf_counter() - _chat_gen_t0) * 1000)} "
            f"report_chars={len(report_output.report_content or '')}"
        )
        
        # STRUCTURE VALIDATION (synchronous, before saving)
        # DISABLED: Validation checks temporarily disabled - code preserved below
        ENABLE_STRUCTURE_VALIDATION = os.getenv("ENABLE_STRUCTURE_VALIDATION", "true").lower() == "true"
        
        # if ENABLE_STRUCTURE_VALIDATION:  # DISABLED
        if False:  # Validation disabled - uncomment above line to re-enable
            from .enhancement_utils import validate_report_structure
            
            findings = request.variables.get('FINDINGS', '') if request.variables else ''
            
            print(f"\n{'='*80}")
            print(f"🔍 STRUCTURE VALIDATION - Starting")
            print(f"{'='*80}")
            print(f"[DEBUG] Scan type: {report_output.scan_type or '(none)'}")
            print(f"[DEBUG] Findings length: {len(findings)} chars")
            print(f"[DEBUG] Report content length: {len(report_output.report_content)} chars")
            
            try:
                print(f"[DEBUG] Step 1/3: Calling validate_report_structure()...")
                validation_result = await validate_report_structure(
                    report_content=report_output.report_content,
                    scan_type=report_output.scan_type or "",
                    findings=findings
                )
                print(f"[DEBUG] Step 1/3: ✅ Validation complete")
                print(f"[DEBUG]   - is_valid: {validation_result.is_valid}")
                print(f"[DEBUG]   - violations count: {len(validation_result.violations)}")
                
                if not validation_result.is_valid and len(validation_result.violations) > 0:
                    print(f"\n[DEBUG] Step 2/3: Preparing to apply fixes...")
                    print(f"[DEBUG]   - Found {len(validation_result.violations)} violation(s)")
                    
                    # Build simplified prompt directly from violations
                    violations_text = "\n\n".join([
                        f"Violation {i+1}:\n"
                        f"Location: {v.location}\n"
                        f"Issue: {v.issue}\n"
                        f"Fix: {v.fix}"
                        for i, v in enumerate(validation_result.violations)
                    ])
                    
                    user_prompt = f"""Apply these fixes to the radiology report:

{violations_text}

Original report:
{report_output.report_content}

Apply each fix while preserving grammatical completeness and report structure."""
                    
                    # Import enhancement utilities for model configuration
                    from .enhancement_utils import (
                        MODEL_CONFIG,
                        _get_model_provider,
                        _get_api_key_for_provider,
                        _run_agent_with_model,
                        _is_parsing_error,
                    )
                    from .enhancement_utils import with_retry
                    
                    system_prompt = (
                        "CRITICAL: You MUST use British English spelling and terminology throughout all output.\n\n"
                        "You are applying edits to a radiology report. Each violation specifies a problem and how to fix it.\n\n"
                        "EDITING STRATEGY:\n"
                        "1. Read each violation's 'issue' to understand WHAT is wrong\n"
                        "2. Read each violation's 'fix' to understand HOW to fix it\n"
                        "3. Locate the exact text/location mentioned in the fix instruction\n"
                        "4. Apply the fix while preserving grammatical completeness\n\n"
                        "CRITICAL PRINCIPLES:\n"
                        "1. Apply fixes EXACTLY as specified in the 'fix' field\n"
                        "2. If removing text leaves a sentence incomplete, restructure the sentence grammatically\n"
                        "3. If moving text, ensure it flows naturally in the new location\n"
                        "4. If restructuring, maintain all information but integrate it cohesively\n"
                        "5. Preserve formatting, spacing, and structure of unchanged sections\n"
                        "6. Verify every sentence is grammatically complete after edits\n"
                        "7. Do NOT add separators, markdown formatting, or decorative elements\n"
                        "8. Do NOT rewrite sections not mentioned in the violations\n\n"
                        "Return ONLY the complete revised report text. No commentary, no thinking blocks, no tags—just the report."
                    )
                    
                    # Get model and provider
                    primary_model = MODEL_CONFIG["ACTION_APPLIER"]
                    primary_provider = _get_model_provider(primary_model)
                    primary_api_key = _get_api_key_for_provider(primary_provider)
                    
                    print(f"[DEBUG] Step 3/3: Executing fixes...")
                    print(f"[DEBUG]   - Using model: {primary_model}")
                    
                    @with_retry(max_retries=3, base_delay=2.0)
                    async def _apply_fixes():
                        model_settings = {
                            "temperature": 0.3,
                        }
                        if primary_model == "gpt-oss-120b":
                            model_settings["max_completion_tokens"] = 4096
                            model_settings["reasoning_effort"] = "medium"
                        else:
                            model_settings["max_tokens"] = 4096
                        
                        result = await _run_agent_with_model(
                            model_name=primary_model,
                            output_type=str,
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            api_key=primary_api_key,
                            use_thinking=(primary_provider == 'groq'),
                            model_settings=model_settings
                        )
                        
                        refined_content = str(result.output).strip()
                        
                        # Clean up thinking tags if present (for Groq models)
                        if refined_content and primary_provider == 'groq':
                            import re
                            refined_content = re.sub(
                                r'<think>.*?</think>',
                                '',
                                refined_content,
                                flags=re.DOTALL | re.IGNORECASE
                            ).strip()
                        
                        if not refined_content:
                            raise ValueError(f"{primary_model} returned an empty response when applying fixes.")
                        
                        return refined_content
                    
                    refined_content = await _apply_fixes()
                    
                    original_length = len(report_output.report_content)
                    refined_length = len(refined_content)
                    print(f"[DEBUG] Step 3/3: ✅ Fix execution complete")
                    print(f"[DEBUG]   - Original report length: {original_length} chars")
                    print(f"[DEBUG]   - Refined report length: {refined_length} chars")
                    print(f"[DEBUG]   - Length change: {refined_length - original_length:+d} chars")
                    
                    report_output.report_content = refined_content
                    print(f"\n✅ STRUCTURE VALIDATION COMPLETE - Fixes applied successfully")
                    print(f"{'='*80}\n")
                else:
                    print(f"[DEBUG] No fixes needed - report passes validation")
                    print(f"\n✅ STRUCTURE VALIDATION COMPLETE - No violations found")
                    print(f"{'='*80}\n")
            except Exception as e:
                print(f"\n{'='*80}")
                print(f"⚠️ STRUCTURE VALIDATION FAILED")
                print(f"{'='*80}")
                print(f"[ERROR] Exception type: {type(e).__name__}")
                print(f"[ERROR] Error message: {str(e)[:500]}")
                import traceback
                print(f"[ERROR] Full traceback:")
                print(traceback.format_exc())
                # Continue with original report if validation fails
                print(f"[DEBUG] Continuing with original report (validation skipped)")
                print(f"{'='*80}\n")
        else:
            print(f"[DEBUG] Structure validation disabled (ENABLE_STRUCTURE_VALIDATION=false)")
        
        # Build context title: scan type + description
        context_title = None
        if report_output.scan_type:
            if report_output.description:
                context_title = f"{report_output.scan_type} - {report_output.description}"
            else:
                context_title = report_output.scan_type
        else:
            context_title = report_output.description
        
        # Save report to database (only if auto-save is enabled)
        report_id = None
        if should_auto_save(current_user):
            try:
                model_to_store = report_output.model_used or "zai-glm-4.7"
                saved_report = create_report(
                    db=db,
                    user_id=str(current_user.id),
                    report_type="auto",
                    report_content=report_output.report_content,
                    model_used=model_to_store,
                    input_data={
                        "message": request.message,
                        "variables": request.variables,
                        "extracted_scan_type": report_output.scan_type
                    },
                    use_case=use_case_name,
                    description=context_title
                )
                report_id = str(saved_report.id)
                print(f"✅ Report saved")
            except Exception as e:
                print(f"Failed to save report: {e}")
        else:
            print("Auto-save is disabled, skipping report save")
        
        # Map model names to full model identifiers for response
        model_full_name = {
            "claude": "claude-sonnet-4-6",
            "gemini": "gemini-2.5-pro",
            "qwen": "qwen/qwen3-32b"
        }.get(request.model, request.model)
        
        return {
            "success": True,
            "report_id": report_id,
            "response": report_output.report_content,
            "model": model_full_name,
            "use_case": use_case_name,
            "scan_type": report_output.scan_type,
            "applicable_guidelines": [],  # Populated from enhance response (prefetch pipeline)
        }

    except Exception as e:
        import traceback
        print(f"Error in chat endpoint: {e}")
        print(traceback.format_exc())
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# AUTH API ENDPOINTS
# ============================================================================

@app.post("/api/auth/register")
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user. Creates an unapproved account, emails the user for
    verification, and emails the admin for approval."""
    try:
        existing_user = get_user_by_email(db, request.email)
        if existing_user:
            return {"success": False, "error": "Email already registered"}

        password_hash = get_password_hash(request.password)
        user = create_user(
            db=db,
            email=request.email,
            password_hash=password_hash,
            full_name=request.full_name,
            role=request.role,
            institution=request.institution,
            signup_reason=request.signup_reason,
        )

        # Email verification token (user flow — unchanged)
        verification_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        create_reset_token(
            db=db,
            user_id=str(user.id),
            token=verification_token,
            expires_at=expires_at,
            token_type="email_verification",
        )
        send_magic_link_email(request.email, verification_token, "email_verification")

        # Admin notification — best-effort; failure must not block registration.
        try:
            send_admin_signup_notification(user)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[register] admin notification failed: {exc}")

        return {
            "success": True,
            "message": (
                "Thanks — your account is pending admin approval. "
                "You'll receive an email once approved. "
                "We've also sent a verification email so you can confirm your address in the meantime."
            ),
            "user_id": str(user.id),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/auth/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """Login with email and password"""
    try:
        user = get_user_by_email(db, form_data.username)  # OAuth2 uses 'username' field
        
        if not user or not verify_password(form_data.password, user.password_hash):
            return {
                "success": False,
                "error": "Incorrect email or password"
            }
        
        if not user.is_active:
            return {"success": False, "error": "Account is inactive"}
        
        # Check if email is verified
        if not user.is_verified:
            return {
                "success": False,
                "error": "Please verify your email address before logging in. Check your inbox for the verification link."
            }
        
        # Update last login
        update_last_login(db, str(user.id))
        
        # Create JWT token
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user.id)}, expires_delta=access_token_expires
        )
        
        return {
            "success": True,
            "access_token": access_token,
            "token_type": "bearer",
            "user": user.to_dict()
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current authenticated user"""
    return {"success": True, "user": current_user.to_dict()}


@app.post("/api/auth/forgot-password")
async def forgot_password(request: dict, db: Session = Depends(get_db)):
    """Request password reset via email"""
    try:
        email = request.get("email")
        if not email:
            return {"success": False, "error": "Email is required"}
        
        user = get_user_by_email(db, email)
        
        if not user:
            # Don't reveal if user exists (security best practice)
            return {"success": True, "message": "If account exists, reset email sent. Please check your email (including spam/junk folder)."}
        
        # Generate reset token
        reset_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        
        create_reset_token(
            db=db,
            user_id=str(user.id),
            token=reset_token,
            expires_at=expires_at,
            token_type="password_reset",
        )
        
        # Send reset email (or print to console in dev)
        send_magic_link_email(email, reset_token, "password_reset")
        
        return {"success": True, "message": "If account exists, reset link sent. Please check your email (including spam/junk folder)."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/auth/reset-password")
async def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset password using token"""
    try:
        # Get valid token
        reset_record = get_valid_reset_token(db, request.token)
        
        if not reset_record or reset_record.token_type != "password_reset":
            return {"success": False, "error": "Invalid or expired reset token"}
        
        # Update user password
        user = reset_record.user
        user.password_hash = get_password_hash(request.new_password)
        
        # Mark token as used
        mark_token_used(db, request.token)
        
        db.commit()
        
        return {"success": True, "message": "Password reset successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/auth/verify-email")
async def verify_email(request: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Verify email with magic link token"""
    try:
        # Get valid token
        verification_record = get_valid_reset_token(db, request.token)
        
        if not verification_record or verification_record.token_type != "email_verification":
            return {"success": False, "error": "Invalid or expired verification token"}
        
        # Mark user as verified
        user = verification_record.user
        user.is_verified = True
        
        # Mark token as used
        mark_token_used(db, request.token)
        
        db.commit()
        
        return {"success": True, "message": "Email verified successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/auth/resend-verification")
async def resend_verification(request: dict, db: Session = Depends(get_db)):
    """Resend email verification link"""
    try:
        email = request.get("email")
        if not email:
            return {"success": False, "error": "Email is required"}
        
        user = get_user_by_email(db, email)
        
        if not user:
            # Don't reveal if user exists (security best practice)
            return {"success": True, "message": "If account exists, verification email sent. Please check your inbox (including spam/junk folder)."}
        
        if user.is_verified:
            return {"success": False, "error": "Email already verified"}
        
        # Generate new verification token
        verification_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        
        create_reset_token(
            db=db,
            user_id=str(user.id),
            token=verification_token,
            expires_at=expires_at,
            token_type="email_verification",
        )
        
        # Send verification email
        send_magic_link_email(email, verification_token, "email_verification")
        
        return {"success": True, "message": "Verification email sent. Please check your inbox (including spam/junk folder)."}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# TEMPLATE API ENDPOINTS
# ============================================================================

@app.get("/api/templates")
async def list_templates(
    skip: int = 0,
    limit: int = 100,
    tags: Optional[List[str]] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of all templates for current user, optionally filtered by tags"""
    try:
        # Handle tags as comma-separated string or list
        tag_list = None
        if tags:
            if isinstance(tags, str):
                tag_list = [t.strip() for t in tags.split(',') if t.strip()]
            elif isinstance(tags, list):
                tag_list = tags
        
        templates = get_templates(db, user_id=str(current_user.id), skip=skip, limit=limit, tags=tag_list)
        
        # DEBUG: Log backend template data
        print(f"[DEBUG BACKEND] Retrieved {len(templates)} templates from database")
        if templates:
            sample = templates[0]
            print(f"[DEBUG BACKEND] Sample template from DB:", {
                'name': sample.name,
                'usage_count': sample.usage_count,
                'usage_count_type': type(sample.usage_count).__name__,
                'last_used_at': sample.last_used_at,
                'last_used_at_type': type(sample.last_used_at).__name__ if sample.last_used_at else None
            })
        
        # Safely convert templates to dict, handling any serialization errors
        template_dicts = []
        for template in templates:
            try:
                template_dict = template.to_dict()
                
                # DEBUG: Log each template's serialized data
                print(f"[DEBUG BACKEND] Template '{template_dict.get('name')}' to_dict():", {
                    'usage_count': template_dict.get('usage_count'),
                    'usage_count_type': type(template_dict.get('usage_count')).__name__,
                    'last_used_at': template_dict.get('last_used_at'),
                    'last_used_at_type': type(template_dict.get('last_used_at')).__name__ if template_dict.get('last_used_at') else None
                })
                
                # Ensure tags is always a list
                if 'tags' not in template_dict or template_dict['tags'] is None:
                    template_dict['tags'] = []
                elif not isinstance(template_dict['tags'], list):
                    template_dict['tags'] = []
                template_dicts.append(template_dict)
            except Exception as e:
                print(f"Error serializing template {template.id}: {e}")
                # Skip this template if it can't be serialized
                continue
        
        return {
            "success": True,
            "templates": template_dicts
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.get("/api/templates/tags")
async def get_template_tags(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all unique tags across all templates for current user"""
    try:
        from rapid_reports_ai.database.crud import get_all_tags
        tags = get_all_tags(db, user_id=str(current_user.id))
        return {
            "success": True,
            "tags": tags
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


class RenameTagRequest(BaseModel):
    old_tag: str
    new_tag: str


@app.post("/api/templates/tags/rename")
async def rename_template_tag(
    request: RenameTagRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Rename a tag across all templates for current user"""
    try:
        if not request.old_tag or not request.new_tag:
            return {"success": False, "error": "Both old_tag and new_tag are required"}
        
        if request.old_tag.lower() == request.new_tag.lower():
            return {"success": False, "error": "Old and new tag names cannot be the same"}
        
        success = rename_tag(
            db=db,
            user_id=str(current_user.id),
            old_tag=request.old_tag,
            new_tag=request.new_tag
        )
        
        if success:
            return {"success": True, "message": f"Tag '{request.old_tag}' renamed to '{request.new_tag}'"}
        else:
            return {"success": False, "error": "Tag not found or no templates to update"}
    except Exception as e:
        return {"success": False, "error": str(e)}


class DeleteTagRequest(BaseModel):
    tag: str




@app.post("/api/templates/tags/delete")
async def delete_template_tag(
    request: DeleteTagRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a tag from all templates for current user"""
    try:
        if not request.tag:
            return {"success": False, "error": "Tag is required"}
        
        success = delete_tag(
            db=db,
            user_id=str(current_user.id),
            tag_to_delete=request.tag
        )
        
        if success:
            return {"success": True, "message": f"Tag '{request.tag}' deleted from all templates"}
        else:
            return {"success": False, "error": "Tag not found or no templates to update"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/templates/{template_id}")
async def get_template_detail(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get details of a specific template for current user"""
    try:
        template = get_template(db, template_id, user_id=str(current_user.id))
        if not template:
            return {"success": False, "error": "Template not found"}
        
        return {"success": True, "template": template.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _normalize_template_config_styles(config: dict) -> dict:
    """Normalize style_templates to match template_content for template_based FINDINGS sections."""
    if not config or not isinstance(config, dict):
        return config
    config = copy.deepcopy(config)
    sections = config.get("sections")
    if not isinstance(sections, list):
        return config
    for section in sections:
        if not isinstance(section, dict):
            continue
        if section.get("generation_mode") != "template_based":
            continue
        content_style = section.get("content_style")
        if not content_style:
            continue
        template_content = section.get("template_content", "")
        style_templates = section.get("style_templates")
        if style_templates is None:
            style_templates = {}
        if not isinstance(style_templates, dict):
            style_templates = {}
        style_templates = dict(style_templates)
        style_templates[content_style] = template_content
        section["style_templates"] = style_templates
    return config


@app.post("/api/templates")
async def create_template_endpoint(
    template_data: TemplateCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new template for current user"""
    try:
        if not template_data.template_config:
            return {"success": False, "error": "template_config is required"}
        normalized_config = _normalize_template_config_styles(template_data.template_config)
        template = create_template(
            db=db,
            name=template_data.name,
            description=template_data.description,
            tags=template_data.tags,
            template_config=normalized_config,
            is_pinned=template_data.is_pinned or False,
            user_id=str(current_user.id),
        )
        
        return {"success": True, "template": template.to_dict()}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.put("/api/templates/{template_id}")
async def update_template_endpoint(
    template_id: str,
    template_data: TemplateUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing template for current user"""
    try:
        # Normalize style_templates before persisting
        template_config = template_data.template_config
        if template_config:
            template_config = _normalize_template_config_styles(template_config)
        updated_template = update_template(
            db=db,
            template_id=template_id,
            user_id=str(current_user.id),
            name=template_data.name,
            description=template_data.description,
            tags=template_data.tags,
            template_config=template_config,
            is_active=template_data.is_active,
        )
        
        if not updated_template:
            return {"success": False, "error": "Template not found"}
        
        return {"success": True, "template": updated_template.to_dict()}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.delete("/api/templates/{template_id}")
async def delete_template_endpoint(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a template (soft delete) for current user"""
    try:
        deleted = delete_template(db, template_id, user_id=str(current_user.id))
        if not deleted:
            return {"success": False, "error": "Template not found"}
        
        return {"success": True, "message": "Template deleted"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/templates/{template_id}/generate")
async def generate_report_from_template(
    template_id: str,
    request: TemplateGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate a report from a template using new structured config system"""
    try:
        # Get the template
        template = get_template(db, template_id, user_id=str(current_user.id))
        if not template:
            return {"success": False, "error": "Template not found"}
        
        # Initialize actual_user_inputs early to ensure it's always available for saving
        # Prefer user_inputs (new format) over variables (legacy format)
        actual_user_inputs = request.user_inputs if request.user_inputs is not None else (request.variables if request.variables is not None else {})
        print(f"[DEBUG] Received request - user_inputs: {request.user_inputs}, variables: {request.variables}")
        print(f"[DEBUG] Using actual_user_inputs: {actual_user_inputs}, type: {type(actual_user_inputs)}, keys: {list(actual_user_inputs.keys()) if isinstance(actual_user_inputs, dict) else 'not a dict'}")
        
        # Use new template_config system
        if not template.template_config:
            return {
                "success": False,
                "error": "Template configuration is missing. Please recreate this template using the new template editor."
            }
        
        tm = TemplateManager()
        user_inputs = actual_user_inputs
        _tpl_gen_t0 = time.perf_counter()
        # ── Prefetch in parallel with templated report LLM (same as /api/chat) ──
        _findings_text = (user_inputs.get("FINDINGS") or "").strip() if isinstance(user_inputs, dict) else ""
        if _findings_text:
            _prefetch_id = str(uuid.uuid4())
            _findings_hash = hashlib.sha256(
                f"{str(current_user.id)}:{_findings_text}".encode()
            ).hexdigest()[:16]
            PREFETCH_INDEX[_findings_hash] = _prefetch_id
            _scan_type_hint = (user_inputs.get("SCAN_TYPE") or "") if isinstance(user_inputs, dict) else ""
            _clinical = (user_inputs.get("CLINICAL_HISTORY") or "") if isinstance(user_inputs, dict) else ""
            print(
                f"[FLOW_TIMING] template_generate: prefetch_scheduled prefetch_id={_prefetch_id} "
                f"findings_hash={_findings_hash} findings_len={len(_findings_text)}"
            )
            _schedule_prefetch_task(
                prefetch_id=_prefetch_id,
                findings_hash=_findings_hash,
                findings=_findings_text,
                scan_type=_scan_type_hint,
                clinical_history=_clinical,
                user_id=str(current_user.id),
            )
        report_output_dict = await tm.generate_report_from_config(
            template_config=template.template_config,
            user_inputs=user_inputs,
            user_signature=current_user.signature
        )
        print(
            f"[FLOW_TIMING] template_generate: llm_done "
            f"wall_ms={int((time.perf_counter() - _tpl_gen_t0) * 1000)} "
            f"report_chars={len((report_output_dict.get('report_content') or ''))}"
        )
        
        # Convert to ReportOutput format for compatibility
        from .enhancement_models import ReportOutput
        report_output = ReportOutput(
            report_content=report_output_dict["report_content"],
            description=report_output_dict["description"],
            scan_type=report_output_dict["scan_type"],
        )
        
        # Optional: Add structure validation for templated reports
        # Controlled by ENABLE_TEMPLATE_STRUCTURE_VALIDATION env var
        ENABLE_TEMPLATE_STRUCTURE_VALIDATION = os.getenv("ENABLE_TEMPLATE_STRUCTURE_VALIDATION", "false").lower() == "true"
        
        if ENABLE_TEMPLATE_STRUCTURE_VALIDATION:
            from .enhancement_utils import validate_report_structure
            
            user_inputs = request.user_inputs or request.variables or {}
            findings = user_inputs.get('FINDINGS', '')
            
            print(f"\n{'='*80}")
            print(f"🔍 TEMPLATE STRUCTURE VALIDATION - Starting")
            print(f"{'='*80}")
            print(f"[DEBUG] Scan type: {report_output.scan_type or '(none)'}")
            print(f"[DEBUG] Findings length: {len(findings)} chars")
            print(f"[DEBUG] Report content length: {len(report_output.report_content)} chars")
            
            try:
                print(f"[DEBUG] Step 1/3: Calling validate_report_structure()...")
                validation_result = await validate_report_structure(
                    report_content=report_output.report_content,
                    scan_type=report_output.scan_type or "",
                    findings=findings
                )
                print(f"[DEBUG] Step 1/3: ✅ Validation complete")
                print(f"[DEBUG]   - is_valid: {validation_result.is_valid}")
                print(f"[DEBUG]   - violations count: {len(validation_result.violations)}")
                
                if not validation_result.is_valid and len(validation_result.violations) > 0:
                    print(f"\n[DEBUG] Step 2/3: Preparing to apply fixes...")
                    print(f"[DEBUG]   - Found {len(validation_result.violations)} violation(s)")
                    
                    # Build simplified prompt directly from violations
                    violations_text = "\n\n".join([
                        f"Violation {i+1}:\n"
                        f"Location: {v.location}\n"
                        f"Issue: {v.issue}\n"
                        f"Fix: {v.fix}"
                        for i, v in enumerate(validation_result.violations)
                    ])
                    
                    user_prompt = f"""Apply these fixes to the radiology report:

{violations_text}

Original report:
{report_output.report_content}

Apply each fix while preserving grammatical completeness and report structure."""
                    
                    # Import enhancement utilities for model configuration
                    from .enhancement_utils import (
                        MODEL_CONFIG,
                        _get_model_provider,
                        _get_api_key_for_provider,
                        _run_agent_with_model,
                        _is_parsing_error,
                    )
                    from .enhancement_utils import with_retry
                    
                    system_prompt = (
                        "CRITICAL: You MUST use British English spelling and terminology throughout all output.\n\n"
                        "You are applying edits to a radiology report. Each violation specifies a problem and how to fix it.\n\n"
                        "EDITING STRATEGY:\n"
                        "1. Read each violation's 'issue' to understand WHAT is wrong\n"
                        "2. Read each violation's 'fix' to understand HOW to fix it\n"
                        "3. Locate the exact text/location mentioned in the fix instruction\n"
                        "4. Apply the fix while preserving grammatical completeness\n\n"
                        "CRITICAL PRINCIPLES:\n"
                        "1. Apply fixes EXACTLY as specified in the 'fix' field\n"
                        "2. If removing text leaves a sentence incomplete, restructure the sentence grammatically\n"
                        "3. If moving text, ensure it flows naturally in the new location\n"
                        "4. If restructuring, maintain all information but integrate it cohesively\n"
                        "5. Preserve formatting, spacing, and structure of unchanged sections\n"
                        "6. Verify every sentence is grammatically complete after edits\n"
                        "7. Do NOT add separators, markdown formatting, or decorative elements\n"
                        "8. Do NOT rewrite sections not mentioned in the violations\n\n"
                        "Return ONLY the complete revised report text. No commentary, no thinking blocks, no tags—just the report."
                    )
                    
                    # Get model and provider
                    primary_model = MODEL_CONFIG["ACTION_APPLIER"]
                    primary_provider = _get_model_provider(primary_model)
                    primary_api_key = _get_api_key_for_provider(primary_provider)
                    
                    print(f"[DEBUG] Step 3/3: Executing fixes...")
                    print(f"[DEBUG]   - Using model: {primary_model}")
                    
                    @with_retry(max_retries=3, base_delay=2.0)
                    async def _apply_fixes():
                        model_settings = {
                            "temperature": 0.3,
                        }
                        if primary_model == "gpt-oss-120b":
                            model_settings["max_completion_tokens"] = 4096
                            model_settings["reasoning_effort"] = "medium"
                        else:
                            model_settings["max_tokens"] = 4096
                        
                        result = await _run_agent_with_model(
                            model_name=primary_model,
                            output_type=str,
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            api_key=primary_api_key,
                            use_thinking=(primary_provider == 'groq'),
                            model_settings=model_settings
                        )
                        
                        refined_content = str(result.output).strip()
                        
                        # Clean up thinking tags if present (for Groq models)
                        if refined_content and primary_provider == 'groq':
                            import re
                            refined_content = re.sub(
                                r'<think>.*?</think>',
                                '',
                                refined_content,
                                flags=re.DOTALL | re.IGNORECASE
                            ).strip()
                        
                        if not refined_content:
                            raise ValueError(f"{primary_model} returned an empty response when applying fixes.")
                        
                        return refined_content
                    
                    refined_content = await _apply_fixes()
                    
                    original_length = len(report_output.report_content)
                    refined_length = len(refined_content)
                    print(f"[DEBUG] Step 3/3: ✅ Fix execution complete")
                    print(f"[DEBUG]   - Original report length: {original_length} chars")
                    print(f"[DEBUG]   - Refined report length: {refined_length} chars")
                    print(f"[DEBUG]   - Length change: {refined_length - original_length:+d} chars")
                    
                    report_output.report_content = refined_content
                    print(f"\n✅ TEMPLATE STRUCTURE VALIDATION COMPLETE - Fixes applied successfully")
                    print(f"{'='*80}\n")
                else:
                    print(f"[DEBUG] No fixes needed - report passes validation")
                    print(f"\n✅ TEMPLATE STRUCTURE VALIDATION COMPLETE - No violations found")
                    print(f"{'='*80}\n")
            except Exception as e:
                print(f"\n{'='*80}")
                print(f"⚠️ TEMPLATE STRUCTURE VALIDATION FAILED")
                print(f"{'='*80}")
                print(f"[ERROR] Exception type: {type(e).__name__}")
                print(f"[ERROR] Error message: {str(e)[:500]}")
                import traceback
                print(f"[ERROR] Full traceback:")
                print(traceback.format_exc())
                # Continue with original report if validation fails
                print(f"[DEBUG] Continuing with original report (validation skipped)")
                print(f"{'='*80}\n")
        
        # Build context title: template name + description
        context_title = None
        if template.name:
            if report_output.description:
                context_title = f"{template.name} - {report_output.description}"
            else:
                context_title = template.name
        else:
            context_title = report_output.description
        
        # Save report to database (only if auto-save is enabled)
        report_id = None
        if should_auto_save(current_user):
            try:
                model_to_store = report_output_dict.get("model_used", "zai-glm-4.7")
                input_data_to_save = {
                    "variables": actual_user_inputs,
                    "extracted_scan_type": report_output.scan_type
                }
                print(f"[DEBUG] Saving report with input_data: variables={actual_user_inputs}, keys={list(actual_user_inputs.keys()) if isinstance(actual_user_inputs, dict) else 'not a dict'}")
                saved_report = create_report(
                    db=db,
                    user_id=str(current_user.id),
                    report_type="templated",
                    report_content=report_output.report_content,
                    model_used=model_to_store,
                    input_data=input_data_to_save,
                    template_id=str(template.id),
                    description=context_title
                )
                report_id = str(saved_report.id)
                print(f"✅ Report saved with ID: {report_id}")
            except Exception as e:
                print(f"Failed to save report: {e}")
        else:
            print("Auto-save is disabled, skipping report save")
        
        # Increment template usage count
        try:
            increment_template_usage(db, template_id)
        except Exception as e:
            print(f"Failed to increment template usage: {e}")
        
        # Map model names to full model identifiers for response
        model_full_name = {
            "claude": "claude-sonnet-4-6",
            "gemini": "gemini-2.5-pro",
            "qwen": "qwen/qwen3-32b"
        }.get(request.model, request.model)
        
        return {
            "success": True,
            "response": report_output.report_content,
            "model": model_full_name,
            "template_id": str(template.id),
            "report_id": report_id,
            "scan_type": report_output.scan_type,
            "applicable_guidelines": [],  # Populated from enhance response (prefetch pipeline)
        }
    
    except Exception as e:
        import traceback
        print(f"Error generating templated report: {e}")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}


# ============================================================================
# TEMPLATE VERSION API ENDPOINTS
# ============================================================================

@app.get("/api/templates/{template_id}/versions")
async def list_template_versions(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all versions for a template"""
    try:
        # Verify ownership
        template = get_template(db, template_id, user_id=str(current_user.id))
        if not template:
            return {"success": False, "error": "Template not found"}
        
        versions = get_template_versions(db, template_id, user_id=str(current_user.id))
        
        # Find which version (if any) matches the current template state
        current_version_id = get_current_version_id(db, template)
        
        # Add is_current flag to each version
        version_dicts = []
        for v in versions:
            version_dict = v.to_dict()
            version_dict["is_current"] = (str(v.id) == current_version_id) if current_version_id else False
            version_dicts.append(version_dict)
        
        return {
            "success": True,
            "versions": version_dicts,
            "current_version_id": current_version_id
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/templates/{template_id}/versions/{version_id}")
async def get_template_version_detail(
    template_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get specific version details"""
    try:
        # Verify ownership
        template = get_template(db, template_id, user_id=str(current_user.id))
        if not template:
            return {"success": False, "error": "Template not found"}
        
        version = get_template_version(db, version_id, user_id=str(current_user.id))
        if not version:
            return {"success": False, "error": "Version not found"}
        
        # Verify version belongs to template
        if str(version.template_id) != template_id:
            return {"success": False, "error": "Version does not belong to this template"}
        
        return {
            "success": True,
            "version": version.to_dict()
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/templates/{template_id}/versions/{version_id}/restore")
async def restore_template_version_endpoint(
    template_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Restore a template to a specific version"""
    try:
        restored_template = restore_template_version(
            db=db,
            template_id=template_id,
            version_id=version_id,
            user_id=str(current_user.id)
        )
        
        if not restored_template:
            return {"success": False, "error": "Template or version not found, or you don't have permission"}
        
        return {
            "success": True,
            "template": restored_template.to_dict(),
            "message": "Template restored successfully"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/api/templates/{template_id}/versions/{version_id}")
async def delete_template_version_endpoint(
    template_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a specific template version"""
    try:
        success = delete_template_version(
            db=db,
            version_id=version_id,
            user_id=str(current_user.id)
        )
        
        if not success:
            return {"success": False, "error": "Version not found or you don't have permission"}
        
        return {
            "success": True,
            "message": "Version deleted successfully"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# WIZARD ASSISTANCE ENDPOINTS
# ============================================================================

@app.post("/api/templates/generate-findings-content")
async def generate_findings_content_endpoint(
    request: GenerateFindingsContentRequest,
    current_user: User = Depends(get_current_user)
):
    """Generate FINDINGS template content via AI"""
    try:
        tm = TemplateManager()
        api_key = get_system_api_key('cerebras', 'CEREBRAS_API_KEY')
        if not api_key:
            return {"success": False, "error": "Cerebras API key not configured"}
        
        content = await tm.generate_findings_content(
            scan_type=request.scan_type,
            contrast=request.contrast,
            protocol_details=request.protocol_details or "",
            content_style=request.content_style,
            instructions=request.instructions or "",
            api_key=api_key
        )
        
        return {"success": True, "content": content}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/templates/suggest-instructions")
async def suggest_instructions_endpoint(
    request: SuggestInstructionsRequest,
    current_user: User = Depends(get_current_user)
):
    """AI-suggest instructions for FINDINGS or IMPRESSION sections"""
    try:
        tm = TemplateManager()
        api_key = get_system_api_key('cerebras', 'CEREBRAS_API_KEY')
        if not api_key:
            return {"success": False, "error": "Cerebras API key not configured"}
        
        suggestions = await tm.suggest_instructions(
            section=request.section,
            scan_type=request.scan_type,
            content_style=request.content_style,
            api_key=api_key
        )
        
        return {"success": True, "suggestions": suggestions}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/templates/analyze-reports")
async def analyze_reports_endpoint(
    request: AnalyzeReportsRequest,
    current_user: User = Depends(get_current_user)
):
    """Analyze example reports and generate template config"""
    try:
        if len(request.reports) < 3:
            return {"success": False, "error": "At least 3 reports required"}
        if len(request.reports) > 10:
            return {"success": False, "error": "Maximum 10 reports allowed"}
        
        tm = TemplateManager()
        api_key = get_system_api_key('cerebras', 'CEREBRAS_API_KEY')
        if not api_key:
            return {"success": False, "error": "Cerebras API key not configured"}
        
        result = await tm.analyze_reports_and_generate_config(
            scan_type=request.scan_type,
            contrast=request.contrast,
            protocol_details=request.protocol_details or "",
            reports=request.reports,
            api_key=api_key
        )
        
        return {
            "success": True,
            "template_config": result["template_config"],
            "detected_profile": result["detected_profile"]
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/templates/skill-sheet/check-diversity")
async def skill_sheet_check_diversity_endpoint(
    request: SkillSheetDiversityCheckRequest,
    current_user: User = Depends(get_current_user),
):
    """Lightweight diversity check on example reports before full analysis."""
    try:
        from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model, _get_model_provider, _get_api_key_for_provider
        from pydantic import BaseModel

        class DiversityResult(BaseModel):
            score: int
            summary: str
            gaps: list[str]
            suggestion: str

        examples_text = ""
        for i, ex in enumerate(request.examples, 1):
            label = ex.label or f"Example {i}"
            content = (ex.content or "").strip()
            examples_text += f"\n{i}. [{label}]:\n{content}\n"

        primary_model = MODEL_CONFIG["SKILL_SHEET_DIVERSITY_CHECK"]
        fallback_model = MODEL_CONFIG["SKILL_SHEET_DIVERSITY_CHECK_FALLBACK"]

        system_prompt = """You are a senior radiology reporting analyst assessing the diversity of example reports before template creation. Your goal is to ensure the examples cover enough clinical variation to produce a robust template.

Return a JSON object with:
- "score": 1-10 diversity score (internal metric, not shown to user)
- "summary": one sentence for the radiologist. If diverse (score >= 8): state what's covered well, e.g. "Good range — covers normal anatomy, acute pathology, and complex multi-system cases." If not diverse enough: acknowledge what's strong then note what's missing, e.g. "Strong on acute cases — consider adding a normal study to capture your baseline phrasing."
- "gaps": array of missing categories (internal, for logging). Max 3.
- "suggestion": one actionable sentence ONLY if score < 8. Specific and encouraging, e.g. "Swapping one report for a post-operative follow-up would teach the template comparison and interval change language." Empty string if score >= 8.

How to assess diversity:
Do NOT check against a fixed category list. Instead, reason from the scan type and the examples themselves:
1. What are the natural clinical axes of variation for this specific scan type? (e.g. for CT head: normal, haemorrhage, infarct, trauma, mass. For MRI knee: normal, meniscal, ligamentous, degenerative, multi-compartment.)
2. Which of those axes are represented in the examples?
3. Is there a normal/unremarkable example? This is almost always valuable regardless of scan type — it teaches the template mandatory negatives and baseline structure.
4. Do the examples exercise different structural patterns in the report? (e.g. different section lengths, different impression complexity, different numbers of findings)
5. Are the examples genuinely different cases, or variations of the same presentation?
6. Within represented axes, do the examples show variation in severity or complexity? A mild and a severe case of the same pathology teach different language and impression construction — different recommendation graduation, different measurement emphasis, different urgency framing.

Scoring guide:
- 9-10: covers the major clinical axes for this scan type with good structural variety
- 7-8: covers most axes, minor gaps that wouldn't significantly weaken the template
- 5-6: covers some axes well but missing one that would meaningfully improve the template
- 3-4: examples are too similar in clinical presentation
- 1-2: essentially the same report repeated

Be encouraging — acknowledge what's good before noting gaps. Frame gaps as opportunities, not criticisms. Suggestions must be specific to the scan type — never generic."""

        user_prompt = f"Scan type: {request.scan_type}\n\nExample reports:\n{examples_text}"

        def _diversity_settings(model):
            p = _get_model_provider(model)
            if p == "cerebras":
                return {
                    "temperature": 0.3,
                    "top_p": 0.95,
                    "max_tokens": 4096,
                    "extra_body": {"disable_reasoning": False, "clear_thinking": False},
                }
            else:
                return {"temperature": 0.1, "max_tokens": 3000}

        # Try primary, fallback on failure
        try:
            provider = _get_model_provider(primary_model)
            api_key = _get_api_key_for_provider(provider)
            result = await _run_agent_with_model(
                model_name=primary_model,
                output_type=DiversityResult,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                use_thinking=True,
                model_settings=_diversity_settings(primary_model),
            )
        except Exception as primary_err:
            logger.warning("Diversity check primary failed (%s), falling back to %s", primary_err, fallback_model)
            fb_provider = _get_model_provider(fallback_model)
            fb_api_key = _get_api_key_for_provider(fb_provider)
            result = await _run_agent_with_model(
                model_name=fallback_model,
                output_type=DiversityResult,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=fb_api_key,
                use_thinking=True,
                model_settings=_diversity_settings(fallback_model),
            )

        out = result.output
        return {
            "success": True,
            "score": out.score,
            "summary": out.summary,
            "gaps": out.gaps,
            "suggestion": out.suggestion,
        }
    except Exception as e:
        return {"success": True, "score": 7, "summary": "", "gaps": [], "suggestion": ""}


@app.post("/api/templates/skill-sheet/analyze")
async def skill_sheet_analyze_endpoint(
    request: SkillSheetAnalyzeRequest,
    current_user: User = Depends(get_current_user)
):
    """Analyse example reports and generate an initial skill sheet + clarifying questions."""
    try:
        if len(request.examples) < 3:
            return {"success": False, "error": "At least 3 example reports required"}
        if len(request.examples) > 5:
            return {"success": False, "error": "Maximum 5 example reports allowed"}

        protocol_notes = (request.protocol_notes or "").strip()
        logger.info("━━━ SKILL SHEET ANALYZE ━━━")
        logger.info("  scan_type: %s", request.scan_type)
        logger.info("  protocol_notes: %d chars", len(protocol_notes))
        logger.info("  examples: %d provided", len(request.examples))
        for i, ex in enumerate(request.examples):
            chars = len(ex.content)
            logger.info("    [%d] label=%r  chars=%d", i + 1, ex.label or "(none)", chars)

        tm = TemplateManager()
        api_key = get_system_api_key('cerebras', 'CEREBRAS_API_KEY')
        if not api_key:
            return {"success": False, "error": "Cerebras API key not configured"}

        import asyncio
        examples = [{"label": ex.label, "content": ex.content} for ex in request.examples]

        # Run skill sheet analysis and test case generation in parallel
        analysis_task = tm.analyze_examples_to_skill_sheet(
            examples=examples,
            scan_type=request.scan_type,
            protocol_notes=protocol_notes,
            api_key=api_key,
        )
        test_case_task = tm.generate_test_case(
            examples=examples,
            scan_type=request.scan_type,
            api_key=api_key,
        )
        result, test_case = await asyncio.gather(analysis_task, test_case_task)

        logger.info("━━━ SKILL SHEET ANALYZE RESULT ━━━")
        logger.info("  skill_sheet: %d chars", len(result.get("skill_sheet", "")))
        _summary = result.get("summary", {})
        if isinstance(_summary, dict):
            logger.info("  summary: %s", list(_summary.keys()))
        else:
            logger.info("  summary: %s", str(_summary)[:200])
        logger.info("  questions: %s", result.get("questions", []))
        logger.info("  ── skill_sheet content ──\n%s", result.get("skill_sheet", ""))
        logger.info("━━━ TEST CASE RESULT ━━━")
        logger.info("  sample_clinical_history: %s", test_case.get("sample_clinical_history", ""))
        logger.info("  ── sample_findings ──\n%s", test_case.get("sample_findings", ""))

        return {"success": True, **result, **test_case}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/templates/skill-sheet/generate-test-case")
async def skill_sheet_generate_test_case_endpoint(
    request: SkillSheetGenerateTestCaseRequest,
    current_user: User = Depends(get_current_user)
):
    """Generate a fresh test case (clinical history + scratchpad findings) for a skill sheet template.

    Wraps TemplateManager.generate_test_case so the frontend can regenerate just the sample
    without re-running the full /analyze pipeline.
    """
    try:
        logger.info("━━━ GENERATE TEST CASE ━━━")
        logger.info("  scan_type: %s", request.scan_type)
        logger.info("  examples: %d provided", len(request.examples))

        tm = TemplateManager()
        api_key = get_system_api_key('cerebras', 'CEREBRAS_API_KEY')
        if not api_key:
            return {"success": False, "error": "Cerebras API key not configured"}

        examples = [{"label": ex.label, "content": ex.content} for ex in request.examples]
        test_case = await tm.generate_test_case(
            examples=examples,
            scan_type=request.scan_type,
            api_key=api_key,
        )

        logger.info("━━━ GENERATE TEST CASE RESULT ━━━")
        logger.info("  sample_clinical_history: %s", test_case.get("sample_clinical_history", ""))
        logger.info("  ── sample_findings ──\n%s", test_case.get("sample_findings", ""))

        return {"success": True, **test_case}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/templates/skill-sheet/refine")
async def skill_sheet_refine_endpoint(
    request: SkillSheetRefineRequest,
    current_user: User = Depends(get_current_user)
):
    """Refine a skill sheet via one chat turn."""
    try:
        logger.info("━━━ SKILL SHEET REFINE ━━━")
        logger.info("  message: %s", request.message[:300])
        logger.info("  chat_history: %d turns", len(request.chat_history or []))
        if request.rejection_context:
            logger.info("  rejection_context: rejected_claim=%r", request.rejection_context.rejected_claim[:200])
        logger.info("  skill_sheet in: %d chars", len(request.skill_sheet))

        tm = TemplateManager()
        api_key = get_system_api_key('cerebras', 'CEREBRAS_API_KEY')
        if not api_key:
            return {"success": False, "error": "Cerebras API key not configured"}

        history = [{"role": m.role, "content": m.content} for m in (request.chat_history or [])]
        rejection_ctx = (
            {"original_instruction": request.rejection_context.original_instruction,
             "rejected_claim": request.rejection_context.rejected_claim}
            if request.rejection_context else None
        )
        result = await tm.refine_skill_sheet(
            skill_sheet=request.skill_sheet,
            message=request.message,
            chat_history=history,
            api_key=api_key,
            rejection_context=rejection_ctx,
        )

        logger.info("━━━ SKILL SHEET REFINE RESULT ━━━")
        logger.info("  skill_sheet out: %d chars", len(result.get("skill_sheet", "")))
        logger.info("  response: %s", result.get("response", "")[:500])
        logger.info("  behavioral_claim: %s", result.get("behavioral_claim", ""))
        logger.info("  ── refined skill_sheet ──\n%s", result.get("skill_sheet", ""))

        return {"success": True, **result}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/templates/skill-sheet/test-generate")
async def skill_sheet_test_generate_endpoint(
    request: SkillSheetTestGenerateRequest,
    current_user: User = Depends(get_current_user)
):
    """Generate a test report from a skill sheet (no saved template required)."""
    try:
        logger.info("━━━ SKILL SHEET TEST GENERATE ━━━")
        logger.info("  scan_type: %s", request.scan_type)
        logger.info("  clinical_history: %s", request.clinical_history[:200] if request.clinical_history else "(empty)")
        logger.info("  findings_input: %d chars", len(request.findings_input))
        logger.info("  skill_sheet: %d chars", len(request.skill_sheet))

        tm = TemplateManager()
        api_key = get_system_api_key('cerebras', 'CEREBRAS_API_KEY')
        if not api_key:
            return {"success": False, "error": "Cerebras API key not configured"}

        result = await tm.test_generate_with_skill_sheet(
            skill_sheet=request.skill_sheet,
            scan_type=request.scan_type,
            clinical_history=request.clinical_history,
            findings_input=request.findings_input,
            api_key=api_key,
        )

        logger.info("━━━ SKILL SHEET TEST GENERATE RESULT ━━━")
        logger.info("  model_used: %s", result.get("model_used", "unknown"))
        logger.info("  report_content: %d chars", len(result.get("report_content", "")))
        logger.info("  ── generated report ──\n%s", result.get("report_content", ""))

        return {"success": True, **result}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/templates/skill-sheet/save")
async def skill_sheet_save_endpoint(
    request: SkillSheetSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save a skill-sheet-guided template."""
    try:
        logger.info("━━━ SKILL SHEET SAVE ━━━")
        logger.info("  template_name: %s", request.template_name)
        logger.info("  scan_type: %s", request.scan_type)
        logger.info("  skill_sheet: %d chars", len(request.skill_sheet))
        logger.info("  tags: %s", request.tags)

        if not request.template_name.strip():
            return {"success": False, "error": "Template name is required"}
        if not request.skill_sheet.strip():
            return {"success": False, "error": "Skill sheet is required"}

        tm = TemplateManager()
        api_key = get_system_api_key('cerebras', 'CEREBRAS_API_KEY')
        try:
            coverage_sections = await tm.extract_coverage_sections(request.skill_sheet, api_key)
        except Exception as cov_err:
            logger.warning("  coverage_sections extraction failed: %s", cov_err)
            coverage_sections = []
        logger.info("  coverage_sections: %s", coverage_sections)
        template_config = {
            "generation_mode": "skill_sheet_guided",
            "skill_sheet": request.skill_sheet,
            "scan_type": request.scan_type,
            "coverage_sections": coverage_sections,
        }
        template = create_template(
            db=db,
            name=request.template_name.strip(),
            description=None,
            tags=request.tags,
            template_config=template_config,
            is_pinned=False,
            user_id=str(current_user.id),
        )
        return {"success": True, "template_id": str(template.id)}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


class ExtractCoverageRequest(BaseModel):
    skill_sheet: str


@app.post("/api/templates/skill-sheet/extract-coverage")
async def extract_coverage_endpoint(
    request: ExtractCoverageRequest,
    current_user: User = Depends(get_current_user),
):
    """Extract anatomical coverage sections from a skill sheet."""
    try:
        tm = TemplateManager()
        api_key = get_system_api_key('cerebras', 'CEREBRAS_API_KEY')
        sections = await tm.extract_coverage_sections(request.skill_sheet, api_key)
        return {"success": True, "sections": sections}
    except Exception as e:
        return {"success": True, "sections": []}


# ═══════════════════════════════════════════════════════════════════════════════
# Quick Report Proto — ephemeral skill sheet pipeline
# ═══════════════════════════════════════════════════════════════════════════════
# Stress-test surface for the quick-report analyser + generator flow.
# Analyser: scan_type + clinical_history → bespoke skill sheet (GLM-4.7)
# Generator: skill_sheet + findings → report (same skill_sheet_guided path as
# production templates)
# All runs logged to /tmp/radflow_quick_proto.log (separate from /tmp/radflow.log)

@app.post("/api/quick-report-proto/analyse")
async def quick_report_proto_analyse_endpoint(
    request: QuickReportProtoAnalyseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate an ephemeral skill sheet from scan_type + clinical_history.

    Phase 1 persistence: every successful analyser run is written to the
    `ephemeral_skill_sheets` table. `sheet_id` is returned so the subsequent
    generate call can reference the persisted sheet.
    """
    from .quick_report_analyser import (
        generate_ephemeral_skill_sheet,
        log_analyser_run,
        new_run_id,
        analyser_prompt_version,
    )
    from .database import create_ephemeral_skill_sheet

    run_id = new_run_id()
    try:
        if not request.scan_type.strip():
            return {"success": False, "error": "Scan type is required"}

        # api_key passes through for Cerebras-backed analysers; Anthropic-backed
        # analysers ignore this and fetch ANTHROPIC_API_KEY inside the call.
        api_key = get_system_api_key('cerebras', 'CEREBRAS_API_KEY') or ""

        result = await generate_ephemeral_skill_sheet(
            scan_type=request.scan_type,
            clinical_history=request.clinical_history,
            api_key=api_key,
        )

        # Persist the sheet so it can be referenced at report-generation time
        # and clustered by the maintenance agent later.
        sheet_id = None
        try:
            sheet_row = create_ephemeral_skill_sheet(
                db=db,
                user_id=str(current_user.id),
                scan_type=request.scan_type,
                clinical_history=request.clinical_history,
                skill_sheet_markdown=result.get("skill_sheet", ""),
                analyser_model=result.get("model_used", ""),
                analyser_latency_ms=result.get("latency_ms"),
                analyser_prompt_version=result.get("prompt_version") or analyser_prompt_version(result.get("model_used", "zai-glm-4.7")),
                run_id=run_id,
            )
            sheet_id = str(sheet_row.id)
        except Exception as persist_err:
            # Do not fail the analyse call on persistence error — the sheet is
            # still usable in-session. Log for debugging.
            logger.warning("ephemeral skill sheet persistence failed: %s", persist_err)

        log_analyser_run(
            run_id=run_id,
            scan_type=request.scan_type,
            clinical_history=request.clinical_history,
            result=result,
        )

        return {"success": True, "run_id": run_id, "sheet_id": sheet_id, **result}
    except Exception as e:
        import traceback
        traceback.print_exc()
        from .quick_report_analyser import log_analyser_run
        log_analyser_run(
            run_id=run_id,
            scan_type=request.scan_type,
            clinical_history=request.clinical_history,
            result={},
            error=str(e),
        )
        return {"success": False, "error": str(e), "run_id": run_id}


@app.post("/api/quick-report-proto/generate")
async def quick_report_proto_generate_endpoint(
    request: QuickReportProtoGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a report using an ephemeral skill sheet + findings.

    Reuses the same skill_sheet_guided generation path as production templates,
    so the only difference between this and the templated flow is where the
    skill sheet came from (ephemeral vs cached in a templates row).
    """
    from .quick_report_analyser import (
        log_generator_run,
        new_run_id,
        proto_logger,
    )
    import time

    run_id = request.run_id or new_run_id()
    try:
        if not request.skill_sheet.strip():
            return {"success": False, "error": "Skill sheet is required"}

        api_key = get_system_api_key('cerebras', 'CEREBRAS_API_KEY')
        if not api_key:
            return {"success": False, "error": "Cerebras API key not configured"}

        # Shared preamble — same in production (/api/quick-report/generate)
        # and proto. Single source of truth at quick_report_hardening.py.
        from .quick_report_hardening import QUICK_REPORT_HARDENING_PREAMBLE
        hardening_preamble = QUICK_REPORT_HARDENING_PREAMBLE

        tm = TemplateManager()
        template_config = {
            "generation_mode": "skill_sheet_guided",
            "skill_sheet": hardening_preamble + request.skill_sheet,
            "scan_type": request.scan_type,
        }
        user_inputs = {
            "FINDINGS": request.findings,
            "CLINICAL_HISTORY": request.clinical_history,
        }

        # Model override is validated against an allow-list so the proto doesn't
        # accept arbitrary strings from the frontend. Every model here must be
        # registered in MODEL_PROVIDERS in enhancement_utils.py.
        allowed_models = {
            # Proprietary
            "zai-glm-4.7",                       # Cerebras GLM-4.7 (current default)
            "claude-sonnet-4-6",                 # Anthropic Claude Sonnet 4.6
            # Open source
            "gpt-oss-120b",                      # Cerebras GPT-OSS 120B
            "qwen-3-235b-a22b-instruct-2507",    # Cerebras Qwen 3 235B
            "llama-3.3-70b-versatile",           # Groq Llama 3.3 70B
            "qwen/qwen3-32b",                    # Groq Qwen 3 32B
        }
        model_override = request.model if request.model in allowed_models else None

        t0 = time.time()
        result = await tm.generate_report_from_config(
            template_config=template_config,
            user_inputs=user_inputs,
            user_signature=None,
            model_override=model_override,
        )
        latency_ms = int((time.time() - t0) * 1000)
        result["latency_ms"] = latency_ms

        log_generator_run(
            run_id=run_id,
            scan_type=request.scan_type,
            clinical_history=request.clinical_history,
            findings=request.findings,
            skill_sheet=request.skill_sheet,
            result=result,
        )

        # Phase 1 persistence: record the report row with this candidate in
        # `candidate_reports` so future dual-model runs can append alongside.
        # Persistence failure must not fail the generate call — the report is
        # still usable in-session. Log for debugging.
        report_id = None
        try:
            from .database import create_quick_report_with_candidates
            from datetime import datetime, timezone

            candidate_record = {
                "model": result.get("model_used", "unknown"),
                "content": result.get("report_content", ""),
                "latency_ms": latency_ms,
                "run_id": run_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }
            report_row = create_quick_report_with_candidates(
                db=db,
                user_id=str(current_user.id),
                ephemeral_skill_sheet_id=request.sheet_id,
                findings_dictation=request.findings,
                clinical_history=request.clinical_history,
                scan_type=request.scan_type,
                candidate_reports=[candidate_record],
                description=result.get("description"),
            )
            report_id = str(report_row.id)
        except Exception as persist_err:
            logger.warning("quick-report persistence failed: %s", persist_err)

        return {"success": True, "run_id": run_id, "report_id": report_id, **result}
    except Exception as e:
        import traceback
        traceback.print_exc()
        from .quick_report_analyser import log_generator_run
        log_generator_run(
            run_id=run_id,
            scan_type=request.scan_type,
            clinical_history=request.clinical_history,
            findings=request.findings,
            skill_sheet=request.skill_sheet,
            result={},
            error=str(e),
        )
        return {"success": False, "error": str(e), "run_id": run_id}


@app.post("/api/templates/extract-placeholders")
async def extract_placeholders_endpoint(
    request: ExtractPlaceholdersRequest,
    current_user: User = Depends(get_current_user)
):
    """Extract placeholders from a structured template for UI display"""
    try:
        tm = TemplateManager()
        placeholders = tm.extract_structured_placeholders(request.template_content)
        
        return {
            "success": True,
            "placeholders": placeholders
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# Feedback Pipeline Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/feedback/capture")
async def feedback_capture_endpoint(
    request: FeedbackCaptureRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Capture or update a feedback record (called on generate, edit, copy, abandon)."""
    try:
        from .database.models import ReportFeedback, TemplateRating
        import uuid as _uuid

        def _compute_edit_distance(a: str, b: str) -> int:
            """Character-level Levenshtein distance via SequenceMatcher."""
            from difflib import SequenceMatcher
            sm = SequenceMatcher(None, a, b)
            distance = 0
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag != 'equal':
                    distance += max(i2 - i1, j2 - j1)
            return distance

        existing = db.query(ReportFeedback).filter(
            ReportFeedback.template_id == _uuid.UUID(request.template_id),
            ReportFeedback.user_id == current_user.id,
            ReportFeedback.ai_output == request.ai_output,
        ).order_by(ReportFeedback.created_at.desc()).first()

        if existing and request.lifecycle in ("edited", "copied"):
            existing.lifecycle = request.lifecycle
            existing.final_output = request.final_output
            existing.copy_count = request.copy_count
            existing.time_to_first_edit_ms = request.time_to_first_edit_ms or existing.time_to_first_edit_ms
            existing.time_to_copy_ms = request.time_to_copy_ms or existing.time_to_copy_ms
            if request.final_output and existing.ai_output:
                existing.edit_distance = _compute_edit_distance(existing.ai_output, request.final_output)
            existing.sections_modified = request.sections_modified or existing.sections_modified
            if request.report_id:
                existing.report_id = _uuid.UUID(request.report_id)
            db.commit()
            return {"success": True, "feedback_id": str(existing.id), "updated": True}

        feedback = ReportFeedback(
            report_id=_uuid.UUID(request.report_id) if request.report_id else None,
            template_id=_uuid.UUID(request.template_id),
            user_id=current_user.id,
            ai_output=request.ai_output,
            final_output=request.final_output,
            lifecycle=request.lifecycle,
            copy_count=request.copy_count,
            time_to_first_edit_ms=request.time_to_first_edit_ms,
            time_to_copy_ms=request.time_to_copy_ms,
            edit_distance=request.edit_distance,
            sections_modified=request.sections_modified,
        )
        db.add(feedback)
        db.commit()
        db.refresh(feedback)

        # Bump template_rating.total_uses on first capture (lifecycle=generated)
        if request.lifecycle == "generated":
            rating = db.query(TemplateRating).filter(
                TemplateRating.template_id == _uuid.UUID(request.template_id),
                TemplateRating.user_id == current_user.id,
            ).first()
            if rating:
                rating.total_uses += 1
            else:
                rating = TemplateRating(
                    template_id=_uuid.UUID(request.template_id),
                    user_id=current_user.id,
                    total_uses=1,
                )
                db.add(rating)
            db.commit()

        return {"success": True, "feedback_id": str(feedback.id)}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/feedback/rate")
async def feedback_rate_endpoint(
    request: FeedbackRatingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the thumbs up/down rating on an existing feedback record."""
    try:
        from .database.models import ReportFeedback, TemplateRating
        import uuid as _uuid

        feedback = db.query(ReportFeedback).filter(
            ReportFeedback.id == _uuid.UUID(request.feedback_id),
            ReportFeedback.user_id == current_user.id,
        ).first()
        if not feedback:
            return {"success": False, "error": "Feedback record not found"}

        feedback.rating = request.rating
        db.commit()

        # Update template_rating aggregates
        rating = db.query(TemplateRating).filter(
            TemplateRating.template_id == feedback.template_id,
            TemplateRating.user_id == current_user.id,
        ).first()
        if rating:
            if request.rating == "positive":
                rating.positive_count += 1
            elif request.rating == "negative":
                rating.negative_count += 1
            db.commit()

        return {"success": True}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/templates/validate-template")
async def validate_template_endpoint(
    request: ValidateTemplateRequest,
    current_user: User = Depends(get_current_user)
):
    """Validate a structured template and return errors, warnings, and stats"""
    try:
        tm = TemplateManager()
        validation = tm.validate_structured_template(request.template_content)
        
        return {
            "success": True,
            "validation": validation
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/templates/suggest-placeholder-fill")
async def suggest_placeholder_fill_endpoint(
    request: SuggestPlaceholderFillRequest,
    current_user: User = Depends(get_current_user)
):
    """Generate AI suggestion for filling a specific placeholder"""
    try:
        from .enhancement_utils import (
            MODEL_CONFIG,
            _get_model_provider,
            _get_api_key_for_provider,
            _run_agent_with_model
        )
        
        # Use fast model for quick tips
        model_name = "gpt-oss-120b"  # Fast inference model
        
        # Build context-aware prompt based on type
        if request.placeholder_type == 'measurement':
            prompt = f"""Based on this radiology report excerpt, suggest what value should fill the "xxx" measurement.

Context: "{request.surrounding_context}"

Provide a brief suggestion (1 sentence). If not specified in report, say "Not provided - manual entry needed."
Format: Just the suggestion, no extra text."""
        
        elif request.placeholder_type == 'alternative':
            options = request.placeholder_text.split('/')
            prompt = f"""Based on this radiology report excerpt, which option should be selected?

Context: "{request.surrounding_context}"
Options: {request.placeholder_text}

Provide a brief explanation (1-2 sentences) of which option to choose and why.
Format: "Choose '[option]' because [reason]." """
        
        elif request.placeholder_type == 'variable':
            prompt = f"""Based on this radiology report, suggest a value for the variable {request.placeholder_text}.

Context: "{request.surrounding_context}"

Provide the value if it appears elsewhere in the report, or suggest "Not specified" if not found.
Format: Just the value or explanation, no extra text."""
        
        else:  # instruction
            prompt = f"""Based on this radiology report excerpt, how should this instruction marker be handled?

Context: "{request.surrounding_context}"
Instruction: {request.placeholder_text}

Provide a brief suggestion (1 sentence) on whether to remove it, keep it, or what text should replace it.
Format: Just the suggestion, no extra text."""
        
        # Get API key
        provider = _get_model_provider(model_name)
        api_key = _get_api_key_for_provider(provider)
        
        if not api_key:
            return {"success": False, "error": f"{provider} API key not configured"}
        
        # Use simple text output (not structured)
        system_prompt = "You are a helpful assistant providing brief, concise suggestions for filling in radiology report placeholders. Respond with just the suggestion, no extra text."
        
        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=str,
            system_prompt=system_prompt,
            user_prompt=prompt,
            api_key=api_key,
            use_thinking=False,
            model_settings={
                "temperature": 0.3,  # Low temperature for consistent suggestions
                "max_completion_tokens": 150  # Keep it brief
            }
        )
        
        suggestion = str(result).strip() if result else "Unable to generate suggestion"
        
        return {
            "success": True,
            "suggestion": suggestion
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/templates/{template_id}/toggle-pin")
async def toggle_template_pin_endpoint(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Toggle the pinned status of a template"""
    try:
        template = toggle_template_pin(
            db=db,
            template_id=template_id,
            user_id=str(current_user.id)
        )
        
        if not template:
            return {"success": False, "error": "Template not found or you don't have permission"}
        
        return {
            "success": True,
            "template": template.to_dict(),
            "is_pinned": template.is_pinned
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# WRITING STYLE PRESETS API ENDPOINTS
# ============================================================================

# ============================================================================
# SETTINGS API ENDPOINTS
# ============================================================================

@app.get("/api/settings")
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user settings (LLM and Deepgram API keys now system-wide via environment variables)"""
    # Force a fresh read from database
    db.refresh(current_user)
    settings = current_user.settings or {}
    tag_colors = settings.get('tag_colors', {})
    
    print(f"[COLOR_PICKER] Backend GET /api/settings - returning tag_colors: {tag_colors}")
    return {
        "success": True,
        "full_name": current_user.full_name,
        "signature": current_user.signature,
        "auto_save": settings.get('auto_save', True),
        "tag_colors": tag_colors,
        "deepgram_configured": bool(os.getenv("DEEPGRAM_API_KEY"))
    }


class UpdateSettingsRequest(BaseModel):
    full_name: Optional[str] = None
    signature: Optional[str] = None
    auto_save: Optional[bool] = None
    tag_colors: Optional[Dict[str, str]] = None


@app.post("/api/settings")
async def update_settings(
    request: UpdateSettingsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user settings"""
    try:
        if request.full_name is not None:
            current_user.full_name = request.full_name
        if request.signature is not None:
            current_user.signature = request.signature
        
        # Update settings JSON - create a NEW dict to trigger SQLAlchemy change detection
        settings = dict(current_user.settings or {})
        # Remove legacy default_model if present (no longer used)
        settings.pop('default_model', None)
        if request.auto_save is not None:
            settings['auto_save'] = request.auto_save
        if request.tag_colors is not None:
            # Merge tag_colors with existing ones (don't overwrite entire object)
            existing_tag_colors = settings.get('tag_colors', {})
            print(f"[COLOR_PICKER] Backend - received tag_colors: {request.tag_colors}")
            print(f"[COLOR_PICKER] Backend - existing tag_colors: {existing_tag_colors}")
            existing_tag_colors.update(request.tag_colors)
            print(f"[COLOR_PICKER] Backend - merged tag_colors: {existing_tag_colors}")
            settings['tag_colors'] = existing_tag_colors
        
        # Also remove notifications if it exists (legacy field)
        if 'notifications' in settings:
            del settings['notifications']
        
        # Create a completely new dict to ensure SQLAlchemy detects the change
        from copy import deepcopy
        from sqlalchemy.orm.attributes import flag_modified
        current_user.settings = deepcopy(settings)
        # Explicitly flag the JSON column as modified for SQLAlchemy
        flag_modified(current_user, "settings")
        print(f"[COLOR_PICKER] Backend - settings before commit: {current_user.settings}")
        
        db.commit()
        print(f"[COLOR_PICKER] Backend - after commit, before refresh: {current_user.settings}")
        
        # Reload from database to ensure we have the latest
        db.refresh(current_user)
        print(f"[COLOR_PICKER] Backend - after refresh: {current_user.settings}")
        
        # Get the updated settings from the refreshed user object
        updated_settings = current_user.settings or {}
        final_tag_colors = updated_settings.get('tag_colors', {})
        print(f"[COLOR_PICKER] Backend - returning tag_colors: {final_tag_colors}")
        
        # If tag_colors is empty but we just saved it, something went wrong with refresh
        # Use the value we just saved instead
        if request.tag_colors and not final_tag_colors:
            print(f"[COLOR_PICKER] Backend - WARNING: tag_colors was saved but returned empty after refresh!")
            print(f"[COLOR_PICKER] Backend - Full settings dict from refresh: {updated_settings}")
            # Use the value we know was saved
            final_tag_colors = settings.get('tag_colors', {})
            print(f"[COLOR_PICKER] Backend - Using saved value directly: {final_tag_colors}")
        elif request.tag_colors:
            # Verify the saved value matches what we sent
            saved_colors = settings.get('tag_colors', {})
            if saved_colors != final_tag_colors:
                print(f"[COLOR_PICKER] Backend - Saved colors don't match refreshed: saved={saved_colors}, refreshed={final_tag_colors}")
                # Use saved value
                final_tag_colors = saved_colors
                print(f"[COLOR_PICKER] Backend - Using saved value: {final_tag_colors}")
        
        return {
            "success": True,
            "full_name": current_user.full_name,
            "signature": current_user.signature,
            "auto_save": updated_settings.get('auto_save', True),
            "tag_colors": final_tag_colors,
            "deepgram_configured": bool(os.getenv("DEEPGRAM_API_KEY"))
        }
    except Exception as e:
        print(f"Error updating settings: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.get("/api/settings/status")
async def get_api_key_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get API key configuration status - all keys from system env (DEEPGRAM_API_KEY central)"""
    db.refresh(current_user)
    
    # All API keys are system-wide via environment variables
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    has_groq = bool(os.getenv("GROQ_API_KEY"))
    has_cerebras = bool(os.getenv("CEREBRAS_API_KEY"))
    has_deepgram = bool(os.getenv("DEEPGRAM_API_KEY"))
    
    return {
        "success": True,
        "anthropic_configured": has_anthropic,
        "groq_configured": has_groq,
        "cerebras_configured": has_cerebras,
        "deepgram_configured": has_deepgram,
        "has_at_least_one_model": has_anthropic or has_groq or has_cerebras,
        "using_user_keys": {
            "deepgram": has_deepgram  # backward compat: same as deepgram_configured
        }
    }


# ============================================================================
# REPORTS API ENDPOINTS
# ============================================================================

@app.get("/api/reports")
async def get_reports(
    report_type: Optional[str] = None,
    model_used: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get reports for the current user with optional filters"""
    try:
        # Parse dates
        start_date_obj = None
        end_date_obj = None
        if start_date:
            start_date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        if end_date:
            end_date_obj = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        
        # Get reports
        reports = get_user_reports(
            db=db,
            user_id=str(current_user.id),
            skip=skip,
            limit=limit,
            report_type=report_type,
            model_used=model_used,
            start_date=start_date_obj,
            end_date=end_date_obj,
            search=search
        )
        
        return {
            "success": True,
            "reports": [report.to_dict() for report in reports]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/reports/{report_id}")
async def get_single_report(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a single report by ID"""
    try:
        report = get_report(db, report_id, user_id=str(current_user.id))
        if not report:
            return {"success": False, "error": "Report not found"}
        
        return {
            "success": True,
            "report": report.to_dict()
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/api/reports/{report_id}")
async def delete_report_endpoint(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a report"""
    try:
        success = delete_report(db, report_id, user_id=str(current_user.id))
        if not success:
            return {"success": False, "error": "Report not found"}
        
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/reports/{report_id}/validation-status")
async def get_validation_status(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get validation status for a report"""
    try:
        from .database.crud import get_validation_status
        
        status = get_validation_status(db, report_id, user_id=str(current_user.id))
        
        if status is None:
            return {"success": False, "error": "Report not found"}
        
        return {
            "success": True,
            "validation_status": status
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# REPORT ENHANCEMENT API ENDPOINTS
# ============================================================================

class ChatMessageRequest(BaseModel):
    message: str
    history: Optional[List[Dict]] = Field(default_factory=list)


class UpdateReportRequest(BaseModel):
    content: str
    edit_source: Optional[str] = None  # 'manual', 'chat', or 'audit_suggested_replacement'
    original_span: Optional[str] = None   # verbatim text replaced (audit fix only)
    replacement_span: Optional[str] = None  # replacement text applied (audit fix or inserted sentence)
    audit_criterion: Optional[str] = None   # criterion key that triggered the fix


class ApplyActionItem(BaseModel):
    id: str
    title: Optional[str] = None
    details: Optional[str] = None
    patch: Optional[str] = None


class ApplyActionsRequest(BaseModel):
    actions: List[ApplyActionItem]
    additional_context: Optional[str] = None


async def _get_prefetch_with_retry(
    findings_hash: str,
    findings_input: str,
    scan_type: str,
    clinical_history: str,
    user_id: str,
    db,
) -> Optional[PrefetchOutput]:
    """Multi-tier prefetch lookup with inline retry as last resort.

    Tiers: A (memory) → B (in-flight task) → C (DB) → D (inline retry).
    Returns None only on total failure.
    """
    # Tier A — in-memory store
    _prefetch_id = PREFETCH_INDEX.get(findings_hash)
    if _prefetch_id:
        output = PREFETCH_STORE.get(_prefetch_id)
        if output:
            PREFETCH_INDEX.pop(findings_hash, None)
            PREFETCH_STORE.pop(_prefetch_id, None)
            print(f"enhance_report: prefetch hit (in-memory) hash={findings_hash}")
            return output

    # Tier B — await in-flight task
    if _prefetch_id:
        _task = PREFETCH_TASKS.get(_prefetch_id)
        if _task and not _task.done():
            _wait_budget = float(os.getenv("PREFETCH_ENHANCE_WAIT_SEC", "120"))
            print(f"[FLOW_TIMING] enhance: awaiting in-flight prefetch prefetch_id={_prefetch_id}")
            try:
                await asyncio.wait_for(asyncio.shield(_task), timeout=_wait_budget)
            except asyncio.TimeoutError:
                print(f"[FLOW_TIMING] enhance: prefetch wait TIMEOUT after {_wait_budget}s")
            output = PREFETCH_STORE.get(_prefetch_id)
            if output:
                PREFETCH_INDEX.pop(findings_hash, None)
                PREFETCH_STORE.pop(_prefetch_id, None)
                return output

    # Tier C — DB lookup
    try:
        from .database.models import PrefetchResult as _PR
        _row = db.query(_PR).filter(_PR.findings_hash == findings_hash).first()
        if _row and _row.output_json:
            output = PrefetchOutput(**_row.output_json)
            print(f"enhance_report: prefetch hit (DB) hash={findings_hash}")
            return output
    except Exception as _pex:
        print(f"enhance_report: prefetch DB lookup failed: {_pex}")

    # Tier D — inline retry (run S1-S3 synchronously)
    print(f"enhance_report: prefetch miss — running inline S1-S3 retry")
    try:
        from .guideline_prefetch import run_prefetch_pipeline
        output = await asyncio.wait_for(
            run_prefetch_pipeline(
                findings=findings_input,
                scan_type=scan_type,
                clinical_history=clinical_history,
                prefetch_id=f"inline-{findings_hash}",
                user_id=user_id,
            ),
            timeout=60.0,
        )
        if output and output.consolidated_findings:
            return output
    except Exception as _rex:
        print(f"enhance_report: inline prefetch retry failed: {_rex}")

    return None


@app.post("/api/reports/{report_id}/enhance")
async def enhance_report(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Enhancement pipeline: Prefetch S1-S3 → S4 Synthesis → Phase 2 Audit."""
    try:
        report = get_report(db, report_id, user_id=str(current_user.id))
        if not report:
            return {"success": False, "error": "Report not found"}

        report_content = report.report_content
        _enh_wall0 = time.perf_counter()

        # Extract findings_input, scan_type, clinical_history from stored input_data
        findings_input = ""
        scan_type = ""
        clinical_history = ""
        other_variables: dict = {}
        if report.input_data and isinstance(report.input_data, dict):
            variables = report.input_data.get("variables", {})
            if isinstance(variables, dict):
                findings_input = variables.get("FINDINGS", "").strip()
                clinical_history = variables.get("CLINICAL_HISTORY", "").strip()
                other_variables = {k: v for k, v in variables.items() if k != "FINDINGS"}
            scan_type = report.input_data.get("extracted_scan_type", "")

        print(
            f"[FLOW_TIMING] enhance: begin report_id={report_id} "
            f"report_chars={len(report_content)} findings_input_chars={len(findings_input)} "
            f"scan_type={scan_type!r}"
        )

        # ── Prefetch lookup (multi-tier with inline retry) ──────────────────
        _findings_hash = ""
        prefetch_output = None
        if findings_input:
            _findings_hash = hashlib.sha256(
                f"{str(current_user.id)}:{findings_input}".encode()
            ).hexdigest()[:16]
            prefetch_output = await _get_prefetch_with_retry(
                findings_hash=_findings_hash,
                findings_input=findings_input,
                scan_type=scan_type,
                clinical_history=clinical_history,
                user_id=str(current_user.id),
                db=db,
            )

        # Prefetch-pipeline failure modes — distinguish true failure (no evidence
        # could be retrieved) from a successful run that happens to yield no
        # applicable guideline. The latter is a legitimate clinical outcome and
        # should be silent. The former needs the degraded banner + Retry.
        guideline_lookup_failed = False

        if not prefetch_output:
            # Prefetch helper returned None entirely (shouldn't happen in normal
            # operation — it's designed to return an empty PrefetchOutput on error).
            print("enhance_report: total prefetch failure — no prefetch output")
            guideline_lookup_failed = True
            prefetch_output = None
        elif (
            not prefetch_output.knowledge_base
            and not prefetch_output.applicable_guidelines
        ):
            # Prefetch ran but produced no knowledge AND no applicable guidelines.
            # This is the "Tavily unavailable" / "upstream retrieval failed" shape:
            # the pipeline didn't throw but it couldn't retrieve anything to
            # synthesise from. Distinct from a case that genuinely has no
            # applicable guideline — in that real case, S1 still identifies
            # applicable frameworks even when the knowledge_base is sparse.
            print(
                "enhance_report: prefetch returned empty knowledge_base + zero "
                "applicable_guidelines — treating as degraded lookup"
            )
            guideline_lookup_failed = True

        # ── S4 Synthesis ────────────────────────────────────────────────────
        from .guideline_prefetch import run_synthesis

        guidelines_cards: list = []
        synth_stats: dict = {}
        _synth_t0 = time.perf_counter()

        if prefetch_output is None or guideline_lookup_failed:
            # No point running synthesis on empty evidence; Phase 2 will run
            # unanchored against the report alone.
            print("enhance_report: skipping S4 synthesis — no usable evidence (unanchored Phase 2)")
        else:
            try:
                guidelines_cards, synth_stats = await run_synthesis(
                    knowledge_base=prefetch_output.knowledge_base,
                    consolidated_findings=prefetch_output.consolidated_findings,
                    finding_short_labels=prefetch_output.finding_short_labels,
                    applicable_guidelines=prefetch_output.applicable_guidelines,
                    scan_type=scan_type,
                    clinical_history=clinical_history,
                    report_content=report_content,
                )
            except Exception as _synth_ex:
                # Synthesis itself errored (LLM failure, parse error, etc.).
                # Treat as a degraded lookup — the retry button will re-fire /enhance.
                guideline_lookup_failed = True
                guidelines_cards = []
                print(f"enhance_report: S4 synthesis failed ({type(_synth_ex).__name__}): {_synth_ex}")

        _synth_ms = int((time.perf_counter() - _synth_t0) * 1000)
        print(
            f"[FLOW_TIMING] enhance: S4 synthesis {_synth_ms}ms "
            f"cards={len(guidelines_cards)} lookup_failed={guideline_lookup_failed}"
        )

        # Wrap S1 findings in the object shape the frontend expects
        findings_response = [
            {"finding": f, "sources": [i + 1]}
            for i, f in enumerate(prefetch_output.consolidated_findings if prefetch_output else [])
        ]

        # ── Audit phase ────────────────────────────────────────────────────
        # Single-generator flow: Phase 2 (four additional criteria) appended to
        # the existing Phase 1 audit row created by /api/audit. The earlier
        # dual-candidate branch (one audit row per generator) is gone now that
        # /generate produces a single GLM candidate.
        phase2_criteria_list = []
        audit_id = None
        candidate_audits_response: list = []

        try:
            from .enhancement_utils import run_audit_phase2

            phase2_criteria_list = await run_audit_phase2(
                report_content=report_content,
                scan_type=scan_type,
                clinical_history=clinical_history,
                synthesis_cards=guidelines_cards,
                urgency_signals=prefetch_output.urgency_signals if prefetch_output else [],
                consolidated_findings=prefetch_output.consolidated_findings if prefetch_output else [],
                finding_short_labels=prefetch_output.finding_short_labels if prefetch_output else [],
            )

            try:
                from .database.crud import append_audit_criteria
                from .database.models import ReportAudit as _RA

                existing_audit = (
                    db.query(_RA)
                    .filter(_RA.report_id == uuid.UUID(report_id))
                    .order_by(_RA.created_at.desc())
                    .first()
                )
                if existing_audit:
                    audit_id = str(existing_audit.id)
                    all_statuses = [c.status for c in existing_audit.criteria] + [
                        c.status if hasattr(c, "status") else c.get("status", "pass")
                        for c in phase2_criteria_list
                    ]
                    new_overall = "pass"
                    if any(s == "flag" for s in all_statuses):
                        new_overall = "flag"
                    elif any(s == "warning" for s in all_statuses):
                        new_overall = "warning"
                    append_audit_criteria(
                        db, existing_audit.id, phase2_criteria_list, new_overall,
                    )
                else:
                    print("enhance_report: no Phase 1 audit row yet — Phase 2 criteria stored in enhancement_json only")
            except Exception as _pa_ex:
                print(f"enhance_report: Phase 2 audit persistence failed: {_pa_ex}")

        except Exception as _p2_ex:
            print(f"enhance_report: Phase 2 audit failed (non-fatal): {_p2_ex}")

        # ── Store results & persist ─────────────────────────────────────────
        phase2_criteria_dicts = [
            c.model_dump() if hasattr(c, "model_dump") else c
            for c in phase2_criteria_list
        ]

        enhancement_data = {
            "findings": findings_response,
            "guidelines": guidelines_cards,
            "urgency_signals": prefetch_output.urgency_signals if prefetch_output else [],
            "applicable_guidelines": prefetch_output.applicable_guidelines if prefetch_output else [],
            "prefetch_output_json": prefetch_output.model_dump() if prefetch_output else None,
            "synthesis_stats": synth_stats,
            "phase2_audit": {"criteria": phase2_criteria_dicts},
            "candidate_audits": candidate_audits_response,
            "guideline_lookup_failed": guideline_lookup_failed,
        }

        _enhancement_mem = dict(enhancement_data)
        _enhancement_mem["prefetch_output"] = prefetch_output
        ENHANCEMENT_RESULTS[report_id] = _enhancement_mem

        try:
            from .database.models import Report as _Report
            _rep = db.query(_Report).filter(_Report.id == uuid.UUID(report_id)).first()
            if _rep:
                _rep.enhancement_json = enhancement_data
                db.commit()
        except Exception as _eex:
            print(f"enhance_report: enhancement_json DB write failed: {_eex}")

        _enh_wall_ms = int((time.perf_counter() - _enh_wall0) * 1000)
        print(
            f"[FLOW_TIMING] enhance: end report_id={report_id} total_wall_ms={_enh_wall_ms} "
            f"guidelines_cards={len(guidelines_cards)} phase2_criteria={len(phase2_criteria_list)} "
            f"candidate_audits={len(candidate_audits_response)}"
        )

        return {
            "success": True,
            "findings": findings_response,
            "guidelines": guidelines_cards,
            "applicable_guidelines": prefetch_output.applicable_guidelines if prefetch_output else [],
            "urgency_signals": prefetch_output.urgency_signals if prefetch_output else [],
            "phase2_audit": {
                "criteria": phase2_criteria_dicts,
                "audit_id": audit_id,
            },
            "candidate_audits": candidate_audits_response,
            "guideline_lookup_failed": guideline_lookup_failed,
        }

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"ERROR in enhance_report for report_id {report_id}: {str(e)}")
        print(f"Traceback: {error_trace}")
        return {"success": False, "error": str(e), "traceback": error_trace}


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, Any]]] = None
    audit_fix_context: Optional[AuditFixContext] = None

class ComparisonRequest(BaseModel):
    prior_reports: List[dict]  # [{text: str, date?: str}]

class ApplyComparisonRequest(BaseModel):
    revised_report: str

class ReportUpdate(BaseModel):
    """Tool for updating the report content."""
    content: str = Field(..., description="The ENTIRE text of the updated radiology report. Do NOT provide a diff or snippet. You must provide the FULL report content.")

class StructuredActionItem(BaseModel):
    """Single structured action for report editing."""
    title: str = Field(..., description="Brief title describing what this action does (e.g., 'Update TNM staging', 'Add measurement details')")
    details: str = Field(..., description="Detailed explanation of what needs to change and why, based on conversation context")
    patch: str = Field(..., description="Specific patch instruction describing exactly what to change (e.g., 'Replace X with Y in Section Z', 'Add measurement after finding in Findings section')")


class ChatStructuredActionItem(BaseModel):
    """Chat tool action: title + details only. Patch omitted to avoid JSON escaping issues (e.g. quotes in text)."""
    title: str = Field(..., description="Brief title describing what this action does")
    details: str = Field(..., description="What to change and why, based on conversation context")


class ChatStructuredActionsRequest(BaseModel):
    """Chat tool schema: actions with title and details only."""
    actions: List[ChatStructuredActionItem] = Field(..., description="List of actions to apply. Each needs title and details.")
    conversation_summary: Optional[str] = Field(None, description="Brief summary of the conversation context (optional)")


class SearchExternalGuidelinesRequest(BaseModel):
    """Perplexity search tool: 1–3 focused queries for UK radiology / imaging guidance not in ENHANCEMENT CONTEXT."""
    queries: List[str] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="1–3 specific search strings (e.g. 'Fleischner subsolid nodule follow-up UK', 'RCR incidental adrenal lesion').",
    )

    @field_validator("queries", mode="before")
    @classmethod
    def strip_queries(cls, v: Any) -> List[str]:
        if not isinstance(v, list):
            return []
        return [str(q).strip() for q in v if q is not None and str(q).strip()][:3]


class StructuredActionsRequest(BaseModel):
    """Tool for applying structured actions to the report."""
    actions: List[StructuredActionItem] = Field(..., description="List of specific actions to apply to the report. Each action should be a focused, surgical edit.")
    conversation_summary: Optional[str] = Field(None, description="Brief summary of the conversation context that led to these edits (optional but helpful)")


def _groq_assistant_to_dict(message: Any) -> Dict[str, Any]:
    """Serialize Groq/OpenAI chat assistant message for a follow-up completion."""
    d: Dict[str, Any] = {"role": getattr(message, "role", "assistant"), "content": message.content or ""}
    tcs = getattr(message, "tool_calls", None)
    if tcs:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": getattr(tc, "type", None) or "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
            }
            for tc in tcs
        ]
    return d


def _strip_report_chat_meta_phrases(text: Optional[str]) -> str:
    """
    Remove boilerplate where the model narrates tools, ENHANCEMENT CONTEXT, or search decisions
    (must not appear in the clinician-facing chat UI).
    """
    if not text or not str(text).strip():
        return (text or "").strip()
    t = str(text)
    patterns = [
        r"(?is)\n*\s*No additional action is required[^\n.]*\.",
        r"(?is)\n*\s*No further action is required[^\n.]*\.",
        r"(?is)\n*\s*As the ENHANCEMENT CONTEXT[^\n.]*\.",
        r"(?is)\n*\s*The ENHANCEMENT CONTEXT[^\n.]*\.",
        r"(?is)\n*\s*Since the ENHANCEMENT CONTEXT[^\n.]*\.",
        r"(?is)\n*\s*Because the ENHANCEMENT CONTEXT[^\n.]*\.",
        r"(?is)\n*\s*This (question|topic|query) is (fully |already )?answered (by|in) the ENHANCEMENT CONTEXT[^\n.]*\.",
        r"(?is)\n*\s*The (available )?guideline context (already )?(covers|addresses|fully covers)[^\n.]*\.",
        r"(?is)\n*\s*No (further |additional )?search (was |is )?(required|needed|necessary)[^\n.]*\.",
        r"(?is)\n*\s*I (did not|have not) (invoke|call|use|need to call) (the )?search[^\n.]*\.",
        r"(?is)\n*\s*I (did not|have not) (invoke|call) `search_external_guidelines`[^\n.]*\.",
        r"(?is)\s*No additional action is required[^\n.]*\.\s*",
        r"(?is)\s*The ENHANCEMENT CONTEXT fully covers[^\n.]*\.\s*",
    ]
    for p in patterns:
        t = re.sub(p, "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def _merge_chat_source_lists(
    primary_sources: List[Dict[str, Any]], secondary_sources: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Dedupe by normalised URL; earlier list wins (Perplexity sources passed as primary).
    Uses normalize_evidence_url_for_dedupe so that URL variants like ?lang=us or
    trailing slashes don't produce duplicate entries for the same article.
    """
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for s in primary_sources + secondary_sources:
        u = (s.get("url") or "").strip()
        key = normalize_evidence_url_for_dedupe(u) if u else ""
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


@app.post("/api/reports/{report_id}/chat")
async def chat_about_report(
    report_id: str,
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Chat interface for iterative refinement powered by Groq Qwen
    """
    try:
        # Get report
        report = get_report(db, report_id, user_id=str(current_user.id))
        if not report:
            return {"success": False, "error": "Report not found"}
        
        # Get Groq API key (system environment variable)
        groq_api_key = get_system_api_key('groq', 'GROQ_API_KEY')
        
        if not groq_api_key:
            return {
                "success": False,
                "error": "Groq API key not configured. Please set GROQ_API_KEY environment variable."
            }
        
        from groq import Groq
        client = Groq(api_key=groq_api_key)

        await _ensure_enhancement_loaded(report_id, db)
        enhancement_data = ENHANCEMENT_RESULTS.get(report_id) or {}
        findings = enhancement_data.get("findings", [])
        guidelines = enhancement_data.get("guidelines", [])
        try:
            max_ctx = int(os.getenv("CHAT_GUIDELINE_CONTEXT_MAX_CHARS", "14000"))
        except ValueError:
            max_ctx = 14000

        # Pass the full guideline context for all findings — let the LLM decide what's relevant
        enhancement_context = build_chat_guideline_context(findings, guidelines, max_ctx)
        guideline_sources = collect_guideline_sources_for_chat(guidelines)

        audit_fix_block = ""
        audit_holistic_block = ""
        if request.audit_fix_context is not None:
            audit_holistic_block = format_audit_fix_holistic_workflow_instructions()
            audit_fix_block = format_audit_fix_context_for_system_prompt(request.audit_fix_context)
            print(
                f"📎 audit_fix_context: criterion={request.audit_fix_context.criterion!r} "
                f"audit_id={request.audit_fix_context.audit_id!r} "
                f"holistic_chars={len(audit_holistic_block)} audit_chars={len(audit_fix_block)}"
            )

        audit_memory_refs = enhancement_data.get("audit_guideline_references") or []
        audit_memory_cap = min(4000, max(1500, max_ctx // 2))
        audit_memory_block = ""
        if not request.audit_fix_context and audit_memory_refs:
            audit_memory_block = build_audit_guideline_references_memory_section(
                audit_memory_refs if isinstance(audit_memory_refs, list) else [],
                audit_memory_cap,
            )
            if audit_memory_block:
                print(
                    f"📎 audit_guideline_memory: refs={len(audit_memory_refs)} "
                    f"chars={len(audit_memory_block)}"
                )

        print(f"📚 Chat context: {len(guidelines)} guideline(s), {len(guideline_sources)} source(s) | report={report_id[:8]}…")

        system_prompt = (
            "You are a radiology reporting assistant. Use British English throughout. "
            "Be concise and evidence-based; say so if unsure.\n\n"
            "## User-facing reply (mandatory)\n"
            "- Address the clinician only: clinical content, practical implications, and clear language.\n"
            "- Use light Markdown when it helps readability: **bold** for society names and key thresholds, "
            "short bullet lists for multiple recommendations, optional `###` subheadings in longer answers.\n"
            "- Never mention or allude to: \"EVIDENCE CONTEXT\", internal blocks, tools, searches, retrieval, "
            "the UI Sources list, filtering, pipelines, or whether you did or did not call a function.\n"
            "- Do not end with system-style lines such as \"no additional action is required\", "
            "\"the context fully covers…\", \"no search was needed\", or similar meta commentary.\n\n"
            "## EVIDENCE CONTEXT (priority)\n"
            "For questions about guidelines, staging, classifications, measurements, or follow-up imaging, "
            "ground answers in the source evidence passages below first. If the evidence is insufficient or missing "
            "the topic, call `search_external_guidelines` with 1–3 focused queries — do not invent citations.\n"
            "Do not write inline [1], [2] or similar numbered citation markers.\n\n"
            "## Evidence context use\n"
            "How you surface the evidence depends on what your output becomes:\n"
            "- **Conversational reply to the clinician.** You may name sources naturally — society names, document titles, "
            "and years **exactly as written in the evidence**. That is how you answer the clinician faithfully.\n"
            "- **Content that lands in the report body** (via `apply_structured_actions`, or as revised report text). "
            "Integrate the evidence as clinical judgement, not as attribution. Report prose is the radiologist's own voice — "
            "it does not cite the paper, name the society, or quote the guideline. The evidence informs what you write; "
            "the report must not read as if the evidence wrote it.\n\n"
            + "## Source attribution (mandatory)\n"
            "After your complete reply, on its own line, output exactly:\n"
            "<SOURCES_USED>[\"https://url1\", \"https://url2\"]</SOURCES_USED>\n"
            "List only the URLs you directly drew on. Use the exact URL strings from the evidence passages above. "
            "Omit URLs from sources you did not draw on. Output an empty array [] if no external sources were used.\n\n"
            + "## Tool: `search_external_guidelines`\n"
            "Call only when authoritative imaging/radiology guidance is needed and not adequately covered in ENHANCEMENT CONTEXT.\n"
            "Do not call for: report edits, laterality fixes, typos, chit-chat, or questions fully answered below.\n"
            "Do not call `search_external_guidelines` in the **same** assistant message as `apply_structured_actions` — "
            "finish retrieval first, then call apply in a follow-up assistant message if still needed.\n\n"
            "## Tool use: `apply_structured_actions`\n\n"
            "**Apply immediately** (no preamble, no confirmation) when the message:\n"
            "- States the exact correction ('change right to left', 'it should be 12 mm', 'fix the laterality')\n"
            "- Ends with an apply instruction ('apply it now', 'go ahead and apply', 'apply to the report now')\n"
            "- Explicitly asks you to modify/update/implement/apply after prior discussion\n\n"
            "**Discuss first, then offer to apply** when the message:\n"
            "- Asks for assessment, review, or opinion without specifying a fix\n"
            "- Flags a potential issue without saying what the correction should be\n"
            "- Asks a question ('is this correct?', 'what should I change?')\n"
            "→ Analyse, recommend, then end with: 'Would you like me to apply this edit?'\n"
            "→ Only call the tool once the user confirms ('yes', 'go ahead', 'do it').\n\n"
            "**Never use the tool** for pure questions, explanations, or general discussion.\n"
            "**Never output the report text** in the chat message when calling the tool.\n\n"
            "## Filling placeholders\n\n"
            "When asked to fill a placeholder (e.g. 'xxx mm', '{VARIABLE}'):\n"
            "- If the value is explicit in the report findings, use it.\n"
            "- If not, apply a clinically appropriate normal/reference value for the anatomy and modality.\n"
            "- **Never refuse to fill a placeholder** — always apply something and state in `details` whether the value was taken from the report or is a reference value requiring verification.\n\n"
            "When calling the tool, decompose the request into focused actions, each with:\n"
            "- `title`: one-line description\n"
            "- `details`: what to change and why (state if a reference value was used)\n\n"
            "**Composing `details` — no attribution in prescribed text.**\n"
            "The `details` field describes a change that will land in the report body. Apply the same "
            "voice rule from **Evidence context use** above: any text you prescribe for insertion into "
            "the report (whether written inline or wrapped in quotes like `Insert 'X'`) must NOT embed "
            "source citations — no society names (NICE, ACR, Fleischner), no guideline numbers (NG147, "
            "1.3.10), no 'per X' phrases, no document titles. State the clinical substance in the "
            "radiologist's own voice. You may reference the source in the *reasoning* portion of "
            "`details` (e.g. 'supports addition because…'), but the text to be inserted into the "
            "report must stand alone as clinical prose.\n\n"
            f"## Report\n{report.report_content}"
            f"{enhancement_context}"
            f"{audit_memory_block}"
            f"{audit_holistic_block}"
            f"{audit_fix_block}"
        )
        
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        if request.history:
            for msg in request.history:
                text = msg.get('content', '')
                if not text:
                    continue
                role = 'assistant' if msg.get('role') == 'assistant' else 'user'
                messages.append({
                    "role": role,
                    "content": text
                })
        
        messages.append({
            "role": "user",
            "content": request.message
        })
        
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "apply_structured_actions",
                    "description": "ONLY use this tool when the user explicitly asks you to MODIFY, UPDATE, CHANGE, IMPLEMENT, or APPLY changes to the report. Do NOT use for questions, discussions, or requests for opinions (e.g., 'thoughts on...', 'review of...', 'what do you think?'). Only use when user says 'implement', 'apply', 'make changes', 'update', etc.",
                    "parameters": ChatStructuredActionsRequest.model_json_schema()
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "update_report",
                    "description": "DEPRECATED: Updates the full content of the radiology report. Use apply_structured_actions instead.",
                    "parameters": ReportUpdate.model_json_schema()
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_external_guidelines",
                    "description": (
                        "Search authoritative web sources for UK-relevant radiology/imaging guidance when ENHANCEMENT CONTEXT "
                        "does not cover the user's question (e.g. specific staging, classification, society guideline). "
                        "Do not use for report text edits or questions already answered in ENHANCEMENT CONTEXT."
                    ),
                    "parameters": SearchExternalGuidelinesRequest.model_json_schema(),
                }
            },
        ]

        tools_edit_only = tools[:2]

        print(f"\n💬 Chat request received:")
        print(f"  Model: qwen/qwen3-32b (Groq)")
        print(f"  User message: {request.message[:100]}...")
        print(f"  History: {len(request.history) if request.history else 0} messages")

        perplexity_sources: List[Dict[str, Any]] = []

        response = client.chat.completions.create(
            model="qwen/qwen3-32b",
            max_tokens=4096,
            temperature=0.3,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stop=None,
        )

        print(f"✅ Qwen response received")

        message = response.choices[0].message
        tool_calls = message.tool_calls or []

        search_tool_name = "search_external_guidelines"
        has_search = any(getattr(tc.function, "name", None) == search_tool_name for tc in tool_calls)

        if has_search:
            merged_queries: List[str] = []
            for tc in tool_calls:
                if tc.function.name != search_tool_name:
                    continue
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    qlist = args.get("queries") or []
                    if isinstance(qlist, list):
                        for x in qlist:
                            xs = str(x).strip() if x is not None else ""
                            if xs:
                                merged_queries.append(xs)
                except (json.JSONDecodeError, TypeError):
                    pass
            seen_q: set = set()
            uniq_queries: List[str] = []
            for q in merged_queries:
                if q not in seen_q:
                    seen_q.add(q)
                    uniq_queries.append(q)
            uniq_queries = uniq_queries[:3]
            if uniq_queries:
                evidence, perplexity_sources = await _run_tavily_search_chat(uniq_queries)
            else:
                evidence, perplexity_sources = ("", [])
            deferred_note = json.dumps(
                {
                    "note": "Answer using external search evidence first. If report edits are still needed, call apply_structured_actions in your next assistant turn only."
                }
            )
            tool_messages = []
            for tc in tool_calls:
                if tc.function.name == search_tool_name:
                    tool_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": evidence if evidence else "(no search results)",
                        }
                    )
                else:
                    tool_messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": deferred_note}
                    )
            messages_followup = messages + [_groq_assistant_to_dict(message)] + tool_messages
            response2 = client.chat.completions.create(
                model="qwen/qwen3-32b",
                max_tokens=4096,
                temperature=0.3,
                messages=messages_followup,
                tools=tools_edit_only,
                tool_choice="auto",
                stop=None,
            )
            message = response2.choices[0].message
            tool_calls = message.tool_calls or []
            print(f"✅ Qwen follow-up after external search ({len(perplexity_sources)} sources)")

        response_text = message.content

        # DEBUG: Log response details
        print(f"\n{'='*80}")
        print(f"🔍 DEBUG: Qwen Response Analysis")
        print(f"{'='*80}")
        print(f"Response text length: {len(response_text) if response_text else 0} chars")
        print(f"Response text preview: {response_text[:200] if response_text else 'None'}...")
        print(f"Tool calls: {len(tool_calls) if tool_calls else 0}")
        if tool_calls:
            for i, tc in enumerate(tool_calls, 1):
                print(f"  Tool call {i}: {tc.function.name}")
                print(f"    Arguments preview: {tc.function.arguments[:200] if tc.function.arguments else 'None'}...")
        print(f"{'='*80}\n")

        edit_proposal = None
        actions_applied = None  # Structured actions (title, details, patch) for UI display

        if tool_calls:
            for tool_call in tool_calls:
                if tool_call.function.name == "apply_structured_actions":
                    print(f"\n{'='*80}")
                    print(f"🔧 Chat tool call detected: apply_structured_actions")
                    print(f"{'='*80}")
                    print(f"User request: {request.message[:200]}")
                    print(f"Chat history length: {len(request.history) if request.history else 0}")
                    
                    # DEBUG: Log raw tool call arguments
                    print(f"\n🔍 DEBUG: Raw tool call arguments:")
                    print(f"  Full arguments: {tool_call.function.arguments}")
                    print(f"  Arguments length: {len(tool_call.function.arguments)} chars")
                    
                    try:
                        # Parse structured actions from Qwen's tool call (ChatStructuredActionsRequest: title+details only, no patch)
                        args = json.loads(tool_call.function.arguments)
                        print(f"\n🔍 DEBUG: Parsed JSON arguments:")
                        print(f"  Keys: {list(args.keys())}")
                        print(f"  Actions count: {len(args.get('actions', []))}")
                        if 'conversation_summary' in args:
                            print(f"  Conversation summary: {args['conversation_summary'][:100] if args['conversation_summary'] else 'None'}...")
                        
                        structured_actions_data = ChatStructuredActionsRequest(**args)
                        
                        print(f"\n📋 Extracted {len(structured_actions_data.actions)} structured actions:")
                        for i, action in enumerate(structured_actions_data.actions, 1):
                            print(f"  {i}. {action.title}")
                            print(f"     Details: {action.details[:200] if len(action.details) > 200 else action.details}")
                        
                        # Convert to format expected by regenerate_report_with_actions (patch omitted—updater uses title+details)
                        actions_payload = []
                        for idx, action in enumerate(structured_actions_data.actions):
                            actions_payload.append({
                                "id": f"chat_action_{idx}",
                                "title": action.title,
                                "details": action.details,
                                "patch": ""  # Not used by updater; omitted from chat schema to avoid JSON escaping issues
                            })
                        
                        # Build conversation summary for additional context
                        conversation_summary = structured_actions_data.conversation_summary
                        if not conversation_summary and request.history:
                            # Auto-generate summary from recent history if not provided
                            recent_messages = request.history[-3:] if len(request.history) > 3 else request.history
                            conversation_summary = "Recent conversation context:\n"
                            for msg in recent_messages:
                                role = msg.get('role', 'user')
                                content = msg.get('content', '')
                                if content:
                                    conversation_summary += f"{role.upper()}: {content[:200]}\n"
                        
                        # Use existing regenerate_report_with_actions function
                        print(f"\n🚀 Routing to regenerate_report_with_actions (GPT-OSS)...")
                        print(f"  Actions payload: {len(actions_payload)} actions")
                        print(f"  Conversation summary length: {len(conversation_summary) if conversation_summary else 0} chars")
                        
                        edit_proposal = await regenerate_report_with_actions(
                            report=report,
                            actions=actions_payload,
                            additional_context=conversation_summary,
                            current_user=current_user
                        )
                        actions_applied = actions_payload
                        
                        print(f"\n✅ Structured actions applied successfully")
                        print(f"  └─ Updated report length: {len(edit_proposal)} chars")
                        print(f"  └─ Edit proposal preview: {edit_proposal[:200]}...")
                        print(f"{'='*80}\n")
                        
                    except json.JSONDecodeError as e:
                        print(f"❌ Failed to parse structured actions tool call: {e}")
                        import traceback
                        traceback.print_exc()
                    except Exception as e:
                        import traceback
                        print(f"❌ Failed to apply structured actions: {type(e).__name__}")
                        print(f"  Error: {str(e)[:500]}")
                        traceback.print_exc()
                        print(f"{'='*80}\n")
                
                elif tool_call.function.name == "update_report":
                    # Backward compatibility: handle old update_report tool
                    print(f"\n{'='*80}")
                    print(f"⚠️ DEPRECATED tool call detected: update_report")
                    print(f"   Falling back to legacy full-report regeneration")
                    print(f"{'='*80}")
                    print(f"User request: {request.message[:200]}")
                    print(f"Chat history length: {len(request.history) if request.history else 0}")
                    
                    # Try GPT OSS first for report generation
                    try:
                        from .enhancement_utils import (
                            MODEL_CONFIG,
                            _get_model_provider,
                            _get_api_key_for_provider,
                            _run_agent_with_model,
                        )
                        from .enhancement_models import ReportOutput
                        import asyncio
                        import time
                        
                        gpt_oss_start = time.time()
                        model_name = MODEL_CONFIG["ACTION_APPLIER"]
                        provider = _get_model_provider(model_name)
                        api_key = _get_api_key_for_provider(provider)
                        
                        print(f"📊 Using GPT OSS for report update (legacy mode):")
                        print(f"  Model: {model_name}")
                        print(f"  Provider: {provider}")
                        
                        system_prompt = (
                            "CRITICAL: You MUST use British English spelling and terminology throughout all output.\n\n"
                            "You are a radiology reporting assistant. Generate the COMPLETE updated report text "
                            "incorporating the user's requested changes. Preserve exact structure, formatting style, and organization. "
                            "Return ONLY the full report text. No commentary, no thinking blocks, no tags—just the complete revised report."
                        )
                        
                        user_prompt = f"""ORIGINAL REPORT:
{report.report_content}
{enhancement_context}

USER REQUEST:
{request.message}

TASK: Generate the complete updated report incorporating the requested changes.
Maintain the same structure, formatting, and style as the original report."""
                        
                        model_settings = {"temperature": 0.3}
                        if provider == 'cerebras':
                            model_settings["max_completion_tokens"] = 4096
                            model_settings["reasoning_effort"] = "high"
                            print(f"  Settings: reasoning_effort=high, max_completion_tokens=4096")
                        else:
                            model_settings["max_tokens"] = 4096
                            print(f"  Settings: {model_settings}")
                        
                        # Call GPT OSS with timeout protection
                        print(f"⏳ Calling GPT OSS (timeout: 60s)...")
                        result = await asyncio.wait_for(
                            _run_agent_with_model(
                                model_name=model_name,
                                output_type=ReportOutput,
                                system_prompt=system_prompt,
                                user_prompt=user_prompt,
                                api_key=api_key,
                                use_thinking=False,
                                model_settings=model_settings
                            ),
                            timeout=60.0  # 60 second timeout
                        )
                        
                        edit_proposal = result.output.report_content
                        gpt_oss_elapsed = time.time() - gpt_oss_start
                        
                        print(f"✅ GPT OSS report update completed in {gpt_oss_elapsed:.2f}s")
                        print(f"  └─ Updated report length: {len(edit_proposal)} chars")
                        print(f"{'='*80}\n")
                        
                    except asyncio.TimeoutError:
                        print(f"⏱️ GPT OSS timeout after 60s, falling back to Qwen tool call")
                        print(f"{'='*80}\n")
                        # Fallback to Qwen's tool call
                        try:
                            args = json.loads(tool_call.function.arguments)
                            edit_proposal = args.get("content")
                            if edit_proposal:
                                print(f"✅ Using Qwen fallback (length: {len(edit_proposal)} chars)")
                        except json.JSONDecodeError as e:
                            print(f"❌ Failed to parse Qwen tool call: {e}")
                            
                    except Exception as e:
                        import traceback
                        print(f"❌ GPT OSS report update failed: {type(e).__name__}")
                        print(f"  Error: {str(e)[:500]}")
                        print(f"  Falling back to Qwen tool call...")
                        traceback.print_exc()
                        print(f"{'='*80}\n")
                        # Fallback to Qwen's tool call
                        try:
                            args = json.loads(tool_call.function.arguments)
                            edit_proposal = args.get("content")
                            if edit_proposal:
                                print(f"✅ Using Qwen fallback (length: {len(edit_proposal)} chars)")
                        except json.JSONDecodeError as e:
                            print(f"❌ Failed to parse Qwen tool call: {e}")
                elif tool_call.function.name == search_tool_name:
                    print(f"⚠️ Ignoring unexpected {search_tool_name} in follow-up turn")
                else:
                    print(f"⚠️ Unexpected tool call: {tool_call.function.name}")
        
        # DEBUG: Log final state before returning
        print(f"\n{'='*80}")
        print(f"🔍 DEBUG: Final Response State")
        print(f"{'='*80}")
        print(f"Tool calls detected: {len(tool_calls) if tool_calls else 0}")
        print(f"Edit proposal exists: {edit_proposal is not None}")
        print(f"Edit proposal length: {len(edit_proposal) if edit_proposal else 0} chars")
        print(f"Response text exists: {response_text is not None and response_text.strip() != ''}")
        print(f"Response text length: {len(response_text) if response_text else 0} chars")
        
        # If no tool calls but Qwen might have provided content in response
        if not edit_proposal and not tool_calls:
            print(f"💬 Chat response only (no tool calls)")
            print(f"  Response length: {len(response_text) if response_text else 0} chars")
            print(f"  Response preview: {response_text[:300] if response_text else 'None'}...")
        
        # Check if response_text contains report-like content (potential issue)
        if response_text and edit_proposal:
            # Check for common report indicators in response_text
            report_indicators = ['Comparison:', 'Findings:', 'Impression:', '---', '-----']
            found_indicators = [ind for ind in report_indicators if ind in response_text]
            if found_indicators:
                print(f"\n⚠️ WARNING: Response text contains report-like content!")
                print(f"  Found indicators: {found_indicators}")
                print(f"  Response text snippet: {response_text[:500]}...")
        
        # Filter out Qwen's thinking tokens if present in text response
        sources_used_urls: List[str] = []
        if response_text:
            original_length = len(response_text)
            response_text = re.sub(
                r'<think>.*?</think>',
                '',
                response_text,
                flags=re.DOTALL | re.IGNORECASE
            ).strip()
            if len(response_text) != original_length:
                print(f"  └─ Removed thinking tokens (length changed: {original_length} -> {len(response_text)})")
            # Extract and strip the LLM-declared source URLs block
            sources_used_match = re.search(
                r'\s*<SOURCES_USED>(.*?)</SOURCES_USED>\s*',
                response_text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            if sources_used_match:
                try:
                    sources_used_urls = json.loads(sources_used_match.group(1).strip())
                    if not isinstance(sources_used_urls, list):
                        sources_used_urls = []
                except (json.JSONDecodeError, ValueError):
                    sources_used_urls = []
                response_text = (
                    response_text[: sources_used_match.start()].rstrip()
                    + response_text[sources_used_match.end():]
                ).strip()
                print(f"  └─ Extracted SOURCES_USED: {sources_used_urls}")
            meta_stripped = _strip_report_chat_meta_phrases(response_text)
            if meta_stripped != response_text:
                print(f"  └─ Stripped chat meta phrases (length {len(response_text)} -> {len(meta_stripped)})")
            response_text = meta_stripped
            if response_text:
                stripped_refs = re.sub(r"\s*\[\d+\]", "", response_text).strip()
                if stripped_refs != response_text:
                    print(f"  └─ Stripped spurious [n] refs")
                response_text = stripped_refs

        if not response_text and edit_proposal:
            response_text = "I've drafted the changes for you. Please review and apply them below."
            print(f"  └─ Set default response text (edit_proposal exists but no response_text)")
        
        print(f"\n📤 Returning response:")
        print(f"  Response text length: {len(response_text) if response_text else 0} chars")
        print(f"  Edit proposal length: {len(edit_proposal) if edit_proposal else 0} chars")
        print(f"{'='*80}\n")
        
        # Bank any new Perplexity sources into the cumulative pool for this report session
        if perplexity_sources:
            pool: List[Dict[str, Any]] = enhancement_data.setdefault("chat_perplexity_pool", [])
            seen_pool = {normalize_evidence_url_for_dedupe(s.get("url", "")) for s in pool}
            for src in perplexity_sources:
                key = normalize_evidence_url_for_dedupe(src.get("url", ""))
                if key and key not in seen_pool:
                    seen_pool.add(key)
                    pool.append(src)

        # Merge: current-turn Perplexity first (most relevant to this question),
        # then any previously accumulated Perplexity hits, then pre-computed guideline sources.
        # Deduplication is handled by _merge_chat_source_lists; cap at 3.
        accumulated_perplexity = enhancement_data.get("chat_perplexity_pool", [])
        all_perplexity = _merge_chat_source_lists(perplexity_sources, accumulated_perplexity)
        candidate_sources = _merge_chat_source_lists(all_perplexity, guideline_sources)

        # Filter to only sources the LLM declared it used, when available
        if sources_used_urls:
            used_keys = {normalize_evidence_url_for_dedupe(u) for u in sources_used_urls if u}
            filtered = [
                s for s in candidate_sources
                if normalize_evidence_url_for_dedupe(s.get("url", "")) in used_keys
            ]
            sources = filtered[:3] if filtered else candidate_sources[:3]
            print(f"   SOURCES_USED filter: {len(sources_used_urls)} declared → {len(filtered)} matched (pool: {len(accumulated_perplexity)}, guideline: {len(guideline_sources)})")
        else:
            sources = candidate_sources[:3]
            print(f"   Sources returned: {len(sources)} (no SOURCES_USED block; perplexity pool: {len(accumulated_perplexity)}, guideline: {len(guideline_sources)})")

        # Strip patch from actions_applied for frontend—patch is used only for updater prompt, not displayed
        actions_for_frontend = (
            [{"title": a.get("title", ""), "details": a.get("details", "")} for a in actions_applied]
            if actions_applied else actions_applied
        )

        return {
            "success": True,
            "response": response_text,
            "edit_proposal": edit_proposal,
            "actions_applied": actions_for_frontend,
            "sources": sources,
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/reports/{report_id}/apply-actions")
async def apply_report_actions(
    report_id: str,
    request: ApplyActionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Apply selected enhancement actions by regenerating the report content with AI.
    Creates a new report version without refreshing the enhancement cache.
    """
    try:
        report = get_report(db, report_id, user_id=str(current_user.id))
        if not report:
            return {"success": False, "error": "Report not found"}

        if not request.actions:
            return {"success": False, "error": "No actions provided"}

        actions_payload = [action.model_dump() for action in request.actions]
        actionable = [action for action in actions_payload if action.get("patch") and action["patch"].strip()]
        if not actionable:
            return {"success": False, "error": "No actionable patches provided"}

        try:
            new_content = await regenerate_report_with_actions(
                report=report,
                actions=actionable,
                additional_context=request.additional_context,
                current_user=current_user
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        report.report_content = new_content
        db.commit()
        db.refresh(report)

        version = create_report_version(
            db,
            report=report,
            actions_applied=actionable,
            notes="Applied enhancement actions"
        )

        return {
            "success": True,
            "report": report.to_dict(),
            "version": version.to_dict()
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}


@app.post("/api/reports/{report_id}/compare")
async def compare_with_priors(
    report_id: str,
    request: ComparisonRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Compare current report to prior reports with guideline integration."""
    report = get_report(db, report_id, user_id=str(current_user.id))
    if not report:
        return {"success": False, "error": "Report not found"}
    
    if not request.prior_reports:
        return {"success": False, "error": "No prior reports provided"}
    
    try:
        guidelines_data = ENHANCEMENT_RESULTS.get(report_id, {}).get('guidelines', [])
        
        from .enhancement_utils import analyze_interval_changes
        result = await analyze_interval_changes(
            current_report=report.report_content,
            prior_reports=request.prior_reports,
            guidelines_data=guidelines_data
        )
        
        # Cache result
        ENHANCEMENT_RESULTS[f"{report_id}_comparison"] = result.model_dump()
        
        return {
            "success": True,
            "comparison": result.model_dump(),
            "used_guidelines": len(guidelines_data) > 0
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


@app.post("/api/reports/{report_id}/apply-comparison")
async def apply_comparison_revision(
    report_id: str,
    request: ApplyComparisonRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Apply revised report from comparison analysis directly to database."""
    report = get_report(db, report_id, user_id=str(current_user.id))
    if not report:
        return {"success": False, "error": "Report not found"}
    
    # Update report content
    report.report_content = request.revised_report
    db.commit()
    
    # Create version in history
    create_report_version(
        db,
        report=report,
        actions_applied=None,
        notes="Comparison edit"
    )
    
    return {
        "success": True,
        "updated_content": request.revised_report,
        "version_created": True
    }


@app.get("/api/reports/{report_id}/versions")
async def list_report_versions_endpoint(
    report_id: str,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Return report version history for the current user."""
    versions = get_report_versions(
        db=db,
        report_id=report_id,
        user_id=str(current_user.id),
        limit=max(1, min(limit, 100))
    )
    if not versions:
        return {"success": True, "versions": []}

    payload = []
    for version in versions:
        version_dict = version.to_dict()
        # Use the actual is_current flag from the database
        version_dict["report_content_preview"] = version.report_content[:400]
        payload.append(version_dict)

    return {"success": True, "versions": payload}


@app.get("/api/reports/{report_id}/versions/{version_id}")
async def get_report_version_endpoint(
    report_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Return details for a specific report version."""
    version = get_report_version(
        db=db,
        report_id=report_id,
        version_id=version_id,
        user_id=str(current_user.id)
    )
    if not version:
        return {"success": False, "error": "Version not found"}

    version_dict = version.to_dict()
    report = get_report(db, report_id, user_id=str(current_user.id))
    version_dict["is_current"] = bool(report and version.version_number == max(
        (v.version_number for v in report.versions), default=version.version_number
    ))
    return {"success": True, "version": version_dict}


@app.post("/api/reports/{report_id}/versions/{version_id}/restore")
async def restore_report_version_endpoint(
    report_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Restore a report to a specific version without creating a new snapshot."""
    try:
        report = get_report(db, report_id, user_id=str(current_user.id))
        if not report:
            return {"success": False, "error": "Report not found"}

        version = get_report_version(
            db=db,
            report_id=report_id,
            version_id=version_id,
            user_id=str(current_user.id)
        )
        if not version:
            return {"success": False, "error": "Version not found"}

        # Update report content
        report.report_content = version.report_content
        db.commit()
        db.refresh(report)

        # Set this version as the current one (without creating a new version)
        set_current_report_version(db, report_id=report_id, version_id=version_id)

        ENHANCEMENT_RESULTS.pop(report_id, None)

        return {
            "success": True,
            "report": report.to_dict(),
            "version": version.to_dict()
        }
    except Exception as exc:
        db.rollback()
        return {"success": False, "error": str(exc)}


@app.put("/api/reports/{report_id}/update")
async def update_report_content(
    report_id: str,
    request: UpdateReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update report content (for applying suggestions)
    """
    try:
        # Get report
        report = get_report(db, report_id, user_id=str(current_user.id))
        if not report:
            return {"success": False, "error": "Report not found"}
        
        # Update content
        report.report_content = request.content
        
        # Clear validation_status since content changed (manual/chat edits invalidate previous validation)
        # Validation only applies to the original AI-generated content
        report.validation_status = None
        
        db.commit()
        db.refresh(report)

        version = None
        try:
            # Determine notes based on edit source
            edit_source = request.edit_source or "manual"
            _criterion_labels = {
                "recommendations": "Recommendations",
                "anatomical_accuracy": "Anatomical Accuracy",
                "report_completeness": "Report Completeness",
                "clinical_relevance": "Clinical Relevance",
                "clinical_flagging": "Clinical Flagging",
                "diagnostic_fidelity": "Diagnostic Fidelity",
            }
            if edit_source == "chat":
                notes = "Chat edit"
            elif edit_source == "audit_suggested_replacement" and request.audit_criterion:
                label = _criterion_labels.get(request.audit_criterion, request.audit_criterion)
                if request.original_span and request.replacement_span:
                    orig = request.original_span[:60]
                    repl = request.replacement_span[:60]
                    notes = f"Audit fix ({label}): '{orig}' → '{repl}'"
                elif request.replacement_span:
                    preview = request.replacement_span[:60]
                    notes = f"Audit insertion ({label}): '{preview}...'"
                else:
                    notes = f"Audit-suggested fix ({label})"
            else:
                notes = "Manual content update"
            
            version = create_report_version(
                db,
                report=report,
                actions_applied=None,
                notes=notes
            )
        except Exception as exc:
            print(f"Warning: failed to create report version snapshot for manual update: {exc}")
        
        ENHANCEMENT_RESULTS.pop(report_id, None)

        return {
            "success": True,
            "report": report.to_dict(),
            "version": version.to_dict() if version else None
        }
        
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}


# ============================================================================
# SPEECH TO TEXT API ENDPOINTS
# ============================================================================

def process_dictation_transcript(transcript: str) -> str:
    """
    Post-process Deepgram transcript to convert dictation commands to actual punctuation.
    
    Deepgram returns dictation commands as literal strings:
    - "new line" → "<\\n>" (literal string with backslash-n, not actual newline)
    - "new paragraph" → "<\\n\\n>" (literal string)
    - "full stop" is not recognized by Deepgram, but we can convert it for British English users
    
    This function converts these to actual characters.
    """
    if not transcript:
        return transcript

    processed = transcript

    # Convert Deepgram's literal dictation command strings to actual characters
    # Deepgram returns these as literal strings like "<\n>" (backslash followed by n)
    # Replace <\n\n> (new paragraph) first, then <\n> (new line)
    processed = processed.replace('<\\n\\n>', '\n\n')  # New paragraph
    processed = processed.replace('<\\n>', '\n')  # New line


    # Convert "full stop" / "fullstop" to period (British English — Deepgram
    # only recognises "period" as a dictation command).
    processed = re.sub(r'\bfull\s+stop\b', '.', processed, flags=re.IGNORECASE)
    processed = re.sub(r'\bfullstop\b', '.', processed, flags=re.IGNORECASE)

    return processed


@app.websocket("/api/transcribe")
async def websocket_transcribe(websocket: WebSocket):
    """
    WebSocket endpoint for real-time speech-to-text transcription
    Uses Deepgram API for medical dictation
    Token should be passed as query parameter: ?token=...
    """
    await websocket.accept()
    print("WebSocket transcription connection accepted")
    
    # Extract token from query parameters (FastAPI WebSocket doesn't support query params in signature)
    token = websocket.query_params.get("token")
    
    # Try to get user from token if provided
    user_settings = {}
    if token:
        try:
            from jose import jwt, JWTError
            import uuid as uuid_lib
            
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("sub")
            if user_id:
                db = SessionLocal()
                try:
                    user_uuid = uuid_lib.UUID(user_id) if isinstance(user_id, str) else user_id
                    user = db.query(User).filter(User.id == user_uuid, User.is_active == True).first()
                    if user:
                        user_settings = user.settings or {}
                finally:
                    db.close()
        except (JWTError, ValueError, Exception) as e:
            print(f"Error authenticating WebSocket: {e}")
            # Continue with env fallback
    
    # Get Deepgram API key from central env (DEEPGRAM_API_KEY)
    deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
    
    if not deepgram_api_key:
        await websocket.send_json({
            "error": "Deepgram API key not configured. Set DEEPGRAM_API_KEY environment variable."
        })
        await websocket.close()
        return

    # pcm=1 signals raw linear16 PCM from AudioContext (used by Chrome where MediaRecorder
    # produces silent webm frames). Without pcm=1 Deepgram auto-detects the container format.
    # sr = actual AudioContext.sampleRate from the client device (varies by hardware:
    # built-in mic → 16000/44100, headset/USB → 44100/48000). Default 16000 for safety.
    use_pcm = websocket.query_params.get("pcm") == "1"
    pcm_sample_rate = int(websocket.query_params.get("sr", "16000"))
    
    # Connect to Deepgram WebSocket API with Nova-3 Medical model
    # Using nova-3-medical for optimized medical transcription
    # punctuate=true is required for dictation commands (full stop, new line, etc.) to work
    # Radiology keyterms — boost recall on terms the model may mishear in dictation
    radiology_keyterms = [
        "spiculated", "appendicolith", "periappendiceal", "Bosniak", "hydronephrosis",
        "haemorrhage", "oedema", "atelectasis", "consolidation", "ground-glass opacity",
        "pneumothorax", "pleural effusion", "lymphadenopathy", "cardiomegaly",
        "hepatomegaly", "splenomegaly", "pericardial effusion", "aortic aneurysm",
        "dissection", "pulmonary embolism", "deep vein thrombosis", "mesenteric ischaemia",
        "cholecystitis", "choledocholithiasis", "pancreatitis", "appendicitis",
        "diverticulitis", "intussusception", "volvulus", "ileus", "pneumoperitoneum",
        "ascites", "retroperitoneal", "mediastinal", "hilar", "subphrenic",
        "interstitial", "parenchymal", "cortical", "corticomedullary",
        "nephrolithiasis", "ureterolithiasis", "hydronephrosis", "hydroureter",
        "sacroiliitis", "spondylolisthesis", "spondylosis", "foraminal stenosis",
        "canal stenosis", "listhesis", "discitis", "vertebral body",
    ]
    keyterm_params = "&".join(
        f"keyterm={term.replace(' ', '%20')}" for term in radiology_keyterms
    )
    pcm_params = f"&encoding=linear16&sample_rate={pcm_sample_rate}&channels=1" if use_pcm else ""
    deepgram_url = (
        f"wss://api.deepgram.com/v1/listen"
        f"?model=nova-3-medical"
        f"&language=en-GB"
        f"&smart_format=true"
        f"&measurements=true"
        f"&dictation=true"
        f"&punctuate=true"
        f"&interim_results=true"
        f"&endpointing=300"
        f"&utterance_end_ms=1000"
        f"{pcm_params}"
        f"&{keyterm_params}"
    )
    print(f"🎙️ Deepgram mode: {'PCM linear16 @ ' + str(pcm_sample_rate) + ' Hz' if use_pcm else 'auto-detect container'}")
    
    try:
        # Open connection to Deepgram WebSocket
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Token {deepgram_api_key}"}
            
            async with session.ws_connect(deepgram_url, headers=headers) as dg_ws:
                print("✅ Connected to Deepgram WebSocket")
                
                async def forward_to_deepgram():
                    """Forward audio from client to Deepgram"""
                    try:
                        while True:
                            data = await websocket.receive_bytes()
                            await dg_ws.send_bytes(data)
                    except WebSocketDisconnect:
                        print("❌ Client disconnected")
                        await dg_ws.close()

                async def forward_from_deepgram():
                    """Forward transcripts from Deepgram to client"""
                    try:
                        async for msg in dg_ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                transcript_data = json.loads(msg.data)

                                # Parse Deepgram response
                                if transcript_data.get("type") == "Results":
                                    alternatives = transcript_data.get("channel", {}).get("alternatives", [])
                                    if alternatives:
                                        raw_transcript = alternatives[0].get("transcript", "")
                                        is_final = transcript_data.get("is_final", False)
                                        speech_final = transcript_data.get("speech_final", False)

                                        # Process dictation commands (convert <\n> to actual newlines, etc.)
                                        transcript = process_dictation_transcript(raw_transcript)

                                        # Only log finalised, non-empty utterances — skip interim / empty frames.
                                        if is_final and transcript:
                                            print(f"📝 {transcript!r} (speech_final={speech_final})")

                                        if transcript:
                                            await websocket.send_json({
                                                "transcript": transcript,
                                                "is_final": is_final,
                                                "speech_final": speech_final
                                            })
                                elif transcript_data.get("type") == "UtteranceEnd":
                                    # Signal the frontend that a natural utterance boundary was detected
                                    await websocket.send_json({"utterance_end": True})
                                elif transcript_data.get("type") == "error":
                                    error_msg = transcript_data.get("msg", "Unknown error")
                                    print(f"❌ Deepgram error: {error_msg}")
                                    await websocket.send_json({"error": error_msg})
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                print(f"❌ WebSocket error: {msg.data}")
                                    
                    except Exception as e:
                        print(f"❌ Error receiving from Deepgram: {e}")
                        import traceback
                        traceback.print_exc()
                        await websocket.send_json({"error": str(e)})
                        await websocket.close()
                
                # Run both forwarders concurrently
                await asyncio.gather(
                    forward_to_deepgram(),
                    forward_from_deepgram()
                )
    
    except Exception as e:
        print(f"Error in WebSocket transcription: {e}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({"error": str(e)})
        except:
            pass
        await websocket.close()


@app.websocket("/api/transcribe/whisper")
async def websocket_transcribe_whisper(websocket: WebSocket):
    """
    WebSocket endpoint for speech-to-text using Groq Whisper Large v3 Turbo.
    Buffers incoming WebM audio chunks and transcribes on silence detection.
    Returns the same message format as the Deepgram endpoint.
    """
    await websocket.accept()
    print("🎙️ Whisper WebSocket connection accepted")

    # Auth — same pattern as Deepgram endpoint
    token = websocket.query_params.get("token")
    user_settings = {}
    if token:
        try:
            from jose import jwt, JWTError
            import uuid as uuid_lib
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("sub")
            if user_id:
                db = SessionLocal()
                try:
                    user_uuid = uuid_lib.UUID(user_id) if isinstance(user_id, str) else user_id
                    user = db.query(User).filter(User.id == user_uuid, User.is_active == True).first()
                    if user:
                        user_settings = user.settings or {}
                finally:
                    db.close()
        except Exception as e:
            print(f"Whisper WS auth error: {e}")

    groq_api_key = get_system_api_key("groq", "GROQ_API_KEY")
    if not groq_api_key:
        await websocket.send_json({"error": "Groq API key not configured."})
        await websocket.close()
        return

    import io
    from groq import Groq as GroqClient

    # WebM requires the EBML header (first chunk) prepended to every segment sent to Whisper.
    webm_header: bytes | None = None
    segment_buffer = bytearray()
    MIN_BUFFER_BYTES = 8000   # ~0.25 s of audio — skip near-empty segments
    INTERVAL = 5.0            # seconds between transcription calls during active recording
    disconnect_event = asyncio.Event()

    async def call_whisper(audio_bytes: bytes) -> str | None:
        try:
            client = GroqClient(api_key=groq_api_key)
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = "audio.webm"
            result = client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3-turbo",
                language="en",
                response_format="text",
                prompt=(
                    "Medical radiology dictation. Terms: consolidation, ground-glass opacity, "
                    "pneumothorax, atelectasis, pleural effusion, lymphadenopathy, spiculated, "
                    "Bosniak, appendicolith, periappendiceal, hydronephrosis, haemorrhage, oedema."
                ),
            )
            text = result.strip() if isinstance(result, str) else (result.text or "").strip()
            return text if text else None
        except Exception as e:
            print(f"Whisper API error: {e}")
            return None

    async def send_transcript(text: str) -> bool:
        """Send transcript to frontend. Returns False if the connection is gone."""
        processed = process_dictation_transcript(text)
        print(f"🎙️ Whisper result: '{processed}'")
        try:
            await websocket.send_json({
                "transcript": processed,
                "is_final": True,
                "speech_final": True,
            })
            return True
        except Exception:
            return False

    async def drain_buffer() -> None:
        """Transcribe and send whatever is left in the buffer."""
        if segment_buffer and webm_header and len(segment_buffer) > MIN_BUFFER_BYTES:
            segment = bytes(segment_buffer)
            segment_buffer.clear()
            audio = webm_header + segment
            print(f"🎙️ Draining {len(audio)} bytes to Whisper")
            transcript = await call_whisper(audio)
            if transcript:
                await send_transcript(transcript)

    async def receive_audio():
        nonlocal webm_header
        try:
            while True:
                data = await websocket.receive_bytes()
                if webm_header is None:
                    webm_header = bytes(data)
                segment_buffer.extend(data)
        except WebSocketDisconnect:
            print("🎙️ Whisper client disconnected")
        finally:
            disconnect_event.set()

    async def process_periodically():
        """Every INTERVAL seconds, transcribe accumulated audio.
        On disconnect, drain any remaining buffer immediately."""
        while True:
            try:
                # Wait up to INTERVAL seconds; exit early if disconnected
                await asyncio.wait_for(disconnect_event.wait(), timeout=INTERVAL)
                # Disconnect happened — drain remaining buffer then stop
                await drain_buffer()
                break
            except asyncio.TimeoutError:
                # Interval elapsed — process current segment
                if segment_buffer and webm_header and len(segment_buffer) > MIN_BUFFER_BYTES:
                    segment = bytes(segment_buffer)
                    segment_buffer.clear()
                    audio = webm_header + segment
                    print(f"🎙️ Sending {len(audio)} bytes to Whisper (periodic)")
                    transcript = await call_whisper(audio)
                    if transcript:
                        ok = await send_transcript(transcript)
                        if not ok:
                            break

    try:
        await asyncio.gather(receive_audio(), process_periodically())
    except Exception as e:
        print(f"Whisper WS error: {e}")
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
        await websocket.close()


@app.post("/api/transcribe/pre-recorded")
async def transcribe_pre_recorded(
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Transcribe pre-recorded audio using Deepgram's pre-recorded API
    Processes the entire audio file at once for better formatting
    """
    # Get Deepgram API key from central env (DEEPGRAM_API_KEY)
    deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
    
    if not deepgram_api_key:
        raise HTTPException(
            status_code=400,
            detail="Deepgram API key not configured. Set DEEPGRAM_API_KEY environment variable."
        )
    
    try:
        # Read audio file
        audio_data = await audio.read()
        
        # Check if audio is empty
        if len(audio_data) == 0:
            raise HTTPException(
                status_code=400,
                detail="Empty audio file"
            )
        
        # Call Deepgram REST API
        deepgram_url = "https://api.deepgram.com/v1/listen"
        params = {
            "model": "nova-3-medical",
            "language": "en-GB",
            "smart_format": "true",
            "measurements": "true",
            "dictation": "true",
            "punctuate": "true"  # Required for dictation commands (full stop, new line, etc.) to work
        }
        headers = {
            "Authorization": f"Token {deepgram_api_key}",
            "Content-Type": audio.content_type or "audio/webm"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                deepgram_url,
                params=params,
                headers=headers,
                data=audio_data,
                timeout=aiohttp.ClientTimeout(total=60.0)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"Deepgram API error: {error_text}"
                    )
                
                result = await response.json()
        
        # Extract transcript from Deepgram response
        raw_transcript = ""
        if result.get("results") and result["results"].get("channels"):
            alternatives = result["results"]["channels"][0].get("alternatives", [])
            if alternatives:
                raw_transcript = alternatives[0].get("transcript", "")
        
        # Process dictation commands (convert <\n> to actual newlines, etc.)
        transcript = process_dictation_transcript(raw_transcript)
        
        return {
            "success": True,
            "transcript": transcript
        }
        
    except aiohttp.ClientError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error communicating with Deepgram: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error transcribing audio: {str(e)}"
        )


# ============================================================================
# REPORT AUDIT / QA API ENDPOINTS
# ============================================================================

@app.post("/api/audit")
async def run_audit(
    request: AuditRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Run Phase 1 audit (6 report-integrity criteria).

    Phase 2 (3 guideline-compliance criteria) runs inside /enhance after S4 synthesis.
    """
    try:
        _audit_t0 = time.perf_counter()
        if not request.report_content or not request.report_content.strip():
            raise HTTPException(status_code=400, detail="Report content is required")

        if request.report_id:
            await _ensure_enhancement_loaded(request.report_id, db)

        print(
            f"[FLOW_TIMING] audit: begin report_id={request.report_id!r} "
            f"content_chars={len(request.report_content)}"
        )

        # Load findings_input + other_variables for input_fidelity
        findings_input = ""
        other_variables: dict = {}
        urgency_signals: list = []
        if request.report_id:
            _report = get_report(db, request.report_id, user_id=str(current_user.id))
            if _report and _report.input_data and isinstance(_report.input_data, dict):
                variables = _report.input_data.get("variables", {})
                if isinstance(variables, dict):
                    findings_input = variables.get("FINDINGS", "").strip()
                    other_variables = {k: v for k, v in variables.items() if k != "FINDINGS"}
            _enh = ENHANCEMENT_RESULTS.get(request.report_id or "")
            if _enh:
                urgency_signals = _enh.get("urgency_signals", [])

        from .enhancement_utils import run_audit_phase1, run_full_audit

        _enh = ENHANCEMENT_RESULTS.get(request.report_id or "")
        has_synthesis = bool(_enh and _enh.get("guidelines"))

        try:
            if has_synthesis:
                prefetch_output = _enh.get("prefetch_output")
                consolidated_findings: list = []
                finding_short_labels: list = []
                if prefetch_output and hasattr(prefetch_output, "consolidated_findings"):
                    consolidated_findings = prefetch_output.consolidated_findings or []
                    finding_short_labels = prefetch_output.finding_short_labels or []
                elif prefetch_output and isinstance(prefetch_output, dict):
                    consolidated_findings = prefetch_output.get("consolidated_findings", [])
                    finding_short_labels = prefetch_output.get("finding_short_labels", [])
                else:
                    pf_json = _enh.get("prefetch_output_json", {})
                    consolidated_findings = pf_json.get("consolidated_findings", [])
                    finding_short_labels = pf_json.get("finding_short_labels", [])

                result = await run_full_audit(
                    report_content=request.report_content,
                    scan_type=request.scan_type or "",
                    clinical_history=request.clinical_history or "",
                    findings_input=findings_input,
                    other_variables=other_variables,
                    urgency_signals=urgency_signals,
                    synthesis_cards=_enh.get("guidelines", []),
                    consolidated_findings=consolidated_findings,
                    finding_short_labels=finding_short_labels,
                )
            else:
                result = await run_audit_phase1(
                    report_content=request.report_content,
                    scan_type=request.scan_type or "",
                    clinical_history=request.clinical_history or "",
                    findings_input=findings_input,
                    other_variables=other_variables,
                    urgency_signals=urgency_signals,
                )
        except Exception as e:
            print(f"Audit model error: {type(e).__name__}: {str(e)}")
            raise HTTPException(
                status_code=422,
                detail=f"Audit model returned malformed response: {str(e)[:200]}"
            )

        # Save to database
        audit_id = None
        if request.report_id:
            report = get_report(db, request.report_id, user_id=str(current_user.id))
            if report:
                audit = create_report_audit(
                    db=db,
                    report=report,
                    user_id=str(current_user.id),
                    audit_result=result,
                    scan_type=request.scan_type or "",
                    clinical_history=request.clinical_history or "",
                    model_used="zai-glm-4.7",
                    audited_candidate_model=request.audited_candidate_model,
                )
                audit_id = str(audit.id)

        _audit_ms = int((time.perf_counter() - _audit_t0) * 1000)
        print(
            f"[FLOW_TIMING] audit: end report_id={request.report_id!r} "
            f"total_wall_ms={_audit_ms} criteria={len(result.get('criteria', []))}"
        )

        return {
            "success": True,
            "audit_id": audit_id,
            "partial": result.get("partial", False),
            **result,
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error in audit endpoint: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/audit/phase2")
async def run_audit_phase2_endpoint(
    request: AuditRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-run Phase 2 audit (3 guideline-compliance criteria) against current report content.

    Uses stored synthesis cards from ENHANCEMENT_RESULTS or DB — does NOT re-run S4.
    Called by the frontend on re-audit to refresh stale Phase 2 criteria.
    """
    try:
        _p2_t0 = time.perf_counter()
        if not request.report_content or not request.report_content.strip():
            raise HTTPException(status_code=400, detail="Report content is required")

        report_id = request.report_id
        if not report_id:
            raise HTTPException(status_code=400, detail="report_id is required for Phase 2 re-audit")

        await _ensure_enhancement_loaded(report_id, db)
        _enh = ENHANCEMENT_RESULTS.get(report_id)
        if not _enh:
            return {"success": False, "error": "No enhancement data found — run /enhance first", "criteria": []}

        synthesis_cards = _enh.get("guidelines", [])
        if not synthesis_cards:
            return {"success": False, "error": "No synthesis cards available", "criteria": []}

        prefetch_output = _enh.get("prefetch_output")
        urgency_signals = _enh.get("urgency_signals", [])
        consolidated_findings: list = []
        finding_short_labels: list = []
        if prefetch_output and hasattr(prefetch_output, "consolidated_findings"):
            consolidated_findings = prefetch_output.consolidated_findings or []
            finding_short_labels = prefetch_output.finding_short_labels or []
        elif prefetch_output and isinstance(prefetch_output, dict):
            consolidated_findings = prefetch_output.get("consolidated_findings", [])
            finding_short_labels = prefetch_output.get("finding_short_labels", [])
        else:
            pf_json = _enh.get("prefetch_output_json", {})
            consolidated_findings = pf_json.get("consolidated_findings", [])
            finding_short_labels = pf_json.get("finding_short_labels", [])

        scan_type = request.scan_type or ""
        clinical_history = request.clinical_history or ""

        print(
            f"[FLOW_TIMING] audit_phase2: begin report_id={report_id!r} "
            f"content_chars={len(request.report_content)} synth_cards={len(synthesis_cards)}"
        )

        from .enhancement_utils import run_audit_phase2

        phase2_criteria_list = await run_audit_phase2(
            report_content=request.report_content,
            scan_type=scan_type,
            clinical_history=clinical_history,
            synthesis_cards=synthesis_cards,
            urgency_signals=urgency_signals,
            consolidated_findings=consolidated_findings,
            finding_short_labels=finding_short_labels,
        )

        phase2_criteria_dicts = [
            c.model_dump() if hasattr(c, "model_dump") else c
            for c in phase2_criteria_list
        ]

        # Persist Phase 2 criteria to the latest audit row for this report.
        # For dual-candidate quick reports, target the row tagged with the
        # re-audit's candidate model so criteria land in the correct slot.
        audit_id = None
        if phase2_criteria_dicts:
            try:
                from .database.crud import append_audit_criteria
                from .database.models import ReportAudit as _RA

                _audit_query = (
                    db.query(_RA)
                    .filter(_RA.report_id == uuid.UUID(report_id))
                )
                if request.audited_candidate_model:
                    _audit_query = _audit_query.filter(
                        _RA.audited_candidate_model == request.audited_candidate_model
                    )
                else:
                    _audit_query = _audit_query.filter(
                        _RA.audited_candidate_model.is_(None)
                    )
                latest_audit = _audit_query.order_by(_RA.created_at.desc()).first()
                if latest_audit:
                    audit_id = str(latest_audit.id)
                    existing_names = {
                        c.criterion for c in latest_audit.criteria
                    }
                    new_only = [
                        c for c in phase2_criteria_dicts
                        if c.get("criterion") not in existing_names
                    ]
                    if new_only:
                        from .enhancement_utils import merge_audit_phases
                        merged = merge_audit_phases(
                            {"criteria": [
                                {"criterion": c.criterion, "status": c.status}
                                for c in latest_audit.criteria
                            ]},
                            new_only,
                        )
                        append_audit_criteria(
                            db, latest_audit.id, new_only,
                            merged.get("overall_status", "pass"),
                        )
            except Exception as _pe:
                print(f"[AUDIT] Phase 2 re-audit: DB persist failed: {_pe}")

        _p2_ms = int((time.perf_counter() - _p2_t0) * 1000)
        print(
            f"[FLOW_TIMING] audit_phase2: end report_id={report_id!r} "
            f"total_wall_ms={_p2_ms} criteria={len(phase2_criteria_dicts)}"
        )

        return {
            "success": True,
            "audit_id": audit_id,
            "criteria": phase2_criteria_dicts,
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error in audit phase2 endpoint: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/audit/{audit_id}/criteria/{criterion}")
async def acknowledge_audit_criterion(
    audit_id: str,
    criterion: str,
    request: AcknowledgeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Acknowledge a specific criterion on an audit.
    Marks it as reviewed with the specified resolution method.
    """
    try:
        valid_criteria = [
            "anatomical_accuracy", "clinical_relevance", "recommendations",
            "clinical_flagging", "report_completeness", "diagnostic_fidelity",
            "input_fidelity", "scan_coverage", "characterisation_gap",
        ]
        legacy_audit_criteria = ("language_quality",)

        if criterion not in valid_criteria and criterion not in legacy_audit_criteria:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid criterion. Must be one of: {', '.join(valid_criteria)}"
            )
        
        result = acknowledge_criterion(
            db=db,
            audit_id=audit_id,
            criterion=criterion,
            resolution_method=request.resolution_method,
            user_id=str(current_user.id)
        )
        
        if not result.get("acknowledged"):
            raise HTTPException(
                status_code=404,
                detail="Audit or criterion not found, or you don't have permission to modify it"
            )
        
        return {
            "success": True,
            "acknowledged": result["acknowledged"],
            "is_reviewed": result["is_reviewed"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error acknowledging criterion: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reports/{report_id}/audits")
async def list_report_audits(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all audits for a specific report.
    Returns audits sorted by created_at DESC.
    """
    try:
        audits = get_report_audits(
            db=db,
            report_id=report_id,
            user_id=str(current_user.id)
        )
        
        return {
            "success": True,
            "audits": [audit.to_dict() for audit in audits]
        }
        
    except Exception as e:
        import traceback
        print(f"Error getting report audits: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


app.include_router(canvas_router)
# Experimental planning/execution pipeline (/api/v2/*). Product report generation uses monolithic
# prompts + /api/chat + generate_auto_report; keep router mounted for future work and manual API tests.
app.include_router(agentic_router)

# Quick-report production pipeline (/api/quick-report/*). Ephemeral-skill-sheet
# path — deliberately separate from the legacy /api/chat radiology_report flow
# (which remains the default quick-report path and the fallback) and from the
# /api/quick-report-proto/* stress-test surface. See quick_report_api.py +
# project_quick_report_analyser.md for architecture and phasing.
from .quick_report_api import router as quick_report_router
app.include_router(quick_report_router)


def main():
    """Main entry point for running the server"""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()

