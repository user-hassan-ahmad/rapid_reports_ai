# Jev wording v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the Jev wording-suite results (2026-10-01): new question wordings and thresholds, Jev replacing regex selection where it judges meaning, and the hedged-branch label. Two parts: **Part Q** changes live quick, on the hotfix branch off `main`, together with the split fix. **Part T** is template-only, on `feat/template-pipeline-mirror`.

**Architecture:** Each change swaps a question string or threshold, or replaces a regex judgement with a batched Jev question inside a call we already make. Code still decides; Jev classifies. Every Jev failure falls back to today's behaviour (fail-open where it was fail-open before). Evidence and exact arm definitions are in `/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/9e672c4e-4eef-41cc-a40f-806516ac58ef/scratchpad/jev_wording_suite/{A..E}*/` (run.py / arms.py per group).

**Tech Stack:** Python 3.12, pytest, httpx Jev client (`_jev(state, questions)`), pydantic-ai Qwen.

**User decisions (2026-10-01):**
1. Omitted dictated negatives are inserted back. This restores dictated content, never turns a negative into a finding.
2. "Organ unremarkable" does not make a specific negative option a repeat; the option is kept.
3. Hedged branches get a present-vs-possible question in the same call and an "address as a possibility" label. The label's header text joins the global_style_guide sign-off package, so code only stages it.
4. Quick changes go as one change on the hotfix branch with the split fix, validated by re-scoring production quick reports (Jev only) and a hand read, with one ledger entry per question.

**Jev polarity rule (group D):** a noul's `instructions` and `criteria.true` must point the same way. Criteria cannot invert an instruction.

---

## Shared constants (used by both parts; Part Q defines them in main's modules, Part T ports them on rebase)

```python
HEDGE = "(?, possible, query, cannot exclude, versus, no definite, equivocal)"

# One wording for "is it already in the report?" (group A, S2). Thresholds differ per use.
Q_CONVEYS = ("The report itself states everything this statement says, in any wording, abbreviation or synonym "
             "(not merely implied or inferable): ")
OMIT_FLAG = 0.40        # omission check: flag when score < 0.40  (stated >= 0.51, omitted <= 0.31)
INSERT_DUP = 0.25       # inserter guard: skip a sentence when score >= 0.25 (conveyed >= 0.32, new <= 0.14)
ALREADY_DROP = 0.85     # option uniqueness gate (Part T): drop when score >= 0.85

# If-present finding presence: score type, value = score / 3, route_finding cut-offs unchanged (group B).
def q_finding(key: str) -> dict:
    return {"type": "score",
            "instructions": "How definitely do the dictated findings report this imaging finding as present? Finding: " + key,
            "criteria": ["Stated as absent or normal",
                         "Not mentioned, or only a different finding is reported",
                         "Raised only as a possibility " + HEDGE,
                         "Reported as present, in any wording or size"]}

# Diagnosis / branch presence (group B, R3; R2 when the line has no discriminator).
PRESENT_TRUE = ("The dictation names this diagnosis (or a synonym or abbreviation), or describes findings that point to it, "
                "including when it is raised as a possibility " + HEDGE + ".")
PRESENT_FALSE = ("The diagnosis is not mentioned, is excluded, or the dictated findings are explained as a different "
                 "diagnosis, even one in the same organ or sharing a sign.")
def q_present(name: str, discriminator: str = "") -> dict:
    instr = "The dictated findings name or describe this diagnosis as present or possible in this case: " + name
    if discriminator:
        instr += ". A typical sign (an example only; it need not be dictated): " + discriminator
    return {"type": "noul", "instructions": instr, "criteria": {"true": PRESENT_TRUE, "false": PRESENT_FALSE}}

# Removal confirmation for a flagged report negative (group B, S1).
def q_restated(finding: str) -> dict:
    return {"type": "noul", "instructions": "The dictated findings report this finding, including as a possibility: " + finding,
            "criteria": {"true": "This same finding is reported, in any wording (synonym, abbreviation, or a more specific "
                                 "form of it), as present or possible.",
                         "false": "It is not mentioned, is stated as absent or normal, or the dictation reports a different "
                                  "finding that only shares some words with it (a different qualifier such as size, "
                                  "severity, pattern, chronicity or location)."}}

# Recommendation condition, asked with met polarity; unmet = 1 - score (group D, R2).
Q_REC_MET = "The dictated findings show the finding or diagnosis this recommendation is for. Recommendation: "

# Sheet negatives the findings make untrue: Jev choice, OR'd with Qwen's label (group C, ECH). n=50, directional:
# shipped only if the production re-score (Task Q9) holds.
def q_negative_relation(neg: str) -> dict:
    return {"type": "choice", "instructions": "How does this negative statement relate to the dictated findings? Negative: " + neg,
            "criteria": {"contradicted": "The dictation reports the denied finding as present, or a finding of the same kind in the same place",
                         "expected": "A dictated finding would normally and predictably cause what the negative denies (not merely make it possible)",
                         "keep": "Neither: the negative can stand beside the dictated findings"}}
```

