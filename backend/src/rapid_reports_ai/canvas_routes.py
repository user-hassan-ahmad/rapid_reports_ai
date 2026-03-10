"""Canvas routes for intelligent dictation — section generation and transcript processing."""

import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import get_current_user
from .database.models import User
from .enhancement_utils import (
    MODEL_CONFIG,
    _get_api_key_for_provider,
    _get_model_provider,
    _run_agent_with_model,
)

canvas_router = APIRouter(prefix="/api/canvas", tags=["canvas"])


# -----------------------------------------------------------------------------
# Pydantic Models
# -----------------------------------------------------------------------------


class SectionGenerateRequest(BaseModel):
    scan_type: str
    clinical_history: str


class SectionsFromTemplateRequest(BaseModel):
    template_content: str


class SectionGenerateResponse(BaseModel):
    sections: list[str]


class CanvasProcessRequest(BaseModel):
    session_transcript: str
    scratchpad_content: str
    scan_type: str = ""
    clinical_history: str = ""
    preferred_section_names: list[str] = []


class IntelliPrompt(BaseModel):
    question: str
    source_text: str
    rationale: str = ""


class CanvasProcessResponse(BaseModel):
    scratchpad: str
    covered_sections: list[str] = []


class CanvasReviewRequest(BaseModel):
    scratchpad_content: str
    checklist_sections: list[str] = []
    existing_prompts: list[str] = []
    scan_type: str = ""
    clinical_history: str = ""


class CanvasReviewResponse(BaseModel):
    covered_sections: list[str]
    prompts: list[IntelliPrompt] = []


class CoverageOnlyResponse(BaseModel):
    covered_sections: list[str] = []


class PromptsOnlyResponse(BaseModel):
    prompts: list[IntelliPrompt] = []


# -----------------------------------------------------------------------------
# Prompts
# -----------------------------------------------------------------------------

SECTIONS_SYSTEM_PROMPT = """You are a radiology report structure assistant. Your only task is to return an ordered JSON array of anatomical section names for a radiology report."""

SECTIONS_USER_PROMPT_TEMPLATE = """Scan type: {scan_type}
Clinical history: {clinical_history}

## PRE-OUTPUT ANALYSIS

Before producing the list, reason through the following steps. Do not include this analysis in the output — use it to inform the final array:

1. **Field of view**: What anatomical region does this scan cover from superior to inferior extent? Include incidentally imaged structures at the periphery of the field (e.g. lung bases on an abdominal CT, visualised upper abdomen on a chest CT, included joints at the extremes of an MSK scan).

2. **Full structure enumeration**: List every discrete anatomical structure or system present within that field of view — including incidentally included regions.

3. **Grouping decisions**: Consolidate structures into functional anatomical systems as a radiologist would think of them. The guiding principle: a section represents a system you would assess as a single coherent unit at the workstation. Structures that share the same parenchyma, lumen, or immediate anatomical relationship and are always reviewed together belong in one section. Structures with distinct pathology profiles, independent clinical significance, or separate reporting conventions warrant their own section — even if adjacent. A single organ with multiple distinct compartments (e.g. a joint with bone, cartilage, and soft tissue) may warrant one section covering the whole system rather than sub-sections for each compartment. Never create a section for a single anatomical sub-unit that would only ever be mentioned within a broader system assessment.

4. **Order**: Arrange the final groups in the sequence a radiologist would naturally dictate — lead with the primary focus given the clinical history, then sweep remaining structures logically by anatomical region.

5. **Granularity check**: The list should feel like a structured reporting template — comprehensive but clean. Every clinically distinct system should have its own entry; no system should be buried inside another. Avoid micro-sections for individual ligaments, ducts, spaces, or sub-structures that are always reported as part of a parent system.

## OUTPUT RULES

- Uppercase section names only, using spaces not underscores (e.g. "COMMON BILE DUCT" not "COMMON_BILE_DUCT")
- Do NOT include TECHNIQUE, BACKGROUND, IMPRESSION, or CONCLUSION
- Return a JSON array of strings"""

