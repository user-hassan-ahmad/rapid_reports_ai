from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, File, UploadFile, HTTPException
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Optional, List, Any
import os
import re
from dotenv import load_dotenv
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
    # Startup: create database tables
    Base.metadata.create_all(bind=engine)
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
        "You are a radiology reporting assistant. Integrate every requested action into the report.\n"
        "Respect clinical accuracy, keep formatting consistent, and return the full revised report text only "
        "(no commentary, headings, or markdown besides the report itself).\n\n"
        f"{context_section}"
        "Original report:\n"
        "---------------------\n"
        f"{report.report_content}\n"
        "---------------------\n\n"
        "Actions to apply:\n"
        "---------------------\n"
        f"{chr(10).join(action_lines)}\n"
        "---------------------\n"
        "Produce the revised report now."
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
        "You are a radiology reporting assistant. Apply every requested action to the report. "
        "Return ONLY the full, final report text. No commentary, no thinking blocks, no tags—just the complete revised report."
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
                model_settings["reasoning_effort"] = "high"
                print(f"regenerate_report_with_actions: Using Cerebras reasoning_effort=high, max_completion_tokens=4096 for {primary_model}")
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
    template_content: str
    master_prompt_instructions: Optional[str] = None
    model_compatibility: Optional[List[str]] = None
    variables: Optional[List[str]] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    template_content: Optional[str] = None
    master_prompt_instructions: Optional[str] = None
    model_compatibility: Optional[List[str]] = None
    variables: Optional[List[str]] = None
    variable_config: Optional[Dict] = None
    is_active: Optional[bool] = None


class TemplateGenerateRequest(BaseModel):
    variables: Dict[str, str]
    model: str = "claude"  # Always uses Claude (kept for API compatibility, fallback handled automatically)


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
        
        # Always run validation on generated report
        from .enhancement_utils import validate_report_protocol, apply_protocol_fixes
        findings = request.variables.get('FINDINGS', '') if request.variables else ''
        
        try:
            validation_result = await validate_report_protocol(
                report_content=report_output.report_content,
                scan_type=report_output.scan_type,
                findings=findings
            )
            
            # Apply fixes if violations found, otherwise use original report
            if validation_result.violations:
                violation_count = len(validation_result.violations)
                print(f"\n{'='*80}")
                print(f"⚠️ PROTOCOL VIOLATIONS DETECTED: {violation_count} violation(s)")
                print(f"{'='*80}")
                for i, violation in enumerate(validation_result.violations, 1):
                    print(f"  {i}. [{violation.violation_type}] {violation.location}")
                    print(f"     Issue: {violation.issue}")
                print(f"{'='*80}\n")
                print(f"Applying fixes...")
                report_output = await apply_protocol_fixes(
                    report_output=report_output,
                    validation_result=validation_result
                )
                print(f"✅ Fixes applied successfully")
            else:
                print("✅ No violations found, using original report")
        except Exception as validation_error:
            # If validation fails, log error but continue with original report
            print(f"⚠️ Validation failed: {validation_error}")
            print("Continuing with original report output")
        
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
        # Extract variables from template if not provided
        tm = TemplateManager()
        if not template_data.variables:
            variables = tm.extract_variables(template_data.template_content)
        else:
            variables = template_data.variables
        
        template = create_template(
            db=db,
            name=template_data.name,
            description=template_data.description,
            tags=template_data.tags,
            template_content=template_data.template_content,
            user_id=str(current_user.id),
            master_prompt_instructions=template_data.master_prompt_instructions,
            model_compatibility=template_data.model_compatibility,
            variables=variables,
        )
        
        return {"success": True, "template": template.to_dict()}
    except Exception as e:
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
        # Always re-extract variables from template_content if it's provided
        tm = TemplateManager()
        variables = template_data.variables  # Default to provided variables
        
        if template_data.template_content is not None:
            # Re-extract variables from the template content
            variables = tm.extract_variables(template_data.template_content)
        
        updated_template = update_template(
            db=db,
            template_id=template_id,
            user_id=str(current_user.id),
            name=template_data.name,
            description=template_data.description,
            tags=template_data.tags,
            template_content=template_data.template_content,
            variables=variables,
            variable_config=template_data.variable_config,
            master_prompt_instructions=template_data.master_prompt_instructions,
            model_compatibility=template_data.model_compatibility,
            is_active=template_data.is_active,
        )
        
        if not updated_template:
            return {"success": False, "error": "Template not found"}
        
        return {"success": True, "template": updated_template.to_dict()}
    except Exception as e:
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
    """Generate a report from a template using Pydantic AI"""
    try:
        # Get the template
        template = get_template(db, template_id, user_id=str(current_user.id))
        if not template:
            return {"success": False, "error": "Template not found"}
        
        # Build prompts using TemplateManager (now returns dict with system_prompt and user_prompt)
        # Get primary model from MODEL_CONFIG for conditional routing
        from .enhancement_utils import MODEL_CONFIG
        
        tm = TemplateManager()
        primary_model = MODEL_CONFIG.get("PRIMARY_REPORT_GENERATOR")
        
        # Conditionally use reasoning method for gpt-oss-120b
        if primary_model == "gpt-oss-120b":
            prompts = tm.build_master_prompt_with_reasoning(
                template=template.template_content,
                variable_values=request.variables,
                template_name=template.name,
                template_description=template.description,
                master_instructions=template.master_prompt_instructions,
                model=request.model
            )
        else:
            prompts = tm.build_master_prompt(
                template=template.template_content,
                variable_values=request.variables,
                template_name=template.name,
                template_description=template.description,
                master_instructions=template.master_prompt_instructions,
                model=request.model
            )
        
        system_prompt = prompts.get('system_prompt', '')
        user_prompt = prompts.get('user_prompt', '')
        
        # Always use Claude as primary model (with automatic fallback if Claude fails)
        # Get Anthropic API key for Claude (primary)
        api_key = get_system_api_key('anthropic', 'ANTHROPIC_API_KEY')
        if not api_key:
            return {
                "success": False,
                "error": "Anthropic API key not configured. Please set ANTHROPIC_API_KEY environment variable."
            }
        
        # Generate report using Claude (with automatic fallback to Qwen if Claude fails)
        report_output = await generate_templated_report(
            model="claude",  # Always use Claude (model param kept for API compatibility)
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            api_key=api_key,
            signature=current_user.signature
        )
        
        # Always run validation on generated report
        from .enhancement_utils import validate_report_protocol, apply_protocol_fixes
        findings = request.variables.get('FINDINGS', '')
        
        try:
            validation_result = await validate_report_protocol(
                report_content=report_output.report_content,
                scan_type=report_output.scan_type,
                findings=findings
            )
            
            # Apply fixes if violations found, otherwise use original report
            if validation_result.violations:
                violation_count = len(validation_result.violations)
                print(f"\n{'='*80}")
                print(f"⚠️ PROTOCOL VIOLATIONS DETECTED: {violation_count} violation(s)")
                print(f"{'='*80}")
                for i, violation in enumerate(validation_result.violations, 1):
                    print(f"  {i}. [{violation.violation_type}] {violation.location}")
                    print(f"     Issue: {violation.issue}")
                print(f"{'='*80}\n")
                print(f"Applying fixes...")
                report_output = await apply_protocol_fixes(
                    report_output=report_output,
                    validation_result=validation_result
                )
                print(f"✅ Fixes applied successfully")
            else:
                print("✅ No violations found, using original report")
        except Exception as validation_error:
            # If validation fails, log error but continue with original report
            print(f"⚠️ Validation failed: {validation_error}")
            print("Continuing with original report output")
        
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
                
                saved_report = create_report(
                    db=db,
                    user_id=str(current_user.id),
                    report_type="templated",
                    report_content=report_output.report_content,
                    model_used=model_display,
                    input_data={
                        "variables": request.variables,
                        "extracted_scan_type": report_output.scan_type
                    },
                    template_id=str(template.id),
                    description=context_title
                )
                report_id = str(saved_report.id)
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


