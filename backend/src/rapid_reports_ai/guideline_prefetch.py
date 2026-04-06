"""
Guideline Prefetch Pipeline
===========================
Parallel background pipeline that fires alongside report generation and
builds a structured knowledge base of UK clinical guidelines, classification
criteria, and imaging reference material for downstream use by the
enhancement and audit modules.

Pipeline stages:
  S1  — GLM Extract (zai-glm-4.7, reasoning ON): structured extraction of
         findings, applicable guidelines, urgency signals, and a 3-branch
         Tavily query plan from raw report inputs. Reasoning ON to correctly
         group multi-feature disease processes into single pathway entries.
  S2  — Tavily Search (3 parallel domain-filtered branches): URL discovery
         with hard domain filters to ensure UK guideline authority.
  S2.5 — GLM Triage (zai-glm-4.7, reasoning OFF): routes each candidate URL
         to deep_extract, use_inline, or skip, and generates a targeted
         extract_hint per deep_extract URL.
  S3  — Structured Extract: Tavily Extract (advanced depth) for deep_extract
         URLs; ScraperAPI UK proxy fallback for geo-blocked / failed URLs;
         inline passthrough for use_inline.

Entry point:
  async def run_prefetch_pipeline(
      findings: str,
      scan_type: str,
      clinical_history: str,
      prefetch_id: str,
      user_id: str = "",
      score_threshold: float = 0.25,
  ) -> PrefetchOutput
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from html.parser import HTMLParser as _HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from rapid_reports_ai.enhancement_models import PrefetchKnowledgeItem, PrefetchOutput

logger = logging.getLogger(__name__)

# ── Content-level geo-block signatures ───────────────────────────────────────
# Pages that return HTTP 200 but serve an access-restriction message instead
# of real clinical content (e.g. CKS behind UK-only wall).
# Checked after Tavily Extract so matched URLs are retried via ScraperAPI.
_GEO_BLOCK_SIGNATURES = (
    "only available to eligible users within the uk",
    "cks via nice is only available",
    "not available in your region",
    "please access from within the uk",
    "restricted to users in the uk",
    "only accessible to users in the uk",
    "this content is only available",
)

# ── Stage 1 system prompt ─────────────────────────────────────────────────────
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

    pathway_followup    → target the COMPLETE clinical next-steps for this finding: referral pathways
                          and urgency criteria, recommended imaging investigations (modality, sequence,
                          timing), and immediate management or intervention steps. Do not limit queries
                          to referral-trigger actions alone — a finding may warrant concurrent or
                          pre-referral investigations alongside specialist review. Cover the full
                          spectrum of what should happen next for this patient clinically.
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

# ── Stage 2.5 triage system prompt ───────────────────────────────────────────
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

# ── Stage 2.5 recovery triage system prompt ───────────────────────────────────
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

# ── Domain filters per branch ─────────────────────────────────────────────────
DOMAIN_FILTER_PATHWAY = [
    # NICE / Scottish / NHS
    "nice.org.uk",
    "cks.nice.org.uk",
    "sign.ac.uk",
    # Royal Colleges
    "rcr.ac.uk",
    "rcog.org.uk",
    "rcseng.ac.uk",
    "rcp.ac.uk",
    # Specialty societies — general/GI/HPB
    "bsg.org.uk",
    "augis.org.uk",
    "baus.org.uk",
    "basl.org.uk",             # British Association for the Study of the Liver
    # Thoracic
    "brit-thoracic.org.uk",    # British Thoracic Society (BTS)
    # Vascular / renal
    "vascularsociety.org.uk",  # Vascular Society of GB & Ireland
    "renal.org",               # UK Kidney Association (UKKA)
    # Interventional radiology
    "bsir.org",                # British Society of Interventional Radiology
    # Endocrine / thyroid
    "britishthyroidassociation.org",  # British Thyroid Association
]

DOMAIN_FILTER_CLASSIFICATION = [
    "radiopaedia.org",
    "rsna.org",
    "bir.org.uk",
    "pubmed.ncbi.nlm.nih.gov",
    "pmc.ncbi.nlm.nih.gov",
]

DOMAIN_FILTER_DIFFERENTIAL = [
    "radiopaedia.org",
    "pubmed.ncbi.nlm.nih.gov",
    "pmc.ncbi.nlm.nih.gov",
    "rsna.org",
]

_BRANCH_DOMAINS = {
    "pathway_followup": DOMAIN_FILTER_PATHWAY,
    "classification_measurement": DOMAIN_FILTER_CLASSIFICATION,
    "imaging_differential": DOMAIN_FILTER_DIFFERENTIAL,
}

# Domains where Tavily search index is sparse (JS SPAs) — deep extract preferred
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
    "basl.org.uk", "www.basl.org.uk",
    "brit-thoracic.org.uk", "www.brit-thoracic.org.uk",
    "vascularsociety.org.uk", "www.vascularsociety.org.uk",
    "renal.org", "www.renal.org",
    "bsir.org", "www.bsir.org",
    "britishthyroidassociation.org", "www.britishthyroidassociation.org",
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

# ── Local pipeline models ─────────────────────────────────────────────────────

class _ApplicableGuidelineItem(BaseModel):
    system: str
    type: str
    search_keywords: Optional[str] = None
    context: Optional[str] = None


class _QueryPlan(BaseModel):
    pathway_followup: List[str] = Field(default_factory=list)
    classification_measurement: List[str] = Field(default_factory=list)
    imaging_differential: List[str] = Field(default_factory=list)

    def total_queries(self) -> int:
        return (len(self.pathway_followup)
                + len(self.classification_measurement)
                + len(self.imaging_differential))


class _PrefetchContext(BaseModel):
    consolidated_findings: List[str] = Field(default_factory=list)
    finding_short_labels: List[str] = Field(default_factory=list)
    applicable_guidelines: List[_ApplicableGuidelineItem] = Field(default_factory=list)
    urgency_signals: List[str] = Field(default_factory=list)
    query_plan: _QueryPlan = Field(default_factory=_QueryPlan)


class _TriageURLItem(BaseModel):
    url: str
    title: str = ""
    domain: str = ""
    score: float = 0.0
    branch: str = ""
    inline_content: str = ""
    source_query: str = ""  # The search query that retrieved this URL

    @property
    def inline_content_chars(self) -> int:
        return len(self.inline_content)


class _TriageDecision(BaseModel):
    url: str
    action: str  # "deep_extract" | "use_inline" | "skip"
    branch: str
    extract_hint: Optional[str] = None
    reason: Optional[str] = None
    finding_indices: List[int] = Field(default_factory=list)


class _TriageResult(BaseModel):
    decisions: List[_TriageDecision] = Field(default_factory=list)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lstrip("www.")
    except Exception:
        return ""


def _normalize_tavily_results(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for r in response.get("results", []):
        url = r.get("url", "")
        if not url:
            continue
        content = r.get("content", "")
        normalized.append({
            "url": url,
            "title": r.get("title", ""),
            "domain": _extract_domain(url),
            "score": r.get("score", 0.0),
            "content": content,
            "snippet": content[:300] if content else "",
        })
    return normalized


# ── ScraperAPI HTML extraction ────────────────────────────────────────────────

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


# ── Stage functions ───────────────────────────────────────────────────────────

async def _stage_glm_extract(
    findings: str,
    scan_type: str,
    clinical_history: str,
) -> _PrefetchContext:
    """S1: GLM extraction — returns structured PrefetchContext."""
    from rapid_reports_ai.enhancement_utils import _run_agent_with_model

    cerebras_key = os.environ.get("CEREBRAS_API_KEY", "")
    if not cerebras_key:
        raise RuntimeError("CEREBRAS_API_KEY not set")

    user_prompt = (
        f"SCAN TYPE: {scan_type}\n"
        f"CLINICAL HISTORY: {clinical_history}\n"
        f"FINDINGS: {findings}"
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

    result = await _run_agent_with_model(
        model_name="zai-glm-4.7",
        output_type=_PrefetchContext,
        system_prompt=PREFETCH_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        api_key=cerebras_key,
        model_settings=model_settings,
    )
    return result.output


async def _run_tavily_branch(
    branch_key: str,
    queries: List[str],
    domain_filter: List[str],
) -> List[Dict[str, Any]]:
    """Run one Tavily Search branch — all queries in parallel."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        logger.warning("[S2] TAVILY_API_KEY not set — branch %s skipped", branch_key)
        return []

    try:
        from tavily import AsyncTavilyClient
    except ImportError:
        logger.error("[S2] tavily package not installed")
        return []

    queries = queries[:5]  # Hard cap per branch

    async def _one_query(query: str) -> List[Dict[str, Any]]:
        kwargs: Dict[str, Any] = {
            "query": query,
            "search_depth": "advanced",
            "max_results": 5,
            "chunks_per_source": 3,
        }
        if domain_filter:
            kwargs["include_domains"] = domain_filter
        client = AsyncTavilyClient(api_key)
        try:
            resp = await asyncio.wait_for(client.search(**kwargs), timeout=30.0)
            results = _normalize_tavily_results(resp)
            for r in results:
                r["_query"] = query  # tag with originating query
            logger.debug("[S2] %s query=%r → %d results", branch_key, query[:60], len(results))
            return results
        except asyncio.TimeoutError:
            logger.warning("[S2] %s TIMEOUT query=%r", branch_key, query[:60])
            return []
        except Exception as exc:
            logger.warning("[S2] %s ERROR %s query=%r", branch_key, exc, query[:60])
            return []

    nested: List[List[Dict[str, Any]]] = list(
        await asyncio.gather(*[_one_query(q) for q in queries])
    )

    seen: set = set()
    raw: List[Dict[str, Any]] = []
    for results in nested:
        for item in results:
            url = item.get("url", "")
            if url and url not in seen:
                seen.add(url)
                item["_branch"] = branch_key
                raw.append(item)

    raw.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return raw


