from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, File, UploadFile, HTTPException
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Optional, List, Any
import os
import re
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
from .email_utils import send_magic_link_email
from .encryption import encrypt_api_key, decrypt_api_key, get_user_api_key, get_system_api_key
from .enhancement_utils import (
    extract_consolidated_findings,
    search_guidelines_for_findings,
    analyze_report_completeness,
    generate_auto_report,
    generate_templated_report,
)
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
    
    yield
    # Shutdown: nothing to do yet


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
# Enhancement and completeness analysis cache
# -----------------------------------------------------------------------------
ENHANCEMENT_RESULTS: Dict[str, Dict[str, Any]] = {}  # Stores findings + guidelines
COMPLETENESS_RESULTS: Dict[str, Dict[str, Any]] = {}
COMPLETENESS_TASKS: Dict[str, asyncio.Task] = {}


def reset_completeness_state(report_id: str):
    task = COMPLETENESS_TASKS.pop(report_id, None)
    if task and not task.done():
        task.cancel()
    COMPLETENESS_RESULTS.pop(report_id, None)
    ENHANCEMENT_RESULTS.pop(report_id, None)  # Also clear enhancement data


async def run_completeness_async(
    report_id: str,
    report_content: str,
    guidelines_data: List[dict],
    anthropic_api_key: Optional[str]
):
    try:
        result = await analyze_report_completeness(
            report_content,
            guidelines_data,
            anthropic_api_key
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {
            "analysis": "Error analyzing report completeness.",
            "structured": {
                "checklist": [],
                "suggestions": [],
                "feedback": ""
            },
            "warning": str(exc)
        }
    COMPLETENESS_RESULTS[report_id] = result
    COMPLETENESS_TASKS.pop(report_id, None)

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
        patch = (action.get("patch") or "").strip()
        block = [f"{index}. {title}"]
        if details:
            block.append(f"   Details: {details}")
        if patch:
            block.append("   Patch to incorporate:\n" + patch)
        action_lines.append("\n".join(block))

    context_section = (
        f"Additional context:\n{additional_context.strip()}\n\n" if additional_context else ""
    )

    prompt = (
        "CRITICAL: You MUST use British English spelling and terminology throughout all output.\n\n"
        "You are applying SPECIFIC edits to an existing radiology report.\n"
        "Your task is to make SURGICAL changes—modify ONLY what's requested, keep everything else identical.\n\n"
        "CRITICAL EDITING PRINCIPLES:\n"
        "1. Apply ONLY the changes specified in the actions below\n"
        "2. Preserve ALL other content exactly as it appears in the original report\n"
        "3. Maintain the exact formatting, spacing, line breaks, and structure\n"
        "4. Do NOT add separators, decorative lines, or markdown formatting (no '---', '====', '**' for section headers, etc.)\n"
        "5. Do NOT rewrite or rephrase content unless explicitly requested in the actions\n"
        "6. Do NOT change section headers, terminology, or style unless specified\n"
        "7. Make minimal, targeted edits—change only what the action specifies\n\n"
        f"{context_section}"
        "Original report:\n"
        "---------------------\n"
        f"{report.report_content}\n"
        "---------------------\n\n"
        "Actions to apply:\n"
        "---------------------\n"
        f"{chr(10).join(action_lines)}\n"
        "---------------------\n\n"
        "TASK: Apply ONLY the changes specified above. Keep all other content, formatting, and structure identical to the original.\n"
        "Return the complete revised report with surgical edits applied. No separators, no markdown, just the report text."
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
    email: str
    password: str
    full_name: Optional[str] = None

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
    model: str = "zai-glm-4.6"  # Uses zai-glm-4.6 as primary


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
        
        # Always use Claude as primary model (with automatic fallback if Claude fails)
        # Get Anthropic API key for Claude (primary)
        api_key = get_system_api_key('anthropic', 'ANTHROPIC_API_KEY')
        if not api_key:
            return {
                "success": False,
                "error": "Anthropic API key not configured. Please set ANTHROPIC_API_KEY environment variable."
            }
        
        # Generate report using Claude (with automatic fallback to Qwen if Claude fails)
        # Debug: Log signature status
        signature_value = current_user.signature
        print(f"[DEBUG] Auto report - signature present: {signature_value is not None and signature_value.strip() != ''}")
        print(f"[DEBUG] Auto report - signature length: {len(signature_value) if signature_value else 0}")
        
        report_output = await generate_auto_report(
            model="claude",  # Always use Claude (model param kept for API compatibility)
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            api_key=api_key,
            signature=signature_value
        )
        
        # STRUCTURE VALIDATION (synchronous, before saving)
        # DISABLED: Validation checks temporarily disabled - code preserved below
        import os
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
                # Map model names to display names
                model_display = {
                    "claude": "claude",
                    "gemini": "gemini",
                    "qwen": "qwen"
                }.get(request.model, request.model)
                
                saved_report = create_report(
                    db=db,
                    user_id=str(current_user.id),
                    report_type="auto",
                    report_content=report_output.report_content,
                    model_used=model_display,
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
            "claude": "claude-sonnet-4-20250514",
            "gemini": "gemini-2.5-pro",
            "qwen": "qwen/qwen3-32b"
        }.get(request.model, request.model)
        
        return {
            "success": True,
            "report_id": report_id,
            "response": report_output.report_content,
            "model": model_full_name,
            "use_case": use_case_name
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
    """Register a new user and send email verification"""
    try:
        # Check if user exists
        existing_user = get_user_by_email(db, request.email)
        if existing_user:
            return {"success": False, "error": "Email already registered"}
        
        # Create user
        password_hash = get_password_hash(request.password)
        user = create_user(
            db=db,
            email=request.email,
            password_hash=password_hash,
            full_name=request.full_name,
        )
        
        # Generate email verification token
        verification_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        create_reset_token(
            db=db,
            user_id=str(user.id),
            token=verification_token,
            expires_at=expires_at,
            token_type="email_verification",
        )
        
        # Send verification email (or print to console in dev)
        send_magic_link_email(request.email, verification_token, "email_verification")
        
        return {
            "success": True,
            "message": "User created successfully. Please check your email (including spam/junk folder) to verify your account.",
            "user_id": str(user.id)
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
        
        template = create_template(
            db=db,
            name=template_data.name,
            description=template_data.description,
            tags=template_data.tags,
            template_config=template_data.template_config,
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
        # Use new template_config format if provided
        updated_template = update_template(
            db=db,
            template_id=template_id,
            user_id=str(current_user.id),
            name=template_data.name,
            description=template_data.description,
            tags=template_data.tags,
            template_config=template_data.template_config,
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
        report_output_dict = await tm.generate_report_from_config(
            template_config=template.template_config,
            user_inputs=user_inputs,
            user_signature=current_user.signature
        )
        
        # Convert to ReportOutput format for compatibility
        from .enhancement_models import ReportOutput
        report_output = ReportOutput(
            report_content=report_output_dict["report_content"],
            description=report_output_dict["description"],
            scan_type=report_output_dict["scan_type"]
        )
        
        # Optional: Add structure validation for templated reports
        # Controlled by ENABLE_TEMPLATE_STRUCTURE_VALIDATION env var
        import os
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
                # Map model names to display names
                model_display = {
                    "claude": "claude",
                    "gemini": "gemini",
                    "qwen": "qwen"
                }.get(request.model, request.model)
                
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
                    model_used=model_display,
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
            "claude": "claude-sonnet-4-20250514",
            "gemini": "gemini-2.5-pro",
            "qwen": "qwen/qwen3-32b"
        }.get(request.model, request.model)
        
        return {
            "success": True,
            "response": report_output.report_content,
            "model": model_full_name,
            "template_id": str(template.id),
            "report_id": report_id
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
        if len(request.reports) < 2:
            return {"success": False, "error": "At least 2 reports required"}
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
    """Get user settings (LLM API keys now system-wide via environment variables)"""
    # Force a fresh read from database
    db.refresh(current_user)
    settings = current_user.settings or {}
    tag_colors = settings.get('tag_colors', {})
    
    # Check if Deepgram API key exists (only user-configurable key remaining)
    has_deepgram = bool(settings.get('deepgram_api_key'))
    
    print(f"[COLOR_PICKER] Backend GET /api/settings - returning tag_colors: {tag_colors}")
    return {
        "success": True,
        "full_name": current_user.full_name,
        "signature": current_user.signature,
        "default_model": settings.get('default_model', 'claude'),
        "auto_save": settings.get('auto_save', True),
        "tag_colors": tag_colors,
        "has_deepgram_key": has_deepgram
    }


class UpdateSettingsRequest(BaseModel):
    full_name: Optional[str] = None
    signature: Optional[str] = None
    default_model: Optional[str] = None
    auto_save: Optional[bool] = None
    tag_colors: Optional[Dict[str, str]] = None
    deepgram_api_key: Optional[str] = None  # Only user-configurable API key


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
        if request.default_model is not None:
            settings['default_model'] = request.default_model
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
        
        # Handle Deepgram API key - only user-configurable key remaining
        # LLM API keys (Anthropic, Groq) are now system-wide via environment variables
        if request.deepgram_api_key is not None:
            if request.deepgram_api_key.strip():
                settings['deepgram_api_key'] = encrypt_api_key(request.deepgram_api_key)
            else:
                # Empty string means delete the key
                settings.pop('deepgram_api_key', None)
        
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
        
        # Check Deepgram API key status (only user-configurable key)
        has_deepgram = bool(updated_settings.get('deepgram_api_key'))
        
        return {
            "success": True,
            "full_name": current_user.full_name,
            "signature": current_user.signature,
            "default_model": updated_settings.get('default_model', 'claude'),
            "auto_save": updated_settings.get('auto_save', True),
            "tag_colors": final_tag_colors,
            "has_deepgram_key": has_deepgram
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
    """Get API key configuration status - LLM keys from system env, Deepgram from user settings"""
    db.refresh(current_user)
    settings = current_user.settings or {}
    
    # LLM API keys are now system-wide only (environment variables)
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    has_groq = bool(os.getenv("GROQ_API_KEY"))
    
    # Deepgram remains user-configurable (check user settings first, then env)
    has_deepgram_user = bool(settings.get('deepgram_api_key'))
    has_deepgram_env = bool(os.getenv("DEEPGRAM_API_KEY"))
    has_deepgram = has_deepgram_user or has_deepgram_env
    
    return {
        "success": True,
        "anthropic_configured": has_anthropic,
        "groq_configured": has_groq,
        "deepgram_configured": has_deepgram,
        "has_at_least_one_model": has_anthropic or has_groq,
        "using_user_keys": {
            "deepgram": has_deepgram_user
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
    edit_source: Optional[str] = None  # 'manual' or 'chat', defaults to 'manual'


class ApplyActionItem(BaseModel):
    id: str
    title: Optional[str] = None
    details: Optional[str] = None
    patch: Optional[str] = None


class ApplyActionsRequest(BaseModel):
    actions: List[ApplyActionItem]
    additional_context: Optional[str] = None


@app.post("/api/reports/{report_id}/enhance")
async def enhance_report(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    test_mode: bool = False,  # Add test mode parameter
    skip_completeness: bool = False  # Skip completeness analysis if True
):
    """
    Three-phase enhancement: Extract Findings → Search Guidelines → Analyze Completeness
    """
    try:
        # Get report
        report = get_report(db, report_id, user_id=str(current_user.id))
        if not report:
            return {"success": False, "error": "Report not found"}
        
        report_content = report.report_content
        
        # Extract original FINDINGS input for cache key generation
        # Cache based on FINDINGS alone (not clinical history) since guidelines are generated from findings
        findings_input = ""
        if report.input_data:
            variables = report.input_data.get('variables', {}) if isinstance(report.input_data, dict) else {}
            findings_input = variables.get('FINDINGS', '').strip() if isinstance(variables, dict) else ''
        
        print(f"enhance_report: Processing report_id {report_id}, content length: {len(report_content)}")
        print(f"enhance_report: Original FINDINGS input length: {len(findings_input)} chars")
        
        # TEST MODE: Return simple mock data to test data flow
        # Set TEST_MODE = True to bypass AI calls and return mock data
        TEST_MODE = False  # Set to False to use real AI enhancement
        if TEST_MODE:
            print("enhance_report: TEST MODE - Returning mock data")
            await asyncio.sleep(0.5)  # Simulate small delay
            
            # Extract simple findings from report content (simple keyword matching)
            findings = []
            if "nodule" in report_content.lower() or "nodules" in report_content.lower():
                findings.append({
                    "finding": "lung nodules",
                    "specialty": "chest/thoracic",
                    "type": "follow-up protocol",
                    "guideline_focus": "measurement and surveillance intervals"
                })
            if "aneurysm" in report_content.lower():
                findings.append({
                    "finding": "aortic aneurysm",
                    "specialty": "vascular",
                    "type": "measurement protocol",
                    "guideline_focus": "measurement criteria and follow-up"
                })
            if "appendicitis" in report_content.lower() or "appendix" in report_content.lower():
                findings.append({
                    "finding": "appendicitis",
                    "specialty": "abdominal/emergency",
                    "type": "diagnostic criteria",
                    "guideline_focus": "diagnostic findings and complications"
                })
            
            # If no findings detected, add a generic one
            if not findings:
                findings.append({
                    "finding": "general radiology findings",
                    "specialty": "general radiology",
                    "type": "protocol",
                    "guideline_focus": "standard reporting practices"
                })
            
            # Mock guidelines data
            guidelines_data = []
            for finding in findings:
                guidelines_data.append({
                    "finding": finding,
                    "discovered_bodies": [
                        {"name": "Royal College of Radiologists", "domain": "rcr.ac.uk", "reason": "UK radiology standards", "priority": "high"},
                        {"name": "Radiopaedia", "domain": "radiopaedia.org", "reason": "Comprehensive radiology reference", "priority": "high"}
                    ],
                    "body_names": ["Royal College of Radiologists", "Radiopaedia"],
                    "reasoning": "Standard UK radiology reference sources for this finding type",
                    "guideline_summary": f"**Guidelines for {finding['finding']}**\n\nStandard UK radiology guidelines recommend:\n\n1. Proper documentation of measurements\n2. Follow-up intervals based on size/criteria\n3. Clear reporting of diagnostic features\n\n*This is test/mock data to verify data flow.*",
                    "sources": [
                        {"url": "https://www.rcr.ac.uk/guidelines", "title": "RCR Guidelines"},
                        {"url": "https://radiopaedia.org/articles/" + finding['finding'].replace(' ', '-'), "title": f"Radiopaedia: {finding['finding']}"}
                    ]
                })
            
            # Mock completeness analysis (only if not skipped)
            completeness_analysis = None
            if not skip_completeness:
                completeness_analysis = {
                    "analysis": f"**Report Review for {report_id[:8]}...**\n\nThis is a test analysis. The report has been reviewed for completeness.\n\n**Checklist Questions:**\n- Have all relevant measurements been included?\n- Are follow-up recommendations clear?\n- Have diagnostic criteria been addressed?\n\n**Suggested Additions:**\n- Consider adding specific measurements if applicable\n- Review follow-up intervals based on findings",
                    "structured": {
                        "checklist": [
                            "Have all relevant measurements been included?",
                            "Are follow-up recommendations clear?",
                            "Have diagnostic criteria been addressed?"
                        ],
                        "suggestions": [
                            "Consider adding specific measurements if applicable",
                            "Review follow-up intervals based on findings"
                        ],
                        "feedback": "Report structure looks good. Consider the checklist items above."
                    }
                }
            
            return {
                "success": True,
                "findings": findings,
                "guidelines": guidelines_data,
                "completeness": completeness_analysis,
                "completeness_pending": False,
                "test_mode": True
            }
        
        # PRODUCTION MODE: Full AI enhancement with Groq
        import time
        pipeline_start = time.time()
        
        # Get Groq API key (system environment variable)
        groq_api_key = get_system_api_key('groq', 'GROQ_API_KEY')
        
        if not groq_api_key:
            return {
                "success": False,
                "error": "Groq API key not configured. Please set GROQ_API_KEY environment variable."
            }
        
        # Get Anthropic API key for completeness analysis
        anthropic_api_key = get_system_api_key('anthropic', 'ANTHROPIC_API_KEY')
        
        # Phase 1: Extract and consolidate findings
        phase1_start = time.time()
        print("enhance_report: Phase 1 - Extracting and consolidating findings...")
        consolidated_result = await extract_consolidated_findings(report_content, groq_api_key)
        phase1_time = time.time() - phase1_start
        print(f"enhance_report: Phase 1 complete - consolidated into {len(consolidated_result.findings)} findings in {phase1_time:.2f}s")

        # Phase 2: Search guidelines for consolidated findings
        guidelines_data = []
        phase2_time = 0
        if consolidated_result.findings:
            phase2_start = time.time()
            print(f"enhance_report: Phase 2 - Searching guidelines for {len(consolidated_result.findings)} consolidated findings...")
            guidelines_data = await search_guidelines_for_findings(
                consolidated_result,
                report_content,
                groq_api_key,
                findings_input=findings_input  # Pass original FINDINGS input for cache key generation
            )
            phase2_time = time.time() - phase2_start
            print(f"enhance_report: Phase 2 complete - found guidelines for {len(guidelines_data)} findings in {phase2_time:.2f}s")
        else:
            print("enhance_report: Phase 2 skipped - no findings to search")
        
        completeness_analysis = None
        completeness_pending = False
        
        if not skip_completeness:
            completeness_analysis = COMPLETENESS_RESULTS.get(report_id)
            completeness_pending = report_id in COMPLETENESS_TASKS

            if not completeness_analysis and not completeness_pending:
                if anthropic_api_key:
                    print("enhance_report: Phase 3 - Scheduling Claude completeness analysis...")
                    snapshot = copy.deepcopy(guidelines_data)
                    task = asyncio.create_task(
                        run_completeness_async(
                            report_id,
                            report_content,
                            snapshot,
                            anthropic_api_key
                        )
                    )
                    COMPLETENESS_TASKS[report_id] = task
                    completeness_pending = True
                else:
                    print("enhance_report: Phase 3 - Anthropic API key missing, returning fallback analysis")
                    fallback_result = await analyze_report_completeness(
                        report_content,
                        guidelines_data,
                        anthropic_api_key
                    )
                    COMPLETENESS_RESULTS[report_id] = fallback_result
                    completeness_analysis = fallback_result
                    completeness_pending = False

            completeness_analysis = completeness_analysis or COMPLETENESS_RESULTS.get(report_id)
            completeness_pending = completeness_pending or (report_id in COMPLETENESS_TASKS)
        else:
            print("enhance_report: Skipping completeness analysis (skip_completeness=True)")

        # Store enhancement results for chat context
        ENHANCEMENT_RESULTS[report_id] = {
            "findings": [finding.model_dump() for finding in consolidated_result.findings],
            "guidelines": guidelines_data
        }
        
        # Calculate total pipeline time (excluding async Phase 3)
        pipeline_time = time.time() - pipeline_start
        print(f"enhance_report: ✅ Pipeline complete (Phases 1+2) in {pipeline_time:.2f}s")
        print(f"  ├─ Phase 1 (Extraction): {phase1_time:.2f}s")
        print(f"  ├─ Phase 2 (Guidelines): {phase2_time:.2f}s")
        if skip_completeness:
            print(f"  └─ Phase 3 (Analysis): skipped")
        else:
            print(f"  └─ Phase 3 (Analysis): {'async (running)' if completeness_pending else 'completed'}")

        return {
            "success": True,
            "findings": [finding.model_dump() for finding in consolidated_result.findings],
            "guidelines": guidelines_data,
            "completeness": completeness_analysis,
            "completeness_pending": completeness_pending
        }
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"ERROR in enhance_report for report_id {report_id}: {str(e)}")
        print(f"Traceback: {error_trace}")
        return {"success": False, "error": str(e), "traceback": error_trace}


@app.get("/api/reports/{report_id}/completeness")
async def get_completeness_status(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    report = get_report(db, report_id, user_id=str(current_user.id))
    if not report:
        return {"success": False, "error": "Report not found"}
    
    pending = report_id in COMPLETENESS_TASKS
    completeness = COMPLETENESS_RESULTS.get(report_id)
    return {
        "success": True,
        "pending": pending,
        "completeness": completeness
    }


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, Any]]] = None

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

class StructuredActionsRequest(BaseModel):
    """Tool for applying structured actions to the report."""
    actions: List[StructuredActionItem] = Field(..., description="List of specific actions to apply to the report. Each action should be a focused, surgical edit.")
    conversation_summary: Optional[str] = Field(None, description="Brief summary of the conversation context that led to these edits (optional but helpful)")

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
        
        # Get enhancement data if available
        enhancement_context = ""
        enhancement_data = ENHANCEMENT_RESULTS.get(report_id)
        if enhancement_data:
            findings = enhancement_data.get('findings', [])
            guidelines = enhancement_data.get('guidelines', [])
            
            if findings or guidelines:
                enhancement_context += "\n\n=== ENHANCEMENT CONTEXT ===\n"
                enhancement_context += "The following information has been automatically extracted and synthesized from the report above to assist with discussion:\n\n"
            
            if findings:
                enhancement_context += "### Extracted Findings:\n"
                enhancement_context += "These are the key radiological findings that were automatically identified and consolidated from the report:\n"
                for finding in findings:
                    enhancement_context += f"- {finding.get('finding', 'N/A')}\n"
                enhancement_context += "\n"
            
            if guidelines:
                enhancement_context += "### Clinical Guidelines:\n"
                enhancement_context += "For each extracted finding above, relevant UK radiology guidelines have been synthesized from authoritative sources. Use this context when discussing diagnostic criteria, classification systems, measurement protocols, or follow-up recommendations:\n\n"
                for guideline in guidelines:
                    finding_name = guideline.get('finding', {}).get('finding', 'N/A')
                    enhancement_context += f"**Finding: {finding_name}**\n"
                    
                    # Use diagnostic overview (new structure)
                    overview = guideline.get('diagnostic_overview', '')
                    if overview:
                        enhancement_context += f"{overview}\n"
                    
                    # Include classification systems
                    classification_systems = guideline.get('classification_systems', [])
                    if classification_systems:
                        enhancement_context += "\nClassification Systems:\n"
                        for system in classification_systems[:2]:
                            enhancement_context += f"- {system.get('name', '')}: {system.get('grade_or_category', '')} - {system.get('criteria', '')}\n"
                    
                    # Include key imaging characteristics
                    imaging_chars = guideline.get('imaging_characteristics', [])
                    if imaging_chars:
                        enhancement_context += "\nKey Imaging Features:\n"
                        for char in imaging_chars[:3]:
                            enhancement_context += f"- {char.get('feature', '')}: {char.get('description', '')} ({char.get('significance', '')})\n"
                    
                    # Include differential diagnoses
                    differentials = guideline.get('differential_diagnoses', [])
                    if differentials:
                        enhancement_context += "\nDifferential Diagnoses:\n"
                        for ddx in differentials[:2]:
                            enhancement_context += f"- {ddx.get('diagnosis', '')}: {ddx.get('imaging_features', '')}\n"
                    
                    enhancement_context += "\n"
        
        system_prompt = (
            "CRITICAL: You MUST use British English spelling and terminology throughout all output.\n\n"
            "You are a radiology reporting assistant helping a clinician refine and discuss a radiology report. "
            "Provide concise, authoritative guidance grounded in evidence-based radiology and clinical practices. "
            "When discussing findings, reference the clinical guidelines context provided below. "
            "If asked about management or next steps, prioritize the guideline recommendations. "
            "If unsure, say so clearly.\n\n"
            "### RESPONSE WORKFLOW FOR EDIT REQUESTS:\n"
            "When a user asks about filling in a measurement, selecting an alternative, or fixing a placeholder:\n"
            "1. FIRST: Provide your analysis, explanation, and recommendation (including any calculations or reasoning)\n"
            "2. THEN: End your response with: 'Would you like me to make this edit to the report?'\n"
            "3. WAIT: Do NOT use the tool until the user explicitly confirms (e.g., 'yes', 'go ahead', 'make the edit', 'apply it')\n"
            "4. ONLY AFTER CONFIRMATION: Use the `apply_structured_actions` tool to implement the change\n\n"
            "### PROACTIVE EDIT SUGGESTIONS:\n"
            "When providing conversational responses, proactively suggest specific, actionable edits where appropriate to improve clarity, precision, or guideline alignment.\n\n"
            "### WHEN TO USE THE TOOL vs WHEN TO JUST CHAT:\n\n"
            "DO NOT use the tool for:\n"
            "- Questions asking for your opinion, thoughts, or analysis (e.g., 'thoughts on report structure?', 'review of report structure?', 'what do you think?')\n"
            "- Requests for clarification or explanation (e.g., 'what does this mean?', 'explain this finding')\n"
            "- General discussion or conversation about the report\n"
            "- Asking for recommendations or suggestions (e.g., 'what should I change?', 'any recommendations?')\n"
            "- Initial requests about unfilled placeholders - provide explanation FIRST, then ask for confirmation\n"
            "For these, reply conversationally with your analysis, guidance, AND proactive edit suggestions where appropriate.\n\n"
            "ONLY use the `apply_structured_actions` tool when:\n"
            "- User explicitly confirms after you've provided analysis (e.g., 'yes', 'go ahead', 'make the edit', 'apply it', 'do it')\n"
            "- User explicitly asks you to MODIFY, UPDATE, CHANGE, IMPLEMENT, or APPLY changes (e.g., 'go ahead and implement', 'make those changes', 'update the report', 'apply the recommendations')\n"
            "- User gives you specific edits to make (e.g., 'add TNM staging', 'change X to Y')\n"
            "- User says 'do it', 'implement', 'apply', 'make the changes' after you've provided recommendations\n\n"
            "### Report Editing Instructions (ONLY when user explicitly requests modifications):\n"
            "If the user explicitly asks you to modify, rewrite, update, implement, or apply changes to the report, THEN use the `apply_structured_actions` tool.\n"
            "CRITICAL: Extract structured actions from the conversation - break down the user's request into specific, focused edits.\n"
            "Each action should have:\n"
            "- title: Brief description (e.g., 'Update TNM staging', 'Add measurement details')\n"
            "- details: Explanation of what to change and why, referencing conversation context\n"
            "- patch: Specific instruction (e.g., 'Replace X with Y in Section Z', 'Add measurement after finding')\n"
            "Do NOT use the old `update_report` tool - it is deprecated.\n"
            "Do NOT output the report text in the chat message if you are calling the tool.\n\n"
            f"### Original Report:\n{report.report_content}"
            f"{enhancement_context}"
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
        
        # Define tools - use structured actions (preferred) with backward compatibility
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "apply_structured_actions",
                    "description": "ONLY use this tool when the user explicitly asks you to MODIFY, UPDATE, CHANGE, IMPLEMENT, or APPLY changes to the report. Do NOT use for questions, discussions, or requests for opinions (e.g., 'thoughts on...', 'review of...', 'what do you think?'). Only use when user says 'implement', 'apply', 'make changes', 'update', etc.",
                    "parameters": StructuredActionsRequest.model_json_schema()
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "update_report",
                    "description": "DEPRECATED: Updates the full content of the radiology report. Use apply_structured_actions instead.",
                    "parameters": ReportUpdate.model_json_schema()
                }
            }
        ]
        
        print(f"\n💬 Chat request received:")
        print(f"  Model: qwen/qwen3-32b (Groq)")
        print(f"  User message: {request.message[:100]}...")
        print(f"  History: {len(request.history) if request.history else 0} messages")
        
        response = client.chat.completions.create(
            model="qwen/qwen3-32b",
            max_tokens=1500,
            temperature=0.3,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stop=None
        )
        
        print(f"✅ Qwen response received")
        
        message = response.choices[0].message
        response_text = message.content
        tool_calls = message.tool_calls
        
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
                        # Parse structured actions from Qwen's tool call
                        args = json.loads(tool_call.function.arguments)
                        print(f"\n🔍 DEBUG: Parsed JSON arguments:")
                        print(f"  Keys: {list(args.keys())}")
                        print(f"  Actions count: {len(args.get('actions', []))}")
                        if 'conversation_summary' in args:
                            print(f"  Conversation summary: {args['conversation_summary'][:100] if args['conversation_summary'] else 'None'}...")
                        
                        structured_actions_data = StructuredActionsRequest(**args)
                        
                        print(f"\n📋 Extracted {len(structured_actions_data.actions)} structured actions:")
                        for i, action in enumerate(structured_actions_data.actions, 1):
                            print(f"  {i}. {action.title}")
                            print(f"     Details: {action.details[:200] if len(action.details) > 200 else action.details}")
                            print(f"     Patch: {action.patch[:200] if len(action.patch) > 200 else action.patch}")
                        
                        # Convert to format expected by regenerate_report_with_actions
                        # Generate IDs for actions (required by ApplyActionItem)
                        actions_payload = []
                        for idx, action in enumerate(structured_actions_data.actions):
                            actions_payload.append({
                                "id": f"chat_action_{idx}",
                                "title": action.title,
                                "details": action.details,
                                "patch": action.patch
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
                else:
                    # Other tool calls (shouldn't happen, but handle gracefully)
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
            
        if not response_text and edit_proposal:
            response_text = "I've drafted the changes for you. Please review and apply them below."
            print(f"  └─ Set default response text (edit_proposal exists but no response_text)")
        
        print(f"\n📤 Returning response:")
        print(f"  Response text length: {len(response_text) if response_text else 0} chars")
        print(f"  Edit proposal length: {len(edit_proposal) if edit_proposal else 0} chars")
        print(f"{'='*80}\n")
        
        sources = []
        
        return {
            "success": True,
            "response": response_text,
            "edit_proposal": edit_proposal,
            "sources": sources
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

        reset_completeness_state(report_id)

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
            if edit_source == "chat":
                notes = "Chat edit"
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
        
        reset_completeness_state(report_id)
        
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
    
    # DEBUG: Log the raw transcript to see what Deepgram actually returns
    print(f"🔍 DEBUG: Raw transcript before processing: '{transcript}'")
    print(f"🔍 DEBUG: Transcript repr: {repr(transcript)}")
    
    processed = transcript
    
    # Convert Deepgram's literal dictation command strings to actual characters
    # Deepgram returns these as literal strings like "<\n>" (backslash followed by n)
    # Replace <\n\n> (new paragraph) first, then <\n> (new line)
    processed_before_fullstop = processed
    processed = processed.replace('<\\n\\n>', '\n\n')  # New paragraph
    processed = processed.replace('<\\n>', '\n')  # New line
    
    # DEBUG: Check if newline replacements worked
    if processed != processed_before_fullstop:
        print(f"🔍 DEBUG: Newline replacements applied. After: '{processed}'")
    
    # Convert "full stop" and "fullstop" to period (British English support)
    # Deepgram doesn't recognize "full stop" as a dictation command, only "period"
    # So we post-process it here for better British English support
    # Handle both "full stop" (two words) and "fullstop" (one word) variations
    # Make replacements case-insensitive and handle various spacing/punctuation scenarios
    
    processed_before_fullstop = processed
    
    # Use regex for case-insensitive matching of "full stop" / "fullstop"
    # This handles all cases: standalone, with spaces, at start/end of string
    # Pattern to match "full stop" or "fullstop" (case-insensitive) as whole words
    # or standalone phrases
    patterns = [
        (r'\bfull\s+stop\b', '.'),  # "full stop" as whole words
        (r'\bfullstop\b', '.'),      # "fullstop" as whole word
    ]
    
    for pattern, replacement in patterns:
        matches = re.findall(pattern, processed, re.IGNORECASE)
        if matches:
            processed = re.sub(pattern, replacement, processed, flags=re.IGNORECASE)
            print(f"🔍 DEBUG: Replaced pattern '{pattern}' (found: {matches}) with '{replacement}'")
    
    # DEBUG: Check if full stop replacements worked
    if processed != processed_before_fullstop:
        print(f"🔍 DEBUG: Full stop replacements applied. After: '{processed}'")
    else:
        print(f"🔍 DEBUG: No full stop replacements applied. Checking if 'full stop' exists in transcript...")
        if 'full' in processed.lower() and 'stop' in processed.lower():
            print(f"🔍 DEBUG: Found 'full' and 'stop' in transcript but pattern didn't match!")
            # Try to find the exact pattern (re is already imported at top of file)
            matches = re.findall(r'\b(full\s*stop|fullstop)\b', processed, re.IGNORECASE)
            if matches:
                print(f"🔍 DEBUG: Found potential matches: {matches}")
    
    print(f"🔍 DEBUG: Final processed transcript: '{processed}'")
    
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
    
    # Get Deepgram API key from user settings or fallback to env
    deepgram_api_key = get_user_api_key(user_settings, 'deepgram', 'DEEPGRAM_API_KEY')
    
    if not deepgram_api_key:
        await websocket.send_json({
            "error": "Deepgram API key not configured. Please add your Deepgram API key in Settings."
        })
        await websocket.close()
        return
    
    # Connect to Deepgram WebSocket API with Nova-3 Medical model
    # Using nova-3-medical for optimized medical transcription
    # punctuate=true is required for dictation commands (full stop, new line, etc.) to work
    deepgram_url = f"wss://api.deepgram.com/v1/listen?model=nova-3-medical&language=en-GB&smart_format=true&measurements=true&dictation=true&punctuate=true&interim_results=true"
    
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
                            print(f"📤 Forwarding {len(data)} bytes to Deepgram")
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
                                print(f"📥 Received from Deepgram: {transcript_data}")
                                
                                # Parse Deepgram response
                                if transcript_data.get("type") == "Results":
                                    alternatives = transcript_data.get("channel", {}).get("alternatives", [])
                                    if alternatives:
                                        raw_transcript = alternatives[0].get("transcript", "")
                                        is_final = transcript_data.get("is_final", False)
                                        
                                        # Process dictation commands (convert <\n> to actual newlines, etc.)
                                        transcript = process_dictation_transcript(raw_transcript)
                                        
                                        print(f"📝 Raw transcript: '{raw_transcript}' → Processed: '{transcript}' (final: {is_final})")
                                        
                                        if transcript:
                                            await websocket.send_json({
                                                "transcript": transcript,
                                                "is_final": is_final
                                            })
                                elif transcript_data.get("type") == "error":
                                    error_msg = transcript_data.get("msg", "Unknown error")
                                    print(f"❌ Deepgram error: {error_msg}")
                                    await websocket.send_json({"error": error_msg})
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                print(f"❌ WebSocket error: {msg.data}")
                            else:
                                print(f"ℹ️ Received message type: {msg.type}")
                                    
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
    # Get Deepgram API key from user settings or fallback to env
    settings = current_user.settings or {}
    deepgram_api_key = get_user_api_key(settings, 'deepgram', 'DEEPGRAM_API_KEY')
    
    if not deepgram_api_key:
        raise HTTPException(
            status_code=400,
            detail="Deepgram API key not configured. Please add your Deepgram API key in Settings."
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


def main():
    """Main entry point for running the server"""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()

