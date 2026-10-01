"""Lab copies of the skill-sheet analyser prompt in the LEAN template grammar (spec 2026-10-01 template
two-phase design), plus the lint-repair prompt.

Production (`TemplateManager.analyze_examples_to_skill_sheet`) is untouched: this module is used only by
`scripts/template_sheet_lab.py` until Hassan signs off the wording. The analyser keeps production's intent
(reverse-engineer the radiologist's voice and structure from their example reports, grounded in quoted
text). The sheet is lean: structure, rich voice prose, and the template-intrinsic units (NORMAL, routine
NEGATIVE, FIXED, TERM, LIST_MISSING, context rules). Case-dependent clinical reasoning (findings-conditioned
rules, If-present negatives, recommendations) belongs to the per-case Phase 1 analyser; here it appears only
as quoted voice exemplars. Instructions are case-agnostic: structural placeholders only.

The sheet is returned between delimiters, with the UI summary/questions JSON after it, so the quote-heavy
sheet never has to survive JSON escaping.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

# Production analyser settings (template_manager.analyze_examples_to_skill_sheet), unchanged.
ANALYSER_SETTINGS = {
    "temperature": 0.8,
    "top_p": 0.95,
    "max_tokens": 40960,
    "extra_body": {"disable_reasoning": False, "clear_thinking": False},
}
# Repair is a constrained edit of an existing sheet, not authorship: low temperature.
REPAIR_SETTINGS = {
    "temperature": 0.3,
    "top_p": 0.95,
    "max_tokens": 40960,
    "extra_body": {"disable_reasoning": False, "clear_thinking": False},
}

SHEET_OPEN, SHEET_CLOSE = "<<<SKILL_SHEET", "SKILL_SHEET>>>"

GRAMMAR = """## THE SHEET GRAMMAR

The sheet mixes two kinds of line.
- UNIT LINES: one item per line, starting with the bare UPPERCASE KEYWORD from the list below (optionally preceded by "- "). No other bullets, no numbering, no bold, no backticks around a unit line. Code parses these lines; a malformed unit line breaks the sheet.
- PROSE LINES: everything else. Prose carries the radiologist's voice and passes through to the report writer untouched. A prose line never starts with a word written in capitals, abbreviations included; start it with a capitalised ordinary word ("Opening:", "Order:", "Abnormal pattern:", "The ...") or a lowercase word.
- The sheet is the finished document only: no notes to yourself, corrections or commentary inside it.
- Free-prose blocks are exactly these "## " titles: Scan Context, Voice, Impression Construction, Measurement and Grading, Reference Values, Incidental Findings, Domain Rules, Open Questions. Use these titles word for word.
- Outside the free-prose blocks (Report Structure, Report-wide, every Paragraph block), prose states no absence in any form: no "No ...", "There is no ...", "Without ...", "Absent ...", "Nil ...", "Negative for ...", "<x> is absent", not even in brackets or as a bare quoted line; that breaks the sheet. Every absence the radiologist writes is a NEGATIVE unit. A quoted exemplar quotes the abnormal, interpretive or recommendation wording only: cut the quote before any negative sentence that follows it in the example.
- Prose may describe how wording varies with what is found ("when present, the maximal diameter is given first"): that is voice guidance. A prose line with such a conditional never also mentions an absence.
- Every prose line under a paragraph starts with its label ("Opening:", "Order:", "Abnormal pattern:", "Interpretive phrasing:", "Recommendation phrasing:", "Measurement:"); no bare quoted lines. No prose line starts with a word that is also a keyword (Normal, Negative, Fixed, Term, Rule, Section, Covers), in any letter case.

Quoting: unit text and exemplars go in straight double quotes ("..."). Quoted text is never empty and never contains a double quote; use single quotes inside it if needed. No curly quotes. Quoted text is copied from the example reports word for word; where a value varies between studies, put a named slot in curly braces in its place ({value}, {measurement}, {laterality}, {date} ...). Never paraphrase quoted text.

### Report structure (exactly one block)

## Report Structure
SECTION <NAME> | header: none | role: <role>
SECTION <NAME> | header: "<heading exactly as written in the reports>" | role: <role>

