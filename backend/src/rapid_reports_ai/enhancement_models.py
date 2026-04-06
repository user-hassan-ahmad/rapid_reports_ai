"""
Pydantic models for AI-powered report enhancement
All structured outputs use these typed models for validation and type safety.
AuditResult applies light before-validation coercion for common LLM/tool formatting mistakes.
"""

import json
import time
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ============================================================================
# Finding Extraction Models
# ============================================================================

class Finding(BaseModel):
    """A single clinically significant finding from a radiology report"""
    finding: str = Field(
        description="Brief description of the finding (e.g., 'lung nodule', 'aortic aneurysm')"
    )
    specialty: str = Field(
        default="general radiology",
        description="Medical specialty area (e.g., 'chest/thoracic', 'neuro', 'vascular')"
    )
    type: str = Field(
        default="protocol",
        description="Type of finding (e.g., 'follow-up protocol', 'diagnostic criteria')"
    )
    guideline_focus: str = Field(
        default="relevant guidelines",
        description="What specific guidance is needed (e.g., 'measurement and surveillance intervals')"
    )


class FindingsResponse(BaseModel):
    """Response containing all extracted findings from a report"""
    findings: List[Finding] = Field(
        description="List of 2-3 most clinically significant POSITIVE findings. Empty if no significant findings."
    )


# ============================================================================
# Guideline Search Models (Radiologist-Focused)
# ============================================================================

class KeyPoint(BaseModel):
    """A single key clinical guidance point"""
    title: str = Field(
        description="Clear action-oriented label (e.g., 'Urgent Referral', 'Recommended Imaging', 'Follow-up Protocol')"
    )
    detail: str = Field(
        description="Specific, actionable guidance with timeframes or criteria where applicable"
    )


class ClassificationSystem(BaseModel):
    """Radiology classification or grading system"""
    name: str = Field(
        description="System name with year (e.g., 'Fleischner Society 2017', 'Bosniak 2019')"
    )
    grade_or_category: str = Field(
        description="Specific grade/category (e.g., 'Category 4', 'Low risk')"
    )
    criteria: str = Field(
        description="Imaging criteria for this grade"
    )


class MeasurementProtocol(BaseModel):
    """Imaging measurement specifications"""
    parameter: str = Field(
        description="What to measure (e.g., 'nodule diameter')"
    )
    technique: str = Field(
        description="How to measure (e.g., 'long axis on axial CT, lung windows')"
    )
    normal_range: Optional[str] = Field(
        default=None,
        description="Normal values with units"
    )
    threshold: Optional[str] = Field(
        default=None,
        description="Abnormal thresholds with significance"
    )


class ImagingCharacteristic(BaseModel):
    """Imaging features to document"""
    feature: str = Field(
        description="Feature name (e.g., 'attenuation', 'T2 signal')"
    )
    description: str = Field(
        description="How to assess (e.g., 'measure HU on non-contrast CT')"
    )
    significance: str = Field(
        description="Clinical significance (e.g., '> 20 HU suggests solid component')"
    )


class DifferentialDiagnosis(BaseModel):
    """Diagnosis with distinguishing imaging features"""
    diagnosis: str = Field(
        description="Diagnosis name"
    )
    imaging_features: str = Field(
        description="Imaging features that suggest this diagnosis"
    )
    supporting_findings: str = Field(
        description="Additional features that support or exclude"
    )


class FollowUpImaging(BaseModel):
    """Follow-up imaging protocol specifications"""
    indication: str = Field(
        description="Clinical scenario requiring follow-up"
    )
    modality: str = Field(
        description="Imaging modality with rationale"
    )
    timing: str = Field(
        description="Timing interval from guidelines"
    )
    technical_specs: Optional[str] = Field(
        default=None,
        description="Technical parameters"
    )


