# Template Pipeline for the Scratchpad (Project 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every step of a template's life produce, keep and use a grammar sheet, so the scratchpad is the way
templates are reported; fix the scratchpad bugs the conversion lab found; capture the evidence the later learning
loop needs; ship with the 31 converted templates and a banner.

**Architecture:** Four reused building blocks — one writer (grammar analyser), one server save function
(`template_sheet_save.py`, every sheet write), one preview function (`template_preview.py`, the lab harness as a
server function), one evidence record (examples, chat turns, generation stamps, gate fields, fixed edit capture).
Runtime fixes land first (phase A) because the lab cases are re-run against them. Spec:
`docs/superpowers/specs/2026-10-12-template-pipeline-design.md`.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend, Python 3.12, pytest with `asyncio_mode=auto`), SvelteKit
(Svelte 4 components + Svelte 5 layout, Vitest browser tests via bun), Jev (`jev_client.jev_post`, noul questions),
Qwen via `_run_agent_with_model`.

**Conventions for every task**
- Worktree: `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack`, branch `feat/template-stack`.
  `B` = `backend/src/rapid_reports_ai`, `T` = `backend/tests`, `F` = `frontend/src`.
- Backend tests: `cd backend && .venv/bin/pytest <file> -q` (full suite: `.venv/bin/pytest -q`).
- Frontend tests: `cd frontend && bunx vitest --run <file>`; type check `bun run check`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- Production data (lab inputs, converted sheets) stays in the session scratchpad
  `SP=/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/0777b95c-b0c3-44a8-a16e-4ace56e641f1/scratchpad/convlab`
  (or the private folder Hassan names in Task F1). Never copy it into the repo.
- Keep tool output small (grep/head/tail).

---

## File structure

| File | Responsibility | Phase |
|---|---|---|
| `B/hybrid_stack/template.py` (modify) | region normals carry their structure; context suppressions per sheet | A |
| `B/hybrid_stack/normals.py` (modify) | context suppressions applied; global-normal dictation; dropped normals with reason | A, D |
| `B/hybrid_stack/jev_stack.py` (modify) | `GLOBAL_NORMAL_QUESTION`, `ask_global_normal` | A |
| `B/hybrid_stack/routes.py` (modify) | cap 16; `/assumed` takes `template_id` + `clinical_history`; `/log` stamps | A, D |
| `B/template_stack.py` (modify) | session rules: FIXED lines, examples are wording only | A |
| `B/global_style_guide.py` (modify) | `_STACK`: TERM applies to sheet wording only; header truth | A |
| `B/template_sheet_save.py` (create) | the one save function: vet, repair, drop/refuse, coverage | B |
| `B/template_sheet_checks.py` (create) | save-time unit checks (code + Jev) | B |
| `B/main.py` (modify) | create/update/save/restore/analyze/refine call the save function; coverage endpoint removed | B, C |
| `B/template_manager.py` (modify) | refine writes the grammar; grammar analyser | C |
| `B/template_writer.py` (create) | grammar analyser call + `ANALYSER_VERSION` | C |
| `B/template_preview.py` (create) | `preview_report` + `findings_block` | C |
| `backend/migrations/versions/20261013090000_template_evidence.py` (create) | examples, chat turns, report stamp, stack log template/stamp | D |
| `B/database/models.py`, `B/database/crud.py` (modify) | new tables/columns, crud helpers | D |
| `B/template_examples.py` (create) | de-identification + storage of pasted examples | D |
| `B/quality_scoring.py` (modify) | judge against the stamped sheet; template final from report versions; path | D |
| `B/template_lean.py` (modify) | no options job on the stack path; sections/terms from structure | E |
| `F/lib/hybrid-stack/api.ts`, `types.ts` (modify) | assumed request/response, gate fields, log template_id | A, D |
| `F/lib/components/DictationScratchpad.svelte` (modify) | sends template/history to `/assumed`; gate offered/dropped | A, D |
| `F/routes/components/TemplateForm.svelte` (modify) | copy capture scoped to the report; no `/prepare` in scratchpad | D, E |
| `F/routes/components/TemplateRefinePanel.svelte` (modify) | no coverage call; template_id on refine; refusal message | B, C |
| `F/routes/components/SkillSheetCreator.svelte` (modify) | examples + chat turns on save; notice; preview on demand | C, D |
| `F/lib/components/UpgradeBanner.svelte` (create), `F/routes/+layout.svelte` (modify) | the banner | F |
| `B/scripts/template_upgrade_apply.py` (create) | the one-off production write (from `SP/apply_prod.py`) | F |

---

# Phase A — Scratchpad runtime fixes (from the conversion lab)

### Task A1: Raise the per-region normals cap and name subject-less normals

**Files:**
- Modify: `B/hybrid_stack/routes.py:246`
- Modify: `B/hybrid_stack/template.py:47-70`
- Test: `T/test_hybrid_stack_slim_sheet.py`, `T/test_hybrid_stack_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `T/test_hybrid_stack_slim_sheet.py`:

```python
from rapid_reports_ai.template_sheet_grammar import parse_sheet
from rapid_reports_ai.hybrid_stack.template import template_region_normals

_SUBJECTLESS = """## Report Structure
SECTION FINDINGS role: findings

## Paragraph: Liver (FINDINGS)
COVERS ["liver"]
Opening: "The liver is normal."
NORMAL [liver] "Unremarkable."
NORMAL [spleen] "The spleen is normal in size."
"""


def test_a_normal_without_its_structure_is_named_by_its_label():
    st = parse_sheet(_SUBJECTLESS, mode="template").structure
    assert st.usable
    assert template_region_normals(st)["Liver"] == ["Liver: unremarkable.", "The spleen is normal in size."]
```

Append to `T/test_hybrid_stack_routes.py`:

```python
def test_assumed_checks_up_to_sixteen_normals_per_region(client, auth_headers, monkeypatch):
    seen = {}

    async def fake_assumed(dictation, normals, *a, **k):
        seen.update(normals)
        from rapid_reports_ai.hybrid_stack.normals import AssumedResult
        return AssumedResult(assumed={r: [] for r in normals})

    monkeypatch.setattr("rapid_reports_ai.hybrid_stack.routes.assumed_normals", fake_assumed)
    sentences = [f"Normal {i}." for i in range(20)]
    r = client.post("/api/hybrid-stack/assumed", headers=auth_headers,
                    json={"dictation": "x", "region_normals": {"A": sentences}})
    assert r.status_code == 200
    assert len(seen["A"]) == 16
```

(If the router prefix differs, read it from `B/hybrid_stack/routes.py` `APIRouter(prefix=...)` and use it; the
existing `test_items_assumed_and_draft_routes` shows the path in use.)

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && .venv/bin/pytest T/test_hybrid_stack_slim_sheet.py T/test_hybrid_stack_routes.py -q -k "label or sixteen"`
Expected: 2 failed (`['Unremarkable.', …]` != expected; `8 == 16`).

- [ ] **Step 3: Implement**

`B/hybrid_stack/routes.py:246`:

```python
    normals = {r: s[:MAX_NORMALS_PER_REGION] for r, s in list(req.region_normals.items())[:40]}
```

and near the other constants at the top of the file:

```python
MAX_NORMALS_PER_REGION = 16   # conversion lab 2026-10-12: 8 silently cut mandatory negatives in long paragraphs
```

`B/hybrid_stack/template.py`, inside `template_region_normals`, replace the two `texts` lines with:

```python
        texts = [_named(n.text, n.structure) for n in st.normals if n.paragraph == p.id]
        texts += [n.text for n in st.negatives if n.paragraph == p.id and n.condition is None]
```

and add above the function:

```python
_WORD = re.compile(r"[a-z]+")


def _named(text: str, structure: str) -> str:
    """A Normal whose own text does not name its structure ("Unremarkable." under NORMAL [liver]) is offered as
    "Liver: unremarkable.", so the check and the writer know what it is about (conversion lab 2026-10-12: Jev never
    kept a subject-less normal)."""
    words = set(_WORD.findall(text.lower()))
    label = (structure or "").strip()
    if not label or words & set(_WORD.findall(label.lower())):
        return text
    body = text.strip()
    return f"{label[:1].upper()}{label[1:]}: {body[:1].lower()}{body[1:]}"
```

(add `import re` at the top of `template.py` if absent).

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest T/test_hybrid_stack_slim_sheet.py T/test_hybrid_stack_routes.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/routes.py backend/src/rapid_reports_ai/hybrid_stack/template.py backend/tests/test_hybrid_stack_slim_sheet.py backend/tests/test_hybrid_stack_routes.py
git commit -m "fix(stack): 16 normals per region; subject-less normals named by their label

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A2: Template context rules stop assumed normals

A context RULE (`RULE WHEN [context: no prior study] SUPPRESS "No other interval changes…"`, or REPLACE) names its
target by quoted text. When its condition is met for this case, the targeted normal is not assumed.

**Files:**
- Modify: `B/hybrid_stack/template.py` (new `template_suppressions`)
- Modify: `B/hybrid_stack/normals.py` (`assumed` gains `suppressions`, `context`)
- Modify: `B/hybrid_stack/routes.py` (`AssumedRequest` gains `template_id`, `clinical_history`)
- Modify: `F/lib/hybrid-stack/api.ts:35-37`, `F/lib/components/DictationScratchpad.svelte:1812-1814`
- Test: `T/test_hybrid_stack_normals.py`, `T/test_hybrid_stack_slim_sheet.py`

- [ ] **Step 1: Write the failing tests**

Append to `T/test_hybrid_stack_slim_sheet.py`:

```python
from rapid_reports_ai.hybrid_stack.template import template_suppressions

_RULED = """## Report Structure
SECTION FINDINGS role: findings

## Paragraph: Brain (FINDINGS)
COVERS ["brain"]
NEGATIVE "No other interval changes compared with the previous MRI."
NORMAL [ventricles] "The ventricles are normal in size."
RULE WHEN [context: no previous study is available] SUPPRESS "No other interval changes compared with the previous MRI."
"""


def test_context_suppressions_name_the_normal_they_hide():
    st = parse_sheet(_RULED, mode="template").structure
    assert st.usable
    assert template_suppressions(st) == [
        ("no previous study is available", "No other interval changes compared with the previous MRI.")]
```

Append to `T/test_hybrid_stack_normals.py`:

```python
from rapid_reports_ai.hybrid_stack import normals as N
from rapid_reports_ai.hybrid_stack.jev_stack import RowCheck


async def test_a_met_context_condition_drops_its_target(monkeypatch):
    async def rows(dictation, sentences, removed, transport=None):
        return [RowCheck(0.0, 0.0, 0.0) for _ in sentences]

    async def conds(state, conditions):
        assert "No previous MRI." in state and "Headache." in state
        return [0.9 for _ in conditions]

    monkeypatch.setattr(N, "ask_rows", rows)
    monkeypatch.setattr(N, "ask_conditions", conds)
    monkeypatch.setattr(N, "ask_global_normal", lambda d: _zero())
    out = await N.assumed(
        "No previous MRI.", {"Brain": ["No other interval changes compared with the previous MRI.",
                                       "The ventricles are normal in size."]}, [], [], [],
        suppressions=[("no previous study is available",
                       "No other interval changes compared with the previous MRI.")],
        clinical_history="Headache.")
    assert out.assumed == {"Brain": ["The ventricles are normal in size."]}
    assert out.dropped["Brain"] == [{"sentence": "No other interval changes compared with the previous MRI.",
                                     "reason": "rule"}]


async def _zero():
    return 0.0
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && .venv/bin/pytest T/test_hybrid_stack_slim_sheet.py T/test_hybrid_stack_normals.py -q -k "suppress or context"`
Expected: ImportError / TypeError (`template_suppressions`, `suppressions` unknown).

- [ ] **Step 3: Implement**

`B/hybrid_stack/template.py` — add:

```python
def template_suppressions(st: SheetStructure) -> list[tuple[str, str]]:
    """(condition, sentence) for each context RULE that suppresses or replaces a sentence the scratchpad would
    assume: when the condition is met for the case, that sentence is not assumed (conversion lab 2026-10-12: a
    "no prior study" rule did not stop "compared with the previous MRI")."""
    offered = {" ".join(s.lower().split()).rstrip(".") for ss in template_region_normals(st).values() for s in ss}
    out: list[tuple[str, str]] = []
    for r in st.rules:
        if r.condition_source != "context" or r.effect not in ("suppress", "replace") or not r.target:
            continue
        key = " ".join(r.target.lower().split()).rstrip(".")
        if key in offered:
            t = " ".join(r.target.split()).strip()
            out.append((r.condition, t if t.endswith(".") else t + "."))
    return out
```

`B/hybrid_stack/jev_stack.py` — add (beside `ask_rows`):

