"""Required values decided in the scratchpad (requirements spec 2026-10-12 part 1, Generate).

The radiologist resolved every LIST_MISSING item in the scratchpad's value cluster: filled from the dictation,
typed, or marked N/A. Code owns the missing-values list (Hassan 2026-10-13: always the literal wording):
- apply_required_values: every LIST_MISSING line leaves the sheet the generator reads (the stack brief then says to
  write no list); the record keeps the N/A items, the list's position and its section. An item on two lists is
  listed once.
- write_missing: after generation, any generator line beginning "Values not provided" is removed and code writes
  "Values not provided: <items>." as its own paragraph: AT TOP before the first findings heading (after any
  preamble), AT END after the last findings section; a list anchored to another section (not the default first
  findings one) goes at the TOP or END of that section; with no findings section found, the report itself.
- backstop: before the line is written, Jev asks whether the generated report states each value whose chip was
  filled (a false "stated" must never let a value vanish from both the report and the line); each "no" joins its
  list's N/A items and becomes a value_missing review flag.
The stored sheet is never changed. Regex here only reads the grammar's own syntax and our own literal line. Never
raises: a sheet that does not parse clean, or any error, leaves things as they came with the reason in the record;
values_applied() then says the generator must not be told the values were decided."""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Sequence, Tuple

from .hybrid_stack.jev_stack import BACKSTOP_MIN, ask_report_values
from .hybrid_stack.template import norm_key
from .template_context_rules import _clean

logger = logging.getLogger(__name__)

NA_PREFIX = "Values not provided"
VALUE_MISSING = "value_missing"
VALUE_CHECK_UNAVAILABLE = "value_check_unavailable"   # the backstop could not run: never a silent failure
_NA_LINE = re.compile(r"(?im)^[ \t]*(?:[-*•][ \t]*)?values not provided\b[^\n]*\n?")


def missing_line(items: Sequence[str]) -> str:
    return f"{NA_PREFIX}: {', '.join(items)}."


def apply_required_values(sheet: str, na: Sequence[str]) -> Tuple[str, dict]:
    """(the sheet the generator reads, the record). `na`: the items the radiologist marked N/A."""
    rec: dict = {"lists": [], "skipped": None, "error": None}
    try:
        st = _clean(sheet)
        if st is None:
            rec["skipped"] = "parse"
            return sheet, rec
        rules = [r for r in st.rules if r.effect == "list_missing"]
        if not rules:
            rec["skipped"] = "no_list"
            return sheet, rec
        gone = {norm_key(x) for x in na if isinstance(x, str) and x.strip()}
        lines = sheet.splitlines()
        out: List[Optional[str]] = list(lines)
        taken: set[int] = set()
        listed: set[str] = set()
        for r in rules:
            raw = r.source_lines[0] if r.source_lines else None
            i = next((k for k, ln in enumerate(lines) if k not in taken and ln == raw), None)
            keep: List[str] = []
            for x in r.items:
                k = norm_key(x)
                if k in gone and k not in listed:
                    listed.add(k)
                    keep.append(x)
            rec["lists"].append({"line": None if i is None else i + 1, "items": list(r.items), "na": keep,
                                 "position": r.position or "top", "section": r.section,
                                 "outcome": "unmatched" if i is None else "applied"})
            if i is not None:
                taken.add(i)
                out[i] = None
        text = "\n".join(x for x in out if x is not None)
        return (text + "\n" if sheet.endswith("\n") else text), rec
    except Exception as e:  # noqa: BLE001 -- fail-soft: the generator reads the sheet as it came
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
        logger.warning("[template.required_values] error=%s", rec["error"])
        return sheet, rec


def values_applied(rec: dict) -> bool:
    """True only when code took over every list: no error, no skip, every LIST_MISSING line matched."""
    return (rec.get("error") is None and rec.get("skipped") is None and bool(rec.get("lists"))
            and all(e.get("outcome") == "applied" for e in rec["lists"]))