class GuidelineEntry(BaseModel):
    """Radiologist-focused diagnostic guidelines for a finding"""
    finding_number: int = Field(
        ge=1,
        description="The finding number from the input list (1-based index)"
    )
    finding: str = Field(
        description="The exact finding text from the input list"
    )
    diagnostic_overview: str = Field(
        min_length=20,
        description="2-3 sentences: what this represents, key imaging features, diagnostic considerations"
    )
    classification_systems: List[ClassificationSystem] = Field(
        default_factory=list,
        description="0-2 established radiology classification/grading systems"
    )
    measurement_protocols: List[MeasurementProtocol] = Field(
        default_factory=list,
        description="2-4 measurement techniques with thresholds and units"
    )
    imaging_characteristics: List[ImagingCharacteristic] = Field(
        min_length=1,
        description="4-6 key imaging features to identify and document"
    )
    differential_diagnoses: List[DifferentialDiagnosis] = Field(
        default_factory=list,
        description="2-4 differential diagnoses with distinguishing imaging features"
    )
    follow_up_imaging: Optional[List[FollowUpImaging]] = Field(
        default_factory=list,
        description="Follow-up imaging protocols with technical specifications"
    )


class GuidelinesResponse(BaseModel):
    """Response containing guidelines for all findings"""
    guidelines: List[GuidelineEntry] = Field(
        min_length=1,
        description="Clinical guidelines for each finding, in the same order as the input findings"
    )


# ============================================================================
# Rich Guideline Models (Bespoke Synthesis — v2)
# ============================================================================

class UrgencyTier(str, Enum):
    URGENT   = "urgent"      # same-day / 48h action required
    SOON     = "soon"        # 2–6 weeks
    ROUTINE  = "routine"     # 3–6 months
    WATCH    = "watch"       # annual / long-term surveillance
    NONE     = "none"        # no specific follow-up indicated


class RichFollowUpAction(BaseModel):
    """A single follow-up imaging action with guideline attribution"""
    modality: str = Field(description="Imaging modality (e.g. 'MRCP', 'LDCT thorax')")
    timing: str = Field(description="Timing interval (e.g. '4–6 weeks', '6 months')")
    indication: str = Field(description="Short trigger condition or clinical scenario")
    urgency: UrgencyTier = Field(description="Urgency tier for this specific action")
    guideline_source: str = Field(description="Specific guideline reference (e.g. 'NICE CG188', 'BSG 2020')")


class RichClassificationGrade(BaseModel):
    """A classification/grading system entry with management implication"""
    system: str = Field(description="System name (e.g. 'Bosniak', 'Fleischner', 'LI-RADS')")
    authority: str = Field(description="Issuing body (e.g. 'RSNA/ACR', 'RCR', 'Fleischner Society')")
    year: Optional[str] = Field(default=None, description="Version year (e.g. '2019', '2017')")
    grade: str = Field(description="Grade or category label (e.g. 'IIF', '3', 'Probably benign')")
    criteria: str = Field(description="Generic textbook definition of this grade boundary — no patient-specific content")
    management: str = Field(description="Patient-specific assignment ('This patient: [stage] — [features]') plus recommended clinical action")


class ActionableThreshold(BaseModel):
    """An imaging measurement threshold with clinical decision point"""
    parameter: str = Field(description="What to measure — imaging metric or lab/biomarker (e.g. 'CBD diameter', 'CA 19-9')")
    threshold: str = Field(description="The decision-point value (e.g. '> 8 mm', 'CA 19-9 > 100 U/mL')")
    significance: str = Field(description="What exceeding the threshold means clinically (e.g. 'warrants MRCP')")
    context: str = Field(default="", description="Measurement technique (imaging) or assay notes (lab/biomarker)")


class RichDifferential(BaseModel):
    """A differential diagnosis with distinguishing and excluding features"""
    diagnosis: str = Field(description="Diagnosis name")
    key_features: str = Field(description="Imaging features that suggest this diagnosis")
    excluders: str = Field(description="Features that rule this diagnosis out")
    likelihood: str = Field(description="'common' | 'less common' | 'rare'")


