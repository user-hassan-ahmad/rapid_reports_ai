# Structure-name check (dictated fidelity step 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flag a dictated value the writer put on a different structure ("aortic sinus 4.1 cm" → "aortic root 4.1 cm") as an action card on the review rail, with an Apply that puts the dictated sentence back when that is safe.

**Architecture:** `dictated_number_check.pairs()` pairs each dictated chain with the FINDINGS sentences that hold it (reusing the number check's extraction and an abbreviation-aware splitter in `template_number_check`). A new `dictated_structure_check.py` passes pairs in code when the report sentence contains the dictated sentence, asks Jev (one request, W1 wording, P(yes) < 0.7 = different site, at most 12 pairs) about the rest, and emits `dictated_structure_changed` review flags with an optional replace edit. `hybrid_stack/report.py` calls it after the number check behind `RR_DICTATED_STRUCTURES` (off by default); `review_engine/live.check_flag_items` passes the kind, label and edit through to the rail. No frontend source changes.

**Tech Stack:** Python 3 (FastAPI backend, pydantic, pytest with `asyncio_mode = "auto"`), Jev via `jev_client.jev_post`; Svelte 5 + vitest browser tests for the one rail test.

**Spec:** `docs/superpowers/specs/2026-10-17-structure-name-check-design.md` (approved; follow it exactly, add no scope).

---

## Conventions for every task

- Worktree: `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/structure-name` (branch `feat/structure-name-check`). All paths below are relative to it.
- Backend test command (run from `backend/`):
  `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest <path> -q`
  Below this is abbreviated as `$PYTEST <path>`; always type the full command.
- Known unrelated failure in the full suite: `tests/test_provider_key_routing.py` (one parametrised case). Ignore it.
- All test data is freshly written SYNTHETIC text. Never copy anything from the private lab repo (`rr-template-conversion-private/synthetic/structure_name/`) into this repo; only its logic is ported (already done in the code below).
- Commit messages end with the two trailer lines:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit
  ```
- Do not push.

## File structure

| File | Change | Responsibility |
|---|---|---|
| `backend/src/rapid_reports_ai/template_number_check.py` | modify | `sentence_spans()` (abbreviation-aware splitter); `_sentence()` uses it |
| `backend/src/rapid_reports_ai/dictated_number_check.py` | modify | `Pair`, `pairs()`, and its helpers `findings_only`, `chains`, `chain_keys`, `strip_prefix`, `norm`; `missing_dictated_numbers` unchanged |
| `backend/src/rapid_reports_ai/dictated_structure_check.py` | create | flag, Jev question/state/call, code pass, judge, items, edit guard |
| `backend/src/rapid_reports_ai/hybrid_stack/report.py` | modify | one call after the number check (shared source list) |
| `backend/src/rapid_reports_ai/review_engine/live.py` | modify | kind in `_FLAG_KINDS`/`_FLAG_LABEL`, key on chain + sentence, edit pass-through |
| `backend/tests/test_template_number_check.py` | modify | splitter tests |
| `backend/tests/test_dictated_structure_pairs.py` | create | pairing tests |
| `backend/tests/test_dictated_structure_check.py` | create | judge, items, edit, Jev call tests |
| `backend/tests/test_stack_review_engine.py` | modify | `check_flag_items` carries edit + `dictated_quote` |
| `backend/tests/test_stack_generate_endpoint.py` | modify | report route with the flag on/off |
| `frontend/src/lib/review/rail/ReviewRail.svelte.test.ts` | modify | the card renders with Apply and "You dictated:" |

---

### Task 1: Abbreviation-aware sentence splitter

**Files:**
- Modify: `backend/src/rapid_reports_ai/template_number_check.py:124-128` (`_sentence`)
- Test: `backend/tests/test_template_number_check.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_template_number_check.py`:

```python


# --- sentence splitting (structure-name check, spec 2026-10-17 §3.1) ---

def test_an_abbreviation_or_initial_does_not_end_a_sentence():
    from rapid_reports_ai.template_number_check import sentence_spans
    text = "Cyst approx. 4 cm in segment 6, e.g. simple. Seen by Dr J. Smith. Spleen 11 cm."
    got = [text[s:e].strip() for s, e in sentence_spans(text)]
    assert got == ["Cyst approx. 4 cm in segment 6, e.g. simple.", "Seen by Dr J. Smith.", "Spleen 11 cm."]


def test_a_decimal_and_a_letter_after_a_digit_still_split_correctly():
    from rapid_reports_ai.template_number_check import _sentence
    assert _sentence("Duct 6.5 mm. Next.", 5) == "Duct 6.5 mm."
    assert _sentence("Lesion in segment 4a. Spleen 11 cm.", 25) == "Spleen 11 cm."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`): `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests/test_template_number_check.py -q`
Expected: `test_an_abbreviation_or_initial_does_not_end_a_sentence` FAILS with `ImportError: cannot import name 'sentence_spans'`; the other new test passes (it guards the decimal and "4a." behaviour that must not change).

- [ ] **Step 3: Implement**

In `backend/src/rapid_reports_ai/template_number_check.py`, replace:

```python
def _sentence(report: str, start: int) -> str:
    """The sentence holding `start`: from the last end (., !, ? before a space, or a line break) to the next."""
    a = max((m.end() for m in _END.finditer(report, 0, start)), default=0)
    m = _END.search(report, start)
    return report[a:m.end() if m else len(report)].strip()
```

with:

```python
_ABBR = {"approx", "e.g", "eg", "i.e", "ie", "vs", "cf", "etc"}
_WORD_BEFORE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z.]*)\Z")


def _is_end(text: str, m: "re.Match[str]") -> bool:
    """A sentence end, unless a lone full stop closes an abbreviation (approx., e.g., i.e., vs., cf., etc.) or a
    single-letter initial."""
    if m.group(0) != ".":
        return True
    w = _WORD_BEFORE.search(text[max(0, m.start() - 24):m.start()])
    if not w:
        return True
    tok = w.group(1).lower()
    return not (tok in _ABBR or (len(tok) == 1 and tok.isalpha()))


def sentence_spans(text: str) -> List[Tuple[int, int]]:
    """[(start, end)] of the non-blank sentences of `text`: an end is ., !, ? before a space or the end, or a line
    break; never inside a decimal, after an abbreviation or after a single-letter initial."""
    out, a = [], 0
    for m in _END.finditer(text):
        if _is_end(text, m):
            out.append((a, m.end()))
            a = m.end()
    if a < len(text):
        out.append((a, len(text)))
    return [(s, e) for s, e in out if text[s:e].strip()]


def _sentence(report: str, start: int) -> str:
    """The sentence holding `start` (`sentence_spans`)."""
    for s, e in sentence_spans(report):
        if s <= start < e:
            return report[s:e].strip()
    return ""
