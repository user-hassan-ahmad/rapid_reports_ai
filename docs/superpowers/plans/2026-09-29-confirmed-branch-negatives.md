# Confirmed-Branch Negatives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the dictation confirms a differential branch, the report states that branch's standard negatives in FINDINGS (policy 1). Ambiguous ones are offered as FINDINGS-scoped options. The impression carries a negative only when it changes interpretation.

**Architecture:** An opt-in analyser directive adds an "If confirmed" list to the sheet. `compile_brief` parses it and runs each candidate through the existing Qwen negatives call. It reads Jev's existing `present` score for the branch and routes each candidate by rule C: stated, offered, do-not-assert or dropped. Stated negatives become KEEP mandatory negatives. Offered ones become `confirmed_negative` options with `section: "FINDINGS"`. The frontend hides that kind until the side-panel sub-project ships.

**Tech Stack:** Python 3.11, pydantic 2, pydantic-ai, pytest + pytest-asyncio (backend); SvelteKit + vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-09-29-policy1-confirmed-branch-negatives-design.md`

**Correction to the spec:** `get_analyser_prompt` returns the Anthropic prompt before it applies any directive. Directives therefore reach only the open-weights prompt, which is the one production uses (Qwen). The Anthropic analyser is not in production. This plan does not change it.

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `backend/src/rapid_reports_ai/quick_report_analyser.py` | modify | `CONFIRMED_NEGATIVES` directive text + `DIRECTIVES` entry |
| `backend/src/rapid_reports_ai/quick_report_brief.py` | modify | parse candidates, route (rule C), merge into negatives / options / plan, decisions |
| `backend/src/rapid_reports_ai/quick_report_generator.py` | modify | options pass-through with `section`; return `brief_text` |
| `backend/src/rapid_reports_ai/quick_report_api.py` | modify | persist `brief` on the candidate |
| `frontend/src/lib/utils/impressionOptions.ts` | modify | `ReportOption` gains kind/section; `panelOptions()` filter |
| `frontend/src/routes/components/IntelliDictateTab.svelte` | modify | use `panelOptions()` |
| `backend/tests/test_confirmed_negatives.py` | create | all backend unit tests for this feature |
| `frontend/src/lib/utils/impressionOptions.test.ts` | modify | `panelOptions` test |
| `backend/src/rapid_reports_ai/scripts/confirmed_negatives_eval.py` | create | calibration dump + A/B evaluation runner |
| `backend/test_cases/silent_staging.json` | create | 6 silent-staging + 2 control cases |
| `docs/model-migration/parameter-ledger.md` | modify | L-45 predictions, then results |

Run all backend commands from `backend/`. Run frontend commands from `frontend/`.

---

### Task 1: Analyser directive `confirmed_negatives`

**Files:**
- Modify: `backend/src/rapid_reports_ai/quick_report_analyser.py` (after `PRUNE_V1`; `DIRECTIVES` dict)
- Test: `backend/tests/test_confirmed_negatives.py`

- [ ] **Step 1: Write the failing test**

```python
"""Policy 1 for confirmed branches (spec 2026-09-29-policy1-confirmed-branch-negatives-design)."""
from __future__ import annotations

import pytest

from rapid_reports_ai import quick_report_analyser as qa


def test_confirmed_negatives_is_an_opt_in_directive():
    model = "qwen-3.8-27b"
    prod = qa.get_analyser_prompt(model, directives=qa.PRODUCTION_DIRECTIVES)
    arm_b = qa.get_analyser_prompt(model, directives=qa.PRODUCTION_DIRECTIVES + ("confirmed_negatives",))
    assert "**If confirmed:**" not in prod
    assert "**If confirmed:**" in arm_b
    assert "(core | contextual)" in arm_b
    assert "confirmed_negatives" not in qa.PRODUCTION_DIRECTIVES
```

- [ ] **Step 2: Run it and check it fails**

Run: `poetry run pytest tests/test_confirmed_negatives.py -q`
Expected: FAIL with `ValueError: unknown directive 'confirmed_negatives'`

- [ ] **Step 3: Implement**

In `quick_report_analyser.py`, directly after the `PRUNE_V1 = """…"""` block, add:

```python
# Policy 1 for confirmed branches (spec 2026-09-29): the sheet is written before anything is
# dictated, so its mandatory negatives answer the question as asked. The negatives a consultant
# states once a diagnosis is confirmed (extent, spread, complications) had no carrier. The brief
# promotes these only when Jev finds the branch confirmed.
CONFIRMED_NEGATIVES = """

---

## If confirmed — negatives that follow a confirmed diagnosis

Add one bullet to the Companion Matrix, directly after Mandatory negatives:

- **If confirmed:** (negatives stated only when the dictation confirms the branch)
  - <differential name exactly as written in Differentials in scope> → "<negative in final report form>" (core | contextual)

For each differential tagged *visible on this technique: yes* whose confirmation would change
management through its extent, spread or complications, list the negatives a consultant states
once that diagnosis is made: the absence of each extension, spread or complication this
technique shows and the next management step depends on. One finding per negative: no "or",
no comma-separated list. Tag each negative core when any consultant states it once the
diagnosis is made, contextual when stating it depends on the case or on local practice. At most
three per differential and twelve in total. Never repeat a mandatory negative. Never write a
negative denying something the confirmed diagnosis is expected to cause.
"""
```

In `DIRECTIVES`, add the entry after `"prune_v1"`:

```python
    "prune_v1": lambda: PRUNE_V1,
    "confirmed_negatives": lambda: CONFIRMED_NEGATIVES,
```

- [ ] **Step 4: Run it and check it passes**

Run: `poetry run pytest tests/test_confirmed_negatives.py -q`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/quick_report_analyser.py tests/test_confirmed_negatives.py
git commit -m "feat(analyser): opt-in confirmed_negatives directive — If confirmed list per branch"
```

---

### Task 2: Parse candidates and route by rule C (pure functions)

**Files:**
- Modify: `backend/src/rapid_reports_ai/quick_report_brief.py` (items section, after `_recommendations`)
- Test: `backend/tests/test_confirmed_negatives.py`

- [ ] **Step 1: Write the failing tests** (append to the test file)

```python
from rapid_reports_ai import quick_report_brief as qb

DIFFS = [
    "Acute subdural — crescentic hyperdensity *(visible on this technique: yes)*",
    "Epidural — biconvex hyperdensity *(visible on this technique: yes)*",
]
IF_CONFIRMED_LINES = [
    "- **If confirmed:** (negatives stated only when the dictation confirms the branch)",
    '  - Acute subdural → "No midline shift" (core)',
    '  - Acute subdural → "No uncal herniation" (contextual)',
    '  - Epidural -> "No skull fracture"',
    '  - Haemorrhagic contusion → "No contrecoup injury" (core)',
]


def test_candidates_parse_branch_negative_and_tag():
    cands, unmatched = qb.parse_confirmed(IF_CONFIRMED_LINES, DIFFS)
    assert [(c.branch, c.text, c.tag, c.diff_index) for c in cands] == [
        ("Acute subdural", "No midline shift", "core", 0),
        ("Acute subdural", "No uncal herniation", "contextual", 0),
        ("Epidural", "No skull fracture", "contextual", 1),   # missing tag -> contextual
    ]
    assert unmatched == 1                                     # no such differential


@pytest.mark.parametrize("label,present,tag,outcome", [
    ("keep", 0.3, "core", "dropped"),                # branch not confirmed
    ("contradicted", 0.95, "core", "dropped"),       # the dictation says otherwise
    ("expected", 0.95, "core", "do_not_assert"),     # the diagnosis causes it
    ("expected", 0.6, "contextual", "do_not_assert"),
    ("keep", 0.95, "core", "stated"),
    ("keep", 0.95, "contextual", "offered"),
    ("keep", 0.6, "core", "offered"),                # branch borderline
])
def test_route_confirmed_rule_c(label, present, tag, outcome):
    assert qb.route_confirmed(label, present, tag) == outcome
```