- One SECTION line per top-level section, in the order the sections appear in the reports.
- <NAME>: uppercase words (letters, spaces, "/" and "&"). Use the visible heading in capitals when the reports show one, else a short descriptive uppercase name.
- header: the heading text exactly as it appears on its own line in the reports (including any trailing colon), or none when the section's content appears without a visible heading.
- <role> is one of: findings | impression | history | technique | comparison | other. A report has at least one findings section and at least one impression section (the concluding section, whatever the reports call it).

### Paragraphs

## Paragraph: <name> (<SECTION NAME>)

- The heading is exactly "## Paragraph: " then the name then the section NAME in round brackets, nothing after it. <SECTION NAME> is exactly a NAME from a SECTION line.
- <name> is the paragraph's visible heading as written in the reports (without its trailing colon) when it has one, else a short descriptive name.
- Every line below the heading belongs to that paragraph until the next line starting with "## " ("### " subheadings stay inside it).
- Give every section at least one paragraph, in report order; a section with no internal divisions has one paragraph named after the section.

## Report-wide
- Holds TERM lines, LIST_MISSING, and context rules that act on a whole section (SUPPRESS_SECTION, SUPPRESS_HEADERS). A non-TERM unit here ends with "| section: <NAME>" after its last quote. Nothing else goes here.

### Unit keywords (template-intrinsic units only)

COVERS ["<structure>" | "<structure>" | ...]
  Exactly one in every paragraph of a findings-role section, as the first unit line under its heading; never in a paragraph of any other section (impression, history, technique, comparison, other). Items are separated by " | " (a straight bar with a space each side), each in its own double quotes; never commas between items. Every anatomical structure, organ, compartment or measured element this paragraph reports, in plain words, in the order the paragraph covers them, including structures the examples mention only when abnormal. Anatomical structures only: never a finding, disease, pathology, abnormality or appearance name; name the place a finding would be reported in, not the finding. Another analyser places case-specific sentences into paragraphs by this list, so it must be complete for the paragraph's territory and must not list structures another paragraph reports.
NORMAL [<structure>] "<text>"
  The sentence the radiologist writes to state that one named structure (or group) is normal. One per structure. Always with the bracketed [<structure>]. Exactly ONE sentence per NORMAL line (one full stop, at the end): where the example follows a normal statement with a negative sentence ("<structure> is normal. No <thing>."), the normal sentence is the NORMAL and the negative sentence is its own NEGATIVE line; never join them in one quote.
NEGATIVE "<text>"
  A routine negative the radiologist writes in every normal study of this type (the standard sweep), one per sentence as written. No [label] and never a WHEN: a negative that depends on what was performed is an unconditional NEGATIVE plus a context RULE that SUPPRESSes or REPLACEs it.
FIXED "<text>"
  Verbatim text that never depends on the patient's state: what was performed and how, standard wording, field labels followed by a {slot} ("<Label>: {value} <unit>"). A statement that could be false for a different patient is never FIXED. Impression sentences are never FIXED.
TERM PREFER "<term>"
TERM AVOID "<term>"
  A term is a word or short phrase, not a sentence. PREFER: a distinctive term the radiologist uses consistently where a common synonym exists, found at least twice across the examples. AVOID: only a variant that actually appears in the examples and that their predominant usage replaces. At most six TERM lines in the sheet; ordinary anatomical or descriptive words are not terms. Few and distinctive beats many.
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["<item>" | "<item>" | ...] AT TOP
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["<item>" | "<item>" | ...] AT END
  Values expected in every report of this type, flagged when the dictation leaves them out. Use it when an example shows a list of values not provided (under any label), or contains unfilled placeholders (curly-brace slots or blank values), or when every example states the same set of measured values. Items are short plain names of every such value, each expected in EVERY report of this type regardless of findings: an item carries no condition or qualifier ("if", "when", "where applicable", "if present", "for <finding>"), and a value that only applies when some finding is present is not an item. At most one per sheet, under ## Report-wide.