class RichGuidelineEntry(BaseModel):  # DEPRECATED — replaced by S4 synthesis cards
    """Bespoke radiologist-focused guideline entry — v2 synthesis output (legacy, kept for persisted data)."""
    finding_number: int = Field(ge=1, description="1-based index matching the input finding list")
    finding: str = Field(description="The exact finding text")
    urgency_tier: UrgencyTier = Field(description="Overall urgency — the most urgent action required for this finding")
    clinical_summary: str = Field(
        min_length=10,
        description="2 sentences max: what this finding represents and its primary clinical significance"
    )
    uk_authority: str = Field(description="Primary UK guideline body (e.g. 'NICE', 'BSG', 'RCR', 'BTS')")
    guideline_refs: List[str] = Field(
        default_factory=list,
        description="Short guideline attributions (e.g. ['NICE CG188', 'BSG 2020'])"
    )
    follow_up_actions: List[RichFollowUpAction] = Field(
        default_factory=list,
        description="Ordered follow-up imaging actions, most urgent first"
    )
    classifications: List[RichClassificationGrade] = Field(
        default_factory=list,
        description="0–2 applicable classification/grading systems"
    )
    thresholds: List[ActionableThreshold] = Field(
        default_factory=list,
        description="Actionable measurement thresholds with clinical decision points"
    )
    differentials: List[RichDifferential] = Field(
        default_factory=list,
        description="2–4 differential diagnoses with distinguishing and excluding features"
    )
    imaging_flags: List[str] = Field(
        default_factory=list,
        description="Flat list of key imaging features to note (e.g. 'dilated CBD > 8mm', 'posterior acoustic shadowing')"
    )
    sources: List[dict] = Field(
        default_factory=list,
        description="Source URLs with titles"
    )


class RichGuidelinesResponse(BaseModel):
    """Response wrapper for the bespoke synthesis output"""
    guidelines: List[RichGuidelineEntry] = Field(
        min_length=1,
        description="Rich guideline entries for each finding, in the same order as the input findings"
    )


# ============================================================================
# S4 Branch-Decomposed Synthesis Models
# ============================================================================

class SynthFollowUpAction(BaseModel):
    """A single follow-up action from pathway synthesis (S4 Pass A)."""
    modality: str
    timing: str = ""
    indication: str = ""
    urgency: str = "routine"
    guideline_source: str = ""


class PathwaySynthesis(BaseModel):
    """S4 Pass A output: pathway, urgency, and follow-up actions."""
    urgency_tier: str = "none"
    uk_authority: str = ""
    guideline_refs: List[str] = Field(default_factory=list)
    follow_up_actions: List[SynthFollowUpAction] = Field(default_factory=list)


class SynthClassification(BaseModel):
    """A classification/grading system entry from S4 Pass B."""
    system: str
    authority: str = ""
    year: Optional[str] = None
    grade: str = ""
    criteria: str = ""
    management: str = ""


class SynthThreshold(BaseModel):
    """A clinical decision-point threshold from S4 Pass B."""
    parameter: str
    threshold: str
    significance: str = ""
    context: str = ""


class ClassificationSynthesis(BaseModel):
    """S4 Pass B output: classifications and actionable thresholds."""
    classifications: List[SynthClassification] = Field(default_factory=list)
    thresholds: List[SynthThreshold] = Field(default_factory=list)


class SynthDifferential(BaseModel):
    """A differential diagnosis entry from S4 Pass C."""
    diagnosis: str
    key_features: str = ""
    excluders: str = ""
    likelihood: str = "common"


class DifferentialSynthesis(BaseModel):
    """S4 Pass C output: clinical summary, differentials, and imaging flags."""
    clinical_summary: str = ""
    differentials: List[SynthDifferential] = Field(default_factory=list)
    imaging_flags: List[str] = Field(default_factory=list)


# ============================================================================
# Prefetch Pipeline Models
# ============================================================================

class PrefetchKnowledgeItem(BaseModel):
    """A single content item in the prefetch knowledge base."""
    url: str
    content: str
    content_chars: int
    extraction_type: str        # "deep_extract" | "inline" | "deep_extract_fallback"
    extract_hint: Optional[str] = None
    finding_indices: List[int] = Field(default_factory=list)  # 0-based into consolidated_findings[]
    title: str = ""
    domain: str = ""
    branch: str = ""            # "pathway_followup" | "classification_measurement" | "imaging_differential"


class PrefetchOutput(BaseModel):
    """Complete output of the parallel guideline prefetch pipeline."""
    prefetch_id: str
    findings_hash: str = ""
    consolidated_findings: List[str] = Field(default_factory=list)
    finding_short_labels: List[str] = Field(default_factory=list)
    applicable_guidelines: List[dict] = Field(default_factory=list)
    urgency_signals: List[str] = Field(default_factory=list)
    knowledge_base: Dict[str, List[PrefetchKnowledgeItem]] = Field(default_factory=dict)
    pipeline_ms: int = 0
    created_at: float = Field(default_factory=time.time)
    guidelines: List[dict] = Field(default_factory=list)
    triage_counts: dict = Field(default_factory=dict)
    synthesis_stats: dict = Field(default_factory=dict)


