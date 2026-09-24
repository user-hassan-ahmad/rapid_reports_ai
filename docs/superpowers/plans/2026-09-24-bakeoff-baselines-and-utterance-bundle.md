# Bake-off Baselines + Per-Utterance Jev Bundle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every dictation bake-off a plain-code baseline column and 95 % intervals (handover §6 item 2). Then put the triage, `standalone` and section-coverage questions into **one Jev call per utterance** and show per-question parity with the separate calls, plus bundle p95 < 500 ms (handover §6 item 3; rev 2 §4 component 1, §7 experiment 1).

**Architecture:** Two pure helper modules: `scripts/bakeoff_stats.py` (Wilson interval, bootstrap p95 interval, formatting) and `scripts/bakeoff_baselines.py` (lexicon/regex classifiers, no network). The three existing bake-off scripts add a `code` candidate and print intervals. A new `utterance_bundle.py` reuses the separate components' question texts rather than copying them, and sends them all in one System One request. A new `scripts/bundle_parity.py` maps every fixture from the three sets into bundle state and runs **reference → bundle → reference again** on each case. Each question is scored as the bundle's misses against the reference, measured against the reference's own run-to-run noise. The script exits non-zero unless every question passes and the latency gate holds.

**Tech Stack:** Python 3.12, httpx (`MockTransport` in tests), pytest with `asyncio_mode = "auto"`, OpenRouter System One (`typesafe/jev-1.13`).

**Evidence base:** handover `docs/superpowers/handover/2026-09-24-jev-dictation-lab-handover.md` §6 items 2–3; spec `docs/superpowers/specs/2026-09-24-decision-first-dictation-design.md` (rev 2) §2 "Honest error bars", §4 row 1, §5 invariants, §7.1.

---

## Conventions for every task

- Work in the worktree: `cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/dictation-triage-lab/backend`
- The editable install points at the main tree, so always set `PYTHONPATH=src` and use the main venv:
  `PY=/Users/hassan/Code/rapid_reports_ai/backend/.venv/bin/python`
- Test command form: `PYTHONPATH=src $PY -m pytest -q tests/<file>.py`
- Live runs need `backend/.env` in the worktree (symlink or copy it from the main tree if missing: `ls -la .env`).
- Commit only the files named in each step. Commit messages end with
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Honest-baseline rule (read before Task 2)

The baselines in Task 2 were drafted after reading the fixtures. A first draft reached 47/49 on triage because its filler list contained fixture phrases ("close the door", "scroll down"), so those phrases were removed. The rule: **a lexicon entry must be a generic dictation cue a radiologist would plausibly say anywhere, never a phrase lifted from a fixture.** Do not tune the baselines after the live run. Baseline scores are an optimistic ceiling for a lexicon approach and are reported as such.

Prototype scores of the Task 2 code on today's fixtures (use them to sanity-check Task 6):

| Set | Baseline | Jev (2026-09-24 run) |
|---|---|---|
| Triage action (49) | 45/49 = 0.918 [0.81, 0.97] | 0.979 (47/48) |
| Boundary 3-way (39) | 35/39 = 0.897 [0.76, 0.96] | raw 0.868 |
| Standalone, complete/continues only (29) | 25/29 | not previously scored |
| Coverage exact set (26) | 14/26 = 0.538 [0.35, 0.71]; P 25/28, R 25/47 | exact 0.92, P 1.0, R 0.955 |

On today's fixtures the lexicon matches Jev on the boundary and nearly matches it on triage; Jev's lead is on coverage. Those numbers bear on rev 2 §2's rule that Jev must earn its place through calibration. Record them in Task 6 as they come out; do not argue them away.

## File structure

| File | Responsibility |
|---|---|
| Create `backend/src/rapid_reports_ai/scripts/bakeoff_stats.py` | `wilson`, `rate`, `fmt_rate`, `quantile`, `bootstrap_quantile_ci`. Pure, no project imports. |
| Create `backend/src/rapid_reports_ai/scripts/bakeoff_baselines.py` | `baseline_triage`, `baseline_boundary`, `baseline_coverage`, `is_command`. Pure. |
| Modify `backend/src/rapid_reports_ai/scripts/triage_summary.py` | add `accuracy_rate`, `hard.rate`, `latency_p95_ci_ms`; print intervals |
| Modify `backend/src/rapid_reports_ai/scripts/triage_bakeoff.py` | `code_record(case)`; `code` candidate on by default |
| Modify `backend/src/rapid_reports_ai/scripts/coverage_bakeoff.py` | `code_row(case)`; rate fields; print intervals |
| Rewrite `backend/src/rapid_reports_ai/scripts/boundary_bakeoff.py` | pure `score_boundary(rows)`; `code` column; standalone scoring; intervals |
| Create `backend/src/rapid_reports_ai/utterance_bundle.py` | `BundleState`, `bundle_questions`, `JevBundle`, `BundleDecision`, `get_jev_bundle` |
| Create `backend/src/rapid_reports_ai/scripts/bundle_parity.py` | fixture → state mappers, `Unit`, unit builders, `verdict`, `latency_gate`, live runner |
| Tests: create `tests/test_bakeoff_stats.py`, `tests/test_bakeoff_baselines.py`, `tests/test_boundary_bakeoff.py`, `tests/test_utterance_bundle.py`, `tests/test_bundle_parity.py`; modify `tests/test_triage_summary.py`, `tests/test_coverage_bakeoff.py` | |
| Modify `docs/superpowers/handover/2026-09-24-jev-dictation-lab-handover.md` | §3 results rows, §6 items 2–3 status |

Out of scope: wiring the bundle into `/api/canvas/*` routes. Its first consumer is the fast-append band router (component 2), which gets its own plan. The bundle's coverage questions ask about the scratchpad **before** this utterance, matching today's `/review` call so that parity can be measured. Per-utterance section nouls and the collective map are component 3.

---

### Task 1: Interval helpers

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/bakeoff_stats.py`
- Test: `backend/tests/test_bakeoff_stats.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest

from rapid_reports_ai.scripts.bakeoff_stats import bootstrap_quantile_ci, fmt_rate, quantile, rate, wilson


def test_wilson_known_values():
    lo, hi = wilson(47, 48)
    assert lo == pytest.approx(0.891, abs=1e-3) and hi == pytest.approx(0.9963, abs=1e-3)
    assert wilson(0, 10)[0] == 0.0 and wilson(0, 10)[1] == pytest.approx(0.2775, abs=1e-3)
    assert wilson(10, 10)[1] == 1.0 and wilson(10, 10)[0] == pytest.approx(0.7225, abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)


def test_rate_and_format():
    r = rate(45, 49)
    assert r["k"] == 45 and r["n"] == 49 and r["p"] == pytest.approx(45 / 49)
    assert r["ci95"] == [pytest.approx(0.8081, abs=1e-4), pytest.approx(0.9678, abs=1e-4)]
    assert fmt_rate(r) == "0.918 [0.81, 0.97] (45/49)"
    assert rate(0, 0)["p"] is None and fmt_rate(rate(0, 0)) == "n/a (0/0)"


def test_quantile_matches_nearest_rank():
    assert quantile([], 0.95) == 0
    assert quantile([100, 200, 300, 400], 0.5) == 300
    assert quantile(list(range(1, 101)), 0.95) == 95


def test_bootstrap_ci_is_ordered_and_deterministic():
    vals = [300] * 95 + [900] * 5
    lo, hi = bootstrap_quantile_ci(vals, 0.95)
    assert 300 <= lo <= hi <= 900
    assert bootstrap_quantile_ci(vals, 0.95) == (lo, hi)  # seeded
    assert bootstrap_quantile_ci([250] * 20, 0.95) == (250, 250)
    assert bootstrap_quantile_ci([], 0.95) == (0, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_bakeoff_stats.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'rapid_reports_ai.scripts.bakeoff_stats'`

- [ ] **Step 3: Write the implementation**

```python
"""Intervals for bake-off numbers. Every bake-off reports a 95 % interval (rev 2 §5).

Proportions use the Wilson score interval (sane at 0/n and n/n, unlike the normal
approximation). Latency p95 uses a seeded percentile bootstrap so reruns print the
same interval for the same data.
"""
from __future__ import annotations

import random
from math import sqrt
from typing import Any, Optional

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson(k, n)
    p: Optional[float] = k / n if n else None
    return {"k": k, "n": n, "p": p, "ci95": [round(lo, 4), round(hi, 4)]}


def fmt_rate(r: dict[str, Any]) -> str:
    if not r["n"]:
        return f"n/a ({r['k']}/{r['n']})"
    lo, hi = r["ci95"]
    return f"{r['p']:.3f} [{lo:.2f}, {hi:.2f}] ({r['k']}/{r['n']})"


def quantile(values: list[int], q: float) -> int:
    """Nearest-rank on the sorted values; same convention as triage_summary._p."""
    if not values:
        return 0
    s = sorted(values)
    return s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))]


def bootstrap_quantile_ci(values: list[int], q: float, n_boot: int = 2000, seed: int = 0) -> tuple[int, int]:
    if not values:
        return (0, 0)
    rng = random.Random(seed)
    stats = sorted(quantile([rng.choice(values) for _ in values], q) for _ in range(n_boot))
    return (stats[int(0.025 * (n_boot - 1))], stats[int(0.975 * (n_boot - 1))])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_bakeoff_stats.py`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/bakeoff_stats.py backend/tests/test_bakeoff_stats.py
git commit -m "feat(bakeoff): Wilson and bootstrap-p95 intervals for every bake-off number"
```

---