```python
CONDITION_MIN = 0.6   # template_brief's context-condition question; met = stated for this case


async def ask_conditions(state: str, conditions: list[str], transport=None) -> list[float]:
    """Is each context condition stated for this case (history, technique or dictation)? One Jev call; the
    question is template_brief.q_condition (Jev wording suite 2026-10-01)."""
    if not conditions:
        return []
    from ..template_brief import q_condition
    qs = {f"cond_{i}": q_condition(c) for i, c in enumerate(conditions)}
    r = await jev_post({"model": JEV_MODEL, "state": state, "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    return [float((ans.get(f"cond_{i}") or {}).get("noul") or 0.0) for i in range(len(conditions))]
```

`B/hybrid_stack/normals.py` — change the result model and `assumed`:

```python
from .jev_stack import CONDITION_MIN, ask_conditions, ask_global_normal, ask_rows, normal_assumed, GLOBAL_NORMAL_MIN


class AssumedResult(BaseModel):
    assumed: dict[str, list[str]]
    dropped: dict[str, list[dict]] = {}   # region -> [{sentence, reason: covered|hedged|contradicted|removed|rule}]
    ms: int = 0
    error: str | None = None


def _reason(c) -> str:
    from .jev_stack import HEDGED_MIN, REMOVED_MIN, STATED_MIN
    if c.removed >= REMOVED_MIN:
        return "removed"
    if c.contra >= HEDGED_MIN:
        return "contradicted"
    return "covered" if c.stated >= STATED_MIN else "hedged"


async def assumed(dictation: str, region_normals: dict[str, list[str]], abnormal: list[str],
                  dictated_normal: list[str], removed: list[str], owned: list[str] | None = None,
                  touched: list[str] | None = None, suppressions: list[tuple[str, str]] | None = None,
                  clinical_history: str = "") -> AssumedResult:
    t0 = time.perf_counter()
    gone = list(dict.fromkeys(r for r in [*removed, *(owned or [])] if r.strip()))
    said = set(dictated_normal)
    asked = [(region, s) for region, sentences in region_normals.items() if region not in said for s in sentences]
    out: dict[str, list[str]] = {r: [] for r in region_normals}
    dropped: dict[str, list[dict]] = {r: [] for r in region_normals}
    error = None
    if asked:
        try:
            conds = list(dict.fromkeys(c for c, _ in suppressions or []))
            ctx = f"CLINICAL HISTORY:\n{clinical_history or '(not given)'}\nDICTATION:\n{dictation}"
            checks, met, global_normal = await asyncio.gather(
                _ask(dictation, [s for _, s in asked], gone), ask_conditions(ctx, conds), ask_global_normal(dictation))
            hidden = {_norm(s) for c, s in suppressions or [] if met[conds.index(c)] >= CONDITION_MIN}
            for (region, s), c in zip(asked, checks):
                if _norm(s) in hidden:
                    dropped[region].append({"sentence": s, "reason": "rule"})
                elif normal_assumed(c) or (global_normal >= GLOBAL_NORMAL_MIN and _covered_only(c)):
                    out[region].append(s)
                else:
                    dropped[region].append({"sentence": s, "reason": _reason(c)})
        except Exception as e:
            logger.warning("[stack.normals] %s: %s", type(e).__name__, str(e)[:200])
            error = f"{type(e).__name__}: {e}"
            out = {r: [] for r in region_normals}
            dropped = {r: [] for r in region_normals}
    return AssumedResult(assumed=out, dropped=dropped, ms=int((time.perf_counter() - t0) * 1000), error=error)


def _covered_only(c) -> bool:
    """A global "normal" dictation covers every normal; it neither contradicts nor removes one (Task A3)."""
    from .jev_stack import HEDGED_MIN, REMOVED_MIN
    return c.contra < HEDGED_MIN and c.removed < REMOVED_MIN
```

(`ask_global_normal`/`GLOBAL_NORMAL_MIN` are added in Task A3; land A2 and A3 in one commit, or stub them as
`async def ask_global_normal(d): return 0.0` / `GLOBAL_NORMAL_MIN = 1.1` here and replace in A3.)

`B/hybrid_stack/routes.py` — `AssumedRequest` gains:

```python
    template_id: str | None = None
    clinical_history: str = ""
```

and `stack_assumed` becomes:

```python
@router.post("/assumed", response_model=AssumedResult)
async def stack_assumed(req: AssumedRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require()
    normals = {r: s[:MAX_NORMALS_PER_REGION] for r, s in list(req.region_normals.items())[:40]}
    owned = list(dict.fromkeys(o for o in req.owned if o.strip()))[:100]   # the client sends current rows first
    suppressions: list[tuple[str, str]] = []
    if req.template_id:
        t = get_template(db, req.template_id, str(user.id))
        st = template_structure(t.template_config) if t is not None else None
        suppressions = template_suppressions(st) if st is not None else []
    return await assumed_normals(req.dictation, normals, req.abnormal, req.dictated_normal, req.removed[:50],
                                 owned, req.touched[:40], suppressions=suppressions,
                                 clinical_history=req.clinical_history[:2000])
```

(import `template_suppressions` beside `template_region_normals`).

`F/lib/hybrid-stack/api.ts` — `postAssumed` body type gains `template_id?: string | null; clinical_history?: string;`
and `AssumedResult` (in `types.ts` or `items.ts`, wherever it is declared — `grep -n "AssumedResult" F/lib/hybrid-stack/*.ts`)
gains `dropped?: Record<string, { sentence: string; reason: string }[]>;`.

`F/lib/components/DictationScratchpad.svelte:1812-1814` — add to the `postAssumed` body:

```ts
				template_id: stackTemplateId, clinical_history: clinicalHistory,
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest T/test_hybrid_stack_slim_sheet.py T/test_hybrid_stack_normals.py T/test_hybrid_stack_routes.py -q`
Expected: all pass (existing normals tests still pass: `dropped` defaults to `{}` and old call sites pass no
suppressions). Then `cd frontend && bun run check 2>&1 | tail -3` → no new errors.

- [ ] **Step 5: Commit** (with A3 if stubbed)

```bash
git add backend/src/rapid_reports_ai/hybrid_stack backend/tests/test_hybrid_stack_slim_sheet.py backend/tests/test_hybrid_stack_normals.py frontend/src/lib/hybrid-stack/api.ts frontend/src/lib/components/DictationScratchpad.svelte
git commit -m "fix(stack): template context rules stop the normals they suppress; dropped normals with reason

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A3: A bare "normal" dictation keeps the template's normals

**Files:**
- Modify: `B/hybrid_stack/jev_stack.py`
- Test: `T/test_hybrid_stack_jev_stack.py`, `T/test_hybrid_stack_normals.py`
- Lab: `SP/global_normal_lab.py` (scratchpad, not committed)

- [ ] **Step 1: Wording lab (validate the Jev question before wiring)**

Write `SP/global_normal_lab.py`:

```python
"""Jev wording lab: does the DICTATION say the whole study is normal without naming structures?"""
import asyncio, os
from dotenv import load_dotenv
load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")
from rapid_reports_ai.hybrid_stack.jev_stack import ask_global_normal

YES = ["normal", "Normal study.", "No abnormality detected.", "normal scan", "Unremarkable examination.",
       "No acute abnormality. Normal study.", "Normal CT.", "Nothing abnormal seen.", "NAD", "normal appearances"]
NO = ["Liver normal.", "Normal liver and spleen. 9 mm adrenal nodule.", "No fracture.", "Appendix dilated 11 mm.",
      "Normal except for a small effusion.", "Kidneys unremarkable.", "No pneumothorax. Normal heart size.",
      "Normal brain. Sinus mucosal thickening.", "Lungs clear.", "No acute intracranial abnormality."]

async def main():
    ys = [await ask_global_normal(d) for d in YES]
    ns = [await ask_global_normal(d) for d in NO]
    print("YES", [round(x, 2) for x in ys]); print("NO ", [round(x, 2) for x in ns])
asyncio.run(main())
```

Run: `cd backend && PYTHONPATH=src .venv/bin/python $SP/global_normal_lab.py 2>&1 | grep -v "^🔧\|└─" | tail -2`
Expected: a threshold separating all YES from all NO. Set `GLOBAL_NORMAL_MIN` to the midpoint of the gap. If no
clean gap, change the wording (one retry) and record the result in the commit message; if still no gap, stop and
report to Hassan.

- [ ] **Step 2: Write the failing test**

Append to `T/test_hybrid_stack_normals.py`:

```python
async def test_a_global_normal_dictation_keeps_covered_normals(monkeypatch):
    async def rows(dictation, sentences, removed, transport=None):
        return [RowCheck(0.9, 0.0, 0.0) for _ in sentences]   # "normal" covers each

    async def gn(d):
        return 0.95

    monkeypatch.setattr(N, "ask_rows", rows)
    monkeypatch.setattr(N, "ask_global_normal", gn)
    out = await N.assumed("normal", {"Spine": ["No fracture.", "Normal alignment."]}, [], [], [])
    assert out.assumed == {"Spine": ["No fracture.", "Normal alignment."]}
```

- [ ] **Step 3: Implement** in `B/hybrid_stack/jev_stack.py`:

```python
GLOBAL_NORMAL_MIN = 0.5   # set from SP/global_normal_lab.py (Task A3 step 1)
GLOBAL_NORMAL_QUESTION = (
    "The DICTATION says the whole study is normal (or shows no abnormality) without naming any particular "
    "structure, finding or exception.")


async def ask_global_normal(dictation: str, transport=None) -> float:
    """A bare global normal ("normal", "No abnormality detected"): the template's normals stay assumed instead of
    being dropped as covered (conversion lab 2026-10-12: polytrauma kept 8 of 16)."""
    if not dictation.strip() or len(dictation) > 300:
        return 0.0
    return await _noul(f"DICTATION:\n{dictation}", GLOBAL_NORMAL_QUESTION, transport)
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest T/test_hybrid_stack_normals.py T/test_hybrid_stack_jev_stack.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/jev_stack.py backend/tests/test_hybrid_stack_normals.py
git commit -m "fix(stack): a bare global-normal dictation keeps the template's normals (Jev lab: <result>)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A4: Writer rules — FIXED lines, examples are wording only, TERM on sheet wording only

**Files:**
- Modify: `B/template_stack.py:62-76` (session rules)
- Modify: `B/global_style_guide.py:432-438` (header), the `GLOBAL_STYLE_GUIDE_STACK` swaps (`:440`)
- Test: `T/test_template_stack.py`

- [ ] **Step 1: Write the failing tests**

Append to `T/test_template_stack.py`:

```python
from rapid_reports_ai.global_style_guide import GLOBAL_STYLE_GUIDE_STACK, TEMPLATE_SHEET_HEADER_STACK


def test_session_rules_cover_fixed_lines_and_examples():
    b = stack_brief("", "C.", [])
    assert "FIXED line" in b and "written as it stands" in b
    assert "examples of the radiologist's wording" in b


def test_stack_terminology_applies_only_to_sheet_wording():
    assert "a term in the FINDINGS input is kept as the radiologist said it" in GLOBAL_STYLE_GUIDE_STACK
    assert "suppression rules" not in TEMPLATE_SHEET_HEADER_STACK.split("were taken out")[0]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && .venv/bin/pytest T/test_template_stack.py -q -k "fixed or terminology"` → 2 failed.

- [ ] **Step 3: Implement**

`B/template_stack.py` — inside the Scratchpad Session `parts.append(...)`, after the Required statements bullet add:

```python
        "\n- **Fixed lines:** a FIXED line is the template's fixed wording (what was performed, standard text): it is "
        "written as it stands in its place, unless a RULE whose condition the input meets suppresses or replaces it. "
        "A FIXED line with a {slot} is written only when the input gives that value; otherwise it is left out.\n"
        "- **Examples are wording only:** quoted Opening, Order, Abnormal pattern and Measurement lines are examples "
        "of the radiologist's wording. Copy their phrasing for what the input states; never their content: no finding, "
        "value, grade, code, time window or interpretation from an example appears unless the input states it."
```

`B/global_style_guide.py` — header (`:432-438`) becomes:

```python
TEMPLATE_SHEET_HEADER_STACK = """## TEMPLATE SKILL SHEET

The following skill sheet defines this radiologist's structure and style for this template. Its negatives, normal
statements, interpretive clauses and case deliberation were taken out: the radiologist confirmed every statement in
the FINDINGS input, and the conclusion, in the scratchpad before generation. Its context rules and fixed lines stay.
The skill sheet inherits the Global Style Guide; where they conflict, the skill sheet takes precedence, except over
its Scratchpad Session rules, which outrank both."""
```

and add one more pair to the `GLOBAL_STYLE_GUIDE_STACK = _swaps(GLOBAL_STYLE_GUIDE, …)` call:

```python
    ("Apply preferred/suppressed term pairs from the skill sheet across ALL sections\nincluding the impression. "
     "If a term is suppressed, it must never appear anywhere.",
     "Apply preferred/suppressed term pairs from the skill sheet to the wording the skill sheet supplies; a term in "
     "the FINDINGS input is kept as the radiologist said it."),
```

