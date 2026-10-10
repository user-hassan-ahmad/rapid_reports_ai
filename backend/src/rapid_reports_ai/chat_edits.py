"""Chat edits (spec §12.5, Plan 3 D1): the report chat reply carries surgical `edits[]` alongside prose.

The model writes edits as one decoded JSON string (`edits_json`) on its existing tool call, so its schema stays flat.
Code parses them, and every edit goes through the review engine's one-click code guards
(`review_engine.verifier.guard_failures`) against the current report text. An edit that fails comes back with
`verified: false` and its failure codes, and the rail shows it without Apply.

The request's open review items go into the model context, so chat does not propose them again."""
from __future__ import annotations

import difflib
import json
import re
from typing import Any, Iterable, List, Optional, Tuple

from .review_engine.items import Edit
from .review_engine.verifier import guard_failures

CHAT_KIND = "chat"          # not a removal kind: an edit that drops a negation fails (L-47)
OPEN_ITEMS_CAP = 30

EDITS_JSON_DESCRIPTION = (
    "Optional. The same changes as surgical text edits, written as a JSON array string, e.g. "
    '[{"section": "FINDINGS", "find": "<exact text copied from the report>", "replace": "<new text>"}]. '
    "`find` is copied verbatim from the current report and occurs exactly once; keep it to the sentence or "
    "clause that changes. `replace` is the full new text for that span (an empty string deletes it). "
    "`section` is the report heading the span sits under. Required whenever you change the report: the rail "
    "offers each edit with its own Apply, and a change without an edit here cannot be applied."
)


def _s(v: Any) -> str:
    return v if isinstance(v, str) else ""


def parse_edits_json(raw: Any) -> List[dict]:
    """Fails open: anything unparseable gives []. Accepts a JSON array string, a {"edits": [...]} wrapper, or an
    already-decoded list. Non-object entries are dropped; missing fields become ""."""
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw) if raw.strip() else []
        except (json.JSONDecodeError, ValueError):
            return []
    if isinstance(data, dict):
        data = data.get("edits")
    if not isinstance(data, list):
        return []
    return [{"section": _s(e.get("section")), "find": _s(e.get("find")), "replace": _s(e.get("replace"))}
            for e in data if isinstance(e, dict)]


MAX_DIFF_EDITS = 8         # more changed sentences than this is a restructure, not surgery: no edits offered
_HEADING = re.compile(r"^\s*([A-Z][A-Z0-9 /&()'-]*):\s*$")
_SENT_END = re.compile(r"(?<=[.!?])\s+")


def _units(text: str) -> List[Tuple[int, int, str, Optional[str], bool]]:
    """(start, end, normalised text, section, is_heading) per sentence of `text`, in order; offsets into `text`."""
    out, section, pos = [], None, 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        h = _HEADING.match(body)
        if h:
            section = h.group(1).strip()
            out.append((pos, pos + len(body), " ".join(body.split()), section, True))
        else:
            k = 0
            for part in _SENT_END.split(body):
                j = body.find(part, k) if part else -1
                if part.strip() and j >= 0:
                    a = j + len(part) - len(part.lstrip())
                    b = j + len(part.rstrip())
                    out.append((pos + a, pos + b, " ".join(part.split()), section, False))
                    k = j + len(part)
        pos += len(line)
    return out


def diff_edits(current: str, proposal: str) -> List[dict]:
    """A whole-report rewrite (the chat's `edit_proposal`) as surgical find / replace edits on `current`, one per run
    of changed sentences, so the rail can offer each with Apply (live b4e8e644: the model returned only a rewrite and
    the rail showed nothing). Mechanical: a sentence diff, never a judgement; whitespace-only changes are no change.
    An inserted sentence rides on the sentence before it (or after it, at a section start). No edits when a change
    touches a heading, a `find` is not unique, or more than MAX_DIFF_EDITS runs changed."""
    if not current or not proposal:
        return []
    cu, nu = _units(current), _units(proposal)
    ops = difflib.SequenceMatcher(None, [u[2] for u in cu], [u[2] for u in nu], autojunk=False).get_opcodes()
    edits: List[dict] = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        new = " ".join(u[2] for u in nu[j1:j2])
        if any(u[4] for u in cu[i1:i2]) or any(u[4] for u in nu[j1:j2]):
            return []                                       # a heading moved or changed: restructure
        if tag == "insert":
            if i1 > 0 and not cu[i1 - 1][4]:
                a, b, _, section, _ = cu[i1 - 1]
                find = current[a:b]
                edit = {"section": section or "", "find": find, "replace": f"{find} {new}"}
            elif i1 < len(cu) and not cu[i1][4]:
                a, b, _, section, _ = cu[i1]
                find = current[a:b]
                edit = {"section": section or "", "find": find, "replace": f"{new} {find}"}
            else:
                return []
        else:
            if len({u[3] for u in cu[i1:i2]}) > 1:
                return []                                   # one edit never spans two sections
            a, b, section = cu[i1][0], cu[i2 - 1][1], cu[i1][3]
            edit = {"section": section or "", "find": current[a:b], "replace": new}
        if current.count(edit["find"]) == 1:              # else it cannot be placed safely: skipped
            edits.append(edit)
    return edits if len(edits) <= MAX_DIFF_EDITS else []


