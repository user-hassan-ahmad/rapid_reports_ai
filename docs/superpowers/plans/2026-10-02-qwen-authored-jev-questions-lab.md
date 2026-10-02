# Qwen-authored Jev questions lab: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the lab harness, run the wording mini-check (T2 on the dictation, and T6), then run the S1 grade-grounding pilot across arms A, A0, B, C and D. The result is a directional go/no-go.

**Spec:** `docs/superpowers/specs/2026-10-02-qwen-authored-jev-questions-lab-design.md`. Read §2, which covers the catalogue and its constraints, and §7, which covers pass criteria and the paired counts.

**Architecture:**
- A small package, `rapid_reports_ai/scripts/jev_tool_lab/`, holds the lab. Each module has one job:
  - `catalogue.py`: code-owned Jev wordings, slot validation and rendering;
  - `rules.py`: answer banding and the declared decision rule;
  - `calls.py`: the Jev and Qwen transport;
  - `prompts.py` and `scenarios.py`: what Qwen is told;
  - `arms.py`: the five arms;
  - `run_lab.py`, `score.py` and `wording_check.py`: the CLIs.
- The arms take their Qwen and Jev functions as parameters, so every unit test runs with fakes.
- Production data stays in the scratchpad. The repo only gets synthetic fixtures.

**Tech stack:** Python 3.13, pydantic 2, pydantic-ai 1.104 (through the existing `_run_agent_with_model`, which already applies `normalise_model_settings`), httpx, and pytest with `asyncio_mode = "auto"`. Jev is `typesafe/jev-1.13` through OpenRouter `/api/v1/systemone`. Qwen is `qwen-3.8-27b` on Cerebras.

**Conventions:**
- Run everything from `backend/` with `.venv/bin/python`.
- Tests live in `backend/tests/` (flat, `test_*.py`).
- Lab outputs go to `$LAB_OUT`, a folder in the session scratchpad. Set it once per session: `export LAB_OUT=<scratchpad>/jev_tool_lab && mkdir -p $LAB_OUT`.
- Output filenames carry the pid (memory `feedback_eval_economy`).
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## File map

| File | Responsibility |
|---|---|
| Create `backend/src/rapid_reports_ai/scripts/jev_tool_lab/__init__.py` | package marker |
| Create `.../jev_tool_lab/catalogue.py` | `Case`, `QuestionSpec`, `validate`, `render`, `state_for`, `question_source`, wordings |
| Create `.../jev_tool_lab/rules.py` | `Condition`, `Rule`, `band`, `evaluate` |
| Create `.../jev_tool_lab/scenarios.py` | `S1Item`, `Decision`, `JUDGEMENT_S1`, `s1_user` |
| Create `.../jev_tool_lab/prompts.py` | system prompts for baseline, authoring (catalogue), free-form authoring and deciding with evidence |
| Create `.../jev_tool_lab/calls.py` | `qwen`, `jev`, `Usage` |
| Create `.../jev_tool_lab/arms.py` | `ArmResult`, `Plan`, `FreePlan`, `lint_free`, `arm_a`, `arm_b`, `arm_c`, `arm_d` |
| Create `.../jev_tool_lab/run_lab.py` | CLI: arms × runs → JSONL, with reuse |
| Create `.../jev_tool_lab/score.py` | metrics, paired gains and losses, McNemar, Brier, ECE, AUC |
| Create `.../jev_tool_lab/wording_check.py` | CLI: phase 1 mini-check |
| Create `backend/test_cases/jev_tool_lab/wording_check.json` | 40 synthetic items (20 T2d, 20 T6) |
| Create `backend/test_cases/jev_tool_lab/s1_pilot.json` | 20 synthetic S1 items |
| Create `backend/tests/test_jev_tool_lab_catalogue.py` | catalogue tests |
| Create `backend/tests/test_jev_tool_lab_rules.py` | rules tests |
| Create `backend/tests/test_jev_tool_lab_arms.py` | arms tests (fakes), lint tests, run_lab test |
| Create `backend/tests/test_jev_tool_lab_score.py` | score tests |

---

### Task 1: Catalogue: types, cases, validation

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/jev_tool_lab/__init__.py`
- Create: `backend/src/rapid_reports_ai/scripts/jev_tool_lab/catalogue.py`
- Test: `backend/tests/test_jev_tool_lab_catalogue.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_jev_tool_lab_catalogue.py
from rapid_reports_ai.scripts.jev_tool_lab.catalogue import Case, QuestionSpec, validate

CASE = Case(scan_type="CT abdomen",
            dictation="Left renal lesion 3 cm with a thin wall and two thin septa. No enhancement.",
            report="FINDINGS:\nLeft renal cyst 3 cm with thin septa.\nIMPRESSION:\nBosniak II cyst.")


def q(**kw):
    return QuestionSpec(id="q1", **kw)


def test_t1_needs_verbatim_item():
    assert validate(q(type="T1", source="dictation", item="Left renal cyst 3 cm"), CASE) is None
    assert validate(q(type="T1", source="dictation", item="left  renal CYST 3 cm"), CASE) is None  # whitespace/case
    assert validate(q(type="T1", source="dictation", item="a cyst in the kidney"), CASE) == "item not verbatim"


def test_t1_needs_source():
    assert validate(q(type="T1", item="Left renal cyst 3 cm"), CASE) == "missing source"


def test_t2_topic_rules():
    assert validate(q(type="T2", source="dictation", topic="wall thickness of the lesion"), CASE) is None
    assert validate(q(type="T2", source="dictation", topic="no enhancement"), CASE) == "topic carries a negation"
    assert validate(q(type="T2", source="dictation", topic="septa over 2 mm"), CASE) == "topic carries a number"
    assert validate(q(type="T2", source="dictation", topic="a b c d e f g"), CASE) == "topic must be 1-6 words"
    assert validate(q(type="T2", source="report", topic="septa"), CASE) == "T2 on the report needs a section"
    assert validate(q(type="T2", source="report", section="FINDINGS", topic="septa"), CASE) is None
    assert validate(q(type="T2", source="history", topic="septa"), CASE) == "T2 source must be dictation or report"


def test_t3_clause_must_be_in_report():
    assert validate(q(type="T3", clause="Left renal cyst 3 cm with thin septa."), CASE) is None
    assert validate(q(type="T3", clause="No enhancement."), CASE) == "clause not verbatim in the report"


def test_t4_options():
    ok = q(type="T4", source="dictation", item="two thin septa", options=["thin septa", "thick septa"])
    assert validate(ok, CASE) is None
    one = q(type="T4", source="dictation", item="two thin septa", options=["thin septa"])
    assert validate(one, CASE) == "T4 needs 2-5 options"
    neg = q(type="T4", source="dictation", item="two thin septa", options=["septa enhance", "septa do not enhance"])
    assert validate(neg, CASE) == "an option negates another"


def test_t5_property_must_be_known():
    assert validate(q(type="T5", item="No enhancement.", property="abnormal"), CASE) is None
    assert validate(q(type="T5", item="No enhancement.", property="hedged"), CASE) == "unknown property"


def test_t6_spans_verbatim():
    assert validate(q(type="T6", a="Left renal lesion 3 cm", b="Left renal cyst 3 cm"), CASE) is None
    assert validate(q(type="T6", a="Left renal lesion 3 cm", b="right kidney"), CASE) == "span not verbatim"


def test_empty_source_text_rejected():
    case = Case(dictation="Normal study.")
    assert validate(q(type="T2", source="report", section="FINDINGS", topic="septa"), case) == "source text is empty"
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_catalogue.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.scripts.jev_tool_lab'`

- [ ] **Step 3: Write the implementation**

```python
# backend/src/rapid_reports_ai/scripts/jev_tool_lab/__init__.py
"""Lab: Qwen authors Jev questions (spec 2026-10-02-qwen-authored-jev-questions-lab-design)."""
```

