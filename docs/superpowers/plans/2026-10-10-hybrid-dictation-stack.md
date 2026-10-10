# Hybrid Dictation Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scratchpad's Verbatim/Structured tabs with one view that shows the radiologist's own sentences grouped into report regions, with checklist pills derived from the grouping, while the old Structured build, `/sections` and Jev pills keep running in shadow.

**Architecture:** A stateless backend package `rapid_reports_ai/hybrid_stack/` turns the verbatim scratchpad text into sentence units and asks one Qwen call (the *grouper*) for labels only (region, structure, link, exact split, covers); code enforces invariants; a Jev question decides the conclusion boundary. Regions come from a fixed schema library (quick path; a reconciler composes and caches families for unseen scan types) or from the template's grammar structure (template path). The frontend keeps the units, sends them back each update (sticky placement), renders the grouped view, and drives the pills from the server's derived pills. The dictation machinery (Deepgram, two-pass, v2 write path, verbatim text) is untouched.

**Tech Stack:** FastAPI + pydantic v2 + SQLAlchemy/Alembic (Postgres prod, SQLite tests), httpx, pytest (asyncio auto); SvelteKit (Svelte 5), Vitest (node + browser projects), CodeMirror 6.

**Spec:** `docs/superpowers/specs/2026-10-10-hybrid-dictation-stack-design.md`. **Lab:** `backend/src/rapid_reports_ai/scripts/hybrid_stack_lab/` (source of every prompt below). **Replay fixtures:** `backend/tests/fixtures/hybrid_stack/`.

**Conventions for every task:**
- Backend commands run from `backend/`: tests `PYTHONPATH=src .venv/bin/python -m pytest <path> -q`.
- Frontend commands run from `frontend/`: tests `npx vitest run <path>`, types `bun run check`.
- Commit after each task with the message given; end each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Prompts are case-agnostic (structural rules, no single-domain clinical examples) — do not add examples to them.

---

## File map

**Backend — create**
| File | Responsibility |
|---|---|
| `backend/src/rapid_reports_ai/hybrid_stack/__init__.py` | package docstring |
| `.../hybrid_stack/schema_library.json` | region library, families, levels (data) |
| `.../hybrid_stack/schemas.py` | `Region`, library access, family regions, fixed group names, scan-type key |
| `.../hybrid_stack/units.py` | sentence split, `StackUnit`, sticky matching |
| `.../hybrid_stack/http.py` | one keep-alive httpx client per event loop |
| `.../hybrid_stack/grouper.py` | grouper prompt, call (Cerebras → Groq), invariants (`apply_placements`) |
| `.../hybrid_stack/gate.py` | Jev conclusion boundary: live gate + uncued closing check |
| `.../hybrid_stack/family.py` | Jev family choice with a "none" option |
| `.../hybrid_stack/reconciler.py` | Qwen reconciler for unseen scan types + validation |
| `.../hybrid_stack/template.py` | regions from a template's grammar structure |
| `.../hybrid_stack/pills.py` | pills derived from `covers` |
| `.../hybrid_stack/service.py` | `resolve_schema`, `group_update`, `close_update` |
| `.../hybrid_stack/routes.py` | `/api/canvas/stack/*` endpoints, flag, reviewer endpoints |
| `backend/migrations/versions/20261010120000_add_hybrid_stack_tables.py` | `stack_schema_families`, `dictation_stack_logs` |
| `backend/src/rapid_reports_ai/scripts/hybrid_stack_eval.py` | replay eval against the fixtures (real models) |
| `backend/tests/test_hybrid_stack_*.py` | unit + route tests |

**Backend — modify:** `database/models.py` (two models), `main.py` (include router, settings status flag).

**Frontend — create:** `frontend/src/lib/hybrid-stack/{types.ts,flag.ts,stackState.ts,api.ts,HybridStackView.svelte}` + tests; `frontend/src/routes/dev/hybrid-stack/{+page.ts,+page.svelte}`; `frontend/src/routes/stack-families/+page.svelte`.

**Frontend — modify:** `src/lib/components/DictationScratchpad.svelte`, `src/routes/components/IntelliDictateTab.svelte`, `src/routes/components/TemplateForm.svelte`, `src/routes/+page.svelte`.

---

# Part A — Backend engine

### Task 1: Package, schema library, `schemas.py`

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/__init__.py`, `.../hybrid_stack/schema_library.json`, `.../hybrid_stack/schemas.py`
- Test: `backend/tests/test_hybrid_stack_schemas.py`

- [ ] **Step 1: Create the package and copy the library data**

```bash
mkdir -p src/rapid_reports_ai/hybrid_stack
cp src/rapid_reports_ai/scripts/hybrid_stack_lab/schemas.json src/rapid_reports_ai/hybrid_stack/schema_library.json
```

`src/rapid_reports_ai/hybrid_stack/__init__.py`:
```python
"""Hybrid dictation stack: the radiologist's verbatim sentences, grouped into report regions.

Spec: docs/superpowers/specs/2026-10-10-hybrid-dictation-stack-design.md. The words never change:
models return labels only and code assembles the view.
"""
```

- [ ] **Step 2: Add the generic family to the library**

Edit `schema_library.json`: add five regions under `"regions"` and one family under `"families"` (keep everything else as copied):

```json
"generic_head": {"name": "Head", "includes": "brain, skull, face, orbits, sinuses"},
"generic_neck": {"name": "Neck", "includes": "neck soft tissues, airway, thyroid, cervical nodes and vessels"},
"generic_chest": {"name": "Chest", "includes": "lungs, pleura, heart, mediastinum, chest wall"},
"generic_abdomen": {"name": "Abdomen", "includes": "abdominal organs, bowel, peritoneum, abdominal vessels and nodes"},
"generic_pelvis": {"name": "Pelvis", "includes": "bladder, pelvic organs, pelvic bones and nodes"},
```
```json
"generic": {"description": "Fallback when no family describes the examination",
  "regions": ["generic_head", "generic_neck", "generic_chest", "generic_abdomen", "generic_pelvis", "spine_all", "limbs", "other"]}
```

- [ ] **Step 3: Write the failing test**

`backend/tests/test_hybrid_stack_schemas.py`:
```python
from rapid_reports_ai.hybrid_stack import schemas as s


def test_every_family_resolves_with_unique_names_and_ends_with_other():
    for fam in list(s.library()["families"]):
        names = [r.name for r in s.family_regions(fam)]
        assert len(names) == len(set(n.lower() for n in names)), fam
        assert names[-1] == s.OTHER, fam


def test_levels_expand():
    names = [r.name for r in s.family_regions("lumbar_spine")]
    assert "L4/5" in names and "L5/S1" in names


def test_generic_is_not_offered_as_a_choice():
    assert s.GENERIC_FAMILY not in s.family_keys()
    assert "abdomen_pelvis" in s.family_keys()


def test_groups_and_pills():
    regions = s.family_regions("knee")
    groups = s.groups_for(regions)
    assert groups[0] == s.TECHNIQUE and groups[-2:] == [s.GENERAL, s.CONCLUSION]
    assert s.OTHER not in s.pill_regions(regions)


def test_scan_key_normalises():
    assert s.scan_key("  MRI   Left  Ankle ") == "mri left ankle"
```

- [ ] **Step 4: Run it to see it fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_schemas.py -q`
Expected: FAIL — `ModuleNotFoundError: ... hybrid_stack.schemas`

- [ ] **Step 5: Implement `schemas.py`**

```python
"""Region lists for the hybrid stack (spec §3.3): the schema library and the fixed groups."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

TECHNIQUE, GENERAL, CONCLUSION, OTHER = "Technique", "General", "Conclusion", "Other findings"
FIXED = (TECHNIQUE, GENERAL, CONCLUSION)
GENERIC_FAMILY = "generic"


class Region(BaseModel):
    name: str
    includes: str


@lru_cache(maxsize=1)
def library() -> dict:
    return json.loads(Path(__file__).with_name("schema_library.json").read_text())


def family_keys() -> list[str]:
    """Families offered to Jev and the reconciler (the generic fallback is never offered)."""
    return [k for k in library()["families"] if k != GENERIC_FAMILY]


def family_regions(family: str) -> list[Region]:
    lib = library()
    out: list[Region] = []
    for key in lib["families"][family]["regions"]:
        if key.startswith("@"):
            out += [Region(name=lvl, includes=lib["level_includes"]) for lvl in lib["levels"][key[1:]]]
        else:
            r = lib["regions"][key]
            out.append(Region(name=r["name"], includes=r["includes"]))
    return out


def other_region() -> Region:
    r = library()["regions"]["other"]
    return Region(name=r["name"], includes=r["includes"])


def groups_for(regions: list[Region]) -> list[str]:
    return [TECHNIQUE] + [r.name for r in regions] + [GENERAL, CONCLUSION]


def pill_regions(regions: list[Region]) -> list[str]:
    """The checklist pills: every region except the catch-all."""
    return [r.name for r in regions if r.name != OTHER]


def scan_key(scan_type: str) -> str:
    return re.sub(r"\s+", " ", (scan_type or "").strip().lower())
```

- [ ] **Step 6: Run the test to see it pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_schemas.py -q`
Expected: `5 passed`

- [ ] **Step 7: Commit**

```bash
git add src/rapid_reports_ai/hybrid_stack tests/test_hybrid_stack_schemas.py
git commit -m "feat(hybrid-stack): schema library and region helpers"
```

---

### Task 2: Sentence units and sticky matching (`units.py`)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/units.py`
- Test: `backend/tests/test_hybrid_stack_units.py`

- [ ] **Step 1: Write the failing test**

```python
from rapid_reports_ai.hybrid_stack.units import StackUnit, match_units, sentences


def test_split_keeps_decimals_and_breaks_lines():
    assert sentences("A 5.2 cm mass. It is new.\nNo effusion.") == ["A 5.2 cm mass.", "It is new.", "No effusion."]


def test_new_text_gives_new_units():
    units, new = match_units("Liver normal. Spleen normal.", [])
    assert [u.text for u in units] == ["Liver normal.", "Spleen normal."] and new == [0, 1]


def test_sticky_keeps_placement_and_remaps_links():
    prev = [StackUnit(id=0, text="A mass.", group="Liver"),
            StackUnit(id=1, text="It measures 2 cm.", group="Liver", attach_to=0)]
    units, new = match_units("Technique line. A mass. It measures 2 cm.", prev)
    assert new == [0]
    assert units[1].group == "Liver" and units[1].id == 1
    assert units[2].attach_to == 1


def test_link_to_a_removed_sentence_is_cut():
    prev = [StackUnit(id=0, text="A mass.", group="Liver"),
            StackUnit(id=1, text="It measures 2 cm.", group="Liver", attach_to=0)]
    units, new = match_units("It measures 2 cm.", prev)
    assert units[0].attach_to is None and new == []


def test_heading_only_sentences_are_flagged():
    units, _ = match_units("Conclusion. Acute appendicitis.", [])
    assert units[0].heading is True and units[1].heading is False
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_units.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `units.py`**

```python
"""Sentence units of the verbatim scratchpad and sticky matching (spec §3.2, §3.5)."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..spoken_format import heading_only

_SPLIT = re.compile(r"(?<=[.?!])\s+(?=\S)|\n+")


def sentences(text: str) -> list[str]:
    """Break at . ? ! followed by whitespace (decimals stay whole) and at line breaks."""
    return [s.strip() for s in _SPLIT.split(text or "") if s.strip()]


class PartOut(BaseModel):
    text: str
    group: str


class StackUnit(BaseModel):
    id: int
    text: str
    group: str | None = None
    structure: str | None = None
    attach_to: int | None = None
    parts: list[PartOut] | None = None
    covers: list[str] = Field(default_factory=list)
    pinned: bool = False  # moved by the radiologist: never changed by the server
    heading: bool = False  # only a heading cue ("Conclusion."): hidden in the view


def match_units(text: str, previous: list[StackUnit]) -> tuple[list[StackUnit], list[int]]:
    """Units for `text`. A sentence whose exact text was in `previous` keeps its placement (sticky).
    Ids are positions in the new list; links are remapped; a link to a sentence that no longer
    exists, or that would point forwards, is cut. Returns (units, ids of new sentences)."""
    pool: dict[str, list[StackUnit]] = {}
    for u in previous:
        pool.setdefault(u.text, []).append(u)
    old_to_new: dict[int, int] = {}
    units: list[StackUnit] = []
    new_ids: list[int] = []
    for i, s in enumerate(sentences(text)):
        if pool.get(s):
            old = pool[s].pop(0)
            old_to_new[old.id] = i
            units.append(old.model_copy(update={"id": i}))
        else:
            units.append(StackUnit(id=i, text=s, heading=heading_only(s) is not None))
            new_ids.append(i)
    for u in units:
        if u.attach_to is not None:
            target = old_to_new.get(u.attach_to)
            u.attach_to = target if target is not None and target < u.id else None
    return units, new_ids
```

Note for the remap: only retained units carry an `attach_to`, and it still holds the *old* id when the loop runs, which is why it is looked up in `old_to_new`.

- [ ] **Step 4: Run the test to see it pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_units.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/hybrid_stack/units.py tests/test_hybrid_stack_units.py
git commit -m "feat(hybrid-stack): sentence units with sticky matching"
```

---

### Task 3: Shared HTTP client (`http.py`)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/http.py`
- Test: `backend/tests/test_hybrid_stack_http.py`

- [ ] **Step 1: Write the failing test**

```python
import httpx

from rapid_reports_ai.hybrid_stack.http import post_json


async def test_post_json_uses_the_given_transport():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["Authorization"]
        return httpx.Response(200, json={"ok": True})

    r = await post_json("https://x.test/v1", "k", {"a": 1}, 5.0, transport=httpx.MockTransport(handler))
    assert r.json() == {"ok": True} and seen["auth"] == "Bearer k"
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_http.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `http.py`**

```python
"""One keep-alive httpx client per event loop for the stack's model calls (as jev_client does)."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=20, keepalive_expiry=60.0)
_SHARED: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None


