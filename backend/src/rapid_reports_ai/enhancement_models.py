"""
Pydantic models for AI-powered report enhancement
All structured outputs use these typed models for validation and type safety
Pure Pydantic validation - no custom field validators or regex processing
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal


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
# Completeness Analysis Models
# ============================================================================

class AnalysisSummary(BaseModel):
    """Overall completeness summary"""
    title: str = Field(
        max_length=100,
        description="Short heading (≤12 words) summarizing the report quality"
    )
    details: str = Field(
        min_length=50,
        description="2-3 sentence narrative describing overall impression, strengths, and concerns"
    )


class ReviewQuestion(BaseModel):
    """A review question for the radiologist to mentally confirm"""
    id: str = Field(
        description="Kebab-case slug identifier (e.g., 'confirm-hernia-measurements')"
    )
    prompt: str = Field(
        min_length=10,
        description="Plain sentence phrased as a review question with no leading numbering or bullets and no direct edit instructions"
    )


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


class CompletenessAnalysis(BaseModel):
    """Structured completeness analysis of a radiology report"""
    summary: AnalysisSummary = Field(
        description="Overall assessment of report completeness and quality"
    )
    questions: List[ReviewQuestion] = Field(
        min_length=2,
        max_length=4,
        description="2-4 review questions focused on contextual verification (no edit instructions)"
    )
    suggested_actions: List[SuggestedAction] = Field(
        default_factory=list,
        description="Optional specific changes to improve clarity/completeness; empty if report is complete"
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
# Protocol Validation Models
# ============================================================================

class ProtocolViolation(BaseModel):
    """A single protocol violation found in a radiology report"""
    violation_type: str = Field(
        description="Type of violation (e.g., 'contrast_on_noncontrast', 'duplication', 'hallucination', 'protocol_incompatibility')"
    )
    location: str = Field(
        description="Where in report the violation occurs (e.g., 'Findings section, line 3', 'Impression section')"
    )
    original_text: str = Field(
        description="The problematic text that violates the protocol"
    )
    issue: str = Field(
        description="Why this violates the scan protocol/type"
    )
    suggested_fix: str = Field(
        description="How to fix this violation"
    )


class ValidationResult(BaseModel):
    """Result of protocol validation check"""
    violations: List[ProtocolViolation] = Field(
        default_factory=list,
        description="List of protocol violations found. Empty list if no violations."
    )
    is_valid: bool = Field(
        description="True if no violations found, False if violations exist"
    )
    scan_type_checked: str = Field(
        description="The scan type that was validated against"
    )


# ============================================================================
# Report Generation Output Model
# ============================================================================

class ReportOutput(BaseModel):
    """Output from report generation - both auto and templated reports"""
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
        description="Progression trend when multiple priors exist. MUST include numerical/statistical details: actual measurement values, percentage changes, growth rates (e.g., mm/month), and time intervals. Example: 'Gradually increasing from 3.2 cm (15/09/2024) to 4.1 cm (22/09/2024) to 5.3 cm (current), representing 28% growth over 37 days (0.57 mm/day average)'"
    )
    
    current_measurement: Optional[Measurement] = None
    current_description: Optional[str] = None
    
    assessment: str = Field(
        description="Model's contextual analysis of the change and clinical significance, including trend analysis if multiple priors"
    )

class ComparisonAnalysisStage1(BaseModel):
    """Stage 1: Comparison analysis without revised report"""
    findings: List[FindingComparison] = Field(
        description="All findings analyzed with status classification"
    )
    summary: str = Field(
        description="High-level synthesis of changes and clinical implications"
    )
    key_changes: List[dict] = Field(
        default_factory=list,
        description="Important text changes for UI highlighting: {original, revised, reason}"
    )

class ComparisonAnalysis(BaseModel):
    """Complete comparison analysis with revised report"""
    findings: List[FindingComparison] = Field(
        description="All findings analyzed with status classification"
    )
    summary: str = Field(
        description="High-level synthesis of changes and clinical implications"
    )
    revised_report: str = Field(
        description="Complete rewritten report with comparison language integrated"
    )
    key_changes: List[dict] = Field(
        default_factory=list,
        description="Important text changes for UI highlighting: {original, revised, reason}"
    )