```python
# backend/src/rapid_reports_ai/scripts/jev_tool_lab/catalogue.py
"""Question catalogue (spec 2026-10-02-qwen-authored-jev-questions-lab-design §2).

Qwen picks a question type and fills its slots; the wording is owned here, by code, and comes from measured Jev
results (memory reference_jev_capability_profile, ledger L-46/L-49). validate() rejects a slot set that drifts into
a type Jev is weak at."""
from __future__ import annotations

import re
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

from rapid_reports_ai.report_review import Q_CONTRA

Source = Literal["dictation", "report", "history"]
QType = Literal["T1", "T2", "T3", "T4", "T5", "T6"]

SOURCE_NAME = {"dictation": "dictated findings", "report": "report", "history": "clinical history"}
SUBJECT = {"dictation": "The dictated findings themselves state",
           "report": "The report itself states",
           "history": "The clinical history itself states"}
CANT_TELL = "cant_tell"
MAX_QUESTIONS = 8
MAX_TOPIC_WORDS = 6
MAX_OPTION_WORDS = 25
# T5 starts with its one proven property (group F selector noul, AUC ~1.0); more join only after a mini-check.
PROPERTIES = {"abnormal": "reports an abnormality or a limitation, including as a possibility"}
_NEGATION = {"no", "not", "without", "absent", "negative", "normal", "unremarkable", "nil", "none"}
_AUX = {"do", "does", "did", "is", "are", "was", "were", "has", "have"}   # "X enhance" vs "X do not enhance"
_WORD = re.compile(r"[a-z0-9']+")

# The two new wordings (spec §5 phase 1). The mini-check picks w1 or w2 and records it in DEFAULT_WORDING.
WORDINGS: Dict[str, Dict[str, dict]] = {
    "T2d": {
        "w1": {"instructions": "The dictated findings themselves say something about this topic, whatever they say "
                               "about it (present, absent, normal, a measurement or a description): {topic}",
               "criteria": {"true": "The dictation mentions this topic, in any wording, abbreviation or synonym, "
                                    "whatever it says about it.",
                            "false": "The dictation says nothing about this topic."}},
        "w2": {"instructions": "Do the dictated findings say anything about {topic}, in any wording?",
               "criteria": {"true": "Yes: the dictation describes {topic} in some way (present, absent, normal, "
                                    "measured or described), in any wording or synonym.",
                            "false": "No: {topic} is not mentioned anywhere in the dictation."}},
    },
    "T6": {
        "w1": {"instructions": '"{a}" and "{b}" describe the same structure or finding.',
               "criteria": {"true": "Both refer to the same structure or finding, in any wording.",
                            "false": "They refer to different structures or findings, or to a different side or "
                                     "level."}},
        "w2": {"instructions": 'Read only these two quoted texts: "{a}" and "{b}". They are about the same structure '
                               'or finding, at the same side and level.',
               "criteria": {"true": "Same structure or finding, same side and level, in any wording.",
                            "false": "A different structure or finding, or a different side or level."}},
    },
}
DEFAULT_WORDING = {"T2d": "w1", "T6": "w1"}


class Case(BaseModel):
    scan_type: str = ""
    dictation: str
    report: str = ""
    history: str = ""

    def text(self, source: str) -> str:
        return {"dictation": self.dictation, "report": self.report, "history": self.history}[source]


class QuestionSpec(BaseModel):
    """One question as Qwen fills it: a type plus slots. Flat on purpose (one nesting level for Qwen's output)."""
    id: str
    type: QType
    source: Optional[Source] = None
    section: Optional[str] = None
    item: Optional[str] = None
    topic: Optional[str] = None
    clause: Optional[str] = None
    options: Optional[List[str]] = None
    property: Optional[str] = None
    a: Optional[str] = None
    b: Optional[str] = None


def state_for(case: Case, source: str) -> str:
    if source == "dictation":
        return f"SCAN TYPE: {case.scan_type}\nDICTATED FINDINGS:\n{case.dictation}"
    if source == "report":
        return f"REPORT:\n{case.report}"
    return f"CLINICAL HISTORY:\n{case.history}"


def question_source(spec: QuestionSpec) -> str:
    """The text Jev reads as state for this question."""
    if spec.type == "T3":
        return "dictation"
    return spec.source or "dictation"


def _norm(t: str) -> str:
    return " ".join(t.split()).casefold()


def _quoted_in(quote: Optional[str], *texts: str) -> bool:
    return bool(quote and quote.strip()) and any(_norm(quote) in _norm(t) for t in texts if t)


def _words(t: str) -> List[str]:
    return _WORD.findall(t.casefold())


def _negation_pair(x: str, y: str) -> bool:
    wx, wy = _words(x), _words(y)
    rest = lambda ws: [w for w in ws if w not in _NEGATION and w not in _AUX]  # noqa: E731
    same_rest = rest(wx) == rest(wy)
    return same_rest and (set(wx) & _NEGATION) != (set(wy) & _NEGATION)


def validate(spec: QuestionSpec, case: Case) -> Optional[str]:
    """None when the slot set is a valid catalogue question for this case, else the reason it is rejected."""
    t = spec.type
    texts = (case.dictation, case.report, case.history)
    if t in ("T1", "T2", "T4") and spec.source is None:
        return "missing source"
    if t == "T2" and spec.source not in ("dictation", "report"):
        return "T2 source must be dictation or report"
    if not case.text(question_source(spec)).strip():
        return "source text is empty"
    if t == "T1":
        if not _quoted_in(spec.item, *texts):
            return "item not verbatim"
    elif t == "T2":
        if spec.source == "report" and not spec.section:
            return "T2 on the report needs a section"
        topic = (spec.topic or "").strip()
        words = _words(topic)
        if set(words) & _NEGATION:
            return "topic carries a negation"
        if any(ch.isdigit() for ch in topic):
            return "topic carries a number"
        if not 1 <= len(words) <= MAX_TOPIC_WORDS:
            return "topic must be 1-6 words"
    elif t == "T3":
        if not _quoted_in(spec.clause, case.report):
            return "clause not verbatim in the report"
    elif t == "T4":
        if not _quoted_in(spec.item, *texts):
            return "item not verbatim"
        opts = spec.options or []
        if not 2 <= len(opts) <= 5:
            return "T4 needs 2-5 options"
        if any(not o.strip() or len(_words(o)) > MAX_OPTION_WORDS for o in opts):
            return "option too long or empty"
        if any(_negation_pair(x, y) for i, x in enumerate(opts) for y in opts[i + 1:]):
            return "an option negates another"
    elif t == "T5":
        if not _quoted_in(spec.item, *texts):
            return "item not verbatim"
        if spec.property not in PROPERTIES:
            return "unknown property"
    elif t == "T6":
        if not (_quoted_in(spec.a, *texts) and _quoted_in(spec.b, *texts)):
            return "span not verbatim"
    return None
```

The test `validate(q(type="T5", item="No enhancement.", property="abnormal"), CASE)` passes because T5 defaults its source to the dictation, which is non-empty.

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_catalogue.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/jev_tool_lab/__init__.py backend/src/rapid_reports_ai/scripts/jev_tool_lab/catalogue.py backend/tests/test_jev_tool_lab_catalogue.py
git commit -m "feat(jev-tool-lab): question catalogue with slot validation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Catalogue: rendering to Jev JSON

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/jev_tool_lab/catalogue.py` (append)
- Test: `backend/tests/test_jev_tool_lab_catalogue.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_jev_tool_lab_catalogue.py
from rapid_reports_ai.report_review import Q_CONTRA
from rapid_reports_ai.scripts.jev_tool_lab.catalogue import CANT_TELL, WORDINGS, render, state_for


def test_render_t1_quotes_item_and_names_source():
    out = render(q(type="T1", source="dictation", item="thin septa"))
    assert out["type"] == "noul"
    assert '"thin septa"' in out["instructions"]
    assert out["instructions"].startswith("Read only this one quoted text:")
    assert "The dictated findings themselves state" in out["instructions"]
    assert set(out["criteria"]) == {"true", "false"}


def test_render_t2_report_uses_probe_wording():
    out = render(q(type="T2", source="report", section="FINDINGS", topic="ascites"))
    assert out == {"type": "noul", "instructions": "Does the FINDINGS section of the report say whether there is ascites?"}


def test_render_t2_dictation_uses_chosen_wording():
    out = render(q(type="T2", source="dictation", topic="septal thickness"), wording="w2")
    assert out["instructions"] == WORDINGS["T2d"]["w2"]["instructions"].format(topic="septal thickness")
    assert "septal thickness" in out["criteria"]["true"]


def test_render_t3_is_production_contradiction():
    out = render(q(type="T3", clause="Left renal cyst 3 cm with thin septa."))
    assert out == {"type": "noul", "instructions": Q_CONTRA + "Left renal cyst 3 cm with thin septa."}


def test_render_t4_appends_cant_tell():
    out = render(q(type="T4", source="dictation", item="two thin septa", options=["thin septa", "thick septa"]))
    assert out["type"] == "choice"
    assert list(out["criteria"]) == ["o1", "o2", CANT_TELL]


def test_render_t5_and_t6():
    assert render(q(type="T5", item="No enhancement.", property="abnormal"))["instructions"] == \
        'The quoted text "No enhancement." itself reports an abnormality or a limitation, including as a possibility.'
    t6 = render(q(type="T6", a="lesion", b="cyst"))
    assert '"lesion"' in t6["instructions"] and '"cyst"' in t6["instructions"]


def test_state_for_dictation_matches_production_state():
    assert state_for(CASE, "dictation").startswith("SCAN TYPE: CT abdomen\nDICTATED FINDINGS:\n")
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_catalogue.py -q`
Expected: FAIL with `ImportError: cannot import name 'render'`

- [ ] **Step 3: Write the implementation (append to `catalogue.py`)**

```python
def _from_wording(kind: str, wording: Optional[str], **slots) -> dict:
    w = WORDINGS[kind][wording or DEFAULT_WORDING[kind]]
    return {"type": "noul", "instructions": w["instructions"].format(**slots),
            "criteria": {k: v.format(**slots) for k, v in w["criteria"].items()}}


def render(spec: QuestionSpec, wording: Optional[str] = None) -> dict:
    """The Jev question JSON for a validated spec. `wording` overrides DEFAULT_WORDING for T2-dictation and T6."""
    t = spec.type
    if t == "T1":
        return {"type": "noul",
                "instructions": f'Read only this one quoted text: "{spec.item}". {SUBJECT[spec.source]} what it says, '
                                "in any wording, abbreviation or synonym, or spread over more than one sentence, "
                                "including as a possibility (not merely implied or inferable).",
                "criteria": {"true": "It is stated there, in any wording (synonym, abbreviation or a more specific "
                                     "form), as present or possible.",
                             "false": "It is not mentioned there, is stated as absent or normal, or only something "
                                      "different that shares some words with it is stated."}}
    if t == "T2":
        if spec.source == "report":
            return {"type": "noul",
                    "instructions": f"Does the {spec.section} section of the report say whether there is {spec.topic}?"}
        return _from_wording("T2d", wording, topic=spec.topic)
    if t == "T3":
        return {"type": "noul", "instructions": Q_CONTRA + spec.clause}
    if t == "T4":
        name = SOURCE_NAME[spec.source]
        criteria = {f"o{i + 1}": o for i, o in enumerate(spec.options)}
        criteria[CANT_TELL] = "It is not possible to tell from this text which description fits."
        return {"type": "choice",
                "instructions": f'Read only this one quoted text: "{spec.item}". Using only the {name}, choose the '
                                "description that fits it.",
                "criteria": criteria}
    if t == "T5":
        return {"type": "noul", "instructions": f'The quoted text "{spec.item}" itself {PROPERTIES[spec.property]}.'}
    return _from_wording("T6", wording, a=spec.a, b=spec.b)
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_catalogue.py -q`
Expected: `15 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/jev_tool_lab/catalogue.py backend/tests/test_jev_tool_lab_catalogue.py
git commit -m "feat(jev-tool-lab): render catalogue questions with code-owned wording

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Rules: banding and the declared decision rule

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/jev_tool_lab/rules.py`
- Test: `backend/tests/test_jev_tool_lab_rules.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_jev_tool_lab_rules.py
from rapid_reports_ai.scripts.jev_tool_lab.catalogue import CANT_TELL
from rapid_reports_ai.scripts.jev_tool_lab.rules import UNSURE, Condition, Rule, band, evaluate


def test_band_noul():
    assert band({"noul": 0.92}, "noul") == "yes"
    assert band({"noul": 0.7}, "noul") == "yes"
    assert band({"noul": 0.1}, "noul") == "no"
    assert band({"noul": 0.5}, "noul") == UNSURE
    assert band(0.95, "noul") == "yes"          # some responses carry a bare float
    assert band(None, "noul") == UNSURE


def test_band_choice():
    assert band({"probabilities": {"o1": 0.8, "o2": 0.15, CANT_TELL: 0.05}}, "choice") == "o1"
    assert band({"probabilities": {"o1": 0.45, "o2": 0.4, CANT_TELL: 0.15}}, "choice") == UNSURE   # margin < 0.2
    assert band({"probabilities": {"o1": 0.2, "o2": 0.1, CANT_TELL: 0.7}}, "choice") == UNSURE
    assert band({}, "choice") == UNSURE


def rule(*conds):
    return Rule(all_of=[Condition(q=q, want=w, label=l) for q, w, l in conds])


def test_evaluate_all_hold():
    r = rule(("q1", "yes", "wall"), ("q2", "yes", "septa"))
    assert evaluate(r, {"q1": "yes", "q2": "yes"}) == ("yes", [])


def test_evaluate_definite_failure_beats_unsure():
    r = rule(("q1", "yes", "wall"), ("q2", "yes", "enhancement"))
    assert evaluate(r, {"q1": UNSURE, "q2": "no"}) == ("no", ["enhancement"])


def test_evaluate_unsure_without_failure():
    r = rule(("q1", "yes", "wall"), ("q2", "yes", "enhancement"))
    assert evaluate(r, {"q1": UNSURE, "q2": "yes"}) == (UNSURE, [])