### Task 2: Plain-code baselines

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/bakeoff_baselines.py`
- Test: `backend/tests/test_bakeoff_baselines.py`

Tests use synthetic strings, not the fixtures. A test pinned to fixture scores would fail on every lab export.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest

from rapid_reports_ai.scripts.bakeoff_baselines import (
    baseline_boundary,
    baseline_coverage,
    baseline_triage,
    is_command,
)


@pytest.mark.parametrize("utt,expected", [
    ("Scratch that", "delete_previous_utterance"),
    ("remove the last sentence", "delete_previous_utterance"),
    ("new paragraph", "formatting_command"),
    ("next line please", "formatting_command"),
    ("full stop", "formatting_command"),
    ("actually the right side", "correct_previous_finding"),
    ("make that twelve millimetres", "correct_previous_finding"),
    ("severe not mild", "correct_previous_finding"),
    ("um er okay", "ignore_noise"),
    ("hang on a second", "ignore_noise"),
    ("small left pleural effusion", "append_new_finding"),
    ("the spleen is normal", "restate_existing_finding"),
])
def test_triage(utt, expected):
    assert baseline_triage("", "- spleen normal", utt) == expected


def test_triage_restate_uses_committed_too():
    assert baseline_triage("- 4 mm renal calculus", "", "renal calculus 4 mm") == "restate_existing_finding"
    assert baseline_triage("", "", "renal calculus 4 mm") == "append_new_finding"


@pytest.mark.parametrize("buffered,chunk,expected", [
    ("", "delete that", "command"),
    ("", "generate report", "command"),
    ("", "switch to verbatim mode", "command"),
    ("", "the", "continues"),
    ("there is a lesion", "in the", "continues"),
    ("", "measuring", "continues"),
    ("", "the pancreas is normal", "complete"),
    ("a cyst", "in the left kidney", "complete"),
])
def test_boundary(buffered, chunk, expected):
    assert baseline_boundary(buffered, chunk) == expected


def test_is_command_ignores_findings_that_mention_words():
    assert is_command("new line") and not is_command("new lesion in the liver")


def test_coverage_forms_bare_mentions_and_no_collectives():
    sections = ["LIVER", "KIDNEYS", "SPLEEN", "PANCREAS"]
    pad = "Hepatic steatosis.\nRenal cyst on the left.\n- Spleen\nThe solid organs are otherwise normal."
    assert baseline_coverage(pad, sections) == {"LIVER": 1.0, "KIDNEYS": 1.0, "SPLEEN": 0.0, "PANCREAS": 0.0}
    assert baseline_coverage("", ["LIVER"]) == {"LIVER": 0.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_bakeoff_baselines.py`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
