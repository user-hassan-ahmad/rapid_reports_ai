"""
Enhancement Utilities using Pydantic AI for structured outputs
Cleaner, type-safe implementation with automatic validation
"""

import asyncio
import os
import re
import time
from datetime import datetime
from functools import wraps
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from pydantic import BaseModel
from pydantic_ai import RunContext

from .enhancement_cache import (
    get_cache,
    generate_finding_hash,
    generate_query_hash,
    generate_search_results_hash
)
import hashlib

# Cerebras concurrency guard — limits concurrent LLM calls across all modules
# (S1, S2.5 triage, S4 synthesis, and all 3 audit phases) to prevent rate-limit
# errors. Default 4; tune via CEREBRAS_MAX_CONCURRENT env var.
_CEREBRAS_MAX_CONCURRENT = int(os.environ.get("CEREBRAS_MAX_CONCURRENT", "4"))
_cerebras_semaphore = asyncio.Semaphore(_CEREBRAS_MAX_CONCURRENT)

from perplexity import Perplexity
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.groq import GroqModel, GroqModelSettings
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from .enhancement_models import (
    Finding,
    FindingsResponse,
    GuidelineEntry,
    GuidelinesResponse,
    RichGuidelineEntry,
    RichGuidelinesResponse,
    UrgencyTier,
    KeyPoint,
    ClassificationSystem,
    MeasurementProtocol,
    ImagingCharacteristic,
    DifferentialDiagnosis,
    FollowUpImaging,
    SuggestedAction,
    ConsolidatedFinding,
    ConsolidationResult,
    ReportOutput,
    StructureViolation,
    StructureValidationResult,
    CompatibleIndicesResponse,
    Measurement,
    PriorState,
    FindingComparison,
    ComparisonAnalysis,
    ComparisonAnalysisStage1,
    ChangeDirective,
    ComparisonReportGeneration,
    AuditResult,
    GuidelineReference,
    AuditFixContext,
)

# ── Semantic embedding cache ──────────────────────────────────────────────────
# Keyed by MD5 of the input text; populated lazily on first embed call per text.
# Survives the lifetime of the server process; reset on restart (fine at our scale).
_EMBEDDING_CACHE: Dict[str, List[float]] = {}
_EMBEDDING_CACHE_MAX = 8_000  # ~8k short snippets ≈ a few MB of floats


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _batch_embed(texts: List[str]) -> Optional[List[List[float]]]:
    """
    Batch-embed texts using OpenAI text-embedding-3-small.

    Returns a parallel list of embedding vectors, or None if the API key is absent
    or the call fails (callers should fall back to lexical scoring).
    All results are stored in _EMBEDDING_CACHE keyed by MD5(text).
    """
    import openai

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    cache_keys = [hashlib.md5(t.encode()).hexdigest() for t in texts]
    result: List[Optional[List[float]]] = [_EMBEDDING_CACHE.get(k) for k in cache_keys]
    uncached_idx = [i for i, v in enumerate(result) if v is None]

    if uncached_idx:
        try:
            client = openai.AsyncOpenAI(api_key=api_key)
            resp = await client.embeddings.create(
                model="text-embedding-3-small",
                input=[texts[i] for i in uncached_idx],
            )
            for list_pos, orig_idx in enumerate(uncached_idx):
                vec = resp.data[list_pos].embedding
                # Evict oldest entries if cache is full
                if len(_EMBEDDING_CACHE) >= _EMBEDDING_CACHE_MAX:
                    oldest = next(iter(_EMBEDDING_CACHE))
                    del _EMBEDDING_CACHE[oldest]
                _EMBEDDING_CACHE[cache_keys[orig_idx]] = vec
                result[orig_idx] = vec
        except Exception as exc:
            print(f"[embedding] API error, falling back to lexical: {exc}")
            return None

    # If any slot is still None (shouldn't happen), abort
    if any(v is None for v in result):
        return None
    return result  # type: ignore[return-value]


# ── GLM Reasoning Mode Toggle ──────────────────────────────────────────────────
# Cerebras docs: temperature >= 0.8 required when reasoning is enabled.
# If reasoning is disabled, temperature can go below 0.8 for more deterministic output.
#   Reasoning ON  → temperature=0.8, max_completion_tokens=16000 (budget for reasoning + report)
#   Reasoning OFF → temperature=0.5, max_completion_tokens=6000  (no reasoning overhead)
# Toggle without restarting: edit GLM_REASONING_ENABLED in backend/.env — read fresh on every request.
def _glm_reasoning_enabled() -> bool:
    """Read GLM_REASONING_ENABLED from .env on every call so changes take effect without a server restart."""
    from dotenv import dotenv_values
    env = dotenv_values()
    return env.get("GLM_REASONING_ENABLED", "false").lower() == "true"

# Central Model Configuration Dictionary
# Maps generic roles to specific model identifiers for easy model swapping
# Update this dictionary to change models without modifying code throughout the codebase
MODEL_CONFIG = {
    # Report Generation Models
    "PRIMARY_REPORT_GENERATOR": "zai-glm-4.7",  # Primary model for report generation (Cerebras GLM-4.7)
    "FALLBACK_REPORT_GENERATOR": "claude-sonnet-4-6",  # Fallback model if primary fails (Claude Sonnet 4.6)
    
    # Structure Validation Models
    "STRUCTURE_VALIDATOR": "gpt-oss-120b",  # Structure validation: Check for structural quality violations (Cerebras GPT-OSS-120B with medium reasoning)
    "STRUCTURE_VALIDATOR_FALLBACK": "qwen/qwen3-32b",  # Fallback for structure validation (Groq Qwen with thinking)
    
    # Enhancement Pipeline Models
    "FINDING_EXTRACTION": "gpt-oss-120b",  # Phase 1: Finding extraction and consolidation (primary - Cerebras GPT-OSS-120B with high reasoning)
    "FINDING_EXTRACTION_FALLBACK": "qwen/qwen3-32b",  # Fallback for finding extraction (Qwen with thinking)
    "QUERY_GENERATION": "gpt-oss-120b",  # Query generation primary (Cerebras GPT-OSS-120B with high reasoning)
    "QUERY_GENERATION_FALLBACK": "llama-3.3-70b-versatile",  # Query generation fallback (Llama)
    "GUIDELINE_VALIDATOR": "gpt-oss-120b",  # Guideline compatibility validation (primary - Cerebras GPT-OSS-120B with high reasoning)
    "GUIDELINE_VALIDATOR_FALLBACK": "llama-3.3-70b-versatile",  # Fallback for guideline validation (Llama)
    "COMPATIBILITY_FILTER": "gpt-oss-120b",  # Search result compatibility filtering (primary - Cerebras GPT-OSS-120B with high reasoning)
    "COMPATIBILITY_FILTER_FALLBACK": "llama-3.3-70b-versatile",  # Fallback for compatibility filtering (Llama)
    "GUIDELINE_SEARCH": "gpt-oss-120b",  # Phase 2: Guideline synthesis (primary - Cerebras GPT-OSS-120B, reliable structured output)
    "GUIDELINE_SEARCH_FALLBACK": "zai-glm-4.7",  # Fallback (GLM cannot reliably generate tool_calls for complex schemas)
    "COMPARISON_ANALYZER": "gpt-oss-120b",  # Interval comparison analysis (primary - Cerebras GPT-OSS-120B with high reasoning)
    "COMPARISON_ANALYZER_FALLBACK": "qwen/qwen3-32b",  # Fallback for comparison analysis (Qwen)
    
    # Action Application Models
    "ACTION_APPLIER": "gpt-oss-120b",  # Apply enhancement actions to reports (primary - Cerebras GPT-OSS-120B with high reasoning)
    "ACTION_APPLIER_FALLBACK": "qwen/qwen3-32b",  # Fallback for action application (Qwen)
    
    # Linguistic Validation Models (for zai-glm-4.7 post-processing)
    "ZAI_GLM_LINGUISTIC_VALIDATOR": "llama-3.3-70b-versatile",  # Linguistic/anatomical correction for zai-glm-4.7 output (Groq Llama)
    
    # Audit / QA Analysis Models
    "AUDIT_ANALYZER": "zai-glm-4.7",  # Report audit/QA primary (Cerebras Zai-GLM-4.7)
    "AUDIT_ANALYZER_FALLBACK": "qwen/qwen3-32b",  # Fallback for audit (Groq Qwen 32B)
    
    # Canvas / IntelliDictate Models
    "CANVAS_SECTIONS": "gpt-oss-120b",  # Section generation from scan type (Cerebras)
    "CANVAS_SECTIONS_FALLBACK": "llama-3.3-70b-versatile",  # Fallback for section generation (Groq Llama)
    "CANVAS_SECTIONS_FROM_TEMPLATE": "gpt-oss-120b",  # Extract sections from template (Cerebras)
    "CANVAS_SECTIONS_FROM_TEMPLATE_FALLBACK": "llama-3.3-70b-versatile",  # Fallback for template section extraction (Groq Llama)
    "CANVAS_PROCESS": "qwen/qwen3-32b",  # Transcript → scratchpad (Groq Qwen)
    "CANVAS_COVERAGE": "llama-3.3-70b-versatile",  # Coverage check (Groq Llama)
    "CANVAS_INTELLIPROMPTS": "qwen/qwen3-32b",  # IntelliPrompts generation (Groq Qwen)

    # Agentic Report Pipeline Models
    "REPORT_PLANNER": "zai-glm-4.7",        # Phase 1: planning agent (Cerebras, reasoning ON)
    "REPORT_EXECUTOR": "zai-glm-4.7",  # Phase 2: execution agent (Cerebras GLM, reasoning ON)
    "PLAN_ADHERENCE_CHECKER": "qwen/qwen3-32b",  # Phase 3: cross-check output vs plan (Groq)

    # Template Wizard Generation Models
    "TEMPLATE_FINDINGS_GENERATOR": "zai-glm-4.7",     # Wizard: generate FINDINGS section template
    "TEMPLATE_INSTRUCTION_SUGGESTER": "zai-glm-4.7",  # Wizard: suggest section instructions
    "TEMPLATE_REPORT_GENERATOR": "zai-glm-4.7",       # generate_report_from_config primary model (Cerebras GLM-4.7)

    # Skill Sheet Models
    "SKILL_SHEET_ANALYZER": "zai-glm-4.7",      # Extract skill sheet from example reports
    "SKILL_SHEET_DIVERSITY_CHECK": "zai-glm-4.7",       # Pre-analysis diversity assessment (primary, Cerebras with reasoning)
    "SKILL_SHEET_DIVERSITY_CHECK_FALLBACK": "qwen/qwen3-32b",  # Diversity check fallback (Groq Qwen with thinking)
    "SKILL_SHEET_REFINER": "zai-glm-4.7",       # Refine skill sheet via chat
    "SKILL_SHEET_TEST_GENERATE": "zai-glm-4.7", # Test-generate report from skill sheet (Cerebras GLM-4.7)

    # Knowledge Maintenance Agent
    "KNOWLEDGE_MAINTENANCE": "gpt-oss-120b",  # Async agent: populate knowledge_links from skill sheet
}

# Legacy constants for backward compatibility (deprecated - use MODEL_CONFIG instead)
QWEN_EXTRACTION_MODEL = MODEL_CONFIG["FINDING_EXTRACTION"]
LLAMA_GUIDELINE_MODEL = MODEL_CONFIG["GUIDELINE_SEARCH"]
LLAMA_REPORT_PRIMARY_MODEL = MODEL_CONFIG["FALLBACK_REPORT_GENERATOR"]  # Legacy: was used for fast mode
LLAMA_REPORT_FALLBACK_MODEL = "llama-3.3-70b-versatile"  # Legacy fallback (not currently used)

# Provider Mapping Dictionary
# Maps model names to their providers for easy model switching
# To add a new model, just add an entry here mapping model_name -> provider
MODEL_PROVIDERS = {
    # Groq models
    "qwen/qwen3-32b": "groq",
    "llama-3.3-70b-versatile": "groq",
    
    # Anthropic models
    "claude-sonnet-4-20250514": "anthropic",
    "claude-sonnet-4-6": "anthropic",
    
    # Cerebras models
    "gpt-oss-120b": "cerebras",
    "zai-glm-4.7": "cerebras",
    "qwen-3-235b-a22b-instruct-2507": "cerebras",  # Cerebras-hosted Qwen for linguistic validation

    # Fireworks models
    "accounts/fireworks/models/glm-5p1": "fireworks",
}


def _get_model_provider(model_name: str) -> str:
    """
    Get the provider for a given model name.
    
    Args:
        model_name: The model identifier (e.g., "qwen/qwen3-32b", "gpt-oss-120b")
    
    Returns:
        Provider string: 'groq', 'anthropic', or 'cerebras'
    
    Raises:
        ValueError: If model is not found in MODEL_PROVIDERS
    """
    provider = MODEL_PROVIDERS.get(model_name)
    if provider is None:
        available_models = ", ".join(sorted(MODEL_PROVIDERS.keys()))
        raise ValueError(
            f"Model '{model_name}' not found in MODEL_PROVIDERS. "
            f"Available models: {available_models}. "
            f"To add a new model, add it to MODEL_PROVIDERS dictionary."
        )
    return provider


# ============================================================================
# Comparison Analysis - Measurement Calculation Tool
# ============================================================================

class MeasurementCalculationInput(BaseModel):
    prior_value: float
    prior_unit: str
    prior_date: Optional[str] = None
    current_value: float
    current_unit: str
    current_date: Optional[str] = None

class MeasurementCalculationResult(BaseModel):
    absolute_change: float
    absolute_change_str: str
    percentage_change: float
    percentage_change_str: str
    days_elapsed: Optional[int] = None
    growth_rate: Optional[str] = None
    calculation_error: Optional[str] = None

def calculate_measurement_change(input: MeasurementCalculationInput) -> MeasurementCalculationResult:
    """Tool for precise measurement calculations with unit conversion."""
    try:
        # Unit conversion to mm
        def to_mm(value: float, unit: str) -> float:
            unit_lower = unit.lower().strip()
            if unit_lower in ['mm', 'millimeter', 'millimeters']:
                return value
            elif unit_lower in ['cm', 'centimeter', 'centimeters']:
                return value * 10
            elif unit_lower in ['m', 'meter', 'meters']:
                return value * 1000
            return value
        
        prior_mm = to_mm(input.prior_value, input.prior_unit)
        current_mm = to_mm(input.current_value, input.current_unit)
        absolute_change_mm = current_mm - prior_mm
        
        # Display unit selection
        if input.prior_unit.lower() == input.current_unit.lower():
            display_unit = input.current_unit
            absolute_change = input.current_value - input.prior_value
        else:
            display_unit = 'mm'
            absolute_change = absolute_change_mm
        
        absolute_change_str = f"{absolute_change:+.1f} {display_unit}"
        
        # Percentage calculation
        if prior_mm == 0:
            raise ValueError("Cannot calculate percentage from zero")
        percentage_change = ((current_mm - prior_mm) / prior_mm) * 100
        percentage_change_str = f"{percentage_change:+.1f}%"
        
        # Growth rate calculation
        days_elapsed = None
        growth_rate = None
        
        if input.prior_date and input.current_date:
            try:
                current_dt = datetime.now() if input.current_date.lower() == 'current' else datetime.fromisoformat(input.current_date.replace('Z', '+00:00'))
                prior_dt = datetime.fromisoformat(input.prior_date.replace('Z', '+00:00'))
                days_elapsed = (current_dt - prior_dt).days
                
                if days_elapsed > 0:
                    mm_per_day = absolute_change_mm / days_elapsed
                    if days_elapsed < 400:
                        rate = mm_per_day * 30
                        growth_rate = f"{rate:.1f} mm/month"
                    else:
                        rate = mm_per_day * 365
                        growth_rate = f"{rate:.1f} mm/year"
            except:
                pass
        
        return MeasurementCalculationResult(
            absolute_change=absolute_change,
            absolute_change_str=absolute_change_str,
            percentage_change=percentage_change,
            percentage_change_str=percentage_change_str,
            days_elapsed=days_elapsed,
            growth_rate=growth_rate
        )
    except Exception as e:
        return MeasurementCalculationResult(
            absolute_change=0,
            absolute_change_str="Calculation error",
            percentage_change=0,
            percentage_change_str="N/A",
            calculation_error=str(e)
        )


def _get_api_key_for_provider(provider: str, fallback_api_key: str = None) -> str:
    """
    Get the appropriate API key for a given provider.
    
    Args:
        provider: Provider string ('groq', 'anthropic', or 'cerebras')
        fallback_api_key: Optional API key to use for Anthropic provider
    
    Returns:
        API key string
    
    Raises:
        ValueError: If API key not found
    """
    import os
    
    if provider == 'groq':
        api_key = os.environ.get('GROQ_API_KEY')
        if not api_key:
            raise ValueError("Groq API key not configured. Please set GROQ_API_KEY environment variable.")
        return api_key
    elif provider == 'anthropic':
        api_key = fallback_api_key or os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("Anthropic API key not configured. Please set ANTHROPIC_API_KEY environment variable or provide as parameter.")
        return api_key
    elif provider == 'cerebras':
        api_key = os.environ.get('CEREBRAS_API_KEY')
        if not api_key:
            raise ValueError("Cerebras API key not configured. Please set CEREBRAS_API_KEY environment variable.")
        return api_key
    elif provider == 'fireworks':
        api_key = os.environ.get('FIREWORKS_API_KEY')
        if not api_key:
            raise ValueError("Fireworks API key not configured. Please set FIREWORKS_API_KEY environment variable.")
        return api_key
    else:
        raise ValueError(f"Unknown provider: {provider}. Must be 'groq', 'anthropic', 'cerebras', or 'fireworks'.")


def with_retry(max_retries=3, base_delay=2.0):
    """Retry decorator with exponential backoff for rate limits"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    error_str = str(e).lower()
                    
                    # Check if it's a rate limit error (use specific substrings to avoid
                    # matching unrelated words like "generate" which contains "rate")
                    is_rate_limit = (
                        "rate limit" in error_str
                        or "ratelimit" in error_str
                        or "rate_limit" in error_str
                        or "quota" in error_str
                        or "429" in error_str
                        or "too many requests" in error_str
                    )
                    if is_rate_limit:
                        if attempt < max_retries - 1:
                            delay = base_delay * (2 ** attempt)
                            print(f"Rate limit hit (attempt {attempt + 1}/{max_retries}), retrying in {delay}s...")
                            await asyncio.sleep(delay)
                            continue
                    
                    # If not a rate limit error, raise immediately
                    raise
            
            raise last_exception
        return wrapper
    return decorator


def _is_parsing_error(exception: Exception) -> bool:
    """
    Detect if error is a parsing/validation issue that won't be fixed by retrying.
    Returns True for structured output failures where model can't follow the schema.
    """
    from pydantic import ValidationError
    from pydantic_ai.exceptions import ModelHTTPError
    
    # Pydantic validation errors - model output doesn't match schema
    if isinstance(exception, ValidationError):
        return True
    
    if isinstance(exception, ModelHTTPError):
        if exception.status_code == 400:
            body_str = str(exception.body).lower()
            # Groq: tool_use_failed / failed to call a function
            if 'tool_use_failed' in body_str or 'failed to call a function' in body_str:
                return True
            # Cerebras/GLM: parser_error code or failed to generate tool_calls
            if 'parser_error' in body_str or 'failed to generate tool_call' in body_str:
                return True
    
    return False


def _recover_report_output_from_groq_tool_use_failed(exception: BaseException) -> Optional[ReportOutput]:
    """
    Groq returns HTTP 400 with code tool_use_failed when the model writes JSON in the
    assistant message instead of a valid function/tool call. The API still echoes that
    text in error.failed_generation — often a valid ReportOutput payload.
    """
    import json

    from pydantic import ValidationError
    from pydantic_ai.exceptions import ModelHTTPError

    def _failed_generation_string(exc: ModelHTTPError) -> Optional[str]:
        if exc.status_code != 400:
            return None
        body = getattr(exc, "body", None)
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                return None
        if not isinstance(body, dict):
            return None
        err = body.get("error")
        if not isinstance(err, dict):
            return None
        if err.get("code") != "tool_use_failed":
            return None
        fg = err.get("failed_generation")
        return fg if isinstance(fg, str) else None

    def _parse_failed_generation(raw: str) -> Optional[ReportOutput]:
        s = raw.strip()
        if s.startswith("```"):
            lines = s.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        try:
            data = json.loads(s)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        try:
            return ReportOutput.model_validate(data)
        except ValidationError:
            return None

    seen: set[int] = set()
    stack: List[BaseException] = [exception]
    while stack:
        e = stack.pop()
        if id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, ModelHTTPError):
            fg = _failed_generation_string(e)
            if fg:
                out = _parse_failed_generation(fg)
                if out is not None:
                    return out
        if e.__cause__ is not None:
            stack.append(e.__cause__)
        ctx = getattr(e, "__context__", None)
        if ctx is not None and ctx is not e.__cause__:
            stack.append(ctx)
    return None


def _to_plain_object(value: Any, depth: int = 0, max_depth: int = 5) -> Any:
    """Convert SDK objects into plain Python dict/list structures"""
    if depth > max_depth:
        return None

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    if isinstance(value, list):
        return [_to_plain_object(item, depth + 1, max_depth) for item in value]

    if isinstance(value, dict):
        return {k: _to_plain_object(v, depth + 1, max_depth) for k, v in value.items()}

    if hasattr(value, "to_dict"):
        try:
            return _to_plain_object(value.to_dict(), depth + 1, max_depth)
        except Exception:
            pass

    if hasattr(value, "__dict__"):
        return {
            k: _to_plain_object(v, depth + 1, max_depth)
            for k, v in vars(value).items()
            if not k.startswith("_")
        }

    return str(value)


def _extract_thinking_content(result) -> str:
    """
    Extract thinking/reasoning content from result's all_messages.
    Returns the full thinking content as a string.
    """
    thinking_parts = []
    try:
        if hasattr(result, 'all_messages') and result.all_messages:
            for msg in result.all_messages():
                if hasattr(msg, 'parts'):
                    for part in msg.parts:
                        if hasattr(part, '__class__') and 'thinking' in part.__class__.__name__.lower():
                            if hasattr(part, 'content'):
                                thinking_parts.append(part.content)
                            elif hasattr(part, 'text'):
                                thinking_parts.append(part.text)
                            else:
                                thinking_parts.append(str(part))
        return "\n\n".join(thinking_parts) if thinking_parts else ""
    except Exception as e:
        print(f"⚠️  Could not extract thinking content: {e}")
        return ""


def _log_glm_reasoning(result, context: str = ""):
    """
    Log reasoning content from Cerebras GLM (zai-glm-4.7) responses.
    GLM uses text_parsed reasoning format by default — reasoning is returned in a separate
    'reasoning' field on the OpenAI message object, not as a Pydantic AI thinking part.
    This function attempts to surface that reasoning for debugging purposes.
    """
    try:
        reasoning_content = ""

        # Attempt 1: check all_messages for any message with a 'reasoning' attribute
        if hasattr(result, 'all_messages') and result.all_messages:
            for msg in result.all_messages():
                if hasattr(msg, 'reasoning') and msg.reasoning:
                    reasoning_content = msg.reasoning
                    break
                # Also check parts for any reasoning-like content
                if hasattr(msg, 'parts'):
                    for part in msg.parts:
                        part_class = part.__class__.__name__.lower()
                        if 'reasoning' in part_class or 'thinking' in part_class:
                            content = getattr(part, 'content', None) or getattr(part, 'text', None)
                            if content:
                                reasoning_content = content
                                break

        # Attempt 2: check _result or raw response attributes
        if not reasoning_content and hasattr(result, '_result'):
            raw = result._result
            if hasattr(raw, 'reasoning'):
                reasoning_content = raw.reasoning or ""

        if reasoning_content:
            print(f"\n{'='*80}")
            print(f"🧠 GLM REASONING TRACE ({context}) — {len(reasoning_content)} chars")
            print(f"{'='*80}")
            print(reasoning_content)
            print(f"{'='*80}\n")
        else:
            print(f"ℹ️  No GLM reasoning trace captured ({context}) — reasoning may be in hidden format or not exposed by Pydantic AI")
    except Exception as e:
        print(f"⚠️  Could not log GLM reasoning ({context}): {e}")


def _log_thinking_parts(result, context: str = ""):
    """
    Log thinking parts from Claude's response (backend only - never sent to frontend).
    Thinking parts are automatically handled by Pydantic AI and not included in structured output.
    """
    try:
        # Extract thinking content
        thinking_content = _extract_thinking_content(result)
        
        if thinking_content:
            print(f"\n{'='*80}")
            print(f"🧠 THINKING PROCESS ({context})")
            print(f"{'='*80}")
            
            # Log truncated thinking (first 1000 chars for readability)
            if len(thinking_content) > 1000:
                print(f"{thinking_content[:1000]}...")
                print(f"\n[Thinking truncated - total length: {len(thinking_content)} chars]")
            else:
                print(thinking_content)
            print(f"{'='*80}\n")
        else:
            print(f"ℹ️  No thinking parts found in response ({context})")
    except Exception as e:
        # Silently fail - thinking logging is non-critical
        print(f"⚠️  Could not log thinking parts ({context}): {e}")


def _collect_url_candidates(data: Any) -> List[tuple]:
    """Traverse structure looking for URL, title, snippet tuples"""
    candidates = []

    if isinstance(data, dict):
        url = None
        title = ""
        snippet = ""

        for key, value in data.items():
            lower_key = key.lower()
            if lower_key in {"title", "name", "heading"} and isinstance(value, str):
                title = value
            elif lower_key in {"snippet", "description", "summary", "text"} and isinstance(value, str):
                if not snippet:
                    snippet = value
            elif lower_key in {"url", "uri", "link"} and isinstance(value, str):
                url = value
            else:
                candidates.extend(_collect_url_candidates(value))

        if url:
            candidates.append((url, title, snippet))

    elif isinstance(data, list):
        for item in data:
            candidates.extend(_collect_url_candidates(item))

    return candidates


def extract_sources(metadata_source, trusted_domains: List[str] | None = None) -> List[dict]:
    """Extract source URLs from grounding metadata"""
    plain_metadata = _to_plain_object(metadata_source)
    if not plain_metadata:
        return []

    seen_urls = set()
    sources = []

    for url, title, snippet in _collect_url_candidates(plain_metadata):
        domain = extract_domain(url)
        if trusted_domains:
            if not domain:
                continue
            if not any(allowed in domain for allowed in trusted_domains):
                continue
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append({
            "url": url,
            "title": title or domain or url,
            "snippet": snippet,
            "domain": domain
        })

    return sources


def extract_domain(url: str) -> str:
    """Extract domain from URL"""
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url


# Query keys that must not create a second evidence row (locale, tracking, etc.)
_DEDUPE_IGNORE_QUERY_KEYS = frozenset(
    k.lower()
    for k in (
        "lang",
        "hl",
        "ref",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
    )
)

def normalize_evidence_url_for_dedupe(url: str) -> str:
    """
    Stable key for deduplicating search-hit URLs (http/https, www, trailing slash, query).
    First-seen URL is kept in lists; later duplicates are dropped.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        p = urlparse(raw)
        scheme = (p.scheme or "https").lower()
        netloc = (p.netloc or "").lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = (p.path or "").rstrip("/") or "/"
        # Radiopaedia: same article often appears as /articles/foo and /articles/foo?lang=us
        if netloc == "radiopaedia.org":
            query = ""
        else:
            pairs = [
                (k, v)
                for k, v in parse_qsl(p.query, keep_blank_values=True)
                if k.lower() not in _DEDUPE_IGNORE_QUERY_KEYS
            ]
            pairs.sort()
            query = urlencode(pairs)
        return urlunparse((scheme, netloc, path, "", query, ""))
    except Exception:
        return raw


def build_guideline_markdown(summary: str, key_points: List[Dict[str, Any]]) -> str:
    """Combine summary text and key points into Markdown-friendly string (DEPRECATED - use build_radiologist_guideline_markdown)"""
    lines = []
    if summary:
        lines.append(summary.strip())

    for point in key_points or []:
        detail = point.get("detail", "")
        title = point.get("title", "")
        if not detail:
            continue
        if title:
            lines.append(f"- **{title}** — {detail}")
        else:
            lines.append(f"- {detail}")

    return "\n\n".join(lines).strip()


def build_radiologist_guideline_markdown(guideline_entry: GuidelineEntry) -> str:
    """Build structured markdown from radiologist-focused guideline structure"""
    sections = []
    
    # Diagnostic Overview
    if guideline_entry.diagnostic_overview:
        sections.append(guideline_entry.diagnostic_overview.strip())
    
    # Classification Systems
    if guideline_entry.classification_systems:
        sections.append("**Classification & Grading:**")
        for system in guideline_entry.classification_systems:
            sections.append(f"- **{system.name}** — {system.grade_or_category}: {system.criteria}")
    
    # Measurement Protocols
    if guideline_entry.measurement_protocols:
        sections.append("**Measurement Protocols:**")
        for measure in guideline_entry.measurement_protocols:
            sections.append(f"- **{measure.parameter}** — {measure.technique}")
            if measure.normal_range:
                sections.append(f"  - Normal: {measure.normal_range}")
            if measure.threshold:
                sections.append(f"  - Threshold: {measure.threshold}")
    
    # Imaging Characteristics
    if guideline_entry.imaging_characteristics:
        sections.append("**Key Imaging Features:**")
        for char in guideline_entry.imaging_characteristics:
            sections.append(f"- **{char.feature}** — {char.description} ({char.significance})")
    
    # Differential Diagnoses
    if guideline_entry.differential_diagnoses:
        sections.append("**Differential Diagnoses (Imaging Features):**")
        for ddx in guideline_entry.differential_diagnoses:
            sections.append(f"- **{ddx.diagnosis}** — {ddx.imaging_features}")
            if ddx.supporting_findings:
                sections.append(f"  - Supporting: {ddx.supporting_findings}")
    
    # Follow-up Imaging
    if guideline_entry.follow_up_imaging:
        sections.append("**Follow-up Imaging:**")
        for followup in guideline_entry.follow_up_imaging:
            sections.append(f"- **{followup.indication}** — {followup.modality}, {followup.timing}")
            if followup.technical_specs:
                sections.append(f"  - Technical: {followup.technical_specs}")
    
    return "\n\n".join(sections)



COMPREHENSIVE_RADIOLOGY_DOMAINS = [
    # == Core UK Professional & Guideline Bodies ==
    "rcr.ac.uk",        # The Royal College of Radiologists (Key guidelines, e.g., iRefer)
    "nice.org.uk",      # National Institute for Health and Care Excellence (All UK guidance)
    "bir.org.uk",       # British Institute of Radiology

    # == British Sub-Specialty Groups ==
    "bsgar.org",        # British Society of Gastrointestinal & Abdominal Radiology
    "bsir.org",         # British Society of Interventional Radiology
    "bsnr.org.uk",      # British Society of Neuroradiologists
    "bspr.org.uk",      # British Society of Paediatric Radiology
    "bssr.org.uk",      # British Society of Skeletal Radiologists
    "bsti.org.uk",      # British Society of Thoracic Imaging
    "bsci.org.uk",      # British Society of Cardiovascular Imaging
    "bsbr.org.uk",      # British Society of Breast Radiology
    "bshni.org.uk",     # British Society of Head and Neck Imaging
    "bnms.org.uk",      # British Nuclear Medicine Society

    # == User-Requested Global Resources ==
    "radiopaedia.org",  # Radiopaedia (Global educational resource)
    "rsna.org",         # Radiological Society of North America (Major US/Global body)

    # == To Include PubMed Abstracts ==
    "pubmed.ncbi.nlm.nih.gov",
]


def build_search_query(finding: str) -> str:
    """Create a single, focused search query for clinically actionable findings (DEPRECATED - use generate_radiology_search_queries)"""
    finding = finding.strip()
    if not finding:
        return "clinical radiology finding UK guidelines"

    # Focus on management and decision-making for actionable findings
    return f"{finding} UK radiology management guidelines clinical decision making"


async def generate_radiology_search_queries(finding: str, api_key: str) -> tuple[List[str], str]:
    """
    Generate 2-3 UK-focused radiology search queries using AI with fallback support.
    Model selection is driven by MODEL_CONFIG - supports any configured model with fallback.
    
    CACHED: Results are cached based on finding text (not api_key or settings).
    If same finding is queried again, cached queries are returned.
    
    Args:
        finding: The radiological finding to search for
        api_key: API key (kept for compatibility, actual key determined by provider)
        
    Returns:
        Tuple of (list of 2-3 focused search queries, model_name_used)
    """
    import os
    
    # Note: Caching is handled at search_guidelines_for_findings level using report content hash
    # This ensures same report content gets cached results even if finding normalization differs
    
    start_time = time.time()
    print(f"generate_radiology_search_queries: Generating queries for finding='{finding}'")
    
    system_prompt = (
        "Generate 3-5 focused search queries for radiology guidelines.\n\n"
        
        "CRITICAL - OUTPUT FORMAT:\n"
        "• Return a list of DIRECT STRING VALUES, not wrapped in objects\n"
        "• Example: ['query1', 'query2', 'query3'] NOT [{'text': 'query1'}, {'text': 'query2'}]\n"
        "• Each list item must be a plain string value\n\n"
        
        "REQUIREMENTS:\n"
        "• ADULT radiology only - always include 'adult' keyword\n"
        "• Use varied terminology: include synonyms, alternative phrasings, and related terms\n"
        "• Each query can target ONE aspect OR combine related aspects\n"
        "• 8-15 words per query - use descriptive phrases\n"
        
        "QUERY STRATEGY:\n"
        "Query 1: Classification/grading systems\n"
        "Query 2: Measurement techniques with thresholds and protocols\n"
        "Query 3: Differential diagnoses with distinguishing imaging features\n"
        "Query 4: Imaging characteristics and technical parameters\n"
        "Query 5: Follow-up imaging protocols and surveillance (if applicable)\n\n"
        
        "EXCLUDE: Pediatric systems, fetal guidelines\n"
        
        "FORMAT: ['query1', 'query2', 'query3', 'query4', 'query5']"
    )
    
    user_prompt = f"Generate 3-5 focused search queries for: {finding}"
    
    # Get primary model and provider
    primary_model = MODEL_CONFIG["QUERY_GENERATION"]
    primary_provider = _get_model_provider(primary_model)
    primary_api_key = _get_api_key_for_provider(primary_provider)
    
    # Try primary model first with explicit retry logic
    last_exception = None
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            # Build model settings with conditional reasoning_effort for Cerebras
            model_settings = {
                "temperature": 0.3,
            }
            if primary_model == "gpt-oss-120b":
                model_settings["max_completion_tokens"] = 500  # Generous token limit for Cerebras
                model_settings["reasoning_effort"] = "high"
                print(f"generate_radiology_search_queries: Using Cerebras reasoning_effort=high, max_completion_tokens=500 for {primary_model}")
            else:
                model_settings["max_tokens"] = 300
            
            result = await _run_agent_with_model(
                model_name=primary_model,
                output_type=list[str],
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=primary_api_key,
                use_thinking=False,  # Primary model doesn't use thinking (Cerebras uses reasoning_effort instead)
                model_settings=model_settings
            )
            
            queries = result.output
            
            # Ensure we have a list
            if not isinstance(queries, list):
                queries = [queries]
            
            # Limit to 5 queries
            queries = queries[:5]
            
            elapsed = time.time() - start_time
            print(f"generate_radiology_search_queries: ✅ Completed with {primary_model} (primary, attempt {attempt + 1}) in {elapsed:.2f}s")
            for i, q in enumerate(queries, 1):
                print(f"  Query {i}: {q}")
            
            return queries, primary_model
            
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                # Retry with exponential backoff
                delay = 2.0 * (2 ** attempt)
                print(f"⚠️ Primary model attempt {attempt + 1}/{max_retries} failed ({type(e).__name__}) - retrying in {delay:.1f}s...")
                print(f"  Error: {str(e)[:200]}")
                await asyncio.sleep(delay)
            else:
                # All retries exhausted
                fallback_model = MODEL_CONFIG['QUERY_GENERATION_FALLBACK']
                print(f"⚠️ Primary model failed after {max_retries} attempts ({type(e).__name__}) - falling back to {fallback_model}")
                print(f"  Final error: {str(e)[:200]}")
    
    # If we get here, all retries failed - fallback to fallback model
    try:
        fallback_model = MODEL_CONFIG["QUERY_GENERATION_FALLBACK"]
        fallback_provider = _get_model_provider(fallback_model)
        fallback_api_key = _get_api_key_for_provider(fallback_provider)
        
        result = await _run_agent_with_model(
            model_name=fallback_model,
            output_type=list[str],
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=fallback_api_key,
            use_thinking=(fallback_provider == 'groq'),  # Enable thinking for Groq fallback
            model_settings={"temperature": 0.3, "max_tokens": 300}
        )
        
        queries = result.output
        if not isinstance(queries, list):
            queries = [queries]
        queries = queries[:5]
        
        elapsed = time.time() - start_time
        print(f"generate_radiology_search_queries: ✅ Completed with {fallback_model} (fallback) in {elapsed:.2f}s")
        return queries, fallback_model
        
    except Exception as fallback_error:
        # Both models failed - return simple fallback query
        print(f"❌ Fallback model also failed: {type(fallback_error).__name__}")
        import traceback
        print(traceback.format_exc())
        fallback_query = f"{finding} UK radiology imaging classification measurement guidelines"
        print(f"  Falling back to simple query: {fallback_query}")
        return [fallback_query], "fallback-simple"