def test_evaluate_missing_question_is_unsure_and_empty_rule_is_unsure():
    assert evaluate(rule(("q9", "yes", "x")), {}) == (UNSURE, [])
    assert evaluate(Rule(all_of=[]), {"q1": "yes"}) == (UNSURE, [])


def test_evaluate_choice_condition():
    assert evaluate(rule(("q1", "o2", "thick septa")), {"q1": "o2"}) == ("yes", [])
    assert evaluate(rule(("q1", "o2", "thick septa")), {"q1": "o1"}) == ("no", ["thick septa"])
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_rules.py -q`
Expected: FAIL with `ModuleNotFoundError: ... rules`

- [ ] **Step 3: Write the implementation**

```python
# backend/src/rapid_reports_ai/scripts/jev_tool_lab/rules.py
"""Jev answer bands and Qwen's declared decision rule (spec §2.3, §3 arm B).

Bands are fixed with a wide margin, never tuned on the pilot: repeat drift is up to 0.2 (wording suite)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from .catalogue import CANT_TELL

UNSURE = "unsure"
NOUL_HI = 0.7
NOUL_LO = 0.3
CHOICE_MARGIN = 0.2


class Condition(BaseModel):
    q: str        # question id
    want: str     # "yes" / "no" for a noul; an option key ("o1", ...) for a choice
    label: str    # what the condition checks, in a few words; becomes the missing-input text


class Rule(BaseModel):
    all_of: List[Condition]


def _p_yes(ans: Any) -> Optional[float]:
    try:
        return float(ans["noul"] if isinstance(ans, dict) else ans)
    except Exception:
        return None


def band(ans: Any, jev_type: str) -> str:
    """'yes' / 'no' for a noul, the chosen option key for a choice, or UNSURE."""
    if jev_type == "choice":
        try:
            probs = {k: float(v) for k, v in ans["probabilities"].items()}
        except Exception:
            return UNSURE
        ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
        if not ranked or ranked[0][0] == CANT_TELL:
            return UNSURE
        if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < CHOICE_MARGIN:
            return UNSURE
        return ranked[0][0]
    p = _p_yes(ans)
    if p is None:
        return UNSURE
    if p >= NOUL_HI:
        return "yes"
    if p <= NOUL_LO:
        return "no"
    return UNSURE


def evaluate(rule: Rule, banded: Dict[str, str]) -> Tuple[str, List[str]]:
    """('yes', []) when every condition holds; ('no', failed labels) when any condition definitely fails;
    (UNSURE, []) otherwise, including an empty rule or a condition on a dropped question."""
    if not rule.all_of:
        return UNSURE, []
    failed, unsure = [], False
    for c in rule.all_of:
        got = banded.get(c.q, UNSURE)
        if got == UNSURE:
            unsure = True
        elif got != c.want:
            failed.append(c.label)
    if failed:
        return "no", failed
    return (UNSURE, []) if unsure else ("yes", [])
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_rules.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/jev_tool_lab/rules.py backend/tests/test_jev_tool_lab_rules.py
git commit -m "feat(jev-tool-lab): answer bands and declared decision rule

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Scenario S1, prompts and transport

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/jev_tool_lab/scenarios.py`
- Create: `backend/src/rapid_reports_ai/scripts/jev_tool_lab/prompts.py`
- Create: `backend/src/rapid_reports_ai/scripts/jev_tool_lab/calls.py`
- Test: `backend/tests/test_jev_tool_lab_arms.py` (created here; grows in Tasks 5–6)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_jev_tool_lab_arms.py
from rapid_reports_ai.scripts.jev_tool_lab import prompts
from rapid_reports_ai.scripts.jev_tool_lab.scenarios import S1Item, s1_user

ITEM = S1Item(id="s1-t", origin="synthetic", scan_type="CT abdomen",
              dictation="Left renal lesion 3 cm with a thin wall and two thin septa. No enhancement.",
              finding="Left renal lesion 3 cm with a thin wall and two thin septa.", system="Bosniak 2019",
              gradable=True)


def test_s1_user_carries_case_finding_and_system():
    u = s1_user(ITEM)
    assert "DICTATED FINDINGS:\nLeft renal lesion" in u
    assert "FINDING: Left renal lesion 3 cm" in u
    assert "CLASSIFICATION SYSTEM: Bosniak 2019" in u


def test_author_prompt_lists_catalogue_and_forbids_inference():
    p = prompts.author_system()
    for t in ("T1", "T2", "T3", "T4", "T5", "T6"):
        assert t in p
    assert "Never ask what imaging would show" in p
    assert "before seeing any answer" in p


def test_free_prompt_has_no_catalogue():
    p = prompts.free_author_system()
    assert "T2" not in p and "noul" in p


def test_decide_prompt_treats_answers_as_evidence():
    assert "evidence" in prompts.decide_system() and "not as verdicts" in prompts.decide_system()
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_arms.py -q`
Expected: FAIL with `ImportError` on `prompts` / `scenarios`

- [ ] **Step 3: Write the implementation**

```python
# backend/src/rapid_reports_ai/scripts/jev_tool_lab/scenarios.py
"""Scenario S1, grade grounding (spec §4): is the finding gradable with the named system from what was dictated?"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel

from .catalogue import Case

JUDGEMENT_S1 = ("Decide whether the finding can be graded with the named classification system using only what the "
                "dictation states. It is gradable only if every input the system needs for this finding is described "
                "in the dictation; an input stated as absent or normal counts as described. Never assume an input "
                "that is not dictated. If it is not gradable, list each missing input in a few words.")


class S1Item(BaseModel):
    id: str
    origin: Literal["synthetic", "production"]
    seed: str = ""            # production report id prefix the item was seeded from
    scan_type: str
    dictation: str
    finding: str              # verbatim from the dictation
    system: str               # e.g. "Bosniak 2019"
    gradable: bool            # the label
    missing: List[str] = []   # the label's missing inputs, for the hand read

    def case(self) -> Case:
        return Case(scan_type=self.scan_type, dictation=self.dictation)


class Decision(BaseModel):
    gradable: bool
    missing: List[str] = []
    reason: str = ""


def s1_user(item: S1Item) -> str:
    return (f"SCAN TYPE: {item.scan_type}\n\nDICTATED FINDINGS:\n{item.dictation}\n\n"
            f"FINDING: {item.finding}\nCLASSIFICATION SYSTEM: {item.system}")
```

```python
# backend/src/rapid_reports_ai/scripts/jev_tool_lab/prompts.py
"""What Qwen is told in each arm (spec §2.3, §3). Examples are structural, never clinical (case-agnostic rule)."""
from __future__ import annotations

from .scenarios import JUDGEMENT_S1

ROLE = "You are a consultant radiologist checking a report draft against the radiologist's dictation."

CATALOGUE = """QUESTION TYPES. These are the only questions you may ask. Give each an id: q1, q2, ...
T1 STATED: is a quoted piece of text stated in a source text? Slots: source (dictation | report | history), item (an exact quote copied from the case).
T2 TOPIC COVERED: does the source say anything at all about a topic? Slots: source (dictation | report), section (report only: its heading), topic (1-6 plain words, general terms, no negation, no numbers).
T3 CONTRADICTED: does the dictation contradict a report clause? Slots: clause (an exact quote from the report).
T4 WHICH ONE: which of 2-5 clearly different descriptions fits a quoted text, judged from the source? Slots: source, item (an exact quote), options (2-5 short descriptions, clearly different, none the negation of another). A "can't tell" option is added for you.
T5 PROPERTY: does the quoted text itself report an abnormality or a limitation? Slots: source, item (an exact quote), property ("abnormal").
T6 SAME THING: do two quoted texts describe the same structure or finding? Slots: source, a, b (exact quotes).

RULES FOR QUESTIONS
- Ask only about what a text STATES. Never ask what imaging would show, what is expected or likely, or what a grade, system or guideline requires: you know that, so work it out yourself, then ask only whether each input is stated.
- Copy quotes exactly from the case. Never paraphrase inside a quote.
- One judgement per question. Never join two with "or" or "and also".
- For coverage, ask about the topic in general terms (for example "wall thickness of the lesion"), never about a claim or its polarity (not "no enhancement").
- Never ask about numbers, sizes, dates or counts.
- Ask the fewest questions that settle the judgement, at most 8.

STRUCTURAL EXAMPLE (not a clinical one): to decide whether finding X can be classified, where the system needs inputs P, Q and R for X, ask three T2 questions on the dictation, one per input, each topic naming that input of X in general terms.

THE RULE
Declare, before seeing any answer, how the answers decide the judgement. all_of is a list of conditions {q, want, label}. want is "yes" or "no" for T1, T2, T3, T5 and T6, or an option key ("o1", "o2", ...) for T4. label names what the condition checks in a few words; it becomes the missing-input text. The judgement holds only if every condition holds."""

FREE = """Write your own questions for a fast classifier (Jev) that reads the dictation and answers each question. Give each an id: q1, q2, ... Each question has: type ("noul" for a yes/no statement, answered with a probability that it is true; "choice" for picking one option), instructions (the question or statement), and criteria (for a choice: option key -> description; for a noul: optional "true" and "false" descriptions). Ask the fewest questions that settle the judgement, at most 8.

THE RULE
Declare, before seeing any answer, how the answers decide the judgement. all_of is a list of conditions {q, want, label}. want is "yes" or "no" for a noul, or an option key for a choice. label names what the condition checks in a few words; it becomes the missing-input text. The judgement holds only if every condition holds."""


def baseline_system() -> str:
    return f"{ROLE}\n\n{JUDGEMENT_S1}\n\nReturn gradable, missing and a one-sentence reason."


def author_system() -> str:
    return f"{ROLE}\n\n{JUDGEMENT_S1}\n\nDo not decide yet. Plan questions for a fast classifier and declare the rule.\n\n{CATALOGUE}"


def free_author_system() -> str:
    return f"{ROLE}\n\n{JUDGEMENT_S1}\n\nDo not decide yet. Plan questions for a fast classifier and declare the rule.\n\n{FREE}"


def decide_system() -> str:
    return (f"{ROLE}\n\n{JUDGEMENT_S1}\n\nYou asked a fast classifier some questions about the case text. Its answers "
            "are listed below the case as yes / no / unsure, or the chosen option, with the raw probability. Treat them "
            "as evidence about what the text states, not as verdicts: check each against the case yourself, and "
            "overrule an answer you can see is wrong. Return gradable, missing and a one-sentence reason.")
```

```python
# backend/src/rapid_reports_ai/scripts/jev_tool_lab/calls.py
"""Transport: Qwen via the shared agent runner (applies normalise_model_settings), Jev via OpenRouter systemone."""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
import time
from typing import Any, Dict, Tuple

import httpx
from pydantic import BaseModel

from rapid_reports_ai.enhancement_utils import _run_agent_with_model
from rapid_reports_ai.report_reconcile import JEV_MODEL, JEV_URL