# ============================================================================
# Consolidation Models
# ============================================================================

class ConsolidatedFinding(BaseModel):
    """A consolidated radiological observation"""
    finding: str = Field(description="Consolidated categorical observation")
    sources: List[int] = Field(default_factory=list, description="1-based indices of merged source findings")


class ConsolidationResult(BaseModel):
    """Result of consolidating multiple findings"""
    findings: List[ConsolidatedFinding] = Field(
        min_length=0,
        description="List of consolidated observations. Empty list if no findings requiring assessment."
    )


# ============================================================================
# Suggested actions (chat / enhancement apply-actions)
# ============================================================================

class SuggestedAction(BaseModel):
    """A suggested edit or addition to improve the report"""
    id: str = Field(
        description="Kebab-case slug identifier (e.g., 'add-measurement-details')"
    )
    title: str = Field(
        max_length=80,
        description="Concise action label (≤10 words)"
    )
    details: str = Field(
        min_length=20,
        description="1-2 sentence explanation of why/when to apply this action"
    )
    patch: str = Field(
        default="",
        description="Explicit text snippet to add/modify in the report; empty string if not applicable"
    )


# ============================================================================
# Search Result Compatibility Models
# ============================================================================

class CompatibleIndicesResponse(BaseModel):
    """Response containing compatible search result indices as JSON string"""
    indices_json: str = Field(
        description="JSON array string containing 0-based indices of compatible results. Example: '[0, 2, 5]' or '[]' if none. Return only valid JSON array format."
    )
    
    def get_indices(self) -> List[int]:
        """Parse the JSON string and return list of integers"""
        import json
        try:
            parsed = json.loads(self.indices_json.strip())
            if isinstance(parsed, list):
                return [int(x) for x in parsed if isinstance(x, (int, str)) and str(x).isdigit()]
            return []
        except (json.JSONDecodeError, ValueError, TypeError):
            # Fallback: try to extract numbers from string
            import re
            return [int(x) for x in re.findall(r'\d+', self.indices_json)]


# ============================================================================
# Structure Validation Models
# ============================================================================

class StructureViolation(BaseModel):
    """A structural quality violation found in the report"""
    location: str = Field(
        description="Specific location: section name and paragraph (e.g., 'Findings paragraph 2', 'Impression')"
    )
    issue: str = Field(
        description="Clear description of what's wrong and why it violates the principle"
    )
    fix: str = Field(
        description="Specific fix instruction: what to change, where, and how. Format: '[Action: Remove/Add/Move/Restructure] [what/where] because [reason].'"
    )


class StructureValidationResult(BaseModel):
    """Result of structural quality validation"""
    violations: List[StructureViolation] = Field(
        default_factory=list,
        description="List of structural violations found, each with location, issue description and recommended fix"
    )
    is_valid: bool = Field(
        description="True if no violations found"
    )


# ============================================================================
# Report Generation Output Model
# ============================================================================


class ApplicableGuideline(BaseModel):
    """Classification system or UK guideline identified from findings + scan type (not from report prose audit)."""

    system: str = Field(
        max_length=60,
        description=(
            "Short canonical name only e.g. 'Bosniak', 'LI-RADS', 'Fleischner Society pulmonary nodule', 'NICE NG12'. "
            "Not a long narrative title (max 60 characters)."
        ),
    )
    context: str = Field(
        description="One sentence clinical context in English only (disambiguation for humans)"
    )
    search_keywords: Optional[str] = Field(
        default=None,
        description=(
            "3–12 search tokens for Firecrawl only (organ, modality, key finding, jurisdiction). "
            "For uk_pathway entries, include the governing specialist society acronym when known "
            "(e.g. AUGIS for upper-GI surgery, BAUS for urology, BTS for thoracic, SIGN for Scotland, "
            "BSGE for gynaecology, RCS/RCSED for general surgery, RCOG for obstetrics, BAETS for ENT). "
            "Omit if the system name is already fully distinctive. English only."
        ),
    )
    type: Literal["classification", "uk_pathway", "other"] = Field(
        default="other",
        description=(
            "classification: named radiology scoring/classification (Lung-RADS, Fleischner, LI-RADS, Bosniak, etc.). "
            "uk_pathway: NHS pathway, NICE, RCR, or UK specialist society guideline (e.g. BTS pulmonary nodule). "
            "Use uk_pathway for UK governing pathways even when an international classification also applies. "
            "other: anything else."
        ),
    )