async def _stage_tavily_search(
    query_plan: _QueryPlan,
    score_threshold: float = 0.25,
) -> List[_TriageURLItem]:
    """S2: Tavily Search — 3 parallel branches, returns deduplicated candidates."""
    branch_jobs = [
        (k, getattr(query_plan, k), _BRANCH_DOMAINS[k])
        for k in ("pathway_followup", "classification_measurement", "imaging_differential")
        if getattr(query_plan, k)
    ]

    branch_results: List[List[Dict[str, Any]]] = list(
        await asyncio.gather(*[
            _run_tavily_branch(key, queries, domains)
            for key, queries, domains in branch_jobs
        ])
    )

    # Per-branch cap: keep top 10 by score within each branch (already score-sorted)
    # before cross-branch dedup. Preserves clinical balance — Branch A items score lower
    # than B/C but are equally important; a global cap would drop them preferentially.
    _BRANCH_CAP = 10
    capped_results: List[List[Dict[str, Any]]] = []
    for results in branch_results:
        kept: List[Dict[str, Any]] = []
        for item in results:
            if item.get("score", 0.0) >= score_threshold:
                kept.append(item)
            if len(kept) >= _BRANCH_CAP:
                break
        capped_results.append(kept)

    seen_urls: set = set()
    candidates: List[_TriageURLItem] = []
    for results in capped_results:
        for item in results:
            url = item.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append(_TriageURLItem(
                url=url,
                title=item.get("title", ""),
                domain=item.get("domain", _extract_domain(url)),
                score=item.get("score", 0.0),
                branch=item.get("_branch", ""),
                inline_content=item.get("content", ""),
                source_query=item.get("_query", ""),
            ))

    # Global score sort so triage sees highest-confidence items first
    candidates.sort(key=lambda c: c.score, reverse=True)

    logger.info("[S2] %d candidates after score≥%.2f filter + branch cap", len(candidates), score_threshold)
    return candidates


