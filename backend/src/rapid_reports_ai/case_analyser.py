"""Phase 1 template-grounded case analyser (LAB ONLY; spec 2026-10-01-template-two-phase-design).

Runs during dictation, before any findings exist. From the template (lean template sheet) and the
clinical history it does quick's anticipatory clinical deliberation — Clinical Lane, Companion Matrix
(targeted negatives, If present), Recommendation scope — grounded by the template's technique and
paragraph inventory, and emits CASE UNITS:

    ## Case Deliberation
    QUESTION "<clinical question>"
    DIFFERENTIAL [<name>] TIER triage|aetiology "<imaging discriminator>" VISIBLE yes|no|silent
    RECOMMEND <IMAGING|REFERRAL|MDT|TISSUE|CORRELATION> "<report-form sentence>" WHEN [findings: <statement>]

and, placed into the template's findings paragraphs (by the paragraph's COVERS structures):

    NEGATIVE "<text>" TARGETS [<differential name>] | origin: case
    IF_PRESENT [<finding>] "<negative>" (core|contextual) | origin: case

The model returns the deliberation block and a list of placements (paragraph name + unit line). CODE
checks every unit and inserts the accepted placements after each paragraph's own units
(`merge_master`) — the model never rewrites the sheet. Checks fail closed: a unit that fails a check is
dropped and recorded in `rejected`; a block that cannot be read at all (no QUESTION, no DIFFERENTIAL)
leaves the result unusable (`errors`), and `merge_master` then returns the template unchanged.

The template is read with ``parse_sheet(mode="template")`` (`summarise_template`: paragraph inventory with
COVERS, negatives, normals; technique; terminology) and a template that does not parse is not deliberated
on. The model's output is read line by line; the checks the parser does not do (placement paragraph,
single-finding, duplicates of template units, TARGETS visible) run here, per unit; then the merged
master sheet must parse clean with ``parse_sheet(mode="master")`` or the whole result is unusable.

Production is untouched: nothing imports this module outside the lab script and its tests.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .report_reconcile import _is_bundled
from .template_sheet_grammar import _content_words, parse_sheet

TAGS = ("IMAGING", "REFERRAL", "MDT", "TISSUE", "CORRELATION")
TIERS = ("triage", "aetiology")
VISIBILITY = ("yes", "no", "silent")

# Rejection reasons (one per check in the spec's list, plus the shapes the grammar implies).
R_MALFORMED = "malformed unit"
R_NO_PARAGRAPH = "placement paragraph does not exist"
R_NOT_FINDINGS = "placement paragraph is not a findings paragraph"
R_BUNDLED = "negative is not single-finding"
R_DUPLICATE = "duplicates a template negative or normal"
R_DUPLICATE_CASE = "duplicates another case unit"
R_UNKNOWN_DIFF = "TARGETS names no listed DIFFERENTIAL"
R_NOT_VISIBLE = "TARGETS a differential not visible on this technique"
R_NO_VISIBLE = "DIFFERENTIAL without VISIBLE yes|no|silent"
R_BAD_TAG = "RECOMMEND tag outside the closed set"
R_NO_SUBJECT = "WHEN statement without subject"
R_UNKNOWN_LINE = "unknown line in the deliberation block"


# ─────────────────────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────────────────────
# Derived from quick_report_analyser.ANALYSER_SYSTEM_PROMPT_OPEN_WEIGHTS (Phase 2 Clinical Lane,
# Phase 4 Companion Matrix / Mandatory negatives, Phase 7 Recommendation scope + history-not-emitted,
# Phase 8 self-checks) with PRUNE_V1 lineage (no voice / structure / exemplar phases) and the
# FINDING_NEGATIVES directive (If present). Case-agnostic: structural placeholders only, no clinical
# examples (feedback_case_agnostic_prompts).

CASE_ANALYSER_SYSTEM_PROMPT = """You are a senior consultant radiologist preparing the clinical layer for one case that will be reported on a radiologist's own report template. The template already fixes the report's voice, structure, paragraphs, routine sweep negatives and technique; you do not touch any of that. Your work is the case: from the clinical history, decide what this study is being asked, which differentials the imaging bears on, which negatives answer them, which negatives follow once a finding is reported, and which recommendations a reported finding would trigger. A downstream brief reconciles your units with the dictated findings, and a generator writes the report in the template's voice.

