"""Tests for the Qwen sheet-budget experiment harness.

Spec: docs/superpowers/specs/2026-08-12-qwen-sheet-budget-experiment-design.md
Plan: docs/superpowers/plans/2026-08-12-qwen-sheet-budget-harness.md
"""
from __future__ import annotations

from rapid_reports_ai import quick_report_analyser as qra


def test_production_prompts_are_byte_identical_without_a_budget():
    """Regression guard: the two production analysers must not change at all."""
    assert qra.get_analyser_prompt("zai-glm-4.7") == qra.ANALYSER_SYSTEM_PROMPT_GLM
    assert (
        qra.get_analyser_prompt("claude-haiku-4-5-20251001")
        == qra.ANALYSER_SYSTEM_PROMPT_SONNET
    )


def test_empty_budget_leaves_no_override_block():
    """T1 is a true control - identical to what the bake-off ran."""
    assert qra.get_analyser_prompt("qwen/qwen3.6-27b", "") == qra.ANALYSER_SYSTEM_PROMPT_GLM
    assert qra.get_analyser_prompt("qwen/qwen3.6-27b", "   ") == qra.ANALYSER_SYSTEM_PROMPT_GLM


def test_budget_directive_is_appended_and_placeholder_is_consumed():
    prompt = qra.get_analyser_prompt("qwen/qwen3.6-27b", "Cover exactly 3 findings.")
    assert "Cover exactly 3 findings." in prompt
    assert "{{BUDGET_DIRECTIVE}}" not in prompt
    assert prompt.startswith(qra.ANALYSER_SYSTEM_PROMPT_GLM)


def test_budget_block_declares_itself_an_override():
    prompt = qra.get_analyser_prompt("qwen/qwen3.6-27b", "Cover exactly 3 findings.")
    tail = prompt[len(qra.ANALYSER_SYSTEM_PROMPT_GLM):]
    assert "OVERRIDE" in tail.upper()


def test_anthropic_ignores_the_budget():
    """Sonnet path is out of scope for this experiment and must not change."""
    assert (
        qra.get_analyser_prompt("claude-haiku-4-5-20251001", "Cover exactly 3 findings.")
        == qra.ANALYSER_SYSTEM_PROMPT_SONNET
    )


# ── Task 2: tier config ──────────────────────────────────────────────────────

from rapid_reports_ai.scripts.sheet_budget import tiers as T


def test_tiers_load_all_five():
    loaded = T.load_tiers()
    assert [t["id"] for t in loaded] == ["T1", "T2", "T3", "T4", "T5"]


def test_t1_is_the_unbudgeted_control():
    t1 = T.load_tiers()[0]
    assert t1["findings"] is None
    assert t1["variants_per_finding"] is None
    assert T.render_directive(t1) == ""


def test_budgets_are_non_increasing_down_the_ladder():
    T.validate_tiers(T.load_tiers())  # raises if not


def test_validate_rejects_an_increasing_ladder():
    bad = [
        {"id": "A", "findings": 2, "variants_per_finding": 1, "impression_exemplars": 1,
         "interpretive_clauses": 2, "mandatory_negatives": 2, "normal_study_path": "full"},
        {"id": "B", "findings": 4, "variants_per_finding": 1, "impression_exemplars": 1,
         "interpretive_clauses": 2, "mandatory_negatives": 2, "normal_study_path": "full"},
    ]
    try:
        T.validate_tiers(bad)
    except ValueError as exc:
        assert "findings" in str(exc)
    else:
        raise AssertionError("expected ValueError on an increasing ladder")


# ── Task 3: compliance counter ───────────────────────────────────────────────

from rapid_reports_ai.scripts.sheet_budget import compliance as C

FIXTURE_SHEET = """# Skill Sheet: CT thorax

## Companion Matrix
- **In-scope companions:** Nodule — long-axis in mm
- **Mandatory negatives:** "No pleural effusion.", "No bone destruction.", "No contralateral adenopathy."
- **Out-of-scope suppressed:** cardiac source (requires echocardiography)

## Style Exemplars

For each likely finding, variants:

- **Pulmonary nodule**
  - Normal: "No pulmonary nodule identified."
  - Abnormal (uncomplicated): "A 22 mm nodule is present."
- **Hilar lymphadenopathy**
  - Normal: "No hilar lymphadenopathy."
  - Abnormal (uncomplicated): "Right hilar node measures 14 mm."

## Interpretive Clause Rules

- IF [spiculated margin AND pleural tethering] THEN append "suspicious for primary malignancy"
- IF [short-axis node >10 mm] THEN append "nodal involvement"

## Impression Exemplars

- **Normal exemplar:** "No focal abnormality."
- **Abnormal exemplar:** "Right upper lobe nodule. Urgent referral."
"""


