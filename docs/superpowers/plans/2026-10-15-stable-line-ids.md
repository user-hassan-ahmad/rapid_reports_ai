# Stable Sheet-Line IDs and the Normals Confirm Record: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every line-bound unit of a template's skill sheet a stable `uid` kept across persisted saves, key the decision ledger on it (uid first, today's key matching second), and add the server-written normals confirm record and `sheet_rev`. Writer uncertainty items are deferred to slice 4 (see "Deferred to slice 4").

**Architecture:** A sidecar registry (`template_config["line_registry"]`) re-bound by pure code on every persisted save. "Same text" is exact equality after representation-only normalising (lookalike characters, whitespace; spec decision 7): no similarity score, no cosmetic matching. One helper, `template_sheet_save.persist_sheet`, owns every persisted save (vet, rebind, stamp ledger uids, `sheet_rev`); stateless endpoints keep calling `vet_sheet` with no registry and never mint. Confirms are computed server-side from the stored sheet and registry.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy (JSON column `Template.template_config`), Pydantic v2, pytest (asyncio auto mode, SQLite in-memory in tests).

**Spec (source of truth):** `docs/superpowers/specs/2026-10-15-stable-line-ids-design.md`. Its decisions are not re-opened here; where it cannot be built exactly as written, see the next section.

---

## Spec gaps found while planning

Each of these is either a place where the spec's wording cannot be met literally, or a choice the spec leaves open. Hassan should read 1 and 2 before execution starts. The plan follows the spec as of `d234b67a` (Hassan's decisions 4 and 5: the wider meaningful-token set with protected negation and hedge words, filler scope ending at the sentence's earlier negation or hedge, quote-after-number as a unit token, Task 1, since superseded by decision 7: exact matching only, representation-normalised, cosmetic layer removed; a normal follows a renamed paragraph only with its own text unchanged, Task 3; a renamed group's confirm is stale, Task 13).

1. **Uid-first resolution uses `match`, not `uids_for` (spec "Registry threading": "resolves uid-first (via `uids_for` on the current parse)").** `uids_for` pairs by exact identity only. During a rebuild, a renamed paragraph (same COVERS), the normals in it whose text is unchanged (decision 5), therefore have no uid on the incoming parse, so the entry would fall back to key matching, become a card, and heal only on the save after next. The plan adds `tlr.match(st, registry)`: the pairing `rebind` would make (exact identity and the COVERS rename rule against live units only, no revival, no minting, nothing stored). It uses the same safety rules as rebind, so it adds no new matching logic. `uids_for` is still the read-time function the spec describes (confirms, stamping). **To follow the spec literally instead**, change one line in `_uid_map` (Task 6) from `tlr.match(...)` to `tlr.uids_for(...)` and delete `test_across_a_paragraph_rename_a_normal_entry_follows_only_an_unchanged_line`.
2. **"Removal decisions … never become cards" is narrowed (plan review H1).** A removal counts as satisfied only when its line is *shown* absent: the entry carries a uid the registry knows, and no unit of the current parse holds that uid. Without that evidence (no uid, a paragraph not found or ambiguous, a reworded negative) it stays a card, as today. It applies only on the registry path (persisted saves), so `registry=None` stays exactly as today and `test_removing_a_negative_the_sheet_reworded_is_unmatched_not_kept` is unchanged.
3. **"Deterministic: same inputs, same result" vs "6 random base32 characters".** Each registry gets a random 8-hex `salt` when it is first minted; uids are `sha256(salt | kind | identity | n)`, base32, first 6 characters. Given the stored registry, rebind is fully deterministic, and two templates never share uids.
4. **Writer questions: deferred to slice 4** (spec decision 8). The gap noted here (the creator UI ignores `questions`, so they only reach Create once the client echoes them) moves with Tasks 15 and 16.
5. **Confirm endpoint, an unknown group:** returns **422** (the spec names only 404 and 409). **Storage:** `normal_confirms` is `{group id: latest record}`. "Each confirm recorded" is read as one current record per group, which keeps the config size bounded.
6. **Line identity includes the section uid as well as the paragraph uid** (the spec lists the paragraph uid for normals and negatives). This matters only for units outside any paragraph (Report-wide units that name a section). A paragraph uid already implies its section, so nothing else changes.
7. **`set_decision` keeps the existing entry's `uid`** (a new answer on the same line belongs to the same slot). **`rekey_decision` drops it.** That is how `reconcile_chat` "clears uid on any entry it re-keys" without new code in `reconcile_chat`.
8. **Existing tests that must change** (each one tests behaviour this spec changes): four `vet_sheet` spies in `tests/test_template_sheet_save_routes.py` gain `**kw` (persist_sheet passes `registry=`); `test_generation_stamp_is_total` gains `"sheet_rev": None`. (The three writer-prompt assertions that moved to the `{line, why}` format went with Task 15 to slice 4.)
9. **Dropped 2026-10-15** (was: backfill `--apply` takes the dry-run report as its plan). There is no backfill; see Task 18.
10. **Registry `text` per kind:** normal, negative and fixed store the quoted text, rule stores its raw line stripped, and section and paragraph store their name. `text_hash = "sha256:" + sha256(text)`.
11. **A legacy template saved without a sheet change keeps `sheet_rev` 0** (no stored value means 0). The first change makes it 1. (The backfill that would have set it to 1 was dropped 2026-10-15.)
12. **The per-rebuild metric** ("share resolved by uid against today's text matching") is computed by `tla.uid_share` on the incoming sheet and logged by `persist_sheet` when `origin == "rebuild"`. The rebuild fixture test prints the same numbers.
13. **Carried lines never move (plan review M2).** A carried uid pairs only with a line in the same section and paragraph (by uid) as its previous identity, both in `rebind` and in `apply_ledger`'s per-step map. A rewritten line deleted later in the run therefore cannot hand its uid to an identical line elsewhere.
14. **The upgrade script writes its planned config later, under the lock (plan review L3).** The sheet hash re-check guarantees the sheet, and so the registry and `sheet_rev` the plan computed, did not move. The server-written keys the plan does not own (`uncertain`, reserved for slice 4, and `normal_confirms`) are re-read under the lock and kept, so a confirm recorded between plan and write survives.
15. **Baseline:** the suite on this branch has one failure that predates this work: `tests/test_provider_key_routing.py::test_every_provider_client_carries_its_key_explicitly[claude-sonnet-5-5-anthropic-key]`. It is not ours; leave it.

---

## Conventions for every task

- Work in `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/line-ids` on branch `spec/stable-line-ids`. No push, no merge.
- Test command (run from `backend/`):
  ```bash
  cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/line-ids/backend
  PYTHONPATH=src ../../hybrid-stack/backend/.venv/bin/python -m pytest <path> -q -p no:cacheprovider
  ```
  Below, `PYTEST <path>` means exactly that command.
- Never read `~/Code/rr-template-conversion-private`. Do not touch ports 5174/8000 or `.claude/worktrees/demo`. No `npm install`.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit
  ```
- Each task ends green: run the task's tests, then the regression set `PYTEST tests/test_template_ledger_apply.py tests/test_template_decisions.py tests/test_template_sheet_save.py tests/test_template_ledger_save.py tests/test_template_sheet_save_routes.py tests/test_template_ledger_routes.py tests/test_template_upgrade_apply.py tests/test_template_writer.py tests/test_template_sheet_lab_prompts.py tests/test_chat_router.py tests/test_chat_router_routes.py tests/test_template_refine.py tests/test_rules_step_lab.py tests/test_template_generate_endpoint.py` (about 5 s) before committing.

## File map

| File | Status | Responsibility |
| --- | --- | --- |
| `backend/src/rapid_reports_ai/template_line_match.py` | Create | `rep_key` / `same_text`: exact after lookalikes and whitespace (decision 7). Versioned `LOOKALIKES`. |
| `backend/src/rapid_reports_ai/template_line_registry.py` | Create | Units of a parse, identity keys, `rebind`, `match`, `uids_for`. |
| `backend/src/rapid_reports_ai/template_normal_confirms.py` | Create | Confirm groups, attestable units, `record`, `confirm_state`. |
| `backend/src/rapid_reports_ai/template_decisions.py` | Modify | `LINE_BOUND`, `UID`; `clean_ledger` keeps `uid`; `set_decision` keeps it. |
| `backend/src/rapid_reports_ai/template_ledger_apply.py` | Modify | `apply_ledger(registry=)`: uid-first re-key, `carried`, removal-satisfied; `locate`, `stamp_uids`, `uid_share`. |
| `backend/src/rapid_reports_ai/template_sheet_save.py` | Modify | `vet_sheet(registry=)`, `VetOutcome.carried`, `persist_sheet`. |
| `backend/src/rapid_reports_ai/main.py` | Modify | `_carry_structure` server-written keys; `_vet_config` via `persist_sheet`; confirm endpoint. |
| `backend/src/rapid_reports_ai/scripts/template_upgrade_apply.py` | Modify | `_plan_entry` uses `persist_sheet`. |
| `backend/src/rapid_reports_ai/template_sheet_structure.py` | Modify | `generation_stamp` gains `sheet_rev`. |
| `backend/tests/test_template_line_registry.py` | Create | Text identity, adversarial pairs, lookalike collisions, rebind, uids_for, match. |
| `backend/tests/test_template_normal_confirms.py` | Create | Groups, chunks, state. |
| `backend/tests/test_template_line_ids_routes.py` | Create | Persisting vs stateless paths, server-written keys, confirm endpoint. |
| `backend/tests/template_line_fixtures.py` | Create | Rebuild fixture (two writer outputs + planted truth). |
| `backend/tests/test_template_line_rebuild.py` | Create | Rebuild metric test. |
| Existing tests (listed per task) | Modify | New cases appended; the changed assertions in gap 8. |

---

### Task 1: Representation-only text identity (exact matching; revised by decision 7)

**Files:**
- Create: `backend/src/rapid_reports_ai/template_line_match.py`
- Create: `backend/tests/test_template_line_registry.py`

> **Revised 2026-10-15 (spec decision 7).** Built first as a tokeniser with clinical gates, a filler list and a UK/US spelling table (commit 202da478); replaced by exact matching after representation-only normalising (lookalikes, whitespace). The code below is the revised version. Every adversarial pair is kept as a tripwire; the former cosmetic matches now assert a new uid; typography-only pairs still match.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_template_line_registry.py`:

```python
"""The line registry (spec 2026-10-15-stable-line-ids-design): stable uids per line-bound sheet unit, re-bound by code.
Pure code: no model, no database. Pass condition for the adversarial pairs: zero wrong matches."""
import hashlib

import pytest

from rapid_reports_ai import template_line_match as tlm
from tests.template_sheet_fixtures import LEDGER_SHEET


# ── text identity: exact after representation-only normalising (decision 7) ─────────────────────────────────────

ADVERSARIAL = [
    ("No pleural effusion.", "No pericardial effusion."),
    ("Left kidney is normal.", "Right kidney is normal."),
    ("Mild narrowing.", "Moderate narrowing."),
    ("No evidence of fracture.", "Evidence of fracture."),
    ("Lesion with enhancement.", "Lesion without enhancement."),
    ("Calcium score > 0.", "Calcium score < 0."),
    ("Calcium score > 0.", "Calcium score ≥ 100."),
    ("Measures 1.5 mm.", "Measures 15 mm."),
    ("Dose 10 mGycm.", "Dose 10 mGy."),
    ("Left kidney, right adrenal.", "Right kidney, left adrenal."),
    ("Non-enhancing lesion.", "Enhancing lesion."),
    ("Small effusion.", "Large effusion."),
    ("Measures .5 mm.", "Measures 5 mm."),
    ("No fracture. Dislocation.", "No fracture, dislocation."),
    ("No mass; effusion.", "No mass effusion."),
    ("Stenosis <25%.", "Stenosis 25%."),
    ("Measures 5 x 3 mm.", "Measures 53 mm."),
    ("Effusion is seen.", "Effusion is not seen."),
    ("Likely pneumonia.", "Pneumonia."),
    ("Malignancy cannot be excluded.", "Malignancy excluded."),
    ("Possible collection.", "Probable collection."),
    ("Well-defined margin.", "Defined margin."),
    ("No collapse, there is consolidation.", "No collapse, consolidation."),
    ("No mass, fluid is seen.", "No mass, fluid."),
    ("Length 5'.", "Length 5."),
]


@pytest.mark.parametrize("a,b", ADVERSARIAL)
def test_adversarial_texts_are_never_the_same_line(a, b):
    """Near misses: once guarded by the cosmetic layer's gates, now non-matching by construction. They stay as a
    tripwire against fuzzy matching being re-added."""
    assert not tlm.same_text(a, b) and not tlm.same_text(b, a)


@pytest.mark.parametrize("a,b", [
    ("There is no pleural effusion.", "No pleural effusion"),         # filler words
    ("Oedema is seen.", "Edema"),                                      # spelling
    ("Oedema.", "Edema."),
    ("No focal liver lesion.", "no focal liver lesion."),              # case
    ("No focal liver lesion.", "No focal liver lesion"),               # a final full stop
    ("No mass. There is fluid.", "No mass. Fluid."),
    ("Possible mass; there is fluid.", "Possible mass; fluid."),
    ("Well-defined margin.", "Well defined margin."),                  # a hyphen is punctuation
])
def test_rewordings_case_punctuation_and_spelling_are_other_lines(a, b):
    assert not tlm.same_text(a, b) and not tlm.same_text(b, a)


@pytest.mark.parametrize("a,b", [
    ("No fracture \u2013 left side.", "No fracture - left side."),
    ("No fracture \u2014 left side.", "No fracture - left side."),
    ("Change of \u22121 mm.", "Change of -1 mm."),
    ("The patient\u2019s \u201cnormal\u201d study.", "The patient's \"normal\" study."),
    ("Measures 5 \u00d7 3 mm.", "Measures 5 x 3 mm."),
    ("No\u00a0effusion.", "No effusion."),
    ("No\u202feffusion.", "No effusion."),
    ("  No   effusion. ", "No effusion."),
])
def test_typography_only_differences_are_the_same_line(a, b):
    assert tlm.same_text(a, b) and tlm.rep_key(a) == tlm.rep_key(b)


@pytest.mark.parametrize("a,b", [
    ("Measures 5 X 3 mm.", "Measures 5 x 3 mm."),     # only the multiplication sign merges into "x", never case
    ("Length 5\u2032.", "Length 5'."),                # prime is not a lookalike
    ("Grade \u2264 2.", "Grade < 2."),                # comparators never merge
    ("Grade \u2265 2.", "Grade > 2."),
    ("Change of -1 mm.", "Change of 1 mm."),
    ("No\u200beffusion.", "No effusion."),            # a zero-width space is not a space
])
def test_lookalikes_never_collide_with_a_different_character(a, b):
    assert not tlm.same_text(a, b)


def test_lookalike_map_merges_only_into_ascii_forms():
    assert set(tlm.LOOKALIKES.values()) <= {"-", '"', "'", "x", " "}
    assert all(ord(k) > 127 for k in tlm.LOOKALIKES) and not set(tlm.LOOKALIKES) & set(tlm.LOOKALIKES.values())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_template_line_registry.py`
Expected: collection error `ModuleNotFoundError: No module named 'rapid_reports_ai.template_line_match'`.

- [ ] **Step 3: Write the module**

Create `backend/src/rapid_reports_ai/template_line_match.py`:

```python
"""Text identity of two sheet-line texts (spec 2026-10-15-stable-line-ids-design, "Wrong matches are worse than lost
answers"; Hassan's decision 7): two texts are the same line only when they are EXACTLY equal after normalising their
representation, nothing else:

1. lookalike characters unified (en/em dash, minus and other dashes -> "-", curly -> straight quotes and apostrophes,
   the multiplication sign -> "x", Unicode spaces -> space);
2. whitespace collapsed (runs become one space, ends trimmed).

Case, punctuation (a final full stop included), spelling and filler words all stay significant: "No effusion." and
"No effusion", "Oedema" and "Edema", "There is no mass." and "No mass." are different lines. No similarity, no
tokeniser, no clinical gates.

Versioned constant: changing LOOKALIKES changes which lines keep their uid, so bump MATCH_VERSION and keep the
constant tests green."""
from __future__ import annotations

MATCH_VERSION = 2

# Lookalike characters -> one form. The only merging step.
LOOKALIKES = {
    "–": "-", "—": "-", "−": "-", "‒": "-", "‐": "-", "‑": "-",
    "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "‚": "'",
    "×": "x",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", "　": " ",
}
_LOOKALIKE = str.maketrans(LOOKALIKES)


def rep_key(text: str) -> str:
    """The text with its representation normalised (lookalikes unified, whitespace collapsed); nothing else changed."""
    return " ".join((text or "").translate(_LOOKALIKE).split())


def same_text(a: str, b: str) -> bool:
    """True when the two texts are the same line: equal after rep_key."""
    return rep_key(a) == rep_key(b)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_line_registry.py`
Expected: `48 passed` (25 adversarial pairs, 8 rewording pairs, 8 typography pairs, 6 lookalike-collision pairs, parametrised, plus 1 constant test).

- [ ] **Step 5: Commit**

```bash
cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/line-ids
git add backend/src/rapid_reports_ai/template_line_match.py backend/tests/test_template_line_registry.py
git commit -m "feat(line-ids): representation-only text identity (lookalikes, whitespace)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 2: Registry module: units, identity keys, load

**Files:**
- Create: `backend/src/rapid_reports_ai/template_line_registry.py`
- Modify: `backend/tests/test_template_line_registry.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_template_line_registry.py`:

```python
# ── the registry module ────────────────────────────────────────────────────────────────────────────────────────

from rapid_reports_ai import template_line_registry as tlr
from rapid_reports_ai import template_sheet_grammar as tsg


def _st(sheet):
    res = tsg.parse_sheet(sheet)
    assert not res.errors and res.structure.usable, res.errors
    return res.structure


def test_units_lists_every_line_bound_unit_parents_first():
    us = tlr.units(_st(LEDGER_SHEET))
    assert [u.ref for u in us] == ["S:TECHNIQUE", "S:FINDINGS", "S:IMPRESSION", "p0", "p1", "p2", "m0", "n0", "f0", "f1"]
    neg = next(u for u in us if u.ref == "n0")
    assert (neg.kind, neg.raw, neg.text, neg.section, neg.paragraph) == (
        "negative", 'NEGATIVE "No focal liver lesion."', "No focal liver lesion.", "S:FINDINGS", "p1")
    assert tlr.text_hash("x") == "sha256:" + hashlib.sha256(b"x").hexdigest()