No findings are provided. This is deliberate — your units are a scaffold, not a prediction. You are describing what the report must be able to say once dictation arrives, not inferring what will be dictated. Silence in dictation is never interpreted as presence.

Use British English throughout. Write concrete wording; no curly braces and no parameter placeholders appear in any unit.

**Voice anchor: radiology-first, UK/NHS perspective.** Negatives and recommendations reflect what a consultant radiologist writes for NHS clinicians — imaging observations rather than adjacent-specialty descriptors, UK/NHS service and referral conventions rather than US equivalents.

**Editorial restraint applies to duplication only.** A negative the template already states on every case is never repeated, reworded or split out. Restraint does not thin the case layer: every differential this study can show (VISIBLE yes) gets its targeted negative unless the template already states that exact absence, and the If-present negatives cover the findings a case like this plausibly reports. Six well-targeted negatives are better than two generic ones.

Work through the phases in order; each locks a layer the next consumes. Return ONLY the output described in OUTPUT FORMAT.

---

### Phase 1 — Evaluable field, read from the template

The template's technique — the Scan Context, the technique paragraph and any fixed technique text — states the modality, region, contrast, phases, sequences and acquisitions this radiologist's study includes. That, not the scan-type name alone and not a typical protocol for the scan type, is the evaluable field. A phase, sequence, acquisition or contrast state the template's technique does not include is not available to this study. Where the template states that an element varies by case, treat that element as uncertain, not as present.

Read the paragraph inventory. Each findings paragraph lists the structures it reports (COVERS), and the negatives and normals the template already states on every case. Those negatives and normals are the template's own phrasing: they show how this radiologist words an absence.

---

### Phase 2 — Clinical Lane

Decompose the clinical question (rule in / rule out / characterise / stage / follow up / screen / broad screen), with the management gate explicit where one exists: the decision the imaging answer feeds. State it as an imaging question. Generic framing ("rule out X") loses the management context the impression needs.

**Differentials in scope — two-tier structure when the primary hypothesis branches on aetiology.** Some clinical questions have a primary hypothesis whose confirmation on imaging opens a second question: *given confirmation, what is the cause?* — any primary pathology where aetiology materially affects management. A simple anatomical finding whose identification is itself the clinical answer is self-complete and does not require an aetiology tier.

- **Triage** — what the imaging is ruling in or out at the level of the primary hypothesis, including the alternatives that would answer the same presentation and the complications the next step depends on.
- **Aetiology** — emit only when the primary hypothesis branches on aetiology: given confirmation, the causes the imaging can discriminate.

Every differential is written on its own line with the imaging discriminator that would support it, in this technique's own descriptive vocabulary. **Visibility on this technique.** Tag each one against the evaluable field from Phase 1: VISIBLE yes when this study, as the template describes it, would show the discriminator; VISIBLE no when only another phase, sequence, acquisition or modality would show it; VISIBLE silent when imaging cannot discriminate it at all and clinical or laboratory correlation must address it (these are still listed, so the report can surface them with deferral framing). Silence in a dictation can only close a differential whose discriminator this study would show — so the tag is judged against THIS template's technique, never against the best possible protocol.

**Clinical history modifiers.** Use each relevant history item to set urgency, differential weighting and which complications matter. Modifiers shape what you emit; they are never written into any unit.

---

### Phase 3 — Targeted negatives

**One targeted negative for every differential you listed with VISIBLE yes** — the absence that would answer that differential on this study. The only exception is a differential whose absence the template's own negatives or normals already state; then the template carries it and you write nothing for it. A negative for a differential this technique cannot show (VISIBLE no or silent) cannot be asserted from this study and is not written. Generic negatives that do not tie to a listed differential do not appear.

