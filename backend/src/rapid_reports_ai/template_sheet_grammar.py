"""Template skill-sheet grammar v1: code parses a grammar sheet into SheetStructure (spec
2026-10-01-template-sheet-grammar-design).

Prose is the radiologist's voice and passes through untouched; every unit the brief reconciles against a
dictation is a keyword-led line. The parser is pure and deterministic, and fails closed: any lint error
leaves the structure unusable (the raw path generates) and records the lint errors on it. Grammar
structures are the only ones generation trusts (template_sheet_structure.fresh); they are parsed
synchronously on save. A sheet not in grammar form (no "## Report Structure" line) stays on the raw
path until converted; the LLM extractor is lab-only (RR_SHEET_EXTRACTOR) and never trusted.

Modes. parse_sheet(sheet, mode=...):
- "template" (default; the save path): a stored template sheet in the LEAN grammar (spec
  2026-10-01-template-two-phase "Lean template sheet"). Findings- or history-conditioned RULEs (except
  LIST_MISSING, whose WHEN is the fixed findings statement), NEGATIVE … WHEN [findings|history: …],
  IF_PRESENT, context RULEs with an effect other than REPLACE/SUPPRESS/USE/SUPPRESS_SECTION/
  SUPPRESS_HEADERS, and every case unit are lint errors. Every findings-role paragraph needs one COVERS.
- "master": a template sheet plus the Phase-1 case units (the master sheet). Lean rules as "template";
  case units allowed; exactly one QUESTION.
- "v1": grammar v1 as first specified (findings rules, IF_PRESENT; no case units; COVERS optional).
  Lab and tests only: kept so the brief's v1 rule handling stays testable. Never used on save.

Unit lines (optional indentation and an optional "- " bullet before the keyword):

    SECTION <NAME> | header: none | role: <role>              (only in the "## Report Structure" block)
    SECTION <NAME> | header: "<as written>" | role: <role> [| alt: "<other header>"]… [| optional: yes]
    NORMAL [<structure>] "<text>"
    NEGATIVE "<text>"  [WHEN [<source>: <statement>]]
    FIXED "<text>"
    TERM PREFER "<term>" | TERM AVOID "<term>"
    IF_PRESENT [<finding>] "<negative>" (core|contextual)
    RULE WHEN [<source>: <statement>] <EFFECT>
    COVERS ["<structure>" | "<structure>" …]                  (one per paragraph)

Case units (master mode only):

    ## Case Deliberation                                        (one block, outside any paragraph)
    QUESTION "<clinical question>"
    DIFFERENTIAL [<name>] TIER triage|aetiology "<imaging discriminator>" VISIBLE yes|no|silent
    RECOMMEND <IMAGING|REFERRAL|MDT|TISSUE|CORRELATION> "<text>" WHEN [findings: <statement>]
    (inside paragraphs)
    NEGATIVE "<text>" TARGETS [<differential>] | origin: case   (TARGETS names a VISIBLE yes DIFFERENTIAL)
    IF_PRESENT [<finding>] "<negative>" (core|contextual) | origin: case

Headings (2026-10-01 retest extensions). A paragraph with its own visible sub-heading is
"## Paragraph: <name> (<SECTION>) | header: \"<sub-heading as printed>\"": the generator prints it on its own
line above the paragraph. A SECTION's "| alt: \"<header>\"" lists other headers the reports use for it (the
generator writes the primary one; alternatives only help parsing a report); "| optional: yes" marks a section
written only when the dictation has content for it (never the impression; it holds no NORMAL, NEGATIVE or FIXED).

Sections of a unit. Under "## Paragraph: <name> (<SECTION>)" a unit belongs to that paragraph and
section. Outside a paragraph a unit may name its section with a trailing "| section: <NAME>" (outside
quotes); without one, a unit under "## Report-wide" belongs to the FIRST findings-role SECTION of the
Report Structure, and a unit anywhere else is a lint error. TERM units are sheet-wide.

LIST_MISSING's WHEN statement is free text like any other (the canonical one is
"[findings: any listed value is not stated]"); it is parsed, not rewritten.

Fail-closed sweep. Every line that is not a unit line is checked:
- anywhere: a decorated or miscased unit (bullet "*", "1.", "–", ">", backticks, bold, zero-width or
  NBSP prefix, lowercase keyword) and a paragraph heading at the wrong level or malformed;
- in every section except the free-prose ones (FREE_PROSE_SECTIONS): a negative statement written as
  prose (it should be a NEGATIVE unit — the brief can only reconcile units), an error; and a conditional
  phrase outside quotes, a WARNING only (stored on the structure, never blocking: voice guidance
  legitimately says "when present, give the maximal diameter").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional, Tuple

from . import template_sheet_structure as tss
from .report_review import is_negative

# The keywords that open a unit line. Anything else starting with an uppercase word followed by
# `[`, `"` or WHEN is an unknown keyword-like line.
KEYWORDS = ("SECTION", "NORMAL", "NEGATIVE", "FIXED", "TERM", "IF_PRESENT", "RULE", "COVERS",
            "QUESTION", "DIFFERENTIAL", "RECOMMEND")
CASE_BLOCK_KEYWORDS = ("QUESTION", "DIFFERENTIAL", "RECOMMEND")  # only inside "## Case Deliberation"
CASE_BLOCK = "case deliberation"
Mode = Literal["template", "master", "v1"]
MODES = ("template", "master", "v1")
# Context rules a lean template keeps: what was performed, protocol, prior imaging availability.
CONTEXT_EFFECTS = ("replace", "suppress", "use", "suppress_section", "suppress_headers")
ROLES = ("findings", "impression", "history", "technique", "comparison", "other")
SOURCES = ("findings", "history", "context")

# Lint reasons. The first nine are the spec's list; the rest cover shapes the spec implies
# (a known keyword whose syntax is wrong, a section a unit names that is not in the structure, …).
UNKNOWN_KEYWORD = "unknown keyword-like line"
MALFORMED_QUOTES = "malformed quotes"
UNKNOWN_SOURCE = "unknown source"
NO_SUBJECT = "statement without subject"
UNKNOWN_PARAGRAPH_SECTION = "unknown section in a paragraph heading"
DUPLICATE_SECTION = "duplicate SECTION"
NO_SECTION = "unit outside any paragraph without section"
PROSE_CONDITIONAL = "conditional phrase in prose"  # a WARNING (lint_warnings), never an error
CONDITIONAL_NEGATIVE = "conditional negative in prose"  # a conditional that also states a negative: blocks
OLD_SYNTAX = "old IF [ syntax"
MALFORMED_UNIT = "malformed unit"
UNKNOWN_SECTION = "unknown section"
DECORATED_UNIT = "decorated or miscased unit"
MISLEVELLED_PARAGRAPH = "mis-levelled paragraph heading"
PROSE_NEGATIVE = "negative outside a NEGATIVE unit"
SECTION_OUTSIDE_STRUCTURE = "SECTION outside the Report Structure block"
DUPLICATE_STRUCTURE = "duplicate Report Structure block"
# lean template sheet + case units (spec 2026-10-01-template-two-phase)
NOT_LEAN = "unit not allowed in a template sheet"
CASE_IN_TEMPLATE = "case unit outside a master sheet"
MISSING_COVERS = "findings paragraph without COVERS"
DUPLICATE_COVERS = "second COVERS in a paragraph"
QUESTION_COUNT = "master sheet needs exactly one QUESTION"
DUPLICATE_CASE_BLOCK = "duplicate Case Deliberation block"
DUPLICATE_DIFFERENTIAL = "duplicate DIFFERENTIAL"
UNKNOWN_TARGET = "TARGETS names no DIFFERENTIAL"
# A case negative excludes its differential by silence only when this study would show it (policy 1):
# TARGETS naming a VISIBLE no / silent DIFFERENTIAL asks a negative the study cannot support.
UNSUPPORTED_TARGET = "TARGETS names a DIFFERENTIAL this study cannot show (VISIBLE no/silent)"
# An optional section is written only from dictated content: a stated unit there would force it.
OPTIONAL_SECTION_UNIT = "NORMAL, NEGATIVE or FIXED in an optional section"


@dataclass(frozen=True)
class LintError:
    line: int  # 1-based sheet line
    text: str  # the sheet line as written
    reason: str  # one of the reason constants above
    detail: str = ""


@dataclass
class GrammarResult:
    structure: tss.SheetStructure
    errors: List[LintError] = field(default_factory=list)
    warnings: List[LintError] = field(default_factory=list)  # stored, never blocking usable


# ── line shapes ──────────────────────────────────────────────────────────────

_BULLET = re.compile(r"^\s*(?:-\s+)?")
_HEADING = re.compile(r"^#{1,2}\s+(.*?)\s*$")  # "# " and "## " open a new context; "### " is prose
_PARAGRAPH = re.compile(r"^Paragraph:\s*(?P<name>.*?)\s*(?:\((?P<sec>[^()]*)\))?\s*$", re.I)
_OLD_IF = re.compile(r"\bIF\s*\[")
_KEYWORD_LIKE = re.compile(r"^([A-Z][A-Z_]+)\s*(?:\[|\"|WHEN\b)")
_FIRST_WORD = re.compile(r"^([A-Z][A-Z_]*)\b")
_CURLY = re.compile(r"[“”]")
_QUOTED = re.compile(r'"([^"]*)"|“([^“”]*)”')  # straight or curly double-quoted text

_NAME = r"[A-Z0-9][A-Z0-9 /&-]*?"
_Q = r'"([^"]+)"'
_COND = r"WHEN\s*\[([^\]]*)\]"
_SECTION_ATTR = re.compile(r"\s*\|\s*section:\s*([^\"]*?)\s*$")  # after the last quote only
_ORIGIN_ATTR = re.compile(r"\s*\|\s*origin:\s*([^\"|]*?)\s*$")  # after the last quote; before any section attr

_SECTION = re.compile(rf"SECTION\s+(?P<name>{_NAME})\s*\|\s*header:\s*(?:none|\"(?P<header>[^\"]+)\")"
                      r"\s*\|\s*role:\s*(?P<role>\w+)"
                      r"(?P<alts>(?:\s*\|\s*alt:\s*\"[^\"]+\")*)(?P<optional>\s*\|\s*optional:\s*yes)?\s*")
_ALT = re.compile(r'alt:\s*"([^"]+)"')
_PARAGRAPH_HEADER_ATTR = re.compile(r'\s*header:\s*"(?P<header>[^"]+)"\s*')
_UNITS = {
    "NORMAL": re.compile(rf"NORMAL\s*\[(?P<structure>[^\]]+)\]\s*{_Q}\s*"),
    "NEGATIVE": re.compile(rf"NEGATIVE\s*{_Q}(?:\s+{_COND})?(?:\s+TARGETS\s*\[(?P<targets>[^\]]+)\])?\s*"),
    "FIXED": re.compile(rf"FIXED\s*{_Q}\s*"),
    "TERM": re.compile(rf"TERM\s+(PREFER|AVOID)\s*{_Q}\s*"),
    "IF_PRESENT": re.compile(rf"IF_PRESENT\s*\[(?P<finding>[^\]]+)\]\s*{_Q}\s*\((core|contextual)\)\s*"),
    "RULE": re.compile(rf"RULE\s+{_COND}\s*(?P<effect>.*?)\s*"),
    "COVERS": re.compile(r"COVERS\s*\[(?P<items>[^\]]*)\]\s*"),
    "QUESTION": re.compile(rf"QUESTION\s*{_Q}\s*"),
    "DIFFERENTIAL": re.compile(rf"DIFFERENTIAL\s*\[(?P<name>[^\]]+)\]\s*TIER\s+(?P<tier>triage|aetiology)\s*{_Q}"
                               r"\s*VISIBLE\s+(?P<visible>yes|no|silent)\s*"),
    "RECOMMEND": re.compile(rf"RECOMMEND\s+(?P<tag>IMAGING|REFERRAL|MDT|TISSUE|CORRELATION)\s*{_Q}\s*{_COND}\s*"),
}
_ITEMS = re.compile(r'\s*"[^"]+"(?:\s*\|\s*"[^"]+")*\s*')
_EFFECTS: List[Tuple[str, re.Pattern]] = [
    ("replace", re.compile(rf"REPLACE\s*{_Q}\s*WITH\s*{_Q}")),
    ("suppress_paragraph_negatives", re.compile(r"SUPPRESS\s+NEGATIVES")),
    ("suppress", re.compile(rf"SUPPRESS\s*{_Q}")),
    ("append", re.compile(rf"APPEND\s*{_Q}")),
    ("use", re.compile(rf"USE\s*{_Q}")),
    ("insert_before", re.compile(rf"INSERT\s*{_Q}\s*BEFORE\s*{_Q}")),
    ("list_missing", re.compile(r"LIST_MISSING\s*\[([^\]]*)\]\s*AT\s+(TOP|END)")),
    ("suppress_section", re.compile(rf"SUPPRESS_SECTION\s+({_NAME})")),
    ("suppress_headers", re.compile(r"SUPPRESS_HEADERS")),
    ("order", re.compile(r"ORDER\s+(FIRST|LAST)")),
]
_PARAGRAPH_EFFECTS = {"suppress_paragraph_negatives", "order"}  # meaningless outside a paragraph

# Subject rule: a statement names what it is about — at least two content words once function words
# and report verbs ("is reported", "stated", "present") are set aside. "abnormal" fails;
# "abnormal ascending aorta dimensions are reported" passes.
_STOP = frozenset("""
a an the this that these those it its they them their there here
is are was were be been being has have had do does did will would can could may might should must
of in on at to for from by with without within into onto over under about as than then and or nor but
not no any all some each every either neither both other another such same
reported reports report stated states state described describes mentioned noted notes dictated
documented given seen shown present absent found identified recorded
""".split())

# Headings (exact "## <title>", case-insensitive) whose prose is free: the analyser's generator-guidance
# sections, not reconcilable units ("### " subheadings inside them stay free prose). Prose everywhere
# else (paragraphs, Report-wide, the Report Structure block, any other heading, text before the first
# "## ") is checked for conditionals and negatives.
FREE_PROSE_SECTIONS = ("scan context", "impression construction", "measurement and grading", "reference values",
                       "incidental findings", "domain rules", "open questions", "voice", "style", "terminology")

# Prose that states a condition outside quoted text should have been a RULE / NEGATIVE … WHEN.
# "if any" is exempt only as a closing idiom ("…, if any." / "(if any)").
_PROSE_COND = re.compile(
    r"\b(?:if|when|unless|whenever|wherever|where|provided|in\s+case|in\s+the\s+presence\s+of"
    r"|should\s+\w+\s+be|otherwise|depending\s+on|once|for\s+patients\s+with)\b", re.I)
_PROSE_COND_EXEMPT = re.compile(r"\bif\s+any\b(?=\s*(?:[,.)]|$))", re.I)

# Decoration a model may put before a unit keyword or a paragraph heading.
_INVISIBLE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_DECORATION = re.compile(r"^(?:[\s\-*+•–—>`#_]|\d+[.)])+")
_TOKEN = re.compile(r"^([A-Za-z_]+)(.*)$", re.S)
_PARAGRAPH_LIKE = re.compile(r"^paragraph\s*:", re.I)


def paragraph_heading(title: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """(name, section as written, sub-heading or None) of a "Paragraph: <name> (<SECTION>) [| header: \"…\"]"
    heading title (the text after "## "); None when the title is not a paragraph heading or its attribute is
    malformed. The shared reader for every module that walks paragraph headings."""
    head, bar, attr = title.partition("|")
    p = _PARAGRAPH.fullmatch(head.strip())
    if not p:
        return None
    header = None
    if bar:
        a = _PARAGRAPH_HEADER_ATTR.fullmatch(attr)
        if not a:
            return None
        header = a.group("header")
    return p.group("name"), (p.group("sec") or ""), header


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().upper()


def _content_words(statement: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", statement.lower()) if w not in _STOP and not w.isdigit()]


def _outside_quotes(text: str) -> str:
    return _QUOTED.sub(" ", text)


# A statement of absence. In prose it should be a NEGATIVE unit. Normal-state voice ("the ducts are not
# dilated") is not an absence statement and stays prose.
_ABSENCE_START = re.compile(r"^(?:No|There\s+is\s+no|There\s+are\s+no|Without|Absent|Nil|Negative\s+for)\b", re.I)
_ABSENCE_ANY = re.compile(
    r"\b(?:is|are)\s+absent\b"
    r"|^Free\s+of\b"  # "Free of X."
    r"|^Not\s+(?:seen|identified|demonstrated)\s*:"  # "Not seen: X."
    r"|^[^:]+:\s*(?:none|nil|not\s+(?:seen|identified|demonstrated))\s*\.?\s*$"  # "X: none." / "X: not seen."
    r"|\bnot\s+(?:seen|identified|demonstrated)\s*\.?\s*$",  # "X not seen." (at the end of the statement)
    re.I)
# A conditional line that also carries one of these cues states a negative under a condition: it should
# have been a NEGATIVE unit (or Phase-1 material), so it blocks instead of warning.
_QUOTED_NEG = re.compile(r"^\s*(?:No|There\s+is\s+no|There\s+are\s+no|Without)\b", re.I)
_NEG_CUE = re.compile(r"\b(?:no|without|absent|nil|negative\s+for)\b|\bnot\s+\w+ed\b", re.I)


def _negative_cue(plain: str) -> bool:
    quoted = [a or b for a, b in _QUOTED.findall(plain)]
    return any(_QUOTED_NEG.match(q) for q in quoted) or bool(_NEG_CUE.search(_outside_quotes(plain)))


def _states_absence(plain: str) -> bool:
    """A prose line written as an absence statement: "No X.", "There is no X.", "Without X.", "Absent X.",
    "Nil X.", "Negative for X.", "X is absent.", "Free of X.", "Not seen: X.", "X: none|nil|not seen.",
    "X not seen|identified|demonstrated.", also bulleted, bold, parenthesised or wholly quoted."""
    stated = plain.replace("**", "").strip()
    if stated[:1] in ('"', "“", "'"):
        stated = re.sub(r'["“”]', "", stated)
    else:
        stated = _outside_quotes(stated)
    stated = stated.strip().lstrip("('_ ").strip()
    return bool(_ABSENCE_START.match(stated) or _ABSENCE_ANY.search(stated) or is_negative(stated))


def _undecorate(line: str) -> str:
    """The line with invisible characters, NBSP and leading decoration (bullets, numbering, quote and
    heading marks, backticks, bold) removed."""
    s = _INVISIBLE.sub("", line).replace("\u00a0", " ")
    return _DECORATION.sub("", s).strip()


def _sweep(i: int, body: str, ctx: "_Ctx", err, warn) -> None:
    """Fail closed on a line that is not a unit line (at most one error and one warning per line)."""
    km = _KEYWORD_LIKE.match(body)
    if km:
        err(i, UNKNOWN_KEYWORD, km.group(1))
        return
    plain = _undecorate(body)
    if not plain:
        return
    tok = _TOKEN.match(plain)
    # "Normal-appearing …", "Normal: …", "Covers: …" (a keyword word in ordinary case followed by a hyphen
    # or colon) is a prose label, not a unit; "NORMAL [", "Normal \"" and any all-caps keyword still fail closed.
    prose_label = tok and not tok.group(1).isupper() and tok.group(2)[:1] in ("-", ":")
    if tok and not prose_label and tok.group(1).upper() in KEYWORDS and (
            tok.group(1).isupper() or re.search(r'["“”\[|]', tok.group(2))):
        err(i, DECORATED_UNIT, tok.group(1))
        return
    if _PARAGRAPH_LIKE.match(plain):
        err(i, MISLEVELLED_PARAGRAPH)
        return
    if ctx.kind == "free":
        return
    cm = _PROSE_COND.search(_PROSE_COND_EXEMPT.sub(" ", _outside_quotes(plain)))
    if cm:
        if _negative_cue(_PROSE_COND_EXEMPT.sub(" ", plain)):
            err(i, CONDITIONAL_NEGATIVE, cm.group(0).lower())
            return
        warn(i, PROSE_CONDITIONAL, cm.group(0).lower())
    if _states_absence(plain):
        err(i, PROSE_NEGATIVE)


@dataclass
class _Ctx:
    kind: str = "none"  # none | structure | paragraph | report_wide | case | free | other
    paragraph: str = ""  # paragraph id
    section: str = ""  # paragraph's section (canonical name, or as written when unknown)


_GRAMMAR_MARK = re.compile(r"^##\s+Report Structure\s*$", re.I | re.M)


def is_grammar_sheet(sheet: str) -> bool:
    """A sheet is in grammar form when it has a "## Report Structure" line."""
    return bool(_GRAMMAR_MARK.search(sheet or ""))


def parse_sheet(sheet: str, mode: Mode = "template") -> GrammarResult:
    """Parse a grammar sheet. Deterministic: the same sheet gives the same structure, errors and warnings
    (created_at aside). mode: "template" (a stored template sheet, lean grammar), "master" (template
    sheet + Phase-1 case units) or "v1" (lab/tests only; see the module docstring)."""
    if mode not in MODES:
        raise ValueError(f"unknown grammar mode {mode!r}")
    lines = (sheet or "").splitlines()
    errors: List[LintError] = []
    warnings: List[LintError] = []

    def err(i: int, reason: str, detail: str = "") -> None:
        errors.append(LintError(line=i, text=lines[i - 1] if i else "", reason=reason, detail=detail))

    def warn(i: int, reason: str, detail: str = "") -> None:
        warnings.append(LintError(line=i, text=lines[i - 1], reason=reason, detail=detail))

    # Pass 1: the Report Structure block, so paragraph headings and units may name any section.
    sections: List[tss.StructSection] = []
    by_name: Dict[str, str] = {}
    structure_blocks = 0
    in_structure = False
    section_lines = set()
    for i, raw in enumerate(lines, 1):
        h = _HEADING.match(raw)
        if h:
            in_structure = h.group(1).strip().lower() == "report structure"
            if in_structure:
                structure_blocks += 1
                if structure_blocks > 1:
                    err(i, DUPLICATE_STRUCTURE)
            continue
        first = _FIRST_WORD.match(_BULLET.sub("", raw, count=1))
        if first and first.group(1) == "SECTION":
            body = _BULLET.sub("", raw, count=1)
            section_lines.add(i)
            if not in_structure:
                err(i, SECTION_OUTSIDE_STRUCTURE)
                continue
            if _OLD_IF.search(raw):
                continue  # reported in pass 2
            if raw.count('"') % 2 or _CURLY.search(raw) or '""' in raw:
                err(i, MALFORMED_QUOTES)
                continue
            m = _SECTION.fullmatch(body)
            if not m:
                err(i, MALFORMED_UNIT, "SECTION <NAME> | header: none|\"…\" | role: <role> [| alt: \"…\"]… [| optional: yes]")
                continue
            if m.group("role") not in ROLES:
                err(i, MALFORMED_UNIT, f"unknown role {m.group('role')!r}")
                continue
            alts, optional = _ALT.findall(m.group("alts") or ""), bool(m.group("optional"))
            # Attribute errors still register the section, so its paragraphs do not cascade into errors.
            if alts and not m.group("header"):
                err(i, MALFORMED_UNIT, "| alt: needs a primary header (header: none has no alternative)")
            if optional and m.group("role") == "impression":
                err(i, MALFORMED_UNIT, "the impression section is never optional")
            name = _norm_name(m.group("name"))
            if name in by_name:
                err(i, DUPLICATE_SECTION, name)
                continue
            by_name[name] = name
            sections.append(tss.StructSection(name=name, role=m.group("role"), header=m.group("header"),
                                              order=len(sections), alt_headers=alts, optional=optional))
    default_section = next((s.name for s in sections if s.role == "findings"), "")
    role_of = {s.name: s.role for s in sections}

    # Pass 2: headings, units, prose.
    paragraphs: List[tss.Paragraph] = []
    paragraph_lines: Dict[str, int] = {}  # paragraph id -> heading line
    rules: List[tss.Rule] = []
    negatives: List[tss.Negative] = []
    normals: List[tss.Normal] = []
    fixed: List[tss.FixedBlock] = []
    preferred: List[str] = []
    suppressed: List[str] = []
    if_present: List[tss.IfPresent] = []
    questions: List[str] = []
    differentials: List[tss.Differential] = []
    recommendations: List[tss.Recommendation] = []
    case_targets: List[Tuple[int, int]] = []  # (sheet line, index into negatives) of case negatives
    case_block_line = 0
    stated_lines: List[Tuple[int, str]] = []  # (sheet line, section) of NORMAL / NEGATIVE / FIXED units
    covers_tried = set()  # paragraphs with a COVERS line (a malformed one is reported as such, not as missing)
    cov = {"if_lines": 0, "if_covered": 0, "negative_lines": 0, "negative_covered": 0}
    uncovered: List[str] = []
    ctx = _Ctx()

    def condition(i: int, inner: str) -> Optional[Tuple[str, str]]:
        src, sep, statement = inner.partition(":")
        src, statement = src.strip().lower(), statement.strip()
        if not sep or src not in SOURCES:
            err(i, UNKNOWN_SOURCE, src or "(none)")
            return None
        if len(_content_words(statement)) < 2:
            err(i, NO_SUBJECT, statement)
            return None
        return src, statement

    for i, raw in enumerate(lines, 1):
        if _OLD_IF.search(raw):
            err(i, OLD_SYNTAX)
            continue
        h = _HEADING.match(raw)
        if h:
            title = h.group(1).strip()
            p = paragraph_heading(title) if raw.startswith("## ") else None
            bare = _PARAGRAPH.fullmatch(title.partition("|")[0].strip()) if raw.startswith("## ") else None
            if p is None and bare:  # a paragraph heading whose "| header:" attribute is malformed
                err(i, MALFORMED_QUOTES if title.count('"') % 2 or _CURLY.search(title) else MALFORMED_UNIT,
                    '## Paragraph: <name> (<SECTION>) | header: "<sub-heading as printed>"')
                p = (bare.group("name"), bare.group("sec") or "", None)
            if p:
                sec = _norm_name(p[1])
                if sec not in by_name:
                    err(i, UNKNOWN_PARAGRAPH_SECTION, sec or "(none)")
                pid = f"p{len(paragraphs)}"
                paragraphs.append(tss.Paragraph(id=pid, section=sec, name=p[0], header=p[2]))
                paragraph_lines[pid] = i
                ctx = _Ctx("paragraph", pid, sec)
            elif title.lower() == "report structure":
                ctx = _Ctx("structure")
            elif raw.startswith("## ") and title.lower() == "report-wide":
                ctx = _Ctx("report_wide")
            elif raw.startswith("## ") and title.lower() == CASE_BLOCK:
                if mode != "master":
                    err(i, CASE_IN_TEMPLATE, "## Case Deliberation")
                elif case_block_line:
                    err(i, DUPLICATE_CASE_BLOCK)
                case_block_line = case_block_line or i
                ctx = _Ctx("case")
            else:
                if _PARAGRAPH_LIKE.match(_undecorate(raw)):
                    err(i, MISLEVELLED_PARAGRAPH)
                free = raw.startswith("## ") and title.lower() in FREE_PROSE_SECTIONS
                ctx = _Ctx("free" if free else "other")
            continue
        if i in section_lines:
            continue
        body = _BULLET.sub("", raw, count=1).rstrip()
        first = _FIRST_WORD.match(body)
        keyword = first.group(1) if first and first.group(1) in KEYWORDS else ""
        if not keyword:
            _sweep(i, body, ctx, err, warn)
            continue

        # A unit line.
        conditional = keyword == "RULE" or (keyword == "NEGATIVE" and "WHEN" in body)
        cov["if_lines"] += conditional
        cov["negative_lines"] += keyword == "NEGATIVE"
        n_err = len(errors)
        if keyword == "COVERS" and ctx.kind == "paragraph":
            covers_tried.add(ctx.paragraph)
        unit = _parse_unit(i, raw, body, keyword, ctx, by_name, default_section, err, condition, mode)
        if unit is not None and len(errors) == n_err:
            _mode_check(i, unit, mode, role_of, err)
        if unit is None or len(errors) > n_err:
            uncovered.append(raw)
            continue
        cov["if_covered"] += conditional
        cov["negative_covered"] += keyword == "NEGATIVE"
        kind, data = unit
        if kind in ("negative", "normal", "fixed"):
            stated_lines.append((i, data["section"]))
        if kind == "rule":
            rules.append(tss.Rule(id=f"r{len(rules)}", **data))
        elif kind == "negative":
            if data["origin"] == "case":
                case_targets.append((i, len(negatives)))
            negatives.append(tss.Negative(id=f"n{len(negatives)}", **data))
        elif kind == "normal":
            normals.append(tss.Normal(id=f"m{len(normals)}", **data))
        elif kind == "fixed":
            fixed.append(tss.FixedBlock(id=f"f{len(fixed)}", **data))
        elif kind == "term":
            bucket = preferred if data["kind"] == "PREFER" else suppressed
            if data["text"] not in bucket:
                bucket.append(data["text"])
        elif kind == "if_present":
            if_present.append(tss.IfPresent(**data))
        elif kind == "covers":
            para = paragraphs[int(ctx.paragraph[1:])]
            if para.covers:
                err(i, DUPLICATE_COVERS, para.name)
                uncovered.append(raw)
            else:
                para.covers = data["items"]
        elif kind == "question":
            questions.append(data["text"])
            if len(questions) > 1:
                err(i, QUESTION_COUNT, f"{len(questions)} QUESTION lines")
        elif kind == "differential":
            if any(_norm_name(d.name) == _norm_name(data["name"]) for d in differentials):
                err(i, DUPLICATE_DIFFERENTIAL, data["name"])
                uncovered.append(raw)
            else:
                differentials.append(tss.Differential(id=f"d{len(differentials)}", **data))
        elif kind == "recommendation":
            recommendations.append(tss.Recommendation(id=f"rec{len(recommendations)}", **data))

    # Whole-sheet checks.
    if mode == "master" and not questions:
        err(case_block_line, QUESTION_COUNT, "no QUESTION")
    known = {_norm_name(d.name): d.name for d in differentials}
    visible = {_norm_name(d.name): d.visible for d in differentials}
    for line, idx in case_targets:
        name = known.get(_norm_name(negatives[idx].targets))
        if name is None:
            err(line, UNKNOWN_TARGET, negatives[idx].targets)
        elif visible[_norm_name(name)] != "yes":
            err(line, UNSUPPORTED_TARGET, f"{name} (VISIBLE {visible[_norm_name(name)]})")
        else:
            negatives[idx].targets = name  # canonical: as the DIFFERENTIAL line writes it
    optional = {s.name for s in sections if s.optional}
    for unit_line, unit_section in stated_lines:
        if unit_section in optional:
            err(unit_line, OPTIONAL_SECTION_UNIT, unit_section)
    if mode != "v1":
        for para in paragraphs:
            if role_of.get(para.section) == "findings" and not para.covers and para.id not in covers_tried:
                err(paragraph_lines[para.id], MISSING_COVERS, para.name)
    errors.sort(key=lambda e: e.line)  # stable: same-line errors keep their order

    roles = {s.role for s in sections}
    usable = not errors and structure_blocks == 1 and "findings" in roles and "impression" in roles
    structure = tss.SheetStructure(
        sections=sections, paragraphs=paragraphs, rules=rules, negatives=negatives, normals=normals,
        fixed_blocks=fixed, terminology=tss.Terminology(preferred=preferred, suppressed=suppressed),
        if_present=if_present, sheet_hash=tss.sheet_hash(sheet or ""), model="grammar", source="grammar",
        created_at=datetime.now(timezone.utc).isoformat(), usable=usable,
        coverage=tss.Coverage(**cov, uncovered=uncovered),
        question=questions[0] if len(questions) == 1 else "", differentials=differentials,
        recommendations=recommendations, grammar_mode=mode)
    if errors:
        structure.lint_errors = [tss.LintIssue(line=e.line, text=e.text, reason=e.reason, detail=e.detail)
                                 for e in errors]
    structure.lint_warnings = [tss.LintIssue(line=w.line, text=w.text, reason=w.reason, detail=w.detail)
                               for w in warnings]
    return GrammarResult(structure=structure, errors=errors, warnings=warnings)


def _mode_check(i, unit, mode: str, role_of, err) -> None:
    """Template and master sheets carry the lean template grammar: study/context rules only, unconditional
    negatives only, no template IF_PRESENT (spec 2026-10-01-template-two-phase). A case IF_PRESENT
    belongs to a findings-role paragraph."""
    kind, data = unit
    if kind == "if_present" and data["origin"] == "case" and role_of.get(data["section"]) != "findings":
        err(i, MALFORMED_UNIT, "a case IF_PRESENT belongs in a findings-role paragraph")
        return
    if mode == "v1":
        return
    if kind == "rule":
        src, effect = data["condition_source"], data["effect"]
        if effect == "list_missing":
            if src != "findings":
                err(i, NOT_LEAN, f"LIST_MISSING conditioned on {src}")
        elif src != "context":
            err(i, NOT_LEAN, f"{src}-conditioned RULE (case-dependent: Phase 1 or voice prose)")
        elif effect not in CONTEXT_EFFECTS:
            err(i, NOT_LEAN, f"context RULE with {effect} (context rules: {', '.join(CONTEXT_EFFECTS)})")
    elif kind == "negative" and data["origin"] == "template" and data["condition"]:
        err(i, NOT_LEAN, f"NEGATIVE … WHEN [{data['condition_source']}: …] (template negatives are unconditional; "
                         "case-dependent negatives come from Phase 1)")
    elif kind == "if_present" and data["origin"] == "template":
        err(i, NOT_LEAN, "IF_PRESENT without | origin: case (case-dependent: Phase 1)")


def _parse_unit(i, raw, body, keyword, ctx: _Ctx, by_name, default_section, err, condition, mode="template"):
    """One unit line -> (kind, fields) or None (an error was recorded)."""
    if raw.count('"') % 2 or _CURLY.search(raw) or '""' in raw:
        err(i, MALFORMED_QUOTES)
        return None
    # Case Deliberation block: its three keywords, nothing else; they appear nowhere else.
    if keyword in CASE_BLOCK_KEYWORDS:
        if mode != "master":
            err(i, CASE_IN_TEMPLATE, keyword)
            return None
        if ctx.kind != "case":
            err(i, MALFORMED_UNIT, f"{keyword} outside the ## Case Deliberation block")
            return None
        m = _UNITS[keyword].fullmatch(body)
        if not m:
            err(i, MALFORMED_UNIT, f"not a {keyword} unit")
            return None
        if keyword == "QUESTION":
            return "question", {"text": m.group(1)}
        if keyword == "DIFFERENTIAL":
            if not m.group("name").strip():
                err(i, MALFORMED_UNIT, "DIFFERENTIAL [<name>] needs a name")
                return None
            return "differential", {"name": m.group("name").strip(), "tier": m.group("tier"),
                                    "discriminator": m.group(3), "visible": m.group("visible")}
        cond = condition(i, m.group(3))
        if cond is None:
            return None
        if cond[0] != "findings":
            err(i, MALFORMED_UNIT, "RECOMMEND is conditioned on findings")
            return None
        return "recommendation", {"tag": m.group("tag"), "text": m.group(2), "condition": cond[1],
                                  "condition_source": cond[0]}
    if ctx.kind == "case":
        err(i, MALFORMED_UNIT, f"{keyword} in the Case Deliberation block (QUESTION, DIFFERENTIAL, RECOMMEND only)")
        return None
    # Origin (case units inside paragraphs), then section, both trailing attributes outside quotes.
    origin = "template"
    oa = _ORIGIN_ATTR.search(body)
    if oa:
        body = body[:oa.start()]
        if oa.group(1).strip().lower() != "case" or keyword not in ("NEGATIVE", "IF_PRESENT"):
            err(i, MALFORMED_UNIT, "| origin: case is for NEGATIVE … TARGETS and IF_PRESENT only")
            return None
        if mode != "master":
            err(i, CASE_IN_TEMPLATE, "| origin: case")
            return None
        if ctx.kind != "paragraph":
            err(i, MALFORMED_UNIT, "a case unit belongs inside a paragraph")
            return None
        origin = "case"
    sa = _SECTION_ATTR.search(body)
    named = _norm_name(sa.group(1)) if sa else ""
    if sa:
        body = body[:sa.start()]
    if named and named not in by_name:
        err(i, UNKNOWN_SECTION, named)
        return None
    if ctx.kind == "paragraph":
        if named and named != ctx.section:
            err(i, MALFORMED_UNIT, f"section {named} differs from its paragraph's {ctx.section}")
            return None
        section, paragraph = ctx.section, ctx.paragraph
    else:
        section, paragraph = named or (default_section if ctx.kind == "report_wide" else ""), ""
    if keyword == "COVERS" and ctx.kind != "paragraph":
        err(i, MALFORMED_UNIT, "COVERS outside a paragraph")
        return None
    if keyword != "TERM" and not section:
        err(i, NO_SECTION)
        return None

    m = _UNITS[keyword].fullmatch(body)
    if not m:
        err(i, MALFORMED_UNIT, f"not a {keyword} unit")
        return None
    where = {"section": section, "paragraph": paragraph}
    if keyword == "COVERS":
        if not _ITEMS.fullmatch(m.group("items")):
            comma = re.search(r'"\s*,\s*"', m.group("items"))
            err(i, MALFORMED_UNIT, 'COVERS ["<structure>" | "<structure>"]: separate items with " | ", not commas'
                if comma else 'COVERS ["<structure>" | "<structure>"]: each item double-quoted, at least one')
            return None
        return "covers", {"items": re.findall(r'"([^"]+)"', m.group("items"))}
    if keyword == "NORMAL":
        return "normal", {**where, "structure": m.group("structure").strip(), "text": m.group(2),
                          "source_line": raw}
    if keyword == "NEGATIVE":
        targets = (m.group("targets") or "").strip()
        if origin == "case" and (not targets or m.group(2) is not None):
            err(i, MALFORMED_UNIT, 'a case negative is NEGATIVE "<text>" TARGETS [<differential>] | origin: case')
            return None
        if origin == "template" and m.group("targets") is not None:
            err(i, MALFORMED_UNIT, "TARGETS is for a case negative (| origin: case)")
            return None
        cond = None
        if m.group(2) is not None:
            cond = condition(i, m.group(2))
            if cond is None:
                return None
        return "negative", {**where, "text": m.group(1), "condition": cond[1] if cond else None,
                            "condition_source": cond[0] if cond else "findings", "source_lines": [raw],
                            "origin": origin, "targets": targets}
    if keyword == "FIXED":
        return "fixed", {"section": section, "text": m.group(1)}
    if keyword == "TERM":
        return "term", {"kind": m.group(1), "text": m.group(2)}
    if keyword == "IF_PRESENT":
        return "if_present", {**where, "finding": m.group("finding").strip(), "origin": origin,
                              "negatives": [tss.IfPresentNeg(text=m.group(2), tag=m.group(3))]}
    # RULE
    cond = condition(i, m.group(1))
    if cond is None:
        return None
    effect_text = m.group("effect")
    for effect, pat in _EFFECTS:
        e = pat.fullmatch(effect_text)
        if e:
            break
    else:
        err(i, MALFORMED_UNIT, f"unknown effect {effect_text!r}")
        return None
    if effect in _PARAGRAPH_EFFECTS and ctx.kind != "paragraph":
        err(i, MALFORMED_UNIT, f"{effect} outside a paragraph")
        return None
    rule = {**where, "condition": cond[1], "condition_source": cond[0], "effect": effect, "source_lines": [raw]}
    if effect == "replace":
        rule.update(target=e.group(1), then_text=e.group(2))
    elif effect == "suppress":
        rule.update(target=e.group(1))
    elif effect in ("append", "use"):
        rule.update(then_text=e.group(1))
    elif effect == "insert_before":
        rule.update(then_text=e.group(1), anchor=e.group(2))
    elif effect == "list_missing":
        if not _ITEMS.fullmatch(e.group(1)):
            err(i, MALFORMED_UNIT, 'LIST_MISSING ["<item>" | "<item>" …]')
            return None
        rule.update(items=re.findall(r'"([^"]+)"', e.group(1)), position=e.group(2).lower())
    elif effect == "suppress_section":
        name = _norm_name(e.group(1))
        if name not in by_name:
            err(i, UNKNOWN_SECTION, name)
            return None
        rule.update(target=name)
    elif effect == "order":
        rule.update(position=e.group(1).lower())
    return "rule", rule


# ── rendering (the canonical line for a parsed unit; parse(render(x)) gives x back) ──────────────

def render_condition(source: str, statement: str) -> str:
    return f"WHEN [{source}: {statement}]"


def render_rule(rule: tss.Rule) -> str:
    e = rule.effect
    effect = {
        "replace": lambda: f'REPLACE "{rule.target}" WITH "{rule.then_text}"',
        "suppress": lambda: f'SUPPRESS "{rule.target}"',
        "append": lambda: f'APPEND "{rule.then_text}"',
        "use": lambda: f'USE "{rule.then_text}"',
        "insert_before": lambda: f'INSERT "{rule.then_text}" BEFORE "{rule.anchor}"',
        "suppress_paragraph_negatives": lambda: "SUPPRESS NEGATIVES",
        "list_missing": lambda: "LIST_MISSING [" + " | ".join(f'"{x}"' for x in rule.items)
                                + f"] AT {(rule.position or 'top').upper()}",
        "suppress_section": lambda: f"SUPPRESS_SECTION {rule.target}",
        "suppress_headers": lambda: "SUPPRESS_HEADERS",
        "order": lambda: f"ORDER {(rule.position or 'first').upper()}",
    }[e]()
    return f"RULE {render_condition(rule.condition_source, rule.condition)} {effect}"


def render_negative(neg: tss.Negative) -> str:
    cond = f" {render_condition(neg.condition_source, neg.condition)}" if neg.condition else ""
    case = f" TARGETS [{neg.targets}] | origin: case" if neg.origin == "case" else ""
    return f'NEGATIVE "{neg.text}"{cond}{case}'