def test_load_drops_malformed_units_and_never_raises():
    assert tlr.load(None) == tlr.empty() and tlr.load("x") == tlr.empty()
    raw = {"v": 1, "units": {"n_aaaaaa": {"kind": "normal", "identity": {}}, "bad": {"kind": "normal", "identity": {}},
                             "g_bbbbbb": {"kind": "nope", "identity": {}}, "f_cccccc": "x"}, "salt": "0a1b2c3d"}
    assert list(tlr.load(raw)["units"]) == ["n_aaaaaa"] and tlr.load(raw)["salt"] == "0a1b2c3d"
    assert "salt" not in tlr.load({**raw, "salt": "not hex!"})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_template_line_registry.py`
Expected: collection error `ImportError: cannot import name 'template_line_registry'`.

- [ ] **Step 3: Write the module (first part)**

Create `backend/src/rapid_reports_ai/template_line_registry.py`:

```python
"""The line registry (spec 2026-10-15-stable-line-ids-design): a stable uid per line-bound sheet unit, kept beside the
sheet in template_config["line_registry"] and re-bound by code on every persisted save (template_sheet_save.
persist_sheet). Pure code, no model call. The sheet text is never changed.

A uid names a slot, not a string. Identity per kind (all must match):
    section    normalised name
    paragraph  section uid + normalised name; or (a rename) section uid + the same non-empty COVERS set
    normal     section uid + paragraph uid + structure (its text is tracked by text_hash, not identity); across a
               paragraph rename (the COVERS rule) its text must also be exactly equal (decision 5)
    negative   section uid + paragraph uid + condition + condition_source + kind + origin + text
    fixed      section uid + paragraph uid + text
    rule       section uid + paragraph uid + effect + condition + condition_source + target + anchor + position +
               then_text + else_text + items + question
Every text and name compares EXACTLY after representation-only normalising (template_line_match.rep_key: lookalike
characters unified, whitespace collapsed); case, punctuation, spelling and filler words stay significant (decision 7).
TERM, COVERS and IF_PRESENT lines get no uid.

rebind(registry, structure, carried) pairs the new parse's units with the previous registry's, kind by kind,
parents first: carried units (lines apply_ledger rewrote) keep their uid; then exact identity against live units (a
paragraph also by the COVERS rename rule, reported as exact); then exact identity against gone units (revival). Pairs are 1:1: a unit with two candidates, or a
candidate claimed twice, pairs with nothing (`ambiguous`, new uids). Deterministic, uid minting included.

uids_for(structure, registry) maps a parse's units to their uids by exact identity against live units (read time);
match(structure, registry) is the pairing rebind would make, without minting (apply_ledger's uid-first resolution)."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from . import template_line_match as tlm

logger = logging.getLogger(__name__)

REGISTRY_VERSION = 1
KINDS = ("section", "paragraph", "normal", "negative", "fixed", "rule")
LINE_KINDS = ("normal", "negative", "fixed", "rule")
PREFIX = {"section": "s_", "paragraph": "p_", "normal": "n_", "negative": "g_", "fixed": "f_", "rule": "r_"}

# Identity fields after the parents, and how each is compared: "plain" (as is), "text" (tlm.rep_key, exactly), "items"
# (a list of texts, each as "text", in order).
_FIELDS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "section": (("name", "text"),),
    "paragraph": (("name", "text"),),
    "normal": (("structure", "text"),),
    "negative": (("condition", "text"), ("condition_source", "plain"), ("kind", "plain"), ("origin", "plain"),
                 ("text", "text")),
    "fixed": (("text", "text"),),
    "rule": (("effect", "plain"), ("condition", "text"), ("condition_source", "plain"), ("target", "text"),
             ("anchor", "text"), ("position", "plain"), ("then_text", "text"), ("else_text", "text"),
             ("items", "items"), ("question", "text")),
}
_PARENTS = {"section": (), "paragraph": ("section",), "normal": ("section", "paragraph"),
            "negative": ("section", "paragraph"), "fixed": ("section", "paragraph"), "rule": ("section", "paragraph")}


@dataclass(frozen=True)
class Unit:
    """One line-bound unit of a parse. `ref` is the parse's own id ("S:<NAME>" for a section, else p0 / m0 / n0 / f0 /
    r0); `raw` the sheet line ("" for a section or paragraph); `section` / `paragraph` the parse's parent refs."""
    ref: str
    kind: str
    raw: str
    text: str
    fields: tuple        # ((name, value), ...) in _FIELDS order; lists as tuples
    section: str = ""    # parent section ref ("S:<NAME>"), "" for a section
    paragraph: str = ""  # parent paragraph ref, "" when none
    covers: tuple = ()   # a paragraph's COVERS


def _structure_label(s: str) -> str:
    s = (s or "").strip()
    return s[1:-1].strip() if len(s) > 2 and s.startswith('"') and s.endswith('"') else s


def units(st) -> List[Unit]:
    """Every line-bound unit of a parsed sheet, parents first, each kind in parse order."""
    out: List[Unit] = []
    for s in sorted(st.sections, key=lambda x: x.order):
        out.append(Unit(f"S:{s.name}", "section", "", s.name, (("name", s.name),)))
    for p in st.paragraphs:
        out.append(Unit(p.id, "paragraph", "", p.name, (("name", p.name),), section=f"S:{p.section}",
                        covers=tuple(p.covers)))
    for n in st.normals:
        out.append(Unit(n.id, "normal", str(n.source_line), n.text, (("structure", _structure_label(n.structure)),),
                        section=f"S:{n.section}", paragraph=n.paragraph))
    for n in st.negatives:
        out.append(Unit(n.id, "negative", str(n.source_lines[0]) if n.source_lines else "", n.text,
                        (("condition", n.condition or ""),
                         ("condition_source", n.condition_source if n.condition else ""),
                         ("kind", n.kind), ("origin", n.origin), ("text", n.text)),
                        section=f"S:{n.section}", paragraph=n.paragraph))
    for f in st.fixed_blocks:
        out.append(Unit(f.id, "fixed", f.source_line, f.text, (("text", f.text),), section=f"S:{f.section}",
                        paragraph=f.paragraph))
    for r in st.rules:
        raw = str(r.source_lines[0]) if r.source_lines else ""
        out.append(Unit(r.id, "rule", raw, raw.strip(),
                        (("effect", r.effect), ("condition", r.condition), ("condition_source", r.condition_source),
                         ("target", r.target), ("anchor", r.anchor), ("position", r.position or ""),
                         ("then_text", r.then_text), ("else_text", r.else_text), ("items", tuple(r.items)),
                         ("question", r.question)),
                        section=f"S:{r.section}", paragraph=r.paragraph))
    return out


def text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256((text or "").encode()).hexdigest()


def empty() -> dict:
    return {"v": REGISTRY_VERSION, "units": {}}


_SALT = re.compile(r"[0-9a-f]{8}")


def load(raw) -> dict:
    """A stored registry (a deep copy, its salt kept), or an empty one when absent or unreadable (never raises)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("units"), dict):
        return empty()
    good = {u: e for u, e in raw["units"].items()
            if isinstance(u, str) and isinstance(e, dict) and e.get("kind") in KINDS
            and isinstance(e.get("identity"), dict) and u.startswith(PREFIX[e["kind"]])}
    out = {"v": REGISTRY_VERSION, "units": copy.deepcopy(good)}
    if isinstance(raw.get("salt"), str) and _SALT.fullmatch(raw["salt"]):
        out["salt"] = raw["salt"]
    return out


def _identity(u: Unit, parents: Dict[str, str]) -> dict:
    """The identity stored for a unit: its parents' uids (from `parents`, unit ref -> uid) and its own fields."""
    ident = {p: parents.get(getattr(u, p), "") if getattr(u, p) else "" for p in _PARENTS[u.kind]}
    for name, value in u.fields:
        ident[name] = list(value) if isinstance(value, tuple) else value
    if u.kind == "paragraph":
        ident["covers"] = list(u.covers)
    return ident


def _exact(kind: str, ident: dict) -> tuple:
    key = [ident.get(p, "") for p in _PARENTS[kind]]
    for name, how in _FIELDS[kind]:
        v = ident.get(name)
        if how == "items":
            key.append(tuple(tlm.rep_key(x) for x in v or []))
        elif how == "text":
            key.append(tlm.rep_key(v or ""))
        else:
            key.append(v or "")
    return (kind, *key)


def _rename(kind: str, ident: dict) -> Optional[tuple]:
    """A paragraph's rename identity (decision 5): section uid + the same non-empty COVERS set, the name ignored.
    None for every other kind, and for a paragraph without COVERS."""
    if kind != "paragraph":
        return None
    covers = frozenset(tlm.rep_key(c) for c in ident.get("covers") or [])
    return (kind, ident.get("section", ""), covers) if covers else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_line_registry.py`
Expected: `50 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_line_registry.py backend/tests/test_template_line_registry.py
git commit -m "feat(line-ids): registry units, identity keys and safe load

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 3: `rebind` with adversarial, ambiguity, carried and revival tests

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_line_registry.py` (append)
- Modify: `backend/tests/test_template_line_registry.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_template_line_registry.py`:

```python
# ── rebind ─────────────────────────────────────────────────────────────────────────────────────────────────────

HEAD = """## Report Structure
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression
"""
TAIL = "\n## Paragraph: Impression (IMPRESSION)\nOpening: \"Normal study.\"\n"


def _sheet(*paragraphs: str) -> str:
    return HEAD + "".join(f"\n{p.strip()}\n" for p in paragraphs) + TAIL


def _bind(sheet, registry=None, carried=None):
    return tlr.rebind(registry, _st(sheet), carried, now="T")


def _live(registry, text):
    (uid,) = [u for u, e in registry["units"].items() if e["status"] == "live" and e["text"] == text]
    return uid


def _counts(report):
    return {k: len(v) for k, v in report.items() if v}


def test_first_save_mints_one_uid_per_line_bound_unit_and_a_second_is_all_exact():
    reg, rep = _bind(LEDGER_SHEET)
    st = _st(LEDGER_SHEET)
    n = len(st.sections) + len(st.paragraphs) + len(st.normals) + len(st.negatives) + len(st.fixed_blocks) + len(st.rules)
    assert _counts(rep) == {"new": n} and len(reg["units"]) == n
    assert {u[:2] for u in reg["units"]} == {"s_", "p_", "n_", "g_", "f_"}
    assert all(e["status"] == "live" and e["minted"] == "T" for e in reg["units"].values())
    again, rep2 = _bind(LEDGER_SHEET, reg)
    assert _counts(rep2) == {"exact": n} and again == reg


def test_rebind_is_deterministic_and_never_mutates_its_input():
    reg, _ = _bind(LEDGER_SHEET)
    snapshot = repr(reg)
    edited = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."', 'NEGATIVE "No focal hepatic lesion."')
    assert _bind(edited, reg) == _bind(edited, reg)
    assert repr(reg) == snapshot


def test_normal_text_lives_in_text_hash_not_identity():
    reg, _ = _bind(LEDGER_SHEET)
    uid = _live(reg, "The liver is normal in size.")
    edited = LEDGER_SHEET.replace('"The liver is normal in size."\nNEGATIVE', '"The liver is unremarkable."\nNEGATIVE')
    reg2, rep = _bind(edited, reg)
    assert uid in rep["exact"] and reg2["units"][uid]["text"] == "The liver is unremarkable."
    assert reg2["units"][uid]["text_hash"] != reg["units"][uid]["text_hash"]


def test_reordering_sections_and_paragraphs_keeps_every_uid():
    a = _sheet('## Paragraph: Liver (FINDINGS)\nCOVERS ["liver"]\nNORMAL [liver] "The liver is normal."',
               '## Paragraph: Spleen (FINDINGS)\nCOVERS ["spleen"]\nNORMAL [spleen] "The spleen is normal."')
    b = _sheet('## Paragraph: Spleen (FINDINGS)\nCOVERS ["spleen"]\nNORMAL [spleen] "The spleen is normal."',
               '## Paragraph: Liver (FINDINGS)\nCOVERS ["liver"]\nNORMAL [liver] "The liver is normal."')
    b = b.replace('SECTION TECHNIQUE | header: "Technique:" | role: technique\n', "") \
         .replace('SECTION IMPRESSION | header: "Impression:" | role: impression\n',
                  'SECTION IMPRESSION | header: "Impression:" | role: impression\n'
                  'SECTION TECHNIQUE | header: "Technique:" | role: technique\n')
    reg, _ = _bind(a)
    reg2, rep = _bind(b, reg)
    assert set(_counts(rep)) == {"exact"} and reg2 == reg


def test_inserting_a_normal_mints_one_uid_and_changes_no_other():
    reg, _ = _bind(LEDGER_SHEET)
    edited = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."',
                                  'NORMAL [gallbladder] "The gallbladder is normal."\nNEGATIVE "No focal liver lesion."')
    reg2, rep = _bind(edited, reg)
    assert len(rep["new"]) == 1 and rep["new"][0].startswith("n_") and not rep["gone"]
    assert {u: e for u, e in reg2["units"].items() if u not in rep["new"]} == reg["units"]


def test_a_rewording_is_a_new_unit_and_a_typography_change_keeps_the_uid():
    reg, _ = _bind(LEDGER_SHEET)
    uid = _live(reg, "No focal liver lesion.")
    reworded = LEDGER_SHEET.replace('"No focal liver lesion."', '"There is no focal liver lesion"')
    reg2, rep = _bind(reworded, reg)
    assert rep["gone"] == [uid] and len(rep["new"]) == 1 and reg2["units"][uid]["status"] == "gone"
    for variant in ('"No focal liver lesion"', '"no focal liver lesion."'):        # a full stop, case: other lines
        _, repv = _bind(LEDGER_SHEET.replace('"No focal liver lesion."', variant), reg)
        assert repv["gone"] == [uid]
    typo = LEDGER_SHEET.replace('"No focal liver lesion."', '"No focal\u00a0liver  lesion."')
    reg4, rep4 = _bind(typo, reg)
    assert uid in rep4["exact"] and not rep4["gone"] and reg4["units"][uid]["text"] == "No focal\u00a0liver  lesion."
    changed = LEDGER_SHEET.replace('"No focal liver lesion."', '"No focal hepatic lesion."')
    reg3, rep3 = _bind(changed, reg)
    assert rep3["gone"] == [uid] and len(rep3["new"]) == 1 and reg3["units"][uid]["status"] == "gone"


@pytest.mark.parametrize("a,b", ADVERSARIAL)
def test_adversarial_negatives_never_keep_a_uid(a, b):
    para = '## Paragraph: Body (FINDINGS)\nCOVERS ["body"]\nNEGATIVE "{}"'
    reg, _ = _bind(_sheet(para.format(a)))
    uid = _live(reg, a)
    _, rep = _bind(_sheet(para.format(b)), reg)
    assert rep["gone"] == [uid] and uid not in rep["exact"]


def test_the_same_normal_text_under_another_structure_is_another_unit():
    a = _sheet('## Paragraph: Body (FINDINGS)\nCOVERS ["alpha" | "beta"]\nNORMAL [alpha] "Normal appearance."')
    b = a.replace("NORMAL [alpha]", "NORMAL [beta]")
    reg, _ = _bind(a)
    _, rep = _bind(b, reg)
    assert len(rep["gone"]) == 1 and len(rep["new"]) == 1


def test_a_conditional_and_an_unconditional_negative_with_the_same_text_differ():
    a = _sheet('## Paragraph: Body (FINDINGS)\nCOVERS ["body"]\nNEGATIVE "No free fluid."')
    b = a.replace('NEGATIVE "No free fluid."', 'NEGATIVE "No free fluid." WHEN [findings: a body mass is reported]')
    reg, _ = _bind(a)
    _, rep = _bind(b, reg)
    assert len(rep["gone"]) == 1 and len(rep["new"]) == 1


def test_two_suppress_rules_with_one_condition_and_different_targets_differ():
    cond = "RULE WHEN [context: the dictation states contrast was given] SUPPRESS"
    a = _sheet('## Paragraph: Body (FINDINGS)\nCOVERS ["body"]\nFIXED "Line one."\nFIXED "Line two."\n'
               f'{cond} "Line one."')
    b = a.replace(f'{cond} "Line one."', f'{cond} "Line two."')
    reg, _ = _bind(a)
    _, rep = _bind(b, reg)
    assert [u[:2] for u in rep["gone"]] == ["r_"] and [u[:2] for u in rep["new"]] == ["r_"]


def test_identical_fixed_lines_in_two_paragraphs_are_two_units():
    a = _sheet('## Paragraph: Upper (FINDINGS)\nCOVERS ["upper"]\nFIXED "Same line."',
               '## Paragraph: Lower (FINDINGS)\nCOVERS ["lower"]\nNORMAL [lower] "Lower is normal."')
    b = _sheet('## Paragraph: Upper (FINDINGS)\nCOVERS ["upper"]\nNORMAL [upper] "Upper is normal."',
               '## Paragraph: Lower (FINDINGS)\nCOVERS ["lower"]\nNORMAL [lower] "Lower is normal."\nFIXED "Same line."')
    reg, _ = _bind(a)
    fixed = _live(reg, "Same line.")
    reg2, rep = _bind(b, reg)
    assert fixed in rep["gone"] and _live(reg2, "Same line.") != fixed


def test_identical_fixed_lines_in_two_paragraphs_each_keep_their_own_uid():
    sheet = _sheet('## Paragraph: Upper (FINDINGS)\nCOVERS ["upper"]\nFIXED "Same line."',
                   '## Paragraph: Lower (FINDINGS)\nCOVERS ["lower"]\nFIXED "Same line."')
    reg, rep = _bind(sheet)
    uids = [u for u, e in reg["units"].items() if e["text"] == "Same line."]
    assert len(set(uids)) == 2 and not rep["ambiguous"]
    reg2, rep2 = _bind(sheet, reg)
    assert set(uids) <= set(rep2["exact"]) and reg2 == reg


def test_each_registry_has_its_own_salt_and_keeps_it():
    a, _ = _bind(LEDGER_SHEET)
    b, _ = _bind(LEDGER_SHEET)
    assert a["salt"] != b["salt"] and set(a["units"]).isdisjoint(b["units"])
    assert _bind(LEDGER_SHEET, a)[0]["salt"] == a["salt"]


def test_a_paragraph_rename_keeps_uids_only_with_the_same_covers():
    a = _sheet('## Paragraph: Liver (FINDINGS)\nCOVERS ["liver" | "gallbladder"]\nNORMAL [liver] "The liver is normal."')
    reg, _ = _bind(a)
    para, normal = _live(reg, "Liver"), _live(reg, "The liver is normal.")
    renamed = a.replace("## Paragraph: Liver (FINDINGS)", "## Paragraph: Hepatobiliary (FINDINGS)")
    _, rep = _bind(renamed, reg)
    assert para in rep["exact"] and normal in rep["exact"]   # a COVERS rename reports as exact
    other_covers = renamed.replace('COVERS ["liver" | "gallbladder"]', 'COVERS ["liver"]')
    _, rep3 = _bind(other_covers, reg)
    assert para in rep3["gone"]
    no_covers = _sheet('## Paragraph: Protocol (TECHNIQUE)\nFIXED "Axial CT."')
    reg5, _ = _bind(no_covers)
    _, rep5 = _bind(no_covers.replace("Paragraph: Protocol", "Paragraph: Method"), reg5)
    assert _live(reg5, "Protocol") in rep5["gone"]                         # no COVERS: a rename is a new paragraph
    sided = _sheet('## Paragraph: Left kidney (FINDINGS)\nCOVERS ["left kidney"]\nNORMAL [left kidney] "Normal."')
    reg4, _ = _bind(sided)
    _, rep4 = _bind(sided.replace("Left kidney", "Right kidney").replace("left kidney", "right kidney"), reg4)
    assert _live(reg4, "Left kidney") in rep4["gone"]                     # the side lives in COVERS
    _, rep6 = _bind(a.replace("Paragraph: Liver", "Paragraph: liver"), reg)
    assert para in rep6["exact"]                                          # case only: the COVERS rule keeps it