async def backstop(report: str, lists: List[dict], filled: Sequence[str], ask=None) -> Tuple[List[dict], List[dict], dict]:
    """The post-generation backstop: (lists with every filled value the report does not state added to its list's
    N/A items, value_missing review flags, record). Jev decides (ask_report_values, BACKSTOP_MIN); code lists and
    flags. A Jev failure or a short reply changes nothing and adds one value_check_unavailable flag (never silent);
    no filled items: no call."""
    rec: dict = {"asked": 0, "missing": [], "error": None}
    required = {norm_key(x) for e in lists for x in e["items"]}   # the client's items, checked against the template
    items = list(dict.fromkeys(x.strip() for x in filled
                               if isinstance(x, str) and x.strip() and norm_key(x) in required))
    if not items:
        return lists, [], rec
    rec["asked"] = len(items)
    try:
        # the generator's own "Values not provided" lines would read as stating the value: Jev never sees them
        scores = await (ask or ask_report_values)(_NA_LINE.sub("", report or ""), items)
        if len(scores) != len(items):
            raise ValueError("jev: answer count mismatch")
    except Exception as e:  # noqa: BLE001 -- fail-soft: the report as it is, no flags
        rec["error"] = ("jev: answer count mismatch" if isinstance(e, ValueError) and "mismatch" in str(e)
                        else f"{type(e).__name__}: {e}"[:200])
        logger.warning("[template.required_values] backstop error=%s", rec["error"])
        return lists, [{"kind": VALUE_CHECK_UNAVAILABLE, "text": "",
                        "message": "Required values could not be checked against the report"}], rec
    missing = [i for i, p in zip(items, scores) if p < BACKSTOP_MIN]
    rec["missing"] = missing
    if not missing:
        return lists, [], rec
    out = [dict(e, na=list(e["na"])) for e in lists]
    listed = {norm_key(x) for e in out for x in e["na"]}
    for item in missing:
        k = norm_key(item)
        if k in listed:
            continue
        listed.add(k)
        next(e for e in out if k in {norm_key(x) for x in e["items"]})["na"].append(item)
    flags = [{"kind": VALUE_MISSING, "text": i, "message": f"Required value {i} not found in the report"} for i in missing]
    logger.info("[template.required_values] backstop asked=%d missing=%d", len(items), len(missing))
    return out, flags, rec


def _insert(text: str, a: int, b: int, line: str, end: bool) -> str:
    body = text[a:b]
    if end:
        k = a + len(body.rstrip())
        return text[:k] + ("\n" if k > a else "") + line + text[k:]
    k = a + len(body) - len(body.lstrip())
    head = text[:k]
    if head and not head.endswith("\n"):   # an inline header ("Findings: Normal LV."): the line goes on its own line
        return head.rstrip(" \t") + "\n" + line + "\n" + text[k:]
    return head + line + ("\n" if text[k:b].strip() else "") + text[k:]


def _between(text: str, findings: list, line: str, end: bool) -> str:
    """The line as its own paragraph outside every findings section: before the first one's heading (after any
    preamble such as a comparison line), or, at END, after the last one (before the summary/impression)."""
    # the report's own headed findings sections; an implicit one is the text before them (e.g. a comparison line)
    findings = [f for f in findings if f[0].header] or findings
    if end:
        _, a, b = findings[-1]
        k = a + len(text[a:b].rstrip())
        return text[:k] + "\n\n" + line + text[k:]
    s, a, _ = findings[0]
    p = a
    if s.header:   # the heading's line start: a standalone header line, or an inline "Findings: …"
        p = text.rfind("\n", 0, a - 1 if text[a - 1:a] == "\n" else a) + 1
    head = text[:p]
    if head.strip():
        return head.rstrip("\n") + "\n\n" + line + "\n\n" + text[p:].lstrip("\n")
    return line + "\n\n" + text[p:].lstrip("\n")


def write_missing(report: str, sheet: str, lists: List[dict], rec: Optional[dict] = None) -> Tuple[str, int]:
    """(the report with code's "Values not provided" lines, generator lines in that wording removed). Never raises:
    on any error the report comes back as it was, and the error goes in rec["write_error"]."""
    try:
        from .report_review import section_spans
        from .template_lean import report_sections
        text, stripped = _NA_LINE.subn("", report or "")
        st = _clean(sheet)
        names = {s.name.upper(): {s.name.upper(), (s.header or s.name).strip().rstrip(":").strip().upper()}
                 for s in (st.sections if st else [])}
        # A report-wide list names the first findings section by default (the grammar's default, which the analyser
        # also writes out): that is no anchor. Only another section anchors the line inside it.
        default = next((s.name.upper() for s in (st.sections if st else []) if s.role == "findings"), "")
        for e in lists:
            if not e.get("na"):
                continue
            spans = section_spans(text, report_sections(text, sheet))
            line, end = missing_line(e["na"]), e.get("position") == "end"
            section = (e.get("section") or "").upper()
            findings = [(s, a, b) for s, a, b in spans if s.role == "findings"]
            if (not section or section == default) and findings:
                text = _between(text, findings, line, end)
                continue
            want = names.get(section, {section})
            hit = (next(((a, b) for s, a, b in spans if s.name in want), None)
                   or next(((a, b) for _, a, b in findings), None) or (0, len(text)))
            text = _insert(text, hit[0], hit[1], line, end)
        logger.info("[template.required_values] written=%d stripped=%d", sum(bool(e.get("na")) for e in lists), stripped)
        return text, stripped
    except Exception as e:  # noqa: BLE001 -- never break Generate
        err = f"{type(e).__name__}: {e}"[:200]
        if rec is not None:
            rec["write_error"] = err
        logger.warning("[template.required_values] write error=%s", err)
        return report, 0
