#!/usr/bin/env python3
"""
Prefetch Pipeline Test Server

A standalone FastAPI development server for testing and tuning the guideline
prefetch pipeline before full integration into the production scaffold.

Pipeline stages:
  1. GLM Extract    — zai-glm-4.7 (reasoning ON, temp ≥0.8) → PrefetchContext from raw inputs
  2. Perplexity     — web search with TLD domain filter → candidate guideline URLs per query
  3. Firecrawl      — parallel targeted scrapes on selected URLs → authoritative content check

Usage (from backend/):
  poetry run python scripts/prefetch_pipeline_server.py
  # Then open http://localhost:8765 in your browser

The UI allows editing outputs between stages (e.g. tweak Perplexity queries before
running Stage 2, select/deselect URLs before running Stage 3).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# --- Path setup ------------------------------------------------------------------
_BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

_BACKEND_DIR = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND_DIR / ".env")
except ImportError:
    pass

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# --- Pipeline constants ----------------------------------------------------------

# Content-level geo-block signatures — pages that return HTTP 200 but serve an
# access-restriction message instead of real content (e.g. CKS behind UK-only wall).
# Checked after Tavily Extract so matched URLs are retried via ScraperAPI UK proxy.
_GEO_BLOCK_SIGNATURES = (
    "only available to eligible users within the uk",
    "cks via nice is only available",
    "not available in your region",
    "please access from within the uk",
    "restricted to users in the uk",
    "only accessible to users in the uk",
    "this content is only available",
)

PREFETCH_SYSTEM_PROMPT = """You are a UK clinical guideline specialist and senior radiologist.
Given radiology scan inputs, extract structured guideline retrieval data in a single reasoning pass.

Output ONLY valid JSON matching this exact schema:
{
  "consolidated_findings": ["finding1", "finding2"],
  "finding_short_labels": ["label1", "label2"],
  "applicable_guidelines": [
    {
      "system": "canonical name ≤60 chars",
      "type": "uk_pathway | classification | other",
      "search_keywords": "3-8 tokens for Perplexity/Firecrawl search",
      "context": "one sentence — why this guideline applies"
    }
  ],
  "urgency_signals": ["signal1"],
  "query_plan": {
    "pathway_followup": [
      "[Publisher] [doc type] [condition] [key action] — UK pathway/referral/follow-up"
    ],
    "classification_measurement": [
      "[Named system] [condition] criteria tables OR measurement thresholds [unit]"
    ],
    "imaging_differential": [
      "[Modality] [condition] imaging features OR differential diagnosis appearances"
    ]
  }
}

Rules:
- consolidated_findings: each entry represents ONE distinct clinical pathway — a suspected
    diagnosis or disease process that routes to a specific specialist or investigation sequence.

    STEP 1 — Group by implied diagnosis:
    Read all findings, scan type, and clinical history together. Identify the underlying
    suspected diagnoses. Cluster all imaging features that collectively describe ONE disease
    process under a single entry. The operative test is:
      "Do these features all point to the same suspected diagnosis and lead to the same
       specialist or management pathway?"
    If yes → one finding, not multiple. A complex disease process with multiple imaging features
    (primary mass + biliary obstruction + vascular encasement + elevated tumour marker) is
    ONE clinical decision, not four. Produce a rich label that captures the primary diagnosis
    and key imaging determinants:
      ✓ "Suspected Klatskin cholangiocarcinoma — 2.8cm hilar mass, type IIIA biliary stricture,
         left portal vein encasement" (one entry, not three)
      ✓ "Incidental 8mm solid right upper lobe pulmonary nodule" (one entry covering all features)

    STEP 2 — Separate only genuinely independent pathways:
    Keep findings as separate entries only when they route to demonstrably different specialists
    or management pathways:
      ✓ Renal mass (urology/BAUS) + adrenal nodule (endocrine) + lung nodule (respiratory/BTS)
        → three separate entries, each with a distinct pathway
      ✗ Hilar mass + portal vein encasement + biliary dilatation → same HPB pathway → one entry

    STEP 3 — Exclude non-findings:
    Never include in any entry:
    • Negative or exclusion statements ("no lymphadenopathy", "no macroscopic fat")
    • Background observations with no independent workup pathway (mild emphysema, fatty liver,
      degenerative change, incidental vertebral changes)
    • Lab or clinical values from the history (CA 19-9, PSA, AFP, creatinine) — these are
      risk context for the primary finding, not findings themselves

    RESULT: one entry per distinct clinical pathway — one entry for a single complex disease
    process, several entries for genuinely independent incidental findings each requiring a
    different specialist or investigation sequence.
- finding_short_labels: parallel array aligned 1:1 with consolidated_findings. Each entry is
    a concise display label ≤5 words: primary diagnosis + key qualifier only.
    Examples: "Klatskin tumour (suspected)", "Bosniak IIF renal cyst",
              "8mm lung nodule (high-risk)", "Adrenal adenoma (indeterminate)"
    Strip all measurements, anatomy lists, and tumour marker values — those belong in
    consolidated_findings. The short label is for card titles and console display only.
- applicable_guidelines: at most 4, uk_pathway before classification, UK-first
  • Only name guideline bodies you are certain exist as recognised UK specialty societies.
    Permitted bodies include: NICE, SIGN, RCR, BSG, BTS (brit-thoracic.org.uk), AUGIS,
    BAUS, RCOG, RCP, RCSEng, RCPCH, BSGE, BHRS, BSIR, BASL, UKONS, PCUK, CRUK.
    Do NOT invent acronyms or name bodies you are uncertain about — use a descriptive name
    instead (e.g. "UK HPB specialist society guidance") rather than a fabricated acronym.
    A hallucinated body name produces irrelevant search queries with no return.
  • Use NICE guideline codes only when you are confident they are correct. If uncertain,
    use a descriptive name ("NICE gallstone disease guidance") — a wrong number produces
    irrelevant search results. Never substitute a cancer referral pathway (e.g. NG12) as
    the primary management guideline for an active disease process; specialty management
    guidelines (NICE disease-specific, BSG, RCR, BAUS etc.) take precedence unless the
    primary clinical question is ruling out malignancy.
  • CLASSIFICATION SYSTEM SCOPE-CHECK: Before naming any classification/scoring system,
    verify the finding satisfies ALL THREE of that system's scope conditions:
      (1) correct anatomy/organ — necessary but not sufficient
      (2) correct imaging characteristics — e.g. solid vs cystic, enhancement pattern, modality
      (3) correct clinical context — incidental vs known disease, high-risk vs low-risk patient
    High-risk mismatches to avoid:
      - Bosniak → CYSTIC renal masses only (fluid, septa, calcification). A solid enhancing
        renal lesion with no cystic component requires BAUS solid renal mass guidelines instead.
      - LI-RADS → hepatic lesions in cirrhosis / chronic HBV / known HCC risk ONLY.
        An incidental liver lesion in a low-risk patient requires RCR incidental findings
        guidance or EASL, not LI-RADS.
      - Fleischner / Brock model → incidental nodules in patients WITHOUT known malignancy.
        A nodule in a known-cancer patient requires NICE NG122 / BTS staging guidance, not
        an incidental nodule surveillance system.
    When the scope does not match, name the correct alternative system explicitly rather
    than omitting the classification entry entirely.
- urgency_signals: time-sensitive clinical observations only (empty list if none)
- query_plan: THREE branches, each with 2-4 queries (hard max 5 per branch — API limit):

    pathway_followup    → target UK management pathways, follow-up intervals, referral criteria.
                          Structure each query as: [PUBLISHER] [document type] [condition] [key action]
                          e.g. "[Society] guidelines [condition] management pathway UK"
                               "NICE CG188 gallstone disease management pathway recommendations"
                               "RCR iRefer [modality/organ] imaging referral criteria UK"
                          ALWAYS include at least one query targeting the relevant UK specialist
                          society for the organ system (BSG for GI/hepatobiliary, BTS for thoracic,
                          AUGIS for upper GI surgery, BAUS for urology, RCOG for obstetric,
                          RCR for imaging pathways, RCP for general medicine).
                          Use the society name explicitly — not just NICE.
                          ALWAYS include one CKS (Clinical Knowledge Summaries) query for the
                          specific management scenario:
                          "CKS NICE [condition] management scenario UK"
                          CKS pages are scenario-specific and directly searchable.
                          If a NICE guideline number is known with confidence, include it.
                          English only.

    classification_measurement → target recognised classification, staging, and grading systems with
                          their actual criteria tables and boundary definitions, plus measurement
                          technique protocols (thresholds, units, cut-offs). English only.

                          STAGING FRAMEWORK RULE: Authoritative UICC TNM 9th Edition data is
                          available locally and injected at synthesis time. For each consolidated
                          finding involving suspected/confirmed malignancy, determine:
                            1. What is the PRIMARY staging framework used in MDT communication
                               for this tumour type?
                               — FIGO for gynaecological cancers (endometrial, cervical,
                                 ovarian/fallopian tube, vulval, GTD)
                               — Ann Arbor / Lugano for lymphoma
                               — WHO grade for CNS tumours
                               — UICC TNM for most other solid organ malignancies
                            2. If the primary framework IS TNM → do NOT generate TNM queries
                               (local data covers it). Use slots for specialist classifications
                               and biomarker thresholds instead.
                            3. If the primary framework is NOT TNM (e.g. FIGO, Ann Arbor, WHO
                               grade) → generate a query targeting that system's criteria table
                               with the current edition and full stage definitions. TNM is still
                               available as supplementary but the primary query slot must target
                               the framework the MDT actually uses.
                          In all cases, also use slots for:
                            (a) SPECIALIST classifications that inform surgical planning or risk
                                stratification (e.g. resectability criteria, Bosniak, LI-RADS,
                                Fleischner, BCLC, BIRADS).
                            (b) MEASUREMENT TECHNIQUE protocols and biomarker cut-offs (e.g.
                                adrenal washout, HU thresholds, CA 19-9, AFP, CA-125).
                          The goal is to retrieve evidence that COMPLEMENTS the local TNM data —
                          primary non-TNM frameworks, specialist criteria, and thresholds.

    imaging_differential → target imaging features per modality (CT HU, MRI signal, US echogenicity),
                          characteristic appearances, and differential diagnosis imaging features.
                          English only."""

# ── Branch A: UK pathway / follow-up ──────────────────────────────────────────
# Targets named UK specialist society and NHS pathway documents.
# Feeds → follow_up_imaging, diagnostic_overview (pathway context)
DOMAIN_FILTER_PATHWAY = [
    "nice.org.uk",          # NICE clinical guidelines (full guideline pages)
    "cks.nice.org.uk",      # NICE Clinical Knowledge Summaries (management scenarios — well-indexed)
    "sign.ac.uk",           # SIGN Scottish guidelines
    "rcr.ac.uk",            # RCR iRefer + imaging guidelines
    "rcog.org.uk",          # Royal College of Obstetricians
    "bsg.org.uk",           # British Society of Gastroenterology
    "augis.org.uk",         # Association of Upper GI Surgeons
    "baus.org.uk",          # British Association of Urological Surgeons
    "rcseng.ac.uk",         # Royal College of Surgeons England
    "rcp.ac.uk",            # Royal College of Physicians
    # NOTE: bts.org.uk REMOVED — Tavily indexes British Transplantation Society abstract
    # books under this domain, not clinical guidelines. For thoracic cases use
    # brit-thoracic.org.uk instead (add per-case if needed).
]

# ── Branch B: Classification systems / measurement protocols ──────────────────
# Targets society classification papers, criteria tables, and technique specs.
# Feeds → classification_systems, measurement_protocols
DOMAIN_FILTER_CLASSIFICATION = [
    "radiopaedia.org",              # Structured educational reference articles
    "rsna.org",                     # RSNA technical + classification guidelines
    "bir.org.uk",                   # British Institute of Radiology specs
    "pubmed.ncbi.nlm.nih.gov",      # PubMed — original classification papers
    "pmc.ncbi.nlm.nih.gov",         # PMC full text
]

# ── Branch C: Imaging features / differential diagnosis ───────────────────────
# Targets imaging-feature articles and DDx literature.
# Feeds → imaging_characteristics, differential_diagnoses, diagnostic_overview
DOMAIN_FILTER_DIFFERENTIAL = [
    "radiopaedia.org",              # Per-feature structured articles (best DDx source)
    "pubmed.ncbi.nlm.nih.gov",      # PubMed review articles
    "pmc.ncbi.nlm.nih.gov",         # PMC full text reviews
    "rsna.org",                     # RSNA educational articles
]

# Branch label metadata (used by UI)
BRANCH_META = {
    "pathway_followup": {
        "label": "Pathway / Follow-up",
        "domains": DOMAIN_FILTER_PATHWAY,
        "feeds": "follow_up_imaging · pathway context",
        "color": "var(--accent)",
    },
    "classification_measurement": {
        "label": "Classification / Measurement",
        "domains": DOMAIN_FILTER_CLASSIFICATION,
        "feeds": "classification_systems · measurement_protocols",
        "color": "var(--purple)",
    },
    "imaging_differential": {
        "label": "Imaging Features / DDx",
        "domains": DOMAIN_FILTER_DIFFERENTIAL,
        "feeds": "imaging_characteristics · differential_diagnoses",
        "color": "var(--green)",
    },
}

# Fallback: open-web (no domain restriction)
DOMAIN_FILTER_OPEN: List[str] = []

# --- Inline Pydantic models (mirrors the planned enhancement_models.py additions) -

class ApplicableGuidelineItem(BaseModel):
    system: str
    type: str
    search_keywords: Optional[str] = None
    context: Optional[str] = None


class QueryPlan(BaseModel):
    """Three-branch query plan — each branch targets different domain groups."""
    pathway_followup: List[str] = Field(
        default_factory=list,
        description="Queries for UK management pathways/follow-up → NICE/RCR/BTS domains",
    )
    classification_measurement: List[str] = Field(
        default_factory=list,
        description="Queries for classification criteria + measurement thresholds → RSNA/Radiopaedia/BIR",
    )
    imaging_differential: List[str] = Field(
        default_factory=list,
        description="Queries for imaging features + DDx → Radiopaedia/PubMed",
    )

    def total_queries(self) -> int:
        return len(self.pathway_followup) + len(self.classification_measurement) + len(self.imaging_differential)

    def as_dict(self) -> Dict[str, List[str]]:
        return {
            "pathway_followup": self.pathway_followup,
            "classification_measurement": self.classification_measurement,
            "imaging_differential": self.imaging_differential,
        }


class PrefetchContext(BaseModel):
    consolidated_findings: List[str] = Field(default_factory=list)
    finding_short_labels: List[str] = Field(default_factory=list)
    applicable_guidelines: List[ApplicableGuidelineItem] = Field(default_factory=list)
    urgency_signals: List[str] = Field(default_factory=list)
    query_plan: QueryPlan = Field(default_factory=QueryPlan)


# --- Stage 2.5: Triage prompt + models ------------------------------------------

TRIAGE_SYSTEM_PROMPT = """You are a clinical evidence triage specialist for a radiology AI pipeline.