QWEN_MODEL = "qwen-3.8-27b"
JEV_TIMEOUT_S = 30
QWEN_TIMEOUT_S = 180


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0


async def qwen(output_type, system: str, user: str, reasoning: bool) -> Tuple[Any, Usage]:
    t = time.monotonic()
    settings = {"temperature": 0, "max_tokens": 8000 if reasoning else 3000,
                "reasoning_effort": "medium" if reasoning else "none"}
    with contextlib.redirect_stdout(io.StringIO()):
        r = await asyncio.wait_for(_run_agent_with_model(model_name=QWEN_MODEL, output_type=output_type,
                                                         system_prompt=system, user_prompt=user, api_key="",
                                                         model_settings=settings), QWEN_TIMEOUT_S)
    usage = Usage(latency_s=time.monotonic() - t)
    try:
        u = r.usage()
        usage.input_tokens = getattr(u, "input_tokens", None) or getattr(u, "request_tokens", 0) or 0
        usage.output_tokens = getattr(u, "output_tokens", None) or getattr(u, "response_tokens", 0) or 0
    except Exception:
        pass
    return r.output, usage


async def jev(by_state: Dict[str, Dict[str, dict]]) -> Tuple[Dict[str, Any], int, float]:
    """{state text: {qid: question}} -> ({qid: raw answer}, calls made, wall-clock seconds). One call per state,
    all concurrent."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    t = time.monotonic()
    async with httpx.AsyncClient() as client:
        async def one(state: str, qs: Dict[str, dict]) -> Dict[str, Any]:
            r = await client.post(JEV_URL, headers={"Authorization": f"Bearer {key}"},
                                  json={"model": JEV_MODEL, "state": state, "questions": qs}, timeout=JEV_TIMEOUT_S)
            r.raise_for_status()
            d = r.json()
            return d.get("answers") or d
        parts = await asyncio.gather(*(one(s, qs) for s, qs in by_state.items() if qs))
    merged: Dict[str, Any] = {}
    for p in parts:
        merged.update(p)
    return merged, len(parts), time.monotonic() - t
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_arms.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/jev_tool_lab/scenarios.py backend/src/rapid_reports_ai/scripts/jev_tool_lab/prompts.py backend/src/rapid_reports_ai/scripts/jev_tool_lab/calls.py backend/tests/test_jev_tool_lab_arms.py
git commit -m "feat(jev-tool-lab): S1 scenario, arm prompts and Jev/Qwen transport

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Arms A, A0 and B, plus the free-form lint

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/jev_tool_lab/arms.py`
- Test: `backend/tests/test_jev_tool_lab_arms.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_jev_tool_lab_arms.py
from rapid_reports_ai.scripts.jev_tool_lab.arms import (ArmResult, FreeQuestion, Plan, arm_a, arm_b, lint_free)
from rapid_reports_ai.scripts.jev_tool_lab.calls import Usage
from rapid_reports_ai.scripts.jev_tool_lab.catalogue import QuestionSpec
from rapid_reports_ai.scripts.jev_tool_lab.rules import Condition, Rule
from rapid_reports_ai.scripts.jev_tool_lab.scenarios import Decision


def fake_qwen(outputs):
    """Returns queued outputs in order; records calls."""
    calls = []
    async def fn(output_type, system, user, reasoning):
        calls.append({"type": output_type.__name__, "reasoning": reasoning, "user": user})
        return outputs.pop(0), Usage(input_tokens=100, output_tokens=50, latency_s=1.0)
    fn.calls = calls
    return fn


def fake_jev(answers):
    seen = []
    async def fn(by_state):
        seen.append(by_state)
        qids = [q for qs in by_state.values() for q in qs]
        return {q: answers[q] for q in qids if q in answers}, len(by_state), 0.4
    fn.seen = seen
    return fn


PLAN = Plan(questions=[QuestionSpec(id="q1", type="T2", source="dictation", topic="wall thickness of the lesion"),
                       QuestionSpec(id="q2", type="T2", source="dictation", topic="septa of the lesion"),
                       QuestionSpec(id="q3", type="T2", source="dictation", topic="enhancement of the lesion")],
            rule=Rule(all_of=[Condition(q="q1", want="yes", label="wall"),
                              Condition(q="q2", want="yes", label="septa"),
                              Condition(q="q3", want="yes", label="enhancement")]))


async def test_arm_a_and_a0():
    q = fake_qwen([Decision(gradable=True, reason="r"), Decision(gradable=False, missing=["x"])])
    a = await arm_a(ITEM, run=1, qwen_fn=q)
    a0 = await arm_a(ITEM, run=1, reasoning=False, qwen_fn=q)
    assert (a.arm, a.decision.gradable, a.latency_s, a.qwen_in) == ("A", True, 1.0, 100)
    assert (a0.arm, a0.decision.gradable) == ("A0", False)
    assert [c["reasoning"] for c in q.calls] == [True, False]


async def test_arm_b_rule_decides_without_second_qwen_call():
    q = fake_qwen([PLAN])
    j = fake_jev({"q1": {"noul": 0.9}, "q2": {"noul": 0.95}, "q3": {"noul": 0.05}})
    fb = ArmResult(arm="A", item_id=ITEM.id, run=1, decision=Decision(gradable=True), latency_s=9.0)
    b = await arm_b(ITEM, run=1, fallback=fb, qwen_fn=q, jev_fn=j)
    assert b.decision == Decision(gradable=False, missing=["enhancement"], reason="rule")
    assert b.rule_outcome == "no" and not b.fallback
    assert len(q.calls) == 1 and q.calls[0]["reasoning"] is False
    assert b.latency_s == 1.4 and b.jev_calls == 1


async def test_arm_b_falls_back_to_a_when_unsure():
    q = fake_qwen([PLAN])
    j = fake_jev({"q1": {"noul": 0.9}, "q2": {"noul": 0.5}, "q3": {"noul": 0.9}})
    fb = ArmResult(arm="A", item_id=ITEM.id, run=1, decision=Decision(gradable=True), latency_s=9.0,
                   qwen_in=1000, qwen_out=500)
    b = await arm_b(ITEM, run=1, fallback=fb, qwen_fn=q, jev_fn=j)
    assert b.fallback and b.decision.gradable is True and b.rule_outcome == "unsure"
    assert b.latency_s == 1.4 + 9.0 and b.qwen_in == 1100


async def test_arm_b_drops_invalid_questions():
    bad = Plan(questions=[QuestionSpec(id="q1", type="T2", source="dictation", topic="no enhancement")],
               rule=Rule(all_of=[Condition(q="q1", want="yes", label="enhancement")]))
    fb = ArmResult(arm="A", item_id=ITEM.id, run=1, decision=Decision(gradable=False), latency_s=2.0)
    b = await arm_b(ITEM, run=1, fallback=fb, qwen_fn=fake_qwen([bad]), jev_fn=fake_jev({}))
    assert b.invalid == ["q1: topic carries a negation"]
    assert b.fallback and b.jev_calls == 0


async def test_arm_errors_are_recorded_not_raised():
    async def boom(*a, **k):
        raise RuntimeError("down")
    a = await arm_a(ITEM, run=1, qwen_fn=boom)
    assert a.decision is None and a.error.startswith("RuntimeError")


def test_lint_free():
    ok = FreeQuestion(id="q1", type="noul",
                      instructions='The dictated findings describe the "septa" of the lesion in some way.')
    assert lint_free(ok) == []
    assert "unquoted" in lint_free(FreeQuestion(id="q2", type="noul", instructions="Is the wall thin?"))
    assert "embedded_negative" in lint_free(FreeQuestion(id="q3", type="noul", instructions='"No enhancement" is stated.'))
    assert "numbers" in lint_free(FreeQuestion(id="q4", type="noul", instructions='"septa" are over 2 mm.'))
    assert "two_judgements" in lint_free(FreeQuestion(id="q5", type="noul", instructions='Is "wall" thin? Is it smooth?'))
    assert "inference" in lint_free(FreeQuestion(id="q6", type="noul", instructions='The "lesion" would enhance.'))
    assert "choice_without_options" in lint_free(FreeQuestion(id="q7", type="choice", instructions='Pick "wall".'))
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_arms.py -q`
Expected: FAIL with `ModuleNotFoundError: ... arms`

- [ ] **Step 3: Write the implementation**

```python
# backend/src/rapid_reports_ai/scripts/jev_tool_lab/arms.py
"""The five arms (spec §3). Every arm returns an ArmResult and never raises; Qwen and Jev are parameters so the
unit tests run on fakes."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

from . import calls, prompts
from .catalogue import MAX_QUESTIONS, QuestionSpec, question_source, render, state_for, validate
from .rules import UNSURE, Rule, band, evaluate
from .scenarios import Decision, S1Item, s1_user


class Plan(BaseModel):
    questions: List[QuestionSpec]
    rule: Rule


class FreeQuestion(BaseModel):
    id: str
    type: Literal["noul", "choice"]
    instructions: str
    criteria: Optional[Dict[str, str]] = None


class FreePlan(BaseModel):
    questions: List[FreeQuestion]
    rule: Rule


class ArmResult(BaseModel):
    arm: str
    item_id: str
    run: int
    decision: Optional[Decision] = None
    latency_s: float = 0.0
    qwen_in: int = 0
    qwen_out: int = 0
    jev_calls: int = 0
    plan: Optional[dict] = None
    answers: Optional[dict] = None
    banded: Optional[dict] = None
    invalid: List[str] = []
    lint: List[str] = []
    rule_outcome: Optional[str] = None
    fallback: bool = False
    error: Optional[str] = None


def _err(arm: str, item: S1Item, run: int, e: Exception) -> ArmResult:
    return ArmResult(arm=arm, item_id=item.id, run=run, error=f"{type(e).__name__}: {str(e)[:200]}")


def _add_usage(res: ArmResult, u) -> None:
    res.latency_s += u.latency_s
    res.qwen_in += u.input_tokens
    res.qwen_out += u.output_tokens


@dataclass
class Asked:
    valid: List[QuestionSpec] = field(default_factory=list)
    invalid: List[str] = field(default_factory=list)
    answers: Dict[str, Any] = field(default_factory=dict)
    banded: Dict[str, str] = field(default_factory=dict)
    calls: int = 0
    latency_s: float = 0.0


async def _ask(questions: List[QuestionSpec], item: S1Item, jev_fn) -> Asked:
    case, out = item.case(), Asked()
    for s in questions[:MAX_QUESTIONS]:
        err = validate(s, case)
        if err:
            out.invalid.append(f"{s.id}: {err}")
        else:
            out.valid.append(s)
    out.invalid += [f"{s.id}: over the cap" for s in questions[MAX_QUESTIONS:]]
    by_state: Dict[str, Dict[str, dict]] = {}
    types: Dict[str, str] = {}
    for s in out.valid:
        q = render(s)
        types[s.id] = q["type"]
        by_state.setdefault(state_for(case, question_source(s)), {})[s.id] = q
    if by_state:
        out.answers, out.calls, out.latency_s = await jev_fn(by_state)
    out.banded = {qid: band(out.answers.get(qid), t) for qid, t in types.items()}
    return out


