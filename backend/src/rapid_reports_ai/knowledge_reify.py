"""
Knowledge Reification — persist prefetch pipeline output to the knowledge graph.

Fire-and-forget: called as a background task after prefetch completes.
Failures are logged silently and never propagate to the report generation flow.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Authoritative domains for evidence_quality classification
AUTHORITATIVE_DOMAINS = {
    "nice.org.uk", "cks.nice.org.uk", "sign.ac.uk", "rcr.ac.uk",
    "bsg.org.uk", "baus.org.uk", "brit-thoracic.org.uk",
    "bhsoc.org", "acr.org", "rsna.org",
}
CLINICAL_DOMAINS = {
    "radiopaedia.org", "statdx.com", "radiopedia.org",
    "auntminnie.com", "learningradiology.com",
}


def _classify_evidence_quality(domain: str) -> str:
    """Classify a URL's domain into evidence quality tier."""
    if not domain:
        return "general"
    domain_lower = domain.lower().strip()
    for auth in AUTHORITATIVE_DOMAINS:
        if domain_lower.endswith(auth):
            return "authoritative"
    for clin in CLINICAL_DOMAINS:
        if domain_lower.endswith(clin):
            return "clinical"
    return "general"


async def _normalise_finding_label(raw_label: str, db: Session) -> str:
    """
    Map a raw finding label to a canonical form.
    Checks the normalisation_cache table first; on miss, calls the LLM.
    """
    from .database.models import NormalisationCache

    raw_stripped = raw_label.strip()
    if not raw_stripped:
        return ""

    # Check cache
    cached = db.query(NormalisationCache).filter(
        NormalisationCache.raw_label == raw_stripped
    ).first()
    if cached:
        return cached.canonical_form

    # LLM normalisation
    try:
        canonical = await _llm_normalise(raw_stripped)
    except Exception as e:
        logger.warning("[REIFY] LLM normalisation failed for %r: %s — using lowercase fallback", raw_stripped, e)
        canonical = re.sub(r'\s+', ' ', raw_stripped.lower().strip())

    # Persist to cache
    try:
        entry = NormalisationCache(raw_label=raw_stripped, canonical_form=canonical)
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()

    return canonical


async def _llm_normalise(raw_label: str) -> str:
    """Call a lightweight LLM to produce a canonical finding label."""
    from .enhancement_utils import (
        MODEL_CONFIG, _run_agent_with_model, _get_model_provider, _get_api_key_for_provider,
    )
    from pydantic import BaseModel

    class CanonicalLabel(BaseModel):
        canonical: str

    model_name = "llama-3.3-70b-versatile"
    provider = _get_model_provider(model_name)
    api_key = _get_api_key_for_provider(provider)

    result = await _run_agent_with_model(
        model_name=model_name,
        output_type=CanonicalLabel,
        system_prompt=(
            "You normalise radiology finding labels to canonical clinical concepts. "
            "Return a JSON object with one key 'canonical' containing the normalised label. "
            "\n\nRules:"
            "\n- Map to the PRIMARY CLINICAL CONCEPT only — not the clinical presentation"
            "\n- Remove complications, measurements, anatomical specifics, and incidental findings unless they define a distinct clinical entity"
            "\n- If a label contains multiple distinct concepts, keep only the dominant one (the one that drives management)"
            "\n- Aim for SNOMED-level granularity: specific enough to be clinically meaningful, generic enough to accumulate across different cases of the same condition"
            "\n- Lowercase, remove articles (a/an/the)"
            "\n- Keep 'acute' or 'chronic' only when it changes the clinical entity (acute pancreatitis ≠ chronic pancreatitis)"
            "\n- Keep laterality only when it defines a distinct entity (left renal cell carcinoma → renal cell carcinoma)"
            "\n\nExamples:"
            "\n'Acute calculous cholecystitis with biliary obstruction' → 'acute cholecystitis'"
            "\n'Crohn's disease with terminal ileitis, RIF abscess, enterocolic fistula and hydronephrosis' → 'crohn's abscess'"
            "\n'Severe acute pancolitis with toxic megacolon measuring 8.2cm, bilateral pleural effusions' → 'toxic megacolon'"
            "\n'Right-sided pulmonary embolism with right heart strain' → 'pulmonary embolism'"
            "\n'Suspected renal cell carcinoma with renal vein thrombus' → 'renal cell carcinoma'"
            "\n'Small bilateral pleural effusions' → 'pleural effusions'"
            "\n'Ruptured abdominal aortic aneurysm with retroperitoneal haematoma' → 'ruptured aaa'"
        ),
        user_prompt=f"Normalise: {raw_label}",
        api_key=api_key,
        use_thinking=False,
        model_settings={"temperature": 0.0, "max_tokens": 100},
    )
    return result.output.canonical.strip()


