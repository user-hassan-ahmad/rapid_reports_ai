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
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from pydantic import BaseModel
from pydantic_ai import RunContext

from .enhancement_cache import (
    get_cache,
    generate_finding_hash,
    generate_query_hash,
    generate_search_results_hash
)
import hashlib

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
    KeyPoint,
    ClassificationSystem,
    MeasurementProtocol,
    ImagingCharacteristic,
    DifferentialDiagnosis,
    FollowUpImaging,
    CompletenessAnalysis,
    AnalysisSummary,
    ReviewQuestion,
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
)

# Central Model Configuration Dictionary
# Maps generic roles to specific model identifiers for easy model swapping
# Update this dictionary to change models without modifying code throughout the codebase
MODEL_CONFIG = {
    # Report Generation Models
    "PRIMARY_REPORT_GENERATOR": "zai-glm-4.7",  # Primary model for report generation (Cerebras Zai-GLM-4.6)
    "FALLBACK_REPORT_GENERATOR": "claude-sonnet-4-20250514",  # Fallback model if primary fails after retries (Claude Sonnet 4)
    
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
    "GUIDELINE_SEARCH": "gpt-oss-120b",  # Phase 2: Guideline synthesis (primary - Cerebras)
    "GUIDELINE_SEARCH_FALLBACK": "llama-3.3-70b-versatile",  # Fallback for guideline synthesis (Llama)
    "COMPLETENESS_ANALYZER": "gpt-oss-120b",  # Phase 3: Completeness analysis (primary - Cerebras GPT-OSS-120B with high reasoning)
    "COMPLETENESS_ANALYZER_FALLBACK": "qwen/qwen3-32b",  # Fallback for completeness analysis (Qwen)
    "COMPARISON_ANALYZER": "gpt-oss-120b",  # Interval comparison analysis (primary - Cerebras GPT-OSS-120B with high reasoning)
    "COMPARISON_ANALYZER_FALLBACK": "qwen/qwen3-32b",  # Fallback for comparison analysis (Qwen)
    
    # Action Application Models
    "ACTION_APPLIER": "gpt-oss-120b",  # Apply enhancement actions to reports (primary - Cerebras GPT-OSS-120B with high reasoning)
    "ACTION_APPLIER_FALLBACK": "qwen/qwen3-32b",  # Fallback for action application (Qwen)
    
    # Linguistic Validation Models (for zai-glm-4.7 post-processing)
    "ZAI_GLM_LINGUISTIC_VALIDATOR": "llama-3.3-70b",  # Linguistic/anatomical correction for zai-glm-4.7 output (Cerebras-hosted Llama)
}

# Legacy constants for backward compatibility (deprecated - use MODEL_CONFIG instead)
QWEN_EXTRACTION_MODEL = MODEL_CONFIG["FINDING_EXTRACTION"]
QWEN_ANALYSIS_MODEL = MODEL_CONFIG["COMPLETENESS_ANALYZER"]  # Note: Completeness uses Qwen as primary, Claude as fallback
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
    
    # Cerebras models
    "gpt-oss-120b": "cerebras",
    "zai-glm-4.7": "cerebras",
    "llama-3.3-70b": "cerebras",  # Cerebras-hosted Llama for linguistic validation
    "qwen-3-235b-a22b-instruct-2507": "cerebras",  # Cerebras-hosted Qwen for linguistic validation
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
    else:
        raise ValueError(f"Unknown provider: {provider}. Must be 'groq', 'anthropic', or 'cerebras'.")


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
                    
                    # Check if it's a rate limit error
                    if "rate" in error_str or "quota" in error_str or "429" in error_str:
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
    
    # Groq tool_use_failed errors - model can't generate proper function calls
    if isinstance(exception, ModelHTTPError):
        if exception.status_code == 400:
            body_str = str(exception.body).lower()
            # Check for known parsing error indicators
            if 'tool_use_failed' in body_str or 'failed to call a function' in body_str:
                return True
    
    return False


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
        title = (result.get("title") or "")[:150]
        snippet = (result.get("snippet") or "")[:200]
        batch_prompt += f"{i}. Title: {title}\n   Summary: {snippet}\n\n"
    
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
    guideline_entry: GuidelineEntry,
    finding: str,
    api_key: str
) -> bool:
    """
    Validate that synthesized guideline matches the clinical premise of the finding.
    Returns True if compatible, False otherwise.
    Model selection is driven by MODEL_CONFIG - supports any configured model with fallback.
    
    Args:
        guideline_entry: The synthesized GuidelineEntry from guideline synthesis
        finding: The original radiological finding text
        api_key: API key (kept for compatibility, actual key determined by provider)
        
    Returns:
        True if guideline is compatible with finding, False otherwise
    """
    import os
    
    start_time = time.time()
    print(f"validate_guideline_compatibility: Validating guideline for finding '{finding}'")
    
    # Build validation prompt
    guideline_summary = (
        f"Diagnostic Overview: {guideline_entry.diagnostic_overview[:300]}\n"
    )
    if guideline_entry.classification_systems:
        guideline_summary += f"Classification Systems: {', '.join([cs.name for cs in guideline_entry.classification_systems])}\n"
    if guideline_entry.differential_diagnoses:
        guideline_summary += f"Differential Diagnoses: {', '.join([dd.diagnosis for dd in guideline_entry.differential_diagnoses])}\n"
    
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