async def arm_a(item: S1Item, *, run: int, reasoning: bool = True, qwen_fn=calls.qwen) -> ArmResult:
    name = "A" if reasoning else "A0"
    try:
        dec, u = await qwen_fn(Decision, prompts.baseline_system(), s1_user(item), reasoning)
        res = ArmResult(arm=name, item_id=item.id, run=run, decision=dec)
        _add_usage(res, u)
        return res
    except Exception as e:
        return _err(name, item, run, e)


async def arm_b(item: S1Item, *, run: int, fallback: ArmResult, qwen_fn=calls.qwen, jev_fn=calls.jev) -> ArmResult:
    try:
        plan, u = await qwen_fn(Plan, prompts.author_system(), s1_user(item), False)
        asked = await _ask(plan.questions, item, jev_fn)
        outcome, failed = evaluate(plan.rule, asked.banded)
        res = ArmResult(arm="B", item_id=item.id, run=run, plan=plan.model_dump(), answers=asked.answers,
                        banded=asked.banded, invalid=asked.invalid, rule_outcome=outcome, jev_calls=asked.calls,
                        latency_s=asked.latency_s)
        _add_usage(res, u)
        if outcome == UNSURE:
            res.fallback = True
            res.decision = fallback.decision
            res.latency_s += fallback.latency_s
            res.qwen_in += fallback.qwen_in
            res.qwen_out += fallback.qwen_out
        else:
            res.decision = Decision(gradable=outcome == "yes", missing=failed, reason="rule")
        res.latency_s = round(res.latency_s, 6)
        return res
    except Exception as e:
        return _err("B", item, run, e)


_QUOTE = re.compile(r'"([^"]+)"')
_NEG_WORDS = re.compile(r"\b(no|not|without|absent|negative|nil|none)\b", re.I)
_INFER = re.compile(r"\b(would|expected|likely|should|typical|typically|suggests?)\b", re.I)
_TWO = re.compile(r"\b(and also|or whether|and whether|as well as)\b", re.I)


def lint_free(q: FreeQuestion) -> List[str]:
    """Rule breaks in a free-form question (spec §2.1 forbidden list); D's risk measure."""
    text = q.instructions
    quotes = _QUOTE.findall(text)
    outside = _QUOTE.sub(" ", text)
    codes = []
    if not quotes:
        codes.append("unquoted")
    if any(_NEG_WORDS.search(x) for x in quotes):
        codes.append("embedded_negative")
    if re.search(r"\d", text):
        codes.append("numbers")
    if text.count("?") > 1 or _TWO.search(outside):
        codes.append("two_judgements")
    if _INFER.search(outside):
        codes.append("inference")
    if q.type == "choice" and not q.criteria:
        codes.append("choice_without_options")
    return codes
```

Note: the `latency_s == 1.4` assertion depends on `round(..., 6)`, which avoids float noise (1.0 + 0.4).

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_arms.py -q`
Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/jev_tool_lab/arms.py backend/tests/test_jev_tool_lab_arms.py
git commit -m "feat(jev-tool-lab): arms A, A0, B and the free-form lint

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Arms C and D (tool round, free-form)

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/jev_tool_lab/arms.py` (append)
- Test: `backend/tests/test_jev_tool_lab_arms.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_jev_tool_lab_arms.py
from rapid_reports_ai.scripts.jev_tool_lab.arms import FreePlan, arm_c, arm_d


async def test_arm_c_second_turn_sees_answers_and_records_overrule_basis():
    q = fake_qwen([PLAN, Decision(gradable=True, reason="septa described as 'two thin septa'")])
    j = fake_jev({"q1": {"noul": 0.9}, "q2": {"noul": 0.2}, "q3": {"noul": 0.9}})
    c = await arm_c(ITEM, run=1, qwen_fn=q, jev_fn=j)
    assert [x["type"] for x in q.calls] == ["Plan", "Decision"]
    assert all(x["reasoning"] for x in q.calls)
    second = q.calls[1]["user"]
    assert "CLASSIFIER ANSWERS:" in second and "q2" in second and "no" in second
    assert c.rule_outcome == "no" and c.decision.gradable is True       # Qwen overruled the rule
    assert c.latency_s == 2.4 and c.qwen_in == 200


async def test_arm_d_sends_free_questions_and_lints():
    free = FreePlan(questions=[FreeQuestion(id="q1", type="noul", instructions="Is the wall thin?"),
                               FreeQuestion(id="q2", type="choice", instructions='Pick "septa".')],
                    rule=Rule(all_of=[Condition(q="q1", want="yes", label="wall")]))
    q = fake_qwen([free, Decision(gradable=False, missing=["wall"])])
    j = fake_jev({"q1": {"noul": 0.1}})
    d = await arm_d(ITEM, run=1, qwen_fn=q, jev_fn=j)
    assert d.arm == "D" and d.decision.gradable is False
    assert "q1: unquoted" in d.lint and "q2: choice_without_options" in d.lint
    sent = [qid for qs in j.seen[0].values() for qid in qs]
    assert sent == ["q1"]                                                # the option-less choice is not sent
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_arms.py -q`
Expected: FAIL with `ImportError: cannot import name 'arm_c'`

- [ ] **Step 3: Write the implementation (append to `arms.py`)**

```python
def _raw(ans: Any) -> str:
    if isinstance(ans, dict) and "probabilities" in ans:
        return ", ".join(f"{k} {float(v):.2f}" for k, v in ans["probabilities"].items())
    if isinstance(ans, dict) and "noul" in ans:
        return f"{float(ans['noul']):.2f}"
    return "no answer"


def _evidence(described: List[tuple], answers: Dict[str, Any], banded: Dict[str, str]) -> str:
    return "\n".join(f"{qid} ({desc}): {banded.get(qid, UNSURE)} [raw: {_raw(answers.get(qid))}]"
                     for qid, desc in described) or "(no valid questions)"


async def _decide(item: S1Item, described: List[tuple], answers, banded, qwen_fn):
    user = f"{s1_user(item)}\n\nCLASSIFIER ANSWERS:\n{_evidence(described, answers, banded)}"
    return await qwen_fn(Decision, prompts.decide_system(), user, True)


async def arm_c(item: S1Item, *, run: int, qwen_fn=calls.qwen, jev_fn=calls.jev) -> ArmResult:
    try:
        plan, u1 = await qwen_fn(Plan, prompts.author_system(), s1_user(item), True)
        asked = await _ask(plan.questions, item, jev_fn)
        outcome, _ = evaluate(plan.rule, asked.banded)
        described = [(s.id, render(s)["instructions"]) for s in asked.valid]
        dec, u2 = await _decide(item, described, asked.answers, asked.banded, qwen_fn)
        res = ArmResult(arm="C", item_id=item.id, run=run, decision=dec, plan=plan.model_dump(), answers=asked.answers,
                        banded=asked.banded, invalid=asked.invalid, rule_outcome=outcome, jev_calls=asked.calls,
                        latency_s=asked.latency_s)
        _add_usage(res, u1)
        _add_usage(res, u2)
        res.latency_s = round(res.latency_s, 6)
        return res
    except Exception as e:
        return _err("C", item, run, e)


async def arm_d(item: S1Item, *, run: int, qwen_fn=calls.qwen, jev_fn=calls.jev) -> ArmResult:
    try:
        plan, u1 = await qwen_fn(FreePlan, prompts.free_author_system(), s1_user(item), True)
        qs = plan.questions[:MAX_QUESTIONS]
        lint = [f"{q.id}: {code}" for q in qs for code in lint_free(q)]
        send = [q for q in qs if not (q.type == "choice" and not q.criteria)]
        jq = {q.id: {"type": q.type, "instructions": q.instructions, **({"criteria": q.criteria} if q.criteria else {})}
              for q in send}
        answers, n, jlat = (await jev_fn({state_for(item.case(), "dictation"): jq})) if jq else ({}, 0, 0.0)
        banded = {q.id: band(answers.get(q.id), q.type) for q in send}
        outcome, _ = evaluate(plan.rule, banded)
        dec, u2 = await _decide(item, [(q.id, q.instructions) for q in send], answers, banded, qwen_fn)
        res = ArmResult(arm="D", item_id=item.id, run=run, decision=dec, plan=plan.model_dump(), answers=answers,
                        banded=banded, lint=lint, rule_outcome=outcome, jev_calls=n, latency_s=jlat)
        _add_usage(res, u1)
        _add_usage(res, u2)
        res.latency_s = round(res.latency_s, 6)
        return res
    except Exception as e:
        return _err("D", item, run, e)
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_arms.py -q`
Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/jev_tool_lab/arms.py backend/tests/test_jev_tool_lab_arms.py
git commit -m "feat(jev-tool-lab): arms C (tool round) and D (free-form)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Lab runner with reuse

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/jev_tool_lab/run_lab.py`
- Test: `backend/tests/test_jev_tool_lab_arms.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_jev_tool_lab_arms.py
import io as _io
from rapid_reports_ai.scripts.jev_tool_lab import run_lab


async def test_run_lab_order_reuse_and_d_runs(monkeypatch):
    log = []
    def mk(arm):
        async def fn(item, *, run, **kw):
            log.append((arm if arm != "A" or kw.get("reasoning", True) else "A0", item.id, run))
            if arm == "B":
                assert kw["fallback"].arm == "A"            # B receives A's result for the same item and run
            name = "A0" if arm == "A" and kw.get("reasoning") is False else arm
            return ArmResult(arm=name, item_id=item.id, run=run, decision=Decision(gradable=True))
        return fn
    for name, arm in (("arm_a", "A"), ("arm_b", "B"), ("arm_c", "C"), ("arm_d", "D")):
        monkeypatch.setattr(run_lab, name, mk(arm))
    reuse = {run_lab.key("A", ITEM.id, 1): ArmResult(arm="A", item_id=ITEM.id, run=1, decision=Decision(gradable=True))}
    out = _io.StringIO()
    await run_lab.run_lab([ITEM], ["A", "A0", "B", "C", "D"], runs=2, d_runs=1, out=out, reuse=reuse)
    assert ("A", ITEM.id, 1) not in log                       # reused, not re-run
    assert ("A", ITEM.id, 2) in log and ("B", ITEM.id, 2) in log
    assert [x for x in log if x[0] == "D"] == [("D", ITEM.id, 1)]
    assert len(out.getvalue().strip().splitlines()) == 8      # run 1: A0,B,C,D ; run 2: A,A0,B,C
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_arms.py::test_run_lab_order_reuse_and_d_runs -q`
Expected: FAIL with `ImportError` on `run_lab`

- [ ] **Step 3: Write the implementation**