async def reify_prefetch_output(
    prefetch_output: dict,
    user_id: str,
    prefetch_id: str,
    db: Session,
) -> int:
    """
    Persist PrefetchOutput.knowledge_base items to dynamic_knowledge_items.

    Returns the number of items inserted or updated.
    """
    from .database.models import DynamicKnowledgeItem

    knowledge_base = prefetch_output.get("knowledge_base", {})
    consolidated_findings = prefetch_output.get("consolidated_findings", [])
    finding_short_labels = prefetch_output.get("finding_short_labels", [])

    if not knowledge_base:
        logger.info("[REIFY] No knowledge_base in prefetch output — skipping")
        return 0

    count = 0
    now = datetime.now(timezone.utc)

    for branch, items in knowledge_base.items():
        for item in items:
            # Resolve finding label from finding_indices
            finding_indices = item.get("finding_indices", [])
            if finding_indices and len(consolidated_findings) > 0:
                idx = finding_indices[0] if finding_indices[0] < len(consolidated_findings) else 0
                finding_label = consolidated_findings[idx]
                finding_short = finding_short_labels[idx] if idx < len(finding_short_labels) else finding_label[:50]
            else:
                finding_label = branch
                finding_short = branch

            url = (item.get("url") or "").strip()
            content = (item.get("content") or "").strip()
            if not url or not content:
                continue

            # Normalise the finding label
            finding_normalized = await _normalise_finding_label(finding_label, db)
            if not finding_normalized:
                finding_normalized = re.sub(r'\s+', ' ', finding_label.lower().strip())

            domain = (item.get("domain") or "").strip()
            evidence_quality = _classify_evidence_quality(domain)

            # Upsert: check by (finding_label_normalized, url)
            existing = db.query(DynamicKnowledgeItem).filter(
                DynamicKnowledgeItem.finding_label_normalized == finding_normalized,
                DynamicKnowledgeItem.url == url,
            ).first()

            if existing:
                existing.seen_count += 1
                existing.last_seen_at = now
                existing.prefetch_id = prefetch_id
                if len(content) > (existing.content_chars or 0):
                    existing.content = content
                    existing.content_chars = len(content)
                count += 1
            else:
                new_item = DynamicKnowledgeItem(
                    finding_label=finding_label,
                    finding_label_normalized=finding_normalized,
                    finding_short_label=finding_short,
                    branch=branch,
                    title=(item.get("title") or "").strip(),
                    url=url,
                    domain=domain,
                    content=content,
                    content_chars=len(content),
                    extraction_type=item.get("extraction_type"),
                    evidence_quality=evidence_quality,
                    user_id=None,
                    prefetch_id=prefetch_id,
                    search_text=f"{finding_label} {finding_short} {item.get('title', '')}",
                )
                db.add(new_item)
                count += 1

    try:
        db.commit()
        logger.info("[REIFY] Persisted %d knowledge items from prefetch %s", count, prefetch_id)
    except Exception as e:
        db.rollback()
        logger.error("[REIFY] Commit failed: %s", e)
        return 0

    return count