def test_across_a_paragraph_rename_a_normal_keeps_its_uid_only_with_the_same_text():
    a = _sheet('## Paragraph: Arterial phase (FINDINGS)\nCOVERS ["liver" | "spleen"]\n'
               'NORMAL [liver] "The liver enhances normally."\nNORMAL [spleen] "The spleen is normal."')
    reg, _ = _bind(a)
    changed, same = _live(reg, "The liver enhances normally."), _live(reg, "The spleen is normal.")
    renamed = a.replace("Arterial phase", "Portal venous phase")
    _, rep = _bind(renamed.replace("The liver enhances normally.", "The liver enhances homogeneously."), reg)
    assert _live(reg, "Arterial phase") in rep["exact"]                    # the paragraph kept its uid (COVERS)
    assert changed in rep["gone"] and same in rep["exact"]                 # a reworded normal is a new unit
    _, rep2 = _bind(renamed.replace('"The liver enhances normally."', '"There is normal liver enhancement"'), reg)
    assert changed in rep2["gone"]
    _, rep3 = _bind(renamed, reg)
    assert changed in rep3["exact"]                                        # exact text: kept
    _, rep4 = _bind(renamed.replace('"The liver enhances normally."', '"The liver enhances normally"'), reg)
    assert changed in rep4["gone"]                                         # a full stop is significant
    _, rep5 = _bind(renamed.replace('"The liver enhances normally."', '"The liver enhances\u00a0normally."'), reg)
    assert changed in rep5["exact"]                                        # typography only: kept


def test_one_old_uid_claimed_by_two_new_lines_is_ambiguous():
    reg, _ = _bind(LEDGER_SHEET)
    uid = _live(reg, "No focal liver lesion.")
    twice = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."',
                                 'NEGATIVE "No focal liver lesion."\nNEGATIVE "No focal liver lesion."')
    _, rep = _bind(twice, reg)
    assert len(rep["ambiguous"]) == 2 and uid in rep["gone"] and uid not in rep["ambiguous"]


def test_two_old_uids_matching_one_new_line_are_ambiguous():
    twice = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."',
                                 'NEGATIVE "No focal liver lesion."\nNEGATIVE "No focal liver lesion."')
    reg, _ = _bind(twice)
    olds = sorted(u for u in reg["units"] if u.startswith("g_"))
    _, rep = _bind(LEDGER_SHEET, reg)
    assert len(rep["ambiguous"]) == 1 and sorted(rep["gone"]) == olds


def test_carried_units_keep_their_uid_whatever_the_new_text():
    reg, _ = _bind(LEDGER_SHEET)
    uid = _live(reg, "No focal liver lesion.")
    new_line = 'NEGATIVE "No focal hepatic lesion."'
    edited = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."', new_line)
    reg2, rep = _bind(edited, reg, carried={uid: new_line})
    assert rep["carried"] == [uid] and reg2["units"][uid]["text"] == "No focal hepatic lesion." and not rep["gone"]


def test_a_carried_uid_the_registry_does_not_know_is_ignored():
    reg, _ = _bind(LEDGER_SHEET)
    _, rep = _bind(LEDGER_SHEET, reg, carried={"g_zzzzzz": 'NEGATIVE "No focal liver lesion."'})
    assert not rep["carried"] and set(_counts(rep)) == {"exact"}


def test_gone_units_revive_on_exact_identity_only():
    reg, _ = _bind(LEDGER_SHEET)
    uid = _live(reg, "No focal liver lesion.")
    away = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."\n', "")
    reg2, _ = _bind(away, reg)
    assert reg2["units"][uid]["status"] == "gone"
    reworded = LEDGER_SHEET.replace('"No focal liver lesion."', '"There is no focal liver lesion"')
    _, rep = _bind(reworded, reg2)
    assert not rep["revived"] and len(rep["new"]) == 1
    reg4, rep4 = _bind(LEDGER_SHEET, reg2)
    assert rep4["revived"] == [uid] and reg4["units"][uid]["status"] == "live"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_template_line_registry.py`
Expected: FAIL with `AttributeError: module 'rapid_reports_ai.template_line_registry' has no attribute 'rebind'`.

- [ ] **Step 3: Append `rebind` to the module**

Append to `backend/src/rapid_reports_ai/template_line_registry.py`:

```python
def _mint(kind: str, ident: dict, taken: set, salt: str = "") -> str:
    """A new uid: kind prefix + 6 base32 characters of sha256(salt | kind | identity | n), deterministic given the
    registry's salt (spec gap 3)."""
    n = 0
    while True:
        digest = hashlib.sha256(f"{salt}|{kind}|{json.dumps(ident, sort_keys=True)}|{n}".encode()).digest()
        uid = PREFIX[kind] + base64.b32encode(digest).decode().lower()[:6]
        if uid not in taken:
            return uid
        n += 1


def _parents_match(u: Unit, assigned: Dict[str, str], prev_identity: dict) -> bool:
    """A carried line keeps its uid only in the same section and paragraph it had: never moved to an identical line
    elsewhere (spec gap 13)."""
    ident = _identity(u, assigned)
    return all(ident.get(p, "") == prev_identity.get(p, "") for p in _PARENTS[u.kind])


def _pair(new: List[Tuple[Unit, dict]], pool: Dict[str, dict], keyfn) -> Tuple[Dict[str, str], List[str], set]:
    """One tier: {unit ref: uid} for 1:1 pairs, the refs of new units with competing candidates (ambiguous), and the
    uids those competed for (they pair with nothing after this tier). keyfn(kind, identity, text)."""
    by_key: Dict[tuple, List[str]] = {}
    for uid, e in pool.items():
        k = keyfn(e["kind"], e["identity"], e.get("text", ""))
        if k is not None:
            by_key.setdefault(k, []).append(uid)
    cands = {}
    for u, ident in new:
        k = keyfn(u.kind, ident, u.text)
        if k is not None and by_key.get(k):
            cands[u.ref] = by_key[k]
    claims: Dict[str, int] = {}
    for c in cands.values():
        for uid in c:
            claims[uid] = claims.get(uid, 0) + 1
    paired, ambiguous, burnt = {}, [], set()
    for ref, c in cands.items():
        if len(c) == 1 and claims[c[0]] == 1:
            paired[ref] = c[0]
        else:
            ambiguous.append(ref)
            burnt.update(c)
    return paired, ambiguous, burnt


def rebind(registry, st, carried: Optional[Dict[str, str]] = None, *,
           now: Optional[str] = None) -> Tuple[dict, dict]:
    """(new registry, report) for the parse `st` against the previous registry (module doc). `carried`: {uid: the raw
    line apply_ledger rewrote that unit to}. report = {exact, carried, revived, new, gone, ambiguous}, each a
    list of uids (a paragraph kept by the COVERS rename rule counts as exact). Never mutates its inputs."""
    reg, report, _ = _bind(registry, st, carried, now)
    return reg, report


def _bind(registry, st, carried, now):
    reg = load(registry)
    reg.setdefault("salt", secrets.token_hex(4))   # minted once per registry; uids differ across templates
    prev = reg["units"]
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = {k: [] for k in ("exact", "carried", "revived", "new", "gone", "ambiguous")}
    assigned: Dict[str, str] = {}   # unit ref -> uid
    used: set = set()
    all_units = units(st)
    renamed: set = set()   # paragraph uids kept by the COVERS rename rule (spec decision 5)

    def exact_key(k: str, ident: dict, text: str) -> tuple:
        """Across a paragraph rename a normal also needs its own text (decision 5, option c)."""
        base = _exact(k, ident)
        return (*base, tlm.rep_key(text)) if k == "normal" and ident.get("paragraph") in renamed else base

    for kind in KINDS:
        todo = [u for u in all_units if u.kind == kind]
        live = {uid: e for uid, e in prev.items() if e["kind"] == kind and e.get("status") == "live"}
        gone = {uid: e for uid, e in prev.items() if e["kind"] == kind and e.get("status") != "live"}

        def take(u: Unit, uid: str, ident: dict, how: str) -> None:
            assigned[u.ref] = uid
            used.add(uid)
            prev[uid] = {**prev[uid], "kind": kind, "identity": ident, "text": u.text, "text_hash": text_hash(u.text),
                         "status": "live"}
            report[how].append(uid)

        if kind in LINE_KINDS:
            for uid, raw in sorted((carried or {}).items()):
                if uid not in live or uid in used or not uid.startswith(PREFIX[kind]):
                    continue
                hits = [u for u in todo if u.ref not in assigned and u.raw == raw
                        and _parents_match(u, assigned, prev[uid]["identity"])]
                if len(hits) == 1:
                    take(hits[0], uid, _identity(hits[0], assigned), "carried")
        excluded: set = set()
        tiers = (("exact", live, exact_key), ("exact", live, lambda k, i, t: _rename(k, i)),
                 ("revived", gone, exact_key))
        for tier, (how, pool, keyfn) in enumerate(tiers):
            rest = [(u, _identity(u, assigned)) for u in todo if u.ref not in assigned and u.ref not in excluded]
            avail = {uid: e for uid, e in pool.items() if uid not in used}
            paired, ambiguous, burnt = _pair(rest, avail, keyfn)
            for u, ident in rest:
                if u.ref in paired:
                    take(u, paired[u.ref], ident, how)
                    if tier == 1:
                        renamed.add(paired[u.ref])
            excluded.update(ambiguous)
            used.update(burnt)   # a uid two new units competed for pairs with nothing
        for u in todo:
            if u.ref in assigned:
                continue
            ident = _identity(u, assigned)
            uid = _mint(kind, ident, set(prev) | used, reg["salt"])
            prev[uid] = {"kind": kind, "identity": ident, "text": u.text, "text_hash": text_hash(u.text),
                         "status": "live", "minted": now}
            assigned[u.ref] = uid
            used.add(uid)
            report["ambiguous" if u.ref in excluded else "new"].append(uid)
        for uid in live:
            if uid not in assigned.values():
                prev[uid] = {**prev[uid], "status": "gone"}
                report["gone"].append(uid)
    return reg, report, assigned


def summary(report: dict) -> str:
    """The rebind report as one log fragment: "exact=9 carried=1 …"."""
    return " ".join(f"{k}={len(v)}" for k, v in report.items())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_line_registry.py`
Expected: `94 passed` (50 before + 44 new, 25 of them adversarial).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_line_registry.py backend/tests/test_template_line_registry.py
git commit -m "feat(line-ids): rebind — carried, exact (with the COVERS rename), revival tiers; 1:1 pairing

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 4: `uids_for` (read time) and `match` (uid-first resolution)

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_line_registry.py` (append)
- Modify: `backend/tests/test_template_line_registry.py` (append)

- [ ] **Step 1: Write the failing tests**

Append:

```python
# ── reading uids ───────────────────────────────────────────────────────────────────────────────────────────────

def test_uids_for_reads_exact_identity_against_live_units_only():
    assert tlr.uids_for(_st(LEDGER_SHEET), None) == {}
    reg, _ = _bind(LEDGER_SHEET)
    got = tlr.uids_for(_st(LEDGER_SHEET), reg)
    assert set(got) == {"S:TECHNIQUE", "S:FINDINGS", "S:IMPRESSION", "p0", "p1", "p2", "m0", "n0", "f0", "f1"}
    assert got["n0"] == _live(reg, "No focal liver lesion.")
    reworded = LEDGER_SHEET.replace('"No focal liver lesion."', '"There is no focal liver lesion"')
    assert "n0" not in tlr.uids_for(_st(reworded), reg)    # a rewording is another line


def test_match_pairs_renames_but_never_rewordings_without_minting():
    reg, _ = _bind(LEDGER_SHEET)
    snapshot = repr(reg)
    exact = tlr.uids_for(_st(LEDGER_SHEET), reg)
    renamed = LEDGER_SHEET.replace("## Paragraph: Liver (FINDINGS)", "## Paragraph: Hepatobiliary (FINDINGS)") \
                          .replace('"No focal liver lesion."', '"There is no focal liver lesion"')
    got = tlr.match(_st(renamed), reg)
    assert (got["p1"], got["m0"]) == (exact["p1"], exact["m0"]) and "n0" not in got
    assert "p1" not in tlr.uids_for(_st(renamed), reg) and repr(reg) == snapshot
    assert tlr.match(_st(LEDGER_SHEET), None) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_template_line_registry.py -k "uids_for or match"`
Expected: FAIL with `AttributeError: … has no attribute 'uids_for'`.

- [ ] **Step 3: Append the two readers**

```python
def uids_for(st, registry) -> Dict[str, str]:
    """{unit ref: uid} for the parse's units that match a live registry unit by exact identity, parents first, 1:1
    (a unit with two candidates gets none). Pure; never mints. Consumers call it at read time: uids are never stored
    on the cached sheet_structure."""
    reg = load(registry)
    out: Dict[str, str] = {}
    for kind in KINDS:
        live = {uid: e for uid, e in reg["units"].items() if e["kind"] == kind and e.get("status") == "live"}
        todo = [(u, _identity(u, out)) for u in units(st) if u.kind == kind]
        paired, _, _ = _pair(todo, live, lambda k, i, t: _exact(k, i))
        out.update(paired)
    return out


def match(st, registry) -> Dict[str, str]:
    """{unit ref: uid} for the units rebind would pair with a live unit of `registry` (exact identity, a paragraph
    rename included), without minting or storing anything: apply_ledger's uid-first resolution (spec gap 1).
    Gone units are never matched here (a gone uid falls back to key matching)."""
    _, report, assigned = _bind(registry, st, None, "")
    kept = set(report["exact"])
    return {ref: uid for ref, uid in assigned.items() if uid in kept}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_line_registry.py`
Expected: `96 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_line_registry.py backend/tests/test_template_line_registry.py
git commit -m "feat(line-ids): uids_for (exact, read time) and match (rebind pairing, no minting)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 5: Ledger entries carry `uid` (`clean_ledger`, `set_decision`, `rekey_decision`)

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_decisions.py:55` (constants), `:330-336` (`set_decision`), `:460-475` (`clean_ledger`)
- Modify: `backend/tests/test_template_decisions.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_template_decisions.py`:

```python
# ── stable line IDs: an entry may carry its line's uid (spec 2026-10-15-stable-line-ids-design) ─────────────────

def test_clean_ledger_keeps_a_well_formed_uid_on_line_bound_entries_only():
    led, _ = td.set_decision([], "normal", "Liver :: liver", {"text": "The liver is normal."}, source="creation", at="t")
    val, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation", at="t")
    out = td.clean_ledger([{**led[0], "uid": "n_abc234"}, {**val[0], "uid": "n_abc234"},
                           {**led[0], "key": "Kidney :: kidney", "uid": "<script>"}])
    assert out[0]["uid"] == "n_abc234" and "uid" not in out[1] and "uid" not in out[2]


def test_a_new_answer_on_the_same_line_keeps_the_uid_and_a_rekey_drops_it():
    led, _ = td.set_decision([], "fixed", "Line one.", {"keep": "always"}, source="creation", at="t")
    led = [{**led[0], "uid": "f_abc234"}]
    again, change = td.set_decision(led, "fixed", "Line one.", {"keep": "remove"}, source="chat")
    assert again[0]["uid"] == "f_abc234" and change is not None
    moved, _ = td.rekey_decision(led, "fixed", "Line one.", "Line two.", source="chat")
    assert moved[0]["key"] == "Line two." and "uid" not in moved[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_template_decisions.py -k uid`
Expected: FAIL: `KeyError: 'uid'` in the first test, and `assert 'uid' in …` failing in the second.

- [ ] **Step 3: Implement**

In `template_decisions.py`, after `_SEP = " :: "` add:

```python
LINE_BOUND = ("normal", "fixed", "habit")   # kinds whose entry names one sheet line (and may carry its uid)
UID = re.compile(r"[spngfr]_[a-z2-7]{6}")   # template_line_registry uid: kind prefix + 6 base32 characters
```

In the module docstring, after the line `One entry per (kind, key): {"kind", "key", "choice", "by", "at", "source"}.`, add:

```
A line-bound entry (normal, fixed, habit) may also carry "uid": the line registry's id of the line it names
(template_line_registry; stamped by template_sheet_save.persist_sheet after each persisted save).
```

In `set_decision`, replace:

```python
    entry: Entry = {"kind": kind, "key": old["key"] if old else key, "choice": choice, "by": by,
                    "at": at or _now(), "source": source}
    out = [entry if e is old else e for e in ledger] if old else [*(ledger or []), entry]
```

with:

```python
    entry: Entry = {"kind": kind, "key": old["key"] if old else key, "choice": choice, "by": by,
                    "at": at or _now(), "source": source}
    if old and old.get("uid"):   # the same line, a new answer: the slot keeps its uid
        entry["uid"] = old["uid"]
    out = [entry if e is old else e for e in ledger] if old else [*(ledger or []), entry]
```

(`rekey_decision` already builds a fresh entry without `uid`; that is the "clear" `reconcile_chat` needs. Add to its docstring: `The moved entry has no uid: the post-rebind stamp gives it the new line's.`)

In `clean_ledger`, replace:

```python
        out.append({"kind": e["kind"], "key": key, "choice": choice,
                    "by": e.get("by") if e.get("by") in BY else "code", "at": str(e.get("at") or ""),
                    "source": e.get("source") if e.get("source") in SOURCES else "default"})
    return out
```

with:

```python
        entry = {"kind": e["kind"], "key": key, "choice": choice,
                 "by": e.get("by") if e.get("by") in BY else "code", "at": str(e.get("at") or ""),
                 "source": e.get("source") if e.get("source") in SOURCES else "default"}
        if e["kind"] in LINE_BOUND and isinstance(e.get("uid"), str) and UID.fullmatch(e["uid"]):
            entry["uid"] = e["uid"]
        out.append(entry)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_decisions.py`
Expected: `37 passed`. Then run the regression set from Conventions. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_decisions.py backend/tests/test_template_decisions.py
git commit -m "feat(line-ids): ledger entries keep a well-formed uid; a re-key drops it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 6: `apply_ledger(registry=…)`: uid-first re-key and the `carried` map

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_ledger_apply.py` (`LedgerResult`, `_values`, `_concept`, `_normal`, `_habit`, `apply_ledger`, new helpers)
- Modify: `backend/tests/test_template_ledger_apply.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_template_ledger_apply.py`:

```python
# ── stable line IDs: uid first, key second (spec 2026-10-15-stable-line-ids-design, "Ledger changes") ───────────

from rapid_reports_ai import template_line_registry as tlr

NEG = td.negative_key("Liver", "No focal liver lesion.")
SUPPRESS = 'RULE WHEN [context: the dictation states contrast was given] SUPPRESS "No focal liver lesion."'


def _reg(sheet):
    return tlr.rebind(None, _clean(sheet), now="T")[0]


def _uid(sheet, reg, ref):
    return tlr.uids_for(_clean(sheet), reg)[ref]


def _with_uid(entry, uid):
    return {**entry, "uid": uid}


def test_registry_none_is_todays_key_matching():
    led = _led(("normal", td.normal_key("Liver", "liver"), {"text": "The liver is unremarkable."}))
    a, b = tla.apply_ledger(LEDGER_SHEET, led), tla.apply_ledger(LEDGER_SHEET, led, registry=None)
    assert (a.sheet, a.applied, a.unmatched) == (b.sheet, b.applied, b.unmatched)
    assert b.carried == {} and b.satisfied == [] and b.rekeyed == [] and b.ledger == led