PROPOSAL_REPLY = "I've drafted the changes for you. Please review and apply them below."
NO_EDIT_REPLY = ("I couldn't turn that into an edit that applies safely to the report. Tell me which sentence to "
                 "change and how, and I'll draft it as a single edit.")


def edits_for_reply(raw_edits: List[dict], current: str, proposal: Optional[str]) -> List[dict]:
    """The model's surgical edits; when it gave none but wrote a whole-report rewrite, the rewrite as edits."""
    return raw_edits if raw_edits or not proposal else diff_edits(current, proposal)


def reply_text(response_text: str, verified: List[dict]) -> str:
    """Never promise edits "below" that the rail will not show (no verified edit to Apply)."""
    if response_text == PROPOSAL_REPLY and not any(e.get("verified") for e in verified):
        return NO_EDIT_REPLY
    return response_text


def verify_chat_edits(report: str, edits: Iterable[dict], dictation: str, history: str,
                      sections: Optional[List[str]] = None) -> List[dict]:
    """Each edit → {section, find, replace, verified, failed}. Spec §8 code guards only (the one-click rules)."""
    out = []
    for e in edits:
        find, new, section = e.get("find") or "", e.get("replace") or "", e.get("section") or ""
        if not find.strip():
            fails = ["missing_find"]
        elif find == new:
            fails = ["no_change"]
        else:
            edit = Edit(mode="replace", find=find, replace=new, section=section or None)
            fails = list(dict.fromkeys(guard_failures(report, edit, CHAT_KIND, dictation, history,
                                                      sections=sections, item_section=section or None)))
        out.append({"section": section, "find": find, "replace": new, "verified": not fails, "failed": fails})
    return out


def _compact(it: Any) -> dict:
    get = it.get if isinstance(it, dict) else (lambda k: getattr(it, k, None))
    return {"id": _s(get("id")), "section": _s(get("section")), "kind": _s(get("kind")), "label": _s(get("label"))}


def resolve_open_items(open_items: Optional[list], stored: Iterable[Any]) -> List[dict]:
    """Ids are looked up in the stored items (unknown ids are dropped); compact dicts are kept as given."""
    by_id = {getattr(s, "id", None): s for s in stored}
    out = []
    for o in open_items or []:
        if isinstance(o, str):
            if o in by_id:
                out.append(_compact(by_id[o]))
        elif isinstance(o, dict) and (o.get("label") or o.get("id") in by_id):
            out.append(_compact(by_id[o["id"]]) if not o.get("label") else _compact(o))
    return out[:OPEN_ITEMS_CAP]


def format_open_items_block(items: List[dict]) -> str:
    if not items:
        return ""
    lines = [f"- [{i.get('section') or 'report'}] {i.get('label')}" + (f" ({i['kind']})" if i.get("kind") else "")
             for i in items]
    return ("## Open review items\n"
            "These are already shown to the radiologist in the review rail. Do not propose these again, as edits "
            "or as suggestions, unless the user asks about one directly.\n" + "\n".join(lines))


def report_sources(report: Any) -> Tuple[str, str, List[str]]:
    """(dictation, clinical history, section names) for the guards, from the stored report row."""
    v = ((report.input_data or {}).get("variables") or {}) if isinstance(report.input_data, dict) else {}
    cand = (report.candidate_reports or [None])[0] or {}
    sections = list(cand.get("sections") or []) if isinstance(cand, dict) else []
    return _s(v.get("FINDINGS")), _s(v.get("CLINICAL_HISTORY")), sections