```

(`List` and `Tuple` are already imported: `from typing import Iterable, List, Optional, Set, Tuple`. The lookbehind in `_WORD_BEFORE` keeps "4a." a sentence end: a letter after a digit is not an initial.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests/test_template_number_check.py tests/test_dictated_number_check.py -q`
Expected: all pass (the existing number-check tests use `_sentence` and must not change).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/template_number_check.py backend/tests/test_template_number_check.py
git commit -m "feat(numbers): abbreviation-aware sentence splitter

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 2: `pairs()` in the number check

**Files:**
- Modify: `backend/src/rapid_reports_ai/dictated_number_check.py` (imports at lines 23-25; append before `__all__` at the end)
- Create: `backend/tests/test_dictated_structure_pairs.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_dictated_structure_pairs.py`:

```python
"""Structure-name check pairing (spec 2026-10-17 §3.1): dictated chain -> FINDINGS sentences. SYNTHETIC."""
from rapid_reports_ai.dictated_number_check import Pair, findings_only, pairs, strip_prefix


def P(report, *sources, removed=()):
    return [(p.dictated, p.report, p.chain) for p in pairs(report, list(sources), removed)]


def test_label_and_bullet_prefixes_are_stripped_unless_nothing_else_is_left():
    assert strip_prefix("AORTA: Aortic sinus 4.1 cm.") == "Aortic sinus 4.1 cm."
    assert strip_prefix("- Right kidney 11 cm.") == "Right kidney 11 cm."
    assert strip_prefix("**Liver:** Segment 6 cyst 2 cm.") == "Segment 6 cyst 2 cm."
    assert strip_prefix("LVEF: 45%.") == "LVEF: 45%."


def test_the_impression_is_cut_from_its_heading_line():
    report = "FINDINGS\nAortic root 4.1 cm.\n\nConclusion: aortic sinus 4.1 cm.\n"
    assert findings_only(report) == "FINDINGS\nAortic root 4.1 cm.\n\n"
    assert findings_only("FINDINGS\nA 2 cm.\nIMPRESSION\nB 2 cm.\nCOMPARISON\nC 2 cm.") == \
        "FINDINGS\nA 2 cm.\nCOMPARISON\nC 2 cm."
    assert findings_only("FINDINGS\nA 2 cm.") == "FINDINGS\nA 2 cm."


def test_a_single_pair():
    assert P("FINDINGS\nAORTA: Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.") == [
        ("Aortic sinus 4.1 cm.", "Aortic root 4.1 cm.", "4.1 cm")]


def test_a_value_in_two_findings_sentences_gives_two_pairs_and_the_impression_none():
    report = "FINDINGS\nThe right kidney is 11 cm. Renal length 11 cm on the right.\n\nIMPRESSION\nRight kidney 11 cm."
    assert [r for _, r, _ in P(report, "Right kidney 11 cm.")] == ["The right kidney is 11 cm.",
                                                                   "Renal length 11 cm on the right."]


def test_a_chain_is_paired_once_and_needs_all_its_values():
    assert P("Cyst 2.3 x 1.8 cm in segment 6.", "Segment 6 cyst 2.3 x 1.8 cm.") == [
        ("Segment 6 cyst 2.3 x 1.8 cm.", "Cyst 2.3 x 1.8 cm in segment 6.", "2.3 x 1.8 cm")]
    assert P("Cyst 2.3 cm. Node 1.8 cm.", "Segment 6 cyst 2.3 x 1.8 cm.") == []


def test_one_report_value_said_to_cover_both_pairs_with_each_dictated_value():
    got = P("Both kidneys measure 11 cm.", "Right kidney 11 cm. Left kidney 11 cm.")
    assert got == [("Right kidney 11 cm.", "Both kidneys measure 11 cm.", "11 cm"),
                   ("Left kidney 11 cm.", "Both kidneys measure 11 cm.", "11 cm")]


def test_identical_pairs_from_two_sources_are_one():
    assert len(pairs("Spleen 13 cm.", ["Spleen 13 cm.", "Spleen 13 cm."])) == 1


def test_a_removed_sentence_and_a_unitless_value_are_not_paired():
    assert P("Spleen 13 cm. Ratio 0.4.", "Spleen 13 cm.", "Ratio 0.4.", removed=["spleen 13 cm"]) == []


def test_a_value_only_fragment_is_joined_to_the_sentence_before_it():
    got = P("The left ventricle is mildly impaired. LVEF 45%.", "Left ventricle mildly impaired, LVEF 45%.")
    assert got == [("Left ventricle mildly impaired, LVEF 45%.",
                    "The left ventricle is mildly impaired. LVEF 45%.", "45%")]


def test_pairs_come_in_report_order():
    got = pairs("Spleen 13 cm. Liver 18 cm.", ["Liver 18 cm.", "Spleen 13 cm."])
    assert [p.chain for p in got] == ["13 cm", "18 cm"]
    assert isinstance(got[0], Pair)


def test_never_raises_on_empty_input():
    assert pairs(None, [None, ""]) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests/test_dictated_structure_pairs.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'Pair' from 'rapid_reports_ai.dictated_number_check'`.

- [ ] **Step 3: Implement**

In `backend/src/rapid_reports_ai/dictated_number_check.py` replace the two import lines

```python
from typing import Iterable, List, Optional

from .template_number_check import _masked, _sentence
```

with

```python
from typing import FrozenSet, Iterable, List, Optional, Set, Tuple

from .template_number_check import _masked, _sentence, sentence_spans
```

Then replace the last line

```python
__all__ = ["KIND", "FLAG", "Num", "enabled", "extract", "missing_dictated_numbers"]
```

with:

