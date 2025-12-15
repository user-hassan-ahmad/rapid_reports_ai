# Auto Report Generation and Validation Mechanism - Summary

## Overview
The auto report generation system creates NHS radiology reports from user inputs (findings, clinical history, scan type) using AI models with **Structure Validation** (synchronous) that runs before returning the response.

---

## Flow Diagram

```
User Request (POST /api/chat)
    ↓
1. Load Prompt Template
   - Use case: "radiology_report"
   - Load from: prompts/radiology_report/gptoss.json (if primary model is gpt-oss-120b)
   - Extract system_prompt and template
   - Render template with variables (FINDINGS, CLINICAL_HISTORY, SCAN_TYPE)
    ↓
2. Generate Report (generate_auto_report)
   - Primary Model: gpt-oss-120b (Cerebras GPT-OSS-120B)
   - Fallback Model: claude-sonnet-4-20250514 (if primary fails)
   - Output: ReportOutput { report_content, description, scan_type }
   - Append user signature programmatically
    ↓
3. Structure Validation (SYNCHRONOUS - blocks response)
   - Model: gpt-oss-120b (STRUCTURE_VALIDATOR)
   - Fallback: qwen/qwen3-32b (if primary fails)
   - Checks: redundancy, duplication, prose flow, impression verbosity, structure
   - If violations found → Apply fixes using ACTION_APPLIER model
   - Returns: StructureValidationResult with violations and fixes
    ↓
4. Save Report to Database (if auto-save enabled)
   - Create report record
    ↓
5. Return Response to User
   - report_content (validated and fixed)
   - model used
```

---

## Detailed Flow Breakdown

### 1. API Endpoint: `/api/chat`

**Location**: `backend/src/rapid_reports_ai/main.py` (lines 467-799)

**Request Format**:
```json
{
  "message": "User message",
  "use_case": "radiology_report",
  "variables": {
    "FINDINGS": "...",
    "CLINICAL_HISTORY": "...",
    "SCAN_TYPE": "..."
  },
  "model": "claude"  // Kept for compatibility, always uses Claude/configured primary
}
```

**Key Steps**:
1. **Prompt Loading** (lines 484-523):
   - Uses `PromptManager` to load prompt from `prompts/radiology_report/`
   - If primary model is `gpt-oss-120b`, loads `gptoss.json`
   - Otherwise falls back to `unified.json` or model-specific file
   - Extracts `system_prompt` and `template`
   - Renders template with provided variables

2. **Report Generation** (lines 540-546):
   - Calls `generate_auto_report()` with:
     - Model: Always uses configured `PRIMARY_REPORT_GENERATOR` (gpt-oss-120b)
     - System prompt: From loaded prompt data
     - User prompt: Rendered template with variables
     - Signature: User's signature from database

3. **Structure Validation** (lines 548-702):
   - Controlled by `ENABLE_STRUCTURE_VALIDATION` env var (default: true)
   - Synchronous validation before returning response
   - If violations found, applies fixes using `ACTION_APPLIER` model

4. **Report Saving** (lines 714-770):
   - Saves to database if auto-save enabled

---

### 2. Report Generation: `generate_auto_report()`

**Location**: `backend/src/rapid_reports_ai/enhancement_utils.py` (lines 2839-2959)

**Function Signature**:
```python
async def generate_auto_report(
    model: str,              # Kept for API compatibility
    user_prompt: str,        # Rendered template with variables
    system_prompt: str,      # System prompt from PromptManager
    api_key: str,            # API key (determined automatically)
    signature: str | None    # User signature to append
) -> ReportOutput
```

**Model Configuration**:
- **Primary**: `MODEL_CONFIG["PRIMARY_REPORT_GENERATOR"]` = `"gpt-oss-120b"` (Cerebras GPT-OSS-120B)
- **Fallback**: `MODEL_CONFIG["FALLBACK_REPORT_GENERATOR"]` = `"claude-sonnet-4-20250514"`

**Model Settings**:
- **Cerebras (gpt-oss-120b)**:
  - `temperature`: 0
  - `max_completion_tokens`: 6500
  - `reasoning_effort`: "high"
- **Claude/Others**:
  - `temperature`: 0
  - `max_tokens`: 6500