- [ ] **Step 2: Run them and check they fail**

Run: `poetry run pytest tests/test_confirmed_negatives.py -q`
Expected: FAIL with `AttributeError: module 'rapid_reports_ai.quick_report_brief' has no attribute 'parse_confirmed'`

- [ ] **Step 3: Implement**

In `quick_report_brief.py`, directly after `def _recommendations(...)`, add:

```python
# Policy 1 for confirmed branches: a branch Jev finds present brings the negatives the analyser
# listed for it. Cut-offs on Jev's `present` score; the high one is calibrated (ledger L-45).
PRESENT_LOW = 0.5
PRESENT_HIGH = 0.8
MAX_CONFIRMED_OPTIONS = 4
_CONFIRMED = re.compile(r'^\s+-\s+(.+?)\s*(?:→|->)\s*"([^"]+)"\s*(?:\((core|contextual)\))?')


@dataclass
class Candidate:
    branch: str
    text: str
    tag: str          # "core" | "contextual"
    diff_index: int   # index into differential_lines(), whose Jev key is f"d{diff_index}"


def _diff_name(line: str) -> str:
    return re.split(r"\s+—\s+|\s+\*\(", line, maxsplit=1)[0].strip().lower()


def parse_confirmed(lines: List[str], diffs: List[str]) -> tuple[List[Candidate], int]:
    """The If-confirmed bullet's lines as candidates matched to a differential by name."""
    names = {_diff_name(d): i for i, d in enumerate(diffs)}
    cands, unmatched = [], 0
    for line in lines[1:]:
        m = _CONFIRMED.match(line)
        if not m:
            continue
        branch, text, tag = m.group(1).strip(), m.group(2).strip().rstrip("."), m.group(3) or "contextual"
        k = names.get(branch.lower())
        if k is None:
            unmatched += 1
            continue
        cands.append(Candidate(branch, text, tag, k))
    return cands, unmatched


def route_confirmed(label: str, present: float, tag: str) -> str:
    """Rule C: stated only when the branch is clearly confirmed and the negative is core."""
    if present < PRESENT_LOW or label == "contradicted":
        return "dropped"
    if label == "expected":
        return "do_not_assert"
    if present >= PRESENT_HIGH and tag == "core":
        return "stated"
    return "offered"
```

- [ ] **Step 4: Run them and check they pass**

Run: `poetry run pytest tests/test_confirmed_negatives.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/quick_report_brief.py tests/test_confirmed_negatives.py
git commit -m "feat(brief): parse If-confirmed candidates and route them by rule C"
```

---

### Task 3: Integrate into `compile_brief` (negatives, options, drop bullet, decisions)

**Files:**
- Modify: `backend/src/rapid_reports_ai/quick_report_brief.py` (`DROP_TOP_BULLETS`, `compile_brief`)
- Modify: `backend/tests/test_quick_report_brief.py` (`fake_plan` accepts a 5th argument)
- Test: `backend/tests/test_confirmed_negatives.py`

- [ ] **Step 1: Write the failing test** (append)

```python
from rapid_reports_ai.quick_report_brief import NegativeDecision, QwenDecisions

SHEET_C = '''# Skill Sheet: CT head — head injury

## Clinical Lane
- **Question:** Intracranial injury?
- **Differentials in scope:**
  - **Aetiology (if haemorrhage confirmed):**
    - Acute subdural — crescentic hyperdensity *(visible on this technique: yes)*
    - Epidural — biconvex hyperdensity *(visible on this technique: yes)*

## Structural Pattern
- **Normal-study path:** "The orbits are clear."

## Companion Matrix
- **Mandatory negatives:** (one line each, one finding each)
  - "No skull fracture" (trauma)
- **If confirmed:** (negatives stated only when the dictation confirms the branch)
  - Acute subdural → "No midline shift" (core)
  - Acute subdural → "No uncal herniation" (contextual)
  - Acute subdural → "No effacement of the basal cisterns" (core)
  - Acute subdural → "No subfalcine herniation" (core)
  - Epidural → "No venous sinus involvement" (core)

## Impression Exemplars
- **Abnormal exemplar:** "Acute subdural."
'''


def _stub_c(monkeypatch, subdural_present: float, qwen_negs):
    async def fake_jev(state, questions):
        out = {k: {"noul": 0.1} for k in questions}
        out["d0"] = {"noul": subdural_present}
        return out
    async def fake_qwen(state, negs, normals, measurements):
        fake_qwen.negs = negs
        return QwenDecisions(negatives=qwen_negs, affected_normals=[], applicable_measurements=[])
    async def no_split(negs):
        return [[n] for n in negs]
    async def no_plan(*a):
        raise RuntimeError("no plan")
    monkeypatch.setattr(qb, "_jev", fake_jev)
    monkeypatch.setattr(qb, "_qwen", fake_qwen)
    monkeypatch.setattr(qb, "_split_bundled", no_split)
    monkeypatch.setattr(qb, "_plan", no_plan)
    return fake_qwen


@pytest.mark.asyncio
async def test_confirmed_branch_negatives_are_stated_offered_or_labelled(monkeypatch):
    # candidates follow the one mandatory negative in Qwen's list: indices 1..5
    fq = _stub_c(monkeypatch, 0.95, [
        NegativeDecision(index=0, action="keep"),
        NegativeDecision(index=1, action="keep"),                      # core -> stated
        NegativeDecision(index=2, action="keep"),                      # contextual -> offered
        NegativeDecision(index=3, action="expected", dictated_finding="10 mm subdural"),
        NegativeDecision(index=4, action="contradicted", dictated_finding="subfalcine herniation"),
        NegativeDecision(index=5, action="keep"),                      # epidural branch not present
    ])
    b = await qb.compile_brief(SHEET_C, "CT head", "10 mm right acute subdural. Subfalcine herniation.")
    t = b.text
    assert fq.negs[1:] == ["No midline shift", "No uncal herniation", "No effacement of the basal cisterns",
                           "No subfalcine herniation", "No venous sinus involvement"]
    assert 'KEEP: "No midline shift" (confirmed: Acute subdural)' in t
    assert 'DO NOT ASSERT: "No effacement of the basal cisterns" — expected consequence of: 10 mm subdural' in t
    assert "No subfalcine herniation" not in t and "No venous sinus involvement" not in t
    assert "No uncal herniation" not in t                              # offered, not in the brief
    assert "If confirmed" not in t
    opts = [o for o in b.decisions["options"] if o["kind"] == "confirmed_negative"]
    assert opts == [{"kind": "confirmed_negative", "section": "FINDINGS", "text": "No uncal herniation",
                     "branch": "Acute subdural", "reason": "contextual"}]
    routes = {c["text"]: c["outcome"] for c in b.decisions["confirmed_negatives"]}
    assert routes == {"No midline shift": "stated", "No uncal herniation": "offered",
                      "No effacement of the basal cisterns": "do_not_assert",
                      "No subfalcine herniation": "dropped", "No venous sinus involvement": "dropped"}
    sources = {n["text"]: n["source"] for n in b.decisions["negatives"]}
    assert sources["No skull fracture"] == "sheet" and sources["No midline shift"] == "confirmed:Acute subdural"


@pytest.mark.asyncio
async def test_borderline_branch_offers_its_core_negatives_with_a_reason(monkeypatch):
    _stub_c(monkeypatch, 0.6, [NegativeDecision(index=i, action="keep") for i in range(6)])
    b = await qb.compile_brief(SHEET_C, "CT head", "Possible thin right subdural.")
    offered = [o for o in b.decisions["options"] if o["kind"] == "confirmed_negative"]
    assert len(offered) == qb.MAX_CONFIRMED_OPTIONS                     # 4 of the 4 subdural candidates
    assert offered[0]["reason"] == "branch borderline (p=0.60)"
    assert "(confirmed:" not in b.text
```