(`_swap` raises if the old text is not found — run the test to confirm the exact source text matches; copy it from
`global_style_guide.py:115-116` if the line break differs.)

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest T/test_template_stack.py T/test_template_generate_endpoint.py -q` → pass.

- [ ] **Step 5: Re-run the affected lab cases** (two runs max, eval economy)

```bash
cd backend
for s in acute_stroke_protocol_mri ct_thorax_concise_telegraphic_zaman mri_arthrogram_shoulder_ma cardiac_mr_2 mri_brain_headache_evaluation; do
  echo -n "$s: "; PYTHONPATH=src .venv/bin/python $SP/e2e.py $SP/final/$s.e2e_case.json $SP/final/$s.e2e_a4.json 2>&1 | grep -a "^ok\|Error" | tail -1
done
```

Hand read each `report` field: no "4.5 hours"/ASPECTS codes (stroke), no "apicobasal gradient" unless dictated
(thorax), no undictated "No partial thickness tear" (shoulder), no undictated valve normal (cardiac), the Orbits
FIXED line printed (brain). Record PASS/ISSUES per case in the commit message.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/template_stack.py backend/src/rapid_reports_ai/global_style_guide.py backend/tests/test_template_stack.py
git commit -m "fix(template-stack): fixed lines kept, examples are wording only, TERM only on sheet wording

Lab re-run: <per-case verdicts>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A5: Fallback comparison — today's path on old vs converted sheets (lab, no code)

- [ ] **Step 1: Write `SP/fallback_compare.py`**

```python
"""Today's template path on the OLD free-form sheet vs the CONVERTED sheet, same dictation (31 cases)."""
import asyncio, json, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")
from rapid_reports_ai.template_manager import TemplateManager

SP = Path(sys.argv[1])
data = {t["slug"]: t for t in json.loads((SP / "data_all.json").read_text())["templates"]}

async def one(slug):
    c = json.loads((SP / "final" / f"{slug}.e2e_case.json").read_text())
    out = {}
    for arm, sheet in (("old", data[slug]["skill_sheet"]), ("new", (SP / "final" / f"{slug}.final.md").read_text())):
        cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": sheet, "scan_type": c["scan_type"]}
        r = await TemplateManager().generate_report_from_config(
            cfg, {"FINDINGS": c["dictation"], "CLINICAL_HISTORY": c.get("history", "")}, None)
        out[arm] = r["report_content"]
    (SP / "final" / f"{slug}.fallback.json").write_text(json.dumps(out, indent=1))
    print("ok", slug, flush=True)

async def main():
    for slug in sorted(data):
        try:
            await one(slug)
        except Exception as e:
            print("ERR", slug, type(e).__name__, str(e)[:120], flush=True)
asyncio.run(main())
```

- [ ] **Step 2: Run it** (background, sequential):
`cd backend && PYTHONPATH=src .venv/bin/python $SP/fallback_compare.py $SP 2>&1 | grep -a "^ok\|^ERR" | tail -35`

- [ ] **Step 3: Hand read** with an error tally per arm (as the 2026-10-01 4-arm retest): per case count invented
findings/normals, missing dictated findings, wrong side/number, hardened hedges, undictated recommendations, raw
placeholders. Dispatch 3 subagents (≈10 cases each) with these rules if the volume is too large; they write
`SP/final/<slug>.fallback_read.md`.

- [ ] **Step 4: Decide with Hassan.** If `new` errors ≤ `old` errors: no change. If worse: report the error classes
and stop for a decision (adapt the fallback, or rely on the scratchpad and log every fallback use). Write the tally
to `SP/final/FALLBACK.md`.

---

# Phase B — The one server save function

### Task B1: Save-time unit checks

**Files:**
- Create: `B/template_sheet_checks.py`
- Test: `T/test_template_sheet_checks.py`
- Lab: `SP/unit_check_lab.py`

- [ ] **Step 1: Write the failing test**

`T/test_template_sheet_checks.py`:

```python
import pytest
from rapid_reports_ai import template_sheet_checks as C
from rapid_reports_ai.template_sheet_grammar import parse_sheet

SHEET = """## Report Structure
SECTION FINDINGS role: findings

## Paragraph: Knee (FINDINGS)
COVERS ["menisci", "cartilage"]
NORMAL [menisci] "The menisci are intact."
NORMAL [cartilage] "Mild chondral irregularity and thinning."
NEGATIVE "No effusion, synovitis or loose body."
NORMAL [ligaments] "LVEF {value}%."
"""


async def test_checks_flag_placeholders_abnormal_and_multi_structure(monkeypatch):
    async def fake(units):
        return {u.text: (0.1 if "Mild" in u.text else 0.95, 0.9 if "effusion" in u.text else 0.1) for u in units}

    monkeypatch.setattr(C, "_jev_scores", fake)
    st = parse_sheet(SHEET, mode="template").structure
    fails = await C.check_units(st)
    by = {f.text: f.reason for f in fails}
    assert by["LVEF {value}%."] == C.PLACEHOLDER
    assert by["Mild chondral irregularity and thinning."] == C.NOT_NORMAL
    assert by["No effusion, synovitis or loose body."] == C.MULTI_STRUCTURE
    assert "The menisci are intact." not in by
```

- [ ] **Step 2: Run** `cd backend && .venv/bin/pytest T/test_template_sheet_checks.py -q` → ImportError.

- [ ] **Step 3: Implement** `B/template_sheet_checks.py`:

```python
"""Save-time checks on a grammar sheet's NORMAL / NEGATIVE units (template pipeline spec, block 2). Code checks
placeholders; one Jev call asks, per unit, whether it states something normal or absent and whether it covers more
than one structure. The saving code repairs or drops what fails."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .jev_client import JEV_MODEL, jev_post
from .template_sheet_structure import SheetStructure

PLACEHOLDER = "placeholder in a normal"
NOT_NORMAL = "states an abnormality as a normal"
MULTI_STRUCTURE = "normal covers more than one structure"

NORMAL_MIN = 0.5          # set from SP/unit_check_lab.py (Task B1 step 5)
MULTI_MIN = 0.6           # set from SP/unit_check_lab.py
TIMEOUT_S = 6.0
_SLOT = re.compile(r"\{[^}]*\}")

Q_NORMAL = ("The SENTENCE states that a structure is normal, or that a finding is absent, with no abnormality, "
            "measurement or grade of disease: {s}")
Q_MULTI = ("The SENTENCE makes a normal or negative statement about more than one distinct anatomical structure, "
           "so one of them could be abnormal while the others are normal: {s}")


@dataclass(frozen=True)
class UnitFailure:
    line: int
    text: str
    reason: str


def _units(st: SheetStructure):
    return [*st.normals, *st.negatives]


async def _jev_scores(units) -> Dict[str, Tuple[float, float]]:
    qs = {}
    for i, u in enumerate(units):
        qs[f"n{i}"] = {"type": "noul", "instructions": Q_NORMAL.format(s=u.text)}
        qs[f"m{i}"] = {"type": "noul", "instructions": Q_MULTI.format(s=u.text)}
    r = await jev_post({"model": JEV_MODEL, "state": "Statements from a radiology report template.", "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    s = lambda k: float((ans.get(k) or {}).get("noul") or 0.0)
    return {u.text: (s(f"n{i}"), s(f"m{i}")) for i, u in enumerate(units)}


def _line(u) -> int:
    return int(getattr(u, "source_line", 0) or (getattr(u, "source_lines", None) or [0])[0] or 0)


async def check_units(st: SheetStructure) -> List[UnitFailure]:
    """Failures for the sheet's NORMAL / NEGATIVE units. Raises on a Jev error (the caller refuses the write)."""
    units = _units(st)
    fails = [UnitFailure(_line(u), u.text, PLACEHOLDER) for u in units if _SLOT.search(u.text)]
    rest = [u for u in units if not _SLOT.search(u.text)]
    if not rest:
        return fails
    scores = await _jev_scores(rest)
    for u in rest:
        normal, multi = scores.get(u.text, (1.0, 0.0))
        if normal < NORMAL_MIN:
            fails.append(UnitFailure(_line(u), u.text, NOT_NORMAL))
        elif multi >= MULTI_MIN:
            fails.append(UnitFailure(_line(u), u.text, MULTI_STRUCTURE))
    return fails
