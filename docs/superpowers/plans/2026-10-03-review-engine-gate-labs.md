# Review engine Gates A–D labs: implementation plan (Plan 1 of the review engine)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the four evidence gates of the review engine spec (§11 Gates A–D) on real production data, so each lane's design is decided by measurement and Hassan's hand read before engine code depends on it.

**Architecture:** One small lab package, `scripts/review_labs/`, holds the shared plumbing: scratchpad output, Metabase, a self-contained HTML labelling page, a lab copy of the flat adjudicator and verifier, the clinical pass, and metrics. Each gate is one CLI module with subcommands (`pull`, `page`, `run`, `score`). Production text lives only under `$RR_LAB_OUT` (the scratchpad). The repo gets code, prompts and synthetic fixtures only. Pure helpers are test-first. Model behaviour is measured by the gate runs, never by unit tests.

**Tech Stack:** Python 3.11, pydantic v2, httpx, pytest (`asyncio_mode=auto`). The Qwen and Jev transport is reused from `scripts/jev_tool_lab/calls.py`, and the scoring helpers from `scripts/jev_tool_lab/score.py`. The labelling pages are plain HTML and JS with localStorage and a "Copy my verdicts" button.

**Spec:** `docs/superpowers/specs/2026-10-02-review-engine-and-rail-design.md` (§6, §7, §8, §11; §15 confirmed 2026-10-03).
**Ledger:** `docs/model-migration/parameter-ledger.md`. Each gate result gets the next free L-number (L-51 onwards).

---

## Binding rules for every task

- **Production text never enters the repo.** Every script writes under `$RR_LAB_OUT/<gate>/`, and `common.lab_out()` refuses a path inside the repo. Repo fixtures are synthetic, seeded from production *structure*.
- **Prod read permission:** Hassan has standing permission to read production content for analysis (memory `feedback_prod_access`). Any subagent prompt that touches production data must say so, and must say "keep it in the scratchpad".
- **Lab method (L-50):**
  - 20-item pilots are directional only; adoption needs at least 100 balanced, category-tagged items.
  - Labelling rules go into the shared prompt *before* labelling.
  - **Smoke-test 2 items on every arm before each live run.**
  - At most 2 runs, with a pid in every output filename (memory `feedback_eval_economy`).
  - Measure latency sequentially when it gates a decision.
- **Hassan's hand read is the gate.** Scripts compute the numbers; Hassan's verdicts decide.
- **Qwen schemas are flat** (no nested objects). List fields decode JSON-encoded strings. A validation failure becomes a logged `minor`/no-fix row, never a retry at temperature 0.
- **Prompts are case-agnostic:** structural examples only, never single-domain clinical ones.
- **Do not build `review_engine/` here.** Two Gate B1 steps need Plan 2's `alignment.py` and `checks.py`; they are marked **[after Plan 2 Task N]**, and everything else runs now.

**Shell setup used by every command below:**
```bash
cd /Users/hassan/Code/rapid_reports_ai/backend
export RR_LAB_OUT=/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/<session>/scratchpad/review_labs
export RR_PIPELINE_SCRATCH=/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/9e672c4e-4eef-41cc-a40f-806516ac58ef/scratchpad
```
`RR_PIPELINE_SCRATCH` is the pipeline session's scratchpad. It holds `review_cards50_v3.json`, `audit_compare/compare.json`, `jev_v2_rescore/prod_quick_150.json` and `cards50/prompt_v3.txt`. The second blind peer read (2026-10-03) is in *this* session's scratchpad at `gateA/blind_A.json` and `gateA/blind_B.json`. Copy both into `$RR_LAB_OUT/gate_a/` before Task A1.

## Execution and parallelism

**The critical path is Hassan's labelling, not code.** So the waves are ordered to put each labelling page in front of him as early as possible, and every model run happens while he labels.

| Wave | Runs in parallel (one subagent per lane) | Hassan |
|---|---|---|
| **0** | One subagent: Tasks 0.1 → 0.2, then 0.3, 0.4 and 0.5 (these three in parallel once 0.1 lands; each has its own module) | n/a |
| **1** | A1 (label page) · B0 (cases + 2 blind readers → gold page) · D1 (pull + reconstruct) · C1 (mapper) | Starts labelling: Gate A 27 cards first, then the D edits page as soon as D2 Step 2 builds it |
| **2** | A2 (smoke → 2 runs) · B1a (clinical pass, smoke → 41) · C2 (pull, gate, adjudicate) · C3 (s1 arms) · D2 Steps 1–3 (page, smoke → re-score) · B2 Step 5 (build the unsupported half + stated readers) | Gate B gold page, then the B2 confirmation page |
| **3** | A3 (read page) · B2 Steps 6–7 (runs, bands, escalation) · C4 (page) | Gate A read page, then the Gate C cards page |
| **4** | Scoring + ledger per gate (A4, B2 Step 8, C4 Steps 5–6, D2 Steps 4–5), each as soon as its labels arrive | Confirms the Gate D option per edit type |
| **after Plan 2 Tasks 2–3** | B1c | alignment page |

**Subagent rules** (subagent-driven development):
- **One task per subagent,** with the full task text pasted in. Don't make it read the plan.
- **Shared test file:** Part 0 tasks append to `tests/test_review_labs.py` sequentially. Gate subagents running in parallel write their tests to their own file, `tests/test_review_labs_gate_<a|b|c|d>.py` (same imports), and run that file instead, so parallel edits never collide.
- **Each gate module is owned by one subagent at a time.** Parallel lanes never edit the same file. Tasks within a gate that touch the same module run in sequence.
- **Live model runs are executed by the controller,** or by a subagent told to stop after the smoke test and report. Each 2-item smoke test is checked before the full run is released, so a structured-output failure is caught before it costs a full run.
- **Every subagent touching production data** is told: "Hassan has standing permission to read production content for analysis; keep everything under $RR_LAB_OUT, never in the repo."
- **Review after each wave:** one `superpowers:code-reviewer` pass over that wave's commits (spec compliance + tests) before the next wave builds on it. Pure-lab scripts get a light review. Shared modules (Part 0) get a full one.
- **Readers and labelling:** blind-reader subagents (B0, B2 stated set) run in parallel, split by case index. Their outputs are proposals; Hassan's page verdicts are the labels.

## File structure

