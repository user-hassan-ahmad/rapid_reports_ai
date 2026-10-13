"""Example reports stored with a template (template pipeline spec, block 4): de-identified at paste (a code backstop,
then a Jev identifier question; a still-flagged example is not stored), deleted with the template, never used across
users. Evidence for the later learning loop, so storing never fails a template save."""
import asyncio
import hashlib
import logging
import math
import os
import re
import uuid

from .database.models import TemplateExample
from .jev_client import JEV_MODEL, jev_post

logger = logging.getLogger(__name__)

IDENTIFIER_MIN = 0.5   # lab 2026-10-13: real reports after scrub <= 0.21, planted names/addresses/DOB >= 0.80
MAX_EXAMPLES = 10      # the creator takes 1-5; a bound on Jev calls per save
TIMEOUT_S = 5.0        # one Jev call per example, all in parallel (~0.5-1 s for 10 in the lab); the save waits on it
REMOVED = "[removed]"

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_PATTERNS = [
    # a labelled identifier line ("Name: …", "DOB: …", "NHS No: …") goes whole
    re.compile(r"(?im)^[ \t]*(?:name|patient name|patient|pt name|dob|d\.o\.b\.?|date of birth|nhs(?: no\.?| number)?|"
               r"mrn|hospital (?:no\.?|number)|accession(?: no\.?| number)?|address|tel|phone)[ \t]*[:#].*$"),
    re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{4}\b"),                     # NHS-number shape (10 digits)
    re.compile(r"\b0\d{2,4}[ -]?\d{3,4}[ -]?\d{3,4}\b"),            # UK phone (020 7946 0958, 07700 900123)
    re.compile(r"\b[A-Z]{1,3}\d{6,9}\b"),                              # MRN / accession shape
    re.compile(r"\b\d{7,}\b"),                                         # GMC / registration / other long ID numbers
    re.compile(r"\b\d{1,2}([/.-])\d{1,2}\1\d{2,4}\b"),                 # numeric dates: one separator, so 1.2/3.4 stays
    re.compile(rf"(?i)\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH},?\s+\d{{4}}\b"),   # 12 March 2023
    re.compile(rf"(?i)\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b"),   # March 12, 2023
    # a titled name ("Dr Jones", "Mrs A. Patel", "Dr Sarah O'Neill"): case-sensitive, one line, up to three words.
    # Lab: every real report Jev held back named a clinician this way.
    re.compile(r"\b(?:Dr|Mr|Mrs|Ms|Miss|Prof)\.?[ \t]+(?:[A-Z]\.[ \t]*)*[A-Z][A-Za-z'’-]+(?:[ \t]+[A-Z][A-Za-z'’-]+){0,2}"),
    re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}\b"),               # UK postcode (upper case only: "L4 5mm" stays)
]

Q_IDENT = ("The TEXT contains information that could identify a patient or a person involved in their care: a "
           "name, date of birth, address, phone number, hospital or NHS number, or accession number.")


def scrub(text: str) -> str:
    """The code backstop: every identifier-shaped span becomes [removed]."""
    for p in _PATTERNS:
        text = p.sub(REMOVED, text)
    return text


async def _identifier_scores(texts: list[str]) -> list[float]:
    """P(identifying) per text: one Jev noul question per text (each text is its own state), asked in parallel."""
    key = os.environ.get("OPENROUTER_API_KEY", "")

    async def one(t: str) -> float:
        r = await jev_post({"model": JEV_MODEL, "state": f"TEXT:\n{t}",
                            "questions": {"q": {"type": "noul", "instructions": Q_IDENT}}}, key, TIMEOUT_S)
        r.raise_for_status()
        return _score(r.json())

    return list(await asyncio.gather(*(one(t) for t in texts)))


def _score(body) -> float:
    """The noul score from a Jev reply, strictly: a missing, null or non-finite score raises (so nothing is stored,
    never read as clean); a finite one is clamped to [0, 1]."""
    v = ((body.get("answers") or {}).get("q") or {}).get("noul") if isinstance(body, dict) else None
    if v is None or isinstance(v, bool):
        raise ValueError("Jev reply has no identifier score")
    v = float(v)
    if not math.isfinite(v):
        raise ValueError("Jev identifier score is not finite")
    return min(1.0, max(0.0, v))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def store_examples(db, template_id, texts: list[str]) -> int:
    """Scrub, Jev-check and store the template's pasted examples; returns how many were stored. A text Jev still
    flags is skipped; if the Jev check fails, nothing is stored. A text already stored for this template is skipped."""
    tid = template_id if isinstance(template_id, uuid.UUID) else uuid.UUID(str(template_id))
    scrubbed, shas = [], []
    for t in texts[:MAX_EXAMPLES]:
        s = scrub(t or "").strip()
        h = _sha(s)
        if s and h not in shas:
            shas.append(h)
            scrubbed.append(s)
    if not scrubbed:
        return 0
    try:
        scores = await _identifier_scores(scrubbed)
    except Exception as e:
        logger.warning("template examples not stored for %s: identifier check failed (%s)", tid, type(e).__name__)
        return 0
    if len(scores) != len(scrubbed):
        logger.warning("template examples not stored for %s: %d scores for %d examples", tid, len(scores), len(scrubbed))
        return 0
    have = {sha for (sha,) in db.query(TemplateExample.sha256).filter(TemplateExample.template_id == tid).all()}
    kept = [(s, h) for s, h, score in zip(scrubbed, shas, scores) if score < IDENTIFIER_MIN and h not in have]
    held = sum(score >= IDENTIFIER_MIN for score in scores)
    for s, h in kept:
        db.add(TemplateExample(template_id=tid, text=s, sha256=h, source="pasted"))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info("template examples %s: stored=%d held_back=%d", tid, len(kept), held)
    return len(kept)