**Process**:
1. Removes `{{SIGNATURE}}` placeholder from prompt (signature appended programmatically)
2. Calls primary model with retry logic (3 retries, 2s base delay)
3. If primary fails → falls back to Claude Sonnet 4
4. Appends signature to `report_content` programmatically
5. Returns `ReportOutput` with:
   - `report_content`: Full report text
   - `description`: 5-15 word summary (max 150 chars)
   - `scan_type`: Extracted scan type with protocol

**Output Structure** (`ReportOutput`):
```python
class ReportOutput(BaseModel):
    report_content: str      # Complete report text
    description: str          # Brief summary (5-15 words, max 150 chars)
    scan_type: str | None    # Scan type with protocol (e.g., "CT head non-contrast")
```

---

### 3. Structure Validation: `validate_report_structure()`

**Location**: `backend/src/rapid_reports_ai/enhancement_utils.py` (lines 3178-3368)

**Function Signature**:
```python
async def validate_report_structure(
    report_content: str,      # Generated report content
    scan_type: str,          # Extracted scan type
    findings: str            # Original findings input
) -> StructureValidationResult
```

**Model Configuration**:
- **Primary**: `MODEL_CONFIG["STRUCTURE_VALIDATOR"]` = `"gpt-oss-120b"`
- **Fallback**: `MODEL_CONFIG["STRUCTURE_VALIDATOR_FALLBACK"]` = `"qwen/qwen3-32b"`

**Model Settings**:
- **Cerebras (gpt-oss-120b)**:
  - `temperature`: 0.1
  - `max_completion_tokens`: 2000
  - `reasoning_effort`: "medium"
- **Qwen/Others**:
  - `temperature`: 0.1
  - `max_tokens`: 2000

**Validation Rules** (from prompt, lines 3227-3264):

**Content Rules**:
1. **NO REDUNDANCY**: Same information stated multiple times (even in different words)
2. **NO DUPLICATION**: Each anatomical structure mentioned only once. Pertinent negatives not repeated
3. **INFORMATION DENSITY**: Every sentence must add new information
4. **IMPRESSION PURPOSE**:
   - Maximum 2 bullets, 1-2 sentences each
   - Must include: Diagnostic conclusions, actionable recommendations, urgent incidental findings
   - Must NOT include: Descriptive qualifiers, benign incidentals below action threshold

**Structure Rules**:
5. **PATHOLOGY-CENTRIC ORGANIZATION**: Pathology paragraphs expand outward (pathology → complications → pertinent negatives)
6. **REMAINING ANATOMY SCOPE**: Only cover structures NOT mentioned in pathology paragraphs

**Style Rules**:
7. **FLOWING PROSE**: Cohesive integration, not choppy list-like sentences
8. **BREVITY**: Remaining anatomy paragraphs: 2-3 sentences max

**Output Structure** (`StructureValidationResult`):
```python
class StructureValidationResult(BaseModel):
    is_valid: bool
    violations: List[StructureViolation]

class StructureViolation(BaseModel):
    location: str      # e.g., "Findings paragraph 2", "Impression"
    issue: str        # Description of violation
    fix: str          # Specific fix instruction
```

**Fix Application** (if violations found):
- Uses `MODEL_CONFIG["ACTION_APPLIER"]` = `"gpt-oss-120b"`
- System prompt instructs to apply fixes EXACTLY as specified
- Preserves grammatical completeness and report structure
- Returns refined report content

---


---

## Prompt Details

### Prompt File Structure

**Location**: `backend/src/rapid_reports_ai/prompts/radiology_report/`

**Files**:
- `metadata.json`: Use case metadata (name, description, variables)
- `gptoss.json`: Prompt template for GPT-OSS-120B model
- `unified.json`: Fallback prompt template

### Prompt Loading Logic

**Location**: `backend/src/rapid_reports_ai/prompt_manager.py`

**Selection Logic** (lines 51-74):
1. If `primary_model == "gpt-oss-120b"` → Try `gptoss.json`
2. Otherwise → Try `unified.json`
3. Fallback → Try `{model}.json` (e.g., `claude.json`)

### Prompt Template: `gptoss.json`