```python
# backend/src/rapid_reports_ai/scripts/jev_tool_lab/run_lab.py
"""Run arms x runs over S1 items and append ArmResults as JSONL (spec §5 phase 2).

    .venv/bin/python -m rapid_reports_ai.scripts.jev_tool_lab.run_lab \
        --items test_cases/jev_tool_lab/s1_pilot.json --out-dir $LAB_OUT --runs 2 --d-runs 1 [--reuse old.jsonl ...]

A is run first in each run because B falls back to A's result for the same item and run (eval economy: the
fallback reuses A rather than calling Qwen again)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List, TextIO

from dotenv import load_dotenv

from .arms import ArmResult, arm_a, arm_b, arm_c, arm_d
from .scenarios import S1Item

CONCURRENCY = 4


def key(arm: str, item_id: str, run: int) -> str:
    return f"{arm}|{item_id}|{run}"


def load_reuse(paths: List[str]) -> Dict[str, ArmResult]:
    done: Dict[str, ArmResult] = {}
    for p in paths:
        for line in Path(p).read_text().splitlines():
            if line.strip():
                r = ArmResult.model_validate_json(line)
                if r.error is None:
                    done[key(r.arm, r.item_id, r.run)] = r
    return done


async def run_lab(items: List[S1Item], arms: List[str], runs: int, d_runs: int, out: TextIO,
                  reuse: Dict[str, ArmResult]) -> None:
    done = dict(reuse)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def go(arm: str, item: S1Item, r: int, make) -> ArmResult:
        k = key(arm, item.id, r)
        if k in done:
            return done[k]
        async with sem:
            res = await make()
        out.write(res.model_dump_json() + "\n")
        out.flush()
        done[k] = res
        return res

    for r in range(1, runs + 1):
        a: Dict[str, ArmResult] = {}
        if "A" in arms or "B" in arms:
            got = await asyncio.gather(*(go("A", it, r, lambda it=it: arm_a(it, run=r)) for it in items))
            a = {x.item_id: x for x in got}
        jobs = []
        for it in items:
            if "A0" in arms:
                jobs.append(go("A0", it, r, lambda it=it: arm_a(it, run=r, reasoning=False)))
            if "B" in arms:
                jobs.append(go("B", it, r, lambda it=it: arm_b(it, run=r, fallback=a[it.id])))
            if "C" in arms:
                jobs.append(go("C", it, r, lambda it=it: arm_c(it, run=r)))
            if "D" in arms and r <= d_runs:
                jobs.append(go("D", it, r, lambda it=it: arm_d(it, run=r)))
        await asyncio.gather(*jobs)


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--arms", default="A,A0,B,C,D")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--d-runs", type=int, default=1)
    ap.add_argument("--reuse", nargs="*", default=[])
    args = ap.parse_args()
    items = [S1Item(**x) for x in json.loads(Path(args.items).read_text())]
    out_path = Path(args.out_dir) / f"results_{os.getpid()}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a") as out:
        asyncio.run(run_lab(items, args.arms.split(","), args.runs, args.d_runs, out, load_reuse(args.reuse)))
    print(out_path)


if __name__ == "__main__":
    main()
```

Note: when "A" is not in `--arms` but "B" is, A still runs, because B needs it. When "A" is in `--arms` but "B" is not, A runs as itself. Both cases share the `"A" in arms or "B" in arms` branch.

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_arms.py -q`
Expected: `13 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/jev_tool_lab/run_lab.py backend/tests/test_jev_tool_lab_arms.py
git commit -m "feat(jev-tool-lab): lab runner with A-first ordering and result reuse

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Scoring: metrics, paired counts, calibration

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/jev_tool_lab/score.py`
- Test: `backend/tests/test_jev_tool_lab_score.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_jev_tool_lab_score.py
import pytest

from rapid_reports_ai.scripts.jev_tool_lab.arms import ArmResult
from rapid_reports_ai.scripts.jev_tool_lab.scenarios import Decision, S1Item
from rapid_reports_ai.scripts.jev_tool_lab.score import (auc, balanced_accuracy, brier, ece, mcnemar_exact, paired,
                                                         percentile, summarise)


def item(i, gradable):
    return S1Item(id=f"i{i}", origin="synthetic", scan_type="CT", dictation="d", finding="d", system="S",
                  gradable=gradable)


ITEMS = {f"i{i}": item(i, i < 2) for i in range(4)}      # i0,i1 gradable; i2,i3 not


def res(arm, i, run, g, **kw):
    return ArmResult(arm=arm, item_id=f"i{i}", run=run, decision=Decision(gradable=g), **kw)


def test_balanced_accuracy_and_percentile():
    assert balanced_accuracy([(True, True), (True, False), (False, False), (False, False)]) == 0.75
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == 9
    assert percentile([], 0.5) is None


def test_calibration_metrics():
    assert brier([1.0, 0.0], [True, False]) == 0.0
    assert ece([0.9, 0.9, 0.1, 0.1], [True, True, False, False], bins=5) == pytest.approx(0.1)
    assert auc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0
    assert auc([0.5, 0.5], [True, False]) == 0.5


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 0) == pytest.approx(0.0625)


def test_paired_gains_and_losses():
    a = [res("A", 0, 1, True), res("A", 1, 1, False), res("A", 2, 1, False), res("A", 3, 1, True)]
    b = [res("B", 0, 1, True), res("B", 1, 1, True), res("B", 2, 1, True), res("B", 3, 1, False)]
    assert paired(b, a, ITEMS, run=1) == {"gains": 2, "losses": 1}   # gains i1, i3; loss i2


def test_summarise_core_fields():
    rows = [res("A", i, r, ITEMS[f"i{i}"].gradable, latency_s=10.0, qwen_in=100) for i in range(4) for r in (1, 2)]
    rows += [res("B", i, 1, True, latency_s=2.0, rule_outcome="yes", plan={"questions": [{}, {}]},
                 invalid=["q1: x"] if i == 0 else []) for i in range(4)]
    rows.append(res("C", 0, 1, False, rule_outcome="yes"))
    s = summarise(rows, ITEMS)
    assert s["A"]["bal_acc"] == 1.0 and s["A"]["stability"] == 1.0 and s["A"]["p90_latency_s"] == 10.0
    assert s["B"]["bal_acc"] == 0.5 and s["B"]["invalid_share"] == pytest.approx(1 / 8)
    assert (s["B"]["vs_A"]["run1"]["gains"], s["B"]["vs_A"]["run1"]["losses"]) == (0, 2)
    assert s["C"]["overrule_share"] == 1.0 and s["C"]["overrule_right_share"] == 0.0
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_score.py -q`
Expected: FAIL with `ModuleNotFoundError: ... score`

- [ ] **Step 3: Write the implementation**

```python
# backend/src/rapid_reports_ai/scripts/jev_tool_lab/score.py
"""Scoring (spec §6, §7): per-arm metrics, paired gains/losses against A, McNemar, and calibration helpers.

    .venv/bin/python -m rapid_reports_ai.scripts.jev_tool_lab.score \
        --items test_cases/jev_tool_lab/s1_pilot.json --results $LAB_OUT/results_*.jsonl"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .arms import ArmResult
from .scenarios import S1Item


def balanced_accuracy(pairs: Sequence[Tuple[bool, bool]]) -> float:
    """pairs of (label, predicted) for the gradable decision."""
    pos = [p for lab, p in pairs if lab]
    neg = [p for lab, p in pairs if not lab]
    tpr = sum(pos) / len(pos) if pos else 0.0
    tnr = sum(1 for p in neg if not p) / len(neg) if neg else 0.0
    return (tpr + tnr) / 2


def percentile(xs: Sequence[float], q: float) -> Optional[float]:
    """Nearest-rank percentile."""
    if not xs:
        return None
    s = sorted(xs)
    return s[max(0, math.ceil(q * len(s)) - 1)]


def brier(probs: Sequence[float], labels: Sequence[bool]) -> float:
    return sum((p - (1.0 if y else 0.0)) ** 2 for p, y in zip(probs, labels)) / len(probs)


def ece(probs: Sequence[float], labels: Sequence[bool], bins: int = 5) -> float:
    total, n = 0.0, len(probs)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(probs) if (lo <= p < hi) or (b == bins - 1 and p == 1.0)]
        if idx:
            conf = sum(probs[i] for i in idx) / len(idx)
            acc = sum(1 for i in idx if labels[i]) / len(idx)
            total += len(idx) / n * abs(acc - conf)
    return total


def auc(probs: Sequence[float], labels: Sequence[bool]) -> float:
    pos = [p for p, y in zip(probs, labels) if y]
    neg = [p for p, y in zip(probs, labels) if not y]
    if not pos or not neg:
        return float("nan")
    wins = sum(1.0 if p > q else 0.5 if p == q else 0.0 for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value on discordant counts b (gains) and c (losses)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def _correct(r: ArmResult, items: Dict[str, S1Item]) -> Optional[bool]:
    if r.decision is None:
        return None
    return r.decision.gradable == items[r.item_id].gradable


def paired(arm_rows: List[ArmResult], a_rows: List[ArmResult], items: Dict[str, S1Item], run: int) -> Dict[str, int]:
    a = {r.item_id: _correct(r, items) for r in a_rows if r.run == run}
    gains = losses = 0
    for r in arm_rows:
        if r.run != run or r.item_id not in a:
            continue
        mine, base = _correct(r, items), a[r.item_id]
        if mine and base is False:
            gains += 1
        elif base and mine is False:
            losses += 1
    return {"gains": gains, "losses": losses}


def summarise(rows: List[ArmResult], items: Dict[str, S1Item]) -> Dict[str, dict]:
    by_arm: Dict[str, List[ArmResult]] = defaultdict(list)
    for r in rows:
        by_arm[r.arm].append(r)
    out: Dict[str, dict] = {}
    for arm, rs in sorted(by_arm.items()):
        ok = [r for r in rs if r.decision is not None]
        pairs = [(items[r.item_id].gradable, r.decision.gradable) for r in ok]
        flag = [p for lab, p in pairs if not lab]          # flag class = not gradable
        clear = [p for lab, p in pairs if lab]
        lat = [r.latency_s for r in ok]
        runs = sorted({r.run for r in rs})
        s = {"n": len(rs), "errors": len(rs) - len(ok),
             "bal_acc": round(balanced_accuracy(pairs), 3) if pairs else None,
             "flag_recall": round(sum(1 for p in flag if not p) / len(flag), 3) if flag else None,
             "false_alarm": round(sum(1 for p in clear if not p) / len(clear), 3) if clear else None,
             "p50_latency_s": percentile(lat, 0.5), "p90_latency_s": percentile(lat, 0.9),
             "mean_qwen_in": round(statistics.mean(r.qwen_in for r in ok), 1) if ok else None,
             "mean_qwen_out": round(statistics.mean(r.qwen_out for r in ok), 1) if ok else None,
             "mean_jev_calls": round(statistics.mean(r.jev_calls for r in ok), 2) if ok else None}
        if len(runs) >= 2:
            first = {r.item_id: r.decision.gradable for r in ok if r.run == runs[0]}
            second = {r.item_id: r.decision.gradable for r in ok if r.run == runs[1]}
            both = [i for i in first if i in second]
            s["stability"] = round(sum(first[i] == second[i] for i in both) / len(both), 3) if both else None
        if arm != "A" and "A" in by_arm:
            s["vs_A"] = {}
            for run in runs:
                g = paired(rs, by_arm["A"], items, run)
                s["vs_A"][f"run{run}"] = {**g, "mcnemar_p": round(mcnemar_exact(g["gains"], g["losses"]), 4)}
        if arm == "B":
            asked = sum(len((r.plan or {}).get("questions", [])) for r in rs)
            s["invalid_share"] = sum(len(r.invalid) for r in rs) / asked if asked else None
            s["fallback_share"] = round(sum(r.fallback for r in rs) / len(rs), 3)
        if arm in ("C", "D"):
            decided = [r for r in ok if r.rule_outcome in ("yes", "no")]
            over = [r for r in decided if r.decision.gradable != (r.rule_outcome == "yes")]
            s["overrule_share"] = round(len(over) / len(decided), 3) if decided else None
            s["overrule_right_share"] = (round(sum(1 for r in over if _correct(r, items)) / len(over), 3)
                                         if over else None)
        if arm == "D":
            asked = sum(len((r.plan or {}).get("questions", [])) for r in rs)
            linted = sum(len({e.split(":")[0] for e in r.lint}) for r in rs)
            s["lint_share"] = round(linted / asked, 3) if asked else None
        out[arm] = s
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--results", nargs="+", required=True)
    args = ap.parse_args()
    items = {x["id"]: S1Item(**x) for x in json.loads(Path(args.items).read_text())}
    rows = [ArmResult.model_validate_json(line) for p in args.results
            for line in Path(p).read_text().splitlines() if line.strip()]
    summary = summarise(rows, items)
    print(json.dumps(summary, indent=2))
    dest = Path(args.results[0]).parent / f"summary_{os.getpid()}.json"
    dest.write_text(json.dumps(summary, indent=2))
    print(dest)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_score.py -q`
Expected: `5 passed`

- [ ] **Step 5: Run the whole lab suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_*.py -q`
Expected: `40 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/jev_tool_lab/score.py backend/tests/test_jev_tool_lab_score.py
git commit -m "feat(jev-tool-lab): scoring with paired counts, McNemar and calibration helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Wording mini-check CLI (phase 1)

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/jev_tool_lab/wording_check.py`
- Test: `backend/tests/test_jev_tool_lab_score.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_jev_tool_lab_score.py
from rapid_reports_ai.scripts.jev_tool_lab import wording_check as wc


async def test_wording_check_runs_and_reports():
    items = [wc.CheckItem(id="t1", kind="T2d", dictation="Thin septa.", topic="septa of the lesion", label=True),
             wc.CheckItem(id="t2", kind="T2d", dictation="Thin septa.", topic="calcification", label=False),
             wc.CheckItem(id="s1", kind="T6", dictation="Left cyst. Right cyst.", a="Left cyst", b="Right cyst",
                          label=False)]
    async def fake_jev(by_state):
        ans = {}
        for qs in by_state.values():
            for qid in qs:
                ans[qid] = {"noul": 0.9 if qid.startswith("t1") else 0.1}
        return ans, len(by_state), 0.1
    rows = await wc.run(items, wordings=("w1", "w2"), repeats=2, jev_fn=fake_jev)
    assert len(rows) == 3 * 2 * 2
    rep = wc.report(rows)
    t2 = rep["T2d|w1"]
    assert t2["auc"] == 1.0 and t2["confident_errors"] == 0 and t2["unsure_share"] == 0.0 and t2["max_drift"] == 0.0
    assert rep["T6|w1"]["n"] == 1
```

- [ ] **Step 2: Run the test and check it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_score.py::test_wording_check_runs_and_reports -q`
Expected: FAIL with `ImportError` on `wording_check`

- [ ] **Step 3: Write the implementation**

```python
# backend/src/rapid_reports_ai/scripts/jev_tool_lab/wording_check.py
"""Phase 1 (spec §5): the wording mini-check for the two new catalogue wordings, T2 on the dictation (T2d) and T6.

    .venv/bin/python -m rapid_reports_ai.scripts.jev_tool_lab.wording_check \
        --items test_cases/jev_tool_lab/wording_check.json --out-dir $LAB_OUT