```

- [ ] **Step 4: Run** `cd backend && .venv/bin/pytest T/test_template_sheet_checks.py -q` → pass.

- [ ] **Step 5: Threshold lab** — `SP/unit_check_lab.py`: positives for NOT_NORMAL = the abnormal-as-normal units the
hand reads removed (collect from `SP/final/*.handread.md`, lines mentioning "removed … normal"; at least: "Mild
chondral irregularity and thinning.", "Small joint effusion.", "Minimal mucosal thickening noted.", "Mild {valve}
regurgitation." without the slot, the emphysema normal from `ctpa` handread); negatives = every NORMAL/NEGATIVE of
the 31 `SP/final/*.final.md`. For MULTI: positives = the multi-structure normals named in handreads (organ sweeps such
as "The liver, kidneys …, spleen, pancreas, adrenals, and gallbladder are …"), negatives = single-structure normals
(hand-pick 20). Print score distributions; set `NORMAL_MIN`/`MULTI_MIN` at clean gaps. If MULTI has no clean gap,
keep the code but set `MULTI_MIN = 1.1` (off) and note it — multi-structure normals then stay a prompt rule only.

```python
"""Score save-time unit checks on hand-labelled units from the conversion lab."""
import asyncio, glob, sys
from dotenv import load_dotenv
load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")
from rapid_reports_ai.template_sheet_grammar import parse_sheet
from rapid_reports_ai import template_sheet_checks as C

ABNORMAL = ["Mild chondral irregularity and thinning.", "Small joint effusion.", "Minimal mucosal thickening noted.",
            "Mild tricuspid regurgitation.", "Mild centrilobular emphysema."]

class U:  # minimal unit
    def __init__(self, t): self.text = t

async def main():
    units = []
    for p in glob.glob(sys.argv[1] + "/final/*.final.md"):
        st = parse_sheet(open(p).read(), mode="template").structure
        units += [u.text for u in [*st.normals, *st.negatives]]
    units = list(dict.fromkeys(units))
    sc = {}
    for i in range(0, len(units) + len(ABNORMAL), 40):
        chunk = (ABNORMAL + units)[i:i + 40]
        sc.update(await C._jev_scores([U(t) for t in chunk]))
    print("ABNORMAL normal-scores", sorted(round(sc[t][0], 2) for t in ABNORMAL))
    print("FINAL   normal-scores (lowest 15)", sorted(round(sc[t][0], 2) for t in units)[:15])
    print("FINAL   multi-scores (highest 15)", sorted(round(sc[t][1], 2) for t in units)[-15:])
    for t in sorted(units, key=lambda t: sc[t][0])[:8]:
        print("  low normal:", round(sc[t][0], 2), t[:90])
asyncio.run(main())
```

Run: `cd backend && PYTHONPATH=src .venv/bin/python $SP/unit_check_lab.py $SP 2>&1 | grep -v "^🔧\|└─" | tail -14`

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/template_sheet_checks.py backend/tests/test_template_sheet_checks.py
git commit -m "feat(template-save): save-time unit checks (placeholders, abnormal-as-normal, multi-structure)

Thresholds from the conversion-lab units: <numbers>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B2: The save function

**Files:**
- Create: `B/template_sheet_save.py`
- Test: `T/test_template_sheet_save.py`

Origins: `"analyser"`, `"repair"`, `"rebuild"` (automatic) and `"chat"` (the user asked), `"restore"`.

- [ ] **Step 1: Write the failing tests**

`T/template_sheet_fixtures.py` (shared by the save, routes, writer and refine tests; `backend/tests` is on
`sys.path` through its `conftest.py`):

```python
GOOD = """## Report Structure
SECTION FINDINGS role: findings
SECTION IMPRESSION role: impression

## Paragraph: Knee (FINDINGS)
COVERS ["menisci"]
NORMAL [menisci] "The menisci are intact."
"""
BAD_UNIT = GOOD + 'NORMAL [cartilage] "Mild chondral thinning."\n'
```

`T/test_template_sheet_save.py`:

```python
import pytest
from rapid_reports_ai import template_sheet_save as S
from rapid_reports_ai.template_sheet_checks import UnitFailure, NOT_NORMAL
from template_sheet_fixtures import BAD_UNIT, GOOD


@pytest.fixture
def no_jev(monkeypatch):
    async def none(st):
        return []
    monkeypatch.setattr(S, "check_units", none)


async def test_unchanged_sheet_is_skipped(no_jev):
    out = await S.vet_sheet(GOOD, origin="chat", previous=GOOD)
    assert out.status == "unchanged" and out.sheet == GOOD


async def test_clean_sheet_is_saved_with_coverage(no_jev):
    out = await S.vet_sheet(GOOD, origin="analyser", previous="")
    assert out.status == "saved" and out.coverage_sections == ["FINDINGS", "IMPRESSION"]


async def test_failing_new_unit_from_the_analyser_is_dropped(monkeypatch):
    async def fails(st):
        return [UnitFailure(8, "Mild chondral thinning.", NOT_NORMAL)] if "Mild" in "".join(
            n.text for n in st.normals) else []

    async def no_repair(sheet, errors):
        return sheet

    monkeypatch.setattr(S, "check_units", fails)
    monkeypatch.setattr(S, "_repair", no_repair)
    out = await S.vet_sheet(BAD_UNIT, origin="analyser", previous="")
    assert out.status == "saved" and "Mild chondral" not in out.sheet
    assert out.dropped == [{"text": "Mild chondral thinning.", "reason": NOT_NORMAL}]


async def test_failing_unit_in_a_chat_edit_is_refused(monkeypatch):
    async def fails(st):
        return [UnitFailure(8, "Mild chondral thinning.", NOT_NORMAL)] if "Mild" in "".join(
            n.text for n in st.normals) else []

    async def no_repair(sheet, errors):
        return sheet

    monkeypatch.setattr(S, "check_units", fails)
    monkeypatch.setattr(S, "_repair", no_repair)
    out = await S.vet_sheet(BAD_UNIT, origin="chat", previous=GOOD)
    assert out.status == "refused" and out.sheet == GOOD
    assert "Mild chondral thinning." in out.message


async def test_grammar_to_free_form_is_refused(no_jev):
    out = await S.vet_sheet("# Old free-form sheet\nSome prose.", origin="chat", previous=GOOD)
    assert out.status == "refused" and out.sheet == GOOD


async def test_losing_an_existing_unit_automatically_is_refused(monkeypatch):
    async def fails(st):
        return [UnitFailure(7, "The menisci are intact.", NOT_NORMAL)]

    async def no_repair(sheet, errors):
        return sheet

    monkeypatch.setattr(S, "check_units", fails)
    monkeypatch.setattr(S, "_repair", no_repair)
    out = await S.vet_sheet(GOOD.replace("SECTION IMPRESSION role: impression\n", ""), origin="rebuild", previous=GOOD)
    assert out.status == "refused"


async def test_a_jev_error_refuses_the_write(monkeypatch):
    async def boom(st):
        raise RuntimeError("jev down")
    monkeypatch.setattr(S, "check_units", boom)
    out = await S.vet_sheet(GOOD, origin="analyser", previous="")
    assert out.status == "refused" and "try again" in out.message.lower()
```

- [ ] **Step 2: Run** `cd backend && .venv/bin/pytest T/test_template_sheet_save.py -q` → ImportError.

- [ ] **Step 3: Implement** `B/template_sheet_save.py`:

```python
"""The one path that writes a template's skill sheet (template pipeline spec, block 2). Parse; save-time unit
checks; one repair call; then drop (automatic writes, new units only) or refuse (a user's chat edit, a broken or
reverted sheet, an existing unit an automatic write would lose, a check that could not run)."""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import List, Literal

from . import template_sheet_grammar as tsg
from . import template_sheet_lab_prompts as P
from .template_sheet_checks import UnitFailure, check_units

logger = logging.getLogger(__name__)
Origin = Literal["analyser", "repair", "rebuild", "chat", "restore"]
AUTOMATIC = {"analyser", "repair", "rebuild"}


@dataclass
class VetOutcome:
    status: Literal["unchanged", "saved", "refused"]
    sheet: str
    message: str = ""
    dropped: List[dict] = field(default_factory=list)
    coverage_sections: List[str] = field(default_factory=list)


def _norm(t: str) -> str:
    return " ".join(t.lower().split()).rstrip(".")


def _unit_texts(sheet: str) -> set:
    st = tsg.parse_sheet(sheet, mode="template").structure
    return {_norm(u.text) for u in [*st.normals, *st.negatives]}


async def _repair(sheet: str, errors: List[dict]) -> str:
    from .scripts.template_sheet_convert import model_call
    out = await model_call(P.REPAIR_SYSTEM_PROMPT, P.repair_user_prompt(sheet, errors), P.REPAIR_SETTINGS)
    return P.strip_fences(out)


def _errors(res, fails: List[UnitFailure]) -> List[dict]:
    errs = [dataclasses.asdict(e) for e in res.errors]
    if not res.errors and not res.structure.usable:
        errs.append({"line": 0, "text": "", "reason": "structure not usable", "detail": ""})
    errs += [{"line": f.line, "text": f.text, "reason": f.reason, "detail": ""} for f in fails]
    return errs


def _drop_lines(sheet: str, texts: set) -> str:
    keep = []
    for line in sheet.splitlines():
        body = line.strip()
        if body.startswith(("NORMAL", "NEGATIVE")) and any(f'"{t}"' in body for t in texts):
            continue
        keep.append(line)
    return "\n".join(keep) + ("\n" if sheet.endswith("\n") else "")


def _refuse(previous: str, message: str) -> VetOutcome:
    return VetOutcome("refused", previous, message)


async def vet_sheet(sheet: str, origin: Origin, previous: str = "") -> VetOutcome:
    if previous and sheet == previous:
        return VetOutcome("unchanged", previous)
    if not tsg.is_grammar_sheet(sheet):
        return _refuse(previous, "This change could not be applied: the template would lose its structure.")
    try:
        res = tsg.parse_sheet(sheet, mode="template")
        fails = await check_units(res.structure) if res.structure.usable else []
        if res.errors or not res.structure.usable or fails:
            sheet = await _repair(sheet, _errors(res, fails))
            res = tsg.parse_sheet(sheet, mode="template")
            fails = await check_units(res.structure) if res.structure.usable else []
    except Exception as e:  # a check or repair that could not run never lets an unchecked sheet through
        logger.warning("[sheet-save] %s refused: %s: %s", origin, type(e).__name__, str(e)[:200])
        return _refuse(previous, "The template could not be checked just now. Please try again.")
    if res.errors or not res.structure.usable or not tsg.is_grammar_sheet(sheet):
        return _refuse(previous, "This change could not be applied: the template would not be readable.")
    dropped: List[dict] = []
    if fails:
        existing = _unit_texts(previous) if previous else set()
        failed = {f.text for f in fails}
        if origin not in AUTOMATIC:
            quoted = "; ".join(f'"{t}"' for t in sorted(failed))
            return _refuse(previous, f"Couldn't apply: {quoted} ({fails[0].reason}).")
        if existing & {_norm(t) for t in failed}:
            return _refuse(previous, "This change would remove a statement every report includes.")
        sheet = _drop_lines(sheet, failed)
        dropped = [{"text": f.text, "reason": f.reason} for f in fails]
        logger.info("[sheet-save] %s dropped %d unit(s): %s", origin, len(fails), dropped)
        res = tsg.parse_sheet(sheet, mode="template")
        if res.errors or not res.structure.usable:
            return _refuse(previous, "This change could not be applied: the template would not be readable.")
    coverage = [s.name for s in sorted(res.structure.sections, key=lambda s: s.order)]
    return VetOutcome("saved", sheet, dropped=dropped, coverage_sections=coverage)
```

- [ ] **Step 4: Run** `cd backend && .venv/bin/pytest T/test_template_sheet_save.py -q` → pass. (If the
`test_losing_an_existing_unit…` sheet fails earlier because removing IMPRESSION breaks the structure, adjust the test
to keep IMPRESSION and change only the NORMAL text so the failure is the existing-unit branch.)

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_sheet_save.py backend/tests/test_template_sheet_save.py backend/tests/template_sheet_fixtures.py
git commit -m "feat(template-save): one vet function for every sheet write (repair, drop, refuse)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B3: Wire the save function into create, update, save and restore; derive coverage

**Files:**
- Modify: `B/main.py` — `create_template_endpoint` (:1684), update (:1713), restore (:2245), `/skill-sheet/save` (:2684)
- Test: `T/test_template_sheet_save_routes.py`

- [ ] **Step 1: Write the failing tests**

`T/test_template_sheet_save_routes.py`:

```python
import pytest
from rapid_reports_ai import template_sheet_save as S
from template_sheet_fixtures import GOOD

FREE = "# Free-form\nProse only."


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    async def none(st):
        return []
    monkeypatch.setattr(S, "check_units", none)
    monkeypatch.setattr("rapid_reports_ai.template_sheet_structure.store_parsed", lambda tid, st: True)


def _guided(client, auth_headers, sheet=GOOD):
    r = client.post("/api/templates", headers=auth_headers, json={
        "name": "Knee", "template_config": {"generation_mode": "skill_sheet_guided", "skill_sheet": sheet,
                                            "scan_type": "MRI knee"}}).json()
    return r


def test_create_saves_a_grammar_sheet_with_derived_coverage(client, auth_headers):
    r = _guided(client, auth_headers)
    assert r["success"] and r["template"]["template_config"]["coverage_sections"] == ["FINDINGS", "IMPRESSION"]


def test_update_refuses_a_revert_to_free_form(client, auth_headers):
    t = _guided(client, auth_headers)["template"]
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={
        "template_config": {**t["template_config"], "skill_sheet": FREE}}).json()
    assert r["success"] is False and "structure" in r["error"]
    again = client.get(f"/api/templates/{t['id']}", headers=auth_headers).json()
    assert again["template"]["template_config"]["skill_sheet"] == GOOD


def test_update_without_a_sheet_change_skips_vetting(client, auth_headers, monkeypatch):
    t = _guided(client, auth_headers)["template"]

    async def boom(*a, **k):
        raise AssertionError("vetted an unchanged sheet")
    monkeypatch.setattr(S, "vet_sheet", boom)
    r = client.put(f"/api/templates/{t['id']}", headers=auth_headers, json={"name": "Knee 2"}).json()
    assert r["success"]
```

(Check the GET response shape at `main.py:1607` — if it returns the template at top level, adjust `again[...]`.)

- [ ] **Step 2: Run** `cd backend && .venv/bin/pytest T/test_template_sheet_save_routes.py -q` → failures.

- [ ] **Step 3: Implement** — add a helper in `B/main.py` beside `_carry_structure`:

```python
async def _vet_config(new_cfg: dict | None, old_cfg: dict | None, origin: str) -> tuple[dict | None, str]:
    """Run the one save function when a guided template's sheet changes (template pipeline spec, block 2).
    Returns (config to store, refusal message or "")."""
    from .template_sheet_save import vet_sheet
    if not new_cfg or new_cfg.get("generation_mode") != "skill_sheet_guided":
        return new_cfg, ""
    sheet, before = new_cfg.get("skill_sheet") or "", (old_cfg or {}).get("skill_sheet") or ""
    if not sheet or sheet == before:
        return new_cfg, ""
    out = await vet_sheet(sheet, origin=origin, previous=before)
    if out.status == "refused":
        return None, out.message
    return {**new_cfg, "skill_sheet": out.sheet, "coverage_sections": out.coverage_sections}, ""
```

In `create_template_endpoint`, after `cfg = _carry_structure(...)`:

```python
    cfg, refusal = await _vet_config(cfg, {}, "analyser")
    if refusal:
        return {"success": False, "error": refusal}
```

In the PUT endpoint, after `cfg = _carry_structure(cfg, existing.template_config)`:

```python
        cfg, refusal = await _vet_config(cfg, existing.template_config, "chat")
        if refusal:
            return {"success": False, "error": refusal}
```

In `/skill-sheet/save`: delete the `extract_coverage_sections` try-block (main.py:2704-2710) and vet instead:

```python
        cfg, refusal = await _vet_config({"generation_mode": "skill_sheet_guided", "skill_sheet": request.skill_sheet,
                                          "scan_type": request.scan_type}, {}, "analyser")
        if refusal:
            return {"success": False, "error": refusal}
        template_config = cfg
```

In restore (:2245): load the version first and refuse a non-grammar sheet for guided templates:

```python
    version = db.query(TemplateVersion).filter(TemplateVersion.id == uuid.UUID(version_id),
                                               TemplateVersion.template_id == uuid.UUID(template_id)).first()
    vcfg = (version.template_config or {}) if version else {}
    if vcfg.get("generation_mode") == "skill_sheet_guided" and not tsg.is_grammar_sheet(vcfg.get("skill_sheet") or ""):
        return {"success": False, "error": "This version is from before the template upgrade and can't be restored."}
```

(Use the imports already present in `main.py` for `TemplateVersion`/`uuid`; add them if missing.)

- [ ] **Step 4: Run** `cd backend && .venv/bin/pytest T/test_template_sheet_save_routes.py T/test_template_structure_triggers.py T/test_template_generate_endpoint.py -q` → pass.

- [ ] **Step 5: Remove the coverage endpoint and its client call**

Delete `ExtractCoverageRequest` and `/api/templates/skill-sheet/extract-coverage` (`main.py:2734-2750`) and
`TemplateManager.extract_coverage_sections` if no other caller (`grep -rn "extract_coverage_sections" backend/src`).
In `F/routes/components/TemplateRefinePanel.svelte:96-106` remove the `postJson('/api/templates/skill-sheet/extract-coverage' …)`
block, and show the server's refusal: after the PUT, `if (!data.success) { saveError = data.error; return; }`
(declare `let saveError = '';` and render `{#if saveError}<p class="text-xs text-amber-400">{saveError}</p>{/if}` under
the save button). Same in `F/lib/.../VersionHistory.svelte:56` for the restore error.

Run: `cd frontend && bun run check 2>&1 | tail -3` → no new errors; `cd backend && .venv/bin/pytest -q 2>&1 | tail -2` → pass.

- [ ] **Step 6: Commit**

```bash
git add -A backend/src/rapid_reports_ai/main.py backend/src/rapid_reports_ai/template_manager.py backend/tests/test_template_sheet_save_routes.py frontend/src/routes/components/TemplateRefinePanel.svelte frontend/src/lib
git commit -m "feat(template-save): create/update/save/restore go through the save function; coverage from the parse

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

# Phase C — One writer and the preview

### Task C1: Preview function (the lab harness as a server function)

**Files:**
- Create: `B/template_preview.py`
- Modify: `B/main.py` `/skill-sheet/test-generate` (:2646)
- Test: `T/test_template_preview.py`

- [ ] **Step 1: Write the failing test**

`T/test_template_preview.py`:

```python
from types import SimpleNamespace as NS
from rapid_reports_ai.template_preview import findings_block

R = [NS(name="Liver"), NS(name="Kidneys")]


def test_findings_block_matches_the_scratchpad_order():
    units = [NS(text="CT with contrast.", group="Technique", heading=False),
             NS(text="9 mm cyst.", group="Liver", heading=False),
             NS(text="Free fluid.", group="General", heading=False),
             NS(text="Odd sentence.", group=None, heading=False),
             NS(text="Appendicitis.", group="Conclusion", heading=False)]
    b = findings_block(units, R, {"Liver": ["No biliary dilatation."], "Kidneys": ["Normal kidneys."]},
                       "Appendicitis.", [])
    assert b.splitlines()[0] == "CT with contrast."
    assert "Liver: 9 mm cyst. Assumed normal (confirmed by the radiologist): No biliary dilatation." in b
    assert "Free fluid." in b and "Odd sentence." in b
    assert "Assumed normal (confirmed by the radiologist): Kidneys: Normal kidneys." in b
    assert b.endswith("Conclusion (confirmed by the radiologist): Appendicitis.")
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement** `B/template_preview.py` (from `SP/e2e.py`):

```python
"""Preview a template sheet as the scratchpad would report a dictation (template pipeline spec, block 3): group
the dictation, assume the template's normals, build the findings block as regionState.buildFindingsBlock does,
and generate on the template stack path. Used by the creator's preview and the labs."""
from __future__ import annotations

from typing import Optional

from .template_sheet_grammar import parse_sheet

ASSUMED = "Assumed normal (confirmed by the radiologist):"
_FREE = ("Technique", "General", None)


def findings_block(units, regions, kept: dict, conclusion: str, declined: list) -> str:
    groups = [r.name for r in regions]
    items = [u for u in units if not u.heading and u.group != "Conclusion"]
    lines, dictated = [], {u.group for u in items if u.group in groups}
    tech = [u.text for u in items if u.group == "Technique"]
    if tech:
        lines += [" ".join(tech), ""]
    for g in groups:
        own = [u.text for u in items if u.group == g]
        more = [f"{ASSUMED} {' '.join(kept[g])}"] if g in dictated and kept.get(g) else []
        if own or more:
            lines.append(f"{g}: {' '.join(own + more)}")
    for g in dict.fromkeys(u.group for u in items):
        if g not in groups and g not in _FREE:
            lines.append(f"{g}: {' '.join(u.text for u in items if u.group == g)}")
    lines += [u.text for u in items if u.group in ("General", None)]
    parts = ["\n".join(lines).strip()]
    tray = [f"{r}: {' '.join(s)}" for r, s in kept.items() if s and r not in dictated]
    if tray:
        parts.append(f"{ASSUMED} {' '.join(tray)}")
    if conclusion.strip():
        parts.append(f"Conclusion (confirmed by the radiologist): {conclusion.strip()}")
    if declined:
        parts.append(f"DO NOT ASSERT (removed by the radiologist): {' '.join(declined)}")
    return "\n\n".join(p for p in parts if p)


async def preview_report(sheet: str, scan_type: str, history: str, dictation: str, conclusion: str = "",
                         declined: Optional[list] = None) -> dict:
    from .hybrid_stack.normals import assumed
    from .hybrid_stack.service import group_update
    from .hybrid_stack.template import template_region_normals, template_regions, template_suppressions
    from .template_manager import TemplateManager
    declined = declined or []
    st = parse_sheet(sheet, mode="template").structure
    if not st.usable:
        return {"usable": False}
    regions = template_regions(st)
    normals = {r: s[:16] for r, s in template_region_normals(st).items()}
    g = await group_update(scan_type, dictation, regions, [])
    a = await assumed(dictation, normals, [u.text for u in g.units if u.abnormal], [], declined,
                      suppressions=template_suppressions(st), clinical_history=history)
    block = findings_block(g.units, regions, a.assumed, conclusion, declined)
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": sheet, "scan_type": scan_type}
    gen = await TemplateManager().generate_report_from_config(
        cfg, {"FINDINGS": block, "CLINICAL_HISTORY": history}, None,
        stack={"conclusion": conclusion, "declined": declined})
    return {"usable": True, "regions": [r.name for r in regions], "assumed": a.assumed, "dropped": a.dropped,
            "findings_block": block, "report_content": gen["report_content"], "model_used": gen.get("model_used")}
```

`/skill-sheet/test-generate` body becomes:

```python
        from .template_preview import preview_report
        out = await preview_report(request.skill_sheet, request.scan_type, request.clinical_history,
                                   request.findings_input)
        if not out.get("usable"):
            return {"success": False, "error": "The template isn't readable yet; refine it and try again."}
        return {"success": True, "report_content": out["report_content"], "model_used": out.get("model_used")}
```

- [ ] **Step 4: Run** `cd backend && .venv/bin/pytest T/test_template_preview.py -q` → pass. Parity: run
`SP/e2e.py` and `preview_report` on `SP/final/ct_abdomen_and_pelvis_portal_venous.e2e_case.json` and diff the
`findings_block` strings (must be identical).

- [ ] **Step 5: Creator preview on demand** — `F/routes/components/SkillSheetCreator.svelte:463-469`: delete the
auto `runTestGenerate()` after a refine turn; under the test report add a button
`<button on:click={runTestGenerate} disabled={testGenerating}>Update preview</button>` (reuse the existing busy flag
name — `grep -n "runTestGenerate\|Generating" SkillSheetCreator.svelte`). `bun run check` → clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/template_preview.py backend/src/rapid_reports_ai/main.py backend/tests/test_template_preview.py frontend/src/routes/components/SkillSheetCreator.svelte
git commit -m "feat(template): preview through the scratchpad path; creator preview on demand

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task C2: Writer prompt rules (one structure per normal, named; slotted examples)

**Files:**
- Modify: `B/template_sheet_lab_prompts.py` (GRAMMAR NORMAL line ~78; analyser voice-exemplar rule ~166)
- Test: `T/test_template_sheet_lab_prompts.py`

- [ ] **Step 1: Failing test** — append:

```python
from rapid_reports_ai import template_sheet_lab_prompts as P


def test_grammar_asks_one_named_structure_per_normal_and_slotted_examples():
    assert "(or group)" not in P.GRAMMAR
    assert "names its structure in its own words" in P.GRAMMAR
    assert "never a specific value, code, grade or time window" in P.ANALYSER_SYSTEM_PROMPT
```

- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** — in `GRAMMAR`, the NORMAL description: replace "that one named structure (or group) is
normal" with "that one named structure is normal; the sentence names its structure in its own words (\"The liver is
unremarkable.\", never just \"Unremarkable.\")". In the analyser's voice-exemplar rule (~:166) append: "Exemplars use
{slots} for every value; never a specific value, code, grade or time window, and never a diagnosis."
- [ ] **Step 4: Run** `cd backend && .venv/bin/pytest T/test_template_sheet_lab_prompts.py T/test_template_sheet_convert.py -q` → pass.
- [ ] **Step 5: Commit** `feat(template-writer): one named structure per normal; slotted, diagnosis-free exemplars`.

### Task C3: Lab — direct grammar analyser vs analyser + conversion (decides C4)

- [ ] **Step 1: Write `SP/writer_lab.py`.** For each of the 31 templates in `SP/data_all.json` with ≥ 3 reports:
examples = the radiologist's latest-version report texts (`latest_version_content or report_content`) except the most
recent (held out). Arm D: `P.ANALYSER_SYSTEM_PROMPT` + `P.analyser_user_prompt(examples, scan_type)` →
`P.split_answer` → `vet_sheet(origin="analyser")`. Arm C: production `analyze_examples_to_skill_sheet` →
`template_sheet_convert.convert(old_sheet, scan_type, examples)` → `vet_sheet`. Save each sheet as
`SP/writer/<slug>.<arm>.md`. Then run `preview_report` on the held-out report's `e2e_case.json` for both arms →
`SP/writer/<slug>.<arm>.preview.json`. Sequential, one template at a time (Cerebras TPM).

```python
"""Writer lab: direct grammar analyser (D) vs free-form analyser + conversion (C), hold-one-out."""
import asyncio, json, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")
from rapid_reports_ai import template_sheet_lab_prompts as P
from rapid_reports_ai.scripts.template_sheet_convert import model_call, convert
from rapid_reports_ai.template_manager import TemplateManager
from rapid_reports_ai.template_sheet_save import vet_sheet
from rapid_reports_ai.template_preview import preview_report

SP = Path(sys.argv[1]); OUT = SP / "writer"; OUT.mkdir(exist_ok=True)

async def arm_d(examples, scan):
    raw = await model_call(P.ANALYSER_SYSTEM_PROMPT, P.analyser_user_prompt(examples, scan), P.ANALYSER_SETTINGS)
    return P.split_answer(raw)["skill_sheet"]

async def arm_c(examples, scan):
    free = await TemplateManager().analyze_examples_to_skill_sheet(examples, scan, "")
    return (await convert(free["skill_sheet"], scan, [{"report_content": e["content"]} for e in examples]))["sheet"]

async def main():
    for t in json.loads((SP / "data_all.json").read_text())["templates"]:
        reps = [r for r in t["reports"] if (r.get("latest_version_content") or r.get("report_content"))]
        if len(reps) < 3:
            continue
        ex = [{"label": "", "content": r.get("latest_version_content") or r["report_content"]} for r in reps[1:]]
        case = json.loads((SP / "final" / f"{t['slug']}.e2e_case.json").read_text())
        for arm, fn in (("D", arm_d), ("C", arm_c)):
            try:
                v = await vet_sheet(await fn(ex, t["scan_type"] or t["name"]), origin="analyser")
                (OUT / f"{t['slug']}.{arm}.md").write_text(v.sheet)
                pv = await preview_report(v.sheet, case["scan_type"], case.get("history", ""), case["dictation"],
                                          case.get("conclusion", "")) if v.status == "saved" else {"usable": False}
                (OUT / f"{t['slug']}.{arm}.preview.json").write_text(json.dumps({"vet": v.status, "dropped": v.dropped, **pv}, indent=1))
                print("ok", t["slug"], arm, v.status, len(v.dropped), flush=True)
            except Exception as e:
                print("ERR", t["slug"], arm, type(e).__name__, str(e)[:100], flush=True)
asyncio.run(main())
```

(Check `convert`'s signature and return keys in `scripts/template_sheet_convert.py:163` before running; adapt the
reports argument to what it expects.)

- [ ] **Step 2: Run** in the background: `cd backend && PYTHONPATH=src .venv/bin/python $SP/writer_lab.py $SP 2>&1 | grep -a "^ok\|^ERR" | tail -70`

- [ ] **Step 3: Score.** Per arm: usable rate; units dropped by the save function; regions vs the hand-fixed sheet
(`SP/final/<slug>.final.md`, via `SP/lint.py`); mandatory units of the hand-fixed sheet present (NORMAL/NEGATIVE text
overlap ≥ 0.8 token Jaccard); hand read of the preview report against the radiologist's held-out report (dispatch
subagents, ≈10 templates each, same rules as `SP/AGENT_BRIEF.md` step 2). Write `SP/writer/RESULT.md`.

- [ ] **Step 4: Decide.** D wins or ties → Task C4 uses D. C clearly better → C4 wires analyser + conversion
instead (same save function). Report to Hassan before C4.

### Task C4: Production writer — the creator writes the grammar

**Files:**
- Create: `B/template_writer.py`
- Modify: `B/main.py` `/skill-sheet/analyze` (:2499)
- Test: `T/test_template_writer.py`

- [ ] **Step 1: Failing test** `T/test_template_writer.py`:

```python
from rapid_reports_ai import template_writer as W
from template_sheet_fixtures import GOOD


async def test_write_returns_a_vetted_sheet_summary_and_questions(monkeypatch):
    async def call(system, user, settings):
        return f'<<<SKILL_SHEET\n{GOOD}\nSKILL_SHEET>>>\n{{"summary": "s", "questions": [{{"question": "q?"}}]}}'

    async def vet(sheet, origin, previous=""):
        from rapid_reports_ai.template_sheet_save import VetOutcome
        return VetOutcome("saved", sheet, coverage_sections=["FINDINGS"])

    monkeypatch.setattr(W, "model_call", call)
    monkeypatch.setattr(W, "vet_sheet", vet)
    out = await W.write_sheet([{"label": "", "content": "r1"}], "MRI knee")
    assert out["skill_sheet"].startswith("## Report Structure") and out["questions"][0]["question"] == "q?"
    assert out["analyser_version"] == W.ANALYSER_VERSION
```

(Check `P.split_answer`'s exact expected layout at `template_sheet_lab_prompts.py:251` and shape the fake answer to it.)

- [ ] **Step 2: Run** → ImportError.
- [ ] **Step 3: Implement** `B/template_writer.py` (arm D; if C3 chose C, implement `write_sheet` as analyser +
`convert` instead, same return shape):

```python
"""The one writer (template pipeline spec, block 1): example reports -> grammar sheet, vetted by the save function.
Creation and any future rebuild use this call."""
from __future__ import annotations

from typing import Dict, List

from . import template_sheet_lab_prompts as P
from .scripts.template_sheet_convert import model_call
from .template_sheet_save import vet_sheet

ANALYSER_VERSION = "grammar-analyser-2026-10-13"


async def write_sheet(examples: List[Dict[str, str]], scan_type: str, protocol_notes: str = "") -> Dict:
    raw = await model_call(P.ANALYSER_SYSTEM_PROMPT, P.analyser_user_prompt(examples, scan_type, protocol_notes),
                           P.ANALYSER_SETTINGS)
    ans = P.split_answer(raw)
    v = await vet_sheet(ans["skill_sheet"] or "", origin="analyser")
    if v.status != "saved":
        raise ValueError(v.message or "the template could not be written")
    return {"skill_sheet": v.sheet, "summary": ans.get("summary") or {}, "questions": ans.get("questions") or [],
            "dropped": v.dropped, "analyser_version": ANALYSER_VERSION}
```

In `/skill-sheet/analyze` replace `tm.analyze_examples_to_skill_sheet(...)` with
`template_writer.write_sheet([{"label": e.label or "", "content": e.content} for e in request.examples],
request.scan_type, request.protocol_notes or "")` (keep the parallel `generate_test_case`; keep the response keys
`skill_sheet, summary, questions, sample_clinical_history, sample_findings`). Check the frontend reads `summary` the
same way (`SkillSheetCreator.svelte:~340`); map lab `SUMMARY_SPEC` keys if they differ.

- [ ] **Step 4: Run** `cd backend && .venv/bin/pytest T/test_template_writer.py -q` and the full suite → pass.
- [ ] **Step 5: Commit** `feat(template-writer): the creator writes the grammar sheet (vetted)`.

### Task C5: Chat-to-edit writes the grammar

**Files:**
- Modify: `B/template_manager.py:3704-3744` (refine system prompt), `B/main.py` `/skill-sheet/refine` (:2600)
- Test: `T/test_template_refine.py`

- [ ] **Step 1: Failing test** `T/test_template_refine.py`:

```python
from rapid_reports_ai import template_sheet_save as S
from template_sheet_fixtures import GOOD


def test_refine_refusal_keeps_the_sheet_and_says_why(client, auth_headers, monkeypatch):
    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": GOOD + 'NORMAL [cartilage] "Mild thinning."\n', "response": "Done", "behavioral_claim": ""}

    async def vet(sheet, origin, previous=""):
        return S.VetOutcome("refused", previous, 'Couldn\'t apply: "Mild thinning." (states an abnormality as a normal).')

    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    monkeypatch.setattr(S, "vet_sheet", vet)
    r = client.post("/api/templates/skill-sheet/refine", headers=auth_headers,
                    json={"skill_sheet": GOOD, "message": "add cartilage thinning as normal"}).json()
    assert r["success"] is True and r["skill_sheet"] == GOOD and r["response"].startswith("Couldn't apply")


async def test_refine_prompt_carries_the_grammar(monkeypatch):
    from rapid_reports_ai import template_manager as tm_mod
    from rapid_reports_ai import template_sheet_lab_prompts as P
    seen = {}

    async def capture(model_name, output_type, system_prompt, user_prompt, api_key, **k):
        seen["system"] = system_prompt
        return type("R", (), {"output": '{"skill_sheet": "x", "response": "ok", "behavioral_claim": ""}'})()
    monkeypatch.setattr(tm_mod, "_run_agent_with_model", capture)
    await tm_mod.TemplateManager().refine_skill_sheet("## Report Structure\n", "shorter", [], "")
    assert P.GRAMMAR[:60] in seen["system"] and "report behaviour" in seen["system"]
```

(If `_run_agent_with_model` is imported into `template_manager` under another name, patch that name — `grep -n
"_run_agent_with_model" backend/src/rapid_reports_ai/template_manager.py | head -2`.)

- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** — in `refine_skill_sheet`, build the system prompt as
`system_prompt = BASE_REFINE_PROMPT + "\n\n" + P.GRAMMAR + "\n\n" + P.SHEET_LAYOUT + REFINE_GRAMMAR_RULE` where
`BASE_REFINE_PROMPT` is the existing string and:

```python
REFINE_GRAMMAR_RULE = """

The skill sheet is written in the strict line grammar above. Your edited skill_sheet keeps every unit line valid:
a new constraint becomes a unit (NORMAL, NEGATIVE, FIXED, TERM, RULE, LIST_MISSING) in the right paragraph, never a
prose instruction; keep everything you were not asked to change exactly as it is. Your response describes the
change as report behaviour ("Reports will now …"), never as sheet syntax."""
```

In the `/skill-sheet/refine` endpoint, after `result = await tm.refine_skill_sheet(...)`:

```python
        from .template_sheet_save import vet_sheet
        v = await vet_sheet(result["skill_sheet"], origin="chat", previous=request.skill_sheet)
        if v.status == "refused":
            return {"success": True, "skill_sheet": request.skill_sheet, "response": v.message,
                    "behavioral_claim": "", "applied": False}
        result["skill_sheet"] = v.sheet
```

and add `"applied": True` to the normal success response. Frontend `TemplateRefinePanel.svelte` and
`SkillSheetCreator.svelte` already render `response`; no change needed beyond showing it.

- [ ] **Step 4: Refine round-trip lab** — for 5 of the `SP/final/*.final.md` sheets, send 3 instructions each
("always state the conus level", "remove the comparison line", "use 'no ascites' instead of 'no free fluid'") through
`refine_skill_sheet` + `vet_sheet(origin="chat")`; expect every result `saved` with lint clean or `refused` with a
message — never an unusable stored sheet. Record counts in the commit message.
- [ ] **Step 5: Run** the tests and full suite → pass.
- [ ] **Step 6: Commit** `feat(template-refine): chat-to-edit writes the grammar; refusals keep the sheet`.

---

# Phase D — Evidence record

### Task D1: Migration and models

**Files:**
- Create: `backend/migrations/versions/20261013090000_template_evidence.py`
- Modify: `B/database/models.py` (Report, DictationStackLog, new TemplateExample, TemplateChatTurn)
- Test: `T/test_template_evidence_models.py`

- [ ] **Step 1: Failing test** `T/test_template_evidence_models.py`:

```python
from rapid_reports_ai.database.models import TemplateExample, TemplateChatTurn, Report, DictationStackLog


def test_evidence_columns_exist():
    assert "generation_stamp" in Report.__table__.columns
    assert {"template_id", "stamp"} <= set(DictationStackLog.__table__.columns.keys())
    assert {"template_id", "text", "sha256", "source"} <= set(TemplateExample.__table__.columns.keys())
    assert {"template_id", "instruction", "response", "applied"} <= set(TemplateChatTurn.__table__.columns.keys())
```

- [ ] **Step 2: Run** → ImportError.
- [ ] **Step 3: Migration** (`down_revision = "20261012090000"`):

```python
"""Template evidence: stored examples, chat turns, generation stamps (template pipeline spec, block 4)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261013090000"
down_revision = "20261012090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pg = op.get_bind().dialect.name == "postgresql"
    json_type = postgresql.JSONB if pg else sa.JSON
    uuid_type = postgresql.UUID(as_uuid=True) if pg else sa.String(36)
    op.create_table("template_examples",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("template_id", uuid_type, sa.ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="pasted"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("template_chat_turns",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("template_id", uuid_type, sa.ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sheet_hash_before", sa.String(64), nullable=True),
        sa.Column("sheet_hash_after", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.add_column("reports", sa.Column("generation_stamp", json_type(), nullable=True))
    op.add_column("dictation_stack_logs", sa.Column("template_id", sa.String(64), nullable=True))
    op.add_column("dictation_stack_logs", sa.Column("stamp", json_type(), nullable=True))


def downgrade() -> None:
    op.drop_column("dictation_stack_logs", "stamp")
    op.drop_column("dictation_stack_logs", "template_id")
    op.drop_column("reports", "generation_stamp")
    op.drop_table("template_chat_turns")
    op.drop_table("template_examples")
```

Models (`B/database/models.py`): add `generation_stamp = Column(JSONB_or_JSON, nullable=True)` to `Report` (use the
JSON type the file already uses for `candidate_reports`), `template_id = Column(String(64), nullable=True)` and
`stamp = Column(<same JSON type>, nullable=True)` to `DictationStackLog`, and the two classes:

```python
class TemplateExample(Base):
    __tablename__ = "template_examples"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    sha256 = Column(String(64), nullable=False)
    source = Column(String(16), nullable=False, default="pasted")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TemplateChatTurn(Base):
    __tablename__ = "template_chat_turns"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True)
    instruction = Column(Text, nullable=False)
    response = Column(Text, nullable=True)
    applied = Column(Boolean, nullable=False, default=True)
    sheet_hash_before = Column(String(64), nullable=True)
    sheet_hash_after = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

(Match the column helpers the file already imports — `UUID`, `JSONB`/`JSON`, `func`. Per the note at
`models.py:411-414`, mapping new columns is safe because Railway runs `fix_migration_state.py` → `upgrade head`
before the app starts in the same deploy.)

- [ ] **Step 4: Run** `cd backend && .venv/bin/pytest T/test_template_evidence_models.py -q` and
`.venv/bin/alembic upgrade head` against a scratch SQLite (`DATABASE_URL=sqlite:////tmp/<SP>/mig.db`) → succeeds,
then `alembic downgrade -1` → succeeds.
- [ ] **Step 5: Commit** `feat(evidence): template examples, chat turns, generation stamps (migration)`.

### Task D2: Generation stamps on reports and stack logs

**Files:**
- Modify: `B/database/crud.py:731` (`create_report` gains `generation_stamp=None`)
- Modify: `B/main.py:2105` (template report creation), `B/hybrid_stack/routes.py` `/log`
- Modify: `F/lib/hybrid-stack/api.ts` (`StackLog.template_id`), `F/lib/components/DictationScratchpad.svelte:1995-2007`
- Test: `T/test_template_generate_endpoint.py`, `T/test_hybrid_stack_routes.py`

- [ ] **Step 1: Failing tests** — append to `T/test_template_generate_endpoint.py` a test that generates a stack
report for `guided_template` (follow the existing stack tests' pattern in that file) and asserts:

```python
    rep = db_session.query(Report).order_by(Report.created_at.desc()).first()
    assert rep.generation_stamp["path"] == "scratchpad"
    assert rep.generation_stamp["sheet_hash"] == sheet_hash(guided_template.template_config["skill_sheet"])
    assert rep.generation_stamp["grammar_version"] == STRUCTURE_VERSION
```

and one for the fallback path asserting `path == "fallback"`. Append to `T/test_hybrid_stack_routes.py`:

```python
def test_log_stamps_the_template_sheet(client, auth_headers, guided_template, db_session):
    r = client.post("/api/hybrid-stack/log", headers=auth_headers,
                    json={"session_id": "s1", "template_id": str(guided_template.id)})
    assert r.status_code == 200
    row = db_session.query(DictationStackLog).filter_by(session_id="s1").one()
    assert row.template_id == str(guided_template.id) and row.stamp["sheet_hash"]
```

- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** — a helper in `B/template_sheet_structure.py`:

```python
def generation_stamp(template_id: str, config: dict, path: str) -> dict:
    """Which sheet produced a report or a session (template pipeline spec, block 4)."""
    raw = (config or {}).get("sheet_structure") or {}
    return {"template_id": str(template_id), "sheet_hash": sheet_hash((config or {}).get("skill_sheet") or ""),
            "grammar_version": STRUCTURE_VERSION, "analyser_version": raw.get("analyser_version", ""), "path": path}
```

`crud.create_report(..., generation_stamp=None)` sets `generation_stamp=generation_stamp` on the row. In
`main.py:2105` pass
`generation_stamp=tss.generation_stamp(str(template.id), template.template_config, "scratchpad" if _stack else "fallback")`.
`LogRequest` gains `template_id: str | None = None`; in `/log`, when `req.template_id` is set, load the template
(owner) and set `stamp = generation_stamp(req.template_id, t.template_config, "scratchpad")` on the upserted row.
Frontend: `StackLog` gains `template_id?: string | null`; `sendStackLog()` adds `template_id: stackTemplateId`.
Analyser version: in Task C4's `write_sheet` result, the creator's save stores `analyser_version` — add it to the
save request (`SkillSheetSaveRequest.analyser_version: str = ""`) and into `template_config["analyser_version"]`; have
`generation_stamp` read `config.get("analyser_version", "")` instead of the structure.

- [ ] **Step 4: Run** the two test files and the full suite → pass; `bun run check` → clean.
- [ ] **Step 5: Commit** `feat(evidence): generation stamps on template reports and scratchpad logs`.

### Task D3: Gate record — offered and dropped normals

**Files:**
- Modify: `F/lib/hybrid-stack/types.ts:63-78`, `F/lib/hybrid-stack/items.ts:65` (AssumedSnap), `F/lib/components/DictationScratchpad.svelte:1806-1821, 1936-1961`
- Test: `F/lib/hybrid-stack/regionState.test.ts` or a new `F/lib/hybrid-stack/gate.test.ts`

- [ ] **Step 1: Failing test** — extract the gate's new fields into a pure helper so it can be tested:

`F/lib/hybrid-stack/gate.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { offeredAndDropped } from './gate';

describe('offeredAndDropped', () => {
	it('records what was offered and what the check dropped, with the reason', () => {
		const out = offeredAndDropped({ Liver: ['A.', 'B.'] }, { Liver: [{ sentence: 'B.', reason: 'contradicted' }] });
		expect(out.offered).toEqual({ Liver: ['A.', 'B.'] });
		expect(out.jev_dropped).toEqual({ Liver: [{ sentence: 'B.', reason: 'contradicted' }] });
	});
});
```

- [ ] **Step 2: Run** `cd frontend && bunx vitest --run src/lib/hybrid-stack/gate.test.ts` → fail.
- [ ] **Step 3: Implement** `F/lib/hybrid-stack/gate.ts`:

```ts
export type Dropped = Record<string, { sentence: string; reason: string }[]>;

/** The gate's evidence of the assumed-normal check (template pipeline spec, block 4): what the sheet offered and
 *  what the check dropped, with its reason. */
