"""Chat edits (spec §12.5, Plan 3 D1): the report chat reply carries surgical `edits[]` alongside prose.

The model writes edits as one decoded JSON string (`edits_json`) on its existing tool call, so its schema stays flat.
Code parses them, and every edit goes through the review engine's one-click code guards
(`review_engine.verifier.guard_failures`) against the current report text. An edit that fails comes back with
`verified: false` and its failure codes, and the rail shows it without Apply.

The request's open review items go into the model context, so chat does not propose them again."""
from __future__ import annotations

import json
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
    "`section` is the report heading the span sits under. Leave this out for whole-report restructuring."
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