In `backend/tests/test_quick_report_brief.py`, change the stub signature so the new fifth argument is accepted:

```python
    async def fake_plan(scan_type, history, items, recs, cand_negs=()):
```

- [ ] **Step 2: Run them and check they fail**

Run: `poetry run pytest tests/test_confirmed_negatives.py -q`
Expected: the two new tests FAIL (`KEY_ERROR` / assertion on `confirmed_negatives`)

- [ ] **Step 3: Implement**

a) Drop the raw bullet from what the generator sees:

```python
DROP_TOP_BULLETS = {"Out of scope", "Modality non-assessables", "In-scope companions", "Out-of-scope suppressed",
                    "If confirmed"}
```

b) In `compile_brief`, after `diffs = differential_lines(secs)`, add:

```python
    conf_bullet = _bullet(matrix, "If confirmed")
    cands, unmatched = parse_confirmed(conf_bullet.lines, diffs) if conf_bullet else ([], 0)
```

c) Send the candidates through the same Qwen call. Replace the `_qwen(...)` argument
`[n for n, _ in negs]` with `[n for n, _ in negs] + [c.text for c in cands]`. Pass the
candidates to the plan by changing `plan_or_none`'s call to:

```python
            return await _plan(scan_type, clinical_history, items, recs, [c.text for c in cands])
```

d) Add `"confirmed_negatives": [], "confirmed_negatives_unmatched": unmatched` to the initial
`decisions` dict. In the mandatory-negatives loop, add `"source": "sheet"` to the appended dict:

```python
        decisions["negatives"].append({"text": text, "action": action, "dictated_finding": d.dictated_finding if d else "",
                                       "source": "sheet"})
```

e) **Replace** the two lines `if neg_bullet:` / `neg_bullet.lines = neg_lines` (end of the
mandatory-negatives block) with the routing below. The routing ends with the same assignment:

```python
    # Confirmed-branch negatives (policy 1): stated as KEEP, labelled DO NOT ASSERT, or offered.
    stated: List[str] = []
    n_offered = 0
    for j, c in enumerate(cands):
        d = qneg.get(len(negs) + j)
        label = d.action if d else "keep"
        p = score(f"d{c.diff_index}")
        outcome = route_confirmed(label, p, c.tag)
        if outcome == "offered":
            if n_offered >= MAX_CONFIRMED_OPTIONS:
                outcome = "dropped"
            else:
                n_offered += 1
                decisions["options"].append({"kind": "confirmed_negative", "section": "FINDINGS", "text": c.text,
                                             "branch": c.branch,
                                             "reason": "contextual" if p >= PRESENT_HIGH else f"branch borderline (p={p:.2f})"})
        decisions["confirmed_negatives"].append({"branch": c.branch, "text": c.text, "tag": c.tag, "qwen": label,
                                                 "present": round(p, 3), "outcome": outcome})
        if outcome == "stated":
            stated.append(c.text)
            neg_lines.append(f'  - KEEP: "{c.text}" (confirmed: {c.branch})')
            decisions["negatives"].append({"text": c.text, "action": "keep", "dictated_finding": "",
                                           "source": f"confirmed:{c.branch}"})
        elif outcome == "do_not_assert":
            neg_lines.append(f'  - DO NOT ASSERT: "{c.text}" — expected consequence of: {d.dictated_finding}')
    if neg_bullet:
        neg_bullet.lines = neg_lines
    elif matrix and len(neg_lines) > 0:
        matrix.bullets.insert(0, Bullet("Mandatory negatives",
                                        ["- **Mandatory negatives:** (reconciled with this dictation; one finding each)"] + neg_lines))
```

Note: `neg_lines` starts empty when the sheet has no Mandatory negatives bullet. The `elif`
branch then creates the bullet with the header line the normal path writes.

- [ ] **Step 4: Run the brief tests and check they pass**

Run: `poetry run pytest tests/test_confirmed_negatives.py tests/test_quick_report_brief.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/quick_report_brief.py tests/test_confirmed_negatives.py tests/test_quick_report_brief.py
git commit -m "feat(brief): confirmed-branch negatives stated, offered or labelled; raw list never reaches the generator"
```

---

### Task 4: Impression plan — carry a negative only when it changes interpretation

**Files:**
- Modify: `backend/src/rapid_reports_ai/quick_report_brief.py` (`ImpressionPlan`, `PLAN_SYS`, `_plan`, plan block in `compile_brief`)
- Test: `backend/tests/test_confirmed_negatives.py`

- [ ] **Step 1: Write the failing test** (append)

```python
@pytest.mark.asyncio
async def test_plan_carries_only_stated_negatives_it_chose(monkeypatch):
    _stub_c(monkeypatch, 0.95, [NegativeDecision(index=i, action="keep") for i in range(6)])
    seen = {}
    async def fake_plan(scan_type, history, items, recs, cand_negs=()):
        seen["cands"] = list(cand_negs)
        # 0 = "No midline shift" (stated), 1 = "No uncal herniation" (offered): only 0 may be carried
        return qb.ImpressionPlan(recommendations=[], impression=[0], carry_negatives=[0, 1])
    monkeypatch.setattr(qb, "_plan", fake_plan)
    b = await qb.compile_brief(SHEET_C, "CT head", "10 mm right acute subdural")
    assert seen["cands"][:2] == ["No midline shift", "No uncal herniation"]
    carry = b.text.split("Carry forward")[1].split("\n")[0]
    assert '"No midline shift"' in carry and "No uncal herniation" not in carry
    assert b.decisions["impression_plan"]["carry_negatives"] == ["No midline shift"]


def test_plan_prompt_keeps_negatives_out_of_the_impression_by_default():
    assert "carry_negatives" in qb.PLAN_SYS
    assert "changes the interpretation of a carried finding" in qb.PLAN_SYS
```

- [ ] **Step 2: Run them and check they fail**

Run: `poetry run pytest tests/test_confirmed_negatives.py -q`
Expected: FAIL (`ImpressionPlan` has no `carry_negatives`)

- [ ] **Step 3: Implement**

a) `ImpressionPlan`: add the field, and add it to the before-validator list:

```python
    findings_only: List[int] = []
    carry_negatives: List[int] = []
    @field_validator("recommendations", "impression", "optional_impression", "findings_only", "carry_negatives", mode="before")
```

b) Append to `PLAN_SYS` (inside the string, after the "A finding may be in none of the lists…" sentence):

```
carry_negatives — the numbers of CANDIDATE NEGATIVES the impression must carry. A negative is carried only when it changes the interpretation of a carried finding; never carry a negative for any other reason. Most cases carry none.
```

c) `_plan` gains the candidates:

```python
async def _plan(scan_type: str, clinical_history: str, items: List[str], recs: List[str],
                cand_negs: List[str] = ()) -> ImpressionPlan:
    user = (f"SCAN TYPE: {scan_type}\nCLINICAL QUESTION (context only): {clinical_history or '(not given)'}\n\n"
            "DICTATED FINDINGS:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(items))
            + "\n\nCANDIDATE RECOMMENDATIONS:\n" + ("\n".join(f"{i}. {t}" for i, t in enumerate(recs)) or "(none)")
            + "\n\nCANDIDATE NEGATIVES — apply only if their diagnosis is confirmed:\n"
            + ("\n".join(f"{i}. {t}" for i, t in enumerate(cand_negs)) or "(none)"))
```

d) In the plan block of `compile_brief`, keep only stated carries. Replace
`carry, only = pick(plan.impression), pick(plan.findings_only)` with:

```python
        carry, only = pick(plan.impression), pick(plan.findings_only)
        carry_negs = [cands[i].text for i in dict.fromkeys(plan.carry_negatives)
                      if 0 <= i < len(cands) and cands[i].text in stated]
        carry = carry + carry_negs
```

and add `"carry_negatives": carry_negs` to the `decisions["impression_plan"]` dict.

Note: the plan block runs after the routing block from Task 3, so `stated` is already filled.
If the plan block comes before it in the file, move the routing block above the plan block.

- [ ] **Step 4: Run them and check they pass**

Run: `poetry run pytest tests/test_confirmed_negatives.py tests/test_quick_report_brief.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/quick_report_brief.py tests/test_confirmed_negatives.py
git commit -m "feat(brief): impression plan carries a confirmed negative only when it changes interpretation"
```

---

### Task 5: Options payload — section on every option, confirmed negatives verbatim

**Files:**
- Modify: `backend/src/rapid_reports_ai/quick_report_generator.py` (`_write_options`, return dict)
- Test: `backend/tests/test_confirmed_negatives.py`

- [ ] **Step 1: Write the failing test** (append)

```python
from rapid_reports_ai import quick_report_generator as qrg


@pytest.mark.asyncio
async def test_options_carry_a_section_and_confirmed_negatives_skip_the_writer(monkeypatch):
    calls = []
    async def fake_run(**kw):
        calls.append(kw["user_prompt"])
        class R:
            output = qrg._OptionSentences(sentences=["MRI brain is recommended."])
        return R()
    monkeypatch.setattr(qrg, "_run_agent_with_model", fake_run)
    opts = [{"kind": "recommendation", "text": "IMAGING: MRI brain", "reason": "either way"},
            {"kind": "confirmed_negative", "section": "FINDINGS", "text": "No uncal herniation",
             "branch": "Acute subdural", "reason": "contextual"}]
    out = await qrg._write_options(opts, "findings", "CT")
    assert "No uncal herniation" not in calls[0]
    assert out[0] == {"id": "opt0", "kind": "recommendation", "section": "IMPRESSION",
                      "sentence": "MRI brain is recommended.", "reason": "either way", "source": "IMAGING: MRI brain"}
    assert out[1] == {"id": "cn0", "kind": "confirmed_negative", "section": "FINDINGS",
                      "sentence": "No uncal herniation.", "reason": "contextual",
                      "source": "No uncal herniation", "branch": "Acute subdural"}


@pytest.mark.asyncio
async def test_confirmed_negatives_survive_when_the_writer_fails(monkeypatch):
    async def boom(**kw):
        raise RuntimeError("down")
    monkeypatch.setattr(qrg, "_run_agent_with_model", boom)
    opts = [{"kind": "impression", "text": "Small effusion", "reason": ""},
            {"kind": "confirmed_negative", "section": "FINDINGS", "text": "No uncal herniation",
             "branch": "Acute subdural", "reason": "contextual"}]
    out = await qrg._write_options(opts, "findings", "CT")
    assert [o["id"] for o in out] == ["cn0"]
```

- [ ] **Step 2: Run them and check they fail**

Run: `poetry run pytest tests/test_confirmed_negatives.py -q`
Expected: FAIL (the writer receives the confirmed negative; no `section` key)

- [ ] **Step 3: Implement** (replace `_write_options` whole)

```python
async def _write_options(options: List[dict], findings: str, scan_type: str) -> List[dict]:
    """Reporter-choice items. Impression and recommendation items get one sentence each from a
    writer call beside the generator; confirmed-branch negatives are already in report form and
    pass through. On a writer failure only the written items are lost."""
    direct = [o for o in options if o["kind"] == "confirmed_negative"]
    to_write = [o for o in options if o["kind"] != "confirmed_negative"]
    passed = [{"id": f"cn{i}", "kind": o["kind"], "section": o.get("section", "FINDINGS"),
               "sentence": o["text"].rstrip(".") + ".", "reason": o.get("reason", ""), "source": o["text"],
               "branch": o.get("branch", "")}
              for i, o in enumerate(direct)]
    if not to_write:
        return passed
    try:
        items = "\n".join(f"{i}. [{o['kind']}] {o['text']}" for i, o in enumerate(to_write))
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=MODEL_CONFIG["QUICK_REPORT_GENERATOR"], output_type=_OptionSentences,
            system_prompt=("Write one sentence for the IMPRESSION of a radiology report for each numbered item, in order. "
                           "A 'recommendation' item becomes a recommendation sentence naming the test or service and, where "
                           "the item gives one, its urgency; drop any condition in brackets once it is met. An 'impression' "
                           "item becomes a compressed statement of that dictated finding. Use only facts in the item and the "
                           "findings. British English, consultant voice, no preamble. Return JSON {\"sentences\": [...]}."),
            user_prompt=f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}\n\nITEMS:\n{items}",
            api_key="",
            model_settings={"temperature": 0.2, "max_tokens": 2000, "reasoning_effort": "none"}), 10.0)
        sentences = r.output.sentences
    except Exception as e:
        logger.warning("option sentences failed (%s: %s); no written options offered", type(e).__name__, str(e)[:200])
        return passed
    written = [{"id": f"opt{i}", "kind": o["kind"], "section": "IMPRESSION", "sentence": s.strip(),
                "reason": o.get("reason", ""), "source": o["text"]}
               for i, (o, s) in enumerate(zip(to_write, sentences)) if s and s.strip()]
    return written + passed
```

Also in `generate_quick_report`'s return dict, add the brief text next to `brief_decisions`:

```python
            "brief_text": brief.text if brief else None,
```

- [ ] **Step 4: Run and check they pass (including the existing options test)**

Run: `poetry run pytest tests/test_confirmed_negatives.py tests/test_quick_report_brief.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/quick_report_generator.py tests/test_confirmed_negatives.py
git commit -m "feat(options): every option names its section; confirmed negatives pass through verbatim"
```

---

### Task 6: Persist the brief on the candidate

**Files:**
- Modify: `backend/src/rapid_reports_ai/quick_report_api.py` (`_run_one_generator` success dict)
- Test: `backend/tests/test_confirmed_negatives.py`

- [ ] **Step 1: Write the failing test** (append)

```python
@pytest.mark.asyncio
async def test_candidate_persists_the_brief(monkeypatch):
    from rapid_reports_ai import quick_report_api as api

    async def fake_generate(**kw):
        return {"report_content": "R", "description": "d", "brief_used": True,
                "brief_text": "BRIEF", "brief_decisions": {"negatives": []}, "brief_options": []}
    monkeypatch.setattr(api, "generate_quick_report", fake_generate)
    monkeypatch.setattr(api, "log_generator_run", lambda **kw: None)
    cand = await api._run_one_generator(skill_sheet_markdown="S", findings="F", model_name="m", run_id="r",
                                        scan_type="CT", clinical_history="h")
    assert cand["brief"] == {"text": "BRIEF", "decisions": {"negatives": []}}
```