class ReportOutput(BaseModel):
    """Output from report generation - both auto and templated reports"""

    model_config = ConfigDict(extra="ignore")

    report_content: str = Field(
        min_length=50,
        description="The complete radiology report text with proper formatting"
    )
    description: str = Field(
        min_length=5,
        max_length=250,
        description="Brief summary for history tab (5-15 words describing key findings, max 250 characters)"
    )
    scan_type: str = Field(
        min_length=3,
        max_length=200,
        description="Extracted scan type and protocol combined (e.g., 'CT head non-contrast', 'MRI brain with contrast'). Extract from template name/description and findings context. Include contrast status ONLY if explicitly mentioned."
    )
    model_used: Optional[str] = None  # Set by backend after generation; not from LLM

    # NO field validators - let Pydantic handle validation exclusively
    # This preserves formatting and allows models to generate natural output


class ReportOutputWithReasoning(BaseModel):
    """Output from optimized report generation with explicit reasoning step"""
    reasoning: str = Field(
        min_length=50,
        description="Detailed step-by-step analysis: 1) Identify scan type/protocol. 2) Map findings to anatomy. 3) Cross-reference findings with protocol (explicitly state if any finding is invalid). 4) Plan the report structure."
    )
    report_content: str = Field(
        min_length=50,
        description="The complete radiology report text with proper formatting"
    )
    description: str = Field(
        min_length=5,
        max_length=250,
        description="Brief summary for history tab (5-15 words describing key findings, max 250 characters)"
    )
    scan_type: str = Field(
        min_length=3,
        max_length=200,
        description="Extracted scan type and protocol combined (e.g., 'CT head non-contrast', 'MRI brain with contrast'). Extract from template name/description and findings context. Include contrast status ONLY if explicitly mentioned."
    )


# ============================================================================
# Report Audit / QA Models
# ============================================================================

class InputDiscrepancy(BaseModel):
    """A discrepancy between original dictated input and generated report."""
    input_text: str
    report_text: str = ""
    type: Literal["dropped", "measurement_changed", "laterality_changed", "qualifier_changed", "inverted"]
    severity: Literal["minor", "significant"]


class CharacterisationGap(BaseModel):
    """A missing characterisation feature for a finding relative to guidelines."""
    finding: str
    missing_features: List[str]
    guideline_basis: str
    severity: Literal["critical", "supporting"]


class AuditCriterionFlag(BaseModel):
    """Sub-flag for clinical_flagging criterion — 3-tier severity model aligned with RCR standards"""
    type: Literal["critical", "urgent", "significant"] = Field(
        description="Severity tier: critical (life-threatening, immediate action), "
                    "urgent (same-day attention), significant (clinical management)"
    )
    present: bool = Field(
        description="Whether this flag type is present in the report"
    )
    adequately_supported: bool = Field(
        description="Whether surrounding language justifies this flag level"
    )
    detail: str = Field(
        description="Brief explanation of the flag assessment (British English only)"
    )


class FlagBannerOption(BaseModel):
    """Banner option for clinical_flagging — pure severity alert the user may append to the report"""
    category: Literal["critical", "urgent", "significant"] = Field(
        description="Severity tier for the banner"
    )
    label: str = Field(description="Short label in British English e.g. 'Critical — Immediate Action Required'")
    banner_text: str = Field(description="Full text to append to the report (use standard templates verbatim)")
    rationale: str = Field(description="Why this was suggested, British English only (shown to user)")
    clinical_context: Optional[str] = Field(
        default=None,
        description="Semantic tag for frontend visual differentiation (e.g. 'malignancy_new', "
                    "'vascular_emergency', 'infection_sepsis', 'malignancy_interval'). "
                    "Not displayed as text — used for icon/colour selection."
    )