SECTIONS_FROM_TEMPLATE_SYSTEM_PROMPT = """You are a radiology report structure assistant. Your only task is to extract anatomical section headers from a FINDINGS template and return them as an ordered JSON array."""

SECTIONS_FROM_TEMPLATE_USER_PROMPT_TEMPLATE = """Below is the FINDINGS template content from a radiology report template. It may contain section headers (e.g. "Lungs:", "Pleura:", "CHEST WALL:", bullet lists with organ names, or prose with embedded structure).

Extract the distinct anatomical section/organ names that the template expects the radiologist to cover. Return them in the order they appear in the template. Use UPPERCASE for consistency (e.g. LUNGS, PLEURA, CHEST WALL).

Rules:
- Only include anatomical structures/systems — no TECHNIQUE, BACKGROUND, IMPRESSION, or CONCLUSION
- Preserve the template's intended order
- If the template has no clear section structure, return a sensible default list based on the content (e.g. ["FINDINGS"])

FINDINGS template content:
---
{template_content}
---

Return a JSON array of uppercase section names."""


CANVAS_PROCESS_SYSTEM_PROMPT = """You are a clinical findings extractor for a radiology dictation system. You receive the FULL session transcript (everything the radiologist has said so far in this dictation session) and the current state of a structured scratchpad. Your job is to produce the COMPLETE updated scratchpad and determine checklist coverage.

TRANSCRIPTION CORRECTION
The transcript comes from speech-to-text. Correct obvious homophones and phonetic approximations using radiology knowledge: "white base" → lung base, "speculated" → spiculated, "bile duck" → bile duct, "Bosnia" → Bosniak, etc. Apply corrections when producing the scratchpad content.

EXTRACTION RULES
- Preserve all measurements (numerals for numbers, units: cm, mm, HU), laterality (left, right, bilateral), anatomical locations, clinical descriptors, staging, negative findings, temporal comparators, qualifiers ("suspicious for", "consistent with", "cannot exclude", "in keeping with").
- Preserve specific pathology terms: consolidation, ground-glass opacity, nodule, mass, lymphadenopathy, effusion, atelectasis, fibrosis, cavitation, necrosis, haemorrhage, oedema, infiltration, collapse, pneumothorax, etc. NEVER replace with vague terms like "involvement", "changes", "abnormality".
- Discard filler, navigation preamble, hedges ("I think there's", "it looks like"), conversational confirmations. On self-correction ("no wait", "actually", "I mean"), output only the corrected content.
- CONSOLIDATION: If a new transcript segment adds detail, qualification, or measurement to a finding already in the scratchpad, UPDATE that existing bullet — do not add a duplicate. Example: scratchpad has "- Gallbladder distended" and transcript adds "wall thickening and pericholecystic fluid" → merge into "- Gallbladder distended with wall thickening and pericholecystic fluid". Only create a new bullet if the new content is genuinely a separate, independent finding about a different aspect of the same organ.
- CONTRADICTIONS: When a later finding contradicts or supersedes an earlier one, remove the superseded statement and replace with the new one. Example: scratchpad has "- Lungs appear clear" but transcript adds "spiculated nodule in right upper lobe" → remove the clear lungs bullet and add the nodule. A blanket negative is always superseded by a specific positive finding in the same region.

SCRATCHPAD FORMAT
Plain bulleted list — no section headers in the text itself.
- One finding per line, each prefixed with `- `
- Group findings from the same anatomical system together, separated by a blank line between groups
- Follow standard radiology order: technique/limitations first, then anatomical systems, background last
- Plain text only. Do NOT use: horizontal rules (---, ***), bold (**text**), italics, or any markdown. Formatting characters will break the display.
- Example:
  - IV contrast administered; no prior imaging for comparison

  - Gallbladder distended with mural oedema
  - 2 mm calculus at the CBD with upstream biliary dilatation

  - Increased T2 signal in pancreatic head with surrounding fluid

ONE SYSTEM PER FINDING: Every finding belongs to exactly one anatomical group. Never repeat a finding under a second group. Choose the most anatomically specific owner.

COVERED SECTIONS: After writing the scratchpad, return in covered_sections the names from preferred_section_names that are now meaningfully addressed. Use the EXACT name strings from preferred_section_names — do not invent or paraphrase. Clinical judgment applies: a system with a negative finding ("unremarkable", "no focal lesion") counts as covered. Only include sections with substantive content.

OUTPUT
Return the complete scratchpad and the covered_sections list (exact names from preferred_section_names)."""