def _result_to_dict(result: Any) -> Dict[str, Any]:
    """Convert Perplexity result objects into dictionaries"""
    if isinstance(result, dict):
        data = dict(result)
    else:
        data = {}
        for field in ("title", "url", "snippet", "text", "content", "score", "date", "published_at"):
            if hasattr(result, field):
                data[field] = getattr(result, field)
        if not data and hasattr(result, "__dict__"):
            data.update({
                k: v for k, v in vars(result).items()
                if not k.startswith("_")
            })
        if not data:
            data["text"] = str(result)
    return data


def normalize_perplexity_results(search_response: Any, queries: List[str]) -> List[Dict[str, Any]]:
    """Flatten and normalize multi-query Perplexity results"""
    raw_results = getattr(search_response, "results", None)
    normalized: List[Dict[str, Any]] = []

    if isinstance(raw_results, list):
        # Multi-query returns list of lists
        for query_idx, query_results in enumerate(raw_results):
            query_text = queries[query_idx] if query_idx < len(queries) else queries[0] if queries else ""
            if isinstance(query_results, list):
                for item in query_results:
                    data = _result_to_dict(item)
                    data.setdefault("title", data.get("name") or data.get("url") or "")
                    snippet_text = data.get("text") or data.get("content") or ""
                    if snippet_text and len(snippet_text) > 320:
                        snippet_text = snippet_text[:317].rstrip() + "..."
                    data.setdefault("snippet", snippet_text)
                    data.setdefault("url", data.get("link") or "")
                    data["query"] = query_text
                    data["domain"] = extract_domain(data.get("url", ""))
                    normalized.append(data)
            else:
                data = _result_to_dict(query_results)
                data["query"] = query_text
                data["domain"] = extract_domain(data.get("url", ""))
                normalized.append(data)
    elif raw_results:
        # Single list
        query_text = queries[0] if queries else ""
        items = raw_results if isinstance(raw_results, list) else [raw_results]
        for item in items:
            data = _result_to_dict(item)
            data["query"] = query_text
            data["domain"] = extract_domain(data.get("url", ""))
            normalized.append(data)

    unique_results = []
    seen_urls = set()
    for item in normalized:
        url = item.get("url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        unique_results.append(item)

    return unique_results


def _extract_text_from_synthesis_card(card: Dict[str, Any]) -> str:
    """Serialize a new S4 synthesis card into a flat text representation for chat context."""
    parts: List[str] = []
    finding = card.get("finding") or card.get("finding_short_label") or ""
    if finding:
        parts.append(f"Finding: {finding}")
    summary = card.get("clinical_summary") or ""
    if summary:
        parts.append(summary)
    for a in card.get("follow_up_actions", []):
        parts.append(
            f"- Follow-up: {a.get('modality','')} {a.get('timing','')} "
            f"({a.get('indication','')}) [{a.get('guideline_source','')}]"
        )
    for c in card.get("classifications", []):
        parts.append(
            f"- Classification: {c.get('system','')} ({c.get('authority','')}) "
            f"grade {c.get('grade','')} — {c.get('management','')}"
        )
    for t in card.get("thresholds", []):
        parts.append(f"- Threshold: {t.get('parameter','')}: {t.get('threshold','')} — {t.get('significance','')}")
    for d in card.get("differentials", []):
        parts.append(f"- DDx: {d.get('diagnosis','')} — {d.get('key_features','')}")
    for f in card.get("imaging_flags", []):
        parts.append(f"- Flag: {f}")
    for s in card.get("sources", []):
        title = s.get("title") or s.get("domain") or ""
        url = s.get("url", "")
        if title or url:
            parts.append(f"- Source: {title} [{url}]")
    return "\n".join(parts)


def build_chat_guideline_context(
    findings: List[Dict[str, Any]],
    guidelines: List[Dict[str, Any]],
    max_total_chars: int,
) -> str:
    """
    Build EVIDENCE CONTEXT for report chat.

    Injects source excerpts (title + snippet from raw_evidence, or synthesized structured
    fields for older cached data) so the model can ground answers in real guideline text.
    No numbered [n] references are injected — sources are shown as a flat list to the model.
    """
    if max_total_chars < 500:
        max_total_chars = 500

    chunks: List[str] = []
    remaining = max_total_chars

    def append_text(text: str) -> None:
        nonlocal remaining
        if not text or remaining <= 0:
            return
        t = text.rstrip()
        if not t:
            return
        if len(t) <= remaining:
            chunks.append(t)
            remaining -= len(t)
            return
        if remaining > 100:
            chunks.append(t[: remaining - 40].rstrip() + "\n[truncated for length]\n")
        remaining = 0

    if findings or guidelines:
        append_text(
            "\n\n=== EVIDENCE CONTEXT ===\n"
            "The following source excerpts and synthesized notes ground answers about this report.\n"
            "Use society names and years exactly as written here. Do not invent citations.\n\n"
        )

    if findings:
        append_text("### Extracted Findings:\n")
        for finding in findings:
            append_text(f"- {finding.get('finding', 'N/A')}\n")
        append_text("\n")

    if not guidelines:
        return "".join(chunks)

    for guideline in guidelines:
        if remaining <= 0:
            break

        # Detect new S4 synthesis card shape (has follow_up_actions/classifications/imaging_flags)
        is_s4_card = any(
            k in guideline for k in ("follow_up_actions", "urgency_tier", "imaging_flags", "finding_short_label")
        )
        if is_s4_card:
            card_text = _extract_text_from_synthesis_card(guideline)
            if card_text:
                append_text(card_text + "\n\n")
            continue

        finding_name = guideline.get("finding", {})
        if isinstance(finding_name, dict):
            finding_name = finding_name.get("finding", "N/A")

        raw_evidence: List[Dict[str, Any]] = guideline.get("raw_evidence") or []
        if raw_evidence:
            _seen_ev: set[str] = set()
            _deduped: List[Dict[str, Any]] = []
            for _hit in raw_evidence:
                _k = normalize_evidence_url_for_dedupe((_hit.get("url") or ""))
                if not _k or _k in _seen_ev:
                    continue
                _seen_ev.add(_k)
                _deduped.append(_hit)
            raw_evidence = _deduped

        if raw_evidence:
            append_text(f"### Finding: {finding_name}\n")
            overview = guideline.get("diagnostic_overview") or ""
            if overview:
                append_text(f"{overview}\n\n")
            append_text("Source excerpts:\n")
            for item in raw_evidence:
                if remaining <= 0:
                    break
                title = (item.get("title") or "").strip()
                url = (item.get("url") or "").strip()
                snippet = (item.get("snippet") or "").strip()
                if not (title or snippet):
                    continue
                entry = f"- {title}"
                if url:
                    entry += f" [{url}]"
                if snippet:
                    entry += f": {snippet}"
                append_text(entry + "\n")
            append_text("\n")
        else:
            # Fallback for legacy cached data without raw_evidence
            append_text(f"### Finding: {finding_name}\n")
            overview = guideline.get("diagnostic_overview") or ""
            if overview:
                append_text(f"{overview}\n")
            for system in guideline.get("classification_systems") or []:
                if remaining <= 0:
                    break
                append_text(
                    f"- {system.get('name', '')}: {system.get('grade_or_category', '')} — {system.get('criteria', '')}\n"
                )
            for mp in guideline.get("measurement_protocols") or []:
                if remaining <= 0:
                    break
                append_text(
                    f"- {mp.get('parameter', '')}: {mp.get('technique', '')} "
                    f"(threshold: {mp.get('threshold', '')})\n"
                )
            for fi in guideline.get("follow_up_imaging") or []:
                if remaining <= 0:
                    break
                append_text(
                    f"- {fi.get('modality', '')} at {fi.get('timing', '')}: {fi.get('indication', '')}\n"
                )
            gsum = guideline.get("guideline_summary") or ""
            if gsum and remaining > 200:
                append_text(gsum[:800])
            append_text("\n")

    return "".join(chunks)


def format_audit_fix_holistic_workflow_instructions() -> str:
    """
    Staged reasoning for audit-triggered chat (single completion).
    Insert immediately before AUDIT QA GROUNDING when audit_fix_context is present.
    """
    return (
        "\n\n## Audit-triggered fix (holistic workflow)\n\n"
        "**Trigger vs task:** The user clicked a specific QA item. You must address that concern. "
        "That item is the **trigger**, not necessarily the **only** change needed for a sound report.\n\n"
        "In one reasoning pass before calling tools:\n"
        "1. **Understand** — From `## Report` and the enhancement context below, note clinically material "
        "claims and how **impression** aligns with **findings**.\n"
        "2. **Map** — Relate the triggered audit rationale (in AUDIT QA GROUNDING) to the report; identify "
        "any **material** omission or inconsistency supported by the report text itself.\n"
        "3. **Synthesize** — Choose proportionate wording; do not treat `suggested_replacement` as mandatory "
        "if a clearer clinical synthesis is justified (still respect named guideline frameworks in the grounding).\n"
        "4. **Act** — Call `apply_structured_actions` to fix the trigger **and** any material gaps you found; "
        "keep edits focused—no drive-by rewrites of unrelated sections.\n\n"
        "**Structure preservation (mandatory):** Certain report elements are structurally required by MDT "
        "workflow and must never be deleted as a resolution strategy:\n"
        "- **TNM staging strings** — correct the stage; do not remove it. If a staging axis is uncertain, "
        "use the 'x' descriptor (e.g. cTx, Nx, Mx) and state why, but keep the staging line.\n"
        "- **Referral/follow-up recommendations** — correct the destination or wording; do not omit.\n"
        "- **Measurement citations in the impression** — correct the value; do not drop it.\n"
        "If the audit flags an error in one of these, your job is to CORRECT the content using the "
        "enhancement context and guideline references — not to remove it. Removal of a required element "
        "is a worse outcome than a corrected-but-uncertain one.\n\n"
        "**Evidence-bound:** Add or change management statements only when supported by the presented report "
        "(and enhancement context). If key facts are missing or ambiguous, prefer conservative wording or brief "
        "note in your user-facing reply rather than inventing clinical detail.\n\n"
    )


def format_audit_fix_context_for_system_prompt(ctx: AuditFixContext) -> str:
    """Markdown section appended to chat system prompt when Fix-with-AI sends audit_fix_context."""
    lines: List[str] = [
        "\n\n## AUDIT QA GROUNDING\n",
        "The following is the **anchor** for the QA item the user chose. It constrains framework and "
        "guideline interpretation for that concern.\n"
        "It is **not** an exhaustive list of everything that might need improving—the audit may not flag "
        "every material gap. You must still cross-check **impression vs findings** using the full report "
        "and enhancement context.\n",
        "Do **not** substitute an alternative guideline framework "
        "(e.g. do not apply Fleischner if Lung-RADS is the named framework below, and vice versa).\n",
        "Avoid calling `search_external_guidelines` unless the information below is **clearly insufficient** "
        "for the substantive issues you are addressing.\n\n",
        f"- **Audit ID:** {ctx.audit_id or '(not persisted)'}\n",
        f"- **Criterion:** {ctx.criterion}\n",
        f"- **Rationale (deficiency):** {ctx.rationale}\n",
    ]
    if ctx.criterion_line:
        lines.append(f"- **Guideline rule line (criterion_line):** {ctx.criterion_line}\n")
    if ctx.highlighted_spans:
        lines.append("- **highlighted_spans (verbatim from report):**\n")
        for sp in ctx.highlighted_spans:
            lines.append(f"  - {sp!r}\n")
    if ctx.suggested_replacement:
        lines.append(f"- **suggested_replacement (drop-in if applicable):** {ctx.suggested_replacement}\n")
    if ctx.guideline_references:
        lines.append("\n### Guideline references (audit)\n")
        for ref in ctx.guideline_references:
            lines.append(f"- **{ref.system}** ({ref.type})\n")
            if ref.context:
                lines.append(f"  - Context: {ref.context}\n")
            if ref.criteria_summary:
                lines.append(f"  - Criteria excerpt: {ref.criteria_summary}\n")
    return "".join(lines)


def build_audit_guideline_references_memory_section(
    refs: List[Dict[str, Any]],
    max_total_chars: int,
    per_ref_summary_cap: int = 600,
) -> str:
    """
    In-session guideline snapshot from the last audit (stored under ENHANCEMENT_RESULTS).
    Kept separate from enhancement Phase-2 guidelines; optional precedence note in system prompt.
    """
    if not refs or max_total_chars < 200:
        return ""
    lines: List[str] = [
        "\n\n## LATEST AUDIT GUIDELINE CONTEXT\n",
        "Grounding from the most recent QA run in this server session — the report may have been edited since.\n",
        "Where this conflicts with generic enhancement evidence below on follow-up or classification, "
        "prefer the **framework named first** in this section for UK-ordered applicable guidelines.\n\n",
    ]
    used = sum(len(s) for s in lines)
    for ref in refs:
        if used >= max_total_chars:
            break
        system = str(ref.get("system") or "Guideline")
        typ = str(ref.get("type") or "")
        ctx = str(ref.get("context") or "").strip()
        raw_sum = ref.get("criteria_summary")
        summ = (str(raw_sum) if raw_sum else "").strip()
        if len(summ) > per_ref_summary_cap:
            summ = summ[: per_ref_summary_cap - 20].rstrip() + "\n[truncated]\n"
        chunk = f"### {system}"
        if typ:
            chunk += f" ({typ})"
        chunk += "\n"
        if ctx:
            chunk += f"{ctx}\n"
        if summ:
            chunk += f"{summ}\n"
        chunk += "\n"
        if used + len(chunk) > max_total_chars:
            chunk = chunk[: max_total_chars - used - 30].rstrip() + "\n[truncated]\n"
        lines.append(chunk)
        used += len(chunk)
    return "".join(lines)


_CHAT_SOURCE_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "from",
        "what",
        "say",
        "does",
        "about",
        "how",
        "are",
        "was",
        "were",
        "you",
        "your",
        "can",
        "any",
        "has",
        "have",
        "had",
        "not",
        "but",
        "all",
        "each",
        "our",
        "out",
        "use",
        "using",
        "into",
        "than",
        "then",
        "them",
        "they",
        "its",
        "also",
        "just",
        "only",
        "very",
        "when",
        "will",
        "would",
        "could",
        "should",
        "please",
        "like",
        "want",
        "need",
        "tell",
        "give",
        "some",
        "such",
        "who",
        "why",
        "way",
        "may",
        "did",
        "get",
    }
)


def _chat_corpus_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _CHAT_SOURCE_STOPWORDS}


_SOCIETY_ACRONYM_EXPANSIONS: Dict[str, str] = {
    "bts": "british thoracic society",
    "acr": "american college radiology",
    "ats": "american thoracic society",
    "ers": "european respiratory society",
    "nice": "national institute health care excellence",
    "esmo": "european society medical oncology",
    "asco": "american society clinical oncology",
    "itmig": "international thymic malignancy interest group",
    "lung-rads": "lung rads",
    "lungrads": "lung rads",
    "fleischner": "fleischner society pulmonary nodule",
}


