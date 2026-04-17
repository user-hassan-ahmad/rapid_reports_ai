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
    content_style: str = ""


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


def _syntax_legend(content_style: str) -> str:
    shared_comment_rule = (
        "// lines: guidance that annotates the preceding placeholder or prose section. "
        "A // line is never a section itself — it confirms what the preceding structure covers "
        "and is stripped from the final report. Never extract a // line as a coverage section."
    )

    if content_style == "structured_template":
        return f"""TEMPLATE SYNTAX — Structured Fill-In:
- {{VAR_NAME}}: a named placeholder for a specific finding. Each label followed by a {{VAR}} placeholder is a distinct dictation target and therefore a distinct coverage unit.
- xxx: a generic measurement placeholder — treat the surrounding label as a dictation target.
- [option1/option2]: a choice the radiologist selects between — treat the enclosing label as a dictation target.
- {shared_comment_rule}

Granularity rule for this style: a label followed by its own {{VAR}}/xxx placeholder is the unit to extract. A header that groups multiple such labelled placeholders is a container — extract the labelled placeholders, not the header."""

    if content_style == "guided_template":
        return f"""TEMPLATE SYNTAX — Guided Prose:
- Prose lines: the actual report structure. Each distinct prose block (separated by a blank line or clear topic shift) represents a section the radiologist addresses individually.
- {shared_comment_rule}

Granularity rule for this style: each distinct prose block is the unit to extract. A // line belongs to the prose block above it — do not treat it as a separate section or as evidence of a new section boundary."""

    if content_style == "normal_template":
        return """TEMPLATE SYNTAX — Normal Prose:
- This template has flowing prose with no placeholders ({VAR}, xxx, or //).
- Each distinct prose paragraph or anatomical region (separated by blank lines or clear topic shifts) is a coverage unit.
- Extract section names from the prose structure (anatomical names, paragraph topics, organ systems mentioned).
- Principle #2 (technique exclusion) does NOT apply here: prose-only templates ARE dictation targets — extract sections from the prose blocks."""

    return ""


SECTIONS_FROM_TEMPLATE_USER_PROMPT_TEMPLATE = """Below is the FINDINGS template content from a radiology report.

{syntax_context}EXTRACTION PRINCIPLES:

1. Dictation granularity — extract at the level the radiologist addresses individually. A structure with its own dedicated placeholder or prose block is a distinct coverage unit. A header that groups multiple named sub-structures each with their own placeholder is a container — extract the sub-structures, not the header.

2. Technique exclusion — exclude any section that contains only fixed prose with no placeholder or blank slot. It requires no dictation and cannot be covered by a scratchpad. Include any section that has at least one placeholder or named dictation slot, even if its name sounds procedural.

3. Preserve template order. Use UPPERCASE with spaces (e.g. CORONARY CALCIUM SCORING, OTHER FINDINGS).

4. Do not include IMPRESSION, CONCLUSION, BACKGROUND, or CLINICAL HISTORY sections.

FINDINGS template content:
---
{template_content}
---

Return a JSON array of uppercase section names."""