**Structure**:
```json
{
  "system_prompt": "You are an expert NHS consultant radiologist...",
  "template": "=== CASE DATA - USER INPUTS ===\n<scan_type>{{SCAN_TYPE}}</scan_type>..."
}
```

**Key Components**:

1. **System Prompt**:
   - Role: Expert NHS consultant radiologist
   - Language: British English
   - Report structure: Comparison → Limitations → Findings → Impression
   - Two-phase approach: REASONING (internal) → GENERATION (JSON output)

2. **Template Structure**:
   - **PHASE 1: CLINICAL REASONING**:
     - Input extraction (prior imaging, limitations)
     - Clinical question understanding
     - Protocol verification (modality-specific terminology)
     - Anatomical scope enumeration
     - Findings significance analysis
     - Impression synthesis
     - Structure planning
   
   - **PHASE 2: REPORT GENERATION**:
     - Output format: JSON with `report_content`, `description`, `scan_type`
     - Report structure:
       - **Comparison**: Prior imaging or "No previous imaging available"
       - **Limitations**: Technical factors (omit if none)
       - **Findings**: Pathology paragraphs + Remaining anatomy paragraphs
       - **Impression**: Maximum 2 bullets, diagnostic conclusions only

3. **Writing Principles**:
   - Flowing prose (not telegraphic)
   - Information density (every sentence adds value)
   - No redundancy (same meaning = duplication)
   - Brevity (more detail for pathology, minimal for normals)
   - Comprehensive (all visible regions addressed)

4. **Anti-Redundancy Principles**:
   - Don't state obvious implications
   - Don't list information already conveyed
   - Don't repeat negatives globally
   - Don't restate same fact with different terminology

---

## Model Configuration

**Location**: `backend/src/rapid_reports_ai/enhancement_utils.py` (lines 59-91)

**Key Models Used**:
- **PRIMARY_REPORT_GENERATOR**: `gpt-oss-120b` (Cerebras GPT-OSS-120B)
- **FALLBACK_REPORT_GENERATOR**: `claude-sonnet-4-20250514`
- **STRUCTURE_VALIDATOR**: `gpt-oss-120b`
- **STRUCTURE_VALIDATOR_FALLBACK**: `qwen/qwen3-32b`
- **ACTION_APPLIER**: `gpt-oss-120b`

**Model Providers**:
- **Cerebras**: `gpt-oss-120b` (via OpenAI-compatible API)
- **Anthropic**: `claude-sonnet-4-20250514`
- **Groq**: `qwen/qwen3-32b`, `llama-3.3-70b-versatile`

---

## Environment Variables

**Validation Control**:
- `ENABLE_STRUCTURE_VALIDATION`: Enable/disable synchronous structure validation (default: "true")

**API Keys**:
- `ANTHROPIC_API_KEY`: For Claude models
- `GROQ_API_KEY`: For Groq models (Qwen, Llama)
- `OPENAI_API_KEY`: For Cerebras GPT-OSS-120B (if using OpenAI-compatible endpoint)

---

## Error Handling & Retry Logic

**Retry Mechanism**:
- All model calls wrapped with `@with_retry(max_retries=3, base_delay=2.0)`
- Exponential backoff on failures
- Automatic fallback to secondary models on parsing errors or failures

**Fallback Strategy**:
1. Primary model fails → Try fallback model
2. If fallback fails → Raise exception with context from both failures
3. Parsing errors trigger immediate fallback (no retries)

---

## Database Integration

**Report Saving**:
- Saves report with `report_type="auto"`
- Stores `input_data` (message, variables, extracted_scan_type)
- Tracks `model_used` and `use_case`
- Creates `description` from report output

**Validation Status**:
- `validation_status`: "pending" → "valid" / "invalid"
- `violations_count`: Number of violations found
- Updated asynchronously by background validation task

---

## Summary

The auto report generation system uses **synchronous structure validation** that runs before returning the response:

1. **Synchronous Structure Validation**: Runs before returning response, checks for redundancy, duplication, prose quality, and impression verbosity. Applies fixes immediately if violations found.

The system uses **Cerebras GPT-OSS-120B** as the primary model for generation and validation, with **Claude Sonnet 4** and **Qwen 3-32B** as fallbacks. All models are configured centrally via `MODEL_CONFIG` dictionary for easy swapping.