async def _stage_glm_triage(
    ctx: _PrefetchContext,
    candidates: List[_TriageURLItem],
    max_deep_extract: int,
) -> List[_TriageDecision]:
    """S2.5: GLM Triage — routes each candidate to deep_extract / use_inline / skip."""
    from rapid_reports_ai.enhancement_utils import _run_agent_with_model

    cerebras_key = os.environ.get("CEREBRAS_API_KEY", "")
    if not cerebras_key:
        raise RuntimeError("CEREBRAS_API_KEY not set")

    findings = ctx.consolidated_findings
    guidelines = ctx.applicable_guidelines
    urgency = ctx.urgency_signals

    ctx_summary = (
        f"FINDINGS: {', '.join(findings)}\n"
        f"URGENCY: {', '.join(urgency) or 'none'}\n"
        f"KEY GUIDELINES: {', '.join(g.system for g in guidelines)}"
    )

    candidate_lines: List[str] = []
    for i, c in enumerate(candidates, 1):
        preview = c.inline_content[:650].replace("\n", " ") if c.inline_content else "(no inline content)"
        query_line = f"    query: {c.source_query}\n" if c.source_query else ""
        blocked = _is_deep_extract_blocked(c.url, c.domain)
        routing_line = "    routing: [INLINE-ONLY] deep_extract not available — use_inline or skip only\n" if blocked else ""
        candidate_lines.append(
            f"[{i}] branch={c.branch} score={c.score:.2f} domain={c.domain}\n"
            f"    url: {c.url}\n"
            f"    title: {c.title or '(no title)'}\n"
            f"{query_line}"
            f"{routing_line}"
            f"    inline ({c.inline_content_chars} chars): {preview}"
        )

    user_prompt = (
        f"CLINICAL CONTEXT:\n{ctx_summary}\n\n"
        f"max_deep_extract: {max_deep_extract}\n\n"
        f"CANDIDATES ({len(candidates)}):\n"
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

    result = await _run_agent_with_model(
        model_name="zai-glm-4.7",
        output_type=_TriageResult,
        system_prompt=TRIAGE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        api_key=cerebras_key,
        model_settings=model_settings,
    )
    decisions = result.output.decisions
    logger.info(
        "[S2.5] triage: %d deep, %d inline, %d skip",
        sum(1 for d in decisions if d.action == "deep_extract"),
        sum(1 for d in decisions if d.action == "use_inline"),
        sum(1 for d in decisions if d.action == "skip"),
    )
    return decisions


async def _run_recovery_triage(
    ctx: _PrefetchContext,
    starved_branches: List[str],
    candidates: List[_TriageURLItem],
    max_deep_extract: int,
) -> List[_TriageDecision]:
    """Second-pass triage for branches with zero evidence after primary triage."""
    from rapid_reports_ai.enhancement_utils import _run_agent_with_model

    cerebras_key = os.environ.get("CEREBRAS_API_KEY", "")
    if not cerebras_key:
        logger.warning("[S2.5] CEREBRAS_API_KEY not set — recovery triage skipped")
        return []

    ctx_summary = (
        f"FINDINGS: {', '.join(ctx.consolidated_findings)}\n"
        f"URGENCY: {', '.join(ctx.urgency_signals) or 'none'}\n"
        f"KEY GUIDELINES: {', '.join(g.system for g in ctx.applicable_guidelines)}"
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
            output_type=_TriageResult,
            system_prompt=TRIAGE_RECOVERY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=cerebras_key,
            model_settings=model_settings,
        )
        return result.output.decisions
    except Exception as exc:
        logger.warning("[S2.5] RECOVERY TRIAGE FAILED: %s: %s", type(exc).__name__, exc)
        return []


async def _scraperapi_fetch(url: str, api_key: str) -> str:
    """Fetch a URL via ScraperAPI UK plain-HTML proxy and return cleaned text."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=25.0) as hx:
            resp = await hx.get(
                "https://api.scraperapi.com",
                params={"api_key": api_key, "url": url, "country_code": "uk"},
            )
            resp.raise_for_status()
        extractor = _HTMLTextExtractor()
        extractor.feed(resp.text)
        return _strip_cookie_noise(extractor.get_text()).strip()
    except Exception as exc:
        logger.warning("[S3] ScraperAPI fallback FAILED %s: %s", url, exc)
        return ""


async def _stage_structured_extract(
    decisions: List[_TriageDecision],
    candidates: List[_TriageURLItem],
    guideline_system: str = "",
) -> Dict[str, List[PrefetchKnowledgeItem]]:
    """S3: Structured extract — builds per-branch knowledge base."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not set")

    try:
        from tavily import AsyncTavilyClient
    except ImportError as exc:
        raise RuntimeError(f"tavily package not installed: {exc}") from exc

    candidate_map: Dict[str, _TriageURLItem] = {c.url: c for c in candidates}

    knowledge_base: Dict[str, List[PrefetchKnowledgeItem]] = {
        "pathway_followup": [],
        "classification_measurement": [],
        "imaging_differential": [],
    }

    deep_decisions = [d for d in decisions if d.action == "deep_extract"]
    inline_decisions = [d for d in decisions if d.action == "use_inline"]

    tavily_failed_urls: set = set()

    # Group deep_extract decisions by branch for batch Tavily calls
    deep_by_branch: Dict[str, List[_TriageDecision]] = defaultdict(list)
    for d in deep_decisions:
        deep_by_branch[d.branch].append(d)

    for branch, branch_decisions in deep_by_branch.items():
        urls = [d.url for d in branch_decisions]
        hints = [d.extract_hint for d in branch_decisions if d.extract_hint]
        combined_hint = " ".join(hints) if hints else f"{guideline_system} management criteria"
        combined_hint = combined_hint[:200]

        logger.info("[S3] deep_extract branch=%s %d URLs", branch, len(urls))
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

            for item in response.get("results", []):
                url = item.get("url", "")
                content = (item.get("raw_content") or "").strip()
                decision = next((d for d in branch_decisions if d.url == url), None)

                # Detect content-level geo-blocks: HTTP 200 but access-restriction page
                content_probe = content[:600].lower()
                if any(sig in content_probe for sig in _GEO_BLOCK_SIGNATURES):
                    logger.info("[S3] GEO-BLOCKED (content): %s → ScraperAPI fallback", url)
                    tavily_failed_urls.add(url)
                    continue

                cand = candidate_map.get(url, _TriageURLItem(url=url))
                knowledge_base[branch].append(PrefetchKnowledgeItem(
                    url=url,
                    content=content,
                    content_chars=len(content),
                    extraction_type="deep_extract",
                    extract_hint=decision.extract_hint if decision else None,
                    finding_indices=decision.finding_indices if decision else [],
                    title=cand.title,
                    domain=cand.domain,
                    branch=branch,
                ))

            for item in response.get("failed_results", []):
                url = item.get("url", "")
                tavily_failed_urls.add(url)
                logger.warning("[S3] deep_extract failed: %s — %s", url, item.get("error", "?"))

        except asyncio.TimeoutError:
            logger.error("[S3] TIMEOUT branch=%s", branch)
            for d in branch_decisions:
                tavily_failed_urls.add(d.url)
        except Exception as exc:
            logger.error("[S3] ERROR branch=%s: %s", branch, exc)
            for d in branch_decisions:
                tavily_failed_urls.add(d.url)

    # ── ScraperAPI UK plain-HTML fallback ─────────────────────────────────────
    # Handles HTTP-level failures AND content-level geo-blocks detected above.
    scraper_key = os.environ.get("SCRAPER_API_KEY", "")
    fallback_decisions = [d for d in deep_decisions if d.url in tavily_failed_urls]
    if fallback_decisions:
        if not scraper_key:
            logger.warning("[S3] ScraperAPI fallback: SCRAPER_API_KEY not set — %d URLs skipped",
                           len(fallback_decisions))
        else:
            logger.info("[S3] ScraperAPI fallback: %d URLs", len(fallback_decisions))
            fallback_results = await asyncio.gather(*[
                _scraperapi_fetch(d.url, scraper_key) for d in fallback_decisions
            ])
            for d, content in zip(fallback_decisions, fallback_results):
                if content:
                    cand = candidate_map.get(d.url, _TriageURLItem(url=d.url))
                    knowledge_base[d.branch].append(PrefetchKnowledgeItem(
                        url=d.url,
                        content=content,
                        content_chars=len(content),
                        extraction_type="deep_extract_fallback",
                        extract_hint=d.extract_hint,
                        finding_indices=d.finding_indices,
                        title=cand.title,
                        domain=cand.domain,
                        branch=d.branch,
                    ))

    # ── Inline passthrough — use S2 Tavily Search content directly ────────────
    for d in inline_decisions:
        candidate = candidate_map.get(d.url)
        content = candidate.inline_content if candidate else ""
        if content:
            knowledge_base[d.branch].append(PrefetchKnowledgeItem(
                url=d.url,
                content=content,
                content_chars=len(content),
                extraction_type="inline",
                extract_hint=None,
                finding_indices=d.finding_indices,
                title=candidate.title if candidate else "",
                domain=candidate.domain if candidate else "",
                branch=d.branch,
            ))

    total_items = sum(len(v) for v in knowledge_base.values())
    total_chars = sum(item.content_chars for v in knowledge_base.values() for item in v)
    logger.info("[S3] complete: %d items, %d chars", total_items, total_chars)
    return knowledge_base


