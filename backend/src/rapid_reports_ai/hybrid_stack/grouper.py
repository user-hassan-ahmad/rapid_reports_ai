"""The grouper: one Qwen call returns labels for new sentences; code applies them (spec §3.4, §3.5)."""
from __future__ import annotations

import os

from pydantic import BaseModel, Field

from .http import post_json
from .schemas import CONCLUSION, GENERAL, TECHNIQUE, Region
from .units import PartOut, StackUnit


class Part(BaseModel):
    text: str
    group: str


class Placement(BaseModel):
    # Field order is the decoding order of the JSON-schema call: keep covers before attach_to and parts.
    # With attach_to/parts first, Cerebras Qwen ran away to the length limit on every reply (lab, 6/6).
    id: int
    group: str
    structure: str | None = None
    covers: list[str] = Field(default_factory=list)
    attach_to: int | None = None
    parts: list[Part] = Field(default_factory=list)


class GrouperOut(BaseModel):
    placements: list[Placement]


def _norm(name: str | None, groups: list[str]) -> str | None:
    key = (name or "").strip().lower()
    return next((g for g in groups if g.lower() == key), None)


def valid_parts(sentence: str, parts: list[Part]) -> bool:
    """Parts are exact pieces of the sentence that together cover all of it, in order (only
    whitespace between them): nothing the radiologist said can fall between two parts."""
    pos = 0
    for p in parts:
        if not any(c.isalnum() for c in p.text):
            return False
        i = sentence.find(p.text, pos)
        if i < 0 or sentence[pos:i].strip():
            return False
        if pos and i == pos and sentence[pos - 1].isalnum() and sentence[i].isalnum():
            return False  # a boundary inside a word
        pos = i + len(p.text)
    return len(parts) >= 2 and not sentence[pos:].strip()


def apply_placements(units: list[StackUnit], placements: list[Placement], new_ids: list[int],
                     groups: list[str]) -> list[str]:
    """Write the grouper's labels onto the new units, enforcing the invariants. Placements for
    any other unit (placed earlier, or pinned) are ignored. Returns the problems for the log."""
    problems: list[str] = []
    by_id = {u.id: u for u in units}
    wanted = {p.id: p for p in placements if p.id in new_ids}
    non_regions = {TECHNIQUE, GENERAL, CONCLUSION}
    for i in sorted(new_ids):
        if i not in by_id:
            problems.append(f"[{i}] unknown unit")
            continue
        u, p = by_id[i], wanted.get(i)
        if u.pinned:
            continue
        if p is None:
            u.group, u.attach_to, u.parts = GENERAL, None, None
            problems.append(f"[{i}] no placement")
            continue
        g = _norm(p.group, groups)
        if g is None:
            problems.append(f"[{i}] unknown group {p.group!r}")
            g = GENERAL
        att = p.attach_to if p.attach_to in by_id and p.attach_to < i else None
        if p.attach_to is not None and att is None:
            problems.append(f"[{i}] bad attach_to {p.attach_to}")
        parts = None
        if p.parts and att is not None:
            problems.append(f"[{i}] parts on attached sentence")
        elif p.parts:
            part_groups = [_norm(x.group, groups) or GENERAL for x in p.parts]
            if valid_parts(u.text, p.parts) and len(set(part_groups)) > 1:
                parts = [PartOut(text=x.text, group=pg) for x, pg in zip(p.parts, part_groups)]
            else:
                problems.append(f"[{i}] rejected parts")
        covers = [c for c in (_norm(x, groups) for x in p.covers) if c and c not in non_regions]
        if att is not None:
            parent_group = by_id[att].group
            if parent_group is None:
                problems.append(f"[{i}] parent {att} unplaced")
                parent_group = g
            u.group = parent_group
        elif parts:
            u.group = parts[0].group
            if u.group != g:
                problems.append(f"[{i}] group {g!r} replaced by first part's {u.group!r}")
        else:
            u.group = g
        u.attach_to, u.parts, u.structure, u.covers = att, parts, (p.structure or None), list(dict.fromkeys(covers))
    return problems