CANVAS_PROCESS_SYSTEM_PROMPT = """# Role

You capture a radiologist's live dictation into a structured scratchpad. Your single source of truth is the dictation transcript. Every bullet you write must originate in something the radiologist actually said.

# Hard fidelity rule

You are not a clinical reasoning engine and you are not completing the report. Do not introduce findings, companion assessments, expected negatives, or review items that the radiologist did not dictate. You may not add descriptors, qualifiers, or features to a finding beyond what was dictated, even if they would be clinically coherent — a bullet's content is bounded by what was said, not by what could plausibly accompany it.

Silence about a structure in the transcript means silence in the scratchpad. Silence about a descriptor on a mentioned structure means silence in the scratchpad for that descriptor. Fidelity applies at the level of each word, not just at the level of whether a structure is mentioned.

# Speech-to-text correction

Apply radiology knowledge to fix homophones and phonetic approximations — what you record is the radiologist's spoken intent, not the literal transcript surface form. Three sources of disambiguation:

1. General medical vocabulary — homophones of established radiological terms
2. The reference context — scan type and clinical history at the top of the user prompt
3. The current scratchpad — terms already established in this session

When the dictated form is phonetically close to a term made salient by one of these sources, and the established form is clinically consistent with surrounding findings, prefer the established form. Phonetic proximity plus context consistency is the test for correction.

Correction changes the surface form, never the substance. If the radiologist deliberately dictates a term that clashes with context, that is a legitimate substantive statement and must be recorded as said. The test: phonetic proximity plus context incoherence points to a speech-to-text error; phonetic distance plus standalone clinical coherence points to a legitimate substantive variation.

When no disambiguation source makes the intended term clear, record the transcript surface form verbatim. Imperfect literal transcription is recoverable by re-dictation or manual edit; invented descriptors are not. Invention is always worse than ambiguity.

# Date format

Dates in the scratchpad use British format — DD/MM/YYYY. Convert any other representation (spoken form, MM/DD/YYYY, ISO YYYY-MM-DD) to DD/MM/YYYY. The date being referenced is preserved; only the surface form changes.

# What to preserve

Measurements with units, laterality, anatomical location, qualifiers that convey confidence or interpretation, temporal comparators, staging, and specific pathology terms. Never substitute vague language for specific pathology — a capable reasoner knows consolidation is not "changes", a nodule is not "abnormality", an effusion is not "involvement".

# What to discard

Filler, navigation preamble, conversational confirmations, thinking-aloud hedges, and causal or discursive connectives that belong to spoken prose rather than written notes. The scratchpad is a written structured finding, not a verbal reasoning transcript. Preserve substantive content and the qualifiers that convey confidence or interpretation; drop the verbal bridges, sentence connectives, and chain-of-thought phrasing that led to them.

On self-correction, record only the corrected intent.

# Consolidation

Every bullet represents one finding as a single coherent statement. When the transcript adds detail, qualification, or measurement to a finding already captured, or when a later utterance clarifies or reinterprets an earlier one, rewrite the bullet so the whole statement reads as a single coherent finding. Do not append new clauses to the end of an existing bullet — that produces incoherent duplication or contradictory surface forms.

A genuinely independent finding about a different aspect of the same structure warrants its own bullet.

# Contradictions and re-interpretations

A specific positive finding supersedes a blanket negative about the same structure. A later statement supersedes an earlier one when they cannot both be true. When a later utterance reclassifies, reinterprets, or corrects an earlier finding — whether signalled by a correction marker or by contradicting the earlier interpretation — treat it as superseding and rewrite the bullet to carry only the final intended meaning.

Do not retain the earlier interpretation as a vestigial clause, do not keep a parallel bullet about the same structure with the superseded interpretation, and do not include the correction marker itself. The final scratchpad should read as if the final interpretation had been the first one given.

# Scratchpad field content

These rules describe what goes *inside* the `scratchpad` string of your structured response — not the shape of your overall reply.

The scratchpad string is plain text — no markdown, no headings, no bold, no horizontal rules inside it.

- One finding per line, each line beginning with `- `
- Group lines by anatomical system, separated by one blank line between groups
- Order: technique and limitations first, then anatomical systems in standard radiology reading order, then background or incidental context last

# One home per finding

Each finding belongs to exactly one anatomical group — the most specific owner. Never repeat a bullet under a second group, even when the finding has cross-system implications.

# Response shape

Your reply is a structured object with two fields:

- `scratchpad` — a single string containing the complete updated scratchpad, formatted per the rules above
- `covered_sections` — always return an empty list `[]`. Coverage is computed in a separate pass; any value you provide here is discarded.

When the transcript contains no findings yet, return an empty `scratchpad` string. Never emit raw text outside the structured response."""