"""Plain-code baselines for the three dictation bake-offs. No model, no network.

Every bake-off reports one of these next to the model (rev 2 §5). They were drafted
after the fixtures existed, so their scores are an optimistic ceiling for a lexicon
approach. Lexicon entries are generic dictation cues only, never fixture phrases;
do not tune them to a bake-off result.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+")

DELETE_PATTERNS = (
    r"\b(scratch|scrap|strike|delete|remove|ignore) (that|the last (line|one|sentence))\b",
    r"\bundo that\b",
)
FORMAT_PATTERNS = (
    r"^(new|next) (line|paragraph)( please)?$",
    r"^paragraph$",
    r"^(full stop|comma|period)$",
    r"^new heading\b",
)
APP_COMMAND_PATTERNS = (r"^generate (the )?report$", r"^switch to \w+ mode$")
CORRECTION_PATTERNS = (
    r"^actually\b", r"\bmake that\b", r"^sorry\b", r"\bi mean\b", r"^correction\b",
    r"^change .+ to\b", r"\bits not .+ its\b", r"^\w+ not \w+$",
)
FILLERS = frozenset(
    "um umm er erm uh ah hmm so well okay ok right yeah yes let me see just hang on a second wait "
    "testing".split()
)
# A statement that stops on one of these is waiting for more words.
TRAILING_OPEN = frozenset(
    "the a an of in on at to from with without and or but which that is are was were there "
    "measuring actually make".split()
)
STOP = frozenset("the a an of in on at to with and or is are was there it this that no so as i said".split())

# Adjectival and abbreviated forms a checklist section is commonly written in.
SECTION_FORMS: dict[str, tuple[str, ...]] = {
    "LIVER": ("liver", "hepatic"),
    "KIDNEYS": ("kidney", "kidneys", "renal"),
    "LUNGS": ("lung", "lungs", "lobe", "pulmonary"),
    "PLEURA": ("pleura", "pleural"),
    "MEDIASTINUM": ("mediastinum", "mediastinal"),
    "HEART": ("heart", "cardiac"),
    "COMMON BILE DUCT": ("common bile duct", "cbd"),
    "INTERVERTEBRAL DISCS": ("disc", "discs"),
    "SPINAL CANAL": ("canal",),
}


def _norm(text: str) -> str:
    return " ".join(_WORD.findall((text or "").lower().replace("'", "")))


def _any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def _content(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in STOP}


def is_command(text: str) -> bool:
    t = _norm(text)
    return _any(DELETE_PATTERNS, t) or _any(FORMAT_PATTERNS, t) or _any(APP_COMMAND_PATTERNS, t)


def baseline_triage(committed: str, active: str, utterance: str) -> str:
    t = _norm(utterance)
    if _any(DELETE_PATTERNS, t):
        return "delete_previous_utterance"
    if _any(FORMAT_PATTERNS, t):
        return "formatting_command"
    if _any(CORRECTION_PATTERNS, t):
        return "correct_previous_finding"
    if not any(ch.isdigit() for ch in t) and all(w in FILLERS for w in t.split()):
        return "ignore_noise"
    content = _content(utterance)
    seen = _content(committed) | _content(active)
    if content and len(content & seen) / len(content) >= 0.6:
        return "restate_existing_finding"
    return "append_new_finding"


def baseline_boundary(buffered: str, chunk: str) -> str:
    if is_command(chunk):
        return "command"
    words = _norm(f"{buffered} {chunk}").split()
    if len(words) < 3 or words[-1] in TRAILING_OPEN:
        return "continues"
    return "complete"


def baseline_coverage(scratchpad: str, sections: list[str]) -> dict[str, float]:
    """1.0 when a section's name or a listed form appears in a line that asserts more
    than the bare name; 0.0 otherwise. No collectives: that is what the model adds."""
    lines = [_norm(l.lstrip("-* ")) for l in (scratchpad or "").splitlines() if l.strip()]
    out: dict[str, float] = {}
    for s in sections:
        forms = SECTION_FORMS.get(s.upper(), (s.lower(),))
        hit = any(re.search(rf"\b{re.escape(f)}\b", line) and line != f for line in lines for f in forms)
        out[s] = 1.0 if hit else 0.0
    return out
```

Note: `_norm` strips apostrophes, so `it's not … it's` becomes `its not … its`. The correction pattern is written in that normalised form.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_bakeoff_baselines.py`
Expected: all pass (26 parametrised + 3).

- [ ] **Step 5: Check the fixture scores match the prototype**

Run:
```bash
PYTHONPATH=src $PY - <<'EOF'
import json
from rapid_reports_ai.scripts.bakeoff_baselines import *
L = lambda n: [json.loads(l) for l in open(f"tests/fixtures/{n}.jsonl") if l.strip()]
t = L("triage_utterances"); b = L("boundary_cases"); c = L("coverage_cases")
print("triage", sum(baseline_triage(x["committed"], x["active"], x["utterance"]) == x["expected_action"] for x in t), len(t))
print("boundary", sum(baseline_boundary(x["buffered"], x["chunk"]) == x["expected_boundary"] for x in b), len(b))
print("coverage exact", sum({k for k, v in baseline_coverage(x["scratchpad"], x["checklist"]).items() if v} == set(x["expected_covered"]) for x in c), len(c))
EOF
```
Expected: `triage 45 49`, `boundary 35 39`, `coverage exact 14 26`. If these differ, the code was mistyped. Fix the code; do not edit the lexicon to chase a number.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/bakeoff_baselines.py backend/tests/test_bakeoff_baselines.py
git commit -m "feat(bakeoff): plain-code lexicon baselines for triage, boundary and coverage"
```

---

### Task 3: Triage bake-off — `code` column and intervals

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/triage_summary.py`
- Modify: `backend/src/rapid_reports_ai/scripts/triage_bakeoff.py`
- Test: `backend/tests/test_triage_summary.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_triage_summary.py`)

```python
def test_summary_carries_intervals():
    records = [
        _rec("jev", "ignore_noise", "ignore_noise", 0.99, 200),
        _rec("jev", "ignore_noise", "append_new_finding", 0.6, 300),
        _rec("jev", "append_new_finding", "append_new_finding", 0.97, 250, hard=True),
    ]
    jev = summarise(records)["jev"]
    r = jev["accuracy_rate"]
    assert (r["k"], r["n"]) == (2, 3) and r["ci95"][0] < 2 / 3 < r["ci95"][1]
    assert (jev["hard"]["rate"]["k"], jev["hard"]["rate"]["n"]) == (1, 1)
    lo, hi = jev["latency_p95_ci_ms"]
    assert 200 <= lo <= hi <= 300


def test_format_summary_prints_interval():
    from rapid_reports_ai.scripts.triage_summary import format_summary
    out = format_summary(summarise([_rec("code", "ignore_noise", "ignore_noise", None, 0)]))
    assert "accuracy=1.000 [0.21, 1.00] (1/1)" in out


def test_code_record_uses_the_baseline():
    from rapid_reports_ai.scripts.triage_bakeoff import code_record
    case = {"id": "x", "committed": "", "active": "- liver normal", "utterance": "scratch that",
            "scan_type": "CT", "expected_action": "delete_previous_utterance", "expected_is_correction": False,
            "expected_needs_committed_edit": False, "hard": False}
    r = code_record(case)
    assert r.candidate == "code" and r.action == "delete_previous_utterance" and r.error is None
    assert r.confidence is None and r.is_correction == 0.0 and r.needs_committed_edit is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_triage_summary.py`
Expected: the 3 new tests FAIL (`KeyError: 'accuracy_rate'`, `ImportError: cannot import name 'code_record'`). The existing tests still pass.

- [ ] **Step 3: Implement in `triage_summary.py`**

Add the import under the existing imports:

```python
from rapid_reports_ai.scripts.bakeoff_stats import bootstrap_quantile_ci, fmt_rate, rate
```

In `_candidate_summary`, replace the `out: dict[str, Any] = {...}` block with:

```python
    correct = sum(r.action == r.expected_action for r in ok)
    out: dict[str, Any] = {
        "n": len(records),
        "errors": len(records) - len(ok),
        "accuracy": _acc(ok),
        "accuracy_rate": rate(correct, len(ok)),
        "per_action": per_action,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "latency_p50_ms": int(median(lat)) if lat else 0,
        "latency_p95_ms": _p(lat, 0.95),
        "latency_p95_ci_ms": list(bootstrap_quantile_ci(lat, 0.95)),
        "cost_usd": round(sum(r.cost_usd or 0.0 for r in records), 8),
        "hard": {
            "n": len(hard),
            "accuracy": _acc(hard),
            "rate": rate(sum(r.action == r.expected_action for r in hard), len(hard)),
        },
        "is_correction_accuracy": _aux(ok, "is_correction", "expected_is_correction"),
        "needs_committed_edit_accuracy": _aux(ok, "needs_committed_edit", "expected_needs_committed_edit"),
    }
```

In `format_summary`, replace the first two `lines.append(...)` calls with:

```python
        lines.append(
            f"== {cand}: n={s['n']} errors={s['errors']} accuracy={fmt_rate(s['accuracy_rate'])} "
            f"p50={s['latency_p50_ms']}ms p95={s['latency_p95_ms']}ms {s['latency_p95_ci_ms']} "
            f"cost=${s['cost_usd']:.5f}"
        )
        lines.append(
            f"   hard: accuracy={fmt_rate(s['hard']['rate'])}   "
            f"is_correction@0.5={s['is_correction_accuracy']}  "
            f"needs_committed_edit@0.5={s['needs_committed_edit_accuracy']}"
        )
```

- [ ] **Step 4: Implement in `triage_bakeoff.py`**

Add imports:

```python
import time

from rapid_reports_ai.scripts.bakeoff_baselines import baseline_triage
```

Add above `run_case`:

```python
def code_record(case: dict) -> Record:
    """The plain-code baseline as a candidate row. No confidence (a lexicon has none)."""
    t0 = time.perf_counter()
    action = baseline_triage(case["committed"], case["active"], case["utterance"])
    return Record(
        id=case["id"], candidate="code", expected_action=case["expected_action"], action=action,
        confidence=None, latency_ms=int((time.perf_counter() - t0) * 1000), cost_usd=None, hard=case["hard"],
        error=None, is_correction=1.0 if action == "correct_previous_finding" else 0.0,
        expected_is_correction=case["expected_is_correction"], needs_committed_edit=None,
        expected_needs_committed_edit=case["expected_needs_committed_edit"],
    )
```

At the top of the `for cand in candidates:` loop in `run_case`, add:

```python
            if cand == "code":
                out.append(code_record(case))
                continue
```

In `main`, change the argument and candidate lines, and check keys only for model candidates:

```python
    ap.add_argument("--only", choices=["code", "jev", "qwen"])
```
```python
    candidates = [args.only] if args.only else ["code", "jev", "qwen"]
    needed = {"jev": "OPENROUTER_API_KEY", "qwen": "CEREBRAS_API_KEY"}
    missing = [needed[c] for c in candidates if c in needed and not os.environ.get(needed[c])]
    if missing:
        print(f"missing env: {', '.join(missing)}", file=sys.stderr)
        return 2
```
(Delete the old `missing = [...]` block that preceded `candidates = ...`.)

Also update the module docstring's usage line to `[--only code|jev|qwen]`.

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_triage_summary.py tests/test_triage_fixtures.py`
Expected: all pass.

- [ ] **Step 6: Offline smoke of the code candidate**

Run: `PYTHONPATH=src $PY -m rapid_reports_ai.scripts.triage_bakeoff --only code | head -3`
Expected: first line starts `== code: n=49 errors=0 accuracy=0.918 [0.81, 0.97] (45/49)`. This writes `docs/model-migration/triage-bakeoff-<today>.json` with code rows only. **Undo that before committing:** `git checkout -- ../docs/model-migration/` if the file was tracked, or delete it if it is new (`git status --short ../docs/model-migration/` shows which). The full live run happens in Task 6.

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/triage_summary.py backend/src/rapid_reports_ai/scripts/triage_bakeoff.py backend/tests/test_triage_summary.py
git commit -m "feat(triage-bakeoff): plain-code candidate and 95% intervals"
```

---

### Task 4: Coverage bake-off — `code` column and intervals

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/coverage_bakeoff.py`
- Test: `backend/tests/test_coverage_bakeoff.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_coverage_bakeoff.py`)

```python
def test_score_carries_rates():
    rows = [
        Row("a", "jev", ["L", "P", "M"], ["L", "P"], {"L": 0.9, "P": 0.8, "M": 0.1}, 300, None, False, "direct-subject", None),
        Row("b", "jev", ["L", "P", "M"], ["L"], {"L": 0.3, "P": 0.9, "M": 0.1}, 400, None, True, "bare-mention", None),
    ]
    s = score(rows)["jev"]
    assert (s["precision_rate"]["k"], s["precision_rate"]["n"]) == (2, 3)
    assert (s["recall_rate"]["k"], s["recall_rate"]["n"]) == (2, 3)
    assert (s["exact_rate"]["k"], s["exact_rate"]["n"]) == (1, 2)
    assert len(s["latency_p95_ci_ms"]) == 2


def test_code_row_is_the_baseline():
    from rapid_reports_ai.scripts.coverage_bakeoff import code_row
    case = {"id": "x", "scan_type": "CT", "checklist": ["LIVER", "SPLEEN"], "scratchpad": "Hepatic cyst.",
            "expected_covered": ["LIVER"], "rule": "direct-modifier", "hard": False}
    r = code_row(case)
    assert r.candidate == "code" and r.scores == {"LIVER": 1.0, "SPLEEN": 0.0} and r.error is None
    assert score([r])["code"]["exact_set_accuracy"] == 1.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_coverage_bakeoff.py`
Expected: 2 new FAIL (`KeyError: 'precision_rate'`, `ImportError: code_row`).

- [ ] **Step 3: Implement**

Add imports:

```python
from rapid_reports_ai.scripts.bakeoff_baselines import baseline_coverage
from rapid_reports_ai.scripts.bakeoff_stats import bootstrap_quantile_ci, fmt_rate, rate
```

Add after `_exact`:

```python
def code_row(case: dict) -> Row:
    return Row(case["id"], "code", case["checklist"], case["expected_covered"],
               baseline_coverage(case["scratchpad"], case["checklist"]), 0, None, case["hard"], case["rule"], None)
```

In `score`, before `out[cand] = {`, add `exact_k = sum(_exact(r, threshold) for r in ok)`, and add these keys to the `out[cand]` dict (keep the existing ones):

```python
            "precision_rate": rate(tp, tp + fp),
            "recall_rate": rate(tp, tp + fn),
            "exact_rate": rate(exact_k, len(ok)),
            "latency_p95_ci_ms": list(bootstrap_quantile_ci(lat, 0.95)),
```

Replace the first `lines.append(...)` in `fmt` with:

```python
        lines.append(
            f"== {cand}: n={m['n']} errors={m['errors']} p50={m['latency_p50_ms']}ms "
            f"p95={m['latency_p95_ms']}ms {m['latency_p95_ci_ms']} cost=${m['cost_usd']:.5f}"
        )
        lines.append(f"   P={fmt_rate(m['precision_rate'])}  R={fmt_rate(m['recall_rate'])}")
        lines.append(f"   exact={fmt_rate(m['exact_rate'])}")
```

In `main`'s `run`, add the code row before the model loop: inside `async with sem:` put `rows.append(code_row(case))` as the first line.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_coverage_bakeoff.py tests/test_coverage_fixtures.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/coverage_bakeoff.py backend/tests/test_coverage_bakeoff.py
git commit -m "feat(coverage-bakeoff): plain-code candidate and 95% intervals"
```

---

### Task 5: Boundary bake-off — pure scorer, `code` column, standalone, intervals

`standalone` has no fixture label of its own. The derived label: `complete` → True, `continues` → False, `command` → not scored (a command is not a statement). This scores the separate call's `standalone`, which is the reference for Task 8.

**Files:**
- Rewrite: `backend/src/rapid_reports_ai/scripts/boundary_bakeoff.py`
- Test: `backend/tests/test_boundary_bakeoff.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from rapid_reports_ai.scripts.boundary_bakeoff import expected_standalone, score_boundary


def _row(i, expected, raw, code, standalone, lat=300, err=None):
    return {"id": f"r{i}", "expected_boundary": expected, "raw": raw, "resolved": raw, "code": code,
            "standalone": standalone, "confidence": 0.9, "latency_ms": lat, "cost_usd": 1e-5, "error": err,
            "hard": False}


def test_expected_standalone():
    assert expected_standalone({"expected_boundary": "complete"}) is True
    assert expected_standalone({"expected_boundary": "continues"}) is False
    assert expected_standalone({"expected_boundary": "command"}) is None


def test_score_boundary():
    rows = [
        _row(1, "complete", "complete", "complete", 0.8),
        _row(2, "continues", "complete", "continues", 0.7),   # jev wrong, code right, standalone wrong
        _row(3, "command", "command", "command", 0.1),        # standalone not scored
        _row(4, "complete", None, "continues", None, lat=0, err="TriageError"),
    ]
    s = score_boundary(rows)
    assert s["n"] == 4 and s["errors"] == 1
    assert (s["jev_raw"]["k"], s["jev_raw"]["n"]) == (2, 3)
    assert (s["code"]["k"], s["code"]["n"]) == (3, 4)          # code has no error rows
    assert (s["standalone_jev"]["k"], s["standalone_jev"]["n"]) == (1, 2)
    assert (s["standalone_code"]["k"], s["standalone_code"]["n"]) == (2, 3)
    assert (s["by_class"]["continues"]["code"]["k"], s["by_class"]["continues"]["jev_raw"]["k"]) == (1, 0)
    assert s["latency_p95_ms"] == 300
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_boundary_bakeoff.py`
Expected: FAIL, `ImportError: cannot import name 'expected_standalone'`

- [ ] **Step 3: Rewrite `boundary_bakeoff.py`**

```python
"""Score Jev's boundary + ASR-risk decisions on tests/fixtures/boundary_cases.jsonl,
next to the plain-code baseline (scripts/bakeoff_baselines.py), with 95 % intervals.