Write each in its final report form, quoted: the observable feature that would indicate the differential, named in this technique's own descriptive vocabulary, phrased the way the template's own negatives are phrased (match their grammatical shape, register and terminology). **One finding per negative.** Each negative states the absence of exactly one finding, so it can be checked against the dictation on its own: a list of findings in one sentence cannot be kept for some items and withdrawn for others. The test is mechanical: a negative contains no "or" and no comma-separated list of findings or locations. Where you would write "or" or a comma between findings, start a new line instead, repeating the shared wording, even when the findings belong to the same differential.

**Never duplicate the template.** If a negative or normal already in the paragraph inventory states the absence (in any paragraph, in any wording, alone or inside a longer sentence), the template already covers it — do not restate it, reword it or split it out.

**Placement.** Put each negative in the findings paragraph whose COVERS list includes the structure the negative is about. Use the paragraph name exactly as the inventory writes it. A negative whose structure no paragraph covers is placed in the paragraph covering the nearest structure in the same region.

---

### Phase 4 — If present: negatives that follow a reported finding

The template's routine negatives answer the question as asked. The negatives a consultant states once a finding is reported — extent, spread, complications — have no carrier yet. List the imaging findings a case like this plausibly reports: the primary finding and each alternative or complication the study could show for this question. Every such finding gets its If-present negatives; do not leave a plausible finding without them to be brief. For each, list the negatives a consultant states once that finding is reported: the absence of each extension, spread or complication this technique shows and the next management step depends on.

Write each key as the imaging finding a radiologist would dictate, never the diagnosis it suggests, and at the most general level at which its negatives still apply. A key names one finding, never two findings joined by "with", "and" or "or": an extension or complication of the finding is a negative under its key, never part of the key. One finding per negative: no "or", no comma-separated list. Tag each negative core when any consultant states it once that finding is reported, contextual when stating it depends on the case or on local practice. At most four negatives per finding and twelve in total, in order of consequence. Never repeat a targeted negative or a template negative. Never write a negative denying something the finding is expected to cause. Place each in the findings paragraph whose COVERS list includes the structure the negative is about.

---

### Phase 5 — Recommendation scope — radiological remit, closed tag set, UK services

The remit is to clarify diagnostic uncertainty, guide probabilistic evaluation from the imaging, and direct any further radiological investigation that would resolve a doubtful element. Management decisions belong to the governing clinical team.

Every recommendation carries one of these tags, and nothing that cannot take a tag may appear. The tags are sheet notation and never appear in the report — the quoted sentence is the recommendation as the report would say it, in prose (specialty and urgency, or investigation and what it resolves):

- `IMAGING` a named further radiological test, naming what it would resolve
- `REFERRAL` named UK NHS specialty service, with urgency tier
- `MDT` a named UK multidisciplinary team that exists for this condition; omit the entry where no such MDT exists — most studies outside a planned treatment pathway have none, and an MDT is never invented to fill the slot. An MDT is a scheduled planning forum: it is never recommended on an acute or emergency study, where coordination is by referral to the receiving specialties
- `TISSUE` tissue sampling, where imaging cannot resolve the question
- `CORRELATION` clinical or laboratory correlation

**A recommendation names the service or the test, and the urgency — nothing more.** Outside remit, and never emitted: any procedure, intervention, operation or treatment by any name, management strategy, conservative-versus-operative choice, procedural technique, surgical approach, device or hardware selection, drugs, dosing, immobilisation, rehabilitation. No clause about what the service should then do: "for consideration of …", "with a view to …", "for <procedure>", "to guide <treatment>" are forbidden. Naming the specialty that should review is in scope; naming what that specialty should then do is not.

Be specific. When the next step that resolves the doubt is a test, recommend that named test (IMAGING, CORRELATION or TISSUE) rather than a generic specialty review; when it is a specialty, name the specific UK NHS service, not a broad "clinical review". Name UK NHS services and pathways, not US or international equivalents.

Each recommendation is conditional on a finding: its WHEN statement names ONE imaging finding that triggers it, with its subject (the structure or finding the statement is about), so it can be checked against the dictation. A WHEN statement never joins findings with "or" or "and/or": where two findings each trigger the same recommendation, write two RECOMMEND lines. Emit only recommendations a reported finding on this study would make clear; a recommendation that applies regardless of findings is not emitted.