```python
# --- pairing for the structure-name check (spec 2026-10-17 §3.1) ---

# a leading bullet or number, then a line label ("AORTA: ", "**Liver:** ")
_PREFIX = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)?(?:\*\*[^*\n]{1,60}?:?\*\*:?\s*|[A-Za-z][A-Za-z /&()'-]{0,40}:\s+)?")
_IMPRESSION = re.compile(r"(?im)^[ \t]*(?:#+[ \t]*)?(?:\*\*)?(?:impression|conclusion)s?\b")
_HEADING = re.compile(r"(?m)^[ \t]*(?:#+[ \t]*)?(?:\*\*)?[A-Z][A-Z /&()-]{2,40}:?(?:\*\*)?[ \t]*$")   # all-caps line
_LETTERS = re.compile(r"[a-z][a-z']+")


@dataclass(frozen=True)
class Pair:
    dictated: str   # the dictated sentence holding the chain, label prefix stripped
    report: str     # the FINDINGS sentence holding every value of the chain, label prefix stripped
    chain: str      # the dictated chain as written ("2.3 x 1.8 cm")


def findings_only(report: Optional[str]) -> str:
    """`report` minus its impression: from a line starting IMPRESSION or CONCLUSION (any case, optional colon) to the
    next all-caps heading line, or to the end."""
    report = report or ""
    m = _IMPRESSION.search(report)
    if not m:
        return report
    nxt = _HEADING.search(report, m.end())   # "^" never matches mid-line, so the impression line itself is skipped
    return report[:m.start()] + (report[nxt.start():] if nxt else "")


def _words(text: str) -> Set[str]:
    return set(_LETTERS.findall(text.lower()))


def chains(text: Optional[str]) -> List[Tuple[int, str, FrozenSet[tuple]]]:
    """[(start, chain text, {(value, unit)})] for each chain in `text` that carries a unit, in text order."""
    by: dict = {}
    for n in extract(text):
        if n.unit:
            by.setdefault((n.start, n.text), set()).add((n.value, n.unit))
    return [(s, t, frozenset(v)) for (s, t), v in sorted(by.items())]


def chain_keys(text: Optional[str]) -> Set[FrozenSet[tuple]]:
    return {k for _, _, k in chains(text)}


def strip_prefix(sentence: str) -> str:
    """`sentence` without a leading bullet, number or line label ("AORTA:", "- ", "**Liver:**"); unchanged when the
    label is all there is besides the values ("LVEF: 45%.")."""
    s = sentence.strip()
    m = _PREFIX.match(s)
    out = s[m.end():].strip() if m else s
    rest = out
    for _, t, _ in chains(out):
        rest = rest.replace(t, " ")
    return out if out and _words(rest) else s


def norm(text: str) -> str:
    """Lower case, full stops (not decimal points) and other punctuation to spaces, whitespace collapsed."""
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text.lower())
    s = re.sub(r"[^\w.%/]+", " ", s)
    return " ".join(s.split())


def _value_only(sentence: str, dictated: str) -> bool:
    """No word besides the values and at most two names that the dictated sentence also holds ("LVEF 45%.")."""
    s, d = sentence, dictated
    for _, t, _ in chains(sentence):
        s = s.replace(t, " ")
    for _, t, _ in chains(dictated):
        d = d.replace(t, " ")
    w = _words(s)
    return len(w) <= 2 and w < _words(d)


def pairs(report: Optional[str], sources: Iterable[Optional[str]], removed: Iterable[str] = ()) -> List[Pair]:
    """One Pair per dictated chain (with a unit) per FINDINGS sentence holding all its values, in report order.
    `sources` as for `missing_dictated_numbers`; a dictated sentence equal to a removed one (normalised) is skipped.
    A value-only report fragment is joined to the sentence before it on the same line. Identical pairs are one."""
    text = findings_only(report)
    spans = sentence_spans(text)
    held: dict = {}   # sentence index -> {(value, unit)}
    for n in extract(text):
        if n.unit:
            i = next((k for k, (s, e) in enumerate(spans) if s <= n.start < e), None)
            if i is not None:
                held.setdefault(i, set()).add((n.value, n.unit))
    gone = {norm(r) for r in removed if r}
    out: List[Tuple[int, Pair]] = []
    seen: set = set()
    for src in sources:
        if not src:
            continue
        sspans = sentence_spans(src)
        for start, chain, keys in chains(src):
            j = next((k for k, (s, e) in enumerate(sspans) if s <= start < e), None)
            if j is None:
                continue
            d = strip_prefix(src[sspans[j][0]:sspans[j][1]])
            if norm(d) in gone:
                continue
            for i in sorted(held):
                if not keys <= held[i]:
                    continue
                a, b = spans[i]
                raw = text[a:b].strip()
                if i > 0 and "\n" not in text[spans[i - 1][0]:a] and _value_only(raw, d):
                    a = spans[i - 1][0]   # a value-only fragment ("LVEF 45%.") reads with the sentence before it
                    raw = text[a:b].strip()
                p = Pair(d, strip_prefix(raw), chain)
                if p in seen:
                    continue
                seen.add(p)
                out.append((a, p))
    out.sort(key=lambda x: x[0])
    return [p for _, p in out]


__all__ = ["KIND", "FLAG", "Num", "Pair", "enabled", "extract", "missing_dictated_numbers", "pairs", "findings_only",
           "chains", "chain_keys", "strip_prefix", "norm"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests/test_dictated_structure_pairs.py tests/test_dictated_number_check.py -q`