CANVAS_COVERAGE_SYSTEM_PROMPT = """You are a strict radiology checklist coverage checker.

DEFINITION OF "COVERED":
A section is covered when the scratchpad contains a definitive statement whose grammatical subject is THAT SECTION'S OWN NAMED STRUCTURE — combined with a qualifier, finding, or measurement. The statement must be about the structure itself, not about a related, adjacent, or parent/child structure.

QUALIFIES AS COVERED:
  • Explicit normal qualifier applied to the structure: "liver unremarkable", "spleen NAD", "gallbladder clear", "kidneys within normal limits"
  • Positive imaging finding about the structure: "gallbladder distended", "liver 2cm hypodense lesion", "CBD calculus"
  • Explicit confident negative about the structure: "no gallbladder stones", "no biliary dilatation", "no free fluid", "no adnexal mass"
  • Standard shorthand where the structure name is present: "uterus NAD", "pancreas unremarkable"
  • Quantitative measurement that constitutes a clinical statement: "CBD measures 4mm", "aorta 2.1cm"

DOES NOT QUALIFY — reject every one of these:
  • Bare anatomical mention with no qualifier: "liver", "gallbladder", "kidneys" written alone
  • A related structure covering another: if GALLBLADDER and BILIARY SYSTEM are separate checklist sections, a statement about one does NOT cover the other — they must each be addressed independently
  • Parent structure covering a child section: "liver unremarkable" does NOT cover HEPATIC VEINS or PORTAL VEIN if those are separate sections
  • Incidental co-mention: "CBD calculus causing biliary dilatation" covers BILIARY SYSTEM but does NOT cover GALLBLADDER unless the gallbladder itself is also explicitly addressed in the same or another bullet
  • Vague collective terms: "upper abdomen clear" or "visualised structures unremarkable" do NOT cover individual organ sections — each section needs its own named statement

MATCHING RULE:
For each section, locate the specific scratchpad text whose grammatical subject is that section's own structure (or a universally accepted radiological abbreviation of it — e.g. CBD for common bile duct, IVC for inferior vena cava). If that text also carries a qualifier, finding, or measurement, the section is covered. If no such anchored text exists, it is NOT covered. Coverage is never transitive, inferred, or borrowed from adjacent structures.

Use the EXACT name strings from the checklist. Return only covered_sections."""


CANVAS_COVERAGE_USER_PROMPT_TEMPLATE = """Scratchpad:
---
{scratchpad_content}
---

Checklist sections to check: {checklist_sections}

Return which sections from the checklist are covered."""