---

### Phase 6 — Clinical history is never emitted

This is a radiology report: it states what the imaging establishes. The history has done its work upstream — in the question, the tiering, the weighting, and in which negatives and recommendations you chose — and none of it is written into any unit: no demographics, presenting symptoms, medications, laboratory values, prior diagnoses, prior procedures or referral wording in a negative, a recommendation sentence or a WHEN statement. The QUESTION states the imaging question and its management gate; it names no symptom, demographic, prior diagnosis or prior procedure.

---

### Phase 7 — Self-check

Before emitting, verify:

- **Differentials carry visibility** — every DIFFERENTIAL has a discriminator and VISIBLE yes, no or silent, judged against the template's technique.
- **Negatives are targeted and single** — each targeted negative names a listed DIFFERENTIAL with VISIBLE yes in TARGETS (exactly as named there) and denies exactly one finding (no "or", no list).
- **No duplicates** — no negative restates, rewords or splits out a template negative or normal, and no negative appears twice.
- **Placement** — every placement names a findings paragraph exactly as the inventory writes it, and that paragraph covers the negative's structure.
- **Recommendations in remit** — each carries one tag from the closed set, names a specific UK service or a named test and the urgency, and nothing about procedures, treatment or management ("for consideration of …" is absent); its WHEN statement names exactly one triggering finding with its subject (no "or").
- **Coverage** — every VISIBLE yes differential has its targeted negative (or is already stated by the template), and every plausible reported finding has its If-present negatives.
- **History absent** — no unit contains a history item.

---

## OUTPUT FORMAT

Return exactly two blocks, nothing before or after. One unit per line; no bullets, numbering, bold or backticks. `<angle brackets>` mark placeholders here only.

## Case Deliberation
QUESTION "<the imaging question, one line, with its management gate>"
DIFFERENTIAL [<short differential name>] TIER triage "<imaging discriminator>" VISIBLE yes
DIFFERENTIAL [<short differential name>] TIER aetiology "<imaging discriminator>" VISIBLE no
DIFFERENTIAL [<short differential name>] TIER aetiology "<what correlation must address>" VISIBLE silent
RECOMMEND <IMAGING|REFERRAL|MDT|TISSUE|CORRELATION> "<recommendation as the report would say it>" WHEN [findings: <triggering imaging finding with its subject>]

## Placements
PLACE [<paragraph name exactly as in the inventory>] NEGATIVE "<absence of one finding, in final report form>" TARGETS [<differential name exactly as in a DIFFERENTIAL line>]
PLACE [<paragraph name exactly as in the inventory>] IF_PRESENT [<imaging finding as dictated>] "<negative in final report form>" (core)
PLACE [<paragraph name exactly as in the inventory>] IF_PRESENT [<imaging finding as dictated>] "<negative in final report form>" (contextual)"""


CASE_ANALYSER_USER_TEMPLATE = """## INPUTS

Scan Type: {{SCAN_TYPE}}
Clinical History: {{CLINICAL_HISTORY}}

No findings are provided. This is deliberate — the units are a scaffold, not a prediction.

## TEMPLATE TECHNIQUE (the evaluable field)

{{TECHNIQUE}}

## PARAGRAPH INVENTORY (findings paragraphs; place case units only here)

{{INVENTORY}}

## TEMPLATE TERMINOLOGY

{{TERMS}}