class AuditCriterion(BaseModel):
    """Single audit criterion evaluation result"""
    criterion: Literal[
        "anatomical_accuracy",
        "clinical_relevance",
        "recommendations",
        "clinical_flagging",
        "report_completeness",
        "diagnostic_fidelity",
        "input_fidelity",
        "scan_coverage",
        "characterisation_gap",
    ] = Field(description="Audit criterion name (6 legacy + 3 new)")
    status: Literal["pass", "flag", "warning"] = Field(
        description="Audit status: pass (no issues), flag (requires attention), warning (minor concern)"
    )
    rationale: str = Field(
        description=(
            "Explanation of why this status was assigned (British English only). "
            "For diagnostic_fidelity, must use the two-line format required in the audit system prompt "
            "(a) Certainty: ... (b) Consistency: .... "
            "For recommendations when criterion_line is set, state only what is deficient in the report "
            "wording; do not restate guideline thresholds or correct pathways (those belong in criterion_line)."
        )
    )
    highlighted_spans: List[str] = Field(
        default_factory=list,
        description="Verbatim substrings from the report to highlight inline"
    )
    recommendation: Optional[str] = Field(
        default=None,
        description="Suggested improvement if status is flag or warning (British English only)"
    )
    suggested_replacement: Optional[str] = Field(
        default=None,
        description=(
            "anatomical_accuracy and recommendations flags only. "
            "Verbatim drop-in substitution for highlighted_spans[0] — must read naturally at the "
            "same position in the sentence, no new sentences or line breaks. "
            "Null if the fix is structural rather than a span substitution."
        )
    )
    suggested_sentence: Optional[str] = Field(
        default=None,
        description=(
            "report_completeness flags only. "
            "A complete, report-ready British English sentence to insert when a finding is entirely "
            "absent. Null if the problem is a span substitution rather than a missing sentence."
        )
    )
    criterion_line: Optional[str] = Field(
        default=None,
        description=(
            "Single scannable line from injected guideline context identifying the specific rule the "
            "report failed to follow. Populated for recommendations flags only (flag or warning). "
            "Maximum one sentence. Null on pass or when no guideline context applies or the failure is "
            "structural rather than criterion-specific."
        ),
    )
    flags_identified: Optional[List[AuditCriterionFlag]] = Field(
        default=None,
        description="Populated only for clinical_flagging criterion - lists 3 sub-flag evaluations (critical, urgent, significant)"
    )
    suggested_banners: Optional[List[FlagBannerOption]] = Field(
        default=None,
        description="Populated only for clinical_flagging - banners to optionally append to report"
    )
    discrepancies: Optional[List[InputDiscrepancy]] = Field(
        default=None,
        description="Populated only for input_fidelity — each discrepancy between original input and report"
    )
    systems_unaddressed: Optional[List[str]] = Field(
        default=None,
        description="Populated only for scan_coverage — anatomical systems expected but not mentioned"
    )
    characterisation_gaps: Optional[List[CharacterisationGap]] = Field(
        default=None,
        description="Populated only for characterisation_gap — missing features per finding"
    )


class GuidelineReference(BaseModel):
    """Server-populated audit payload: what guideline evidence was available for QA context."""

    system: str = Field(description="Canonical guideline / classification name")
    context: str = Field(description="One-line clinical context from report generation")
    type: str = Field(description="classification | uk_pathway | other")
    source_url: Optional[str] = Field(default=None, description="URL of scraped source when available")
    criteria_summary: Optional[str] = Field(
        default=None,
        description="Truncated excerpt of criteria text sent to the audit model (full text in DB cache)",
    )
    criteria_summary_truncated: bool = Field(
        default=False,
        description="True if criteria_summary is shorter than the full cached text",
    )
    injected: bool = Field(
        description="True if non-empty criteria text was appended to the audit prompt for this system"
    )


class AuditGuidelineRef(BaseModel):
    """Trimmed guideline row sent with chat `audit_fix_context` (criteria capped client-side)."""

    system: str = Field(description="Canonical guideline / classification name")
    type: str = Field(description="classification | uk_pathway | other")
    context: str = Field(default="", description="One-line clinical context from report generation")
    criteria_summary: Optional[str] = Field(
        default=None,
        description="Truncated criteria excerpt for chat grounding (not full cache text)",
    )