Given a set of candidate URLs found by search (with titles, domains, relevance scores, and
already-retrieved preview text), decide how each should be processed for Stage 3 extraction.

ROUTING OPTIONS:
  deep_extract — perform full page extraction (JS rendering). Use for:
    • Canonical UK guideline pages (nice.org.uk, cks.nice.org.uk, sign.ac.uk, rcr.ac.uk,
      bsg.org.uk, rcog.org.uk, rcseng.ac.uk, augis.org.uk, baus.org.uk, rcp.ac.uk) when
      the page TITLE or URL path clearly indicates diagnostic/imaging guidance — words like
      "management", "recommendations", "guidance", "criteria", "pathway", "iRefer",
      "referral", "imaging", "diagnosis". Domain authority alone is NOT sufficient —
      the page must address the diagnostic or imaging workup question for the clinical
      finding, not treatment planning or surgical technique.
      NOTE: These SPA pages are often indexed sparsely by search engines — a low score
      (0.4–0.6) does NOT mean the page is irrelevant. Judge by the title and domain,
      not the score. A NICE recommendations page at score 0.5 beats a PMC paper at 1.0
      for the pathway_followup branch.
    • Any page where the inline preview shows rendering gaps — navigation menus, cookie
      notices, "CKS is only available in the UK", login prompts, or boilerplate marketing
      text. These signals confirm a JS SPA whose clinical content has not loaded; full
      extraction will retrieve the actual page body regardless of how much text is visible.
    • Classification criteria pages where the criteria table lives in the full page body
      rather than the abstract snippet.
    HARD LIMIT: never exceed max_deep_extract deep_extract decisions.
    Candidates marked [INLINE-ONLY] must be routed use_inline or skip.

  use_inline — use the content already retrieved from search indexing. Use for:
    • Any page where the inline preview contains clinically actionable content for this branch:
      imaging features, classification criteria, measurement thresholds, management
      recommendations, referral triggers, diagnostic statistics, or biomarker cut-offs.
      Judge on CONTENT QUALITY, not content length — a 90-character PubMed snippet containing
      a sensitivity/specificity value for this condition is more useful than a 1,000-character
      methodology section. Do not skip a source merely because its preview is brief.
    • PMC full-text articles, PubMed abstracts, Radiopaedia articles, and similar sources
      whose preview demonstrates relevant clinical data for the branch.
    • Any canonical UK guideline page marked [INLINE-ONLY] that cannot be deep_extracted —
      use the inline preview even if sparse; partial content is better than no content.

  skip — discard entirely. Use for:
    • Navigation/index pages (e.g. NICE "published guidance" list, NICE research recommendations)
    • Wrong therapeutic area or wrong patient population for the clinical context provided
    • Evidence appendix pages, surveillance reviews, abstract books, conference proceedings,
      annual review reports, commissioning guides, donor transplant guidelines
    • Duplicate content (same paper already selected with another action)
    • Score < 0.1 or title is clearly irrelevant to the finding
    • Completely empty inline content with no title or domain evidence of relevance
    • Any URL whose title contains "Abstract Book", "Annual Review", "Congress Abstracts",
      "Living Donor", "Commissioning Guide", "Appendix", "Surveillance Review"
    • Cancer referral pathway pages (e.g. NG12) when the clinical case involves an active,
      confirmed disease process — prefer disease-specific management guidelines (NICE CG/NG,
      BSG, RCR, BAUS) for pathway_followup deep_extract instead.
    • Treatment planning and clinical oncology documents — radiotherapy dose fractionation
      guides, chemotherapy protocols, preoperative radiotherapy schedules, and palliative
      dosing documents. These contain no diagnostic imaging pathways, referral criteria, or
      follow-up intervals. Reliable signal: if your own extract_hint or reason naturally
      includes "radiotherapy", "dose fractionation", "chemotherapy", or "fractionation
      schedule" — skip it regardless of domain authority.

For each deep_extract decision, write an extract_hint: a 5–12 word targeted query naming the
specific criteria, threshold, or pathway step the page should contain.

For every decision, set finding_indices: 0-based indices into consolidated_findings[].
  • Specific to one finding → [0] or [1] etc.
  • Spans multiple findings → [0, 1]
  • General context for all findings → []

Output ONLY valid JSON:
{
  "decisions": [
    {
      "url": "...",
      "action": "deep_extract" | "use_inline" | "skip",
      "branch": "pathway_followup" | "classification_measurement" | "imaging_differential",
      "extract_hint": "..." (deep_extract only; null otherwise),
      "reason": "one brief phrase",
      "finding_indices": [0] | [0, 1] | []
    }
  ]
}"""


TRIAGE_RECOVERY_SYSTEM_PROMPT = """You are a clinical evidence recovery specialist for a radiology AI pipeline.

The primary triage identified no evidence for one or more critical branches. Your task is to find
the BEST available sources from the candidates below to cover those gaps. These candidates were
already reviewed and skipped — re-evaluate them with more lenient criteria.

ROUTING RULES (recovery mode):
  deep_extract — full page extraction. Use for:
    • Canonical UK guideline bodies (bsg.org.uk, nice.org.uk, rcr.ac.uk, cks.nice.org.uk,
      sign.ac.uk, rcog.org.uk, augis.org.uk, baus.org.uk, rcp.ac.uk) whose title or URL
      path has ANY connection to the clinical condition or organ system — even indirect. These
      are authoritative sources and full extraction often reveals content not visible in the
      inline preview. In recovery mode, err toward deep_extract for these domains.
    • Any page whose inline preview shows navigation or boilerplate rather than clinical text.
    HARD LIMIT: never exceed max_deep_extract.
    [INLINE-ONLY] marked candidates must use use_inline or skip.

  use_inline — use already-retrieved content. Use for:
    • Any source where the title, domain, or inline preview suggests partial relevance to the
      finding or branch. In recovery mode, marginal relevance is acceptable — the synthesis
      model will handle filtering. A source that mentions the condition name, organ system, or
      related specialty is worth including.
    • All PMC, PubMed, or Radiopaedia sources related to the condition even loosely.

  skip — ONLY if definitively irrelevant:
    • Wrong specialty or condition (e.g. paediatric guideline for adult case)
    • Treatment planning / oncology protocol with no diagnostic or imaging content
    • Completely unrelated clinical domain

PRIORITY: For each starved branch, you MUST route at least one candidate to deep_extract or
use_inline if any remotely relevant candidate exists. An empty branch means the clinical
synthesis for that domain fails entirely — any source is better than none.

Output ONLY valid JSON:
{
  "decisions": [
    {
      "url": "...",
      "action": "deep_extract" | "use_inline" | "skip",
      "branch": "pathway_followup" | "classification_measurement" | "imaging_differential",
      "extract_hint": "..." (deep_extract only; null otherwise),
      "reason": "one brief phrase",
      "finding_indices": [0] | [0, 1] | []
    }
  ]
}"""

# Domains that need deep extraction (JS SPAs — Tavily search index returns sparse content)
DEEP_EXTRACT_DOMAINS = {
    "nice.org.uk", "cks.nice.org.uk", "www.nice.org.uk",
    "sign.ac.uk", "www.sign.ac.uk",
    "rcr.ac.uk", "www.rcr.ac.uk",
    "bsg.org.uk", "www.bsg.org.uk",
    "rcog.org.uk", "www.rcog.org.uk",
    "rcseng.ac.uk", "www.rcseng.ac.uk",
    "augis.org.uk", "www.augis.org.uk",
    "baus.org.uk", "www.baus.org.uk",
    "rcp.ac.uk", "www.rcp.ac.uk",
}

# Publisher-gated journals and NICE full PDFs that either fail Tavily extraction or return
# oversized junk HTML via ScraperAPI fallback. Identified pre-triage so the LLM reasons
# over an accurate candidate pool and its deep_extract budget lands on real targets.
_DEEP_EXTRACT_BLOCK_PUBLISHERS = {
    "pubs.rsna.org",
    "onlinelibrary.wiley.com",
    "journals.lww.com",
    "jamanetwork.com",
    "springer.com",
    "link.springer.com",
    "nejm.org",
    "bmj.com",
    "thelancet.com",
    "academic.oup.com",
    "tandfonline.com",
    "journals.sagepub.com",
}


def _is_deep_extract_blocked(url: str, domain: str) -> bool:
    """Return True if this URL must not be sent to deep_extract.

    Covers:
    - Publisher-gated journals: Tavily extraction fails → ScraperAPI fallback returns
      oversized raw HTML with near-zero signal density.
    - NICE full PDF URLs: large documents that extract slowly and yield poorly-targeted
      chunks. Pattern: nice.org.uk + /resources/ path + numeric/hash suffix.
    """
    clean = domain.replace("www.", "").lower()
    if clean in _DEEP_EXTRACT_BLOCK_PUBLISHERS:
        return True
    if clean in ("nice.org.uk",):
        if "/resources/" in url and ("-pdf-" in url or url.rsplit("/", 1)[-1].replace("-", "").isdigit()):
            return True
    return False


# --- Request/response models -----------------------------------------------------

class TriageURLItem(BaseModel):
    url: str
    title: str = ""
    domain: str = ""
    score: float = 0.0
    branch: str = ""
    inline_content: str = ""

    @property
    def inline_content_chars(self) -> int:
        return len(self.inline_content)


class TriageDecision(BaseModel):
    url: str
    action: str  # "deep_extract" | "use_inline" | "skip"
    branch: str
    extract_hint: Optional[str] = None
    reason: Optional[str] = None
    finding_indices: List[int] = Field(
        default_factory=list,
        description="0-based indices into consolidated_findings[] this URL primarily serves. "
                    "Use [] for content relevant to all findings (e.g. general classification systems)."
    )


class TriageResult(BaseModel):
    decisions: List[TriageDecision] = Field(default_factory=list)


class TriageRequest(BaseModel):
    prefetch_context: Dict[str, Any]
    candidates: List[TriageURLItem]
    max_deep_extract: int = 3


class StructuredExtractRequest(BaseModel):
    decisions: List[TriageDecision]
    candidates: List[TriageURLItem]  # needed for inline content passthrough
    guideline_system: str = ""


class ExtractRequest(BaseModel):
    findings: str
    scan_type: str = ""
    clinical_history: str = ""


class DiscoverRequest(BaseModel):
    # Structured 3-branch plan (preferred — from Stage 1 query_plan)
    query_plan: Optional[Dict[str, List[str]]] = None
    # Legacy flat list (still accepted for manual testing via UI editors)
    queries: Optional[List[str]] = None
    search_mode: str = "uk-domains"
    guideline_systems: List[str] = Field(default_factory=list)


class ScrapeRequest(BaseModel):
    urls: List[str]
    guideline_system: str = ""


class RunAllRequest(BaseModel):
    findings: str
    scan_type: str = ""
    clinical_history: str = ""
    search_mode: str = "uk-domains"
    search_provider: str = "tavily"  # "perplexity" | "tavily" (Stage 2 discovery)
    score_threshold: float = 0.25    # Tavily only: drop candidates below this before triage
    max_deep_extract: int = 3        # GLM triage: max URLs routed to Tavily deep extract
    report_content: str = ""         # Optional: when provided, Stage 4 synthesis runs automatically


# --- FastAPI app -----------------------------------------------------------------

app = FastAPI(title="Prefetch Pipeline Tester", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def serve_ui() -> HTMLResponse:
    html_path = Path(__file__).parent / "prefetch_pipeline_ui.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<p>UI not found — ensure prefetch_pipeline_ui.html is in the same directory.</p>",
        status_code=404,
    )


@app.get("/api/status")
async def api_status() -> Dict[str, Any]:
    """Quick health check — confirms server is up and which API keys are present."""
    return {
        "ok": True,
        "keys": {
            "CEREBRAS_API_KEY": bool(os.environ.get("CEREBRAS_API_KEY")),
            "PERPLEXITY_API_KEY": bool(os.environ.get("PERPLEXITY_API_KEY")),
            "FIRECRAWL_API_KEY": bool(os.environ.get("FIRECRAWL_API_KEY")),
            "TAVILY_API_KEY": bool(os.environ.get("TAVILY_API_KEY")),
        },
    }


# --- Stage 1: GLM Extraction -----------------------------------------------------

@app.post("/api/stage/glm-extract")
async def stage_glm_extract(req: ExtractRequest) -> Dict[str, Any]:
    """
    Run the GLM (zai-glm-4.7) extraction call with reasoning ON.
    Reasoning is needed to correctly group CT features by implied diagnosis and
    consolidate multi-feature disease processes into single pathway entries.
    Returns a PrefetchContext with consolidated findings, applicable guidelines,
    urgency signals, and Tavily query plan.
    """
    t0 = time.perf_counter()

    cerebras_key = os.environ.get("CEREBRAS_API_KEY")
    if not cerebras_key:
        raise HTTPException(status_code=500, detail="CEREBRAS_API_KEY not set in .env")

    try:
        from rapid_reports_ai.enhancement_utils import _run_agent_with_model
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    user_prompt = (
        f"SCAN TYPE: {req.scan_type}\n"
        f"CLINICAL HISTORY: {req.clinical_history}\n"
        f"FINDINGS: {req.findings}"
    )

    # Cerebras GLM-4.7: reasoning ON requires temperature >= 0.8 (documented floor).
    # Below 0.8, the model cannot reconcile its reasoning chain with low-temperature
    # decoding and intermittently fails to produce valid tool_calls (400 parser_error).
    # max_completion_tokens must be large enough to fit reasoning trace + JSON output;
    # 1500 was too tight — reasoning alone can exceed that before the schema is written.
    model_settings = {
        "temperature": 0.8,
        "top_p": 0.95,
        "max_completion_tokens": 5000,
        "extra_body": {"disable_reasoning": False},
    }

    try:
        result = await _run_agent_with_model(
            model_name="zai-glm-4.7",
            output_type=PrefetchContext,
            system_prompt=PREFETCH_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=cerebras_key,
            model_settings=model_settings,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        ctx = result.output
        data = ctx.model_dump()
        total_q = ctx.query_plan.total_queries()

        # ── Stage 1 detailed log ──────────────────────────────────────────────
        print(f"\n[S1] ✅ GLM EXTRACT — {elapsed_ms}ms")
        n_findings = len(ctx.consolidated_findings)
        n_short = len(ctx.finding_short_labels)
        if n_short != n_findings:
            print(f"[S1] ⚠ SHORT LABEL MISMATCH: {n_findings} findings but {n_short} short_labels — "
                  f"missing labels will fall back to empty string")
        print(f"[S1]   Findings ({n_findings}):")
        for i, f in enumerate(ctx.consolidated_findings):
            short = ctx.finding_short_labels[i] if i < n_short else ""
            tag = f" [{short}]" if short else " [⚠ no short_label]"
            print(f"[S1]     · {f}{tag}")

        print(f"[S1]   Urgency signals ({len(ctx.urgency_signals)}):")
        for u in ctx.urgency_signals:
            print(f"[S1]     ⚠ {u}")

        print(f"[S1]   Applicable guidelines ({len(ctx.applicable_guidelines)}):")
        for i, g in enumerate(ctx.applicable_guidelines, 1):
            print(f"[S1]     {i}. [{g.type}] {g.system}")
            if g.search_keywords:
                print(f"[S1]        keywords: {g.search_keywords}")
            if g.context:
                print(f"[S1]        context:  {g.context}")

        print(f"[S1]   Query plan ({total_q} total):")
        branch_display = {
            "pathway_followup":          ("Branch A", "pathway / follow-up"),
            "classification_measurement": ("Branch B", "classification / measurement"),
            "imaging_differential":       ("Branch C", "imaging features / DDx"),
        }
        for key, (label, desc) in branch_display.items():
            qs = getattr(ctx.query_plan, key)
            print(f"[S1]     {label} — {desc} ({len(qs)} queries):")
            for q in qs:
                print(f"[S1]       → {q}")
        # ─────────────────────────────────────────────────────────────────────

        return {"ok": True, "elapsed_ms": elapsed_ms, "result": data}
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        print(f"[S1] ❌ GLM EXTRACT FAILED elapsed_ms={elapsed_ms}: {exc}")
        return {"ok": False, "elapsed_ms": elapsed_ms, "error": str(exc)}


# --- Stage 2: Shared helpers -----------------------------------------------------

def _extract_domain_simple(url: str) -> str:
    """Extract bare hostname from a URL (no www prefix)."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lstrip("www.")
    except Exception:
        return ""