export function offeredAndDropped(offered: Record<string, string[]>, dropped: Dropped | undefined) {
	return { offered: { ...offered }, jev_dropped: { ...(dropped ?? {}) } };
}
```

`types.ts` `GateRecord` gains `offered?: Record<string, string[]>; jev_dropped?: Record<string, { sentence: string; reason: string }[]>;`.
`items.ts` `AssumedSnap` gains `dropped?: Dropped`. In `refreshAssumed()` store `dropped: res.dropped` in the snap. In
`stackConfirm()` spread `...offeredAndDropped(stackRegionNormals, assumedSnap?.dropped)` into the gate object.

- [ ] **Step 4: Run** the test and `bun run check` → pass.
- [ ] **Step 5: Commit** `feat(evidence): the gate records offered and Jev-dropped normals`.

### Task D4: Stored example reports (de-identified) and the creator notice

**Files:**
- Create: `B/template_examples.py`
- Modify: `B/main.py` `SkillSheetSaveRequest` (:760) + `/skill-sheet/save`; `F/routes/components/SkillSheetCreator.svelte:562, 641-643`
- Test: `T/test_template_examples.py`

- [ ] **Step 1: Failing test** `T/test_template_examples.py`:

```python
from rapid_reports_ai import template_examples as E


def test_code_backstop_removes_identifier_shapes():
    t = "Name: John Smith\nDOB: 01/02/1960\nNHS 943 476 5919\nMRN A1234567\nThe liver is normal."
    out = E.scrub(t)
    assert "John Smith" not in out and "01/02/1960" not in out and "943 476 5919" not in out and "A1234567" not in out
    assert "The liver is normal." in out