def _default_clinical_flagging_rationale(data: dict) -> str:
    """When the model omits top-level rationale on clinical_flagging, derive a minimal UK English line."""
    banners = data.get("suggested_banners") or []
    flags = data.get("flags_identified") or []
    parts: List[str] = []
    if banners:
        cats = [
            str(b.get("category", ""))
            for b in banners
            if isinstance(b, dict) and b.get("category")
        ]
        if cats:
            parts.append(
                f"{len(banners)} communication banner(s) suggested ({', '.join(cats)})."
            )
    present_types = [
        str(f.get("type", ""))
        for f in flags
        if isinstance(f, dict) and f.get("present")
    ]
    if present_types:
        parts.append("Sub-flags marked present: " + ", ".join(present_types) + ".")
    st = data.get("status", "pass")
    if not parts:
        return (
            f"Clinical flagging assessed (status {st}); see flags_identified for "
            "sub-flag detail — no banner indicated or detail carried in structured fields only."
        )
    return " ".join(parts)


class AuditFixContext(BaseModel):
    """Structured audit grounding for Fix-with-AI chat — must stay in sync with frontend `AuditFixContext`."""

    audit_id: str = Field(default="", description="Persisted audit UUID when available")
    criterion: str = Field(description="Audit criterion key, e.g. recommendations")
    rationale: str = Field(description="Deficiency-focused rationale from the audit")
    criterion_line: Optional[str] = Field(
        default=None,
        description="Single guideline rule line from audit when populated",
    )
    highlighted_spans: List[str] = Field(
        default_factory=list,
        description="Verbatim report spans from the audit",
    )
    suggested_replacement: Optional[str] = Field(
        default=None,
        description="One-click replacement text from audit when present",
    )
    guideline_references: List[AuditGuidelineRef] = Field(
        default_factory=list,
        description="Per-reference grounding; criteria_summary already capped for chat",
    )