Run all phases internally. Return ONLY the two blocks of the OUTPUT FORMAT."""


# ─────────────────────────────────────────────────────────────────────────────
# Template grounding summary (grammar parser, template mode)
# ─────────────────────────────────────────────────────────────────────────────

_H2 = re.compile(r"^##\s+(.*?)\s*$")
_PARA = re.compile(r"^Paragraph:\s*(?P<name>.*?)\s*(?:\((?P<sec>[^()]*)\))?\s*$", re.I)
_UNIT_LINE = re.compile(r"^\s*(?:-\s+)?[A-Z][A-Z_]+\b")


def _prose_by_block(sheet: str) -> Dict[str, List[str]]:
    """Non-unit prose lines keyed by '## ' heading title (lowercased; paragraphs by name)."""
    out: Dict[str, List[str]] = {}
    key = None
    for line in (sheet or "").splitlines():
        m = _H2.match(line)
        if m:
            pm = _PARA.match(m.group(1))
            key = ("paragraph:" + pm.group("name").strip().lower()) if pm else m.group(1).strip().lower()
            continue
        if line.startswith("# "):
            key = None
            continue
        if key and line.strip() and not _UNIT_LINE.match(line):
            out.setdefault(key, []).append(line.strip())
    return out


def summarise_template(sheet: str) -> dict:
    """Grounding summary of a lean template sheet, read with parse_sheet(mode="template").

    {"technique": str, "terms": [str], "errors": [str], "paragraphs": [{"name", "section", "role",
     "covers", "negatives", "normals"}]}
    Technique = Scan Context prose + technique-role paragraphs' FIXED text and prose. Template negatives
    are the unconditional ones (a lean sheet has no other kind). ``errors`` carries the template-mode
    lint errors: a template that does not parse is not deliberated on (fail closed).
    """
    parsed = parse_sheet(sheet or "", mode="template")
    st = parsed.structure
    roles = {sec.name: sec.role for sec in st.sections}
    prose = _prose_by_block(sheet)
    paragraphs = []
    for para in st.paragraphs:
        paragraphs.append({
            "name": para.name, "section": para.section, "role": roles.get(para.section, ""),
            "covers": list(para.covers),
            "negatives": [n.text for n in st.negatives if n.paragraph == para.id and not n.condition],
            "normals": [n.text for n in st.normals if n.paragraph == para.id],
        })
    tech_sections = {name for name, role in roles.items() if role == "technique"}
    technique_lines = [f.text for f in st.fixed_blocks if f.section in tech_sections]
    for para in st.paragraphs:
        if para.section in tech_sections:
            technique_lines += prose.get("paragraph:" + para.name.lower(), [])
    technique = "\n".join(prose.get("scan context", []))
    if technique_lines:
        technique += ("\n\nTechnique paragraph:\n" if technique else "Technique paragraph:\n") + "\n".join(technique_lines)
    terms = [f'PREFER "{t}"' for t in st.terminology.preferred] + [f'AVOID "{t}"' for t in st.terminology.suppressed]
    errors = [f"{e.line}: {e.reason}: {e.text[:80]}" for e in parsed.errors]
    return {"technique": technique.strip(), "terms": terms, "paragraphs": paragraphs, "errors": errors}


def _inventory_text(summary: dict) -> str:
    out = []
    for p in summary["paragraphs"]:
        if p.get("role") != "findings":
            continue
        out.append(f'- Paragraph "{p["name"]}" (section {p["section"]})')
        out.append(f'  COVERS: {"; ".join(p["covers"]) or "(not stated)"}')
        for n in p["normals"]:
            out.append(f'  normal: "{n}"')
        for n in p["negatives"]:
            out.append(f'  negative: "{n}"')
    return "\n".join(out) or "(no findings paragraphs)"


def build_user_prompt(summary: dict, scan_type: str, clinical_history: str) -> str:
    return (CASE_ANALYSER_USER_TEMPLATE
            .replace("{{SCAN_TYPE}}", scan_type or "")
            .replace("{{CLINICAL_HISTORY}}", (clinical_history or "").strip() or "(none provided)")
            .replace("{{TECHNIQUE}}", summary.get("technique") or "(not stated in the template)")
            .replace("{{INVENTORY}}", _inventory_text(summary))
            .replace("{{TERMS}}", "\n".join(summary.get("terms") or []) or "(none)"))


# ─────────────────────────────────────────────────────────────────────────────
# Output parsing and checks
# ─────────────────────────────────────────────────────────────────────────────

_Q_RE = re.compile(r'^QUESTION\s+"(?P<text>[^"]+)"\s*$')
_DIFF_RE = re.compile(r'^DIFFERENTIAL\s+\[(?P<name>[^\]]+)\]\s+TIER\s+(?P<tier>\w+)\s+"(?P<disc>[^"]+)"'
                      r'(?:\s+VISIBLE\s+(?P<vis>\w+))?\s*$')
_REC_RE = re.compile(r'^RECOMMEND\s+(?P<tag>[A-Za-z_]+):?\s+"(?P<text>[^"]+)"\s+WHEN\s+\[(?P<src>\w+):\s*(?P<stmt>[^\]]+)\]\s*$')
_PLACE_RE = re.compile(r'^PLACE\s+\[(?P<para>[^\]]+)\]\s+(?P<unit>.+?)\s*$')
_NEG_RE = re.compile(r'^NEGATIVE\s+"(?P<text>[^"]+)"\s+TARGETS\s+\[(?P<diff>[^\]]+)\]'
                     r'(?:\s*\|\s*origin:\s*case)?\s*$')
_IFP_RE = re.compile(r'^IF_PRESENT\s+\[(?P<finding>[^\]]+)\]\s+"(?P<text>[^"]+)"\s+\((?P<tag>core|contextual)\)'
                     r'(?:\s*\|\s*origin:\s*case)?\s*$')
_DECOR = re.compile(r"^(?:[\s\-*+•>`_]|\d+[.)])+")


@dataclass
class Placement:
    paragraph: str  # canonical paragraph name (as in the template)
    line: str       # the unit line as inserted, ending "| origin: case"
    kind: str       # "NEGATIVE" | "IF_PRESENT"
    text: str       # the negative's text
    key: str = ""   # TARGETS differential (NEGATIVE) or finding (IF_PRESENT)


@dataclass
class CaseResult:
    units_block: str = ""                       # "## Case Deliberation" block, accepted units only
    placements: List[Placement] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)       # fatal: result unusable
    rejected: List[Tuple[str, str]] = field(default_factory=list)  # (line, reason): unit dropped
    ms: int = 0
    question: str = ""
    differentials: List[dict] = field(default_factory=list)
    recommendations: List[dict] = field(default_factory=list)
    raw: str = ""
    model: str = ""

    @property
    def usable(self) -> bool:
        return not self.errors


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())).strip()


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.;])\s+|\n", text or "") if s.strip()]


def _template_claims(summary: dict) -> List[Tuple[str, frozenset]]:
    """Every template negative and normal sentence (all paragraphs), normalised, with its content words."""
    claims = []
    for p in summary["paragraphs"]:
        for t in p["negatives"] + p["normals"]:
            for s in [t] + _sentences(t):
                claims.append((_norm(s), frozenset(_content_words(s))))
    return claims


def _duplicates_template(text: str, claims) -> bool:
    """Same text (normalised), same content words, or every content word inside one template claim — a
    restated, reordered or split-out template negative is still the template's claim."""
    n, words = _norm(text), frozenset(_content_words(text))
    for cn, cw in claims:
        if n == cn or (words and words == cw) or (len(words) >= 2 and words <= cw):
            return True
    return False


