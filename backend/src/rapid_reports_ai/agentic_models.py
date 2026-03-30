"""
Pydantic models for the agentic planning-then-execution report pipeline.
These types are used exclusively by agentic_pipeline.py and agentic_routes.py.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal


# ============================================================================
# Supporting types for ReportPlan
# ============================================================================

RetrievalIntentKind = Literal[
    "staging_taxonomy",
    "surveillance_protocol",
    "classification_scale",
    "acute_severity",
    "pathway_trigger",
    "general_reference",
]


class RetrievalIntent(BaseModel):
    """High-yield external evidence lookup — drives Phase 1.5 Perplexity queries."""

    intent: RetrievalIntentKind = Field(
        description="Type of clinical knowledge to retrieve for this case."
    )
    anchor_finding: str = Field(
        description="Short phrase tying this lookup to a specific finding or question."
    )
    optional_params: Optional[str] = Field(
        default=None,
        description="Optional query conditioning: organ, size, histology, etc.",
    )
    rationale: str = Field(
        description="One line why this retrieval is high-yield for this case."
    )


class CompanionFinding(BaseModel):
    structure: str = Field(description="e.g. 'right heart strain'")
    status: Literal["present", "absent", "not_mentioned", "not_assessable"]
    companion_type: Literal["clinical_cluster", "systematic_sweep"] = Field(
        description=(
            "clinical_cluster: inseparable from the index abnormality in the primary finding paragraph. "
            "systematic_sweep: place during systematic review in the appropriate anatomical region."
        )
    )
    detail: Optional[str] = Field(
        default=None,
        description="e.g. 'RV:LV ratio, septal bowing' or aetiological context for not_mentioned"
    )


class RecommendationDecision(BaseModel):
    """
    Typed list entry — replacing Dict[str, Optional[str]] for reliable pydantic-ai structured output.
    """

    finding: str = Field(description="e.g. 'bilateral pulmonary emboli'")
    recommendation: Optional[str] = Field(
        default=None,
        description="e.g. 'urgent respiratory referral'; None if no action required"
    )


class ImpressionPlan(BaseModel):
    included_findings: List[str]
    management_altering_negatives: List[str] = Field(
        default_factory=list,
        description=(
            "Negatives that directly alter management decisions — state as clinical conclusions in IMPRESSION. "
            "Examples: 'No perforation' (appendicitis — determines laparoscopic vs open), "
            "'No haemorrhage' (acute stroke — determines thrombolysis eligibility), "
            "'No obstruction' (bowel wall thickening — determines conservative vs surgical). "
            "Do NOT put these in excluded_from_impression."
        )
    )
    excluded_from_impression: List[str]
    recommendation_decisions: List[RecommendationDecision]
    is_normal_scan: bool


class ClinicalContextItem(BaseModel):
    item: str
    management_impact: str


# ============================================================================
# ReportPlan — the central planning type
# ============================================================================

class ReportPlan(BaseModel):
    """
    Output of Phase 1 (planning agent). Clinical intelligence only — no structural sweep plan.
    dictation_brief is the primary executor input — a prose narration of the structured fields.
    _build_execution_brief() is retained as dead code during the hybrid evaluation phase.
    """

    # Step 1
    clinical_question: str

    # Step 2
    primary_diagnosis: str

    # Step 3
    supporting_findings: List[str]

    # Step 4
    excluded_differentials: List[str]

    # Step 5
    unexplained_findings: List[str]

    # Step 6 — companion findings (Phase 3 / brief COMPANION OBLIGATIONS)
    companion_findings: List[CompanionFinding]

    # Step 7
    cross_finding_connections: List[str]

    # Step 8 — impression plan (brief IMPRESSION CONTRACT)
    impression_plan: ImpressionPlan

    # Step 9
    clinical_context_items: List[ClinicalContextItem]

    # Routing metadata
    modality: str
    body_region: str
    retrieval_intents: List[RetrievalIntent] = Field(
        default_factory=list,
        description="High-yield Perplexity lookups (staging, surveillance, classification, etc.); often empty.",
    )
    scan_type_extracted: str
    plan_confidence: Literal["high", "moderate", "low"]
    reasoning_summary: str = Field(description="Short summary for UI display and audit logs")

    # Step 11 — prose dictation brief (primary executor input)
    # Narration of committed structured fields. Derived from companion_findings,
    # cross_finding_connections, and impression_plan — introduces no new clinical content.
    dictation_brief: str = Field(
        min_length=300,
        description=(
            "Prose handover brief for the execution model. Written after all structured fields "
            "are committed and gates applied. Covers seven elements: clinical answer, severity frame, "
            "companion reasoning with why, relevant negatives, impression pre-synthesis, sweep "
            "completion naming, case-specific prohibitions."
        ),
    )

    # Retained for audit/debug — not injected into Phase 2 execution.
    execution_brief: Optional[str] = None


# ============================================================================
# API response types
# ============================================================================

class AgenticReportOutput(BaseModel):
    """
    Full agentic pipeline output. Drop-in compatible with ReportOutput:
    report_content, description, scan_type, model_used fields are identical.
    """

    report_content: str = Field(description="Complete radiology report text")
    description: str = Field(description="Brief summary for history tab")
    scan_type: str = Field(description="Extracted scan type and protocol")
    model_used: Optional[str] = None
    plan: ReportPlan
    plan_adherence_violations: List[str] = []
    pipeline_ms: Optional[int] = None


class PlanOnlyResponse(BaseModel):
    """Response for POST /api/v2/plan — Phase 1 only, evaluation endpoint."""

    plan: ReportPlan
    plan_ms: int


class CompareResponse(BaseModel):
    """Response for POST /api/v2/compare — side-by-side A/B outputs."""

    current_output: str
    agentic_output: str
    plan: ReportPlan
    current_ms: int
    agentic_ms: int


class MonolithicCompareResponse(BaseModel):
    """Response for POST /api/v2/compare-monolithic — classic vs clinical-clusters prompt, same primary model."""

    classic_output: str
    clinical_clusters_output: str
    classic_ms: int
    clusters_ms: int
    model_used: Optional[str] = None


class AgenticGenerateRequest(BaseModel):
    """Request body shared by all /api/v2/* endpoints."""

    clinical_history: str
    scan_type: str
    findings: str
    prior_report: str = ""
    skip_guidelines: bool = False