| File | Responsibility |
|---|---|
| `backend/src/rapid_reports_ai/scripts/review_labs/__init__.py` | package marker |
| `.../review_labs/common.py` | env, scratchpad paths, Metabase, JSON-list decoding, sentence helpers, case loading |
| `.../review_labs/label_page.py` | `build_page()`: one self-contained HTML labelling page used by every gate |
| `.../review_labs/judgement.py` | lab copy of the flat `Judgement`, candidate rendering, `adjudicate()`, `apply_edit()`, code guards, `verify()` |
| `.../review_labs/clinical_pass.py` | the one clinical pass (characterise, safety, urgency, inconsistencies) |
| `.../review_labs/metrics.py` | gate metrics: Gate A bar, binary recall/false alarm, band error location |
| `.../review_labs/additions_map.py` | S4 synthesis card → Additions candidates; criteria-by-system index |
| `.../review_labs/prompts/adjudicator_v4.txt` | the adjudicator v4 prompt |
| `.../review_labs/prompts/clinical_pass_v1.txt` | the clinical pass prompt |
| `.../review_labs/gate_a.py` | Gate A: label page, v4 runs, read page, score |
| `.../review_labs/gate_b.py` | Gate B: pull, fabrication gold page, B2 set and runs, B1 scoring (part after Plan 2) |
| `.../review_labs/gate_c.py` | Gate C: pull synthesis, map, "already in report" gate, adjudicate (± criteria), s1 grade arm, clinical pass, page, score |
| `.../review_labs/gate_d.py` | Gate D: pull automatic edits, reconstruct, page, re-score, decide |
| `backend/tests/test_review_labs.py` | unit tests for every pure helper |
| `backend/test_cases/review_labs/gate_a_synthetic.json` | synthetic balance cases for Gate A (used only if Hassan's labels hold fewer than 10 `action`) |

---

## Part 0: shared plumbing

### Task 0.1: `common.py`

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/__init__.py` (empty)
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/common.py`
- Test: `backend/tests/test_review_labs.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_review_labs.py
"""Unit tests for the review-engine gate labs (plan 2026-10-03-review-engine-gate-labs)."""
import os

import pytest

from rapid_reports_ai.scripts.review_labs import common


def test_decode_json_list_passes_lists_through():
    assert common.decode_json_list(["a", "b"]) == ["a", "b"]


def test_decode_json_list_decodes_string_encoded_list():
    assert common.decode_json_list('["a", "b"]') == ["a", "b"]


def test_decode_json_list_wraps_plain_string_and_drops_blank():
    assert common.decode_json_list("one item") == ["one item"]
    assert common.decode_json_list("  ") == []
    assert common.decode_json_list(None) == []


def test_lab_out_refuses_repo_paths(monkeypatch):
    monkeypatch.setenv("RR_LAB_OUT", str(common.REPO / "backend" / "tmp_lab"))
    with pytest.raises(SystemExit):
        common.lab_out("gate_a")


def test_lab_out_creates_gate_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("RR_LAB_OUT", str(tmp_path))
    p = common.lab_out("gate_a")
    assert p == tmp_path / "gate_a" and p.is_dir()


def test_out_file_has_pid(monkeypatch, tmp_path):
    monkeypatch.setenv("RR_LAB_OUT", str(tmp_path))
    p = common.out_file("gate_a", "run1", "jsonl")
    assert p.name.startswith("run1_") and p.suffix == ".jsonl" and str(os.getpid()) in p.name


def test_sentences_and_best_sentence():
    text = "FINDINGS:\nThe liver is normal. A 5 mm cyst is in the left kidney.\nIMPRESSION:\nNo acute finding."
    spans = common.sentences(text)
    assert any(text[a:b].strip() == "A 5 mm cyst is in the left kidney." for a, b in spans)
    a, b = common.best_sentence(text, "left kidney cyst 5 mm")
    assert "left kidney" in text[a:b]


def test_section_of_reads_nearest_heading():
    text = "FINDINGS:\nA.\nIMPRESSION:\nB."
    assert common.section_of(text, text.index("B.")) == "Impression"
    assert common.section_of(text, text.index("A.")) == "Findings"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q`
Expected: FAIL with `ModuleNotFoundError: ... review_labs`.

- [ ] **Step 3: Write `common.py`**

```python
# backend/src/rapid_reports_ai/scripts/review_labs/common.py
"""Shared plumbing for the review-engine gate labs (spec 2026-10-02 §11).

Production text is written only under $RR_LAB_OUT (a scratchpad), never inside the repo."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[4]
REPO = BACKEND.parent


def load_env() -> None:
    load_dotenv(BACKEND / ".env")


def lab_out(gate: str) -> Path:
    root = os.environ.get("RR_LAB_OUT")
    if not root:
        raise SystemExit("set RR_LAB_OUT to a scratchpad directory; production text never goes in the repo")
    p = (Path(root) / gate).resolve()
    if p == REPO or REPO in p.parents:
        raise SystemExit(f"RR_LAB_OUT must be outside the repo: {p}")
    p.mkdir(parents=True, exist_ok=True)
    return p


def out_file(gate: str, stem: str, ext: str = "json") -> Path:
    return lab_out(gate) / f"{stem}_{os.getpid()}.{ext}"


def pipeline_scratch() -> Path:
    p = os.environ.get("RR_PIPELINE_SCRATCH")
    if not p:
        raise SystemExit("set RR_PIPELINE_SCRATCH to the pipeline session's scratchpad")
    return Path(p)


def read_json(p: Path | str) -> Any:
    return json.loads(Path(p).read_text())


def write_json(p: Path | str, obj: Any) -> Path:
    Path(p).write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    return Path(p)


def read_jsonl(p: Path | str) -> List[dict]:
    return [json.loads(line) for line in Path(p).read_text().splitlines() if line.strip()]


def metabase(sql: str, timeout: float = 120) -> List[Dict[str, Any]]:
    """Read-only SQL against production through Metabase (database 2)."""
    load_env()
    r = httpx.post(os.environ["METABASE_URL"].rstrip("/") + "/api/dataset",
                   headers={"x-api-key": os.environ["METABASE_API_KEY"], "User-Agent": "curl/8",
                            "Content-Type": "application/json"},
                   json={"database": 2, "type": "native", "native": {"query": sql}}, timeout=timeout)
    r.raise_for_status()
    d = r.json()
    if d.get("error"):
        raise RuntimeError(d["error"])
    cols = [c["name"] for c in d["data"]["cols"]]
    return [dict(zip(cols, row)) for row in d["data"]["rows"]]


def decode_json_list(v: Any) -> List[Any]:
    """Qwen string-encodes list fields (L-50): accept a list, a JSON-encoded list, or one plain string."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    s = str(v).strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            out = json.loads(s)
            if isinstance(out, list):
                return out
        except json.JSONDecodeError:
            pass
    return [s]


SENT_END = re.compile(r"(?<=[.;])\s+(?=[A-Z])|\n+")
_HEADING = re.compile(r"^([A-Z][A-Z /&()-]{2,}):\s*$", re.M)


def sentences(text: str) -> List[Tuple[int, int]]:
    out, s = [], 0
    for m in SENT_END.finditer(text):
        out.append((s, m.start()))
        s = m.end()
    out.append((s, len(text)))
    return [(a, b) for a, b in out if text[a:b].strip() and not _HEADING.fullmatch(text[a:b].strip())]


def best_sentence(text: str, query: str) -> Tuple[int, int]:
    q = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
    best, score = (0, 0), -1.0
    for a, b in sentences(text):
        w = set(re.findall(r"[a-z0-9]+", text[a:b].lower()))
        sc = len(q & w) / (len(w) ** 0.5 + 1)
        if sc > score:
            best, score = (a, b), sc
    return best


def section_of(report: str, pos: int) -> str:
    hs = [m.group(1) for m in _HEADING.finditer(report) if m.start() <= pos]
    return hs[-1].title() if hs else "Report"


def prod_cases() -> Dict[str, dict]:
    """id8 → {id, scan, dictation, history, report} for the 150 quick reports the pipeline session pulled."""
    rows = read_json(pipeline_scratch() / "jev_v2_rescore" / "prod_quick_150.json")
    out = {}
    for r in rows:
        v = (r.get("input_data") or {}).get("variables") or {}
        out[r["id"][:8]] = {"id": r["id"], "scan": v.get("SCAN_TYPE") or "", "dictation": v.get("FINDINGS") or "",
                            "history": v.get("CLINICAL_HISTORY") or "", "report": r.get("report_content") or ""}
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/__init__.py src/rapid_reports_ai/scripts/review_labs/common.py tests/test_review_labs.py
git commit -m "feat(review-labs): shared lab plumbing (scratchpad guard, Metabase, JSON-list decode, sentences)"
```

### Task 0.2: `label_page.py`, the shared HTML labelling page

The page is self-contained (data embedded, no fetch), so it opens straight from the scratchpad with `open <file>`. Verdicts autosave to localStorage. "Copy my verdicts" copies them as JSON, falling back to a visible textarea. Hidden blocks (the peer read, the engine's call) appear only once every required field on that card is answered, so they can't anchor the label.

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/label_page.py`
- Test: `backend/tests/test_review_labs.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
from rapid_reports_ai.scripts.review_labs import label_page

CARD = {"id": "c2", "title": "Card 2", "meta": "CT · partial",
        "blocks": [{"label": "Dictated line", "text": "A </script> tag"},
                   {"label": "Report", "text": "Full report", "highlight": ["Full"], "collapsed": True}],
        "hidden": [{"label": "Peer read", "text": "action: absent"}]}
FIELDS = [{"key": "verdict", "type": "choice", "options": ["action", "minor", "info", "suppress"], "required": True},
          {"key": "material", "type": "check", "label": "Material loss"},
          {"key": "note", "type": "text"}]


def test_build_page_embeds_data_safely():
    html = label_page.build_page("Gate A labels", "gateA-v1", [CARD], FIELDS)
    assert html.startswith("<!doctype html>")
    assert "<title>Gate A labels</title>" in html
    assert "A </script> tag" not in html          # raw closing tag would break the data block
    assert "A <\\/script> tag" in html
    assert '"storage_key": "gateA-v1"' in html


def test_build_page_has_copy_button_and_hidden_gate():
    html = label_page.build_page("t", "k", [CARD], FIELDS)
    assert 'id="copy"' in html and "Copy my verdicts" in html
    assert "function decided(" in html


def test_build_page_rejects_duplicate_ids():
    with pytest.raises(ValueError):
        label_page.build_page("t", "k", [CARD, CARD], FIELDS)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q -k build_page`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write `label_page.py`**

```python
# backend/src/rapid_reports_ai/scripts/review_labs/label_page.py
"""One self-contained HTML labelling page for every gate. Data is embedded; verdicts live in localStorage
and leave through "Copy my verdicts". Hidden blocks show only after the card's required fields are set."""
from __future__ import annotations

import html as _html
import json
from pathlib import Path
from typing import List

_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--card:#fff;--line:#e4e2dc;--accent:#2f5d8a;--mark:#ffe89a;--on:#2f5d8a;--onfg:#fff}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161615;--fg:#ecebe6;--muted:#a3a29c;--card:#1f1f1d;--line:#34332f;--accent:#8db4dc;--mark:#5c4d12;--on:#8db4dc;--onfg:#111}}
:root[data-theme="dark"]{--bg:#161615;--fg:#ecebe6;--muted:#a3a29c;--card:#1f1f1d;--line:#34332f;--accent:#8db4dc;--mark:#5c4d12;--on:#8db4dc;--onfg:#111}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
h1{font-size:17px;margin:0;flex:1 1 auto}main{max-width:980px;margin:0 auto;padding:12px 16px 80px}
section.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px;margin:12px 0}
section.card.done{border-left:4px solid var(--accent)}.meta{color:var(--muted);font-size:13px}
.block{margin:8px 0}.block b{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
pre{white-space:pre-wrap;word-wrap:break-word;font:14px/1.45 ui-monospace,Menlo,monospace;margin:4px 0;background:transparent}
mark{background:var(--mark);color:inherit}button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:6px;padding:5px 10px;cursor:pointer;margin:2px}
button[aria-pressed="true"]{background:var(--on);color:var(--onfg);border-color:var(--on)}textarea{width:100%;min-height:54px;font:inherit;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px}
.fields{border-top:1px dashed var(--line);margin-top:10px;padding-top:8px}.hidden{opacity:.95;border-left:3px solid var(--muted);padding-left:8px}
#out{position:fixed;bottom:0;left:0;right:0;height:30vh}
</style></head><body>
<header><h1>__TITLE__</h1><span id="progress" class="meta"></span>
<label class="meta"><input type="checkbox" id="todo"> Unlabelled only</label>
<button id="copy">Copy my verdicts</button></header>
<main id="cards"></main><textarea id="out" readonly hidden></textarea>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
let S = {}; try { S = JSON.parse(localStorage.getItem(D.storage_key) || '{}'); } catch (e) {}
const esc = t => String(t ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function marked(text, hl) { let h = esc(text); for (const m of (hl || [])) { if (!m) continue; const e = esc(m); h = h.split(e).join('<mark>' + e + '</mark>'); } return h; }
function decided(id) { const v = S[id] || {}; return D.fields.filter(f => f.required).every(f => v[f.key] !== undefined && v[f.key] !== ''); }
function save() { try { localStorage.setItem(D.storage_key, JSON.stringify(S)); } catch (e) {} progress(); }
function progress() { const n = D.cards.filter(c => decided(c.id)).length; document.getElementById('progress').textContent = n + ' / ' + D.cards.length + ' labelled'; }
function setv(id, key, val) { S[id] = S[id] || {}; S[id][key] = val; S[id].at = new Date().toISOString(); save(); render(); }
function blockHtml(b) { const body = '<pre>' + marked(b.text, b.highlight) + '</pre>';
  return '<div class="block"><b>' + esc(b.label) + '</b>' + (b.collapsed ? '<details><summary>show</summary>' + body + '</details>' : body) + '</div>'; }
function fieldHtml(c, f) { const v = (S[c.id] || {})[f.key];
  if (f.type === 'choice') return '<div><span class="meta">' + esc(f.label || f.key) + ': </span>' + f.options.map(o =>
    '<button aria-pressed="' + (v === o) + '" data-id="' + esc(c.id) + '" data-k="' + esc(f.key) + '" data-v="' + esc(o) + '">' + esc(o) + '</button>').join('') + '</div>';
  if (f.type === 'check') return '<label><input type="checkbox" data-id="' + esc(c.id) + '" data-k="' + esc(f.key) + '"' + (v ? ' checked' : '') + '> ' + esc(f.label || f.key) + '</label>';
  return '<div><span class="meta">' + esc(f.label || f.key) + '</span><textarea data-id="' + esc(c.id) + '" data-k="' + esc(f.key) + '">' + esc(v || '') + '</textarea></div>'; }
function render() { const todo = document.getElementById('todo').checked; const m = document.getElementById('cards');
  m.innerHTML = D.cards.filter(c => !todo || !decided(c.id)).map(c => '<section class="card' + (decided(c.id) ? ' done' : '') + '" id="card-' + esc(c.id) + '">' +
    '<div><strong>' + esc(c.title) + '</strong> <span class="meta">' + esc(c.meta || '') + '</span></div>' + c.blocks.map(blockHtml).join('') +
    '<div class="fields">' + D.fields.map(f => fieldHtml(c, f)).join('') + '</div>' +
    (decided(c.id) && (c.hidden || []).length ? '<div class="hidden">' + c.hidden.map(blockHtml).join('') + '</div>' : '') + '</section>').join('');
  progress(); }
document.addEventListener('click', e => { const b = e.target.closest('button[data-k]'); if (b) setv(b.dataset.id, b.dataset.k, b.dataset.v); });
document.addEventListener('change', e => { const t = e.target; if (!t.dataset || !t.dataset.k) return;
  if (t.type === 'checkbox') { if (t.id !== 'todo') setv(t.dataset.id, t.dataset.k, t.checked); } else setv(t.dataset.id, t.dataset.k, t.value); });
document.getElementById('todo').addEventListener('change', render);
document.getElementById('copy').addEventListener('click', () => { const json = JSON.stringify(S, null, 1); const out = document.getElementById('out');
  (navigator.clipboard ? navigator.clipboard.writeText(json) : Promise.reject()).then(() => { document.getElementById('copy').textContent = 'Copied ✓'; },
    () => { out.hidden = false; out.value = json; out.select(); }); });
render();
</script></body></html>
"""


def build_page(title: str, storage_key: str, cards: List[dict], fields: List[dict]) -> str:
    ids = [c["id"] for c in cards]
    if len(ids) != len(set(ids)):
        raise ValueError("card ids must be unique")
    data = json.dumps({"storage_key": storage_key, "cards": cards, "fields": fields}, ensure_ascii=False)
    data = data.replace("</", "<\\/")
    return _TEMPLATE.replace("__TITLE__", _html.escape(title)).replace("__DATA__", data)


def write_page(path: Path, title: str, storage_key: str, cards: List[dict], fields: List[dict]) -> Path:
    path.write_text(build_page(title, storage_key, cards, fields))
    return path
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/label_page.py tests/test_review_labs.py
git commit -m "feat(review-labs): self-contained HTML labelling page with hidden peer read and copy-verdicts"
```

### Task 0.3: `judgement.py`, the lab adjudicator and verifier

This is a lab copy of spec §7–§8, so the gates can run before Plan 2. Plan 2 ports the winning prompt and the guards into `review_engine/` test-first.

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/judgement.py`
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/prompts/adjudicator_v4.txt`
- Test: `backend/tests/test_review_labs.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
from rapid_reports_ai.scripts.review_labs import judgement as J

REPORT = "FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst."


def J_(**kw):
    base = dict(cls="action", kind="partial", label="l", reason="r", edit_mode="none",
                edit_find=None, edit_replace=None, edit_after=None, edit_section=None, probe=None)
    base.update(kw)
    return J.Judgement(**base)


def test_judgement_is_flat():
    for name, f in J.Judgement.model_fields.items():
        assert f.annotation not in (dict, list), name


def test_apply_replace_and_remove_and_insert():
    j = J_(edit_mode="replace", edit_find="a cyst", edit_replace="a 12 mm cyst")
    assert "a 12 mm cyst in the left kidney" in J.apply_edit(REPORT, j)
    j = J_(edit_mode="remove", edit_find="The liver is normal. ")
    assert "liver" not in J.apply_edit(REPORT, j)
    j = J_(edit_mode="insert", edit_after="The liver is normal.", edit_replace="The spleen is normal.")
    assert "The liver is normal. The spleen is normal. There is a cyst" in J.apply_edit(REPORT, j)


def test_apply_returns_none_when_find_not_unique_or_absent():
    rep = "The liver is normal. The spleen is normal."
    assert J.apply_edit(rep, J_(edit_mode="replace", edit_find="normal", edit_replace="x")) is None
    assert J.apply_edit(REPORT, J_(edit_mode="replace", edit_find="pancreas", edit_replace="x")) is None


def test_guards_grounding_numbers_and_side():
    j = J_(edit_mode="replace", edit_find="a cyst", edit_replace="a 12 mm cyst")
    assert "ungrounded_number" in J.guard_failures(REPORT, j, dictation="cyst left kidney", history="")
    assert J.guard_failures(REPORT, j, dictation="12 mm cyst left kidney", history="") == []
    j = J_(edit_mode="replace", edit_find="a cyst in the left kidney", edit_replace="a cyst in the right kidney")
    assert "ungrounded_side" in J.guard_failures(REPORT, j, dictation="cyst left kidney", history="")


def test_guards_negation_drop():
    rep = "FINDINGS:\nNo free fluid. The liver is normal."
    j = J_(edit_mode="replace", edit_find="No free fluid.", edit_replace="Free fluid.")
    assert "drops_negation" in J.guard_failures(rep, j, dictation="free fluid", history="")


def test_guards_remove_only_for_contradicted():
    j = J_(kind="partial", edit_mode="remove", edit_find="The liver is normal.")
    assert "remove_not_allowed" in J.guard_failures(REPORT, j, dictation="", history="")
    j = J_(kind="contradicted", edit_mode="remove", edit_find="The liver is normal.")
    assert "remove_not_allowed" not in J.guard_failures(REPORT, j, dictation="", history="")


def test_render_candidate_marks_unsure_without_leaning():
    c = {"lane": "coverage", "kind": "partial", "detector": "jev.classify_first", "line": "Cyst left kidney",
         "evidence": {"jev_unsure": {"question": "classify_first", "band": "0.4-0.6"}, "missing_detail": "12 mm"}}
    s = J.render_candidate(c)
    assert "unsure" in s and "classify_first" in s and "0.4" not in s and "12 mm" in s
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q -k "judgement or apply or guards or render_candidate"`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write the prompt `prompts/adjudicator_v4.txt`**

The v3 prompt (`$RR_PIPELINE_SCRATCH/cards50/prompt_v3.txt`) is the starting text. v4 removes "when in doubt suppress", adds the `minor` tier ("uncertain → minor"), the additions and grade labelling rules (L-50), the smallest-fix rule and the probe rule:

```text
You review one group of automated flags on a radiology report. Detectors compared the radiologist's dictation (and, for some flags, the clinical history or a guideline synthesis) with the report generated from it. Detectors over-flag. Read the case, decide what the radiologist should see, and write the smallest fix.

How the report relates to the dictation:
- The dictation is the source of truth for content. The report may reword, reorder, regroup by section or by side, merge, compact, add standard normal statements and sensible recommendations, and quietly correct obvious speech-recognition slips. None of that is an error.
- It is an error when dictated content is missing or stated with a changed meaning: a finding, a descriptor (size, number, character, location, extent, severity, certainty, a named variant, including a normal variant), a value or a side. The scope of the study never justifies dropping dictated content.
- It is also an error when the report states something the dictation and history do not support: an invented finding, measurement or prior study, or more certainty than was dictated.
- The clinical history is context only. The report never restates it.

Read before deciding. Work out, in order:
1. What the flagged words refer to: the structure, the side, and whether they describe the organ itself or a lesion, finding or part within it. Use the neighbouring sentences, not only the flagged words.
2. Where the report covers that structure. A statement applies to what its heading, subheading or sentence names. A summary such as "remaining", "otherwise" or "no other" that follows the description of the abnormal parts covers the rest, not those parts. Search the whole report, not only the nearest sentence.
3. Whether the dictated wording could be a slip: a word that makes no clinical sense in its context, a word that reverses an otherwise normal description in the same sentence, or a side or number that the rest of the dictation contradicts.

Classes:
- action: a real problem that the radiologist should fix, and you are confident.
- minor: a real but low-impact difference, or you are unsure whether it matters. Uncertain means minor, not suppress. Write the fix anyway.
- info: the dictated wording is a slip and the report states the coherent version. Use kind "slip" and no edit.
- suppress: clearly noise. The content is present in other words or elsewhere, the difference has no interpretive or management effect, or the flag misreads the structure.
A missing side is a problem only when nothing bounds it (study title, heading, subheading or the sentence itself). A sensible recommendation the radiologist did not dictate is never a problem. A dictated negative is never inserted.

Guideline-derived flags (kinds grade, characterise, threshold, follow_up, option):
- Assign a grade or apply a threshold only from features that are stated. An input counts only if it is stated, read by its standard meaning; a criterion counts as described when its ordinarily dictated features are covered. Judge the core category only; ignore modifiers and eligibility unless they change the category.
- When a criteria text is supplied, use it as the definition of the system.
- If the classification can be assigned from what is stated, use kind "grade". If an input it needs is not described, use kind "characterise", name what is missing in the label, and use class minor at most.
- Radiology remit only: no management beyond imaging. The impression carries one recommendation line. Improve the existing line (edit_mode "upgrade"); never add a second recommendation line.

The fix, the smallest that works:
- replace or upgrade: edit_find is an exact span copied from the report that occurs once, as short as possible; edit_replace is its corrected text.
- remove: edit_find is the exact span to delete. Use remove only for a report statement that the dictation contradicts.
- insert: edit_after is an exact sentence copied from the report; edit_replace is the new sentence to place after it.
- none: no change is right.
- Never rewrite a whole sentence when part of it is already stated. Add only what the dictation, history or supplied guideline text states, in the report's own wording and style. Never copy a slip from the dictation.
- edit_section is the report heading the edit sits under.

The probe is one statement that becomes true once the problem is fixed. It says whether the topic is covered, scoped to its section, in general terms, never the wording of your edit. Form: "The <SECTION> section states <the topic> for <the structure>."

Fields: cls; kind (keep the flag's kind unless your reading refines it, for example differs to slip); label (at most 80 characters, what the radiologist sees in the list); reason (one sentence); edit_mode; edit_find; edit_replace; edit_after; edit_section; probe. Leave the edit fields empty when edit_mode is none, and leave probe empty for suppress.
```

- [ ] **Step 4: Write `judgement.py`**

```python
# backend/src/rapid_reports_ai/scripts/review_labs/judgement.py
"""Lab copy of the review-engine adjudicator (spec §7) and verifier (spec §8).

Flat schema on purpose (L-50). One Qwen call per candidate group. The verifier checks the FIX, never the reading."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel

from rapid_reports_ai.report_reconcile import Q_CONVEYS
from rapid_reports_ai.report_review import CONTRA_FLAG, Q_CONTRA
from rapid_reports_ai.scripts.jev_tool_lab import calls

PROMPTS = Path(__file__).parent / "prompts"
ADDRESSED_OK = 0.8          # spec §8; confirmed or re-set in Gate E
UNSURE_LO = 0.5             # §6.5: 0.5–0.8 = unsure → "unconfirmed"


class Judgement(BaseModel):
    cls: Literal["action", "minor", "info", "suppress"]
    kind: str
    label: str
    reason: str
    edit_mode: Literal["none", "replace", "insert", "upgrade", "remove"]
    edit_find: Optional[str] = None
    edit_replace: Optional[str] = None
    edit_after: Optional[str] = None
    edit_section: Optional[str] = None
    probe: Optional[str] = None


def prompt(name: str = "adjudicator_v4") -> str:
    return (PROMPTS / f"{name}.txt").read_text().strip()


_KIND_TEXT = {
    "partial": "The report seems to cover this dictated line but leave out part of it.",
    "absent": "The report seems not to cover this dictated line at all.",
    "differs": "The report seems to say something different from this dictated line.",
    "laterality": "A side in this dictated line seems missing from the report.",
    "contradicted": "The dictation seems to contradict this report statement.",
    "unsupported": "This report statement seems not to be supported by the dictation or history.",
    "overstated": "This report statement seems more certain than the dictation.",
    "misattributed": "A measurement seems attached to a different structure than dictated.",
    "inconsistent": "This report statement seems internally inconsistent (modality wording or size word).",
    "grade": "A guideline classification may be assignable for this finding.",
    "characterise": "A guideline classification may need an input that is not described.",
    "threshold": "A guideline threshold may apply to this finding.",
    "follow_up": "The guideline may change the existing recommendation.",
    "option": "A guideline point the radiologist may want to add.",
}


def render_candidate(c: dict) -> str:
    """One candidate as prompt text. An unsure Jev answer is named, never its leaning (§6.5)."""
    lines = [f"- [{c.get('lane')}/{c.get('kind')}, detector {c.get('detector')}] {_KIND_TEXT.get(c.get('kind'), '')}"]
    if c.get("line"):
        lines.append(f'  Dictated line: "{c["line"]}"')
    if c.get("anchor"):
        lines.append(f'  Report statement: "{c["anchor"]}"')
    ev = c.get("evidence") or {}
    if ev.get("jev_unsure"):
        lines.append(f"  The detector question {ev['jev_unsure'].get('question')} was unsure here; read it fresh.")
    if ev.get("missing_detail"):
        lines.append(f"  Possibly missing detail: {ev['missing_detail']}")
    for k in ("system", "grade", "parameter", "threshold", "significance", "modality", "timing", "indication", "text"):
        if ev.get(k):
            lines.append(f"  {k}: {ev[k]}")
    if ev.get("criteria"):
        lines.append(f"  Criteria text for this system: {ev['criteria']}")
    return "\n".join(lines)


def user_message(case: dict, group: List[dict]) -> str:
    return ("FLAGS (one group, same place in the report):\n" + "\n".join(render_candidate(c) for c in group) +
            f"\n\nSTUDY TITLE: {case.get('scan', '')}\n\nCLINICAL HISTORY:\n{case.get('history') or '(none)'}"
            f"\n\nDICTATION:\n{case.get('dictation', '')}\n\nREPORT:\n{case.get('report', '')}")


async def adjudicate(case: dict, group: List[dict], system: Optional[str] = None,
                     qwen_fn=calls.qwen) -> Tuple[Optional[Judgement], dict, Optional[str]]:
    """One Qwen reasoning call. A validation failure returns (None, usage, error); the caller logs it as minor/no fix."""
    try:
        out, usage = await qwen_fn(Judgement, system or prompt(), user_message(case, group), True)
        return out, usage.model_dump(), None
    except Exception as e:   # noqa: BLE001 — lab: record and move on (retries at T=0 are futile, L-50)
        return None, {}, f"{type(e).__name__}: {str(e)[:300]}"


def _once(text: str, needle: Optional[str]) -> bool:
    return bool(needle) and text.count(needle) == 1


def apply_edit(report: str, j: Judgement) -> Optional[str]:
    m = j.edit_mode
    if m in ("replace", "upgrade") and _once(report, j.edit_find) and j.edit_replace is not None:
        return report.replace(j.edit_find, j.edit_replace, 1)
    if m == "remove" and _once(report, j.edit_find):
        return re.sub(r"[ \t]{2,}", " ", report.replace(j.edit_find, "", 1))
    if m == "insert" and _once(report, j.edit_after) and j.edit_replace:
        i = report.index(j.edit_after) + len(j.edit_after)
        return report[:i] + " " + j.edit_replace.strip() + report[i:]
    return None


_NUM = re.compile(r"\d+(?:\.\d+)?")
_SIDE = re.compile(r"\b(left|right|bilateral)\b", re.I)
_NEG = re.compile(r"\b(no|not|without|absent|negative for)\b", re.I)


def guard_failures(report: str, j: Judgement, dictation: str, history: str) -> List[str]:
    """Spec §8 code guards. An empty list means the fix may be shown with Apply."""
    if j.edit_mode == "none":
        return []
    fails = []
    if apply_edit(report, j) is None:
        fails.append("anchor_not_unique")
    source = f"{dictation}\n{history}"
    new, old = j.edit_replace or "", j.edit_find or ""
    if set(_NUM.findall(new)) - set(_NUM.findall(old)) - set(_NUM.findall(source)):
        fails.append("ungrounded_number")
    added_sides = {s.lower() for s in _SIDE.findall(new)} - {s.lower() for s in _SIDE.findall(old)}
    if added_sides - {s.lower() for s in _SIDE.findall(source)}:
        fails.append("ungrounded_side")
    if j.edit_mode in ("replace", "upgrade") and len(_NEG.findall(old)) > len(_NEG.findall(new)):
        fails.append("drops_negation")
    if j.edit_mode == "remove" and j.kind != "contradicted":
        fails.append("remove_not_allowed")
    return fails


def changed_sentence(after: str, j: Judgement) -> str:
    key = (j.edit_replace or "").strip() or (j.edit_after or "")
    for s in re.split(r"(?<=[.;])\s+|\n+", after):
        if key and key[:40] in s:
            return s.strip()
    return key


async def verify(case: dict, j: Judgement, jev_fn=calls.jev) -> Dict:
    """Code guards, then one batched Jev call: the probe on the edited report, contradiction on the changed text."""
    fails = guard_failures(case["report"], j, case.get("dictation", ""), case.get("history", ""))
    res = {"code": not fails, "failed": fails, "addressed": None, "contra": None, "unconfirmed": False}
    if fails or j.edit_mode == "none":
        return res
    after = apply_edit(case["report"], j)
    by_state = {f"SCAN TYPE: {case.get('scan', '')}\nDICTATED FINDINGS:\n{case.get('dictation', '')}":
                    {"contra": {"type": "noul", "instructions": Q_CONTRA + changed_sentence(after, j)}}}
    if j.probe:
        by_state[f"REPORT:\n{after}"] = {"addressed": {"type": "noul", "instructions": j.probe}}
    try:
        answers, _, _ = await jev_fn(by_state)
        res["contra"] = float(answers["contra"]["noul"])
        if j.probe:
            res["addressed"] = float(answers["addressed"]["noul"])
            res["unconfirmed"] = UNSURE_LO <= res["addressed"] < ADDRESSED_OK
    except Exception as e:   # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    if res["contra"] is not None and res["contra"] >= CONTRA_FLAG:
        res["code"] = False
        res["failed"].append("fix_contradicts_dictation")
    return res


async def judge_and_verify(case: dict, group: List[dict], sem: asyncio.Semaphore, system: Optional[str] = None) -> dict:
    async with sem:
        j, usage, err = await adjudicate(case, group, system)
    if j is None:
        return {"cls": "minor", "kind": group[0].get("kind"), "label": "", "edit_mode": "none", "error": err,
                "usage": usage, "verified": None}
    v = await verify(case, j)
    return {**j.model_dump(), "usage": usage, "verified": v, "error": None}


__all__ = ["Judgement", "prompt", "render_candidate", "user_message", "adjudicate", "apply_edit",
           "guard_failures", "verify", "judge_and_verify", "Q_CONVEYS"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/judgement.py src/rapid_reports_ai/scripts/review_labs/prompts/adjudicator_v4.txt tests/test_review_labs.py
git commit -m "feat(review-labs): lab adjudicator v4 (flat Judgement, minor tier) and verifier guards"
```

### Task 0.4: `metrics.py`

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/metrics.py`
- Test: `backend/tests/test_review_labs.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
from rapid_reports_ai.scripts.review_labs import metrics as M


def test_gate_a_metrics():
    labels = {"a": {"verdict": "action", "material": True}, "b": {"verdict": "action"},
              "c": {"verdict": "suppress"}, "d": {"verdict": "minor"}}
    run1 = {"a": "action", "b": "minor", "c": "action", "d": "minor"}
    run2 = {"a": "action", "b": "suppress", "c": "action", "d": "minor"}
    report_of = {"a": "r1", "b": "r1", "c": "r2", "d": "r2"}
    m = M.gate_a([run1, run2], labels, report_of)
    assert m["action_recall"] == 1.0                      # a, b shown in run 1
    assert m["material_missed"] == []
    assert m["action_precision"] == 0.5                   # a right, c wrong
    assert m["minor_per_report_median"] == 1.0
    assert m["class_change_share"] == 0.25                # b changed
    assert m["crossed_shown_hidden"] == ["b"]
    assert M.gate_a_pass(m) == {"recall": True, "material": True, "precision": False, "noise": True, "stability": False}


def test_binary_and_bands():
    rows = [(True, True), (True, False), (False, False), (False, True)]
    b = M.binary(rows)
    assert b == {"n_pos": 2, "n_neg": 2, "recall": 0.5, "false_alarm": 0.5}
    probs, labels = [0.9, 0.6, 0.1, 0.65], [True, True, False, False]
    e = M.errors_by_band(probs, labels, lo=0.3, hi=0.7)
    assert e["yes"] == {"n": 1, "errors": 0} and e["unsure"] == {"n": 2, "errors": 1} and e["no"] == {"n": 1, "errors": 0}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q -k "gate_a_metrics or binary"`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write `metrics.py`**

```python
# backend/src/rapid_reports_ai/scripts/review_labs/metrics.py
"""Gate metrics (spec §11). Calibration (brier, ece, auc) and McNemar come from jev_tool_lab.score."""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from rapid_reports_ai.scripts.jev_tool_lab.score import auc, brier, ece, mcnemar_exact  # noqa: F401  (re-export)

SHOWN = {"action", "minor"}


def gate_a(runs: List[Dict[str, str]], labels: Dict[str, dict], report_of: Dict[str, str]) -> dict:
    """runs: [{item_id: cls}] (run 1 first). labels: Hassan's {item_id: {verdict, material?}}."""
    r1 = runs[0]
    action = [i for i, l in labels.items() if l.get("verdict") == "action"]
    material = [i for i, l in labels.items() if l.get("material")]
    engine_action = [i for i, c in r1.items() if c == "action" and i in labels]
    per_report = defaultdict(int)
    for i, c in r1.items():
        if c == "minor":
            per_report[report_of.get(i, "?")] += 1
    reports = set(report_of.values())
    minors = [per_report.get(r, 0) for r in reports] or [0]
    out = {
        "n_labelled": len(labels),
        "n_action_labels": len(action),
        "action_recall": sum(r1.get(i) in SHOWN for i in action) / len(action) if action else None,
        "material_missed": [i for i in material if r1.get(i) not in SHOWN],
        "action_precision": (sum(labels[i]["verdict"] == "action" for i in engine_action) / len(engine_action)
                             if engine_action else None),
        "minor_per_report_median": float(statistics.median(minors)),
        "class_change_share": None,
        "crossed_shown_hidden": [],
    }
    if len(runs) > 1:
        r2 = runs[1]
        common_ids = [i for i in r1 if i in r2]
        out["class_change_share"] = sum(r1[i] != r2[i] for i in common_ids) / len(common_ids) if common_ids else None
        out["crossed_shown_hidden"] = sorted(i for i in common_ids if (r1[i] in SHOWN) != (r2[i] in SHOWN))
    return out


def gate_a_pass(m: dict) -> Dict[str, bool]:
    return {"recall": (m["action_recall"] or 0) >= 0.90,
            "material": not m["material_missed"],
            "precision": (m["action_precision"] or 0) >= 0.85,
            "noise": m["minor_per_report_median"] <= 2,
            "stability": m["class_change_share"] is not None and m["class_change_share"] <= 0.10
                         and not m["crossed_shown_hidden"]}


def binary(rows: Sequence[Tuple[bool, bool]]) -> dict:
    """rows of (label_positive, predicted_positive)."""
    pos = [p for l, p in rows if l]
    neg = [p for l, p in rows if not l]
    return {"n_pos": len(pos), "n_neg": len(neg),
            "recall": sum(pos) / len(pos) if pos else None,
            "false_alarm": sum(neg) / len(neg) if neg else None}


def band(p: float, lo: float, hi: float) -> str:
    return "yes" if p >= hi else "no" if p < lo else "unsure"


def errors_by_band(probs: Sequence[float], labels: Sequence[bool], lo: float, hi: float) -> Dict[str, dict]:
    """Where Jev's errors fall (§11 point 2): an unsure answer counts as an error when its side of 0.5 is wrong."""
    out = {b: {"n": 0, "errors": 0} for b in ("yes", "unsure", "no")}
    for p, l in zip(probs, labels):
        b = band(p, lo, hi)
        out[b]["n"] += 1
        out[b]["errors"] += int((p >= 0.5) != l)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/metrics.py tests/test_review_labs.py
git commit -m "feat(review-labs): gate metrics (Gate A bar, binary, error location by band)"
```

### Task 0.5: `clinical_pass.py`, shared by Gate B1 (arm 2) and Gate C

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/clinical_pass.py`
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/prompts/clinical_pass_v1.txt`
- Test: `backend/tests/test_review_labs.py` (append)

- [ ] **Step 1: Write the failing test**

```python
from rapid_reports_ai.scripts.review_labs import clinical_pass as CP


def test_clinical_pass_decodes_string_lists_and_splits_items():
    out = CP.ClinicalPass(characterise='["Lesion :: enhancement not described"]', safety=[],
                          inconsistencies="Signal on CT :: MRI wording in a CT report",
                          urgency="routine", urgency_reason="")
    assert out.characterise == ["Lesion :: enhancement not described"]
    assert CP.split_item(out.inconsistencies[0]) == ("Signal on CT", "MRI wording in a CT report")
    assert CP.split_item("no separator") == ("", "no separator")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q -k clinical_pass`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write the prompt `prompts/clinical_pass_v1.txt`**

```text
You are a consultant radiologist reading a finished report beside the dictation it came from. List only what a consultant would add or correct for safety and characterisation. Most reports need nothing; empty lists are the expected answer.

Lists (each item is one string "<exact quote from the report, or the finding's name> :: <one sentence>"):
- characterise: a reported finding whose characterisation is incomplete for its standard classification or management, naming the descriptor that is not described. Only features a radiologist would normally describe on this study. Never infer a grade from features that are not stated.
- safety: a critical radiology step that is missing and time-critical (for example an urgent further imaging test within hours, or an immediate communication of a critical finding). Radiology remit only: no drug, surgical or medical management.
- inconsistencies: a statement in the report that is internally inconsistent: wording that belongs to another modality, a size word that disagrees with the stated measurement, an anatomical location that does not exist as stated, or two statements in the report that contradict each other.

urgency: one of "routine", "soon", "urgent", "critical", for how quickly the referrer must act on the report as written. urgency_reason: one sentence, empty for routine.

Do not repeat anything the report already states. Do not restate the clinical history. Do not add recommendations the report already makes.
```

- [ ] **Step 4: Write `clinical_pass.py`**

```python
# backend/src/rapid_reports_ai/scripts/review_labs/clinical_pass.py
"""The one clinical pass (spec §6.4): characterisation, safety, urgency, plus the Gate B1 arm-2 inconsistencies."""
from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Tuple

from pydantic import BaseModel, field_validator

from rapid_reports_ai.scripts.jev_tool_lab import calls

from .common import decode_json_list

PROMPT = (Path(__file__).parent / "prompts" / "clinical_pass_v1.txt").read_text().strip()


class ClinicalPass(BaseModel):
    characterise: List[str] = []
    safety: List[str] = []
    inconsistencies: List[str] = []
    urgency: Literal["routine", "soon", "urgent", "critical"]
    urgency_reason: str = ""

    @field_validator("characterise", "safety", "inconsistencies", mode="before")
    @classmethod
    def _decode(cls, v):
        return [str(x) for x in decode_json_list(v)]


def split_item(s: str) -> Tuple[str, str]:
    if "::" not in s:
        return "", s.strip()
    a, b = s.split("::", 1)
    return a.strip().strip('"'), b.strip()


def user_message(case: dict) -> str:
    return (f"STUDY TITLE: {case.get('scan', '')}\n\nCLINICAL HISTORY:\n{case.get('history') or '(none)'}"
            f"\n\nDICTATION:\n{case.get('dictation', '')}\n\nREPORT:\n{case.get('report', '')}")


async def run(case: dict, qwen_fn=calls.qwen):
    try:
        out, usage = await qwen_fn(ClinicalPass, PROMPT, user_message(case), True)
        return out, usage.model_dump(), None
    except Exception as e:   # noqa: BLE001
        return None, {}, f"{type(e).__name__}: {str(e)[:300]}"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/clinical_pass.py src/rapid_reports_ai/scripts/review_labs/prompts/clinical_pass_v1.txt tests/test_review_labs.py
git commit -m "feat(review-labs): clinical pass (characterise, safety, urgency, inconsistencies), flat schema"
```

---

## Part A: Gate A, Coverage recall

**Order:** A1 (Hassan labels) → A2 (smoke, then 2 runs) → A3 (Hassan reads the v4 output) → A4 (score, ledger). A2 can run while Hassan labels; scoring waits for both.

### Task A1: the labelling page for the 27 cards

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/gate_a.py`
- Test: `backend/tests/test_review_labs.py` (append)

The 27 cards are 2, 3, 4, 5, 6, 7, 9, 11, 18, 20, 24, 25, 28, 31, 33, 35, 38, 39, 40, 42, 43, 44, 46, 47, 48, 49 and 50 (spec §11 Gate A, 2026-10-03). Each card shows the flag, the dictated line, the report sentence, and the full dictation and report (collapsed, with the line highlighted). v3's call and the 2026-10-03 peer read are hidden until Hassan has entered a verdict.

**Labelling rules,** shown at the top of the page as card 0 and fixed before labelling:
- `action`: dictated meaning is lost or changed and the radiologist should fix it.
- `minor`: real but low impact.
- `info`: a slip the report fixed.
- `suppress`: noise.
- Tick "material" for a clinically material loss.

- [ ] **Step 1: Write the failing test**

```python
from rapid_reports_ai.scripts.review_labs import gate_a as GA


def test_gate_a_card_hides_engine_and_peer_read():
    src = {"n": 7, "kind": "partial", "id8": "abcd1234", "scan": "CT", "detector_line": "Line X",
           "report_sentence": "Sentence Y", "dictation_full": "Line X", "report_full": "Sentence Y",
           "class": "suppress", "issue": "v3 issue"}
    peer = {"n": 7, "verdict": "minor", "reason": "peer reason"}
    card = GA.label_card(src, peer)
    shown = " ".join(b["text"] for b in card["blocks"])
    hidden = " ".join(b["text"] for b in card["hidden"])
    assert card["id"] == "c7" and "Line X" in shown
    assert "suppress" not in shown and "peer reason" not in shown
    assert "suppress" in hidden and "peer reason" in hidden


def test_gate_a_card_ids_constant():
    assert len(GA.LABEL_SET) == 27 and len(set(GA.LABEL_SET)) == 27
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q -k gate_a_card`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write `gate_a.py` (the `page` subcommand; later tasks add the others)**

```python
# backend/src/rapid_reports_ai/scripts/review_labs/gate_a.py
"""Gate A: Coverage recall (spec §11).

    python -m rapid_reports_ai.scripts.review_labs.gate_a page            # 27-card labelling page
    python -m rapid_reports_ai.scripts.review_labs.gate_a items           # the ~72 items (50 cards + unsampled pool)
    python -m rapid_reports_ai.scripts.review_labs.gate_a run --runs 2 [--only c2,c3]
    python -m rapid_reports_ai.scripts.review_labs.gate_a read-page --results <jsonl>
    python -m rapid_reports_ai.scripts.review_labs.gate_a score --labels <json> --read <json> --results <jsonl>"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Dict, List, Optional

from . import common, judgement, label_page, metrics

LABEL_SET = [2, 3, 4, 5, 6, 7, 9, 11, 18, 20, 24, 25, 28, 31, 33, 35, 38, 39, 40, 42, 43, 44, 46, 47, 48, 49, 50]
KIND_MAP = {"partial": ("coverage", "partial"), "differs": ("coverage", "differs"),
            "omission": ("coverage", "absent"), "contradiction": ("accuracy", "contradicted")}
FIELDS = [{"key": "verdict", "label": "Should show as", "type": "choice",
           "options": ["action", "minor", "info", "suppress"], "required": True},
          {"key": "material", "type": "check", "label": "Material loss"},
          {"key": "note", "type": "text", "label": "Note"}]
RULES = ("action = dictated meaning lost or changed, the radiologist should fix it. minor = real but low impact. "
         "info = a speech-recognition slip the report fixed. suppress = noise (present elsewhere, no effect, misread). "
         "Tick 'Material loss' for a clinically material loss. The engine's call and the peer read appear after you choose.")


def label_card(src: dict, peer: Optional[dict]) -> dict:
    line = src["detector_line"]
    return {
        "id": f"c{src['n']}", "title": f"Card {src['n']} · {src['kind']}", "meta": f"{src['scan']} · {src['id8']}",
        "blocks": [
            {"label": "Flagged" + (" report statement" if src["kind"] == "contradiction" else " dictated line"), "text": line},
            {"label": "Nearest report sentence", "text": src.get("report_sentence") or ""},
            {"label": "Full dictation", "text": src["dictation_full"], "highlight": [line], "collapsed": True},
            {"label": "Full report", "text": src["report_full"], "highlight": [src.get("report_sentence") or ""],
             "collapsed": True},
        ],
        "hidden": [
            {"label": "v3 call", "text": f"{src.get('class')}: {src.get('issue') or ''}"},
            {"label": "Peer read (2026-10-03)",
             "text": f"{peer['verdict']}: {peer['reason']}" if peer else "not in the peer read (both reads: suppress)"},
        ],
    }


def cmd_page(_args) -> None:
    cards = {c["n"]: c for c in common.read_json(common.pipeline_scratch() / "review_cards50_v3.json")}
    out = common.lab_out("gate_a")
    peer = {p["n"]: p for f in ("blind_A.json", "blind_B.json") for p in common.read_json(out / f)}
    page_cards = [{"id": "rules", "title": "Labelling rules", "meta": "read first", "blocks": [{"label": "Rules", "text": RULES}],
                   "hidden": []}]
    page_cards += [label_card(cards[n], peer.get(n)) for n in LABEL_SET]
    p = label_page.write_page(out / "label_27.html", "Gate A · label 27 cards", "gateA-label27-v1", page_cards, FIELDS)
    print(p)


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("page").set_defaults(fn=cmd_page)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q`
Expected: all PASS.

- [ ] **Step 5: Build the page and hand it to Hassan**

Run: `mkdir -p $RR_LAB_OUT/gate_a && cp /private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/88f6dff1-ef5c-4b05-a61f-1f536fb63ade/scratchpad/gateA/blind_*.json $RR_LAB_OUT/gate_a/ && .venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_a page && open $RR_LAB_OUT/gate_a/label_27.html`
Expected: prints the path. The page shows 28 cards (the rules card plus 27), and the hidden blocks appear only after a verdict is chosen.
Tell Hassan: "label the 27 cards, then press Copy my verdicts and paste the JSON here". Save his paste as `$RR_LAB_OUT/gate_a/labels.json`.

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_a.py tests/test_review_labs.py
git commit -m "feat(review-labs): Gate A labelling page for the 27 disputed cards"
```

### Task A2: the ~72 items and the v4 runs

The items are the 50 v3 cards plus the 22 `jev_pool_unsampled` flags in `compare.json` (10 partial, 9 omission, 3 differs), adjudicated with v4 and verified. **No Jev veto and no flip rule.**

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/review_labs/gate_a.py`
- Test: `backend/tests/test_review_labs.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_gate_a_items_map_kinds_and_ids():
    cards = [{"n": 1, "kind": "contradiction", "id8": "r1", "detector_line": "No X."}]
    compare = [{"id8": "r1", "jev_pool_unsampled": [{"kind": "omission", "text": "Y seen"}]}]
    cases = {"r1": {"id": "r1-full", "scan": "CT", "dictation": "d", "history": "", "report": "No X."}}
    items = GA.build_items(cards, compare, cases)
    assert [i["id"] for i in items] == ["c1", "u-r1-0"]
    assert items[0]["candidate"] == {"lane": "accuracy", "kind": "contradicted", "detector": "jev.contradiction",
                                     "anchor": "No X.", "line": None, "evidence": {}}
    assert items[1]["candidate"]["kind"] == "absent" and items[1]["candidate"]["line"] == "Y seen"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q -k gate_a_items`
Expected: FAIL (`AttributeError: build_items`).

- [ ] **Step 3: Add `build_items`, `cmd_items` and `cmd_run` to `gate_a.py`, and register both subcommands in `main()`**

```python
def _candidate(kind: str, text: str, evidence: Optional[dict] = None) -> dict:
    lane, k = KIND_MAP[kind]
    is_report_side = lane == "accuracy"
    return {"lane": lane, "kind": k, "detector": "jev.contradiction" if is_report_side else "jev.classify_first",
            "anchor": text if is_report_side else None, "line": None if is_report_side else text,
            "evidence": evidence or {}}


def build_items(cards: List[dict], compare: List[dict], cases: Dict[str, dict]) -> List[dict]:
    items = []
    for c in sorted(cards, key=lambda c: c["n"]):
        items.append({"id": f"c{c['n']}", "id8": c["id8"], "case": cases[c["id8"]],
                      "candidate": _candidate(c["kind"], c["detector_line"])})
    for r in compare:
        for k, u in enumerate(r.get("jev_pool_unsampled") or []):
            items.append({"id": f"u-{r['id8']}-{k}", "id8": r["id8"], "case": cases[r["id8"]],
                          "candidate": _candidate(u["kind"], u["text"])})
    return items


def _load_items() -> List[dict]:
    ps = common.pipeline_scratch()
    return build_items(common.read_json(ps / "review_cards50_v3.json"),
                       common.read_json(ps / "audit_compare" / "compare.json"), common.prod_cases())


def cmd_items(_args) -> None:
    items = _load_items()
    p = common.write_json(common.lab_out("gate_a") / "items.json", items)
    print(p, len(items))


async def _run(items: List[dict], runs: int, out_path) -> None:
    sem = asyncio.Semaphore(8)                     # spec §7: at most 8 concurrent calls per report
    system = judgement.prompt("adjudicator_v4")
    with open(out_path, "a") as fh:
        for run in range(1, runs + 1):
            async def one(it):
                r = await judgement.judge_and_verify(it["case"], [it["candidate"]], sem, system)
                return {"item_id": it["id"], "id8": it["id8"], "run": run, **r}
            for row in await asyncio.gather(*(one(it) for it in items)):
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"run {run}: {len(items)} items")


def cmd_run(args) -> None:
    common.load_env()
    items = _load_items()
    if args.only:
        keep = set(args.only.split(","))
        items = [i for i in items if i["id"] in keep]
    out = common.out_file("gate_a", f"v4_{args.tag}", "jsonl")
    asyncio.run(_run(items, args.runs, out))
    print(out)
```

Register in `main()`:

```python
    sub.add_parser("items").set_defaults(fn=cmd_items)
    r = sub.add_parser("run"); r.add_argument("--runs", type=int, default=2); r.add_argument("--only", default="")
    r.add_argument("--tag", default="full"); r.set_defaults(fn=cmd_run)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q`
Expected: all PASS.

- [ ] **Step 5: Build the items, then smoke-test 2 items**

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_a items`
Expected: `.../gate_a/items.json 72`.

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_a run --runs 1 --only c2,c6 --tag smoke`
Expected: 2 rows with `error: null`, a `cls` set, and `verified` set (or `edit_mode: none`). If either row has an `error` (a structured-output failure), fix the schema or prompt before the full run (L-50 method).

- [ ] **Step 6: Run the full 2 runs**

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_a run --runs 2 --tag full`
Expected: `run 1: 72 items`, `run 2: 72 items`, and the jsonl path printed.

- [ ] **Step 7: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_a.py tests/test_review_labs.py
git commit -m "feat(review-labs): Gate A items (50 cards + unsampled pool) and v4 runner"
```

### Task A3: the read page for v4's output on all ~72 items

For the 27 labelled cards, Hassan's labels are the ground truth. For the other ~45 items, Hassan reads v4's call (shown, since this is the hand read of the output) and either agrees or picks the right class.

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/review_labs/gate_a.py`

- [ ] **Step 1: Add `cmd_read_page` and register `read-page --results`**

```python
READ_FIELDS = [{"key": "verdict", "label": "Correct class", "type": "choice",
                "options": ["action", "minor", "info", "suppress"], "required": True},
               {"key": "fix_ok", "label": "Fix right", "type": "choice", "options": ["yes", "no", "n/a"]},
               {"key": "material", "type": "check", "label": "Material loss"},
               {"key": "note", "type": "text", "label": "Note"}]


def cmd_read_page(args) -> None:
    rows = [r for r in common.read_jsonl(args.results) if r["run"] == 1]
    items = {i["id"]: i for i in common.read_json(common.lab_out("gate_a") / "items.json")}
    labelled = {f"c{n}" for n in LABEL_SET}
    cards = []
    for r in rows:
        if r["item_id"] in labelled:
            continue
        it = items[r["item_id"]]
        c = it["candidate"]
        flagged = c.get("line") or c.get("anchor") or ""
        fix = (f"{r.get('edit_mode')}: find «{r.get('edit_find') or r.get('edit_after') or ''}» → «{r.get('edit_replace') or ''}»"
               if r.get("edit_mode") not in (None, "none") else "no edit")
        cards.append({"id": r["item_id"], "title": f"{r['item_id']} · {c['lane']}/{c['kind']}", "meta": it["case"]["scan"],
                      "blocks": [{"label": "Flagged", "text": flagged},
                                 {"label": f"v4 call: {r.get('cls')} · {r.get('kind')}", "text": f"{r.get('label')}\n{r.get('reason') or ''}"},
                                 {"label": "v4 fix", "text": fix + f"\nverified: {json.dumps(r.get('verified'))}"},
                                 {"label": "Full dictation", "text": it["case"]["dictation"], "highlight": [flagged], "collapsed": True},
                                 {"label": "Full report", "text": it["case"]["report"], "highlight": [flagged], "collapsed": True}],
                      "hidden": []})
    p = label_page.write_page(common.lab_out("gate_a") / "read_v4.html", "Gate A · read v4 output",
                              "gateA-read-v4-v1", cards, READ_FIELDS)
    print(p, len(cards))
```

Register in `main()`:

```python
    rp = sub.add_parser("read-page"); rp.add_argument("--results", required=True); rp.set_defaults(fn=cmd_read_page)
```

- [ ] **Step 2: Build the page and hand it to Hassan**

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_a read-page --results $RR_LAB_OUT/gate_a/v4_full_<pid>.jsonl && open $RR_LAB_OUT/gate_a/read_v4.html`
Expected: about 45 cards. Save Hassan's pasted verdicts as `$RR_LAB_OUT/gate_a/read.json`.

- [ ] **Step 3: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_a.py
git commit -m "feat(review-labs): Gate A read page for v4 output on the unlabelled items"
```

### Task A4: score, balance, ledger

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/review_labs/gate_a.py`
- Create (only if needed): `backend/test_cases/review_labs/gate_a_synthetic.json`
- Modify: `docs/model-migration/parameter-ledger.md`

- [ ] **Step 1: Add `cmd_score` and register `score --labels --read --results`**

```python
def cmd_score(args) -> None:
    labels = {k: v for k, v in common.read_json(args.labels).items() if k != "rules"}
    labels.update(common.read_json(args.read) if args.read else {})
    rows = common.read_jsonl(args.results)
    runs = [{r["item_id"]: r["cls"] for r in rows if r["run"] == n} for n in (1, 2)]
    runs = [r for r in runs if r]
    report_of = {r["item_id"]: r["id8"] for r in rows}
    m = metrics.gate_a(runs, labels, report_of)
    m["pass"] = metrics.gate_a_pass(m)
    m["errors"] = sum(1 for r in rows if r.get("error"))
    m["fix_rejected_by_guards"] = sum(1 for r in rows if r["run"] == 1 and r.get("verified") and not r["verified"]["code"])
    m["unconfirmed"] = sum(1 for r in rows if r["run"] == 1 and (r.get("verified") or {}).get("unconfirmed"))
    m["disagreements"] = sorted(i for i, l in labels.items() if runs[0].get(i) and
                                (runs[0][i] in metrics.SHOWN) != (l["verdict"] in metrics.SHOWN))
    p = common.write_json(common.out_file("gate_a", "score"), m)
    print(json.dumps(m, indent=1)); print(p)
```

Register in `main()`:

```python
    s = sub.add_parser("score"); s.add_argument("--labels", required=True); s.add_argument("--read", default="")
    s.add_argument("--results", required=True); s.set_defaults(fn=cmd_score)
```

- [ ] **Step 2: Score**

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_a score --labels $RR_LAB_OUT/gate_a/labels.json --read $RR_LAB_OUT/gate_a/read.json --results $RR_LAB_OUT/gate_a/v4_full_<pid>.jsonl`
Expected: the metrics JSON with a `pass` dict. Bar (spec §11):
- every material loss shown;
- action recall ≥ 0.90;
- action precision ≥ 0.85;
- minor median ≤ 2 per report;
- class change ≤ 10% across runs, with none crossing between shown and hidden.

- [ ] **Step 3: Balance check, only if `n_action_labels` < 10**

Write `backend/test_cases/review_labs/gate_a_synthetic.json`: 10 synthetic `action` cases (2 each of descriptor drop, size change, differential order reversed, missed lesion, a scope word such as "all" dropped) plus 5 paraphrase controls (`suppress`). Every case is synthetic and structural. Shape, with two complete examples:

```json
[
 {"id": "s-desc-1", "category": "descriptor_drop", "label": "action", "scan": "CT abdomen",
  "dictation": "- Liver normal in size.\n- Simple-appearing 14 mm cyst in the upper pole of the left kidney with a thin septation.",
  "history": "", "report": "FINDINGS:\nThe liver is normal in size. A 14 mm cyst is present in the upper pole of the left kidney.\nIMPRESSION:\nLeft renal cyst.",
  "candidate": {"lane": "coverage", "kind": "partial", "detector": "synthetic",
                "line": "Simple-appearing 14 mm cyst in the upper pole of the left kidney with a thin septation", "anchor": null, "evidence": {}}},
 {"id": "s-ctrl-1", "category": "paraphrase_control", "label": "suppress", "scan": "CT abdomen",
  "dictation": "- No free fluid in the abdomen or pelvis.",
  "history": "", "report": "FINDINGS:\nThere is no ascites.\nIMPRESSION:\nNo acute abnormality.",
  "candidate": {"lane": "coverage", "kind": "partial", "detector": "synthetic",
                "line": "No free fluid in the abdomen or pelvis", "anchor": null, "evidence": {}}}
]
```

Run them through the same runner by adding `--synthetic <path>` to `cmd_run`. Each synthetic case becomes an item `{"id", "id8": id, "case": {scan, dictation, history, report}, "candidate"}`, and its label is added to `labels`. Then re-score with the synthetic labels merged.

- [ ] **Step 4: Ledger entry**

Append the next free `L-5x · Gate A: coverage recall with adjudicator v4` to `docs/model-migration/parameter-ledger.md`:
- the data (27 labelled + ~45 read, synthetic if used);
- the metrics table against the bar;
- the disagreements Hassan saw;
- the decision (lane passes / prompt change needed).

Keep production text out of it: quote card numbers and structural descriptions only.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_a.py docs/model-migration/parameter-ledger.md
git add test_cases/review_labs/gate_a_synthetic.json 2>/dev/null || true
git commit -m "docs(ledger): Gate A coverage recall result (adjudicator v4)"
```

---

## Part B: Gate B, Accuracy

### Task B0: pull the 41 cases and build the fabrication gold

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/gate_b.py`

- [ ] **Step 1: Write `gate_b.py` with `cases` and `gold-page`**

`cases` writes the 41 audit-comparison reports, with dictation, history, report and audit items, to `$RR_LAB_OUT/gate_b/cases.json`.

`gold-page` builds a page over candidate unsupported spans. Two blind reader subagents (Step 2) propose the spans into `$RR_LAB_OUT/gate_b/gold_candidates_*.json`. Hassan confirms each one.

```python
# backend/src/rapid_reports_ai/scripts/review_labs/gate_b.py
"""Gate B: Accuracy (spec §11). B1 = alignment + code checks (+ inconsistent arms); B2 = Jev wording lab for
"is this positive finding stated".

    python -m rapid_reports_ai.scripts.review_labs.gate_b cases
    python -m rapid_reports_ai.scripts.review_labs.gate_b gold-page
    python -m rapid_reports_ai.scripts.review_labs.gate_b b2-build
    python -m rapid_reports_ai.scripts.review_labs.gate_b b2-run --runs 2 [--only id,id] [--arms W1n,W1c,...]
    python -m rapid_reports_ai.scripts.review_labs.gate_b b2-escalate --results <jsonl> --lo X --hi Y
    python -m rapid_reports_ai.scripts.review_labs.gate_b b2-score --results <jsonl> --escalated <jsonl> --lo X --hi Y
    python -m rapid_reports_ai.scripts.review_labs.gate_b inconsistent-run
    python -m rapid_reports_ai.scripts.review_labs.gate_b align-page        # [after Plan 2 Task 2]
    python -m rapid_reports_ai.scripts.review_labs.gate_b checks-score      # [after Plan 2 Task 3]"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Dict, List, Optional

from . import clinical_pass, common, judgement, label_page, metrics

GOLD_KINDS = ["invented_finding", "invented_measurement", "invented_prior", "certainty_upgrade", "misattributed",
              "inconsistent_modality", "inconsistent_size_word", "other"]


def load_cases() -> List[dict]:
    cases = common.prod_cases()
    out = []
    for r in common.read_json(common.pipeline_scratch() / "audit_compare" / "compare.json"):
        c = dict(cases[r["id8"]])
        c.update(id8=r["id8"], audit_items=r.get("audit_items") or [], both_missed=r.get("both_missed"))
        out.append(c)
    return out


def cmd_cases(_args) -> None:
    cs = load_cases()
    print(common.write_json(common.lab_out("gate_b") / "cases.json", cs), len(cs))


GOLD_FIELDS = [{"key": "verdict", "label": "Unsupported by dictation/history?", "type": "choice",
                "options": ["unsupported", "supported", "unsure"], "required": True},
               {"key": "kind", "label": "Kind", "type": "choice", "options": GOLD_KINDS},
               {"key": "note", "type": "text", "label": "Note"}]


def gold_candidates(out) -> List[dict]:
    """Reader-proposed spans, de-duplicated by (id8, span), with stable ids g0, g1, … shared by every subcommand."""
    seen, res = set(), []
    for f in sorted(out.glob("gold_candidates_*.json")):
        for x in common.read_json(f):
            key = (x["id8"], x["span"])
            if key not in seen:
                seen.add(key)
                res.append({**x, "gid": f"g{len(res)}"})
    return res


def confirmed_gold(out) -> List[dict]:
    """Candidates Hassan marked unsupported; his kind overrides the reader's."""
    verdicts = common.read_json(out / "gold.json")
    return [{**x, "kind": verdicts[x["gid"]].get("kind") or x.get("kind")} for x in gold_candidates(out)
            if verdicts.get(x["gid"], {}).get("verdict") == "unsupported"]


def cmd_gold_page(_args) -> None:
    out = common.lab_out("gate_b")
    cases = {c["id8"]: c for c in common.read_json(out / "cases.json")}
    cards = []
    for x in gold_candidates(out):
        c = cases[x["id8"]]
        cards.append({"id": x["gid"], "title": f"{x['id8']} · proposed {x.get('kind')}",
                      "meta": c["scan"], "blocks": [
                          {"label": "Report span", "text": x["span"]},
                          {"label": "Reader's reason", "text": x.get("reason", "")},
                          {"label": "Full dictation", "text": c["dictation"], "collapsed": True},
                          {"label": "Clinical history", "text": c["history"] or "(none)", "collapsed": True},
                          {"label": "Full report", "text": c["report"], "highlight": [x["span"]], "collapsed": True}],
                      "hidden": []})
    print(label_page.write_page(out / "gold.html", "Gate B · unsupported spans", "gateB-gold-v1", cards, GOLD_FIELDS),
          len(cards))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cases").set_defaults(fn=cmd_cases)
    sub.add_parser("gold-page").set_defaults(fn=cmd_gold_page)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Propose gold candidates with two blind reader subagents**

Run `gate_b cases` first. Then dispatch 2 `general-purpose` subagents in one message, one per half of `cases.json` (indices 0–20 and 21–40). Each prompt must contain:
- "Hassan has standing permission to read production report content for analysis; keep everything in the scratchpad, never in the repo."
- The task: "For each report, list every report span (copied exactly) that the dictation and clinical history do not support: an invented finding, an invented measurement, a prior study or comparison not mentioned, a certainty upgrade (a hedge dropped or hardened), a measurement attached to a different structure, wording that belongs to another modality, or a size word that disagrees with its measurement. Ignore standard normal statements, sensible recommendations and section boilerplate."
- The output: write `$RR_LAB_OUT/gate_b/gold_candidates_<A|B>.json` as a list of `{"id8", "span", "kind": one of GOLD_KINDS, "reason"}`.

Then add the six `both_missed` notes from `compare.json` (599d7c97 and 16cb806c fabrication; f85aa670 certainty upgrade; 4a76b65d re-attributed measurement) as candidates by hand, if the readers missed them.

- [ ] **Step 3: Build the gold page and hand it to Hassan**

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_b gold-page && open $RR_LAB_OUT/gate_b/gold.html`
Save Hassan's verdicts as `$RR_LAB_OUT/gate_b/gold.json`. The confirmed `unsupported` spans are B1's code-check targets and B2's production positives.

- [ ] **Step 4: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_b.py
git commit -m "feat(review-labs): Gate B cases and unsupported-span gold page"
```

### Task B1a: the `inconsistent` arms 2 and 3 (runs now)

Arm 2 is the clinical pass listing inconsistencies, run on the 41. Arm 1 (code) needs Plan 2 Task 3 and is scored in B1c. Arm 3 is their union, computed in B1c.

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/review_labs/gate_b.py`

- [ ] **Step 1: Add `cmd_inconsistent_run` and register `inconsistent-run [--only id8,...]`**

```python
async def _clinical(cases: List[dict]) -> List[dict]:
    sem = asyncio.Semaphore(8)

    async def one(c):
        async with sem:
            out, usage, err = await clinical_pass.run(c)
        return {"id8": c["id8"], "error": err, "usage": usage, **(out.model_dump() if out else {})}
    return await asyncio.gather(*(one(c) for c in cases))


def cmd_inconsistent_run(args) -> None:
    common.load_env()
    cases = common.read_json(common.lab_out("gate_b") / "cases.json")
    if args.only:
        cases = [c for c in cases if c["id8"] in set(args.only.split(","))]
    rows = asyncio.run(_clinical(cases))
    print(common.write_json(common.out_file("gate_b", "clinical_pass"), rows))
```

Register in `main()`:

```python
    ir = sub.add_parser("inconsistent-run"); ir.add_argument("--only", default=""); ir.set_defaults(fn=cmd_inconsistent_run)
```

- [ ] **Step 2: Smoke-test 2 cases, then run all**

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_b inconsistent-run --only <id8a>,<id8b>`
Expected: 2 rows with `error: null`.

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_b inconsistent-run`
Expected: 41 rows. This output is reused by Gate C (characterise / safety / urgency). Don't run it again there (memory `feedback_eval_economy`).

- [ ] **Step 3: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_b.py
git commit -m "feat(review-labs): Gate B1 inconsistent arm 2 (clinical pass) runner"
```

### Task B2: the Jev wording lab for "is this positive finding stated"

**Data: 100 items, balanced 50/50, category-tagged** (adoption needs at least 100, per L-50).
- **Unsupported (50):** 10 each of `production` (Hassan-confirmed spans from B0, topped up with the next category if fewer than 10), `invented_finding`, `invented_measurement`, `invented_prior` and `certainty_upgrade`. The synthetic ones are written into a real report from the 41 as one inserted sentence (Step 2). The clause and its report stay in the scratchpad.
- **Stated (50):** 10 each of `verbatim`, `paraphrased`, `hedged` (the dictation hedges and the report keeps the hedge), `merged` (two dictated lines in one report sentence) and `abbreviated`. These are positive report clauses from the 41 whose content the dictation states, confirmed on a page.

**Labelling rule, fixed before labelling** (it goes into the page's rules card and the escalation prompt): *a report clause is "stated" when every finding, measurement, comparison and certainty level it asserts is in the dictation or history, in any wording, including as a possibility; otherwise it is "not stated".*

**Arms:** 3 wordings × 2 types = 6 arms. `n` = noul; `c` = Choice of `stated` / `not_stated` / `cant_tell`.
- **W1:** `The dictated findings report this finding, including as a possibility, in any wording. Report statement: "{clause}"` (true = stated).
- **W2:** `Read only this one report statement: "{clause}". Everything it asserts (each finding, measurement, comparison and its certainty) is stated in the dictated findings or clinical history, in any wording, including as a possibility.` (true = stated).
- **W3:** `Read only this one report statement: "{clause}". Find what the dictated findings and clinical history say about the same structure, then decide whether they state what this statement asserts.` This wording is Choice-only. The noul form uses the W2 instruction with criteria `{"true": "stated", "false": "not stated"}`, so the noul arm `W3n` is skipped by construction, giving 5 arms.

The Choice options are:
- `stated`: "Every finding, measurement, comparison and certainty level in the statement is in the dictation or history, in any wording, including as a possibility."
- `not_stated`: "The statement asserts a finding, measurement, comparison or certainty that the dictation and history do not state."
- `cant_tell`: "The statement cannot be checked against the dictation and history from the text alone."

The state is `SCAN TYPE: …\nCLINICAL HISTORY: …\nDICTATED FINDINGS:\n…`.

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/review_labs/gate_b.py`
- Test: `backend/tests/test_review_labs.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
from rapid_reports_ai.scripts.review_labs import gate_b as GB


def test_b2_questions_shapes():
    q = GB.b2_question("W1n", "A 5 mm nodule.")
    assert q["type"] == "noul" and q["instructions"].endswith('"A 5 mm nodule."')
    q = GB.b2_question("W3c", "A 5 mm nodule.")
    assert q["type"] == "choice" and set(q["criteria"]) == {"stated", "not_stated", "cant_tell"}
    assert "W3n" not in GB.B2_ARMS


def test_b2_p_stated_from_answers():
    assert GB.p_stated("W1n", {"noul": 0.8}) == 0.8
    assert GB.p_stated("W1c", {"choice": "stated", "probabilities": {"stated": 0.7, "not_stated": 0.2, "cant_tell": 0.1}}) == 0.7
    assert GB.is_cant_tell("W1c", {"choice": "cant_tell", "probabilities": {"cant_tell": 0.5}})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q -k b2_`
Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Add the B2 question builders, `b2-build`, `b2-run` and `b2-score` to `gate_b.py`**

```python
_W = {
    "W1": 'The dictated findings report this finding, including as a possibility, in any wording. Report statement: "{c}"',
    "W2": ('Read only this one report statement: "{c}". Everything it asserts (each finding, measurement, comparison '
           'and its certainty) is stated in the dictated findings or clinical history, in any wording, including as a possibility.'),
    "W3": ('Read only this one report statement: "{c}". Find what the dictated findings and clinical history say about '
           'the same structure, then decide whether they state what this statement asserts.'),
}
_CHOICES = {
    "stated": "Every finding, measurement, comparison and certainty level in the statement is in the dictation or history, "
              "in any wording, including as a possibility.",
    "not_stated": "The statement asserts a finding, measurement, comparison or certainty that the dictation and history do not state.",
    "cant_tell": "The statement cannot be checked against the dictation and history from the text alone.",
}
B2_ARMS = ["W1n", "W1c", "W2n", "W2c", "W3c"]


def b2_question(arm: str, clause: str) -> dict:
    w, t = arm[:2], arm[2]
    if t == "n":
        return {"type": "noul", "instructions": _W[w].format(c=clause),
                "criteria": {"true": "stated", "false": "not stated"}}
    return {"type": "choice", "instructions": _W[w].format(c=clause), "criteria": dict(_CHOICES)}


def p_stated(arm: str, ans: dict) -> float:
    if arm.endswith("n"):
        return float(ans["noul"])
    return float((ans.get("probabilities") or {}).get("stated", 0.0))


def is_cant_tell(arm: str, ans: dict) -> bool:
    return arm.endswith("c") and ans.get("choice") == "cant_tell"


def _state(c: dict) -> str:
    return (f"SCAN TYPE: {c['scan']}\nCLINICAL HISTORY: {c.get('history') or '(none)'}\n"
            f"DICTATED FINDINGS:\n{c['dictation']}")
```

**`b2-build`** assembles `$RR_LAB_OUT/gate_b/b2_items.json` as a list of `{"id", "id8", "category", "label": "stated"|"not_stated", "clause", "case": {...}}`:

```python
FABRICATE_SYS = ("Write ONE sentence in the style of this radiology report that states a {kind} which the dictation does "
                 "not contain. kind meanings: invented_finding = a plausible abnormal finding in an organ the report "
                 "covers; invented_measurement = a measurement for a structure the report names without one; "
                 "invented_prior = a comparison with a prior study; certainty_upgrade = a definite restatement of a "
                 "finding the dictation hedges. Return only the sentence.")


class OneSentence(BaseModel):          # add `from pydantic import BaseModel` to gate_b.py's imports
    sentence: str


async def _fabricate(case: dict, kind: str) -> Optional[str]:
    from rapid_reports_ai.scripts.jev_tool_lab import calls
    try:
        out, _ = await calls.qwen(OneSentence, FABRICATE_SYS.format(kind=kind),
                                  f"DICTATION:\n{case['dictation']}\n\nREPORT:\n{case['report']}", False)
        return out.sentence.strip()
    except Exception:   # noqa: BLE001
        return None


def cmd_b2_build(_args) -> None:
    common.load_env()
    out = common.lab_out("gate_b")
    cases = common.read_json(out / "cases.json")
    by8 = {c["id8"]: c for c in cases}
    items = [{"id": f"p-{x['gid']}", "id8": x["id8"], "category": "production", "label": "not_stated",
              "clause": x["span"], "case": by8[x["id8"]]} for x in confirmed_gold(out)][:10]
    kinds = ["invented_finding", "invented_measurement", "invented_prior", "certainty_upgrade"]
    need = {k: 10 for k in kinds}
    need[kinds[0]] += 10 - len(items)                   # top up when production positives < 10

    async def build():
        jobs = []
        for k in kinds:
            for i in range(need[k]):
                c = cases[(i * 7 + kinds.index(k) * 3) % len(cases)]
                jobs.append((k, c, _fabricate(c, k)))
        res = await asyncio.gather(*(j[2] for j in jobs))
        for (k, c, _), s in zip(jobs, res):
            if s:
                items.append({"id": f"f-{k}-{len(items)}", "id8": c["id8"], "category": k, "label": "not_stated",
                              "clause": s, "case": {**c, "report": c["report"].replace("\nIMPRESSION:", f" {s}\nIMPRESSION:", 1)}})
    asyncio.run(build())
    print(common.write_json(out / "b2_items_unsupported.json", items), len(items))
```

The 50 **stated** items come from the stated-candidates page (Step 4). They are written to `b2_items_stated.json` with the same shape and `label: "stated"`, then merged into `b2_items.json`.

**`b2-run`** sends every item × arm, `runs` times. One `calls.jev` call per item per run, with all arms' questions under one state:

```python
async def _b2(items: List[dict], arms: List[str], runs: int, out_path) -> None:
    from rapid_reports_ai.scripts.jev_tool_lab import calls
    sem = asyncio.Semaphore(4)
    with open(out_path, "a") as fh:
        for run in range(1, runs + 1):
            async def one(it):
                qs = {a: b2_question(a, it["clause"]) for a in arms}
                async with sem:
                    try:
                        ans, _, secs = await calls.jev({_state(it["case"]): qs})
                        err = None
                    except Exception as e:   # noqa: BLE001
                        ans, secs, err = {}, None, f"{type(e).__name__}: {e}"
                return [{"item_id": it["id"], "run": run, "arm": a, "label": it["label"], "category": it["category"],
                         "answer": ans.get(a), "jev_s": secs, "error": err} for a in arms]
            for rows in await asyncio.gather(*(one(it) for it in items)):
                for r in rows:
                    fh.write(json.dumps(r) + "\n")


def cmd_b2_run(args) -> None:
    common.load_env()
    items = common.read_json(common.lab_out("gate_b") / "b2_items.json")
    if args.only:
        items = [i for i in items if i["id"] in set(args.only.split(","))]
    arms = args.arms.split(",") if args.arms else B2_ARMS
    out = common.out_file("gate_b", "b2_jev", "jsonl")
    asyncio.run(_b2(items, arms, args.runs, out))
    print(out)
```

**`b2-escalate`** runs once, after band edges are chosen from run 1's measured gap. It sends every *unsure* item (Choice `cant_tell`, or noul / Choice `p_stated` within `[lo, hi)`) to the lab adjudicator as an `accuracy/unsupported` candidate. One adjudicator call per distinct item, reused across arms:

```python
def cmd_b2_escalate(args) -> None:
    common.load_env()
    items = {i["id"]: i for i in common.read_json(common.lab_out("gate_b") / "b2_items.json")}
    rows = [r for r in common.read_jsonl(args.results) if r["run"] == 1 and r["answer"]]
    unsure = sorted({r["item_id"] for r in rows if is_cant_tell(r["arm"], r["answer"]) or
                     args.lo <= p_stated(r["arm"], r["answer"]) < args.hi})
    sem = asyncio.Semaphore(8)

    async def go():
        async def one(iid):
            it = items[iid]
            cand = {"lane": "accuracy", "kind": "unsupported", "detector": "jev.b2", "anchor": it["clause"], "line": None,
                    "evidence": {"jev_unsure": {"question": "positive_stated", "band": "unsure"}}}
            r = await judgement.judge_and_verify({**it["case"]}, [cand], sem)
            return {"item_id": iid, **r}
        return await asyncio.gather(*(one(i) for i in unsure))
    out = common.out_file("gate_b", "b2_escalated", "jsonl")
    with open(out, "w") as fh:
        for r in asyncio.run(go()):
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(out, len(unsure))
```

**`b2-score`** reports, per arm:
- AUC, Brier and ECE over `p_stated`;
- `errors_by_band` at the chosen `lo`/`hi`;
- the unsure pile per report;
- recall and false alarm **after escalation**. An unsure item counts as flagged when the adjudicator's `cls` is `action` or `minor`. A confident "not stated" (`p_stated < lo`, or Choice `not_stated`) counts as flagged.

It also reports the with-vs-without exit option comparison (the `Wxc` arms against their `Wxn` twins), per-category recall, and run-to-run drift (max |Δp|):

```python
def cmd_b2_score(args) -> None:
    rows = [r for r in common.read_jsonl(args.results) if r["answer"]]
    esc = {r["item_id"]: r for r in common.read_jsonl(args.escalated)} if args.escalated else {}
    out = {}
    for arm in sorted({r["arm"] for r in rows}):
        r1 = [r for r in rows if r["arm"] == arm and r["run"] == 1]
        probs = [p_stated(arm, r["answer"]) for r in r1]
        labels = [r["label"] == "stated" for r in r1]

        def flagged(r):
            p = p_stated(arm, r["answer"])
            if is_cant_tell(arm, r["answer"]) or args.lo <= p < args.hi:
                e = esc.get(r["item_id"])
                return bool(e and e.get("cls") in ("action", "minor"))
            return p < args.lo
        by_cat = {}
        for r in r1:
            by_cat.setdefault(r["category"], []).append((r["label"] == "not_stated", flagged(r)))
        r2 = {r["item_id"]: p_stated(arm, r["answer"]) for r in rows if r["arm"] == arm and r["run"] == 2}
        out[arm] = {
            "auc": metrics.auc([1 - p for p in probs], [not l for l in labels]),
            "brier": metrics.brier(probs, labels), "ece": metrics.ece(probs, labels),
            "bands": metrics.errors_by_band(probs, labels, args.lo, args.hi),
            "after_escalation": metrics.binary([(r["label"] == "not_stated", flagged(r)) for r in r1]),
            "by_category": {k: metrics.binary(v) for k, v in by_cat.items()},
            "unsure_items": sum(1 for r in r1 if is_cant_tell(arm, r["answer"]) or args.lo <= p_stated(arm, r["answer"]) < args.hi),
            "max_drift": max((abs(r2[r["item_id"]] - p_stated(arm, r["answer"])) for r in r1 if r["item_id"] in r2), default=None),
        }
    print(json.dumps(out, indent=1))
    print(common.write_json(common.out_file("gate_b", "b2_score"), out))
```

Register all four subcommands in `main()`:

```python
    b = sub.add_parser("b2-build"); b.set_defaults(fn=cmd_b2_build)
    r = sub.add_parser("b2-run"); r.add_argument("--runs", type=int, default=2); r.add_argument("--only", default="")
    r.add_argument("--arms", default=""); r.set_defaults(fn=cmd_b2_run)
    e = sub.add_parser("b2-escalate"); e.add_argument("--results", required=True)
    e.add_argument("--lo", type=float, required=True); e.add_argument("--hi", type=float, required=True); e.set_defaults(fn=cmd_b2_escalate)
    s = sub.add_parser("b2-score"); s.add_argument("--results", required=True); s.add_argument("--escalated", default="")
    s.add_argument("--lo", type=float, default=0.3); s.add_argument("--hi", type=float, default=0.7); s.set_defaults(fn=cmd_b2_score)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q`
Expected: all PASS.

- [ ] **Step 5: Build the unsupported half and the stated half, and confirm both on a page**

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_b b2-build`
Expected: about 50 items in `b2_items_unsupported.json`.

For the stated half, dispatch one blind reader subagent (with the prod-permission sentence) over `cases.json`. It picks 10 positive report clauses per stated category (verbatim, paraphrased, hedged, merged, abbreviated) whose content the dictation states, and writes `b2_stated_candidates.json` as `[{"id8", "clause", "category"}]`.

Build one confirmation page over both halves with `label_page.write_page`. The fields are `label: stated | not_stated | unsure (required)`, and the rules card holds the labelling rule above. Hassan confirms. Drop `unsure` items and replace them from spare candidates until the set is 50/50. Write the final `b2_items.json`.

- [ ] **Step 6: Smoke-test 2 items on every arm, then run**

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_b b2-run --runs 1 --only <stated_id>,<unsupported_id>`
Expected: 10 rows (2 items × 5 arms), all with an `answer` and no `error`.

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_b b2-run --runs 2`
Expected: 1,000 rows.

- [ ] **Step 7: Set the bands in the measured gap, escalate, score**

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_b b2-score --results <b2_jev.jsonl> --lo 0.3 --hi 0.7`. This is a first pass, before escalation, to see the gap.

Pick `lo`/`hi` per arm in the gap between the stated and not-stated distributions, and record them.

Run: `... gate_b b2-escalate --results <b2_jev.jsonl> --lo <lo> --hi <hi>`
Run: `... gate_b b2-score --results <b2_jev.jsonl> --escalated <b2_escalated.jsonl> --lo <lo> --hi <hi>`

**Pass (spec §11):** after escalation, recall ≥ 90% on not-stated, false alarm ≤ 5% on stated, and max drift ≤ 0.2. The baseline is L-46 (5/32, 49 false alarms). If no arm passes, `unsupported` ships code-only.

- [ ] **Step 8: Ledger and commit**

Append the next free L-number, "Gate B2: positive-finding-stated wording lab". It holds the table per arm (AUC / Brier / ECE / bands / recall / false alarm after escalation / drift / unsure pile), with vs without the exit option, the chosen arm and bands, or "code-only".

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_b.py tests/test_review_labs.py docs/model-migration/parameter-ledger.md
git commit -m "feat(review-labs): Gate B2 wording lab (5 arms, escalation to adjudicator) + ledger"
```

### Task B1c: alignment hand-check and code-check scoring [after Plan 2 Tasks 2–3]

This runs once Plan 2 has landed `review_engine/alignment.py` (`align`) and `review_engine/checks.py` (`run_checks`).

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/review_labs/gate_b.py`

- [ ] **Step 1: Add `cmd_align_page`, with each report clause as a card showing its paired dictated lines**

```python
ALIGN_FIELDS = [{"key": "verdict", "label": "Pairing", "type": "choice",
                 "options": ["correct", "wrong pair", "should be unmatched", "missed a line"], "required": True},
                {"key": "note", "type": "text", "label": "Note"}]


def cmd_align_page(args) -> None:
    from rapid_reports_ai.review_engine.alignment import align
    from rapid_reports_ai.generation_artifacts import GenerationArtifacts  # noqa: F401  (sections come from the report)
    from rapid_reports_ai.report_review import quick_section_names
    cases = common.read_json(common.lab_out("gate_b") / "cases.json")[: args.n]
    cards = []
    for c in cases:
        al = align(c["report"], c["dictation"], c["history"], quick_section_names(c["report"]))
        lines = {l.id: l.text for l in al.lines}
        for cl in al.clauses:
            pairs = [p for p in al.pairs if p.clause_id == cl.id]
            txt = "\n".join(f"{p.how} {p.score:.2f}: {lines[p.line_id]}" for p in pairs) or "(unmatched)"
            cards.append({"id": f"{c['id8']}-{cl.id}", "title": f"{c['id8']} · {cl.section}", "meta": c["scan"],
                          "blocks": [{"label": "Report clause", "text": cl.text},
                                     {"label": "Paired dictated lines", "text": txt},
                                     {"label": "Full dictation", "text": c["dictation"], "collapsed": True}],
                          "hidden": []})
    print(label_page.write_page(common.lab_out("gate_b") / "align.html", "Gate B1 · alignment hand-check",
                                "gateB-align-v1", cards, ALIGN_FIELDS), len(cards))
```

Register `align-page --n 10`. Hassan labels. **Pass:** ≥ 95% of clauses `correct` (spec §11).

- [ ] **Step 2: Add `cmd_checks_score`, and score the code checks and arms 1, 2 and 3 against the gold**

```python
def _hit(span: str, text: str) -> bool:
    a, b = span.lower(), (text or "").lower()
    return bool(a and b) and (a in b or b in a)


def cmd_checks_score(args) -> None:
    from rapid_reports_ai.review_engine.alignment import align
    from rapid_reports_ai.review_engine.checks import run_checks
    from rapid_reports_ai.report_review import quick_section_names
    out = common.lab_out("gate_b")
    cases = common.read_json(out / "cases.json")
    gold = confirmed_gold(out)
    clinical = {r["id8"]: r for r in common.read_json(args.clinical)}
    res = {"code": {"tp": 0, "fp": 0}, "clinical": {"tp": 0, "fp": 0}, "both": {"tp": 0, "fp": 0}, "missed": {}}
    for c in cases:
        al = align(c["report"], c["dictation"], c["history"], quick_section_names(c["report"]))
        code_spans = [x.anchor.text for x in run_checks(c["report"], c["dictation"], c["history"], c["scan"], al)
                      if x.anchor]
        cl_spans = [clinical_pass.split_item(s)[0] for s in (clinical.get(c["id8"], {}).get("inconsistencies") or [])]
        g = [x for x in gold if x["id8"] == c["id8"]]
        for arm, spans in (("code", code_spans), ("clinical", cl_spans), ("both", code_spans + cl_spans)):
            hits = [s for s in spans if any(_hit(x["span"], s) for x in g)]
            res[arm]["tp"] += len({x["span"] for x in g if any(_hit(x["span"], s) for s in spans)})
            res[arm]["fp"] += len(spans) - len(hits)
        for x in g:
            if not any(_hit(x["span"], s) for s in code_spans):
                res["missed"].setdefault(x["kind"], []).append(f"{c['id8']}: {x['span'][:80]}")
    res["gold_n"] = len(gold)
    res["fp_per_report"] = {a: res[a]["fp"] / len(cases) for a in ("code", "clinical", "both")}
    print(json.dumps(res, indent=1)); print(common.write_json(common.out_file("gate_b", "b1_score"), res))
```

Register `checks-score --clinical <clinical_pass_*.json>`.

**Pass (spec §11 B1):**
- code catches every fabricated number, prior study and certainty upgrade in the gold;
- false alarms ≤ 1 per report on mean, after a hand read of the false positives;
- the `inconsistent` arm with the best recall at ≤ 1 false alarm per report is adopted.

The hand read of the false positives is a `label_page` over the `fp` spans, with fields `real problem | false alarm`.

- [ ] **Step 3: Ledger and commit**

Append the next free L-number, "Gate B1: alignment + code checks + inconsistent arms". It records the alignment %, the code catch table by kind, false alarms per report, the arm comparison and the adopted arm.

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_b.py docs/model-migration/parameter-ledger.md
git commit -m "feat(review-labs): Gate B1 alignment page and code-check scoring + ledger"
```

---

## Part C: Gate C, Additions

### Task C1: `additions_map.py`, synthesis cards → candidates (code, test-first)

The S4 card shape comes from `guideline_prefetch.py:1683-1697`:
- `classifications[]`: `{system, authority, year, grade, criteria, management}`. Note that `criteria` defines the **assigned grade only**, not the whole system.
- `thresholds[]`: `{parameter, threshold, significance, context}`.
- `follow_up_actions[]`: `{modality, timing, indication, urgency, guideline_source}`.
- `differentials[]`, `imaging_flags[]`, `sources[]`, `finding`, `finding_short_label`, `finding_number`.

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/additions_map.py`
- Test: `backend/tests/test_review_labs.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
from rapid_reports_ai.scripts.review_labs import additions_map as AM

CARD = {"finding_number": 1, "finding": "12 mm left renal lesion", "finding_short_label": "Left renal lesion",
        "classifications": [{"system": "Bosniak 2019", "grade": "II", "criteria": "Thin septa ...", "management": "x"}],
        "thresholds": [{"parameter": "size", "threshold": "4 cm", "significance": "s", "context": "c"}],
        "follow_up_actions": [{"modality": "US", "timing": "6 months", "indication": "i", "urgency": "routine",
                               "guideline_source": "g"}, {"modality": "MRI", "timing": "", "indication": "j"}],
        "differentials": [{"diagnosis": "d1"}], "imaging_flags": ["f1"], "sources": [{"url": "u", "title": "t"}]}


def test_map_card_kinds_and_citation():
    cands = AM.map_card(CARD)
    kinds = [c["kind"] for c in cands]
    assert kinds == ["grade", "threshold", "follow_up", "option", "option", "option"]
    g = cands[0]
    assert g["lane"] == "additions" and g["detector"] == "s4.classification"
    assert g["evidence"]["system"] == "Bosniak 2019" and "criteria" not in g["evidence"]
    assert g["citation"] == {"card": 1, "source": "u", "label": "t"}


def test_map_card_with_criteria_arm():
    g = AM.map_card(CARD, with_criteria=True)[0]
    assert g["evidence"]["criteria"] == "Thin septa ..."


def test_system_key_normalises():
    assert AM.system_key("Bosniak classification v2019") == AM.system_key("Bosniak 2019") == "bosniak"
    assert AM.system_key("LI-RADS v2018") == "lirads"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q -k "map_card or system_key"`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write `additions_map.py`**

```python
# backend/src/rapid_reports_ai/scripts/review_labs/additions_map.py
"""S4 synthesis card → Additions candidates (spec §6.4), and a criteria-by-system index for the Gate C arm."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Iterable, List

_ALIASES = {"cadrads": "cadrads", "tirads": "tirads", "acrtirads": "tirads", "orads": "orads", "orad": "orads",
            "lirads": "lirads", "lungrads": "lungrads", "pirads": "pirads", "birads": "birads", "bosniak": "bosniak",
            "fleischner": "fleischner", "kellgrenlawrence": "kellgrenlawrence", "cacdrs": "cacdrs", "garden": "garden",
            "nascet": "nascet", "modic": "modic", "pfirrmann": "pfirrmann", "aast": "aast"}


def system_key(name: str) -> str:
    """Lower-case letters of the system name up to its first version/year token, mapped through _ALIASES."""
    head = re.split(r"\b(?:v?\d{2,4}|classification|criteria|system|version)\b", name or "", 1, flags=re.I)[0]
    key = re.sub(r"[^a-z]", "", head.lower())
    for k, v in _ALIASES.items():
        if key.startswith(k):
            return v
    return key


def _citation(card: dict) -> dict:
    src = (card.get("sources") or [{}])[0]
    return {"card": card.get("finding_number"), "source": src.get("url"), "label": src.get("title")}


def _cand(card: dict, kind: str, detector: str, evidence: dict) -> dict:
    return {"lane": "additions", "kind": kind, "detector": detector, "line": None,
            "anchor": card.get("finding_short_label") or card.get("finding"),
            "evidence": {"finding": card.get("finding"), **{k: v for k, v in evidence.items() if v}},
            "citation": _citation(card)}


def map_card(card: dict, with_criteria: bool = False) -> List[dict]:
    out = []
    for c in card.get("classifications") or []:
        ev = {"system": c.get("system"), "grade": c.get("grade")}
        if with_criteria:
            ev["criteria"] = c.get("criteria")
        out.append(_cand(card, "grade", "s4.classification", ev))
    for t in card.get("thresholds") or []:
        out.append(_cand(card, "threshold", "s4.threshold",
                         {"parameter": t.get("parameter"), "threshold": t.get("threshold"), "significance": t.get("significance")}))
    for i, f in enumerate(card.get("follow_up_actions") or []):
        out.append(_cand(card, "follow_up" if i == 0 else "option", "s4.follow_up",
                         {"modality": f.get("modality"), "timing": f.get("timing"), "indication": f.get("indication")}))
    for d in card.get("differentials") or []:
        out.append(_cand(card, "option", "s4.differential", {"text": d.get("diagnosis")}))
    for fl in card.get("imaging_flags") or []:
        out.append(_cand(card, "option", "s4.imaging_flag", {"text": fl if isinstance(fl, str) else str(fl)}))
    return out


def criteria_index(cards: Iterable[dict]) -> Dict[str, List[str]]:
    """system key → distinct per-grade criteria texts seen in production synthesis (each defines ONE grade)."""
    idx: Dict[str, set] = defaultdict(set)
    for card in cards:
        for c in card.get("classifications") or []:
            if c.get("criteria"):
                idx[system_key(c.get("system", ""))].add(f"{c.get('grade')}: {c['criteria'].strip()}")
    return {k: sorted(v) for k, v in idx.items()}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/additions_map.py tests/test_review_labs.py
git commit -m "feat(review-labs): S4 synthesis card → Additions candidates and criteria-by-system index"
```

### Task C2: pull, gate, adjudicate (± criteria), clinical pass, page

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/gate_c.py`

- [ ] **Step 1: Write `gate_c.py`**

```python
# backend/src/rapid_reports_ai/scripts/review_labs/gate_c.py
"""Gate C: Additions (spec §11).

    python -m rapid_reports_ai.scripts.review_labs.gate_c pull              # enhancement_json for the 41 + criteria index
    python -m rapid_reports_ai.scripts.review_labs.gate_c gate --runs 2     # "already in report" Jev (noul + Choice)
    python -m rapid_reports_ai.scripts.review_labs.gate_c adjudicate [--only id,id]   # arms: nocrit, crit
    python -m rapid_reports_ai.scripts.review_labs.gate_c s1 --runs 2 [--only s1-01,s1-02]
    python -m rapid_reports_ai.scripts.review_labs.gate_c page --adjudicated <jsonl> --clinical <json>
    python -m rapid_reports_ai.scripts.review_labs.gate_c score --labels <json> --adjudicated <jsonl> --s1 <jsonl>"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import List, Optional

from rapid_reports_ai.report_reconcile import Q_CONVEYS

from . import additions_map as AM
from . import common, judgement, label_page, metrics

IN_REPORT_CHOICES = {
    "stated": "The report itself already states this point, in any wording (not merely implied or inferable).",
    "not_stated": "The report does not state this point.",
    "cant_tell": "Whether the report states this point cannot be judged from the text alone.",
}


def candidate_text(c: dict) -> str:
    ev = c["evidence"]
    if c["kind"] == "grade":
        return f"a {ev.get('system')} category for the {c.get('anchor')}"
    if c["kind"] == "threshold":
        return f"the {ev.get('parameter')} threshold {ev.get('threshold')} for the {c.get('anchor')}"
    if c["kind"] in ("follow_up", "option") and ev.get("modality"):
        return f"{ev.get('modality')} follow-up {ev.get('timing') or ''} for the {c.get('anchor')}".strip()
    return f"{ev.get('text')} (for the {c.get('anchor')})"


def cmd_pull(_args) -> None:
    out = common.lab_out("gate_c")
    cases = common.read_json(common.lab_out("gate_b") / "cases.json")
    ids = ",".join(f"'{c['id']}'" for c in cases)
    rows = common.metabase(f"select id::text as id, enhancement_json->'guidelines' as guidelines from reports where id in ({ids})")
    g = {r["id"]: (json.loads(r["guidelines"]) if isinstance(r["guidelines"], str) else r["guidelines"]) or [] for r in rows}
    for c in cases:
        c["guidelines"] = g.get(c["id"], [])
    common.write_json(out / "cases.json", cases)
    allrows = common.metabase("select enhancement_json->'guidelines' as guidelines from reports "
                              "where enhancement_json is not null and created_at >= now() - interval '120 days'")
    cards = [card for r in allrows for card in ((json.loads(r["guidelines"]) if isinstance(r["guidelines"], str)
                                                 else r["guidelines"]) or [])]
    idx = AM.criteria_index(cards)
    common.write_json(out / "criteria_index.json", idx)
    print(f"{sum(1 for c in cases if c['guidelines'])}/41 with synthesis; criteria systems: {sorted(idx)}")


async def _gate(cases: List[dict], runs: int, out_path) -> None:
    from rapid_reports_ai.scripts.jev_tool_lab import calls
    sem = asyncio.Semaphore(4)
    with open(out_path, "a") as fh:
        for run in range(1, runs + 1):
            async def one(c):
                cands = [x for card in c["guidelines"] for x in AM.map_card(card)]
                qs = {}
                for k, x in enumerate(cands):
                    t = candidate_text(x)
                    qs[f"n{k}"] = {"type": "noul", "instructions": Q_CONVEYS + t}
                    qs[f"c{k}"] = {"type": "choice", "criteria": dict(IN_REPORT_CHOICES),
                                   "instructions": f'Read only this one guideline point: "{t}". Does the report state it?'}
                if not qs:
                    return []
                async with sem:
                    ans, _, _ = await calls.jev({f"REPORT:\n{c['report']}": qs})
                return [{"id8": c["id8"], "run": run, "k": k, "candidate": x, "text": candidate_text(x),
                         "noul": (ans.get(f"n{k}") or {}).get("noul"), "choice": ans.get(f"c{k}")} for k, x in enumerate(cands)]
            for rows in await asyncio.gather(*(one(c) for c in cases)):
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def cmd_gate(args) -> None:
    common.load_env()
    cases = common.read_json(common.lab_out("gate_c") / "cases.json")
    if args.only:
        cases = [c for c in cases if c["id8"] in set(args.only.split(","))]
    out = common.out_file("gate_c", "in_report", "jsonl")
    asyncio.run(_gate(cases, args.runs, out))
    print(out)


async def _adjudicate(cases: List[dict], gate_rows: List[dict], out_path) -> None:
    sem = asyncio.Semaphore(8)
    idx = common.read_json(common.lab_out("gate_c") / "criteria_index.json")
    by8 = {c["id8"]: c for c in cases}
    keep = [r for r in gate_rows if r["run"] == 1 and (r["choice"] or {}).get("choice") != "stated"]
    with open(out_path, "a") as fh:
        async def one(r, arm):
            cand = json.loads(json.dumps(r["candidate"]))
            if arm == "crit" and cand["kind"] == "grade":
                crit = idx.get(AM.system_key(cand["evidence"].get("system", "")))
                if not crit:
                    return None
                cand["evidence"]["criteria"] = " | ".join(crit)
            elif arm == "crit":
                return None                                 # the criteria arm only changes grade items
            res = await judgement.judge_and_verify(by8[r["id8"]], [cand], sem)
            return {"id8": r["id8"], "k": r["k"], "arm": arm, "kind_in": cand["kind"], "text": r["text"],
                    "citation": cand.get("citation"), **res}
        rows = await asyncio.gather(*(one(r, a) for r in keep for a in ("nocrit", "crit")))
        for row in rows:
            if row:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def cmd_adjudicate(args) -> None:
    common.load_env()
    cases = common.read_json(common.lab_out("gate_c") / "cases.json")
    gate_rows = common.read_jsonl(args.gate)
    if args.only:
        gate_rows = [r for r in gate_rows if f"{r['id8']}-{r['k']}" in set(args.only.split(","))]
    out = common.out_file("gate_c", "adjudicated", "jsonl")
    asyncio.run(_adjudicate(cases, gate_rows, out))
    print(out)


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pull").set_defaults(fn=cmd_pull)
    g = sub.add_parser("gate"); g.add_argument("--runs", type=int, default=2); g.add_argument("--only", default="")
    g.set_defaults(fn=cmd_gate)
    a = sub.add_parser("adjudicate"); a.add_argument("--gate", required=True); a.add_argument("--only", default="")
    a.set_defaults(fn=cmd_adjudicate)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Pull**

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_c pull`
Expected: `N/41 with synthesis; criteria systems: [...]`.

If N is under 20, the 41 have little stored synthesis. Then extend the case set with the most recent quick reports that have `enhancement_json->'guidelines'` non-empty, up to 41 with synthesis, using the same SQL with `order by created_at desc limit 60`. Record that in the ledger.

- [ ] **Step 3: Smoke-test 2 reports on the gate, then run 2 runs**

Run: `... gate_c gate --runs 1 --only <id8a>,<id8b>`. Expected: rows with `noul` and `choice` set.
Run: `... gate_c gate --runs 2`.

- [ ] **Step 4: Smoke-test 2 candidates on both arms, then adjudicate**

Run: `... gate_c adjudicate --gate <in_report.jsonl> --only <id8a>-0,<id8b>-0`. Expected: rows with `error: null`.
Run: `... gate_c adjudicate --gate <in_report.jsonl>`.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_c.py
git commit -m "feat(review-labs): Gate C pull, already-in-report Jev gate, adjudication with/without criteria"
```

### Task C3: the grade arm on `s1_phase3.json` (100 labelled items) with vs without criteria

Each s1 item becomes a case whose report is a one-section rendering of its dictation, with one `grade` candidate for `item.system`. The decision is read from the judgement's kind: `grade` means gradable, and `characterise` means "can't grade".
- **False "can't grade":** a gradable item judged `characterise` (baseline 0.16).
- **Overcall:** a not-gradable item judged `grade`.

The criteria arm adds `criteria_index[system_key(system)]`. Items whose system has no indexed criteria are reported and excluded from the paired comparison. The production index holds per-grade criteria only (it defines the assigned grade, not the whole system), which is a known weakness of this arm. Record the coverage.

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/review_labs/gate_c.py`

- [ ] **Step 1: Add `cmd_s1` and register `s1 --runs --only`**

```python
def s1_case(item: dict) -> dict:
    return {"scan": item["scan_type"], "history": "", "dictation": item["dictation"],
            "report": "FINDINGS:\n" + item["dictation"].replace("\n", " ") + "\nIMPRESSION:\nSee findings."}


async def _s1(items: List[dict], runs: int, out_path) -> None:
    sem = asyncio.Semaphore(4)
    idx = common.read_json(common.lab_out("gate_c") / "criteria_index.json")
    with open(out_path, "a") as fh:
        for run in range(1, runs + 1):
            async def one(it, arm):
                ev = {"system": it["system"], "finding": it["finding"]}
                if arm == "crit":
                    crit = idx.get(AM.system_key(it["system"]))
                    if not crit:
                        return {"item_id": it["id"], "run": run, "arm": arm, "skipped": "no_criteria"}
                    ev["criteria"] = " | ".join(crit)
                cand = {"lane": "additions", "kind": "grade", "detector": "s1", "line": None,
                        "anchor": it["finding"], "evidence": ev}
                r = await judgement.judge_and_verify(s1_case(it), [cand], sem)
                return {"item_id": it["id"], "run": run, "arm": arm, "kind": r.get("kind"), "cls": r.get("cls"),
                        "label": r.get("label"), "error": r.get("error"), "usage": r.get("usage"),
                        "gradable": it["gradable"], "category": it["category"]}
            for row in await asyncio.gather(*(one(it, a) for it in items for a in ("nocrit", "crit"))):
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def cmd_s1(args) -> None:
    common.load_env()
    items = common.read_json(common.BACKEND / "test_cases" / "jev_tool_lab" / "s1_phase3.json")
    if args.only:
        items = [i for i in items if i["id"] in set(args.only.split(","))]
    out = common.out_file("gate_c", "s1", "jsonl")
    asyncio.run(_s1(items, args.runs, out))
    print(out)
```

Register in `main()`:

```python
    s = sub.add_parser("s1"); s.add_argument("--runs", type=int, default=2); s.add_argument("--only", default="")
    s.set_defaults(fn=cmd_s1)
```

- [ ] **Step 2: Smoke-test 2 items on both arms, then run**

Run: `... gate_c s1 --runs 1 --only s1-01,s1-02`. Expected: 4 rows. If an item has no criteria, its `crit` row is `skipped: no_criteria`; otherwise `error: null`, with `kind` in {grade, characterise}.
Run: `... gate_c s1 --runs 2`. The run-2 stability check may use the 40-item stratified subset `test_cases/jev_tool_lab/s1_phase3_run2_ids.json` (L-50 method). If so, run `--runs 1` on all 100 and then `--runs 1 --only <run2 ids>` with a separate output file.

- [ ] **Step 3: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_c.py
git commit -m "feat(review-labs): Gate C grade arm on s1_phase3 with vs without supplied criteria"
```

### Task C4: Hassan's card read, hard checks, score, ledger

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/review_labs/gate_c.py`
- Test: `backend/tests/test_review_labs.py` (append)

- [ ] **Step 1: Write the failing test for the hard checks**

```python
from rapid_reports_ai.scripts.review_labs import gate_c as GC


def test_hard_checks():
    rep = "FINDINGS:\nA 12 mm lesion.\nIMPRESSION:\nLesion. Recommend MRI."
    row = {"kind": "threshold", "edit_mode": "upgrade", "edit_find": "Recommend MRI.",
           "edit_replace": "Recommend MRI in 6 months; lesions over 40 mm need surgery referral.", "cls": "action"}
    v = GC.hard_violations(row, rep, dictation="12 mm lesion", history="")
    assert "ungrounded_number" in v and "management" in v
    row2 = {"kind": "option", "edit_mode": "insert", "edit_after": "Lesion.", "edit_replace": "Suggest follow-up CT.",
            "cls": "minor"}
    assert "second_recommendation" in GC.hard_violations(row2, rep, dictation="", history="")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q -k hard_checks`
Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Add `hard_violations`, `cmd_page` and `cmd_score`**

```python
_REC = re.compile(r"\b(recommend\w*|suggest\w*|advise\w*|consider|follow-?up)\b", re.I)
_MGMT = re.compile(r"\b(refer\w*|surgery|surgical|prescrib\w*|commence|start(?:ing)?|anticoagul\w*|biopsy should|treat\w*)\b", re.I)
_NUM = re.compile(r"\d+(?:\.\d+)?")


def hard_violations(row: dict, report: str, dictation: str, history: str) -> List[str]:
    """Spec §11 Gate C hard bar, checked in code where possible; the hand read decides the rest."""
    v = []
    new, old = row.get("edit_replace") or "", row.get("edit_find") or ""
    if row.get("kind") in ("grade", "threshold") and set(_NUM.findall(new)) - set(_NUM.findall(old)) - set(_NUM.findall(f"{dictation}\n{history}")):
        v.append("ungrounded_number")
    if _MGMT.search(new):
        v.append("management")
    imp = report.split("IMPRESSION:", 1)[1] if "IMPRESSION:" in report else ""
    if row.get("edit_mode") == "insert" and _REC.search(new) and _REC.search(imp) and (row.get("edit_after") or "") in imp:
        v.append("second_recommendation")
    return v


C_FIELDS = [{"key": "verdict", "label": "Should show as", "type": "choice",
             "options": ["action", "minor", "info", "suppress"], "required": True},
            {"key": "correct", "label": "Correct and useful", "type": "choice", "options": ["yes", "no"]},
            {"key": "in_report", "label": "Already in report", "type": "choice", "options": ["yes", "no"]},
            {"key": "violation", "label": "Hard violation", "type": "choice",
             "options": ["none", "undictated grade/threshold", "management", "second recommendation"]},
            {"key": "note", "type": "text", "label": "Note"}]


def cmd_page(args) -> None:
    out = common.lab_out("gate_c")
    cases = {c["id8"]: c for c in common.read_json(out / "cases.json")}
    rows = [r for r in common.read_jsonl(args.adjudicated) if r["arm"] == "nocrit"]
    clinical = {r["id8"]: r for r in common.read_json(args.clinical)}
    cards = []
    for r in rows:
        c = cases[r["id8"]]
        fix = (f"{r.get('edit_mode')}: «{r.get('edit_find') or r.get('edit_after') or ''}» → «{r.get('edit_replace') or ''}»"
               if r.get("edit_mode") not in (None, "none") else "no edit")
        cards.append({"id": f"{r['id8']}-{r['k']}", "title": f"{r['id8']} · {r['kind_in']} → {r.get('cls')}/{r.get('kind')}",
                      "meta": f"{c['scan']} · {json.dumps(r.get('citation'))}",
                      "blocks": [{"label": "Guideline point", "text": r["text"]},
                                 {"label": "Engine label / reason", "text": f"{r.get('label')}\n{r.get('reason') or ''}"},
                                 {"label": "Fix", "text": fix + "\ncode hard checks: " +
                                  (", ".join(hard_violations(r, c["report"], c["dictation"], c["history"])) or "none")},
                                 {"label": "Full report", "text": c["report"], "collapsed": True},
                                 {"label": "Full dictation", "text": c["dictation"], "collapsed": True}], "hidden": []})
    for id8, r in clinical.items():
        c = cases.get(id8)
        if not c:
            continue
        for key in ("characterise", "safety"):
            for k, s in enumerate(r.get(key) or []):
                cards.append({"id": f"{id8}-cp-{key}-{k}", "title": f"{id8} · clinical pass {key}", "meta": c["scan"],
                              "blocks": [{"label": key, "text": s},
                                         {"label": "Audit items (for comparison)",
                                          "text": "\n".join(f"{a['criterion']} [{a.get('verdict')}]: {a.get('finding') or ''}"
                                                            for a in c.get("audit_items") or []) or "(none)", "collapsed": True},
                                         {"label": "Full report", "text": c["report"], "collapsed": True}], "hidden": []})
        cards.append({"id": f"{id8}-cp-urgency", "title": f"{id8} · urgency {r.get('urgency')}", "meta": c["scan"],
                      "blocks": [{"label": "Urgency reason", "text": r.get("urgency_reason") or "(routine)"},
                                 {"label": "Audit banners", "text": "\n".join(
                                     f"[{a.get('verdict')}] {a.get('banners') or a.get('finding') or ''}"
                                     for a in c.get("audit_items") or [] if a.get("category") == "banner") or "(none)"}],
                      "hidden": []})
    print(label_page.write_page(out / "cards.html", "Gate C · additions read", "gateC-read-v1", cards, C_FIELDS), len(cards))


def cmd_score(args) -> None:
    labels = common.read_json(args.labels)
    adj = common.read_jsonl(args.adjudicated)
    s1 = [r for r in common.read_jsonl(args.s1) if not r.get("skipped") and not r.get("error")]
    res = {}
    act = [r for r in adj if r["arm"] == "nocrit" and r.get("cls") == "action"]
    good = [r for r in act if (labels.get(f"{r['id8']}-{r['k']}") or {}).get("correct") == "yes"]
    res["action_correct_share"] = len(good) / len(act) if act else None
    res["hard_violations_hand"] = sorted(k for k, v in labels.items() if v.get("violation") not in (None, "none"))
    for arm in ("nocrit", "crit"):
        for run in (1, 2):
            rows = [r for r in s1 if r["arm"] == arm and r["run"] == run]
            g = [r for r in rows if r["gradable"]]
            ng = [r for r in rows if not r["gradable"]]
            res[f"s1_{arm}_run{run}"] = {
                "n": len(rows),
                "false_cant_grade": sum(r["kind"] == "characterise" for r in g) / len(g) if g else None,
                "overcall": sum(r["kind"] == "grade" for r in ng) / len(ng) if ng else None,
                "by_category": {cat: sum((r["kind"] == "grade") == r["gradable"] for r in rows if r["category"] == cat) /
                                max(1, sum(1 for r in rows if r["category"] == cat))
                                for cat in sorted({r["category"] for r in rows})}}
    nc = {r["item_id"]: (r["kind"] == "grade") == r["gradable"] for r in s1 if r["arm"] == "nocrit" and r["run"] == 1}
    cr = {r["item_id"]: (r["kind"] == "grade") == r["gradable"] for r in s1 if r["arm"] == "crit" and r["run"] == 1}
    both = [i for i in nc if i in cr]
    b = sum(1 for i in both if cr[i] and not nc[i])
    c = sum(1 for i in both if nc[i] and not cr[i])
    res["crit_vs_nocrit_paired"] = {"n": len(both), "gains": b, "losses": c, "mcnemar_p": metrics.mcnemar_exact(b, c)}
    print(json.dumps(res, indent=1)); print(common.write_json(common.out_file("gate_c", "score"), res))
```

Register in `main()`:

```python
    p = sub.add_parser("page"); p.add_argument("--adjudicated", required=True); p.add_argument("--clinical", required=True)
    p.set_defaults(fn=cmd_page)
    sc = sub.add_parser("score"); sc.add_argument("--labels", required=True); sc.add_argument("--adjudicated", required=True)
    sc.add_argument("--s1", required=True); sc.set_defaults(fn=cmd_score)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q`
Expected: all PASS.

- [ ] **Step 5: Build the page and hand it to Hassan, then score**

Run: `... gate_c page --adjudicated <adjudicated.jsonl> --clinical $RR_LAB_OUT/gate_b/clinical_pass_<pid>.json && open $RR_LAB_OUT/gate_c/cards.html`
Save Hassan's verdicts as `$RR_LAB_OUT/gate_c/labels.json`.

Run: `... gate_c score --labels $RR_LAB_OUT/gate_c/labels.json --adjudicated <adjudicated.jsonl> --s1 <s1.jsonl>`

**Pass (spec §11 C):**
- **Hard:** zero violations in the hand read.
- At least 80% of `action` guideline items correct and useful.
- The clinical pass surfaces the known safety-critical misses with less noise than the audit's recommendations criterion (4/20 useful).
- Urgency tiers agree with the audit's 16/22 useful banners, with no more false banners.
- **s1:** report false "can't grade" (baseline 0.16) and overcalls. `characterise` stays `minor` unless false "can't grade" ≤ 10%.
- **Criteria arm:** adopt it if false "can't grade" drops with no rise in overcall (paired, n ≥ 100 where criteria exist; directional if fewer).

The "already in report" gate is scored from the `in_report` hand labels: noul vs Choice recall and false alarm, plus its band errors via `metrics.errors_by_band`. This is the gate's wording read (§11).

- [ ] **Step 6: Ledger and commit**

Append the next free L-number, "Gate C: additions". It records:
- the synthesis coverage;
- the "already in report" gate wording result;
- the action correctness;
- the hard violations;
- the clinical-pass versus audit comparison;
- the urgency agreement;
- the s1 false "can't grade" and overcall for both arms, and the paired result;
- the criteria-index coverage, and the per-grade-only caveat.

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_c.py tests/test_review_labs.py docs/model-migration/parameter-ledger.md
git commit -m "feat(review-labs): Gate C read page, hard checks, scoring + ledger"
```

---

## Part D: Gate D, production audit of the automatic edits (read-only)

**What is stored** (`reports.candidate_reports[0].quality_check`):
- `flags[]` (`{kind, text, score}`), `clauses_removed`, `edits_applied`, `edits_skipped`, `kept_dictated_negative[]`, `error`.
- **Removed negatives:** a `contradiction` flag whose text `is_negative` and is not in `kept_dictated_negative`. The removed text is the flag's `text`.
- **Insertions:** `omission` flags. **The inserted sentence is not stored**, so it is located in `content` with `best_sentence` on the omitted line and shown for the hand read. `final_report_content` shows whether the radiologist kept it.

### Task D1: pull and reconstruct (test-first for the reconstruction)

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/review_labs/gate_d.py`
- Test: `backend/tests/test_review_labs.py` (append)

- [ ] **Step 1: Write the failing test**

```python
from rapid_reports_ai.scripts.review_labs import gate_d as GD


def test_reconstruct_edits():
    qc = {"flags": [{"kind": "contradiction", "text": "No free fluid", "score": 0.8},
                    {"kind": "contradiction", "text": "Liver enlarged", "score": 0.7},
                    {"kind": "omission", "text": "Small left pleural effusion", "score": 0.1}],
          "kept_dictated_negative": [], "clauses_removed": 1, "edits_applied": 1}
    content = "FINDINGS:\nThe liver is normal. There is a small left pleural effusion.\nIMPRESSION:\nEffusion."
    final = content.replace(" There is a small left pleural effusion.", "")
    edits = GD.reconstruct(qc, content, final)
    rem = [e for e in edits if e["type"] == "removal"]
    ins = [e for e in edits if e["type"] == "insertion"]
    assert [e["text"] for e in rem] == ["No free fluid"]          # the positive contradiction is never auto-removed
    assert ins[0]["located"] == "There is a small left pleural effusion."
    assert ins[0]["kept_by_user"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q -k reconstruct`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write `gate_d.py` with `reconstruct` and `pull`**

```python
# backend/src/rapid_reports_ai/scripts/review_labs/gate_d.py
"""Gate D: read-only production audit of the automatic edits since L-49 (spec §9, §11).

    python -m rapid_reports_ai.scripts.review_labs.gate_d pull [--since 2026-10-01]
    python -m rapid_reports_ai.scripts.review_labs.gate_d page
    python -m rapid_reports_ai.scripts.review_labs.gate_d rescore [--only key,key]
    python -m rapid_reports_ai.scripts.review_labs.gate_d decide --labels <json> --rescored <jsonl>"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import List, Optional

from rapid_reports_ai.report_review import is_negative

from . import common, judgement, label_page


def reconstruct(qc: dict, content: str, final: Optional[str]) -> List[dict]:
    kept = {k.get("text") for k in qc.get("kept_dictated_negative") or []}
    edits = []
    for f in qc.get("flags") or []:
        if f["kind"] == "contradiction" and is_negative(f["text"]) and f["text"] not in kept:
            edits.append({"type": "removal", "text": f["text"], "score": f.get("score"),
                          "still_absent": f["text"].lower() not in content.lower()})
        elif f["kind"] == "omission":
            a, b = common.best_sentence(content, f["text"])
            located = content[a:b].strip()
            edits.append({"type": "insertion", "text": f["text"], "score": f.get("score"), "located": located,
                          "kept_by_user": None if final is None else located in final})
    return edits


SQL = """select id::text as id, created_at::text as created_at, report_type, input_data,
       candidate_reports->0->>'content' as content, final_report_content,
       candidate_reports->0->'quality_check' as qc
from reports
where created_at >= '{since}' and candidate_reports->0->'quality_check' is not null
  and (coalesce((candidate_reports->0->'quality_check'->>'clauses_removed')::int, 0) > 0
       or coalesce((candidate_reports->0->'quality_check'->>'edits_applied')::int, 0) > 0)
order by created_at"""


def cmd_pull(args) -> None:
    rows = common.metabase(SQL.format(since=args.since))
    out = []
    for r in rows:
        qc = json.loads(r["qc"]) if isinstance(r["qc"], str) else r["qc"]
        inp = json.loads(r["input_data"]) if isinstance(r["input_data"], str) else (r["input_data"] or {})
        v = inp.get("variables") or {}
        for k, e in enumerate(reconstruct(qc, r["content"] or "", r["final_report_content"])):
            out.append({"key": f"{r['id'][:8]}-{k}", "report_id": r["id"], "created_at": r["created_at"],
                        "report_type": r["report_type"], "scan": v.get("SCAN_TYPE") or "", "dictation": v.get("FINDINGS") or "",
                        "history": v.get("CLINICAL_HISTORY") or "", "content": r["content"] or "",
                        "final": r["final_report_content"], **e})
    p = common.write_json(common.lab_out("gate_d") / f"edits_since_{args.since}.json", out)
    by = {t: sum(1 for e in out if e["type"] == t) for t in ("removal", "insertion")}
    print(p, len(rows), "reports", by)


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull"); p.add_argument("--since", default="2026-10-01"); p.set_defaults(fn=cmd_pull)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_review_labs.py -q`
Expected: all PASS.

- [ ] **Step 5: Pull**

Run: `.venv/bin/python -m rapid_reports_ai.scripts.review_labs.gate_d pull`
Expected: the counts by type. If either type has fewer than 20 edits, re-run with `--since 2026-09-30` (L-47). Hand reading is per type, so the type that is short gets the extension. If it is still under 20, note in the ledger that the read is directional, as allowed by spec §11 D ("or replay the current code on earlier reports" is the fallback, and only if Hassan asks).

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_d.py tests/test_review_labs.py
git commit -m "feat(review-labs): Gate D pull and reconstruction of automatic edits"
```

### Task D2: hand-read page, re-score through the lab adjudicator, decide

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/review_labs/gate_d.py`

- [ ] **Step 1: Add `cmd_page`, `cmd_rescore` and `cmd_decide`, and register them**

```python
D_FIELDS = [{"key": "verdict", "label": "This automatic edit was", "type": "choice",
             "options": ["correct", "redundant", "harmful"], "required": True},
            {"key": "harm", "label": "Harm type", "type": "choice",
             "options": ["invented", "duplicated", "incoherent", "whole-line rewrite", "other"]},
            {"key": "note", "type": "text", "label": "Note"}]


def _latest_edits() -> List[dict]:
    """The widest window pulled (the earliest --since is a superset of later ones)."""
    files = sorted(common.lab_out("gate_d").glob("edits_since_*.json"))
    return common.read_json(files[0])


def cmd_page(_args) -> None:
    cards = []
    for e in _latest_edits():
        what = (f"REMOVED from the report: «{e['text']}»" if e["type"] == "removal"
                else f"INSERTED for the dictated line «{e['text']}»\nlocated sentence: «{e['located']}»\n"
                     f"radiologist kept it: {e['kept_by_user']}")
        cards.append({"id": e["key"], "title": f"{e['key']} · {e['type']}", "meta": f"{e['scan']} · {e['created_at'][:16]}",
                      "blocks": [{"label": "Automatic edit", "text": what},
                                 {"label": "Report as shown", "text": e["content"],
                                  "highlight": [e.get("located") or ""], "collapsed": True},
                                 {"label": "Dictation", "text": e["dictation"], "highlight": [e["text"]], "collapsed": True},
                                 {"label": "Final (radiologist)", "text": e.get("final") or "(not finalised)", "collapsed": True}],
                      "hidden": []})
    print(label_page.write_page(common.lab_out("gate_d") / "edits.html", "Gate D · automatic edits",
                                "gateD-edits-v1", cards, D_FIELDS), len(cards))


def pre_edit(e: dict) -> str:
    """The report before the edit: insertion → the located sentence deleted; removal → the clause re-added at the
    end of FINDINGS (position approximate, recorded in the ledger as a limitation)."""
    if e["type"] == "insertion":
        return e["content"].replace(e["located"], "", 1)
    c = e["content"]
    i = c.find("\nIMPRESSION:")
    return (c[:i] + f" {e['text']}." + c[i:]) if i >= 0 else c + f"\n{e['text']}."


async def _rescore(edits: List[dict], out_path) -> None:
    sem = asyncio.Semaphore(8)

    async def one(e):
        case = {"scan": e["scan"], "dictation": e["dictation"], "history": e["history"], "report": pre_edit(e)}
        cand = ({"lane": "coverage", "kind": "absent", "detector": "jev.classify_first", "line": e["text"], "anchor": None,
                 "evidence": {}} if e["type"] == "insertion" else
                {"lane": "accuracy", "kind": "contradicted", "detector": "jev.contradiction", "line": None,
                 "anchor": e["text"], "evidence": {}})
        r = await judgement.judge_and_verify(case, [cand], sem)
        would = bool(r.get("cls") == "action" and r.get("verified") and r["verified"]["code"]
                     and not r["verified"].get("unconfirmed") and r.get("kind") != "slip"
                     and ((e["type"] == "insertion" and r.get("kind") == "absent" and r.get("edit_mode") == "insert")
                          or (e["type"] == "removal" and r.get("edit_mode") == "remove")))
        return {"key": e["key"], "type": e["type"], "would_pre_apply": would, **r}
    with open(out_path, "w") as fh:
        for row in await asyncio.gather(*(one(e) for e in edits)):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def cmd_rescore(args) -> None:
    common.load_env()
    edits = _latest_edits()
    if args.only:
        edits = [e for e in edits if e["key"] in set(args.only.split(","))]
    out = common.out_file("gate_d", "rescored", "jsonl")
    asyncio.run(_rescore(edits, out))
    print(out)


def cmd_decide(args) -> None:
    labels = common.read_json(args.labels)
    rows = common.read_jsonl(args.rescored)
    res = {}
    for t in ("insertion", "removal"):
        mine = [r for r in rows if r["type"] == t]
        routed = [r for r in mine if r["would_pre_apply"]]
        lab = [labels.get(r["key"], {}).get("verdict") for r in routed]
        today = [labels.get(r["key"], {}).get("verdict") for r in mine]
        correct = sum(v == "correct" for v in lab) / len(lab) if lab else None
        res[t] = {"n_today": len(mine), "today": {v: today.count(v) for v in ("correct", "redundant", "harmful")},
                  "n_routed_pre_apply": len(routed), "routed_correct_share": correct,
                  "routed_harmful": sum(v == "harmful" for v in lab),
                  "option": "A" if (correct is not None and correct >= 0.95 and not any(v == "harmful" for v in lab)) else "B"}
    print(json.dumps(res, indent=1)); print(common.write_json(common.out_file("gate_d", "decision"), res))
```

Register in `main()`:

```python
    sub.add_parser("page").set_defaults(fn=cmd_page)
    r = sub.add_parser("rescore"); r.add_argument("--only", default=""); r.set_defaults(fn=cmd_rescore)
    d = sub.add_parser("decide"); d.add_argument("--labels", required=True); d.add_argument("--rescored", required=True)
    d.set_defaults(fn=cmd_decide)
```

- [ ] **Step 2: Build the page and hand it to Hassan**

Run: `... gate_d page && open $RR_LAB_OUT/gate_d/edits.html`
Save the verdicts as `$RR_LAB_OUT/gate_d/labels.json`.

- [ ] **Step 3: Smoke-test 2 edits (one of each type), then re-score all**

Run: `... gate_d rescore --only <ins-key>,<rem-key>`. Expected: 2 rows, `error: null`.
Run: `... gate_d rescore`.

- [ ] **Step 4: Decide**

Run: `... gate_d decide --labels $RR_LAB_OUT/gate_d/labels.json --rescored <rescored.jsonl>`

**Rule (spec §11 D), per edit type:** option A if, routed through the engine, the edit is ≥ 95% correct with zero harmful; otherwise option B. **Hassan confirms the decision.**

- [ ] **Step 5: Ledger and commit**

Append the next free L-number, "Gate D: automatic edits". It records:
- the counts and window;
- today's correct / redundant / harmful per type;
- the routed result per type;
- the decision (A or B per type) and Hassan's confirmation;
- the limitations (insertion located by sentence match; removal re-inserted at the end of FINDINGS for re-scoring).

```bash
git add src/rapid_reports_ai/scripts/review_labs/gate_d.py docs/model-migration/parameter-ledger.md
git commit -m "feat(review-labs): Gate D hand-read page, engine re-score, decision + ledger"
```

---

## After the four gates

- Update the spec §6–§9 only where a gate changed a design choice: the adopted `inconsistent` arm, the B2 wording or code-only, the criteria arm, the Gate D option per edit type. Each change cites its L-number.
- Carry the adopted adjudicator prompt (`prompts/adjudicator_v4.txt`, as revised by Gate A) into Plan 2 Task 8 verbatim.
- Update memory `project_template_mirror_decisions` / the review-engine memory with the gate outcomes (one line each).

## Self-review notes

- **Spec coverage:**
  - Gate A: 27 labels, all ~72 adjudicated, balance via synthetic, bar, stability.
  - B1: alignment ≥ 95%, code catches, false alarms ≤ 1, inconsistent arms.
  - B2: wordings × noul/Choice, exit option, bands, calibration, unsure pile, escalation.
  - C: hard bar, ≥ 80% action correct, clinical pass vs audit, urgency, s1 false "can't grade", criteria arm, "already in report" wording.
  - D: window, hand classes, re-score, rule.
  - The §11 "targeted follow-ups" item is out of scope by design: it is demoted by L-50 and §6.5, and needs a confusion pair that Qwen also gets wrong first.
- **Known limits, recorded in the ledger:**
  - The criteria index holds per-grade criteria only.
  - Gate D insertion text is located, not stored.
  - B1c runs only after Plan 2 Tasks 2–3.