def test_uid_first_finds_a_negative_across_a_paragraph_rename_and_rekeys_it():
    reg = _reg(LEDGER_SHEET)
    uid = _uid(LEDGER_SHEET, reg, "n0")
    led = [_with_uid(_led(("normal", NEG, {"text": "No focal liver lesion."}))[0], uid)]
    renamed = LEDGER_SHEET.replace("## Paragraph: Liver (FINDINGS)", "## Paragraph: Hepatobiliary (FINDINGS)")
    assert tla.apply_ledger(renamed, led).unmatched == led                 # today: paragraph not found, a card
    res = tla.apply_ledger(renamed, led, registry=reg)
    assert not res.unmatched and 'NEGATIVE "No focal liver lesion."' in res.sheet
    assert res.ledger[0]["key"] == 'Hepatobiliary :: "No focal liver lesion."' and res.ledger[0]["uid"] == uid
    assert res.rekeyed == [{"kind": "normal", "uid": uid, "old": NEG, "new": res.ledger[0]["key"]}]


def test_a_negative_the_writer_reworded_is_not_found_by_uid():
    reg = _reg(LEDGER_SHEET)
    uid = _uid(LEDGER_SHEET, reg, "n0")
    led = [_with_uid(_led(("normal", NEG, {"text": "No focal liver lesion."}))[0], uid)]
    rebuilt = LEDGER_SHEET.replace('"No focal liver lesion."', '"There is no focal liver lesion"')
    res = tla.apply_ledger(rebuilt, led, registry=reg)                    # exact matching only: lost, a card
    assert res.unmatched == led and not res.rekeyed and res.carried == {}


def test_across_a_paragraph_rename_a_normal_entry_follows_only_an_unchanged_line():
    reg = _reg(LEDGER_SHEET)
    uid = _uid(LEDGER_SHEET, reg, "m0")
    led = [_with_uid(_led(("normal", td.normal_key("Liver", "liver"), {"text": "The liver is unremarkable."}))[0], uid)]
    renamed = LEDGER_SHEET.replace("## Paragraph: Liver (FINDINGS)", "## Paragraph: Hepatobiliary (FINDINGS)")
    assert tla.apply_ledger(renamed, led).unmatched == led                 # today: paragraph not found
    res = tla.apply_ledger(renamed, led, registry=reg)                     # the line unchanged: its uid finds it
    assert 'NORMAL [liver] "The liver is unremarkable."' in res.sheet and not res.unmatched
    assert res.ledger[0]["key"] == "Hepatobiliary :: liver" and uid in res.carried
    reworded = renamed.replace('"The liver is normal in size."\nNEGATIVE', '"Normal liver size."\nNEGATIVE')
    res2 = tla.apply_ledger(reworded, led, registry=reg)                   # renamed and reworded: asked again
    assert res2.unmatched == led and res2.sheet == reworded


def test_a_uid_the_registry_does_not_know_is_no_uid():
    reg = _reg(LEDGER_SHEET)
    led = [_with_uid(_led(("normal", NEG, {"text": "No focal hepatic lesion."}))[0], "g_zzzzzz")]
    res = tla.apply_ledger(LEDGER_SHEET, led, registry=reg)
    assert 'NEGATIVE "No focal hepatic lesion."' in res.sheet and res.rekeyed == []


def test_carried_includes_the_context_rule_a_normal_rewrite_retargets():
    sheet = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."\n', f'NEGATIVE "No focal liver lesion."\n{SUPPRESS}\n')
    reg = _reg(sheet)
    neg, rule = _uid(sheet, reg, "n0"), _uid(sheet, reg, "r0")
    led = [_with_uid(_led(("normal", NEG, {"text": "No focal hepatic lesion."}))[0], neg)]
    res = tla.apply_ledger(sheet, led, registry=reg)
    assert res.carried == {neg: 'NEGATIVE "No focal hepatic lesion."',
                           rule: SUPPRESS.replace("liver lesion", "hepatic lesion")}
    _, rep = tlr.rebind(reg, _clean(res.sheet), res.carried, now="T")
    assert sorted(rep["carried"]) == sorted([neg, rule]) and rep["gone"] == [] and rep["new"] == []


def test_a_line_edited_by_two_steps_carries_its_final_text(monkeypatch):
    reg = _reg(LEDGER_SHEET)
    uid = _uid(LEDGER_SHEET, reg, "n0")
    first, second = 'NEGATIVE "No focal hepatic lesion."', 'NEGATIVE "No hepatic lesion."'

    def step(old, new):
        def op(lines, st, entry):
            out = [new if ln == old else ln for ln in lines]
            return out, [{"kind": entry["kind"], "key": entry["key"], "action": "rewritten"}], [], [], [(old, new)]
        return op
    monkeypatch.setattr(tla, "_OPS", [("fixed", step('NEGATIVE "No focal liver lesion."', first)),
                                      ("normal", step(first, second))])
    led = _led(("fixed", "Axial images were acquired.", {"keep": "always"}),
               ("normal", td.normal_key("Liver", "liver"), {"text": "The liver is normal in size."}))
    res = tla.apply_ledger(LEDGER_SHEET, led, registry=reg)
    assert res.carried == {uid: second}