class AuditResult(BaseModel):
    """Complete audit result for a radiology report.

    Phase 1 returns 6 criteria (1a input_fidelity + 1b x5).
    Phase 2 appends 3 more (recommendations, clinical_flagging, characterisation_gap).
    Partial results (5-8 criteria) are valid during progressive rendering.
    """

    overall_status: Literal["pass", "flag", "warning"] = Field(
        description="Overall audit status - worst status among all criteria"
    )
    criteria: List[AuditCriterion] = Field(
        min_length=1,
        max_length=9,
        description="1-9 criterion evaluations (6 from Phase 1, up to 9 after Phase 2 merge)"
    )
    summary: str = Field(
        description="High-level summary of audit findings and key issues (British English only)"
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_llm_audit_payload(cls, data: Any) -> Any:
        """Recover common provider mistakes: stringified criteria JSON, missing summary, missing clinical_flagging rationale."""
        if not isinstance(data, dict):
            return data
        out = dict(data)

        cr = out.get("criteria")
        if isinstance(cr, str):
            s = cr.strip()
            if s.startswith("["):
                try:
                    out["criteria"] = json.loads(s)
                except json.JSONDecodeError:
                    pass

        summ = out.get("summary")
        if summ is None or (isinstance(summ, str) and not summ.strip()):
            os = out.get("overall_status", "completed")
            out["summary"] = (
                f"Overall audit status: {os}. See per-criterion rationales for detail."
            )

        crit_list = out.get("criteria")
        if isinstance(crit_list, list):
            fixed: List[Any] = []
            for item in crit_list:
                if not isinstance(item, dict):
                    fixed.append(item)
                    continue
                d = dict(item)
                if d.get("criterion") == "clinical_flagging":
                    r = d.get("rationale")
                    if r is None or (isinstance(r, str) and not r.strip()):
                        d["rationale"] = _default_clinical_flagging_rationale(d)
                fixed.append(d)
            out["criteria"] = fixed

        return out


# ============================================================================
# Audit Phase LLM Output Wrappers
# ============================================================================

class Phase1aOutput(BaseModel):
    """Structured LLM output for Phase 1a: input_fidelity (single criterion)."""
    criterion: str = "input_fidelity"
    status: Literal["pass", "warning", "flag"]
    rationale: str = ""
    highlighted_spans: List[str] = Field(default_factory=list)
    recommendation: Optional[str] = None
    discrepancies: List[InputDiscrepancy] = Field(default_factory=list)


class Phase1bOutput(BaseModel):
    """Structured LLM output for Phase 1b: 4 report-integrity criteria."""
    criteria: List[AuditCriterion] = Field(min_length=4, max_length=4)


class Phase2Output(BaseModel):
    """Structured LLM output for Phase 2: 4 guideline-compliance criteria."""
    criteria: List[AuditCriterion] = Field(min_length=4, max_length=4)


# ============================================================================
# Comparison Analysis Models
# ============================================================================

class Measurement(BaseModel):
    """Extracted measurement with context"""
    value: str = Field(description="Numerical value as string (e.g., '3.8')")
    unit: str = Field(description="Unit of measurement (e.g., 'cm', 'mm')")
    raw_text: str = Field(description="Original phrase from report")

class PriorState(BaseModel):
    """State of a finding in a prior report"""
    date: str = Field(description="Date of prior report (UK format DD/MM/YYYY)")
    measurement: Optional[Measurement] = None
    description: Optional[str] = None

class FindingComparison(BaseModel):
    """A single finding's comparison analysis"""
    name: str = Field(description="Finding name (e.g., 'Right upper lobe nodule')")
    location: str = Field(description="Anatomic location details")
    
    status: Literal["changed", "stable", "new", "not_mentioned"] = Field(
        description="Temporal status: compares current to most recent prior. For multiple priors, use trend field."
    )
    
    # Single prior state (for backward compatibility and simple cases)
    prior_measurement: Optional[Measurement] = None
    prior_description: Optional[str] = None
    prior_date: Optional[str] = None
    
    # Multiple prior states (for progression tracking across multiple scans)
    prior_states: List[PriorState] = Field(
        default_factory=list,
        description="List of prior report states when multiple priors exist, ordered chronologically (oldest first)"
    )
    
    # Trend analysis for multiple priors
    trend: Optional[str] = Field(
        None,
        description="Progression trend when multiple priors exist. Describe the clinical trajectory faithfully: direction of change, magnitude (measurements and calculated rates where meaningful), and the time frame involved. The goal is a compact, factually complete narrative of trajectory that Stage 2 can draw on to write natural prose — not a template for how that prose should be phrased. Do not prescribe inline date formatting here."
    )
    
    current_measurement: Optional[Measurement] = None
    current_description: Optional[str] = None
    
    assessment: str = Field(
        description="Model's contextual analysis of the change and clinical significance, including trend analysis if multiple priors"
    )

class ChangeDirective(BaseModel):
    """Structured directive for Stage 2 report modification"""
    finding_name: str = Field(
        description="Name of the finding being addressed"
    )
    location: str = Field(
        description="Anatomical location of the finding"
    )
    change_type: str = Field(
        description="Type of change: 'new', 'changed', 'resolved', or 'stable'"
    )
    integration_strategy: str = Field(
        description="How to integrate this change into the report (e.g., 'Add to Findings after discussion of X', 'Update Comparison section', 'Modify Impression')"
    )
    measurement_data: Optional[dict] = Field(
        default=None,
        description="Structured measurement data including prior/current values, changes, and dates"
    )
    clinical_significance: str = Field(
        description="Brief clinical interpretation for context"
    )
    section_target: str = Field(
        description="Primary target section: 'Comparison', 'Findings', 'Impression', or 'Multiple'"
    )

class ComparisonAnalysisStage1(BaseModel):
    """Stage 1: Pure analysis with structured change directives"""
    findings: List[FindingComparison] = Field(
        description="All findings analyzed with status classification"
    )
    summary: str = Field(
        description="High-level synthesis of changes and clinical implications"
    )
    change_directives: List[ChangeDirective] = Field(
        default_factory=list,
        description="Structured directives for Stage 2 report integration (NOT text replacements)"
    )

class ComparisonReportGeneration(BaseModel):
    """Stage 2: Generated report with documented changes"""
    revised_report: str = Field(
        description="Complete rewritten report with comparison language integrated"
    )
    key_changes: List[dict] = Field(
        default_factory=list,
        description="5-7 most significant actual changes made for UI display: {original, revised, reason}"
    )

class ComparisonAnalysis(BaseModel):
    """Complete two-stage comparison analysis result"""
    findings: List[FindingComparison] = Field(
        description="All findings analyzed with status classification (from Stage 1)"
    )
    summary: str = Field(
        description="High-level synthesis of changes and clinical implications (from Stage 1)"
    )
    change_directives: List[ChangeDirective] = Field(
        default_factory=list,
        description="Structured directives used for report generation (from Stage 1)"
    )
    revised_report: str = Field(
        description="Complete rewritten report with comparison language integrated (from Stage 2)"
    )
    key_changes: List[dict] = Field(
        default_factory=list,
        description="Actual text changes made for UI highlighting (from Stage 2): {original, revised, reason}"
    )