CANVAS_COVERAGE_SYSTEM_PROMPT = """You are a radiology checklist coverage checker. Given a dictation scratchpad and a list of expected anatomical sections, determine which sections have been meaningfully addressed.

COVERAGE RULE: A section is covered only when the radiologist has made a definitive statement about that structure — a finding, impression, or explicit qualifier ("normal", "unremarkable", "no focal lesion", "clear", "within normal limits", "NAD"). A bare anatomical name with no qualifier does NOT count as covered. Clinical shorthand counts (e.g. "uterus NAD", "cervix clear", "no adnexal mass", "liver unremarkable").

Use the EXACT name strings from the checklist — do not invent or paraphrase. Return only covered_sections."""


CANVAS_COVERAGE_USER_PROMPT_TEMPLATE = """Scratchpad:
---
{scratchpad_content}
---

Checklist sections to check: {checklist_sections}

Return which sections from the checklist are covered."""


CANVAS_INTELLIPROMPTS_SYSTEM_PROMPT = """You are a radiology decision-support assistant reviewing a dictation scratchpad. You are advising a radiologist who is actively at the workstation with the images in front of them. The scratchpad is a plain bulleted list of imaging findings grouped by anatomical system, separated by blank lines.

Your task: Identify imaging structures or features the radiologist has NOT yet reviewed but SHOULD, given what is already documented. You are directing their eyes back to the scan — not asking about clinical history, symptoms, or documentation.

CARDINAL RULE: Every IntelliPrompt must direct the radiologist to look at or assess a specific IMAGING STRUCTURE or FEATURE on the scan. Never ask about clinical symptoms (fever, pain, jaundice), patient history, or whether something has been "documented". The radiologist is looking at images — ask them to look at something they may have missed.

SELF-CHECK before writing any prompt: "Is this imaging feature already assessed somewhere in the scratchpad?" If yes, DO NOT generate the prompt.

THRESHOLD — only generate a prompt if ALL of these apply:
- A documented finding implies a related structure or feature that should be reviewed but has not been mentioned in the scratchpad
- Reviewing it would change the imaging diagnosis, urgency classification, or report impression
- The finding or structure is genuinely absent from the scratchpad

DO NOT generate for:
- Any structure or feature already described in the scratchpad, even partially
- Re-confirming a finding already present (never ask "is there biliary dilatation?" if it is documented)
- Isolated incidental findings with no meaningful imaging consequence
- Negated structures: "no X", "clear", "normal", "unremarkable", "not identified"
- Clinical or laboratory correlation requests — you only direct the gaze, not the clerk

DO generate for (radiology-specific imaging targets):
- A documented finding whose local complications on imaging are unassessed (e.g. acute appendicitis documented → "Appendix tip and base reviewed for perforation, abscess, or free gas?")
- A finding that raises a specific imaging differential requiring targeted review (e.g. spiculated lung nodule → "Mediastinal and hilar nodes assessed for lymphadenopathy? Adrenals and liver reviewed for metastatic deposits?")
- A pattern of findings where a key structure completing the picture has not been assessed (e.g. CBD calculus + intrahepatic biliary dilatation → "Gallbladder wall and pericholecystic fat reviewed for secondary cholecystitis? Liver parenchyma assessed for biliary abscess?")
- A finding with known imaging spread patterns not yet reviewed (e.g. portal vein thrombosis → "Superior mesenteric vein and splenic vein assessed for propagation? Bowel wall reviewed for ischaemia?")
- A structure that could be directly compromised by the documented pathology (e.g. large aortic aneurysm → "Adjacent structures — IVC, duodenum, ureters — assessed for mass effect or involvement?")
- Quantification that materially changes the imaging impression (e.g. aneurysm with no size → "Maximum aortic diameter measured?")

ONE PROMPT PER ROOT FINDING: If multiple unassessed consequences stem from the same scratchpad finding, generate ONE prompt covering the most important consequence. Do not generate separate prompts for each consequence of the same root finding — consolidate. Each prompt must have a distinct root finding as its source_text.

MODALITY CONSTRAINT — ABSOLUTE RULE: Before writing any prompt or rationale, identify the exact scan type from the user prompt. Only suggest imaging features and assessments that are physically obtainable on that specific modality and protocol. If contrast or a specific sequence is not part of the declared scan (e.g. MRCP is non-contrast T2, plain CT has no enhancement), never reference it. Every prompt and rationale must be achievable by the radiologist on the images they actually have in front of them.

STYLE: Direct, concise imaging instruction. ≤12 words. End with "?" No preamble. Name the structure, name the feature.
SOURCE TEXT: Shortest verbatim scratchpad phrase that triggers the prompt — 3–6 words, exact substring.
RATIONALE: 2–3 sentences of practical workstation guidance specific to the declared modality: what to scroll to, what characteristic to assess on that specific scan, and what the finding would imply. Must not reference any technique unavailable on this scan type.
CONSOLIDATION: Re-evaluate existing_prompts against the current scratchpad. Discard any that are now answered or no longer relevant. Combine related prompts into one. Add new ones at threshold. Return the full consolidated list. Return [] if nothing meets the threshold.

You do NOT rewrite or modify the scratchpad. Return only prompts."""