Usage (from backend/):
    PYTHONPATH=src python -c "from dotenv import load_dotenv; load_dotenv('.env'); import runpy; runpy.run_module('rapid_reports_ai.scripts.boundary_bakeoff', run_name='__main__')"
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any, Callable, Optional

from rapid_reports_ai.scripts.bakeoff_baselines import baseline_boundary
from rapid_reports_ai.scripts.bakeoff_stats import bootstrap_quantile_ci, fmt_rate, rate
from rapid_reports_ai.scripts.triage_summary import BUCKETS, _p
from rapid_reports_ai.utterance_boundary import get_jev_boundary, resolve, resolve_placement

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "boundary_cases.jsonl"
OUT_DIR = Path(__file__).resolve().parents[4] / "docs" / "model-migration"
CLASSES = ("complete", "continues", "command")


def expected_standalone(row: dict) -> Optional[bool]:
    """Standalone has no label of its own: a finished statement should read as one, an
    unfinished one should not. Commands are not statements and are not scored."""
    return {"complete": True, "continues": False}.get(row["expected_boundary"])


def _hits(rows: list[dict], pred: Callable[[dict], bool]) -> dict[str, Any]:
    return rate(sum(1 for r in rows if pred(r)), len(rows))


def score_boundary(rows: list[dict]) -> dict[str, Any]:
    ok = [r for r in rows if r["error"] is None]
    lat = [r["latency_ms"] for r in ok]
    st_ok = [r for r in ok if expected_standalone(r) is not None]
    st_all = [r for r in rows if expected_standalone(r) is not None]
    return {
        "n": len(rows),
        "errors": len(rows) - len(ok),
        "jev_raw": _hits(ok, lambda r: r["raw"] == r["expected_boundary"]),
        "jev_resolved": _hits(ok, lambda r: r["resolved"] == r["expected_boundary"]),
        "code": _hits(rows, lambda r: r["code"] == r["expected_boundary"]),
        "by_class": {
            k: {
                "jev_raw": _hits([r for r in ok if r["expected_boundary"] == k], lambda r: r["raw"] == k),
                "code": _hits([r for r in rows if r["expected_boundary"] == k], lambda r: r["code"] == k),
            }
            for k in CLASSES
        },
        "standalone_jev": _hits(st_ok, lambda r: (r["standalone"] >= 0.5) == expected_standalone(r)),
        "standalone_code": _hits(st_all, lambda r: (r["code"] == "complete") == expected_standalone(r)),
        "latency_p50_ms": int(median(lat)) if lat else 0,
        "latency_p95_ms": _p(lat, 0.95),
        "latency_p95_ci_ms": list(bootstrap_quantile_ci(lat, 0.95)),
        "cost_usd": round(sum(r["cost_usd"] or 0 for r in rows), 8),
    }