async def test_store_skips_an_example_jev_still_flags(db_session, guided_template, monkeypatch):
    async def flags(texts):
        return [0.9 if "Dr Jones" in t else 0.1 for t in texts]
    monkeypatch.setattr(E, "_identifier_scores", flags)
    n = await E.store_examples(db_session, guided_template.id, ["Normal study.", "Reported by Dr Jones for Mrs Patel."])
    assert n == 1
```

- [ ] **Step 2: Run** → ImportError.
- [ ] **Step 3: Implement** `B/template_examples.py`:

```python
"""Example reports stored with a template (template pipeline spec, block 4): de-identified at paste (a code backstop,
then a Jev identifier question; a still-flagged example is not stored), deleted with the template (FK cascade),
never used across users."""
from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import List

from .database.models import TemplateExample
from .jev_client import JEV_MODEL, jev_post

logger = logging.getLogger(__name__)
IDENTIFIER_MIN = 0.5   # unvalidated starting point; Task D4 step 5 checks it on the 31 templates' reports
_PATTERNS = [
    re.compile(r"(?im)^\s*(name|patient|pt name|dob|date of birth|nhs( no| number)?|mrn|hospital no|accession)\s*[:#].*$"),
    re.compile(r"\b\d{3}\s?\d{3}\s?\d{4}\b"),                 # NHS-number shape
    re.compile(r"\b[A-Z]{1,3}\d{6,9}\b"),                      # MRN / accession shape
    re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b"),        # dates
]
Q_IDENT = ("The TEXT contains information that could identify a patient or a person involved in their care: a "
           "name, date of birth, address, phone number, hospital or NHS number, or accession number.")