- [ ] **Step 2: Run it and check it fails**

Run: `poetry run pytest tests/test_confirmed_negatives.py::test_candidate_persists_the_brief -q`
Expected: FAIL with `KeyError: 'brief'`

- [ ] **Step 3: Implement** — add to the success dict in `_run_one_generator`, after `"options"`:

```python
            # The compiled brief the generator read, so a prod report can be traced to it.
            "brief": ({"text": result.get("brief_text"), "decisions": result.get("brief_decisions")}
                      if result.get("brief_used") else None),
```

- [ ] **Step 4: Run it and check it passes**

Run: `poetry run pytest tests/test_confirmed_negatives.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/quick_report_api.py tests/test_confirmed_negatives.py
git commit -m "feat(quick-report): persist the compiled brief on the candidate"
```

---

### Task 7: Frontend — hide `confirmed_negative` until the side panel ships

**Files:**
- Modify: `frontend/src/lib/utils/impressionOptions.ts`
- Modify: `frontend/src/lib/utils/impressionOptions.test.ts`
- Modify: `frontend/src/routes/components/IntelliDictateTab.svelte:465`

- [ ] **Step 1: Write the failing test** (append to `impressionOptions.test.ts`)

```ts
import { panelOptions } from './impressionOptions';

describe('panelOptions', () => {
	it('keeps impression-section kinds and hides confirmed negatives until the side panel exists', () => {
		const opts: ReportOption[] = [
			{ id: 'opt0', kind: 'recommendation', section: 'IMPRESSION', sentence: 'MRI brain is recommended.' },
			{ id: 'cn0', kind: 'confirmed_negative', section: 'FINDINGS', sentence: 'No uncal herniation.' }
		];
		expect(panelOptions(opts).map((o) => o.id)).toEqual(['opt0']);
	});
});
```

(If `describe`/`expect` are not already imported at the top of the file, add them to its existing
`vitest` import.)

- [ ] **Step 2: Run it and check it fails**

Run: `npx vitest run src/lib/utils/impressionOptions.test.ts`
Expected: FAIL (`panelOptions` is not exported)

- [ ] **Step 3: Implement** in `impressionOptions.ts`

```ts
export interface ReportOption {
	id: string;
	kind: 'recommendation' | 'impression' | 'confirmed_negative';
	section?: 'IMPRESSION' | 'FINDINGS';
	sentence: string;
	reason?: string;
```

(keep the remaining existing fields unchanged) and add:

```ts
/** Options the current below-editor panel can place. It inserts into the IMPRESSION only, so
 * FINDINGS-scoped confirmed negatives wait for the per-section side panel. */
export function panelOptions(options: ReportOption[]): ReportOption[] {
	return options.filter((o) => o.kind !== 'confirmed_negative');
}
```

In `IntelliDictateTab.svelte`, change the import and line 465:

```ts
import { appliedOptionIds, panelOptions, type ReportOption } from '$lib/utils/impressionOptions';
```

```ts
					reportOptions = panelOptions(cand.options ?? []);
```

- [ ] **Step 4: Run tests + typecheck**

Run: `npx vitest run src/lib/utils/impressionOptions.test.ts && npx svelte-check --threshold error 2>&1 | tail -3`
Expected: tests pass; svelte-check reports 0 errors

- [ ] **Step 5: Commit**

```bash
git add src/lib/utils/impressionOptions.ts src/lib/utils/impressionOptions.test.ts src/routes/components/IntelliDictateTab.svelte
git commit -m "feat(quick-report-ui): hide FINDINGS-scoped confirmed negatives until the side panel ships"
```

---