async def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("missing OPENROUTER_API_KEY", file=sys.stderr)
        return 2
    cases = [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()]
    sem = asyncio.Semaphore(4)

    async def run(c):
        base = {**c, "code": baseline_boundary(c["buffered"], c["chunk"])}
        async with sem:
            try:
                d = await get_jev_boundary().classify(
                    c["scan_type"], c["buffered"], c["chunk"], c["scratchpad_tail"], c.get("silence_s", 0.0)
                )
                return {**base, "raw": d.boundary, "resolved": resolve(d), "confidence": d.confidence,
                        "asr_risk": d.asr_risk, "standalone": d.standalone, "latency_ms": d.latency_ms,
                        "cost_usd": d.cost_usd, "error": None, "placement_raw": d.placement,
                        "placement": resolve_placement(d), "placement_confidence": d.placement_confidence}
            except Exception as e:
                return {**base, "raw": None, "resolved": "complete", "confidence": None, "asr_risk": None,
                        "standalone": None, "latency_ms": 0, "cost_usd": None, "error": type(e).__name__}

    rows = await asyncio.gather(*(run(c) for c in cases))
    ok = [r for r in rows if r["error"] is None]
    s = score_boundary(rows)
    print(f"== boundary: n={s['n']} errors={s['errors']} p50={s['latency_p50_ms']}ms "
          f"p95={s['latency_p95_ms']}ms {s['latency_p95_ci_ms']} cost=${s['cost_usd']:.5f}")
    print(f"   jev raw        {fmt_rate(s['jev_raw'])}")
    print(f"   jev resolved   {fmt_rate(s['jev_resolved'])}")
    print(f"   code           {fmt_rate(s['code'])}")
    for k, v in s["by_class"].items():
        print(f"   {k:<10} jev_raw={fmt_rate(v['jev_raw'])}  code={fmt_rate(v['code'])}")
    print(f"   standalone@0.5 jev={fmt_rate(s['standalone_jev'])}  code={fmt_rate(s['standalone_code'])}")
    hard = [r for r in ok if r["hard"]]
    print(f"   hard       n={len(hard):<3} resolved_acc="
          f"{sum(r['resolved'] == r['expected_boundary'] for r in hard) / max(1, len(hard)):.2f}")
    asr = [r for r in ok if r["asr_risk"] is not None]
    print(f"   asr_risk@0.5 acc={sum((r['asr_risk'] >= 0.5) == r['expected_asr_risk'] for r in asr) / max(1, len(asr)):.3f}")
    for name, lo, hi in BUCKETS:
        rs = [r for r in ok if lo <= r["confidence"] < hi]
        if rs:
            print(f"   conf {name:<8} n={len(rs):<3} raw_acc={sum(r['raw'] == r['expected_boundary'] for r in rs) / len(rs):.3f}")
    print("\n-- jev misses --")
    for r in ok:
        if r["resolved"] != r["expected_boundary"]:
            print(f"   {r['id']:<7} expected={r['expected_boundary']:<9} raw={r['raw']:<9} "
                  f"conf={r['confidence']:.2f} resolved={r['resolved']:<9} '{r['buffered']} | {r['chunk']}'")
    print("\n-- code misses --")
    for r in rows:
        if r["code"] != r["expected_boundary"]:
            print(f"   {r['id']:<7} expected={r['expected_boundary']:<9} code={r['code']:<9} '{r['buffered']} | {r['chunk']}'")
    pl = [r for r in ok if r.get("expected_placement")]
    if pl:
        print(f"\n-- placement (n={len(pl)}) resolved_acc="
              f"{sum(r['placement'] == r['expected_placement'] for r in pl) / len(pl):.3f} raw_acc="
              f"{sum(r['placement_raw'] == r['expected_placement'] for r in pl) / len(pl):.3f}")
    print("\n-- asr risk --")
    for r in asr:
        if (r["asr_risk"] >= 0.5) != r["expected_asr_risk"] or r["expected_asr_risk"]:
            print(f"   {r['id']:<7} expected={r['expected_asr_risk']!s:<5} asr={r['asr_risk']:.2f} '{r['buffered']} | {r['chunk']}'")
    print(f"\nasr cases: {dict(Counter(r['expected_asr_risk'] for r in asr))}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"boundary-bakeoff-{date.today().isoformat()}.json"
    out.write_text(json.dumps({"summary": s, "rows": rows}, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

Changes from the current file: the JSON output is now `{"summary", "rows"}` rather than a bare list; placement mismatches are no longer printed row by row, because placement is retired (rev 2 §8) and its accuracy line is kept. Placement fields stay in the rows.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_boundary_bakeoff.py tests/test_boundary_fixtures.py tests/test_utterance_boundary.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/boundary_bakeoff.py backend/tests/test_boundary_bakeoff.py
git commit -m "feat(boundary-bakeoff): plain-code column, standalone scoring and 95% intervals"
```

---

### Task 6: Live re-run of the three bake-offs; record the baseline table

**Files:**
- Regenerate: `docs/model-migration/{triage,coverage,boundary}-bakeoff-<today>.json`
- Modify: `docs/superpowers/handover/2026-09-24-jev-dictation-lab-handover.md` §3

- [ ] **Step 1: Run all three** (from `backend/`, sequentially, capturing output)

```bash
LOAD="from dotenv import load_dotenv; load_dotenv('.env'); import runpy, sys"
for m in triage_bakeoff coverage_bakeoff boundary_bakeoff; do
  PYTHONPATH=src $PY -c "$LOAD; runpy.run_module('rapid_reports_ai.scripts.$m', run_name='__main__')" \
    > "$TMPDIR/$m.txt"; echo "$m exit=$?"; cat "$TMPDIR/$m.txt"
done
```
Expected: each prints a `code` line whose numbers match the Task 2 prototype table (triage 45/49, coverage exact 14/26, boundary 35/39, standalone code 25/29), plus Jev and Qwen lines with intervals. Errors = 0 for Jev. If Jev returns an HTTP error, rerun once; if it persists, stop and report.

- [ ] **Step 2: Add a baseline table to handover §3**

Under the existing bullets in §3 "Results that matter", insert a sub-heading `**Baselines + 95 % intervals (rerun <today>):**` followed by a table built from the run's output lines:

```markdown
| Set | Plain code | Jev | Qwen-off |
|---|---|---|---|
| Triage action (n=49) | <code accuracy fmt_rate> | <jev> | <qwen> |
| Coverage exact set (n=26) | <code exact> | <jev> | <qwen> |
| Coverage recall (sections) | <code R> | <jev R> | <qwen R> |
| Boundary 3-way (n=39) | <code> | <jev raw> | — |
| Standalone@0.5 (n=29) | <code> | <jev> | — |
```
Fill every cell with the printed `fmt_rate` string (e.g. `0.918 [0.81, 0.97] (45/49)`). Then one sentence saying where Jev's interval clears the baseline's and where it does not. Nothing more.

- [ ] **Step 3: Run the full backend suite**

Run: `PYTHONPATH=src $PY -m pytest -q`
Expected: previous total (344) + the new tests, 0 failures.

- [ ] **Step 4: Commit**

```bash
git add ../docs/model-migration/triage-bakeoff-*.json ../docs/model-migration/coverage-bakeoff-*.json ../docs/model-migration/boundary-bakeoff-*.json ../docs/superpowers/handover/2026-09-24-jev-dictation-lab-handover.md
git commit -m "docs(bakeoff): rerun with plain-code baselines and 95% intervals"
```

---

### Task 7: The per-utterance bundle

One System One request carries: `action`, `is_correction`, `needs_committed_edit` (from `TRIAGE_QUESTIONS`, unchanged), `standalone` (from `BOUNDARY_QUESTIONS`, rewording its subject only), and one noul per checklist section (from `coverage_questions`, rewording its subject only). Section question ids are `section_<i>` so that no checklist string has to be a valid id. The parser maps them back to section names.

**Files:**
- Create: `backend/src/rapid_reports_ai/utterance_bundle.py`
- Test: `backend/tests/test_utterance_bundle.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import json

import httpx
import pytest

from rapid_reports_ai.dictation_triage import JEV_MODEL, TRIAGE_QUESTIONS, TriageError
from rapid_reports_ai.section_coverage import coverage_questions
from rapid_reports_ai.utterance_boundary import BOUNDARY_QUESTIONS
from rapid_reports_ai.utterance_bundle import BundleState, JevBundle, bundle_questions

STATE = BundleState(scan_type="CT chest", committed="- 6 mm nodule RUL", active="- no effusion",
                    open_line="there is a", latest_utterance="small pneumothorax",
                    checklist=["LUNGS", "PLEURA"])


def _resp(action="append_new_finding", sections=(0.9, 0.2)):
    probs = {a: 0.0 for a in TRIAGE_QUESTIONS["action"]["criteria"]}
    probs[action] = 1.0
    answers = {
        "action": {"type": "choice", "choice": action, "confidence": 0.97, "probabilities": probs},
        "is_correction": {"type": "noul", "noul": 0.03},
        "needs_committed_edit": {"type": "noul", "noul": 0.02},
        "standalone": {"type": "noul", "noul": 0.81},
    }
    for i, p in enumerate(sections):
        answers[f"section_{i}"] = {"type": "noul", "noul": p}
    return {"answers": answers, "usage": {"input_tokens": 900, "cost": 3.6e-05}}


def test_questions_reuse_component_texts():
    q = bundle_questions(["LUNGS", "PLEURA"])
    assert set(q) == {"action", "is_correction", "needs_committed_edit", "standalone", "section_0", "section_1"}
    for k in ("action", "is_correction", "needs_committed_edit"):
        assert q[k] == TRIAGE_QUESTIONS[k]
    assert "open line plus the latest utterance" in q["standalone"]["instructions"]
    assert q["standalone"]["instructions"].replace(
        "the open line plus the latest utterance", "the buffered words plus the chunk"
    ) == BOUNDARY_QUESTIONS["standalone"]["instructions"]
    ref = coverage_questions(["PLEURA"])["PLEURA"]
    assert q["section_1"]["criteria"] == ref["criteria"]
    assert "COMMITTED plus ACTIVE" in q["section_1"]["instructions"] and "PLEURA" in q["section_1"]["instructions"]


def test_questions_without_checklist():
    assert set(bundle_questions([])) == {"action", "is_correction", "needs_committed_edit", "standalone"}


async def test_request_and_parse():
    captured = {}

    def handler(req):
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json=_resp())

    d = await JevBundle(api_key="k", transport=httpx.MockTransport(handler)).classify(STATE)
    body = captured["body"]
    assert body["model"] == JEV_MODEL
    assert body["state"] == {"scan_type": "CT chest", "committed": "- 6 mm nodule RUL", "active": "- no effusion",
                             "open_line": "there is a", "latest_utterance": "small pneumothorax",
                             "checklist": ["LUNGS", "PLEURA"]}
    assert set(body["questions"]) == set(bundle_questions(["LUNGS", "PLEURA"]))
    assert d.triage.action == "append_new_finding" and d.triage.confidence == 0.97
    assert d.standalone == 0.81
    assert d.coverage == {"LUNGS": 0.9, "PLEURA": 0.2}
    assert d.n_questions == 6 and d.cost_usd == 3.6e-05 and d.latency_ms >= 0


async def test_missing_section_answer_raises():
    data = _resp()
    del data["answers"]["section_1"]
    t = httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    with pytest.raises(TriageError, match="section_1"):
        await JevBundle(api_key="k", transport=t).classify(STATE)


async def test_http_error_raises():
    t = httpx.MockTransport(lambda req: httpx.Response(502, text="bad gateway"))
    with pytest.raises(TriageError, match="502"):
        await JevBundle(api_key="k", transport=t).classify(STATE)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(TriageError):
        JevBundle()
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_utterance_bundle.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'rapid_reports_ai.utterance_bundle'`

- [ ] **Step 3: Write the implementation**

```python
"""One Jev call per utterance: triage + standalone + section coverage.

Rev 2 component 1. The question texts are the separate components' own, imported
rather than copied, so a bundle-vs-separate difference measures bundling, not
wording. The shared state forces two subject edits: 'standalone' names the open line
plus the latest utterance (was: buffered words plus the chunk), and coverage names
COMMITTED plus ACTIVE (was: the scratchpad). Coverage is of the scratchpad before
this utterance, as /review asks it today; per-utterance section nouls are component 3.

Spec: docs/superpowers/specs/2026-09-24-decision-first-dictation-design.md §4, §7.1
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from .dictation_triage import (
    JEV_MODEL,
    JEV_TIMEOUT_S,
    JEV_URL,
    TRIAGE_QUESTIONS,
    JevTriager,
    TriageDecision,
    TriageError,
    _check_unit,
)
from .section_coverage import coverage_questions
from .utterance_boundary import BOUNDARY_QUESTIONS

STANDALONE_QUESTION: dict[str, Any] = {
    **BOUNDARY_QUESTIONS["standalone"],
    "instructions": BOUNDARY_QUESTIONS["standalone"]["instructions"].replace(
        "the buffered words plus the chunk", "the open line plus the latest utterance"
    ),
}


def section_key(i: int) -> str:
    return f"section_{i}"


def bundle_questions(checklist: list[str]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {**TRIAGE_QUESTIONS, "standalone": STANDALONE_QUESTION}
    for i, (_, q) in enumerate(coverage_questions(checklist).items()):
        questions[section_key(i)] = {
            **q,
            "instructions": q["instructions"].replace("The scratchpad", "The scratchpad (COMMITTED plus ACTIVE)", 1),
        }
    return questions


@dataclass(frozen=True)
class BundleState:
    scan_type: str
    committed: str
    active: str
    open_line: str
    latest_utterance: str
    checklist: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "scan_type": self.scan_type or "",
            "committed": self.committed or "",
            "active": self.active or "",
            "open_line": self.open_line or "",
            "latest_utterance": self.latest_utterance or "",
            "checklist": list(self.checklist),
        }


@dataclass(frozen=True)
class BundleDecision:
    triage: TriageDecision
    standalone: float
    coverage: dict[str, float]
    latency_ms: int
    n_questions: int
    input_tokens: Optional[int]
    cost_usd: Optional[float]


class JevBundle:
    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = JEV_TIMEOUT_S,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or ""
        if not self._api_key:
            raise TriageError("OPENROUTER_API_KEY is not set")
        self._transport = transport
        self._timeout_s = timeout_s

    async def classify(self, state: BundleState) -> BundleDecision:
        questions = bundle_questions(state.checklist)
        body = {"model": JEV_MODEL, "state": state.as_payload(), "questions": questions}
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout_s) as client:
                resp = await client.post(JEV_URL, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise TriageError(f"jev bundle transport failure: {type(e).__name__}") from e
        latency_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            raise TriageError(f"jev bundle http {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise TriageError("jev bundle returned non-JSON") from e
        triage = JevTriager.parse(data, latency_ms)  # validates the three triage answers
        answers = data.get("answers") or {}
        if "standalone" not in answers:
            raise TriageError("jev bundle answer missing: standalone")
        coverage: dict[str, float] = {}
        for i, s in enumerate(state.checklist):
            key = section_key(i)
            if key not in answers:
                raise TriageError(f"jev bundle answer missing: {key}")
            coverage[s] = _check_unit(answers[key].get("noul"), f"coverage[{s}]")
        usage = data.get("usage") or {}
        return BundleDecision(
            triage=triage,
            standalone=_check_unit(answers["standalone"].get("noul"), "standalone"),
            coverage=coverage,
            latency_ms=latency_ms,
            n_questions=len(questions),
            input_tokens=usage.get("input_tokens"),
            cost_usd=usage.get("cost"),
        )


_JEV: JevBundle | None = None


def get_jev_bundle() -> JevBundle:
    global _JEV
    if _JEV is None:
        _JEV = JevBundle()
    return _JEV
```

Note: `coverage_questions` keys by section string, so a checklist with a duplicate section yields fewer questions than `len(checklist)`, and the parser then raises "answer missing". Checklists do not repeat sections; if one ever does, the error is loud rather than a silent misalignment.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_utterance_bundle.py tests/test_dictation_triage.py tests/test_section_coverage.py tests/test_utterance_boundary.py`
Expected: all pass.

- [ ] **Step 5: One live call to check the wire contract**

```bash
PYTHONPATH=src $PY -c "
from dotenv import load_dotenv; load_dotenv('.env')
import asyncio
from rapid_reports_ai.utterance_bundle import BundleState, get_jev_bundle
s = BundleState('CT chest', '', '- 6 mm nodule right upper lobe', '', 'no pleural effusion', ['LUNGS','PLEURA','MEDIASTINUM'])
d = asyncio.run(get_jev_bundle().classify(s))
print(d.triage.action, round(d.triage.confidence,2), round(d.standalone,2), {k: round(v,2) for k,v in d.coverage.items()}, d.latency_ms, 'ms')
"
```
Expected: one line such as `append_new_finding 0.9x 0.8x {'LUNGS': 0.xx, 'PLEURA': 0.9x, 'MEDIASTINUM': 0.0x} ~300 ms`. A `TriageError` naming an answer id means System One rejected or renamed a question id. Check `resp.text` and stop before Task 8.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/utterance_bundle.py backend/tests/test_utterance_bundle.py
git commit -m "feat(bundle): one Jev call per utterance — triage, standalone and section coverage"
```

---

### Task 8: Parity scorer (pure)

**Parity definition.** A *unit* is one scored answer: a triage fixture for `action` / `is_correction` / `needs_committed_edit`, a complete-or-continues boundary fixture for `standalone`, and a (coverage fixture, section) pair for `coverage`. Each unit is answered by the separate call twice (`ref`, `ref2`) and by the bundle once. The call order is ref → bundle → ref2, so drift over time cannot favour one side. For each question:

- `bundle_only_wrong` = units where ref is right and the bundle is wrong; `ref_only_wrong` = the reverse.
- `noise` = units where ref and ref2 disagree on correctness: what the separate call does to itself.
- `allowed` = max(1, noise, ⌈2 % of n⌉).
- **PASS** when `bundle_only_wrong − ref_only_wrong ≤ allowed` **and** no bundle-only wrong answer has confidence ≥ 0.95 (for a noul, confidence = 0.5 + |p − 0.5|). A confident new error would land in the act band (rev 2 §3.2), so one is enough to fail.

The latency gate passes when bundle p95 < 500 ms over every bundle call (all fixtures × repeats) and there are zero bundle errors. The bootstrap interval is reported but does not gate.

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/bundle_parity.py` (pure part only in this task)
- Test: `backend/tests/test_bundle_parity.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import json
from pathlib import Path

from rapid_reports_ai.dictation_triage import TriageDecision
from rapid_reports_ai.scripts.bundle_parity import (
    PARITY_CHECKLISTS,
    Unit,
    boundary_state,
    coverage_state,
    coverage_units,
    latency_gate,
    standalone_units,
    triage_state,
    triage_units,
    verdict,
)
from rapid_reports_ai.section_coverage import CoverageDecision
from rapid_reports_ai.utterance_boundary import BoundaryDecision
from rapid_reports_ai.utterance_bundle import BundleDecision

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return [json.loads(l) for l in (FIX / name).read_text().splitlines() if l.strip()]


def _td(action="append_new_finding", conf=0.97, ic=0.1, nce=0.1):
    return TriageDecision("jev", action, conf, {}, ic, nce, 300, None, None)


def _bd(action="append_new_finding", conf=0.97, ic=0.1, nce=0.1, standalone=0.8, coverage=None):
    return BundleDecision(_td(action, conf, ic, nce), standalone, coverage or {}, 320, 8, None, None)


def _bnd(standalone):
    return BoundaryDecision("complete", 0.9, {}, 0.1, 300, None, None, standalone=standalone)


def _u(ref, ref2, bun, conf=0.7):
    return Unit("q", "c", ref, ref2, bun, conf)


def test_every_fixture_scan_type_has_a_checklist():
    for name in ("triage_utterances.jsonl", "boundary_cases.jsonl"):
        for c in _load(name):
            assert c["scan_type"] in PARITY_CHECKLISTS, (name, c["id"])


def test_state_mappers():
    t = triage_state({"scan_type": "CT chest", "committed": "C", "active": "A", "utterance": "U"})
    assert (t.committed, t.active, t.open_line, t.latest_utterance) == ("C", "A", "", "U")
    assert t.checklist == PARITY_CHECKLISTS["CT chest"]
    b = boundary_state({"scan_type": "CT chest", "buffered": "B", "chunk": "K", "scratchpad_tail": "T"})
    assert (b.committed, b.active, b.open_line, b.latest_utterance) == ("", "T", "B", "K")
    c = coverage_state({"scan_type": "CT", "scratchpad": "S", "checklist": ["LIVER"]})
    assert (c.active, c.latest_utterance, c.checklist) == ("S", "", ["LIVER"])


def test_triage_units():
    case = {"id": "t1", "expected_action": "correct_previous_finding",
            "expected_is_correction": True, "expected_needs_committed_edit": False}
    us = triage_units(case, _td("correct_previous_finding", ic=0.9), _td("correct_previous_finding", ic=0.9),
                      _bd("append_new_finding", conf=0.96, ic=0.4))
    by_q = {u.question: u for u in us}
    assert set(by_q) == {"action", "is_correction", "needs_committed_edit"}
    assert by_q["action"].ref_ok and not by_q["action"].bundle_ok and by_q["action"].bundle_conf == 0.96
    assert by_q["is_correction"].ref_ok and not by_q["is_correction"].bundle_ok
    assert abs(by_q["is_correction"].bundle_conf - 0.6) < 1e-9
    assert by_q["needs_committed_edit"].bundle_ok


def test_standalone_units_skip_commands():
    assert standalone_units({"id": "c", "expected_boundary": "command"}, _bnd(0.1), _bnd(0.1), _bd()) == []
    [u] = standalone_units({"id": "k", "expected_boundary": "continues"}, _bnd(0.3), _bnd(0.6), _bd(standalone=0.2))
    assert u.question == "standalone" and u.ref_ok and not u.ref2_ok and u.bundle_ok


def test_coverage_units_one_per_section():
    case = {"id": "cv", "checklist": ["LIVER", "SPLEEN"], "expected_covered": ["LIVER"]}
    ref = CoverageDecision("jev", {"LIVER": 0.9, "SPLEEN": 0.1}, ["LIVER"], 300)
    us = coverage_units(case, ref, ref, _bd(coverage={"LIVER": 0.4, "SPLEEN": 0.1}))
    assert [u.case_id for u in us] == ["cv/LIVER", "cv/SPLEEN"]
    assert not us[0].bundle_ok and us[1].bundle_ok


def test_verdict_rules():
    assert verdict([_u(True, True, True)] * 10)["pass"]
    two_new = [_u(True, True, False)] * 2 + [_u(True, True, True)] * 8
    v = verdict(two_new)
    assert v["bundle_only_wrong"] == 2 and v["allowed_net_loss"] == 1 and not v["pass"]
    noisy = two_new + [_u(True, False, True)] * 2
    assert verdict(noisy)["allowed_net_loss"] == 2 and verdict(noisy)["pass"]
    offset = [_u(True, True, False), _u(False, False, True)] + [_u(True, True, True)] * 8
    assert verdict(offset)["pass"]
    confident = [_u(True, True, False, conf=0.97)] + [_u(True, True, True)] * 9
    assert verdict(confident)["confident_new_wrong"] == 1 and not verdict(confident)["pass"]
    assert verdict([_u(True, True, True)] * 200)["allowed_net_loss"] == 4


def test_latency_gate():
    assert latency_gate([300] * 100)["pass"]
    g = latency_gate([300] * 90 + [600] * 10)
    assert g["p95"] == 600 and not g["pass"]
    assert not latency_gate([])["pass"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_bundle_parity.py`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Write the pure part of `scripts/bundle_parity.py`**

```python
"""Bundle parity: does asking every per-utterance question in one Jev call change any
answer, and is the one call fast enough? Rev 2 §4 component 1 exit criterion.

Each fixture (triage, boundary, coverage sets) is run ref -> bundle -> ref again. A
question passes when the bundle's net extra misses fit inside the separate call's own
run-to-run noise (min 1, or 2 % of units) and none of them is confident (>= 0.95).
The one call passes when p95 < 500 ms over all bundle calls with zero errors.

Usage (from backend/, keys in .env):
    PYTHONPATH=src python -c "from dotenv import load_dotenv; load_dotenv('.env'); import runpy; runpy.run_module('rapid_reports_ai.scripts.bundle_parity', run_name='__main__')" [--repeats 2] [--concurrency 1]

Never run by pytest. Writes docs/model-migration/bundle-parity-<date>.json; exits 1 on FAIL.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from statistics import median
from typing import Any

from rapid_reports_ai.dictation_triage import TriageDecision
from rapid_reports_ai.scripts.bakeoff_stats import bootstrap_quantile_ci, quantile, rate
from rapid_reports_ai.section_coverage import CoverageDecision
from rapid_reports_ai.utterance_boundary import BoundaryDecision
from rapid_reports_ai.utterance_bundle import BundleDecision, BundleState

CONFIDENT = 0.95
LATENCY_LIMIT_MS = 500

# Triage and boundary fixtures carry no checklist; the bundle always asks section
# questions, so each scan type gets a realistic one. Coverage fixtures bring their own.
PARITY_CHECKLISTS: dict[str, list[str]] = {
    "CT chest": ["LUNGS", "PLEURA", "MEDIASTINUM", "HEART", "BONES"],
    "CXR": ["LUNGS", "PLEURA", "HEART", "MEDIASTINUM", "BONES"],
    "CT abdomen pelvis": ["LIVER", "GALLBLADDER", "PANCREAS", "SPLEEN", "KIDNEYS", "BOWEL", "LYMPH NODES", "BONES"],
    "US abdomen": ["LIVER", "GALLBLADDER", "BILE DUCTS", "PANCREAS", "SPLEEN", "KIDNEYS"],
    "US renal": ["KIDNEYS", "BLADDER"],
    "CT head": ["BRAIN PARENCHYMA", "VENTRICLES", "EXTRA-AXIAL SPACES", "SKULL"],
    "MRI lumbar spine": ["VERTEBRAL BODIES", "INTERVERTEBRAL DISCS", "SPINAL CANAL", "NERVE ROOTS"],
    "MRCP": ["LIVER", "GALLBLADDER", "BILE DUCTS", "PANCREATIC DUCT"],
}


def triage_state(c: dict) -> BundleState:
    return BundleState(c["scan_type"], c["committed"], c["active"], "", c["utterance"], PARITY_CHECKLISTS[c["scan_type"]])


def boundary_state(c: dict) -> BundleState:
    return BundleState(c["scan_type"], "", c["scratchpad_tail"], c["buffered"], c["chunk"], PARITY_CHECKLISTS[c["scan_type"]])


def coverage_state(c: dict) -> BundleState:
    return BundleState(c["scan_type"], "", c["scratchpad"], "", "", list(c["checklist"]))


@dataclass(frozen=True)
class Unit:
    question: str
    case_id: str
    ref_ok: bool
    ref2_ok: bool
    bundle_ok: bool
    bundle_conf: float


def _noul_ok(p: float, expected: bool) -> bool:
    return (p >= 0.5) == expected


def _noul_conf(p: float) -> float:
    return 0.5 + abs(p - 0.5)


def triage_units(c: dict, ref: TriageDecision, ref2: TriageDecision, b: BundleDecision) -> list[Unit]:
    bt = b.triage
    units = [Unit("action", c["id"], ref.action == c["expected_action"], ref2.action == c["expected_action"],
                  bt.action == c["expected_action"], bt.confidence or 0.0)]
    for q, exp_key in (("is_correction", "expected_is_correction"), ("needs_committed_edit", "expected_needs_committed_edit")):
        exp = c[exp_key]
        p_ref, p_ref2, p_b = getattr(ref, q), getattr(ref2, q), getattr(bt, q)
        units.append(Unit(q, c["id"], _noul_ok(p_ref, exp), _noul_ok(p_ref2, exp), _noul_ok(p_b, exp), _noul_conf(p_b)))
    return units


def standalone_units(c: dict, ref: BoundaryDecision, ref2: BoundaryDecision, b: BundleDecision) -> list[Unit]:
    exp = {"complete": True, "continues": False}.get(c["expected_boundary"])
    if exp is None:
        return []
    return [Unit("standalone", c["id"], _noul_ok(ref.standalone, exp), _noul_ok(ref2.standalone, exp),
                 _noul_ok(b.standalone, exp), _noul_conf(b.standalone))]


def coverage_units(c: dict, ref: CoverageDecision, ref2: CoverageDecision, b: BundleDecision) -> list[Unit]:
    expected = set(c["expected_covered"])
    return [
        Unit("coverage", f"{c['id']}/{s}", _noul_ok(ref.scores[s], s in expected), _noul_ok(ref2.scores[s], s in expected),
             _noul_ok(b.coverage[s], s in expected), _noul_conf(b.coverage[s]))
        for s in c["checklist"]
    ]


def verdict(units: list[Unit]) -> dict[str, Any]:
    n = len(units)
    bundle_only = sum(u.ref_ok and not u.bundle_ok for u in units)
    ref_only = sum(u.bundle_ok and not u.ref_ok for u in units)
    noise = sum(u.ref_ok != u.ref2_ok for u in units)
    allowed = max(1, noise, ceil(0.02 * n))
    confident_new = sum(u.ref_ok and not u.bundle_ok and u.bundle_conf >= CONFIDENT for u in units)
    return {
        "n": n,
        "ref": rate(sum(u.ref_ok for u in units), n),
        "ref2": rate(sum(u.ref2_ok for u in units), n),
        "bundle": rate(sum(u.bundle_ok for u in units), n),
        "bundle_only_wrong": bundle_only,
        "ref_only_wrong": ref_only,
        "noise_discordant": noise,
        "allowed_net_loss": allowed,
        "confident_new_wrong": confident_new,
        "pass": (bundle_only - ref_only) <= allowed and confident_new == 0,
    }


def latency_gate(latencies: list[int], limit_ms: int = LATENCY_LIMIT_MS) -> dict[str, Any]:
    p95 = quantile(latencies, 0.95)
    return {
        "n": len(latencies),
        "p50": int(median(latencies)) if latencies else 0,
        "p95": p95,
        "p95_ci": list(bootstrap_quantile_ci(latencies, 0.95)),
        "limit_ms": limit_ms,
        "pass": bool(latencies) and p95 < limit_ms,
    }
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_bundle_parity.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/bundle_parity.py backend/tests/test_bundle_parity.py
git commit -m "feat(bundle): parity scorer — per-question noise-bounded verdict and p95 gate"
```

---

### Task 9: Parity runner (live)

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/bundle_parity.py` (append the runner)

No unit test: this is the network runner, like the other bake-off `main`s. The pure pieces are covered by Task 8.

- [ ] **Step 1: Append the runner**

Add these imports at the top of the file, merged into the existing import block:

```python
import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

from rapid_reports_ai.dictation_triage import TriageError, TriageState, get_triager
from rapid_reports_ai.section_coverage import get_jev_coverage
from rapid_reports_ai.utterance_boundary import get_jev_boundary
from rapid_reports_ai.utterance_bundle import get_jev_bundle
```

Append:

```python
FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
OUT_DIR = Path(__file__).resolve().parents[4] / "docs" / "model-migration"
COMMAND_ACTIONS = ("delete_previous_utterance", "formatting_command")


async def _ref_triage(c: dict) -> TriageDecision:
    return await get_triager("jev").classify(TriageState(c["committed"], c["active"], c["utterance"], c["scan_type"]))


async def _ref_boundary(c: dict) -> BoundaryDecision:
    return await get_jev_boundary().classify(c["scan_type"], c["buffered"], c["chunk"], c["scratchpad_tail"], 0.0)


async def _ref_coverage(c: dict) -> CoverageDecision:
    return await get_jev_coverage().classify(c["scratchpad"], c["checklist"], c["scan_type"])


KINDS = {
    "triage": ("triage_utterances.jsonl", triage_state, _ref_triage, triage_units),
    "boundary": ("boundary_cases.jsonl", boundary_state, _ref_boundary, standalone_units),
    "coverage": ("coverage_cases.jsonl", coverage_state, _ref_coverage, coverage_units),
}


async def run_case(kind: str, c: dict, sem: asyncio.Semaphore, repeats: int) -> dict[str, Any]:
    _, to_state, ref_fn, to_units = KINDS[kind]
    state = to_state(c)
    rec: dict[str, Any] = {"kind": kind, "id": c["id"], "error": None, "units": [], "bundle_latencies": []}
    async with sem:
        try:
            ref = await ref_fn(c)
            b = await get_jev_bundle().classify(state)
            ref2 = await ref_fn(c)
            extra = [(await get_jev_bundle().classify(state)).latency_ms for _ in range(repeats - 1)]
        except TriageError as e:
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
            return rec
    rec["units"] = [u.__dict__ for u in to_units(c, ref, ref2, b)]
    rec["bundle_latencies"] = [b.latency_ms, *extra]
    rec["ref_latencies"] = [ref.latency_ms, ref2.latency_ms]
    rec["n_questions"] = b.n_questions
    rec["bundle_cost_usd"] = b.cost_usd
    if kind == "boundary" and c["expected_boundary"] == "command":
        rec["command_action"] = b.triage.action  # informational: commands are not a bundle question yet
    return rec


def summarise(recs: list[dict[str, Any]]) -> dict[str, Any]:
    units = [Unit(**u) for r in recs for u in r["units"]]
    questions = sorted({u.question for u in units})
    per_q = {q: verdict([u for u in units if u.question == q]) for q in questions}
    bundle_lat = [l for r in recs for l in r["bundle_latencies"]]
    small = [l for r in recs if r.get("n_questions", 0) <= 8 for l in r["bundle_latencies"]]
    large = [l for r in recs if r.get("n_questions", 0) > 8 for l in r["bundle_latencies"]]
    ref_lat = {k: latency_gate([l for r in recs if r["kind"] == k for l in r.get("ref_latencies", [])])
               for k in KINDS}
    errors = [r for r in recs if r["error"]]
    cmds = [r for r in recs if "command_action" in r]
    gate = latency_gate(bundle_lat)
    return {
        "questions": per_q,
        "latency": gate,
        "latency_by_size": {"<=8 questions": latency_gate(small), ">8 questions": latency_gate(large)},
        "ref_latency": ref_lat,
        "errors": len(errors),
        "commands_caught_by_action": rate(sum(r["command_action"] in COMMAND_ACTIONS for r in cmds), len(cmds)),
        "bundle_cost_usd": round(sum(r.get("bundle_cost_usd") or 0.0 for r in recs), 8),
        "pass": all(v["pass"] for v in per_q.values()) and gate["pass"] and not errors,
    }


def fmt(s: dict[str, Any]) -> str:
    from rapid_reports_ai.scripts.bakeoff_stats import fmt_rate

    lines = [f"== bundle parity: {'PASS' if s['pass'] else 'FAIL'}  errors={s['errors']}  cost=${s['bundle_cost_usd']:.5f}"]
    for q, v in s["questions"].items():
        lines.append(
            f"   {q:<22} {'PASS' if v['pass'] else 'FAIL'}  ref={fmt_rate(v['ref'])}  bundle={fmt_rate(v['bundle'])}  "
            f"bundle-only={v['bundle_only_wrong']} ref-only={v['ref_only_wrong']} noise={v['noise_discordant']} "
            f"allowed={v['allowed_net_loss']} confident-new={v['confident_new_wrong']}"
        )
    g = s["latency"]
    lines.append(f"   latency (bundle)       {'PASS' if g['pass'] else 'FAIL'}  n={g['n']} p50={g['p50']}ms "
                 f"p95={g['p95']}ms {g['p95_ci']} limit<{g['limit_ms']}ms")
    for k, v in s["latency_by_size"].items():
        lines.append(f"     {k:<20} n={v['n']} p50={v['p50']}ms p95={v['p95']}ms")
    for k, v in s["ref_latency"].items():
        lines.append(f"   latency (separate {k:<8}) n={v['n']} p50={v['p50']}ms p95={v['p95']}ms")
    lines.append(f"   commands caught by action (info): {fmt_rate(s['commands_caught_by_action'])}")
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=2, help="bundle calls per fixture (accuracy uses the first)")
    ap.add_argument("--concurrency", type=int, default=1, help="1 = one utterance at a time, as in the app")
    args = ap.parse_args(sys.argv[1:])
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("missing OPENROUTER_API_KEY", file=sys.stderr)
        return 2
    sem = asyncio.Semaphore(args.concurrency)
    jobs = []
    for kind, (fname, *_rest) in KINDS.items():
        for c in (json.loads(l) for l in (FIXTURES / fname).read_text().splitlines() if l.strip()):
            jobs.append(run_case(kind, c, sem, max(1, args.repeats)))
    recs = await asyncio.gather(*jobs)
    s = summarise(recs)
    print(fmt(s))
    print("\n-- bundle-only misses --")
    for r in recs:
        for u in r["units"]:
            if u["ref_ok"] and not u["bundle_ok"]:
                print(f"   {u['question']:<22} {u['case_id']:<24} bundle_conf={u['bundle_conf']:.2f}")
    for r in recs:
        if r["error"]:
            print(f"   ERROR {r['kind']:<8} {r['id']:<14} {r['error']}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"bundle-parity-{date.today().isoformat()}.json"
    out.write_text(json.dumps({"summary": s, "records": recs}, indent=1))
    print(f"\nwrote {out}")
    return 0 if s["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

Why concurrency defaults to 1: the gate is about the latency one radiologist sees, one utterance at a time. Client-side fan-out would inflate the tail and fail the bundle for a reason production never has. `--concurrency 4` is fine for a quick accuracy-only look.

- [ ] **Step 2: Offline sanity checks**

Run: `PYTHONPATH=src $PY -m pytest -q tests/test_bundle_parity.py && PYTHONPATH=src $PY -c "import rapid_reports_ai.scripts.bundle_parity as m; print(sorted(m.KINDS))"`
Expected: tests pass; prints `['boundary', 'coverage', 'triage']`.

- [ ] **Step 3: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/bundle_parity.py
git commit -m "feat(bundle): live parity runner — ref, bundle, ref sandwich over all three fixture sets"
```

---

### Task 10: Run parity live, apply the exit criterion, record

**Files:**
- Create: `docs/model-migration/bundle-parity-<today>.json` (written by the script)
- Modify: `docs/superpowers/handover/2026-09-24-jev-dictation-lab-handover.md` §3 and §6

- [ ] **Step 1: Run**

```bash
PYTHONPATH=src $PY -c "from dotenv import load_dotenv; load_dotenv('.env'); import runpy; runpy.run_module('rapid_reports_ai.scripts.bundle_parity', run_name='__main__')" --repeats 2 > "$TMPDIR/bundle-parity.txt"; echo "exit=$?"; cat "$TMPDIR/bundle-parity.txt"
```
Expected runtime is about 114 fixtures × 4 sequential calls × ~0.3 s ≈ 2–3 min. The output has five question rows (`action`, `coverage`, `is_correction`, `needs_committed_edit`, `standalone`), a bundle latency row with n ≈ 228, and a PASS/FAIL headline.

- [ ] **Step 2: Read the result against the exit criterion.** Do not re-run to get a better number. A second run is allowed only if the first had transport errors, and both runs are then reported.

- **PASS** (every question PASS, latency PASS, errors 0): component 1 has met its exit criterion.
- **A question FAILS:** read the `bundle-only misses` list for it. Two causes are allowed, each with one remedy:
  1. *Subject wording* (misses concentrate on `standalone` or `coverage`, the only reworded questions): one rewording attempt, rerun, report both runs.
  2. *Question interference* (misses on unchanged triage questions): do not tune. Record it. The fallback design is two parallel calls (triage + standalone | coverage), which costs no wall-clock latency; it is component 2's decision.
- **Latency FAILS:** look at `latency_by_size`. If only `>8 questions` breaches, the cost is checklist length (lab-cov-01 has 14 sections), which supports rev 2 §9's open question about a region-first chain. Record it; do not trim the checklist to pass.

- [ ] **Step 3: Record in the handover.** In §3, add one bullet:

```markdown
- **Bundle parity (<today>, 114 fixtures, ref→bundle→ref):** <PASS|FAIL>. Per question (ref vs bundle, bundle-only/ref-only/noise): action <…>; is_correction <…>; needs_committed_edit <…>; standalone <…>; coverage <…>. Bundle p50/p95 <…>/<…> ms [<ci>] over <n> calls (≤8 q: <…>; >8 q: <…>) vs separate p95 triage <…> / boundary <…> / coverage <…>. Commands caught by action: <…>. `docs/model-migration/bundle-parity-<today>.json`.
```

Fill every `<…>` from the printed output. In §6, mark item 2 `**Done <today>**` and item 3 `**Done <today> — PASS**` or `**Run <today> — FAIL: <one clause naming the failing gate>**`.

- [ ] **Step 4: Full suite, then commit**

Run: `PYTHONPATH=src $PY -m pytest -q`
Expected: 0 failures.

```bash
git add ../docs/model-migration/bundle-parity-*.json ../docs/superpowers/handover/2026-09-24-jev-dictation-lab-handover.md
git commit -m "docs(bundle): parity run — per-question verdicts and p95 against the 500 ms gate"
```

---

## Self-review notes

- **Coverage of the request.** Baseline column: Tasks 2–5, run in Task 6. 95 % intervals: Task 1, used in Tasks 3–5 and 8–9. One call per utterance: Task 7. Per-question parity: Tasks 8–10. p95 < 500 ms: `latency_gate` in Task 8, applied in Task 10. The rev 2 §5 invariant "baseline + interval in every bake-off" also covers the new parity script, which reports intervals for every rate. It has no baseline column because parity compares Jev with Jev; the baselines live in the component bake-offs.
- **Deliberately not done:** route wiring (component 2's plan); the `command` choice, `asr_sense`, `tiebreak.*` and `needs_committed` questions in rev 2 §3's diagram (components 4, 5, 7; `needs_committed_edit` from triage is already in the bundle); per-utterance coverage (component 3).
- **Name consistency.** `rate`/`fmt_rate`/`bootstrap_quantile_ci`/`quantile` (Task 1) are used with those names in Tasks 3, 4, 5, 8 and 9. `BundleDecision.triage` is a `TriageDecision`, used as `b.triage.action` in Tasks 8 and 9. `section_key(i)` is used only inside `utterance_bundle.py`.
