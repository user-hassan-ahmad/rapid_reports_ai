"""The slim skill sheet (checklist spec §8): structure, style and each region's normal sentences for one scan-type
family and contrast facet. Written once by the model, stored and shared by every user; no clinical knowledge
about findings (the checklist rows own that). A new sheet is provisional and used at once (the radiologist
confirms every assumed sentence); reviewers approve, edit or discard it."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time

from sqlalchemy.orm import Session

from ..database.models import StackSlimSheet
from ..jev_client import JEV_MODEL, jev_post
from ..report_reconcile import _MEASUREMENT
from .http import post_json
from .schemas import OTHER, Region

logger = logging.getLogger(__name__)

PROMPT_VERSION = "slim-3"   # slim-2: no sex-specific organs in region normals; slim-3: Report Flow (house prose flow)
URL = "https://api.cerebras.ai/v1/chat/completions"
TIMEOUT_S = 120.0   # cached per family: the first case of a new scan type waits, nobody after

# The contrast facet keys the sheet: it changes what a normal sentence may say (enhancement needs contrast).
CONTRAST: dict[str, str] = {
    "none": "No intravenous contrast (a non-contrast, unenhanced or plain study, or a modality without contrast).",
    "arterial": "Intravenous contrast in an arterial or angiographic phase only.",
    "portal_venous": "Intravenous contrast in a portal venous or single routine post-contrast phase.",
    "multiphase": "Intravenous contrast in more than one phase (for example arterial and portal venous, or triple phase).",
    "delayed": "Intravenous contrast with a delayed or excretory phase.",
    "unknown": "The scan type does not say whether or how contrast is given.",
}

SLIM_SYS = """You write the structure and style sheet for one kind of radiology report. It is shared by every radiologist reporting this kind of scan, so it holds no case-specific content and no knowledge about which findings to look for: only how the report is laid out and what each region's normal statements say.

Write Markdown with exactly these sections, in this order:

## Scan Context
- **Modality:** the modality and protocol, including the contrast phase given
- **Imaged volume:** what the scan covers
- **Not assessable on this scan:** the features this protocol cannot show (for example enhancement on an unenhanced study, or a phase that is not acquired), separated by semicolons

## Structural Pattern
- **Sections:** the report sections in order
- **Sweep order:** the order regions are reported in
- **Macro-structure:** FLAT or HEADED

## Report Flow
How a consultant's findings read as prose in this kind of report, whatever order the radiologist dictated in. It is about flow, never a clinical statement. The REGIONS are only the scratchpad's sorting: never one paragraph per region.
- **Macro-structure:** FLAT (continuous prose paragraphs, no region headings) or HEADED (name the headings), as this kind of report is usually written in UK practice.
- **Lead paragraph:** the abnormal findings come first, in one paragraph opening the findings, the finding that answers the clinical question first, each with its related statements; other abnormal findings follow in the next paragraph.
- **Normal paragraphs:** after the abnormal findings, the remaining regions grouped into 2-4 paragraphs as a consultant groups them (by system), one bullet per paragraph listing the REGIONS it covers in order: "Paragraph: <Region>, <Region>, ...".
- **Joining:** how normal statements are joined (for example several normal structures named in one sentence in sweep order).

## Region Normals
One bullet per region in REGIONS, using the region name exactly: - **<Region>:** then 1-6 quoted sentences, each the statement a consultant writes when that structure is normal on this scan. One structure or feature per sentence; final report form; British English; no measurements or numbers; nothing this scan cannot show; never a statement about a disease or the clinical question. Never a sentence about an organ only one sex has (the uterus, ovaries, adnexa, cervix, prostate, seminal vesicles, testes): the sheet is shared by every patient, so those reach the report only when dictated. A region with nothing left gets no bullet.

## Style Exemplars
2-4 bullets, each - **<finding type>:** "<one example abnormal sentence in house style>".

## Terminology Rules
- **Preferred:** short rules on wording, one per bullet.

## Measurement Conventions
- **<structure or finding>:** how it is measured and reported, one per bullet.

## Impression Conventions
- **Opening convention:** how the impression opens.
- **Descriptor propagation:** which descriptors carry from findings into the impression.