### Task 8: Eval runner + silent-staging basket

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/confirmed_negatives_eval.py`
- Create: `backend/test_cases/silent_staging.json`

- [ ] **Step 1: Write the basket**

`silent_staging.json` has 8 cases with fields `name, scan_type, clinical_history, findings, kind`
(`kind` is `silent` or `control`):
1. `prod_jaundice_panc_head` — the prod case verbatim. Scan `CT AP with contrast`, history
   `jaundice`, and the three dictated sentences from report `064ff6f1`.
2. `lung_nodule_silent` — `ct_thorax_smoker_lung_nodule` from `varied_10.json`, keeping only
   the nodule line (no pleura, chest wall, node or metastasis statements).
3. `cerebellar_haem_silent` — `ct_head_cerebellar_haemorrhage`, keeping only the haematoma
   size and location line (no oedema, shift, hydrocephalus or herniation).
4. `diverticulitis_silent` — `ct_ap_diverticulitis_abscess`, keeping only the diverticulosis
   with wall thickening and the pericolic stranding lines (no gas, collection or abscess
   lines).
5. `pe_silent` — `ctpa_acute_pe_rv_strain`, keeping only the filling-defect line (no RV/LV,
   septum or reflux lines).
6. `mscc_silent` — `mri_spine_mscc`, keeping only the vertebral metastases line (no
   compression, cord or canal lines).
7. `control_normal_ct_head` — `CT head non-con`, `headache`, findings
   `No acute intracranial abnormality.`
8. `control_normal_ct_ap` — `CT AP with contrast`, `abdominal pain`, findings
   `No acute abnormality in the abdomen or pelvis.`

Copy each source case's `scan_type` and `clinical_history` verbatim from `varied_10.json`,
and copy the kept findings lines verbatim.

- [ ] **Step 2: Write the runner**

```python
"""Confirmed-branch negatives: calibration dump and A/B runner (ledger L-45).

    poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm A --runs 3
    poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm B --runs 3
    poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm B --runs 1 --calibrate

A = production directives; B = production + confirmed_negatives. Serial, to stay inside
provider rate limits. Results go to test_output/confirmed_negatives/.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[3]
load_dotenv(BACKEND / ".env")

from rapid_reports_ai import quick_report_brief as qb  # noqa: E402
from rapid_reports_ai.quick_report_analyser import PRODUCTION_DIRECTIVES, generate_ephemeral_skill_sheet  # noqa: E402
from rapid_reports_ai.quick_report_generator import generate_quick_report  # noqa: E402
from rapid_reports_ai.scripts.sheet_budget import gate  # noqa: E402

ARMS = {"A": PRODUCTION_DIRECTIVES, "B": PRODUCTION_DIRECTIVES + ("confirmed_negatives",)}


def _findings_block(report: str) -> str:
    m = re.search(r"FINDINGS:(.*?)(?:\n[A-Z ]+:|\Z)", report, re.S)
    return (m.group(1) if m else "").lower()


async def run_case(case: dict, arm: str) -> dict:
    t0 = time.time()
    sheet = await generate_ephemeral_skill_sheet(scan_type=case["scan_type"], clinical_history=case["clinical_history"],
                                                 api_key="", directives=ARMS[arm])
    res = await generate_quick_report(skill_sheet=sheet["skill_sheet"], scan_type=case["scan_type"],
                                      findings=case["findings"], clinical_history=case["clinical_history"])
    report, dec = res["report_content"], res.get("brief_decisions") or {}
    conf = dec.get("confirmed_negatives", [])
    findings = _findings_block(report)
    stated = [c["text"] for c in conf if c["outcome"] == "stated"]
    return {
        "case": case["name"], "kind": case.get("kind", "silent"), "arm": arm,
        "analyser_ms": sheet["latency_ms"], "brief_ms": res.get("brief_reconcile_ms"),
        "wall_s": round(time.time() - t0, 1),
        "stated": stated, "stated_in_findings": [s for s in stated if s.lower().rstrip(".") in findings],
        "offered": [o["sentence"] for o in res.get("brief_options") or [] if o["kind"] == "confirmed_negative"],
        "do_not_assert": [c["text"] for c in conf if c["outcome"] == "do_not_assert"],
        "carried": (dec.get("impression_plan") or {}).get("carry_negatives", []),
        "unmatched": dec.get("confirmed_negatives_unmatched", 0),
        "routes": conf, "gate": gate.run_gate(report),
        "report": report, "sheet": sheet["skill_sheet"], "brief": res.get("brief_text"),
    }


async def calibrate(case: dict) -> list[dict]:
    """Jev `present` score for every differential of a B sheet, for hand labelling."""
    sheet = await generate_ephemeral_skill_sheet(scan_type=case["scan_type"], clinical_history=case["clinical_history"],
                                                 api_key="", directives=ARMS["B"])
    diffs = qb.differential_lines(qb.parse_sheet(sheet["skill_sheet"]))
    state = f"SCAN TYPE: {case['scan_type']}\nDICTATED FINDINGS:\n{case['findings']}"
    ans = await qb._jev(state, {f"d{k}": {"type": "noul", "instructions": qb.Q_PRESENT + t} for k, t in enumerate(diffs)})
    return [{"case": case["name"], "branch": t[:90], "present": round(float(ans[f"d{k}"]["noul"]), 3), "label": ""}
            for k, t in enumerate(diffs)]


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--arm", choices=ARMS, required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--cases-file", default=str(BACKEND / "test_cases" / "silent_staging.json"))
    p.add_argument("--case", action="append")
    p.add_argument("--calibrate", action="store_true")
    a = p.parse_args()
    cases = [c for c in json.loads(Path(a.cases_file).read_text()) if not a.case or c["name"] in a.case]
    out_dir = BACKEND / "test_output" / "confirmed_negatives"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    if a.calibrate:
        rows = [r for c in cases for r in await calibrate(c)]
        path = out_dir / f"{stamp}_calibration.json"
        path.write_text(json.dumps(rows, indent=1))
        for r in rows:
            print(f"{r['present']:.2f}  {r['case']:<28} {r['branch']}")
        print(path)
        return
    rows = []
    for run in range(a.runs):
        for c in cases:
            r = await run_case(c, a.arm)
            r["run"] = run
            rows.append(r)
            print(f"[{a.arm} r{run}] {c['name']:<28} stated={len(r['stated'])} in_findings={len(r['stated_in_findings'])} "
                  f"offered={len(r['offered'])} dna={len(r['do_not_assert'])} carried={len(r['carried'])} "
                  f"gate={'ok' if r['gate']['passed'] else r['gate']['failures']} analyser={r['analyser_ms']/1000:.1f}s")
    path = out_dir / f"{stamp}_arm{a.arm}.json"
    path.write_text(json.dumps(rows, indent=1, default=str))
    print(path)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Smoke it on one case**

Run: `poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm B --runs 1 --case prod_jaundice_panc_head`
Expected: one line with `stated>=1`, and a JSON file path. If `unmatched > 0`, read `sheet` in the
JSON: the analyser renamed a branch. Note it for the ledger; do not change the parser to guess.

- [ ] **Step 4: Commit**

```bash
git add src/rapid_reports_ai/scripts/confirmed_negatives_eval.py test_cases/silent_staging.json
git commit -m "eval(confirmed-negatives): silent-staging basket and A/B + calibration runner"
```

---

### Task 9: Calibrate PRESENT_HIGH

**Files:**
- Modify: `backend/src/rapid_reports_ai/quick_report_brief.py` (`PRESENT_HIGH`, only if the data says so)
- Modify: `docs/model-migration/parameter-ledger.md`

- [ ] **Step 1: Dump scores**

Run: `poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm B --calibrate --cases-file test_cases/silent_staging.json`
Then run it again with `--cases-file test_cases/varied_10.json`.

- [ ] **Step 2: Label by hand.** For every row with `present ≥ 0.5`, label it `clear` (the
dictation states the diagnosis or its defining sign) or `borderline` (compatible but not
stated). Write the labels into the saved JSON.

- [ ] **Step 3: Choose the cut-off.** Pick the lowest value at which every `clear` row is ≥ and
no `borderline` row is ≥. If there is no such gap, set `PRESENT_HIGH = PRESENT_LOW` (0.5), so
the tag alone decides, as the spec prescribes. Edit the constant, then run
`poetry run pytest tests/test_confirmed_negatives.py -q`. If the value changed, update the
parametrised `0.6 → offered` case to a value between the two cut-offs; if the cut-offs are
equal, change that row to `("keep", 0.6, "core", "stated")` and `("keep", 0.6, "contextual", "offered")`.

- [ ] **Step 4: Record and commit.** Add the chosen value and the score table to L-45 (Task 10
opens the entry; write this into it).

```bash
git add src/rapid_reports_ai/quick_report_brief.py tests/test_confirmed_negatives.py test_output/confirmed_negatives/*_calibration.json
git commit -m "calibrate(brief): PRESENT_HIGH from labelled Jev present scores (L-45)"
```

---

### Task 10: Ledger L-45 predictions, A/B runs, results

**Files:**
- Modify: `docs/model-migration/parameter-ledger.md` (append after L-44)

- [ ] **Step 1: Write predictions before any run.** Append:

```markdown
### L-45 · Confirmed-branch negatives (policy 1 for confirmed branches) — opt-in `confirmed_negatives`

Spec `docs/superpowers/specs/2026-09-29-policy1-confirmed-branch-negatives-design.md`. Trigger:
prod report 064ff6f1 (jaundice, pancreatic head mass) omitted every resectability negative.
Arms: A = production directives; B = + `confirmed_negatives`. Basket `test_cases/silent_staging.json`
(6 silent + 2 control) × 3 runs; regression `varied_10.json` × 1 run per arm.

**Predictions (written 2026-09-29, before any run):**
- Silent: ≥1 confirmed negative stated in FINDINGS — A ~0/6, B ≥5/6 cases (majority of runs).
- Report negatives contradicting the dictation — 0 both arms.
- Expected-consequence negative anywhere in a report — 0.
- Confirmed negatives carried into the impression — median ≤1 per case, each changing interpretation.
- Offered confirmed negatives — median 1–2 per silent case.
- Controls — 0 new negatives or options in B.
- Regression gate — 100% both arms.
- Analyser median latency — B within +1.5 s of A.

**Calibration:** (Task 9 table and chosen PRESENT_HIGH)

**Results:** (Step 3)
```

Commit: `git commit -am "ledger(L-45): predictions before the confirmed-negatives A/B"`

- [ ] **Step 2: Run the arms** (serial, one after the other)

```bash
poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm A --runs 3
poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm B --runs 3
poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm A --runs 1 --cases-file test_cases/varied_10.json
poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm B --runs 1 --cases-file test_cases/varied_10.json
```

- [ ] **Step 3: Read every B report against its dictation, and write the results.** The
runner's counts are the automated part. By hand, per B report:
- Does any negative contradict the dictation?
- Does any stated negative deny an expected consequence?
- Does each carried negative change the interpretation?
- Is any positive descriptor invented for a named structure (naming primes)?
- Does the core/contextual tag agree across the three runs?

Fill **Results** with a prediction-by-prediction table: predicted vs observed, with the
contradicted predictions called out. Commit:

```bash
git add ../docs/model-migration/parameter-ledger.md test_output/confirmed_negatives/
git commit -m "ledger(L-45): confirmed-negatives A/B results"
```

- [ ] **Step 4: Full suite and stop.**

Run: `poetry run pytest tests -q --ignore=tests/test_dictation_triage_live.py`
Expected: all passed.

Turning the directive on in production (adding `"confirmed_negatives"` to
`PRODUCTION_DIRECTIVES`) is **not** in this plan. It needs Hassan's sign-off on the L-45
results (the v1 subtraction rule).

---

## Revision 2 (2026-09-29): key negatives by finding, not branch

**Why:** the first live run of Task 8 stated nothing in any of 8 cases. Imaging confirms
findings, not diagnoses; the main finding is usually not a differential line; and branch names
did not match. The spec's revision-2 header gives the detail.

**Status of the tasks above:**
- **Carried forward unchanged:** Tasks 1–7 (routing, impression plan, options, persistence,
  frontend) and Task 8's runner and basket.
- **Superseded:** Task 9 (calibration moves into R3) and Task 10 (becomes R7).
- **Replaced by R4:** the branch-keyed parts of Tasks 1–3 (directive text, parser, Jev key).

**R4–R7 are written after the R3 gate,** because its result decides how much weight the
fallback carries.

### R1: Directive `finding_negatives` (replaces `confirmed_negatives`)

**Files:** modify `backend/src/rapid_reports_ai/quick_report_analyser.py`,
`backend/tests/test_confirmed_negatives.py`

- [ ] **Step 1: Failing test.** In `test_confirmed_negatives_is_an_opt_in_directive`, replace
  `"confirmed_negatives"` with `"finding_negatives"` and `"**If confirmed:**"` with
  `"**If present:**"`, then add:

```python
    assert "never the diagnosis it suggests" in arm_b
    assert "confirmed_negatives" not in qa.DIRECTIVES
```

- [ ] **Step 2:** `poetry run pytest tests/test_confirmed_negatives.py -q`. Expect a FAIL
  (unknown directive).
- [ ] **Step 3: Implement.** Rename the constant to `FINDING_NEGATIVES`. Its text is the spec's
  §1 directive, under the heading `## If present — negatives that follow a reported finding`,
  with the bullet format block from the spec. Rename the DIRECTIVES key to
  `"finding_negatives"` and update the comment above the constant.
- [ ] **Step 4:** tests pass. **Step 5:** commit `feat(analyser): finding_negatives directive —
  negatives keyed by imaging finding`.

### R2: Parser for finding keys

**Files:** modify `backend/src/rapid_reports_ai/quick_report_brief.py`,
`backend/tests/test_confirmed_negatives.py`

- [ ] **Step 1: Failing test** (append):

```python
def test_if_present_parses_keys_in_both_shapes():
    lines = ["- **If present:** (negatives stated only when the dictation reports the finding)",
             '  - pancreatic head mass → "No superior mesenteric vein contact." (core)',
             '  - pancreatic head mass -> "No peritoneal deposit"',
             "  - spiculated lung nodule →",
             '    - "No chest wall invasion." (core)']
    cands = qb.parse_if_present(lines)
    assert [(c.key, c.text, c.tag) for c in cands] == [
        ("pancreatic head mass", "No superior mesenteric vein contact", "core"),
        ("pancreatic head mass", "No peritoneal deposit", "contextual"),
        ("spiculated lung nodule", "No chest wall invasion", "core"),
    ]
    assert qb.distinct_keys(cands) == ["pancreatic head mass", "spiculated lung nodule"]
```

- [ ] **Step 2:** run it; expect `AttributeError: parse_if_present`.
- [ ] **Step 3: Implement** (next to `parse_confirmed`, reusing its regexes):

```python
Q_FINDING = "The dictated findings report this imaging finding, in any wording or size: "


@dataclass
class FindingNegative:
    key: str
    text: str
    tag: str   # "core" | "contextual"


def parse_if_present(lines: List[str]) -> List[FindingNegative]:
    """The If-present bullet as (finding key, negative, tag), one-line or nested shape."""
    out: List[FindingNegative] = []
    key = None
    for line in lines[1:]:
        if m := _CONFIRMED.match(line):
            out.append(FindingNegative(m.group(1).strip(), m.group(2).strip().rstrip("."), m.group(3) or "contextual"))
        elif m := _CONFIRMED_BRANCH.match(line):
            key = m.group(1).strip()
        elif (m := _CONFIRMED_NEG.match(line)) and key:
            out.append(FindingNegative(key, m.group(1).strip().rstrip("."), m.group(2) or "contextual"))
    return out


def distinct_keys(cands: List[FindingNegative]) -> List[str]:
    return list(dict.fromkeys(c.key for c in cands))
```

- [ ] **Step 4:** tests pass. **Step 5:** commit `feat(brief): parse If-present finding keys`.

### R3: Coverage check (gate)

**Files:** modify `backend/src/rapid_reports_ai/scripts/confirmed_negatives_eval.py` (add
`--coverage`); modify `backend/test_cases/silent_staging.json` (+3 hedged cases, `kind: "hedged"`)

- [ ] **Step 1: Hedged cases.** Append three cases, each a hedged restatement of a silent case
  with the same scan and history:
  - `hedged_panc`: `Possible subtle hypodensity in the region of the pancreatic head, of uncertain significance.`
  - `hedged_lung`: `Ill-defined opacity in the right upper lobe, possibly a nodule versus vessel.`
  - `hedged_cerebellar`: `Questionable small hyperdensity in the right cerebellum, possibly artefact.`
- [ ] **Step 2: `--coverage` mode.** For each case, generate one arm-B sheet
  (`finding_negatives`), parse the keys, and ask Jev `Q_FINDING + key` for every distinct key
  in one call. Record: every key with its score; the top key and score; the number of
  negatives per key with their tags; and the full If-present block. Print one line per case:
  `case kind top_score top_key n_keys`. Save the JSON to
  `test_output/confirmed_negatives/<stamp>_coverage_<file>.json`.
- [ ] **Step 3: Run** on `silent_staging.json` and on `varied_10.json`.
- [ ] **Step 4: Read by hand**, per case:
  - Does the top key name the main dictated finding?
  - For controls, is every score below 0.5?
  - For hedged vs clear pairs, how do the scores compare?
  - Are the negatives single-finding, pertinent, and not expected consequences?
- [ ] **Step 5: Gate.** Report coverage (target ≥90% of silent + `varied_10` cases), false
  triggers (target 0), the calibration table, and the quality notes to Hassan before writing
  R4–R7. Commit the runner change and outputs:
  `eval(finding-negatives): coverage check`.

### R3 result (2026-09-29)

The gate passed: 15/16 main findings keyed ≥0.5, 0 false triggers, clear 0.86–0.99 vs hedged
≤0.72. The negatives are of mixed quality, and the Qwen check is doing essential work (ledger
L-45). Hassan approved R4–R7.

### R4: Brief keyed by finding (replaces the branch-keyed code)

**Files:**
- modify `backend/src/rapid_reports_ai/quick_report_brief.py`, `backend/src/rapid_reports_ai/quick_report_generator.py`,
  `backend/src/rapid_reports_ai/scripts/confirmed_negatives_eval.py`,
  `frontend/src/lib/utils/impressionOptions.ts(+test)`;
- rewrite the branch-keyed tests in `backend/tests/test_confirmed_negatives.py`.

- [ ] **Step 1: Rewrite the tests.**
  - Delete `test_candidates_parse_branch_negative_and_tag` and
    `test_candidates_parse_the_nested_shape_the_analyser_emits`.
  - Rename `route_confirmed` → `route_finding` in the rule-C test.
  - `SHEET_C` loses its differentials' role. Its Companion Matrix bullet becomes:
    ```
    - **If present:** (negatives stated only when the dictation reports the finding)
      - subdural haematoma → "No midline shift" (core)
      - subdural haematoma → "No uncal herniation" (contextual)
      - subdural haematoma → "No effacement of the basal cisterns" (core)
      - subdural haematoma → "No subfalcine herniation" (core)
      - extradural haematoma → "No venous sinus involvement" (core)
    ```
  - `_stub_c` sets `f0` (the subdural key) to the given score and every other question to 0.1.
  - Expected texts are unchanged. Kind `finding_negative`, field `finding` instead of
    `branch`, decisions key `finding_negatives`, source `finding:subdural haematoma`, and the
    KEEP annotation `(finding: subdural haematoma)`.
  - The generator tests use kind `finding_negative` and `finding`.
  - Add a test that the Jev question for each key starts with `Q_FINDING`, and that a key
    shared by several negatives is asked once.
- [ ] **Step 2:** run the tests; expect FAILs.
- [ ] **Step 3: Implement.**
  - **Remove** `Candidate`, `_diff_name`, `_name_key`, `parse_confirmed`.
  - **Rename** `route_confirmed` → `route_finding` and `MAX_CONFIRMED_OPTIONS` →
    `MAX_FINDING_OPTIONS`. In `DROP_TOP_BULLETS`, replace `"If confirmed"` with `"If present"`.
  - **In `compile_brief`:**
    - `fb = _bullet(matrix, "If present")`, `cands = parse_if_present(fb.lines) if fb else []`,
      `keys = distinct_keys(cands)`.
    - Add `qs.update({f"f{i}": {"type": "noul", "instructions": Q_FINDING + k} for i, k in enumerate(keys)})`.
    - Each candidate's score is `score(f"f{keys.index(c.key)}")`.
    - Options become `{"kind": "finding_negative", "section": "FINDINGS", "text", "finding": c.key, "reason"}`.
    - Decisions become `finding_negatives` entries `{finding, text, tag, qwen, present, outcome}`,
      and `unmatched` is removed.
  - **Generator:** `"confirmed_negative"` → `"finding_negative"`, `"branch"` → `"finding"`.
  - **Frontend:** `'confirmed_negative'` → `'finding_negative'`, `branch` → `finding`.
  - **Eval runner:** `confirmed_negatives` → `finding_negatives`, kind `finding_negative`,
    and the `unmatched` column is removed.
- [ ] **Step 4:** backend and frontend tests pass. **Step 5:** commit
  `feat(brief): link negatives to the reported finding (Jev per key); drop branch keying`.

### R5: Fallback for unanticipated findings (offered only)

**Files:** modify `backend/src/rapid_reports_ai/quick_report_brief.py`, `backend/tests/test_confirmed_negatives.py`

This deviates from the spec's §3 on one point. Jev scores keys, not dictated items, so code
cannot tell which item a key covers. The fallback Qwen call therefore judges coverage itself.
It sees every dictated item and every key, and runs in the same `gather`.

- [ ] **Step 1: Failing tests.** Stub `_fallback`, returning items 0 (covered) and 1 (not
  covered, negatives `["No adrenal haemorrhage"]`), with the plan carrying items [0, 1].
  - An option `{"kind": "finding_negative", "section": "FINDINGS", "text": "No adrenal haemorrhage", "finding": <item 1>, "reason": "unanticipated finding"}` appears.
  - Nothing from the fallback is ever stated.
  - With the plan not carrying item 1, nothing is offered.
  - When `_fallback` raises, the brief still compiles and offers nothing from it.
  - The fallback shares the `MAX_FINDING_OPTIONS` cap.
- [ ] **Step 2:** run the tests; expect FAIL.
- [ ] **Step 3: Implement.**

```python
class FallbackItem(BaseModel):
    index: int
    covered: bool
    negatives: List[str] = []


class FallbackNegatives(BaseModel):
    items: List[FallbackItem]
    @field_validator("items", mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return _unstring(v)


FALLBACK_SYS = (
    "You check whether each dictated radiology finding is covered by a prepared list of finding types, and write "
    "pertinent negatives only for findings that are not. For each numbered dictated finding return covered=true "
    "when one of the FINDING TYPES describes the same kind of finding in the same place; otherwise covered=false "
    "and up to three negatives a consultant states once that finding is reported: the absence of each extension, "
    "spread or complication this technique shows and the next management step depends on. One finding per "
    "negative, no 'or', no list, final report form. Never deny anything dictated or its expected consequence.")
FALLBACK_TIMEOUT_S = 6.0


async def _fallback(state: str, items: List[str], keys: List[str]) -> FallbackNegatives:
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=FallbackNegatives, system_prompt=FALLBACK_SYS,
        user_prompt=(f"{state}\n\nNUMBERED DICTATED FINDINGS:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(items))
                     + "\n\nFINDING TYPES:\n" + ("\n".join(f"- {k}" for k in keys) or "(none)")),
        api_key="", model_settings={"temperature": 0, "max_tokens": 3000, "reasoning_effort": "none"}), FALLBACK_TIMEOUT_S)
    return r.output
```

In `compile_brief`, add `fallback_or_none()` (it catches everything and returns `None`) to the
`gather`. After the plan block, and only when `plan` exists:

```python
    if plan and fb_out:
        seen = {c.text for c in cands}
        for it in fb_out.items:
            if it.covered or it.index not in plan.impression or not (0 <= it.index < len(items)):
                continue
            for neg in it.negatives[:3]:
                neg = neg.strip().rstrip(".")
                if neg in seen or n_offered >= MAX_FINDING_OPTIONS:
                    continue
                seen.add(neg)
                n_offered += 1
                decisions["options"].append({"kind": "finding_negative", "section": "FINDINGS", "text": neg,
                                             "finding": items[it.index], "reason": "unanticipated finding"})
                decisions["finding_negatives"].append({"finding": items[it.index], "text": neg, "tag": "fallback",
                                                       "qwen": "n/a", "present": None, "outcome": "offered"})
```

- [ ] **Step 4:** tests pass. **Step 5:** commit
  `feat(brief): unanticipated carried findings get offered negatives from a parallel Qwen fallback`.

### R6: PRESENT_HIGH

It stays at 0.8, which sits in the measured gap (clear ≥0.86, hedged ≤0.72). There is no code
change. Re-check it on the A/B's hedged cases in R7.

### R7: A/B, read by hand, results (the old Task 10)

- [ ] **Step 1:** add the L-45 predictions block (spec "Evaluation" table), then commit it
  before any run.
- [ ] **Step 2: Run** in the background, serially:
  - arm A, 3 runs, `silent_staging.json`;
  - arm B, 3 runs, `silent_staging.json`;
  - arms A and B, 1 run each, `varied_10.json`.
- [ ] **Step 3: Read every B report by hand** against its dictation, per the spec's measures.
  Add: did the Qwen check drop every contradicted negative? Do fallback options appear, and
  are they sensible? Write the results table into L-45.
- [ ] **Step 4:** run the full backend suite, then commit. Production enablement is not in
  scope; it needs Hassan's sign-off.
