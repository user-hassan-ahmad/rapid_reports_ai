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
  list's N/A items and becomes a value_missing review flag. A value the scratchpad gate filled from the dictation
  was provided, so it never joins the line: restore_values writes its dictated sentence back (P3 2026-10-15).
The stored sheet is never changed. Regex here only reads the grammar's own syntax and our own literal line. Never
raises: a sheet that does not parse clean, or any error, leaves things as they came with the reason in the record;
values_applied() then says the generator must not be told the values were decided."""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Sequence, Tuple

from .hybrid_stack.jev_stack import BACKSTOP_MIN, ask_report_values
from .hybrid_stack.template import norm_key, paragraph_regions
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


async def backstop(report: str, lists: List[dict], filled: Sequence[str], ask=None,
                   list_missing: bool = True) -> Tuple[List[dict], List[dict], dict]:
    """The post-generation backstop: (lists with every filled value the report does not state added to its list's
    N/A items, value_missing review flags, record). Jev decides (ask_report_values, BACKSTOP_MIN); code lists and
    flags. A Jev failure or a short reply changes nothing and adds one value_check_unavailable flag (never silent);
    no filled items: no call. `list_missing` False (the value cluster: the gate filled these values from the
    dictation): a value the report lacks was provided, so it is flagged and recorded but never listed as not
    provided; the caller writes it back (restore_values)."""
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
    flags = [{"kind": VALUE_MISSING, "text": i, "message": f"Required value {i} not found in the report"} for i in missing]
    logger.info("[template.required_values] backstop asked=%d missing=%d", len(items), len(missing))
    if not list_missing:
        return lists, flags, rec
    out = [dict(e, na=list(e["na"])) for e in lists]
    listed = {norm_key(x) for e in out for x in e["na"]}
    for item in missing:
        k = norm_key(item)
        if k in listed:
            continue
        listed.add(k)
        next(e for e in out if k in {norm_key(x) for x in e["items"]})["na"].append(item)
    return out, flags, rec


def _flat(s: str) -> str:
    return " ".join((s or "").split()).rstrip(".").lower()


_BULLET = re.compile(r"^([-*•]|(\d+)([.)]))\s")


def _present(sentence: str, text: str) -> bool:
    """The sentence is in the text as whole words ("EF 55%" is not inside "RVEF 55%")."""
    return re.search(r"(?<!\w)" + re.escape(_flat(sentence)) + r"(?!\w)", " ".join((text or "").split()).lower()) is not None


def _append(text: str, a: int, b: int, sentence: str) -> str:
    """The sentence at the end of text[a:b]: after its last sentence on the same line; on its own line after a list
    item (with the list's marker) or after a "Values not provided" line (never joined onto it)."""
    k = a + len(text[a:b].rstrip())
    last = text[a:k].rsplit("\n", 1)[-1].strip()
    bullet = _BULLET.match(last)
    if last and last[-1] in ".!?" and not bullet and not _NA_LINE.match(last):
        return text[:k] + " " + sentence + text[k:]
    if bullet:
        n = bullet.group(2)
        sentence = (f"{int(n) + 1}{bullet.group(3)} " if n else bullet.group(1) + " ") + sentence
    sep = "\n" if k > a or (k > 0 and text[k - 1] != "\n") else ""
    return text[:k] + sep + sentence + text[k:]


def _section_aliases(st) -> dict:
    """A scratchpad region (a sheet section's name or header, or a findings paragraph's region name) -> the names
    the report gives that section (its name and its header line)."""
    names = {}
    for s in (st.sections if st else []):
        header = (s.header or s.name).strip().rstrip(":").strip().upper()
        names[s.name] = {s.name.upper(), header}
    alias = {}
    for s in (st.sections if st else []):
        for n in (s.name, (s.header or "").strip().rstrip(":").strip()):
            if n:
                alias[" ".join(n.split()).upper()] = names[s.name]
    if st:
        sec = {p.id: p.section for p in st.paragraphs}
        for pid, region in paragraph_regions(st).items():
            alias.setdefault(" ".join(region.split()).upper(), names.get(sec.get(pid), set()))
    return alias


def restore_values(report: str, sheet: str, missing: Sequence[str],
                   quotes: dict) -> Tuple[str, List[dict], List[str]]:
    """A value the gate filled from the dictation never vanishes (P3 2026-10-15): (the report with each missing
    value's dictated sentence written back, the insertion edits, the items the report now holds). `quotes`: item ->
    {"sentence": the dictated sentence holding the value, "region": its scratchpad region}
    (hybrid_stack.findings.filled_value_quotes). The sentence goes at the end of the report's headed section named
    for its region, as dictated (capitalised, terminated; a bulleted section's marker). Flag only (the item is not
    returned, so its value_missing flag stays; it is never listed as not provided): no sentence (a stated? or kept
    chip), no region, a region no headed report section is named for, a region naming the conclusion, or a report
    without headers. A sentence already in the report is not written again. Run before write_missing. Never raises:
    on any error the report comes back as it was."""
    try:
        from .report_review import section_spans
        from .template_lean import report_sections
        by = {norm_key(k): v for k, v in (quotes or {}).items() if isinstance(v, dict)}
        alias = _section_aliases(_clean(sheet))
        text, edits, restored = report or "", [], []
        for item in missing:
            q = by.get(norm_key(item)) or {}
            sent = " ".join(str(q.get("sentence") or "").split())
            if not sent:
                continue
            sent = sent[0].upper() + sent[1:]
            sent = sent if sent[-1] in ".!?" else sent + "."
            if _present(sent, _NA_LINE.sub("", text)):
                restored.append(item)
                continue
            region = " ".join(str(q.get("region") or "").split()).upper()
            if not region:
                continue
            want = alias.get(region, {region})
            spans = section_spans(text, report_sections(text, sheet))
            hit = next(((a, b) for s, a, b in spans if s.header and s.role != "impression" and s.name in want), None)
            if hit is None:
                continue
            text = _append(text, hit[0], hit[1], sent)
            edits.append({"type": "insertion", "sentence": sent})
            restored.append(item)
        logger.info("[template.required_values] restored=%d", len(edits))
        return text, edits, restored
    except Exception as e:  # noqa: BLE001 -- never break Generate
        logger.warning("[template.required_values] restore error=%s", f"{type(e).__name__}: {e}"[:200])
        return report, [], []


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