# ── Public entry point ────────────────────────────────────────────────────────

async def run_prefetch_pipeline(
    findings: str,
    scan_type: str,
    clinical_history: str,
    prefetch_id: str,
    user_id: str = "",
    score_threshold: float = 0.25,
) -> PrefetchOutput:
    """
    Run the full prefetch pipeline and return a PrefetchOutput.

    Designed to be called as an asyncio background task that fires in parallel
    with report generation. On any unhandled exception, logs the error and
    returns a minimal PrefetchOutput so callers can proceed gracefully.

    Parameters
    ----------
    findings:          raw FINDINGS text from the chat request variables
    scan_type:         scan modality / protocol
    clinical_history:  patient clinical context
    prefetch_id:       uuid4 string assigned by the chat handler
    user_id:           user UUID string (used for findings_hash scoping)
    score_threshold:   Tavily score threshold for S2 candidate filtering (default 0.25)
    """
    import hashlib

    t0 = time.perf_counter()
    findings_hash = hashlib.sha256(
        f"{user_id}:{findings}".encode()
    ).hexdigest()[:16]

    logger.info(
        "[PREFETCH] start prefetch_id=%s findings_hash=%s findings_len=%d",
        prefetch_id, findings_hash, len(findings),
    )

    try:
        # ── S1: GLM extraction ─────────────────────────────────────────────
        _s1 = time.perf_counter()
        try:
            ctx = await asyncio.wait_for(
                _stage_glm_extract(findings, scan_type, clinical_history),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[S1] GLM extract timed out after 15s — returning minimal prefetch output"
            )
            return PrefetchOutput(
                consolidated_findings=[],
                applicable_guidelines=[],
                urgency_signals=[],
                knowledge_base={},
                pipeline_ms=int((time.perf_counter() - t0) * 1000),
                findings_hash=findings_hash,
            )
        _s1_ms = int((time.perf_counter() - _s1) * 1000)
        logger.info(
            "[FLOW_TIMING] prefetch prefetch_id=%s S1_glm_extract_ms=%d",
            prefetch_id,
            _s1_ms,
        )
        logger.info(
            "[S1] %d findings, %d guidelines, %d urgency, %d total queries",
            len(ctx.consolidated_findings),
            len(ctx.applicable_guidelines),
            len(ctx.urgency_signals),
            ctx.query_plan.total_queries(),
        )

        # ── S2: Tavily Search ──────────────────────────────────────────────
        _s2 = time.perf_counter()
        candidates = await _stage_tavily_search(ctx.query_plan, score_threshold)
        _s2_ms = int((time.perf_counter() - _s2) * 1000)
        logger.info(
            "[FLOW_TIMING] prefetch prefetch_id=%s S2_tavily_search_ms=%d candidates=%d",
            prefetch_id,
            _s2_ms,
            len(candidates),
        )

        # Scale deep-extract budget: 3 per finding, max 9
        n_findings = max(1, len(ctx.consolidated_findings))
        max_deep = min(3 * n_findings, 9)
        logger.info("[S2] %d candidates → max_deep_extract=%d", len(candidates), max_deep)

        # ── S2.5: GLM Triage ──────────────────────────────────────────────
        _s25 = time.perf_counter()
        decisions = await _stage_glm_triage(ctx, candidates, max_deep)
        _s25_ms = int((time.perf_counter() - _s25) * 1000)
        logger.info(
            "[FLOW_TIMING] prefetch prefetch_id=%s S2p5_glm_triage_ms=%d",
            prefetch_id,
            _s25_ms,
        )

        # ── Branch adequacy check + recovery triage ─────────────────────────
        _ALL_BRANCHES = ["pathway_followup", "classification_measurement", "imaging_differential"]

        def _branch_has_evidence(decs: List[_TriageDecision], branch: str) -> bool:
            return any(d.action in ("deep_extract", "use_inline") and d.branch == branch for d in decs)

        starved_branches = [b for b in _ALL_BRANCHES if not _branch_has_evidence(decisions, b)]

        if starved_branches:
            logger.warning(
                "[S2.5] BRANCH ADEQUACY — starved: %s — running recovery triage",
                ", ".join(starved_branches),
            )
            skipped_urls = {d.url for d in decisions if d.action == "skip"}
            recovery_pool: List[_TriageURLItem] = []
            for branch in starved_branches:
                branch_skipped = sorted(
                    [c for c in candidates if c.url in skipped_urls and c.branch == branch],
                    key=lambda c: c.score,
                    reverse=True,
                )[:8]
                recovery_pool.extend(branch_skipped)

            if recovery_pool:
                deep_already_used = sum(1 for d in decisions if d.action == "deep_extract")
                recovery_max_deep = max(1, max_deep - deep_already_used)

                recovery_decisions = await _run_recovery_triage(
                    ctx=ctx,
                    starved_branches=starved_branches,
                    candidates=recovery_pool,
                    max_deep_extract=recovery_max_deep,
                )

                if recovery_decisions:
                    recovered_urls = {d.url for d in recovery_decisions}
                    decisions = [d for d in decisions if d.url not in recovered_urls] + recovery_decisions
                    r_deep = sum(1 for d in recovery_decisions if d.action == "deep_extract")
                    r_inline = sum(1 for d in recovery_decisions if d.action == "use_inline")
                    logger.info(
                        "[S2.5] RECOVERY — rescued: %d deep, %d inline across %s",
                        r_deep, r_inline, ", ".join(starved_branches),
                    )

        # ── S3: Structured Extract ─────────────────────────────────────────
        guideline_system = ctx.applicable_guidelines[0].system if ctx.applicable_guidelines else ""
        _s3 = time.perf_counter()
        knowledge_base = await _stage_structured_extract(decisions, candidates, guideline_system)
        _s3_ms = int((time.perf_counter() - _s3) * 1000)
        logger.info(
            "[FLOW_TIMING] prefetch prefetch_id=%s S3_structured_extract_ms=%d",
            prefetch_id,
            _s3_ms,
        )

        pipeline_ms = round((time.perf_counter() - t0) * 1000)
        logger.info("[PREFETCH] complete prefetch_id=%s pipeline_ms=%d", prefetch_id, pipeline_ms)

        return PrefetchOutput(
            prefetch_id=prefetch_id,
            findings_hash=findings_hash,
            consolidated_findings=ctx.consolidated_findings,
            finding_short_labels=ctx.finding_short_labels,
            applicable_guidelines=[g.model_dump() for g in ctx.applicable_guidelines],
            urgency_signals=ctx.urgency_signals,
            knowledge_base=knowledge_base,
            pipeline_ms=pipeline_ms,
        )

    except Exception as exc:
        pipeline_ms = round((time.perf_counter() - t0) * 1000)
        logger.error(
            "[PREFETCH] FAILED prefetch_id=%s pipeline_ms=%d: %s",
            prefetch_id, pipeline_ms, exc, exc_info=True,
        )
        return PrefetchOutput(
            prefetch_id=prefetch_id,
            findings_hash=findings_hash,
            pipeline_ms=pipeline_ms,
        )