CANVAS_INTELLIPROMPTS_USER_PROMPT_TEMPLATE = """Scan type: {scan_type}
Clinical history: {clinical_history}

Current scratchpad:
---
{scratchpad_content}
---

Current active IntelliPrompts (re-evaluate, consolidate, discard stale, add new): {existing_prompts}

Return the consolidated IntelliPrompts list."""

CANVAS_PROCESS_USER_PROMPT_TEMPLATE = """Scan type: {scan_type}
Clinical history: {clinical_history}

Current scratchpad:
---
{scratchpad_content}
---

Full session transcript (everything said so far):
---
{session_transcript}
---

Preferred section names for coverage reporting (return EXACT strings from this list in covered_sections): {preferred_section_names}

Produce the complete updated scratchpad and the covered_sections list."""


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------


@canvas_router.post("/sections", response_model=SectionGenerateResponse)
async def generate_sections(
    request: SectionGenerateRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate ordered anatomical section names for a radiology report based on scan type and clinical history."""
    model_name = MODEL_CONFIG["CANVAS_SECTIONS"]
    try:
        provider = _get_model_provider(model_name)
        api_key = _get_api_key_for_provider(provider)
    except ValueError:
        raise HTTPException(status_code=503, detail="Service not available. Contact your administrator.")

    user_prompt = SECTIONS_USER_PROMPT_TEMPLATE.format(
        scan_type=request.scan_type,
        clinical_history=request.clinical_history,
    )

    try:
        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=SectionGenerateResponse,
            system_prompt=SECTIONS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=api_key,
            model_settings={"temperature": 0.1, "max_completion_tokens": 1000},
        )
        return result.output
    except Exception:
        return SectionGenerateResponse(sections=["FINDINGS"])


@canvas_router.post("/sections-from-template", response_model=SectionGenerateResponse)
async def sections_from_template(
    request: SectionsFromTemplateRequest,
    current_user: User = Depends(get_current_user),
):
    """Extract ordered anatomical section headers from a FINDINGS template body."""
    model_name = MODEL_CONFIG["CANVAS_SECTIONS_FROM_TEMPLATE"]
    try:
        provider = _get_model_provider(model_name)
        api_key = _get_api_key_for_provider(provider)
    except ValueError:
        raise HTTPException(status_code=503, detail="Service not available. Contact your administrator.")

    user_prompt = SECTIONS_FROM_TEMPLATE_USER_PROMPT_TEMPLATE.format(
        template_content=request.template_content or "(empty)",
    )

    try:
        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=SectionGenerateResponse,
            system_prompt=SECTIONS_FROM_TEMPLATE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=api_key,
            model_settings={"temperature": 0.1, "max_completion_tokens": 500},
        )
        return result.output
    except Exception:
        return SectionGenerateResponse(sections=["FINDINGS"])


@canvas_router.post("/process", response_model=CanvasProcessResponse)
async def process_transcript(
    request: CanvasProcessRequest,
    current_user: User = Depends(get_current_user),
):
    """Process the full session transcript and return the complete updated scratchpad plus covered checklist sections."""
    model_name = MODEL_CONFIG["CANVAS_PROCESS"]
    try:
        provider = _get_model_provider(model_name)
        api_key = _get_api_key_for_provider(provider)
    except ValueError:
        raise HTTPException(status_code=503, detail="Service not available. Contact your administrator.")

    preferred_names_str = ", ".join(request.preferred_section_names) if request.preferred_section_names else "(none)"
    user_prompt = CANVAS_PROCESS_USER_PROMPT_TEMPLATE.format(
        scan_type=request.scan_type or "(not specified)",
        clinical_history=request.clinical_history or "(not specified)",
        scratchpad_content=request.scratchpad_content,
        session_transcript=request.session_transcript,
        preferred_section_names=preferred_names_str,
    )

    try:
        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=CanvasProcessResponse,
            system_prompt=CANVAS_PROCESS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=api_key,
            use_thinking=True,
            model_settings={"temperature": 0.1, "max_tokens": 4000},
        )
        return result.output
    except Exception:
        return CanvasProcessResponse(scratchpad=request.scratchpad_content, covered_sections=[])


@canvas_router.post("/review", response_model=CanvasReviewResponse)
async def review_scratchpad(
    request: CanvasReviewRequest,
    current_user: User = Depends(get_current_user),
):
    """Parallel pass: coverage matching and IntelliPrompts generation."""
    coverage_model = MODEL_CONFIG["CANVAS_COVERAGE"]
    intelliprompts_model = MODEL_CONFIG["CANVAS_INTELLIPROMPTS"]
    try:
        coverage_provider = _get_model_provider(coverage_model)
        intelliprompts_provider = _get_model_provider(intelliprompts_model)
        coverage_api_key = _get_api_key_for_provider(coverage_provider)
        intelliprompts_api_key = _get_api_key_for_provider(intelliprompts_provider)
    except ValueError:
        raise HTTPException(status_code=503, detail="Service not available. Contact your administrator.")

    checklist_str = ", ".join(request.checklist_sections) if request.checklist_sections else "(none)"
    existing_prompts_str = ", ".join(f'"{q}"' for q in request.existing_prompts) if request.existing_prompts else "(none)"

    coverage_prompt = CANVAS_COVERAGE_USER_PROMPT_TEMPLATE.format(
        scratchpad_content=request.scratchpad_content,
        checklist_sections=checklist_str,
    )
    intelliprompts_prompt = CANVAS_INTELLIPROMPTS_USER_PROMPT_TEMPLATE.format(
        scan_type=request.scan_type or "(not specified)",
        clinical_history=request.clinical_history or "(not specified)",
        scratchpad_content=request.scratchpad_content,
        existing_prompts=existing_prompts_str,
    )

    async def run_coverage() -> list[str]:
        try:
            result = await _run_agent_with_model(
                model_name=coverage_model,
                output_type=CoverageOnlyResponse,
                system_prompt=CANVAS_COVERAGE_SYSTEM_PROMPT,
                user_prompt=coverage_prompt,
                api_key=coverage_api_key,
                model_settings={"temperature": 0.0, "max_tokens": 200},
            )
            return result.output.covered_sections
        except Exception:
            return []

    async def run_intelliprompts() -> list[IntelliPrompt]:
        try:
            result = await _run_agent_with_model(
                model_name=intelliprompts_model,
                output_type=PromptsOnlyResponse,
                system_prompt=CANVAS_INTELLIPROMPTS_SYSTEM_PROMPT,
                user_prompt=intelliprompts_prompt,
                api_key=intelliprompts_api_key,
                use_thinking=True,
                model_settings={"temperature": 0.1, "max_tokens": 1000},
            )
            return result.output.prompts
        except Exception:
            return []

    covered, prompts = await asyncio.gather(run_coverage(), run_intelliprompts())
    return CanvasReviewResponse(covered_sections=covered, prompts=prompts)