@with_retry(max_retries=3, base_delay=2.0)
async def search_guidelines_for_findings(
    consolidated_result: ConsolidationResult,
    report_content: str,
    api_key: str,
    findings_input: str = ""
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

    # Guidelines synthesis agent - Radiologist-to-radiologist diagnostic perspective
    guidelines_system_prompt = (
        "CRITICAL: You MUST use British English spelling and terminology throughout all output.\n\n"
        "You are a senior UK consultant radiologist providing diagnostic imaging guidance to NHS colleagues.\n\n"
        
        "PERSPECTIVE: Radiologist-to-radiologist - focus on imaging characterization that informs diagnostic and management decisions.\n\n"
        
        "FOCUS: Highlight significant/impactful information and criteria that support or direct patient care:\n"
        "• Actionable thresholds and decision points (e.g., size criteria for follow-up, severity grading)\n"
        "• Clinically relevant imaging features that guide management\n"
        "• Classification systems that inform treatment decisions\n"
        "• Measurement protocols with management implications\n"
        "• Follow-up recommendations based on imaging findings\n\n"
        
        "CRITICAL REQUIREMENTS:\n"
        "• ADULT radiology only (age 16+) - EXCLUDE pediatric systems (SFU, UTD)\n"
        "• UK guidelines FIRST (RCR, NICE, BIR, British societies) - international sources supplement\n"
        "• PRIORITIZE reputable sources: professional societies, academic institutions, peer-reviewed guidelines\n"
        "• DISCARD or de-prioritize low-quality sources: blogs, forums, non-peer-reviewed content\n"
        "• Use only provided search evidence - weight higher-quality sources more heavily\n\n"
        
        "CRITICAL: Guideline must match ALL three components of the finding: (1) anatomy, (2) pathology, (3) imaging finding. "
        "ANY mismatch = incompatible. Shared terminology does not imply compatibility. "
        "Only synthesize information matching the finding's complete definition.\n\n"
        
        "SOURCE QUALITY PRIORITY:\n"
        "1. UK professional societies (RCR, NICE, BIR, British specialty societies)\n"
        "2. International professional societies (RSNA, ACR, ECR, etc.)\n"
        "3. Academic institutions and peer-reviewed sources (Radiopaedia, PubMed)\n"
        "4. Use lower-quality sources only if no reputable sources available\n\n"
        
        "CRITICAL - OUTPUT FORMAT:\n"
        "• All string fields (diagnostic_overview, finding) must be DIRECT STRING VALUES, not wrapped in objects\n"
        "• Example: diagnostic_overview: 'Text here' NOT diagnostic_overview: {'text': 'Text here'}\n"
        "• All array/list fields (classification_systems, measurement_protocols, imaging_characteristics, differential_diagnoses, follow_up_imaging) must be ARRAYS/LISTS, not single objects\n"
        "• Example: follow_up_imaging: [{'indication': '...', 'modality': '...', 'timing': '...'}] NOT follow_up_imaging: {'indication': '...', 'modality': '...', 'timing': '...'}\n"
        "• Example: classification_systems: [{'name': '...', 'grade_or_category': '...', 'criteria': '...'}] NOT classification_systems: {'name': '...', 'grade_or_category': '...', 'criteria': '...'}\n"
        "• Return arrays even if there is only one item: [{...}] not {...}\n"
        "• Return empty arrays [] if no items, not null or missing\n\n"
        
        "RETURN GuidelineEntry WITH:\n\n"
        
        "CRITICAL - ALL REQUIRED FIELDS MUST BE INCLUDED:\n"
        "• ClassificationSystem: name, grade_or_category, criteria (all 3 required)\n"
        "• DifferentialDiagnosis: diagnosis, imaging_features, supporting_findings (all 3 required)\n"
        "• FollowUpImaging: indication, modality, timing (all 3 required)\n"
        "• MeasurementProtocol: parameter, technique (required); normal_range, threshold (optional)\n"
        "• ImagingCharacteristic: feature, description, significance (all 3 required)\n"
        "If any required field is missing, omit the entire object.\n\n"
        
        "1. diagnostic_overview (2-3 sentences):\n"
        "   Direct string value: What this represents on imaging, key features, diagnostic considerations\n\n"
        
        "2. classification_systems (0-2 items - MUST be an array):\n"
        "   ARRAY of ClassificationSystem objects: [{...}, {...}]\n"
        "   Named systems with year (Fleischner 2017, Bosniak 2019, TI-RADS, LI-RADS)\n"
        "   Include grade/category with imaging criteria. Return empty array [] if no criteria/system exists.\n\n"
        
        "3. measurement_protocols (2-4 items - MUST be an array):\n"
        "   ARRAY of MeasurementProtocol objects: [{...}, {...}, {...}]\n"
        "   Specific techniques with numeric thresholds and units that inform management\n"
        "   Focus on actionable thresholds (e.g., 'long axis on axial CT, normal < 10mm, abnormal > 15mm triggers follow-up')\n\n"
        
        "4. imaging_characteristics (4-6 items - MUST be an array):\n"
        "   ARRAY of ImagingCharacteristic objects: [{...}, {...}, {...}, {...}]\n"
        "   Key features with modality-specific details (CT density, MRI signal, US echogenicity)\n"
        "   Emphasize features that impact diagnosis or management decisions\n"
        "   Include technical considerations (phase, windowing) when clinically significant\n\n"
        
        "5. differential_diagnoses (2-4 items - MUST be an array):\n"
        "   ARRAY of DifferentialDiagnosis objects: [{...}, {...}]\n"
        "   Diagnoses WITH distinguishing imaging features\n"
        "   Focus: 'How to tell them apart on imaging'\n\n"
        
        "6. follow_up_imaging (if applicable - MUST be an array):\n"
        "   ARRAY of FollowUpImaging objects: [{...}] or [{...}, {...}]\n"
        "   Return as array even if only one item: [{...}] NOT {...}\n"
        "   Return empty array [] if not applicable, not null\n"
        "   Modality, timing from UK guidelines, technical parameters\n"
        "   Focus on recommendations that guide patient management\n\n"
        
        "EMPHASIZE: Significant/impactful criteria, actionable thresholds, classification systems that inform care, UK adaptations\n"
        "PRIORITIZE: Information that supports diagnostic decisions or directs management pathways"
    )

    perplexity_client = Perplexity()
    guidelines_results: List[dict] = []
    total_sources = 0
    # Track which models were used
    query_models_used = set()
    synthesis_models_used = set()

    for idx, consolidated_finding in enumerate(consolidated_result.findings, start=1):
        print(f"  └─ Processing consolidated finding {idx}: {consolidated_finding.finding}")

        # Generate cache key prefix using extracted finding text hash + finding index
        # This enables cache reuse across users with the same findings (much higher hit rate)
        # Normalize finding text for consistent hashing
        finding_text_normalized = consolidated_finding.finding.strip().lower()
        finding_text_hash = hashlib.sha256(finding_text_normalized.encode('utf-8')).hexdigest()
        finding_cache_prefix = f"{finding_text_hash}:finding_{idx}"
        print(f"      [CACHE DEBUG] Finding text hash: {finding_text_hash[:16]}... (finding: '{consolidated_finding.finding[:50]}...')")
        
        # Generate 2-3 focused search queries using AI
        # Cache based on extracted finding text hash (enables cross-user cache reuse)
        cache = get_cache()
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
        
        query_models_used.add(query_model)
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
            continue
        
        # Log which fallback level was used
        if fallback_attempt > 1:
            print(f"      ⚠️  Used fallback level {fallback_attempt} (less restrictive filtering)")

        # Check cache for compatibility filtering (cache based on report content + search_results)
        search_results_hash = generate_search_results_hash(search_results)
        filter_cache_key = f"compat_filter:{finding_cache_prefix}:{search_results_hash}"
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
            continue

        total_sources += len(search_results)
        print(f"      Retrieved {len(search_results)} compatible search results")

        # Build evidence context
        context_lines = []
        for rank, item in enumerate(search_results[:12], start=1):
            title = (item.get("title") or "").strip()
            snippet = (item.get("snippet") or "").strip()
            if snippet and len(snippet) > 280:
                snippet = snippet[:277].rstrip() + "..."
            url = (item.get("url") or "").strip()
            query = (item.get("query") or "").strip()
            context_lines.append(f"[{rank}] Query: {query}\nTitle: {title}\nSummary: {snippet}\nURL: {url}\n")

        evidence_block = "\n".join(context_lines) if context_lines else "No supporting evidence."

        # Check cache for guideline synthesis (cache based on report content + search_results)
        synthesis_cache_key = f"guideline_synth:{finding_cache_prefix}:{search_results_hash}"
        print(f"      [CACHE DEBUG] Checking guideline synthesis cache with key: {synthesis_cache_key[:80]}...")
        cached_synthesis = cache.get(synthesis_cache_key)
        
        if cached_synthesis is not None:
            print(f"      [CACHE HIT] Using cached guideline synthesis")
            print(f"      [CACHE DEBUG] Cache key: {synthesis_cache_key[:80]}...")
            # Reconstruct GuidelineEntry from cached dict if needed
            if isinstance(cached_synthesis, dict):
                guideline_entry_raw = GuidelineEntry(**cached_synthesis)
            else:
                guideline_entry_raw = cached_synthesis
            synthesis_model = "cached"  # Mark as cached
        else:
            print(f"      [CACHE MISS] Executing guideline synthesis")
            print(f"      [CACHE DEBUG] Cache key: {synthesis_cache_key[:80]}...")
            
            # Guidelines synthesis prompt
            queries_text = "\n".join(f"  {i}. {q}" for i, q in enumerate(queries, 1))
            prompt = (
                f"Consolidated finding: {consolidated_finding.finding}\n"
                f"Search queries used:\n{queries_text}\n\n"
                f"SEARCH EVIDENCE:\n{evidence_block}\n\n"
                "Return a GuidelineEntry JSON object with radiologist-focused diagnostic information."
            )

            try:
                # Try primary model first with retry logic
                @with_retry(max_retries=3, base_delay=2.0)
                async def _try_synthesis():
                    # Build model settings with conditional reasoning_effort and max_completion_tokens for Cerebras
                    model_settings = {
                        "temperature": 0.2,
                    }
                    if primary_model == "gpt-oss-120b":
                        model_settings["max_completion_tokens"] = 5000  # Generous token limit for Cerebras
                        model_settings["reasoning_effort"] = "medium"
                        print(f"      └─ Using Cerebras reasoning_effort=medium, max_completion_tokens=5000 for {primary_model}")
                    else:
                        model_settings["max_tokens"] = 4000  # Generous token limit for other models
                    
                    result = await _run_agent_with_model(
                        model_name=primary_model,
                        output_type=GuidelineEntry,
                        system_prompt=guidelines_system_prompt,
                        user_prompt=prompt,
                        api_key=primary_api_key,
                        use_thinking=(primary_provider == 'groq'),  # Enable thinking for Groq models
                        model_settings=model_settings
                    )
                    return result
                
                result = await _try_synthesis()
                synthesis_model = primary_model
                guideline_entry_raw = result.output
                
                # Cache the synthesized guideline (serialize Pydantic model to dict for storage)
                guideline_dict = guideline_entry_raw.model_dump() if hasattr(guideline_entry_raw, 'model_dump') else guideline_entry_raw.dict()
                print(f"      [CACHE DEBUG] Storing guideline with key: {synthesis_cache_key[:80]}...")
                cache.set(synthesis_cache_key, guideline_dict)
                
            except Exception as synthesis_error:
                # Log detailed error information for debugging
                print(f"⚠️ Primary model (Cerebras) error details for finding {idx}:")
                print(f"  └─ Error type: {type(synthesis_error).__name__}")
                print(f"  └─ Error message: {str(synthesis_error)}")
                if hasattr(synthesis_error, 'status_code'):
                    print(f"  └─ Status code: {synthesis_error.status_code}")
                if hasattr(synthesis_error, 'body'):
                    print(f"  └─ Error body: {synthesis_error.body}")
                
                # Primary model failed - try fallback
                fallback_model = MODEL_CONFIG["GUIDELINE_SEARCH_FALLBACK"]
                fallback_provider = _get_model_provider(fallback_model)
                fallback_api_key = _get_api_key_for_provider(fallback_provider)
                
                if _is_parsing_error(synthesis_error):
                    print(f"⚠️ Primary model parsing error for finding {idx} - falling back to {fallback_model}")
                else:
                    print(f"⚠️ Primary model failed after retries for finding {idx} - falling back to {fallback_model}")
                
                try:
                    # Build model settings for fallback (Llama)
                    fallback_model_settings = {
                        "temperature": 0.2,
                        "max_tokens": 4000  # Generous token limit for Llama fallback
                    }
                    
                    # Only enable thinking for Groq models that support reasoning_format (Qwen, not Llama)
                    use_thinking_fallback = (fallback_provider == 'groq' and 'qwen' in fallback_model.lower())
                    
                    result = await _run_agent_with_model(
                        model_name=fallback_model,
                        output_type=GuidelineEntry,
                        system_prompt=guidelines_system_prompt,
                        user_prompt=prompt,
                        api_key=fallback_api_key,
                        use_thinking=use_thinking_fallback,  # Only enable for Qwen models, not Llama
                        model_settings=fallback_model_settings
                    )
                    
                    synthesis_model = fallback_model
                    guideline_entry_raw = result.output
                    print(f"      ✅ Guideline synthesis completed with {synthesis_model} (fallback)")
                    
                    # Cache the synthesized guideline (serialize Pydantic model to dict)
                    guideline_dict = guideline_entry_raw.model_dump() if hasattr(guideline_entry_raw, 'model_dump') else guideline_entry_raw.dict()
                    print(f"      [CACHE DEBUG] Storing guideline (fallback) with key: {synthesis_cache_key[:80]}...")
                    cache.set(synthesis_cache_key, guideline_dict)
                    
                except Exception as fallback_error:
                    print(f"❌ Both primary and fallback models failed for finding {idx}: {fallback_error}")
                    continue

        synthesis_models_used.add(synthesis_model)
        guideline_entry: GuidelineEntry = guideline_entry_raw
        print(f"      Generated guideline: {guideline_entry.diagnostic_overview[:160]}...")

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
            continue

        guideline_entry = guideline_entry.model_copy(
            update={"finding_number": idx, "finding": consolidated_finding.finding}
        )

        # Build new radiologist-focused markdown
        guideline_markdown = build_radiologist_guideline_markdown(guideline_entry)

        # Build sources (organic only - no hardcoded fallbacks)
        sources = []
        for item in search_results[:10]:
            sources.append({
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "snippet": "",
                "domain": item.get("domain", ""),
                "query": item.get("query", ""),
            })

        # Extract unique domains (no fallback)
        unique_domains = list(dict.fromkeys(
            source["domain"] for source in sources if source.get("domain")
        ))
        discovered_bodies = [
            {"name": domain, "domain": domain, "reason": "Referenced in search evidence", "priority": "medium"}
            for domain in unique_domains[:3]
        ]
        body_names = unique_domains[:3]

        # Debug logging for structured fields
        print(f"📊 DEBUG - Guideline for '{consolidated_finding.finding}':")
        print(f"  classification_systems: {len(guideline_entry.classification_systems)} items")
        if guideline_entry.classification_systems:
            for cs in guideline_entry.classification_systems:
                print(f"    • {cs.name} - {cs.grade_or_category}")
        else:
            print(f"    (empty)")
        print(f"  measurement_protocols: {len(guideline_entry.measurement_protocols)} items")
        print(f"  imaging_characteristics: {len(guideline_entry.imaging_characteristics)} items")
        print(f"  differential_diagnoses: {len(guideline_entry.differential_diagnoses)} items")
        print(f"  follow_up_imaging: {len(guideline_entry.follow_up_imaging or [])} items")
        if guideline_entry.follow_up_imaging:
            for fi in guideline_entry.follow_up_imaging:
                print(f"    • {fi.modality} at {fi.timing}")
        else:
            print(f"    (empty)")
        
        guidelines_results.append({
            "finding": {
                "finding": consolidated_finding.finding,
                "guideline_focus": "diagnostic imaging guidance",
                "specialty": "general radiology",
                "search_query": " | ".join(queries),  # Show all queries used
            },
            "discovered_bodies": discovered_bodies,
            "body_names": body_names,
            "reasoning": "Synthesized from UK-focused multi-query search evidence",
            "guideline_summary": guideline_markdown,
            "diagnostic_overview": guideline_entry.diagnostic_overview,
            "sources": sources[:5],
            # New structured fields
            "classification_systems": [cs.model_dump() for cs in guideline_entry.classification_systems],
            "measurement_protocols": [mp.model_dump() for mp in guideline_entry.measurement_protocols],
            "imaging_characteristics": [ic.model_dump() for ic in guideline_entry.imaging_characteristics],
            "differential_diagnoses": [dd.model_dump() for dd in guideline_entry.differential_diagnoses],
            "follow_up_imaging": [fi.model_dump() for fi in (guideline_entry.follow_up_imaging or [])],
        })

    elapsed = time.time() - start_time
    # Build model summary string
    query_models_str = ", ".join(sorted(query_models_used)) if query_models_used else "none"
    synthesis_models_str = ", ".join(sorted(synthesis_models_used)) if synthesis_models_used else "none"
    models_summary = f"Query: {query_models_str} | Synthesis: {synthesis_models_str}"
    print(f"search_guidelines_for_findings: Completed with {len(guidelines_results)} guidelines from {total_sources} sources in {elapsed:.2f}s ({models_summary})")
    return guidelines_results


async def _analyze_completeness_with_model(
    model_name: str,
    model_label: str,
    report_content: str,
    guidelines_data: List[dict],
    api_key: str
) -> dict:
    """
    Helper function to analyze report completeness with specified model.
    Model selection is driven by MODEL_CONFIG - supports any configured model.
    
    Args:
        model_name: Model identifier (e.g., "qwen/qwen3-32b", "claude-sonnet-4-20250514")
        model_label: Human-readable model name for logging
        report_content: The report text
        guidelines_data: Guidelines found for the report
        api_key: API key for the model provider
    
    Returns:
        Dictionary with analysis and structured feedback
    """
    import os
    
    start_time = time.time()
    print(f"analyze_report_completeness: Attempting with {model_label}...")
    print(f"  └─ Received {len(guidelines_data)} guideline entries for completeness analysis")
    
    provider = _get_model_provider(model_name)
    
    system_prompt = (
        "CRITICAL: You MUST use British English spelling and terminology throughout all output.\n\n"
        "You are an expert radiologist reviewing imaging reports for quality and completeness "
        "of findings documentation.\n\n"
        "Your role is to assess whether the radiologist has:\n"
        "• Systematically documented all imaging findings visible on the study\n"
        "• Clearly described anatomic locations, measurements, and characteristics\n"
        "• Provided appropriate differential considerations based on imaging alone\n"
        "• Communicated findings clearly for clinical application\n\n"
        "Do NOT evaluate whether clinical information is provided or whether clinical context "
        "is present in the report. The radiologist interprets the imaging; clinical correlation "
        "is the ordering clinician's responsibility.\n\n"
        "CRITICAL - OUTPUT FORMAT:\n"
        "• All string fields (title, details, id, prompt, patch) must be returned as DIRECT STRING VALUES, not wrapped in objects\n"
        "• Example: title: 'Report Quality Assessment' NOT title: {'text': 'Report Quality Assessment'}\n"
        "• Example: prompt: 'Has the full anatomy been documented?' NOT prompt: {'text': 'Has the full anatomy been documented?'}\n"
        "• Return plain string values for all text fields\n\n"
        "Produce structured feedback with three parts:\n"
        "• Summary – plain-language overview of completeness, clarity, and imaging interpretation quality\n"
        "  - title: Direct string value (≤12 words)\n"
        "  - details: Direct string value (2-3 sentences)\n"
        "• Questions – 2-4 review prompts to verify imaging findings are adequately characterized "
        "(specific to scan modality and anatomic region)\n"
        "  - id: Direct string value (kebab-case identifier)\n"
        "  - prompt: Direct string value (plain sentence, no leading numbering)\n"
        "• Suggested Actions – optional concrete edits when specific wording would improve clarity "
        "of imaging description. Each suggested action MUST include:\n"
        "  - id: Direct string value (kebab-case identifier)\n"
        "  - title: Direct string value (concise action label ≤10 words)\n"
        "  - details: Direct string value (1-2 sentence explanation)\n"
        "  - patch: Direct string value (EXPLICIT TEXT to add/modify in the report)\n\n"
        "IMPORTANT: For suggested_actions, you MUST provide specific, actionable text in the 'patch' field. "
        "Examples:\n"
        "- patch: 'The nodule measures 8 mm in diameter'\n"
        "- patch: 'No aggressive bone lesions or fractures identified'\n"
        "- patch: 'Recommend follow-up CT in 3 months to assess for interval change'\n\n"
        "Always provide a summary. Include questions focused on verification of imaging interpretation. "
        "Only include suggested_actions when specific changes would improve the report's imaging documentation, "
        "and ALWAYS include the actual text patch for each action."
    )
    
    findings_summary = "\n".join(
        f"- {g['finding']['finding']}: {g.get('guideline_summary', '')[:200]}"
        for g in guidelines_data[:3]
    )
    print(f"  └─ Prepared guideline highlights (truncated):\n{findings_summary[:400] or '- None available.'}")
    
    user_prompt = (
        f"REPORT:\n{report_content}\n\n"
        f"GUIDELINE HIGHLIGHTS:\n{findings_summary or '- No guideline highlights available.'}\n\n"
        "Analyze this report for completeness and provide structured feedback."
    )
    
    # Build model settings with conditional reasoning_effort for Cerebras
    model_settings = {
        "temperature": 0,
        "top_p": 1,
    }
    if model_name == "gpt-oss-120b":
        model_settings["max_completion_tokens"] = 2000  # Generous token limit for Cerebras
        model_settings["reasoning_effort"] = "high"
        print(f"  └─ Using Cerebras reasoning_effort=high, max_completion_tokens=2000 for {model_name}")
    else:
        model_settings["max_tokens"] = 1500
    
    result = await _run_agent_with_model(
        model_name=model_name,
        output_type=CompletenessAnalysis,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        use_thinking=(provider == 'groq'),  # Enable thinking for Groq models
        model_settings=model_settings
    )
    
    completeness: CompletenessAnalysis = result.output
    
    elapsed = time.time() - start_time
    print(f"analyze_report_completeness: ✅ Completed with {model_label} in {elapsed:.2f}s")
    print(f"  └─ Summary title: {completeness.summary.title}")
    print(f"  └─ Questions generated: {len(completeness.questions)}")
    print(f"  └─ Suggested actions generated: {len(completeness.suggested_actions)}")
    
    # Convert to format expected by frontend
    return {
        "analysis": f"{completeness.summary.title}\n\n{completeness.summary.details}",
        "structured": {
            "summary": completeness.summary.model_dump(),
            "questions": [q.model_dump() for q in completeness.questions],
            "suggested_actions": [a.model_dump() for a in completeness.suggested_actions],
        }
    }


async def analyze_report_completeness(
    report_content: str,
    guidelines_data: List[dict],
    anthropic_api_key: str | None
) -> dict:
    """
    Analyze report completeness using configured primary model with automatic fallback.
    Model selection is driven by MODEL_CONFIG - supports any configured model.
    
    Args:
        report_content: The report text
        guidelines_data: Guidelines found for the report
        anthropic_api_key: Anthropic API key (for fallback if primary is Anthropic)
    
    Returns:
        Dictionary with analysis and structured feedback
    """
    import os
    
    # Get primary model and provider
    primary_model = MODEL_CONFIG["COMPLETENESS_ANALYZER"]
    primary_provider = _get_model_provider(primary_model)
    
    # Try primary model first with retry logic
    try:
        primary_api_key = _get_api_key_for_provider(primary_provider, anthropic_api_key)
        
        @with_retry(max_retries=3, base_delay=2.0)
        async def _try_primary():
            return await _analyze_completeness_with_model(
                primary_model,
                f"{primary_model} (Completeness Analyzer)",
                report_content,
                guidelines_data,
                primary_api_key
            )
        
        return await _try_primary()
    except Exception as e:
        # Primary failed - determine why and fallback
        fallback_model = MODEL_CONFIG["COMPLETENESS_ANALYZER_FALLBACK"]
        if _is_parsing_error(e):
            print(f"⚠️ {primary_model} parsing error detected - immediate fallback to {fallback_model}")
            print(f"  Error: {type(e).__name__}: {str(e)[:200]}")
        else:
            print(f"⚠️ {primary_model} failed after retries ({type(e).__name__}) - falling back to {fallback_model}")
            print(f"  Error: {str(e)[:200]}")
        
        # Fallback to configured fallback model
        try:
            fallback_provider = _get_model_provider(fallback_model)
            fallback_api_key = _get_api_key_for_provider(fallback_provider, anthropic_api_key)
            
            return await _analyze_completeness_with_model(
                fallback_model,
                f"{fallback_model} (Completeness Analyzer - Fallback)",
                report_content,
                guidelines_data,
                fallback_api_key
            )
        except Exception as fallback_error:
            # Both models failed - return graceful error
            print(f"❌ Both primary and fallback models failed: {type(fallback_error).__name__}")
            import traceback
            print(traceback.format_exc())
            return {
                "analysis": f"Error analyzing report completeness (both {primary_model} and {fallback_model} failed).",
                "structured": {
                    "summary": {"title": "Analysis Error", "details": f"Unable to analyze report with both {primary_model} and {fallback_model}"},
                    "questions": [],
                    "suggested_actions": []
                }
            }


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
   - For findings with TREND (multiple priors): Instruct to integrate full progression pattern with all measurements and dates, not just most recent comparison
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

FINDINGS & IMPRESSION INTEGRATION:
- Integrate comparison language naturally within the Findings section
- For findings with TREND data (multiple priors): Reference the full progression pattern, not just most recent comparison
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
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def _run_agent_with_model(
    model_name: str,
    output_type,
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    use_thinking: bool = False,
    model_settings: dict = None
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
        
        # Create agent
        agent = Agent(
            pydantic_model,
            output_type=output_type,
            system_prompt=system_prompt,
            model_settings=agent_model_settings,
        )
        
        # Build final model settings dict
        final_model_settings = model_settings or {}
        
        # Log model settings for Cerebras to verify reasoning_effort is included
        if provider == 'cerebras':
            print(f"\n🔧 CEREBRAS MODEL SETTINGS ({model_name}):")
            print(f"  └─ temperature: {final_model_settings.get('temperature', 'not set')}")
            if 'max_completion_tokens' in final_model_settings:
                print(f"  └─ max_completion_tokens: {final_model_settings.get('max_completion_tokens', 'not set')}")
            else:
                print(f"  └─ max_tokens: {final_model_settings.get('max_tokens', 'not set')}")
            reasoning_effort = final_model_settings.get('reasoning_effort')
            if reasoning_effort:
                print(f"  └─ reasoning_effort: {reasoning_effort} ✅")
            else:
                print(f"  └─ reasoning_effort: NOT SET ⚠️  (check if parameter is supported)")
        
        # Run agent with error handling for Cerebras to capture raw output
        try:
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
        
        result = await agent.run(
            final_prompt,
            model_settings={
                "temperature": 0.3,
                "max_tokens": 4096,
            }
        )
        
        # Log thinking parts (backend only - not sent to frontend)
        _log_thinking_parts(result, f"{model_label} - Groq/Qwen")
        
        report_output: ReportOutput = result.output
        
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
    signature: str | None = None
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
                model_settings["max_completion_tokens"] = 40960
                model_settings["temperature"] = 0.3
                model_settings["top_p"] = 0.7
                print(f"  └─ Using Cerebras zai-glm-4.7 with max_completion_tokens=40960, temperature=0.3, top_p=0.7 for {primary_model}")
            elif primary_model == "gpt-oss-120b":
                model_settings["max_completion_tokens"] = 6500
                model_settings["reasoning_effort"] = "high"
                print(f"  └─ Using Cerebras reasoning_effort=high, max_completion_tokens=6500 for {primary_model}")
            elif primary_model == "claude-sonnet-4-20250514":
                model_settings["max_tokens"] = 6000
                model_settings["anthropic_thinking"] = {
                    "type": "enabled",
                    "budget_tokens": 2048
                }
                print(f"  └─ Using Claude with thinking enabled, budget_tokens=2048, temperature=1 for {primary_model}")
            else:
                model_settings["max_tokens"] = 6000
            
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
        
        # Log thinking parts for Claude when using extended thinking
        if primary_model == "claude-sonnet-4-20250514":
            _log_thinking_parts(result, f"{primary_model} (Primary) - Claude Extended Thinking")
        
        report_output = result.output
        
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
        
        # LINGUISTIC VALIDATION for zai-glm-4.7 (conditionally enabled)
        if primary_model == "zai-glm-4.7":
            import os
            ENABLE_LINGUISTIC_VALIDATION = os.getenv("ENABLE_ZAI_GLM_LINGUISTIC_VALIDATION", "true").lower() == "true"
            
            if ENABLE_LINGUISTIC_VALIDATION:
                try:
                    print(f"\n{'='*80}")
                    print(f"🔍 LINGUISTIC VALIDATION - Starting for zai-glm-4.7")
                    print(f"{'='*80}")
                    
                    validated_content = await validate_zai_glm_linguistics(
                        report_content=report_output.report_content,
                        scan_type=report_output.scan_type or "",
                        description=report_output.description or ""
                    )
                    
                    report_output.report_content = validated_content
                    print(f"✅ LINGUISTIC VALIDATION COMPLETE")
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
    fallback_model = "claude-sonnet-4-20250514"
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
                model_settings["max_completion_tokens"] = 40960
                model_settings["temperature"] = 0.3
                model_settings["top_p"] = 0.7
                print(f"  └─ Using Cerebras zai-glm-4.7 with max_completion_tokens=40960, temperature=0.3, top_p=0.7 for {primary_model}")
            elif primary_model == "gpt-oss-120b":
                model_settings["max_completion_tokens"] = 6500
                model_settings["reasoning_effort"] = "high"
                print(f"  └─ Using Cerebras reasoning_effort=high, max_completion_tokens=6500 for {primary_model}")
            elif primary_model == "claude-sonnet-4-20250514":
                model_settings["max_tokens"] = 6000
                model_settings["anthropic_thinking"] = {
                    "type": "enabled",
                    "budget_tokens": 2048
                }
                print(f"  └─ Using Claude with thinking enabled, budget_tokens=2048, temperature=0.7 for {primary_model}")
            else:
                model_settings["max_tokens"] = 6000
            
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
        
        # Log thinking parts for Groq models (Cerebras models don't use thinking, use reasoning_effort instead)
        if provider == 'groq':
            _log_thinking_parts(result, f"{primary_model} (Primary) - Groq")
        
        report_output = result.output
        
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
        
        # LINGUISTIC VALIDATION for zai-glm-4.7 (conditionally enabled)
        if primary_model == "zai-glm-4.7":
            import os
            ENABLE_LINGUISTIC_VALIDATION = os.getenv("ENABLE_ZAI_GLM_LINGUISTIC_VALIDATION", "true").lower() == "true"
            
            if ENABLE_LINGUISTIC_VALIDATION:
                try:
                    print(f"\n{'='*80}")
                    print(f"🔍 LINGUISTIC VALIDATION - Starting for zai-glm-4.7")
                    print(f"{'='*80}")
                    
                    validated_content = await validate_zai_glm_linguistics(
                        report_content=report_output.report_content,
                        scan_type=report_output.scan_type or "",
                        description=report_output.description or ""
                    )
                    
                    report_output.report_content = validated_content
                    print(f"✅ LINGUISTIC VALIDATION COMPLETE")
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
    description: str = ""
) -> str:
    """
    Validate and correct linguistic/anatomical errors in zai-glm-4.7 generated reports.
    Uses Cerebras llama-3.3-70b to fix British English grammar, anatomical errors,
    and redundant qualifiers without altering clinical content.
    
    This function addresses specific issues from the Chinese zai-glm-4.7 model:
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
    print(f"\n[LINGUISTIC VALIDATION] Starting linguistic validation for zai-glm-4.7")
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

3. Redundant qualifiers: Remove when measurements specify size
   Example: "Large 5cm stone" → "5 cm stone"

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

10. Finding consolidation: Merge repeated findings into single comprehensive statement
    a) Structural findings: Keep instance with most clinical context, delete sparse mentions
       Example: "Pleural effusion" + later "Moderate effusion with atelectasis" → Keep detailed version only
    
    b) Functional abnormalities: State once with all hemodynamic/structural consequences
       Example: "SAM present" + later "SAM with LVOT obstruction, no MR" → "Systolic anterior motion with dynamic LVOT obstruction. No significant mitral regurgitation."
       Example: "Patent foramen ovale" + later "Small left-to-right shunt" → "Patent foramen ovale with small left-to-right shunt."

11. Passive voice tightening: Use active constructs where natural
    Example: "is present" → direct statement, "is seen" → eliminate
    Example: "Enhancement is present in" → "Enhancement involves"

12. Measurement redundancy: Don't repeat same measurement in different sections
    Example: "22mm hypertrophy" + later "maximum thickness 22mm" → Use once in most detailed context

13. Sequential negatives: Combine related negative findings
    Example: "No thrombus. No aneurysm. No wall thinning." → "No thrombus, aneurysm, or wall thinning."

14. IMPRESSION refinement:
    - Remove symptom-explanatory phrases: "explains the...", "accounts for..."
    - Use clinical synthesis, not descriptive repetition
    - Don't repeat findings in recommendations: "Referral for the calculus" → "Referral recommended"
    - Format: Finding → Diagnosis + differentials → Recommendation
    Example: "5cm calculus explains renal colic" → "Obstructing calculus (5 cm)"

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
    model_name = MODEL_CONFIG["ZAI_GLM_LINGUISTIC_VALIDATOR"]  # llama-3.3-70b
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
- Unfilled {{VAR}} variables: Must remain as "{{VAR}}" exactly
- Do NOT replace with explanatory text like "not specified", "not provided", "not measured"
- Do NOT remove or alter unfilled placeholders
- Post-processing will detect and handle unfilled placeholders
- Examples:
  ✓ KEEP: "diameter xxx mm" (if xxx unfilled)
  ✓ KEEP: "LVEF {{LVEF}}%" (if {{LVEF}} unfilled)
  ✗ NEVER: "diameter xxx mm" → "diameter not specified"
  ✗ NEVER: "{{LVEF}}%" → "LVEF not provided"

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
    follow_template_style = advanced_config.get('follow_template_style', False)
    
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
    """Get format-specific guidance for validator, conditional on organization"""
    
    if format_type == 'prose':
        if organization == 'clinical_priority':
            return """   Style: Flowing prose paragraphs with natural breaks
   - ENSURE paragraph breaks between major anatomical regions or finding types
   - ENSURE grouping of related findings/entities within paragraphs
   - Add paragraph breaks where missing, without reorganizing content
   - Refine sentence quality while maintaining proper paragraph structure"""
        else:  # template_order
            return """   Style: Flowing prose paragraphs with natural breaks
   - ENSURE paragraph breaks aligned with template's anatomical sections
   - ENSURE template's structural organization in paragraph breaks
   - Add paragraph breaks where missing, without reorganizing content
   - Refine sentence quality while maintaining proper paragraph structure"""
    
    # Non-prose formats remain unchanged
    guides = {
        'bullets': """   Style: Bullet points (•)
   - PRESERVE existing bullet structure (already generated)
   - Refine wording within each bullet
""",
        'numbered': """   Style: Numbered list (1., 2., 3.)
   - PRESERVE existing numbered structure (already generated)
   - Refine wording within each item
""",
        'headers': """   Style: Anatomical headers with content
   - PRESERVE existing header structure (already generated)
   - Refine content under each header
"""
    }
    
    return guides.get(format_type, guides['prose'])


# Removed _get_comparison_guidance - comparisons now handled within verbosity_style principles