# ══════════════════════════════════════════════════════════════════════════════
# S4: Branch-Decomposed Synthesis Engine
# ══════════════════════════════════════════════════════════════════════════════

from rapid_reports_ai.enhancement_models import (
    ClassificationSynthesis,
    DifferentialSynthesis,
    PathwaySynthesis,
)
from typing import Tuple

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
    knowledge_base: Dict[str, List[Any]],
    chars_per_item: int = 2500,
    max_items_per_branch: int = 3,
) -> Dict[str, str]:
    """Build per-branch evidence text for one finding, filtered by finding_indices."""
    branch_caps: Dict[str, int] = {"classification_measurement": 5}
    result: Dict[str, str] = {}
    for branch, items in knowledge_base.items():
        cap = branch_caps.get(branch, max_items_per_branch)
        relevant = []
        for item in items:
            fi = item.finding_indices if hasattr(item, "finding_indices") else item.get("finding_indices", [])
            if not fi or finding_idx in fi:
                relevant.append(item)
        if not relevant:
            continue
        parts: List[str] = []
        for i, item in enumerate(relevant[:cap], 1):
            content_raw = item.content if hasattr(item, "content") else item.get("content", "")
            content = (content_raw or "")[:chars_per_item]
            title = (item.title if hasattr(item, "title") else item.get("title", "")) or \
                    (item.domain if hasattr(item, "domain") else item.get("domain", ""))
            url = item.url if hasattr(item, "url") else item.get("url", "")
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
    source_items: List[Any],
    scan_type: str,
    clinical_history: str,
    report_content: str,
) -> Dict[str, Any]:
    """3 parallel GLM passes (pathway / classification / differential) for one finding."""
    from rapid_reports_ai.enhancement_utils import _run_agent_with_model

    cerebras_key = os.environ.get("CEREBRAS_API_KEY", "")
    if not cerebras_key:
        raise RuntimeError("CEREBRAS_API_KEY not set")

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

    ms_s4: Dict[str, Any] = {
        "temperature": 0.8,
        "top_p": 0.95,
        "extra_body": {"disable_reasoning": False},
    }

    async def _pass_a() -> PathwaySynthesis:
        ev = branch_evidence.get("pathway_followup", "")
        if not ev:
            return PathwaySynthesis()
        up = f"{ctx}\n\nEVIDENCE (UK Pathway & Follow-up):\n{ev}"
        try:
            r = await _run_agent_with_model(
                model_name="zai-glm-4.7", output_type=PathwaySynthesis,
                system_prompt=_PATHWAY_SYNTHESIS_SYSTEM, user_prompt=up,
                api_key=cerebras_key, model_settings={**ms_s4, "max_completion_tokens": 2000},
            )
            return r.output
        except Exception as e:
            logger.warning("[S4] PassA FAIL [%d]: %s", finding_idx, e)
            return PathwaySynthesis()

    async def _pass_b() -> ClassificationSynthesis:
        ev = branch_evidence.get("classification_measurement", "")
        if not ev:
            return ClassificationSynthesis()

        # Hybrid TNM lookup: inject authoritative staging data when available
        tnm_block = ""
        try:
            from rapid_reports_ai.tnm_lookup import hybrid_tnm_search, format_tnm_evidence
            from rapid_reports_ai.database.connection import SessionLocal
            db = SessionLocal()
            try:
                results = hybrid_tnm_search(finding_label, db, top_k=1)
                if results:
                    tnm_block = format_tnm_evidence(results[0])
                    logger.info(
                        "[S4] [%d] TNM hit: %s (score=%.4f, bm25=#%s, sem=#%s)",
                        finding_idx, results[0].tumour, results[0].rrf_score,
                        results[0].bm25_rank, results[0].semantic_rank,
                    )
            finally:
                db.close()
        except Exception as e:
            logger.debug("[S4] TNM lookup skipped: %s", e)

        if tnm_block:
            up = (
                f"{ctx}\n\n{tnm_block}\n\n"
                f"EVIDENCE (Classification & Measurement):\n{ev}"
            )
        else:
            up = f"{ctx}\n\nEVIDENCE (Classification & Measurement):\n{ev}"

        try:
            r = await _run_agent_with_model(
                model_name="zai-glm-4.7", output_type=ClassificationSynthesis,
                system_prompt=_CLASSIFICATION_SYNTHESIS_SYSTEM, user_prompt=up,
                api_key=cerebras_key, model_settings={**ms_s4, "max_completion_tokens": 3500},
            )
            return r.output
        except Exception as e:
            logger.warning("[S4] PassB FAIL [%d]: %s", finding_idx, e)
            return ClassificationSynthesis()

    async def _pass_c() -> DifferentialSynthesis:
        ev = branch_evidence.get("imaging_differential", "")
        if not ev:
            return DifferentialSynthesis()
        up = f"{ctx}\n\nEVIDENCE (Imaging Features & Differentials):\n{ev}"
        try:
            r = await _run_agent_with_model(
                model_name="zai-glm-4.7", output_type=DifferentialSynthesis,
                system_prompt=_DIFFERENTIAL_SYNTHESIS_SYSTEM, user_prompt=up,
                api_key=cerebras_key, model_settings={**ms_s4, "max_completion_tokens": 2000},
            )
            return r.output
        except Exception as e:
            logger.warning("[S4] PassC FAIL [%d]: %s", finding_idx, e)
            return DifferentialSynthesis()

    t0 = time.perf_counter()
    pa, pb, pc = await asyncio.gather(_pass_a(), _pass_b(), _pass_c())
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    logger.info(
        "[S4] [%d] %r — %dms fu=%d cls=%d thr=%d ddx=%d flags=%d",
        finding_idx, finding_short_label or finding_label[:50], elapsed_ms,
        len(pa.follow_up_actions), len(pb.classifications),
        len(pb.thresholds), len(pc.differentials), len(pc.imaging_flags),
    )
    for _ci, _cls in enumerate(pb.classifications):
        print(
            f"[S4] [DEBUG] [PassB] [finding={finding_idx}] classification[{_ci}]: "
            f"system={_cls.system!r} grade={_cls.grade!r} mgmt={_cls.management[:200]!r}"
        )

    sources: List[Dict[str, Any]] = []
    seen: set = set()
    for item in source_items:
        url = item.url if hasattr(item, "url") else item.get("url", "")
        if url and url not in seen:
            seen.add(url)
            title = (item.title if hasattr(item, "title") else item.get("title", "")) or \
                    (item.domain if hasattr(item, "domain") else item.get("domain", ""))
            domain = item.domain if hasattr(item, "domain") else item.get("domain", "")
            sources.append({"url": url, "title": title, "domain": domain})

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