def scrub(text: str) -> str:
    for p in _PATTERNS:
        text = p.sub("[removed]", text)
    return text


async def _identifier_scores(texts: List[str]) -> List[float]:
    qs = {f"t{i}": {"type": "noul", "instructions": Q_IDENT} for i in range(len(texts))}
    out = []
    for i, t in enumerate(texts):
        r = await jev_post({"model": JEV_MODEL, "state": f"TEXT:\n{t[:6000]}", "questions": {"q": qs[f"t{i}"]}},
                           os.environ.get("OPENROUTER_API_KEY", ""), 6.0)
        r.raise_for_status()
        out.append(float(((r.json().get("answers") or {}).get("q") or {}).get("noul") or 0.0))
    return out


async def store_examples(db, template_id, texts: List[str]) -> int:
    clean = [scrub(t).strip() for t in texts if t and t.strip()]
    try:
        scores = await _identifier_scores(clean)
    except Exception as e:
        logger.warning("[examples] identifier check failed, nothing stored: %s", e)
        return 0
    n = 0
    for t, s in zip(clean, scores):
        if s >= IDENTIFIER_MIN:
            logger.info("[examples] not stored (identifier score %.2f)", s)
            continue
        db.add(TemplateExample(template_id=template_id, text=t, sha256=hashlib.sha256(t.encode()).hexdigest(),
                               source="pasted"))
        n += 1
    db.commit()
    return n
```

`SkillSheetSaveRequest` gains `examples: List[SkillSheetExample] = []` and `chat_turns: List[Dict[str, str]] = []`
(used in D5). After `create_template(...)` in `/skill-sheet/save`:
`await template_examples.store_examples(db, template.id, [e.content for e in request.examples])` inside a try/except
that logs and never fails the save.

Frontend `SkillSheetCreator.svelte:562` save body adds `examples: examples.filter((e) => e.content.trim())`. At
`:641-643` add a sibling line, always shown:

```svelte
<p class="px-5 pt-1 pb-0 text-[11px] text-gray-600">Your example reports are kept with this template (with names, dates and ID numbers removed) so it can be improved later. They're deleted if you delete the template.</p>
```

- [ ] **Step 4: Run** `cd backend && .venv/bin/pytest T/test_template_examples.py -q` → pass; `bun run check` → clean.
- [ ] **Step 5: Identifier lab** — run `scrub` + `_identifier_scores` over the 31 templates' report texts in
`SP/data_all.json` (these are de-identified-ish clinical reports) and 10 synthetic texts with planted names/DOBs;
confirm planted ones score ≥ `IDENTIFIER_MIN` after scrub only when the scrub missed them, and fewer than 10% of the
real reports are wrongly held back. Adjust `IDENTIFIER_MIN`; record numbers in the commit.
- [ ] **Step 6: Commit** `feat(evidence): store de-identified example reports with the template`.

### Task D5: Chat turns stored

**Files:**
- Modify: `B/main.py` `SkillSheetRefineRequest` (:743) + `/skill-sheet/refine`; `/skill-sheet/save`
- Modify: `F/routes/components/TemplateRefinePanel.svelte` (send `template_id`), `SkillSheetCreator.svelte` (send `chat_turns` on save)
- Test: `T/test_template_refine.py`

- [ ] **Step 1: Failing test** — append:

```python
def test_refine_with_a_template_records_the_turn(client, auth_headers, guided_template, db_session, monkeypatch):
    from rapid_reports_ai.database.models import TemplateChatTurn
    async def refine(self, skill_sheet, message, chat_history, api_key, rejection_context=None):
        return {"skill_sheet": skill_sheet, "response": "No change needed", "behavioral_claim": ""}
    monkeypatch.setattr("rapid_reports_ai.template_manager.TemplateManager.refine_skill_sheet", refine)
    client.post("/api/templates/skill-sheet/refine", headers=auth_headers, json={
        "skill_sheet": guided_template.template_config["skill_sheet"], "message": "keep it short",
        "template_id": str(guided_template.id)})
    turn = db_session.query(TemplateChatTurn).one()
    assert turn.instruction == "keep it short" and turn.applied is True
```

- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** — `SkillSheetRefineRequest.template_id: Optional[str] = None`. The refine endpoint gets
`db: Session = Depends(get_db)` and `current_user`; after vetting, when `request.template_id` is set and
`get_template(db, request.template_id, str(current_user.id))` exists, add
`TemplateChatTurn(template_id=t.id, instruction=request.message, response=<response sent>, applied=<bool>,
sheet_hash_before=sheet_hash(request.skill_sheet), sheet_hash_after=sheet_hash(<sheet returned>))` and commit (in a
try/except that logs). In `/skill-sheet/save`, store `request.chat_turns` (each `{instruction, response}`) the same
way after the template exists, `applied=True`. Frontend: `TemplateRefinePanel` refine body adds
`template_id: template.id`; `SkillSheetCreator` keeps its chat history and sends
`chat_turns: chatHistory.filter(m => m.role === 'user').map(...)` paired with the assistant reply (use the existing
`toWireChatHistory` data).
- [ ] **Step 4: Run** tests → pass.
- [ ] **Step 5: Commit** `feat(evidence): store chat-to-edit turns with the template`.

### Task D6: Template edit capture tied to its report

**Files:**
- Modify: `F/routes/components/TemplateForm.svelte:50-63` (copy listener), `:901` area (wrapper element)
- Modify: `B/quality_scoring.py:313-345`
- Test: `T/test_quality_scoring.py` (or the existing quality test file — `ls backend/tests | grep -i quality`)

- [ ] **Step 1: Failing backend test**:

```python
def test_template_final_is_the_latest_edited_version(db_session, test_user, guided_template):
    from rapid_reports_ai.database.models import Report, ReportVersion
    from rapid_reports_ai.quality_scoring import _assemble_case
    rep = Report(user_id=test_user.id, report_type="templated", report_content="edited text", model_used="m",
                 template_id=guided_template.id, input_data={})
    db_session.add(rep); db_session.flush()
    db_session.add_all([ReportVersion(report_id=rep.id, version_number=1, report_content="ai text", is_current=False),
                        ReportVersion(report_id=rep.id, version_number=2, report_content="edited text", is_current=True)])
    db_session.commit()
    case = _assemble_case(db_session, rep)
    assert case["ai_output"] == "ai text" and case["final"] == "edited text"
```

(Adapt field names to `ReportVersion`'s required columns; check `models.py:523`.)

- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** in `_assemble_case`, template branch:

```python
        versions = sorted(report.versions or [], key=lambda v: v.version_number) if hasattr(report, "versions") else []
        if len(versions) > 1:
            ai_output = versions[0].report_content or ai_output
            final = versions[-1].report_content
        else:
            final = None  # copy-time capture is not trusted (cross-report copies, fixed in TemplateForm 2026-10-13)