Expected: all pass (`missing_dictated_numbers` unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/dictated_number_check.py backend/tests/test_dictated_structure_pairs.py
git commit -m "feat(numbers): pair dictated chains with FINDINGS sentences

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 3: The structure check — code pass, Jev judge, items (no edit yet)

**Files:**
- Create: `backend/src/rapid_reports_ai/dictated_structure_check.py`
- Create: `backend/tests/test_dictated_structure_check.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_dictated_structure_check.py`:

```python
"""Structure-name check (spec 2026-10-17, dictated fidelity step 3): code pass, Jev judge, items, edit. SYNTHETIC."""
import asyncio
import logging

import pytest

from rapid_reports_ai import dictated_structure_check as dsc
from rapid_reports_ai.dictated_number_check import Pair


def _ask(p_of=None, default=0.95):
    """A stand-in for the Jev call: P(same site) per report sentence (default 0.95), recording what was asked."""
    seen = {"calls": 0, "pairs": []}

    async def ask(ps):
        seen["calls"] += 1
        seen["pairs"] = [(p.dictated, p.report) for p in ps]
        return [(p_of or {}).get(p.report, default) for p in ps]
    return ask, seen


async def run(report, *sources, removed=(), p_of=None, default=0.95):
    ask, seen = _ask(p_of, default)
    return await dsc.changed_structures(report, list(sources), removed, ask=ask), seen


def test_question_wording_is_w1_verbatim_and_state_numbers_the_pairs():
    assert dsc.question("pair_1") == {"type": "noul", "instructions":
        "In pair_1, the REPORT sentence gives the value for exactly the same anatomical structure, site, side and "
        "level as the DICTATED sentence; synonyms and rewording count as the same, a broader or narrower site does "
        "not."}
    assert dsc.state([Pair("a 1 cm.", "b 1 cm.", "1 cm")]) == {"pair_1": {"dictated": "a 1 cm.", "report": "b 1 cm."}}


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("RR_DICTATED_STRUCTURES", raising=False)
    assert dsc.enabled() is False
    monkeypatch.setenv("RR_DICTATED_STRUCTURES", "1")
    assert dsc.enabled() is True


async def test_a_sentence_holding_the_dictated_words_passes_in_code_without_jev():
    items, seen = await run("FINDINGS\nAORTA: The aortic sinus 4.1 cm, stable.", "Aortic sinus 4.1 cm.", default=0.0)
    assert items == [] and seen["calls"] == 0


async def test_a_moved_value_is_one_high_severity_item_on_its_findings_sentence():
    report = "FINDINGS\nAORTA: Aortic root 4.1 cm.\nLiver normal."
    items, seen = await run(report, "Aortic sinus 4.1 cm.", p_of={"Aortic root 4.1 cm.": 0.2})
    assert seen["pairs"] == [("Aortic sinus 4.1 cm.", "Aortic root 4.1 cm.")]
    assert [(i["kind"], i["severity"], i["text"], i["sentence"], i["dictated_quote"]) for i in items] == [
        ("dictated_structure_changed", "high", "4.1 cm", "Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.")]


@pytest.mark.parametrize("p, flagged", [(0.69, True), (0.7, False), (0.95, False)])
async def test_threshold_is_p_below_0_7(p, flagged):
    items, _ = await run("Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.", default=p)
    assert bool(items) is flagged


async def test_a_chain_passes_if_any_of_its_findings_sentences_is_the_same_site():
    report = "Aortic root 4.1 cm. The sinus of Valsalva measures 4.1 cm."
    items, _ = await run(report, "Aortic sinus 4.1 cm.", p_of={"Aortic root 4.1 cm.": 0.1})
    assert items == []


async def test_findings_wrong_and_impression_right_is_still_an_item():
    report = "FINDINGS\nAortic root 4.1 cm.\n\nIMPRESSION\nAortic sinus 4.1 cm."
    items, seen = await run(report, "Aortic sinus 4.1 cm.", default=0.1)
    assert [i["sentence"] for i in items] == ["Aortic root 4.1 cm."]
    assert seen["pairs"] == [("Aortic sinus 4.1 cm.", "Aortic root 4.1 cm.")]


async def test_at_most_twelve_pairs_are_asked_and_the_rest_logged_unchecked(caplog):
    sources = [f"Node {n} mm at station {n}." for n in range(11, 25)]   # 14 values
    report = " ".join(f"Nodule {n} mm." for n in range(11, 25))
    caplog.set_level(logging.INFO, logger="rapid_reports_ai.dictated_structure_check")
    items, seen = await run(report, *sources, default=0.1)
    assert len(seen["pairs"]) == 12 and seen["pairs"][0][1] == "Nodule 11 mm."
    assert [i["text"] for i in items] == [f"{n} mm" for n in range(11, 23)]   # the 2 unasked give no item
    assert "structure_name_unchecked" in caplog.text


@pytest.mark.parametrize("fail", ["raise", "short", "timeout"])
async def test_a_jev_failure_gives_no_item_and_is_logged(fail, monkeypatch, caplog):
    async def ask(ps):
        if fail == "raise":
            raise RuntimeError("down")
        if fail == "timeout":
            await asyncio.sleep(1)
        return []
    monkeypatch.setattr(dsc, "TIMEOUT_S", 0.05)
    caplog.set_level(logging.INFO, logger="rapid_reports_ai.dictated_structure_check")
    assert await dsc.changed_structures("Aortic root 4.1 cm.", ["Aortic sinus 4.1 cm."], ask=ask) == []
    assert "structure_name_check_unavailable" in caplog.text


async def test_two_failing_values_in_one_sentence_are_two_items():
    items, _ = await run("Right kidney 11 cm and right adrenal 2 cm.",
                         "Left kidney 11 cm.", "Left adrenal 2 cm.", default=0.1)
    assert [(i["text"], i["sentence"]) for i in items] == [
        ("11 cm", "Right kidney 11 cm and right adrenal 2 cm."), ("2 cm", "Right kidney 11 cm and right adrenal 2 cm.")]


async def test_a_removed_sentence_is_never_checked():
    items, seen = await run("Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.", removed=["Aortic sinus 4.1 cm."],
                            default=0.1)
    assert items == [] and seen["calls"] == 0


async def test_an_abbreviation_does_not_split_the_dictated_or_report_sentence():
    items, seen = await run("Cyst approx. 4 cm in the left lobe.", "Cyst approx. 4 cm in segment 6.", default=0.1)
    assert seen["pairs"] == [("Cyst approx. 4 cm in segment 6.", "Cyst approx. 4 cm in the left lobe.")]
    assert len(items) == 1


async def test_never_raises():
    assert await dsc.changed_structures(None, [None, ""]) == []


async def test_ask_same_site_sends_one_request_and_refuses_a_partial_answer(monkeypatch):
    from rapid_reports_ai import jev_client
    sent = []

    class R:
        def __init__(self, ans):
            self.ans = ans

        def raise_for_status(self):
            pass

        def json(self):
            return {"answers": self.ans}

    def post(ans):
        async def f(body, key, timeout, transport=None):
            sent.append((body, timeout))
            return R(ans)
        return f
    ps = [Pair("Aortic sinus 4.1 cm.", "Aortic root 4.1 cm.", "4.1 cm"), Pair("Spleen 13 cm.", "Spleen 13 cm.", "13 cm")]
    monkeypatch.setattr(jev_client, "jev_post", post({"pair_1": {"noul": 0.2}, "pair_2": {"noul": 0.9}}))
    assert await dsc.ask_same_site(ps) == [0.2, 0.9]
    body, timeout = sent[0]
    assert len(sent) == 1 and body["model"] == jev_client.JEV_MODEL and timeout == 3.0
    assert body["state"]["pair_1"] == {"dictated": "Aortic sinus 4.1 cm.", "report": "Aortic root 4.1 cm."}
    assert body["questions"]["pair_2"] == dsc.question("pair_2")
    monkeypatch.setattr(jev_client, "jev_post", post({"pair_1": {"noul": 0.2}}))
    with pytest.raises(ValueError):
        await dsc.ask_same_site(ps)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests/test_dictated_structure_check.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'dictated_structure_check' from 'rapid_reports_ai'`.

- [ ] **Step 3: Implement**

Create `backend/src/rapid_reports_ai/dictated_structure_check.py`:

```python
"""A dictated value written against another structure (spec 2026-10-17, dictated fidelity step 3).

Dictated "aortic sinus 4.1 cm", report "aortic root 4.1 cm": the number check passes, the site changed. Each dictated
chain with a unit is paired with the FINDINGS sentences that hold it (`dictated_number_check.pairs`). A pair whose
report sentence contains the dictated sentence (normalised) passes in code; the rest go to Jev in one request (W1
wording, at most MAX_PAIRS, in report order; any beyond are logged `structure_name_unchecked` and give no item). A
pair is a different site when P(yes) < SAME_SITE_MIN; a chain passes when any of its sentences is the same site.
A failing chain is one review flag (severity high: an action card), anchored on its first FINDINGS sentence, with
a replace edit back to the dictated sentence only when that cannot lose or repeat content. Never applied here, never
raises; a Jev error, timeout or partial answer gives no item and logs `structure_name_check_unavailable`.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Callable, Dict, Iterable, List, Optional

from . import dictated_number_check as dnc

logger = logging.getLogger(__name__)

KIND = "dictated_structure_changed"
FLAG = "RR_DICTATED_STRUCTURES"
SAME_SITE_MIN = 0.7    # P(yes) below this: a different site (lab 2026-10-17 §7)
MAX_PAIRS = 12
TIMEOUT_S = 3.0        # as jev_stack.TIMEOUT_S
LABEL = "Different site from your dictation? Apply puts your sentence back."
LABEL_NO_EDIT = "Different site from your dictation? Check this sentence."

Ask = Callable[[List[dnc.Pair]], Awaitable[List[float]]]


def enabled() -> bool:
    """Off unless RR_DICTATED_STRUCTURES is 1/true/on (read per call)."""
    return os.environ.get(FLAG, "0").strip().lower() in ("1", "true", "on")


def question(key: str) -> dict:
    """The lab wording W1, verbatim."""
    return {"type": "noul", "instructions":
            f"In {key}, the REPORT sentence gives the value for exactly the same anatomical structure, site, side and "
            f"level as the DICTATED sentence; synonyms and rewording count as the same, a broader or narrower site "
            f"does not."}


def state(ps: List[dnc.Pair]) -> Dict[str, dict]:
    return {f"pair_{i + 1}": {"dictated": p.dictated, "report": p.report} for i, p in enumerate(ps)}


async def ask_same_site(ps: List[dnc.Pair]) -> List[float]:
    """P(same site) per pair, in order: one Jev request."""
    from .jev_client import JEV_MODEL, jev_post
    qs = {f"pair_{i + 1}": question(f"pair_{i + 1}") for i in range(len(ps))}
    r = await jev_post({"model": JEV_MODEL, "state": state(ps), "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    out: List[float] = []
    for i in range(len(ps)):
        p = (ans.get(f"pair_{i + 1}") or {}).get("noul")
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            raise ValueError("jev: incomplete answers")   # a missing answer is never "different site"
        out.append(float(p))
    return out


def code_pass(p: dnc.Pair) -> bool:
    """The report sentence holds the dictated sentence word for word (case, whitespace, punctuation aside)."""
    return dnc.norm(p.dictated) in dnc.norm(p.report)


async def changed_structures(report: Optional[str], sources: Iterable[Optional[str]], removed: Iterable[str] = (),
                             ask: Optional[Ask] = None) -> List[dict]:
    """[{"kind", "severity": "high", "text", "sentence", "dictated_quote", "message", "edit"}], one per dictated
    chain whose every FINDINGS sentence Jev reads as a different site. `sources`: the radiologist's own statements
    (as for the number check); `removed`: the sentences the radiologist removed. Never raises."""
    try:
        report = report or ""
        sources = [s for s in sources if s]
        ps = dnc.pairs(report, sources, removed)
        asked = [p for p in ps if not code_pass(p)]
        if len(asked) > MAX_PAIRS:
            logger.info("structure_name_unchecked: %d pairs over the cap of %d", len(asked) - MAX_PAIRS, MAX_PAIRS)
        asked = asked[:MAX_PAIRS]
        same: Dict[dnc.Pair, Optional[bool]] = {p: (True if code_pass(p) else None) for p in ps}
        if asked:
            try:
                probs = await asyncio.wait_for((ask or ask_same_site)(asked), TIMEOUT_S)
                if len(probs) != len(asked):
                    raise ValueError("jev: answer count mismatch")
            except Exception as e:  # noqa: BLE001 - fail open: no item
                logger.info("structure_name_check_unavailable (%s: %s)", type(e).__name__, str(e)[:200])
                return []
            for p, pr in zip(asked, probs):
                same[p] = pr >= SAME_SITE_MIN
        groups: Dict[tuple, List[dnc.Pair]] = {}
        for p in ps:   # report order: a chain's first pair is its first FINDINGS sentence
            groups.setdefault((p.dictated, p.chain), []).append(p)
        out: List[dict] = []
        for (dictated, chain), gp in groups.items():
            if any(same[p] is not False for p in gp):   # passes if any sentence is the same site; unasked: unknown
                continue
            out.append({"kind": KIND, "severity": "high", "text": chain, "sentence": gp[0].report,
                        "dictated_quote": dictated, "message": LABEL_NO_EDIT, "edit": None})
        return out
    except Exception as e:  # noqa: BLE001 - a flag is never worth a failed report
        logger.info("structure_name_check_unavailable (%s: %s)", type(e).__name__, str(e)[:200])
        return []


__all__ = ["KIND", "FLAG", "SAME_SITE_MIN", "MAX_PAIRS", "TIMEOUT_S", "LABEL", "LABEL_NO_EDIT", "enabled", "question",
           "state", "ask_same_site", "code_pass", "changed_structures"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests/test_dictated_structure_check.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/dictated_structure_check.py backend/tests/test_dictated_structure_check.py
git commit -m "feat(structure-check): Jev same-site judge for dictated values

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 4: The "use your sentence" edit and its guard (spec §3.5)

**Files:**
- Modify: `backend/src/rapid_reports_ai/dictated_structure_check.py`
- Test: `backend/tests/test_dictated_structure_check.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_dictated_structure_check.py`:

```python


# --- the edit (spec §3.5) ---

async def test_a_moved_value_carries_the_edit_and_the_apply_label():
    report = "FINDINGS\nAORTA: Aortic root 4.1 cm.\nLiver normal."
    items, _ = await run(report, "Aortic sinus 4.1 cm.", p_of={"Aortic root 4.1 cm.": 0.2})
    assert items == [{"kind": "dictated_structure_changed", "severity": "high", "text": "4.1 cm",
                      "sentence": "Aortic root 4.1 cm.", "dictated_quote": "Aortic sinus 4.1 cm.",
                      "message": "Different site from your dictation? Apply puts your sentence back.",
                      "edit": {"mode": "replace", "find": "Aortic root 4.1 cm.", "replace": "Aortic sinus 4.1 cm."}}]


async def test_the_edit_capitalises_the_dictated_sentence_and_adds_a_full_stop():
    items, _ = await run("Cyst approx. 4 cm in the left lobe.", "cyst approx. 4 cm in segment 6", default=0.1)
    assert items[0]["edit"] == {"mode": "replace", "find": "Cyst approx. 4 cm in the left lobe.",
                                "replace": "Cyst approx. 4 cm in segment 6."}


async def test_no_edit_when_the_find_occurs_twice():
    items, _ = await run("Aortic root 4.1 cm. Prior: Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.", default=0.1)
    assert [i["edit"] for i in items] == [None]
    assert items[0]["message"] == "Different site from your dictation? Check this sentence."


async def test_no_edit_when_a_number_free_clause_was_merged_in():
    items, _ = await run("Aortic root 4.1 cm with no aortic regurgitation.", "Aortic sinus 4.1 cm.", default=0.1)
    assert [i["edit"] for i in items] == [None]


async def test_no_edit_when_the_writer_merged_a_word_from_another_statement():
    items, _ = await run("Simple cyst 3 cm in the right lobe.", "Cyst 3 cm in segment 6.", "The cyst is simple.",
                         default=0.1)
    assert [i["edit"] for i in items] == [None]


async def test_no_edit_on_a_reverse_split():
    # dictated as one sentence with two values, written as two: the report sentence lacks a dictated chain
    items, _ = await run("Right kidney 11 cm. Spleen 13 cm.", "Left kidney 11 cm, spleen 13 cm.",
                         p_of={"Right kidney 11 cm.": 0.1})
    assert [(i["text"], i["edit"]) for i in items] == [("11 cm", None)]


async def test_no_edit_when_two_values_share_the_report_sentence():
    items, _ = await run("Right kidney 11 cm and right adrenal 2 cm.",
                         "Left kidney 11 cm.", "Left adrenal 2 cm.", default=0.1)
    assert [i["edit"] for i in items] == [None, None]


async def test_no_edit_with_an_extra_joiner():
    items, _ = await run("Aortic root, ascending, 4.1 cm.", "Aortic sinus 4.1 cm.", default=0.1)
    assert [i["edit"] for i in items] == [None]


async def test_side_and_level_words_from_another_statement_do_not_withhold_the_edit():
    items, _ = await run("Left kidney 11 cm. Right kidney 10 cm.", "Right kidney 11 cm.", "Left kidney 10 cm.",
                         default=0.1)
    assert [i["edit"] for i in items] == [
        {"mode": "replace", "find": "Left kidney 11 cm.", "replace": "Right kidney 11 cm."},
        {"mode": "replace", "find": "Right kidney 10 cm.", "replace": "Left kidney 10 cm."}]
    items, _ = await run("Disc protrusion at L5/S1 4 mm.", "Disc protrusion at L4/5 4 mm.", "L5/S1 disc normal.",
                         default=0.1)
    assert [i["edit"] for i in items] == [
        {"mode": "replace", "find": "Disc protrusion at L5/S1 4 mm.", "replace": "Disc protrusion at L4/5 4 mm."}]
```

- [ ] **Step 2: Run the tests to verify the new behaviour fails**

Run: `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests/test_dictated_structure_check.py -q`
Expected: `test_a_moved_value_carries_the_edit_and_the_apply_label`, `test_the_edit_capitalises_the_dictated_sentence_and_adds_a_full_stop` and `test_side_and_level_words_from_another_statement_do_not_withhold_the_edit` FAIL (`edit` is `None`); the "no edit" tests already pass and guard the next step.

- [ ] **Step 3: Implement**

In `backend/src/rapid_reports_ai/dictated_structure_check.py`:

(a) Replace the imports

```python
import asyncio
import logging
import os
from typing import Awaitable, Callable, Dict, Iterable, List, Optional

from . import dictated_number_check as dnc
```

with

```python
import asyncio
import logging
import os
import re
from typing import Awaitable, Callable, Dict, Iterable, List, Optional, Set

from . import dictated_number_check as dnc
from .template_number_check import sentence_spans
```

(b) Below the line `LABEL_NO_EDIT = "Different site from your dictation? Check this sentence."` add:

```python

_JOINER = re.compile(r"(?i)\band\b|\bwith\b|;|,")
_LETTERS = re.compile(r"[a-z][a-z']+")   # digits never count: a level ("L4/5", "C5-6") is never a content word
_STOP = frozenset("""a an the of in at on to is are was were be been with and or there this that its it as by for from
into measures measure measuring measured measurement seen present noted demonstrated identified shows has have no not
without other up than less more over about approx approximately""".split())
_SIDE = frozenset({"left", "right", "bilateral", "bilaterally"})   # what the check corrects: never "merged content"
```

(c) Below `code_pass` add:

```python


def _words(text: str) -> Set[str]:
    return set(_LETTERS.findall(text.lower()))


def _statements(sources: Iterable[Optional[str]]) -> List[str]:
    return [dnc.strip_prefix(src[s:e]) for src in sources if src for s, e in sentence_spans(src)]


def edit_for(p: dnc.Pair, report: str, sources: Iterable[Optional[str]]) -> Optional[dict]:
    """A replace edit putting the dictated sentence back, or None when replacing the whole sentence could lose or
    repeat content (spec §3.5): other values in it, an extra clause joiner, a word merged in from another dictated
    statement (side words aside), or a find that does not occur exactly once."""
    find = p.report
    if dnc.chain_keys(find) != dnc.chain_keys(p.dictated):
        return None
    if len(_JOINER.findall(find)) > len(_JOINER.findall(p.dictated)):
        return None
    if report.count(find) != 1:
        return None
    own = _words(p.dictated)
    other: Set[str] = set()
    for s in _statements(sources):
        if s != p.dictated:
            other |= _words(s)
    if any(w in other and w not in own for w in _words(find) - _STOP - _SIDE):
        return None
    rep = p.dictated.strip()
    rep = rep[:1].upper() + rep[1:]
    if not rep.endswith((".", "!", "?")):
        rep += "."
    return {"mode": "replace", "find": find, "replace": rep}
```

(d) In `changed_structures` replace

```python
            out.append({"kind": KIND, "severity": "high", "text": chain, "sentence": gp[0].report,
                        "dictated_quote": dictated, "message": LABEL_NO_EDIT, "edit": None})
```

with

```python
            edit = edit_for(gp[0], report, sources)
            out.append({"kind": KIND, "severity": "high", "text": chain, "sentence": gp[0].report,
                        "dictated_quote": dictated, "message": LABEL if edit else LABEL_NO_EDIT, "edit": edit})
```

(e) Add `"edit_for"` to `__all__`:

```python
__all__ = ["KIND", "FLAG", "SAME_SITE_MIN", "MAX_PAIRS", "TIMEOUT_S", "LABEL", "LABEL_NO_EDIT", "enabled", "question",
           "state", "ask_same_site", "code_pass", "edit_for", "changed_structures"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests/test_dictated_structure_check.py -q`
Expected: all pass. Sanity check that the side/level test guards the exemption: temporarily set `_SIDE = frozenset()`, rerun, see `test_side_and_level_words_from_another_statement_do_not_withhold_the_edit` fail, then restore.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/dictated_structure_check.py backend/tests/test_dictated_structure_check.py
git commit -m "feat(structure-check): offer the dictated sentence back when it is safe

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 5: Rail items carry the kind, label, quote and edit

**Files:**
- Modify: `backend/src/rapid_reports_ai/review_engine/live.py:206-247` (`_FLAG_KINDS`, `_FLAG_LABEL`, `check_flag_items`)
- Test: `backend/tests/test_stack_review_engine.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_stack_review_engine.py` (`_inp` there builds a stack report `"FINDINGS\nLiver normal. 12 mm cyst."`):

```python


def test_a_moved_value_is_an_anchored_action_item_carrying_its_edit_and_quote():
    edit = {"mode": "replace", "find": "12 mm cyst.", "replace": "Segment 6 cyst 12 mm."}
    flag = {"kind": "dictated_structure_changed", "severity": "high", "text": "12 mm", "sentence": "12 mm cyst.",
            "dictated_quote": "Segment 6 cyst 12 mm.",
            "message": "Different site from your dictation? Apply puts your sentence back.", "edit": edit}
    inp = _inp(review=[flag, {**flag, "text": "4 mm", "edit": {"mode": "bogus"}},
                       {"kind": "dictated_number_missing", "severity": "high", "text": "9 mm", "sentence": "x",
                        "edit": edit}])
    items = live.check_flag_items(inp, "run1")
    assert [i.kind for i in items] == ["dictated_structure_changed", "dictated_structure_changed",
                                       "dictated_number_missing"]
    item = items[0]
    assert item.cls == "action" and item.status == "open"
    assert item.edit is not None and item.edit.model_dump(exclude_none=True) == edit
    assert item.evidence["dictated_quote"] == "Segment 6 cyst 12 mm."
    assert item.label == "Different site from your dictation? Apply puts your sentence back."
    assert inp.artifacts.report[item.anchor.start:item.anchor.end] == "12 mm cyst."
    assert items[1].edit is None and items[1].key != item.key   # a malformed edit: no Apply; the chain keys it
    assert items[2].edit is None   # other flag kinds never carry an edit
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests/test_stack_review_engine.py -q`
Expected: the new test FAILS (the kind is not in `_FLAG_KINDS`, so only `dictated_number_missing` comes back).

- [ ] **Step 3: Implement**

In `backend/src/rapid_reports_ai/review_engine/live.py`:

(a) Replace

```python
_FLAG_KINDS = {"removed_asserted", "removed_unverified", "undictated_number", "value_missing", "dictated_number_missing",
               "value_said_elsewhere"}   # the last: a quiet note (cls info), never a flag to act on
_FLAG_LABEL = {
    "undictated_number": "Number not in the dictation: {text}",
    "dictated_number_missing": "Dictated number not in the report: {text}",
    "value_missing": "Required value not in the report: {text}",
}
```

with

```python
_FLAG_KINDS = {"removed_asserted", "removed_unverified", "undictated_number", "value_missing", "dictated_number_missing",
               "dictated_structure_changed",
               "value_said_elsewhere"}   # the last: a quiet note (cls info), never a flag to act on
_FLAG_LABEL = {
    "undictated_number": "Number not in the dictation: {text}",
    "dictated_number_missing": "Dictated number not in the report: {text}",
    "value_missing": "Required value not in the report: {text}",
    "dictated_structure_changed": "Different site from your dictation? Apply puts your sentence back.",
}
_EDIT_KINDS = {"dictated_structure_changed"}   # the only flag that carries an edit (spec 2026-10-17 §3.5)


def _flag_edit(e: dict) -> Optional[Edit]:
    """The flag's own replace edit, for a kind that may carry one; None otherwise or when it is malformed."""
    if e.get("kind") not in _EDIT_KINDS or not isinstance(e.get("edit"), dict):
        return None
    try:
        return Edit(**e["edit"])
    except Exception:  # noqa: BLE001 - a malformed edit leaves the card without Apply
        return None
```

(b) In the `check_flag_items` docstring replace

```python
    values) as open rail items (integration spec §7.6). No edit: the radiologist decides."""
```

with

```python
    values, moved values) as open rail items (integration spec §7.6). Only a moved value (dictated_structure_changed)
    may carry an edit, applied only when the radiologist presses Apply; the rest have none."""
```

(c) Replace

```python
        if kind == "dictated_number_missing" and e.get("text"):   # one item per missing number, not per sentence
```

with

```python
        if kind in ("dictated_number_missing", "dictated_structure_changed") and e.get("text"):   # one item per value
```

(d) Replace

```python
            anchor=anchor, label=str(label)[:80], reason=str(label), edit=None,
```

with

```python
            anchor=anchor, label=str(label)[:80], reason=str(label), edit=_flag_edit(e),
```

(`Edit` and `Optional` are already imported in `live.py`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests/test_stack_review_engine.py tests/test_review_engine_template_gaps.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/review_engine/live.py backend/tests/test_stack_review_engine.py
git commit -m "feat(review): moved-value flags reach the rail with their edit

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 6: One call in the stack Generate, behind `RR_DICTATED_STRUCTURES`

**Files:**
- Modify: `backend/src/rapid_reports_ai/hybrid_stack/report.py:21` (import) and `:100-103` (after the number check)
- Test: `backend/tests/test_stack_generate_endpoint.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_stack_generate_endpoint.py` (it reuses the file's `UNITS`, `authed`, `fakes`, `_events`, `_body`, `SR`, `StackUnit`, `findings_hash`):

```python


SITE_UNITS = [{**UNITS[0], "text": "Aortic sinus 4.1 cm.", "abnormal": True}]   # SYNTHETIC


@pytest.mark.parametrize("on", [True, False])
def test_quick_flags_a_dictated_value_moved_to_another_structure(authed, fakes, monkeypatch, on):
    from rapid_reports_ai import dictated_structure_check as dsc

    async def quick(**kw):
        return {"report_content": "FINDINGS\nAortic root 4.1 cm.\n\nIMPRESSION\nAortic sinus 4.1 cm.",
                "description": "d", "scan_type": "CT", "model_used": "m",
                "quality_check": {"enabled": True, "review": []}, "signature": ""}

    async def ask(ps):
        return [0.1 for _ in ps]
    monkeypatch.setattr(SR, "generate_quick_report", quick)
    monkeypatch.setattr(dsc, "ask_same_site", ask)
    if on:
        monkeypatch.setenv("RR_DICTATED_STRUCTURES", "1")
    else:
        monkeypatch.delenv("RR_DICTATED_STRUCTURES", raising=False)
    units = [StackUnit.model_validate(u) for u in SITE_UNITS]
    gate = {"conclusion_text": "Dilated aortic sinus.", "removed": [], "units_hash": "k",
            "findings_hash": findings_hash(units)}
    events = _events(authed.post("/api/canvas/stack/generate", json=_body(units=SITE_UNITS, gate=gate)))
    flags = [i for i in events[0][1]["quality_check"]["review"] if i.get("kind") == "dictated_structure_changed"]
    if not on:
        assert flags == []
        return
    assert [(f["text"], f["sentence"], f["dictated_quote"], f["severity"]) for f in flags] == [
        ("4.1 cm", "Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.", "high")]
    assert flags[0]["edit"] == {"mode": "replace", "find": "Aortic root 4.1 cm.", "replace": "Aortic sinus 4.1 cm."}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests/test_stack_generate_endpoint.py -q`
Expected: `test_quick_flags_a_dictated_value_moved_to_another_structure[True]` FAILS (`flags == []`); `[False]` passes.

- [ ] **Step 3: Implement**

In `backend/src/rapid_reports_ai/hybrid_stack/report.py`:

(a) Replace

```python
from .. import dictated_number_check as dnc
```

with

```python
from .. import dictated_number_check as dnc
from .. import dictated_structure_check as dsc
```

(b) Replace

```python
    if dnc.enabled():   # both paths: a dictated number the report does not hold (spec 2026-10-15), flags only
        gone = set(removed)
        review += dnc.missing_dictated_numbers(
            report, [*(p for p in st.said_parts if p not in gone), *(v + "." for v in _value_statements(req.gate))])
```

with

```python
    # the radiologist's own statements: dictated units and taps minus removed ones, and typed values
    gone = set(removed)
    own = [*(p for p in st.said_parts if p not in gone), *(v + "." for v in _value_statements(req.gate))]
    if dnc.enabled():   # both paths: a dictated number the report does not hold (spec 2026-10-15), flags only
        review += dnc.missing_dictated_numbers(report, own)
    if dsc.enabled():   # both paths: a dictated value written against another structure (spec 2026-10-17), flags only
        review += await dsc.changed_structures(report, own, removed)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests/test_stack_generate_endpoint.py -q`
Expected: all pass (including both existing `RR_DICTATED_NUMBERS` tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/hybrid_stack/report.py backend/tests/test_stack_generate_endpoint.py
git commit -m "feat(stack): run the structure-name check after the number check (RR_DICTATED_STRUCTURES)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

---

### Task 7: Rail test — the card renders with Apply and "You dictated:"

No frontend source change is expected: an action item with an edit is already a card with Apply (`ItemCard.svelte:105-111`) and shows `evidence.dictated_quote` (`ItemCard.svelte:48-50`). This test confirms it. Change `ReviewRail.svelte` or `ItemCard.svelte` only if this test fails, and then only the minimum the failure shows.

**Files:**
- Test: `frontend/src/lib/review/rail/ReviewRail.svelte.test.ts` (insert one `it` inside `describe('ReviewRail', ...)`)

- [ ] **Step 1: Make vitest runnable in this worktree (no install)**

The worktree has no `frontend/node_modules`. Link it; never write under `node_modules` and never run `npm install`. `frontend/.gitignore` already ignores `node_modules`.

```bash
ls -la /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/structure-name/frontend/node_modules 2>/dev/null || \
  ln -s /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/integrate/frontend/node_modules \
        /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/structure-name/frontend/node_modules
```

- [ ] **Step 2: Write the test**

In `frontend/src/lib/review/rail/ReviewRail.svelte.test.ts`, insert directly above the line
`	it('a conflict card with no edit offers Ask in chat and Dismiss, no Apply', async () => {`:

```ts
	it('a moved-value flag (cls action, replace edit) is a card with Apply and the dictated sentence', async () => {
		const label = 'Different site from your dictation? Apply puts your sentence back.';
		const moved = item({
			id: 's1',
			kind: 'dictated_structure_changed',
			cls: 'action',
			lane: 'accuracy',
			section: 'Liver',
			label,
			reason: label,
			anchor: at(80, 'Aortic root 4.1 cm.'),
			evidence: { source: 'post_check', dictated_quote: 'Aortic sinus 4.1 cm.' },
			edit: { mode: 'replace', find: 'Aortic root 4.1 cm.', replace: 'Aortic sinus 4.1 cm.' }
		});
		const { onCommand } = await mount(response({ items: [...ITEMS, moved] }));
		await expect.element(page.getByText(label).first()).toBeInTheDocument();
		const s1 = rail()!.querySelector<HTMLElement>('[data-rv-item="s1"]')!;
		expect(s1.getAttribute('data-rv-variant')).toBe('card');
		expect(s1.querySelector('[data-rv-quote]')?.textContent).toContain('You dictated: “Aortic sinus 4.1 cm.”');
		await page.getByRole('button', { name: `Apply: ${label}` }).click();
		expect(onCommand).toHaveBeenCalledWith('apply', 's1');
	});

```

- [ ] **Step 3: Run the test**

Run (from `frontend/`): `npx vitest run src/lib/review/rail/ReviewRail.svelte.test.ts`
Expected: PASS, all tests in the file (the new one included). This is a confirmation test: it passes without a source change. If it fails, read the failure, make the minimal fix in `ItemCard.svelte`/`ReviewRail.svelte`, and rerun.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/review/rail/ReviewRail.svelte.test.ts
git commit -m "test(rail): a moved-value flag is a card with Apply and the dictated sentence

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WLUGz5KjKhWJ7J2nGWrKit"
```

(Do not `git add` the `node_modules` symlink; it is ignored.)

---

### Task 8: Full verification

- [ ] **Step 1: Full backend suite**

Run (from `backend/`): `PYTHONPATH=src /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend/.venv/bin/python -m pytest tests -q 2>&1 | tail -15`
Expected: all pass except the known unrelated `tests/test_provider_key_routing.py` case. Any other failure: stop and diagnose (most likely a `_sentence` caller affected by Task 1; fix the splitter, not the caller's expectation, unless the new split is the spec's intent).

- [ ] **Step 2: Rail frontend tests**

Run (from `frontend/`): `npx vitest run src/lib/review/rail`
Expected: all pass.

- [ ] **Step 3: Confirm the footprint**

Run: `git diff --stat bc241485..HEAD -- backend/src frontend/src` (`bc241485` is the last spec commit before this plan)
Expected source files only: `template_number_check.py`, `dictated_number_check.py`, `dictated_structure_check.py`, `hybrid_stack/report.py`, `review_engine/live.py`, and the one frontend test file. Nothing in `findings.py`, `gate_model.py`, scratchpad, walkthrough, copilot or writer prompts (spec §5).

No commit in this task. Do not push.

---

## Self-review against the spec

| Spec | Where |
|---|---|
| §2 sources = said_parts minus removed + typed values; unitless skipped | Task 6 (`own`, shared with the number check); Task 2 (`chains` keeps only chains with a unit; test `..._unitless_value_are_not_paired`) |
| §2 FINDINGS only; IMPRESSION/CONCLUSION any case, optional colon | Task 2 `findings_only` + test; Task 3 `test_findings_wrong_and_impression_right_is_still_an_item` |
| §3.1 one pair per chain per FINDINGS sentence; abbreviation-aware splitter; prefix strip; value-only fragment merge; removed dropped; identical merged | Tasks 1–2 |
| §3.2 code pass first | Task 3 `code_pass` + test |
| §3.3 one Jev request, W1 verbatim, noul per pair, P < 0.7, cap 12 in report order, `structure_name_unchecked`, pass-if-any | Task 3 |
| §3.4 item shape, severity high → action, label, chain in the key | Tasks 3–5 |
| §3.5 replace edit + all four guards + side/level exemption | Task 4 |
| §3.6 fail open, 3 s, `structure_name_check_unavailable`, never raises | Task 3 |
| §4 `RR_DICTATED_STRUCTURES` off by default, read per call | Task 3 `enabled` + test; Task 6 |
| §5 footprint; frontend none | Tasks 1–7; Task 8 Step 3 |
| §8 tests | pairing (single, two sentences, chain once, covers): Task 2; code pass, pass-if-any, impression, cap, threshold, fail-open, removed, abbreviation, two items, flag off: Task 3/6; edit offered/withheld (find twice, merged clause, reverse split, extra joiner, merged word, side/level): Task 4; prefixes: Task 2; route with flag on: Task 6; `check_flag_items` edit + quote: Task 5 |

Decisions taken where the spec is silent (flag to the owner at review):
1. A card without an edit gets the label `Different site from your dictation? Check this sentence.` (the spec label promises Apply, which such a card does not have).
2. The merged-word guard compares against every other dictated sentence (other sources and other sentences of the same source), not only other sources as in the lab: the spec says "another dictated statement".
3. `strip_prefix` keeps a label when nothing but the values would remain ("LVEF: 45%."), so the edit never yields "LVEF: LVEF 45%.".
4. A pair beyond the 12-pair cap leaves its chain unjudged: no item for that chain even if another of its pairs was asked and failed.
5. The impression section ends at the next all-caps heading line (e.g. "COMPARISON"), else at the end of the report.
6. `pairs()` takes an optional `removed` argument (the spec's "a dictated sentence equal to a removed sentence is dropped"); the report route also drops removed units before building the sources, as the number check does.