A wording passes when AUC >= 0.95, there are zero confident errors at the fixed bands (0.3 / 0.7), at most 20% of
answers land in the unsure band, and repeat drift stays <= 0.2."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel

from . import calls
from .catalogue import Case, QuestionSpec, render, state_for
from .rules import NOUL_HI, NOUL_LO, _p_yes
from .score import auc, brier, ece


class CheckItem(BaseModel):
    id: str
    kind: Literal["T2d", "T6"]
    scan_type: str = ""
    dictation: str
    topic: Optional[str] = None
    a: Optional[str] = None
    b: Optional[str] = None
    label: bool


def question(item: CheckItem, wording: str) -> dict:
    if item.kind == "T2d":
        spec = QuestionSpec(id=item.id, type="T2", source="dictation", topic=item.topic)
    else:
        spec = QuestionSpec(id=item.id, type="T6", source="dictation", a=item.a, b=item.b)
    return render(spec, wording=wording)


async def run(items: List[CheckItem], wordings=("w1", "w2"), repeats: int = 2, jev_fn=calls.jev) -> List[dict]:
    rows: List[dict] = []
    for wording in wordings:
        for rep in range(1, repeats + 1):
            by_state: Dict[str, Dict[str, dict]] = defaultdict(dict)
            for it in items:
                state = state_for(Case(scan_type=it.scan_type, dictation=it.dictation), "dictation")
                by_state[state][it.id] = question(it, wording)
            answers, _, _ = await jev_fn(dict(by_state))
            for it in items:
                rows.append({"id": it.id, "kind": it.kind, "wording": wording, "repeat": rep,
                             "p": _p_yes(answers.get(it.id)), "label": it.label})
    return rows


def report(rows: List[dict]) -> Dict[str, dict]:
    groups: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        if r["p"] is not None:
            groups[f"{r['kind']}|{r['wording']}"].append(r)
    out: Dict[str, dict] = {}
    for g, rs in sorted(groups.items()):
        ps, ys = [r["p"] for r in rs], [r["label"] for r in rs]
        by_id: Dict[str, List[float]] = defaultdict(list)
        for r in rs:
            by_id[r["id"]].append(r["p"])
        out[g] = {"n": len(by_id), "auc": round(auc(ps, ys), 3), "brier": round(brier(ps, ys), 3),
                  "ece": round(ece(ps, ys), 3),
                  "confident_errors": sum(1 for p, y in zip(ps, ys) if (p >= NOUL_HI and not y) or (p <= NOUL_LO and y)),
                  "unsure_share": round(sum(1 for p in ps if NOUL_LO < p < NOUL_HI) / len(ps), 3),
                  "max_drift": round(max((max(v) - min(v) for v in by_id.values()), default=0.0), 3)}
    return out


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    items = [CheckItem(**x) for x in json.loads(Path(args.items).read_text())]
    rows = asyncio.run(run(items))
    rep = report(rows)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"wording_rows_{os.getpid()}.json").write_text(json.dumps(rows, indent=1))
    (out / f"wording_report_{os.getpid()}.json").write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
```

The test expects `t1` at 0.9 and `t2` at 0.1. `t1` is labelled True and `t2` False, so AUC is 1.0. Both repeats return the same value, so there is no drift.

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_*.py -q`
Expected: `41 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/jev_tool_lab/wording_check.py backend/tests/test_jev_tool_lab_score.py
git commit -m "feat(jev-tool-lab): wording mini-check CLI for the new T2d and T6 wordings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Production seeds (read-only, scratchpad only)

This gives the synthetic items real structure: which classification systems appear in production, and how dictations describe their inputs. Nothing from this task enters the repo (memory `feedback_prod_access`).

**Files:**
- Create (scratchpad only): `$LAB_OUT/seeds_raw.json`, `$LAB_OUT/seeds.md`

- [ ] **Step 1: Pull classification cards with their dictations through Metabase**

```bash
cd backend && set -a && source .env && set +a && mkdir -p "$LAB_OUT"
SQL="SELECT r.id::text AS report_id, r.created_at,
  COALESCE(r.input_data->>'findings', r.input_data->'variables'->>'FINDINGS') AS findings,
  c AS classification
FROM reports r, LATERAL jsonb_path_query(r.enhancement_json::jsonb, 'lax \$.**.classifications[*]') AS c
WHERE r.enhancement_json IS NOT NULL AND r.created_at > now() - interval '60 days'
ORDER BY r.created_at DESC LIMIT 60"
jq -n --arg q "$SQL" '{database: 2, type: "native", native: {query: $q}}' \
 | curl -s -X POST "$METABASE_URL/api/dataset" -H "x-api-key: $METABASE_API_KEY" -H "Content-Type: application/json" -d @- \
 > "$LAB_OUT/seeds_raw.json"
jq '.data.rows | length' "$LAB_OUT/seeds_raw.json"
```

Expected: a number between 1 and 60.

If it prints `0` or `null`, inspect the shape first:

```bash
SQL="SELECT DISTINCT jsonb_object_keys(enhancement_json::jsonb) FROM reports WHERE enhancement_json IS NOT NULL LIMIT 50"
```

Run it the same way, then adjust the JSON path to wherever `classifications` lives.

- [ ] **Step 2: Summarise the seeds by hand into `$LAB_OUT/seeds.md`**

Use `jq` to list each `system` with a count, and pick about 10 cards across at least 4 systems. For each card, note:
- the system;
- the dictated finding sentence;
- which inputs the dictation states, which it states as absent, and which it doesn't state.

This note is the template for the synthetic items in Task 11. Don't copy patient text into the repo.

- [ ] **Step 3: No commit** (scratchpad only)

---

### Task 11: Synthetic fixtures: wording check (40) and S1 pilot (20)

**Files:**
- Create: `backend/test_cases/jev_tool_lab/wording_check.json`
- Create: `backend/test_cases/jev_tool_lab/s1_pilot.json`
- Test: `backend/tests/test_jev_tool_lab_score.py` (append a fixture-shape test)

- [ ] **Step 1: Write the fixture-shape test first**

```python
# append to backend/tests/test_jev_tool_lab_score.py
import json as _json
from pathlib import Path as _Path

from rapid_reports_ai.scripts.jev_tool_lab.catalogue import Case, QuestionSpec, validate

_FIX = _Path(__file__).resolve().parents[1] / "test_cases" / "jev_tool_lab"


def test_wording_fixture_shape():
    items = [wc.CheckItem(**x) for x in _json.loads((_FIX / "wording_check.json").read_text())]
    for kind in ("T2d", "T6"):
        k = [i for i in items if i.kind == kind]
        assert len(k) == 20 and sum(i.label for i in k) == 10
    for i in items:
        spec = (QuestionSpec(id=i.id, type="T2", source="dictation", topic=i.topic) if i.kind == "T2d"
                else QuestionSpec(id=i.id, type="T6", source="dictation", a=i.a, b=i.b))
        assert validate(spec, Case(dictation=i.dictation)) is None, i.id