def _shared() -> httpx.AsyncClient:
    global _SHARED
    loop = asyncio.get_running_loop()
    if _SHARED is None or _SHARED[0] is not loop or _SHARED[1].is_closed:
        _SHARED = (loop, httpx.AsyncClient(limits=_LIMITS))
    return _SHARED[1]


async def post_json(url: str, api_key: str, body: dict[str, Any], timeout_s: float,
                    transport: httpx.AsyncBaseTransport | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if transport is not None:  # tests
        async with httpx.AsyncClient(transport=transport) as c:
            return await c.post(url, json=body, headers=headers, timeout=timeout_s)
    return await _shared().post(url, json=body, headers=headers, timeout=timeout_s)
```

- [ ] **Step 4: Run the test to see it pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_http.py -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/hybrid_stack/http.py tests/test_hybrid_stack_http.py
git commit -m "feat(hybrid-stack): keep-alive http client"
```

---

### Task 4: Grouper — invariants (`apply_placements`, `valid_parts`)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/grouper.py` (models + invariants in this task; the call in Task 5)
- Test: `backend/tests/test_hybrid_stack_grouper.py`

- [ ] **Step 1: Write the failing test**

```python
from rapid_reports_ai.hybrid_stack.grouper import Part, Placement, apply_placements, valid_parts
from rapid_reports_ai.hybrid_stack.units import StackUnit

GROUPS = ["Technique", "Liver", "Kidneys", "Other findings", "General", "Conclusion"]


def _units(*texts):
    return [StackUnit(id=i, text=t) for i, t in enumerate(texts)]


def test_parts_must_cover_the_sentence_exactly():
    s = "Kidneys are normal, and there is a 3 cm liver cyst."
    assert valid_parts(s, [Part(text="Kidneys are normal,", group="Kidneys"),
                           Part(text="and there is a 3 cm liver cyst.", group="Liver")])
    assert not valid_parts(s, [Part(text="Kidneys are normal", group="Kidneys"),
                               Part(text="there is a 3 cm liver cyst.", group="Liver")])  # ", and" dropped
    assert not valid_parts(s, [Part(text=s, group="Kidneys")])  # one part is not a split


def test_attached_sentence_takes_parent_group_and_covers_are_filtered():
    units = _units("A liver lesion.", "It measures 2 cm.")
    problems = apply_placements(units, [
        Placement(id=0, group="Liver", structure="liver", covers=["Liver", "General", "Nope"]),
        Placement(id=1, group="Kidneys", attach_to=0, covers=["Liver"]),
    ], [0, 1], GROUPS)
    assert units[0].covers == ["Liver"]
    assert units[1].group == "Liver" and units[1].attach_to == 0
    assert problems == []


def test_unknown_group_and_missing_placement_go_to_general():
    units = _units("One.", "Two.")
    problems = apply_placements(units, [Placement(id=0, group="Spleen")], [0, 1], GROUPS)
    assert units[0].group == "General" and units[1].group == "General"
    assert len(problems) == 2


def test_forward_or_self_link_is_cut():
    units = _units("One.", "Two.")
    apply_placements(units, [Placement(id=0, group="Liver", attach_to=1), Placement(id=1, group="Liver", attach_to=1)],
                     [0, 1], GROUPS)
    assert units[0].attach_to is None and units[1].attach_to is None


def test_split_into_one_group_is_not_a_split():
    units = _units("Liver and spleen normal.")
    apply_placements(units, [Placement(id=0, group="Liver", parts=[Part(text="Liver", group="Liver"),
                                                                   Part(text="and spleen normal.", group="Liver")])],
                     [0], GROUPS)
    assert units[0].parts is None


def test_placements_for_old_or_pinned_units_are_ignored():
    units = [StackUnit(id=0, text="Old.", group="Liver", pinned=True), StackUnit(id=1, text="New.")]
    apply_placements(units, [Placement(id=0, group="Kidneys"), Placement(id=1, group="Kidneys")], [1], GROUPS)
    assert units[0].group == "Liver" and units[1].group == "Kidneys"
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_grouper.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the models and invariants in `grouper.py`**

```python
"""The grouper: one Qwen call returns labels for new sentences; code applies them (spec §3.4, §3.5)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .schemas import CONCLUSION, GENERAL, TECHNIQUE
from .units import PartOut, StackUnit


class Part(BaseModel):
    text: str
    group: str


class Placement(BaseModel):
    id: int
    group: str
    structure: str | None = None
    attach_to: int | None = None
    parts: list[Part] = Field(default_factory=list)
    covers: list[str] = Field(default_factory=list)


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
        if not p.text.strip():
            return False
        i = sentence.find(p.text, pos)
        if i < 0 or sentence[pos:i].strip():
            return False
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
    for i in new_ids:
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
        if p.parts:
            part_groups = [_norm(x.group, groups) or GENERAL for x in p.parts]
            if valid_parts(u.text, p.parts) and len(set(part_groups)) > 1:
                parts = [PartOut(text=x.text, group=pg) for x, pg in zip(p.parts, part_groups)]
            else:
                problems.append(f"[{i}] rejected parts")
        covers = [c for c in (_norm(x, groups) for x in p.covers) if c and c not in non_regions]
        u.group = by_id[att].group if att is not None else g
        u.attach_to, u.parts, u.structure, u.covers = att, parts, (p.structure or None), list(dict.fromkeys(covers))
    return problems
```

- [ ] **Step 4: Run the test to see it pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_grouper.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/hybrid_stack/grouper.py tests/test_hybrid_stack_grouper.py
git commit -m "feat(hybrid-stack): grouper placement invariants"
```

---

### Task 5: Grouper — prompt and call

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/grouper.py` (append)
- Test: `backend/tests/test_hybrid_stack_grouper.py` (append)

- [ ] **Step 1: Write the failing tests (append)**

```python
import json

import httpx

from rapid_reports_ai.hybrid_stack import grouper as G
from rapid_reports_ai.hybrid_stack.schemas import Region

REGIONS = [Region(name="Liver", includes="liver"), Region(name="Kidneys", includes="kidneys")]


def _llm(body_out: dict, seen: list):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body_out)}}]})
    return httpx.MockTransport(handler)


async def test_place_sends_regions_with_includes_and_only_new_sentences(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    seen = []
    units = [StackUnit(id=0, text="Liver normal.", group="Liver"), StackUnit(id=1, text="Kidneys normal.")]
    out = {"placements": [{"id": 1, "group": "Kidneys", "structure": "kidneys", "covers": ["Kidneys"]}]}
    placements, model, err = await G.place("CT abdomen", REGIONS, units, [1], transport=_llm(out, seen))
    assert err is None and model == "qwen-3.8-27b" and placements[0].group == "Kidneys"
    body = seen[0][1]
    user = body["messages"][1]["content"]
    assert "Liver — includes: liver" in user
    assert "[0] (Liver) Liver normal." in user and "[1] Kidneys normal." in user
    assert body["response_format"]["type"] == "json_schema" and body["reasoning_effort"] == "none"


async def test_place_falls_back_to_groq_then_reports_error(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(500)
    placements, model, err = await G.place("CT", REGIONS, [StackUnit(id=0, text="A.")], [0],
                                           transport=httpx.MockTransport(handler))
    assert placements == [] and model is None and "qwen/qwen3.8-27b" in err
    assert any("cerebras" in c for c in calls) and any("groq" in c for c in calls)
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_grouper.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'place'`

- [ ] **Step 3: Append the prompt and the call to `grouper.py`**

Add to the imports at the top: `import os`, `from .http import post_json`, `from .schemas import Region`.

Append:
```python
GROUPER_SYSTEM = """You organise a radiologist's dictation into the regions of a report. You never write or change text: you only give each sentence labels. Code places the radiologist's own sentences under your labels.

Input: the scan type, the ordered list of GROUPS (each region lists what it includes), the sentences already PLACED (with their groups; context only, fixed), and the NEW sentences to place, each with an id.

For each NEW sentence return:
- group: exactly one name from GROUPS.
- structure: the specific structure the sentence is about, in a few words (for example the organ, vessel, level or space); empty for Technique, General and Conclusion.
- attach_to: the id of an earlier sentence (placed or new) when this sentence cannot stand on its own because it continues that sentence's observation: it refers back to it ("it", "this", "the lesion") or only adds a further attribute of the same observation (size, behaviour on another sequence or phase, effect it causes). A fragment with no verb of its own that completes the sentence just before it attaches to that sentence. Otherwise null. An attached sentence takes its parent's group; give the parent's group.
- parts: only when one sentence joins independent clauses about structures that belong to different groups, each clause with its own subject and its own predicate (two statements run together in one breath). Give each part as an exact, unaltered, contiguous piece of the sentence, in order, each with its own group. The parts together must cover the whole sentence: keep joining words and punctuation on the neighbouring part. Every part must read as a complete statement on its own. Two statements run together because a full stop is missing count as two clauses. A single observation that involves several structures (a finding extending into, invading or compressing a neighbour) is one claim: never split it. Never split structures that share one predicate. Leave parts empty otherwise.
- covers: the regions (names from GROUPS, never Technique, General or Conclusion) about which the sentence makes a definitive claim — a finding, a measurement, a qualifier or an explicit normality statement. Count a region when the claim is direct (its structure is the subject, the location, or the modifier of the claim) or collective (a definitive claim over a recognisable anatomical group, such as several named organs or a named organ system, that the region's structures genuinely belong to). Do not count: a bare mention with nothing asserted; a structure only touched or affected by a finding about another structure; a vague statement with no anatomical scope ("no other abnormality", "otherwise normal"); a group the region does not clearly belong to. Usually the sentence's own region; several for a collective; empty when nothing qualifies. Fill covers for every sentence, including Conclusion sentences.

Match each structure to the region whose includes list covers it, or the anatomically closest region; use the "Other findings" region only when no region is close.

Placement rules:
- One home: the group of the structure the observation is about — where the abnormality is, not what it touches or affects.
- Interpretation attached to a single observation ("in keeping with", "likely", a classification of that one finding) stays with that observation.
- Conclusion: once the radiologist has begun the conclusion (a spoken cue, or a closing summary), every following sentence belongs to Conclusion too, including short restatements of single findings, until the radiologist clearly returns to describing the images in detail. A sentence that is only the cue word itself also belongs to Conclusion.
- Conclusion also takes: the radiologist's overall summary, diagnosis across findings, differential, staging summary, recommendation or advice, and anything introduced by a spoken summary cue (impression, conclusion, in summary, overall, so).
- Technique: protocol, sequences, contrast, phases, image quality, limitations, and which prior studies were compared.
- General: only a sweeping statement that names no specific structure ("no other abnormality", "the rest is normal"), or a list of structures sharing one predicate that spans two or more regions (list each of those regions in covers). A statement about one named structure or space never goes to General: use its region.
- A comparison with a prior study about one finding belongs with that finding's structure.

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
            out = GrouperOut.model_validate_json(r.json()["choices"][0]["message"]["content"])
            return out.placements, model, None
        except Exception as e:  # next endpoint; the caller fails open (sentences stay unplaced)
            err = f"{model}: {type(e).__name__}: {e}"
    return [], None, err or "no grouper endpoint configured"
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_grouper.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/hybrid_stack/grouper.py tests/test_hybrid_stack_grouper.py
git commit -m "feat(hybrid-stack): grouper prompt and Cerebras/Groq call"
```

---

### Task 6: Conclusion gate (`gate.py`)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/gate.py`
- Test: `backend/tests/test_hybrid_stack_gate.py`

- [ ] **Step 1: Write the failing tests**

```python
import json

import httpx

from rapid_reports_ai.hybrid_stack import gate
from rapid_reports_ai.hybrid_stack.units import StackUnit


def _jev(answers: list[tuple[str, float]], seen: list):
    it = iter(answers)

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        choice, conf = next(it)
        return httpx.Response(200, json={"answers": {"boundary": {"choice": choice, "confidence": conf}}})
    return httpx.MockTransport(handler)


def _u(i, text, group, **kw):
    return StackUnit(id=i, text=text, group=group, **kw)


async def test_gate_asks_only_after_conclusion_and_moves_confident_summary(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = []
    units = [_u(0, "A lesion.", "Liver"), _u(1, "Impression, cancer.", "Conclusion"),
             _u(2, "Lesion is cancer.", "Liver", attach_to=0)]
    log = await gate.conclusion_gate(units, [2], transport=_jev([("summary", 0.9)], seen))
    assert units[2].group == "Conclusion" and units[2].attach_to is None
    assert len(seen) == 1 and "SENTENCE:\nLesion is cancer." in seen[0]["state"]
    assert log[0]["to"] == "Conclusion"


async def test_low_confidence_keeps_grouper_placement(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    units = [_u(0, "Impression, x.", "Conclusion"), _u(1, "Liver lesion 2 cm.", "Liver")]
    await gate.conclusion_gate(units, [1], transport=_jev([("summary", 0.4)], []))
    assert units[1].group == "Liver"


async def test_images_moves_out_of_conclusion(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    units = [_u(0, "In summary, x.", "Conclusion"), _u(1, "Also a renal cyst.", "Conclusion")]
    await gate.conclusion_gate(units, [1], transport=_jev([("images", 0.8)], []))
    assert units[1].group == "General"


async def test_no_conclusion_no_call_and_pinned_skipped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = []
    units = [_u(0, "A.", "Liver"), _u(1, "B.", "Liver", pinned=True)]
    assert await gate.conclusion_gate(units, [1], transport=_jev([], seen)) == [] and seen == []


async def test_closing_check_moves_uncued_summary_last_line(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    units = [_u(0, "Segment 8 lesion with washout.", "Liver"),
             _u(1, "Observation is LI-RADS 5, consistent with HCC.", "Liver")]
    log = await gate.closing_check(units, transport=_jev([("summary", 0.8)], []))
    assert units[1].group == "Conclusion" and log["to"] == "Conclusion"


async def test_closing_check_skips_when_a_conclusion_exists(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    units = [_u(0, "Impression, x.", "Conclusion"), _u(1, "Y.", "Conclusion")]
    assert await gate.closing_check(units, transport=_jev([], [])) is None


async def test_failure_fails_open(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    units = [_u(0, "Impression, x.", "Conclusion"), _u(1, "Liver lesion.", "Liver")]
    log = await gate.conclusion_gate(units, [1], transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert units[1].group == "Liver" and log[0]["choice"].startswith("error")
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_gate.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `gate.py`**

```python
"""Conclusion boundary (spec §3.6): a Jev choice decides whether a sentence after the conclusion
has begun is part of it. Also the uncued closing line, asked once when dictation stops."""
from __future__ import annotations

import asyncio
import os

from ..jev_client import JEV_MODEL, jev_post
from .schemas import CONCLUSION, GENERAL
from .units import StackUnit

MIN_CONF = 0.6  # lab fixture (65 sentences): both wrong answers were below 0.6
TIMEOUT_S = 10.0

BOUNDARY_QUESTION = {
    "type": "choice",
    "instructions": ("The radiologist has already begun their conclusion in the dictation. Decide what the "
                     "SENTENCE does."),
    "criteria": {
        "summary": ("It belongs to the conclusion: it summarises, restates or interprets findings already "
                    "given, states a diagnosis, differential, staging or response, or makes a recommendation "
                    "or communication note."),
        "images": ("It returns to describing the images: it reports an observation, measurement or detail "
                   "that the dictation has not already given, as a finding."),
    },
}
# The uncued closing line has no conclusion yet; the question's premise changes, the options do not.
CLOSING_QUESTION = {**BOUNDARY_QUESTION, "instructions": (
    "The radiologist has finished dictating and gave no conclusion cue. Decide what the final SENTENCE does.")}


def _state(before: list[str], sentence: str) -> str:
    return "DICTATION SO FAR:\n" + " ".join(before) + "\n\nSENTENCE:\n" + sentence


async def ask(before: list[str], sentence: str, question: dict = BOUNDARY_QUESTION,
              transport=None) -> tuple[str, float]:
    r = await jev_post({"model": JEV_MODEL, "state": _state(before, sentence), "questions": {"boundary": question}},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    a = r.json()["answers"]["boundary"]
    return a["choice"], float(a.get("confidence") or 0.0)


def _decide(u: StackUnit, choice: str, conf: float) -> None:
    if conf < MIN_CONF:
        return
    if choice == "summary" and u.group != CONCLUSION:
        u.group, u.attach_to, u.parts = CONCLUSION, None, None
    elif choice == "images" and u.group == CONCLUSION:
        u.group, u.attach_to, u.parts = GENERAL, None, None  # no anatomical label to hand: logged


async def conclusion_gate(units: list[StackUnit], new_ids: list[int], transport=None) -> list[dict]:
    """For each new, unpinned, non-heading sentence after a Conclusion sentence: Jev decides at
    >= MIN_CONF; otherwise the grouper's placement stands. Fails open. Returns the log."""
    asks, started = [], False
    for k, u in enumerate(units):
        if u.id in new_ids and started and not u.heading and not u.pinned:
            asks.append((k, u))
        if u.group == CONCLUSION:
            started = True

    async def one(k: int, u: StackUnit):
        try:
            return u, *(await ask([x.text for x in units[:k]], u.text, transport=transport))
        except Exception as e:
            return u, f"error {type(e).__name__}", 0.0
    log = []
    for u, choice, conf in await asyncio.gather(*(one(k, u) for k, u in asks)):
        before = u.group
        _decide(u, choice, conf)
        log.append({"id": u.id, "choice": choice, "conf": round(conf, 2), "from": before, "to": u.group})
    return log


async def closing_check(units: list[StackUnit], transport=None) -> dict | None:
    """When dictation stops with no Conclusion: ask about the last sentence once (spec §3.6)."""
    if not units or any(u.group == CONCLUSION for u in units):
        return None
    last = units[-1]
    if last.pinned or last.heading:
        return None
    try:
        choice, conf = await ask([u.text for u in units[:-1]], last.text, CLOSING_QUESTION, transport)
    except Exception as e:
        return {"id": last.id, "choice": f"error {type(e).__name__}", "conf": 0.0, "from": last.group, "to": last.group}
    before = last.group
    if choice == "summary":  # an uncued line only ever moves into Conclusion, never out
        _decide(last, choice, conf)
    return {"id": last.id, "choice": choice, "conf": round(conf, 2), "from": before, "to": last.group}
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_gate.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/hybrid_stack/gate.py tests/test_hybrid_stack_gate.py
git commit -m "feat(hybrid-stack): Jev conclusion gate and uncued closing check"
```

---

### Task 7: Pills and template regions (`pills.py`, `template.py`)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/pills.py`, `.../hybrid_stack/template.py`
- Test: `backend/tests/test_hybrid_stack_pills_template.py`

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

from rapid_reports_ai.hybrid_stack.pills import derived_pills
from rapid_reports_ai.hybrid_stack.schemas import OTHER, Region
from rapid_reports_ai.hybrid_stack.template import template_regions
from rapid_reports_ai.hybrid_stack.units import StackUnit
from rapid_reports_ai.template_sheet_grammar import parse_sheet

FIX = Path(__file__).parent / "fixtures" / "template_pipeline" / "lean_cmr.md"


def test_pills_follow_covers_in_region_order_and_skip_other():
    regions = [Region(name="Liver", includes="l"), Region(name="Kidneys", includes="k"), Region(name=OTHER, includes="o")]
    units = [StackUnit(id=0, text="a", covers=["Kidneys", OTHER]), StackUnit(id=1, text="b", covers=["Liver"])]
    assert derived_pills(units, regions) == ["Liver", "Kidneys"]


def test_template_regions_are_findings_paragraphs_with_covers():
    st = parse_sheet(FIX.read_text(), mode="template").structure
    regions = template_regions(st)
    names = [r.name for r in regions]
    assert names[:2] == ["Left Ventricle", "Right Ventricle"]
    assert "Late Gadolinium Enhancement" in names and names[-1] == OTHER
    assert "Clinical Details" not in names and "Conclusion" not in names
    assert "myocardium" in next(r.includes for r in regions if r.name == "Tissue Characterisation")
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_pills_template.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement both modules**

`pills.py`:
```python
"""Checklist pills derived from the grouping (spec §3.7): a region is ticked when a sentence covers it."""
from __future__ import annotations

from .schemas import Region, pill_regions
from .units import StackUnit


def derived_pills(units: list[StackUnit], regions: list[Region]) -> list[str]:
    covered = {c for u in units for c in u.covers}
    return [name for name in pill_regions(regions) if name in covered]
```

`template.py`:
```python
"""Regions from the radiologist's own template (spec §3.3, template path): the findings
paragraphs of a fresh grammar structure in template order, each paragraph's COVERS as includes."""
from __future__ import annotations

from ..template_sheet_structure import SheetStructure
from .schemas import OTHER, Region, other_region


def template_regions(st: SheetStructure) -> list[Region]:
    order = {sec.name: sec.order for sec in st.sections}
    findings = {sec.name for sec in st.sections if sec.role == "findings"}
    paras = sorted((p for p in st.paragraphs if p.section in findings), key=lambda p: order.get(p.section, 0))
    out: list[Region] = []
    seen: set[str] = set()
    for p in paras:
        name = p.name if p.name.lower() not in seen else f"{p.name} ({p.section.title()})"
        seen.add(name.lower())
        out.append(Region(name=name, includes=", ".join(p.covers) or p.name))
    if OTHER.lower() not in seen:
        out.append(other_region())
    return out
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_pills_template.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/hybrid_stack/pills.py src/rapid_reports_ai/hybrid_stack/template.py tests/test_hybrid_stack_pills_template.py
git commit -m "feat(hybrid-stack): derived pills and template regions"
```

---

### Task 8: Jev family choice (`family.py`)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/family.py`
- Test: `backend/tests/test_hybrid_stack_family.py`

- [ ] **Step 1: Write the failing test**

```python
import json

import httpx

from rapid_reports_ai.hybrid_stack.family import NONE, choose_family


async def test_offers_families_plus_none_and_returns_choice(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"answers": {"family": {"choice": "knee", "confidence": 0.97}}})
    choice, conf = await choose_family("MRI right knee", "", transport=httpx.MockTransport(handler))
    crit = seen[0]["questions"]["family"]["criteria"]
    assert (choice, conf) == ("knee", 0.97)
    assert NONE in crit and "generic" not in crit and "abdomen_pelvis" in crit
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_family.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `family.py`**

```python
"""Jev maps a free-text scan type to a schema family, or "none" (spec §3.3). Confidence alone did not
flag a missing family (cardiac MRI went to chest at 1.0), hence the explicit option."""
from __future__ import annotations

import os

from ..jev_client import JEV_MODEL, jev_post
from .schemas import family_keys, library

NONE = "none"
TIMEOUT_S = 10.0


async def choose_family(scan_type: str, history: str, transport=None) -> tuple[str, float]:
    fams = library()["families"]
    crit = {k: fams[k]["description"] for k in family_keys()}
    crit[NONE] = ("None of the other options describes this examination: a different body part, joint, "
                  "organ-specific or specialist examination that the options do not name.")
    q = {"type": "choice", "instructions": "Which kind of examination is this?", "criteria": crit}
    r = await jev_post({"model": JEV_MODEL, "state": f"Scan type: {scan_type}\nClinical history: {history}",
                        "questions": {"family": q}}, os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    a = r.json()["answers"]["family"]
    return a["choice"], float(a.get("confidence") or 0.0)
```

- [ ] **Step 4: Run it to see it pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_family.py -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/hybrid_stack/family.py tests/test_hybrid_stack_family.py
git commit -m "feat(hybrid-stack): Jev family choice with none option"
```

---

### Task 9: Reconciler (`reconciler.py`)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/reconciler.py`
- Test: `backend/tests/test_hybrid_stack_reconciler.py`

- [ ] **Step 1: Write the failing tests**

```python
import json

import httpx

from rapid_reports_ai.hybrid_stack import reconciler as R
from rapid_reports_ai.hybrid_stack.schemas import OTHER


def _llm(content: dict, seen: list | None = None):
    def handler(req):
        if seen is not None:
            seen.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})
    return httpx.MockTransport(handler)


async def test_keeps_a_family_as_is(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    seen = []
    res = await R.reconcile("MRI right knee", "", transport=_llm({"family": "knee"}, seen))
    assert res.family == "knee" and res.regions[-1].name == OTHER
    body = seen[0]
    assert body["reasoning_effort"] == "medium" and body["response_format"] == {"type": "json_object"}
    assert "Title Case" in body["messages"][1]["content"]


async def test_composes_reuses_and_validates(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    out = {"regions": [{"key": "biceps"}, {"key": "nope"}, {"name": "Syndesmosis", "includes": "tibiofibular ligaments"},
                       {"name": "Incidental Findings", "includes": "x"}, {"name": "syndesmosis", "includes": "dup"},
                       {"key": "other"}]}
    res = await R.reconcile("MRI ankle", "", transport=_llm(out))
    names = [r.name for r in res.regions]
    assert names == ["Biceps", "Syndesmosis", OTHER]
    assert res.family is None and res.log["new"] == ["Syndesmosis"] and len(res.log["dropped"]) == 4


async def test_new_regions_are_capped(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    out = {"regions": [{"name": f"Region {i}", "includes": "x"} for i in range(12)]}
    res = await R.reconcile("MRI x", "", transport=_llm(out))
    assert len(res.regions) == R.MAX_NEW_REGIONS + 1
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_reconciler.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `reconciler.py`**

```python
"""Reconciler (spec §3.3): for a scan type seen for the first time, keep a family as-is or compose
one from the region library plus new regions. Qwen with reasoning; plain JSON and Title Case,
because uppercase output with reasoning on corrupted names on Cerebras ("MEDIASTINUM" -> "MEDIUMIUM",
11/12 lists; Title Case 0/12). Code validates; the caller caches."""
from __future__ import annotations

import asyncio
import json
import os

from pydantic import BaseModel, Field

from .http import post_json
from .schemas import Region, family_keys, family_regions, library, other_region

MAX_NEW_REGIONS = 8
_RESERVED = {"technique", "conclusion", "general", "other findings", "incidental findings", "other", "incidental"}

RECONCILE_SYSTEM = ("You build the region list for a radiology examination's visual schema. Regions are broad zones "
                    "a radiologist reports one by one; each region lists what it includes.")

RECONCILE_USER = """Scan type: {scan_type}
Clinical history: {history}

FAMILIES (key — what it is for — its regions):
{families}

REGION LIBRARY (key — name — includes):
{library}

If one family above already gives this examination a useful region list as it stands (its regions match what this examination reports, at the right level of detail), reply {{"family": "<family key>"}}.

Otherwise build the ordered region list for this examination, in the order a radiologist reports it:
- Reuse a library region (by its key) wherever it fits this examination as it is.
- Add a new region only for a structure or compartment this examination reports separately and no library region covers. Give it a short name and an includes list in the same style.
- Keep regions broad: one region per structure or compartment the radiologist would report on its own line, typically 6 to 12 regions. Include structures incidentally in the field of view as one region.
- When anatomy differs between patients and the scan type does not say which applies, use one neutral region.
- Do not add Technique, Conclusion, General, Other or Incidental regions: they always exist, and incidental findings outside the listed regions go to "Other findings".
- Write names in Title Case.

Reply as JSON: either {{"family": "<family key>"}} or {{"regions": [{{"key": "<library key>"}} or {{"name": "<new name>", "includes": "<what it includes>"}}]}}"""

URL = "https://api.cerebras.ai/v1/chat/completions"
MODEL = "qwen-3.8-27b"


class Reconciled(BaseModel):
    regions: list[Region]
    family: str | None = None  # set when an existing family was kept as-is
    log: dict = Field(default_factory=dict)


def _prompt(scan_type: str, history: str) -> str:
    lib = library()
    fams = "\n".join(f"{k} — {lib['families'][k]['description']} — {', '.join(r.name for r in family_regions(k))}"
                     for k in family_keys())
    regions = "\n".join(f"{k} — {v['name']} — {v['includes']}" for k, v in lib["regions"].items()
                        if k != "other" and not k.startswith("generic_"))
    return RECONCILE_USER.format(scan_type=scan_type, history=history or "(not specified)", families=fams, library=regions)


def validate(out: dict) -> Reconciled:
    if out.get("family") in family_keys():
        return Reconciled(regions=family_regions(out["family"]), family=out["family"], log={"family": out["family"]})
    lib = library()["regions"]
    regions, seen, reused, new, dropped = [], set(), [], [], []
    for it in out.get("regions") or []:
        key = it.get("key")
        if key in lib and key != "other" and not key.startswith("generic_"):
            name, inc = lib[key]["name"], lib[key]["includes"]
            kind = "reused"
        elif not key and it.get("name") and it.get("includes") and len(new) < MAX_NEW_REGIONS:
            name, inc = str(it["name"]).strip(), str(it["includes"]).strip()
            kind = "new"
        else:
            dropped.append(it)
            continue
        if name.lower() in seen or name.lower() in _RESERVED:
            dropped.append(it)
            continue
        seen.add(name.lower())
        (reused if kind == "reused" else new).append(name if kind == "new" else key)
        regions.append(Region(name=name, includes=inc))
    if not regions:
        raise ValueError("reconciler returned no usable regions")
    regions.append(other_region())
    return Reconciled(regions=regions, log={"reused": reused, "new": new, "dropped": dropped})


async def reconcile(scan_type: str, history: str, transport=None) -> Reconciled:
    body = {"model": MODEL, "temperature": 0.1, "max_tokens": 8000, "reasoning_effort": "medium",
            "messages": [{"role": "system", "content": RECONCILE_SYSTEM},
                         {"role": "user", "content": _prompt(scan_type, history)}],
            "response_format": {"type": "json_object"}}
    key = os.environ.get("CEREBRAS_API_KEY", "")
    for attempt in range(3):
        r = await post_json(URL, key, body, 30.0, transport)
        if r.status_code != 429:
            break
        await asyncio.sleep(1 + 2 * attempt)
    r.raise_for_status()
    return validate(json.loads(r.json()["choices"][0]["message"]["content"]))
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_reconciler.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/hybrid_stack/reconciler.py tests/test_hybrid_stack_reconciler.py
git commit -m "feat(hybrid-stack): schema reconciler with validation"
```

---

### Task 10: Database tables

**Files:**
- Modify: `backend/src/rapid_reports_ai/database/models.py` (append two models)
- Create: `backend/migrations/versions/20261010120000_add_hybrid_stack_tables.py`
- Test: `backend/tests/test_hybrid_stack_models.py`

- [ ] **Step 1: Write the failing test**

```python
import uuid

from rapid_reports_ai.database.models import DictationStackLog, StackSchemaFamily


def test_family_and_log_round_trip(db_session):
    db_session.add(StackSchemaFamily(key="mri left ankle", scan_type="MRI left ankle",
                                     regions=[{"name": "Tendons", "includes": "x"}], source="reconciler:composed",
                                     status="provisional"))
    uid = uuid.uuid4()
    db_session.add(DictationStackLog(user_id=uid, session_id="s1", scan_type="MRI left ankle",
                                     schema_key="mri left ankle", schema_source="reconciled", provisional=True,
                                     units=[], pills_derived=["Tendons"], pills_jev=[], sections=[],
                                     structured_text="", manual_moves=0, latency_ms={}))
    db_session.commit()
    assert db_session.get(StackSchemaFamily, "mri left ankle").status == "provisional"
    assert db_session.query(DictationStackLog).filter_by(session_id="s1").one().pills_derived == ["Tendons"]
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'DictationStackLog'`

- [ ] **Step 3: Append the models to `database/models.py`**

(`Column`, `String`, `Text`, `Boolean`, `Integer`, `DateTime`, `UUID`, `JSONBType`, `datetime`, `timezone`, `uuid` and `_now` are already imported/defined in that module — check the import block at the top and add any missing name to it.)

```python
class StackSchemaFamily(Base):
    """A hybrid-stack region list cached per normalised scan type (spec §3.3). status: provisional (a
    reconciler composition awaiting review) | approved | rejected (use the Jev family instead)."""
    __tablename__ = "stack_schema_families"
    key = Column(Text, primary_key=True)
    scan_type = Column(Text, nullable=False)
    regions = Column(JSONBType(), nullable=False)  # [{"name", "includes"}], "Other findings" last
    source = Column(String(64), nullable=False)    # reconciler:family:<key> | reconciler:composed | admin
    status = Column(String(16), nullable=False, default="provisional")
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class DictationStackLog(Base):
    """One row per dictation session: the hybrid stack beside its shadow (spec §5, live testing)."""
    __tablename__ = "dictation_stack_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    session_id = Column(String(64), nullable=False, index=True)
    scan_type = Column(Text, nullable=True)
    schema_key = Column(Text, nullable=True)
    schema_source = Column(String(32), nullable=True)
    provisional = Column(Boolean, nullable=False, default=False)
    units = Column(JSONBType(), nullable=True)
    pills_derived = Column(JSONBType(), nullable=True)
    pills_jev = Column(JSONBType(), nullable=True)       # shadow: today's Jev coverage
    sections = Column(JSONBType(), nullable=True)        # shadow: today's /sections list
    structured_text = Column(Text, nullable=True)        # shadow: today's Structured build
    manual_moves = Column(Integer, nullable=False, default=0)
    latency_ms = Column(JSONBType(), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
```

- [ ] **Step 4: Run the test to see it pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_models.py -q`
Expected: `1 passed` (the SQLite test harness creates tables from the models)

- [ ] **Step 5: Write the migration**

Check the current head first: `PYTHONPATH=src .venv/bin/alembic heads` — use its revision as `down_revision` (it was `20261005120000` when this plan was written; main may have moved).

`backend/migrations/versions/20261010120000_add_hybrid_stack_tables.py`:
```python
"""add hybrid stack tables (stack_schema_families, dictation_stack_logs)

Revision ID: 20261010120000
Revises: 20261005120000
Create Date: 2026-10-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261010120000"
down_revision: Union[str, Sequence[str], None] = "20261005120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)
    json_type = postgresql.JSONB if is_postgres else sa.JSON
    op.create_table(
        "stack_schema_families",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("scan_type", sa.Text(), nullable=False),
        sa.Column("regions", json_type(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "dictation_stack_logs",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("user_id", uuid_type, nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("scan_type", sa.Text(), nullable=True),
        sa.Column("schema_key", sa.Text(), nullable=True),
        sa.Column("schema_source", sa.String(length=32), nullable=True),
        sa.Column("provisional", sa.Boolean(), nullable=False),
        sa.Column("units", json_type(), nullable=True),
        sa.Column("pills_derived", json_type(), nullable=True),
        sa.Column("pills_jev", json_type(), nullable=True),
        sa.Column("sections", json_type(), nullable=True),
        sa.Column("structured_text", sa.Text(), nullable=True),
        sa.Column("manual_moves", sa.Integer(), nullable=False),
        sa.Column("latency_ms", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dictation_stack_logs_user_id", "dictation_stack_logs", ["user_id"], unique=False)
    op.create_index("ix_dictation_stack_logs_session_id", "dictation_stack_logs", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_dictation_stack_logs_session_id", table_name="dictation_stack_logs")
    op.drop_index("ix_dictation_stack_logs_user_id", table_name="dictation_stack_logs")
    op.drop_table("dictation_stack_logs")
    op.drop_table("stack_schema_families")
```

- [ ] **Step 6: Check the migration chain**

Run: `PYTHONPATH=src .venv/bin/alembic heads`
Expected: a single head, `20261010120000`

- [ ] **Step 7: Commit**

```bash
git add src/rapid_reports_ai/database/models.py migrations/versions/20261010120000_add_hybrid_stack_tables.py tests/test_hybrid_stack_models.py
git commit -m "feat(hybrid-stack): schema family cache and session log tables"
```

---

### Task 11: Service (`service.py`)

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/service.py`
- Test: `backend/tests/test_hybrid_stack_service.py`

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

import pytest

from rapid_reports_ai.database.models import StackSchemaFamily
from rapid_reports_ai.hybrid_stack import service as S
from rapid_reports_ai.hybrid_stack.grouper import Placement
from rapid_reports_ai.hybrid_stack.reconciler import Reconciled
from rapid_reports_ai.hybrid_stack.schemas import OTHER, Region, family_regions
from rapid_reports_ai.hybrid_stack.units import StackUnit

CMR = Path(__file__).parent / "fixtures" / "template_pipeline" / "lean_cmr.md"


@pytest.fixture
def fakes(monkeypatch):
    calls = {"family": 0, "reconcile": 0}

    async def fam(scan_type, history, transport=None):
        calls["family"] += 1
        return ("knee", 0.9)

    async def rec(scan_type, history, transport=None):
        calls["reconcile"] += 1
        return Reconciled(regions=[Region(name="Tendons", includes="t"), Region(name=OTHER, includes="o")],
                          log={"new": ["Tendons"]})
    monkeypatch.setattr(S, "choose_family", fam)
    monkeypatch.setattr(S, "reconcile", rec)
    return calls


async def test_first_time_reconciles_caches_provisional_then_reads_cache(db_session, fakes):
    a = await S.resolve_schema("MRI  Ankle", "", None, db_session)
    assert a.source == "reconciled" and a.provisional and a.regions[0].name == "Tendons"
    b = await S.resolve_schema("mri ankle", "", None, db_session)
    assert b.regions == a.regions and fakes["reconcile"] == 1
    assert db_session.get(StackSchemaFamily, "mri ankle").status == "provisional"


async def test_reconciler_keeping_a_family_is_approved(db_session, monkeypatch, fakes):
    async def keep(scan_type, history, transport=None):
        return Reconciled(regions=family_regions("knee"), family="knee", log={"family": "knee"})
    monkeypatch.setattr(S, "reconcile", keep)
    r = await S.resolve_schema("MRI knee", "", None, db_session)
    assert r.family == "knee" and not r.provisional
    assert db_session.get(StackSchemaFamily, "mri knee").status == "approved"


async def test_reconciler_failure_uses_jev_family_and_caches_nothing(db_session, monkeypatch, fakes):
    async def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(S, "reconcile", boom)
    r = await S.resolve_schema("MRI knee", "", None, db_session)
    assert r.source == "family" and r.family == "knee"
    assert db_session.get(StackSchemaFamily, "mri knee") is None


async def test_rejected_row_uses_jev_family(db_session, fakes):
    db_session.add(StackSchemaFamily(key="mri ankle", scan_type="MRI ankle", regions=[], source="admin",
                                     status="rejected"))
    db_session.commit()
    r = await S.resolve_schema("MRI ankle", "", None, db_session)
    assert r.source == "family" and fakes["reconcile"] == 0


async def test_template_structure_wins(db_session, fakes):
    from rapid_reports_ai.template_sheet_grammar import parse_sheet
    st = parse_sheet(CMR.read_text(), mode="template").structure
    r = await S.resolve_schema("Cardiac MRI", "", st, db_session)
    assert r.source == "template" and r.regions[0].name == "Left Ventricle" and fakes["family"] == 0


async def test_group_update_places_new_sentences_and_derives_pills(monkeypatch):
    async def place(scan_type, regions, units, new_ids, transport=None):
        return [Placement(id=i, group="Liver", structure="liver", covers=["Liver"]) for i in new_ids], "m", None

    async def no_gate(units, new_ids, transport=None):
        return []
    monkeypatch.setattr(S, "place", place)
    monkeypatch.setattr(S, "conclusion_gate", no_gate)
    regions = [Region(name="Liver", includes="l"), Region(name=OTHER, includes="o")]
    res = await S.group_update("CT", "Liver normal. Liver cyst.", regions, [])
    assert [u.group for u in res.units] == ["Liver", "Liver"] and res.pills == ["Liver"]
    assert res.new_ids == [0, 1] and "grouper" in res.timings_ms


async def test_group_update_with_nothing_new_makes_no_call(monkeypatch):
    async def place(*a, **k):
        raise AssertionError("no call expected")
    monkeypatch.setattr(S, "place", place)
    regions = [Region(name="Liver", includes="l")]
    prev = [StackUnit(id=0, text="Liver normal.", group="Liver", covers=["Liver"])]
    res = await S.group_update("CT", "Liver normal.", regions, prev)
    assert res.new_ids == [] and res.pills == ["Liver"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_service.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `service.py`**

```python
"""Hybrid stack service: the region list for a session, and one grouping update (spec §3)."""
from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel, Field

from ..database.models import StackSchemaFamily
from ..template_sheet_structure import SheetStructure
from .family import choose_family
from .gate import closing_check, conclusion_gate
from .grouper import apply_placements, place
from .pills import derived_pills
from .reconciler import reconcile
from .schemas import GENERIC_FAMILY, Region, family_keys, family_regions, groups_for, pill_regions, scan_key
from .template import template_regions
from .units import StackUnit, match_units

logger = logging.getLogger(__name__)
RECONCILE_TIMEOUT_S = 10.0


class SchemaResult(BaseModel):
    regions: list[Region]
    groups: list[str]
    pills: list[str]
    source: str            # template | approved | reconciled | family | generic
    family: str | None = None
    key: str
    provisional: bool = False


class GroupResult(BaseModel):
    units: list[StackUnit]
    new_ids: list[int]
    pills: list[str]
    gate: list[dict] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    timings_ms: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


def _result(regions: list[Region], source: str, key: str, family: str | None = None,
            provisional: bool = False) -> SchemaResult:
    return SchemaResult(regions=regions, groups=groups_for(regions), pills=pill_regions(regions), source=source,
                        family=family, key=key, provisional=provisional)


async def _jev_family(scan_type: str, history: str) -> str:
    try:
        choice, _ = await choose_family(scan_type, history)
    except Exception as e:  # fail open to the generic family
        logger.warning("[stack.family] %s: %s", type(e).__name__, e)
        return GENERIC_FAMILY
    return choice if choice in family_keys() else GENERIC_FAMILY  # "none" -> generic


async def resolve_schema(scan_type: str, history: str, structure: SheetStructure | None, db) -> SchemaResult:
    """Template structure > cached family (approved or provisional) > reconciler (once, cached) >
    Jev family (on reconciler failure or a rejected cache entry; never cached)."""
    key = scan_key(scan_type)
    if structure is not None:
        return _result(template_regions(structure), "template", key)
    row = db.get(StackSchemaFamily, key) if db is not None else None
    if row is not None and row.status in ("approved", "provisional"):
        regions = [Region(**r) for r in row.regions]
        return _result(regions, "approved" if row.status == "approved" else "reconciled", key,
                       provisional=row.status == "provisional")
    if row is not None:  # rejected: the Jev family, no new reconciliation
        fam = await _jev_family(scan_type, history)
        return _result(family_regions(fam), "family" if fam != GENERIC_FAMILY else "generic", key, family=fam)
    try:
        rec = await asyncio.wait_for(reconcile(scan_type, history), RECONCILE_TIMEOUT_S)
    except Exception as e:
        logger.warning("[stack.reconcile] %s: %s; Jev family", type(e).__name__, e)
        fam = await _jev_family(scan_type, history)
        return _result(family_regions(fam), "family" if fam != GENERIC_FAMILY else "generic", key, family=fam)
    status = "approved" if rec.family else "provisional"
    if db is not None:
        db.merge(StackSchemaFamily(key=key, scan_type=scan_type, regions=[r.model_dump() for r in rec.regions],
                                   source=f"reconciler:family:{rec.family}" if rec.family else "reconciler:composed",
                                   status=status))
        db.commit()
    logger.info("[stack.reconcile] key=%r status=%s log=%s", key, status, rec.log)
    return _result(rec.regions, "approved" if rec.family else "reconciled", key, family=rec.family,
                   provisional=status == "provisional")


async def group_update(scan_type: str, text: str, regions: list[Region],
                       previous: list[StackUnit]) -> GroupResult:
    units, new_ids = match_units(text, previous)
    timings: dict[str, int] = {}
    problems: list[str] = []
    gate_log: list[dict] = []
    error = None
    if new_ids:
        t0 = time.perf_counter()
        placements, model, error = await place(scan_type, regions, units, new_ids)
        timings["grouper"] = int((time.perf_counter() - t0) * 1000)
        if placements:
            problems = apply_placements(units, placements, new_ids, groups_for(regions))
            t1 = time.perf_counter()
            gate_log = await conclusion_gate(units, new_ids)
            timings["gate"] = int((time.perf_counter() - t1) * 1000)
    return GroupResult(units=units, new_ids=new_ids, pills=derived_pills(units, regions), gate=gate_log,
                       problems=problems, timings_ms=timings, error=error)


async def close_update(units: list[StackUnit], regions: list[Region]) -> GroupResult:
    log = await closing_check(units)
    return GroupResult(units=units, new_ids=[], pills=derived_pills(units, regions), gate=[log] if log else [])
```

Note: when the grouper fails (`placements == []`), new units keep `group=None`; the client shows them under "just dictated" and they are re-sent as new on the next update (because `match_units` keeps their `group=None` — see the next step).

- [ ] **Step 4: Make unplaced units count as new again**

Unplaced units (`group is None`) must be retried. Edit `match_units` in `units.py` — a retained unit with `group is None` is also new:

```python
        if pool.get(s):
            old = pool[s].pop(0)
            old_to_new[old.id] = i
            units.append(old.model_copy(update={"id": i}))
            if old.group is None:
                new_ids.append(i)
```

Add to `tests/test_hybrid_stack_units.py`:
```python
def test_unplaced_previous_sentence_is_retried():
    units, new = match_units("A.", [StackUnit(id=0, text="A.")])
    assert new == [0]
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_service.py tests/test_hybrid_stack_units.py -q`
Expected: `13 passed`

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/hybrid_stack/service.py src/rapid_reports_ai/hybrid_stack/units.py tests/test_hybrid_stack_service.py tests/test_hybrid_stack_units.py
git commit -m "feat(hybrid-stack): schema resolution and grouping service"
```

---

### Task 12: Routes, flag, settings status

**Files:**
- Create: `backend/src/rapid_reports_ai/hybrid_stack/routes.py`
- Modify: `backend/src/rapid_reports_ai/main.py` (include router next to `app.include_router(canvas_router)` at ~5983; add `"hybrid_stack"` to the `/api/settings/status` payload at ~3395)
- Test: `backend/tests/test_hybrid_stack_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
import uuid

import pytest

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import DictationStackLog, StackSchemaFamily, User
from rapid_reports_ai.hybrid_stack import routes as R
from rapid_reports_ai.hybrid_stack import service as S
from rapid_reports_ai.hybrid_stack.schemas import Region
from rapid_reports_ai.main import app


@pytest.fixture
def user(db_session):
    u = User(id=uuid.uuid4(), email="rad@nhs.net", password_hash="x", full_name="T",
             is_active=True, is_verified=True, is_approved=True)
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def authed(client, user, monkeypatch):
    monkeypatch.setenv("RR_DICTATION_V2", "1")
    monkeypatch.delenv("RR_HYBRID_STACK", raising=False)
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_kill_switch_404(authed, monkeypatch):
    monkeypatch.setenv("RR_HYBRID_STACK", "0")
    assert authed.post("/api/canvas/stack/group", json={"scan_type": "", "text": "", "regions": []}).status_code == 404


def test_off_without_dictation_package(authed, monkeypatch):
    monkeypatch.delenv("RR_DICTATION_V2", raising=False)
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    assert R.stack_allowed() is False


def test_group_route(authed, monkeypatch):
    async def fake(scan_type, text, regions, previous):
        return S.GroupResult(units=[], new_ids=[], pills=["Liver"])
    monkeypatch.setattr(R, "group_update", fake)
    d = authed.post("/api/canvas/stack/group", json={"scan_type": "CT", "text": "x",
                                                     "regions": [{"name": "Liver", "includes": "l"}]}).json()
    assert d["pills"] == ["Liver"]


def test_schema_route_quick(authed, monkeypatch):
    async def fake(scan_type, history, structure, db):
        assert structure is None
        return S._result([Region(name="Liver", includes="l")], "family", "ct", family="abdomen_pelvis")
    monkeypatch.setattr(R, "resolve_schema", fake)
    d = authed.post("/api/canvas/stack/schema", json={"scan_type": "CT", "clinical_history": ""}).json()
    assert d["groups"] == ["Technique", "Liver", "General", "Conclusion"] and d["pills"] == ["Liver"]


def test_log_upserts_by_session(authed, db_session):
    body = {"session_id": "s1", "scan_type": "CT", "schema_key": "ct", "schema_source": "family",
            "provisional": False, "units": [], "pills_derived": ["Liver"], "pills_jev": [], "sections": [],
            "structured_text": "", "manual_moves": 0, "latency_ms": {}}
    assert authed.post("/api/canvas/stack/log", json=body).json() == {"ok": True}
    assert authed.post("/api/canvas/stack/log", json={**body, "manual_moves": 2}).json() == {"ok": True}
    rows = db_session.query(DictationStackLog).filter_by(session_id="s1").all()
    assert len(rows) == 1 and rows[0].manual_moves == 2


def test_reviewer_endpoints(authed, db_session, monkeypatch):
    db_session.add(StackSchemaFamily(key="mri ankle", scan_type="MRI ankle", regions=[{"name": "T", "includes": "t"}],
                                     source="reconciler:composed", status="provisional"))
    db_session.commit()
    monkeypatch.setenv("RR_STACK_REVIEWERS", "someone@else.net")
    assert authed.get("/api/canvas/stack/families").status_code == 403
    monkeypatch.setenv("RR_STACK_REVIEWERS", "Rad@NHS.net")
    rows = authed.get("/api/canvas/stack/families?status=provisional").json()
    assert rows[0]["key"] == "mri ankle"
    upd = authed.post("/api/canvas/stack/families/mri ankle", json={"status": "approved",
                                                                    "regions": [{"name": "Tendons", "includes": "x"}]})
    assert upd.status_code == 200
    row = db_session.get(StackSchemaFamily, "mri ankle")
    db_session.refresh(row)
    assert row.status == "approved" and row.regions[0]["name"] == "Tendons" and row.source == "admin"
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_routes.py -q`
Expected: FAIL — `ModuleNotFoundError: ... hybrid_stack.routes`

- [ ] **Step 3: Implement `routes.py`**

```python
"""Hybrid stack endpoints (spec §3, §5). On when the dictation package is allowed and the kill
switch RR_HYBRID_STACK is not "0" (default on). Reviewers (RR_STACK_REVIEWERS, comma-separated
emails) approve, edit or reject reconciled families."""
from __future__ import annotations

import os
from typing import Literal, Mapping

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..database.models import DictationStackLog, StackSchemaFamily, Template, User
from ..dictation_v2 import v2_allowed
from ..template_sheet_structure import fresh
from .schemas import Region
from .service import GroupResult, SchemaResult, close_update, group_update, resolve_schema
from .units import StackUnit

router = APIRouter(prefix="/api/canvas/stack", tags=["hybrid-stack"])


def stack_allowed(env: Mapping[str, str] = os.environ) -> bool:
    return env.get("RR_HYBRID_STACK", "1") != "0" and v2_allowed(env)


def _require() -> None:
    if not stack_allowed():
        raise HTTPException(status_code=404, detail="Not Found")


class SchemaRequest(BaseModel):
    scan_type: str = ""
    clinical_history: str = ""
    template_id: str | None = None


class GroupRequest(BaseModel):
    scan_type: str = ""
    text: str = ""
    regions: list[Region]
    previous: list[StackUnit] = Field(default_factory=list)


class CloseRequest(BaseModel):
    units: list[StackUnit]
    regions: list[Region]


class LogRequest(BaseModel):
    session_id: str
    scan_type: str | None = None
    schema_key: str | None = None
    schema_source: str | None = None
    provisional: bool = False
    units: list[dict] = Field(default_factory=list)
    pills_derived: list[str] = Field(default_factory=list)
    pills_jev: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    structured_text: str = ""
    manual_moves: int = 0
    latency_ms: dict = Field(default_factory=dict)


class FamilyUpdate(BaseModel):
    status: Literal["approved", "rejected", "provisional"]
    regions: list[Region] | None = None


@router.post("/schema", response_model=SchemaResult)
async def stack_schema(req: SchemaRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    structure = None
    if req.template_id:
        t = db.query(Template).filter(Template.id == req.template_id, Template.user_id == user.id).first()
        structure = fresh(t.template_config or {}) if t is not None else None
    return await resolve_schema(req.scan_type, req.clinical_history, structure, db)


@router.post("/group", response_model=GroupResult)
async def stack_group(req: GroupRequest, user: User = Depends(get_current_user)):
    _require()
    return await group_update(req.scan_type, req.text, req.regions, req.previous)


@router.post("/close", response_model=GroupResult)
async def stack_close(req: CloseRequest, user: User = Depends(get_current_user)):
    _require()
    return await close_update(req.units, req.regions)


@router.post("/log")
async def stack_log(req: LogRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    row = db.query(DictationStackLog).filter_by(user_id=user.id, session_id=req.session_id).first()
    if row is None:
        row = DictationStackLog(user_id=user.id, session_id=req.session_id)
        db.add(row)
    for k, v in req.model_dump().items():
        if k != "session_id":
            setattr(row, k, v)
    db.commit()
    return {"ok": True}


def _reviewer(user: User) -> None:
    allowed = {e.strip().lower() for e in os.environ.get("RR_STACK_REVIEWERS", "").split(",") if e.strip()}
    if (user.email or "").lower() not in allowed:
        raise HTTPException(status_code=403, detail="Not a reviewer")


@router.get("/families")
async def list_families(status: str | None = None, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    _reviewer(user)
    q = db.query(StackSchemaFamily)
    if status:
        q = q.filter(StackSchemaFamily.status == status)
    return [{"key": r.key, "scan_type": r.scan_type, "regions": r.regions, "source": r.source, "status": r.status,
             "updated_at": r.updated_at.isoformat() if r.updated_at else None}
            for r in q.order_by(StackSchemaFamily.updated_at.desc()).all()]


@router.post("/families/{key}")
async def update_family(key: str, upd: FamilyUpdate, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    _reviewer(user)
    row = db.get(StackSchemaFamily, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown family")
    row.status = upd.status
    if upd.regions is not None:
        row.regions = [r.model_dump() for r in upd.regions]
        row.source = "admin"
    db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Wire into `main.py`**

Next to `from .canvas_routes import canvas_router` (~line 86) add:
```python
from .hybrid_stack.routes import router as hybrid_stack_router
```
Next to `app.include_router(canvas_router)` (~line 5983) add:
```python
app.include_router(hybrid_stack_router)
```
In the `/api/settings/status` handler (~line 3379, beside `from rapid_reports_ai.dictation_v2 import v2_allowed`) add `from rapid_reports_ai.hybrid_stack.routes import stack_allowed`, and in the returned dict after `"dictation_v2": v2_allowed(),` add:
```python
        # the hybrid dictation stack: default on with the dictation package; RR_HYBRID_STACK=0 turns it off
        "hybrid_stack": stack_allowed(),
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_hybrid_stack_routes.py -q`
Expected: `6 passed`

- [ ] **Step 6: Run the whole hybrid stack suite and the canvas tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests -q -k "hybrid_stack or canvas"`
Expected: all pass, no failures

- [ ] **Step 7: Commit**

```bash
git add src/rapid_reports_ai/hybrid_stack/routes.py src/rapid_reports_ai/main.py tests/test_hybrid_stack_routes.py
git commit -m "feat(hybrid-stack): stack endpoints, kill switch, reviewer endpoints, settings flag"
```

---

### Task 13: Replay eval against the lab fixtures (real models)

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/hybrid_stack_eval.py`

This is the release gate for Part A: the production modules must match the lab on the same text.

- [ ] **Step 1: Write the eval script**

```python
"""Replay the hybrid stack lab sets through the production modules (real models).

Each case is the scratchpad text after each utterance (tests/fixtures/hybrid_stack/replay_*.json);
every step calls service.group_update with the previous units, as the client does; the closing
check runs at the end. Scores the lab's checks ('region' exact; 'group' against name + includes).

    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.hybrid_stack_eval [dev|heldout|template ...]

Lab results to match (2026-10-10): dev 133/139 (lenient), held-out 97/108, template 104/122.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from rapid_reports_ai.hybrid_stack import service  # noqa: E402
from rapid_reports_ai.hybrid_stack.family import choose_family  # noqa: E402
from rapid_reports_ai.hybrid_stack.schemas import GENERIC_FAMILY, family_keys, family_regions  # noqa: E402
from rapid_reports_ai.hybrid_stack.template import template_regions  # noqa: E402
from rapid_reports_ai.template_sheet_grammar import parse_sheet  # noqa: E402

FIX = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "hybrid_stack"


async def regions_for(case: dict):
    if case.get("template"):
        return template_regions(parse_sheet(Path(case["template"]).read_text(), mode="template").structure)
    choice, _ = await choose_family(case["scan_type"], case["clinical_history"])
    return family_regions(choice if choice in family_keys() else GENERIC_FAMILY)


def score(case: dict, units, regions) -> list[dict]:
    includes = {r.name: r.includes for r in regions}
    out = []
    for e in case["expect"]:
        u = next((u for u in units if e["phrase"].lower() in u.text.lower()), None)
        if u is None:
            out.append({**e, "result": "phrase not found"})
            continue
        grp = u.group or ""
        if u.parts:
            grp = next((p.group for p in u.parts if e["phrase"].lower() in p.text.lower()), grp)
        if "region" in e:
            ok = grp.lower() in {x.lower() for x in e["region"]}
        else:
            ok = any(s in (grp + " " + includes.get(grp, "")).lower() for s in e["group"])
        if ok and e.get("attach") and u.attach_to is None:
            out.append({**e, "result": "not attached", "got": grp})
        else:
            out.append({**e, "result": "ok" if ok else "wrong group", "got": grp})
    return out


async def run_case(case: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        regions = await regions_for(case)
        units = []
        for text in case["steps"]:
            res = await service.group_update(case["scan_type"], text, regions, units)
            units = res.units
        closed = await service.close_update(units, regions)
        return {"id": case["id"], "checks": score(case, closed.units, regions)}


async def main(argv: list[str]) -> None:
    sem = asyncio.Semaphore(3)
    for name in argv or ["dev", "heldout", "template"]:
        cases = json.loads((FIX / f"replay_{name}.json").read_text())["cases"]
        results = await asyncio.gather(*(run_case(c, sem) for c in cases))
        checks = [x for r in results for x in r["checks"]]
        ok = sum(x["result"] == "ok" for x in checks)
        lost = sum(x["result"] == "phrase not found" for x in checks)
        print(f"{name}: {ok}/{len(checks)} (scorable {ok}/{len(checks) - lost})")
        for r in results:
            for x in r["checks"]:
                if x["result"] not in ("ok", "phrase not found"):
                    print(f"  ✗ {r['id']} {x['phrase']!r} {x['result']} got={x.get('got')} "
                          f"want={x.get('region') or x.get('group')}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
```

Template sheets in `replay_template.json` are referenced by paths relative to `backend/` (`src/rapid_reports_ai/scripts/hybrid_stack_lab/template_test/*.md`, `tests/fixtures/template_pipeline/lean_cmr.md`); run from `backend/`.

- [ ] **Step 2: Run the eval**

Run: `PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.hybrid_stack_eval`
Expected (gate): held-out scorable ≥ 95%, template scorable ≥ 93%, dev ≥ 128/139. The text replay skips the ASR step, so "phrase not found" counts can differ slightly from the lab. If a set falls below its gate, read every ✗ line before changing anything: the prompts in this plan are the lab's final prompts, so a drop points at a port error (compare with `scripts/hybrid_stack_lab/lab.py`), not at prompt tuning.

- [ ] **Step 3: Commit**

```bash
git add src/rapid_reports_ai/scripts/hybrid_stack_eval.py
git commit -m "test(hybrid-stack): replay eval of the lab sets through production modules"
```

---

# Part B — Frontend

### Task 14: Types and flag

**Files:**
- Create: `frontend/src/lib/hybrid-stack/types.ts`, `frontend/src/lib/hybrid-stack/flag.ts`
- Test: `frontend/src/lib/hybrid-stack/flag.test.ts`

- [ ] **Step 1: Write the types**

`types.ts`:
```ts
// Wire types for /api/canvas/stack/* (backend hybrid_stack). Spec 2026-10-10-hybrid-dictation-stack-design.
export interface Region { name: string; includes: string }
export interface StackPart { text: string; group: string }
export interface StackUnit {
	id: number;
	text: string;
	group: string | null;
	structure: string | null;
	attach_to: number | null;
	parts: StackPart[] | null;
	covers: string[];
	pinned: boolean;
	heading: boolean;
}
export interface StackSchema {
	regions: Region[];
	groups: string[];
	pills: string[];
	source: string;
	family: string | null;
	key: string;
	provisional: boolean;
}
export interface GroupResult {
	units: StackUnit[];
	new_ids: number[];
	pills: string[];
	gate: Record<string, unknown>[];
	problems: string[];
	timings_ms: Record<string, number>;
	error: string | null;
}
export type StackOrder = 'anatomy' | 'dictated';
export interface ViewRow { unitId: number; text: string; structure: string | null; partOf: number | null; pinned: boolean; children: ViewRow[] }
export interface ViewGroup { name: string; rows: ViewRow[] }
export interface StackView { groups: ViewGroup[]; unplaced: ViewRow[] }
```

- [ ] **Step 2: Write the failing flag test**

`flag.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { HYBRID_STACK_KEY, hybridStackOn } from './flag';

const store = (v: string | null) => ({ getItem: (k: string) => (k === HYBRID_STACK_KEY ? v : null) }) as Storage;

describe('hybridStackOn', () => {
	it('is on when the server allows it and the user has not opted out', () => {
		expect(hybridStackOn(store(null), true)).toBe(true);
	});
	it('is off when the server does not allow it', () => {
		expect(hybridStackOn(store(null), false)).toBe(false);
	});
	it('is off when the user opted out', () => {
		expect(hybridStackOn(store('0'), true)).toBe(false);
	});
});
```

- [ ] **Step 3: Run it to see it fail**

Run: `npx vitest run src/lib/hybrid-stack/flag.test.ts`
Expected: FAIL — cannot find module `./flag`

- [ ] **Step 4: Implement `flag.ts`**

```ts
// The hybrid stack is on when the server allows it (RR_HYBRID_STACK, with the dictation package) and
// the user has not opted out (localStorage rr_hybrid_stack = "0"), as rr_dictation_v2 does.
export const HYBRID_STACK_KEY = 'rr_hybrid_stack';

function storage(): Storage | undefined {
	try {
		return typeof localStorage !== 'undefined' ? localStorage : undefined;
	} catch {
		return undefined;
	}
}

export function hybridStackOn(store = storage(), serverAllows = false): boolean {
	if (!serverAllows) return false;
	try {
		return store?.getItem(HYBRID_STACK_KEY) !== '0';
	} catch {
		return true;
	}
}
```

- [ ] **Step 5: Run it to see it pass**

Run: `npx vitest run src/lib/hybrid-stack/flag.test.ts`
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add src/lib/hybrid-stack/types.ts src/lib/hybrid-stack/flag.ts src/lib/hybrid-stack/flag.test.ts
git commit -m "feat(hybrid-stack): frontend types and flag"
```

---

### Task 15: View model and manual moves (`stackState.ts`)

**Files:**
- Create: `frontend/src/lib/hybrid-stack/stackState.ts`
- Test: `frontend/src/lib/hybrid-stack/stackState.test.ts`

- [ ] **Step 1: Write the failing tests**

```ts
import { describe, expect, it } from 'vitest';
import { buildView, moveUnit, sentenceOffset } from './stackState';
import type { StackUnit } from './types';

const u = (id: number, text: string, group: string | null, extra: Partial<StackUnit> = {}): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], pinned: false, heading: false, ...extra
});
const GROUPS = ['Technique', 'Liver', 'Kidneys', 'General', 'Conclusion'];

describe('buildView', () => {
	it('orders groups by the schema, nests attached sentences, hides headings, keeps unplaced apart', () => {
		const units = [
			u(0, 'CT abdomen.', 'Technique'),
			u(1, 'Kidneys normal.', 'Kidneys'),
			u(2, 'A liver cyst.', 'Liver'),
			u(3, 'It measures 2 cm.', 'Liver', { attach_to: 2 }),
			u(4, 'Conclusion.', 'Conclusion', { heading: true }),
			u(5, 'Simple cyst.', 'Conclusion'),
			u(6, 'Just said.', null)
		];
		const v = buildView(units, GROUPS);
		expect(v.groups.map((g) => g.name)).toEqual(['Technique', 'Liver', 'Kidneys', 'Conclusion']);
		expect(v.groups[1].rows[0].children.map((c) => c.text)).toEqual(['It measures 2 cm.']);
		expect(v.groups[3].rows.map((r) => r.text)).toEqual(['Simple cyst.']);
		expect(v.unplaced.map((r) => r.text)).toEqual(['Just said.']);
	});

	it('shows split parts in their own groups', () => {
		const units = [u(0, 'Kidneys normal, and a liver cyst.', 'Kidneys', {
			parts: [{ text: 'Kidneys normal,', group: 'Kidneys' }, { text: 'and a liver cyst.', group: 'Liver' }]
		})];
		const v = buildView(units, GROUPS);
		expect(v.groups.map((g) => [g.name, g.rows[0].text, g.rows[0].partOf])).toEqual([
			['Liver', 'and a liver cyst.', 0],
			['Kidneys', 'Kidneys normal,', 0]
		]);
	});
});

describe('moveUnit', () => {
	it('pins the sentence in the new group and clears its link and parts', () => {
		const units = [u(0, 'A.', 'Liver'), u(1, 'B.', 'Liver', { attach_to: 0, parts: [] })];
		const moved = moveUnit(units, 1, 'Kidneys');
		expect(moved[1]).toMatchObject({ group: 'Kidneys', pinned: true, attach_to: null, parts: null });
		expect(units[1].group).toBe('Liver');
	});
});

describe('sentenceOffset', () => {
	it('finds the nth occurrence of a sentence', () => {
		expect(sentenceOffset('A. B. A.', [u(0, 'A.', 'x'), u(1, 'B.', 'x'), u(2, 'A.', 'x')], 2)).toBe(6);
	});
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/lib/hybrid-stack/stackState.test.ts`
Expected: FAIL — cannot find module `./stackState`

- [ ] **Step 3: Implement `stackState.ts`**

```ts
import type { StackUnit, StackView, ViewGroup, ViewRow } from './types';

const row = (u: StackUnit, text = u.text, partOf: number | null = null): ViewRow => ({
	unitId: u.id, text, structure: u.structure, partOf, pinned: u.pinned, children: []
});

/** The grouped view: groups in schema order, sentences in dictated order, attached sentences nested
 *  under their parent, heading-only sentences hidden, unplaced sentences kept apart ("just dictated"). */
export function buildView(units: StackUnit[], groups: string[]): StackView {
	const rows = new Map<string, ViewRow[]>(groups.map((g) => [g, []]));
	const byId = new Map<number, ViewRow>();
	const unplaced: ViewRow[] = [];
	const add = (g: string, r: ViewRow) => {
		if (!rows.has(g)) rows.set(g, []);
		rows.get(g)!.push(r);
	};
	for (const u of units) {
		if (u.heading) continue;
		if (u.group === null) {
			unplaced.push(row(u));
			continue;
		}
		if (u.attach_to !== null && byId.has(u.attach_to)) {
			byId.get(u.attach_to)!.children.push(row(u));
			continue;
		}
		if (u.parts && u.parts.length > 1) {
			u.parts.forEach((p, k) => {
				const r = row(u, p.text, u.id);
				if (k === 0) byId.set(u.id, r);
				add(p.group, r);
			});
			continue;
		}
		const r = row(u);
		byId.set(u.id, r);
		add(u.group, r);
	}
	const out: ViewGroup[] = [];
	for (const [name, rs] of rows) if (rs.length) out.push({ name, rows: rs });
	return { groups: out, unplaced };
}

/** A drag to another group: the sentence is pinned there (the server never changes it again). */
export function moveUnit(units: StackUnit[], id: number, group: string): StackUnit[] {
	return units.map((u) => (u.id === id ? { ...u, group, pinned: true, attach_to: null, parts: null } : u));
}

/** Character offset of unit `id` in the verbatim text (the nth occurrence of its sentence). */
export function sentenceOffset(text: string, units: StackUnit[], id: number): number {
	const target = units.find((u) => u.id === id);
	if (!target) return -1;
	const nth = units.filter((u) => u.id < id && u.text === target.text).length;
	let pos = -1;
	for (let k = 0; k <= nth; k++) {
		pos = text.indexOf(target.text, pos + 1);
		if (pos < 0) return -1;
	}
	return pos;
}
```

- [ ] **Step 4: Run them to see them pass**

Run: `npx vitest run src/lib/hybrid-stack/stackState.test.ts`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/lib/hybrid-stack/stackState.ts src/lib/hybrid-stack/stackState.test.ts
git commit -m "feat(hybrid-stack): view model, manual moves, sentence offsets"
```

---

### Task 16: API client (`api.ts`)

**Files:**
- Create: `frontend/src/lib/hybrid-stack/api.ts`
- Test: `frontend/src/lib/hybrid-stack/api.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { postGroup } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('postGroup', () => {
	it('posts text, regions and the previous units with the bearer token', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify({ units: [], new_ids: [], pills: [], gate: [], problems: [], timings_ms: {}, error: null })));
		vi.stubGlobal('fetch', fetchMock);
		await postGroup('tok', { scan_type: 'CT', text: 'A.', regions: [], previous: [] });
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/api/canvas/stack/group')).toBe(true);
		expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
		expect(JSON.parse(init.body as string).text).toBe('A.');
	});
});
```

- [ ] **Step 2: Run it to see it fail**

Run: `npx vitest run src/lib/hybrid-stack/api.test.ts`
Expected: FAIL — cannot find module `./api`

- [ ] **Step 3: Implement `api.ts`**

```ts
import { API_URL } from '$lib/config.js';
import type { GroupResult, Region, StackSchema, StackUnit } from './types';

async function post<T>(token: string | null, path: string, body: unknown, keepalive = false): Promise<T> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (token) headers['Authorization'] = `Bearer ${token}`;
	const res = await fetch(`${API_URL}/api/canvas/stack/${path}`, { method: 'POST', headers, body: JSON.stringify(body), keepalive });
	if (!res.ok) throw new Error(`stack ${path} ${res.status}`);
	return (await res.json()) as T;
}

export const fetchSchema = (token: string | null, body: { scan_type: string; clinical_history: string; template_id?: string | null }) =>
	post<StackSchema>(token, 'schema', body);

export const postGroup = (token: string | null, body: { scan_type: string; text: string; regions: Region[]; previous: StackUnit[] }) =>
	post<GroupResult>(token, 'group', body);

export const postClose = (token: string | null, body: { units: StackUnit[]; regions: Region[] }) =>
	post<GroupResult>(token, 'close', body);

export interface StackLog {
	session_id: string; scan_type: string; schema_key: string | null; schema_source: string | null; provisional: boolean;
	units: StackUnit[]; pills_derived: string[]; pills_jev: string[]; sections: string[]; structured_text: string;
	manual_moves: number; latency_ms: Record<string, number>;
}
export const postLog = (token: string | null, body: StackLog) => post<{ ok: boolean }>(token, 'log', body, true);
```

- [ ] **Step 4: Run it to see it pass**

Run: `npx vitest run src/lib/hybrid-stack/api.test.ts`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/lib/hybrid-stack/api.ts src/lib/hybrid-stack/api.test.ts
git commit -m "feat(hybrid-stack): api client"
```

---

### Task 17: `HybridStackView.svelte`

**Files:**
- Create: `frontend/src/lib/hybrid-stack/HybridStackView.svelte`
- Test: `frontend/src/lib/hybrid-stack/HybridStackView.svelte.test.ts`

- [ ] **Step 1: Write the failing component test**

```ts
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import HybridStackView from './HybridStackView.svelte';
import type { StackUnit } from './types';

const u = (id: number, text: string, group: string | null, extra: Partial<StackUnit> = {}): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], pinned: false, heading: false, ...extra
});

describe('HybridStackView', () => {
	it('renders groups, structure labels and just-dictated lines; a click selects the sentence', async () => {
		const onSelect = vi.fn();
		render(HybridStackView, {
			units: [u(0, 'A liver cyst.', 'Liver', { structure: 'liver' }), u(1, 'Just said.', null)],
			groups: ['Technique', 'Liver', 'General', 'Conclusion'],
			onSelect,
			onMove: vi.fn()
		});
		await expect.element(page.getByRole('heading', { name: 'Liver' })).toBeInTheDocument();
		await expect.element(page.getByText('· liver')).toBeInTheDocument();
		await expect.element(page.getByText('Just dictated')).toBeInTheDocument();
		await page.getByText('A liver cyst.').click();
		expect(onSelect).toHaveBeenCalledWith(0);
	});
});
```

- [ ] **Step 2: Run it to see it fail**

Run: `npx vitest run src/lib/hybrid-stack/HybridStackView.svelte.test.ts`
Expected: FAIL — cannot find module `./HybridStackView.svelte`

- [ ] **Step 3: Implement the component**

```svelte
<script lang="ts">
	// The grouped view of the verbatim dictation (spec §3.1). Read-only text: a click selects the
	// sentence in the verbatim editor; a drag to another group pins it there.
	import { buildView } from './stackState';
	import type { StackUnit, ViewRow } from './types';

	let {
		units,
		groups,
		onSelect,
		onMove
	}: {
		units: StackUnit[];
		groups: string[];
		onSelect: (id: number) => void;
		onMove: (id: number, group: string) => void;
	} = $props();

	const view = $derived(buildView(units, groups));
	let dragOver: string | null = $state(null);

	function drop(e: DragEvent, group: string) {
		e.preventDefault();
		dragOver = null;
		const id = Number(e.dataTransfer?.getData('text/plain'));
		if (Number.isFinite(id)) onMove(id, group);
	}
</script>

{#snippet line(r: ViewRow, nested: boolean)}
	<li>
		<button
			type="button"
			draggable="true"
			class="w-full text-left text-sm leading-6 hover:bg-slate-50 rounded px-1 {nested ? 'pl-5 text-slate-600' : ''}"
			ondragstart={(e) => e.dataTransfer?.setData('text/plain', String(r.unitId))}
			onclick={() => onSelect(r.unitId)}
		>
			{#if nested}<span aria-hidden="true" class="text-slate-400">↳ </span>{/if}{r.text}
			{#if r.structure}<span class="ml-1 text-xs text-slate-400">· {r.structure}</span>{/if}
			{#if r.pinned}<span class="ml-1 text-xs text-slate-400" title="Placed by you">•</span>{/if}
		</button>
		{#if r.children.length}
			<ul>{#each r.children as c (c.unitId + ':' + c.text)}{@render line(c, true)}{/each}</ul>
		{/if}
	</li>
{/snippet}

<div class="space-y-3" data-testid="hybrid-stack">
	{#each view.groups as g (g.name)}
		<section
			class="rounded {dragOver === g.name ? 'bg-sky-50' : ''}"
			ondragover={(e) => { e.preventDefault(); dragOver = g.name; }}
			ondragleave={() => (dragOver = null)}
			ondrop={(e) => drop(e, g.name)}
			aria-label={g.name}
		>
			<h3 class="text-xs font-semibold uppercase tracking-wide text-slate-500">{g.name}</h3>
			<ul>{#each g.rows as r (r.unitId + ':' + r.text)}{@render line(r, false)}{/each}</ul>
		</section>
	{/each}
	{#if view.unplaced.length}
		<section class="opacity-50" aria-label="Just dictated">
			<h3 class="text-xs font-semibold uppercase tracking-wide text-slate-400">Just dictated</h3>
			<ul>{#each view.unplaced as r (r.unitId)}{@render line(r, false)}{/each}</ul>
		</section>
	{/if}
</div>
```

The empty groups (no sentences) are not drop targets in this version; a drag goes to a group that already has content. Dropping on a heading works because the `<section>` is the target.

- [ ] **Step 4: Run it to see it pass**

Run: `npx vitest run src/lib/hybrid-stack/HybridStackView.svelte.test.ts`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/lib/hybrid-stack/HybridStackView.svelte src/lib/hybrid-stack/HybridStackView.svelte.test.ts
git commit -m "feat(hybrid-stack): grouped view component"
```

---

### Task 18: Wire the stack into `DictationScratchpad.svelte`

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte`

The verbatim CodeMirror `editor` stays the only text and the only editing surface. With the stack on, the Verbatim/Structured toggle is replaced by an order toggle; "By anatomy" shows `HybridStackView` over the (hidden, still live) editor; "As dictated" shows the editor. The old Structured build keeps running in the background (shadow).

- [ ] **Step 1: Add props and state** (after the existing props block, ~line 75)

```ts
	import HybridStackView from '$lib/hybrid-stack/HybridStackView.svelte';
	import { postClose, postGroup, postLog } from '$lib/hybrid-stack/api';
	import { moveUnit, sentenceOffset } from '$lib/hybrid-stack/stackState';
	import type { Region, StackOrder, StackUnit } from '$lib/hybrid-stack/types';

	export let hybridStack = false; // the grouped view (rr_hybrid_stack); the old tabs run in shadow
	export let stackRegions: Region[] = [];
	export let stackGroups: string[] = [];
	export let stackSchemaMeta: { key: string; source: string; provisional: boolean } | null = null;
	export let onStackPills: (pills: string[]) => void = () => {};

	const GROUP_DEBOUNCE_MS = 600;
	const CLOSE_IDLE_MS = 1500;
	let stackOrder: StackOrder = 'anatomy';
	let stackUnits: StackUnit[] = [];
	let stackTimer: ReturnType<typeof setTimeout> | null = null;
	let closeTimer: ReturnType<typeof setTimeout> | null = null;
	let stackBusy = false;
	let stackSessionId = crypto.randomUUID();
	let stackManualMoves = 0;
	let stackLatency: Record<string, number> = {};
	let lastJevCovered: string[] = []; // shadow: today's coverage pills, for the log
	// Shadow: keep building the old Structured text in the background while the stack is on.
	$: if (hybridStack) structuredWanted = true;
```

- [ ] **Step 2: Add the grouping functions** (next to `scheduleStructure`, ~line 1276)

```ts
	function scheduleGroup(delay = GROUP_DEBOUNCE_MS): void {
		if (!hybridStack || !stackRegions.length) return;
		if (stackTimer) clearTimeout(stackTimer);
		stackTimer = setTimeout(() => { stackTimer = null; void runGroup(); }, delay);
	}
	async function runGroup(): Promise<void> {
		if (stackBusy || structureBusy()) { scheduleGroup(); return; } // as the Structured build: wait for pending text
		const text = verbatimNow;
		stackBusy = true;
		try {
			const res = await postGroup($token, { scan_type: scanType, text, regions: stackRegions, previous: stackUnits });
			if (verbatimNow === text) {
				stackUnits = res.units;
				onStackPills(res.pills);
				for (const [k, v] of Object.entries(res.timings_ms)) stackLatency[k] = Math.max(stackLatency[k] ?? 0, v);
			} else scheduleGroup(0);
		} catch {
			// fail open: the verbatim text is on screen; the next settle retries
		} finally { stackBusy = false; }
	}
	function stackMove(id: number, group: string): void {
		stackUnits = moveUnit(stackUnits, id, group);
		stackManualMoves += 1;
	}
	function stackSelect(id: number): void {
		const at = sentenceOffset(verbatimNow, stackUnits, id);
		stackOrder = 'dictated';
		if (at >= 0 && editor) {
			const unit = stackUnits.find((u) => u.id === id);
			editor.dispatch({ selection: { anchor: at, head: at + (unit?.text.length ?? 0) }, scrollIntoView: true });
			editor.focus();
		}
	}
	function scheduleClose(): void {
		if (!hybridStack) return;
		if (closeTimer) clearTimeout(closeTimer);
		closeTimer = setTimeout(async () => {
			closeTimer = null;
			if (isRecording || !stackUnits.length) return;
			try {
				const res = await postClose($token, { units: stackUnits, regions: stackRegions });
				stackUnits = res.units;
				onStackPills(res.pills);
			} catch { /* fail open */ }
			void sendStackLog();
		}, CLOSE_IDLE_MS);
	}
	async function sendStackLog(): Promise<void> {
		if (!hybridStack || !stackUnits.length) return;
		try {
			await postLog($token, {
				session_id: stackSessionId, scan_type: scanType, schema_key: stackSchemaMeta?.key ?? null,
				schema_source: stackSchemaMeta?.source ?? null, provisional: stackSchemaMeta?.provisional ?? false,
				units: stackUnits, pills_derived: [...new Set(stackUnits.flatMap((u) => u.covers))],
				pills_jev: lastJevCovered, sections: checklistSections, structured_text: structured.text ?? '',
				manual_moves: stackManualMoves, latency_ms: stackLatency
			});
		} catch { /* logging never affects dictation */ }
	}
```

- [ ] **Step 3: Hook the triggers**

1. In the `editor` update listener (~line 1579-1625), right after the existing `scheduleStructure();` call in the non-empty branch, add `scheduleGroup();`. In the empty branch (`if (!content.trim())`), add `stackUnits = []; onStackPills([]);`.
2. Where the component reacts to recording stopping (the handler that calls `onRecordingChange(false)`), add `scheduleClose();`.
3. In `_runReview` (~line 1331), where the coverage response is handled (`onCoveredSectionsChange(data.covered_sections)`), add `lastJevCovered = data.covered_sections ?? [];` on the line before it.
4. In the scratchpad clear handler (the function that calls `onScratchpadClear()`), add before it: `void sendStackLog(); stackUnits = []; stackSessionId = crypto.randomUUID(); stackManualMoves = 0; stackLatency = {};`.
5. In `onDestroy` (add the import from `svelte` if it is not there), add `void sendStackLog();`.
6. When `stackRegions` change (a new schema), regroup from scratch: add
```ts
	let lastRegionsKey = '';
	$: { const k = stackRegions.map((r) => r.name).join('|'); if (k !== lastRegionsKey) { lastRegionsKey = k; stackUnits = []; scheduleGroup(0); } }
```

- [ ] **Step 4: Swap the toggle and the view** (markup, ~lines 1693-1706 and 1821-1838)

Wrap the existing Verbatim/Structured toggle (`<div role="group" aria-label="Polish mode">…</div>`) in `{#if !hybridStack} … {:else} … {/if}`, with this in the `{:else}` branch:
```svelte
		<div role="group" aria-label="Stack order" class="inline-flex rounded-md border border-slate-200 text-xs">
			<button type="button" class="px-2 py-1 {stackOrder === 'anatomy' ? 'bg-slate-100 font-medium' : ''}"
				aria-pressed={stackOrder === 'anatomy'} onclick={() => (stackOrder = 'anatomy')}>By anatomy</button>
			<button type="button" class="px-2 py-1 {stackOrder === 'dictated' ? 'bg-slate-100 font-medium' : ''}"
				aria-pressed={stackOrder === 'dictated'} onclick={() => (stackOrder = 'dictated')}>As dictated</button>
		</div>
```
(Use the same event-attribute style as the surrounding markup: if the file uses `on:click`, write `on:click` here.)

At the editor mount point (~1826-1827), change the verbatim editor's hide condition from `class:hidden={polishMode === 'structured'}` to `class:hidden={hybridStack ? stackOrder === 'anatomy' : polishMode === 'structured'}`; change the structured editor's to `class:hidden={hybridStack || polishMode !== 'structured'}`. Immediately after the two editor containers add:
```svelte
		{#if hybridStack && stackOrder === 'anatomy'}
			<HybridStackView units={stackUnits} groups={stackGroups} onSelect={stackSelect} onMove={stackMove} />
		{/if}
```
When `hybridStack` is on, `polishMode` stays `'clean'` (the parent never switches it), so `onContentChange` keeps receiving the verbatim text, IntelliPrompts keep using `editor`, and generation is unchanged.

- [ ] **Step 5: Type-check and run the existing scratchpad-adjacent tests**

Run: `bun run check` then `npx vitest run src/lib`
Expected: no new svelte-check errors versus the baseline (`git stash; bun run check; git stash pop` to compare if unsure); all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/lib/components/DictationScratchpad.svelte
git commit -m "feat(hybrid-stack): grouped view in the scratchpad; Structured build kept in shadow"
```

---

### Task 19: Schema and pills in `IntelliDictateTab.svelte`, `TemplateForm.svelte`, `+page.svelte`

**Files:**
- Modify: `frontend/src/routes/+page.svelte` (~343-357), `frontend/src/routes/components/IntelliDictateTab.svelte`, `frontend/src/routes/components/TemplateForm.svelte`

- [ ] **Step 1: Carry the server flag** — in `+page.svelte`, in the `apiKeyStatus = {…}` object, after `dictation_v2: data.dictation_v2 === true`, add:
```ts
						hybrid_stack: data.hybrid_stack === true
```

- [ ] **Step 2: IntelliDictateTab — fetch the schema beside `/sections`**

Add imports and state near `dictationConfig` (~line 134):
```ts
	import { fetchSchema } from '$lib/hybrid-stack/api';
	import { hybridStackOn } from '$lib/hybrid-stack/flag';
	import type { StackSchema } from '$lib/hybrid-stack/types';

	$: hybridStack = hybridStackOn(undefined, apiKeyStatus?.hybrid_stack === true && dictationConfig !== null);
	let stackSchema: StackSchema | null = null;
	let stackPills: string[] = [];
	async function loadStackSchema(scan: string, history: string) {
		if (!hybridStack || !scan.trim()) { stackSchema = null; return; }
		try { stackSchema = await fetchSchema($token, { scan_type: scan, clinical_history: history }); stackPills = []; }
		catch { stackSchema = null; } // fail open: the old pills show
	}
```
Next to each existing `/api/canvas/sections` call (~lines 228 and 262) add `void loadStackSchema(scanType, clinicalHistory);` (the `/sections` call stays: it is the shadow list and the fallback).

- [ ] **Step 3: IntelliDictateTab — pills from the stack when it is on**

Change `allChecklistSections` (~line 160) to:
```ts
	$: allChecklistSections = hybridStack && stackSchema ? stackSchema.pills : prePoppedSections;
```
In the pill strip (~955-972) change the state expression so that, with the stack on, a pill is covered when it is in `stackPills`:
```ts
hybridStack && stackSchema ? (stackPills.includes(section) ? 'covered' : 'absent')
	: pillThresholds && coverageScores ? pillState(coverageScores[section], pillThresholds)
	: coveredSections.has(section) ? 'covered' : 'absent'
```
Pass to `<DictationScratchpad …>` (~977-1000):
```svelte
		{hybridStack}
		stackRegions={stackSchema?.regions ?? []}
		stackGroups={stackSchema?.groups ?? []}
		stackSchemaMeta={stackSchema ? { key: stackSchema.key, source: stackSchema.source, provisional: stackSchema.provisional } : null}
		onStackPills={(p) => (stackPills = p)}
```
`checklistSections={prePoppedSections}` stays as it is: the Jev coverage call keeps running on the old list (shadow) and its result is logged by the scratchpad.

- [ ] **Step 4: TemplateForm — the template path**

In `TemplateForm.svelte` add the same imports, `hybridStack`, `stackSchema`, `stackPills` and `loadStackSchema`, but call `fetchSchema($token, { scan_type: <the form's scan type>, clinical_history: variableValues['CLINICAL_HISTORY'] ?? '', template_id: selectedTemplate?.id ?? null })` next to the existing `/api/canvas/sections-from-template` call (~line 280). For the scan type, use the same value the form passes to `DictationScratchpad` as `scanType` (~line 807-820). Apply the same pill-strip change to its binary strip (~line 796) and pass the same five props to `<DictationScratchpad>`. TemplateForm has no `dictationConfig`; compute `hybridStack = hybridStackOn(undefined, apiKeyStatus?.hybrid_stack === true)` if it receives `apiKeyStatus`, otherwise add `apiKeyStatus` as a prop passed from its parent the same way IntelliDictateTab receives it.

- [ ] **Step 5: Type-check and test**

Run: `bun run check` then `npx vitest run`
Expected: no new svelte-check errors; all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/routes/+page.svelte src/routes/components/IntelliDictateTab.svelte src/routes/components/TemplateForm.svelte
git commit -m "feat(hybrid-stack): schema fetch and derived pills on quick and template paths; old pills in shadow"
```

---

### Task 20: Dev route for the hand read, and the reviewer page

**Files:**
- Create: `frontend/src/routes/dev/hybrid-stack/+page.ts`, `frontend/src/routes/dev/hybrid-stack/+page.svelte`, `frontend/src/routes/stack-families/+page.svelte`

- [ ] **Step 1: Dev route guard** — `src/routes/dev/hybrid-stack/+page.ts`:
```ts
import { requireDevRoute } from '$lib/guards/dev-route';
export const load = () => requireDevRoute();
```

- [ ] **Step 2: Dev page** — paste dictation, replay it sentence by sentence through the real endpoints, see the view:
```svelte
<script lang="ts">
	import { token } from '$lib/stores/auth';
	import HybridStackView from '$lib/hybrid-stack/HybridStackView.svelte';
	import { fetchSchema, postClose, postGroup } from '$lib/hybrid-stack/api';
	import { moveUnit } from '$lib/hybrid-stack/stackState';
	import type { StackSchema, StackUnit } from '$lib/hybrid-stack/types';

	let scanType = $state('CT abdomen and pelvis with contrast');
	let history = $state('');
	let templateId = $state('');
	let dictation = $state('');
	let schema: StackSchema | null = $state(null);
	let units: StackUnit[] = $state([]);
	let pills: string[] = $state([]);
	let status = $state('');

	async function run() {
		status = 'schema…';
		schema = await fetchSchema($token, { scan_type: scanType, clinical_history: history, template_id: templateId || null });
		units = [];
		const sentences = dictation.split(/(?<=[.?!])\s+/).filter((s) => s.trim());
		let text = '';
		for (const s of sentences) {
			text = text ? `${text} ${s}` : s;
			status = `grouping ${text.length} chars…`;
			const res = await postGroup($token, { scan_type: scanType, text, regions: schema.regions, previous: units });
			units = res.units;
			pills = res.pills;
		}
		const closed = await postClose($token, { units, regions: schema.regions });
		units = closed.units;
		pills = closed.pills;
		status = `done · ${schema.source}${schema.provisional ? ' (provisional)' : ''} · ${schema.key}`;
	}
</script>

<div class="mx-auto max-w-5xl p-6 space-y-4">
	<h1 class="text-lg font-semibold">Hybrid stack (dev)</h1>
	<div class="grid grid-cols-3 gap-2">
		<input class="border rounded px-2 py-1" bind:value={scanType} placeholder="Scan type" />
		<input class="border rounded px-2 py-1" bind:value={history} placeholder="Clinical history" />
		<input class="border rounded px-2 py-1" bind:value={templateId} placeholder="Template id (optional)" />
	</div>
	<textarea class="w-full h-40 border rounded p-2 text-sm" bind:value={dictation} placeholder="Paste dictation"></textarea>
	<button class="rounded bg-slate-800 px-3 py-1 text-white text-sm" onclick={run}>Replay</button>
	<p class="text-xs text-slate-500">{status}</p>
	{#if schema}
		<p class="text-xs">Pills: {pills.join(' · ') || '—'}</p>
		<HybridStackView {units} groups={schema.groups} onSelect={() => {}} onMove={(id, g) => (units = moveUnit(units, id, g))} />
	{/if}
</div>
```

- [ ] **Step 3: Reviewer page** — `src/routes/stack-families/+page.svelte` (not a dev route: production review; the server enforces `RR_STACK_REVIEWERS` and returns 403 to anyone else):
```svelte
<script lang="ts">
	import { onMount } from 'svelte';
	import { API_URL } from '$lib/config.js';
	import { token } from '$lib/stores/auth';

	type Fam = { key: string; scan_type: string; regions: { name: string; includes: string }[]; source: string; status: string };
	let rows: Fam[] = $state([]);
	let error = $state('');
	let edits: Record<string, string> = $state({});
	const headers = () => ({ 'Content-Type': 'application/json', ...($token ? { Authorization: `Bearer ${$token}` } : {}) });

	async function load() {
		const res = await fetch(`${API_URL}/api/canvas/stack/families?status=provisional`, { headers: headers() });
		if (!res.ok) { error = res.status === 403 ? 'Not a reviewer.' : `Error ${res.status}`; return; }
		rows = await res.json();
		edits = Object.fromEntries(rows.map((r) => [r.key, JSON.stringify(r.regions, null, 1)]));
	}
	async function decide(key: string, status: 'approved' | 'rejected') {
		const body: Record<string, unknown> = { status };
		if (status === 'approved') body.regions = JSON.parse(edits[key]);
		const res = await fetch(`${API_URL}/api/canvas/stack/families/${encodeURIComponent(key)}`, { method: 'POST', headers: headers(), body: JSON.stringify(body) });
		if (res.ok) rows = rows.filter((r) => r.key !== key);
	}
	onMount(load);
</script>

<div class="mx-auto max-w-4xl p-6 space-y-4">
	<h1 class="text-lg font-semibold">Stack families awaiting review</h1>
	{#if error}<p class="text-sm text-red-600">{error}</p>{/if}
	{#each rows as r (r.key)}
		<section class="rounded border p-3 space-y-2">
			<h2 class="font-medium">{r.scan_type} <span class="text-xs text-slate-500">({r.source})</span></h2>
			<textarea class="w-full h-48 font-mono text-xs border rounded p-2" bind:value={edits[r.key]}></textarea>
			<div class="flex gap-2">
				<button class="rounded bg-emerald-700 px-3 py-1 text-white text-sm" onclick={() => decide(r.key, 'approved')}>Approve (with edits)</button>
				<button class="rounded bg-slate-200 px-3 py-1 text-sm" onclick={() => decide(r.key, 'rejected')}>Reject</button>
			</div>
		</section>
	{:else}
		{#if !error}<p class="text-sm text-slate-500">Nothing to review.</p>{/if}
	{/each}
</div>
```

- [ ] **Step 4: Type-check**

Run: `bun run check`
Expected: no new errors.

- [ ] **Step 5: Hand read (with Hassan)** — start backend (`RR_DICTATION_V2=1`) and frontend (`PUBLIC_ENABLE_DEV_ROUTES=true`), open `/dev/hybrid-stack`, paste three dictations from `backend/tests/fixtures/hybrid_stack/replay_heldout.json` (the last `steps` entry of h03, h05 and h12) and one template case with a template id, and check: groups read right, follow-ons nest, the conclusion lands in Conclusion, pills match the grouped content, a drag pins. Then dictate one live case in the main app with the flag on and confirm the old tabs are gone, the order toggle works, and a click on a grouped line selects it in "As dictated".

- [ ] **Step 6: Commit**

```bash
git add src/routes/dev/hybrid-stack src/routes/stack-families
git commit -m "feat(hybrid-stack): dev replay route and reviewer page"
```

---

# Part C — Deploy and live testing

### Task 21: Deploy with the new layout active

- [ ] **Step 1: Full suites**

Run (backend): `PYTHONPATH=src .venv/bin/python -m pytest -q`
Run (frontend): `npx vitest run` and `bun run check`
Expected: all green; svelte-check at baseline.

- [ ] **Step 2: Replay eval gate**

Run: `PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.hybrid_stack_eval`
Expected: the Task 13 gates hold.

- [ ] **Step 3: Branch, PR, merge** — push the branch and open a PR against `main` with the spec and plan linked; the description lists the switches (`RR_HYBRID_STACK=0` server kill switch; `localStorage rr_hybrid_stack=0` per user), the reviewer env (`RR_STACK_REVIEWERS`) and the migration. Merge only on Hassan's go-ahead.

- [ ] **Step 4: Railway** — set `RR_STACK_REVIEWERS=hass.ahmad.95@gmail.com` (Hassan's account email). Leave `RR_HYBRID_STACK` unset (default on). Confirm the migration ran (`stack_schema_families`, `dictation_stack_logs` exist — Metabase SQL).

- [ ] **Step 5: Prod smoke** (Chrome session, per the prod smoke-testing method): `/api/settings/status` returns `"hybrid_stack": true`; dictate one quick case and one template case; the grouped view shows, pills tick, `dictation_stack_logs` gains a row with `pills_jev`, `sections` and `structured_text` filled (the shadow is running).

### Task 22: Live testing and retirement gates

- [ ] **Step 1: Metabase questions** over `dictation_stack_logs` (one per gate):
  - pill agreement: per session, `pills_derived` vs `pills_jev` restricted to names present in both lists' vocabularies (quick path: compare at region level only where `sections` maps cleanly; template path: direct);
  - manual moves per session (`manual_moves`), and the share of sessions with any;
  - grouper and gate latency (`latency_ms`);
  - provisional families created (`stack_schema_families` where `status = 'provisional'`).
- [ ] **Step 2: Peer read** a sample of 10 sessions per week from `units` (Claude peer read; Hassan spot-checks boundary items).
- [ ] **Step 3: Retirement (separate plan)** — when the gates hold (pill agreement on real dictation, manual moves rare, no latency or fidelity regressions), write a short plan to stop each shadow call and archive its code path: the Structured build (`CANVAS_PROCESS_SYSTEM_PROMPT` structured mode, `structuredView.ts`), `/sections` and `/sections-from-template` in dictation, and the per-update Jev coverage call.