RULE WHEN [context: <statement>] <EFFECT>
  Study-level circumstances only: what was performed or not, the protocol or phases acquired, technical limitation, prior imaging available or not. <statement> names the circumstance in plain words with at least two content words ("context: <named part of the study> was not performed", "context: prior <modality> imaging is available for comparison"). Effects:
  REPLACE "<target>" WITH "<text>"   (<target>: the exact quoted text of a NORMAL, NEGATIVE or FIXED line in the same paragraph)
  SUPPRESS "<target>"
  USE "<text>"
  SUPPRESS_SECTION <NAME>            (under ## Report-wide, with "| section: <NAME>"; only when an example report actually omits that section and shows the visible reason for it)
  SUPPRESS_HEADERS                   (under ## Report-wide, with "| section: <NAME>")
  Every quoted text is taken from an example report word for word, with {slots}.

NOT in this sheet (another analyser handles them per case; writing them breaks the sheet): any RULE conditioned on findings or history (other than LIST_MISSING), APPEND, INSERT, ORDER, SUPPRESS NEGATIVES, any NEGATIVE ... WHEN, IF_PRESENT, "IF [", "THEN". How this radiologist words a finding, an interpretation or a recommendation is captured as quoted exemplars in the paragraph's prose instead."""

SHEET_LAYOUT = """## SHEET LAYOUT (in this order)

# Skill Sheet: <descriptive name>

## Scan Context
Prose: modality and scan type; technique, phases or sequences; clinical setting and the typical clinical question.

## Voice
Prose: the writing voice across the report: sentence length and rhythm, how paragraphs open in normal and abnormal studies, how findings are sequenced and qualified, hedging vocabulary, signature phrases (quoted).

## Report Structure
SECTION lines.

## Report-wide
TERM lines; LIST_MISSING; section-level context rules.

## Paragraph: <name> (<SECTION NAME>)
One block per paragraph, in report order, covering every section. Each block holds, in this order:
COVERS ["..." | ...]   (findings-role sections only)
Opening: how the paragraph opens (quote the opening words of a normal and of an abnormal example).
Order: the sequence of structures and elements; an element that appears only sometimes is marked "(optional)".
Abnormal pattern: "<quoted sentence>" — one line per distinct way pathology is described in this paragraph across the examples; give several (every distinct one the examples show, up to five), each quoted word for word with {slots} for values. Quote the abnormal wording only, never a negative sentence.
Interpretive phrasing: "<quoted clause>" — how the radiologist attributes cause, significance or likelihood here (every example of it, quoted).
Recommendation phrasing: "<quoted clause>" — any recommendation or advice worded in this paragraph (quoted).
Measurement: how values and sizes are written here (quoted).
then its FIXED, NORMAL and NEGATIVE lines in the order they appear in the reports, then any context RULE lines.
Omit a prose line kind the examples give nothing for; never invent an exemplar. The impression section's paragraph holds its prose (opening, numbering, sentence pattern, quoted exemplars) and units only for fixed or context-dependent wording.

## Impression Construction
Prose (### subheadings allowed): the full impression of every example quoted verbatim, keeping its line breaks (each numbered or separate item on its own line, as the example lays it out; never joined onto one line); sentence construction pattern; inclusion logic (which findings were promoted from the findings sections and which stayed there; the threshold); sentence grouping and count; every recommendation phrase quoted, and how recommendations are integrated; the normal-study impression quoted; restatement of measurements and grades.

## Measurement and Grading
Prose: how measurements sit in sentences (quoted), grading systems used and when, explicit numeric thresholds and the language for each tier.

## Reference Values
Prose list of reference values and thresholds the radiologist explicitly wrote as declared normal ranges or cutoffs, with units. Do not infer thresholds from a value described with a qualifier; flag those as [NEEDS CLARIFICATION]. This list is the sole authority for reference values.

## Incidental Findings
Prose: where incidental findings are placed, how they were described (quoted), the inclusion threshold, how they reach the impression.

## Domain Rules
Prose: any other always/never conventions specific to this radiologist and scan type, each illustrated with a quoted phrase.

## Open Questions
Prose list of [NEEDS CLARIFICATION] items the examples cannot settle."""

ANALYSER_SYSTEM_PROMPT = f"""You are an expert radiology reporting analyst. Your task is to reverse-engineer a radiologist's reporting style from their example reports and produce a Skill Sheet: a construction manual that lets an AI write reports indistinguishable from this radiologist's own work.

A Skill Sheet has two layers:
1. STRUCTURE and TEMPLATE UNITS: the sections, paragraphs, the structures each paragraph covers, and the items that are the same for every patient of this scan type (normal-state sentences, the routine negative sweep, fixed text, terminology, expected values, study-level context rules). These are unit lines in a strict grammar that code parses.
2. CONSTRUCTION VOICE: how this radiologist thinks and writes within that structure: paragraph openings, ordering, and many quoted exemplars of how they describe pathology, interpret it and recommend, plus how they build the impression. This is their cognitive fingerprint, written as prose the report writer imitates.

The sheet is the template for every future case. Case-dependent clinical reasoning (which negatives matter for a particular finding or clinical question, what to recommend for a particular finding) is produced separately for each case by another analyser; do not encode it as units here. Capture this radiologist's way of wording such things as quoted exemplars in the voice prose.

Both layers must be grounded in the examples. Quote actual text for every unit and every exemplar. Do not invent units or wording not evidenced in the reports.

IMPORTANT: A Global Style Guide already covers universal rules (British English, impersonal voice, terminology consistency, section boundaries, consolidation, measurement conventions). Do not re-extract these. Focus only on what is specific to this radiologist and this scan type.

## DERIVING THE SHEET FROM THE EXAMPLES

Compare the examples with each other, paragraph by paragraph.
- Sections and paragraphs: the headings and paragraph breaks the reports show, in their order.
- COVERS: for each paragraph, every structure it reports in any example, normal or abnormal.
- NORMAL and NEGATIVE: what the radiologist writes about each structure when it is normal, and what they routinely state as absent. A sentence that recurs across examples (allowing for varying values, which become {{slots}}) is a unit. Quote one representative wording per unit. A negative written only beside a particular finding is not routine and is left out of the sheet: the per-case analyser supplies such negatives.
- FIXED: text that recurs word for word and never depends on the patient's state.
- Voice exemplars: every distinct abnormal description, interpretive clause and recommendation in a paragraph, quoted with {{slots}} for values. An exemplar quotes positive, interpretive or recommendation wording only: never a negative sentence, and the quote stops before any negative sentence that follows it. Where examples differ in how a paragraph is built, describe the variation in the Opening/Order prose.
- LIST_MISSING: the values the radiologist expects in every report of this type, unconditionally.
- TERM: only distinctive terms seen at least twice; at most six.
- SUPPRESS_SECTION: only where an example omits the section and the reason is visible in that example.
- Context rules: where examples differ because of what was performed, the protocol, a technical limitation or prior imaging, write the context RULE that produces the variant wording, quoting it.

Parameter placeholders: where a field's value varies across studies but the field itself is invariant, keep the field and put a named slot in curly braces in place of the value.

{GRAMMAR}

{SHEET_LAYOUT}

Where something cannot be determined from the examples alone, flag it under Open Questions as [NEEDS CLARIFICATION] so it can be raised as a question."""


SUMMARY_SPEC = """{
  "summary": {
    "structure": {
      "sections": [
        { "name": "<SECTION NAME>", "paragraphs": ["short description of paragraph 1", "short description of paragraph 2", "..."] },
        { "name": "<SECTION NAME>", "paragraphs": [] }
      ]
    },
    "voice": {
      "description": "one short sentence (under 12 words) describing the writing voice",
      "phrases": ["quoted signature phrase 1", "quoted signature phrase 2", "quoted signature phrase 3"]
    },
    "conventions": {
      "rules": [
        { "title": "Short rule title (3-6 words)", "detail": "One sentence explanation, may include a quoted example." },
        { "title": "...", "detail": "..." }
      ]
    },
    "impression": {
      "flow": ["Step 1 noun", "Step 2 noun", "Step 3 noun"],
      "detail": "One short sentence describing how the impression is constructed."
    }
  },
  "questions": [
    { "question": "<clarifying question>", "suggestions": ["<answer option>", "<answer option>"] }
  ]
}"""


def analyser_user_prompt(examples: List[Dict[str, str]], scan_type: str, protocol_notes: str = "") -> str:
    """Production's user prompt (examples, protocol notes, summary/questions contract), with the sheet
    returned between delimiters before the JSON."""
    examples_text = ""
    for i, ex in enumerate(examples, 1):
        label = ex.get("label") or f"Example {i}"
        examples_text += f"\n\n### {label}\n```\n{ex.get('content', '').strip()}\n```"
    notes = ""
    if protocol_notes.strip():
        notes = (
            "\n\n**Authoritative context from the radiologist** — treat as ground truth. These notes take precedence "
            "over inferences drawn from the examples alone. They may describe the clinical purpose of this scan type "
            "(use it to shape Scan Context, Impression Construction and what gets emphasised) or technical protocol "
            "variations the examples cannot reveal (use them to decide which text is FIXED and which needs {slots}). "
            f"Apply each piece of context wherever it is relevant.\n\nNotes:\n{protocol_notes.strip()}\n"
        )
    return f"""Analyse these example radiology reports for scan type: **{scan_type}**
{notes}{examples_text}

Answer in exactly two parts.

PART 1: the complete Skill Sheet as plain markdown, following the sheet layout and grammar above, between these delimiter lines (each on its own line, nothing else on it):
{SHEET_OPEN}
# Skill Sheet: ...
...
{SHEET_CLOSE}

PART 2: after the closing delimiter, one JSON object with exactly two keys, "summary" and "questions":

{SUMMARY_SPEC}

Rules for the summary (rendered as visual hierarchy in the UI; terse and scannable):
- structure.sections: every top-level section in report order, matching the SECTION lines. Paragraphs is the list of internal paragraph descriptions within each section (empty list if none). Each is a short noun phrase (under 10 words).
- voice.description: one terse sentence. No "This template" or "This radiologist" framing — just adjectives and tone descriptors.
- voice.phrases: 3-5 verbatim quoted phrases from the example reports that capture the signature voice.
- conventions.rules: 4-6 of the most distinctive scan-specific rules. Title is a short label, detail is one sentence.
- impression.flow: 2-4 nouns describing the construction sequence.
- impression.detail: one short sentence about sentence count, grouping, recommendation integration.
- questions: exactly 3 objects, each with "question" and "suggestions" (2-3 short clickable answer options). Target the most impactful Open Questions or where examples were ambiguous. Suggestions are concrete, specific answers. Do not ask about things clearly evidenced in the reports."""


def split_answer(raw: str) -> Dict[str, Optional[object]]:
    """{"skill_sheet", "summary", "questions", "json_error"} from a delimited answer. The sheet is taken
    between the delimiters (a missing closing delimiter takes the rest up to the JSON); the JSON after it
    is parsed leniently and its failure never loses the sheet. No opening delimiter -> ValueError."""
    start = raw.find(SHEET_OPEN)
    if start < 0:
        raise ValueError("no skill-sheet delimiter in the analyser answer")
    body = raw[start + len(SHEET_OPEN):]
    end = body.find(SHEET_CLOSE)
    if end >= 0:
        sheet, tail = body[:end], body[end + len(SHEET_CLOSE):]
    else:
        brace = re.search(r"\n\{\s*\n?\s*\"summary\"", body)
        sheet, tail = (body[:brace.start()], body[brace.start():]) if brace else (body, "")
    out: Dict[str, Optional[object]] = {"skill_sheet": sheet.strip("\n").strip(), "summary": None,
                                        "questions": None, "json_error": None}
    m = re.search(r"\{[\s\S]*\}", tail)
    try:
        data = json.loads(m.group()) if m else {}
        out["summary"], out["questions"] = data.get("summary"), data.get("questions")
        if not m:
            out["json_error"] = "no JSON after the sheet"
    except ValueError as e:
        out["json_error"] = f"{type(e).__name__}: {e}"[:300]
    return out


REPAIR_SYSTEM_PROMPT = f"""You correct lint errors in a radiology report skill sheet. The sheet is written in a strict line grammar that code parses; a parser has listed the lines it could not accept. Fix exactly those problems and return the complete corrected sheet.

- Change only the flagged lines, plus whatever else the fix strictly needs (a missing COVERS line, a SECTION line a paragraph heading refers to). Every line not listed is returned character for character, in place, even if you would word it differently.
- Keep the meaning and the quoted wording. Never invent new text or units.
- A unit not allowed in this sheet (a findings- or history-conditioned RULE, APPEND, INSERT, ORDER, SUPPRESS NEGATIVES) becomes a prose exemplar line in the same paragraph that keeps its quoted wording: "Abnormal pattern:", "Interpretive phrasing:" or "Recommendation phrasing:" followed by the quote, unless the quoted wording is a negative, in which case the line is deleted. An IF_PRESENT line is deleted (it is case-dependent). A NEGATIVE ... WHEN loses its WHEN when the negative is routine; otherwise it is deleted (it is case-dependent).
- A COVERS line outside a findings-role section is deleted; a COVERS item naming a finding rather than a structure is deleted.
- Prose that states an absence (in any form: "No ...", "There is no ...", "Without ...", "Absent ...", "Nil ...", "Negative for ...", "<x> is absent", bracketed, or a bare quoted negative line) becomes a NEGATIVE line with the same wording when it is a routine negative, and is otherwise deleted. A conditional prose line that also mentions an absence is rewritten without the absence (or deleted).
- A prose line starting with a keyword word (Normal, Negative, Fixed, Term, Rule, Section, Covers) is reworded to start with its label ("Opening:", "Abnormal pattern:" ...).
- A malformed COVERS line is rewritten as COVERS ["<structure>" | "<structure>"], items separated by " | ". A findings paragraph without COVERS gets one: the structures its units and prose report, as the first unit line under the heading.
- A condition without a subject names the circumstance it is about.

{GRAMMAR}

Return only the corrected sheet as plain markdown: no JSON, no delimiters, no code fences, no commentary before or after it."""


def numbered(sheet: str) -> str:
    return "\n".join(f"L{i}| {line}" for i, line in enumerate(sheet.splitlines(), 1))


def repair_user_prompt(sheet: str, errors: List[Dict]) -> str:
    """The sheet with line numbers, then the numbered lint errors (line, reason, detail, offending text)."""
    lines = []
    for k, e in enumerate(errors, 1):
        get = e.get if isinstance(e, dict) else (lambda key, d=None, e=e: getattr(e, key, d))
        line, reason, text, detail = get("line", 0), get("reason", ""), get("text", ""), get("detail", "")
        where = f"L{line}" if line else "sheet"
        lines.append(f"{k}. {where}: {reason}" + (f" ({detail})" if detail else "") + (f' — "{text}"' if text else ""))
    return (
        "SHEET (line numbers are for reference only; do not include them in your answer):\n"
        f"{numbered(sheet)}\n\nLINT ERRORS:\n" + "\n".join(lines) + "\n\nReturn the complete corrected sheet."
    )


def strip_fences(text: str) -> str:
    """The repair answer without a wrapping code fence, delimiters or stray line-number prefixes."""
    t = text.strip()
    if SHEET_OPEN in t:
        t = t.split(SHEET_OPEN, 1)[1].split(SHEET_CLOSE, 1)[0].strip()
    m = re.fullmatch(r"```[a-z]*\n([\s\S]*?)\n```", t)
    if m:
        t = m.group(1)
    if all(re.match(r"L\d+\| ", ln) for ln in t.splitlines() if ln.strip()):
        t = "\n".join(re.sub(r"^L\d+\| ", "", ln) for ln in t.splitlines())
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Conversion of a stored (legacy-format) sheet into the lean grammar (plan G6, lab only)
# ─────────────────────────────────────────────────────────────────────────────

# Same model and settings as the lean analyser (scripts/template_sheet_convert.py passes ANALYSER_SETTINGS).
TEMPLATE_SHEET_CONVERT_PROMPT = f"""You convert a radiology report Skill Sheet from an older free-form layout into the lean sheet grammar below. The old sheet was written for one radiologist and one scan type, and the radiologist has been reporting with it. Your job is a faithful translation, not a rewrite: the new sheet must make the report writer produce the same reports in the same voice, with the same sections, paragraphs, order, routine negatives and fixed text.

## YOUR INPUTS

1. OLD SHEET: the authority. Everything it says about structure, wording, negatives, fixed text, terminology, measurements, reference values, impression construction and conventions is carried over.
2. REPORTS: up to five recent reports made with the old sheet (some edited by the radiologist). They are evidence of how the sheet's instructions came out in practice: the headings and paragraph breaks as printed, the order of sentences, and further wording for the voice exemplars. They never add a unit: every NORMAL, NEGATIVE, FIXED, TERM, LIST_MISSING and RULE comes from the old sheet. Where a report and the old sheet word the same unit differently, keep the old sheet's wording. A sentence that recurs in the reports but is not in the old sheet (a negative, a normal statement, fixed wording) is quoted as an [NEEDS CLARIFICATION] item under Open Questions, never written as a unit.
3. COVERAGE LIST (when given): the structures stored with the template. Use it to complete COVERS lines, placing each structure in the paragraph that reports it.

## WHAT TO CARRY OVER, AND WHERE IT GOES

- Sections and their headers (as the old sheet specifies them, or as printed in the reports) become SECTION lines, in the same order. Keep a section the old sheet declares even if a report omits it.
- Every paragraph, block or per-section entry of the old sheet becomes a "## Paragraph:" block, in the old sheet's order, keeping its name. Do not merge or split paragraphs; do not drop one.
- A paragraph with its own visible heading (a sub-heading inside a section, as the old sheet or the reports show it) keeps that heading: the paragraph name is the heading without its trailing colon, and the paragraph's first prose line is an "Opening:" that quotes the heading line exactly as printed, including its colon and letter case, and says the paragraph starts with it. A paragraph without a visible heading says nothing about one.
- COVERS names the structures a paragraph reports. A paragraph of a findings section that reports no structure of its own (procedure text, acquisition parameters, a score) lists the measured elements it states (the score, the parameters) and never repeats a structure another paragraph covers.
- Mandatory fields, field ordering and listed structures become the paragraph's COVERS line (structures only) and its "Order:" prose, in the old order. An element present only sometimes is marked "(optional)" in the Order line.
- Normal patterns become NORMAL lines, word for word. A normal pattern that is one sentence stays whole as one NORMAL, even when it carries a negative clause; but a sentence that opens with an absence word ("No ...", "There is no ...", "Nil ...") is a NEGATIVE wherever the old sheet lists it. A normal pattern of several sentences is split at its full stops: each normal sentence is its own NORMAL, each negative sentence its own NEGATIVE.
- Mandatory negatives, routine negatives and negative-finding lists become NEGATIVE lines, word for word, once each in the paragraph they belong to. Where the old sheet offers alternative wordings of one negative, keep the first as the NEGATIVE and quote the alternative in the Domain Rules prose.
- Fixed blocks become FIXED lines, word for word, with their {{slots}}. Alternative wordings of one fixed statement (chosen by what was performed, prior imaging and the like) are ONE unit: the default wording as the FIXED line (or, where the old sheet gives no default, no FIXED line), and each alternative as a context RULE that REPLACEs the default or is a USE; an alternative is never a FIXED line of its own, because every FIXED line is printed in every report. A RULE's quoted target is the exact text of the unit it acts on, full stop included. Verification markers on them (such as [NEEDS VERIFICATION]) leave the quote and become an Open Questions item that names the block.
- A wording choice that depends on the study itself (what was performed, protocol, phases or sequences, prior imaging available or not, a technical limitation of the acquisition) becomes a context RULE quoting both wordings from the old sheet. A suppression or replacement the old sheet ties to a limitation of the study (artefact, incomplete coverage, a part not performed) is such a context RULE, even when the old sheet names the cause of the limitation as something seen: its statement names the limitation.
- Terminology: at most six TERM lines, chosen from the old sheet's preferred and suppressed terms (the most distinctive single terms first). Every other preferred phrase or substitution goes into the Voice prose, quoted, so nothing is lost. A suppressed term with a stated replacement keeps that replacement in the prose ("<avoided>" is written "<preferred>").
- Values the old sheet itself says must appear in every report, or must be listed or flagged when not provided, become the one LIST_MISSING line. Never infer a LIST_MISSING from {{slots}} alone, and never list a value the old sheet says to leave out when it is not given.
- Conditional wording keyed on what is found (conditional fields, IF ... THEN appends, interpretive-clause rules, finding-specific phrasing, multi-clause fields) becomes quoted exemplars in the paragraph's prose: "Abnormal pattern:", "Interpretive phrasing:", "Recommendation phrasing:" or "Measurement:", word for word with {{slots}}. Keep the old sheet's description of how wording varies as an "Order:" or "Opening:" note when it is voice guidance ("when present, ... is given first").
- Exemplars: every exemplar the old sheet gives is kept, word for word. Add exemplars from the reports only for a way of wording that the old sheet's exemplars do not already show, up to five lines per prose label per paragraph in total (the old sheet's first).
- A negative or suppression the old sheet ties to a particular finding is not carried as a unit: the per-case analyser now supplies case-dependent negatives. Its positive wording, if any, becomes an exemplar; its negative wording is dropped and the drop is listed in your accounting (PART 2).
- Impression construction (quoted examples, numbering, sentence pattern, inclusion logic, recommendation integration, normal-study impression, restatement rules) goes into the "## Impression Construction" block with every quoted example kept verbatim and laid out line by line as written. The impression section's paragraph block holds only its Opening and Order lines and any FIXED or context RULE units; the quoted impressions live in "## Impression Construction", never in the paragraph block.
- Measurement and grading, reference values, incidental findings, domain rules: the same-named prose blocks, keeping every value, threshold and quoted phrase. A rule that tells the writer to always state something (a sentence that must appear in every report) stays a unit (NEGATIVE, NORMAL or FIXED) as well as a Domain Rules line.
- Scan context, clinical setting and any statement of what the report does or does not cover go into "## Scan Context", saying only what the old sheet says (no typical clinical question unless the old sheet states one).
- Anything the old sheet marks as uncertain, and any conflict between the old sheet and the reports, goes into "## Open Questions" as [NEEDS CLARIFICATION].

## NEVER

- Never invent: every quoted text in the new sheet (unit or exemplar) is copied from the old sheet or from a report, word for word, with {{slots}} only where a value varies. Never write a new negative, normal sentence, fixed text, exemplar, threshold or rule. Never merge two old sentences into a new one, or reword one, to fit the grammar: a NORMAL, NEGATIVE or FIXED quote is a sentence the old sheet contains, letter for letter.
- Never drop a section, paragraph, routine negative, fixed text, threshold, reference value or quoted impression example of the old sheet. What cannot be a unit becomes prose; only finding-specific negatives and suppressions are dropped, and each drop is listed.
- Never change the order of sections or paragraphs, or the order of units within a paragraph, from the old sheet (or, where the old sheet is silent, the reports).

{GRAMMAR}

{SHEET_LAYOUT}

## ANSWER FORMAT

Answer in exactly two parts.

PART 1: the complete converted Skill Sheet as plain markdown, between these delimiter lines (each on its own line, nothing else on it):
{SHEET_OPEN}
# Skill Sheet: ...
...
{SHEET_CLOSE}

PART 2: after the closing delimiter, one JSON object accounting for the old sheet, with exactly these keys:
{{"accounting": [{{"old": "<old sheet heading or item, short>", "new": "<where it went in the new sheet: paragraph or block name and unit kind or prose label>"}}],
  "dropped": [{{"old": "<quoted old text>", "reason": "<one short reason>"}}]}}
Every heading and every quoted negative, fixed text and normal pattern of the old sheet appears in "accounting" or "dropped"."""


def convert_user_prompt(old_sheet: str, scan_type: str, reports: List[Dict[str, str]],
                        coverage: Optional[List[str]] = None) -> str:
    """The old sheet, the voice-evidence reports (labelled, fenced) and the stored coverage list."""
    parts = [f"Convert the Skill Sheet for scan type: **{scan_type}**", "", "## OLD SHEET", "```", old_sheet.strip(), "```"]
    if reports:
        parts += ["", "## REPORTS"]
        for i, r in enumerate(reports, 1):
            parts += ["", f"### {r.get('label') or f'Report {i}'}", "```", (r.get("content") or "").strip(), "```"]
    if coverage:
        parts += ["", "## COVERAGE LIST", " | ".join(str(c) for c in coverage)]
    parts += ["", "Return PART 1 (the sheet between the delimiters) then PART 2 (the accounting JSON)."]
    return "\n".join(parts)


def split_conversion(raw: str) -> Dict[str, object]:
    """{"skill_sheet", "accounting", "dropped", "json_error"} from a conversion answer. The sheet is taken
    between the delimiters exactly as split_answer does; a broken accounting JSON never loses the sheet.
    No opening delimiter -> ValueError."""
    start = raw.find(SHEET_OPEN)
    if start < 0:
        raise ValueError("no skill-sheet delimiter in the conversion answer")
    body = raw[start + len(SHEET_OPEN):]
    end = body.find(SHEET_CLOSE)
    if end >= 0:
        sheet, tail = body[:end], body[end + len(SHEET_CLOSE):]
    else:
        brace = re.search(r"\n\{\s*\n?\s*\"accounting\"", body)
        sheet, tail = (body[:brace.start()], body[brace.start():]) if brace else (body, "")
    out: Dict[str, object] = {"skill_sheet": strip_fences(sheet.strip("\n").strip()), "accounting": None,
                              "dropped": None, "json_error": None}
    m = re.search(r"\{[\s\S]*\}", tail)
    if not m:
        out["json_error"] = "no JSON after the sheet"
        return out
    try:
        data = json.loads(m.group())
        out["accounting"], out["dropped"] = data.get("accounting"), data.get("dropped")
    except ValueError as e:
        out["json_error"] = f"{type(e).__name__}: {e}"[:300]
    return out