# The lab's validated prompt (scripts/hybrid_stack_lab/lab.py, schema variant) with one decided change:
# a list of structures sharing one predicate that spans two or more regions goes to General (spec §3.4).
GROUPER_SYSTEM = """You organise a radiologist's dictation into report groups. You never write or change text: you only give each sentence a label. Code places the radiologist's own sentences under your labels.

Input: the scan type, the ordered list of GROUPS, the sentences already PLACED (with their groups; context only, fixed), and the NEW sentences to place, each with an id.

For each NEW sentence return:
- group: exactly one name from GROUPS.
- attach_to: the id of an earlier sentence (placed or new) when this sentence cannot stand on its own because it continues that sentence's observation: it refers back to it ("it", "this", "the lesion") or only adds a further attribute of the same observation (size, behaviour on another sequence or phase, effect it causes). A fragment with no verb of its own that completes the sentence just before it attaches to that sentence. Otherwise null. An attached sentence takes its parent's group; give the parent's group.
- structure: the specific structure the sentence is about, in a few words (for example the organ, vessel, level or space); empty for Technique, General and Conclusion.

- covers: the regions (names from GROUPS, never Technique, General or Conclusion) about which the sentence makes a definitive claim — a finding, a measurement, a qualifier or an explicit normality statement. Count a region when the claim is direct (its structure is the subject, the location, or the modifier of the claim) or collective (a definitive claim over a recognisable anatomical group, such as several named organs or a named organ system, that the region's structures genuinely belong to). Do not count: a bare mention with nothing asserted; a structure only touched or affected by a finding about another structure; a vague statement with no anatomical scope ("no other abnormality", "otherwise normal"); a group the region does not clearly belong to. Usually the sentence's own region; several for a collective; empty when nothing qualifies. Fill covers for every sentence, including Conclusion sentences.

GROUPS are broad regions of a fixed schema; each lists what it includes. Match the structure to the region whose list covers it, or the anatomically closest region; use the "Other findings" region only when no region is close.
- parts: only when one sentence joins independent clauses about structures that belong to different groups, each clause with its own subject and its own predicate (two statements run together in one breath). Give each part as an exact, unaltered, contiguous piece of the sentence, in order, each with its own group. The parts together must cover the whole sentence: keep joining words and punctuation on the neighbouring part. Every part must read as a complete statement on its own. Two statements run together because a full stop is missing count as two clauses. Never split structures that share one predicate (a list of structures followed by a single "are normal" / "are intact" / "are clear"): that sentence stays whole, in General when its structures span two or more regions (list each of them in covers), otherwise in their region. A single observation that involves several structures (a finding extending into, invading or compressing a neighbour) is one claim: never split it. Leave parts empty otherwise.

Placement rules:
- One home: the group of the structure the observation is about — where the abnormality is, not what it touches or affects.
- Interpretation attached to a single observation ("in keeping with", "likely", a classification of that one finding) stays with that observation.
- Conclusion: once the radiologist has begun the conclusion (a spoken cue, or a closing summary), every following sentence belongs to Conclusion too, including short restatements of single findings, until the radiologist clearly returns to describing the images in detail. A sentence that is only the cue word itself also belongs to Conclusion.
- Conclusion also takes: the radiologist's overall summary, diagnosis across findings, differential, staging summary, recommendation or advice, and anything introduced by a spoken summary cue (impression, conclusion, in summary, overall, so). Also a sentence that restates findings already placed as a closing summary, even without a cue.
- Technique: protocol, sequences, contrast, phases, image quality, limitations, and which prior studies were compared.
- General: only a sweeping statement that names no specific structure ("no other abnormality", "the rest is normal"), or a list of structures sharing one predicate that spans two or more regions (list each of those regions in covers). A statement about one named structure or space never goes to General: use its region.
- A comparison with a prior study about one finding belongs with that finding's structure.
- Never split structures that share one predicate; such a sentence goes to General when its structures span two or more regions.

Return one entry per NEW sentence, in order."""

GROUPER_USER = """Scan type: {scan_type}

GROUPS (in report order):
{groups}

PLACED (fixed, context only):
{placed}

NEW:
{new}"""

ENDPOINTS = (
    ("https://api.cerebras.ai/v1/chat/completions", "CEREBRAS_API_KEY", "qwen-3.8-27b"),
    ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY", "qwen/qwen3.8-27b"),
)
SETTINGS = {"temperature": 0.0, "max_tokens": 4000, "reasoning_effort": "none"}
TIMEOUT_S = 15.0


def grouper_user(scan_type: str, regions: list[Region], units: list[StackUnit], new_ids: list[int]) -> str:
    from .schemas import groups_for
    includes = {r.name: r.includes for r in regions}
    listing = "\n".join(f"{g} — includes: {includes[g]}" if g in includes else g for g in groups_for(regions))
    placed = "\n".join(f"[{u.id}] ({u.group}) {u.text}" for u in units if u.id not in new_ids) or "(none)"
    new = "\n".join(f"[{u.id}] {u.text}" for u in units if u.id in new_ids)
    return GROUPER_USER.format(scan_type=scan_type or "(not specified)", groups=listing, placed=placed, new=new)


async def place(scan_type: str, regions: list[Region], units: list[StackUnit], new_ids: list[int],
                transport=None) -> tuple[list[Placement], str | None, str | None]:
    """(placements, model used, error). Cerebras, then Groq; a direct JSON-schema call, because
    pydantic-ai tool output failed on this nested schema with Qwen (lab 2026-10-10)."""
    user = grouper_user(scan_type, regions, units, new_ids)
    err = None
    for url, key_env, model in ENDPOINTS:
        key = os.environ.get(key_env)
        if not key:
            continue
        try:
            r = await post_json(url, key, {
                "model": model, **SETTINGS,
                "messages": [{"role": "system", "content": GROUPER_SYSTEM}, {"role": "user", "content": user}],
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "placements", "schema": GrouperOut.model_json_schema()}}}, TIMEOUT_S, transport)
            r.raise_for_status()
            choice = r.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                err = f"{model}: runaway reply (finish_reason length)"
                continue
            out = GrouperOut.model_validate_json(choice["message"]["content"])
            if new_ids and not out.placements:
                err = f"{model}: empty placements"
                continue
            return out.placements, model, None
        except Exception as e:  # next endpoint; the caller fails open (sentences stay unplaced)
            err = f"{model}: {type(e).__name__}: {e}"
    return [], None, err or "no grouper endpoint configured"