def test_s1_fixture_shape():
    items = [S1Item(**x) for x in _json.loads((_FIX / "s1_pilot.json").read_text())]
    assert len(items) == 20 and sum(i.gradable for i in items) == 10
    assert len({i.system for i in items}) >= 5 and len({i.scan_type for i in items}) >= 4
    for i in items:
        assert i.finding in i.dictation, i.id
        assert i.gradable == (not i.missing), i.id
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_score.py -k fixture -q`
Expected: FAIL with `FileNotFoundError`

- [ ] **Step 3: Write `wording_check.json` (40 items)**

**T2d (20 items, 10 true, 10 false).** The question is "does the dictation say anything about this topic?"
- The **true** set must include:
  - topics stated as **absent or normal** (absence counts as covered; this is the key polarity test);
  - topics described only by **synonym**;
  - topics described only by a **measurement**.
- The **false** set must include **adjacent** topics that aren't mentioned, e.g. the same organ but a different property, or the property of a different organ that is mentioned.
- Spread the cases over at least 4 modalities and body regions.
- Every `topic` must pass `validate`: 1–6 words, no negation word, no digits. The fixture test enforces this.

**T6 (20 pairs, 10 true, 10 false).** The question is "do the two quoted spans describe the same structure or finding?"
- The **true** set must include the same finding in different words.
- The **false** set must include:
  - the same structure on the **other side**;
  - the same finding at a **different level**;
  - two different findings in the same organ.
- Both `a` and `b` must be verbatim from the item's `dictation`.

Format, with two examples per kind written out. Write all 40 in this shape:

```json
[
  {"id": "t2d-01", "kind": "T2d", "scan_type": "CT abdomen", "dictation": "Right renal lesion 2 cm. No enhancement after contrast. Thin wall.", "topic": "enhancement of the renal lesion", "label": true},
  {"id": "t2d-02", "kind": "T2d", "scan_type": "CT abdomen", "dictation": "Right renal lesion 2 cm. No enhancement after contrast. Thin wall.", "topic": "calcification in the renal lesion", "label": false},
  {"id": "t6-01", "kind": "T6", "scan_type": "MRI knee", "dictation": "Tear of the posterior horn of the medial meniscus. Medial meniscal posterior horn tear extends to the inferior surface.", "a": "Tear of the posterior horn of the medial meniscus", "b": "Medial meniscal posterior horn tear", "label": true},
  {"id": "t6-02", "kind": "T6", "scan_type": "CT chest", "dictation": "Left lower lobe nodule 6 mm. Right lower lobe nodule 4 mm.", "a": "Left lower lobe nodule", "b": "Right lower lobe nodule", "label": false}
]
```

- [ ] **Step 4: Write `s1_pilot.json` (20 items)**

**Mix:**
- 10 gradable and 10 not gradable;
- at least 5 classification systems across at least 4 scan types, taken from `seeds.md` (e.g. Bosniak 2019, LI-RADS, Fleischner, TI-RADS, O-RADS US, Kellgren–Lawrence, AAST organ injury);
- at least half mirror the structure of a production seed (set `origin` to `"synthetic"` and `seed` to its report id prefix).

**Hard cases, in both classes:**
- an input stated only as **absent** (still gradable);
- an input **implied but not stated** (not gradable);
- an input given only as a measurement;
- a second finding nearby that carries the missing input. It isn't the graded finding, so the item is not gradable.

**Rules:**
- `finding` must be verbatim from `dictation`.
- `missing` is empty exactly when `gradable` is true.

Format, with two examples. Write all 20 in this shape:

```json
[
  {"id": "s1-01", "origin": "synthetic", "seed": "", "scan_type": "CT abdomen", "dictation": "Left renal lesion 3.2 cm with a thin smooth wall and two thin septa. No enhancement: 14 HU unenhanced, 16 HU nephrographic. No calcification.", "finding": "Left renal lesion 3.2 cm with a thin smooth wall and two thin septa.", "system": "Bosniak 2019", "gradable": true, "missing": []},
  {"id": "s1-02", "origin": "synthetic", "seed": "", "scan_type": "CT abdomen", "dictation": "Right renal cystic lesion 2.8 cm with one thick irregular septum. Simple cyst in the left kidney shows no enhancement.", "finding": "Right renal cystic lesion 2.8 cm with one thick irregular septum.", "system": "Bosniak 2019", "gradable": false, "missing": ["enhancement of the right lesion"]}
]
```

The second example is the "nearby finding" trap: the enhancement statement belongs to the left cyst.

- [ ] **Step 5: Run the tests and check they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jev_tool_lab_*.py -q`
Expected: `43 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/test_cases/jev_tool_lab/ backend/tests/test_jev_tool_lab_score.py
git commit -m "test(jev-tool-lab): synthetic wording-check and S1 pilot fixtures seeded from production structure

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: CHECKPOINT: Hassan reviews the labels**

Write `$LAB_OUT/labels_review.md`. Show each item's dictation, the question (topic, or pair, or finding plus system) and the label, and ask Hassan to mark any label he disagrees with. Fix the disputed labels, rerun Step 5 and amend the commit. **Do not run Tasks 12–13 until he has signed off.**

---

### Task 12: Run the wording mini-check (phase 1)

- [ ] **Step 1: Run it**

```bash
cd backend && .venv/bin/python -m rapid_reports_ai.scripts.jev_tool_lab.wording_check \
  --items test_cases/jev_tool_lab/wording_check.json --out-dir "$LAB_OUT"
```

Expected: a JSON report with the keys `T2d|w1`, `T2d|w2`, `T6|w1` and `T6|w2`. Each has `n: 20` plus `auc`, `brier`, `ece`, `confident_errors`, `unsure_share` and `max_drift`.

- [ ] **Step 2: Choose the wordings**

A wording passes when:
- `auc ≥ 0.95`;
- `confident_errors == 0`;
- `unsure_share ≤ 0.2`;
- `max_drift ≤ 0.2`.

For each kind, choose the passing wording with the lower `brier`. Hand-read every confident error and every item in the unsure band, and note whether the label or the wording is at fault.

- **Both kinds pass:** set `DEFAULT_WORDING` in `catalogue.py` to the chosen keys and run `.venv/bin/python -m pytest tests/test_jev_tool_lab_*.py -q`. Expect `43 passed`. The render tests either pass `wording` explicitly or check only what both wordings share.
- **T2d fails both wordings: STOP.** Arm B depends on it for S1. Report to Hassan with the hand read, and propose a third wording built from the failure pattern.
- **Only T6 fails:** set T6 aside, remove it from the catalogue text in `prompts.py` for the pilot, and say so in the pilot write-up.

- [ ] **Step 3: Record and commit**

Add the chosen wordings and the four rows of results to the lab spec under a new heading, `## Results: phase 1 (wording mini-check)`, then commit:

```bash
git add backend/src/rapid_reports_ai/scripts/jev_tool_lab/catalogue.py docs/superpowers/specs/2026-10-02-qwen-authored-jev-questions-lab-design.md
git commit -m "chore(jev-tool-lab): choose T2d and T6 wordings from the mini-check

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Run the S1 pilot (phase 2) and stop for the read

- [ ] **Step 1: Smoke-test on 2 items, one run, every arm**

```bash
cd backend && jq '.[0:2]' test_cases/jev_tool_lab/s1_pilot.json > "$LAB_OUT/smoke_items.json"
.venv/bin/python -m rapid_reports_ai.scripts.jev_tool_lab.run_lab \
  --items "$LAB_OUT/smoke_items.json" --out-dir "$LAB_OUT/smoke" --runs 1 --d-runs 1
jq -c '{arm, item_id, error, g: .decision.gradable, inv: .invalid, fb: .fallback, lat: .latency_s}' "$LAB_OUT"/smoke/results_*.jsonl
```

Expected: 10 lines (5 arms × 2 items) with `error: null`.

- **If arm B or C shows a structured-output failure:** Qwen's nested `Plan` failed to parse. Look at the error text before changing anything. The memory note `project_model_routing` records nested-output trouble that turned out to be a schema bug.
- **If `invalid` is non-empty:** read the reasons. They are a result in their own right (question quality), not a bug.

- [ ] **Step 2: Run the pilot**

```bash
.venv/bin/python -m rapid_reports_ai.scripts.jev_tool_lab.run_lab \
  --items test_cases/jev_tool_lab/s1_pilot.json --out-dir "$LAB_OUT/pilot" --runs 2 --d-runs 1 \
  --reuse "$LAB_OUT"/smoke/results_*.jsonl
```

Expected: one results file, about 180 lines. The smoke items' run-1 rows are reused rather than re-run.

- [ ] **Step 3: Score it**

```bash
.venv/bin/python -m rapid_reports_ai.scripts.jev_tool_lab.score \
  --items test_cases/jev_tool_lab/s1_pilot.json --results "$LAB_OUT"/pilot/results_*.jsonl "$LAB_OUT"/smoke/results_*.jsonl
```

Expected: a summary per arm (A, A0, B, C, D) with `bal_acc`, `p90_latency_s`, token means, `stability` (not for D), `vs_A` gains and losses per run, B's `invalid_share` and `fallback_share`, C/D's `overrule_share`, and D's `lint_share`.

- [ ] **Step 4: Prepare the read for Hassan**

Write `$LAB_OUT/pilot_read.md` with three parts.

1. **The go / no-go table from spec §7.1,** filled in from the summary:
   - **B:** losses ≤ 1 in both runs; p90 latency or cost ≤ 70% of A; stability ≥ A.
   - **C:** gains ≥ 3 with losses ≤ 1 in both runs.
   - **A0 vs B:** compare their losses against A, so any B gain can be credited to Jev.

   Cost uses Qwen tokens, since Jev is negligible. State the token ratio B/A and the latency ratio.
2. **Every disagreement between arms, item by item:**
   - the dictation;
   - each arm's decision, with its missing inputs;
   - for B and C, the questions asked, Jev's banded answers and the declared rule;
   - which arm matched the label, and why the others didn't.
3. **Question quality:**
   - B's invalid reasons, tallied;
   - D's lint codes, tallied, with 5 D questions quoted that break a rule;
   - three B or C plans quoted in full, as examples of what Qwen asks.

- [ ] **Step 5: Record and commit**

Add `## Results: phase 2 (S1 pilot)` to the lab spec, with the summary table and the go / no-go verdict marked "pending Hassan's read". Then commit:

```bash
git add docs/superpowers/specs/2026-10-02-qwen-authored-jev-questions-lab-design.md
git commit -m "docs(jev-tool-lab): S1 pilot results, pending the hand read

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: STOP**

Show Hassan `pilot_read.md`. The expansion (≥ 100 items, spec §7.2) and every other scenario wait for his decision.