def _has_content(g: Dict[str, Any]) -> bool:
    """Rendering gate: True if the synthesis card has any actionable content."""
    return any([
        g.get("follow_up_actions"),
        g.get("classifications"),
        g.get("thresholds"),
        g.get("differentials"),
        g.get("imaging_flags"),
    ])


async def run_synthesis(
    knowledge_base: Dict[str, List[Any]],
    consolidated_findings: List[str],
    finding_short_labels: List[str],
    applicable_guidelines: List[dict],
    scan_type: str,
    clinical_history: str,
    report_content: str,
) -> Tuple[List[dict], dict]:
    """Run S4 synthesis. Returns (guidelines_cards, stats).

    Public entry point called by enhance_report after prefetch S1-S3 completes.
    Runs 3 parallel passes per finding, applies rendering gate, returns filtered cards.
    """
    if not consolidated_findings:
        return [], {}

    t0 = time.perf_counter()
    n_findings = len(consolidated_findings)
    n_short = len(finding_short_labels)
    logger.info("[S4] SYNTHESIS — %d finding(s), context_aware=%s", n_findings, bool(report_content))

    async def _process(idx: int, label: str) -> Dict[str, Any]:
        short_label = finding_short_labels[idx] if idx < n_short else ""
        branch_ev = _branch_evidence_text_for_finding(idx, knowledge_base)
        src_items: List[Any] = []
        for items in knowledge_base.values():
            for item in items:
                fi = item.finding_indices if hasattr(item, "finding_indices") else item.get("finding_indices", [])
                if not fi or idx in fi:
                    src_items.append(item)
        if not any(branch_ev.values()):
            logger.info("[S4] [%d] no evidence — returning empty entry", idx)
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
            scan_type, clinical_history, report_content,
        )

    guidelines = list(await asyncio.gather(*[
        _process(i, lbl) for i, lbl in enumerate(consolidated_findings)
    ]))

    all_count = len(guidelines)
    guidelines = [g for g in guidelines if _has_content(g)]
    dropped = all_count - len(guidelines)
    if dropped:
        logger.info("[S4] Rendering gate: dropped %d empty card(s)", dropped)

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    total_fu = sum(len(g.get("follow_up_actions", [])) for g in guidelines)
    total_cls = sum(len(g.get("classifications", [])) for g in guidelines)
    total_ddx = sum(len(g.get("differentials", [])) for g in guidelines)
    logger.info(
        "[S4] SYNTHESIS complete — %dms, %d guideline(s), fu=%d cls=%d ddx=%d",
        elapsed_ms, len(guidelines), total_fu, total_cls, total_ddx,
    )

    stats = {
        "findings_processed": len(guidelines),
        "context_injected": bool(report_content),
        "total_follow_up_actions": total_fu,
        "total_classifications": total_cls,
        "total_differentials": total_ddx,
        "synthesis_ms": elapsed_ms,
    }
    return guidelines, stats