# ============================================================================
# REPORT ENHANCEMENT API ENDPOINTS
# ============================================================================

class ChatMessageRequest(BaseModel):
    message: str
    history: Optional[List[Dict]] = Field(default_factory=list)


class UpdateReportRequest(BaseModel):
    content: str


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
    test_mode: bool = False  # Add test mode parameter
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
        print(f"enhance_report: Processing report_id {report_id}, content length: {len(report_content)}")
        
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
            
            # Mock completeness analysis
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
                groq_api_key
            )
            phase2_time = time.time() - phase2_start
            print(f"enhance_report: Phase 2 complete - found guidelines for {len(guidelines_data)} findings in {phase2_time:.2f}s")
        else:
            print("enhance_report: Phase 2 skipped - no findings to search")
        
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


@app.post("/api/reports/{report_id}/chat")
async def chat_about_report(
    report_id: str,
    request: ChatMessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
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
        
        response = client.chat.completions.create(
            model="qwen/qwen3-32b",
            max_tokens=1500,
            temperature=0.3,
            messages=messages,
            stop=None  # Ensure no special stop sequences
        )
        
        response_text = response.choices[0].message.content
        
        # Filter out Qwen's thinking tokens using <think></think> tags
        # Qwen3-32B uses XML-like tags to demarcate internal thought processes (CoT)
        if response_text:
            # Remove everything between <think> and </think> tags
            response_text = re.sub(
                r'<think>.*?</think>',
                '',
                response_text,
                flags=re.DOTALL | re.IGNORECASE
            )
            # Clean up any extra whitespace left behind
            response_text = response_text.strip()
        
        sources = []
        
        return {
            "success": True,
            "response": response_text,
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
        db.commit()
        db.refresh(report)

        version = None
        try:
            version = create_report_version(
                db,
                report=report,
                actions_applied=None,
                notes="Manual content update"
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
    deepgram_url = f"wss://api.deepgram.com/v1/listen?model=nova-3-medical&language=en-GB&smart_format=true&measurements=true&dictation=true&interim_results=true"
    
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
                                        transcript = alternatives[0].get("transcript", "")
                                        is_final = transcript_data.get("is_final", False)
                                        
                                        print(f"📝 Transcript: '{transcript}' (final: {is_final})")
                                        
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
            "dictation": "true"
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
        transcript = ""
        if result.get("results") and result["results"].get("channels"):
            alternatives = result["results"]["channels"][0].get("alternatives", [])
            if alternatives:
                transcript = alternatives[0].get("transcript", "")
        
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

