"""Template skill-sheet grammar v1: code parses a grammar sheet into SheetStructure (spec
2026-10-01-template-sheet-grammar-design).

Prose is the radiologist's voice and passes through untouched; every unit the brief reconciles against a
dictation is a keyword-led line. The parser is pure and deterministic, and fails closed: any lint error
leaves the structure unusable (the raw path generates) and records the lint errors on it. Grammar
structures are the only ones generation trusts (template_sheet_structure.fresh); they are parsed
synchronously on save. A sheet not in grammar form (no "## Report Structure" line) stays on the raw
path until converted; the LLM extractor is lab-only (RR_SHEET_EXTRACTOR) and never trusted.

Unit lines (optional indentation and an optional "- " bullet before the keyword):

    SECTION <NAME> | header: none | role: <role>              (only in the "## Report Structure" block)
    SECTION <NAME> | header: "<as written>" | role: <role>
    NORMAL [<structure>] "<text>"
    NEGATIVE "<text>"  [WHEN [<source>: <statement>]]
    FIXED "<text>"
    TERM PREFER "<term>" | TERM AVOID "<term>"
    IF_PRESENT [<finding>] "<negative>" (core|contextual)
    RULE WHEN [<source>: <statement>] <EFFECT>

A unit outside a paragraph may name its section with a trailing "| section: <NAME>"; under
"## Report-wide" it defaults to the first findings-role section. TERM units are sheet-wide.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from . import template_sheet_structure as tss

# The keywords that open a unit line. Anything else starting with an uppercase word followed by
# `[`, `"` or WHEN is an unknown keyword-like line.
KEYWORDS = ("SECTION", "NORMAL", "NEGATIVE", "FIXED", "TERM", "IF_PRESENT", "RULE")
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
PROSE_CONDITIONAL = "conditional phrase in prose under a paragraph"
OLD_SYNTAX = "old IF [ syntax"
MALFORMED_UNIT = "malformed unit"
UNKNOWN_SECTION = "unknown section"
SECTION_OUTSIDE_STRUCTURE = "SECTION outside the Report Structure block"
DUPLICATE_STRUCTURE = "duplicate Report Structure block"


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


# ── line shapes ──────────────────────────────────────────────────────────────

_BULLET = re.compile(r"^\s*(?:-\s+)?")
_HEADING = re.compile(r"^#{1,2}\s+(.*?)\s*$")  # "# " and "## " open a new context; "### " is prose
_PARAGRAPH = re.compile(r"^Paragraph:\s*(?P<name>.*?)\s*(?:\((?P<sec>[^()]*)\))?\s*$", re.I)
_OLD_IF = re.compile(r"\bIF\s*\[")
_KEYWORD_LIKE = re.compile(r"^([A-Z][A-Z_]+)\s*(?:\[|\"|WHEN\b)")
_FIRST_WORD = re.compile(r"^([A-Z][A-Z_]*)\b")
_CURLY = re.compile(r"[“”]")

_NAME = r"[A-Z0-9][A-Z0-9 /&-]*?"
_Q = r'"([^"]+)"'
_COND = r"WHEN\s*\[([^\]]*)\]"
_SECTION_ATTR = re.compile(r"\s*\|\s*section:\s*(.*?)\s*$")

_SECTION = re.compile(rf"SECTION\s+(?P<name>{_NAME})\s*\|\s*header:\s*(?:none|\"(?P<header>[^\"]+)\")"
                      r"\s*\|\s*role:\s*(?P<role>\w+)\s*")
_UNITS = {
    "NORMAL": re.compile(rf"NORMAL\s*\[(?P<structure>[^\]]+)\]\s*{_Q}\s*"),
    "NEGATIVE": re.compile(rf"NEGATIVE\s*{_Q}(?:\s+{_COND})?\s*"),
    "FIXED": re.compile(rf"FIXED\s*{_Q}\s*"),
    "TERM": re.compile(rf"TERM\s+(PREFER|AVOID)\s*{_Q}\s*"),
    "IF_PRESENT": re.compile(rf"IF_PRESENT\s*\[(?P<finding>[^\]]+)\]\s*{_Q}\s*\((core|contextual)\)\s*"),
    "RULE": re.compile(rf"RULE\s+{_COND}\s*(?P<effect>.*?)\s*"),
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

# Prose under a paragraph that says "if", "when" or "unless" (outside quoted text) is a conditional
# the analyser should have written as a RULE / NEGATIVE … WHEN. Idioms that are not conditions are
# exempt.
_PROSE_COND = re.compile(r"\b(?:if|when|unless)\b", re.I)
_PROSE_COND_EXEMPT = re.compile(r"\bif\s+any\b", re.I)


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().upper()


def _content_words(statement: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", statement.lower()) if w not in _STOP and not w.isdigit()]


def _outside_quotes(text: str) -> str:
    return re.sub(r'"[^"]*"', " ", text)


@dataclass
class _Ctx:
    kind: str = "none"  # none | structure | paragraph | report_wide | other
    paragraph: str = ""  # paragraph id
    section: str = ""  # paragraph's section (canonical name, or as written when unknown)


_GRAMMAR_MARK = re.compile(r"^##\s+Report Structure\s*$", re.I | re.M)


def is_grammar_sheet(sheet: str) -> bool:
    """A sheet is in grammar form when it has a "## Report Structure" line."""
    return bool(_GRAMMAR_MARK.search(sheet or ""))


def parse_sheet(sheet: str) -> GrammarResult:
    """Parse a grammar sheet. Deterministic: the same sheet gives the same structure and errors
    (created_at aside)."""
    lines = (sheet or "").splitlines()
    errors: List[LintError] = []

    def err(i: int, reason: str, detail: str = "") -> None:
        errors.append(LintError(line=i, text=lines[i - 1], reason=reason, detail=detail))

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
        body = _BULLET.sub("", raw, count=1)
        if _FIRST_WORD.match(body) and _FIRST_WORD.match(body).group(1) == "SECTION":
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
                err(i, MALFORMED_UNIT, "SECTION <NAME> | header: none|\"…\" | role: <role>")
                continue
            if m.group("role") not in ROLES:
                err(i, MALFORMED_UNIT, f"unknown role {m.group('role')!r}")
                continue
            name = _norm_name(m.group("name"))
            if name in by_name:
                err(i, DUPLICATE_SECTION, name)
                continue
            by_name[name] = name
            sections.append(tss.StructSection(name=name, role=m.group("role"), header=m.group("header"),
                                              order=len(sections)))
    default_section = next((s.name for s in sections if s.role == "findings"), "")

    # Pass 2: headings, units, prose.
    paragraphs: List[tss.Paragraph] = []
    rules: List[tss.Rule] = []
    negatives: List[tss.Negative] = []
    normals: List[tss.Normal] = []
    fixed: List[tss.FixedBlock] = []
    preferred: List[str] = []
    suppressed: List[str] = []
    if_present: List[tss.IfPresent] = []
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
            p = _PARAGRAPH.fullmatch(title) if raw.startswith("## ") else None
            if p:
                sec = _norm_name(p.group("sec") or "")
                if sec not in by_name:
                    err(i, UNKNOWN_PARAGRAPH_SECTION, sec or "(none)")
                pid = f"p{len(paragraphs)}"
                paragraphs.append(tss.Paragraph(id=pid, section=sec, name=p.group("name")))
                ctx = _Ctx("paragraph", pid, sec)
            elif title.lower() == "report structure":
                ctx = _Ctx("structure")
            elif raw.startswith("## ") and title.lower() == "report-wide":
                ctx = _Ctx("report_wide")
            else:
                ctx = _Ctx("other")
            continue
        if i in section_lines:
            continue
        body = _BULLET.sub("", raw, count=1).rstrip()
        first = _FIRST_WORD.match(body)
        keyword = first.group(1) if first and first.group(1) in KEYWORDS else ""
        if not keyword:
            km = _KEYWORD_LIKE.match(body)
            if km:
                err(i, UNKNOWN_KEYWORD, km.group(1))
            elif ctx.kind == "paragraph" and body.strip():
                prose = _PROSE_COND_EXEMPT.sub(" ", _outside_quotes(body))
                cm = _PROSE_COND.search(prose)
                if cm:
                    err(i, PROSE_CONDITIONAL, cm.group(0).lower())
            continue

        # A unit line.
        conditional = keyword == "RULE" or (keyword == "NEGATIVE" and "WHEN" in body)
        cov["if_lines"] += conditional
        cov["negative_lines"] += keyword == "NEGATIVE"
        n_err = len(errors)
        unit = _parse_unit(i, raw, body, keyword, ctx, by_name, default_section, err, condition)
        if unit is None or len(errors) > n_err:
            uncovered.append(raw)
            continue
        cov["if_covered"] += conditional
        cov["negative_covered"] += keyword == "NEGATIVE"
        kind, data = unit
        if kind == "rule":
            rules.append(tss.Rule(id=f"r{len(rules)}", **data))
        elif kind == "negative":
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

    roles = {s.role for s in sections}
    usable = not errors and structure_blocks == 1 and "findings" in roles and "impression" in roles
    structure = tss.SheetStructure(
        sections=sections, paragraphs=paragraphs, rules=rules, negatives=negatives, normals=normals,
        fixed_blocks=fixed, terminology=tss.Terminology(preferred=preferred, suppressed=suppressed),
        if_present=if_present, sheet_hash=tss.sheet_hash(sheet or ""), model="grammar", source="grammar",
        created_at=datetime.now(timezone.utc).isoformat(), usable=usable,
        coverage=tss.Coverage(**cov, uncovered=uncovered))
    if errors:
        structure.lint_errors = [tss.LintIssue(line=e.line, text=e.text, reason=e.reason, detail=e.detail)
                                 for e in errors]
    return GrammarResult(structure=structure, errors=errors)


def _parse_unit(i, raw, body, keyword, ctx: _Ctx, by_name, default_section, err, condition):
    """One unit line -> (kind, fields) or None (an error was recorded)."""
    if raw.count('"') % 2 or _CURLY.search(raw) or '""' in raw:
        err(i, MALFORMED_QUOTES)
        return None
    # Section and paragraph.
    sa = _SECTION_ATTR.search(body) if keyword != "SECTION" else None
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
    if keyword != "TERM" and not section:
        err(i, NO_SECTION)
        return None

    m = _UNITS[keyword].fullmatch(body)
    if not m:
        err(i, MALFORMED_UNIT, f"not a {keyword} unit")
        return None
    where = {"section": section, "paragraph": paragraph}
    if keyword == "NORMAL":
        return "normal", {**where, "structure": m.group("structure").strip(), "text": m.group(2),
                          "source_line": raw}
    if keyword == "NEGATIVE":
        cond = None
        if m.group(2) is not None:
            cond = condition(i, m.group(2))
            if cond is None:
                return None
        return "negative", {**where, "text": m.group(1), "condition": cond[1] if cond else None,
                            "condition_source": cond[0] if cond else "findings", "source_lines": [raw]}
    if keyword == "FIXED":
        return "fixed", {"section": section, "text": m.group(1)}
    if keyword == "TERM":
        return "term", {"kind": m.group(1), "text": m.group(2)}
    if keyword == "IF_PRESENT":
        return "if_present", {**where, "finding": m.group("finding").strip(),
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
    return f'NEGATIVE "{neg.text}"{cond}'