def test_a_carried_line_deleted_later_never_moves_its_uid_to_an_identical_line_elsewhere(monkeypatch):
    other, mine = 'NEGATIVE "No hepatic lesion."', 'NEGATIVE "No focal liver lesion."'
    sheet = HABIT_SHEET.replace('NORMAL [delta] "Delta is normal."', f'NORMAL [delta] "Delta is normal."\n{other}')
    reg = _reg(sheet)
    liver, lower = _uid(sheet, reg, "n0"), _uid(sheet, reg, "n1")

    def rewrite(lines, st, entry):      # step 1: the Liver negative takes the Lower negative's exact text
        out = list(lines)
        out[out.index(mine)] = other
        return out, [{"kind": entry["kind"], "key": entry["key"], "action": "rewritten"}], [], [], [(mine, other)]

    def delete(lines, st, entry):       # step 2: the first copy (the Liver one) is removed
        i = lines.index(other)
        return lines[:i] + lines[i + 1:], [{"kind": entry["kind"], "key": entry["key"], "action": "removed"}], [], []
    monkeypatch.setattr(tla, "_OPS", [("fixed", rewrite), ("normal", delete)])
    led = _led(("fixed", "Axial images were acquired.", {"keep": "always"}),
               ("normal", td.normal_key("Liver", "liver"), {"text": "The liver is normal in size."}))
    res = tla.apply_ledger(sheet, led, registry=reg)
    assert res.carried == {liver: other}
    st = _clean(res.sheet)
    assert tla._uid_map(st, reg, res.carried)["n0"] == lower        # the Lower line keeps its own uid
    _, rep = tlr.rebind(reg, st, res.carried, now="T")
    assert liver in rep["gone"] and lower in rep["exact"] and not rep["carried"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_template_ledger_apply.py -k "registry or uid or carried or rename or two_steps"`
Expected: FAIL with `TypeError: apply_ledger() got an unexpected keyword argument 'registry'`.

- [ ] **Step 3: Implement**

3a. Imports: change `from typing import Callable, List, Optional, Set, Tuple` to `from typing import Callable, Dict, List, Optional, Set, Tuple`, and after `from . import template_decisions as td` add `from . import template_line_registry as tlr` (no cycle: the registry imports neither module).

3b. `LedgerResult`: after the `pending` field add:

```python
    # with a registry only (stable line IDs spec): the ledger as resolved (entries re-keyed to their uid's line), the
    # uid -> final raw line of every line this run rewrote (rebind keeps those uids), removal entries whose line is
    # absent (satisfied, never a card) and the re-keys made
    ledger: List[dict] = field(default_factory=list)
    carried: Dict[str, str] = field(default_factory=dict)
    satisfied: List[dict] = field(default_factory=list)
    rekeyed: List[dict] = field(default_factory=list)
```

Update the operations comment line to: `# ── operations: (lines, structure, arg) -> (lines, applied rows, unmatched entries, old texts[, rewrites]) ──` and add below it: `# rewrites: (old raw line, new raw line) for each line the op rewrote in place (the carried map's source).`

3c. `_values`: replace

```python
        if not ordered:
            out[idx[0]] = None
            action = "removed"
        else:
            new = _prefix(lines[idx[0]]) + tsg.render_rule(first.model_copy(update={"items": ordered})) \
                + _suffix(lines[idx[0]])
            action = "kept" if new == lines[idx[0]] and len(idx) == 1 else "rewritten"
            out[idx[0]] = new
        return [x for x in out if x is not None], [{"kind": "value", "key": "*", "action": action}], [], []
```

with

```python
        rewrites: List[Tuple[str, str]] = []
        if not ordered:
            out[idx[0]] = None
            action = "removed"
        else:
            new = _prefix(lines[idx[0]]) + tsg.render_rule(first.model_copy(update={"items": ordered})) \
                + _suffix(lines[idx[0]])
            action = "kept" if new == lines[idx[0]] and len(idx) == 1 else "rewritten"
            out[idx[0]] = new
            if new != lines[idx[0]]:
                rewrites.append((lines[idx[0]], new))
        return [x for x in out if x is not None], [{"kind": "value", "key": "*", "action": action}], [], [], rewrites
```

3d. Before `def _concept(` add:

```python
def _keyword(line: str) -> str:
    body = line[len(_prefix(line)):]
    return body.split(" ", 1)[0]


def _paired_rewrites(old: List[str], new: List[str]) -> List[Tuple[str, str]]:
    """(old line, new line) for a block rewritten line for line: same count and the same keyword in each place;
    anything else is a removal plus an insert (no uid carried)."""
    if len(old) != len(new) or any(_keyword(o) != _keyword(n) for o, n in zip(old, new)):
        return []
    return [(o, n) for o, n in zip(old, new) if o != n]
```

and in `_concept` replace the tail

```python
    out = [ln for i, ln in enumerate(lines) if i not in drop]
    if new:
        prefix = _prefix(old[0]) if old else ""
        out[at:at] = [prefix + ln for ln in new]
    action = "removed" if not new else ("rewritten" if drop else "inserted")
    keep = {norm_key(choice.get("default", "")), norm_key(choice.get("when_met", ""))}
    return out, [{**row, "action": action}], unmatched, [t for t in olds if norm_key(t) not in keep]
```

with

```python
    out = [ln for i, ln in enumerate(lines) if i not in drop]
    placed: List[str] = []
    if new:
        prefix = _prefix(old[0]) if old else ""
        placed = [prefix + ln for ln in new]
        out[at:at] = placed
    action = "removed" if not new else ("rewritten" if drop else "inserted")
    keep = {norm_key(choice.get("default", "")), norm_key(choice.get("when_met", ""))}
    return (out, [{**row, "action": action}], unmatched, [t for t in olds if norm_key(t) not in keep],
            _paired_rewrites(old, placed))
```

3e. `_normal`: replace

```python
    rules = _targeting(st, old_keys)
    if text:
        first = lines[idx[0]]
        body = f'NEGATIVE "{text}"' if neg else f'NORMAL [{units[0].structure}] "{text}"'
        out2[idx[0]] = _prefix(first) + body + _suffix(first)
        for r in rules:   # a context rule on the old wording follows it
            i = _index(lines, r.source_lines[0])
            if i is not None:
                out2[i] = _prefix(lines[i]) + tsg.render_rule(r.model_copy(update={"target": text})) + _suffix(lines[i])
        action = "rewritten"
```

with

```python
    rules = _targeting(st, old_keys)
    rewrites: List[Tuple[str, str]] = []
    if text:
        first = lines[idx[0]]
        body = f'NEGATIVE "{text}"' if neg else f'NORMAL [{units[0].structure}] "{text}"'
        out2[idx[0]] = _prefix(first) + body + _suffix(first)
        rewrites.append((first, out2[idx[0]]))
        for r in rules:   # a context rule on the old wording follows it
            i = _index(lines, r.source_lines[0])
            if i is not None:
                out2[i] = _prefix(lines[i]) + tsg.render_rule(r.model_copy(update={"target": text})) + _suffix(lines[i])
                rewrites.append((lines[i], out2[i]))
        action = "rewritten"
```

and its last line `return [x for x in out2 if x is not None], [{**row, "action": action}], [], stale` with `return [x for x in out2 if x is not None], [{**row, "action": action}], [], stale, rewrites`.

3f. `_habit`: replace its last two lines

```python
    out2[idx[0]] = None if new is None else _prefix(first) + new
    return [x for x in out2 if x is not None], [{**row, "action": "removed" if new is None else "rewritten"}], [], []
```

with

```python
    out2[idx[0]] = None if new is None else _prefix(first) + new
    rewrites = [] if new is None else [(first, out2[idx[0]])]
    return ([x for x in out2 if x is not None], [{**row, "action": "removed" if new is None else "rewritten"}], [], [],
            rewrites)
```

3g. `apply_ledger`: replace the signature, docstring and first lines

```python
def apply_ledger(sheet: str, ledger: List[dict], before: str = "") -> LedgerResult:
    """The sheet with every ledger entry applied (module doc). A non-grammar sheet or an empty ledger is unchanged.
    `before`: the sheet this one replaces, when known; it tells a reworded concept default's added line apart."""
    res = LedgerResult(sheet=sheet)
```

with

```python
def apply_ledger(sheet: str, ledger: List[dict], before: str = "", registry: Optional[dict] = None) -> LedgerResult:
    """The sheet with every ledger entry applied (module doc). A non-grammar sheet or an empty ledger is unchanged.
    `before`: the sheet this one replaces, when known; it tells a reworded concept default's added line apart.
    `registry` (template_config["line_registry"], persisted saves only; None: exactly today's key and text matching):
    an entry whose uid names a live unit is re-keyed to that unit's current line before its edit (uid first, key
    second); every line rewritten is returned in `carried` ({uid: final raw line}); a removal whose line is absent is
    `satisfied`, never unmatched."""
    res = LedgerResult(sheet=sheet, ledger=list(ledger or []))
```

and replace the loop head

```python
    for op, arg, entries in steps:
        before_errors = _err_keys(res.sheet)
        try:
            lines, applied, unmatched, olds = op(res.sheet.split("\n"), _parse(res.sheet), arg)
            new = "\n".join(lines)
```

with (the uid map is built outside the step's `try`, so a failure there only drops the entry to key matching; plan review L1)

```python
    for op, arg, entries in steps:
        before_errors = _err_keys(res.sheet)
        st = _parse(res.sheet)
        uid_map: Dict[str, str] = {}
        mapped = False
        if registry is not None:
            try:
                uid_map, mapped = _uid_map(st, registry, res.carried), True
            except Exception as e:  # never blocks the edit: the entry falls back to key matching
                logger.error("[ledger] uid map failed: %s: %s", type(e).__name__, str(e)[:200])
        try:
            if uid_map and isinstance(arg, dict) and arg.get("uid"):
                arg = _by_uid(arg, st, uid_map, res)
            out = op(res.sheet.split("\n"), st, arg)
            lines, applied, unmatched, olds = out[:4]
            rewrites = out[4] if len(out) > 4 else []
            new = "\n".join(lines)
```

and replace

```python
        res.sheet = new
        res.applied += applied
```

with

```python
        res.sheet = new
        if registry is not None:
            _carry(rewrites, st, uid_map, res.carried)
        res.applied += applied
```

3h. Add the helpers before `RESTATED = "prose quotes a decided standard line"`:

```python
# ── stable line IDs (spec 2026-10-15-stable-line-ids-design) ─────────────────────────────────────────────────────

def _uid_map(st: tss.SheetStructure, registry: Optional[dict], carried: Dict[str, str]) -> Dict[str, str]:
    """{parse ref: uid} for the current parse: the units rebind would pair with a live registry unit (exact
    identity, a paragraph rename included; tlr.match, spec gap 1), then every line this run already rewrote (carried) at its new text, in
    the same section and paragraph only (spec gap 13)."""
    out = tlr.match(st, registry)
    if carried:
        units = tlr.units(st)
        known = tlr.load(registry)["units"]
        for uid, raw in carried.items():
            prev = (known.get(uid) or {}).get("identity") or {}
            hits = [u.ref for u in units if u.raw == raw and uid.startswith(tlr.PREFIX[u.kind])
                    and (out.get(u.section, ""), out.get(u.paragraph, "") if u.paragraph else "")
                    == (prev.get("section", ""), prev.get("paragraph", ""))]
            if len(hits) == 1:
                out = {r: x for r, x in out.items() if x != uid}
                out[hits[0]] = uid
    return out


def _carry(rewrites: List[Tuple[str, str]], st: tss.SheetStructure, uid_map: Dict[str, str],
           carried: Dict[str, str]) -> None:
    """Record each rewritten line's final text under its uid (a second edit of the same line overwrites the first)."""
    units = tlr.units(st)
    for old, new in rewrites:
        hits = [u.ref for u in units if u.raw == old]
        if len(hits) == 1 and hits[0] in uid_map:
            carried[uid_map[hits[0]]] = new
        elif len(hits) > 1:
            logger.info("[ledger] rewrite of a line the sheet holds %d times: no uid carried", len(hits))


def _key_for(entry: dict, st: tss.SheetStructure, ref: str) -> Optional[str]:
    """The key `entry` has when it names the unit `ref` of this parse; None when that unit cannot be the entry's
    (another kind, outside a paragraph, a case unit)."""
    names = {p.id: p.name for p in st.paragraphs}
    kind = entry.get("kind")
    if kind == "normal":
        _, label, neg = td.split_normal_key(entry["key"])
        if not neg:
            u = next((n for n in st.normals if n.id == ref), None)
            return td.normal_key(names[u.paragraph], u.structure) if u and u.paragraph in names else None
        u = next((n for n in st.negatives if n.id == ref), None)
        if u is None or u.paragraph not in names or u.condition or u.origin != "template":
            return None
        mine = {norm_key(label), norm_key((entry.get("choice") or {}).get("text", ""))}
        return td.negative_key(names[u.paragraph], label if norm_key(u.text) in mine else u.text)
    if kind == "fixed":
        u = next((f for f in st.fixed_blocks if f.id == ref), None)
        return u.text if u else None
    if kind == "habit":
        u = next((r for r in st.rules if r.id == ref and r.effect == "ask"), None) or next(
            (n for n in st.negatives if n.id == ref and n.condition and n.condition_source == "findings"), None)
        return td.habit_key(names[u.paragraph], u.condition) if u and u.paragraph in names else None
    return None


def _by_uid(entry: dict, st: tss.SheetStructure, uid_map: Dict[str, str], res: LedgerResult) -> dict:
    """Uid first (spec "Ledger changes" 1): when the entry's uid names a live unit whose key label differs from the
    entry's, the entry is re-keyed to that unit (logged) so the existing edit path finds it. An unknown or gone uid,
    or a new key another entry already holds, leaves the entry to today's key matching."""
    ref = next((r for r, u in uid_map.items() if u == entry["uid"]), None)
    try:
        new_key = _key_for(entry, st, ref) if ref else None
        if new_key is None or td.match_key(entry["kind"], new_key) == td.match_key(entry["kind"], entry["key"]):
            return entry
        if td.find([x for x in res.ledger if x is not entry], entry["kind"], new_key) is not None:
            logger.info("[ledger] uid %s: key %r already decided, kept on key matching", entry["uid"], new_key)
            return entry
    except td.DecisionError:
        return entry
    moved = {**entry, "key": new_key}
    res.ledger = [moved if x is entry else x for x in res.ledger]
    res.rekeyed.append({"kind": entry["kind"], "uid": entry["uid"], "old": entry["key"], "new": new_key})
    logger.info("[ledger] uid %s re-keyed %s %r -> %r", entry["uid"], entry["kind"], entry["key"], new_key)
    return moved
```

Also add to the module docstring's last paragraph: `With a registry (persisted saves only, template_sheet_save.persist_sheet) an entry resolves uid first: its uid's unit in the current parse re-keys it before the edit, and every rewritten line is reported in `carried` so the rebind keeps its uid.`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_ledger_apply.py`
Expected: all pass (49 existing + 7 new = 56). Then run the regression set. Expected: all pass. The existing `test_an_edit_that_would_break_the_sheet_is_not_applied` patches `_OPS` with an op that returns 4 values, so this also checks that the loop still accepts 4-value ops.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_ledger_apply.py backend/tests/test_template_ledger_apply.py
git commit -m "feat(line-ids): apply_ledger resolves uid first and returns the carried map

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 7: A removal whose line is shown absent is satisfied (registry path)

Plan review H1: satisfied only with evidence the line is gone, meaning the entry's uid is known to the registry and no unit of the current parse holds it. Every other unmatched removal (no uid, a paragraph not found or ambiguous, a reworded negative) stays a card, as today. (A removal whose paragraph resolves and holds no matching line is already `kept` today; that path is unchanged.)

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_ledger_apply.py`
- Modify: `backend/tests/test_template_ledger_apply.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
def test_a_removal_is_satisfied_only_when_its_line_is_shown_absent():
    reg = _reg(LEDGER_SHEET)
    uid = _uid(LEDGER_SHEET, reg, "n0")
    removal = _led(("normal", NEG, {"text": ""}))[0]
    reworded = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."', 'NEGATIVE "No focal hepatic lesion."')
    # no uid: nothing shows the line is gone (a reworded negative) -> a card, as today
    assert [e["key"] for e in tla.apply_ledger(reworded, [removal], registry=reg).unmatched] == [NEG]
    # its uid names no unit of this sheet: the line is gone -> satisfied, never a card
    res = tla.apply_ledger(reworded, [_with_uid(removal, uid)], registry=reg)
    assert res.sheet == reworded and res.unmatched == [] and [e["key"] for e in res.satisfied] == [NEG]
    # paragraph renamed with the negative still there, no uid: a card (never silently satisfied)
    renamed = LEDGER_SHEET.replace("## Paragraph: Liver (FINDINGS)", "## Paragraph: Abdomen (FINDINGS)")
    assert [e["key"] for e in tla.apply_ledger(renamed, [removal], registry=_reg(renamed)).unmatched] == [NEG]
    # the same rename with the uid: the line is found through it and removed
    out = tla.apply_ledger(renamed, [_with_uid(removal, uid)], registry=reg)
    assert 'NEGATIVE "No focal liver lesion."' not in out.sheet and out.unmatched == []


def test_is_removal():
    assert tla.is_removal({"kind": "fixed", "choice": {"keep": "remove"}})
    assert tla.is_removal({"kind": "normal", "choice": {"text": ""}})
    assert not tla.is_removal({"kind": "normal", "choice": {"text": "x"}})
    assert not tla.is_removal({"kind": "habit", "choice": {"mode": "removed"}})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_template_ledger_apply.py -k "shown_absent or is_removal"`
Expected: FAIL: `AttributeError: … has no attribute 'is_removal'`, and the uid-carrying removal is still in `res.unmatched`.

- [ ] **Step 3: Implement**

In `apply_ledger`, extend the block added in Task 6:

```python
        res.sheet = new
        if registry is not None:
            _carry(rewrites, st, uid_map, res.carried)
            # a removal is satisfied only when its line is shown absent: its uid is in the registry and no unit of this
            # parse holds it; without that evidence (no uid, paragraph not found or ambiguous, a reworded negative) it
            # stays a card, as today (plan review H1)
            known = set(tlr.load(registry)["units"]) if mapped else set()
            done = [x for x in unmatched if is_removal(x) and x.get("uid") in known and x["uid"] not in uid_map.values()]
            unmatched = [x for x in unmatched if x not in done]
            res.satisfied += done
            applied = applied + [{"kind": x["kind"], "key": x["key"], "action": "kept"} for x in done]
        res.applied += applied
```

(`mapped` is False when the uid map failed; then nothing is treated as gone.) Add before the `# ── stable line IDs` header:

```python
def is_removal(entry: dict) -> bool:
    """A decision that removes its line: a fixed line kept "remove", a normal or negative with no wording."""
    choice = (entry or {}).get("choice") or {}
    return ((entry.get("kind") == "fixed" and choice.get("keep") == "remove")
            or (entry.get("kind") == "normal" and choice.get("text") == ""))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_ledger_apply.py`
Expected: all pass, including the unchanged `test_removing_a_negative_the_sheet_reworded_is_unmatched_not_kept` (registry None; spec gap 2).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_ledger_apply.py backend/tests/test_template_ledger_apply.py
git commit -m "feat(line-ids): a removal whose line is shown absent (uid gone) is satisfied, never a card

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 8: `locate`, `stamp_uids`, `uid_share`; `reconcile_chat` clears and the stamp restores

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_ledger_apply.py`
- Modify: `backend/tests/test_template_ledger_apply.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
def test_locate_names_one_unit_or_none():
    st = _clean(LEDGER_SHEET)
    assert tla.locate({"kind": "normal", "key": "Liver :: liver", "choice": {"text": "x"}}, st) == "m0"
    assert tla.locate({"kind": "normal", "key": NEG, "choice": {"text": ""}}, st) == "n0"
    assert tla.locate({"kind": "fixed", "key": "No previous imaging available", "choice": {"keep": "always"}}, st) == "f1"
    assert tla.locate({"kind": "normal", "key": "Spleen :: spleen", "choice": {"text": "x"}}, st) is None
    assert tla.locate({"kind": "value", "key": "LVEF", "choice": {"need": "every"}}, st) is None


def test_stamp_uids_sets_known_uids_drops_unknown_ones_and_keeps_an_orphans():
    reg = _reg(LEDGER_SHEET)
    st = _clean(LEDGER_SHEET)
    led = _led(("normal", td.normal_key("Liver", "liver"), {"text": "The liver is normal in size."}),
               ("fixed", "A line the sheet lacks.", {"keep": "always"}), ("value", "LVEF", {"need": "every"}))
    led = [led[0], _with_uid(led[1], "f_zzzzzz"), led[2]]
    out = tla.stamp_uids(led, st, reg)
    assert out[0]["uid"] == tlr.uids_for(st, reg)["m0"] and "uid" not in out[1] and "uid" not in out[2]
    orphan = _with_uid(led[1], tlr.uids_for(st, reg)["f0"])
    assert tla.stamp_uids([orphan], st, reg) == [orphan]
    assert led[1]["uid"] == "f_zzzzzz"                                   # never mutated


def test_reconcile_chat_clears_the_uid_of_a_rekeyed_entry_and_the_stamp_restores_the_right_one():
    reg = _reg(LEDGER_SHEET)
    old_uid = _uid(LEDGER_SHEET, reg, "f0")
    led = [_with_uid(_led(("fixed", "Axial images were acquired.", {"keep": "always"}))[0], old_uid)]
    after = LEDGER_SHEET.replace('FIXED "Axial images were acquired."', 'FIXED "Axial images acquired."')
    out, changes, _ = tla.reconcile_chat(LEDGER_SHEET, after, led)
    assert out[0]["key"] == "Axial images acquired." and "uid" not in out[0] and changes
    res = tla.apply_ledger(after, out, registry=reg)
    reg2, _ = tlr.rebind(reg, _clean(res.sheet), res.carried, now="T")
    stamped = tla.stamp_uids(res.ledger, _clean(res.sheet), reg2)
    assert stamped[0]["uid"] == tlr.uids_for(_clean(res.sheet), reg2)["f0"] != old_uid


def test_uid_share_counts_line_bound_entries_by_uid_and_by_text():
    reg = _reg(LEDGER_SHEET)
    uid = _uid(LEDGER_SHEET, reg, "n0")
    led = [_with_uid(_led(("normal", NEG, {"text": "No focal liver lesion."}))[0], uid),
           *_led(("value", "LVEF", {"need": "every"}))]
    renamed = LEDGER_SHEET.replace("## Paragraph: Liver (FINDINGS)", "## Paragraph: Hepatobiliary (FINDINGS)")
    assert tla.uid_share(led, renamed, reg) == {"line_bound": 1, "by_uid": 1, "by_text": 0}
    reworded = LEDGER_SHEET.replace('"No focal liver lesion."', '"There is no focal liver lesion"')
    assert tla.uid_share(led, reworded, reg) == {"line_bound": 1, "by_uid": 0, "by_text": 0}   # exact matching only
    assert tla.uid_share(led, "# free", reg) == {"line_bound": 0, "by_uid": 0, "by_text": 0}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_template_ledger_apply.py -k "locate or stamp or reconcile_chat_clears or uid_share"`
Expected: FAIL with `AttributeError: … has no attribute 'locate'`.

- [ ] **Step 3: Implement**

Append after `_by_uid` (before `RESTATED`):

```python
def locate(entry: dict, st: tss.SheetStructure) -> Optional[str]:
    """The parse ref of the one unit a line-bound entry names by today's exact key and text matching; None when there
    is none or more than one (never guessed)."""
    kind = entry.get("kind")
    try:
        if kind == "normal":
            para_name, label, neg = td.split_normal_key(entry["key"])
            para = _paragraph(st, para_name)
            if para is None:
                return None
            if neg:
                text = (entry.get("choice") or {}).get("text") or ""
                keys = {norm_key(label)} | ({norm_key(text)} if text else set())
                hits = [n.id for n in st.negatives if n.paragraph == para.id and n.origin == "template"
                        and not n.condition and norm_key(n.text) in keys]
            else:
                hits = [n.id for n in st.normals if n.paragraph == para.id
                        and td._name(td.structure_label(n.structure)) == td._name(label)]
        elif kind == "fixed":
            hits = [f.id for f in st.fixed_blocks if norm_key(f.text) == norm_key(entry["key"])]
        elif kind == "habit":
            para_name, cond = td.split_habit_key(entry["key"])
            para = _habit_paragraph(st, para_name)
            if para is None:
                return None
            rules, negs = _habit_units(st, para.id, cond)
            hits = [r.id for r in rules] + [n.id for n in negs]
        else:
            return None
    except (td.DecisionError, KeyError, TypeError, AttributeError):
        return None
    return hits[0] if len(hits) == 1 else None


def stamp_uids(ledger: List[dict], st: tss.SheetStructure, registry: dict) -> List[dict]:
    """The ledger with each line-bound entry's uid set to the uid of the unit it names in the final parse (after the
    rebind). A uid the registry does not know is dropped (a client-held ledger cannot forge one); an entry whose line
    is not found keeps a known uid (visibly orphaned when that unit is gone). Never mutates `ledger`."""
    known = set((registry or {}).get("units") or {})
    uids = tlr.uids_for(st, registry)
    out: List[dict] = []
    for e in ledger or []:
        ref = locate(e, st)
        uid = uids.get(ref) if ref else None
        if uid:
            e = {**e, "uid": uid}
        elif e.get("uid") and e["uid"] not in known:
            e = {k: v for k, v in e.items() if k != "uid"}
        out.append(e)
    return out


def uid_share(ledger: List[dict], sheet: str, registry: Optional[dict]) -> dict:
    """The rebuild metric (logged, never a gate): of the ledger's line-bound entries, how many the incoming sheet
    resolves by uid (tlr.match) and how many by today's key and text matching (locate)."""
    if not tsg.is_grammar_sheet(sheet or ""):
        return {"line_bound": 0, "by_uid": 0, "by_text": 0}
    st = _parse(sheet)
    live = set(tlr.match(st, registry).values()) if registry else set()
    bound = [e for e in ledger or [] if e.get("kind") in td.LINE_BOUND]
    return {"line_bound": len(bound), "by_uid": sum(1 for e in bound if e.get("uid") in live),
            "by_text": sum(1 for e in bound if locate(e, st) is not None)}
```

Also add to `reconcile_chat`'s docstring: `An entry it re-keys (td.rekey_decision) comes back without its uid; persist_sheet's post-rebind stamp gives it the new line's.`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_ledger_apply.py`, then the regression set.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_ledger_apply.py backend/tests/test_template_ledger_apply.py
git commit -m "feat(line-ids): locate, stamp_uids and the uid_share rebuild metric

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 9: `vet_sheet(registry=…)` and `VetOutcome.carried`

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_sheet_save.py:24` (typing), `:61-77` (`VetOutcome`), `:220-272` (`vet_sheet`, `_with_ledger`)
- Modify: `backend/tests/test_template_ledger_save.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# ── stable line IDs: the registry reaches apply_ledger only through vet_sheet(registry=...) ───────────────────────

async def test_with_a_registry_the_ledger_resolves_uid_first_across_a_rename():
    from rapid_reports_ai import template_line_registry as tlr
    from rapid_reports_ai import template_sheet_grammar as tsg
    st = tsg.parse_sheet(LEDGER_SHEET).structure
    reg, _ = tlr.rebind(None, st, now="T")
    uid = tlr.uids_for(st, reg)["n0"]
    key = td.negative_key("Liver", "No focal liver lesion.")
    led = [{**_led(("normal", key, {"text": "No focal liver lesion."}))[0], "uid": uid}]
    rebuilt = LEDGER_SHEET.replace("## Paragraph: Liver (FINDINGS)", "## Paragraph: Hepatobiliary (FINDINGS)")
    out = await S.vet_sheet(rebuilt, origin="rebuild", previous=LEDGER_SHEET, ledger=led, registry=reg)
    assert 'NEGATIVE "No focal liver lesion."' in out.sheet and out.ledger_unmatched == []
    assert out.carried == {} and out.ledger[0]["uid"] == uid
    assert out.ledger[0]["key"] == td.negative_key("Hepatobiliary", "No focal liver lesion.")
    plain = await S.vet_sheet(rebuilt, origin="rebuild", previous=LEDGER_SHEET, ledger=led)
    assert plain.carried == {} and [e["key"] for e in plain.ledger_unmatched] == [key]
    m_uid = tlr.uids_for(st, reg)["m0"]
    m_led = [{**_led(("normal", td.normal_key("Liver", "liver"), {"text": "The liver is unremarkable."}))[0],
              "uid": m_uid}]
    moved = await S.vet_sheet(rebuilt, origin="rebuild", previous=LEDGER_SHEET, ledger=m_led, registry=reg)
    assert moved.carried == {m_uid: 'NORMAL [liver] "The liver is unremarkable."'}   # a rewrite is carried
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTEST tests/test_template_ledger_save.py -k registry`
Expected: FAIL with `TypeError: vet_sheet() got an unexpected keyword argument 'registry'`.

- [ ] **Step 3: Implement**

- `from typing import List, Literal, Optional, Set, TypedDict` becomes `from typing import Dict, List, Literal, Optional, Set, TypedDict`.
- In `VetOutcome`, after `habits_pending`:

```python
    carried: Dict[str, str] = field(default_factory=dict)        # with a registry: {uid: final raw line} of every
                                                                 # line the ledger rewrote (rebind keeps those uids)
```

- `vet_sheet`:

```python
async def vet_sheet(sheet: str, origin: Origin, previous: str = "", ledger: Optional[List[dict]] = None,
                    registry: Optional[dict] = None) -> VetOutcome:
```

Append to its docstring: `` `registry` (the stored line registry; persist_sheet only): the ledger resolves uid first and the outcome carries `carried`; None (every stateless caller) is exactly the key and text matching.`` Change its last line to `return _with_ledger(out, origin, previous, list(ledger), registry)`.

- `_with_ledger(out, origin, previous, ledger, registry: Optional[dict] = None)`; inside, `res = tla.apply_ledger(out.sheet, ledger, before=previous, registry=registry)`; in the final `dataclasses.replace(...)`, change `ledger=ledger` to `ledger=res.ledger` and add `carried=res.carried`. (`res.ledger` equals `ledger` when the registry is None.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_ledger_save.py`, then the regression set.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_sheet_save.py backend/tests/test_template_ledger_save.py
git commit -m "feat(line-ids): vet_sheet threads an optional registry; outcome carries the carried map

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 10: `persist_sheet`: the one persisted save

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_sheet_save.py` (append)
- Modify: `backend/tests/test_template_sheet_save.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_template_sheet_save.py`:

```python
# ── persist_sheet: the one persisted save (stable line IDs spec, "Where rebind runs") ─────────────────────────────

from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_line_registry as tlr
from tests.template_sheet_fixtures import LEDGER_SHEET


def _cfg(sheet, **extra):
    return {"generation_mode": "skill_sheet_guided", "skill_sheet": sheet, **extra}


def _uids(sheet, reg):
    return tlr.uids_for(tsg.parse_sheet(sheet).structure, reg)


async def test_a_first_save_mints_the_registry_and_sheet_rev_1(no_jev):
    p = await S.persist_sheet(_cfg(LEDGER_SHEET), {}, "analyser", now="T")
    assert p.outcome.status == "saved" and p.config["sheet_rev"] == 1
    assert len(p.report["new"]) == len(p.config["line_registry"]["units"]) == 10
    assert p.config["coverage_sections"] == ["TECHNIQUE", "FINDINGS", "IMPRESSION"]


async def test_sheet_rev_increments_from_the_stored_value_only_on_a_sheet_change(no_jev):
    first = (await S.persist_sheet(_cfg(LEDGER_SHEET), {}, "analyser", now="T")).config
    stored = {**first, "sheet_rev": 7}
    same = await S.persist_sheet(_cfg(LEDGER_SHEET, sheet_rev=99), stored, "chat", now="T")
    assert same.outcome.status == "unchanged" and same.config["sheet_rev"] == 7
    edited = LEDGER_SHEET.replace('FIXED "No previous imaging available."\n', "")
    changed = await S.persist_sheet(_cfg(edited, sheet_rev=99), stored, "chat", now="T")
    assert changed.config["sheet_rev"] == 8 and len(changed.report["gone"]) == 1


async def test_the_stored_registry_is_used_never_the_clients(no_jev):
    first = (await S.persist_sheet(_cfg(LEDGER_SHEET), {}, "analyser", now="T")).config
    forged = {"v": 1, "units": {"n_aaaaaa": {"kind": "normal", "identity": {}, "status": "live"}}}
    p = await S.persist_sheet(_cfg(LEDGER_SHEET, line_registry=forged), first, "chat", now="T")
    assert p.config["line_registry"] == first["line_registry"]


async def test_the_ledger_is_stamped_after_the_rebind(no_jev):
    led, _ = td.set_decision([], "normal", td.normal_key("Liver", "liver"), {"text": "The liver is unremarkable."},
                             source="creation", at="t")
    p = await S.persist_sheet(_cfg(LEDGER_SHEET), {}, "analyser", ledger=led, now="T")
    reg = p.config["line_registry"]
    assert p.config["decisions"][0]["uid"] == _uids(p.config["skill_sheet"], reg)["m0"]


async def test_a_refused_sheet_persists_nothing(no_jev):
    p = await S.persist_sheet(_cfg("# Free\nprose"), {}, "analyser", now="T")
    assert p.outcome.status == "refused" and p.config is None


async def test_persist_strips_client_server_written_keys_and_keeps_the_stored_ones(no_jev):
    first = (await S.persist_sheet(_cfg(LEDGER_SHEET), {}, "analyser", now="T")).config
    client = _cfg(LEDGER_SHEET, uncertain=[{"uid": "x"}], normal_confirms={"x": {}}, sheet_rev=50)
    fresh = await S.persist_sheet(client, {}, "analyser", now="T")
    assert "uncertain" not in fresh.config and "normal_confirms" not in fresh.config and fresh.config["sheet_rev"] == 1
    stored = {**first, "uncertain": [{"uid": "kept"}], "normal_confirms": {"g": {"kept": True}}}
    again = await S.persist_sheet(client, stored, "chat", now="T")
    assert again.config["uncertain"] == [{"uid": "kept"}] and again.config["normal_confirms"] == {"g": {"kept": True}}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_template_sheet_save.py -k "persist or sheet_rev or stamped or stored_registry or refused_sheet_persists or strips"`
Expected: FAIL with `AttributeError: module … has no attribute 'persist_sheet'`.

- [ ] **Step 3: Implement**

Append to `backend/src/rapid_reports_ai/template_sheet_save.py`:

```python
# ── the persisted save (spec 2026-10-15-stable-line-ids-design, "Where rebind runs") ─────────────────────────────

@dataclass
class Persisted:
    outcome: VetOutcome
    config: Optional[dict]                        # the config to store; None when the save function refused
    report: dict = field(default_factory=dict)    # the rebind report ({} for a non-grammar sheet)


# Server-written config keys (stable line IDs spec): never taken from a client config. persist_sheet writes
# line_registry, sheet_rev and uncertain; the confirm endpoint writes normal_confirms; main._carry_structure keeps the
# stored copies on a PUT or a restore.
SERVER_WRITTEN = ("line_registry", "uncertain", "normal_confirms", "sheet_rev")


def stored_rev(v) -> int:
    """A stored sheet_rev as an int (absent or malformed: 0, a template saved before sheet_rev existed)."""
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


async def persist_sheet(config: dict, stored_config: Optional[dict], origin: Origin, *,
                        ledger: Optional[List[dict]] = None, now: Optional[str] = None) -> Persisted:
    """The one persisted save of a grammar sheet: load the stored registry -> vet_sheet(registry=...) -> rebind ->
    stamp the ledger's uids -> sheet_rev. Every path that writes a template's sheet to the database calls this
    (main._vet_config, scripts.template_upgrade_apply); stateless callers use vet_sheet and never mint a uid.
    `stored_config`: the template's stored config ({} or None for a new template): its registry and sheet_rev are the
    only ones trusted. `ledger`: the cleaned decisions (None: none). The returned config holds skill_sheet,
    coverage_sections (a changed sheet), line_registry, sheet_rev and decisions (stamped, when a ledger was given).
    sheet_rev is incremented from the stored value when the stored sheet changes; the pair (sheet_rev, sheet_hash)
    is the reference, never sheet_rev alone."""
    from . import template_ledger_apply as tla
    from . import template_line_registry as tlr
    stored = stored_config or {}
    previous = stored.get("skill_sheet") or ""
    registry = tlr.load(stored.get("line_registry"))
    if origin == "rebuild" and ledger:
        logger.info("[line-registry] rebuild resolution %s", tla.uid_share(ledger, config.get("skill_sheet") or "",
                                                                          registry))
    out = await vet_sheet(config.get("skill_sheet") or "", origin=origin, previous=previous, ledger=ledger,
                          registry=registry)
    if out.status == "refused":
        return Persisted(out, None)
    cfg = {k: v for k, v in config.items() if k not in SERVER_WRITTEN}   # a client copy is never trusted (L2)
    cfg.update({k: stored[k] for k in ("uncertain", "normal_confirms") if k in stored})
    cfg["skill_sheet"] = out.sheet
    if out.status != "unchanged":
        cfg["coverage_sections"] = out.coverage_sections
    if ledger is not None:
        cfg["decisions"] = out.ledger
    report: dict = {}
    if tsg.is_grammar_sheet(out.sheet):
        st = tsg.parse_sheet(out.sheet, mode="template").structure
        registry, report = tlr.rebind(registry, st, out.carried, now=now)
        cfg["line_registry"] = registry
        if ledger is not None:
            cfg["decisions"] = tla.stamp_uids(out.ledger, st, registry)
        logger.info("[line-registry] origin=%s %s drift=%d", origin, tlr.summary(report), out.ledger_drift)
    rev = stored_rev(stored.get("sheet_rev"))
    cfg["sheet_rev"] = rev + 1 if out.sheet != previous else rev
    return Persisted(out, cfg, report)
```

Add one line to the module docstring: `persist_sheet is the persisted save: vet_sheet with the stored line registry, then the rebind, the ledger's uids and sheet_rev (spec 2026-10-15-stable-line-ids-design).`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_sheet_save.py`, then the regression set.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_sheet_save.py backend/tests/test_template_sheet_save.py
git commit -m "feat(line-ids): persist_sheet owns the persisted save (vet, rebind, stamp, sheet_rev)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 11: The persisting endpoints: `_carry_structure`, `_vet_config` via `persist_sheet`

Covers POST `/api/templates`, POST `/skill-sheet/save`, PUT `/api/templates/{id}` and restore. All four go through `_vet_config`.

**Files:**
- Modify: `backend/src/rapid_reports_ai/main.py:1728-1788` (`_carry_structure`, `_vet_config`)
- Modify: `backend/tests/test_template_sheet_save_routes.py` (four spies; spec gap 8)
- Create: `backend/tests/test_template_line_ids_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_template_line_ids_routes.py`:

```python
"""Stable line IDs on the persisting endpoints (spec 2026-10-15-stable-line-ids-design, "Where rebind runs"): every
path that stores a sheet runs template_sheet_save.persist_sheet; stateless paths never mint; server-written keys are
never taken from a client; the normals confirm endpoint."""
import uuid

import pytest

from rapid_reports_ai import template_line_registry as tlr
from rapid_reports_ai import template_sheet_grammar as tsg
from rapid_reports_ai import template_sheet_save as S
from rapid_reports_ai import template_sheet_structure as tss
from rapid_reports_ai.database.models import TemplateVersion
from tests.template_sheet_fixtures import GOOD, LEDGER_SHEET
from tests.test_template_sheet_save_routes import _get, _guided, _version_with

EDITED = GOOD + 'NORMAL [ligaments] "The cruciate ligaments are intact."\n'
CONFIRM = "/api/templates/{}/normal-confirms"


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    async def none(st, sheet=""):
        return []

    async def no_repair(sheet, errors):
        raise AssertionError("repair must not run")
    monkeypatch.setattr(S, "check_units", none)
    monkeypatch.setattr(S, "_repair", no_repair)
    monkeypatch.setattr("rapid_reports_ai.template_sheet_structure.store_parsed", lambda tid, st: True)


@pytest.fixture
def persisted(monkeypatch):
    seen = []
    real = S.persist_sheet

    async def spy(config, stored_config, origin, **kw):
        seen.append(origin)
        return await real(config, stored_config, origin, **kw)
    monkeypatch.setattr(S, "persist_sheet", spy)
    return seen


def _uids(sheet, reg):
    return tlr.uids_for(tsg.parse_sheet(sheet).structure, reg)


def test_create_mints_the_registry_and_sheet_rev(client, auth_headers, persisted):
    cfg = _guided(client, auth_headers)["template"]["template_config"]
    assert persisted == ["analyser"] and cfg["sheet_rev"] == 1
    assert set(_uids(GOOD, cfg["line_registry"])) == {"S:FINDINGS", "S:IMPRESSION", "p0", "m0"}


def test_create_ignores_client_server_written_keys(client, auth_headers):
    forged = {"v": 1, "units": {"n_aaaaaa": {"kind": "normal", "identity": {}, "status": "live"}}}
    r = client.post("/api/templates", headers=auth_headers, json={"name": "Knee", "template_config": {
        "generation_mode": "skill_sheet_guided", "skill_sheet": GOOD, "line_registry": forged, "sheet_rev": 41,
        "uncertain": [{"uid": "n_aaaaaa"}], "normal_confirms": {"x": {}}}}).json()
    cfg = r["template"]["template_config"]
    assert "n_aaaaaa" not in cfg["line_registry"]["units"] and cfg["sheet_rev"] == 1
    assert "uncertain" not in cfg and "normal_confirms" not in cfg


def test_skill_sheet_save_persists(client, auth_headers, persisted, db_session):
    from rapid_reports_ai.database.models import Template
    r = client.post("/api/templates/skill-sheet/save", headers=auth_headers, json={
        "skill_sheet": GOOD, "scan_type": "MRI knee", "template_name": "Knee"}).json()
    cfg = db_session.get(Template, uuid.UUID(r["template_id"])).template_config
    assert persisted == ["analyser"] and cfg["sheet_rev"] == 1 and cfg["line_registry"]["units"]


def test_update_keeps_uids_bumps_sheet_rev_and_ignores_a_client_registry(client, auth_headers, persisted):
    t = _guided(client, auth_headers)["template"]
    reg = t["template_config"]["line_registry"]
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={"template_config": {
        **t["template_config"], "skill_sheet": EDITED, "line_registry": {"v": 1, "units": {}}, "sheet_rev": 99}}).json()
    cfg = r["template"]["template_config"]
    assert persisted == ["analyser", "chat"] and cfg["sheet_rev"] == 2
    assert _uids(EDITED, cfg["line_registry"])["m0"] == _uids(GOOD, reg)["m0"]


def test_an_update_without_a_sheet_change_keeps_sheet_rev(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={
        "template_config": {**t["template_config"], "sheet_rev": 99}}).json()
    assert r["template"]["template_config"]["sheet_rev"] == 1


def test_restore_of_a_version_without_a_registry_rebinds_against_the_current_one(client, auth_headers, db_session,
                                                                                 persisted):
    t = _guided(client, auth_headers, sheet=EDITED)["template"]
    current = t["template_config"]["line_registry"]
    vid = _version_with(db_session, t["id"], GOOD)
    v = db_session.get(TemplateVersion, uuid.UUID(vid))   # a version saved before line IDs: no registry, no sheet_rev
    v.template_config = {k: x for k, x in v.template_config.items() if k not in ("line_registry", "sheet_rev")}
    db_session.commit()
    r = client.post(f"/api/templates/{t['id']}/versions/{vid}/restore", headers=auth_headers).json()
    assert r["success"], r
    cfg = _get(client, auth_headers, t["id"])["template_config"]
    assert persisted[-1] == "restore" and cfg["sheet_rev"] == 2
    assert _uids(GOOD, cfg["line_registry"])["m0"] == _uids(EDITED, current)["m0"]
    assert len([u for u in cfg["line_registry"]["units"] if u.startswith("n_")]) == 2   # the removed one is gone


def test_stateless_paths_never_persist_or_mint(client, auth_headers, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("a stateless path persisted")
    monkeypatch.setattr(S, "persist_sheet", boom)
    seen = []
    real = S.vet_sheet

    async def spy(sheet, origin, previous="", ledger=None, registry=None):
        seen.append(registry)
        return await real(sheet, origin, previous, ledger)
    monkeypatch.setattr(S, "vet_sheet", spy)
    monkeypatch.setattr("rapid_reports_ai.main.get_system_api_key", lambda *a, **k: "key")

    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": EDITED, "response": "Done.", "behavioral_claim": "c"}
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    r = client.post("/api/templates/skill-sheet/refine", headers=auth_headers,
                    json={"skill_sheet": GOOD, "message": "add the ligaments"}).json()
    assert r["success"] and "line_registry" not in r
    r = client.post("/api/templates/skill-sheet/apply-decisions", headers=auth_headers, json={
        "skill_sheet": GOOD, "source": "creation",
        "changes": [{"kind": "normal", "key": "Knee :: menisci", "choice": {"text": "The menisci are normal."}}]}).json()
    assert r["success"] and all("uid" not in e for e in r["decisions"])
    assert all(reg is None for reg in seen)
```

In `backend/tests/test_template_sheet_save_routes.py`, add `**kw` to the four spies `spy` (lines ~84 and ~170), `adjusted` (~99) and `refuse` (~185): `async def spy(sheet, origin, previous="", ledger=None, **kw):` and likewise for the other three (persist_sheet now passes `registry=`; spec gap 8).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_template_line_ids_routes.py`
Expected: FAIL with `KeyError: 'sheet_rev'` / `KeyError: 'line_registry'` (the endpoints do not call `persist_sheet` yet; `persisted == []`).

- [ ] **Step 3: Implement in `main.py`**

At the end of `_carry_structure`, before `return new` (the key list lives in `template_sheet_save`, Task 10):

```python
    # stable line IDs (spec 2026-10-15): the registry, `uncertain` (slice 4), the normals confirms and the sheet
    # revision are server-written only: a client (or a restored version's) copy is dropped, the stored one kept
    for k in tsave.SERVER_WRITTEN:
        new.pop(k, None)
        if k in old:
            new[k] = old[k]
```

Update the `_carry_structure` docstring first line to: `"""sheet_structure and the stable-line-ID keys (tsave.SERVER_WRITTEN) are server-written only: drop any client copy, carry the stored one (sheet_structure only while the sheet is unchanged)."""`

In `_vet_config`, add to the docstring: `The save itself is template_sheet_save.persist_sheet (the line registry, the ledger's uids, sheet_rev).` Then replace

```python
    out = await tsave.vet_sheet(sheet, origin=origin, previous=before, ledger=ledger or None)
    if out.status == "refused":
        return None, out.message, "", []
    if ledger:
        cfg = {**new_cfg, "decisions": out.ledger, "ledger_unmatched": out.ledger_unmatched}
    else:
        cfg = {k: v for k, v in new_cfg.items() if k != "ledger_unmatched"}
    notice = " ".join(x for x in [out.message or "", *tsave.ledger_notes(out)] if x)
    if out.status == "unchanged":   # the stored sheet stands (the ledger may have put back what the edit changed)
        return {**cfg, "skill_sheet": out.sheet}, "", notice, out.ledger_cards
    return ({**cfg, "skill_sheet": out.sheet, "coverage_sections": out.coverage_sections}, "", notice,
            out.ledger_cards)
```

with

```python
    saved = await tsave.persist_sheet(new_cfg, old, origin, ledger=ledger or None)
    out = saved.outcome
    if out.status == "refused":
        return None, out.message, "", []
    # persist_sheet returns skill_sheet (the stored one when unchanged), coverage_sections only for a changed sheet,
    # decisions stamped with their uids, line_registry and sheet_rev
    if ledger:
        cfg = {**saved.config, "ledger_unmatched": out.ledger_unmatched}
    else:
        cfg = {k: v for k, v in saved.config.items() if k != "ledger_unmatched"}
    notice = " ".join(x for x in [out.message or "", *tsave.ledger_notes(out)] if x)
    return cfg, "", notice, out.ledger_cards
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_line_ids_routes.py tests/test_template_sheet_save_routes.py tests/test_template_ledger_routes.py`
Expected: all pass. Then run the regression set. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/main.py backend/tests/test_template_line_ids_routes.py backend/tests/test_template_sheet_save_routes.py
git commit -m "feat(line-ids): persisting endpoints save through persist_sheet; registry keys server-written

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 12: The upgrade script saves through `persist_sheet`

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/template_upgrade_apply.py:97-107` (`_plan_entry`)
- Modify: `backend/tests/test_template_upgrade_apply.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_the_upgrade_saves_through_persist_sheet_and_mints_the_registry(db_session, templates, tmp_path, no_jev,
                                                                         monkeypatch):
    seen = []
    real = S.persist_sheet

    async def spy(config, stored_config, origin, **kw):
        seen.append(origin)
        return await real(config, stored_config, origin, **kw)
    monkeypatch.setattr(S, "persist_sheet", spy)
    guided, _ = templates
    summary = U.main(_manifest(tmp_path, guided.id, GOOD), apply=True, db=db_session)
    assert _actions(summary)[str(guided.id)] == "written" and seen == ["rebuild"]
    db_session.expire_all()
    cfg = db_session.get(Template, guided.id).template_config
    assert cfg["sheet_rev"] == 1 and len(cfg["line_registry"]["units"]) == 4


def test_a_confirm_recorded_between_plan_and_write_is_kept(db_session, templates, tmp_path, no_jev, monkeypatch):
    guided, _ = templates
    real = U._plan_entry

    async def plan_then_confirm(db, entry, analyser_version=None):
        row = await real(db, entry, analyser_version)
        t = db.get(Template, guided.id)
        t.template_config = {**t.template_config, "normal_confirms": {"g": {"kept": True}}}
        db.commit()
        return row
    monkeypatch.setattr(U, "_plan_entry", plan_then_confirm)
    summary = U.main(_manifest(tmp_path, guided.id, GOOD), apply=True, db=db_session)
    assert _actions(summary)[str(guided.id)] == "written"
    db_session.expire_all()
    cfg = db_session.get(Template, guided.id).template_config
    assert cfg["normal_confirms"] == {"g": {"kept": True}} and cfg["skill_sheet"] == GOOD
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTEST tests/test_template_upgrade_apply.py -k "persist_sheet or between_plan"`
Expected: FAIL: `seen == []`, `KeyError: 'sheet_rev'`, and the confirm recorded between plan and write is overwritten.

- [ ] **Step 3: Implement**

In `_plan_entry`, replace

```python
    # The same steps as a sheet save (PUT /api/templates: _carry_structure then _vet_config's guided branch): drop
    # the stored structure, carry analyser_version, vet the sheet, store the vetted sheet + coverage_sections.
```

with

```python
    # The same steps as a sheet save (PUT /api/templates: _carry_structure then _vet_config's guided branch): drop
    # the stored structure, carry analyser_version, then the one persisted save (template_sheet_save.persist_sheet:
    # vet, rebind the line registry against the stored one, stamp the ledger's uids, bump sheet_rev).
```

and replace

```python
    out = await tsave.vet_sheet(new_cfg["skill_sheet"], origin=ORIGIN, previous=current, ledger=ledger)
    if out.status == "refused":
        return {"template_id": tid, "action": "skipped-refused", "reason": out.message or "refused"}
    if out.status == "unchanged":
        return {"template_id": tid, "action": "skipped-unchanged"}
    vetted = {**new_cfg, "skill_sheet": out.sheet, "coverage_sections": out.coverage_sections}
```

with

```python
    saved = await tsave.persist_sheet(new_cfg, cfg, ORIGIN, ledger=ledger)
    out = saved.outcome
    if out.status == "refused":
        return {"template_id": tid, "action": "skipped-refused", "reason": out.message or "refused"}
    if out.status == "unchanged":
        return {"template_id": tid, "action": "skipped-unchanged"}
    vetted = dict(saved.config)
```

In `_write`, replace

```python
    # converted_at: the banner names its owner's converted templates (integration spec §10, P2c)
    t.template_config = {**row["config"], "converted_at": datetime.now(timezone.utc).isoformat()}
```

with (plan review L3; spec gap 14)

```python
    # converted_at: the banner names its owner's converted templates (integration spec §10, P2c). The planned config
    # owns the sheet, its registry and sheet_rev (the hash re-check above guarantees the sheet, and so the registry,
    # did not move); the server-written keys the plan does not own (`uncertain`, reserved for slice 4, the normals
    # confirms) are re-read here under the lock, so a confirm recorded since the plan is never overwritten.
    stored = t.template_config or {}
    kept = {k: stored[k] for k in ("uncertain", "normal_confirms") if k in stored}
    t.template_config = {**row["config"], **kept, "converted_at": datetime.now(timezone.utc).isoformat()}
```

In the module docstring, change `skipped-refused   the one save function (template_sheet_save.vet_sheet, origin "rebuild") refused the new sheet` to `skipped-refused   the persisted save (template_sheet_save.persist_sheet, origin "rebuild") refused the new sheet`. `_already_written` keeps calling `vet_sheet` without a registry (a stateless re-run check).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_upgrade_apply.py`
Expected: `24 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/template_upgrade_apply.py backend/tests/test_template_upgrade_apply.py
git commit -m "feat(line-ids): the upgrade script saves through persist_sheet

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 13: Confirm groups and state (pure)

**Files:**
- Create: `backend/src/rapid_reports_ai/template_normal_confirms.py`
- Create: `backend/tests/test_template_normal_confirms.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_template_normal_confirms.py`:

```python
"""The normals confirm record (spec 2026-10-15-stable-line-ids-design, decision 5): groups, chunks, state."""
from rapid_reports_ai import template_line_registry as tlr
from rapid_reports_ai import template_normal_confirms as tnc
from rapid_reports_ai import template_sheet_grammar as tsg
from rapid_reports_ai import template_sheet_structure as tss
from tests.template_sheet_fixtures import HABIT_SHEET, LEDGER_SHEET


def _st(sheet):
    res = tsg.parse_sheet(sheet)
    assert not res.errors and res.structure.usable, res.errors
    return res.structure


def _reg(sheet, registry=None):
    return tlr.rebind(registry, _st(sheet), now="T")[0]


def _groups(sheet, reg):
    return tnc.groups(_st(sheet), sheet, reg)


def test_findings_paragraphs_are_groups_and_sections_without_attestable_units_are_none():
    reg = _reg(HABIT_SHEET)
    uids = tlr.uids_for(_st(HABIT_SHEET), reg)
    got = [(g.id, g.label, g.units) for g in _groups(HABIT_SHEET, reg)]
    assert got == [(uids["p1"], "Findings › Liver", (uids["m0"], uids["n0"])),
                   (uids["p2"], "Findings › Lower", (uids["m1"],))]
    # the technique section holds only a FIXED line (not attestable) and the impression nothing: no group


def test_a_non_findings_section_is_one_group_with_its_normals():
    sheet = LEDGER_SHEET.replace('FIXED "Axial images were acquired."',
                                 'FIXED "Axial images were acquired."\nNORMAL [coverage] "Coverage is complete."')
    reg = _reg(sheet)
    uids = tlr.uids_for(_st(sheet), reg)
    first = _groups(sheet, reg)[0]
    assert (first.id, first.label, first.units) == (uids["S:TECHNIQUE"], "Technique", (uids["m0"],))


def test_conditional_and_habit_negatives_are_not_attestable():
    sheet = HABIT_SHEET.replace('NEGATIVE "No focal liver lesion."',
                                'NEGATIVE "No focal liver lesion."\nNEGATIVE "No duct dilatation." '
                                'WHEN [findings: a liver mass is reported]')
    reg = _reg(sheet)
    assert len(_groups(sheet, reg)[0].units) == 2


def test_a_group_over_eight_is_chunked_in_document_order():
    extra = "\n".join(f'NORMAL [s{k}] "Structure {k} is normal."' for k in range(9))
    sheet = LEDGER_SHEET.replace('COVERS ["liver" | "gallbladder"]',
                                 'COVERS ["liver" | "gallbladder" | ' + " | ".join(f'"s{k}"' for k in range(9)) + "]") \
                        .replace('NEGATIVE "No focal liver lesion."', f'NEGATIVE "No focal liver lesion."\n{extra}')
    reg = _reg(sheet)
    uids = tlr.uids_for(_st(sheet), reg)
    gs = _groups(sheet, reg)
    assert [g.id for g in gs] == [f"{uids['p1']}#1", f"{uids['p1']}#2"]
    assert [len(g.units) for g in gs] == [8, 3] and gs[0].label == "Findings › Liver (1/2)"
    assert gs[0].units[:2] == (uids["m0"], uids["n0"])          # document order: the NORMAL, then the NEGATIVE


def _confirmed(sheet, reg):
    g = _groups(sheet, reg)[0]
    return g, tnc.record(g, reg, sheet_rev=1, sheet_hash=tss.sheet_hash(sheet), user_id="u", now="T")


def test_state_is_valid_until_a_unit_changes_is_added_or_removed():
    reg = _reg(LEDGER_SHEET)
    g, rec = _confirmed(LEDGER_SHEET, reg)
    assert tnc.confirm_state(g, rec, reg) == "valid" and tnc.confirm_state(g, None, reg) == "missing"
    assert rec["units"] == {u: reg["units"][u]["text_hash"] for u in g.units} and rec["user_id"] == "u"
    reworded = LEDGER_SHEET.replace('"The liver is normal in size."\nNEGATIVE', '"The liver is unremarkable."\nNEGATIVE')
    reg2 = _reg(reworded, reg)
    g2 = _groups(reworded, reg2)[0]
    assert (g2.id, g2.units) == (g.id, g.units)                               # (a) the reworded normal kept its slot uid
    assert tnc.confirm_state(g2, rec, reg2) == "stale"                        # ... and its changed text_hash makes it stale
    added = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."',
                                 'NEGATIVE "No focal liver lesion."\nNORMAL [gallbladder] "The gallbladder is normal."')
    reg3 = _reg(added, reg)
    assert tnc.confirm_state(_groups(added, reg3)[0], rec, reg3) == "stale"
    removed = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."\n', "")
    reg4 = _reg(removed, reg)
    assert tnc.confirm_state(_groups(removed, reg4)[0], rec, reg4) == "stale"
    assert tnc.confirm_states(_st(removed), removed, reg4, {g.id: rec}) == {g.id: "stale"}


def test_a_renamed_group_is_stale_even_when_every_sentence_carried():
    reg = _reg(LEDGER_SHEET)
    g, rec = _confirmed(LEDGER_SHEET, reg)
    assert rec["group_name"] == "Liver"
    for new_name in ("Hepatobiliary", "liver"):                          # (b) a rename, a case-only one included
        renamed = LEDGER_SHEET.replace("## Paragraph: Liver (FINDINGS)", f"## Paragraph: {new_name} (FINDINGS)")
        reg2 = _reg(renamed, reg)
        g2 = _groups(renamed, reg2)[0]
        assert (g2.id, g2.units) == (g.id, g.units)                   # every sentence identical, every uid kept
        assert all(reg2["units"][u]["text_hash"] == reg["units"][u]["text_hash"] for u in g.units)
        assert tnc.confirm_state(g2, rec, reg2) == "stale"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_template_normal_confirms.py`
Expected: collection error `ImportError: cannot import name 'template_normal_confirms'`.

- [ ] **Step 3: Write the module**

Create `backend/src/rapid_reports_ai/template_normal_confirms.py`:

```python
"""The normals confirm record (spec 2026-10-15-stable-line-ids-design, decision 5): the radiologist confirms a
template's assumed normals in small groups beside their sentences, and each confirm is recorded in
template_config["normal_confirms"] ({group id: record}), written only by POST /api/templates/{id}/normal-confirms
from the stored sheet and registry (never from the client, never by code on its own). Pure code here.

Groups (one definition): in a findings section, one group per paragraph (the scratchpad's regions,
hybrid_stack.template.paragraph_regions) and one for the section's units outside any paragraph; every other section is
one group. A group with more than MAX_GROUP attestable units is split into consecutive chunks of at most MAX_GROUP in
document order ("<uid>#1", "#2", …). Inserting or removing a normal shifts later chunks, so they go stale and are
confirmed again (accepted). Attestable units: the group's NORMAL lines and its unconditional template NEGATIVE lines.

State: valid (the group's current attestable units are exactly the record's, each with the same text_hash, and its
paragraph or section still has the recorded name), stale (anything else: a unit added, removed or gone; ANY unit's
text_hash changed, including a normal reworded in place that kept its slot uid (a normal's identity holds no text, so
this check is the safety net); or a paragraph or section rename (group_name), even when every sentence carried over:
a confirm given in one context never silently covers another), missing (no record). A stale confirm is asked again and never counts. The confirm UI is offered only
once the template is saved: there are no creation-time confirms."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from . import template_line_match as tlm
from . import template_line_registry as tlr
from .hybrid_stack.template import paragraph_regions

logger = logging.getLogger(__name__)

MAX_GROUP = 8
VALID, STALE, MISSING = "valid", "stale", "missing"


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    units: Tuple[str, ...]   # uids, in document order
    name: str = ""           # the paragraph's or section's name (group_name): a rename makes a confirm stale


def attestable(st) -> List[str]:
    """Parse refs of the attestable units: every NORMAL, and every NEGATIVE with no condition from the template."""
    return [n.id for n in st.normals] + [n.id for n in st.negatives
                                         if not n.condition and n.origin == "template" and n.kind == "negative"]


def _positions(sheet: str, st) -> Dict[str, int]:
    """Parse ref -> sheet line index of each line-bound unit (the k-th identical line is the k-th occurrence)."""
    lines = (sheet or "").split("\n")
    taken: set = set()
    out: Dict[str, int] = {}
    for u in tlr.units(st):
        if u.kind not in tlr.LINE_KINDS:
            continue
        i = next((k for k, ln in enumerate(lines) if k not in taken and ln == u.raw), None)
        if i is not None:
            taken.add(i)
            out[u.ref] = i
    return out


def group_name(name: str) -> str:
    """A paragraph's or section's name as a confirm record stores it: tlm.rep_key (lookalikes and spacing only; any
    other change, case included, is a rename and makes the confirm stale, decision 7)."""
    return tlm.rep_key(name)


def groups(st, sheet: str, registry) -> List[Group]:
    """The confirm groups of a parsed sheet, in section order (module doc). A group whose parent or any unit has no
    uid in `registry` is left out (logged): it cannot be recorded."""
    uids = tlr.uids_for(st, registry)
    pos = _positions(sheet, st)
    by_ref = {u.ref: u for u in tlr.units(st)}
    att = sorted((r for r in attestable(st) if r in pos), key=lambda r: pos[r])
    regions = paragraph_regions(st)
    out: List[Group] = []
    for sec in sorted(st.sections, key=lambda s: s.order):
        mine = [r for r in att if by_ref[r].section == f"S:{sec.name}"]
        buckets: List[Tuple[str, str, str, List[str]]] = []   # (parent ref, label, name, unit refs)
        if sec.role == "findings":
            for p in (p for p in st.paragraphs if p.section == sec.name):
                buckets.append((p.id, f"{sec.name.title()} › {regions.get(p.id, p.name)}", p.name,
                                [r for r in mine if by_ref[r].paragraph == p.id]))
            buckets.append((f"S:{sec.name}", sec.name.title(), sec.name,
                            [r for r in mine if not by_ref[r].paragraph]))
        else:
            buckets.append((f"S:{sec.name}", sec.name.title(), sec.name, mine))
        for parent, label, raw_name, refs in buckets:
            if not refs:
                continue
            if parent not in uids or any(r not in uids for r in refs):
                logger.info("[confirms] group %s left out: a unit has no uid", label)
                continue
            members = tuple(uids[r] for r in refs)
            name = group_name(raw_name)
            if len(members) <= MAX_GROUP:
                out.append(Group(uids[parent], label, members, name))
                continue
            chunks = [members[k:k + MAX_GROUP] for k in range(0, len(members), MAX_GROUP)]
            out += [Group(f"{uids[parent]}#{n}", f"{label} ({n}/{len(chunks)})", c, name)
                    for n, c in enumerate(chunks, 1)]
    return out


def record(group: Group, registry, *, sheet_rev: int, sheet_hash: str, user_id: str,
           now: Optional[str] = None) -> dict:
    """The confirm record of one group, its units' text_hash read from the stored registry."""
    units = tlr.load(registry)["units"]
    return {"group": group.id, "label": group.label, "units": {u: units[u]["text_hash"] for u in group.units},
            "sheet_rev": sheet_rev, "sheet_hash": sheet_hash, "group_name": group.name, "user_id": user_id,
            "at": now or datetime.now(timezone.utc).isoformat(timespec="seconds")}


def confirm_state(group: Optional[Group], rec: Optional[dict], registry) -> str:
    """valid / stale / missing for one group (module doc). `group` None: the group no longer exists (stale when a
    record names it). The same attestable predicate is used when confirming and when checking."""
    if not isinstance(rec, dict):
        return MISSING
    if group is None or rec.get("group_name") != group.name:   # a renamed paragraph or section (decision 5)
        return STALE
    units = tlr.load(registry)["units"]
    now = {u: units[u]["text_hash"] for u in group.units if units.get(u, {}).get("status") == "live"}
    return VALID if len(now) == len(group.units) and rec.get("units") == now else STALE


def confirm_states(st, sheet: str, registry, confirms) -> Dict[str, str]:
    """{group id: state} for every current group, and stale for every recorded group that no longer exists."""
    confirms = confirms if isinstance(confirms, dict) else {}
    current = {g.id: g for g in groups(st, sheet, registry)}
    out = {gid: confirm_state(g, confirms.get(gid), registry) for gid, g in current.items()}
    out.update({gid: STALE for gid in confirms if gid not in current})
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_normal_confirms.py`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_normal_confirms.py backend/tests/test_template_normal_confirms.py
git commit -m "feat(line-ids): normals confirm groups, chunks and state

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 14: The confirm endpoint (`POST /api/templates/{id}/normal-confirms`)

**Files:**
- Modify: `backend/src/rapid_reports_ai/main.py` (request model next to `TemplateCreate` ~661; endpoint before `@app.delete("/api/templates/{template_id}")` ~1896)
- Modify: `backend/tests/test_template_line_ids_routes.py` (append)

- [ ] **Step 1: Write the failing tests**

Append:

```python
# ── the normals confirm endpoint ──────────────────────────────────────────────────────────────────────────────

def _confirmable(client, auth_headers):
    t = client.post("/api/templates", headers=auth_headers, json={"name": "Liver", "template_config": {
        "generation_mode": "skill_sheet_guided", "skill_sheet": LEDGER_SHEET}}).json()["template"]
    cfg = t["template_config"]
    return t, cfg, _uids(LEDGER_SHEET, cfg["line_registry"])["p1"]


def test_a_confirm_is_computed_server_side_and_records_the_session_user(client, auth_headers, test_user):
    t, cfg, group = _confirmable(client, auth_headers)
    r = client.post(CONFIRM.format(t["id"]), headers=auth_headers, json={
        "group": group, "sheet_rev": cfg["sheet_rev"], "sheet_hash": tss.sheet_hash(LEDGER_SHEET),
        "units": {"n_forged": "sha256:x"}, "user_id": "someone-else"})
    assert r.status_code == 200, r.text
    rec = r.json()["confirm"]
    uids = _uids(LEDGER_SHEET, cfg["line_registry"])
    assert set(rec["units"]) == {uids["m0"], uids["n0"]} and rec["user_id"] == str(test_user.id)
    assert rec["units"][uids["m0"]] == cfg["line_registry"]["units"][uids["m0"]]["text_hash"]
    assert _get(client, auth_headers, t["id"])["template_config"]["normal_confirms"] == {group: rec}


@pytest.mark.parametrize("field", ["sheet_rev", "sheet_hash"])
def test_a_confirm_on_a_stale_sheet_is_409(client, auth_headers, field):
    t, cfg, group = _confirmable(client, auth_headers)
    body = {"group": group, "sheet_rev": cfg["sheet_rev"], "sheet_hash": tss.sheet_hash(LEDGER_SHEET)}
    body[field] = 0 if field == "sheet_rev" else "f" * 64
    assert client.post(CONFIRM.format(t["id"]), headers=auth_headers, json=body).status_code == 409
    assert "normal_confirms" not in _get(client, auth_headers, t["id"])["template_config"]


def test_a_confirm_for_a_missing_template_is_404_and_an_unknown_group_422(client, auth_headers):
    body = {"group": "p_aaaaaa", "sheet_rev": 1, "sheet_hash": "x"}
    assert client.post(CONFIRM.format(uuid.uuid4()), headers=auth_headers, json=body).status_code == 404
    t, cfg, _ = _confirmable(client, auth_headers)
    body = {**body, "sheet_rev": cfg["sheet_rev"], "sheet_hash": tss.sheet_hash(LEDGER_SHEET)}
    assert client.post(CONFIRM.format(t["id"]), headers=auth_headers, json=body).status_code == 422


def test_confirms_survive_a_put_that_sends_its_own_copy(client, auth_headers):
    t, cfg, group = _confirmable(client, auth_headers)
    client.post(CONFIRM.format(t["id"]), headers=auth_headers, json={
        "group": group, "sheet_rev": cfg["sheet_rev"], "sheet_hash": tss.sheet_hash(LEDGER_SHEET)})
    stored = _get(client, auth_headers, t["id"])["template_config"]["normal_confirms"]
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={"template_config": {
        **cfg, "normal_confirms": {}}}).json()
    assert r["template"]["template_config"]["normal_confirms"] == stored


def test_a_confirm_on_a_template_saved_before_sheet_rev_compares_against_0(client, auth_headers, db_session):
    from rapid_reports_ai.database.models import Template
    t, cfg, group = _confirmable(client, auth_headers)
    row = db_session.get(Template, uuid.UUID(t["id"]))
    row.template_config = {k: v for k, v in row.template_config.items() if k != "sheet_rev"}
    db_session.commit()
    r = client.post(CONFIRM.format(t["id"]), headers=auth_headers, json={
        "group": group, "sheet_rev": 0, "sheet_hash": tss.sheet_hash(LEDGER_SHEET)})
    assert r.status_code == 200, r.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_template_line_ids_routes.py -k confirm`
Expected: FAIL: the endpoint returns 405 or 404 for every call (no route).

- [ ] **Step 3: Implement**

After `class TemplateCreate` in `main.py`:

```python
class NormalConfirmRequest(BaseModel):
    """A normals confirm (spec 2026-10-15-stable-line-ids-design): the group and the sheet the radiologist saw. Any
    other field (a unit list, a user id) is ignored: the units are worked out from the stored sheet, the user from
    the session."""
    group: str = Field(max_length=64)
    sheet_rev: int
    sheet_hash: str = Field(max_length=128)
```

Before `@app.delete("/api/templates/{template_id}")`:

```python
@app.post("/api/templates/{template_id}/normal-confirms")
async def normal_confirm_endpoint(
    template_id: str,
    request: NormalConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Record a normals confirm for one group of a saved template (spec 2026-10-15-stable-line-ids-design). 404: no
    such template (confirms exist only once a template is saved); 409: the sheet changed since the radiologist saw it
    (sheet_rev / sheet_hash differ), so a concurrent edit is never attested unseen; 422: no such group. The units and
    their text_hash come from the stored sheet and registry; user_id from the session."""
    from sqlalchemy.orm.attributes import flag_modified
    from . import template_normal_confirms as tnc
    template = get_template(db, template_id, user_id=str(current_user.id))
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    row = db.query(Template).filter(Template.id == template.id).with_for_update().populate_existing().first()
    cfg = dict(row.template_config or {})
    sheet = cfg.get("skill_sheet") or ""
    if request.sheet_rev != tsave.stored_rev(cfg.get("sheet_rev")) or request.sheet_hash != tss.sheet_hash(sheet):
        db.rollback()
        raise HTTPException(status_code=409, detail="The template has changed; reload it and confirm again.")
    st = tsg.parse_sheet(sheet, mode="template").structure if tsg.is_grammar_sheet(sheet) else None
    found = tnc.groups(st, sheet, cfg.get("line_registry")) if st is not None else []
    group = next((g for g in found if g.id == request.group), None)
    if group is None:
        db.rollback()
        raise HTTPException(status_code=422, detail="Unknown group.")
    rec = tnc.record(group, cfg.get("line_registry"), sheet_rev=request.sheet_rev, sheet_hash=request.sheet_hash,
                     user_id=str(current_user.id))
    confirms = cfg.get("normal_confirms") if isinstance(cfg.get("normal_confirms"), dict) else {}
    row.template_config = {**cfg, "normal_confirms": {**confirms, group.id: rec}}
    flag_modified(row, "template_config")
    db.commit()
    return {"success": True, "confirm": rec, "state": tnc.VALID}
```

(`Template`, `HTTPException`, `get_template`, `tss`, `tsg` are already imported in `main.py`. A confirm writes the config directly, like `store_structure`, and creates no TemplateVersion.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_line_ids_routes.py`
Expected: all pass (13).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/main.py backend/tests/test_template_line_ids_routes.py
git commit -m "feat(line-ids): normals confirm endpoint (server-computed units, 409 on a stale sheet)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 17: `generation_stamp` records `sheet_rev`

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_sheet_structure.py:268-282`
- Modify: `backend/tests/test_template_generate_endpoint.py:475-486` (`test_generation_stamp_is_total`; spec gap 8)

- [ ] **Step 1: Update the test (failing)**

Replace `test_generation_stamp_is_total` with:

```python
def test_generation_stamp_is_total():
    from rapid_reports_ai.template_sheet_structure import STRUCTURE_VERSION, generation_stamp, sheet_hash
    assert generation_stamp("t", "not a dict", "fallback") == {
        "template_id": "t", "sheet_hash": None, "sheet_rev": None, "grammar_version": STRUCTURE_VERSION,
        "analyser_version": "", "path": "fallback"}
    odd = generation_stamp("t", {"skill_sheet": 123, "analyser_version": 7, "sheet_rev": "9"}, "scratchpad")
    assert odd["sheet_hash"] is None and odd["analyser_version"] == "" and odd["sheet_rev"] is None
    assert generation_stamp("t", {"skill_sheet": "  \n"}, "scratchpad")["sheet_hash"] is None   # empty: no hash
    assert generation_stamp("t", {"skill_sheet": "x", "analyser_version": "v" * 99, "sheet_rev": 4}, "scratchpad") == {
        "template_id": "t", "sheet_hash": sheet_hash("x"), "sheet_rev": 4, "grammar_version": STRUCTURE_VERSION,
        "analyser_version": "v" * 64, "path": "scratchpad"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTEST tests/test_template_generate_endpoint.py -k generation_stamp_is_total`
Expected: FAIL: the dict has no `sheet_rev`.

- [ ] **Step 3: Implement**

In `generation_stamp`, replace the `return {...}` with:

```python
        rev = config.get("sheet_rev")
        return {"template_id": str(template_id), "sheet_hash": sheet_hash(sheet) if sheet.strip() else None,
                "sheet_rev": rev if isinstance(rev, int) and not isinstance(rev, bool) else None,
                "grammar_version": STRUCTURE_VERSION,
                "analyser_version": version[:64] if isinstance(version, str) else "", "path": str(path)}
```

and add to the docstring: `sheet_rev (stable line IDs spec) is recorded beside sheet_hash: the pair is the sheet's reference, never sheet_rev alone.`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_template_generate_endpoint.py tests/test_quality_scoring.py tests/test_review_engine_template_text.py tests/test_stack_generate_endpoint.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_sheet_structure.py backend/tests/test_template_generate_endpoint.py
git commit -m "feat(line-ids): generation_stamp records sheet_rev beside sheet_hash

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 18: Backfill script (dropped)

Dropped (2026-10-15): production count 47 active / 0 with answers / 0 grammar sheets; registry is minted lazily by persist_sheet.

---

### Task 19: Rebuild fixture: wrong matches (primary) and resolved share (secondary)

**Files:**
- Create: `backend/tests/template_line_fixtures.py`
- Create: `backend/tests/test_template_line_rebuild.py`

- [ ] **Step 1: Write the fixture and the test**

Create `backend/tests/template_line_fixtures.py`:

```python
"""Two writer outputs for the same synthetic example reports (stable line IDs spec, rebuild fixture). REBUILD_B is a
rebuild of REBUILD_A with planted changes: paragraphs reordered, one renamed (same COVERS), small rewordings (a dropped
full stop, a filler; new slots under exact matching, decision 7), a reworded NORMAL, real wording changes, adversarial
near-misses (pleural/pericardial, left/right), a dropped and an added line. SAME lists every (A line, B line) pair that
is the same slot; any other uid carried from A is a wrong match."""

REBUILD_A = """# Skill Sheet: Rebuild fixture

## Report Structure
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Paragraph: Technique (TECHNIQUE)
FIXED "Axial images were acquired after contrast."
FIXED "No previous imaging is available."

## Paragraph: Liver (FINDINGS)
COVERS ["liver" | "gallbladder"]
NORMAL [liver] "The liver is normal in size and attenuation."
NORMAL [gallbladder] "The gallbladder is unremarkable."
NEGATIVE "No focal liver lesion."
NEGATIVE "No biliary dilatation."

## Paragraph: Chest base (FINDINGS)
COVERS ["lung bases" | "pleura"]
NORMAL [lung bases] "The lung bases are clear."
NEGATIVE "No pleural effusion."
NEGATIVE "No left basal consolidation."

## Paragraph: Kidneys (FINDINGS)
COVERS ["kidneys"]
NORMAL [kidneys] "The kidneys are normal."
NEGATIVE "No hydronephrosis."

## Paragraph: Impression (IMPRESSION)
Opening: "Normal study."
"""

REBUILD_B = """# Skill Sheet: Rebuild fixture

## Report Structure
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Paragraph: Technique (TECHNIQUE)
FIXED "Axial images were acquired after contrast"
FIXED "No prior imaging available."

## Paragraph: Hepatobiliary (FINDINGS)
COVERS ["liver" | "gallbladder"]
NORMAL [liver] "Normal liver size and attenuation."
NORMAL [gallbladder] "The gallbladder is unremarkable."
NEGATIVE "There is no focal liver lesion"
NEGATIVE "No biliary duct dilatation."

## Paragraph: Kidneys (FINDINGS)
COVERS ["kidneys" | "ureters"]
NORMAL [kidneys] "The kidneys are normal."
NORMAL [ureters] "The ureters are normal."
NEGATIVE "No hydronephrosis."

## Paragraph: Chest base (FINDINGS)
COVERS ["lung bases" | "pleura"]
NORMAL [lung bases] "The lung bases are clear."
NEGATIVE "No pericardial effusion."
NEGATIVE "No right basal consolidation."

## Paragraph: Impression (IMPRESSION)
Opening: "Normal study."
"""

# (A line, B line) of every line-bound unit that is the same slot in both (paragraphs by name). The reworded liver
# NORMAL in the renamed paragraph is NOT the same slot (spec decision 5: across a rename a normal needs its own text),
# nor are the FIXED line that lost its full stop and the NEGATIVE that gained "There is" (decision 7: exact matching).
SAME = [
    ('NORMAL [gallbladder] "The gallbladder is unremarkable."', 'NORMAL [gallbladder] "The gallbladder is unremarkable."'),
    ('NORMAL [lung bases] "The lung bases are clear."', 'NORMAL [lung bases] "The lung bases are clear."'),
    ('NORMAL [kidneys] "The kidneys are normal."', 'NORMAL [kidneys] "The kidneys are normal."'),
    ('NEGATIVE "No hydronephrosis."', 'NEGATIVE "No hydronephrosis."'),
    ("Paragraph: Liver", "Paragraph: Hepatobiliary"),
    ("Paragraph: Chest base", "Paragraph: Chest base"),
    ("Paragraph: Kidneys", "Paragraph: Kidneys"),
    ("Paragraph: Technique", "Paragraph: Technique"),
    ("Paragraph: Impression", "Paragraph: Impression"),
]
```

Create `backend/tests/test_template_line_rebuild.py`:

```python
"""Rebuild fixture (stable line IDs spec, "Tests"): two writer outputs for the same synthetic reports. Primary metric:
wrong matches, which must be 0. Secondary (printed, never asserted): the share of line-bound ledger entries resolved
by uid against today's text matching on the same rebuild. Run with -s to see the numbers."""
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_ledger_apply as tla
from rapid_reports_ai import template_line_registry as tlr
from rapid_reports_ai import template_sheet_grammar as tsg
from tests.template_line_fixtures import REBUILD_A, REBUILD_B, SAME


def _st(sheet):
    res = tsg.parse_sheet(sheet)
    assert not res.errors and res.structure.usable, res.errors
    return res.structure


def _labels(st):
    """parse ref -> a stable label: the raw line for a line unit, "Paragraph: <name>" or "SECTION <NAME>"."""
    out = {}
    for u in tlr.units(st):
        out[u.ref] = u.raw.strip() if u.raw else (f"Paragraph: {u.text}" if u.kind == "paragraph" else f"SECTION {u.text}")
    return out


def _ledger(st, registry):
    led = []
    for kind, key, choice in [
            ("normal", td.normal_key("Liver", "liver"), {"text": "The liver is normal in size and attenuation."}),
            ("normal", td.negative_key("Liver", "No focal liver lesion."), {"text": "No focal liver lesion."}),
            ("normal", td.negative_key("Chest base", "No pleural effusion."), {"text": "No pleural effusion."}),
            ("fixed", "No previous imaging is available.", {"keep": "always"}),
            ("fixed", "Axial images were acquired after contrast.", {"keep": "always"})]:
        led, _ = td.set_decision(led, kind, key, choice, source="creation", at="t")
    return tla.stamp_uids(led, st, registry)


def test_a_rebuild_makes_no_wrong_match():
    sa, sb = _st(REBUILD_A), _st(REBUILD_B)
    reg_a, _ = tlr.rebind(None, sa, now="T")
    reg_b, report = tlr.rebind(reg_a, sb, now="T")
    a_label = {uid: _labels(sa)[ref] for ref, uid in tlr.uids_for(sa, reg_a).items()}
    b_label = {uid: _labels(sb)[ref] for ref, uid in tlr.uids_for(sb, reg_b).items()}
    same = {(a, b) for a, b in SAME} | {(f"SECTION {n}", f"SECTION {n}") for n in ("TECHNIQUE", "FINDINGS", "IMPRESSION")}
    kept = {uid for uid in a_label if uid in b_label}
    wrong = sorted((a_label[u], b_label[u]) for u in kept if (a_label[u], b_label[u]) not in same)
    missed = sorted(p for p in same if p not in {(a_label[u], b_label[u]) for u in kept})
    print(f"\nrebuild: {tlr.summary(report)} kept={len(kept)} wrong={len(wrong)} missed={missed}")
    assert wrong == []


def test_the_rebuild_resolution_share_is_reported():
    sa = _st(REBUILD_A)
    reg_a, _ = tlr.rebind(None, sa, now="T")
    share = tla.uid_share(_ledger(sa, reg_a), REBUILD_B, reg_a)
    print(f"\nrebuild resolution: {share}")
    assert share["line_bound"] == 5
```

- [ ] **Step 2: Run the tests**

Run: `PYTEST tests/test_template_line_rebuild.py -s`
Expected: `2 passed`, printing `rebuild: exact=12 carried=0 revived=0 new=8 gone=7 ambiguous=0 kept=12 wrong=0 missed=[]` and `rebuild resolution: {'line_bound': 5, 'by_uid': 0, 'by_text': 1}`. (Re-verified after decision 7 against the fixture in a scratch copy: the two entries uid resolution carried before were the full-stop and "There is" rewordings, now new slots by design. If they differ, investigate before going on: `wrong` must stay 0.)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/template_line_fixtures.py backend/tests/test_template_line_rebuild.py
git commit -m "test(line-ids): rebuild fixture — zero wrong matches; uid vs text resolution reported

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 21: Final verification

- [ ] **Step 1: Full suite**

Run: `PYTEST tests` (about 3.5 minutes).
Expected: everything passes except the one pre-existing failure (spec gap 15): `tests/test_provider_key_routing.py::test_every_provider_client_carries_its_key_explicitly[claude-sonnet-5-5-anthropic-key]`. Any other failure is ours. Fix it and re-run.

- [ ] **Step 2: Check the working tree**

Run: `git status --short` (from the worktree root).
Expected: clean. No report or production data anywhere under the repo.

- [ ] **Step 3: Hand over**

Report to Hassan: the commits, the spec gaps above (1 and 2 need his eye), and the rebuild metric line from Task 19. No push, no merge.

---

## Deferred to slice 4

Moved out of this plan on 2026-10-15 (spec decision 8: writer uncertainty belongs with uncertainty scoring in slice 4). Their full text, tests and code are in this file at commit `f14b85a2` (`git show f14b85a2:docs/superpowers/plans/2026-10-15-stable-line-ids.md`); task numbers are not reused.

- **Task 15: the writer names a line for each uncertainty.** Re-enable `questions` as `{line, why}` in the writer's JSON, drop the "## Open Questions" prose, keep only well-formed items (`template_sheet_lab_prompts.py`, `template_writer.py`; three writer-prompt test assertions move to the new format).
- **Task 16: uncertain lines resolved at Create.** `tlr.resolve_uncertain` (each `line` to exactly one unit, then its uid), `persist_sheet(questions=)`, `questions` on `TemplateCreate` / `SkillSheetSaveRequest`, stored as `template_config["uncertain"]`. In slice 4 the resolution must follow decision 7 (exact after `rep_key`, not `norm_key`).
- **Task 20: writer check** (question count and resolve rate before and after, live model run). It measures Tasks 15 and 16, so it moves with them.

This slice keeps only `uncertain` as a reserved server-written key in `_carry_structure` and the upgrade script (Tasks 11 and 12), so slice 4 needs no migration.

---

## Self-review (done while writing)

**Spec coverage**

| Spec item | Task |
| --- | --- |
| Registry, uid format, `text_hash`, status live/gone, `minted` once | 2, 3 |
| Identity per kind (section, paragraph incl. rename, normal, negative, fixed, rule) | 2, 3 |
| No similarity threshold; exact matching after lookalikes and whitespace only (decision 7); adversarial pairs kept as a tripwire; lookalike collision test | 1, 3 |
| A normal follows a renamed paragraph only with exactly equal text (decision 5) | 3, 6 |
| A renamed group's confirm is stale (`group_name`); any unit's `text_hash` change (a normal reworded in place included) makes it stale (decision 5) | 13 |
| Rebind: carried first, exact (paragraph COVERS rename reported as exact), revival on exact only, 1:1, ambiguous, deterministic, report | 3 |
| `uids_for` pure, read time, never stored on `sheet_structure` | 4 |
| Persisting vs stateless paths; no minting on stateless; unknown client uid treated as none | 6 (`_by_uid` ignores unknown), 8 (`stamp_uids` drops it), 11 (routes) |
| `persist_sheet` owns the persisted save; `_vet_config` and the upgrade script call it | 10, 11, 12 |
| `vet_sheet` / `apply_ledger` `registry=None` exactly as today | 6 (`test_registry_none_is_todays_key_matching`), existing suites unchanged |
| `carried` for every rewrite incl. `_normal` retargets and composed edits | 6 |
| Stamp uids after the rebind | 8, 10 |
| `_carry_structure` server-written keys | 11 |
| `clean_ledger` keeps `uid` | 5 |
| Uid first, key second, unmatched as today | 6 |
| Removal decisions satisfied | 7 (registry path; gap 2) |
| Normal binds to slot, survives writer rewording | 3, 6 |
| `reconcile_chat` clears, stamp restores | 5, 8 |
| Key updated to new label when uid kept, logged | 6 (`_by_uid`) |
| `ledger_drift` stays logged; rebind report logged beside it | 10 |
| Confirm record: endpoint, `{group, sheet_rev, sheet_hash}` only, 409, server-side units, session user, 404 | 14 |
| Groups (findings paragraphs, section-level, other sections, chunks of 8), attestable predicate, valid/stale/missing | 13 |
| `sheet_rev` from stored value, pair with `sheet_hash`, survives cleanup | 10, 17 |
| Writer uncertainty and its check | deferred to slice 4 (decision 8) |
| Backfill dry-run/apply | 18 (dropped 2026-10-15) |
| Metrics per save and per rebuild | 10 (`uid_share` on rebuild), 19 |
| Rebuild fixture: wrong matches 0, resolved share | 19 |
| Restore against the current registry | 11 |
| `copy_template_to_user.py` copies registry and ledger verbatim | no change (it copies `template_config` whole; stated) |

**Placeholder scan:** no "TBD"/"TODO"/"similar to". Two placeholders are deliberate: `<ROOT given by Hassan>` (private data path) and `<session>` (scratchpad path at run time).

**Type consistency:** `tlr.rebind(registry, st, carried, *, now)` returns `(reg, report)`; `tlr.match`/`uids_for(st, registry)` return `{ref: uid}`; `tla.apply_ledger(sheet, ledger, before, registry)` returns `LedgerResult` with `.ledger/.carried/.satisfied/.rekeyed`; `tla.stamp_uids(ledger, st, registry)`; `tla.locate(entry, st)`; `tla.uid_share(ledger, sheet, registry)`; `S.vet_sheet(..., registry=)` returns `VetOutcome.carried`; `S.persist_sheet(config, stored_config, origin, *, ledger, now)` returns `Persisted(outcome, config, report)` (`questions` comes with slice 4); `S.SERVER_WRITTEN`, `S.stored_rev`; `tnc.groups(st, sheet, registry)`, `tnc.record(group, registry, *, sheet_rev, sheet_hash, user_id, now)`, `tnc.confirm_state(group, rec, registry)`. All of these were checked against a scratch prototype run on a copy of this branch's code and tests.

**Risky tasks**
- **Task 6** (apply_ledger threading) touches the most code paths. The 4- or 5-value op return and the `is` identity in `_by_uid` are the subtle parts. The existing 49 ledger tests are the guard.
- **Task 11** replaces the core of `_vet_config`. The unchanged-status branch now relies on `persist_sheet` omitting `coverage_sections`.
- **Spec gap 1** (`match` vs `uids_for`) is a behavioural choice Hassan should confirm.