def test_counts_findings_and_variants():
    counts = C.count_sheet(FIXTURE_SHEET)
    assert counts["findings"] == 2
    assert counts["variants_per_finding"] == 2


def test_counts_negatives_clauses_and_impression_exemplars():
    counts = C.count_sheet(FIXTURE_SHEET)
    assert counts["mandatory_negatives"] == 3
    assert counts["interpretive_clauses"] == 2
    assert counts["impression_exemplars"] == 2


def test_compliance_reports_each_field_separately():
    tier = {"id": "T3", "findings": 3, "variants_per_finding": 3,
            "impression_exemplars": 2, "interpretive_clauses": 3,
            "mandatory_negatives": 3, "normal_study_path": "full"}
    result = C.check(FIXTURE_SHEET, tier)
    # partial compliance must be visible per-field, not collapsed to pass/fail
    assert result["findings"] == {"want": 3, "got": 2, "ok": False}
    assert result["mandatory_negatives"] == {"want": 3, "got": 3, "ok": True}


def test_control_tier_is_always_compliant():
    tier = {"id": "T1", "findings": None, "variants_per_finding": None,
            "impression_exemplars": None, "interpretive_clauses": None,
            "mandatory_negatives": None, "normal_study_path": None}
    result = C.check(FIXTURE_SHEET, tier)
    assert all(v["ok"] for v in result.values())


# Real Qwen output (CLEAN_qwen_matched/ct_ap_lymphoma_aspergillosis) emits the
# negatives as an indented sub-list rather than inline. Both forms occur across
# the bake-off corpus, so the counter must handle both.
SUBLIST_NEGATIVES_SHEET = """## Companion Matrix
- **In-scope companions:** Collection — volume estimate
- **Mandatory negatives:** 
  - "No rim-enhancing fluid collection or gas to suggest intra-abdominal abscess."
  - "No bowel wall thickening, obstruction, or pneumatosis."
  - "No new or enlarging lymphadenopathy to suggest progressive lymphoma."
  - "No splenic or hepatic hypodense lesions."
  - "No ascites or pleural effusion."
- **Out-of-scope suppressed:** Thoracic disease (requires CT chest)

## Style Exemplars

- **Collection**
  - Normal: "No collection."
"""


def test_counts_negatives_emitted_as_a_sublist():
    assert C.count_sheet(SUBLIST_NEGATIVES_SHEET)["mandatory_negatives"] == 5


def test_counts_negatives_emitted_inline():
    assert C.count_sheet(FIXTURE_SHEET)["mandatory_negatives"] == 3


# ── Task 4: structural gate ──────────────────────────────────────────────────

from rapid_reports_ai.scripts.sheet_budget import gate as G

CONTRADICTORY = """COMPARISON:
None.

TECHNIQUE:
CT thorax with contrast.

FINDINGS:
A 22 mm spiculated nodule is present in the right upper lobe. Right hilar
lymphadenopathy is present, with the largest node measuring 14 mm in short axis.
No mediastinal or hilar lymphadenopathy. No suspicious pulmonary nodule identified.

IMPRESSION:
Right upper lobe nodule. Urgent referral recommended.
"""

CLEAN = """COMPARISON:
None.

TECHNIQUE:
CT thorax with contrast.

FINDINGS:
A 22 mm spiculated nodule is present in the right upper lobe. Right hilar
lymphadenopathy is present, with the largest node measuring 14 mm in short axis.
No pleural effusion. No bone destruction.

IMPRESSION:
Right upper lobe nodule. Urgent referral recommended.
"""


def test_gate_flags_a_self_contradicting_report():
    result = G.run_gate(CONTRADICTORY)
    assert result["passed"] is False
    assert "self_contradiction" in result["failures"]


def test_gate_passes_a_clean_report():
    result = G.run_gate(CLEAN)
    assert result["passed"] is True
    assert result["failures"] == []


def test_gate_flags_a_missing_section():
    result = G.run_gate(CLEAN.replace("IMPRESSION:", "SUMMARY:"))
    assert "missing_section" in result["failures"]


def test_gate_flags_thinking_leak():
    result = G.run_gate(CLEAN + "\n[Done] Output Generation.")
    assert "thinking_leak" in result["failures"]


def test_gate_flags_truncation():
    result = G.run_gate(CLEAN.rstrip(".\n") + " and the patient")
    assert "truncation" in result["failures"]


# ── Task 5: ad-hoc v2.2 judge adapter ────────────────────────────────────────

from rapid_reports_ai import quality_scoring as qs
from rapid_reports_ai.scripts.sheet_budget import judge as J