async def select_guidelines_for_chat_question(
    guidelines: List[Dict[str, Any]],
    user_message: str,
    max_guidelines: int = 2,
    history: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Select the most relevant guidelines for a chat question.

    Scoring strategy (best-available wins):
    1. Semantic: embed the query context and each guideline's finding+overview text,
       then use cosine similarity. Falls back to (2) if OPENAI_API_KEY is absent.
    2. Lexical: token overlap with acronym expansion and conversation history context.

    In both cases the fallback is top-1, never the full unfiltered list.
    """
    if not guidelines:
        return []
    if len(guidelines) == 1:
        return guidelines

    # Build query context: current message + last 3 user turns from history
    history_text = ""
    if history:
        recent_user = [m.get("content", "") for m in history if m.get("role") == "user"][-3:]
        history_text = " ".join(recent_user)
    context = f"{user_message} {history_text}".strip()

    # ── Try semantic scoring first ────────────────────────────────────────────
    guideline_blobs = []
    for g in guidelines:
        fn = g.get("finding", {})
        finding_text = fn.get("finding", "") if isinstance(fn, dict) else str(fn)
        overview = str(g.get("diagnostic_overview") or "")
        gsum = str(g.get("guideline_summary") or "")[:400]
        guideline_blobs.append(f"{finding_text}. {overview} {gsum}".strip())

    all_texts = [context] + guideline_blobs
    embeddings = await _batch_embed(all_texts)

    if embeddings is not None:
        query_vec = embeddings[0]
        sem_scores = [_cosine_similarity(query_vec, embeddings[i + 1]) for i in range(len(guidelines))]
        scored_sem = sorted(enumerate(sem_scores), key=lambda x: -x[1])
        best_sem = scored_sem[0][1]
        # Include guidelines within 0.08 cosine of the best, up to max_guidelines
        threshold_sem = max(0.0, best_sem - 0.08)
        selected = [guidelines[i] for i, s in scored_sem if s >= threshold_sem][:max_guidelines]
        if selected:
            print(f"[guideline-select] semantic  scores: {[(guidelines[i].get('finding', {}).get('finding', '?')[:30], round(s, 3)) for i, s in scored_sem]}")
            return selected

    # ── Lexical fallback ──────────────────────────────────────────────────────
    # Expand society acronyms so "BTS?" matches "british thoracic society"
    context_expanded = context
    for acronym, expansion in _SOCIETY_ACRONYM_EXPANSIONS.items():
        pattern = rf"\b{re.escape(acronym)}\b"
        context_expanded = re.sub(pattern, f"{acronym} {expansion}", context_expanded, flags=re.IGNORECASE)

    utoks = _chat_corpus_tokens(context_expanded)
    if not utoks:
        return guidelines[:1]

    def _tok_variants(toks: set[str]) -> set[str]:
        v = set(toks)
        for t in list(toks):
            if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
                v.add(t[:-1])
        return v

    utoks_v = _tok_variants(utoks)
    scored_lex: List[tuple[float, Dict[str, Any]]] = []
    for g, blob in zip(guidelines, guideline_blobs):
        gtoks_v = _tok_variants(_chat_corpus_tokens(blob))
        overlap = float(len(utoks_v & gtoks_v))
        scored_lex.append((overlap, g))

    scored_lex.sort(key=lambda x: -x[0])
    best_lex = scored_lex[0][0]
    print(f"[guideline-select] lexical   scores: {[(g.get('finding', {}).get('finding', '?')[:30], round(s, 3)) for s, g in scored_lex]}")

    if best_lex <= 0:
        return [scored_lex[0][1]]

    selected_lex: List[Dict[str, Any]] = []
    threshold_lex = max(1.0, best_lex - 1.0)
    for score, g in scored_lex:
        if score >= threshold_lex and len(selected_lex) < max_guidelines:
            selected_lex.append(g)
    return selected_lex if selected_lex else [scored_lex[0][1]]


def collect_guideline_sources_for_chat(guidelines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduped source links from enhancement guideline payloads for chat API.

    Prefers ``raw_evidence`` when available: these are the original Perplexity hits with
    real snippets, stored in order during the pipeline run. The returned list is ordered
    consistently with the [n] numbering injected by ``build_chat_guideline_context``, so
    the frontend can show reliable numbered references.

    Falls back to the legacy ``sources`` list (no snippets) for older cached data.
    """
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for guideline in guidelines:
        # S4 synthesis cards have "sources" with url/title/domain and also
        # follow_up_actions[].guideline_source and classifications[].authority
        evidence_list = guideline.get("raw_evidence") or guideline.get("sources") or []
        for s in evidence_list:
            url = (s.get("url") or "").strip()
            dedupe_key = normalize_evidence_url_for_dedupe(url)
            if not url or not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            title_raw = (s.get("title") or "").strip()
            snippet_raw = (s.get("snippet") or "").strip()
            out.append(
                {
                    "url": url,
                    "title": sanitize_chat_source_text(title_raw, max_display=None) or title_raw,
                    "domain": s.get("domain") or extract_domain(url),
                    "snippet": sanitize_chat_source_text(snippet_raw, 400) if snippet_raw else "",
                }
            )
    return out


def _pubmed_age_penalty(url: str) -> float:
    """Small penalty (0–1.5) for old PubMed entries, based on PMID range."""
    if "pubmed.ncbi.nlm.nih.gov" not in url:
        return 0.0
    pmid_match = re.search(r"/(\d{5,8})/?$", url)
    if not pmid_match:
        return 0.0
    pmid = int(pmid_match.group(1))
    if pmid < 8_000_000:    # ~pre-1997
        return 1.5
    if pmid < 12_000_000:   # ~pre-2002
        return 1.0
    if pmid < 16_000_000:   # ~pre-2006
        return 0.5
    return 0.0


async def filter_chat_sources_by_relevance(
    sources: List[Dict[str, Any]],
    user_message: str,
    assistant_message: str,
    max_sources: int = 4,
) -> List[Dict[str, Any]]:
    """
    Rank sources by relevance to the user question + assistant reply, then return the top N.

    Hybrid scoring via Reciprocal Rank Fusion (RRF, k=60):
    - Semantic rank: cosine similarity between query embedding and (title + snippet) embedding
    - Lexical rank:  token overlap + long-word substring bonus + PubMed age penalty

    Falls back to lexical-only if the embedding API is unavailable.
    Always returns at least 1 source.
    """
    if not sources:
        return []

    # ── Build lexical corpus ──────────────────────────────────────────────────
    full_text = f"{user_message or ''}\n{assistant_message or ''}"
    corpus = full_text.lower()
    corpus_tokens = _chat_corpus_tokens(corpus)
    for ac in re.findall(r"\b([A-Z]{2,6})\b", full_text):
        corpus_tokens.add(ac.lower())
    for acronym, expansion in _SOCIETY_ACRONYM_EXPANSIONS.items():
        if acronym in corpus_tokens:
            corpus_tokens.update(_chat_corpus_tokens(expansion))

    def _lex_score(src: Dict[str, Any]) -> float:
        title = (src.get("title") or "").lower()
        url = (src.get("url") or "").lower()
        domain = (src.get("domain") or "").lower()
        snippet = (src.get("snippet") or "").lower()
        blob_main = f"{title} {url} {domain}"
        s = float(len(_chat_corpus_tokens(blob_main) & corpus_tokens))
        s += 0.5 * float(len(_chat_corpus_tokens(snippet) & corpus_tokens))
        for w in re.findall(r"[a-z]{5,}", blob_main):
            if w in corpus:
                s += 0.75
        s -= _pubmed_age_penalty(url)
        return s

    lex_scores = [_lex_score(src) for src in sources]

    # ── Try semantic scoring ──────────────────────────────────────────────────
    # Query = user message + recent assistant response (first 300 chars to keep it focused)
    query_text = f"{user_message or ''} {(assistant_message or '')[:300]}".strip()
    source_texts = [
        f"{(src.get('title') or '')} {(src.get('snippet') or '')[:300]}".strip()
        for src in sources
    ]
    all_texts = [query_text] + source_texts
    embeddings = await _batch_embed(all_texts)

    sem_scores: Optional[List[float]] = None
    if embeddings is not None:
        query_vec = embeddings[0]
        raw_sem = [_cosine_similarity(query_vec, embeddings[i + 1]) for i in range(len(sources))]
        # Apply age penalty on top of semantic score so old papers are still deprioritised
        sem_scores = [s - _pubmed_age_penalty(src.get("url", "")) for s, src in zip(raw_sem, sources)]

    # ── Reciprocal Rank Fusion ────────────────────────────────────────────────
    RRF_K = 60
    # Rank lists: lower rank index = better (0-based, sorted descending by score)
    lex_order = sorted(range(len(sources)), key=lambda i: -lex_scores[i])
    lex_rank = [0] * len(sources)
    for rank, idx in enumerate(lex_order):
        lex_rank[idx] = rank

    if sem_scores is not None:
        sem_order = sorted(range(len(sources)), key=lambda i: -sem_scores[i])
        sem_rank = [0] * len(sources)
        for rank, idx in enumerate(sem_order):
            sem_rank[idx] = rank
        rrf = [1 / (RRF_K + lex_rank[i]) + 1 / (RRF_K + sem_rank[i]) for i in range(len(sources))]
        mode = "hybrid"
    else:
        rrf = [1 / (RRF_K + lex_rank[i]) for i in range(len(sources))]
        mode = "lexical"

    ranked = sorted(range(len(sources)), key=lambda i: -rrf[i])
    print(f"[source-filter] {mode} RRF ranking ({len(sources)} candidates → top {max_sources}):")
    for pos, idx in enumerate(ranked[:max_sources]):
        src = sources[idx]
        title = (src.get("title") or src.get("domain") or "?")[:55]
        sem_str = f"  sem={sem_scores[idx]:.3f}" if sem_scores else ""
        print(f"  [{pos+1}] lex={lex_scores[idx]:.2f}{sem_str}  rrf={rrf[idx]:.4f}  {title}")

    # Filter out sources with strongly negative lex scores AND low semantic scores
    # (i.e. sources that are irrelevant on both dimensions)
    def _keep(idx: int) -> bool:
        if sem_scores is not None:
            return lex_scores[idx] > -1.0 or sem_scores[idx] > 0.2
        return lex_scores[idx] > -1.0

    filtered = [sources[idx] for idx in ranked if _keep(idx)]
    if not filtered:
        filtered = [sources[ranked[0]]]  # always return at least 1
    return filtered[:max_sources]


def sanitize_chat_source_text(text: str, max_display: Optional[int] = 420) -> str:
    """
    Plain-text preview for source snippets/titles: strip common Markdown so UI does not show ** or #.
    """
    if not text:
        return ""
    t = text.replace("\r\n", "\n")
    t = re.sub(r"^#+\s*", "", t, flags=re.MULTILINE)
    # Bold / italic (non-greedy; repeat for nested remnants)
    for _ in range(4):
        t2 = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
        t2 = re.sub(r"__([^_]+)__", r"\1", t2)
        t2 = re.sub(r"(?<!\*)\*(?!\*)([^*]+)\*(?!\*)", r"\1", t2)
        if t2 == t:
            break
        t = t2
    t = re.sub(r"`+([^`]+)`+", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    if max_display is not None and len(t) > max_display:
        t = t[: max_display - 3].rstrip() + "..."
    return t


def _excerpt_for_chat_hit(item: Dict[str, Any], max_chars: int) -> str:
    raw = item.get("text") or item.get("content") or item.get("snippet") or ""
    raw = (raw or "").strip()
    cleaned = sanitize_chat_source_text(raw, max_display=None)
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


async def run_perplexity_search_chat(
    queries: List[str],
    *,
    max_results_per_query: int = 3,
    max_excerpt_chars: int = 1000,
    max_hits_total: int = 5,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Run Perplexity search for chat grounding. Returns (evidence_block, sources) for the model and API.
    Uses the same domain/language fallback strategy as guideline pipeline search.
    """
    queries = [q.strip() for q in queries if q and q.strip()][:3]
    if not queries:
        return "", []

    cache = get_cache()
    qh = generate_query_hash(queries)
    cache_key = f"chat_perplexity:{qh}"
    cached = cache.get(cache_key)
    if cached is not None:
        search_results: List[Dict[str, Any]] = list(cached)
        print(f"run_perplexity_search_chat: [CACHE HIT] {cache_key[:48]}...")
    else:
        perplexity_client = Perplexity()
        search_results = None

        try:
            search_response = await asyncio.to_thread(
                lambda: perplexity_client.search.create(
                    query=queries,
                    max_results=max_results_per_query,
                    max_tokens_per_page=1024,
                    search_language_filter=["en"],
                    search_domain_filter=COMPREHENSIVE_RADIOLOGY_DOMAINS,
                )
            )
            search_results = normalize_perplexity_results(search_response, queries)
            if search_results:
                print(f"run_perplexity_search_chat: restricted domains → {len(search_results)} hits")
        except Exception as e:
            print(f"run_perplexity_search_chat: attempt 1 (domains) failed: {e}")

        if not search_results:
            try:
                perplexity_client = Perplexity()
                search_response = await asyncio.to_thread(
                    lambda: perplexity_client.search.create(
                        query=queries,
                        max_results=max_results_per_query,
                        max_tokens_per_page=1024,
                        search_language_filter=["en"],
                    )
                )
                search_results = normalize_perplexity_results(search_response, queries)
                if search_results:
                    print(f"run_perplexity_search_chat: no domain filter → {len(search_results)} hits")
            except Exception as e:
                print(f"run_perplexity_search_chat: attempt 2 failed: {e}")

        if not search_results:
            try:
                perplexity_client = Perplexity()
                search_response = await asyncio.to_thread(
                    lambda: perplexity_client.search.create(
                        query=queries,
                        max_results=max_results_per_query,
                        max_tokens_per_page=1024,
                    )
                )
                search_results = normalize_perplexity_results(search_response, queries)
                if search_results:
                    print(f"run_perplexity_search_chat: no filters → {len(search_results)} hits")
            except Exception as e:
                print(f"run_perplexity_search_chat: attempt 3 failed: {e}")

        if search_results is None:
            search_results = []
        cache.set(cache_key, search_results)

    hits = search_results[:max_hits_total]
    lines: List[str] = ["=== EXTERNAL SEARCH EVIDENCE (use for this answer) ===\n"]
    sources: List[Dict[str, Any]] = []

    for i, item in enumerate(hits, start=1):
        title = (item.get("title") or item.get("name") or "Untitled").strip()
        url = (item.get("url") or item.get("link") or "").strip()
        excerpt = _excerpt_for_chat_hit(item, max_excerpt_chars)
        domain = item.get("domain") or extract_domain(url)
        lines.append(f"[{i}] {title}\nURL: {url}\nDomain: {domain}\nExcerpt:\n{excerpt}\n")
        snippet_plain = sanitize_chat_source_text(excerpt, 400)
        sources.append(
            {
                "url": url,
                "title": sanitize_chat_source_text(title, max_display=None) or title,
                "domain": domain,
                "snippet": snippet_plain,
            }
        )

    return "\n".join(lines), sources


async def _extract_consolidated_with_model(
    model_name: str,
    model_label: str,
    report_content: str,
    api_key: str
) -> ConsolidationResult:
    """
    Helper function to extract consolidated findings with a specific model.
    
    Args:
        model_name: Model identifier (e.g., "qwen/qwen3-32b", "gpt-oss-120b")
        model_label: Human-readable model name for logging
        report_content: The generated radiology report text
        api_key: API key for the model provider
    
    Returns:
        ConsolidationResult with consolidated findings
    """
    import os
    
    start_time = time.time()
    print(f"extract_consolidated_findings: Attempting with {model_label}...")
    
    provider = _get_model_provider(model_name)
    
    system_prompt = (
        "You are an expert radiologist extracting findings that require radiological assessment and characterization.\n\n"
        "CRITICAL - OUTPUT FORMAT:\n"
        "• All string fields (finding, specialty, type, guideline_focus) must be returned as DIRECT STRING VALUES, not wrapped in objects\n"
        "• Example: finding: 'lung nodule' NOT finding: {'text': 'lung nodule'}\n"
        "• Example: specialty: 'chest/thoracic' NOT specialty: {'text': 'chest/thoracic'}\n"
        "• Return plain string values for all text fields\n\n"
        "TASK: Identify up to 5 distinct findings requiring diagnostic imaging assessment, classification, or follow-up protocols.\n"
        "If the report is completely normal, return an empty findings list.\n\n"
        "CRITICAL: Use broad categorical terms only - NO specific descriptors\n"
        "❌ AVOID: Exact rib numbers (e.g., '6th-9th rib fractures'), specific measurements, detailed anatomical locations\n"
        "✅ USE: Broad terms (e.g., 'acute rib fractures', 'chronic rib fractures', 'multiple rib fractures')\n\n"
        "INCLUDE:\n"
        "- Findings requiring classification/grading systems\n"
        "- Lesions needing imaging characterization\n"
        "- Acute injuries (fractures, dislocations)\n"
        "- Vascular abnormalities (stenosis, aneurysms, thrombus)\n"
        "- Findings requiring follow-up imaging\n\n"
        "EXCLUDE:\n"
        "- Negative or normal findings\n"
        "- Benign incidental findings with no workup needed\n"
        "- Age-appropriate degenerative changes\n"
        "- Technical artifacts\n\n"
        "GROUPING:\n"
        "- ONLY group multiple instances of the SAME finding type (e.g., multiple rib fractures → 'multiple rib fractures')\n"
        "- Keep distinct finding types SEPARATE, even if they are related complications or share a common cause\n"
        "- Use contextual descriptors (acute, traumatic, etc.) but maintain separate entries for each distinct finding type\n\n"
        "OUTPUT:\n"
        "- Use broad categorical terms only\n"
        "- Return up to 5 findings, prioritizing those needing assessment protocols\n"
        "- All string fields must be direct string values\n"
    )
    
    user_prompt = f"Extract and consolidate findings from this report:\n\n{report_content}"
    
    # Build model settings with conditional reasoning_effort for Cerebras
    model_settings = {
        "temperature": 0.2,
    }
    if model_name == "gpt-oss-120b":
        model_settings["max_completion_tokens"] = 2500  # Generous token limit for Cerebras
        model_settings["reasoning_effort"] = "high"
        print(f"  └─ Using Cerebras reasoning_effort=high, max_completion_tokens=2500 for {model_name}")
        use_thinking = False  # Cerebras uses reasoning_effort instead
    else:
        model_settings["max_tokens"] = 2048
        # Only enable thinking for Groq models that support reasoning_format (Qwen, not Llama)
        use_thinking = (provider == 'groq' and 'qwen' in model_name.lower())
    
    result = await _run_agent_with_model(
        model_name=model_name,
        output_type=ConsolidationResult,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        use_thinking=use_thinking,  # Only enable for Qwen models, not Llama or Cerebras
        model_settings=model_settings
    )
    
    consolidated_result: ConsolidationResult = result.output
    
    print(f"  └─ Consolidated into {len(consolidated_result.findings)} findings:")
    for idx, finding in enumerate(consolidated_result.findings, start=1):
        print(f"    {idx}. {finding.finding}")
    
    elapsed = time.time() - start_time
    print(f"extract_consolidated_findings: ✅ Completed with {model_label} in {elapsed:.2f}s")
    return consolidated_result


# DEPRECATED — replaced by S1 finding extraction in guideline_prefetch.run_prefetch_pipeline
@with_retry(max_retries=3, base_delay=2.0)
async def extract_consolidated_findings(report_content: str, api_key: str) -> ConsolidationResult:
    """
    Extract and consolidate radiological findings with intelligent fallback.
    Uses configured finding extraction model first, falls back to guideline search model on parsing errors or after retry exhaustion.

    Args:
        report_content: The generated radiology report text
        api_key: Groq API key

    Returns:
        ConsolidationResult with 3-5 consolidated findings optimized for guideline searches
    """
    try:
        # Try primary extraction model first
        primary_model = MODEL_CONFIG["FINDING_EXTRACTION"]
        provider = _get_model_provider(primary_model)
        primary_api_key = _get_api_key_for_provider(provider)
        
        return await _extract_consolidated_with_model(
            primary_model,
            f"{primary_model} (Primary)",
            report_content,
            primary_api_key
        )
    except Exception as e:
        # Determine why we're falling back
        if _is_parsing_error(e):
            print(f"⚠️ Primary extraction model parsing error detected - immediate fallback to {MODEL_CONFIG['FINDING_EXTRACTION_FALLBACK']}")
            print(f"  Error: {type(e).__name__}: {str(e)[:200]}")
        else:
            print(f"⚠️ Primary extraction model failed after retries ({type(e).__name__}) - falling back to {MODEL_CONFIG['FINDING_EXTRACTION_FALLBACK']}")
            print(f"  Error: {str(e)[:200]}")
        
        # Fallback to finding extraction fallback model
        try:
            fallback_model = MODEL_CONFIG["FINDING_EXTRACTION_FALLBACK"]
            fallback_provider = _get_model_provider(fallback_model)
            fallback_api_key = _get_api_key_for_provider(fallback_provider)
            
            return await _extract_consolidated_with_model(
                fallback_model,
                f"{fallback_model} (fallback)",
                report_content,
                fallback_api_key
            )
        except Exception as fallback_error:
            # Both models failed - re-raise the original error with context
            print(f"❌ Llama fallback also failed: {type(fallback_error).__name__}")
            import traceback
            print(traceback.format_exc())
            raise Exception(f"Finding extraction failed with both Qwen and Llama. Original error: {e}") from e


async def filter_compatible_search_results(
    search_results: List[Dict[str, Any]],
    finding: str,
    api_key: str
) -> List[Dict[str, Any]]:
    """
    Filter search results to ensure they match the clinical premise of the finding.
    Uses batch processing to check all results in a single API call for efficiency.
    Model selection is driven by MODEL_CONFIG - supports any configured model with fallback.
    
    Args:
        search_results: List of search result dictionaries from Perplexity
        finding: The radiological finding text (e.g., "frontotemporal lesions")
        api_key: API key (kept for compatibility, actual key determined by provider)
        
    Returns:
        Filtered list of compatible search results (same structure as input)
    """
    import os
    
    if not search_results:
        return []
    
    start_time = time.time()
    print(f"filter_compatible_search_results: Checking {len(search_results)} results for finding '{finding}'")
    
    # Build batch prompt with all results
    batch_prompt = (
        f"Finding: {finding}\n\n"
        f"Assess {len(search_results)} search results for clinical relevance.\n\n"
        "Compatible = Results that are clinically relevant to the finding:\n"
        "- Same or related anatomy (e.g., 'colon' matches 'pancolitis')\n"
        "- Same or related pathology (e.g., 'colitis' matches 'pancolitis')\n"
        "- Relevant imaging findings or protocols\n"
        "Include results that substantially match the clinical entity, even if terminology differs slightly.\n\n"
        "Incompatible = Clearly unrelated findings:\n"
        "- Different anatomy (e.g., 'lung' when finding is 'colon')\n"
        "- Different pathology (e.g., 'fracture' when finding is 'inflammation')\n"
        "- Unrelated imaging findings\n\n"
        "Results:\n"
    )
    
    for i, result in enumerate(search_results):
        title = (result.get("title") or "").strip()
        # Full text for relevance: prefetch supplies `content`; Perplexity uses `snippet`
        body = (result.get("content") or result.get("snippet") or "").strip()
        url = (result.get("url") or "").strip()
        batch_prompt += f"{i}. Title: {title}\n"
        if url:
            batch_prompt += f"   URL: {url}\n"
        batch_prompt += f"   Content:\n{body}\n\n"
    
    batch_prompt += (
        "Return a JSON array string containing 0-based indices for compatible results only.\n"
        "Example: '[0, 2, 5, 7]' means results at indices 0, 2, 5, and 7 are compatible.\n"
        "Return '[]' if none are compatible. Return ONLY valid JSON array format."
    )
    
    system_prompt = (
        "Medical expert assessing clinical relevance. Include results that are substantially related to the finding, "
        "even if terminology or phrasing differs slightly. Only exclude clearly unrelated findings.\n\n"
        "CRITICAL - OUTPUT FORMAT:\n"
        "• Return a DIRECT STRING VALUE containing a JSON array, not wrapped in an object\n"
        "• Example: '[0, 2, 5]' NOT {'text': '[0, 2, 5]'}\n"
        "• Example: '[]' NOT {'text': '[]'}\n"
        "• The indices_json field must be a plain string containing valid JSON array format\n"
        "• Return a JSON array string with compatible indices (0-based). Example: '[0, 2, 5]' or '[]'."
    )
    
    # Get primary model and provider
    primary_model = MODEL_CONFIG["COMPATIBILITY_FILTER"]
    primary_provider = _get_model_provider(primary_model)
    primary_api_key = _get_api_key_for_provider(primary_provider)
    
    # Try primary model first with explicit retry logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Build model settings with conditional reasoning_effort for Cerebras
            model_settings = {
                "temperature": 0.2,  # Slightly higher temperature for less strict filtering
            }
            if primary_model == "gpt-oss-120b":
                model_settings["max_completion_tokens"] = 300  # Generous token limit for JSON array
                model_settings["reasoning_effort"] = "medium"  # Medium reasoning for binary validation decisions
                print(f"filter_compatible_search_results: Using Cerebras reasoning_effort=medium, max_completion_tokens=300, temperature=0.2 for {primary_model}")
            else:
                model_settings["max_tokens"] = 200
            
            result = await _run_agent_with_model(
                model_name=primary_model,
                output_type=CompatibleIndicesResponse,
                system_prompt=system_prompt,
                user_prompt=batch_prompt,
                api_key=primary_api_key,
                use_thinking=False,  # Primary model doesn't use thinking (Cerebras uses reasoning_effort instead)
                model_settings=model_settings
            )
            
            # Parse indices from the JSON string
            compatible_indices = result.output.get_indices()
            
            # Filter to valid indices
            compatible_indices = [idx for idx in compatible_indices if 0 <= idx < len(search_results)]
            
            filtered_results = [search_results[i] for i in compatible_indices]
            
            elapsed = time.time() - start_time
            print(f"filter_compatible_search_results: ✅ Filtered {len(search_results)} → {len(filtered_results)} compatible results in {elapsed:.2f}s")
            if len(filtered_results) < len(search_results):
                removed_count = len(search_results) - len(filtered_results)
                removed_indices = [i for i in range(len(search_results)) if i not in compatible_indices]
                print(f"  └─ Removed {removed_count} incompatible result(s) at indices: {removed_indices}")
            else:
                print(f"  └─ All {len(search_results)} results compatible")
            
            return filtered_results
            
        except Exception as e:
            if attempt < max_retries - 1:
                # Retry with exponential backoff
                delay = 2.0 * (2 ** attempt)
                print(f"⚠️ Primary model attempt {attempt + 1}/{max_retries} failed ({type(e).__name__}) - retrying in {delay:.1f}s...")
                print(f"  Error: {str(e)[:200]}")
                await asyncio.sleep(delay)
            else:
                # All retries exhausted
                fallback_model = MODEL_CONFIG['COMPATIBILITY_FILTER_FALLBACK']
                print(f"⚠️ Primary model failed after {max_retries} attempts ({type(e).__name__}) - falling back to {fallback_model}")
                print(f"  Final error: {str(e)[:200]}")
    
    # If we get here, all retries failed - fallback to fallback model
    try:
        fallback_model = MODEL_CONFIG["COMPATIBILITY_FILTER_FALLBACK"]
        fallback_provider = _get_model_provider(fallback_model)
        fallback_api_key = _get_api_key_for_provider(fallback_provider)
        
        result = await _run_agent_with_model(
            model_name=fallback_model,
            output_type=CompatibleIndicesResponse,
            system_prompt=system_prompt,
            user_prompt=batch_prompt,
            api_key=fallback_api_key,
            use_thinking=(fallback_provider == 'groq'),  # Enable thinking for Groq fallback
            model_settings={"temperature": 0.1, "max_tokens": 200}
        )
        
        # Parse indices from the JSON string
        compatible_indices = result.output.get_indices()
        
        # Filter to valid indices
        compatible_indices = [idx for idx in compatible_indices if 0 <= idx < len(search_results)]
        
        filtered_results = [search_results[i] for i in compatible_indices]
        
        elapsed = time.time() - start_time
        print(f"filter_compatible_search_results: ✅ Filtered {len(search_results)} → {len(filtered_results)} compatible results in {elapsed:.2f}s (fallback)")
        if len(filtered_results) < len(search_results):
            removed_count = len(search_results) - len(filtered_results)
            removed_indices = [i for i in range(len(search_results)) if i not in compatible_indices]
            print(f"  └─ Removed {removed_count} incompatible result(s) at indices: {removed_indices}")
        else:
            print(f"  └─ All {len(search_results)} results compatible")
        
        return filtered_results
        
    except Exception as fallback_error:
        # Both models failed - return all results (fail-safe - better to have some results than none)
        print(f"⚠️  Compatibility filter error (both models failed): {fallback_error}")
        print(f"  └─ Returning all {len(search_results)} results (fail-safe)")
        import traceback
        print(traceback.format_exc())
        return search_results


async def validate_guideline_compatibility(
    guideline_entry,  # Union[GuidelineEntry, RichGuidelineEntry]
    finding: str,
    api_key: str
) -> bool:
    """
    Validate that synthesized guideline matches the clinical premise of the finding.
    Accepts both GuidelineEntry (legacy) and RichGuidelineEntry (v2) via duck-typing.
    Returns True if compatible, False otherwise.
    """
    import os

    start_time = time.time()
    print(f"validate_guideline_compatibility: Validating guideline for finding '{finding}'")

    # Build validation prompt — handle both GuidelineEntry and RichGuidelineEntry field names
    overview = (
        getattr(guideline_entry, 'clinical_summary', None)
        or getattr(guideline_entry, 'diagnostic_overview', None)
        or ""
    )
    guideline_summary = f"Overview: {overview[:300]}\n"

    # classification_systems (GuidelineEntry) or classifications (RichGuidelineEntry)
    classifications = (
        getattr(guideline_entry, 'classifications', None)
        or getattr(guideline_entry, 'classification_systems', None)
        or []
    )
    if classifications:
        names = [
            getattr(cs, 'system', None) or getattr(cs, 'name', '') or ''
            for cs in classifications
        ]
        guideline_summary += f"Classification Systems: {', '.join(n for n in names if n)}\n"

    # differential_diagnoses (GuidelineEntry) or differentials (RichGuidelineEntry)
    differentials = (
        getattr(guideline_entry, 'differentials', None)
        or getattr(guideline_entry, 'differential_diagnoses', None)
        or []
    )
    if differentials:
        names = [getattr(dd, 'diagnosis', '') for dd in differentials]
        guideline_summary += f"Differential Diagnoses: {', '.join(n for n in names if n)}\n"
    
    validation_prompt = (
        f"Finding: {finding}\n\n"
        f"Guideline Summary:\n{guideline_summary}\n\n"
        "Compatible = Guideline is clinically relevant to the finding:\n"
        "- Same or related anatomy\n"
        "- Same or related pathology\n"
        "- Relevant imaging findings or protocols\n"
        "Include guidelines that substantially match the clinical entity.\n\n"
        "Incompatible = Clearly unrelated:\n"
        "- Different anatomy\n"
        "- Different pathology\n"
        "- Unrelated imaging findings\n\n"
        "Return 'YES' if compatible, 'NO' if incompatible."
    )
    
    system_prompt = (
        "Medical expert validating clinical relevance. Include guidelines that are substantially related to the finding. "
        "Only exclude clearly unrelated guidelines.\n\n"
        "CRITICAL - OUTPUT FORMAT:\n"
        "• Return a DIRECT STRING VALUE: 'YES' or 'NO', not wrapped in an object\n"
        "• Example: 'YES' NOT {'text': 'YES'}\n"
        "• Return ONLY 'YES' or 'NO' as a plain string value"
    )
    
    # Get primary model and provider
    primary_model = MODEL_CONFIG["GUIDELINE_VALIDATOR"]
    primary_provider = _get_model_provider(primary_model)
    primary_api_key = _get_api_key_for_provider(primary_provider)
    
    # Try primary model first with explicit retry logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Build model settings with conditional reasoning_effort for Cerebras
            model_settings = {
                "temperature": 0.2,  # Slightly higher temperature for less strict validation
            }
            if primary_model == "gpt-oss-120b":
                model_settings["max_completion_tokens"] = 50  # Small token limit for simple YES/NO
                model_settings["reasoning_effort"] = "medium"  # Medium reasoning for binary validation decisions
                print(f"validate_guideline_compatibility: Using Cerebras reasoning_effort=medium, max_completion_tokens=50, temperature=0.2 for {primary_model}")
            else:
                model_settings["max_tokens"] = 10
            
            result = await _run_agent_with_model(
                model_name=primary_model,
                output_type=str,
                system_prompt=system_prompt,
                user_prompt=validation_prompt,
                api_key=primary_api_key,
                use_thinking=False,  # Primary model doesn't use thinking (Cerebras uses reasoning_effort instead)
                model_settings=model_settings
            )
            
            response = str(result.output).strip().upper()
            is_compatible = response.startswith('YES')
            
            elapsed = time.time() - start_time
            status = "✅ COMPATIBLE" if is_compatible else "❌ INCOMPATIBLE"
            print(f"validate_guideline_compatibility: {status} in {elapsed:.2f}s")
            if not is_compatible:
                print(f"  └─ Guideline does not match finding's clinical entity (anatomy/pathology/imaging mismatch)")
            
            return is_compatible
            
        except Exception as e:
            if attempt < max_retries - 1:
                # Retry with exponential backoff
                delay = 2.0 * (2 ** attempt)
                print(f"⚠️ Primary model attempt {attempt + 1}/{max_retries} failed ({type(e).__name__}) - retrying in {delay:.1f}s...")
                print(f"  Error: {str(e)[:200]}")
                await asyncio.sleep(delay)
            else:
                # All retries exhausted
                fallback_model = MODEL_CONFIG['GUIDELINE_VALIDATOR_FALLBACK']
                print(f"⚠️ Primary model failed after {max_retries} attempts ({type(e).__name__}) - falling back to {fallback_model}")
                print(f"  Final error: {str(e)[:200]}")
    
    # If we get here, all retries failed - fallback to fallback model
    try:
        fallback_model = MODEL_CONFIG["GUIDELINE_VALIDATOR_FALLBACK"]
        fallback_provider = _get_model_provider(fallback_model)
        fallback_api_key = _get_api_key_for_provider(fallback_provider)
        
        result = await _run_agent_with_model(
            model_name=fallback_model,
            output_type=str,
            system_prompt=system_prompt,
            user_prompt=validation_prompt,
            api_key=fallback_api_key,
            use_thinking=(fallback_provider == 'groq'),  # Enable thinking for Groq fallback
            model_settings={"temperature": 0.1, "max_tokens": 10}
        )
        
        response = str(result.output).strip().upper()
        is_compatible = response.startswith('YES')
        
        elapsed = time.time() - start_time
        status = "✅ COMPATIBLE" if is_compatible else "❌ INCOMPATIBLE"
        print(f"validate_guideline_compatibility: {status} in {elapsed:.2f}s (fallback)")
        if not is_compatible:
            print(f"  └─ Guideline does not match finding's clinical entity (anatomy/pathology/imaging mismatch)")
        
        return is_compatible
        
    except Exception as fallback_error:
        # Both models failed - return True (fail-safe - better to include guideline than reject it)
        print(f"⚠️  Guideline validation error (both models failed): {fallback_error}")
        print(f"  └─ Returning True (fail-safe - including guideline)")
        import traceback
        print(traceback.format_exc())
        return True


_BRANCH_LABELS = {
    "pathway_followup": "UK PATHWAY & FOLLOW-UP EVIDENCE",
    "classification_measurement": "CLASSIFICATION & MEASUREMENT EVIDENCE",
    "imaging_differential": "IMAGING FEATURES & DIFFERENTIALS EVIDENCE",
}
_BRANCH_INSTRUCTIONS = {
    "pathway_followup": (
        "use for: urgency_tier, uk_authority, guideline_refs, "
        "follow_up_actions (with guideline_source per action traceable to a specific item here)"
    ),
    "classification_measurement": (
        "use for: classifications (system, authority, grade, criteria, management per grade), thresholds"
    ),
    "imaging_differential": (
        "use for: differentials (key_features, excluders, likelihood), imaging_flags, clinical_summary"
    ),
}


def _build_branch_evidence_blocks(
    finding_idx: int,
    prefetched_knowledge,           # PrefetchOutput
    chars_per_item: int = 2500,
    max_items_per_branch: int = 3,
) -> Dict[str, List[dict]]:
    """
    Build branch-labelled evidence blocks from the prefetch knowledge base.
    Preserves branch identity so the synthesis prompt can direct the LLM to
    extract the right fields from the right evidence section.
    Uses 2500 chars per item (no double-truncation from the old 500→280 pipeline).
    """
    branch_map: Dict[str, List[dict]] = {}
    for branch, items in prefetched_knowledge.knowledge_base.items():
        relevant = [
            item for item in items
            if not item.finding_indices or finding_idx in item.finding_indices
        ]
        branch_items = []
        for item in relevant[:max_items_per_branch]:
            branch_items.append({
                "label": _BRANCH_LABELS.get(branch, branch),
                "instruction": _BRANCH_INSTRUCTIONS.get(branch, ""),
                "url": item.url,
                "title": item.title or item.domain,
                "content": (item.content or "")[:chars_per_item],
                "domain": item.domain,
            })
        if branch_items:
            branch_map[branch] = branch_items
    return branch_map


def _format_branch_evidence(branch_blocks: Dict[str, List[dict]]) -> str:
    """
    Format branch-aware evidence blocks into a labelled string for the synthesis prompt.
    Each section has a header identifying what it should be used for.
    """
    if not branch_blocks:
        return "No supporting evidence."
    sections = []
    for branch, items in branch_blocks.items():
        if not items:
            continue
        label = items[0]["label"]
        instruction = items[0]["instruction"]
        header = f"=== {label} ===\n({instruction})"
        item_strs = []
        prefix = branch[0].upper()
        for i, item in enumerate(items, 1):
            item_strs.append(
                f"[{prefix}{i}] {item['title']}\n"
                f"Source: {item['url']}\n"
                f"{item['content']}"
            )
        sections.append(header + "\n\n" + "\n\n---\n\n".join(item_strs))
    return "\n\n".join(sections)


def _build_raw_evidence_from_prefetch(
    finding_idx: int,
    prefetched_knowledge,  # PrefetchOutput
) -> List[dict]:
    """
    Legacy shim — returns flat evidence list for non-synthesis callers
    (e.g. chat grounding, raw_evidence field). Not used for synthesis prompt.
    """
    items = []
    for branch_items in prefetched_knowledge.knowledge_base.values():
        for item in branch_items:
            fi = item.finding_indices
            if not fi or finding_idx in fi:
                content = item.content or ""
                items.append({
                    "url": item.url,
                    "title": item.title or item.domain,
                    "snippet": content[:500].replace("\n", " ").strip(),
                    "content": content,
                    "query": item.extract_hint or f"guideline {item.branch}",
                    "score": 1.0,
                    "domain": item.domain,
                })
    return items


# DEPRECATED — replaced by S4 synthesis in guideline_prefetch.run_synthesis
async def search_guidelines_for_findings(
    consolidated_result: ConsolidationResult,
    report_content: str,
    api_key: str,
    findings_input: str = "",
    prefetched_knowledge=None,  # Optional[PrefetchOutput]
) -> List[dict]:
    """
    Search Perplexity and synthesize guidelines for consolidated findings.
    
    CACHING: Uses original FINDINGS input hash as base for cache keys.
    Clinical history doesn't affect guideline generation, so cache based on FINDINGS alone.
    This ensures same findings input gets cached results even if:
    - Settings change (writing style, etc.)
    - Report content varies slightly
    - Finding extraction normalizes differently between runs
    """
    if not consolidated_result.findings:
        return []

    start_time = time.time()
    print(f"search_guidelines_for_findings: Processing {len(consolidated_result.findings)} consolidated findings")
    
    # Cache keys are now based on extracted finding text (not user input)
    # This enables cache reuse across users with the same findings
    # Cache key generation happens per-finding in the loop below

    import os

    # Get primary model and provider
    primary_model = MODEL_CONFIG["GUIDELINE_SEARCH"]
    primary_provider = _get_model_provider(primary_model)
    primary_api_key = _get_api_key_for_provider(primary_provider)

    # Bespoke branch-aware synthesis system prompt (v2)
    guidelines_system_prompt = (
        "You are a senior UK consultant radiologist synthesising clinical guideline evidence for NHS colleagues.\n"
        "Use British English spelling and terminology throughout.\n\n"

        "SCOPE RULES:\n"
        "• ADULT radiology only (age 16+) — exclude all paediatric classification systems (SFU, UTD, etc.)\n"
        "• Guideline must match ALL THREE of: (1) anatomy, (2) pathology, (3) imaging finding. ANY mismatch = do not include.\n"
        "• UK guidelines first (NICE, RCR, BIR, British specialty societies); international sources supplement only.\n"
        "• Use only the provided evidence — do not fabricate. If a section has no relevant evidence, return [].\n\n"

        "EVIDENCE SECTIONS:\n"
        "The evidence is divided into three labelled sections. Extract specific fields from each:\n"
        "  SECTION A (UK Pathway & Follow-up) → use for: urgency_tier, uk_authority, guideline_refs, follow_up_actions\n"
        "    - Every follow_up_action.guideline_source MUST be traceable to a specific [A*] item\n"
        "    - urgency_tier must reflect the most urgent follow_up_action\n"
        "  SECTION B (Classification & Measurement) → use for: classifications (with management per grade), thresholds\n"
        "  SECTION C (Imaging Features & Differentials) → use for: differentials, imaging_flags, clinical_summary\n\n"

        "OUTPUT FIELD RULES:\n"
        "• urgency_tier: one of 'urgent' | 'soon' | 'routine' | 'watch' | 'none'\n"
        "• clinical_summary: 2 sentences max — what the finding represents and its primary clinical significance\n"
        "• uk_authority: primary UK body only — 'NICE', 'BSG', 'RCR', 'BTS', 'BAUS', 'RCP', etc.\n"
        "• guideline_refs: short attribution strings e.g. ['NICE CG188', 'BSG 2020'] — not full URLs\n"
        "• follow_up_actions: ordered most-urgent first; each needs modality, timing, indication, urgency, guideline_source\n"
        "• classifications: 0–2 systems; each needs system, authority, grade, criteria, management\n"
        "• thresholds: actionable decision points only (e.g. 'CBD > 8mm → MRCP') — not normal ranges\n"
        "• differentials: 2–4 items; each needs diagnosis, key_features, excluders, likelihood\n"
        "• imaging_flags: flat list of key imaging observations as short strings\n"
        "• All list fields must be arrays — return [] not null when empty\n"
        "• Do not wrap string fields in objects\n\n"

        "SOURCE PRIORITY:\n"
        "1. UK professional societies (NICE, RCR, BSG, BTS, BAUS, RCOG, RCP, BIR)\n"
        "2. International professional societies (RSNA, ACR, Fleischner Society, etc.)\n"
        "3. Peer-reviewed / academic sources (Radiopaedia, PubMed)"
    )

    guidelines_results: List[dict] = []
    total_sources = 0
    # Track which models were used
    query_models_used = set()
    synthesis_models_used = set()

    async def _process_finding(idx: int, consolidated_finding) -> Optional[tuple]:
        """Process a single finding: query generation, search, filtering, synthesis, validation.
        Returns (result_dict, query_model, synthesis_model, sources_count) or None if skipped."""
        # Each coroutine gets its own Perplexity client (avoids thread-safety concerns)
        perplexity_client = Perplexity()
        
        print(f"  └─ Processing consolidated finding {idx}: {consolidated_finding.finding}")

        # Generate cache key prefix using extracted finding text hash + finding index
        # This enables cache reuse across users with the same findings (much higher hit rate)
        # Normalize finding text for consistent hashing
        finding_text_normalized = consolidated_finding.finding.strip().lower()
        finding_text_hash = hashlib.sha256(finding_text_normalized.encode('utf-8')).hexdigest()
        finding_cache_prefix = f"{finding_text_hash}:finding_{idx}"
        print(f"      [CACHE DEBUG] Finding text hash: {finding_text_hash[:16]}... (finding: '{consolidated_finding.finding[:50]}...')")

        # Initialise cache early — used by both prefetch and Perplexity paths
        cache = get_cache()

        # ── Prefetch short-circuit: use pre-fetched KB instead of Perplexity ──
        _pf_knowledge = prefetched_knowledge  # local mutable copy
        _branch_blocks: Dict[str, List[dict]] = {}  # branch-aware evidence blocks
        if _pf_knowledge is not None:
            _branch_blocks = _build_branch_evidence_blocks(idx - 1, _pf_knowledge)
            pf_items = _build_raw_evidence_from_prefetch(idx - 1, _pf_knowledge)  # for raw_evidence/sources
            if _branch_blocks:
                total_pf_items = sum(len(v) for v in _branch_blocks.values())
                print(f"      [PREFETCH] Using {total_pf_items} pre-fetched evidence items across {len(_branch_blocks)} branches for finding {idx}")
                search_results = pf_items
                queries = [item.get("query", "") for item in pf_items[:3]]
                query_model = "prefetch"
                fallback_attempt = 0
                # Skip Perplexity; fall through to synthesis below
            else:
                print(f"      [PREFETCH] No prefetch items for finding {idx} — falling back to Perplexity")
                _pf_knowledge = None  # Force Perplexity fallback for this finding

        if _pf_knowledge is None:
            # Generate 2-3 focused search queries using AI
            # Cache based on extracted finding text hash (enables cross-user cache reuse)
            query_cache_key = f"query_gen:{finding_cache_prefix}"
            cached_queries_result = cache.get(query_cache_key)
            
            if cached_queries_result is not None:
                print(f"      [CACHE HIT] Using cached queries")
                queries, query_model = cached_queries_result
            else:
                print(f"      [CACHE MISS] Generating queries")
                queries, query_model = await generate_radiology_search_queries(consolidated_finding.finding, api_key)
                # Cache the queries with report-content-based key
                cache.set(query_cache_key, (queries, query_model))
            
            print(f"      Generated {len(queries)} queries")
            for q_idx, q in enumerate(queries, 1):
                print(f"        Query {q_idx}: {q}")

            # Check cache for Perplexity search results (cache based on report content + queries)
            queries_hash = generate_query_hash(queries)
            search_cache_key = f"perplexity_search:{finding_cache_prefix}:{queries_hash}"
            print(f"      [CACHE DEBUG] Perplexity search cache key: {search_cache_key[:50]}...")
            cached_search_results = cache.get(search_cache_key)
            
            search_results = None
            fallback_attempt = 0
            
            if cached_search_results is not None:
                print(f"      [CACHE HIT] Using cached Perplexity search results")
                search_results = cached_search_results
            else:
                print(f"      [CACHE MISS] Executing Perplexity search")
            
            # Try search with fallback strategy: restricted domains -> no domain filter -> no language filter
            
            # Attempt 1: Restricted domain filter (preferred - highest quality)
            try:
                search_response = await asyncio.to_thread(
                    lambda: perplexity_client.search.create(
                        query=queries,  # List of 3-5 queries
                        max_results=5,   # 5 per query = 15-25 total results
                        max_tokens_per_page=1024,
                        search_language_filter=["en"],
                        search_domain_filter=COMPREHENSIVE_RADIOLOGY_DOMAINS,
                    )
                )
                search_results = normalize_perplexity_results(search_response, queries)
                fallback_attempt = 1
                if search_results:
                    print(f"      ✅ Found {len(search_results)} results with restricted domain filter")
                    # Cache successful search results
                    cache.set(search_cache_key, search_results)
            except Exception as search_error:
                print(f"⚠️  Perplexity search error (attempt 1 - restricted domains): {search_error}")
        
            # Attempt 2: No domain filter (broader search, still English only)
            if not search_results:
                try:
                    print(f"      🔄 Retrying without domain filter...")
                    search_response = await asyncio.to_thread(
                        lambda: perplexity_client.search.create(
                            query=queries,
                            max_results=5,
                            max_tokens_per_page=1024,
                            search_language_filter=["en"],
                            # No search_domain_filter - broader search
                        )
                    )
                    search_results = normalize_perplexity_results(search_response, queries)
                    fallback_attempt = 2
                    if search_results:
                        print(f"      ✅ Found {len(search_results)} results without domain filter")
                        # Cache successful search results
                        cache.set(search_cache_key, search_results)
                except Exception as search_error:
                    print(f"⚠️  Perplexity search error (attempt 2 - no domain filter): {search_error}")
            
            # Attempt 3: No language filter (broadest search)
            if not search_results:
                try:
                    print(f"      🔄 Retrying without language filter...")
                    search_response = await asyncio.to_thread(
                        lambda: perplexity_client.search.create(
                            query=queries,
                            max_results=5,
                            max_tokens_per_page=1024,
                            # No filters - broadest possible search
                        )
                    )
                    search_results = normalize_perplexity_results(search_response, queries)
                    fallback_attempt = 3
                    if search_results:
                        print(f"      ✅ Found {len(search_results)} results without filters")
                        # Cache successful search results
                        cache.set(search_cache_key, search_results)
                except Exception as search_error:
                    print(f"⚠️  Perplexity search error (attempt 3 - no filters): {search_error}")
                
                # Cache empty results too (to avoid retrying on cache miss)
                if search_results is None:
                    cache.set(search_cache_key, [])
        
        # Final check - if still no results, skip this finding
        if not search_results:
            print(f"⚠️  No search results for finding {idx} after {fallback_attempt} attempt(s)")
            return None
        
        # Log which fallback level was used
        if fallback_attempt > 1:
            print(f"      ⚠️  Used fallback level {fallback_attempt} (less restrictive filtering)")

        # Check cache for compatibility filtering (cache based on report content + search_results)
        search_results_hash = generate_search_results_hash(search_results)
        filter_cache_key = f"compat_filter:v2:{finding_cache_prefix}:{search_results_hash}"
        print(f"      [CACHE DEBUG] Compatibility filter cache key: {filter_cache_key[:50]}...")
        cached_filtered_results = cache.get(filter_cache_key)
        
        if cached_filtered_results is not None:
            print(f"      [CACHE HIT] Using cached compatibility filter results")
            filtered_search_results = cached_filtered_results
        else:
            print(f"      [CACHE MISS] Executing compatibility filtering")
            # Filter incompatible search results before synthesis
            filtered_search_results = await filter_compatible_search_results(
                search_results,
                consolidated_finding.finding,
                api_key
            )
            # Cache filtered results
            if filtered_search_results:
                cache.set(filter_cache_key, filtered_search_results)
        
        search_results = filtered_search_results
        if not search_results:
            print(f"⚠️  No compatible search results for finding {idx} after filtering")
            return None

        print(f"      Retrieved {len(search_results)} compatible search results")

        # Build branch-aware evidence block for synthesis prompt
        # If prefetch is available use rich branch blocks; otherwise fall back to flat Perplexity items
        if _branch_blocks:
            evidence_block = _format_branch_evidence(_branch_blocks)
        else:
            # Perplexity fallback — build a flat evidence block from search results
            context_lines = []
            for rank, item in enumerate(search_results[:12], start=1):
                title = (item.get("title") or "").strip()
                snippet = (item.get("snippet") or "").strip()[:1500]
                url = (item.get("url") or "").strip()
                query = (item.get("query") or "").strip()
                context_lines.append(f"[{rank}] Query: {query}\nTitle: {title}\nSummary: {snippet}\nURL: {url}\n")
            evidence_block = "\n".join(context_lines) if context_lines else "No supporting evidence."

        # Check cache for guideline synthesis (v2 prefix — incompatible with old GuidelineEntry dicts)
        synthesis_cache_key = f"guideline_synth_v3:{finding_cache_prefix}:{search_results_hash}"
        print(f"      [CACHE DEBUG] Checking guideline synthesis cache with key: {synthesis_cache_key[:80]}...")
        cached_synthesis = cache.get(synthesis_cache_key)
        
        synthesis_model = None
        guideline_entry_raw = None
        
        if cached_synthesis is not None:
            print(f"      [CACHE HIT] Using cached guideline synthesis")
            print(f"      [CACHE DEBUG] Cache key: {synthesis_cache_key[:80]}...")
            if isinstance(cached_synthesis, dict):
                guideline_entry_raw = RichGuidelineEntry(**cached_synthesis)
            else:
                guideline_entry_raw = cached_synthesis
            synthesis_model = "cached"
        else:
            print(f"      [CACHE MISS] Executing guideline synthesis")
            print(f"      [CACHE DEBUG] Cache key: {synthesis_cache_key[:80]}...")

            # Build applicable guidelines context line from prefetch S1 output
            applicable_guidelines_context = ""
            if prefetched_knowledge and prefetched_knowledge.applicable_guidelines:
                guideline_names = [
                    g.get("system", "") for g in prefetched_knowledge.applicable_guidelines
                    if g.get("system")
                ]
                if guideline_names:
                    applicable_guidelines_context = f"APPLICABLE GUIDELINES CONTEXT: {', '.join(guideline_names)}\n\n"

            prompt = (
                f"CLINICAL FINDING: {consolidated_finding.finding}\n\n"
                f"{applicable_guidelines_context}"
                f"{evidence_block}\n\n"
                "Return a RichGuidelineEntry JSON. "
                "Set urgency_tier from the most urgent follow_up_action. "
                "If a section has no useful evidence for its target fields, return [] — do not fabricate."
            )

            def _synthesis_model_settings(model: str, provider: str) -> dict:
                """Build correct model settings per provider/model for synthesis."""
                settings: dict = {"temperature": 0.2}
                if model == "zai-glm-4.7":
                    # GLM uses extra_body reasoning toggle, NOT reasoning_effort
                    settings["max_completion_tokens"] = 8000
                    settings["extra_body"] = {"disable_reasoning": False}  # reasoning ON for complex schema
                    print(f"      └─ GLM mode: REASONING ON, max_completion_tokens=8000 for {model}")
                elif provider == "cerebras":
                    # gpt-oss-120b and other Cerebras models use reasoning_effort
                    settings["max_completion_tokens"] = 6000
                    settings["reasoning_effort"] = "medium"
                    print(f"      └─ Using Cerebras reasoning_effort=medium, max_completion_tokens=6000 for {model}")
                else:
                    settings["max_tokens"] = 4000
                return settings

            try:
                @with_retry(max_retries=3, base_delay=2.0)
                async def _try_synthesis():
                    model_settings = _synthesis_model_settings(primary_model, primary_provider)
                    result = await _run_agent_with_model(
                        model_name=primary_model,
                        output_type=RichGuidelineEntry,
                        system_prompt=guidelines_system_prompt,
                        user_prompt=prompt,
                        api_key=primary_api_key,
                        use_thinking=(primary_provider == 'groq'),
                        model_settings=model_settings
                    )
                    return result

                result = await _try_synthesis()
                synthesis_model = primary_model
                guideline_entry_raw = result.output

                guideline_dict = guideline_entry_raw.model_dump() if hasattr(guideline_entry_raw, 'model_dump') else guideline_entry_raw.dict()
                print(f"      [CACHE DEBUG] Storing guideline with key: {synthesis_cache_key[:80]}...")
                cache.set(synthesis_cache_key, guideline_dict)

            except Exception as synthesis_error:
                print(f"⚠️ Primary model ({primary_model}) error for finding {idx}:")
                print(f"  └─ Error type: {type(synthesis_error).__name__}")
                print(f"  └─ Error message: {str(synthesis_error)}")
                if hasattr(synthesis_error, 'status_code'):
                    print(f"  └─ Status code: {synthesis_error.status_code}")
                if hasattr(synthesis_error, 'body'):
                    print(f"  └─ Error body: {synthesis_error.body}")

                fallback_model = MODEL_CONFIG["GUIDELINE_SEARCH_FALLBACK"]
                fallback_provider = _get_model_provider(fallback_model)
                fallback_api_key = _get_api_key_for_provider(fallback_provider)

                if _is_parsing_error(synthesis_error):
                    print(f"⚠️ Primary model parsing error for finding {idx} - falling back to {fallback_model}")
                else:
                    print(f"⚠️ Primary model failed after retries for finding {idx} - falling back to {fallback_model}")

                try:
                    fallback_model_settings = _synthesis_model_settings(fallback_model, fallback_provider)
                    use_thinking_fallback = (fallback_provider == 'groq' and 'qwen' in fallback_model.lower())

                    result = await _run_agent_with_model(
                        model_name=fallback_model,
                        output_type=RichGuidelineEntry,
                        system_prompt=guidelines_system_prompt,
                        user_prompt=prompt,
                        api_key=fallback_api_key,
                        use_thinking=use_thinking_fallback,
                        model_settings=fallback_model_settings
                    )

                    synthesis_model = fallback_model
                    guideline_entry_raw = result.output
                    print(f"      ✅ Guideline synthesis completed with {synthesis_model} (fallback)")

                    guideline_dict = guideline_entry_raw.model_dump() if hasattr(guideline_entry_raw, 'model_dump') else guideline_entry_raw.dict()
                    print(f"      [CACHE DEBUG] Storing guideline (fallback) with key: {synthesis_cache_key[:80]}...")
                    cache.set(synthesis_cache_key, guideline_dict)

                except Exception as fallback_error:
                    print(f"❌ Both primary and fallback models failed for finding {idx}: {fallback_error}")
                    return None

        guideline_entry: RichGuidelineEntry = guideline_entry_raw
        print(f"      Generated guideline: {guideline_entry.clinical_summary[:160]}...")

        # Check cache for guideline validation (cache based on report content + guideline)
        import json
        guideline_dict = guideline_entry.model_dump() if hasattr(guideline_entry, 'model_dump') else guideline_entry.dict()
        guideline_str = json.dumps(guideline_dict, sort_keys=True, default=str)
        guideline_hash = hashlib.sha256(guideline_str.encode('utf-8')).hexdigest()
        validation_cache_key = f"guideline_validation:{finding_cache_prefix}:{guideline_hash}"
        print(f"      [CACHE DEBUG] Guideline validation cache key: {validation_cache_key[:50]}...")
        cached_validation = cache.get(validation_cache_key)
        
        if cached_validation is not None:
            print(f"      [CACHE HIT] Using cached validation result")
            is_compatible = cached_validation
        else:
            print(f"      [CACHE MISS] Executing guideline validation")
            # Validate guideline compatibility with finding
            is_compatible = await validate_guideline_compatibility(
                guideline_entry,
                consolidated_finding.finding,
                api_key
            )
            # Cache validation result
            cache.set(validation_cache_key, is_compatible)
        
        if not is_compatible:
            print(f"⚠️  Synthesized guideline incompatible with finding {idx}, skipping...")
            return None

        guideline_entry = guideline_entry.model_copy(
            update={"finding_number": idx, "finding": consolidated_finding.finding}
        )

        # Build sources and raw_evidence for chat citation grounding
        sources = []
        raw_evidence: List[Dict[str, Any]] = []
        seen_evidence_urls: set[str] = set()
        for item in search_results[:10]:
            url = item.get("url", "")
            dedupe_key = normalize_evidence_url_for_dedupe(url)
            if not dedupe_key or dedupe_key in seen_evidence_urls:
                continue
            seen_evidence_urls.add(dedupe_key)
            title = (item.get("title") or "").strip()
            snippet_raw = (item.get("text") or item.get("content") or item.get("snippet") or "").strip()
            if len(snippet_raw) > 600:
                snippet_raw = snippet_raw[:597].rstrip() + "..."
            sources.append({
                "url": url,
                "title": title,
                "snippet": "",
                "domain": item.get("domain", ""),
                "query": item.get("query", ""),
            })
            raw_evidence.append({
                "url": url,
                "title": sanitize_chat_source_text(title, max_display=None) or title,
                "snippet": sanitize_chat_source_text(snippet_raw, 600),
                "domain": item.get("domain", "") or extract_domain(url),
                "query": item.get("query", ""),
            })

        # Debug logging for v2 structured fields
        print(f"📊 DEBUG (v2) - Guideline for '{consolidated_finding.finding}':")
        print(f"  urgency_tier: {guideline_entry.urgency_tier}")
        print(f"  uk_authority: {guideline_entry.uk_authority}")
        print(f"  classifications: {len(guideline_entry.classifications)} items")
        print(f"  follow_up_actions: {len(guideline_entry.follow_up_actions)} items")
        print(f"  thresholds: {len(guideline_entry.thresholds)} items")
        print(f"  differentials: {len(guideline_entry.differentials)} items")
        print(f"  imaging_flags: {len(guideline_entry.imaging_flags)} items")

        result_dict = {
            # Top-level rich fields
            "finding_number": guideline_entry.finding_number,
            "finding": guideline_entry.finding,
            "urgency_tier": guideline_entry.urgency_tier,
            "clinical_summary": guideline_entry.clinical_summary,
            "uk_authority": guideline_entry.uk_authority,
            "guideline_refs": guideline_entry.guideline_refs,
            "follow_up_actions": [a.model_dump() for a in guideline_entry.follow_up_actions],
            "classifications": [c.model_dump() for c in guideline_entry.classifications],
            "thresholds": [t.model_dump() for t in guideline_entry.thresholds],
            "differentials": [d.model_dump() for d in guideline_entry.differentials],
            "imaging_flags": guideline_entry.imaging_flags,
            "sources": sources[:5],
            # Raw evidence for chat grounding
            "raw_evidence": raw_evidence,
        }
        return (result_dict, query_model, synthesis_model, len(search_results))

    # Process all findings concurrently
    tasks = [
        _process_finding(idx, finding)
        for idx, finding in enumerate(consolidated_result.findings, start=1)
    ]
    finding_results = await asyncio.gather(*tasks)

    # Aggregate results from all findings
    for result in finding_results:
        if result is not None:
            result_dict, query_model, synthesis_model, sources_count = result
            guidelines_results.append(result_dict)
            query_models_used.add(query_model)
            synthesis_models_used.add(synthesis_model)
            total_sources += sources_count

    elapsed = time.time() - start_time
    # Build model summary string
    query_models_str = ", ".join(sorted(query_models_used)) if query_models_used else "none"
    synthesis_models_str = ", ".join(sorted(synthesis_models_used)) if synthesis_models_used else "none"
    models_summary = f"Query: {query_models_str} | Synthesis: {synthesis_models_str}"
    print(f"search_guidelines_for_findings: Completed with {len(guidelines_results)} guidelines from {total_sources} sources in {elapsed:.2f}s ({models_summary})")
    return guidelines_results


# ============================================================================
# Comparison Analysis Functions
# ============================================================================

def format_date_uk(date_str: str) -> str:
    """Convert ISO date (YYYY-MM-DD) to UK format (DD/MM/YYYY)"""
    if not date_str:
        return 'unknown date'
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(date_str)
        return dt.strftime('%d/%m/%Y')
    except:
        return date_str  # Return as-is if parsing fails

async def analyze_interval_changes(
    current_report: str,
    prior_reports: List[dict],
    guidelines_data: Optional[List[dict]] = None
) -> ComparisonAnalysis:
    """
    Perform two-stage comparison analysis with guideline integration.
    
    Stage 1: Extract findings, classify changes, generate summary and key changes
    Stage 2: Generate revised report with proper formatting preservation
    """
    import os
    import time
    
    start_time = time.time()
    
    sorted_priors = sorted(prior_reports, key=lambda x: x.get('date', '1900-01-01'), reverse=True)
    
    priors_text = "\n\n".join([
        f"PRIOR REPORT {i+1} (Date: {format_date_uk(p.get('date', ''))}"
        + (f", Scan Type: {p.get('scan_type')}" if p.get('scan_type') else "")
        + f"):\n{p['text']}"
        for i, p in enumerate(sorted_priors)
    ])
    
    guidelines_context = ""
    if guidelines_data:
        guidelines_context = "\n\nCLINICAL GUIDELINES CONTEXT:\n"
        for guideline in guidelines_data:
            is_s4 = any(k in guideline for k in ("follow_up_actions", "urgency_tier", "imaging_flags", "finding_short_label"))
            if is_s4:
                guidelines_context += "\n" + _extract_text_from_synthesis_card(guideline) + "\n"
                continue
            finding_name = guideline.get('finding', {}).get('finding', 'N/A')
            guidelines_context += f"\n{finding_name}:\n"
            if guideline.get('diagnostic_overview'):
                guidelines_context += f"{guideline['diagnostic_overview']}\n"
            if guideline.get('measurement_protocols'):
                guidelines_context += "\nMeasurement Standards:\n"
                for protocol in guideline['measurement_protocols']:
                    guidelines_context += f"- {protocol.get('parameter')}: {protocol.get('technique')}\n"
    
    # ============================================================================
    # STAGE 1: Analysis - Extract findings and classify changes
    # ============================================================================
    
    print(f"\n{'='*80}")
    print(f"🔬 STAGE 1: Comparison Analysis (Findings + Summary)")
    print(f"{'='*80}")
    
    stage1_user_prompt = f"""CURRENT REPORT:
{current_report}

{priors_text}
{guidelines_context}

TASK: Analyze interval changes between reports. Extract findings, classify their status, 
generate summary, and create structured change directives for Stage 2 integration. 
Use calculate_measurement_change tool for precise measurements.

Focus on analysis and structured data extraction - do NOT generate revised report text."""
    
    stage1_system_prompt = """You are an expert radiologist performing interval comparison analysis.

CRITICAL: You MUST use British English spelling and terminology throughout all output.
CRITICAL: Use UK date format (DD/MM/YYYY) for all dates.

TOOL AVAILABLE: calculate_measurement_change
Use this tool for precise measurement calculations between prior and current reports.

YOUR SINGULAR TASK: Analyze findings and classify changes. Do NOT generate any revised text.
This is a pure analysis task. Report generation will be handled separately in Stage 2.

METHODOLOGY:

1. CONTEXT INTEGRATION
   Use provided clinical guidelines to inform significance assessment
   Consider the clinical trajectory across multiple priors when available

2. FINDING CLASSIFICATION
   CRITICAL: Only classify actual findings (pathology, abnormalities, lesions, masses, etc.)
   Do NOT classify normal structures or organs that remain normal as "stable" findings
   
   For each actual finding, determine status:
   - CHANGED: Present in both, significantly changed
   - STABLE: Present in both, no significant change  
   - NEW: Only in current report
   - NOT_MENTIONED: In prior but not current (explain likely reason)
   
   OUTPUT STRUCTURE:
   - Single prior report: Populate prior_measurement, prior_description, prior_date. Leave prior_states empty and trend None.
   - Multiple prior reports: Populate prior_states (all priors where finding present, oldest first) and trend (progression analysis with measurements, dates, growth rates). Status compares to most recent prior. Optionally populate single prior fields with most recent values.
   - Always populate current_measurement and current_description when available.
   - Use calculate_measurement_change tool for precise calculations.

3. MEASUREMENT EXTRACTION
   Measurement Object Structure:
   {
     "value": "5.3",           # STRING (not number)
     "unit": "cm",
     "raw_text": "5.3 cm"     # REQUIRED
   }

4. CHANGE DIRECTIVES (Structured Instructions for Stage 2)
   For each significant finding that requires report integration, create a ChangeDirective with:
   
   {
     "finding_name": "Name of the finding (e.g., 'Left lower lobe nodule')",
     "location": "Anatomical location (e.g., 'Left lower lobe', 'Right parietal region')",
     "change_type": "Type of change: 'new', 'changed', 'resolved', or 'stable'",
     "integration_strategy": "HOW to integrate this into the report (e.g., 'Add new finding to Findings section after discussion of lung parenchyma', 'Update existing measurement in Findings', 'Add to Comparison section with prior date and scan type', 'Update Impression with progression assessment')",
     "measurement_data": {
       "prior": {"value": "X", "unit": "mm", "raw_text": "X mm"},
       "current": {"value": "Y", "unit": "mm", "raw_text": "Y mm"},
       "absolute_change": "+Z mm",
       "percentage_change": "+W%",
       "dates": {"prior": "DD/MM/YYYY", "current": "DD/MM/YYYY"}
     },  # Include only if measurements are relevant
     "clinical_significance": "Brief clinical interpretation (e.g., 'Interval growth concerning for malignancy', 'Stable appearance favours benign process', 'New acute finding requiring urgent attention')",
     "section_target": "Primary section to modify: 'Comparison', 'Findings', 'Impression', or 'Multiple'"
   }
   
   SELECTION CRITERIA FOR DIRECTIVES:
   - Include all NEW findings (change_type='new')
   - Include all CHANGED findings with significant interval change
   - Include RESOLVED findings if previously significant
   - Include STABLE findings only if they are major/critical (e.g., large aneurysm stable)
   - Generally exclude truly stable minor findings
   
   INTEGRATION STRATEGY GUIDANCE:
   - Be specific about WHERE in the report (which section, after which discussion)
   - Be clear about WHAT to do (add, update, modify)
   - Reference anatomical progression when relevant
   - For findings with TREND (multiple priors): Instruct Stage 2 to convey the clinical trajectory (direction, magnitude, pace) — the strategy should describe WHAT the prose must communicate, not HOW the dates should be formatted inline
   - For Comparison section directives: Specify to list ALL prior reports with dates and scan types
   
OUTPUT: ComparisonAnalysisStage1 with findings, summary, and change_directives (NO text generation)
- findings: List of FindingComparison objects, each with:
  * name (string): Finding name
  * location (string): Anatomic location
  * status (string): "changed", "stable", "new", or "not_mentioned"
  * prior_measurement, prior_description, prior_date (for single prior)
  * prior_states (list), trend (string) (for multiple priors)
  * current_measurement, current_description
  * assessment (string): Clinical analysis
- summary: String with high-level synthesis of changes and clinical trajectory
- change_directives: List of ChangeDirective objects with structured instructions for Stage 2

REASONING WORKFLOW (for high-reasoning models like GPT-OSS 120B):
1. Parse all reports systematically (current and all priors)
2. Extract and classify each finding with precise measurements
3. Use tools to calculate exact interval changes
4. Assess clinical significance using guidelines when available
5. Generate structured change directives (NOT text replacements)
6. Synthesize high-level summary of clinical trajectory
7. Output structured analysis"""
    
    # Get model and API key for Stage 1
    model_name = MODEL_CONFIG["COMPARISON_ANALYZER"]
    provider = _get_model_provider(model_name)
    api_key = _get_api_key_for_provider(provider)
    
    model_label = f"{model_name} (Stage 1: Analysis)"
    print(f"  └─ Model: {model_label}")
    print(f"  └─ Prior reports: {len(prior_reports)}")
    print(f"  └─ Guidelines available: {len(guidelines_data) if guidelines_data else 0}")
    print(f"  └─ Current report length: {len(current_report)} chars")
    
    # Create model instance for Stage 1
    pydantic_model = _create_pydantic_model(model_name, api_key, use_thinking=False)
    
    # Create Stage 1 agent with tool
    stage1_agent = Agent(
        pydantic_model,
        output_type=ComparisonAnalysisStage1,
        system_prompt=stage1_system_prompt
    )
    
    # Track tool calls for debugging
    tool_calls_log = []
    
    @stage1_agent.tool
    def calculate_measurement_change_tool(
        ctx: RunContext,
        prior_value: float,
        prior_unit: str,
        current_value: float,
        current_unit: str,
        prior_date: Optional[str] = None,
        current_date: Optional[str] = None
    ) -> dict:
        """Calculate precise interval change between measurements."""
        # Log tool call
        tool_call_info = {
            "tool": "calculate_measurement_change",
            "inputs": {
                "prior": f"{prior_value} {prior_unit}",
                "current": f"{current_value} {current_unit}",
                "prior_date": prior_date,
                "current_date": current_date
            }
        }
        
        input_data = MeasurementCalculationInput(
            prior_value=prior_value,
            prior_unit=prior_unit,
            prior_date=prior_date,
            current_value=current_value,
            current_unit=current_unit,
            current_date=current_date
        )
        result = calculate_measurement_change(input_data)
        
        output = {
            "absolute_change": result.absolute_change_str,
            "percentage_change": result.percentage_change_str,
            "growth_rate": result.growth_rate,
            "days_elapsed": result.days_elapsed,
            "error": result.calculation_error
        }
        
        # Log output
        tool_call_info["output"] = output
        tool_calls_log.append(tool_call_info)
        
        # Print concise tool call
        print(f"  🔧 Tool Call: {prior_value}{prior_unit} → {current_value}{current_unit}")
        if result.percentage_change_str:
            print(f"     └─ Change: {result.absolute_change_str} ({result.percentage_change_str})")
        if result.growth_rate:
            print(f"     └─ Growth rate: {result.growth_rate}")
        
        return output
    
    # Set up environment variable for API key
    env_var_map = {
        'groq': 'GROQ_API_KEY',
        'anthropic': 'ANTHROPIC_API_KEY',
        'cerebras': 'CEREBRAS_API_KEY',
        'fireworks': 'FIREWORKS_API_KEY',
    }
    env_var_name = env_var_map[provider]
    old_api_key = os.environ.get(env_var_name)
    os.environ[env_var_name] = api_key
    
    # Execute Stage 1 with retry logic
    max_retries = 3
    import asyncio
    stage1_result = None
    
    try:
        for attempt in range(max_retries):
            try:
                # Run Stage 1 agent with optimized settings for analysis
                model_settings = {"temperature": 0.2}  # Lower for precise analysis
                if provider == 'cerebras':
                    model_settings["reasoning_effort"] = "high"
                    model_settings["max_tokens"] = 5000  # Increased for comprehensive analysis
                    print(f"  └─ Using Cerebras reasoning_effort=high, max_tokens=5000, temperature=0.2")
                else:
                    model_settings["max_tokens"] = 5000
                    print(f"  └─ Using model settings: {model_settings}")
                
                result = await stage1_agent.run(stage1_user_prompt, model_settings=model_settings)
                stage1_result: ComparisonAnalysisStage1 = result.output
                
                stage1_elapsed = time.time() - start_time
                print(f"\n✅ Stage 1 completed in {stage1_elapsed:.2f}s")
                print(f"  └─ Findings analyzed: {len(stage1_result.findings)}")
                print(f"  └─ Changed: {len([f for f in stage1_result.findings if f.status == 'changed'])}")
                print(f"  └─ New: {len([f for f in stage1_result.findings if f.status == 'new'])}")
                print(f"  └─ Stable: {len([f for f in stage1_result.findings if f.status == 'stable'])}")
                print(f"  └─ Change directives created: {len(stage1_result.change_directives)}")
                
                # Debug: Print Stage 1 outputs
                print(f"\n{'─'*80}")
                print(f"📊 STAGE 1 OUTPUTS")
                print(f"{'─'*80}")
                
                # Summary
                print(f"\n📝 Summary:")
                print(f"  {stage1_result.summary[:200]}{'...' if len(stage1_result.summary) > 200 else ''}")
                
                # Findings breakdown
                print(f"\n🔍 Findings Breakdown:")
                for i, finding in enumerate(stage1_result.findings[:10], 1):  # Show first 10
                    status_emoji = {"changed": "📈", "new": "🆕", "stable": "✅", "not_mentioned": "❌"}.get(finding.status, "❓")
                    print(f"  {i}. {status_emoji} {finding.name} ({finding.status})")
                    if finding.location:
                        print(f"     Location: {finding.location}")
                    if finding.prior_measurement and finding.current_measurement:
                        print(f"     Measurement: {finding.prior_measurement.raw_text} → {finding.current_measurement.raw_text}")
                    elif finding.current_measurement:
                        print(f"     Measurement: {finding.current_measurement.raw_text}")
                    if finding.assessment:
                        assessment_preview = finding.assessment[:100] + "..." if len(finding.assessment) > 100 else finding.assessment
                        print(f"     Assessment: {assessment_preview}")
                if len(stage1_result.findings) > 10:
                    print(f"  ... and {len(stage1_result.findings) - 10} more findings")
                
                # Change directives
                print(f"\n📋 Change Directives ({len(stage1_result.change_directives)}):")
                for i, directive in enumerate(stage1_result.change_directives[:5], 1):  # Show first 5
                    print(f"  {i}. {directive.finding_name} ({directive.change_type})")
                    print(f"     Target: {directive.section_target}")
                    print(f"     Strategy: {directive.integration_strategy[:80]}{'...' if len(directive.integration_strategy) > 80 else ''}")
                if len(stage1_result.change_directives) > 5:
                    print(f"  ... and {len(stage1_result.change_directives) - 5} more directives")
                
                # Tool calls summary
                if tool_calls_log:
                    print(f"\n🔧 Tool Calls ({len(tool_calls_log)}):")
                    for i, tool_call in enumerate(tool_calls_log[:5], 1):
                        inputs = tool_call["inputs"]
                        print(f"  {i}. {tool_call['tool']}: {inputs.get('prior', 'N/A')} → {inputs.get('current', 'N/A')}")
                        if tool_call["output"].get("percentage_change"):
                            print(f"     Result: {tool_call['output']['absolute_change']} ({tool_call['output']['percentage_change']})")
                    if len(tool_calls_log) > 5:
                        print(f"  ... and {len(tool_calls_log) - 5} more tool calls")
                
                print(f"{'─'*80}\n")
                break  # Success
                
            except Exception as e:
                print(f"\n⚠️ Stage 1 attempt {attempt + 1}/{max_retries} failed: {type(e).__name__}: {str(e)[:200]}")
                
                if attempt < max_retries - 1:
                    delay = 2.0 * (2 ** attempt)
                    print(f"⚠️ Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                else:
                    print(f"❌ Stage 1 failed after {max_retries} attempts")
                    raise Exception(f"Stage 1 (Analysis) failed after {max_retries} retries: {str(e)}")
        
        if not stage1_result:
            raise Exception("Stage 1 (Analysis) did not produce a result")
        
        # ============================================================================
        # STAGE 2: Report Generation - Generate revised report with formatting preservation
        # ============================================================================
        
        print(f"\n{'='*80}")
        print(f"📝 STAGE 2: Revised Report Generation")
        print(f"{'='*80}")
        
        # Build comprehensive context for Stage 2 - Pass ALL findings and directives
        import json
        
        # Pass ALL findings with complete data (not truncated)
        findings_json = json.dumps([
            {
                "name": f.name,
                "location": f.location,
                "status": f.status,
                "prior_measurement": f.prior_measurement.dict() if f.prior_measurement else None,
                "current_measurement": f.current_measurement.dict() if f.current_measurement else None,
                "assessment": f.assessment,
                "trend": f.trend if hasattr(f, 'trend') and f.trend else None
            }
            for f in stage1_result.findings
        ], indent=2)
        
        # Build change directives context for Stage 2 (structured instructions)
        directives_context = "\n\n".join([
            f"DIRECTIVE {i+1}: {d.finding_name}\n"
            f"  Location: {d.location}\n"
            f"  Change Type: {d.change_type}\n"
            f"  Integration Strategy: {d.integration_strategy}\n"
            f"  Clinical Significance: {d.clinical_significance}\n"
            f"  Target Section: {d.section_target}\n"
            f"  Measurement Data: {json.dumps(d.measurement_data, indent=4) if d.measurement_data else 'N/A'}"
            for i, d in enumerate(stage1_result.change_directives)
        ])
        
        # Build scan types context for Stage 2 - Pass ALL priors, not just most recent 2
        scan_types_context = "\n".join([
            f"- {format_date_uk(p.get('date', ''))}: {p.get('scan_type', 'Not specified')}"
            for p in sorted_priors  # Pass all priors to ensure complete comparison section
        ])
        
        stage2_user_prompt = f"""Here is the original radiology report that needs interval comparison integrated:

--- START ORIGINAL REPORT ---
{current_report}
--- END ORIGINAL REPORT ---

ANALYSIS CONTEXT (from Stage 1):
Overall Summary: {stage1_result.summary}

Prior Report Scan Types (use these FULL descriptions in Comparison section):
{scan_types_context}

ALL FINDINGS ANALYZED (complete data):
{findings_json}

CHANGE DIRECTIVES TO EXECUTE:
{directives_context}

YOUR TASKS:
1. Execute each change directive systematically to generate the complete updated report
2. Document the 5-7 most significant changes you made for UI display (key_changes output)

EXECUTION INSTRUCTIONS:
- Update the Comparison section with ALL prior scan dates (UK format) and FULL scan type descriptions from context above
- CRITICAL: Comparison section should be a SIMPLE LIST of scans only (e.g., "20/12/2024 - CT Chest with IV contrast") - NO clinical observations or narrative text
- CRITICAL: List ALL prior reports in the Comparison section, not just the most recent one
- CRITICAL: Use the FULL scan type descriptions provided (e.g., "CT Abdomen and Pelvis with IV contrast"), NOT abbreviations
- For each directive, follow the integration_strategy precisely
- Use the exact measurement data provided in each directive
- If a finding has TREND information (multiple priors), integrate the full progression/regression pattern in the FINDINGS section, not in Comparison
- CRITICAL FORMATTING: Preserve exact formatting style - if original uses paragraphs, do NOT introduce bullets when adding new content. Weave new information into existing text flow.
- Update Impression section as appropriate based on interval changes

OUTPUT STRUCTURE:
You must output a structured object with TWO fields:
1. revised_report: The complete revised radiology report text
2. key_changes: List of 5-7 most significant changes made, each with "original", "revised", "reason"

For key_changes, select the most clinically significant changes (new findings, major interval changes, measurement updates, impression changes). Keep text concise (1-2 sentences each)."""
        
        stage2_system_prompt = """CRITICAL: You MUST use British English spelling and terminology throughout all output.

You are a radiology reporting assistant executing change directives from a comprehensive analysis.

YOUR TWO TASKS:
1. Generate the complete updated report by executing the change directives
2. Document the 5-7 most significant changes you made for UI display

OUTPUT: ComparisonReportGeneration with two fields:
- revised_report: The complete revised radiology report text
- key_changes: List of 5-7 most significant changes, each with:
  {
    "original": "exact text from original report that was changed",
    "revised": "exact text in the revised report",
    "reason": "brief explanation (e.g., 'New finding added', 'Updated measurement', 'Added interval comparison')"
  }

EXECUTION APPROACH:
1. Start with the original report structure
2. For each change directive:
   - Locate the appropriate section/position per integration_strategy
   - Integrate the change following the specified strategy
   - Use the exact measurements and data provided
   - Track what you changed for key_changes output
3. Select the 5-7 most clinically significant changes for key_changes

FORMATTING PRESERVATION (HIGHEST PRIORITY):
- Preserve exact structure, formatting style, and organization of the original report
- Keep all section headers exactly as they appear (e.g., "TECHNIQUE:", "FINDINGS:", "IMPRESSION:")
- CRITICAL: If original uses paragraphs, keep paragraphs (do NOT convert to bullets) - even when adding NEW content
- CRITICAL: If original uses bullet points, keep bullet points (do NOT convert to paragraphs) - even when adding NEW content
- When adding new information, integrate it into existing sentences/paragraphs - do NOT introduce bullets or new formatting styles
- Maintain the same section order and spacing
- Do NOT add or remove sections
- Match the original writing style (narrative vs. structured) consistently throughout
- NEVER mix formatting styles within a section (e.g., don't add bullets to a paragraph-based section)

COMPARISON SECTION UPDATE:
- CRITICAL: The Comparison section should be a SIMPLE LIST of prior scans ONLY - no narrative text, no clinical observations
- Format each prior as: "DD/MM/YYYY - Full Scan Type Description" (one per line)
- CRITICAL: List ALL prior reports provided in the context (do not omit any)
- List priors in reverse chronological order (most recent first)
- CRITICAL: Use the FULL scan type descriptions provided (e.g., "CT Abdomen and Pelvis with IV contrast")
- Do NOT use abbreviations like "CT" or "CT A/P" even if they appear in the original text
- Do NOT add clinical details - those belong in Findings section only

SECTION RESPONSIBILITIES (first principle — do not violate):
- The Comparison section is the canonical record of which prior studies exist (date + modality). Its job is complete once it lists them.
- Findings and Impression describe interval change, clinical trajectory, and significance. They must not replicate the Comparison catalogue. References to prior studies in prose should use qualitative anchors ("previous CT", "prior study", "the June examination") rather than repeating exact dates and full scan labels, unless temporal disambiguation is genuinely required (e.g. three studies with the same modality where the sequence matters). Reserve parenthetical notation for quantitative interval detail where it aids precision — not as a reflexive citation of study identity.

FINDINGS & IMPRESSION INTEGRATION:
- Integrate comparison language naturally within the Findings section using qualitative prior references as the default voice
- For findings with TREND data (multiple priors): Convey the clinical trajectory — direction, magnitude, pace — in prose that fits the report's narrative style; measurements and calculated intervals may be included where they add clinical value, but the prose should not read as a transcription of the structured data
- Update measurements and descriptions in-place per directives
- CRITICAL: When adding NEW findings, weave them into the existing text flow - do NOT introduce bullets if section uses paragraphs
- If adding to a paragraph section: Continue the paragraph or add a new paragraph in the same style
- If adding to a bulleted section: Add as a new bullet point
- Update recommendations in Impression section as appropriate
- Ensure clinical consistency with the analysis summary

KEY_CHANGES SELECTION CRITERIA:
- Prioritize new findings and significant interval changes
- Include measurement updates with clinical significance
- Include comparison section updates (prior scan references)
- Include impression updates
- Keep original/revised text concise (1-2 sentences each)
- Do NOT include minor formatting or punctuation changes

REASONING WORKFLOW (for high-reasoning models):
1. Review all change directives systematically
2. Plan integration order (Comparison → Findings → Impression)
3. Execute each change with precise measurement integration
4. As you make significant changes, capture them for key_changes
5. Verify internal consistency before outputting
6. Output the structured ComparisonReportGeneration object"""
        
        # Use same model for Stage 2
        stage2_model_label = f"{model_name} (Stage 2: Report + Key Changes)"
        print(f"  └─ Model: {stage2_model_label}")
        
        # Create model instance for Stage 2
        stage2_pydantic_model = _create_pydantic_model(model_name, api_key, use_thinking=False)
        
        # Create Stage 2 agent with structured output
        stage2_agent = Agent(
            stage2_pydantic_model,
            output_type=ComparisonReportGeneration,
            system_prompt=stage2_system_prompt
        )
        
        stage2_result = None
        for attempt in range(max_retries):
            try:
                # Run Stage 2 with optimized settings for report generation
                model_settings = {"temperature": 0.25}  # Slightly higher for natural flow
                if provider == 'cerebras':
                    model_settings["reasoning_effort"] = "medium"  # Less than Stage 1
                    model_settings["max_tokens"] = 5000  # Increased for report + key_changes
                    print(f"  └─ Using Cerebras reasoning_effort=medium, max_tokens=5000, temperature=0.25")
                else:
                    model_settings["max_tokens"] = 5000
                    print(f"  └─ Using model settings: {model_settings}")
                
                result = await stage2_agent.run(stage2_user_prompt, model_settings=model_settings)
                stage2_result: ComparisonReportGeneration = result.output
                
                # Validate outputs
                if not stage2_result.revised_report or not stage2_result.revised_report.strip():
                    raise ValueError("Stage 2 returned empty revised_report")
                
                stage2_elapsed = time.time() - start_time
                print(f"\n✅ Stage 2 completed in {stage2_elapsed:.2f}s")
                print(f"  └─ Revised report length: {len(stage2_result.revised_report)} chars")
                print(f"  └─ Key changes documented: {len(stage2_result.key_changes)}")
                
                # Debug: Print Stage 2 outputs
                print(f"\n{'─'*80}")
                print(f"📝 STAGE 2 OUTPUTS")
                print(f"{'─'*80}")
                
                # Key changes
                if stage2_result.key_changes:
                    print(f"\n🔑 Key Changes ({len(stage2_result.key_changes)}):")
                    for i, change in enumerate(stage2_result.key_changes, 1):
                        print(f"\n  {i}. {change.get('reason', 'No reason provided')}")
                        original_preview = change.get('original', '')[:100] + "..." if len(change.get('original', '')) > 100 else change.get('original', '')
                        revised_preview = change.get('revised', '')[:100] + "..." if len(change.get('revised', '')) > 100 else change.get('revised', '')
                        print(f"     ❌ Original: {original_preview}")
                        print(f"     ✅ Revised:  {revised_preview}")
                else:
                    print(f"\n⚠️  No key changes documented")
                
                # Revised report preview
                print(f"\n📄 Revised Report Preview (first 500 chars):")
                report_preview = stage2_result.revised_report[:500]
                # Show first few lines
                preview_lines = report_preview.split('\n')[:10]
                for line in preview_lines:
                    print(f"  {line}")
                if len(stage2_result.revised_report) > 500:
                    print(f"  ... ({len(stage2_result.revised_report) - 500} more characters)")
                
                print(f"{'─'*80}\n")
                break  # Success
                
            except Exception as e:
                print(f"\n⚠️ Stage 2 attempt {attempt + 1}/{max_retries} failed: {type(e).__name__}: {str(e)[:200]}")
                
                if attempt < max_retries - 1:
                    delay = 2.0 * (2 ** attempt)
                    print(f"⚠️ Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                else:
                    print(f"❌ Stage 2 failed after {max_retries} attempts")
                    raise Exception(f"Stage 2 (Report Generation) failed after {max_retries} retries: {str(e)}")
        
        if not stage2_result:
            raise Exception("Stage 2 (Report Generation) did not produce a result")
        
        # ============================================================================
        # COMBINE STAGES: Merge Stage 1 analysis with Stage 2 report
        # ============================================================================
        
        final_result = ComparisonAnalysis(
            findings=stage1_result.findings,              # From Stage 1
            summary=stage1_result.summary,                # From Stage 1
            change_directives=stage1_result.change_directives,  # From Stage 1 (NEW!)
            revised_report=stage2_result.revised_report,  # From Stage 2
            key_changes=stage2_result.key_changes         # From Stage 2 (NEW source!)
        )
        
        total_elapsed = time.time() - start_time
        print(f"\n{'='*80}")
        print(f"✅ TWO-STAGE COMPARISON COMPLETE")
        print(f"{'='*80}")
        print(f"⏱️  Total time: {total_elapsed:.2f}s")
        print(f"\n📊 Summary:")
        print(f"  └─ Total findings: {len(final_result.findings)}")
        print(f"     • Changed: {len([f for f in final_result.findings if f.status == 'changed'])}")
        print(f"     • New: {len([f for f in final_result.findings if f.status == 'new'])}")
        print(f"     • Stable: {len([f for f in final_result.findings if f.status == 'stable'])}")
        print(f"  └─ Change directives (Stage 1): {len(final_result.change_directives)}")
        print(f"  └─ Key changes (Stage 2): {len(final_result.key_changes)}")
        print(f"  └─ Revised report: {len(final_result.revised_report)} chars")
        print(f"  └─ Tool calls made: {len(tool_calls_log)}")
        print(f"{'='*80}\n")
        
        return final_result
        
    finally:
        # Restore environment variable
        if old_api_key is not None:
            os.environ[env_var_name] = old_api_key
        else:
            os.environ.pop(env_var_name, None)


# ============================================================================
# Report Generation Functions (Pydantic AI)
# ============================================================================


def _log_model_inputs(model_label: str, system_prompt: str, user_prompt: str):
    """
    Log the exact inputs being fed to the model in a user-friendly format.
    
    Args:
        model_label: Human-readable model name
        system_prompt: System prompt being used
        user_prompt: User prompt (with variables injected)
    """
    print("\n" + "="*80)
    print(f"📤 MODEL INPUT LOG - {model_label}")
    print("="*80)
    
    print("\n🔧 SYSTEM PROMPT:")
    print("-" * 80)
    print(system_prompt)
    print("-" * 80)
    
    print("\n💬 USER PROMPT (with variables injected):")
    print("-" * 80)
    print(user_prompt)
    print("-" * 80)
    
    print("\n📊 PROMPT STATISTICS:")
    print(f"  System prompt length: {len(system_prompt)} characters")
    print(f"  User prompt length: {len(user_prompt)} characters")
    print(f"  Total input length: {len(system_prompt) + len(user_prompt)} characters")
    
    print("="*80 + "\n")


def _append_signature_to_report(report_output: ReportOutput, signature: str | None) -> ReportOutput:
    """
    Append signature to report_content programmatically if signature is provided.
    
    Args:
        report_output: The ReportOutput object to modify
        signature: Optional signature string to append
        
    Returns:
        Modified ReportOutput with signature appended to report_content if signature exists
    """
    if signature and signature.strip():
        # Append signature with double line break before it
        report_output.report_content = report_output.report_content.rstrip() + "\n\n" + signature
        print(f"_append_signature_to_report: Signature appended programmatically ({len(signature)} chars)")
    return report_output


async def _generate_report_with_claude_model(
    model_name: str,
    model_label: str,
    final_prompt: str,
    system_prompt: str,
    api_key: str,
    signature: str | None = None
) -> ReportOutput:
    """
    Helper function to generate report with Claude as fallback.
    
    Args:
        model_name: Anthropic model identifier
        model_label: Human-readable model name for logging
        final_prompt: The user prompt (with signature applied)
        system_prompt: System prompt
        api_key: Anthropic API key
    
    Returns:
        ReportOutput with report_content and description
    """
    import os
    
    start_time = time.time()
    print(f"generate_auto_report: Attempting with {model_label}...")
    
    # Log the exact inputs being fed to the model
    _log_model_inputs(model_label, system_prompt, final_prompt)
    
    old_api_key = os.environ.get('ANTHROPIC_API_KEY')
    os.environ['ANTHROPIC_API_KEY'] = api_key
    
    try:
        pydantic_model = AnthropicModel(model_name)
        
        agent = Agent(
            pydantic_model,
            output_type=ReportOutput,
            system_prompt=system_prompt,
        )
        
        result = await agent.run(
            final_prompt,
            model_settings={
                "temperature": 1,
                "max_tokens": 6500,
                "anthropic_thinking": {
                    "type": "enabled",
                    "budget_tokens": 2048
                }
            }
        )
        
        # Log thinking parts (backend only - not sent to frontend)
        _log_thinking_parts(result, f"{model_label} - Claude")
        
        report_output: ReportOutput = result.output
        
        # Append signature programmatically if provided
        report_output = _append_signature_to_report(report_output, signature)
        
        report_output.model_used = model_name
        elapsed = time.time() - start_time
        print(f"generate_auto_report: ✅ Completed with {model_label} in {elapsed:.2f}s")
        print(f"  └─ Report length: {len(report_output.report_content)} chars")
        print(f"  └─ Description: {report_output.description}")
        
        return report_output
    finally:
        if old_api_key is not None:
            os.environ['ANTHROPIC_API_KEY'] = old_api_key
        else:
            os.environ.pop('ANTHROPIC_API_KEY', None)


def _create_pydantic_model(model_name: str, api_key: str, use_thinking: bool = False):
    """
    Create a pydantic AI model instance based on provider detection.
    Note: Environment variable management is handled by the caller.
    
    Args:
        model_name: Model identifier (e.g., "qwen/qwen3-32b", "gpt-oss-120b")
        api_key: API key for the model provider
        use_thinking: Whether to enable thinking mode (only applies to Groq models)
    
    Returns:
        Pydantic AI model instance (GroqModel, AnthropicModel, or OpenAIModel)
    """
    provider = _get_model_provider(model_name)
    
    if provider == 'groq':
        return GroqModel(model_name)
    elif provider == 'anthropic':
        return AnthropicModel(model_name)
    elif provider == 'cerebras':
        provider_obj = OpenAIProvider(
            base_url='https://api.cerebras.ai/v1',
            api_key=api_key,
        )
        return OpenAIModel(model_name, provider=provider_obj)
    elif provider == 'fireworks':
        provider_obj = OpenAIProvider(
            base_url='https://api.fireworks.ai/inference/v1',
            api_key=api_key,
        )
        return OpenAIModel(model_name, provider=provider_obj)
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def _run_agent_with_model(
    model_name: str,
    output_type,
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    use_thinking: bool = False,
    model_settings: dict = None,
    tools: list = None,
):
    """
    Run an agent with unified model creation and execution.
    
    Args:
        model_name: Model identifier
        output_type: Pydantic model class for structured output
        system_prompt: System prompt for the agent
        user_prompt: User prompt/message
        api_key: API key for the model provider
        use_thinking: Whether to enable thinking mode (only for Groq)
        model_settings: Additional model settings dict
        tools: Optional list of async callable tools to register on the agent
    
    Returns:
        Agent result object
    """
    import os
    
    provider = _get_model_provider(model_name)
    
    # Determine which environment variable to manage
    env_var_map = {
        'groq': 'GROQ_API_KEY',
        'anthropic': 'ANTHROPIC_API_KEY',
        'cerebras': 'CEREBRAS_API_KEY',
        'fireworks': 'FIREWORKS_API_KEY',
    }
    env_var_name = env_var_map[provider]
    
    # Save old value and set new API key
    old_api_key = os.environ.get(env_var_name)
    os.environ[env_var_name] = api_key
    
    try:
        # Create model
        pydantic_model = _create_pydantic_model(model_name, api_key, use_thinking)
        
        # Create agent settings
        agent_model_settings = None
        if provider == 'groq' and use_thinking:
            agent_model_settings = GroqModelSettings(groq_reasoning_format='parsed')
        
        # Create agent (with optional tools)
        agent = Agent(
            pydantic_model,
            output_type=output_type,
            system_prompt=system_prompt,
            model_settings=agent_model_settings,
            tools=tools or [],
            retries=2,
        )
        
        # Build final model settings dict
        final_model_settings = model_settings or {}
        
        # Log model settings for Cerebras to verify reasoning_effort is included
        if provider == 'cerebras':
            print(f"\n🔧 CEREBRAS MODEL SETTINGS ({model_name}):")
            print(f"  └─ temperature: {final_model_settings.get('temperature', 'not set')}")
            print(f"  └─ top_p: {final_model_settings.get('top_p', 'not set')}")
            if 'max_completion_tokens' in final_model_settings:
                print(f"  └─ max_completion_tokens: {final_model_settings.get('max_completion_tokens', 'not set')}")
            else:
                print(f"  └─ max_tokens: {final_model_settings.get('max_tokens', 'not set')}")
            if 'extra_body' in final_model_settings:
                print(f"  └─ extra_body: {final_model_settings.get('extra_body')}")
            # reasoning_effort is GPT-OSS only; GLM/Qwen3 use extra_body toggles
            if model_name == "zai-glm-4.7":
                disable_reasoning = (final_model_settings.get('extra_body') or {}).get('disable_reasoning', 'not set')
                mode_label = "REASONING OFF" if disable_reasoning else "REASONING ON"
                print(f"  └─ GLM mode: {mode_label} (disable_reasoning={disable_reasoning})")
            elif model_name == "qwen-3-235b-a22b-instruct-2507":
                print(f"  └─ Qwen3 mode: thinking auto-hidden for JSON schema (no extra_body needed)")
            else:
                reasoning_effort = final_model_settings.get('reasoning_effort')
                if reasoning_effort:
                    print(f"  └─ reasoning_effort: {reasoning_effort} ✅")
                else:
                    print(f"  └─ reasoning_effort: NOT SET ⚠️  (check if parameter is supported)")
        
        if provider == 'fireworks':
            print(f"\n🔧 FIREWORKS MODEL SETTINGS ({model_name}):")
            print(f"  └─ temperature: {final_model_settings.get('temperature', 'not set')}")
            print(f"  └─ top_p: {final_model_settings.get('top_p', 'not set')}")
            print(f"  └─ max_tokens: {final_model_settings.get('max_tokens', 'not set')}")
            reasoning_effort = final_model_settings.get('reasoning_effort', 'not set')
            print(f"  └─ reasoning_effort: {reasoning_effort}")

        # Run agent with concurrency guard for Cerebras
        try:
            if provider == 'cerebras':
                async with _cerebras_semaphore:
                    result = await agent.run(
                        user_prompt,
                        model_settings=final_model_settings
                    )
            else:
                result = await agent.run(
                    user_prompt,
                    model_settings=final_model_settings
                )
            
            # Log thinking parts for Groq models
            if provider == 'groq' and use_thinking:
                _log_thinking_parts(result, f"{model_name} - {provider}")
            
            return result
        except Exception as e:
            # For Cerebras, try to capture raw output before validation fails
            if provider == 'cerebras':
                print(f"\n{'='*80}")
                print(f"🔍 CEREBRAS RAW OUTPUT DEBUG ({model_name})")
                print(f"{'='*80}")
                print(f"Error type: {type(e).__name__}")
                print(f"Error message: {str(e)}")
                
                # Try to extract raw response from exception if available
                if hasattr(e, 'args') and e.args:
                    print(f"Error args: {e.args}")
                if hasattr(e, '__cause__') and e.__cause__:
                    print(f"Error cause: {type(e.__cause__).__name__}: {str(e.__cause__)}")
                if hasattr(e, '__context__') and e.__context__:
                    print(f"Error context: {type(e.__context__).__name__}: {str(e.__context__)}")
                
                # Check for pydantic_ai specific attributes
                if hasattr(e, 'response'):
                    print(f"Exception has 'response' attribute: {e.response}")
                if hasattr(e, 'raw_response'):
                    print(f"Exception has 'raw_response' attribute: {e.raw_response}")
                if hasattr(e, 'data'):
                    print(f"Exception has 'data' attribute: {e.data}")
                if hasattr(e, 'body'):
                    print(f"Exception has 'body' attribute: {e.body}")
                if hasattr(e, 'text'):
                    print(f"Exception has 'text' attribute: {e.text}")
                
                # Print all exception attributes for debugging
                print(f"\nException attributes: {[attr for attr in dir(e) if not attr.startswith('_')]}")
                
                # Check if exception has response data
                error_str = str(e)
                print(f"\nFull error string (first 2000 chars):")
                print(f"{error_str[:2000]}")
                
                # Try to access any response data from the exception
                import traceback
                tb_str = traceback.format_exc()
                print(f"\nFull traceback (may contain response data):")
                print(tb_str[:4000])  # Print first 4000 chars of traceback
                
                print(f"{'='*80}\n")

            if provider == "groq" and output_type is ReportOutput:
                recovered = _recover_report_output_from_groq_tool_use_failed(e)
                if recovered is not None:
                    print(
                        "[groq] Recovered ReportOutput from tool_use_failed "
                        "(model emitted JSON in message body; Groq rejected non-tool format)"
                    )
                    return SimpleNamespace(output=recovered)

            # Re-raise the exception
            raise
    finally:
        # Restore environment variable
        if old_api_key is not None:
            os.environ[env_var_name] = old_api_key
        else:
            os.environ.pop(env_var_name, None)


async def _generate_report_with_groq_model(
    model_name: str,
    model_label: str,
    final_prompt: str,
    system_prompt: str,
    api_key: str
) -> ReportOutput:
    """
    Helper function to generate report with a specific Groq model.
    
    Args:
        model_name: Groq model identifier
        model_label: Human-readable model name for logging
        final_prompt: The user prompt (with signature applied)
        system_prompt: System prompt
        api_key: Groq API key
    
    Returns:
        ReportOutput with report_content and description
    """
    import os
    
    start_time = time.time()
    print(f"generate_auto_report: Attempting with {model_label}...")
    
    # Log the exact inputs being fed to the model
    _log_model_inputs(model_label, system_prompt, final_prompt)
    
    old_api_key = os.environ.get('GROQ_API_KEY')
    os.environ['GROQ_API_KEY'] = api_key
    
    try:
        # Create Groq model with thinking enabled
        groq_settings = GroqModelSettings(groq_reasoning_format='parsed')
        pydantic_model = GroqModel(model_name)
        
        agent = Agent(
            pydantic_model,
            output_type=ReportOutput,
            system_prompt=system_prompt,
            model_settings=groq_settings,
        )
        
        try:
            result = await agent.run(
                final_prompt,
                model_settings={
                    "temperature": 0.3,
                    "max_tokens": 4096,
                }
            )
        except Exception as run_exc:
            recovered = _recover_report_output_from_groq_tool_use_failed(run_exc)
            if recovered is None:
                raise run_exc
            print(
                f"generate_auto_report: Recovered {model_label} output from Groq tool_use_failed"
            )
            report_output = recovered
        else:
            # Log thinking parts (backend only - not sent to frontend)
            _log_thinking_parts(result, f"{model_label} - Groq/Qwen")
            report_output = result.output
        
        elapsed = time.time() - start_time
        print(f"generate_auto_report: ✅ Completed with {model_label} in {elapsed:.2f}s")
        print(f"  └─ Report length: {len(report_output.report_content)} chars")
        print(f"  └─ Description: {report_output.description}")
        
        return report_output
    finally:
        if old_api_key is not None:
            os.environ['GROQ_API_KEY'] = old_api_key
        else:
            os.environ.pop('GROQ_API_KEY', None)


async def generate_auto_report(
    model: str,
    user_prompt: str,
    system_prompt: str,
    api_key: str,
    signature: str | None = None,
    clinical_history: str = ""
) -> ReportOutput:
    """
    Generate a radiology report using configured primary model with automatic fallback.
    Model selection is driven by MODEL_CONFIG - just change PRIMARY_REPORT_GENERATOR
    to swap models (supports Groq/Qwen, Anthropic/Claude, or Cerebras).
    
    Args:
        model: Model identifier (kept for API compatibility, actual model from MODEL_CONFIG)
        user_prompt: The rendered user prompt with variables
        system_prompt: System prompt from PromptManager
        api_key: API key (provider-specific, will be determined automatically)
        signature: Optional user signature to inject
        
    Returns:
        ReportOutput with report_content and description
    """
    import os
    
    start_time = time.time()
    primary_model = MODEL_CONFIG["PRIMARY_REPORT_GENERATOR"]
    provider = _get_model_provider(primary_model)
    
    print(f"generate_auto_report: Starting with {primary_model} ({provider})")
    
    # Remove signature placeholder from prompt if present (signature will be appended programmatically)
    final_prompt = user_prompt
    if '{{SIGNATURE}}' in final_prompt:
        final_prompt = final_prompt.replace('{{SIGNATURE}}', '').strip()
        print(f"generate_auto_report: Removed signature placeholder from prompt (will append programmatically)")
    
    # Try primary model with retry logic
    try:
        # Log the exact inputs being fed to the model
        _log_model_inputs(f"{primary_model} (Primary)", system_prompt, final_prompt)
        
        # Get API key for primary model
        primary_api_key = _get_api_key_for_provider(provider, api_key)
        
        # Wrap primary model call with retry logic
        @with_retry(max_retries=3, base_delay=2.0)
        async def _try_primary():
            # Build model settings with conditional reasoning_effort and max_completion_tokens for Cerebras
            model_settings = {
                "temperature": 1,
            }
            if primary_model == "zai-glm-4.7":
                if _glm_reasoning_enabled():
                    # Reasoning ON: temperature 0.8 (instruction-following), top_p per Z.ai guidance
                    # 16k tokens: headroom for full reasoning trace + JSON report without truncation
                    model_settings["max_completion_tokens"] = 16000
                    model_settings["temperature"] = 0.8
                    model_settings["top_p"] = 0.95
                    model_settings["extra_body"] = {"disable_reasoning": False}
                    print(f"  └─ GLM mode: REASONING ON — temperature=0.8, top_p=0.95, max_completion_tokens=16000")
                else:
                    # Reasoning OFF: no temp floor, use lower value for more deterministic output
                    model_settings["max_completion_tokens"] = 6000
                    model_settings["temperature"] = 0.5
                    model_settings["extra_body"] = {"disable_reasoning": True}
                    print(f"  └─ GLM mode: REASONING OFF — temperature=0.5, max_completion_tokens=6000")
            elif primary_model == "qwen-3-235b-a22b-instruct-2507":
                # Qwen3: thinking is automatically hidden for JSON schema requests by Cerebras
                # No extra_body needed — Cerebras rejects enable_thinking on this endpoint
                model_settings["max_completion_tokens"] = 6000
                model_settings["temperature"] = 0.7
                print(f"  └─ Using Qwen3-235B — temperature=0.7, max_completion_tokens=6000 (thinking auto-hidden for JSON schema)")
            elif primary_model == "gpt-oss-120b":
                model_settings["max_completion_tokens"] = 6500
                model_settings["reasoning_effort"] = "high"
                print(f"  └─ Using Cerebras reasoning_effort=high, max_completion_tokens=6500 for {primary_model}")
            elif provider == "fireworks":
                model_settings["max_tokens"] = 16000
                model_settings["temperature"] = 0.6
                model_settings["top_p"] = 0.95
                model_settings["reasoning_effort"] = "high"
                print(f"  └─ Using Fireworks GLM-5.1 — temperature=0.6, reasoning_effort=high, max_tokens=16000")
            elif provider == "anthropic":
                model_settings["max_tokens"] = 8000
                model_settings["anthropic_thinking"] = {
                    "type": "enabled",
                    "budget_tokens": 2048
                }
                print(f"  └─ Using Claude with thinking enabled, budget_tokens=2048, temperature=1 for {primary_model}")
            else:
                model_settings["max_tokens"] = 8000
            
            result = await _run_agent_with_model(
                model_name=primary_model,
                output_type=ReportOutput,
                system_prompt=system_prompt,
                user_prompt=final_prompt,
                api_key=primary_api_key,
                use_thinking=(provider == 'groq'),  # Enable thinking for Groq models
                model_settings=model_settings
            )
            return result
        
        result = await _try_primary()
        
        # Log thinking/reasoning for all supported reasoning models
        if provider == "anthropic":
            _log_thinking_parts(result, f"{primary_model} (Primary) - Claude Extended Thinking")
        elif primary_model == "zai-glm-4.7":
            _log_glm_reasoning(result, f"{primary_model} (Primary) - GLM Reasoning")
        
        report_output = result.output
        
        # Normalise literal \n sequences that GLM reasoning mode can produce.
        # When reasoning is ON, GLM sometimes double-escapes newlines in its JSON
        # output (\n → \\n), leaving literal backslash-n characters in the parsed
        # string. The linguistic validator corrects this as a side effect, but
        # normalise here explicitly so formatting is never validator-dependent.
        if report_output.report_content and '\\n' in report_output.report_content:
            report_output.report_content = report_output.report_content.replace('\\n', '\n')
            print(f"  └─ Normalised literal \\n sequences in report content")
        
        # Don't append signature yet - will append after validation
        
        elapsed = time.time() - start_time
        print(f"generate_auto_report: ✅ Completed with {primary_model} (primary) in {elapsed:.2f}s")
        print(f"  └─ Report length: {len(report_output.report_content)} chars")
        print(f"  └─ Description: {report_output.description}")
        
        # DETAILED LOGGING FOR DEBUGGING
        print(f"\n{'='*80}")
        print(f"RAW OUTPUT DEBUG - generate_auto_report ({primary_model})")
        print(f"{'='*80}")
        print(f"Report length: {len(report_output.report_content)} chars")
        print(f"Newline count: {report_output.report_content.count(chr(10))}")
        print(f"Double newline count: {report_output.report_content.count(chr(10)+chr(10))}")
        print(f"\nFull report content:")
        print(report_output.report_content)
        print(f"{'='*80}\n")
        
        # LINGUISTIC VALIDATION disabled for quick reports — primary model handles style natively.
        # Template reports (generate_templated_report) still run the validator.
        # Re-enable by changing `if False` back to `if primary_model in (...)`.
        if False and primary_model in ("zai-glm-4.7", "qwen-3-235b-a22b-instruct-2507"):
            import os
            ENABLE_LINGUISTIC_VALIDATION = os.getenv("ENABLE_ZAI_GLM_LINGUISTIC_VALIDATION", "true").lower() == "true"
            
            if ENABLE_LINGUISTIC_VALIDATION:
                try:
                    print(f"\n{'='*80}")
                    print(f"🔍 LINGUISTIC VALIDATION - Starting for {primary_model}")
                    print(f"{'='*80}")
                    
                    validated_content = await validate_zai_glm_linguistics(
                        report_content=report_output.report_content,
                        scan_type=report_output.scan_type or "",
                        description=report_output.description or "",
                        clinical_history=clinical_history
                    )
                    
                    report_output.report_content = validated_content
                    print(f"✅ LINGUISTIC VALIDATION COMPLETE")
                    print(f"{'='*80}")
                    print(f"📋 POST-VALIDATION OUTPUT DEBUG")
                    print(f"{'='*80}")
                    print(f"Report length: {len(validated_content)} chars")
                    print(f"\nFull validated report content:")
                    print(validated_content)
                    print(f"{'='*80}\n")
                except Exception as e:
                    print(f"\n{'='*80}")
                    print(f"⚠️ LINGUISTIC VALIDATION FAILED - continuing with original report")
                    print(f"{'='*80}")
                    print(f"[ERROR] Exception type: {type(e).__name__}")
                    print(f"[ERROR] Error message: {str(e)[:300]}")
                    import traceback
                    print(f"[ERROR] Traceback:")
                    print(traceback.format_exc()[:500])
                    print(f"[DEBUG] Returning original report (validation skipped)")
                    print(f"{'='*80}\n")
            else:
                print(f"[DEBUG] Linguistic validation disabled (ENABLE_ZAI_GLM_LINGUISTIC_VALIDATION=false)")
        
        # Append signature AFTER validation (or if validation disabled)
        if signature:
            report_output = _append_signature_to_report(report_output, signature)
        
        report_output.model_used = primary_model
        return report_output
                
    except Exception as e:
        # Primary failed - determine why and fallback
        fallback_model = MODEL_CONFIG["FALLBACK_REPORT_GENERATOR"]
        if _is_parsing_error(e):
            print(f"⚠️ {primary_model} parsing error detected - immediate fallback to {fallback_model}")
            print(f"  Error: {type(e).__name__}: {str(e)[:200]}")
        else:
            print(f"⚠️ {primary_model} failed after retries ({type(e).__name__}) - falling back to {fallback_model}")
            print(f"  Error: {type(e).__name__}: {str(e)[:200]}")
        
        # Fallback to configured fallback model (Claude Sonnet 4)
        try:
            if not api_key:
                raise Exception(f"{primary_model} failed and no fallback API key available. Original error: {e}") from e
            
            return await _generate_report_with_claude_model(
                fallback_model,
                f"{fallback_model} (fallback)",
                final_prompt,
                system_prompt,
                api_key,
                signature
            )
        except Exception as fallback_error:
            # Both models failed - re-raise the original error with context
            print(f"❌ Fallback model also failed: {type(fallback_error).__name__}")
            import traceback
            print(traceback.format_exc())
            raise Exception(f"Report generation failed with both {primary_model} and {fallback_model}. Original error: {e}") from e


async def generate_templated_report(
    model: str,
    user_prompt: str,
    system_prompt: str,
    api_key: str,
    signature: str | None = None
) -> ReportOutput:
    """
    Generate a templated radiology report using configured primary model with automatic fallback.
    Model selection is driven by MODEL_CONFIG - just change PRIMARY_REPORT_GENERATOR
    to swap models (supports Groq/Qwen, Anthropic/Claude, or Cerebras).
    
    Args:
        model: Model identifier (kept for API compatibility, actual model from MODEL_CONFIG)
        user_prompt: The task-specific user prompt from TemplateManager
        system_prompt: The persistent system prompt from TemplateManager
        api_key: API key (provider-specific, will be determined automatically)
        signature: Optional user signature to inject
        
    Returns:
        ReportOutput with report_content and description
    """
    import os
    
    start_time = time.time()
    # Templated reports use zai-glm-4.7 as primary, Claude as fallback
    primary_model = "zai-glm-4.7"
    fallback_model = MODEL_CONFIG["FALLBACK_REPORT_GENERATOR"]
    provider = _get_model_provider(primary_model)
    
    print(f"generate_templated_report: Starting with {primary_model} ({provider}), fallback: {fallback_model}")
    
    # Use prompt as-is (signature will be appended programmatically after generation)
    final_prompt = user_prompt
    
    # Try primary model with retry logic
    try:
        # Get API key for primary model
        primary_api_key = _get_api_key_for_provider(provider, api_key)
        
        # Wrap primary model call with retry logic
        @with_retry(max_retries=3, base_delay=2.0)
        async def _try_primary():
            # Build model settings with conditional reasoning_effort and max_completion_tokens for Cerebras
            model_settings = {
                "temperature": 0.7,
            }
            if primary_model == "zai-glm-4.7":
                if _glm_reasoning_enabled():
                    model_settings["max_completion_tokens"] = 16000
                    model_settings["temperature"] = 0.8
                    model_settings["extra_body"] = {"disable_reasoning": False}
                    print(f"  └─ GLM mode: REASONING ON — temperature=0.8, max_completion_tokens=16000")
                else:
                    model_settings["max_completion_tokens"] = 6000
                    model_settings["temperature"] = 0.5
                    model_settings["extra_body"] = {"disable_reasoning": True}
                    print(f"  └─ GLM mode: REASONING OFF — temperature=0.5, max_completion_tokens=6000")
            elif primary_model == "qwen-3-235b-a22b-instruct-2507":
                model_settings["max_completion_tokens"] = 6000
                model_settings["temperature"] = 0.7
                print(f"  └─ Using Qwen3-235B — temperature=0.7, max_completion_tokens=6000 (thinking auto-hidden for JSON schema)")
            elif primary_model == "gpt-oss-120b":
                model_settings["max_completion_tokens"] = 6500
                model_settings["reasoning_effort"] = "high"
                print(f"  └─ Using Cerebras reasoning_effort=high, max_completion_tokens=6500 for {primary_model}")
            elif provider == "anthropic":
                model_settings["max_tokens"] = 8000
                model_settings["anthropic_thinking"] = {
                    "type": "enabled",
                    "budget_tokens": 2048
                }
                print(f"  └─ Using Claude with thinking enabled, budget_tokens=2048, temperature=0.7 for {primary_model}")
            else:
                model_settings["max_tokens"] = 8000
            
            result = await _run_agent_with_model(
                model_name=primary_model,
                output_type=ReportOutput,
                system_prompt=system_prompt,
                user_prompt=final_prompt,
                api_key=primary_api_key,
                use_thinking=(provider == 'groq'),  # Enable thinking for Groq models
                model_settings=model_settings
            )
            return result
        
        result = await _try_primary()
        
        # Log thinking/reasoning for all supported reasoning models
        if provider == 'groq':
            _log_thinking_parts(result, f"{primary_model} (Primary) - Groq")
        elif primary_model == "zai-glm-4.7":
            _log_glm_reasoning(result, f"{primary_model} (Primary) - GLM Reasoning")
        
        report_output = result.output
        
        # Normalise literal \n sequences (same fix as generate_auto_report)
        if report_output.report_content and '\\n' in report_output.report_content:
            report_output.report_content = report_output.report_content.replace('\\n', '\n')
            print(f"  └─ Normalised literal \\n sequences in report content")
        
        # Don't append signature yet - will append after validation
        
        elapsed = time.time() - start_time
        print(f"generate_templated_report: ✅ Completed with {primary_model} (primary) in {elapsed:.2f}s")
        print(f"  └─ Report length: {len(report_output.report_content)} chars")
        print(f"  └─ Description: {report_output.description}")
        
        # DETAILED LOGGING FOR DEBUGGING
        print(f"\n{'='*80}")
        print(f"RAW OUTPUT DEBUG - generate_templated_report ({primary_model})")
        print(f"{'='*80}")
        print(f"Report length: {len(report_output.report_content)} chars")
        print(f"Newline count: {report_output.report_content.count(chr(10))}")
        print(f"Double newline count: {report_output.report_content.count(chr(10)+chr(10))}")
        print(f"\nFull report content:")
        print(report_output.report_content)
        print(f"{'='*80}\n")
        
        # LINGUISTIC VALIDATION for non-Anthropic Cerebras models (conditionally enabled)
        if primary_model in ("zai-glm-4.7", "qwen-3-235b-a22b-instruct-2507"):
            import os
            ENABLE_LINGUISTIC_VALIDATION = os.getenv("ENABLE_ZAI_GLM_LINGUISTIC_VALIDATION", "true").lower() == "true"
            
            if ENABLE_LINGUISTIC_VALIDATION:
                try:
                    print(f"\n{'='*80}")
                    print(f"🔍 LINGUISTIC VALIDATION - Starting for {primary_model}")
                    print(f"{'='*80}")
                    
                    validated_content = await validate_zai_glm_linguistics(
                        report_content=report_output.report_content,
                        scan_type=report_output.scan_type or "",
                        description=report_output.description or "",
                        clinical_history=clinical_history
                    )
                    
                    report_output.report_content = validated_content
                    print(f"✅ LINGUISTIC VALIDATION COMPLETE")
                    print(f"{'='*80}")
                    print(f"📋 POST-VALIDATION OUTPUT DEBUG")
                    print(f"{'='*80}")
                    print(f"Report length: {len(validated_content)} chars")
                    print(f"\nFull validated report content:")
                    print(validated_content)
                    print(f"{'='*80}\n")
                except Exception as e:
                    print(f"\n{'='*80}")
                    print(f"⚠️ LINGUISTIC VALIDATION FAILED - continuing with original report")
                    print(f"{'='*80}")
                    print(f"[ERROR] Exception type: {type(e).__name__}")
                    print(f"[ERROR] Error message: {str(e)[:300]}")
                    import traceback
                    print(f"[ERROR] Traceback:")
                    print(traceback.format_exc()[:500])
                    print(f"[DEBUG] Returning original report (validation skipped)")
                    print(f"{'='*80}\n")
            else:
                print(f"[DEBUG] Linguistic validation disabled (ENABLE_ZAI_GLM_LINGUISTIC_VALIDATION=false)")
        
        # Append signature AFTER validation (or if validation disabled)
        if signature:
            report_output = _append_signature_to_report(report_output, signature)
        
        return report_output
        
    except Exception as e:
        # Primary failed - determine why and fallback to Claude
        if _is_parsing_error(e):
            print(f"⚠️ {primary_model} parsing error detected - immediate fallback to {fallback_model}")
            print(f"  Error: {type(e).__name__}: {str(e)[:200]}")
        else:
            print(f"⚠️ {primary_model} failed after retries ({type(e).__name__}) - falling back to {fallback_model}")
            print(f"  Error: {str(e)[:200]}")
        
        # Fallback to Claude Sonnet 4
        try:
            if not api_key:
                raise Exception(f"{primary_model} failed and no fallback API key available. Original error: {e}") from e
            
            return await _generate_report_with_claude_model(
                fallback_model,
                f"{fallback_model} (fallback)",
                final_prompt,
                system_prompt,
                api_key,
                signature
            )
        except Exception as fallback_error:
            # Both models failed - re-raise the original error with context
            print(f"❌ Fallback model also failed: {type(fallback_error).__name__}")
            import traceback
            print(traceback.format_exc())
            raise Exception(f"Templated report generation failed with both {primary_model} and {fallback_model}. Original error: {e}") from e

@with_retry(max_retries=3, base_delay=2.0)
async def validate_report_structure(
    report_content: str,
    scan_type: str,
    findings: str
) -> StructureValidationResult:
    """
    Validate radiology report for structural quality violations using Qwen with thinking (fast).
    Checks for redundancy, prose flow, duplication, brevity, impression verbosity, pertinent negative placement.
    Returns violations + proposed actions for GPT-OSS to execute.
    
    Args:
        report_content: The generated report content to validate
        scan_type: The extracted scan type and protocol (e.g., "CT head non-contrast")
        findings: The original findings input
        
    Returns:
        StructureValidationResult with violations list, proposed actions, and validation status
    """
    import os
    import time
    
    start_time = time.time()
    print(f"\n[STRUCTURE VALIDATION] Starting structural validation")
    print(f"[STRUCTURE VALIDATION]   Scan type: '{scan_type}'")
    print(f"[STRUCTURE VALIDATION]   Report length: {len(report_content)} chars")
    print(f"[STRUCTURE VALIDATION]   Findings length: {len(findings)} chars")
    
    # Get model and provider
    model_name = MODEL_CONFIG["STRUCTURE_VALIDATOR"]
    provider = _get_model_provider(model_name)
    api_key = _get_api_key_for_provider(provider)
    
    print(f"[STRUCTURE VALIDATION]   Primary model: {model_name} ({provider})")
    
    # GPT-OSS doesn't use thinking format
    use_thinking = False
    print(f"[STRUCTURE VALIDATION]   Thinking enabled: False (GPT-OSS)")
    
    # Build simplified validation prompt - focused on 3 critical issues
    validation_prompt = f"""Validate this radiology report for structural quality violations.

SCAN TYPE: {scan_type}

REPORT TO VALIDATE:
{report_content}

ORIGINAL FINDINGS INPUT:
{findings}

=== VALIDATION RULES (CHECK THESE 3 CRITICAL ISSUES) ===

**1. REDUNDANCY CHECK:**
- Each anatomical structure must appear only ONCE in the entire report
- Same information must not be stated multiple times (even in different words)
- Pertinent negatives must not be repeated across paragraphs

**2. GROUPING CHECK:**
- Related normal structures should be grouped together, not listed individually
- If there are 3+ consecutive sentences about normal structures that could be combined, flag for grouping

**3. IMPRESSION CHECK:**
- Impression must be 1-2 sentences in prose format (NOT bullet points)
- Impression must contain ONLY: diagnostic conclusions, differentials, actionable recommendations
- Impression must NOT contain: descriptive details from Findings, benign incidentals below action threshold

=== OUTPUT FORMAT ===

For each violation found, provide:
- location: Specific section (e.g., "Findings paragraph 2", "Impression")
- issue: What's wrong (e.g., "Liver mentioned twice - once in paragraph 1 and again in paragraph 3")
- fix: Specific instruction using this format:
  * "MERGE: [list structures] into single sentence" (for grouping)
  * "REMOVE: [exact duplicate text]" (for redundancy)
  * "MOVE: [text] from Impression to Findings" (for impression issues)

If no violations found, return empty violations list with is_valid=True.
"""
    
    # Build model settings - Qwen uses max_tokens, no reasoning_effort
    model_settings = {
        "temperature": 0.1,  # Low temperature for rule-checking
    }
    if model_name == "gpt-oss-120b":
        model_settings["max_completion_tokens"] = 2000
        model_settings["reasoning_effort"] = "medium"
        print(f"[STRUCTURE VALIDATION]   Model settings: Cerebras (reasoning_effort=medium, max_completion_tokens=2000)")
    else:
        model_settings["max_tokens"] = 2000
        print(f"[STRUCTURE VALIDATION]   Model settings: {model_name} (temperature=0.1, max_tokens=2000)")
    
    # Try primary model with retry logic
    print(f"[STRUCTURE VALIDATION] Calling primary model: {model_name}...")
    try:
        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=StructureValidationResult,
            system_prompt="You are a radiology report structure validator. Check for 3 critical issues: (1) redundancy - structures mentioned multiple times, (2) grouping - normal structures that should be combined, (3) impression - contains descriptive content that belongs in Findings. Be precise - only flag actual violations.",
            user_prompt=validation_prompt,
            api_key=api_key,
            use_thinking=use_thinking,  # Enable thinking for Qwen
            model_settings=model_settings
        )
        
        validation_result: StructureValidationResult = result.output
        
        print(f"[STRUCTURE VALIDATION] ✅ Primary model succeeded")
        
    except Exception as e:
        # Primary failed - try fallback
        fallback_model = MODEL_CONFIG["STRUCTURE_VALIDATOR_FALLBACK"]
        fallback_provider = _get_model_provider(fallback_model)
        fallback_api_key = _get_api_key_for_provider(fallback_provider)
        
        if _is_parsing_error(e):
            print(f"[STRUCTURE VALIDATION] ⚠️ Primary model parsing error - switching to fallback")
            print(f"[STRUCTURE VALIDATION]   Error type: {type(e).__name__}")
            print(f"[STRUCTURE VALIDATION]   Error message: {str(e)[:200]}")
        else:
            print(f"[STRUCTURE VALIDATION] ⚠️ Primary model failed after retries - switching to fallback")
            print(f"[STRUCTURE VALIDATION]   Error type: {type(e).__name__}")
            print(f"[STRUCTURE VALIDATION]   Error message: {str(e)[:200]}")
        
        # Fallback model settings
        fallback_model_settings = {
            "temperature": 0.1,
        }
        if fallback_model == "gpt-oss-120b":
            fallback_model_settings["max_completion_tokens"] = 2000
            fallback_model_settings["reasoning_effort"] = "medium"
            print(f"[STRUCTURE VALIDATION]   Fallback settings: Cerebras (reasoning_effort=medium, max_completion_tokens=2000)")
        else:
            fallback_model_settings["max_tokens"] = 2000
            print(f"[STRUCTURE VALIDATION]   Fallback settings: {fallback_model} (temperature=0.1, max_tokens=2000)")
        
        # Enable thinking for Qwen fallback (Groq models)
        fallback_use_thinking = (fallback_provider == 'groq' and 'qwen' in fallback_model.lower())
        print(f"[STRUCTURE VALIDATION]   Fallback thinking enabled: {fallback_use_thinking}")
        print(f"[STRUCTURE VALIDATION] Calling fallback model: {fallback_model}...")
        
        result = await _run_agent_with_model(
            model_name=fallback_model,
            output_type=StructureValidationResult,
            system_prompt="You are a radiology report structure validator. Check for 3 critical issues: (1) redundancy - structures mentioned multiple times, (2) grouping - normal structures that should be combined, (3) impression - contains descriptive content that belongs in Findings. Be precise - only flag actual violations.",
            user_prompt=validation_prompt,
            api_key=fallback_api_key,
            use_thinking=fallback_use_thinking,
            model_settings=fallback_model_settings
        )
        
        validation_result: StructureValidationResult = result.output
        
        # Log thinking parts for debugging (if Qwen fallback with thinking)
        if fallback_use_thinking:
            print(f"[STRUCTURE VALIDATION] Logging thinking parts from Qwen fallback...")
            _log_thinking_parts(result, "Structure Validation - Qwen Fallback")
        
        print(f"[STRUCTURE VALIDATION] ✅ Fallback model succeeded")
    
    elapsed = time.time() - start_time
    violation_count = len(validation_result.violations)
    print(f"[STRUCTURE VALIDATION] Validation completed in {elapsed:.2f}s")
    print(f"[STRUCTURE VALIDATION]   Violations found: {violation_count}")
    print(f"[STRUCTURE VALIDATION]   Validation status: {'VALID' if validation_result.is_valid else 'INVALID'}")
    
    # Enhanced debugging: Log each violation in detail
    if violation_count > 0:
        print(f"\n[STRUCTURE VALIDATION] {'='*70}")
        print(f"[STRUCTURE VALIDATION] VIOLATIONS DETECTED ({violation_count} total)")
        print(f"[STRUCTURE VALIDATION] {'='*70}")
        for i, violation in enumerate(validation_result.violations, 1):
            print(f"[STRUCTURE VALIDATION] Violation {i}/{violation_count}:")
            print(f"[STRUCTURE VALIDATION]   Location: {violation.location}")
            print(f"[STRUCTURE VALIDATION]   Issue: {violation.issue}")
            fix_preview = violation.fix[:200] + "..." if len(violation.fix) > 200 else violation.fix
            print(f"[STRUCTURE VALIDATION]   Fix: {fix_preview}")
        print(f"[STRUCTURE VALIDATION] {'='*70}\n")
    else:
        print(f"[STRUCTURE VALIDATION] ✅ No violations found - report passes structure validation")
    
    return validation_result


@with_retry(max_retries=2, base_delay=1.5)
async def validate_zai_glm_linguistics(
    report_content: str,
    scan_type: str = "",
    description: str = "",
    clinical_history: str = ""
) -> str:
    """
    Validate and correct linguistic/anatomical errors in zai-glm-4.7 generated reports.
    Uses llama-3.3-70b-versatile to fix British English grammar, anatomical errors,
    and redundant qualifiers without altering clinical content.
    
    This function addresses specific issues from the zai-glm-4.7 model:
    - Anatomical errors (e.g., "liver demonstrates gallstones" → "gallbladder contains gallstones")
    - Redundant qualifiers (e.g., "Large 5cm stone" → "5 cm stone")
    - Translation artifacts from internal Chinese→English conversion
    
    Args:
        report_content: The generated report text from zai-glm-4.7
        scan_type: The scan type for context (optional)
        description: The report description for context (optional)
    
    Returns:
        Corrected report content (or original if validation fails)
    
    Raises:
        Exception: Re-raises exceptions after retries for graceful handling by caller
    """
    import os
    import time

    start_time = time.time()
    print(f"\n[LINGUISTIC VALIDATION] Starting linguistic validation")
    print(f"[LINGUISTIC VALIDATION]   Report length: {len(report_content)} chars")
    print(f"[LINGUISTIC VALIDATION]   Scan type: '{scan_type}'")
    
    # Get model and provider
    model_name = MODEL_CONFIG["ZAI_GLM_LINGUISTIC_VALIDATOR"]
    provider = _get_model_provider(model_name)
    api_key = _get_api_key_for_provider(provider)
    
    print(f"[LINGUISTIC VALIDATION]   Validation model: {model_name} ({provider})")
    
    # Build system prompt - focused and concise
    system_prompt = """You are a medical text editor specializing in British English medical writing. Fix ONLY linguistic and anatomical errors. Preserve all clinical content, findings, diagnoses, and measurements."""
    
    # Build user prompt - streamlined rules
    user_prompt = f"""Review this radiology report for LINGUISTIC and ANATOMICAL errors ONLY.

CORRECTION RULES:
1. Grammar: Fix verb agreement, tense, sentence structure

2. Anatomy: Correct organ/structure references
   Example: "liver demonstrates gallstones" → "gallbladder contains gallstones"

3. Redundant qualifiers:
   - Remove size qualifiers when a measurement is present: "Large 5 cm stone" → "5 cm stone"
   - Remove synonymous terminology where two terms in the same phrase describe the same pathological process, keeping the more specific or conventional clinical term: "degenerative osteoarthritis" → "osteoarthritis"; "ischaemic infarction" → "infarction"; "haemorrhagic bleed" → "haemorrhage"

4. British English: Use oesophagus, haemorrhage, oedema, paediatric, centre, litre

5. Organ-as-subject patterns: Replace "demonstrates/shows" with direct statements
   Example: "The liver shows metastases" → "Hepatic metastases"
   Example: "The lungs demonstrate nodules" → "Multiple pulmonary nodules"

6. Anatomical redundancy: Omit implied locations
   Example: "gallbladder contains calculi within its lumen" → "gallbladder contains calculi"

7. Subject repetition: Don't repeat organ name in same clause
   Example: "gallbladder wall thickening" → "wall thickening" (when gallbladder is subject)

8. Verbose prepositions: Use direct statements
   Example: "within the lumen of the gallbladder" → "gallbladder"

9. Compound clarity: Separate positive finding from 3+ negative findings
   Example: "calculi without A or B or C" → "Calculi. No A, B, or C."

10. Finding consolidation: Each anatomical structure must appear once only in FINDINGS. Scan across all sentences and paragraphs and merge all mentions into a single comprehensive statement, preserving all descriptors, measurements, and qualifiers.
    Prioritise: abnormality → severity → size/measurement → associated features → relevant negatives.
    For functional findings, preserve causal relationships within the merged statement.
    Example (structural): "Subscapularis tendon is thickened. There is fatty atrophy of the subscapularis muscle." → "Subscapularis tendon thickening with fatty atrophy of the muscle belly."
    Example (functional): "SAM is present." + "SAM causing dynamic LVOT obstruction." → "Systolic anterior motion with dynamic LVOT obstruction."
    This rule applies to FINDINGS only. Structures referenced again in IMPRESSION are expected and correct.

11. Passive voice tightening: Use active constructs where natural
    Example: "is present" → direct statement, "is seen" → eliminate
    Example: "Enhancement is present in" → "Enhancement involves"

12. Measurement redundancy: Don't repeat same measurement in different sections
    Example: "22mm hypertrophy" + later "maximum thickness 22mm" → Use once in most detailed context

13. Sequential negatives: Combine related negative findings
    Example: "No thrombus. No aneurysm. No wall thinning." → "No thrombus, aneurysm, or wall thinning."

14. IMPRESSION: Write a concise clinical synthesis, not a list of findings.
    - Remove symptom-explanatory phrases and recommendation qualifiers: "explains the...", "accounts for...", "due to the...", "for management of..."
    - Lead with the dominant diagnosis; group related pathologies by region or aetiology into single sentences
    - All findings requiring clinical action must appear; omit minor incidentals
    - Recommendations: action only — no restated findings, no reason clauses
    - Format: dominant diagnosis → grouped pathology → recommendation
    ❌ "Complex meniscus tear explains the mechanical symptoms. Orthopaedic referral recommended for management of the displaced meniscal tear."
    ✅ "Complex medial meniscus tear with displaced fragment. Orthopaedic referral recommended."

PROHIBITIONS:
Do NOT change: diagnoses, differentials, severity, measurements, findings, recommendations, sections, medical terminology (unless anatomically incorrect), or clinical meaning.
Do NOT remove signatures or other metadata from the original report.

OUTPUT:
Return ONLY the corrected report text with no commentary or metadata. Preserve spacing and structure.

Report:
{report_content}"""
    
    # Build model settings - low temperature for precise corrections
    model_settings = {
        "temperature": 0.3,  # Low temperature for precise, consistent corrections
        "max_completion_tokens": 6000,  # Sufficient for full radiology reports
    }
    
    print(f"[LINGUISTIC VALIDATION]   Model settings: temperature=0.3, max_completion_tokens=6000")
    print(f"[LINGUISTIC VALIDATION] Calling validation model...")
    
    # Call model for validation
    result = await _run_agent_with_model(
        model_name=model_name,
        output_type=str,  # Plain text output
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        use_thinking=False,  # No thinking needed for Cerebras models
        model_settings=model_settings
    )
    
    validated_content = str(result.output).strip()
    
    # Ensure we got valid output
    if not validated_content or len(validated_content) < 50:
        raise ValueError(f"Linguistic validation returned invalid output (length: {len(validated_content)})")
    
    elapsed = time.time() - start_time
    
    # Calculate changes
    original_length = len(report_content)
    validated_length = len(validated_content)
    length_diff = validated_length - original_length
    
    print(f"[LINGUISTIC VALIDATION] ✅ Validation completed in {elapsed:.2f}s")
    print(f"[LINGUISTIC VALIDATION]   Original length: {original_length} chars")
    print(f"[LINGUISTIC VALIDATION]   Validated length: {validated_length} chars")
    print(f"[LINGUISTIC VALIDATION]   Length change: {length_diff:+d} chars ({length_diff/original_length*100:+.1f}%)")
    
    # Detailed comparison logging (optional - can be made verbose with env var)
    if os.getenv("VERBOSE_LINGUISTIC_VALIDATION", "false").lower() == "true":
        print(f"\n[LINGUISTIC VALIDATION] {'='*70}")
        print(f"[LINGUISTIC VALIDATION] BEFORE:")
        print(f"[LINGUISTIC VALIDATION] {'='*70}")
        print(report_content[:500] + "..." if len(report_content) > 500 else report_content)
        print(f"\n[LINGUISTIC VALIDATION] {'='*70}")
        print(f"[LINGUISTIC VALIDATION] AFTER:")
        print(f"[LINGUISTIC VALIDATION] {'='*70}")
        print(validated_content[:500] + "..." if len(validated_content) > 500 else validated_content)
        print(f"[LINGUISTIC VALIDATION] {'='*70}\n")
    
    return validated_content


async def validate_template_linguistics(
    report_content: str,
    template_config: dict,
    user_inputs: dict,
    scan_type: str = ""
) -> str:
    """
    Validate and refine template-generated report language with section-specific style awareness.
    
    Progressive enhancement approach: Trust the validator to apply linguistic refinements
    while preserving all organizational and structural decisions made by the primary model.
    
    Args:
        report_content: The generated report text from zai-glm-4.7
        template_config: Full template configuration with section configs
        user_inputs: User inputs including FINDINGS for context
        scan_type: The scan type for context (optional)
    
    Returns:
        Linguistically refined report content (or original if validation fails)
    
    Raises:
        Exception: Re-raises exceptions for graceful handling by caller
    """
    import os
    import time
    
    start_time = time.time()
    print(f"\n[TEMPLATE LINGUISTIC VALIDATION] Starting validation")
    print(f"[TEMPLATE LINGUISTIC VALIDATION]   Report length: {len(report_content)} chars")
    print(f"[TEMPLATE LINGUISTIC VALIDATION]   Scan type: '{scan_type}'")
    
    # === EXTRACT SECTION CONFIGS ===
    sections = template_config.get('sections', [])
    
    # Get findings config
    findings_section = next((s for s in sections if s.get('name') == 'FINDINGS'), {})
    findings_advanced = findings_section.get('advanced', {})
    findings_custom = findings_advanced.get('instructions', '')
    findings_content_style = findings_section.get('content_style', 'normal_template')
    
    # Get impression config  
    impression_section = next((s for s in sections if s.get('name') == 'IMPRESSION'), {})
    impression_advanced = impression_section.get('advanced', {})
    impression_custom = impression_advanced.get('instructions', '')
    
    # Get template-wide custom instructions
    template_wide_custom = template_config.get('global_custom_instructions', '')
    
    print(f"[TEMPLATE LINGUISTIC VALIDATION]   Findings content style: {findings_content_style}")
    print(f"[TEMPLATE LINGUISTIC VALIDATION]   Findings custom instructions: {bool(findings_custom)}")
    print(f"[TEMPLATE LINGUISTIC VALIDATION]   Impression custom instructions: {bool(impression_custom)}")
    print(f"[TEMPLATE LINGUISTIC VALIDATION]   Template-wide instructions: {bool(template_wide_custom)}")
    
    # Get model and provider
    model_name = MODEL_CONFIG["ZAI_GLM_LINGUISTIC_VALIDATOR"]  # llama-3.3-70b-versatile
    provider = _get_model_provider(model_name)
    api_key = _get_api_key_for_provider(provider)
    
    print(f"[TEMPLATE LINGUISTIC VALIDATION]   Validation model: {model_name} ({provider})")
    
    # === BUILD VALIDATOR PROMPT ===
    
    system_prompt = """You are an expert NHS medical editor specializing in British medical reporting.
Refine report language and phrasing while preserving all structural and organizational decisions."""
    
    # Get findings input for context (truncate if very long)
    findings_input = user_inputs.get('FINDINGS', '')
    findings_context = findings_input[:500] + "..." if len(findings_input) > 500 else findings_input
    
    # Build section-specific style blocks - pass content_style for structured_template handling
    findings_style_block = _build_findings_style_block(findings_advanced, findings_custom, findings_content_style)
    impression_style_block = _build_impression_style_block(impression_advanced, impression_custom)
    template_wide_block = _build_template_wide_block(template_wide_custom)
    
    # Extract style configurations for both sections
    findings_style = findings_advanced.get('writing_style', 'prose')
    impression_verbosity = impression_advanced.get('verbosity_style', 'prose')
    # Backward compatibility: map old values
    if impression_verbosity == 'standard':
        impression_verbosity = 'prose'
    elif impression_verbosity == 'detailed':
        impression_verbosity = 'prose'
    
    # Build neutral role section (applies to all styles)
    role_section = """=== YOUR ROLE ===
You are a linguistic validator for NHS radiology reports.

Your task: Apply section-specific style refinements to the report below.

PRESERVE (do not change):
- All clinical content, diagnoses, measurements
- Report structure and section organization
- Finding groupings and order
- Any existing line breaks or formatting

REFINE (per section-specific guidance below):
- Language clarity and readability
- British English compliance
- Grammar and phrasing per section style requirements

CRITICAL PRINCIPLE:
Each section has INDEPENDENT style requirements specified below.
Apply each section's guidance ONLY to that section.
- FINDINGS section → Apply FINDINGS style guidance
- IMPRESSION section → Apply IMPRESSION style guidance
- Do NOT carry style from one section to another."""
    
    # Build simplified NHS style rules (applies to all styles)
    nhs_rules = """=== CORE NHS STYLE RULES (ALL SECTIONS) ===

**British English**:
- Spelling: oesophagus, haemorrhage, oedema, paediatric, centre, litre
- Measurements: Space between number and unit ("5 cm" not "5cm")

**Anti-Hallucination** (CRITICAL):
⚠️ NEVER add, invent, estimate, or extrapolate:
- Measurements not in original input
- Morphological descriptors not in original input
- Clinical findings not in original input

**Anatomical Accuracy**:
- Verify correct anatomical terminology
- Fix organ/structure misattributions"""
    
    user_prompt = f"""Review this radiology report for linguistic refinement to NHS standards.

{role_section}

=== CONTEXT ===
**Scan Type**: {scan_type}

**Original Findings Input** (for descriptor verification):
{findings_context}

=== SECTION-SPECIFIC STYLE REQUIREMENTS ===

{findings_style_block}

{impression_style_block}

{template_wide_block}

{nhs_rules}

=== OUTPUT ===
Return ONLY the linguistically refined report. No commentary, no metadata.
Preserve all spacing, line breaks, and structural formatting exactly.

=== REPORT TO REFINE ===

{report_content}"""
    
    # Build model settings
    model_settings = {
        "temperature": 0.3,  # Low temperature for consistent refinement
        "max_completion_tokens": 6000,  # Sufficient for full reports
    }
    
    print(f"[TEMPLATE LINGUISTIC VALIDATION]   Model settings: temperature=0.3, max_completion_tokens=6000")
    print(f"[TEMPLATE LINGUISTIC VALIDATION] Calling validation model...")
    
    # Call model for validation
    result = await _run_agent_with_model(
        model_name=model_name,
        output_type=str,  # Plain text output
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        use_thinking=False,  # No thinking needed
        model_settings=model_settings
    )
    
    validated_content = str(result.output).strip()
    
    # Ensure we got valid output
    if not validated_content or len(validated_content) < 50:
        raise ValueError(f"Template linguistic validation returned invalid output (length: {len(validated_content)})")
    
    elapsed = time.time() - start_time
    
    # Calculate changes
    original_length = len(report_content)
    validated_length = len(validated_content)
    length_diff = validated_length - original_length
    
    print(f"[TEMPLATE LINGUISTIC VALIDATION] ✅ Validation completed in {elapsed:.2f}s")
    print(f"[TEMPLATE LINGUISTIC VALIDATION]   Original length: {original_length} chars")
    print(f"[TEMPLATE LINGUISTIC VALIDATION]   Validated length: {validated_length} chars")
    print(f"[TEMPLATE LINGUISTIC VALIDATION]   Length change: {length_diff:+d} chars ({length_diff/original_length*100:+.1f}%)")
    
    # Detailed comparison logging (optional - controlled by env var)
    if os.getenv("VERBOSE_LINGUISTIC_VALIDATION", "false").lower() == "true":
        print(f"\n[TEMPLATE LINGUISTIC VALIDATION] {'='*70}")
        print(f"[TEMPLATE LINGUISTIC VALIDATION] BEFORE:")
        print(f"[TEMPLATE LINGUISTIC VALIDATION] {'='*70}")
        print(report_content[:500] + "..." if len(report_content) > 500 else report_content)
        print(f"\n[TEMPLATE LINGUISTIC VALIDATION] {'='*70}")
        print(f"[TEMPLATE LINGUISTIC VALIDATION] AFTER:")
        print(f"[TEMPLATE LINGUISTIC VALIDATION] {'='*70}")
        print(validated_content[:500] + "..." if len(validated_content) > 500 else validated_content)
        print(f"[TEMPLATE LINGUISTIC VALIDATION] {'='*70}\n")
    
    return validated_content


def _build_findings_style_block(advanced_config: dict, custom_instructions: str, content_style: str = None) -> str:
    """Build Findings section style requirements with conditional guidance."""
    
    # For structured templates, style settings are disabled - apply minimal validation only
    if content_style == 'structured_template':
        findings_format = advanced_config.get('format', 'prose')
        style_guidance = """
**FINDINGS SECTION** - Mode: STRUCTURED TEMPLATE (Minimal Validation)

PRESERVE EXACT STRUCTURE:
- Maintain all template formatting, headers, and structure exactly as generated
- Preserve any user detail augmentations integrated into template sections
- Do NOT reorganize or restructure content
- Preserve all measurement placeholders, variables, and alternatives as filled

**PLACEHOLDER PRESERVATION (CRITICAL)**:
- Unfilled xxx measurements: Must remain as "xxx" exactly
- Unfilled {VAR} variables: Must remain as "{VAR}" exactly
- Do NOT replace with explanatory text like "not specified", "not provided", "not measured"
- Do NOT remove or alter unfilled placeholders
- Post-processing will detect and handle unfilled placeholders
- Examples:
  ✓ KEEP: "diameter xxx mm" (if xxx unfilled)
  ✓ KEEP: "LVEF {LVEF}%" (if {LVEF} unfilled)
  ✗ NEVER: "diameter xxx mm" → "diameter not specified"
  ✗ NEVER: "{LVEF}%" → "LVEF not provided"

ONLY refine for quality:
- British English spelling (tumour, haemorrhage, oesophagus, centre, litre, calibre)
- Medical terminology accuracy (fix anatomical errors only)
- Grammatical correctness (fix subject-verb agreement, tense errors)
- Grammatical flow of augmented clinical details
- Measurement formatting (ensure consistent units and spacing)

DO NOT apply:
- Writing style transformations (concise/prose)
- Sentence structure modifications
- Phrasing improvements beyond grammatical fixes
- Removal of augmented user details
- Replacement of unfilled placeholders with explanatory text

CRITICAL: Template structure is sacred. User detail augmentations are sacred. Unfilled placeholders are sacred. Only fix linguistic and anatomical errors."""
        
        block = f"""{style_guidance}

**Format**: {findings_format}
{_get_format_guidance(findings_format, advanced_config.get('organization', 'clinical_priority'))}
"""
        if custom_instructions and custom_instructions.strip():
            block += f"""
**Custom Instructions** (if any):
{custom_instructions}
(Note: Structured templates preserve exact structure - instructions guide content only, not structure)
"""
        return block
    
    # Check template fidelity flag first (only present for normal/guided templates)
    # Default True to match primary model default — preserves template voice unless explicitly overridden
    follow_template_style = advanced_config.get('follow_template_style', True)
    
    findings_format = advanced_config.get('format', 'prose')
    
    if follow_template_style:
        # Template fidelity mode - principle-based validation
        style_guidance = """
Maintain template's linguistic character:
- Observe the existing register (formal complete prose vs. concise telegraphic vs. mixed)
- Match sentence structure patterns present in the template
- Keep similar verbosity and descriptor density

Quality refinements only:
- British English spelling (tumour, haemorrhage, oesophagus)
- Medical terminology accuracy and consistency
- Grammatical correctness (subject-verb agreement, tense)
- Measurement formatting (consistent units, spacing: "4cm" or "4 cm" consistently)

Avoid transforming the style:
- Don't convert complete sentences to telegraphic phrasing or vice versa
- Don't arbitrarily add/remove articles, linking verbs, or descriptors
- Don't change the formality register established by the template

Principle: You're ensuring quality and consistency, not imposing a different style. Validate naturalistically within the template's established voice."""
        
        block = f"""**FINDINGS SECTION** - Mode: TEMPLATE FIDELITY

{style_guidance}

**Format**: {findings_format}
{_get_format_guidance(findings_format, advanced_config.get('organization', 'clinical_priority'))}
"""
        if custom_instructions and custom_instructions.strip():
            block += f"""
**Custom Linguistic Instructions**:
{custom_instructions}
(Apply to language/phrasing only - preserve organizational decisions)
"""
        return block
    
    # EXISTING CODE continues for when follow_template_style is False
    writing_style = advanced_config.get('writing_style', 'prose')
    
    # Style-specific linguistic guidance
    if writing_style == 'concise':
        style_guidance = """
=== VALIDATOR: CONCISE STYLE ===

Apply adaptive telegraphic compression based on finding complexity.

COMPLEXITY RULE:
- Simple findings (1-2 attributes): Strip all verbs. Pure noun-adjective.
- Grouped structures (multiple organs/vessels): Keep linking verbs for readability.
- Complex findings (3+ attributes): Keep minimal "shows" for readability.
- Multiple normal attributes: Lead with "Normal [list]" not "attribute normal, attribute normal"

CRITICAL TRANSFORMATIONS FOR VALIDATOR:

When you see these patterns in the draft report, TRANSFORM them:

PATTERN 1 - Normal attributes with wrong word order:
Input: "Small bowel wall thickness and enhancement pattern normal"
Output: "Normal small bowel wall thickness and enhancement pattern"
Rule: If you see "[structure] [attributes] normal" → Move "Normal" to front

PATTERN 2 - Repetitive normal statements:
Input: "Small bowel wall thickness normal. Enhancement pattern normal."
Output: "Normal small bowel wall thickness and enhancement pattern"
Rule: Consolidate multiple normal attributes with "and"

PATTERN 3 - Multiple negatives:
Input: "No thrombosis. No portal hypertension. No free fluid."
Output: "No thrombosis, portal hypertension, or free fluid"
Rule: Chain negatives with commas, single "No"

PATTERN 4 - Wrong word order in normal findings:
Input: "Wall thickness normal and enhancement normal"
Output: "Normal wall thickness and enhancement"
Rule: "Normal" always leads when describing normal attributes

TRANSFORMATION PATTERNS:

Simple → Telegraphic:
"The abdominal aorta is of normal calibre with smooth contours" → "Abdominal aorta normal calibre, smooth contours"
"The portal vein is patent" → "Portal vein patent"
"Free fluid is present in the pelvis" → "Free fluid in pelvis"
"The liver appears normal" → "Liver normal"
"No free air is identified" → "No free air"

Grouped structures → Keep linking verb:
"Portal vein, superior mesenteric vein patent, normal calibre" → "Portal vein and superior mesenteric vein are patent with normal calibre"
"Liver, spleen, kidneys normal" → "Liver, spleen, and kidneys are normal"

Multiple normal attributes → Lead with "Normal":
"Small bowel wall thickness normal, enhancement pattern normal" → "Normal small bowel wall thickness and enhancement"
"Small bowel wall thickness and enhancement pattern normal" → "Normal small bowel wall thickness and enhancement pattern"
"Liver enhancement normal, attenuation normal" → "Normal liver enhancement and attenuation"
"Wall thickness normal and enhancement normal" → "Normal wall thickness and enhancement"

Complex → Minimal verb:
"Multiple small bowel loops are thickened and demonstrate reduced enhancement" → "Small bowel loops show thickening and reduced enhancement"
"The mass demonstrates irregular margins, measures 4cm, and contains calcification" → "Mass shows irregular margins (4cm) with calcification"

REMOVE AGGRESSIVELY:
- Articles: "the", "a", "an"
- Linking verbs for single structures: "is", "are", "was", "were", "appears"
  ✗ "Portal vein is patent" → ✓ "Portal vein patent"
  ✓ EXCEPTION: Keep "are/is" for grouped/compound subjects (see below)
- Verbose phrases: "is present", "is identified", "is noted", "demonstrates" (for simple findings)
- Qualifiers: "approximately", "measuring"
- Padding: "There is", "evidence of", "with no signs of" → "no"

MEASUREMENTS:
- Use parentheses: "stenosis (85%)" not "stenosis of 85%"
- Direct: "4cm mass" not "mass measuring 4cm"

NEGATIVES:
- Single negative: "No free fluid"
- Multiple negatives: Chain with single "No": "No thrombosis, portal hypertension, or free fluid"
- NOT repetitive: "No thrombosis, no portal hypertension, no free fluid"
- Never: "Absent [finding]" or "[finding] absent"

KEEP FOR CLARITY:
- "shows" for complex findings (3+ attributes)
- Linking verbs (are/is) ONLY for grouped/compound subjects:
  ✓ "Portal vein and superior mesenteric vein are patent" (compound subject needs scaffolding)
  ✗ "Portal vein is patent" (single subject - omit)
- Essential connectors: "with", "at", "in", "from"
- All measurements and anatomical locations
- Commas to separate attributes
- "and" to connect items in lists

FORBIDDEN TRANSFORMATIONS:
- Do NOT add measurements not in original
- Do NOT change anatomical specificity
- Do NOT create comma soup (keep "shows" for complex findings)

Apply uniformly to ALL findings (abnormal AND normal):
- Consistent telegraphic compression throughout
- Decision: simple = no verb, complex = "shows"

ONLY refine:
- British English spelling
- Measurement formatting
- Anatomical terminology errors

CRITICAL: NEVER fabricate measurements or details not in original input"""
    
    else:  # prose (formerly standard)
        style_guidance = """
=== VALIDATOR: PROSE STYLE (Balanced NHS Prose) ===

Transform verbose/repetitive prose to natural consultant dictation style.

GOAL: Natural medical prose - not telegraphic, not overly formal. Aim for how a consultant dictates, not how templates read.

CRITICAL TRANSFORMATIONS:

PATTERN 1 - Remove padding verbs (NEVER acceptable):
"A mass is identified in the right upper lobe" → "Right upper lobe mass" or "Mass in right upper lobe"
"Enlarged lymph nodes are seen in the mediastinum" → "Enlarged mediastinal lymph nodes"
"A small pleural effusion is noted" → "Small pleural effusion" or "Small pleural effusion present"
"No focal lesion is identified" → "No focal lesion"
Rule: "is noted", "are seen", "is identified", "is observed" → ALWAYS remove

PATTERN 2 - Simplify negative findings:
"with no evidence of consolidation or pleural effusion" → "no consolidation or effusion"
"without evidence of pneumoperitoneum" → "no pneumoperitoneum"
"No evidence of free intra-abdominal air is identified" → "No free intra-abdominal air"
"with no signs of obstruction" → "no obstruction"
Rule: "no evidence of" → "no" or "without"

PATTERN 3 - Remove excessive articles and verbose phrasing:
"The liver is of normal size" → "Liver normal size" or "The liver is normal size"
"has a normal calibre" → "has normal calibre" or "normal calibre"
"with a homogeneous enhancement pattern" → "with homogeneous enhancement"
Rule: Strip "of" and "a" where verbose, but keep natural articles when introducing findings

PATTERN 4 - Vary sentence openings (avoid monotony):
If seeing 3+ consecutive sentences starting with "The [structure] demonstrates/is/appears":
"The liver demonstrates diffuse steatosis. The spleen demonstrates..." → "Liver shows diffuse steatosis. Spleen normal."
Mix complete and efficient sentences for natural rhythm
Rule: Vary structure - don't let every sentence start identically

PATTERN 5 - Replace verbose template language:
"The liver is of normal size and demonstrates homogeneous enhancement with no focal lesions identified" → "Liver normal size with homogeneous enhancement, no focal lesions"
"The small bowel loops demonstrate normal wall thickness and enhancement pattern" → "Small bowel loops show normal wall thickness and enhancement"
"There is a mass in the right upper lobe measuring 4 cm" → "Right upper lobe mass measuring 4 cm"
Rule: Natural phrasing, not template fill-in-the-blank

PATTERN 6 - Remove redundant qualifiers:
"characteristic focal narrowing" → "focal narrowing"
"approximately" → keep only if genuinely uncertain
"significant stenosis" → "stenosis" (significance implied by reporting)

VERB USAGE HIERARCHY:
1. "shows" - preferred, clear and direct
2. "demonstrates" - acceptable occasionally, not repetitively  
3. "is present", "are patent" - acceptable when natural
4. "is noted", "are seen", "is identified" - FORBIDDEN, always remove

ACCEPTABLE FLEXIBILITY:
- "demonstrates" OK occasionally (not 5 times in a row)
- Passive voice OK when natural ("is present", "are patent")
- Articles OK when introducing findings or needed for clarity
- Complete sentences preferred, but efficient phrasing acceptable for simple findings

SENTENCE RHYTHM:
- Mix complete and concise sentences
- Vary opening patterns
- Natural flow, not robotic template reading
- Professional NHS register

Apply uniformly to ALL findings (abnormal AND normal):
- Maintain consistent balanced prose throughout
- Remove padding verbs and verbose constructions
- Vary structure to avoid monotony
- Natural consultant dictation style

CRITICAL: Aim for natural consultant dictation, not template reading"""
    
    # Extract organization for paragraph guidance
    organization = advanced_config.get('organization', 'clinical_priority')
    
    block = f"""**FINDINGS SECTION** - Linguistic Style: {writing_style.upper()}

{style_guidance}

**Format**: {findings_format}
{_get_format_guidance(findings_format, organization)}
"""
    
    if custom_instructions and custom_instructions.strip():
        block += f"""
**Custom Linguistic Instructions**:
{custom_instructions}
(Apply to language/phrasing only - preserve organizational decisions)
"""
    
    return block


def _build_impression_style_block(advanced_config: dict, custom_instructions: str) -> str:
    """Build Impression section style requirements with conditional guidance."""
    
    verbosity = advanced_config.get('verbosity_style', 'prose')
    
    # Backward compatibility: map old values
    if verbosity == 'standard':
        verbosity = 'prose'
    elif verbosity == 'detailed':
        verbosity = 'prose'
    
    impression_format = advanced_config.get('format') or advanced_config.get('impression_format', 'prose')
    
    # Verbosity-specific linguistic guidance
    if verbosity == 'brief':
        verbosity_guidance = """
⚠️ THIS SECTION USES BRIEF LANGUAGE - Independent of findings style

Terse, direct phrasing:
- Strip to essential wording
- Minimal elaboration
- Example: "Acute appendicitis. No perforation or abscess."

Transform verbose phrasing:
✗ "Acute appendicitis is present without evidence of perforation"
✓ "Acute appendicitis. No perforation."

SCOPE: Refine existing impression text to be more terse
DO NOT: Remove/add content, apply findings phrasing style here"""
    
    else:  # prose (formerly standard)
        verbosity_guidance = """
Natural radiology summary prose:
- Balanced clinical register
- Clear, readable statements
- Mix of complete and fragment constructions typical in radiology
- Example: "Small bowel obstruction at the level of the mid ileum. 
  Probable adhesive aetiology. No signs of ischaemia."

SCOPE: Refine grammar and phrasing for natural readability
DO NOT: Add/remove content"""
    
    block = f"""**IMPRESSION SECTION** - Linguistic Verbosity: {verbosity.upper()}

{verbosity_guidance}

**Format**: {impression_format}
{_get_format_guidance(impression_format)}
"""
    
    if custom_instructions and custom_instructions.strip():
        block += f"""
**Custom Linguistic Instructions**:
{custom_instructions}
(Apply to language/phrasing only - preserve organizational decisions)
"""
    
    return block


def _build_template_wide_block(custom_instructions: str) -> str:
    """Build template-wide instructions block for validator"""
    
    if not custom_instructions or not custom_instructions.strip():
        return """**TEMPLATE-WIDE INSTRUCTIONS**: None"""
    
    return f"""**TEMPLATE-WIDE INSTRUCTIONS** (apply across all sections):

{custom_instructions}

Note: These apply to the entire report. Focus on LINGUISTIC application - preserve all structural/organizational aspects already implemented by the primary model.
"""


def _get_format_guidance(format_type: str, organization: str = 'clinical_priority') -> str:
    """Get format-specific guidance for validator. Supports frontend options: prose, bullets, numbered."""
    prose_guidance = """   Style: Flowing prose paragraphs with natural breaks
   - ENSURE paragraph breaks between major anatomical regions or finding types
   - ENSURE grouping of related findings/entities within paragraphs
   - Add paragraph breaks where missing, without reorganizing content
   - Refine sentence quality while maintaining proper paragraph structure"""

    if format_type == 'prose':
        return prose_guidance

    guides = {
        'bullets': """   Style: Bullet points (•)
   - PRESERVE existing bullet structure (already generated)
   - Refine wording within each bullet
""",
        'numbered': """   Style: Numbered list (1., 2., 3.)
   - PRESERVE existing numbered structure (already generated)
   - Refine wording within each item
""",
    }
    return guides.get(format_type, prose_guidance)


# Removed _get_comparison_guidance - comparisons now handled within verbosity_style principles


# ============================================================================
# Report Audit / QA Analysis
# ============================================================================

def _audit_error_raw_preview(exc: BaseException, limit: int = 500) -> str:
    """Best-effort extract of model/validation payload for audit primary failures."""
    try:
        from pydantic import ValidationError
        from pydantic_ai.exceptions import ModelHTTPError

        if isinstance(exc, ValidationError):
            return exc.json()[:limit]
        if isinstance(exc, ModelHTTPError):
            body = getattr(exc, "body", None)
            if body is not None:
                return (body if isinstance(body, str) else repr(body))[:limit]
    except Exception:
        pass
    return str(exc)[:limit]


def reconcile_audit_status(audit_out: AuditResult) -> AuditResult:
    """
    Backend safety net: enforce worst-of rules that the judge should follow but may drift from.
    Mutates criterion rows and overall_status in place for simplicity; caller then model_dump()s.
    """
    STATUS_RANK = {"pass": 0, "warning": 1, "flag": 2}
    RANK_STATUS = {0: "pass", 1: "warning", 2: "flag"}

    for criterion in audit_out.criteria:
        if criterion.criterion != "diagnostic_fidelity":
            continue
        a_match = re.search(
            r"\(a\)\s*Certainty:\s*(PASS|WARNING|FLAG)",
            criterion.rationale or "",
            re.IGNORECASE,
        )
        b_match = re.search(
            r"\(b\)\s*Consistency:\s*(PASS|WARNING|FLAG)",
            criterion.rationale or "",
            re.IGNORECASE,
        )
        if a_match and b_match:
            a_rank = STATUS_RANK.get(a_match.group(1).lower(), 0)
            b_rank = STATUS_RANK.get(b_match.group(1).lower(), 0)
            correct_status = RANK_STATUS[max(a_rank, b_rank)]
            if criterion.status != correct_status:
                print(
                    f"  └─ [RECONCILE] diagnostic_fidelity status "
                    f"corrected: {criterion.status} → {correct_status}"
                )
                criterion.status = correct_status  # type: ignore[misc]

    worst_rank = max(STATUS_RANK.get(c.status, 0) for c in audit_out.criteria)
    correct_overall = RANK_STATUS[worst_rank]
    if audit_out.overall_status != correct_overall:
        print(
            f"  └─ [RECONCILE] overall_status corrected: "
            f"{audit_out.overall_status} → {correct_overall}"
        )
        audit_out.overall_status = correct_overall  # type: ignore[misc]

    return audit_out


async def audit_report(  # DEPRECATED — replaced by run_audit_phase1 + run_audit_phase2
    report_content: str,
    scan_type: str,
    clinical_history: str,
    api_key: str = None,
    applicable_guidelines: Optional[List[dict]] = None,
    prefetched_knowledge=None,  # Optional[PrefetchOutput] — pre-built KB from parallel prefetch
    db=None,
) -> dict:
    """
    Audit a radiology report against 6 quality criteria using Zai-GLM-4.7 (primary) with Qwen 32B fallback.
    
    Args:
        report_content: The report text to audit
        scan_type: Type of scan (e.g., 'CT head non-contrast')
        clinical_history: Clinical history/indication for the scan
        api_key: Optional API key (if not provided, uses provider-specific key from env)
        applicable_guidelines: Optional list of dicts (ApplicableGuideline-shaped) for cache fetch + audit context
        prefetched_knowledge: Optional PrefetchOutput from the parallel prefetch pipeline.
            When provided, its knowledge_base is injected as a [GUIDELINE CONTEXT] block and
            urgency_signals are injected before the FLAGGING PHILOSOPHY section.
        db: SQLAlchemy Session or None; if None, guideline context is skipped
        
    Returns:
        Dictionary with overall_status, criteria list (6 items), summary, model_used, and
        prefetch_used (True when audit was seeded by prefetched_knowledge).
    """
    start_time = time.time()
    primary_model = MODEL_CONFIG["AUDIT_ANALYZER"]
    fallback_model = MODEL_CONFIG["AUDIT_ANALYZER_FALLBACK"]
    provider = _get_model_provider(primary_model)
    primary_api_key = _get_api_key_for_provider(provider, api_key)
    
    print(f"\n{'='*60}")
    print(f"audit_report: Auditing report with {primary_model} (primary), {fallback_model} (fallback)...")
    print(f"  └─ Scan type     : {scan_type or 'Not specified'}")
    print(f"  └─ Clinical hx   : {clinical_history[:120] if clinical_history else 'Not provided'}")
    print(f"  └─ Report length : {len(report_content)} chars")
    print(f"  └─ Report preview: {report_content[:200].replace(chr(10), ' ')!r}")
    print(f"{'='*60}")
    
    # ── Build prefetch KB context block ───────────────────────────────────────
    _prefetch_kb_block = ""
    _urgency_block = ""
    _prefetch_used = False
    if prefetched_knowledge is not None:
        _prefetch_used = True
        # Urgency signals — injected as a prior before FLAGGING PHILOSOPHY
        if prefetched_knowledge.urgency_signals:
            _urgency_block = (
                "\n[PREFETCH URGENCY CONTEXT — pre-computed from scan inputs]\n"
                + "\n".join(f"• {s}" for s in prefetched_knowledge.urgency_signals)
                + "\nUse these as a prior when evaluating clinical_flagging severity. "
                "They do not override your independent assessment.\n"
            )
        # KB evidence — concatenate all branches into a GUIDELINE CONTEXT supplement
        kb_parts: List[str] = []
        for branch, items in prefetched_knowledge.knowledge_base.items():
            for item in items:
                if item.content and len(item.content) > 100:
                    header = f"[{item.title or item.domain} — {branch}]"
                    snippet = item.content[:1200]
                    kb_parts.append(f"{header}\n{snippet}")
        if kb_parts:
            _prefetch_kb_block = (
                "\n\n[PREFETCH GUIDELINE CONTEXT — pre-fetched from authoritative sources]\n"
                "Use this knowledge block to ground recommendations and classification criteria. "
                "Treat it as supplementary evidence that precedes any criteria appended below.\n\n"
                + "\n\n".join(kb_parts[:8])  # cap at 8 items to stay within context budget
            )
        print(
            f"[GUIDELINE_PIPELINE] audit_report: prefetch KB injected — "
            f"urgency_signals={len(prefetched_knowledge.urgency_signals)} "
            f"kb_items={sum(len(v) for v in prefetched_knowledge.knowledge_base.values())}"
        )
    # ──────────────────────────────────────────────────────────────────────────

    system_prompt = (f"""You are a senior radiologist and clinical radiology QA specialist practising in the UK.
Your task is to audit a radiology report against six specific quality criteria.

LANGUAGE (NON-NEGOTIABLE):
CRITICAL: You MUST write every user-visible string in English only — UK British English spelling and terminology (e.g. oesophagus, haemorrhage, tumour). This includes rationale, recommendation, summary, flag detail text, and every suggested_banners.rationale field. Do not use Chinese, other languages, or mixed-language output under any circumstances. Quoted verbatim spans from the report (highlighted_spans) must stay exactly as in the source.
"""
    + _urgency_block
    + """
FLAGGING PHILOSOPHY:
- Apply the criterion definitions as written. If a criterion is met, it is met — do not invent issues.
- Do NOT flag stylistic preferences, formatting choices, or defensible variations in phrasing.
- Do NOT flag appropriate deferrals of *clinical management* to the referring clinician (e.g., "clinical correlation recommended", "discuss with clinician team").
- DO flag incomplete or vague *radiological* recommendations — if a radiologist recommends further imaging, that recommendation must include modality and appropriate urgency. Vague radiological recommendations cause clinical harm.
- DO flag when the stated clinical question is not addressed, even partially.
- FINDINGS constrain the Impression for factual consistency. When evaluating any criterion, treat explicit FINDINGS statements as the ground truth against which Impression claims are validated — not the reverse. A confident, fluent Impression does not override an explicit FINDINGS negation of the same clinical entity.

For highlighted_spans, copy verbatim substrings from the report exactly as they appear; these will be used to locate and highlight the text inline.
You must evaluate all six criteria and return them in this exact order: anatomical_accuracy, clinical_relevance, recommendations, clinical_flagging, report_completeness, diagnostic_fidelity.
Note: diagnostic_fidelity has access to GUIDELINE CONTEXT below — cross-check staging assignments against synthesis thresholds.

OUTPUT REQUIREMENTS:
- All prose you generate must be British English only (see LANGUAGE above)
- Return exactly 6 criteria evaluations in the specified order
- For each criterion with issues, include highlighted_spans with verbatim text from the report
- Use status "pass" when no issues, "flag" for significant issues requiring attention, "warning" for minor concerns
- For clinical_flagging criterion, always populate flags_identified with all 3 sub-flag types
- For the diagnostic_fidelity criterion, the rationale field must always contain both sub-dimension lines in this exact format, regardless of status:
    (a) Certainty: [PASS | WARNING | FLAG] — [brief explanation]
    (b) Consistency: [PASS | WARNING | FLAG] — [brief explanation]
  Do not collapse into a single sentence. Both lines are required even when both dimensions pass.
- For diagnostic_fidelity (b) Consistency, FINDINGS are the source of truth. If FINDINGS negate a diagnosis and the Impression asserts it, (b) must be FLAG regardless of how clinically plausible the Impression reads in isolation.
- For diagnostic_fidelity, the criterion-level status must equal the worse of the two sub-dimension statuses: flag > warning > pass. If (b) Consistency is WARNING, status must be "warning". If either sub-dimension is FLAG, status must be "flag". Returning "pass" when either sub-dimension is warning or flag is a validation error.
- overall_status must equal the worst status across all six criteria. If any criterion is "flag", overall_status must be "flag". If no criterion is "flag" but any is "warning", overall_status must be "warning". Returning "pass" when any criterion is flag or warning is a validation error.
- If a criterion cannot be meaningfully evaluated (e.g., no prior study referenced so comparative analysis is not applicable), assign "pass" with a brief note

STRUCTURED OUTPUT (API — MANDATORY):
- Return one structured object with exactly these top-level keys: overall_status, criteria, summary.
- criteria MUST be a JSON array of exactly 6 objects. It MUST NOT be a string (do not double-encode or stringify the array).
- summary MUST be a non-empty British English string (one to three sentences) synthesising the outcome for the radiologist.
- EVERY element of criteria MUST include a top-level rationale string. This includes clinical_flagging: populate flags_identified and suggested_banners in addition to rationale, never as a substitute for rationale. Omitting rationale on any criterion causes validation failure.

ONE-CLICK FIX FIELDS (populate only on flag or warning, never on pass):
- suggested_replacement: Populate for anatomical_accuracy and recommendations flags ONLY when a
  verbatim drop-in substitution exists for highlighted_spans[0]. Must read naturally at the same
  position in the sentence where the original appeared — no new sentences, line breaks, or headers.
  Leave null if the correct fix is structural (requires adding content rather than replacing a span).
- **Recommendations + suggested_replacement:** When status is flag or warning and the issue is vague or
  non-specific **recommendation wording** in the report (missing modality, interval, or named pathway)
  and a **contiguous verbatim phrase** in the report captures that vagueness, set **highlighted_spans[0]**
  to that **exact** phrase and **suggested_replacement** to a **single** report-ready clause that
  substitutes at that position, **grounded in GUIDELINE CONTEXT / criterion_line** (e.g. replace
  "respiratory referral advised" with "LDCT chest at 3 months per Lung-RADS 4A" when the audit text
  supports it). Populate both together whenever a clean span swap is feasible — do not leave
  suggested_replacement null merely because criterion_line already states the rule; the replacement
  is the actionable drop-in text. If there is no single substring to replace (e.g. recommendation
  wholly absent), leave suggested_replacement null.
- suggested_sentence: Populate for report_completeness flags ONLY when a finding is entirely absent
  and requires a new sentence to address it. Must be a complete, report-ready sentence in British
  English. Leave null if the problem is a span substitution rather than a missing sentence.
- criterion_line: Populate for **recommendations** flags only (flag or warning). One sentence from
  GUIDELINE CONTEXT — the single most relevant specific rule this report failed to follow; immediately
  scannable for inline QA display. Example: "Lung-RADS 4A: solid nodule ≥8mm → LDCT at 3 months."
  Leave null if no GUIDELINE CONTEXT is appended to this audit, the failure is structural rather than
  criterion-specific, or status is pass.
- **Recommendations criterion — rationale vs criterion_line:** When `criterion_line` is non-null, the
  `rationale` must describe **only** what is wrong with the report's recommendation or impression
  wording (vague interval, missing modality, non-specific protocol language, etc.) — quote or paraphrase
  the problematic phrase where helpful. Do **not** open with or restate guideline classification,
  numerical thresholds, or the correct management pathway in `rationale`; that belongs **exclusively**
  in `criterion_line`. If `criterion_line` is null (no guideline context or structural failure), a
  normal brief rationale covering both gap and context is fine.
Do not attempt suggested_replacement for clinical_relevance, clinical_flagging, or diagnostic_fidelity
— the correct fix for those criteria is almost never a single span swap.

GUIDELINE CONTEXT (when appended below):
Structured classification or guideline criteria may appear after this block. If **multiple** systems could relate to the **same** finding, apply the framework whose **scope** matches **scan purpose** and **clinical question** (e.g. screening programme vs incidental finding on a general CT vs oncology staging or response). **Do not** cross-apply numerical thresholds or management rules between frameworks designed for different clinical contexts. Where **multiple** guideline frameworks appear in the appended GUIDELINE CONTEXT, use the **first** block as the primary reference for **recommendation grounding**; subsequent blocks are for **cross-reference** — note where they corroborate or differ from the primary framework. The injected criteria serve two purposes: (1) recommendation grounding — when a recommendations flag fires, derive the specific correction from the criteria (interval, action, urgency) rather than only identifying the gap; (2) classification reference — do not use criteria to adjudicate whether the assigned category is correct, as that requires image review and is the radiologist's call."""
    + _prefetch_kb_block
    )

    user_prompt = f"""REPORT TO AUDIT:
{report_content}

SCAN TYPE: {scan_type or 'Not specified'}
CLINICAL HISTORY: {clinical_history or 'Not provided'}

Evaluate this report against all 6 audit criteria:

1. ANATOMICAL_ACCURACY
   Assess right/left consistency and correct anatomical labelling.
   FLAG if: A bilateral structure (kidney, lung, adrenal gland, eye, breast) is mentioned without laterality in a context where the side is clinically material; OR a clear anatomical mislabel is present (e.g., a vascular structure named as a lymph node, a measurement assigned to the wrong organ).
   WARNING if: Minor ambiguity in laterality that is unlikely to affect clinical management.
   PASS if: Anatomical references are consistent and unambiguous, or any omission is clinically irrelevant.

2. CLINICAL_RELEVANCE
   Does the impression directly address the stated clinical question/indication?
   FLAG if: The impression fails to address the clinical indication — including when the scan type ordered does not adequately cover the anatomical region relevant to the clinical question (e.g., CT abdomen/pelvis ordered for chest pain where thoracic aortic pathology is not imaged or excluded).
   WARNING if: The indication is only partially addressed, with a clinically meaningful aspect omitted or deflected without explanation.
   PASS if: The impression meaningfully addresses the clinical indication given the scope of the scan performed.

3. RECOMMENDATIONS
   Given the findings described in the impression, assess whether appropriate referral and investigation pathways have been recommended with urgency commensurate with clinical severity.
   FLAG if: An actionable finding in the impression (significant pathology, new diagnosis, finding requiring further characterisation or specialist input) has no associated recommendation when a reasonable radiologist would provide one; OR the urgency is clearly mismatched with clinical severity — e.g., time-sensitive or life-threatening pathology with no urgency stated, or emergency-level findings with only routine follow-up language.
   WARNING if: A recommendation is present but the urgency level is ambiguous or likely under-stated relative to the clinical significance of the finding.
   PASS if: All actionable findings in the impression have appropriate next-step recommendations with urgency commensurate to the finding. Concise referral statements (e.g., "orthopaedic referral advised", "urgent neurosurgical referral") are adequate — do not flag for missing reason clauses or absence of modality detail in specialist referrals.
   When GUIDELINE CONTEXT is appended and status is flag or warning with a populated criterion_line: write rationale as the deficiency in the report only (vague or missing detail in the recommendation text); put thresholds, classification, and correct interval/modality solely in criterion_line — see OUTPUT REQUIREMENTS.

4. CLINICAL_FLAGGING
   Detect whether the report warrants a clinical communication banner that the user may append to the report.
   Important: banner severity must be determined by the clinical features described in FINDINGS — haemodynamic status, RV strain, imaging extent — not by the severity label used in the Impression. If the Impression uses a severity characterisation that is inconsistent with the FINDINGS, base the banner category on FINDINGS.
   Evaluate presence of three severity tiers (flags_identified — return all 3 evaluations):
   - critical: Life-threatening findings requiring immediate action as supported by FINDINGS (e.g., tension pneumothorax, aortic dissection, pulmonary embolism with haemodynamic compromise or shock when so described — do not assign critical from an Impression label alone if FINDINGS describe stability)
   - urgent: Findings needing same-day clinical attention (e.g. new DVT, bowel obstruction, suspected malignancy requiring urgent MDT/oncology referral)
   - significant: Important findings for clinical management that are not immediately time-critical but require documented clinician acknowledgement (e.g. interval change in known malignancy, new indeterminate lesion needing surveillance)
   Populate suggested_banners with 0–3 ranked options (most severe first) from these standard templates. Use the exact banner_text strings below. When no actionable flags are present, return suggested_banners: [].
   Standard banner templates (use verbatim):
   - critical: label "Critical — Immediate Action Required", banner_text "*****CRITICAL RADIOLOGICAL FINDING — REQUIRES IMMEDIATE CLINICIAN ACTION*****"
   - urgent: label "Urgent — Same-Day Attention", banner_text "*****URGENT RADIOLOGICAL FINDING — PLEASE REVIEW TODAY*****"
   - significant: label "Significant — Review with Referring Team", banner_text "*****CLINICALLY SIGNIFICANT FINDING — PLEASE REVIEW WITH REFERRING TEAM*****"
   For each suggested_banner, also populate clinical_context: a short underscore_case semantic tag describing the clinical scenario (e.g. malignancy_new, vascular_emergency, thromboembolism) for frontend icon/colour selection.
   status: "pass" if suggested_banners is empty, "flag" if any banner warranted. Keep flags_identified for diagnostic display (all 3 sub-flag evaluations).

5. REPORT_COMPLETENESS
   Assess three dimensions together:
   (a) Impression completeness — All significant findings described in FINDINGS (primary diagnoses, secondary diagnoses, and clinically meaningful findings) must be synthesised in the Impression. Minor incidentals that require no action and would not change clinical management are intentionally excluded from the Impression — do NOT flag their absence. FLAG if a significant or clinically meaningful finding in FINDINGS is entirely absent from the Impression without explanation. FLAG if the Impression uses language characterising the scan as normal or unremarkable (e.g., "unremarkable", "normal study", "no significant findings") when FINDINGS contain a clinically meaningful finding requiring action or follow-up. This is an active mischaracterisation, not merely an omission. WARNING if a potentially meaningful finding is absent but its clinical significance is uncertain. PASS if the Impression accounts for all significant findings; minor incidentals correctly omitted should not be flagged.
   (b) Systematic coverage — For scan type "{scan_type or 'general'}", flag only if a major expected organ system/region is entirely absent with no explanatory note (e.g., bowel loops not mentioned on an abdominal CT).
   (c) Comparative analysis — If the report references a prior study (e.g., "previously", "prior imaging", "compared to [date]"), explicit comparison language must be present. FLAG if interval change is described without a comparison section. If no prior study is referenced, this dimension is automatically met.
   FLAG if: Any of (a) or (c) are violated. WARNING for minor coverage gaps in (b) with no plausible clinical significance.

6. DIAGNOSTIC_FIDELITY
   Note: this criterion evaluates internal textual consistency within the report only — it does not assess correspondence to the actual images, which cannot be evaluated from text alone.

   Assess two dimensions together. Criterion status = worst of (a) and (b).
   The rationale field must label both dimensions using the exact OUTPUT REQUIREMENTS format (two lines: (a) Certainty: … (b) Consistency: …).

   (a) Certainty calibration
   FLAG if: A definitive diagnosis is stated without hedging for a finding that, as described in the report body, is genuinely equivocal — where a reasonable experienced radiologist would qualify the statement on the basis of the findings as written.
   WARNING if: Clearly normal or abnormal findings as described in the report carry excessive hedging that introduces unwarranted clinical uncertainty.
   PASS if: Certainty level is commensurate with how the findings are characterised in the report. Committed diagnoses for clear-cut findings are correct and should not be flagged.

   (b) Internal consistency — severity, negation, and measurements
   Before scoring, perform this explicit sequential check:

   Step 1 — Extract clinically significant negations from FINDINGS:
   Identify phrases that negate a primary diagnosis or key finding (e.g., "no filling defect", "no evidence of PE", "no thrombus identified"). Exclude generic boilerplate negatives ("no consolidation", "no effusion") unless they are the subject of the clinical question.

   Step 2 — Check Impression against Step 1:
   Does the Impression assert as present or confirmed any finding that FINDINGS explicitly negated? The contradiction must concern the same clinical entity or mutually exclusive claims (e.g., "no filling defect in pulmonary arteries bilaterally" in FINDINGS vs "pulmonary embolism confirmed" in Impression — same entity). Generic boilerplate negatives in FINDINGS that are not inverted in Impression do not qualify.

   Step 3 — Extract significant positive findings from FINDINGS.

   Step 4 — Check whether any significant positive in FINDINGS is negated or absent without explanation in the Impression.

   FLAG if: Any Step 2 contradiction is identified — a finding explicitly negated in FINDINGS but asserted as confirmed in the Impression. This is the highest-priority check and represents a patient safety error; it must be flagged even if the Impression reads fluently and confidently. Do NOT rationalise this as coherence — FINDINGS constrain the Impression, not the reverse.

   FLAG if: A severity characterisation in the Impression (e.g., massive/submassive, mild/moderate/severe) is inconsistent with the supporting descriptive findings in FINDINGS; OR a quantitative attribute (lesion size, vessel diameter, RV:LV ratio) in the Impression is inconsistent with the stated measurement in FINDINGS.

   WARNING if: Severity language is used without adequate descriptive support in FINDINGS to justify the characterisation, but is not directly contradicted.

   PASS if: Severity labels, negations, and measurements are consistent throughout. Do NOT flag when the Impression uses standard clinical shorthand that is consistent with — but less granular than — FINDINGS detail.

   Note: severity classification errors (e.g., 'massive' applied to a presentation that, as described in the report, lacks the defining features of that severity class, such as haemodynamic compromise or RV strain) are diagnostic attribute errors, not terminological preferences. They must be flagged, not excused as classification ambiguity. The label used in the Impression must be consistent with the haemodynamic status, RV findings, and thrombus extent as described in FINDINGS.

For each criterion, provide:
- status: "pass", "flag", or "warning"
- rationale: Brief explanation in British English only. For diagnostic_fidelity, follow the OUTPUT REQUIREMENTS two-line format exactly (required). For other criteria, typically one or two sentences (roughly 10–500 characters). For **recommendations** when criterion_line is populated, rationale is **deficiency-only** — see OUTPUT REQUIREMENTS (do not duplicate the guideline rule text).
- highlighted_spans: Verbatim text from report to highlight (only if status is flag or warning)
- recommendation: Suggested improvement within the radiological domain only (only if status is flag or warning)
- criterion_line: (recommendations only; flag or warning) See OUTPUT REQUIREMENTS; null otherwise and on pass
- flags_identified: (clinical_flagging only) List of all 3 sub-flag evaluations
- suggested_banners: (clinical_flagging only) List of 0–3 FlagBannerOption objects with category, label, banner_text, rationale, clinical_context

---
STRUCTURED OUTPUT (MANDATORY — BEFORE YOU RESPOND):
- Root object keys: overall_status, criteria (array length 6), summary (non-empty string).
- criteria: a real array of objects, not a string containing JSON.
- Each of the 6 objects must include rationale; for clinical_flagging, rationale is required alongside flags_identified and suggested_banners."""

    guideline_context_block = ""
    guideline_references: List[GuidelineReference] = []
    if not applicable_guidelines:
        print("[GUIDELINE_PIPELINE] audit_report: SKIP guideline resolution (no applicable_guidelines)")
    elif db is None:
        print("[GUIDELINE_PIPELINE] audit_report: SKIP guideline resolution (db is None)")
    if applicable_guidelines and db is not None:
        from .database.connection import SessionLocal
        from .guideline_fetcher import (
            GuidelineResolution,
            ensure_guideline_cached,
        )
        from .enhancement_models import ApplicableGuideline as _AG

        n_g = len(applicable_guidelines)
        _mode = "parallel (SessionLocal per guideline)" if n_g > 1 else "request db session"
        print(
            f"[GUIDELINE_PIPELINE] audit_report: resolving {n_g} applicable guideline(s) "
            f"({_mode})"
        )

        async def _fetch_audit_guideline(
            idx: int, g: Any
        ) -> Tuple[int, Any, GuidelineResolution]:
            ag = _AG(**g) if isinstance(g, dict) else g
            _g0 = time.perf_counter()
            try:
                if n_g > 1:
                    sdb = SessionLocal()
                    try:
                        res = await ensure_guideline_cached(ag, sdb)
                    finally:
                        sdb.close()
                else:
                    res = await ensure_guideline_cached(ag, db)
            except Exception as e:
                _g_ms = (time.perf_counter() - _g0) * 1000.0
                print(
                    f"[GUIDELINE_PIPELINE] audit_report: ensure_guideline_cached error "
                    f"idx={idx} system={getattr(ag, 'system', '?')!r}: {type(e).__name__}: {e} "
                    f"elapsed_ms={_g_ms:.0f}"
                )
                res = GuidelineResolution(None, None, False)
            else:
                _g_ms = (time.perf_counter() - _g0) * 1000.0
                print(
                    f"[GUIDELINE_PIPELINE] audit_report: guideline idx={idx} "
                    f"system={ag.system!r} ensure_guideline_cached elapsed_ms={_g_ms:.0f}"
                )
            return (idx, ag, res)

        resolved = await asyncio.gather(
            *[_fetch_audit_guideline(i, g) for i, g in enumerate(applicable_guidelines)]
        )
        resolved_sorted = sorted(resolved, key=lambda t: t[0])

        context_parts: List[str] = []
        for idx, ag, res in resolved_sorted:
            cc = len(res.content or "")
            print(
                f"[GUIDELINE_PIPELINE] audit_report: item {idx + 1}/{n_g} "
                f"system={ag.system!r} type={ag.type!r} injected={res.injected} "
                f"content_chars={cc} source_url={res.source_url!r}"
            )
            guideline_references.append(
                GuidelineReference(
                    system=ag.system,
                    context=ag.context,
                    type=ag.type,
                    source_url=res.source_url,
                    # Pass the full cached content — truncation was a conservative payload
                    # guard that is no longer needed now that the Copilot Guidelines tab
                    # renders the expanded criteria view. The LLM context already uses the
                    # full text (see context_parts below), so this adds no server-side cost.
                    criteria_summary=res.content if res.injected else None,
                    criteria_summary_truncated=False,
                    injected=res.injected,
                )
            )
            if res.injected and res.content:
                part = f"[{ag.system}]\n{res.content}"
                context_parts.append(part)
                print(
                    f"[GUIDELINE_PIPELINE] audit_report: appended context block for "
                    f"{ag.system!r} block_chars={len(part)}"
                )
            else:
                print(
                    f"[GUIDELINE_PIPELINE] audit_report: no context block for "
                    f"{ag.system!r} (not injected or empty content)"
                )
        if context_parts:
            guideline_context_block = (
                "\n\nGUIDELINE CONTEXT:\n"
                "These criteria serve two distinct purposes — apply them differently for each:\n\n"
                "1. RECOMMENDATION GROUNDING — The criteria contain specific management pathways "
                "(intervals, actions, urgency thresholds) tied to findings and classifications. "
                "When a RECOMMENDATIONS flag fires, derive the correction from these criteria "
                "directly: state the specific interval or action the criteria prescribe for the "
                "finding described, rather than noting only that specificity is lacking. "
                "A recommendation that merely identifies the gap without supplying the answer "
                "the criteria already provide is incomplete.\n\n"
                "2. CLASSIFICATION CORRECTNESS — Do not use these criteria to adjudicate whether "
                "the assigned classification is correct. Classification accuracy requires image "
                "review and is the radiologist's call. Flag under diagnostic_fidelity only where "
                "the impression contradicts the stated findings (internal consistency), not where "
                "a category appears inconsistent with the injected criteria.\n\n"
                + "\n\n".join(context_parts)
            )
            print(
                f"[GUIDELINE_PIPELINE] audit_report: GUIDELINE CONTEXT merged "
                f"blocks={len(context_parts)} total_chars={len(guideline_context_block)}"
            )
        else:
            print("[GUIDELINE_PIPELINE] audit_report: GUIDELINE CONTEXT empty (no injected blocks)")
        for gr in guideline_references:
            src = "injected" if gr.injected else "not retrieved"
            print(f"[GUIDELINE_PIPELINE] audit_report: summary {gr.system!r} → {src}")
    if guideline_context_block:
        user_prompt = user_prompt + guideline_context_block

    user_prompt = (
        user_prompt
        + "\n\n---\nREMINDER: Emit criteria as a JSON array (6 objects), not a string; include summary; "
        "every criterion object must have rationale (including clinical_flagging).\n"
    )

    # Primary model settings - provider-specific
    if provider == 'anthropic':
        # Claude (claude-sonnet-4-6): no thinking
        use_thinking = False
        primary_model_settings = {
            "temperature": 0.7,
            "max_tokens": 3500,
        }
    elif provider == 'groq':
        # Qwen 3 32B: per Groq docs for thinking mode
        use_thinking = 'qwen' in primary_model.lower()
        primary_model_settings = {
            "temperature": 0.6,
            "top_p": 0.95,
            "max_tokens": 3500,
        }
    elif provider == 'cerebras':
        # Zai-GLM on Cerebras: temperature 1.0 per provider requirements
        use_thinking = False
        primary_model_settings = {
            "temperature": 1.0,
            "top_p": 1,
            "max_completion_tokens": 3500,
        }
    else:
        use_thinking = False
        primary_model_settings = {"temperature": 0.7, "max_tokens": 3500}

    # ── Tavily search_guideline_criterion tool ────────────────────────────────
    _tavily_call_count = 0
    _TAVILY_MAX_CALLS = 2  # hard budget cap per audit run

    async def search_guideline_criterion(query: str) -> str:  # noqa: E306
        """
        Focused Tavily search for a specific guideline criterion or classification threshold.
        ONLY call when the prefetch KB and injected guidelines lack the exact rule needed.
        Use narrow, specific queries — NOT broad symptom lookups.
        Budget: max 2 calls per audit. Return format: JSON list of {title, url, snippet}.
        """
        nonlocal _tavily_call_count
        if _tavily_call_count >= _TAVILY_MAX_CALLS:
            return '{"error": "search budget exhausted (max 2 calls per audit)"}'
        _tavily_call_count += 1

        import os as _os
        tavily_key = _os.getenv("TAVILY_API_KEY", "")
        if not tavily_key:
            return '{"error": "TAVILY_API_KEY not configured"}'

        try:
            from tavily import AsyncTavilyClient as _TavilyClient
            from .guideline_prefetch import (
                DOMAIN_FILTER_PATHWAY, DOMAIN_FILTER_CLASSIFICATION, DOMAIN_FILTER_DIFFERENTIAL,
            )
            _all_domains = list({
                *DOMAIN_FILTER_PATHWAY, *DOMAIN_FILTER_CLASSIFICATION, *DOMAIN_FILTER_DIFFERENTIAL
            })
            _client = _TavilyClient(tavily_key)
            _resp = await asyncio.wait_for(
                _client.search(
                    query=query,
                    search_depth="advanced",
                    max_results=3,
                    chunks_per_source=2,
                    include_domains=_all_domains,
                ),
                timeout=15.0,
            )
            _items = []
            for _r in (_resp.get("results") or []):
                _items.append({
                    "title": _r.get("title", ""),
                    "url": _r.get("url", ""),
                    "snippet": (_r.get("content") or "")[:600],
                })
            print(
                f"[GUIDELINE_PIPELINE] audit search_guideline_criterion call={_tavily_call_count} "
                f"query={query!r:.80} results={len(_items)}"
            )
            import json as _json
            return _json.dumps(_items)
        except Exception as _exc:
            print(f"[GUIDELINE_PIPELINE] audit search_guideline_criterion error: {_exc!s}")
            return f'{{"error": "{type(_exc).__name__}: {str(_exc)[:120]}"}}'
    # ─────────────────────────────────────────────────────────────────────────
    # Cerebras and Groq reject tool calls mixed with structured-output tools
    # (strict mode conflict). Only Anthropic/Claude handles this cleanly.
    _provider_supports_tools = provider == 'anthropic'
    _primary_tools = [search_guideline_criterion] if _provider_supports_tools else []
    # Append tool-use instruction only when the provider will actually receive the tool
    if _provider_supports_tools:
        user_prompt = (
            user_prompt
            + "\nTOOL USE (search_guideline_criterion): You have access to a focused Tavily search tool. "
            "ONLY call it when the injected GUIDELINE CONTEXT and PREFETCH GUIDELINE CONTEXT are insufficient "
            "to answer a specific classification threshold or management rule required to complete a criterion. "
            "Budget: MAX 2 CALLS per audit. Use narrow, specific queries targeting a single criterion or "
            "classification system — never broad symptom or differential lookups. "
            "Do not call the tool for criteria with status 'pass'.\n"
        )
    print(
        f"[GUIDELINE_PIPELINE] audit_report: search tool "
        f"{'ENABLED' if _primary_tools else 'DISABLED (provider=' + provider + ')'}"
    )

    try:
        result = await _run_agent_with_model(
            model_name=primary_model,
            output_type=AuditResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=primary_api_key,
            use_thinking=use_thinking,
            model_settings=primary_model_settings,
            tools=_primary_tools,
        )
        
        audit_out = result.output
        model_used = primary_model
        
    except Exception as e:
        # Primary failed — try fallback model
        print(f"  └─ Primary model error: {type(e).__name__}: {e}")
        print(f"  └─ Error preview: {_audit_error_raw_preview(e)}")
        fallback_provider = _get_model_provider(fallback_model)
        fallback_api_key = _get_api_key_for_provider(fallback_provider, api_key)
        
        if _is_parsing_error(e):
            print(f"  └─ Treating as parsing/validation failure — switching to fallback {fallback_model}")
        else:
            print(f"  └─ Switching to fallback {fallback_model}: {str(e)[:200]}")
        
        if fallback_provider == 'cerebras':
            fallback_model_settings = {
                "temperature": 1.0,
                "top_p": 1,
                "max_completion_tokens": 3500,
            }
        elif fallback_provider == 'groq':
            fallback_model_settings = {
                "temperature": 0.6,
                "top_p": 0.95,
                "max_tokens": 3500,
            }
        else:
            fallback_model_settings = {"temperature": 0.7, "max_tokens": 3500}
        
        # Reset call count; only pass tool if fallback provider also supports it
        _tavily_call_count = 0
        _fallback_tools = [search_guideline_criterion] if fallback_provider == 'anthropic' else []
        result = await _run_agent_with_model(
            model_name=fallback_model,
            output_type=AuditResult,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=fallback_api_key,
            use_thinking=False,
            model_settings=fallback_model_settings,
            tools=_fallback_tools,
        )
        
        audit_out = result.output
        model_used = fallback_model
        print(f"  └─ Fallback model succeeded")

    audit_out = reconcile_audit_status(audit_out)
    
    elapsed = time.time() - start_time
    flags = sum(1 for c in audit_out.criteria if c.status == "flag")
    warnings = sum(1 for c in audit_out.criteria if c.status == "warning")

    print(f"  └─ Audit completed in {elapsed:.2f}s (model: {model_used})")
    print(f"  └─ Overall status: {audit_out.overall_status}  ({flags} flag(s), {warnings} warning(s))")
    print(f"  └─ Summary: {audit_out.summary}")
    print(f"  └─ Criteria breakdown ({len(audit_out.criteria)} returned):")
    for c in audit_out.criteria:
        icon = {"flag": "🚩", "warning": "⚠️", "pass": "✅"}.get(c.status, "?")
        print(f"       {icon} [{c.status.upper():7s}] {c.criterion}")
        print(f"              rationale : {c.rationale}")
        if c.recommendation:
            print(f"              recommend : {c.recommendation}")
        if c.highlighted_spans:
            print(f"              highlights: {c.highlighted_spans}")
    
    out = audit_out.model_dump()
    out["model_used"] = model_used
    out["guideline_references"] = [g.model_dump() for g in guideline_references]
    out["prefetch_used"] = _prefetch_used
    inj = sum(1 for g in guideline_references if g.injected)
    print(
        f"[GUIDELINE_PIPELINE] audit_report: return guideline_references="
        f"{len(guideline_references)} injected_count={inj} prefetch_used={_prefetch_used}"
    )
    return out


# ============================================================================
# NEW 3-Phase Audit Module
# ============================================================================

_PHASE1A_SYSTEM = """You are a senior radiologist and clinical radiology QA specialist practising in the UK.
Your task is to evaluate whether a radiology report faithfully represents the original
dictated findings input.

LANGUAGE (NON-NEGOTIABLE):
CRITICAL: You MUST write every user-visible string in English only — UK British English
spelling and terminology. Do not use Chinese, other languages, or mixed-language output.

EVALUATION SCOPE:
You are given two documents:
1. ORIGINAL INPUT — the raw findings as dictated/entered by the reporting radiologist
2. FINAL REPORT — the structured report generated from that input

Your job is to identify discrepancies between the two. The report generation process
may restructure, reformat, and professionalise the input — this is expected and correct.
You are NOT checking style, grammar, or structure. You are checking CONTENT FIDELITY.

WHAT COUNTS AS A DISCREPANCY:
- A finding explicitly stated in the ORIGINAL INPUT that is entirely absent from the
  FINAL REPORT (type: dropped)
- A measurement that changed between input and report (type: measurement_changed)
- Laterality that changed or was lost (type: laterality_changed)
- A qualifier or severity that was materially altered (type: qualifier_changed)
- A finding that was present in the input but inverted in the report (type: inverted)

WHAT IS NOT A DISCREPANCY:
- Restructuring into Findings/Impression format
- Professional language refinement
- Reasonable inference or elaboration by the report generator
- Omission of non-clinical fragments
- Reordering of findings into anatomical or systematic structure

STATUS LOGIC:
- FLAG: A clinically significant finding, measurement, or laterality from the input is
  missing, contradicted, or materially altered in the report
- WARNING: A minor detail is lost or altered that is unlikely to affect clinical
  management but represents imperfect fidelity
- PASS: All clinically material content from the input is faithfully represented in the
  report, allowing for expected restructuring and professionalisation

OUTPUT:
Return a single criterion evaluation object with:
- criterion: "input_fidelity"
- status, rationale, highlighted_spans, recommendation (standard fields)
- discrepancies: Array of {input_text, report_text, type, severity} objects documenting
  each specific discrepancy found. Empty array on pass."""


_PHASE2_SYSTEM = """You are a senior radiologist and clinical radiology QA specialist practising in the UK.
Your task is to evaluate a radiology report against four guideline-compliance criteria,
using pre-computed synthesis evidence from authoritative clinical sources.

LANGUAGE (NON-NEGOTIABLE):
CRITICAL: You MUST write every user-visible string in English only — UK British English
spelling and terminology. Do not use Chinese, other languages, or mixed-language output.

FINDINGS-OVER-IMPRESSION RULE:
FINDINGS constrain the Impression for factual consistency. When evaluating any criterion,
treat explicit FINDINGS statements as the ground truth against which Impression claims are
validated — not the reverse. A confident, fluent Impression does not override an explicit
FINDINGS negation or characterisation.

SYNTHESIS EVIDENCE (pre-computed from authoritative guideline sources):
The following structured analysis has been pre-computed for each significant finding
in this report. Use this as your primary reference for all four criteria.

When evaluating DIAGNOSTIC_FIDELITY, use classifications, thresholds, and stage grouping
from the synthesis evidence to cross-check staging assignments in the report. If the
synthesis evidence provides explicit T/N/M definitions with size thresholds, verify the
report's staging against those definitions — not just internal Findings↔Impression
consistency.

When evaluating RECOMMENDATIONS, compare the report's stated recommendations directly
against the synthesised follow_up_actions — these encode the guideline-correct pathway,
timing, and indication for this specific patient. Derive criterion_line from the
synthesis evidence, not from general knowledge. Flag recommendations that are NOT
supported by synthesis evidence (discordant) as well as those that are missing.

When evaluating CLINICAL_FLAGGING, use urgency_tier from the synthesis evidence as a
calibration prior for banner severity. It does not override your independent assessment
of the report's FINDINGS but should inform whether the finding warrants
critical/urgent/significant communication. Banner severity must be determined by the
clinical features described in FINDINGS — haemodynamic status, imaging extent, RV strain,
vascular involvement — not by the severity label used in the Impression.

When evaluating CHARACTERISATION_GAP, use imaging_flags and classifications as the
feature checklist against which to assess report characterisation completeness per finding.

Do not cross-apply numerical thresholds or management rules between frameworks designed
for different clinical contexts. Where multiple classification systems appear for the
same finding, use the one whose scope matches scan purpose and clinical question.

--- CRITERION-SPECIFIC INSTRUCTIONS ---

1. DIAGNOSTIC_FIDELITY
   Assess two dimensions together. Criterion status = worst of (a) and (b).
   rationale MUST use format: (a) Certainty: PASS/WARNING/FLAG — ... (b) Consistency: PASS/WARNING/FLAG — ...

   (a) Certainty calibration
   FLAG if: A definitive diagnosis is stated without hedging for a finding that, as described
   in the report body, is genuinely equivocal.
   WARNING if: Excessive hedging on clearly normal/abnormal findings introduces unwarranted
   clinical uncertainty.
   PASS if: Certainty level is commensurate with how the findings are characterised.

   (b) Internal consistency + guideline-threshold cross-check
   Before scoring, perform this check sequence:
   Step 1 — Extract clinically significant negations from FINDINGS. Identify phrases that negate
   a primary diagnosis or key finding.
   Step 2 — Check Impression against Step 1: Does the Impression assert as present any finding
   that FINDINGS explicitly negated? FLAG if so — this is a patient safety error.
   Step 3 — Cross-check staging and measurements against synthesis thresholds and classifications:
   If the report assigns a staging classification (TNM, FIGO, Bosniak, etc.) or makes a
   measurement-dependent claim, verify it is consistent with the threshold definitions in the
   synthesis evidence. FLAG if the assigned stage contradicts the thresholds (e.g. a 4.8cm tumour
   staged as T2a when the threshold table shows T2b for >4cm). WARNING if borderline.
   Step 4 — Cross-check that the report does NOT recommend investigations that the synthesis
   evidence explicitly does NOT indicate for this tumour type or clinical context (e.g. CT body
   staging for a primary brain tumour when guidelines indicate no role for systemic staging).

2. RECOMMENDATIONS
   Compare the report's stated recommendations against the synthesised follow_up_actions.
   This is a BIDIRECTIONAL concordance check:
   FLAG if: (a) An actionable finding has no associated recommendation when guidelines indicate
   one (MISSING recommendation), OR (b) the report recommends an investigation or referral that
   the synthesis evidence does NOT support for this clinical context (DISCORDANT recommendation —
   e.g. recommending CT staging when guidelines indicate it is not indicated for this tumour type),
   OR (c) urgency is clearly mismatched with clinical severity.
   WARNING if: A recommendation is present but urgency or specificity is likely under-stated.
   PASS if: Recommendations are consistent with synthesised follow_up_actions and no discordant
   recommendations are present.
   When status is flag or warning, populate criterion_line with the single most relevant
   guideline rule from the synthesis evidence, and write rationale as deficiency-only
   (do not duplicate guideline text in rationale).

3. CLINICAL_FLAGGING
   Detect whether the report warrants a clinical communication banner that the user may
   append to the report. This is an ALERT mechanism — banners are pure severity headers,
   not clinical summaries.

   Evaluate presence of three severity tiers (flags_identified — return all 3 evaluations):
   - critical: Life-threatening findings requiring immediate action as supported by FINDINGS
     (e.g. tension pneumothorax, aortic dissection, PE with haemodynamic compromise/RV strain,
     active haemorrhage, cord compression). Do NOT assign critical from an Impression label
     alone if FINDINGS describe haemodynamic stability.
   - urgent: Findings needing same-day clinical attention (e.g. new DVT, bowel obstruction
     with transition point, acute cholecystitis with complications, new stroke territory
     infarct, suspected malignancy requiring urgent MDT/oncology referral).
   - significant: Important findings for clinical management that are not immediately
     time-critical but require documented clinician acknowledgement (e.g. interval change
     in known malignancy, new indeterminate lesion needing surveillance, incidental finding
     requiring specialist follow-up).

   For each present flag, populate suggested_banners (0–3, most severe first) using these
   EXACT standard templates:
   - critical:    label "Critical — Immediate Action Required"
                  banner_text "*****CRITICAL RADIOLOGICAL FINDING — REQUIRES IMMEDIATE CLINICIAN ACTION*****"
   - urgent:      label "Urgent — Same-Day Attention"
                  banner_text "*****URGENT RADIOLOGICAL FINDING — PLEASE REVIEW TODAY*****"
   - significant: label "Significant — Review with Referring Team"
                  banner_text "*****CLINICALLY SIGNIFICANT FINDING — PLEASE REVIEW WITH REFERRING TEAM*****"

   For each suggested_banner, also populate:
   - rationale: One sentence explaining why this severity tier is warranted (British English).
   - clinical_context: A short semantic tag describing the clinical scenario, used by the
     frontend for icon/colour selection. Use underscore_case. Examples:
     malignancy_new, malignancy_interval, vascular_emergency, infection_sepsis,
     bowel_obstruction, cord_compression, haemorrhage_active, fracture_unstable,
     thromboembolism, organ_ischaemia.
     Choose the tag that best captures the dominant clinical concern. Do NOT invent tags
     for trivial findings — only tag banners that you are actually suggesting.

   STATUS: "pass" if suggested_banners is empty; "flag" if any banner is warranted.
   Keep flags_identified as a diagnostic array (all 3 sub-flag evaluations regardless of
   whether present).

4. CHARACTERISATION_GAP
   For each significant positive finding, check whether the radiologist has characterised
   all guideline-relevant features identified in the synthesis evidence (imaging_flags,
   classification features, measurement parameters).
   FLAG if: A critical characterisation feature is absent.
   WARNING if: A supporting feature is absent.
   PASS if: All guideline-relevant features are adequately characterised.
   Populate characterisation_gaps array with specifics for each gap found.

OUTPUT REQUIREMENTS:
Return exactly 4 criterion evaluations in order: diagnostic_fidelity, recommendations,
clinical_flagging, characterisation_gap. Each must include: criterion, status, rationale,
highlighted_spans, recommendation. Additional fields per criterion:
- diagnostic_fidelity: rationale MUST contain both lines: (a) Certainty: ... (b) Consistency: ...
  Do not attempt suggested_replacement for diagnostic_fidelity — the correct fix is almost
  never a single span swap. For diagnostic_fidelity (b) Consistency, FINDINGS are the source
  of truth. Criterion-level status = worst of (a) and (b).
- recommendations: criterion_line (flag/warning only, null on pass). Bidirectional check:
  flag missing recommendations AND discordant recommendations (report recommends something
  not indicated by synthesis evidence).
- clinical_flagging: flags_identified (always 3 sub-flag objects), suggested_banners (0–3)
- characterisation_gap: characterisation_gaps (array of gap objects)
overall_status must equal the worst status across all four criteria."""


def _build_synthesis_evidence_block(
    synthesis_cards: list,
    finding_short_labels: list,
) -> str:
    """Format S4 synthesis cards into a text block for Phase 2 audit prompt injection.

    When no cards are available, return an unanchored-mode preamble. The evaluation
    still runs — Phase 2 criteria are about report quality, not about citation — but
    the bar for flagging is raised because no specific guideline backs the call.
    """
    if not synthesis_cards:
        return (
            "\nUNANCHORED MODE — NO SPECIFIC GUIDELINE APPLIED:\n"
            "No applicable guideline was retrieved for this case. Evaluate the report "
            "using standard radiological reporting practice. The four criteria still "
            "apply; they simply cannot be anchored to a specific guideline document.\n\n"
            "RAISE THE BAR FOR FLAGGING:\n"
            "Only flag issues that would be obviously inappropriate to any consultant "
            "radiologist regardless of specific guideline — do not flag on the basis of "
            "preference or optional best-practice variants. Where the synthesis prompt "
            "normally instructs you to derive criterion_line from synthesis evidence, "
            "leave criterion_line null. Where the prompt normally instructs cross-check "
            "against synthesis thresholds, rely on internal FINDINGS↔Impression "
            "consistency only and do not fabricate thresholds.\n"
        )
    parts = []
    for i, card in enumerate(synthesis_cards):
        short_label = (
            finding_short_labels[i] if i < len(finding_short_labels)
            else card.get("finding_short_label", card.get("finding", f"Finding {i+1}"))
        )
        lines = [f"--- Finding {i+1}: {short_label} ---"]
        lines.append(f"Urgency tier: {card.get('urgency_tier', 'none')}")

        fu_actions = card.get("follow_up_actions", [])
        if fu_actions:
            lines.append("\nFollow-up actions:")
            for a in fu_actions:
                lines.append(
                    f"  - {a.get('modality','')} | timing: {a.get('timing','')} "
                    f"| indication: {a.get('indication','')} | urgency: {a.get('urgency','')}"
                )
                src = a.get("guideline_source", "")
                if src:
                    lines.append(f"    Source: {src}")

        classifications = card.get("classifications", [])
        if classifications:
            lines.append("\nClassifications:")
            for c in classifications:
                yr = f", {c.get('year','')}" if c.get("year") else ""
                lines.append(f"  - {c.get('system','')} ({c.get('authority','')}{yr}): grade {c.get('grade','')}")
                if c.get("criteria"):
                    lines.append(f"    Criteria: {c['criteria']}")
                if c.get("management"):
                    lines.append(f"    Management: {c['management']}")

        thresholds = card.get("thresholds", [])
        if thresholds:
            lines.append("\nThresholds:")
            for t in thresholds:
                lines.append(f"  - {t.get('parameter','')}: {t.get('threshold','')} — {t.get('significance','')}")

        imaging_flags = card.get("imaging_flags", [])
        if imaging_flags:
            lines.append("\nImaging flags:")
            for flg in imaging_flags:
                lines.append(f"  - {flg}")

        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def run_audit_phase1(
    report_content: str,
    scan_type: str,
    clinical_history: str,
    findings_input: str,
    other_variables: dict,
    urgency_signals: list,
    api_key: str = None,
) -> dict:
    """Run Phase 1a (input_fidelity) + Phase 1b (4 criteria) in parallel.

    Returns a partial AuditResult dict (5 criteria).
    """
    from rapid_reports_ai.enhancement_models import (
        Phase1aOutput,
        Phase1bOutput,
        AuditCriterion as _AC,
    )

    cerebras_key = api_key or os.environ.get("CEREBRAS_API_KEY", "")

    model_settings_1a = {
        "temperature": 0.8,
        "top_p": 0.95,
        "max_completion_tokens": 1500,
        "extra_body": {"disable_reasoning": False},
    }

    model_settings_1b = {
        "temperature": 0.8,
        "top_p": 0.95,
        "max_completion_tokens": 2500,
        "extra_body": {"disable_reasoning": False},
    }

    async def _phase1a() -> _AC:
        if not findings_input:
            return _AC(
                criterion="input_fidelity",
                status="pass",
                rationale="No original input provided — input fidelity check not applicable.",
            )
        vars_text = "\n".join(
            f"{k}: {v}" for k, v in (other_variables or {}).items()
            if k != "FINDINGS" and v
        )
        user_prompt = (
            f"ORIGINAL INPUT (as dictated/entered by reporting radiologist):\n{findings_input}\n\n"
            f"ADDITIONAL INPUT VARIABLES:\n{vars_text or '(none)'}\n\n"
            f"FINAL REPORT:\n{report_content}\n\n"
            f"SCAN TYPE: {scan_type or '(not specified)'}\n\n"
            f"Evaluate input fidelity: are all clinically material findings from the "
            f"ORIGINAL INPUT faithfully represented in the FINAL REPORT?"
        )
        try:
            result = await _run_agent_with_model(
                model_name="zai-glm-4.7",
                output_type=Phase1aOutput,
                system_prompt=_PHASE1A_SYSTEM,
                user_prompt=user_prompt,
                api_key=cerebras_key,
                model_settings=model_settings_1a,
            )
            out = result.output
            return _AC(
                criterion="input_fidelity",
                status=out.status,
                rationale=out.rationale,
                highlighted_spans=out.highlighted_spans,
                recommendation=out.recommendation,
                discrepancies=out.discrepancies if out.discrepancies else None,
            )
        except Exception as e:
            print(f"[AUDIT] Phase 1a failed: {e}")
            return _AC(
                criterion="input_fidelity",
                status="pass",
                rationale=f"Input fidelity check could not be completed: {str(e)[:200]}",
            )

    async def _phase1b() -> list:
        try:
            result = await _run_agent_with_model(
                model_name="zai-glm-4.7",
                output_type=Phase1bOutput,
                system_prompt=_build_phase1b_system(scan_type, clinical_history),
                user_prompt=_build_phase1b_user(
                    report_content, scan_type, clinical_history, urgency_signals,
                ),
                api_key=cerebras_key,
                model_settings=model_settings_1b,
            )
            return list(result.output.criteria)
        except Exception as e:
            print(f"[AUDIT] Phase 1b failed: {e}")
            return []

    p1a_result, p1b_results = await asyncio.gather(_phase1a(), _phase1b())

    all_criteria = [p1a_result] + p1b_results
    statuses = [c.status for c in all_criteria]
    overall = "pass"
    if any(s == "flag" for s in statuses):
        overall = "flag"
    elif any(s == "warning" for s in statuses):
        overall = "warning"

    return {
        "overall_status": overall,
        "criteria": [c.model_dump() for c in all_criteria],
        "summary": f"Phase 1 audit complete ({len(all_criteria)} criteria). Phase 2 pending.",
        "partial": True,
    }


async def run_audit_phase2(
    report_content: str,
    scan_type: str,
    clinical_history: str,
    synthesis_cards: list,
    urgency_signals: list,
    consolidated_findings: list,
    finding_short_labels: list,
    api_key: str = None,
) -> list:
    """Run Phase 2 audit (4 guideline-compliance criteria incl. diagnostic_fidelity).

    Returns a list of AuditCriterion objects (or dicts).
    """
    from rapid_reports_ai.enhancement_models import Phase2Output, AuditCriterion as _AC

    cerebras_key = api_key or os.environ.get("CEREBRAS_API_KEY", "")

    evidence_block = _build_synthesis_evidence_block(synthesis_cards, finding_short_labels)
    system_prompt = _PHASE2_SYSTEM + "\n\n" + evidence_block

    user_prompt = (
        f"RADIOLOGY REPORT:\n{report_content}\n\n"
        f"SCAN TYPE: {scan_type or '(not specified)'}\n"
        f"CLINICAL HISTORY: {clinical_history or '(not provided)'}\n\n"
        f"Evaluate the report against these four criteria:\n"
        f"1. DIAGNOSTIC_FIDELITY — Are staging assignments and clinical assertions internally "
        f"consistent with findings AND concordant with the synthesis thresholds/classifications?\n"
        f"2. RECOMMENDATIONS — Are the report's recommendations concordant with the synthesised "
        f"follow_up_actions? Check both directions: missing AND discordant recommendations.\n"
        f"3. CLINICAL_FLAGGING — Does the report appropriately flag urgent/critical findings "
        f"for clinical communication? Return all 3 sub-flag evaluations (critical, urgent, "
        f"significant) in flags_identified and 0–3 suggested_banners with clinical_context tags.\n"
        f"4. CHARACTERISATION_GAP — For each significant positive finding, has the radiologist "
        f"characterised all guideline-relevant features?\n\n"
        f"Return exactly 4 criterion evaluations in order: diagnostic_fidelity, recommendations, "
        f"clinical_flagging, characterisation_gap."
    )

    model_settings = {
        "temperature": 0.8,
        "top_p": 0.95,
        "max_completion_tokens": 5000,
        "extra_body": {"disable_reasoning": False},
    }

    try:
        result = await _run_agent_with_model(
            model_name="zai-glm-4.7",
            output_type=Phase2Output,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=cerebras_key,
            model_settings=model_settings,
        )
        return list(result.output.criteria)
    except Exception as e:
        print(f"[AUDIT] Phase 2 failed: {e}")
        return []


def merge_audit_phases(phase1_result: dict, phase2_criteria: list) -> dict:
    """Merge Phase 2 criteria into Phase 1 result, recompute overall_status."""
    merged = dict(phase1_result)
    p2_dicts = [
        c.model_dump() if hasattr(c, "model_dump") else c
        for c in phase2_criteria
    ]
    merged["criteria"] = merged.get("criteria", []) + p2_dicts
    merged.pop("partial", None)

    status_rank = {"pass": 0, "warning": 1, "flag": 2}
    rank_status = {0: "pass", 1: "warning", 2: "flag"}
    worst = max(
        status_rank.get(c.get("status", "pass") if isinstance(c, dict) else c.status, 0)
        for c in merged["criteria"]
    ) if merged["criteria"] else 0
    merged["overall_status"] = rank_status[worst]
    merged["summary"] = f"Full audit complete ({len(merged['criteria'])} criteria)."
    return merged


async def run_full_audit(
    report_content: str,
    scan_type: str,
    clinical_history: str,
    findings_input: str,
    other_variables: dict,
    urgency_signals: list,
    synthesis_cards: list,
    consolidated_findings: list,
    finding_short_labels: list,
    api_key: str = None,
) -> dict:
    """Run all 9 audit criteria (Phase 1a + 1b + Phase 2) in parallel.

    Returns a complete AuditResult dict with all criteria.
    """
    from rapid_reports_ai.enhancement_models import (
        Phase1aOutput,
        Phase1bOutput,
        Phase2Output,
        AuditCriterion as _AC,
    )

    cerebras_key = api_key or os.environ.get("CEREBRAS_API_KEY", "")

    model_settings_1a = {
        "temperature": 0.8,
        "top_p": 0.95,
        "max_completion_tokens": 1500,
        "extra_body": {"disable_reasoning": False},
    }
    model_settings_1b = {
        "temperature": 0.8,
        "top_p": 0.95,
        "max_completion_tokens": 2500,
        "extra_body": {"disable_reasoning": False},
    }
    model_settings_2 = {
        "temperature": 0.8,
        "top_p": 0.95,
        "max_completion_tokens": 5000,
        "extra_body": {"disable_reasoning": False},
    }

    async def _phase1a() -> _AC:
        if not findings_input:
            return _AC(
                criterion="input_fidelity",
                status="pass",
                rationale="No original input provided — input fidelity check not applicable.",
            )
        vars_text = "\n".join(
            f"{k}: {v}" for k, v in (other_variables or {}).items()
            if k != "FINDINGS" and v
        )
        user_prompt = (
            f"ORIGINAL INPUT (as dictated/entered by reporting radiologist):\n{findings_input}\n\n"
            f"ADDITIONAL INPUT VARIABLES:\n{vars_text or '(none)'}\n\n"
            f"FINAL REPORT:\n{report_content}\n\n"
            f"SCAN TYPE: {scan_type or '(not specified)'}\n\n"
            f"Evaluate input fidelity: are all clinically material findings from the "
            f"ORIGINAL INPUT faithfully represented in the FINAL REPORT?"
        )
        try:
            result = await _run_agent_with_model(
                model_name="zai-glm-4.7",
                output_type=Phase1aOutput,
                system_prompt=_PHASE1A_SYSTEM,
                user_prompt=user_prompt,
                api_key=cerebras_key,
                model_settings=model_settings_1a,
            )
            out = result.output
            return _AC(
                criterion="input_fidelity",
                status=out.status,
                rationale=out.rationale,
                highlighted_spans=out.highlighted_spans,
                recommendation=out.recommendation,
                discrepancies=out.discrepancies if out.discrepancies else None,
            )
        except Exception as e:
            print(f"[AUDIT] Phase 1a failed: {e}")
            return _AC(
                criterion="input_fidelity",
                status="pass",
                rationale=f"Input fidelity check could not be completed: {str(e)[:200]}",
            )

    async def _phase1b() -> list:
        try:
            result = await _run_agent_with_model(
                model_name="zai-glm-4.7",
                output_type=Phase1bOutput,
                system_prompt=_build_phase1b_system(scan_type, clinical_history),
                user_prompt=_build_phase1b_user(
                    report_content, scan_type, clinical_history, urgency_signals,
                ),
                api_key=cerebras_key,
                model_settings=model_settings_1b,
            )
            return list(result.output.criteria)
        except Exception as e:
            print(f"[AUDIT] Phase 1b failed: {e}")
            return []

    async def _phase2() -> list:
        evidence_block = _build_synthesis_evidence_block(synthesis_cards, finding_short_labels)
        system_prompt = _PHASE2_SYSTEM + "\n\n" + evidence_block
        user_prompt = (
            f"RADIOLOGY REPORT:\n{report_content}\n\n"
            f"SCAN TYPE: {scan_type or '(not specified)'}\n"
            f"CLINICAL HISTORY: {clinical_history or '(not provided)'}\n\n"
            f"Evaluate the report against these four criteria:\n"
            f"1. DIAGNOSTIC_FIDELITY — Are staging assignments and clinical assertions internally "
            f"consistent with findings AND concordant with the synthesis thresholds/classifications?\n"
            f"2. RECOMMENDATIONS — Are the report's recommendations concordant with the synthesised "
            f"follow_up_actions? Check both directions: missing AND discordant recommendations.\n"
            f"3. CLINICAL_FLAGGING — Does the report appropriately flag urgent/critical findings "
            f"for clinical communication? Return all 3 sub-flag evaluations (critical, urgent, "
            f"significant) in flags_identified and 0–3 suggested_banners with clinical_context tags.\n"
            f"4. CHARACTERISATION_GAP — For each significant positive finding, has the radiologist "
            f"characterised all guideline-relevant features?\n\n"
            f"Return exactly 4 criterion evaluations in order: diagnostic_fidelity, recommendations, "
            f"clinical_flagging, characterisation_gap."
        )
        try:
            result = await _run_agent_with_model(
                model_name="zai-glm-4.7",
                output_type=Phase2Output,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=cerebras_key,
                model_settings=model_settings_2,
            )
            return list(result.output.criteria)
        except Exception as e:
            print(f"[AUDIT] Phase 2 failed: {e}")
            return []

    p1a_result, p1b_results, p2_results = await asyncio.gather(
        _phase1a(), _phase1b(), _phase2()
    )

    all_criteria = [p1a_result] + p1b_results + p2_results
    all_dicts = [
        c.model_dump() if hasattr(c, "model_dump") else c for c in all_criteria
    ]

    status_rank = {"pass": 0, "warning": 1, "flag": 2}
    rank_status = {0: "pass", 1: "warning", 2: "flag"}
    worst = max(
        (status_rank.get(
            c.get("status", "pass") if isinstance(c, dict) else getattr(c, "status", "pass"), 0
        ) for c in all_criteria),
        default=0,
    )

    return {
        "overall_status": rank_status[worst],
        "criteria": all_dicts,
        "summary": f"Full audit complete ({len(all_dicts)} criteria).",
    }


# -- Phase 1b prompt builder (reuses existing audit prompt structure) --

def _build_phase1b_system(scan_type: str, clinical_history: str) -> str:
    """Build Phase 1b system prompt (4 report-integrity criteria, no guideline context)."""
    return """You are a senior radiologist and clinical radiology QA specialist practising in the UK.
Your task is to evaluate a radiology report against four report-integrity criteria.
You do NOT have access to clinical guidelines — those are assessed separately.

LANGUAGE (NON-NEGOTIABLE):
CRITICAL: You MUST write every user-visible string in English only — UK British English
spelling and terminology. Do not use Chinese, other languages, or mixed-language output.

FLAGGING PHILOSOPHY:
The report was generated by an AI assistant. Err toward tolerance for style differences,
reasonable inferences, and alternative but clinically correct formulations. Reserve FLAG
for material clinical errors or omissions that could affect patient management.

OUTPUT REQUIREMENTS:
Return exactly 5 criterion evaluations, each with:
- criterion, status (pass/flag/warning), rationale, highlighted_spans, recommendation
- Additional fields as specified per criterion below"""


def _build_phase1b_user(
    report_content: str,
    scan_type: str,
    clinical_history: str,
    urgency_signals: list,
) -> str:
    """Build Phase 1b user prompt with the 5 criteria definitions."""
    urgency_text = ", ".join(urgency_signals) if urgency_signals else "none"
    return f"""RADIOLOGY REPORT:
{report_content}

SCAN TYPE: {scan_type or '(not specified)'}
CLINICAL HISTORY: {clinical_history or '(not provided)'}
URGENCY SIGNALS: {urgency_text}

Evaluate the report against these 4 criteria:

1. ANATOMICAL_ACCURACY
   Check for incorrect anatomical terms, laterality errors, spatial relationship errors.
   suggested_replacement: populate when a verbatim span swap fixes the error. Null for structural issues.
   Status: FLAG for material anatomical error, WARNING for minor terminology, PASS otherwise.

2. CLINICAL_RELEVANCE
   Does the report address the clinical question? Are findings appropriately linked to the indication?
   Status: FLAG if the clinical question is ignored or misaddressed, WARNING for weak linkage, PASS otherwise.

3. REPORT_COMPLETENESS
   (a) Impression completeness — Does Impression summarise ALL significant Findings?
   (c) Comparative analysis — If prior studies are referenced, is the comparison adequate?
   suggested_sentence: populate for report_completeness when a complete sentence should be added. Null for span swaps.
   Status: FLAG if a significant finding is missing from Impression, WARNING for minor omission, PASS otherwise.

4. SCAN_COVERAGE
   For the scan type "{scan_type}" and clinical indication "{clinical_history}",
   dynamically determine the expected anatomical review areas.
   Do NOT use a fixed checklist — infer from scan type and clinical context.
   A system is "addressed" if the Findings section contains ANY mention of the relevant anatomy.
   FLAG: A major organ system standard for this scan type is entirely unmentioned.
   WARNING: A secondary review area is unmentioned.
   PASS: All expected systems are addressed.
   Additional output field: systems_unaddressed (array of strings, empty on pass).

Return exactly 4 criteria in order: anatomical_accuracy, clinical_relevance, report_completeness, scan_coverage."""