def parse_and_check(raw: str, summary: dict, template_sheet: Optional[str] = None) -> CaseResult:
    """Read the model output, apply every check, and return the accepted units (fail closed per unit).

    With ``template_sheet``, the merged master sheet is then parsed with parse_sheet(mode="master"): any
    lint error there makes the whole result unusable (``errors``), so a master sheet that does not parse
    is never served."""
    res = CaseResult(raw=raw or "")
    paras = {_norm(p["name"]): p for p in summary["paragraphs"]}
    claims = _template_claims(summary)
    diffs: Dict[str, dict] = {}
    pending_places: List[str] = []
    rec_lines: List[str] = []
    block = None
    for line in (raw or "").splitlines():
        s = _DECOR.sub("", line.replace("“", '"').replace("”", '"')).replace("**", "").strip()
        if not s:
            continue
        h = re.match(r"^#{1,3}\s*(.+?)\s*$", s)
        if h:
            t = h.group(1).lower()
            block = "delib" if "deliberation" in t else ("place" if "placement" in t else None)
            continue
        if s.startswith("PLACE"):
            pending_places.append(s)
            continue
        if block != "delib" and not re.match(r"^(QUESTION|DIFFERENTIAL|RECOMMEND)\b", s):
            continue
        if s.startswith("QUESTION"):
            m = _Q_RE.match(s)
            if m and not res.question:
                res.question = m.group("text").strip()
            elif not m:
                res.rejected.append((s, R_MALFORMED))
        elif s.startswith("DIFFERENTIAL"):
            m = _DIFF_RE.match(s)
            if not m or m.group("tier").lower() not in TIERS:
                res.rejected.append((s, R_MALFORMED))
                continue
            vis = (m.group("vis") or "").lower()
            if vis not in VISIBILITY:
                res.rejected.append((s, R_NO_VISIBLE))
                continue
            name = m.group("name").strip()
            if _norm(name) in diffs:
                res.rejected.append((s, R_DUPLICATE_CASE))
                continue
            diffs[_norm(name)] = {"name": name, "tier": m.group("tier").lower(), "discriminator": m.group("disc").strip(),
                                  "visible": vis}
        elif s.startswith("RECOMMEND"):
            m = _REC_RE.match(s)
            if not m:
                res.rejected.append((s, R_MALFORMED))
                continue
            tag = m.group("tag").upper()
            if tag not in TAGS:
                res.rejected.append((s, R_BAD_TAG))
                continue
            if m.group("src").lower() != "findings":
                res.rejected.append((s, R_MALFORMED))
                continue
            stmt = m.group("stmt").strip()
            if len(_content_words(stmt)) < 2:
                res.rejected.append((s, R_NO_SUBJECT))
                continue
            text = m.group("text").strip()
            res.recommendations.append({"tag": tag, "text": text, "when": stmt})
            rec_lines.append(f'RECOMMEND {tag} "{text}" WHEN [findings: {stmt}]')
        else:
            res.rejected.append((s, R_UNKNOWN_LINE))
    res.differentials = list(diffs.values())
    if not res.question:
        res.errors.append("no QUESTION")
    if not res.differentials:
        res.errors.append("no DIFFERENTIAL")

    seen: set = set()
    for s in pending_places:
        m = _PLACE_RE.match(s)
        if not m:
            res.rejected.append((s, R_MALFORMED))
            continue
        para = paras.get(_norm(m.group("para")))
        unit = m.group("unit")
        if para is None:
            res.rejected.append((s, R_NO_PARAGRAPH))
            continue
        if para.get("role") != "findings":
            res.rejected.append((s, R_NOT_FINDINGS))
            continue
        nm, im = _NEG_RE.match(unit), _IFP_RE.match(unit)
        if nm:
            text, key = nm.group("text").strip(), nm.group("diff").strip()
            d = diffs.get(_norm(key))
            if d is None:
                res.rejected.append((s, R_UNKNOWN_DIFF))
                continue
            if d["visible"] != "yes":
                res.rejected.append((s, R_NOT_VISIBLE))
                continue
            line = f'NEGATIVE "{text}" TARGETS [{d["name"]}] | origin: case'
            kind = "NEGATIVE"
            key = d["name"]
        elif im:
            text, key = im.group("text").strip(), im.group("finding").strip()
            line = f'IF_PRESENT [{key}] "{text}" ({im.group("tag")}) | origin: case'
            kind = "IF_PRESENT"
        else:
            res.rejected.append((s, R_MALFORMED))
            continue
        if _is_bundled(text):
            res.rejected.append((s, R_BUNDLED))
            continue
        if _duplicates_template(text, claims):
            res.rejected.append((s, R_DUPLICATE))
            continue
        # A targeted negative is stated once; an If-present negative once per finding key (the same
        # negative legitimately follows different findings), and never when it is already targeted.
        mine = ("neg", _norm(text)) if kind == "NEGATIVE" else ("ifp", _norm(key), _norm(text))
        if mine in seen or ("neg", _norm(text)) in seen:
            res.rejected.append((s, R_DUPLICATE_CASE))
            continue
        seen.add(mine)
        res.placements.append(Placement(paragraph=para["name"], line=line, kind=kind, text=text, key=key))

    if res.usable:
        lines = ["## Case Deliberation", f'QUESTION "{res.question}"']
        lines += [f'DIFFERENTIAL [{d["name"]}] TIER {d["tier"]} "{d["discriminator"]}" VISIBLE {d["visible"]}'
                  for d in res.differentials]
        lines += rec_lines
        res.units_block = "\n".join(lines)
    if res.usable and template_sheet is not None:
        parsed = parse_sheet(merge_master(template_sheet, res), mode="master")
        res.errors += [f"master sheet: {e.reason}: {e.text[:120]}" for e in parsed.errors]
        if res.usable and not parsed.structure.usable:
            res.errors.append("master sheet: structure not usable")
    if not res.usable:
        res.placements = []
        res.units_block = ""
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Model call
# ─────────────────────────────────────────────────────────────────────────────