def test_case_dict_matches_assemble_case_keys_exactly():
    """Guard against drift in _assemble_case's contract."""
    built = J.build_case(inputs="Scan type: CT head", skill_sheet="# Sheet", report="FINDINGS: ...")
    assert set(built) == {"pipeline", "inputs", "skill_sheet", "ai_output", "final_output"}
    assert built["pipeline"] == "quick"
    assert built["final_output"] is None


def test_case_text_renders_for_every_v22_dimension():
    built = J.build_case(inputs="Scan type: CT head", skill_sheet="# Sheet", report="FINDINGS: x")
    for dim in qs.DIMENSIONS_V22:
        text = qs._case_text_v2(dim, built)
        assert isinstance(text, str) and text.strip()


def test_score_case_uses_an_injected_judge_and_returns_all_dimensions():
    calls = []

    def fake_judge(prompt, case_text):
        calls.append(case_text)
        return qs.JudgeScore(score=4, rationale="fixture")

    scores = J.score_case(
        inputs="Scan type: CT head", skill_sheet="# Sheet",
        report="FINDINGS: x", judge=fake_judge,
    )
    assert set(scores) == set(qs.DIMENSIONS_V22)
    assert all(v["score"] == 4 for v in scores.values())
    assert len(calls) == len(qs.DIMENSIONS_V22)


def test_format_inputs_mirrors_production_format_input_data():
    """The judge sees dictation via inputs; omitting it silently breaks
    dictation_fidelity. Shape must match _format_input_data exactly."""
    produced = J.format_inputs(
        scan_type="CT thorax", clinical_history="40 pack-year smoker", findings="22mm nodule RUL"
    )
    reference = qs._format_input_data({"variables": {
        "SCAN_TYPE": "CT thorax",
        "CLINICAL_HISTORY": "40 pack-year smoker",
        "FINDINGS": "22mm nodule RUL",
    }})
    assert produced == reference
    assert "Dictated findings: 22mm nodule RUL" in produced


# ── Task 7: curve output ─────────────────────────────────────────────────────

from rapid_reports_ai.scripts.sheet_budget import report as R

RUNS_FIXTURE = [
    {"tier": "T1", "case": "a", "sheet_tokens_est": 3400, "sheet_chars": 13600,
     "analyser_latency_ms": 24800, "generator_latency_ms": 12700, "report_chars": 1800,
     "gate": {"passed": True, "failures": []},
     "judge": {"output_adherence": {"score": 5}, "dictation_fidelity": {"score": 4},
               "normal_fill_appropriateness": {"score": 5}, "unwarranted_assertion": {"score": 4}}},
    {"tier": "T5", "case": "a", "sheet_tokens_est": 700, "sheet_chars": 2800,
     "analyser_latency_ms": 9000, "generator_latency_ms": 6000, "report_chars": 1200,
     "gate": {"passed": False, "failures": ["self_contradiction"]}},
]


def test_curve_csv_has_a_row_per_run_and_mean_score(tmp_path):
    path = tmp_path / "curve.csv"
    R.write_curve_csv(RUNS_FIXTURE, path)
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 3  # header + 2 runs
    assert "mean_score" in lines[0]
    assert "4.5" in lines[1]  # (5+4+5+4)/4
    assert "gate_failures" in lines[0]


def test_artifact_html_is_self_contained_and_themed(tmp_path):
    path = tmp_path / "curve.html"
    R.write_artifact_html(RUNS_FIXTURE, path)
    html = path.read_text()
    assert "<title>" in html
    assert "prefers-color-scheme" in html
    assert "http://" not in html and "https://" not in html  # no external assets


# ── Generator output cap (ledger L-04 / L-05) ────────────────────────────────

from rapid_reports_ai import template_manager as tm_mod

# Groq's published hard ceiling for qwen/qwen3.6-27b. Values above are rejected.
QWEN_MAX_OUTPUT_TOKENS = 16384

# Highest single-call generator output observed with reasoning on, across the
# sheet-budget sweep and the reasoning matrix. The cap must clear this or
# reasoning exhausts the budget and the report truncates mid-FINDINGS.
OBSERVED_REASONING_PEAK = 13569


def test_groq_generator_cap_is_within_the_model_ceiling():
    assert tm_mod.GROQ_GENERATOR_MAX_TOKENS <= QWEN_MAX_OUTPUT_TOKENS


def test_groq_generator_cap_clears_observed_reasoning_peak():
    """Regression guard on L-05: at 8000 this failed and reports truncated."""
    assert tm_mod.GROQ_GENERATOR_MAX_TOKENS > OBSERVED_REASONING_PEAK