Score readers: noul → `float(a["noul"])`; score → `float(a["score"]) / 3`; choice → `a["probabilities"][label]` (check the real response shape in `scratchpad/jev_synonym_probe/jevlib.py` and the API memory: choice returns `choice`, `confidence`, `probabilities`).

---

# Part Q — live quick (branch `fix/quick-split-and-classifier`, worktree `/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/agent-aa95f141202d2c290`, files `backend/src/rapid_reports_ai/quick_report_brief.py`, `quick_report_quality.py`)

### Task Q0: Commit Fix 3 (USER)
The option-dedup fix is written and tested but uncommitted (the auto-mode classifier blocked the agent's commit). The user runs:
`! cd /Users/hassan/Code/rapid_reports_ai/.claude/worktrees/agent-aa95f141202d2c290 && git add backend/src/rapid_reports_ai/quick_report_brief.py backend/tests/test_confirmed_negatives.py && git commit -m "fix(quick): offered negatives never duplicate a stated or dictated negative"`
Tasks Q1–Q8 start after this.

### Task Q1: Omission check — shared wording, threshold 0.40, no background filter
**Files:** Modify `quick_report_quality.py` (Q_OMIT, OMIT_FLAG, `positive_items`, the omission question builder, `insert_findings` negation guard). Test `backend/tests/test_quick_report_quality.py` (or the existing quality test module).

- [ ] **Step 1: Failing tests**
```python
def test_omission_question_uses_conveys_wording(monkeypatch):
    asked = {}
    async def fake_jev(state, qs):
        if state.startswith("REPORT:"):
            asked.update(qs)
        return {k: {"noul": 0.9} for k in qs}
    monkeypatch.setattr(qq.qb, "_jev", fake_jev)
    asyncio.run(qq.check("FINDINGS:\nThe appendix is unremarkable.", "appendix fine. 5 mm defect D1", "CT", []))
    omit = [q["instructions"] for k, q in asked.items() if k.startswith("i")]
    assert omit and all(t.startswith(qq.Q_CONVEYS) for t in omit)

def test_every_split_item_is_checked_including_normals_and_negatives():
    assert qq.positive_items("appendix fine. no ascites. liver normal, 2cm cyst L kidney") == [
        "appendix fine", "no ascites", "liver normal, 2cm cyst L kidney"]

def test_omission_flag_threshold_is_040(monkeypatch):
    async def fake_jev(state, qs):
        return {k: {"noul": 0.45 if k == "i0" else 0.35} for k in qs}
    monkeypatch.setattr(qq.qb, "_jev", fake_jev)
    r = asyncio.run(qq.check("FINDINGS:\nx.", "item a. item b", "CT", []))
    assert [f.text for f in r.flags if f.kind == "omission"] == ["item b"]

def test_inserted_negative_must_come_from_an_omitted_negative_item():
    assert qq._negative_allowed("No ascites.", ["no ascites"])
    assert not qq._negative_allowed("No free fluid.", ["no ascites", "5 mm defect"])
```
- [ ] **Step 2:** Run `poetry run pytest tests/test_quick_report_quality.py -q`; expect FAIL.
- [ ] **Step 3: Implement**
  - Add `Q_CONVEYS` and set `OMIT_FLAG = 0.40`. In the omission question builder replace `Q_OMIT + t` with `Q_CONVEYS + t`. Keep `Q_OMIT` only if something else imports it; otherwise delete it.
  - Change `positive_items` to `return qb.split_findings(findings)`, and rename it to `dictated_items` with an alias for any importer. Delete `_BACKGROUND`. Docstring: "every dictated item is checked (wording v2: the conveys question handles shorthand normals; negatives omitted from the report are restored)".
  - Replace the per-sentence negation guard in `insert_findings` with `_negative_allowed(sentence, items)`. A sentence containing negation is allowed only when some omitted item that contains negation shares a content word of 4+ letters with it (lower-case, filler words removed). Use it where `_NEGATION.search(sent) and not any(...)` is now.
- [ ] **Step 4:** Run the module tests plus the full suite, `poetry run pytest -q`; expect PASS.
- [ ] **Step 5:** Commit `feat(quick-check): omission check asks the conveys question at 0.40 and checks every dictated item (Jev wording v2)`.

### Task Q2: Inserter duplicate guard — Jev instead of word overlap
**Files:** Modify `quick_report_quality.py` (`insert_findings`, `_restates` kept as fallback). Test the same module.

- [ ] **Step 1: Failing tests**
```python
def test_inserter_skips_sentence_jev_says_is_conveyed(monkeypatch):
    async def fake_run(**kw):
        return SimpleNamespace(output=qq.Insertions(items=[qq.Insertion(after="", sentence="The appendix is fine.")]))
    async def fake_jev(state, qs):
        return {k: {"noul": 0.9} for k in qs}
    monkeypatch.setattr(qq, "_run_agent_with_model", fake_run)
    monkeypatch.setattr(qq.qb, "_jev", fake_jev)
    r = asyncio.run(qq.insert_findings("FINDINGS:\nThe appendix is unremarkable.", "appendix fine", ["appendix fine"]))
    assert r.applied == 0 and "fine" not in r.report

def test_inserter_falls_back_to_word_overlap_when_jev_fails(monkeypatch):
    ...  # same insertion; fake_jev raises httpx.ReadTimeout; "The appendix is unremarkable." restated by
         # _restates -> skipped; a new sentence ("5 mm defect at D1.") -> applied
```
(Write the second test in full with `pytest.raises`-free assertions on `applied` and `report`, mirroring the first.)
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3: Implement.** After the Qwen insertions return, collect the candidate sentences. Ask one Jev call: state `"REPORT:\n" + without(report, protected, ...)`, questions `{f"d{i}": {"type": "noul", "instructions": Q_CONVEYS + s}}`. Skip a sentence when its score ≥ `INSERT_DUP` (0.25). On any Jev exception, use `_restates` exactly as today. Telemetry: `skipped` counts both paths; add `dup_check: "jev" | "words"` to RepairResult.
- [ ] **Step 4:** Run tests; expect PASS. **Step 5:** Commit `feat(quick-check): inserter skips sentences Jev says the report already conveys (word overlap is the fallback)`.

### Task Q3: If-present finding presence — score type
**Files:** Modify `quick_report_brief.py` (where `Q_FINDING` questions are built, and the score reader near line 476). Test `backend/tests/test_quick_report_brief.py`.

- [ ] **Step 1: Failing tests**
```python
def test_finding_questions_are_score_type():
    q = qb.q_finding("Free air")
    assert q["type"] == "score" and len(q["criteria"]) == 4

def test_finding_score_reads_level_over_three():
    assert qb.finding_presence({"score": 3.0}) == 1.0
    assert abs(qb.finding_presence({"score": 2.0}) - 0.6667) < 1e-3   # hedged -> offered band
    assert qb.route_finding("keep", qb.finding_presence({"score": 2.0}), "core") == "offered"
```
(Check `route_finding`'s real return labels and argument order on main before fixing the assertion text.)
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Add `HEDGE`, `q_finding`, and `finding_presence(a) = float(a["score"]) / 3`. Build the If-present key questions with `q_finding(key)` and read their answers with `finding_presence`. Leave every other key on the noul reader. **Step 4:** PASS. **Step 5:** Commit `feat(quick-brief): If-present presence is a graded score (absent / possible / present)`.

### Task Q4: Branch presence — name the diagnosis, sign as example only
**Files:** `quick_report_brief.py` (Q_PRESENT builder). Quick differential lines are `"<name> — <discriminator> *(visible …)*"`; split the name on `" — "` and strip the visibility tag from the discriminator.

- [ ] **Step 1: Failing tests**
```python
def test_present_question_names_diagnosis_and_marks_sign_as_example():
    q = qb.present_question("Perforated peptic ulcer — perigastric fluid and free gas *(visible on this technique: yes)*")
    assert q["instructions"].startswith("The dictated findings name or describe this diagnosis as present or possible in this case: Perforated peptic ulcer")
    assert "an example only" in q["instructions"] and "visible" not in q["instructions"]
    assert q["criteria"]["true"] == qb.PRESENT_TRUE

def test_present_question_without_discriminator_has_no_sign_clause():
    q = qb.present_question("Haemorrhage *(imaging-silent)*")
    assert "example only" not in q["instructions"] and q["instructions"].endswith(": Haemorrhage")
```
- [ ] Steps 2–5 as above. Commit `feat(quick-brief): branch presence names the diagnosis; the discriminator is an example only`.

### Task Q5: Removal confirmation — hedged findings count
**Files:** `quick_report_quality.py` (Q_RESTATED use). Test: `q_restated("pneumothorax")` has criteria. A check where the dictation is "?pneumothorax" and the report says "No pneumothorax." with a contradiction score of 0.8 removes the clause when the stubbed restated score is 0.6 (threshold unchanged at 0.5). Commit `feat(quick-check): a report negative contradicting a hedged dictated finding is removed`.

### Task Q6: Recommendation condition — ask with met polarity
**Files:** `quick_report_brief.py` (the rec question builder and `score(f"r{k}") >= 0.5` near line 334).

- [ ] **Step 1: Failing test**
```python
def test_recommendation_unmet_is_one_minus_met(monkeypatch):
    # stub Jev so r0 (routine US for ?appendicitis) scores met 0.7 -> unmet 0.3 -> kept
    ...
    assert "US" in kept_recommendation_texts
```
(Write it against the function that consumes the `r{k}` scores. Assert the question text starts with `Q_REC_MET`, and that a met score of 0.3 removes the recommendation while 0.7 keeps it.)
- [ ] Implement: question `Q_REC_MET + t`, unmet = `1 - score`, threshold unchanged (≥ 0.5 removes). Commit `fix(quick-brief): recommendation condition asked with met polarity; Jev no longer judges warrant`.

### Task Q7: Negatives the findings make untrue — Jev choice OR Qwen (gated by Q9)
**Files:** `quick_report_brief.py`. Add `q_negative_relation(neg)` questions (keys `x{i}`) to the existing findings-state Jev call, built on the same negatives list the Qwen classifier receives after the split. If the split runs alongside Jev, ask over the pre-split negatives and map each split part to its parent. A negative Qwen labels `keep` becomes Jev's label when `1 - P(keep) >= 0.5` (the higher of contradicted / expected). Log `decisions["negative_or"]` entries `{text, qwen, jev, final}`. Behind env `RR_NEG_JEV_OR` (default **off** until Q9). Tests cover: off → today's labels unchanged; on, with Qwen keep and Jev P(keep) 0.3 → the label becomes Jev's argmax; Jev failure → Qwen's labels unchanged. Commit `feat(quick-brief): Jev relation check OR'd with Qwen's negative label (flagged off)`.

### Task Q8: Ledger and memory
Add **L-49 Jev wording v2** to `docs/model-migration/parameter-ledger.md`: per-question old and new wording, threshold, DEV/HOLDOUT evidence (cite the scratchpad group folders), user decisions 1–2, and the polarity and drift lessons. Commit `docs(ledger): L-49 Jev wording v2`.

### Task Q9: Production re-score and hand read (no regeneration)
Script `backend/src/rapid_reports_ai/scripts/jev_v2_rescore.py` (lab, no prod writes). Read access to prod is standing permission; keep data in the scratchpad.
- Pull the latest 150 quick reports, each with its dictation, stored brief decisions and quality telemetry. Use the Railway CLI or Metabase `/api/dataset` (see memory reference_prod_smoke_testing).
- For each, run old and new questions on the same inputs:
  - omission: items, flags and would-insert;
  - If-present bands;
  - branch presence;
  - recommendation removal;
  - the Q7 relation (old vs OR).
- Output `scratchpad/jev_v2_rescore_<pid>/changed.md`, listing every changed decision with dictation context, and `summary.md` with counts per question.
- **Gate:** the hand read finds no change that makes a report less safe; Q7 is enabled only if its changes read correct. Report to the user before any merge.

---

# Part T — templates (branch `feat/template-pipeline-mirror`, repo root `/Users/hassan/Code/rapid_reports_ai`)

Runs alongside Part Q. Shared questions (Q1–Q6) arrive on rebase onto main after Part Q merges. At that point port them into `report_reconcile.py` / `report_review.py`, keeping the golden quick tests passing with fixtures updated only for the deliberate question changes.

### Task T1: Option uniqueness gate — conveys wording, 0.85
**Files:** `report_reconcile.py` (`Q_ALREADY`, `gate_apply`), `tests/test_option_gate.py`. Replace `Q_ALREADY` with `Q_CONVEYS`. Drop when ≥ `ALREADY_DROP` (0.85). Tests: 0.84 kept, 0.85 dropped. Question text starts with `Q_CONVEYS`; impression-scope questions are unchanged in routing. Commit `feat(options): uniqueness gate asks the conveys question, drops at 0.85`.

### Task T2: History/protocol conditions — criteria wording at 0.5
**Files:** `template_brief.py` (`Q_CONDITION`, `CTX_MET`). New question:
```python
{"type": "noul", "instructions": "Is this condition stated for this case? Condition: " + cond,
 "criteria": {"true": "Stated: the history, protocol or dictation says this, in any wording (synonyms, abbreviations and shorthand count; a condition worded in the negative is met when the text says that thing was not done or is absent).",
              "false": "Not stated: the text says the opposite, says nothing about it, or only raises it as a question. Silence is not met."}}
```
Rename `CTX_MET` → `MET = 0.5`. Update the boundary tests: 0.49 not met, 0.5 met; the CMR "mapping not acquired" shape is still not met. Commit `feat(template-brief): conditions asked with criteria; one 0.5 cut-off`.

### Task T3: LIST_MISSING item presence
**Files:** `template_brief.py` (`Q_STATED`). New question:
```python
{"type": "noul", "instructions": "The dictated findings state this item, with its value or result: " + item,
 "criteria": {"true": "The dictation gives this item's value, grade or result, in any wording or abbreviation, including a negative result (such as 'no X'). A value written after a structure's name belongs to that structure.",
              "false": "The item is not given: it is not mentioned, not assessed, described only in general words without the value it needs, or the only value given belongs to a different item or structure."}}
```
Test: stubbed 0.6 for "LGE" with dictation "no LGE" → no MISSING line. Commit `feat(template-brief): LIST_MISSING counts a negative result as stated`.

### Task T4: Phase 1 — Jev replaces `_duplicates_template` and `_is_bundled` for case negatives
**Files:** `case_analyser.py` (`parse_and_check` gains an async wrapper `parse_and_check_async(raw, summary, template_sheet, *, jev=rc._jev)` used by the Phase 1 entry point; the sync version stays for the lab and tests). One batched Jev call per Phase 1 run:
- duplicate (group E, C_choice). State `"TEMPLATE STATEMENTS (written on every report from this template):\n" + "\n".join("- " + s for s in template_negatives_and_normals)`; per negative `{"type": "choice", "instructions": f'How does this case negative relate to the template? "{neg}"', "criteria": {"same": "A template statement already denies this same finding in the same structure, in any wording (synonym, abbreviation, list item, normal-size or normal-calibre statement)", "narrower": "The negative names a narrower finding or sub-site, or a specific finding that a template 'normal' or 'unremarkable' sentence only implies", "different": "No template statement denies this finding: a different finding, a different structure, or a broader claim than the template makes"}}`. Reject when P(same) ≥ 0.5.
- bundled (group E, B2). The same call; the state is not used: `{"type": "noul", "instructions": "This negative could be split into two or more shorter negatives, each of which could be true or false on its own: " + neg, "criteria": {"true": "It denies two or more different findings, or one finding at two or more named sites or structures that could each be present or absent on its own, whether joined by commas, 'or', 'and', 'nor', a slash or a semicolon.", "false": "It denies a single finding: any comma or 'or' only adds qualifiers or adjectives to that one finding, gives a size or percentage threshold ('or more'), restates the same finding in other words, or covers all its types ('acute or chronic')."}}`. Reject (R_BUNDLED) when ≥ 0.6.
- If Jev fails: today's regex checks.
- Tests (stubbed Jev):
  - "No ascites" vs template "No free fluid" with P(same) 0.9 → rejected;
  - "No left atrial thrombus" vs "No left ventricular thrombus. The left atrial size is normal." with P(same) 0.1 → kept (the regex used to reject it);
  - "No focal, suspicious lesion" with bundled 0.2 → kept;
  - Jev error → regex result.
- Commit `feat(case-analyser): duplicate and bundled checks by Jev (regex is the fallback)`.

### Task T5: Hedged branches — present vs possible
**Files:** `template_brief.py` (differential routing and labels). Ask both in the same findings-state call:
- `q_present(name, discriminator)`; it arrives with the rebase, so until then add it locally in `report_reconcile` with the exact Shared-constants text;
- the possible-vs-present choice: `{"type": "choice", "instructions": "How do the dictated findings relate to this diagnosis? Diagnosis: " + name, "criteria": {"named": "The diagnosis is named, abbreviated or given a synonym as present", "described": "Findings pointing to this diagnosis are described without naming it", "possible": "It is raised only as a possibility " + HEDGE, "other": "The dictated findings are explained as a different diagnosis, or share a sign with a different diagnosis", "absent": "Not mentioned, or excluded"}}`.

When present ≥ 0.5 and P(possible) ≥ 0.5, the label is `ADDRESS AS POSSIBLE` instead of `ADDRESS`. Stage the header line in `docs/superpowers/specs/2026-10-01-template-two-phase-design.md` under "Sign-off package":

> "ADDRESS AS POSSIBLE — the dictation raises this as a possibility; the impression keeps the hedge."

Do not edit global_style_guide.py. Tests: present 0.9 with possible 0.8 → `ADDRESS AS POSSIBLE`; present 0.9 with possible 0.1 → `ADDRESS`. Commit `feat(template-brief): hedged branches are addressed as a possibility`.

### Task T6: Why the post-generation option check kept "No extraluminal gas at the colon"
Investigation only. Group C scores the string 0.72–0.88 against large free gas under Q_CONTRA. Re-run `report_review.check` on `scratchpad/e2e_small_u_22096` d1 with the options exactly as passed. Find out whether case-exclusion options reach `check()` with a `sentence`, and whether the option contradiction keys were asked. Fix with a test if it is a wiring gap. Commit `fix(...)` or report "no gap" with evidence.

### Task T7: Rerun 3 cases
Re-run ct_ap_acute-d1, ct_ap_acute-d3 and cmr_cardiomyopathy-d2, NEW arm only, reusing sheets from `e2e_small_s_64800`, into `scratchpad/e2e_small_v_<pid>/`. Hand read: reports, options (unique / consistent / pertinent), repair edits (no duplicates), latency, Jev calls per generation.