CANVAS_INTELLIPROMPTS_SYSTEM_PROMPT = """You are a radiology decision-support assistant reviewing a dictation scratchpad. You are advising a radiologist who is actively at the workstation with the images in front of them. The scratchpad is a plain bulleted list of imaging findings grouped by anatomical system, separated by blank lines.

Your task: Identify imaging structures or features the radiologist has NOT yet reviewed but SHOULD, given what is already documented. You are directing their eyes back to the scan — not asking about clinical history, symptoms, or documentation.

CARDINAL RULE: Every IntelliPrompt must direct the radiologist to look at or assess a specific IMAGING STRUCTURE or FEATURE on the scan. Never ask about clinical symptoms (fever, pain, jaundice), patient history, or whether something has been "documented". The radiologist is looking at images — ask them to look at something they may have missed.

SELF-CHECK before writing any prompt: "Is this imaging feature meaningfully assessed somewhere in the scratchpad — with a qualifier, finding, or measurement?" If yes, DO NOT generate the prompt. A bare anatomical name with no qualifier does NOT count as assessed. If the scratchpad has "- Portal vein" or "- Gallbladder" with nothing else, those structures are NOT assessed and DO require a prompt if clinically indicated.

THRESHOLD — only generate a prompt if ALL of these apply:
- A documented finding implies a related structure or feature that should be reviewed but has not been meaningfully assessed in the scratchpad
- Reviewing it would change the imaging diagnosis, urgency classification, or report impression
- The finding or structure is genuinely absent from or only bare-mentioned in the scratchpad

DO NOT generate for:
- Any structure explicitly qualified in the scratchpad — "unremarkable", "normal", "clear", "NAD", "within normal limits", "not identified", "no X"
- Re-confirming a finding already present (never ask "is there biliary dilatation?" if it is documented)
- Isolated incidental findings with no meaningful imaging consequence
- Clinical or laboratory correlation requests — you only direct the gaze, not the clerk

DO generate for (radiology-specific imaging targets):
- A documented finding whose local complications on imaging are unassessed (e.g. acute appendicitis documented → "Appendix tip and base reviewed for perforation, abscess, or free gas?")
- A finding that raises a specific imaging differential requiring targeted review (e.g. spiculated lung nodule → "Mediastinal and hilar nodes assessed for lymphadenopathy? Adrenals and liver reviewed for metastatic deposits?")
- A pattern of findings where a key structure completing the picture has not been assessed (e.g. CBD calculus + intrahepatic biliary dilatation → "Gallbladder wall and pericholecystic fat reviewed for secondary cholecystitis? Liver parenchyma assessed for biliary abscess?")
- A finding with known imaging spread patterns not yet reviewed (e.g. portal vein thrombosis → "Superior mesenteric vein and splenic vein assessed for propagation? Bowel wall reviewed for ischaemia?")
- A structure that could be directly compromised by the documented pathology (e.g. large aortic aneurysm → "Adjacent structures — IVC, duodenum, ureters — assessed for mass effect or involvement?")
- Quantification that materially changes the imaging impression (e.g. aneurysm with no size → "Maximum aortic diameter measured?")
- A mass lesion with no vascular assessment → encasement or involvement of adjacent vessels not documented (e.g. pancreatic head mass → "Coeliac axis, SMA, and portal vein assessed for vascular encasement?"); a mass with hepatic lesions and no characterisation → "Liver lesions assessed for features of metastatic disease — size, number, diffusion restriction?"; lymph node assessment absent despite a mass → "Perivascular and regional lymph nodes assessed for pathological enlargement?"
- An asymmetric or unexplained finding where no cause has been documented (e.g. unilateral duct prominence, asymmetric organ size) → ask what explains the asymmetry on this scan
- A clinically significant incidental finding in a structure visible on this scan, even when full characterisation requires another modality: direct the radiologist to assess what CAN be evaluated on the available images — extent, wall involvement, relationship to adjacent structures, local invasion (e.g. suspicious colonic lesion on MRCP → "Hepatic flexure lesion — extent and relationship to adjacent structures assessed on available sequences?"; lung nodule on abdominal CT → "Lung nodule — size and morphology documented on lung windows?")

ONE PROMPT PER ROOT FINDING: If multiple unassessed consequences stem from the same scratchpad finding, generate ONE prompt targeting the most clinically critical consequence. Do not generate separate prompts for each consequence of the same root finding — consolidate them. Each prompt must have a distinct root finding as its source_text. Note: separate findings (e.g. a pancreatic mass, a distended gallbladder, liver lesions) each warrant their own independent prompt.

MODALITY CONSTRAINT — ABSOLUTE RULE: Before writing any prompt or rationale, identify the exact scan type from the user prompt. Only suggest imaging features and assessments that are physically obtainable on that specific modality and protocol. If contrast or a specific sequence is not part of the declared scan (e.g. MRCP is non-contrast T2 with DWI — no gadolinium, no enhancement phases), never reference it. Every prompt and rationale must be achievable by the radiologist on the images they actually have in front of them.

STYLE: Direct, concise imaging instruction. ≤12 words. End with "?" No preamble. Name the structure, name the feature.
SOURCE TEXT: Shortest verbatim scratchpad phrase that triggers the prompt — 3–6 words, exact substring. Must be a substring that literally appears in the scratchpad — never invent a phrase.
RATIONALE: Always required. 1–3 sentences of practical workstation guidance specific to the declared modality — what to scroll to, what characteristic to assess on that specific scan, and what the finding would imply. For straightforward gaps keep it to 1 sentence. Must not reference any technique unavailable on this scan type.
ORDERING: Order prompts by clinical urgency — most critical unassessed gap first.

OUTPUT: Return the complete current list of prompts for gaps that exist in this scratchpad right now. Order by clinical urgency. Return [] if nothing meets the threshold.

You do NOT rewrite or modify the scratchpad. Return only the prompts."""


CANVAS_INTELLIPROMPTS_USER_PROMPT_TEMPLATE = """Scan type: {scan_type}
Clinical history: {clinical_history}

Current scratchpad:
---
{scratchpad_content}
---

Return your complete IntelliPrompts list for this scratchpad."""