```

(If `Report` has no `versions` relationship, query `db.query(ReportVersion).filter_by(report_id=report.id)`.) Update
the docstring accordingly.

Frontend `TemplateForm.svelte`: wrap the report viewer (`:901`) in `<div bind:this={reportBoxEl}>…</div>` (declare
`let reportBoxEl: HTMLElement | null = null;`) and change the listener:

```js
	function handleReportCopy() {
		if (!feedbackAiOutput || !response || !reportBoxEl) return;
		const s = typeof window !== 'undefined' ? window.getSelection() : null;
		const sel = s?.toString() ?? '';
		// Only a copy made inside this report's viewer is this report's copy-time text (a copy elsewhere on the page
		// was recorded against this report before 2026-10-13).
		if (!s || !s.anchorNode || !reportBoxEl.contains(s.anchorNode)) return;
		if (sel && sel.length > (response || '').length * 0.3) {
			feedbackCopyCount++;
			feedbackCopied = true;
			captureFeedback('copied', sel);
		}
	}
```

and register/unregister with `onMount`/`onDestroy` instead of the bare `document.addEventListener` at module level.

- [ ] **Step 4: Run** backend test + suite; `bun run check` → pass.
- [ ] **Step 5: Commit** `fix(evidence): template copy capture scoped to its report; final from report versions`.

### Task D7: Quality scoring judges against the stamped sheet, grouped by path

**Files:**
- Modify: `B/quality_scoring.py` (`_assemble_case` template branch)
- Test: same file as D6

- [ ] **Step 1: Failing test**: a templated report with `generation_stamp={"sheet_hash": sheet_hash(OLD), "path":
"scratchpad"}` whose template's current sheet is NEW and a `TemplateVersion` holding OLD → `_assemble_case` returns
`skill_sheet == OLD` and `case["path"] == "scratchpad"`.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement**:

```python
def _sheet_for(db, report, current: str) -> str:
    """The sheet a template report was written from: by its generation stamp, from the template's versions;
    otherwise the current sheet (older reports, no stamp)."""
    want = (report.generation_stamp or {}).get("sheet_hash") if hasattr(report, "generation_stamp") else None
    if not want or sheet_hash(current) == want:
        return current
    for v in db.query(TemplateVersion).filter_by(template_id=report.template_id).order_by(TemplateVersion.version_number.desc()):
        s = (v.template_config or {}).get("skill_sheet") or ""
        if sheet_hash(s) == want:
            return s
    return current
```

Use it for `skill_sheet` in the template branch and add `"path": (report.generation_stamp or {}).get("path", "")` to
the returned case; store `path` in `dimensions_json` where the score row is written (`grep -n "dimensions_json"
quality_scoring.py`). Note in `docs/analytics/metabase/trace_and_quality.sql` a `path` column read from
`dimensions_json->>'path'` (edit the view SQL; applying it to prod Metabase is a ship step).
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `feat(quality): judge template reports against the sheet that wrote them; path group`.

---

# Phase E — Integration clean-up

### Task E1: No Phase 1 / options on the scratchpad path

**Files:**
- Modify: `B/template_lean.py:400-450`, `F/routes/components/TemplateForm.svelte:288-299`
- Test: `T/test_template_lean.py`

- [ ] **Step 1: Failing test** — append to `T/test_template_lean.py` (reuse its fake generator):

```python
async def test_stack_session_runs_no_options_job(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)
    routed = {"n": 0}

    async def counting_case_options(*a, **k):
        routed["n"] += 1
        return [], {}
    monkeypatch.setattr(tl, "case_options", counting_case_options)
    out = await tl.generate_template_report_lean(sheet=OLD_SHEET, scan_type="CT", findings="A 2 cm lesion.",
                                                 history="?lesion", case=CASE, signature="Dr A",
                                                 stack={"conclusion": "C.", "declined": []})
    await asyncio.sleep(0)
    assert routed["n"] == 0
    assert out["report_content"].startswith(REPORT)
```

(`_gen_fakes`, `OLD_SHEET`, `CASE`, `REPORT` are this file's existing helpers; add `import asyncio` if absent.)

- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** in `generate_template_report_lean`: wrap the options job:

```python
    opts_t = asyncio.ensure_future(opts()) if stack is None else None   # scratchpad: the checklist confirmed all
```

and wherever `opts_t` is awaited, guard `if opts_t is not None`, returning no options and a job record
`{"skipped": "scratchpad"}`. Frontend `TemplateForm.svelte:289`: change the condition to
`if (selectedTemplate?.id && !hybridStack) {` (the scratchpad never uses Phase 1).
- [ ] **Step 4: Run** `.venv/bin/pytest T/test_template_lean.py T/test_template_generate_endpoint.py -q`; `bun run check` → pass.
- [ ] **Step 5: Commit** `fix(template): no Phase 1 or options on the scratchpad path`.

### Task E2: Fallback options read sections and terms from the parse

**Files:**
- Modify: `B/template_lean.py:415-416, 438-441`, `B/template_pipeline.py:303`
- Test: `T/test_template_lean.py`

- [ ] **Step 1: Failing test**: a grammar sheet whose findings section is `REPORT` and impression `OPINION`; assert
`case_options` (monkeypatched to capture kwargs) receives `findings_section="REPORT", impression_section="OPINION"`.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement**: before `opts()`, compute from `template_structure(config)` (or `parse_sheet`):

```python
    st = template_structure(template_config)
    fsec = next((s.name for s in st.sections if s.role == "findings"), "FINDINGS") if st else "FINDINGS"
    isec = next((s.name for s in st.sections if s.role == "impression"), "IMPRESSION") if st else "IMPRESSION"
    if st and not style:
        style = "\n".join(f"TERM {t.kind.upper()} \"{t.term}\"" for t in st.terminology)
```

and pass `fsec`/`isec` instead of the literals (check `st.terminology` item field names in
`template_sheet_structure.py` before writing the join). Same for `template_pipeline.py:303` if it builds style from
`"Terminology Rules"`.
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `fix(template): fallback options use the parsed sections and terms`.

### Task E3: Shadow — verified, no change

The backend never runs today's template path in shadow on a scratchpad Generate (`RR_STACK_SHADOW_RATE` only drives
the frontend's old Structured-text build at session end). No task; record in the PR description.

---

# Phase F — Ship

### Task F1: Keep the conversion outputs somewhere durable

- [ ] Ask Hassan for a private folder outside the repo. Copy `SP/final/`, `SP/data_all.json`, `SP/apply_prod.py`,
`SP/e2e.py` there (`cp -R`). Production data never enters the repo.

### Task F2: Apply Hassan's template-content decisions to the 31 sheets

- [ ] For each decision in `SP/final/SUMMARY.md` ("Decisions for Hassan"), apply his answer to the matching
`<slug>.final.md`; lint with `SP/lint.py` (usable, 0 errors); re-run that template's e2e once
(`SP/e2e.py`). Record each change in its `handread.md`.

### Task F3: The production write script in the repo

**Files:**
- Create: `B/scripts/template_upgrade_apply.py` (copy of `SP/apply_prod.py`, which already: dry-run default, skips
  sheets changed since the pull or not usable, snapshots a pre-upgrade TemplateVersion, writes a JSON backup next to
  the manifest, soft-deletes active templates with no generation mode)
- Test: `T/test_template_upgrade_apply.py`

- [ ] **Step 1: Failing test**: build an in-memory DB with one guided free-form template (hash H), one legacy
template (no generation_mode), a manifest `[{"template_id", "old_sheet_hash": H, "new_sheet": GOOD}]`; run the
script's `main(manifest_path, apply=True, db=db_session)` (refactor the module into a `main()` taking a session) →
the guided template holds GOOD, a TemplateVersion holds the old sheet, the legacy template `is_active is False`, a
backup file exists. A second test: a stale hash → skipped, nothing written.
- [ ] **Step 2: Run** → fail. **Step 3: Implement** (refactor into `main(manifest_path, apply, db=None)`; run the
save function's `vet_sheet(origin="rebuild")` on each new sheet instead of only `parse_sheet`, skipping refused
ones). **Step 4: Run** → pass. **Step 5: Commit** `feat(ship): template upgrade apply script (dry-run default)`.
- [ ] **Step 6: Build the manifest** in the private folder: for each slug, `{"template_id", "old_sheet_hash":
sheet_hash(data_all skill_sheet), "new_sheet": <final.md>}`.

### Task F4: The banner

**Files:**
- Create: `F/lib/components/UpgradeBanner.svelte`, `F/lib/components/UpgradeBanner.svelte.test.ts`
- Modify: `F/routes/+layout.svelte`

- [ ] **Step 1: Failing test** `UpgradeBanner.svelte.test.ts`:

```ts
import { describe, expect, it, beforeEach } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import UpgradeBanner from './UpgradeBanner.svelte';

describe('UpgradeBanner', () => {
	beforeEach(() => localStorage.clear());
	it('shows the upgrade message until dismissed', async () => {
		render(UpgradeBanner);
		await expect.element(page.getByText('Your templates have been upgraded to the new workflow.')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Dismiss' }).click();
		await expect.element(page.getByRole('status')).not.toBeInTheDocument();
		expect(localStorage.getItem('rr_banner_template_upgrade_2026_10')).toBe('1');
	});
});
```

- [ ] **Step 2: Run** `cd frontend && bunx vitest --run src/lib/components/UpgradeBanner.svelte.test.ts` → fail.
- [ ] **Step 3: Implement** `UpgradeBanner.svelte` (Svelte 5):

```svelte
<script lang="ts">
	const KEY = 'rr_banner_template_upgrade_2026_10';
	let dismissed = $state(read());
	function read(): boolean {
		try { return localStorage.getItem(KEY) === '1'; } catch { return false; }
	}
	function dismiss() {
		dismissed = true;
		try { localStorage.setItem(KEY, '1'); } catch { /* storage blocked */ }
	}
</script>

{#if !dismissed}
	<div role="status" class="flex items-start gap-3 bg-sky-950/60 border-b border-sky-800 px-4 py-2 text-sm text-sky-100">
		<p class="flex-1">
			Your templates have been upgraded to the new workflow. If a template doesn't feel right, you can create a
			fresh one from a few example reports.
		</p>
		<button class="text-sky-300 hover:text-sky-100" onclick={dismiss} aria-label="Dismiss">Dismiss</button>
	</div>
{/if}
```

`F/routes/+layout.svelte`: import it and render `<UpgradeBanner />` immediately before `{@render children?.()}`.
- [ ] **Step 4: Run** the test and `bun run check` → pass.
- [ ] **Step 5: Commit** `feat(ship): template upgrade banner`.

### Task F5: Housekeeping, review, merge

- [ ] Remove the `RR_STACK_DEBUG` trace (`grep -rn "RR_STACK_DEBUG" backend/src` — 2 sites) and its tests; commit.
- [ ] Full suites: `cd backend && .venv/bin/pytest -q 2>&1 | tail -2`; `cd frontend && bun run test 2>&1 | tail -3 && bun run check 2>&1 | tail -3`.
- [ ] Independent review of `feat/stack-tighten` + `feat/template-stack` (everything since PR #31's last review) with
superpowers:requesting-code-review; fix findings; re-review until "ready".
- [ ] Merge into `local/test-combined`, restart :8000 (command in memory `project_scratchpad_v2.md`), live smoke:
create a template from 3 example reports, refine it twice, run a scratchpad session, Generate; confirm the stamps,
the gate fields and a stored example row in the local DB.
- [ ] On Hassan's go-ahead only: fold into PR #31 (or a new PR), update its description (include E3 note and the
fallback result), push, merge. Then at deploy: run `template_upgrade_apply.py` dry run with `railway run`, show
Hassan the output, apply on his yes; apply the Metabase view change.

---

## Self-review notes (resolved)

- Spec coverage: block 1 → C2–C4; block 2 → B1–B3, C5; block 3 → C1; block 4 → D1–D7; integration clean-up → B3
  (coverage), E1, E2, D7 (quality), E3 (shadow verified); ship steps → F1–F5; out-of-scope runtime bugs → A1–A4;
  fallback comparison → A5. Spec wording to align: "flagged spans are removed before storage" → the code backstop
  removes identifier shapes; a still-flagged example is not stored (D4). Update the spec in the same commit as D4.
- Signatures used across tasks: `vet_sheet(sheet, origin, previous="") -> VetOutcome(status, sheet, message,
  dropped, coverage_sections)`; `check_units(st) -> List[UnitFailure(line, text, reason)]`;
  `assumed(..., suppressions=, clinical_history=) -> AssumedResult(assumed, dropped, ms, error)`;
  `template_suppressions(st) -> list[(condition, sentence)]`; `preview_report(sheet, scan_type, history, dictation,
  conclusion="", declined=None) -> dict`; `write_sheet(examples, scan_type, protocol_notes="") -> dict`;
  `generation_stamp(template_id, config, path) -> dict`.