async def deliberate(template_sheet: str, structure_summary: Optional[dict], scan_type: str,
                     clinical_history: str, model_override: Optional[str] = None) -> CaseResult:
    """Phase 1: one reasoning call (quick analyser's model and settings), then code checks.

    ``structure_summary`` is the template's grounding summary (``summarise_template`` shape); None reads
    it from ``template_sheet``. Never raises on model output; a failed model call is a fatal error.
    """
    from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model

    summary = structure_summary or summarise_template(template_sheet)
    if summary.get("errors"):  # a template that does not parse is not deliberated on
        return CaseResult(errors=[f"template sheet: {e}" for e in summary["errors"]])
    user_prompt = build_user_prompt(summary, scan_type, clinical_history)
    model_name = model_override or MODEL_CONFIG["QUICK_REPORT_ANALYZER_BEST"]
    fallback = MODEL_CONFIG.get("QUICK_REPORT_ANALYZER_BEST_FALLBACK")
    # As quick's analyser: reasoning on, one settings dict fitted per provider by normalise_model_settings.
    settings = {"temperature": 0.5, "top_p": 0.95, "max_tokens": 65536}
    t0 = time.time()

    async def _call(model: str):
        return await _run_agent_with_model(model_name=model, output_type=str, system_prompt=CASE_ANALYSER_SYSTEM_PROMPT,
                                           user_prompt=user_prompt, api_key="", use_thinking=True,
                                           model_settings=settings)

    try:
        try:
            out = await _call(model_name)
        except Exception:
            if not fallback or fallback == model_name:
                raise
            model_name = fallback
            out = await _call(model_name)
    except Exception as e:  # fail closed
        res = CaseResult(errors=[f"model call failed: {type(e).__name__}: {e}"[:300]])
        res.ms = int((time.time() - t0) * 1000)
        res.model = model_name
        return res
    raw = out.output if hasattr(out, "output") else str(out)
    res = parse_and_check(raw, summary, template_sheet)
    res.ms = int((time.time() - t0) * 1000)
    res.model = model_name
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Master sheet
# ─────────────────────────────────────────────────────────────────────────────

def merge_master(template_sheet: str, result: CaseResult) -> str:
    """Template sheet + case units. Placements go after each paragraph's own units (the paragraph's last
    non-blank line), in model order; the Case Deliberation block is appended at the end. An unusable
    result returns the template unchanged."""
    if not result.usable or not result.units_block:
        return template_sheet
    by_para: Dict[str, List[str]] = {}
    for p in result.placements:
        by_para.setdefault(_norm(p.paragraph), []).append(p.line)
    lines = template_sheet.rstrip("\n").splitlines()
    out: List[str] = []
    current: Optional[str] = None

    def flush():
        if current and by_para.get(current):
            while out and not out[-1].strip():
                out.pop()
            out.extend(by_para.pop(current))
            out.append("")

    for line in lines:
        if line.startswith("# ") or _H2.match(line):
            flush()
            m = _H2.match(line)
            pm = _PARA.match(m.group(1)) if m else None
            current = _norm(pm.group("name")) if pm else None
        out.append(line)
    flush()
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + "\n\n" + result.units_block + "\n"