CANVAS_PROCESS_USER_PROMPT_TEMPLATE = """## Reference context — disambiguation only, never a source of findings

- **Scan type:** {scan_type}
- **Clinical history:** {clinical_history}

Use these to interpret ambiguous dictation — which anatomy is in the field of view, which acronyms are in play, which side a term refers to, and to correct phonetic errors in words the radiologist DID say. Never write bullets derived from them.

## Current scratchpad

Your previous output. Update in place.

{scratchpad_content}

## Dictation transcript — single source of truth

{session_transcript}

---

Produce the complete updated scratchpad."""


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------


# Shared model settings for section extraction (both scan-type and template)
_SECTIONS_MODEL_SETTINGS_CEREBRAS = {"temperature": 0.1, "max_completion_tokens": 1000}
_SECTIONS_MODEL_SETTINGS_GROQ = {"temperature": 0.1, "max_tokens": 1000}


@canvas_router.post("/sections", response_model=SectionGenerateResponse)
async def generate_sections(
    request: SectionGenerateRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate ordered anatomical section names for a radiology report based on scan type and clinical history."""
    primary_model = MODEL_CONFIG["CANVAS_SECTIONS"]
    fallback_model = MODEL_CONFIG["CANVAS_SECTIONS_FALLBACK"]
    user_prompt = SECTIONS_USER_PROMPT_TEMPLATE.format(
        scan_type=request.scan_type,
        clinical_history=request.clinical_history,
    )
    try:
        provider = _get_model_provider(primary_model)
        api_key = _get_api_key_for_provider(provider)
    except ValueError:
        raise HTTPException(status_code=503, detail="Service not available. Contact your administrator.")

    try:
        settings = _SECTIONS_MODEL_SETTINGS_CEREBRAS if provider == "cerebras" else _SECTIONS_MODEL_SETTINGS_GROQ
        result = await _run_agent_with_model(
            model_name=primary_model,
            output_type=SectionGenerateResponse,
            system_prompt=SECTIONS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=api_key,
            model_settings=settings,
        )
        return result.output
    except Exception:
        try:
            fallback_provider = _get_model_provider(fallback_model)
            fallback_api_key = _get_api_key_for_provider(fallback_provider)
            fallback_settings = _SECTIONS_MODEL_SETTINGS_CEREBRAS if fallback_provider == "cerebras" else _SECTIONS_MODEL_SETTINGS_GROQ
            result = await _run_agent_with_model(
                model_name=fallback_model,
                output_type=SectionGenerateResponse,
                system_prompt=SECTIONS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                api_key=fallback_api_key,
                model_settings=fallback_settings,
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
    import time as _time

    t0 = _time.perf_counter()
    template_len = len(request.template_content or "")
    print(f"\n[SECTIONS-FROM-TEMPLATE] ── New call ──────────────────────────")
    print(f"[SECTIONS-FROM-TEMPLATE] template_content: {template_len} chars | content_style: {request.content_style!r}")

    primary_model = MODEL_CONFIG["CANVAS_SECTIONS_FROM_TEMPLATE"]
    fallback_model = MODEL_CONFIG["CANVAS_SECTIONS_FROM_TEMPLATE_FALLBACK"]
    legend = _syntax_legend(request.content_style)
    user_prompt = SECTIONS_FROM_TEMPLATE_USER_PROMPT_TEMPLATE.format(
        syntax_context=legend + "\n\n" if legend else "",
        template_content=request.template_content or "(empty)",
    )
    try:
        provider = _get_model_provider(primary_model)
        api_key = _get_api_key_for_provider(provider)
    except ValueError:
        print(f"[SECTIONS-FROM-TEMPLATE] ❌ No provider for {primary_model}")
        raise HTTPException(status_code=503, detail="Service not available. Contact your administrator.")

    try:
        settings = _SECTIONS_MODEL_SETTINGS_CEREBRAS if provider == "cerebras" else _SECTIONS_MODEL_SETTINGS_GROQ
        result = await _run_agent_with_model(
            model_name=primary_model,
            output_type=SectionGenerateResponse,
            system_prompt=SECTIONS_FROM_TEMPLATE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=api_key,
            model_settings=settings,
        )
        elapsed = _time.perf_counter() - t0
        sections = result.output.sections
        print(f"[SECTIONS-FROM-TEMPLATE] ✅ {elapsed:.2f}s (primary) → {len(sections)} sections: {sections}")
        return result.output
    except Exception as e:
        print(f"[SECTIONS-FROM-TEMPLATE] ⚠️  Primary failed: {type(e).__name__}: {e}")
        try:
            fallback_provider = _get_model_provider(fallback_model)
            fallback_api_key = _get_api_key_for_provider(fallback_provider)
            fallback_settings = _SECTIONS_MODEL_SETTINGS_CEREBRAS if fallback_provider == "cerebras" else _SECTIONS_MODEL_SETTINGS_GROQ
            result = await _run_agent_with_model(
                model_name=fallback_model,
                output_type=SectionGenerateResponse,
                system_prompt=SECTIONS_FROM_TEMPLATE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                api_key=fallback_api_key,
                model_settings=fallback_settings,
            )
            elapsed = _time.perf_counter() - t0
            sections = result.output.sections
            print(f"[SECTIONS-FROM-TEMPLATE] ✅ {elapsed:.2f}s (fallback) → {len(sections)} sections: {sections}")
            return result.output
        except Exception as fallback_e:
            elapsed = _time.perf_counter() - t0
            print(f"[SECTIONS-FROM-TEMPLATE] ❌ {elapsed:.2f}s both failed, returning [FINDINGS]: {type(fallback_e).__name__}: {fallback_e}")
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

    user_prompt = CANVAS_PROCESS_USER_PROMPT_TEMPLATE.format(
        scan_type=request.scan_type or "(not specified)",
        clinical_history=request.clinical_history or "(not specified)",
        scratchpad_content=request.scratchpad_content,
        session_transcript=request.session_transcript,
    )

    try:
        result = await _run_agent_with_model(
            model_name=model_name,
            output_type=CanvasProcessResponse,
            system_prompt=CANVAS_PROCESS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=api_key,
            use_thinking=False,
            model_settings={"temperature": 0.7, "top_p": 0.8, "max_completion_tokens": 4000},
        )
        return result.output
    except Exception as e:
        import traceback
        print(f"[CANVAS-PROCESS] ❌ {type(e).__name__}: {e}")
        traceback.print_exc()
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

    coverage_prompt = CANVAS_COVERAGE_USER_PROMPT_TEMPLATE.format(
        scratchpad_content=request.scratchpad_content,
        checklist_sections=checklist_str,
    )
    intelliprompts_prompt = CANVAS_INTELLIPROMPTS_USER_PROMPT_TEMPLATE.format(
        scan_type=request.scan_type or "(not specified)",
        clinical_history=request.clinical_history or "(not specified)",
        scratchpad_content=request.scratchpad_content,
    )

    async def run_coverage() -> list[str]:
        import time as _time
        coverage_model_settings = {"temperature": 0.0, "max_tokens": 500}
        scratchpad_preview = request.scratchpad_content[:200].replace('\n', ' | ')
        print(f"\n[COVERAGE] ── New call ──────────────────────────")
        print(f"[COVERAGE] Model: {coverage_model} | Scratchpad: {len(request.scratchpad_content)} chars")
        print(f"[COVERAGE] Scratchpad preview: {scratchpad_preview}...")
        print(f"[COVERAGE] Checklist sections: {request.checklist_sections}")
        t0 = _time.perf_counter()
        try:
            result = await _run_agent_with_model(
                model_name=coverage_model,
                output_type=CoverageOnlyResponse,
                system_prompt=CANVAS_COVERAGE_SYSTEM_PROMPT,
                user_prompt=coverage_prompt,
                api_key=coverage_api_key,
                model_settings=coverage_model_settings,
            )
            covered = result.output.covered_sections
            elapsed = _time.perf_counter() - t0
            print(f"[COVERAGE] ✅ {elapsed:.2f}s → {covered}")
            return covered
        except Exception as e:
            elapsed = _time.perf_counter() - t0
            print(f"[COVERAGE] ❌ {elapsed:.2f}s → {type(e).__name__}: {e}")
            return []

    async def run_intelliprompts() -> list[IntelliPrompt]:
        import time as _time
        if intelliprompts_provider == "cerebras":
            intelliprompts_model_settings = {"temperature": 0.1, "max_completion_tokens": 1500, "reasoning_effort": "medium"}
            use_thinking = False
        else:
            intelliprompts_model_settings = {"temperature": 0.1, "max_tokens": 3000}
            use_thinking = True

        scratchpad_lower = request.scratchpad_content.lower()

        async def _call_model(model_name: str, api_key: str, thinking: bool, settings: dict) -> PromptsOnlyResponse:
            result = await _run_agent_with_model(
                model_name=model_name,
                output_type=PromptsOnlyResponse,
                system_prompt=CANVAS_INTELLIPROMPTS_SYSTEM_PROMPT,
                user_prompt=intelliprompts_prompt,
                api_key=api_key,
                use_thinking=thinking,
                model_settings=settings,
            )
            return result.output

        def _validate_and_log(raw: list[IntelliPrompt], elapsed: float, label: str) -> list[IntelliPrompt]:
            validated = []
            for p in raw:
                if p.source_text and p.source_text.lower() not in scratchpad_lower:
                    print(f"[INTELLIPROMPTS] ⚠️  Clearing fabricated source_text: '{p.source_text}'")
                    validated.append(IntelliPrompt(question=p.question, source_text="", rationale=p.rationale))
                else:
                    validated.append(p)
            print(f"[INTELLIPROMPTS] {label} {elapsed:.2f}s → {len(validated)} prompts")
            for p in validated:
                rationale_preview = (p.rationale[:80] + "…") if p.rationale and len(p.rationale) > 80 else (p.rationale or "⚠️ NO RATIONALE")
                print(f"[INTELLIPROMPTS]   • {p.question}")
                print(f"[INTELLIPROMPTS]     ↳ {rationale_preview}")
            return validated

        print(f"\n[INTELLIPROMPTS] ── New call ──────────────────────────")
        print(f"[INTELLIPROMPTS] Model: {intelliprompts_model} | use_thinking: {use_thinking} | stateless")
        t0 = _time.perf_counter()
        try:
            response = await _call_model(intelliprompts_model, intelliprompts_api_key, use_thinking, intelliprompts_model_settings)
            elapsed = _time.perf_counter() - t0
            return _validate_and_log(response.prompts, elapsed, "✅")
        except Exception as e:
            elapsed = _time.perf_counter() - t0
            error_str = str(e)

            # Detect 503 / Groq busy signals
            is_infra_failure = "503" in error_str or "queue_exceeded" in error_str
            if "failed_generation" in error_str:
                import re as _re
                generation = ""
                match = _re.search(r"'failed_generation':\s*'(.*?)'(?:,|\})", error_str, _re.DOTALL)
                if match:
                    generation = match.group(1)
                is_empty = generation.strip() in ("", "[]", "[ ]")
                if is_empty:
                    is_infra_failure = True

            # 503/busy: try gpt-oss-120b (Cerebras) once, then resume normal Qwen next call
            if is_infra_failure:
                try:
                    fallback_api_key = _get_api_key_for_provider("cerebras")
                    response = await _call_model(
                        "gpt-oss-120b",
                        fallback_api_key,
                        False,
                        {"temperature": 0.1, "max_completion_tokens": 1500, "reasoning_effort": "medium"},
                    )
                    elapsed = _time.perf_counter() - t0
                    return _validate_and_log(response.prompts, elapsed, "⚡ 503→fallback")
                except Exception as fallback_e:
                    print(f"[INTELLIPROMPTS] ❌ Fallback also failed: {fallback_e}")
                    return []

            print(f"[INTELLIPROMPTS] ❌ {elapsed:.2f}s → {type(e).__name__}: {e}")
            return []

    covered, prompts = await asyncio.gather(run_coverage(), run_intelliprompts())
    return CanvasReviewResponse(covered_sections=covered, prompts=prompts)