def _normalize_tavily_results(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalise a Tavily Search response to the same shape as normalize_perplexity_results."""
    normalized: List[Dict[str, Any]] = []
    for r in response.get("results", []):
        url = r.get("url", "")
        if not url:
            continue
        content = r.get("content", "")
        normalized.append({
            "url": url,
            "title": r.get("title", ""),
            "domain": _extract_domain_simple(url),
            "date": r.get("published_date", ""),
            "snippet": content[:300] if content else "",
            "content": content,
            "score": r.get("score", 0.0),
        })
    return normalized


async def _run_tavily_search_branch(
    branch_key: str,
    queries: List[str],
    domain_filter: List[str],
    search_depth: str = "advanced",
) -> Dict[str, Any]:
    """
    Run one Tavily Search branch — all queries dispatched in parallel.

    Key differences vs _run_perplexity_branch:
    - include_domains is a HARD filter (results come only from listed domains)
    - One API call per query (no batching) → asyncio.gather within branch
    - score field per result (0-1 relevance signal)
    - content field contains semantic chunks at advanced depth (~3×500 chars)
    - No fallback needed: hard filter means fewer but higher-quality results
    """
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return {
            "branch": branch_key, "queries_sent": queries, "domain_filter": domain_filter,
            "raw_results": [], "total": 0, "elapsed_ms": 0,
            "fallback_used": False, "error": "TAVILY_API_KEY not set",
        }
    try:
        from tavily import AsyncTavilyClient
    except ImportError as exc:
        return {
            "branch": branch_key, "queries_sent": queries, "domain_filter": domain_filter,
            "raw_results": [], "total": 0, "elapsed_ms": 0,
            "fallback_used": False, "error": f"tavily import failed: {exc}",
        }

    branch_labels = {
        "pathway_followup": "Branch A",
        "classification_measurement": "Branch B",
        "imaging_differential": "Branch C",
    }
    label = branch_labels.get(branch_key, branch_key)

    queries = queries[:5]  # Hard cap
    t0 = time.perf_counter()

    async def _one_query(query: str) -> List[Dict[str, Any]]:
        kwargs: Dict[str, Any] = {
            "query": query,
            "search_depth": search_depth,
            "max_results": 5,
        }
        if domain_filter:
            kwargs["include_domains"] = domain_filter
        if search_depth == "advanced":
            kwargs["chunks_per_source"] = 3
        client = AsyncTavilyClient(api_key)
        try:
            resp = await asyncio.wait_for(client.search(**kwargs), timeout=30.0)
            results = _normalize_tavily_results(resp)
            print(f"[S2T]   {label} query={query!r:.60} → {len(results)} results", flush=True)
            return results
        except asyncio.TimeoutError:
            print(f"[S2T]   {label} TIMEOUT: {query!r:.60}", flush=True)
            return []
        except Exception as exc:
            print(f"[S2T]   {label} ERROR {type(exc).__name__}: {exc} — query={query!r:.60}", flush=True)
            return []

    # All queries in this branch in parallel
    all_nested: List[List[Dict[str, Any]]] = list(
        await asyncio.gather(*[_one_query(q) for q in queries])
    )

    # Deduplicate across queries within this branch
    seen: set = set()
    raw_results: List[Dict[str, Any]] = []
    for results in all_nested:
        for item in results:
            url = item.get("url", "")
            if url and url not in seen:
                seen.add(url)
                raw_results.append(item)

    # Sort by score descending within branch
    raw_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    print(f"[S2T]   {label} ({branch_key}) — {elapsed_ms}ms — {len(raw_results)} unique URLs:", flush=True)
    for item in raw_results:
        score = item.get("score", 0.0)
        title = (item.get("title") or "")[:80]
        url = item.get("url", "?")
        domain = item.get("domain", "?")
        print(f"[S2T]     · [{score:.2f}] {domain:<35} {title}", flush=True)
        print(f"[S2T]       {url}", flush=True)

    return {
        "branch": branch_key,
        "queries_sent": queries,
        "domain_filter": domain_filter,
        "raw_results": raw_results,
        "total": len(raw_results),
        "elapsed_ms": elapsed_ms,
        "fallback_used": False,
        "error": None,
    }


# --- Stage 2a: Perplexity Discovery (branched parallel) --------------------------

async def _run_perplexity_branch(
    branch_key: str,
    queries: List[str],
    domain_filter: List[str],
    use_date_filter: bool,
    normalize_fn: Any,
) -> Dict[str, Any]:
    """
    Run one Perplexity branch (native async, no thread pool).
    Returns per-branch result dict including raw_results and any error.
    """
    from perplexity import AsyncPerplexity

    # Hard cap at 5 per branch — official API limit
    queries = queries[:5]
    t0 = time.perf_counter()

    kwargs: Dict[str, Any] = {
        "query": queries,
        "max_results": 5,
        "max_tokens_per_page": 600,
        "search_language_filter": ["en"],
        "country": "GB",
    }
    if domain_filter:
        kwargs["search_domain_filter"] = domain_filter
    if use_date_filter:
        # search_after_date_filter: correct SDK param name (not last_updated_after_filter)
        # Filters to pages published/indexed after this date — keeps guidelines current
        kwargs["search_after_date_filter"] = "1/1/2018"

    raw_results: List[Dict[str, Any]] = []
    error: Optional[str] = None
    fallback_used = False

    def _log_branch_results(results: List[Dict[str, Any]], label: str) -> None:
        branch_label = {
            "pathway_followup": "Branch A",
            "classification_measurement": "Branch B",
            "imaging_differential": "Branch C",
        }.get(branch_key, branch_key)
        print(f"[S2]   {branch_label} ({branch_key}) — {label} — {len(results)} results:")
        for item in results:
            url = item.get("url", "?")
            domain = item.get("domain", "?")
            title = (item.get("title") or "")[:90]
            date = item.get("date") or item.get("last_updated") or ""
            print(f"[S2]     · {domain:<35} {date:<12} {title}")
            print(f"[S2]       {url}")

    try:
        async with AsyncPerplexity() as client:
            resp = await client.search.create(**kwargs)
        raw_results = normalize_fn(resp, queries)
        elapsed_so_far = round((time.perf_counter() - t0) * 1000)
        _log_branch_results(raw_results, f"primary {elapsed_so_far}ms")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        branch_label = {"pathway_followup": "Branch A", "classification_measurement": "Branch B",
                        "imaging_differential": "Branch C"}.get(branch_key, branch_key)
        print(f"[S2]   {branch_label} ({branch_key}) primary FAILED: {error}")

        # Fallback: open web (no domain filter, no date filter)
        try:
            open_kwargs = {k: v for k, v in kwargs.items()
                          if k not in ("search_domain_filter", "search_after_date_filter")}
            async with AsyncPerplexity() as client:
                resp = await client.search.create(**open_kwargs)
            raw_results = normalize_fn(resp, queries)
            fallback_used = True
            _log_branch_results(raw_results, "open-web fallback")
        except Exception as exc2:
            error += f"; fallback also failed: {exc2}"
            print(f"[S2]   {branch_label} ({branch_key}) fallback also FAILED: {exc2}")

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    return {
        "branch": branch_key,
        "queries_sent": queries,
        "domain_filter": domain_filter,
        "raw_results": raw_results,
        "total": len(raw_results),
        "elapsed_ms": elapsed_ms,
        "fallback_used": fallback_used,
        "error": error,
    }


@app.post("/api/stage/perplexity-discover")
async def stage_perplexity_discover(req: DiscoverRequest) -> Dict[str, Any]:
    """
    Run Perplexity discovery using 3 parallel domain-targeted branches.

    If req.query_plan is provided (from Stage 1), each branch uses its own domain filter:
      pathway_followup        → DOMAIN_FILTER_PATHWAY (NICE/RCR/BTS/specialty societies)
      classification_measurement → DOMAIN_FILTER_CLASSIFICATION (RSNA/Radiopaedia/BIR/PubMed)
      imaging_differential    → DOMAIN_FILTER_DIFFERENTIAL (Radiopaedia/PubMed)

    If req.queries is provided (legacy flat list), runs as a single branch against
    DOMAIN_FILTER_PATHWAY (backward-compat for manual editing in the UI).
    """
    t0 = time.perf_counter()

    try:
        from rapid_reports_ai.enhancement_utils import normalize_perplexity_results
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    use_date_filter = (req.search_mode == "uk-domains")
    print(f"\n[S2] ⏳ PERPLEXITY DISCOVER — mode={req.search_mode!r} date_filter={use_date_filter}")

    # Build branch jobs
    if req.query_plan:
        plan = req.query_plan
        branch_jobs = [
            (k, plan.get(k, []), meta["domains"])
            for k, meta in BRANCH_META.items()
            if plan.get(k)
        ]
    elif req.queries:
        # Legacy flat list: treat as a single pathway branch
        branch_jobs = [("pathway_followup", req.queries, DOMAIN_FILTER_PATHWAY)]
    else:
        raise HTTPException(status_code=400, detail="Provide query_plan or queries")

    if not branch_jobs:
        raise HTTPException(status_code=400, detail="All branches are empty")

    # Log what we're about to send
    branch_labels = {"pathway_followup": "Branch A", "classification_measurement": "Branch B",
                     "imaging_differential": "Branch C"}
    for key, queries, domains in branch_jobs:
        label = branch_labels.get(key, key)
        print(f"[S2]   {label} ({key}) — {len(queries)} queries, {len(domains)} domain filters:")
        for q in queries:
            print(f"[S2]     → {q}")
        print(f"[S2]     domains: {' · '.join(domains[:5])}{' …' if len(domains) > 5 else ''}")

    # Run all non-empty branches in parallel
    branch_results: List[Dict[str, Any]] = list(
        await asyncio.gather(*[
            _run_perplexity_branch(key, queries, domains, use_date_filter, normalize_perplexity_results)
            for key, queries, domains in branch_jobs
        ])
    )

    # Flatten all results for Stage 3 URL selection
    all_raw: List[Dict[str, Any]] = []
    seen_urls: set = set()
    for br in branch_results:
        for item in br.get("raw_results", []):
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                item["_branch"] = br["branch"]
                all_raw.append(item)

    total_queries = sum(len(br["queries_sent"]) for br in branch_results)
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    print(f"[S2] ✅ PERPLEXITY DISCOVER — {len(all_raw)} unique URLs from {total_queries} queries "
          f"across {len(branch_results)} branches — {elapsed_ms}ms total")

    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "mode": req.search_mode,
        "branches": branch_results,
        "total_queries_sent": total_queries,
        "total_results": len(all_raw),
        "raw_results": all_raw,
    }


# --- Stage 2b: Tavily Search Discovery -------------------------------------------

@app.post("/api/stage/tavily-search")
async def stage_tavily_search(req: DiscoverRequest) -> Dict[str, Any]:
    """
    Tavily Search as a drop-in alternative to Perplexity for Stage 2.

    vs Perplexity:
    - include_domains is a HARD filter (strict, not soft like Perplexity's search_domain_filter)
    - score field per result (0-1 relevance signal, enables post-hoc quality filtering)
    - content field contains inline semantic chunks (advanced depth: ~3×500 chars per result)
    - One API call per query → parallel within each branch; no per-branch batching
    - No country/date API params → geographic targeting via include_domains + query wording

    Cost: search_depth='advanced' = 2 credits per search call.
    With 3-4 queries per branch × 3 branches = 18-24 credits per run.
    Use search_depth='basic' (1 credit/call) to halve cost if content quality is sufficient.
    """
    t0 = time.perf_counter()

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="TAVILY_API_KEY not set in .env")

    search_depth = "advanced"

    # Build branch jobs — same logic as perplexity-discover
    if req.query_plan:
        plan = req.query_plan
        branch_jobs = [
            (k, plan.get(k, []), meta["domains"])
            for k, meta in BRANCH_META.items()
            if plan.get(k)
        ]
    elif req.queries:
        branch_jobs = [("pathway_followup", req.queries, DOMAIN_FILTER_PATHWAY)]
    else:
        raise HTTPException(status_code=400, detail="Provide query_plan or queries")

    if not branch_jobs:
        raise HTTPException(status_code=400, detail="All branches are empty")

    total_queries = sum(len(qs) for _, qs, _ in branch_jobs)
    print(f"\n[S2T] ⏳ TAVILY SEARCH — {len(branch_jobs)} branches, {total_queries} total queries, depth={search_depth!r}")
    branch_labels = {"pathway_followup": "Branch A", "classification_measurement": "Branch B", "imaging_differential": "Branch C"}
    for key, queries, domains in branch_jobs:
        lbl = branch_labels.get(key, key)
        print(f"[S2T]   {lbl} ({key}) — {len(queries)} queries, {len(domains)} domains (HARD filter):")
        for q in queries:
            print(f"[S2T]     → {q}")
        print(f"[S2T]     domains: {' · '.join(domains[:5])}{' …' if len(domains) > 5 else ''}")

    # All branches in parallel
    branch_results: List[Dict[str, Any]] = list(
        await asyncio.gather(*[
            _run_tavily_search_branch(key, queries, domains, search_depth)
            for key, queries, domains in branch_jobs
        ])
    )

    # Flatten and deduplicate across all branches
    all_raw: List[Dict[str, Any]] = []
    seen_urls: set = set()
    for br in branch_results:
        for item in br.get("raw_results", []):
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                item["_branch"] = br["branch"]
                all_raw.append(item)

    # Sort globally by score
    all_raw.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    print(f"[S2T] ✅ TAVILY SEARCH — {len(all_raw)} unique URLs from {total_queries} queries — {elapsed_ms}ms total")
    print(f"[S2T]   Top URLs by score:")
    for item in all_raw[:8]:
        branch = item.get("_branch", "?")
        score = item.get("score", 0.0)
        domain = item.get("domain", "?")
        url = item.get("url", "?")
        print(f"[S2T]     [{score:.2f}] [{branch}] {domain:<35} {url}")

    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "provider": "tavily",
        "search_depth": search_depth,
        "mode": req.search_mode,
        "branches": branch_results,
        "total_queries_sent": total_queries,
        "total_results": len(all_raw),
        "raw_results": all_raw,
    }


# --- Stage 3: Firecrawl Scrape ---------------------------------------------------

@app.post("/api/stage/firecrawl-scrape")
async def stage_firecrawl_scrape(req: ScrapeRequest) -> Dict[str, Any]:
    """
    Targeted Firecrawl scrape on up to 5 URLs.
    Uses the same EXTRACTION_SCHEMA + extraction prompt as the production pipeline.
    Returns is_authoritative, source_type, criteria_summary per URL.
    """
    t0 = time.perf_counter()

    if not req.urls:
        raise HTTPException(status_code=400, detail="urls list is empty")

    try:
        from rapid_reports_ai.firecrawl_client import get_async_firecrawl
        from rapid_reports_ai.guideline_fetcher import (
            EXTRACTION_SCHEMA,
            _extraction_prompt_for_system,
        )
        from firecrawl.v2.types import ScrapeOptions
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    client = get_async_firecrawl()
    system = req.guideline_system or "clinical guideline"

    scrape_opts = ScrapeOptions(
        formats=[
            {
                "type": "json",
                "schema": EXTRACTION_SCHEMA,
                "prompt": _extraction_prompt_for_system(system),
            }
        ],
        only_main_content=True,
        parsers=[],              # HTML only — disables PDF parsing for web pages (matches production _scrape_options)
        max_age=7 * 24 * 60 * 60 * 1000,
    )

    urls_to_scrape = req.urls[:5]  # cap at 5 per call to limit credit burn during testing

    print(f"\n[S3] ⏳ FIRECRAWL SCRAPE — {len(urls_to_scrape)} URLs parallel")
    print(f"[S3]   System hint: {system!r}")
    print(f"[S3]   Extraction schema keys: {list(EXTRACTION_SCHEMA.get('properties', {}).keys())}")
    for i, u in enumerate(urls_to_scrape, 1):
        print(f"[S3]   URL {i}: {u}")

    async def _scrape_one(url: str) -> Dict[str, Any]:
        url_t0 = time.perf_counter()
        try:
            doc = await asyncio.wait_for(
                client.scrape(url, scrape_options=scrape_opts),
                timeout=30.0,
            )
            url_elapsed = round((time.perf_counter() - url_t0) * 1000)

            # ── Extraction diagnostics ────────────────────────────────────────
            meta = getattr(doc, "metadata", None)
            http_status = getattr(meta, "status_code", "?")
            page_title = (getattr(meta, "title", None) or "")[:80]
            raw_json = getattr(doc, "json", None)
            extracted: Dict[str, Any] = raw_json or {}
            criteria = (extracted.get("criteria_summary") or "").strip()
            criteria_preview = criteria[:180].replace("\n", " ") if criteria else ""

            print(f"[S3]   ── {url}")
            print(f"[S3]      HTTP {http_status} | {url_elapsed}ms | title: {page_title!r}")
            print(f"[S3]      doc.json: {'present' if raw_json is not None else 'None (extraction returned nothing)'}")
            if extracted:
                print(f"[S3]      extracted keys: {list(extracted.keys())}")
                print(f"[S3]      is_authoritative: {extracted.get('is_authoritative')!r}")
                print(f"[S3]      source_type:      {extracted.get('source_type')!r}")
                if criteria_preview:
                    print(f"[S3]      criteria_summary ({len(criteria)} chars): {criteria_preview!r}{'…' if len(criteria) > 180 else ''}")
                else:
                    print(f"[S3]      criteria_summary: (empty)")
            else:
                print(f"[S3]      extracted: empty dict — no fields populated")
            # ─────────────────────────────────────────────────────────────────

            return {
                "url": url,
                "ok": True,
                "elapsed_ms": url_elapsed,
                "is_authoritative": extracted.get("is_authoritative"),
                "source_type": extracted.get("source_type"),
                "criteria_summary": criteria,
                "criteria_chars": len(criteria),
                "metadata": {
                    "title": page_title,
                    "status_code": http_status,
                },
            }
        except asyncio.TimeoutError:
            url_elapsed = round((time.perf_counter() - url_t0) * 1000)
            print(f"[S3]   ── {url}")
            print(f"[S3]      ❌ TIMEOUT after {url_elapsed}ms")
            return {"url": url, "ok": False, "elapsed_ms": url_elapsed, "error": "timeout (30s)"}
        except Exception as exc:
            url_elapsed = round((time.perf_counter() - url_t0) * 1000)
            print(f"[S3]   ── {url}")
            print(f"[S3]      ❌ ERROR {url_elapsed}ms: {type(exc).__name__}: {exc}")
            return {"url": url, "ok": False, "elapsed_ms": url_elapsed, "error": f"{type(exc).__name__}: {exc}"}

    # Run all scrapes in parallel — mirrors production asyncio.gather pattern
    scrape_results: List[Dict[str, Any]] = list(
        await asyncio.gather(*[_scrape_one(u) for u in urls_to_scrape])
    )

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    authoritative_count = sum(1 for r in scrape_results if r.get("is_authoritative"))
    auth_urls = [r["url"] for r in scrape_results if r.get("is_authoritative")]
    print(f"[S3] {'✅' if authoritative_count else '⚠'} FIRECRAWL SCRAPE — "
          f"{authoritative_count}/{len(scrape_results)} authoritative — {elapsed_ms}ms total")
    if auth_urls:
        for u in auth_urls:
            print(f"[S3]   ✓ {u}")
    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "scrape_results": scrape_results,
        "authoritative_count": authoritative_count,
        "total_scraped": len(scrape_results),
    }


# --- Stage 3b: Tavily Extract (replaces Firecrawl scrape) ------------------------

@app.post("/api/stage/tavily-extract")
async def stage_tavily_extract(req: ScrapeRequest) -> Dict[str, Any]:
    """
    Batch Tavily Extract (advanced depth) as a drop-in replacement for Firecrawl scrape.
    - extract_depth='advanced' handles JS-rendered SPAs (e.g. NICE guideline pages)
    - All URLs dispatched in one API call (batch), not per-URL like Firecrawl
    - query + chunks_per_source=3 returns semantically relevant 500-char chunks
    - Cost: 2 credits per 5 successful extractions (vs ~4 credits per URL with Firecrawl)
    - failed_results are not charged
    """
    import sys
    print(f"[S3T] ENTER — {len(req.urls)} URLs, system={req.guideline_system!r}", flush=True)
    t0 = time.perf_counter()

    if not req.urls:
        print("[S3T] ❌ No URLs passed", flush=True)
        raise HTTPException(status_code=400, detail="urls list is empty")

    api_key = os.environ.get("TAVILY_API_KEY", "")
    print(f"[S3T] API key present: {bool(api_key)} (len={len(api_key)})", flush=True)
    if not api_key:
        raise HTTPException(status_code=500, detail="TAVILY_API_KEY not set in .env")

    try:
        from tavily import AsyncTavilyClient
        print("[S3T] AsyncTavilyClient imported OK", flush=True)
    except Exception as exc:
        print(f"[S3T] ❌ Import error: {exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"tavily import failed: {exc}")

    client = AsyncTavilyClient(api_key)
    print("[S3T] Client created OK", flush=True)
    system = req.guideline_system or "clinical guideline"

    # Reranking query — drives chunk relevance selection within each page
    extract_query = f"{system} management criteria classification imaging findings"

    urls_to_extract = req.urls[:10]  # Tavily max is 20; cap at 10 for testing

    print(f"\n[S3T] ⏳ TAVILY EXTRACT — {len(urls_to_extract)} URLs (advanced depth)", flush=True)
    print(f"[S3T]   System hint:    {system!r}", flush=True)
    print(f"[S3T]   Rerank query:   {extract_query!r}", flush=True)
    print(f"[S3T]   chunks/source:  3  (max 500 chars each)", flush=True)
    for i, u in enumerate(urls_to_extract, 1):
        print(f"[S3T]   URL {i}: {u}", flush=True)

    try:
        print("[S3T]   Calling client.extract()…", flush=True)
        response = await asyncio.wait_for(
            client.extract(
                urls=urls_to_extract,
                query=extract_query,
                chunks_per_source=3,
                extract_depth="advanced",
                include_usage=True,
            ),
            timeout=60.0,
        )
        print(f"[S3T]   extract() returned, type={type(response).__name__}", flush=True)
    except asyncio.TimeoutError:
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        print(f"[S3T] ❌ TIMEOUT after {elapsed_ms}ms", flush=True)
        raise HTTPException(status_code=504, detail="Tavily extract timed out (60s)")
    except BaseException as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        print(f"[S3T] ❌ {type(exc).__name__} after {elapsed_ms}ms: {exc}", flush=True)
        sys.stdout.flush()
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")

    elapsed_ms = round((time.perf_counter() - t0) * 1000)

    successes: List[Dict[str, Any]] = response.get("results", [])
    failures: List[Dict[str, Any]] = response.get("failed_results", [])
    usage = response.get("usage", {})
    credits_used = usage.get("credits", "?")
    resp_time_s = response.get("response_time", "?")

    print(f"[S3T]   Tavily response_time: {resp_time_s}s | credits: {credits_used}", flush=True)
    print(f"[S3T]   Successful: {len(successes)}, Failed: {len(failures)}", flush=True)

    extract_results: List[Dict[str, Any]] = []

    for item in successes:
        url = item.get("url", "?")
        raw = (item.get("raw_content") or "").strip()
        content_chars = len(raw)
        preview = raw[:400].replace("\n", " ") if raw else ""

        print(f"[S3T]   ── {url}", flush=True)
        print(f"[S3T]      content: {content_chars} chars extracted", flush=True)
        if preview:
            print(f"[S3T]      preview: {preview!r}{'…' if content_chars > 400 else ''}", flush=True)
        else:
            print(f"[S3T]      ⚠ empty content returned", flush=True)

        extract_results.append({
            "url": url,
            "ok": True,
            "raw_content": raw,
            "content_chars": content_chars,
            "content_preview": preview,
        })

    for item in failures:
        url = item.get("url", "?")
        error = item.get("error", "unknown error")
        print(f"[S3T]   ── {url}", flush=True)
        print(f"[S3T]      ❌ FAILED: {error}", flush=True)
        extract_results.append({
            "url": url,
            "ok": False,
            "error": error,
            "content_chars": 0,
        })

    success_count = len(successes)
    print(f"[S3T] {'✅' if success_count else '⚠'} TAVILY EXTRACT — "
          f"{success_count}/{len(urls_to_extract)} successful — "
          f"{elapsed_ms}ms total (credits: {credits_used})", flush=True)

    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "extract_results": extract_results,
        "success_count": success_count,
        "failed_count": len(failures),
        "total_urls": len(urls_to_extract),
        "credits_used": credits_used,
        "tavily_response_time_s": resp_time_s,
    }


# --- Stage 2.5: GLM Triage -------------------------------------------------------

@app.post("/api/stage/glm-triage")
async def stage_glm_triage(req: TriageRequest) -> Dict[str, Any]:
    """
    Fast GLM call (reasoning OFF) that reviews all S2 candidates and routes each to:
      deep_extract — full Tavily Extract (JS rendering, best for NICE/SIGN/RCR SPAs)
      use_inline   — use content already returned by Tavily Search (good for PMC/PubMed)
      skip         — discard (irrelevant, boilerplate, duplicate)

    Also generates a per-URL extract_hint for deep_extract items so Stage 3 Tavily Extract
    uses a targeted reranking query per page rather than one generic query for all.
    """
    t0 = time.perf_counter()

    cerebras_key = os.environ.get("CEREBRAS_API_KEY")
    if not cerebras_key:
        raise HTTPException(status_code=500, detail="CEREBRAS_API_KEY not set in .env")

    try:
        from rapid_reports_ai.enhancement_utils import _run_agent_with_model
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    # Build clinical context summary from S1
    ctx = req.prefetch_context
    findings = ctx.get("consolidated_findings", [])
    guidelines = ctx.get("applicable_guidelines", [])
    urgency = ctx.get("urgency_signals", [])
    ctx_summary = (
        f"FINDINGS: {', '.join(findings)}\n"
        f"URGENCY: {', '.join(urgency) or 'none'}\n"
        f"KEY GUIDELINES: {', '.join(g['system'] for g in guidelines)}"
    )

    # Format candidate list for the model
    candidate_lines: List[str] = []
    for i, c in enumerate(req.candidates, 1):
        preview = (c.inline_content[:400].replace("\n", " ")) if c.inline_content else "(no inline content)"
        blocked = _is_deep_extract_blocked(c.url, c.domain)
        routing_line = "    routing: [INLINE-ONLY] deep_extract not available — use_inline or skip only\n" if blocked else ""
        candidate_lines.append(
            f"[{i}] branch={c.branch} score={c.score:.2f} domain={c.domain}\n"
            f"    url: {c.url}\n"
            f"    title: {c.title or '(no title)'}\n"
            f"{routing_line}"
            f"    inline ({c.inline_content_chars} chars): {preview}"
        )

    print(f"\n[S2.5] ⏳ GLM TRIAGE — {len(req.candidates)} candidates "
          f"(max_deep_extract={req.max_deep_extract})")
    for c in req.candidates:
        if _is_deep_extract_blocked(c.url, c.domain):
            action_hint = "→ BLOCKED (inline-only)"
        elif c.domain.replace("www.", "") in DEEP_EXTRACT_DOMAINS:
            action_hint = "→ SPA (deep_extract eligible)"
        elif c.inline_content:
            action_hint = f"→ has inline ({c.inline_content_chars}c)"
        else:
            action_hint = "→ no inline content"
        print(f"[S2.5]   [{c.score:.2f}] [{c.branch[:4]}] {c.domain:<35} {action_hint}")

    user_prompt = (
        f"CLINICAL CONTEXT:\n{ctx_summary}\n\n"
        f"max_deep_extract: {req.max_deep_extract}\n\n"
        f"CANDIDATES ({len(req.candidates)}):\n"
        + "\n\n".join(candidate_lines)
        + "\n\nRoute each candidate. Remember: max_deep_extract hard limit."
    )

    # 50 candidates × ~60 tokens/decision ≈ 3,000 tokens of JSON output — 1,200 was too
    # tight and silently truncated the response, dropping candidates from the decision list.
    model_settings = {
        "temperature": 0.1,
        "max_completion_tokens": 3000,
        "extra_body": {"disable_reasoning": True},
    }

    try:
        result = await _run_agent_with_model(
            model_name="zai-glm-4.7",
            output_type=TriageResult,
            system_prompt=TRIAGE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=cerebras_key,
            model_settings=model_settings,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        triage = result.output

        deep = [d for d in triage.decisions if d.action == "deep_extract"]
        inline = [d for d in triage.decisions if d.action == "use_inline"]
        skip = [d for d in triage.decisions if d.action == "skip"]

        print(f"[S2.5] ✅ GLM TRIAGE — {elapsed_ms}ms")
        print(f"[S2.5]   deep_extract ({len(deep)}):")
        for d in deep:
            print(f"[S2.5]     → {d.url}")
            print(f"[S2.5]       hint: {d.extract_hint!r}  reason: {d.reason}")
        print(f"[S2.5]   use_inline ({len(inline)}):")
        for d in inline:
            print(f"[S2.5]     → {d.url}  ({d.reason})")
        print(f"[S2.5]   skip ({len(skip)}): {[d.url for d in skip]}")

        return {
            "ok": True,
            "elapsed_ms": elapsed_ms,
            "decisions": [d.model_dump() for d in triage.decisions],
            "counts": {"deep_extract": len(deep), "use_inline": len(inline), "skip": len(skip)},
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        print(f"[S2.5] ❌ TRIAGE FAILED {elapsed_ms}ms: {exc}")
        return {"ok": False, "elapsed_ms": elapsed_ms, "error": str(exc), "decisions": []}


async def _run_recovery_triage(
    cerebras_key: str,
    ctx: Dict[str, Any],
    starved_branches: List[str],
    candidates: List[TriageURLItem],
    max_deep_extract: int,
) -> List[Any]:
    """
    Second-pass triage for branches with zero evidence after primary triage.

    Operates over a small, pre-filtered pool of skipped candidates (top-N per branch by
    Tavily score). Uses TRIAGE_RECOVERY_SYSTEM_PROMPT — relaxed criteria, mandatory coverage
    for each starved branch. Returns a list of TriageDecision objects (may be empty on error).
    """
    from rapid_reports_ai.enhancement_utils import _run_agent_with_model

    findings = ctx.get("consolidated_findings", [])
    urgency = ctx.get("urgency_signals", [])
    guidelines = ctx.get("applicable_guidelines", [])
    ctx_summary = (
        f"FINDINGS: {', '.join(findings)}\n"
        f"URGENCY: {', '.join(urgency) or 'none'}\n"
        f"KEY GUIDELINES: {', '.join(g['system'] for g in guidelines)}"
    )

    candidate_lines: List[str] = []
    for i, c in enumerate(candidates, 1):
        preview = (c.inline_content[:400].replace("\n", " ")) if c.inline_content else "(no inline content)"
        blocked = _is_deep_extract_blocked(c.url, c.domain)
        routing_line = "    routing: [INLINE-ONLY] deep_extract not available\n" if blocked else ""
        candidate_lines.append(
            f"[{i}] branch={c.branch} score={c.score:.2f} domain={c.domain}\n"
            f"    url: {c.url}\n"
            f"    title: {c.title or '(no title)'}\n"
            f"{routing_line}"
            f"    inline ({c.inline_content_chars} chars): {preview}"
        )

    user_prompt = (
        f"CLINICAL CONTEXT:\n{ctx_summary}\n\n"
        f"BRANCHES NEEDING COVERAGE: {', '.join(starved_branches)}\n"
        f"max_deep_extract: {max_deep_extract}\n\n"
        f"RECOVERY CANDIDATES ({len(candidates)}) — previously skipped, re-evaluate with relaxed criteria:\n"
        + "\n\n".join(candidate_lines)
        + f"\n\nFor each branch in [{', '.join(starved_branches)}] you MUST route at least one "
          f"candidate to deep_extract or use_inline if any remotely relevant candidate exists. "
          f"Marginal relevance is acceptable — an empty branch is worse than an imperfect source."
    )

    model_settings = {
        "temperature": 0.1,
        "max_completion_tokens": 1200,
        "extra_body": {"disable_reasoning": True},
    }

    try:
        result = await _run_agent_with_model(
            model_name="zai-glm-4.7",
            output_type=TriageResult,
            system_prompt=TRIAGE_RECOVERY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=cerebras_key,
            model_settings=model_settings,
        )
        return result.output.decisions
    except Exception as exc:
        print(f"[S2.5] ❌ RECOVERY TRIAGE FAILED: {type(exc).__name__}: {exc}")
        return []


# --- Stage 3: Structured Extract (per-branch knowledge base) ---------------------

@app.post("/api/stage/structured-extract")
async def stage_structured_extract(req: StructuredExtractRequest) -> Dict[str, Any]:
    """
    Builds a structured per-branch knowledge base from triage decisions:

      deep_extract  → Tavily Extract (advanced depth, JS rendering)
                      Grouped by branch — one API call per branch group, each using
                      the branch's combined extract_hints as the reranking query.
      use_inline    → Passes through the S2 Tavily Search content directly (free, instant)
      skip          → Discarded

    Returns knowledge_base keyed by branch with content + source metadata per item.
    """
    t0 = time.perf_counter()

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="TAVILY_API_KEY not set in .env")

    try:
        from tavily import AsyncTavilyClient
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"tavily import failed: {exc}")

    # Build URL → candidate lookup for inline content passthrough
    candidate_map: Dict[str, TriageURLItem] = {c.url: c for c in req.candidates}

    knowledge_base: Dict[str, List[Dict[str, Any]]] = {
        "pathway_followup": [],
        "classification_measurement": [],
        "imaging_differential": [],
    }

    decisions = [TriageDecision(**d) if isinstance(d, dict) else d for d in req.decisions]

    deep_decisions = [d for d in decisions if d.action == "deep_extract"]
    inline_decisions = [d for d in decisions if d.action == "use_inline"]
    skip_decisions = [d for d in decisions if d.action == "skip"]

    print(f"\n[S3] ⏳ STRUCTURED EXTRACT — "
          f"{len(deep_decisions)} deep, {len(inline_decisions)} inline, {len(skip_decisions)} skip")

    total_credits = 0

    # ── Deep extract: all URLs via Tavily; ScraperAPI plain-HTML for any failures ──
    from collections import defaultdict

    tavily_failed_urls: set = set()

    deep_by_branch: Dict[str, List[TriageDecision]] = defaultdict(list)
    for d in deep_decisions:
        deep_by_branch[d.branch].append(d)

    for branch, branch_decisions in deep_by_branch.items():
        urls = [d.url for d in branch_decisions]
        hints = [d.extract_hint for d in branch_decisions if d.extract_hint]
        combined_hint = " ".join(hints) if hints else f"{req.guideline_system} management criteria"
        combined_hint = combined_hint[:200]  # safety cap

        print(f"[S3]   deep_extract branch={branch} ({len(urls)} URLs)")
        print(f"[S3]   extract_hint: {combined_hint!r}")
        for u in urls:
            print(f"[S3]     → {u}")

        try:
            client = AsyncTavilyClient(api_key)
            response = await asyncio.wait_for(
                client.extract(
                    urls=urls,
                    query=combined_hint,
                    chunks_per_source=4,
                    extract_depth="advanced",
                    include_usage=True,
                ),
                timeout=60.0,
            )
            branch_credits = (response.get("usage") or {}).get("credits", 0)
            total_credits += branch_credits
            resp_time = response.get("response_time", "?")
            print(f"[S3]   → {branch} extract done: {resp_time}s, {branch_credits} credits")

            for item in response.get("results", []):
                url = item.get("url", "")
                content = (item.get("raw_content") or "").strip()
                decision = next((d for d in branch_decisions if d.url == url), None)

                # Detect content-level geo-blocks: HTTP 200 but access-restriction page
                content_probe = content[:600].lower()
                if any(sig in content_probe for sig in _GEO_BLOCK_SIGNATURES):
                    print(f"[S3]   ⚠ GEO-BLOCKED (content): {url} — routing to ScraperAPI UK fallback")
                    tavily_failed_urls.add(url)
                    continue

                print(f"[S3]   ✓ {url}")
                print(f"[S3]     {len(content)} chars — preview: {content[:200].replace(chr(10),' ')!r}")
                knowledge_base[branch].append({
                    "url": url,
                    "content": content,
                    "content_chars": len(content),
                    "extraction_type": "deep_extract",
                    "extract_hint": decision.extract_hint if decision else None,
                    "finding_indices": decision.finding_indices if decision else [],
                    "title": candidate_map.get(url, TriageURLItem(url=url)).title,
                    "domain": candidate_map.get(url, TriageURLItem(url=url)).domain,
                })
            for item in response.get("failed_results", []):
                url = item.get("url", "")
                tavily_failed_urls.add(url)
                print(f"[S3]   ✗ deep_extract failed: {url} — {item.get('error', '?')}")

        except asyncio.TimeoutError:
            print(f"[S3]   ❌ TIMEOUT on branch={branch} deep extract")
            for d in branch_decisions:
                tavily_failed_urls.add(d.url)
        except Exception as exc:
            print(f"[S3]   ❌ ERROR branch={branch}: {type(exc).__name__}: {exc}")
            for d in branch_decisions:
                tavily_failed_urls.add(d.url)

    # ── ScraperAPI plain-HTML fallback ───────────────────────────────────────
    # Handles two distinct failure modes:
    #  1. HTTP-level failures — Tavily explicit failed_results (paywall, timeout, 4xx/5xx)
    #  2. Content-level geo-blocks — Tavily HTTP 200 but page contains access-restriction
    #     text (e.g. "CKS via NICE is only available to eligible users within the UK").
    #     These are detected via _GEO_BLOCK_SIGNATURES above and routed here.
    # ScraperAPI UK proxy (plain HTML, no JS render) resolves both in ~2–5s.
    fallback_decisions = [d for d in deep_decisions if d.url in tavily_failed_urls]
    if fallback_decisions:
        _scraper_api_key = os.environ.get("SCRAPER_API_KEY", "")
        if not _scraper_api_key:
            print(f"[S3]   ⚠ ScraperAPI fallback: SCRAPER_API_KEY not set — {len(fallback_decisions)} URL(s) skipped", flush=True)
        else:
            import httpx
            from html.parser import HTMLParser as _HTMLParser

            class _HTMLTextExtractor(_HTMLParser):
                _SKIP = {"script", "style", "nav", "header", "footer", "noscript", "aside"}
                _BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "div", "br", "tr", "section", "article"}

                def __init__(self):
                    super().__init__()
                    self._skip_depth = 0
                    self._parts: List[str] = []

                def handle_starttag(self, tag, attrs):
                    if tag.lower() in self._SKIP:
                        self._skip_depth += 1

                def handle_endtag(self, tag):
                    tl = tag.lower()
                    if tl in self._SKIP:
                        self._skip_depth = max(0, self._skip_depth - 1)
                    if tl in self._BLOCK:
                        self._parts.append("\n")

                def handle_data(self, data):
                    if not self._skip_depth:
                        stripped = data.strip()
                        if stripped:
                            self._parts.append(stripped)

                def get_text(self) -> str:
                    raw = " ".join(self._parts)
                    lines = [ln.strip() for ln in raw.split("\n")]
                    return "\n".join(ln for ln in lines if ln)

            _COOKIE_NOISE = (
                "cookies on the", "cookies are files", "we use cookies",
                "cookie policy", "accept cookies", "manage cookies",
                "cookie settings", "cookie preferences",
                "view our cookie statement", "accept all cookies",
                "reject cookies", "essential cookies", "these cookies",
                "opens in a new window",
            )

            def _strip_cookie_noise(text: str) -> str:
                clean = []
                for line in text.splitlines():
                    ll = line.lower()
                    if not any(phrase in ll for phrase in _COOKIE_NOISE):
                        clean.append(line)
                return "\n".join(clean).strip()

            async def _scraperapi_scrape(d: TriageDecision):
                try:
                    async with httpx.AsyncClient(timeout=20.0) as _hx:
                        resp = await _hx.get(
                            "https://api.scraperapi.com",
                            params={"api_key": _scraper_api_key, "url": d.url, "country_code": "uk"},
                        )
                        resp.raise_for_status()
                    extractor = _HTMLTextExtractor()
                    extractor.feed(resp.text)
                    content = _strip_cookie_noise(extractor.get_text()).strip()
                    return d, content, None
                except BaseException as exc:
                    return d, "", exc

            print(f"[S3]   🔄 ScraperAPI fallback: {len(fallback_decisions)} URL(s)", flush=True)
            fallback_results = await asyncio.gather(*[_scraperapi_scrape(d) for d in fallback_decisions])

            for d, content, err in fallback_results:
                if err:
                    print(f"[S3]   ✗ ScraperAPI fallback FAILED: {d.url} — {type(err).__name__}: {err}", flush=True)
                elif content:
                    preview = content[:200].replace("\n", " ")
                    print(f"[S3]   ✓ ScraperAPI fallback {d.url} — {len(content)} chars", flush=True)
                    print(f"[S3]     preview: {preview!r}", flush=True)
                    knowledge_base[d.branch].append({
                        "url": d.url,
                        "content": content,
                        "content_chars": len(content),
                        "extraction_type": "deep_extract_fallback",
                        "extract_hint": d.extract_hint,
                        "finding_indices": d.finding_indices,
                        "title": candidate_map.get(d.url, TriageURLItem(url=d.url)).title,
                        "domain": candidate_map.get(d.url, TriageURLItem(url=d.url)).domain,
                    })

    # ── Inline passthrough: use S2 Tavily Search content directly ─────────────
    for d in inline_decisions:
        candidate = candidate_map.get(d.url)
        content = candidate.inline_content if candidate else ""
        print(f"[S3]   inline {d.branch}: {d.url} ({len(content)} chars)")
        if content:
            knowledge_base[d.branch].append({
                "url": d.url,
                "content": content,
                "content_chars": len(content),
                "extraction_type": "inline",
                "extract_hint": None,
                "finding_indices": d.finding_indices,
                "title": candidate.title if candidate else "",
                "domain": candidate.domain if candidate else "",
            })

    elapsed_ms = round((time.perf_counter() - t0) * 1000)

    total_items = sum(len(v) for v in knowledge_base.values())
    total_content = sum(item["content_chars"] for v in knowledge_base.values() for item in v)
    print(f"[S3] ✅ STRUCTURED EXTRACT — {total_items} items, {total_content:,} total chars, "
          f"{total_credits} credits — {elapsed_ms}ms")
    for branch, items in knowledge_base.items():
        if items:
            types = ", ".join(f"{i['extraction_type']}({i['content_chars']}c)" for i in items)
            print(f"[S3]   {branch}: {types}")

    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "knowledge_base": knowledge_base,
        "stats": {
            "deep_extracted": len(deep_decisions),
            "used_inline": len(inline_decisions),
            "skipped": len(skip_decisions),
            "credits_used": total_credits,
            "total_items": total_items,
            "total_content_chars": total_content,
        },
    }


# ══ Stage 4: Branch-decomposed Synthesis ════════════════════════════════════════

class _SynthFollowUpAction(BaseModel):
    modality: str
    timing: str = ""
    indication: str = ""
    urgency: str = "routine"
    guideline_source: str = ""


class _PathwaySynthesis(BaseModel):
    urgency_tier: str = "none"
    uk_authority: str = ""
    guideline_refs: List[str] = Field(default_factory=list)
    follow_up_actions: List[_SynthFollowUpAction] = Field(default_factory=list)


class _SynthClassification(BaseModel):
    system: str
    authority: str = ""
    year: Optional[str] = None
    grade: str = ""
    criteria: str = ""
    management: str = ""


class _SynthThreshold(BaseModel):
    parameter: str
    threshold: str
    significance: str = ""
    context: str = ""  # renamed from measurement_tip — covers both imaging technique and lab/biomarker notes


class _ClassificationSynthesis(BaseModel):
    classifications: List[_SynthClassification] = Field(default_factory=list)
    thresholds: List[_SynthThreshold] = Field(default_factory=list)


class _SynthDifferential(BaseModel):
    diagnosis: str
    key_features: str = ""
    excluders: str = ""
    likelihood: str = "common"


class _DifferentialSynthesis(BaseModel):
    clinical_summary: str = ""
    differentials: List[_SynthDifferential] = Field(default_factory=list)
    imaging_flags: List[str] = Field(default_factory=list)


class SynthesisRequest(BaseModel):
    knowledge_base: Dict[str, List[Dict[str, Any]]]
    consolidated_findings: List[str]
    finding_short_labels: List[str] = Field(default_factory=list)
    applicable_guidelines: List[Dict[str, Any]] = Field(default_factory=list)
    scan_type: str = ""
    clinical_history: str = ""
    report_content: str = ""


_PATHWAY_SYNTHESIS_SYSTEM = """You are a senior UK consultant radiologist synthesising clinical pathway evidence for NHS colleagues.
Use British English. Extract pathway, follow-up, and referral information ONLY from the provided evidence.

OUTPUT: Return ONLY valid JSON — no other text:
{
  "urgency_tier": "urgent" | "soon" | "routine" | "watch" | "none",
  "uk_authority": "primary UK guideline body (NICE/BSG/RCR/BTS/BAUS/RCOG/RCP) or empty string",
  "guideline_refs": ["short attribution e.g. 'NICE CG188'"],
  "follow_up_actions": [
    {
      "modality": "imaging modality or referral type",
      "timing": "NHS-expected timeframe e.g. '2-week wait', 'same day', '3 months'",
      "indication": "patient-specific trigger — include actual values/features that crossed the threshold",
      "urgency": "urgent" | "soon" | "routine" | "watch" | "none",
      "guideline_source": "specific attribution traceable to evidence"
    }
  ]
}
RULES: UK guidelines first. urgency_tier = most urgent action. Max 3 actions, ordered most-urgent first.

SCAN TYPE AWARENESS: Before recommending any imaging modality, check the scan type in PATIENT CONTEXT.
  If the modality was already performed as part of the current study, do not recommend it again.
  Instead, recommend the downstream action that follows from having those results
  (e.g. if CT was already done: 'MDT review with CT staging results' not 'CT abdomen and pelvis').
  Only recommend investigations that have not yet been obtained.

TIMING: timing reflects the NHS-expected timeframe — not just surveillance intervals.
  Urgent suspected cancer referrals: '2-week wait (2WW)'.
  Emergency presentations: 'same day'.
  Surveillance protocols: the specific interval ('3 months', '12 months').
  Leave empty only if the evidence genuinely does not specify a timeframe.

INDICATION: encode the patient's actual values and features that triggered this action, not a generic
  restatement of the guideline criterion. e.g. 'RMI 1278 (≥200 high risk); CA-125 142 U/mL; 6.2cm
  multilocular cystic mass with papillary projections in postmenopausal woman' rather than 'elevated
  CA-125 and high-risk adnexal mass'. The indication should be specific enough that a clinician reading
  it alone understands why this action is warranted for this patient.

For sequential/conditional surveillance protocols (e.g. "CT at 3 months, then if stable CT at 12 months"):
  each step is a separate action — include the dependency in the indication field of the downstream step
  (e.g. "If stable at 3-month CT: further surveillance" not "Solid nodule ≥6mm high-risk").
  Never repeat the same indication verbatim across two actions; the second must encode its trigger condition.
If no pathway evidence applies to this finding: return urgency_tier "none", empty lists.
Use ONLY evidence provided — never fabricate."""

_CLASSIFICATION_SYNTHESIS_SYSTEM = """You are a senior UK consultant radiologist synthesising classification criteria for NHS colleagues.
Use British English. Extract classification systems and thresholds ONLY from evidence.

OUTPUT: Return ONLY valid JSON — no other text:
{
  "classifications": [
    {
      "system": "name", "authority": "issuing body", "year": "YYYY or null",
      "grade": "grade label",
      "criteria": "GENERIC definition of this grade only — the boundary thresholds/features that define this grade in the classification system. Do NOT include any patient-specific staging or measurements here.",
      "management": "Patient-specific assignment + clinical action. MUST start with 'This patient: [stage/grade] — [feature(s)].' then state the recommended action. All patient measurements and staging rationale go HERE, not in criteria."
    }
  ],
  "thresholds": [
    {
      "parameter": "what to measure — imaging metric OR lab/biomarker",
      "threshold": "value e.g. '> 8 mm' or 'CA 19-9 > 100 U/mL'",
      "significance": "clinical meaning",
      "context": "measurement technique (imaging) or assay notes (lab/biomarker) — or empty string"
    }
  ]
}
CLASSIFICATION RULES:
• FIELD SEPARATION (strict):
  — "criteria": the generic textbook definition of this grade/stage boundary (e.g. "Tumour >4 cm but ≤5 cm"
    or "Any T, Any N, M1"). No patient measurements, no "This patient", no staging rationale.
  — "management": ALL patient-specific content — the assigned stage, the patient's measurements that place
    them there, and the recommended clinical action. Always start with "This patient: …"
  — "year": use the edition year from the evidence or authoritative reference. For UICC 9th Edition use "2025".
• Identify the grade or stage BEST MATCHING this patient's described features and state it explicitly in
  the management field. You may include 1–2 adjacent reference grades for direct comparison, but do NOT
  reproduce the full ladder generically — patient assignment is mandatory, not optional.
• Include only classification systems where the patient's findings fall within that system's defined
  scope AND the system would inform a distinct clinical decision (staging, surgical approach,
  surveillance interval, risk stratification). Do not reproduce systems that merely re-describe the
  same decision from a different angle. Typical cases require 1–2 systems; complex cases with multiple
  distinct decision-points may justify more.
• When the finding represents suspected or confirmed malignancy, one system MUST be the universal
  staging framework used for MDT discussion and referral for that tumour type. Apply the STAGING &
  GRADING chain of thought to assign each staging axis independently — using 'x' for any axis the
  available imaging cannot assess. Additional slots should be used for specialist classifications that
  inform surgical or management decisions beyond what universal staging captures, when the evidence
  supports them. If no specialist system applies, use only one classification.

REFERRAL SEQUENCING (solid organ malignancy):
• When the finding is a suspected or confirmed solid organ malignancy where surgical resection is
  a potential treatment, the primary referral in the management field is to the relevant SURGICAL
  specialty or MDT (e.g. "HPB MDT referral", "thoracic MDT referral", "colorectal MDT referral")
  — not to medical oncology. Oncology enters the pathway AFTER the MDT determines resectability
  and completes staging.
• Use "[specialty] MDT referral" as the referral target unless imaging definitively demonstrates
  unresectable or metastatic disease, in which case "oncology/MDT referral" is appropriate.
  Never state or imply treatment intent (curative, palliative) — that is a clinical decision,
  not a radiology determination.

FRAMEWORK SEPARATION (TNM staging vs surgical resectability):
• TNM T-staging and surgical resectability criteria are SEPARATE classification frameworks:
  — TNM T4: tumour involves specific named vessels (per tumour type) — an ANATOMIC staging
    descriptor based on the presence or absence of involvement, not the degree of contact.
  — Resectability (NCCN/ESPAC): defined by CONTACT ANGLE (≤180° vs >180°), vessel segment,
    and reconstructability — a SURGICAL decision framework.
• These frameworks use overlapping anatomy but different definitions. Do NOT conflate them.
  SMA contact ≤180° is a resectability threshold, NOT a T-stage boundary.
• When both apply (common for hepatobiliary, pancreatic, lung malignancy), they MUST appear
  as SEPARATE classification entries — one for TNM staging, one for resectability — each
  with its own grade, criteria, and management fields. Do not merge them into one entry.

THRESHOLD RULES:
• Include thresholds for BOTH imaging measurements (size, attenuation, enhancement, HU values) AND
  laboratory/biomarker cut-offs (CA 19-9, AFP, PSA, bilirubin, CA-125, CEA, alkaline phosphatase)
  when cut-off values are explicitly stated in the evidence.
• Only extract values that appear verbatim in the provided evidence — never invent thresholds.
• A threshold must function as a clinical decision-point: a value that, when crossed, changes
  management, triggers investigation, stratifies risk, or confirms/excludes a diagnosis.
  Ask: "Would a clinician act differently if the patient were above or below this value?"
  If the answer is no — if the value is a descriptive characteristic of a studied cohort
  (mean, median, range, interquartile range, or any population summary) rather than a
  prospectively applied cut-off — it is not a threshold and must not be extracted.

STAGING & GRADING — evidence-anchored chain of thought (mandatory internal reasoning before output):
  1. EXTRACT boundary definitions: From the evidence provided, identify each stage/grade boundary
     and its defining criteria (extent of invasion, size thresholds, morphological features).
     Never rely on recall — use ONLY what the evidence text states.
     SUB-STAGE RULE: When a major stage has lettered or numbered sub-divisions (e.g. T1a/T1b/T1c,
     T2a/T2b, N2a/N2b, Stage IIIA/IIIB), treat each sub-stage as a DISTINCT boundary with its OWN
     size or feature threshold. Never collapse sub-stages into the parent stage (e.g. do NOT treat
     T2a and T2b as a single "T2" bracket — they have different size cut-offs and must be
     distinguished). If the evidence does not provide sub-stage granularity, state this gap
     explicitly in the management field and assign only the parent stage.
  2. MAP patient features: List every imaging finding from the report that is relevant to staging
     (tumour extent, vascular involvement, organ invasion, nodal status, distant spread).
     Include the exact measurement(s) from the report verbatim.
  3. ASSESS COVERAGE: For each staging axis, determine whether the scan modality and anatomical
     coverage in the report are SUFFICIENT to make that call:
     — Can T-stage be assigned? (Does the scan show the primary tumour and local extent?)
     — Can N-stage be assigned? (Does the scan cover the relevant nodal stations?)
     — Can M-stage be assigned? (Does the scan cover the territories where distant metastases
       typically occur for this tumour type? e.g. CT abdomen/pelvis alone CANNOT exclude
       pulmonary metastases — M-stage requires chest imaging.)
     If a staging axis cannot be assessed from the available imaging, use the "x" descriptor
     (Tx, Nx, Mx) and state why in the management field. Never assign a negative stage (e.g. M0)
     when the required anatomy has not been imaged — absence of evidence is not evidence of absence.
  4. MATCH feature to boundary: For each axis where coverage IS sufficient, walk through the
     boundaries from lowest to highest, including ALL sub-stages. The correct stage is the highest
     boundary whose criteria the patient's features fully meet — not the one below it.
     SIZE-MATCHING: Compare the patient's exact measurement against each sub-stage's size range.
     A 4.8cm tumour in a system where T2a=">3–≤4cm" and T2b=">4–≤5cm" is T2b, NOT T2a.
  5. VERIFY: Before outputting, re-check the single most discriminating feature (e.g. does the
     thrombus extend beyond the renal vein into the IVC? Does the tumour breach the muscularis
     propria?). If it crosses the boundary between two adjacent stages, the HIGHER stage applies.
     Also verify that the measurement matches the assigned sub-stage boundary — not just the
     parent stage.
  6. RECONCILE STAGE GROUP: After determining T, N, and M independently, look up the stage group
     that matches your final (T, N, M) triple in the stage grouping table from the evidence.
     The "grade" field MUST contain the stage group derived from the FINAL (T, N, M) triple —
     not an intermediate assignment. Critical rules:
     — If M1 is assigned, the stage group is ALWAYS Stage IV regardless of T and N.
     — If you corrected any axis during verification (step 5), re-derive the stage group
       from the corrected triple before outputting.
     — The "grade" field and the staging string in "management" must be IDENTICAL.
       If they would differ, the grade field is wrong — fix it before outputting.
  7. STATE explicitly in the "management" field: "This patient: [stage] — [feature(s) that place
     them at this stage]. [Any axis marked 'x': state what additional imaging is needed.]"
• This chain of thought applies to ALL staging and grading systems (TNM, Bosniak, LI-RADS, BIRADS,
  Fleischner, BCLC, Child-Pugh, etc.). Never shortcut by defaulting to a lower stage when the
  evidence supports a higher one, and never assume a negative stage when the territory is unimaged.

MANDATORY SCOPE-CHECKS — anatomy + imaging characteristics + clinical context must ALL match:
• Bosniak → CYSTIC renal masses ONLY (septa/calcification/fluid). Solid enhancing renal mass → BAUS solid renal mass, NOT Bosniak.
• LI-RADS → cirrhosis/HBV/known HCC ONLY. Incidental low-risk liver → RCR incidental findings, NOT LI-RADS.
• Fleischner/Brock → incidental nodules WITHOUT known malignancy ONLY. Known cancer → BTS oncology nodule guidance, NOT Fleischner.

STAGING FRAMEWORK PRIORITY:
• Identify which staging framework is PRIMARY for MDT communication for this tumour type:
  — FIGO for gynaecological cancers (endometrial, cervical, ovarian, vulval, GTD)
  — Ann Arbor / Lugano for lymphoma
  — WHO grade for CNS tumours
  — UICC TNM for most other solid organ malignancies
• The PRIMARY framework's stage MUST appear in the "grade" field and as the lead staging
  string in the "management" field. If the primary framework is FIGO, the grade field should
  read e.g. "Stage IIIC1 (FIGO 2023)" — not the TNM equivalent.
• When TNM is SECONDARY (e.g. gynaecological cancers), it may appear as a separate
  supplementary classification entry but must NOT displace the primary framework.
• When TNM IS primary, the AUTHORITATIVE TNM REFERENCE below is ground-truth — use it.

AUTHORITATIVE TNM REFERENCE:
• When an "AUTHORITATIVE TNM REFERENCE (UICC …)" block is provided, it contains ground-truth
  T/N/M definitions and stage grouping from the official UICC publication. For tumour types
  where TNM is the primary framework, this ALWAYS takes precedence over web-sourced evidence
  for staging boundaries and sub-stage thresholds.
• For tumour types where TNM is secondary (e.g. FIGO-primary gynaecological cancers), the
  TNM reference provides supplementary context but the primary classification entry must use
  the primary framework from the evidence.
• Still use the web evidence for specialist classifications (Bosniak, LI-RADS, etc.) and
  thresholds not covered by the TNM reference.
Use ONLY evidence provided — never fabricate."""

_DIFFERENTIAL_SYNTHESIS_SYSTEM = """You are a senior UK consultant radiologist synthesising imaging differentials for NHS colleagues.
Use British English. Extract clinical overview, differentials, and imaging observations ONLY from evidence.

OUTPUT: Return ONLY valid JSON — no other text:
{
  "clinical_summary": "2 sentences maximum",
  "differentials": [
    {
      "diagnosis": "name", "key_features": "imaging features suggesting this dx",
      "excluders": "features ruling it out", "likelihood": "common" | "less common" | "rare"
    }
  ],
  "imaging_flags": ["short observation phrase"]
}
RULES:
- 2 sentences max for summary. 2–4 differentials. Max 6 imaging flags (short phrases, not sentences).
- Use ONLY evidence provided — never fabricate.

DIFFERENTIALS — when to suppress:
  Return "differentials": [] if the finding is already confirmed with no genuine diagnostic
  uncertainty. Do NOT generate alternatives for findings established by the clinical context
  (e.g. emphysema, fatty liver, degenerative change, incidental staging sub-features, or any
  diagnosis explicitly confirmed in the report text). Do NOT cross-contaminate differentials
  from other findings. An empty differentials array is correct and preferred over fabricated
  or misattributed entries.

IMAGING FLAGS — always populate for significant findings:
  "imaging_flags" is independent of diagnostic certainty and must be populated for any
  clinically significant finding — even when the diagnosis is confirmed and differentials
  are empty. Capture the most important quantitative measurements and key morphological
  observations a radiologist would include in a structured report, for example:
    • Lesion dimensions (e.g. "1.4cm right frontal cavernous malformation")
    • Key imaging features confirming the diagnosis (e.g. "SWI blooming — haemorrhagic content confirmed")
    • Morphological details relevant to planning/management (e.g. "haemosiderin rim present", "no perilesional oedema")
    • Critical negative findings (e.g. "no mass effect", "no acute haemorrhage", "solitary lesion")
    • Surveillance or planning parameters (e.g. aneurysm neck anatomy, lesion growth rate)
  Leave "imaging_flags": [] ONLY for genuinely trivial incidental findings (mild fatty liver,
  mild degenerative change) where there is nothing beyond the finding name itself worth
  communicating to a clinician."""


def _branch_evidence_text_for_finding(
    finding_idx: int,
    knowledge_base: Dict[str, List[Dict[str, Any]]],
    chars_per_item: int = 2500,
    max_items_per_branch: int = 3,
) -> Dict[str, str]:
    """Build per-branch evidence text for one finding, filtered by finding_indices.

    classification_measurement gets a higher item cap (5 vs 3) because the top-3
    Tavily results are often staging anatomy papers, which push biomarker threshold
    articles out of the Pass B synthesis window entirely.
    """
    # Per-branch item cap overrides — classification branch gets extra slots for
    # biomarker threshold papers that sit below the top staging results.
    branch_caps: Dict[str, int] = {"classification_measurement": 5}

    result: Dict[str, str] = {}
    for branch, items in knowledge_base.items():
        cap = branch_caps.get(branch, max_items_per_branch)
        relevant = [
            item for item in items
            if not item.get("finding_indices") or finding_idx in item.get("finding_indices", [])
        ]
        if not relevant:
            continue
        parts: List[str] = []
        for i, item in enumerate(relevant[:cap], 1):
            content = (item.get("content") or "")[:chars_per_item]
            title = item.get("title") or item.get("domain") or ""
            url = item.get("url", "")
            hdr = f"[{i}: {title}]" if title else f"[{i}]"
            if url:
                hdr += f" {url}"
            parts.append(f"{hdr}\n{content}" if content else hdr)
        if parts:
            result[branch] = "\n\n---\n\n".join(parts)
    return result


async def _run_synthesis_passes(
    finding_idx: int,
    finding_label: str,
    finding_short_label: str,
    branch_evidence: Dict[str, str],
    source_items: List[Dict[str, Any]],
    scan_type: str,
    clinical_history: str,
    report_content: str,
    cerebras_key: str,
) -> Dict[str, Any]:
    """3 parallel GLM passes (pathway / classification / differential) for one finding."""
    from rapid_reports_ai.enhancement_utils import _run_agent_with_model

    ctx = (
        f"PATIENT CONTEXT (use for scope-checking and scan-type awareness — "
        f"do not synthesise classification or threshold data from this):\n"
        f"Scan type: {scan_type or 'not specified'}\n"
        f"Clinical history: {clinical_history or 'not provided'}\n"
        f"Finding: {finding_label}"
    )
    if report_content:
        ctx += (
            f"\n\nREPORT TEXT (find description of \"{finding_label}\" for scope-check):\n"
            + report_content[:1500]
        )

    # Same GLM settings as S1 extract: reasoning ON with Cerebras floor temp 0.8 + top_p 0.95.
    # Low temperature with reasoning caused intermittent tool_call 400s; per-pass token caps
    # right-sized to reduce TPM reservation: PassA=2000, PassB=2500, PassC=2000.
    ms_s4: Dict[str, Any] = {
        "temperature": 0.8,
        "top_p": 0.95,
        "extra_body": {"disable_reasoning": False},
    }

    async def _pass_a() -> _PathwaySynthesis:
        ev = branch_evidence.get("pathway_followup", "")
        if not ev:
            return _PathwaySynthesis()
        up = f"{ctx}\n\nEVIDENCE (UK Pathway & Follow-up):\n{ev}"
        try:
            r = await _run_agent_with_model(
                model_name="zai-glm-4.7", output_type=_PathwaySynthesis,
                system_prompt=_PATHWAY_SYNTHESIS_SYSTEM, user_prompt=up,
                api_key=cerebras_key, model_settings={**ms_s4, "max_completion_tokens": 2000},
            )
            return r.output
        except Exception as e:
            print(f"[S4] PassA FAIL [{finding_idx}]: {e}")
            return _PathwaySynthesis()

    async def _pass_b() -> _ClassificationSynthesis:
        ev = branch_evidence.get("classification_measurement", "")
        if not ev:
            return _ClassificationSynthesis()
        up = f"{ctx}\n\nEVIDENCE (Classification & Measurement):\n{ev}"
        try:
            r = await _run_agent_with_model(
                model_name="zai-glm-4.7", output_type=_ClassificationSynthesis,
                system_prompt=_CLASSIFICATION_SYNTHESIS_SYSTEM, user_prompt=up,
                api_key=cerebras_key, model_settings={**ms_s4, "max_completion_tokens": 3500},
            )
            return r.output
        except Exception as e:
            print(f"[S4] PassB FAIL [{finding_idx}]: {e}")
            return _ClassificationSynthesis()

    async def _pass_c() -> _DifferentialSynthesis:
        ev = branch_evidence.get("imaging_differential", "")
        if not ev:
            return _DifferentialSynthesis()
        up = f"{ctx}\n\nEVIDENCE (Imaging Features & Differentials):\n{ev}"
        try:
            r = await _run_agent_with_model(
                model_name="zai-glm-4.7", output_type=_DifferentialSynthesis,
                system_prompt=_DIFFERENTIAL_SYNTHESIS_SYSTEM, user_prompt=up,
                api_key=cerebras_key, model_settings={**ms_s4, "max_completion_tokens": 2000},
            )
            return r.output
        except Exception as e:
            print(f"[S4] PassC FAIL [{finding_idx}]: {e}")
            return _DifferentialSynthesis()

    t0 = time.perf_counter()
    pa, pb, pc = await asyncio.gather(_pass_a(), _pass_b(), _pass_c())
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    display = finding_short_label or finding_label[:50]
    print(
        f"[S4] [{finding_idx}] {display!r} — {elapsed_ms}ms "
        f"fu={len(pa.follow_up_actions)} cls={len(pb.classifications)} "
        f"thr={len(pb.thresholds)} ddx={len(pc.differentials)} flags={len(pc.imaging_flags)}"
    )

    # Collect sources from all relevant KB items
    sources: List[Dict[str, Any]] = []
    seen: set = set()
    for item in source_items:
        url = item.get("url", "")
        if url and url not in seen:
            seen.add(url)
            sources.append({
                "url": url,
                "title": item.get("title") or item.get("domain") or "",
                "domain": item.get("domain") or "",
            })

    return {
        "finding_number": finding_idx + 1,
        "finding": finding_label,
        "finding_short_label": finding_short_label,
        "urgency_tier": pa.urgency_tier,
        "uk_authority": pa.uk_authority,
        "guideline_refs": pa.guideline_refs,
        "follow_up_actions": [f.model_dump() for f in pa.follow_up_actions],
        "classifications": [c.model_dump() for c in pb.classifications],
        "thresholds": [t.model_dump() for t in pb.thresholds],
        "clinical_summary": pc.clinical_summary,
        "differentials": [d.model_dump() for d in pc.differentials],
        "imaging_flags": pc.imaging_flags,
        "sources": sources,
        "synthesis_ms": elapsed_ms,
    }


@app.post("/api/stage/synthesise")
async def stage_synthesise(req: SynthesisRequest) -> Dict[str, Any]:
    """
    Stage 4: Branch-decomposed guideline synthesis.

    Runs 3 targeted GLM passes per finding — all in parallel:
      Pass A (pathway_followup)           → urgency_tier, uk_authority, guideline_refs, follow_up_actions
      Pass B (classification_measurement) → classifications, thresholds
      Pass C (imaging_differential)       → clinical_summary, differentials, imaging_flags

    Each pass receives only its branch evidence + a small focused schema, avoiding the
    monolithic RichGuidelineEntry parse failure. Context injection (scan_type,
    clinical_history, report_content excerpt) drives correct scope-checking.
    """
    t0 = time.perf_counter()
    cerebras_key = os.environ.get("CEREBRAS_API_KEY")
    if not cerebras_key:
        raise HTTPException(status_code=500, detail="CEREBRAS_API_KEY not set in .env")
    if not req.consolidated_findings:
        return {"ok": True, "elapsed_ms": 0, "guidelines": [], "stats": {}}

    n_findings = len(req.consolidated_findings)
    n_short = len(req.finding_short_labels)
    print(
        f"\n[S4] ⏳ SYNTHESIS — {n_findings} finding(s) · "
        f"context_aware={bool(req.report_content)}"
    )
    if n_short != n_findings:
        print(f"[S4] ⚠ SHORT LABEL MISMATCH: {n_findings} findings but {n_short} short_labels")
    for i, f in enumerate(req.consolidated_findings):
        short = req.finding_short_labels[i] if i < n_short else ""
        label_display = f"{short!r} → {f}" if short else f"[no short_label] {f}"
        print(f"[S4]   [{i}] {label_display}")

    async def _process(idx: int, label: str) -> Dict[str, Any]:
        short_label = req.finding_short_labels[idx] if idx < len(req.finding_short_labels) else ""
        branch_ev = _branch_evidence_text_for_finding(idx, req.knowledge_base)
        src_items: List[Dict[str, Any]] = []
        for items in req.knowledge_base.values():
            for item in items:
                fi = item.get("finding_indices") or []
                if not fi or idx in fi:
                    src_items.append(item)
        if not any(branch_ev.values()):
            print(f"[S4]   [{idx}] no evidence — returning empty entry")
            return {
                "finding_number": idx + 1, "finding": label,
                "finding_short_label": short_label,
                "urgency_tier": "none",
                "uk_authority": "", "guideline_refs": [], "follow_up_actions": [],
                "classifications": [], "thresholds": [], "clinical_summary": "",
                "differentials": [], "imaging_flags": [], "sources": [], "synthesis_ms": 0,
            }
        return await _run_synthesis_passes(
            idx, label, short_label, branch_ev, src_items,
            req.scan_type, req.clinical_history, req.report_content, cerebras_key,
        )

    guidelines = list(await asyncio.gather(*[
        _process(i, lbl) for i, lbl in enumerate(req.consolidated_findings)
    ]))

    # Rendering gate: drop cards with zero actionable content.
    # A card that passed through synthesis but has no follow-up, classifications,
    # thresholds, differentials, or imaging flags adds no clinical value and should
    # not reach the UI (e.g. background observations like mild emphysema).
    def _has_content(g: Dict[str, Any]) -> bool:
        return any([
            g.get("follow_up_actions"),
            g.get("classifications"),
            g.get("thresholds"),
            g.get("differentials"),
            g.get("imaging_flags"),
        ])

    all_count = len(guidelines)
    guidelines = [g for g in guidelines if _has_content(g)]
    dropped = all_count - len(guidelines)
    if dropped:
        print(f"[S4]   Rendering gate: dropped {dropped} empty card(s)")

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    total_fu = sum(len(g.get("follow_up_actions", [])) for g in guidelines)
    total_cls = sum(len(g.get("classifications", [])) for g in guidelines)
    total_ddx = sum(len(g.get("differentials", [])) for g in guidelines)
    print(
        f"[S4] ✅ SYNTHESIS — {elapsed_ms}ms · {len(guidelines)} guideline(s) · "
        f"fu={total_fu} · cls={total_cls} · ddx={total_ddx}"
    )
    for g in guidelines:
        sl = g.get("finding_short_label") or "[no short_label]"
        fu  = len(g.get("follow_up_actions", []))
        cls = len(g.get("classifications", []))
        thr = len(g.get("thresholds", []))
        ddx = len(g.get("differentials", []))
        flg = len(g.get("imaging_flags", []))
        print(f"[S4]   card: {sl!r} · fu={fu} cls={cls} thr={thr} ddx={ddx} flags={flg}")

    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "guidelines": guidelines,
        "stats": {
            "findings_processed": len(guidelines),
            "context_injected": bool(req.report_content),
            "total_follow_up_actions": total_fu,
            "total_classifications": total_cls,
            "total_differentials": total_ddx,
        },
    }


# --- Run All (sequential stages) -------------------------------------------------

@app.post("/api/run-all")
async def run_all(req: RunAllRequest) -> Dict[str, Any]:
    """
    Full pipeline: S1 GLM Extract → S2 Tavily/Perplexity Discover →
    S2.5 GLM Triage → S3 Structured Extract (per-branch knowledge base).
    """
    run_t0 = time.perf_counter()
    print(f"\n{'═'*70}")
    print(f"[RUN] ▶ RUN-ALL  S2={req.search_provider!r}  score≥{req.score_threshold}")
    print(f"[RUN]   scan_type: {req.scan_type or '(none)'}")
    print(f"[RUN]   clinical_history: {(req.clinical_history or '(none)')[:120]}")
    print(f"[RUN]   findings: {req.findings[:200]}")
    print(f"{'─'*70}")
    stages: Dict[str, Any] = {}

    # ── Stage 1: GLM Extract ──────────────────────────────────────────────────
    extract_result = await stage_glm_extract(
        ExtractRequest(
            findings=req.findings,
            scan_type=req.scan_type,
            clinical_history=req.clinical_history,
        )
    )
    stages["glm_extract"] = extract_result
    if not extract_result.get("ok"):
        total_ms = sum(s.get("elapsed_ms", 0) for s in stages.values())
        return {"ok": False, "total_elapsed_ms": total_ms, "stages": stages, "stopped_at": "glm_extract"}

    ctx = extract_result["result"]
    query_plan = ctx.get("query_plan", {})
    guideline_systems = [g["system"] for g in ctx.get("applicable_guidelines", [])]

    # Scale deep-extract budget with the number of distinct findings from S1.
    # Each finding cluster warrants up to 3 deep extracts; cap at 9 to stay within budget.
    n_findings = max(1, len(ctx.get("consolidated_findings", [])))
    effective_max_deep = min(3 * n_findings, 9)
    print(f"[RUN]   max_deep_extract: {effective_max_deep} ({n_findings} finding(s) × 3, cap 9)")

    # ── Stage 2: Discover (Tavily Search or Perplexity) ───────────────────────
    discover_req = DiscoverRequest(
        query_plan=query_plan,
        search_mode=req.search_mode,
        guideline_systems=guideline_systems,
    )
    if req.search_provider == "tavily":
        discover_result = await stage_tavily_search(discover_req)
        stages["tavily_search"] = discover_result
    else:
        discover_result = await stage_perplexity_discover(discover_req)
        stages["perplexity_discover"] = discover_result

    # ── Stage 2.5: Build triage candidates (score-filtered) + GLM Triage ─────
    raw = discover_result.get("raw_results", [])
    score_threshold = req.score_threshold if req.search_provider == "tavily" else 0.0

    seen_urls: set = set()
    candidates: List[TriageURLItem] = []
    for item in raw:
        score = item.get("score", 1.0)
        if score < score_threshold:
            continue
        url = item.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        candidates.append(TriageURLItem(
            url=url,
            title=item.get("title", ""),
            domain=item.get("domain", _extract_domain_simple(url)),
            score=score,
            branch=item.get("_branch", ""),
            inline_content=item.get("content", ""),
        ))

    print(f"[RUN]   Score filter (≥{score_threshold}): {len(raw)} raw → {len(candidates)} candidates for triage")

    triage_result = await stage_glm_triage(TriageRequest(
        prefetch_context=ctx,
        candidates=candidates,
        max_deep_extract=effective_max_deep,
    ))
    stages["glm_triage"] = triage_result

    # ── Branch adequacy check + recovery triage ───────────────────────────────
    # After primary triage, verify every branch has at least one evidence source.
    # If a branch is starved (0 deep + 0 inline), run a targeted second triage
    # over the top-N skipped candidates for that branch using relaxed criteria.
    # This is deterministic and directly fixes the observed hard failure mode
    # where pathway_followup has zero evidence and synthesis returns empty output.
    decisions = [TriageDecision(**d) for d in triage_result.get("decisions", [])]

    _ALL_BRANCHES = ["pathway_followup", "classification_measurement", "imaging_differential"]

    def _branch_has_evidence(decisions: List[TriageDecision], branch: str) -> bool:
        return any(d.action in ("deep_extract", "use_inline") and d.branch == branch for d in decisions)

    starved_branches = [b for b in _ALL_BRANCHES if not _branch_has_evidence(decisions, b)]

    if starved_branches:
        cerebras_key = os.environ.get("CEREBRAS_API_KEY", "")
        print(f"[S2.5] ⚠ BRANCH ADEQUACY — starved: {', '.join(starved_branches)} — running recovery triage")

        skipped_urls = {d.url for d in decisions if d.action == "skip"}

        # Per starved branch: take the top-8 skipped candidates ordered by Tavily score.
        # A small window keeps the recovery call fast; best-scoring candidates are most likely useful.
        recovery_pool: List[TriageURLItem] = []
        for branch in starved_branches:
            branch_skipped = sorted(
                [c for c in candidates if c.url in skipped_urls and c.branch == branch],
                key=lambda c: c.score,
                reverse=True,
            )[:8]
            recovery_pool.extend(branch_skipped)

        if recovery_pool:
            deep_already_used = sum(1 for d in decisions if d.action == "deep_extract")
            recovery_max_deep = max(1, effective_max_deep - deep_already_used)

            recovery_decisions = await _run_recovery_triage(
                cerebras_key=cerebras_key,
                ctx=ctx,
                starved_branches=starved_branches,
                candidates=recovery_pool,
                max_deep_extract=recovery_max_deep,
            )

            if recovery_decisions:
                recovered_urls = {d.url for d in recovery_decisions}
                # Replace old skip decisions for recovered URLs with new routing
                decisions = [d for d in decisions if d.url not in recovered_urls] + recovery_decisions

                r_deep = [d for d in recovery_decisions if d.action == "deep_extract"]
                r_inline = [d for d in recovery_decisions if d.action == "use_inline"]
                print(f"[S2.5] ✅ RECOVERY — rescued: {len(r_deep)} deep, {len(r_inline)} inline "
                      f"across {', '.join(starved_branches)}")
                stages["glm_triage"]["recovery"] = {
                    "triggered": True,
                    "starved_branches": starved_branches,
                    "candidates_reviewed": len(recovery_pool),
                    "rescued_deep": len(r_deep),
                    "rescued_inline": len(r_inline),
                }
        else:
            print(f"[S2.5] ⚠ RECOVERY — no skipped candidates available for {', '.join(starved_branches)}")
    else:
        stages["glm_triage"]["recovery"] = {"triggered": False}

    # ── Stage 3: Structured Extract ───────────────────────────────────────────

    structured_result = await stage_structured_extract(StructuredExtractRequest(
        decisions=decisions,
        candidates=candidates,
        guideline_system=guideline_systems[0] if guideline_systems else "",
    ))
    stages["structured_extract"] = structured_result

    # ── Stage 4: Synthesis (optional — runs when report_content is provided) ──
    synthesis_result: Optional[Dict[str, Any]] = None
    if req.report_content:
        synthesis_result = await stage_synthesise(SynthesisRequest(
            knowledge_base=structured_result.get("knowledge_base", {}),
            consolidated_findings=ctx.get("consolidated_findings", []),
            finding_short_labels=ctx.get("finding_short_labels", []),
            applicable_guidelines=ctx.get("applicable_guidelines", []),
            scan_type=req.scan_type,
            clinical_history=req.clinical_history,
            report_content=req.report_content,
        ))
        stages["synthesis"] = synthesis_result
        print(f"[RUN]   S4 synthesis: {synthesis_result.get('elapsed_ms', 0)}ms")

    # ── Summary ───────────────────────────────────────────────────────────────
    total_ms = round((time.perf_counter() - run_t0) * 1000)
    s1_ms = stages["glm_extract"].get("elapsed_ms", 0)
    s2_key = "tavily_search" if req.search_provider == "tavily" else "perplexity_discover"
    s2_ms = stages.get(s2_key, {}).get("elapsed_ms", 0)
    s2_urls = stages.get(s2_key, {}).get("total_results", 0)
    triage_ms = triage_result.get("elapsed_ms", 0)
    triage_counts = triage_result.get("counts", {})
    s3_ms = structured_result.get("elapsed_ms", 0)
    s3_stats = structured_result.get("stats", {})

    print(f"{'─'*70}")
    print(f"[RUN] ■ COMPLETE  total={total_ms}ms")
    print(f"[RUN]   S1={s1_ms}ms · S2={s2_ms}ms ({s2_urls} URLs) · "
          f"triage={triage_ms}ms · S3={s3_ms}ms")
    print(f"[RUN]   Triage: {triage_counts.get('deep_extract',0)} deep, "
          f"{triage_counts.get('use_inline',0)} inline, "
          f"{triage_counts.get('skip',0)} skipped")
    print(f"[RUN]   Knowledge base: {s3_stats.get('total_items',0)} items, "
          f"{s3_stats.get('total_content_chars',0):,} chars, "
          f"{s3_stats.get('credits_used',0)} credits")
    print(f"{'═'*70}\n")

    # ── Production-integration envelope ───────────────────────────────────────
    # Top-level keys that production consumers can read directly without digging
    # into nested stage payloads.  Shape mirrors what guideline_prefetch.py will
    # write into ENHANCEMENT_RESULTS when this pipeline is wired into main.py.
    s4_ms = synthesis_result.get("elapsed_ms", 0) if synthesis_result else 0
    s4_stats = synthesis_result.get("stats", {}) if synthesis_result else {}
    prefetch_output = {
        # Structured evidence pool, keyed by branch type.
        # Injected into audit context as-is; also used to seed per-finding synthesis.
        "knowledge_base": structured_result.get("knowledge_base", {}),
        # S4 synthesis output — GuidelineEntry-shaped list, ready for frontend rendering.
        "guidelines": synthesis_result.get("guidelines", []) if synthesis_result else [],
        # S1 extraction artefacts — forwarded to downstream synthesis and audit prompts.
        "consolidated_findings": ctx.get("consolidated_findings", []),
        "finding_short_labels": ctx.get("finding_short_labels", []),
        "applicable_guidelines": ctx.get("applicable_guidelines", []),
        "urgency_signals": ctx.get("urgency_signals", []),
        "query_plan": ctx.get("query_plan", {}),
        # All discovered + triaged URLs — useful for cache seeding in ensure_guideline_cached.
        "deep_extract_urls": [
            d.url for d in decisions if d.action == "deep_extract"
        ],
        "inline_urls": [
            d.url for d in decisions if d.action == "use_inline"
        ],
        # Pipeline telemetry for monitoring / SLA tracking in production.
        "pipeline_ms": {
            "s1_extract": s1_ms,
            "s2_discover": s2_ms,
            "s2_5_triage": triage_ms,
            "s3_extract": s3_ms,
            "s4_synthesis": s4_ms,
            "total": total_ms,
        },
        "triage_counts": triage_counts,
        "kb_stats": s3_stats,
        "synthesis_stats": s4_stats,
    }

    if synthesis_result:
        print(f"[RUN]   Synthesis: {s4_stats.get('findings_processed',0)} findings · "
              f"fu={s4_stats.get('total_follow_up_actions',0)} · "
              f"cls={s4_stats.get('total_classifications',0)} · "
              f"ddx={s4_stats.get('total_differentials',0)}")

    return {"ok": True, "total_elapsed_ms": total_ms, "stages": stages, "prefetch_output": prefetch_output}


# --- Entry point -----------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PREFETCH_TEST_PORT", "8765"))
    print(f"\nPrefetch Pipeline Tester running at http://localhost:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