## Recommendation Scope
- **<kind>:** when a recommendation of that kind is in scope, one per bullet."""

# The radiologist's typed scan type never enters this prompt: the sheet is shared, so it is written from the
# server-resolved family and regions and the contrast facet only (review 2026-10-12).
SLIM_USER = """SCAN FAMILY: {family}
CONTRAST: {contrast}
REGIONS:
{regions}"""

_LOCKS: dict[tuple, asyncio.Lock] = {}
# Backstop for the prompt rule above: a shared sentence about a sex-specific organ would be assumed for every
# patient (hand read 2026-10-12: "The prostate is normal" offered beside an ovarian cyst).
_SEX_SPECIFIC = re.compile(r"(?i)\b(?:prostat\w*|seminal|uter\w*|endometri\w*|ovar\w*|adnex\w*|cervi\w*|testi\w*|testes|scrot\w*|vagin\w*|fallopian|myometri\w*)\b")
_REGION_LINE = re.compile(r"^\s*-\s+\*\*(.+?):\*\*\s*(.*)$")


def _section(md: str, title: str) -> str:
    m = re.search(rf"^##\s+{re.escape(title)}\s*$([\s\S]*?)(?=^##\s|\Z)", md or "", re.M | re.I)
    return m.group(1) if m else ""


def clean_sentences(sentences: list[str]) -> list[str]:
    """The rules every shared normal obeys, written by the model or edited by a reviewer: no measurement, no
    sex-specific organ, one sentence each."""
    out = []
    for s in sentences:
        s = " ".join(str(s).split()).strip()
        if s and not _MEASUREMENT.search(s) and not _SEX_SPECIFIC.search(s):
            out.append(s if s.endswith(".") else s + ".")
    return out


def parse_slim(md: str, region_names: list[str]) -> tuple[dict[str, list[str]], str]:
    """(region normals for known regions, the "not assessable" list). Sentences with a measurement are dropped:
    a number nobody measured is never assumed."""
    known = {r.lower(): r for r in region_names if r != OTHER}
    normals: dict[str, list[str]] = {}
    for line in _section(md, "Region Normals").splitlines():
        m = _REGION_LINE.match(line)
        if not m or m.group(1).strip().lower() not in known:
            continue
        sentences = [s.strip() for s in re.findall(r'"([^"]+)"', m.group(2))]
        keep = clean_sentences(sentences)
        if keep:
            normals[known[m.group(1).strip().lower()]] = keep
    na = ""
    for line in _section(md, "Scan Context").splitlines():
        m = re.match(r"^\s*-\s+\*\*Not assessable on this scan:\*\*\s*(.*)$", line, re.I)
        if m:
            na = m.group(1).strip()
    return normals, na


async def contrast_facet(scan_type: str, transport=None) -> str:
    """A Jev choice over the fixed contrast list (Jev is strong at distinct choices on stated text). Fails to
    'unknown'."""
    try:
        r = await jev_post({"model": JEV_MODEL, "state": f"SCAN TYPE: {scan_type}",
                            "questions": {"contrast": {"type": "choice", "criteria": CONTRAST, "instructions": (
                                "Which describes the intravenous contrast of this scan, as the SCAN TYPE states or "
                                "its modality implies?")}}},
                           os.environ.get("OPENROUTER_API_KEY", ""), 4.0, transport)
        r.raise_for_status()
        choice = ((r.json().get("answers") or {}).get("contrast") or {}).get("choice")
        return choice if choice in CONTRAST else "unknown"
    except Exception as e:
        logger.warning("[stack.slim.contrast] %s: %s", type(e).__name__, str(e)[:200])
        return "unknown"


def model_name() -> str:
    return os.environ.get("RR_STACK_SLIM_MODEL", "qwen-3.8-27b")


async def generate(scan_type: str, family: str, contrast: str, regions: list[Region], transport=None) -> str:
    listed = "\n".join(f"- {r.name}: {r.includes}" for r in regions if r.name != OTHER)
    body = {"model": model_name(), "temperature": 0.2, "max_tokens": 8000, "reasoning_effort": "medium",
            "messages": [{"role": "system", "content": SLIM_SYS},
                         {"role": "user", "content": SLIM_USER.format(family=family, contrast=CONTRAST[contrast],
                                                                     regions=listed)}]}
    r = await post_json(URL, os.environ.get("CEREBRAS_API_KEY", ""), body, TIMEOUT_S, transport)
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"] or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _current(db: Session, family: str, contrast: str) -> StackSlimSheet | None:
    return (db.query(StackSlimSheet)
            .filter(StackSlimSheet.family == family, StackSlimSheet.contrast == contrast,
                    StackSlimSheet.prompt_version == PROMPT_VERSION, StackSlimSheet.status != "discarded")
            .order_by(StackSlimSheet.created_at.desc()).first())


async def get_or_make(db: Session, scan_type: str, family: str, regions: list[Region]) -> StackSlimSheet | None:
    """The shared sheet for this family and contrast facet; generated once (one generation per key at a time).
    A failed or unparseable generation stores nothing and returns None: the scratchpad works without it."""
    contrast = await contrast_facet(scan_type)
    row = _current(db, family, contrast)
    if row is not None:
        return row
    key = (family, contrast)
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        row = _current(db, family, contrast)
        if row is not None:
            return row
        t0 = time.perf_counter()
        try:
            md = await generate(scan_type, family, contrast, regions)
        except Exception as e:
            logger.warning("[stack.slim] %s: %s", type(e).__name__, str(e)[:200])
            return None
        normals, na = parse_slim(md, [r.name for r in regions])
        if not normals:
            logger.warning("[stack.slim] no region normals parsed for %r/%s", family, contrast)
            return None
        row = StackSlimSheet(family=family, contrast=contrast, prompt_version=PROMPT_VERSION, status="provisional",
                             model=model_name(), scan_type=scan_type, markdown=md, region_normals=normals,
                             not_assessable=na)
        db.add(row)
        db.commit()
        logger.info("[stack.slim] made %r/%s in %d ms (%d regions)", family, contrast,
                    int((time.perf_counter() - t0) * 1000), len(normals))
        return row
