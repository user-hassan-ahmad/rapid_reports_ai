"""Template pipeline (spec §4)."""
from __future__ import annotations

import pytest

from rapid_reports_ai import enhancement_utils as eu
from rapid_reports_ai import global_style_guide as g
from rapid_reports_ai.template_manager import TemplateManager


@pytest.fixture
def capture(monkeypatch):
    seen = []

    class R:
        output = "FINDINGS\nX."

    async def fake(**kw):
        seen.append(kw)
        return R
    monkeypatch.setattr(eu, "_run_agent_with_model", fake)
    monkeypatch.setattr(eu, "_get_api_key_for_provider", lambda p, fallback_api_key=None: "k")
    monkeypatch.setattr(eu, "_get_model_provider", lambda m: "cerebras")
    return seen


async def test_brief_path_uses_brief_prompts_and_history_note(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "RAW SHEET", "scan_type": "CT"}
    await TemplateManager()._generate_report_skill_sheet_guided(
        cfg, {"FINDINGS": "f", "CLINICAL_HISTORY": "h"}, None, brief_text="BRIEF TEXT", history_supplied=True)
    gen = next(k for k in capture if k["output_type"] is str)
    assert "BRIEF TEXT" in gen["system_prompt"] and "RAW SHEET" not in gen["system_prompt"]
    assert g.TEMPLATE_SHEET_HEADER_BRIEF in gen["system_prompt"] and g.GLOBAL_STYLE_GUIDE_BRIEF in gen["system_prompt"]
    assert g.PRE_WRITING_ANALYSIS_BRIEF in gen["user_prompt"]
    assert "The CLINICAL HISTORY section is supplied separately; do not write it." in gen["user_prompt"]


async def test_raw_path_is_unchanged(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "RAW SHEET", "scan_type": "CT"}
    await TemplateManager()._generate_report_skill_sheet_guided(cfg, {"FINDINGS": "f"}, None)
    gen = next(k for k in capture if k["output_type"] is str)
    assert "RAW SHEET" in gen["system_prompt"] and g.GLOBAL_STYLE_GUIDE in gen["system_prompt"]
    assert g.PRE_WRITING_ANALYSIS in gen["user_prompt"] and "supplied separately" not in gen["user_prompt"]


def _gen(capture):
    return next(k for k in capture if k["output_type"] is str)


@pytest.mark.parametrize("blank", ["", "   \n  "])
async def test_blank_brief_takes_raw_path(capture, blank):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "RAW SHEET", "scan_type": "CT"}
    await TemplateManager()._generate_report_skill_sheet_guided(cfg, {"FINDINGS": "f"}, None, brief_text=blank)
    gen = _gen(capture)
    assert "RAW SHEET" in gen["system_prompt"] and g.GLOBAL_STYLE_GUIDE in gen["system_prompt"]
    assert g.TEMPLATE_SHEET_HEADER_BRIEF not in gen["system_prompt"]
    assert g.PRE_WRITING_ANALYSIS in gen["user_prompt"] and g.VERIFICATION_CHECKLIST in gen["user_prompt"]


async def test_brief_path_does_not_leak_raw_prompts(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "RAW SHEET", "scan_type": "CT"}
    await TemplateManager()._generate_report_skill_sheet_guided(
        cfg, {"FINDINGS": "f"}, None, brief_text="BRIEF TEXT")
    gen = _gen(capture)
    assert g.GLOBAL_STYLE_GUIDE not in gen["system_prompt"]
    assert "RAW SHEET" not in gen["system_prompt"] and "RAW SHEET" not in gen["user_prompt"]
    assert g.PRE_WRITING_ANALYSIS not in gen["user_prompt"]
    assert g.VERIFICATION_CHECKLIST_BRIEF in gen["user_prompt"]
    # The _BRIEF constants themselves mention "supplied separately"; check the exact note.
    assert "The CLINICAL HISTORY section is supplied separately; do not write it." not in gen["user_prompt"]


async def test_brief_path_anthropic_provider(capture, monkeypatch):
    monkeypatch.setattr(eu, "_get_model_provider", lambda m: "anthropic")
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "RAW SHEET", "scan_type": "CT"}
    await TemplateManager()._generate_report_skill_sheet_guided(
        cfg, {"FINDINGS": "f", "CLINICAL_HISTORY": "h"}, None, brief_text="BRIEF TEXT", history_supplied=True)
    gen = _gen(capture)
    assert "BRIEF TEXT" in gen["system_prompt"] and "RAW SHEET" not in gen["system_prompt"]
    assert ("Findings: f\n\nThe CLINICAL HISTORY section is supplied separately; do not write it.\n\n"
            "Generate the report now.") in gen["user_prompt"]
    assert g.PRE_WRITING_ANALYSIS_BRIEF not in gen["user_prompt"]
    assert g.PRE_WRITING_ANALYSIS not in gen["user_prompt"]


# Byte-identity guard: the raw path must send exactly the pre-mirror prompts (old f-string layout).
_RAW_SHEET = "RAW SHEET\n## x {braces}"
_ANTHROPIC_TAIL = (
    "Generate the report now. Output the report content ONLY — no analysis, no commentary, no "
    "restatement of the skill sheet. Emit exactly the sections declared in the skill sheet's "
    "Structural Pattern, in order.\n\n"
    "**Voice.** Write as a consultant dictating clinical observations at pace — each finding a "
    "compressed declarative, noun-dense, connective-sparse. Separate observations get separate "
    "sentences; a consultant states what is, not what they saw. Hedge only where diagnostic "
    "uncertainty is genuine.\n\n"
    "**Impression.** Write as a consultant handing over to the referring clinician — they need to "
    "know what you concluded and what to do about it, and nothing else. Every sentence earns its "
    "place by changing what happens next. The voice is clinical handover: specific, unsentimental, "
    "and calibrated by consequence rather than adjective."
)


def _expected_raw(provider: str) -> tuple[str, str]:
    system = f"""{g.SYSTEM_PREAMBLE}

{g.GLOBAL_STYLE_GUIDE}

## TEMPLATE SKILL SHEET

The following skill sheet defines scan-specific reporting conventions for this template.
It inherits all rules from the Global Style Guide above. Where a skill sheet rule
conflicts with a global rule, the skill sheet takes precedence.

{_RAW_SHEET}"""
    inputs = "## INPUTS\n\nScan Type: CT abdo\nClinical History: hist\nFindings: f1\nf2\n\n"
    if provider == "anthropic":
        user = inputs + _ANTHROPIC_TAIL
    else:
        user = inputs + f"{g.PRE_WRITING_ANALYSIS}\n\n{g.VERIFICATION_CHECKLIST}"
    return system, user


@pytest.mark.parametrize("provider", ["cerebras", "anthropic"])
async def test_raw_path_prompts_are_byte_identical(capture, monkeypatch, provider):
    monkeypatch.setattr(eu, "_get_model_provider", lambda m: provider)
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": _RAW_SHEET, "scan_type": "CT abdo"}
    await TemplateManager()._generate_report_skill_sheet_guided(
        cfg, {"FINDINGS": "f1\nf2", "CLINICAL_HISTORY": "hist"}, None)
    gen = _gen(capture)
    system, user = _expected_raw(provider)
    assert gen["system_prompt"] == system
    assert gen["user_prompt"] == user


# ── template_pipeline: the orchestration production and the lab share (plan 2026-10-01-template-wiring W2) ──

from rapid_reports_ai import report_reconcile as rc  # noqa: E402
from rapid_reports_ai import template_pipeline as tp  # noqa: E402

import pathlib  # noqa: E402

# A real lean sheet (the lean analyser on the cmr_cardiomyopathy examples) and the master sheet Phase 1 made
# from it for cmr_cardiomyopathy-d2 (lab run e2e_small_w_65773).
_FIX = pathlib.Path(__file__).parent / "fixtures" / "template_pipeline"
LEAN = (_FIX / "lean_cmr.md").read_text()
MASTER = (_FIX / "master_cmr.md").read_text()
LEAN_NO_HISTORY = LEAN.replace('SECTION CLINICAL DETAILS | header: "Clinical details:" | role: history\n', "")
GEN_REPORT = "Findings:\nThe left ventricle is normal.\n\nConclusion:\n1. Normal study."
BRIEF_OPTIONS = [{"kind": "finding_negative", "section": "FINDINGS", "text": "No adjacent fat stranding",
                  "finding": "lesion"},
                 {"kind": "impression", "text": "Normal study", "reason": "r"}]


def _stubs(monkeypatch, brief_ok=True, gate=None, check_extra=None):
    calls = {"order": []}

    async def fake_brief(sheet, s, scan, findings, history):
        calls["brief_sheet"] = sheet
        if not brief_ok:
            raise RuntimeError("boom")
        return rc.Brief(text="BRIEF", decisions={"options": BRIEF_OPTIONS}, reconcile_ms=5)

    async def fake_gen(self, template_config, user_inputs, user_signature=None, model_override=None,
                       brief_text=None, history_supplied=False):
        calls["gen"] = {"brief_text": brief_text, "history_supplied": history_supplied, "sig": user_signature,
                        "sheet": template_config["skill_sheet"]}
        return {"report_content": GEN_REPORT, "description": "d", "scan_type": "CT AP", "model_used": "q"}

    async def fake_options(options, findings, scan_type, **kw):
        calls["options_in"] = options
        return [{"id": "fn0", "kind": "finding_negative", "section": "FINDINGS", "sentence": "No fat stranding."},
                {"id": "opt0", "kind": "impression", "section": "IMPRESSION", "sentence": "Normal study."}]

    async def fake_history(h):
        calls["history_in"] = h
        return ("?Lesion. Follow-up.", "verbatim")

    async def fake_check(report, findings, scan, options, sections=None, protected=None, suppressed=None,
                         extra_report_qs=None, history=None):
        calls["order"].append("check")
        calls["check"] = {"sections": [s.name for s in sections], "protected": protected, "history": history,
                          "report": report, "extra": extra_report_qs}
        return report + "\nCHECKED", options, {"enabled": True, "extra_answers": check_extra or {}}

    async def fake_gate(state, qs):
        calls["gate"] = {"state": state, "qs": qs}
        return gate or {}

    monkeypatch.setattr(tp, "compile_template_brief", fake_brief)
    monkeypatch.setattr(tp.TemplateManager, "_generate_report_skill_sheet_guided", fake_gen)
    monkeypatch.setattr(tp, "write_options", fake_options)
    monkeypatch.setattr(tp, "write_history", fake_history)
    monkeypatch.setattr(tp, "run_quality_check", fake_check)
    monkeypatch.setattr(tp.rc, "gate_scores", fake_gate)
    return calls


async def _run(sheet=LEAN, master=MASTER, signature=None):
    return await tp.generate_template_report(sheet=sheet, scan_type="CT AP", findings="A 2 cm lesion.",
                                             history="?lesion follow-up", master_sheet=master, signature=signature)


async def test_master_sheet_is_used_when_usable(monkeypatch):
    calls = _stubs(monkeypatch)
    out = await _run()
    assert calls["brief_sheet"] == MASTER and out["phase1_used"] is True
    assert calls["gen"]["sheet"] == LEAN  # the generator always reads the lean sheet; the master feeds the brief


@pytest.mark.parametrize("master", [None, "", "not a grammar sheet at all"])
async def test_missing_or_unusable_master_falls_back_to_the_lean_sheet(monkeypatch, master):
    calls = _stubs(monkeypatch)
    out = await _run(master=master)
    assert calls["brief_sheet"] == LEAN and out["phase1_used"] is False


async def test_brief_failure_takes_the_raw_path_and_still_reports(monkeypatch):
    calls = _stubs(monkeypatch, brief_ok=False)
    out = await _run()
    assert calls["gen"]["brief_text"] is None and out["brief_text"] is None and out["brief_used"] is False
    assert out["report_content"] and "brief_error" in out and calls["options_in"] == []


async def test_history_inserted_only_when_the_sheet_defines_it_and_passed_to_the_check(monkeypatch):
    calls = _stubs(monkeypatch)
    out = await _run()
    assert out["history_inserted"] and calls["check"]["history"] == "?Lesion. Follow-up."
    assert calls["check"]["report"].startswith("Clinical details:\n?Lesion. Follow-up.")
    assert "?Lesion. Follow-up." in calls["check"]["protected"] and calls["gen"]["history_supplied"] is True
    assert out["sections"] == ["CLINICAL DETAILS", "TECHNIQUE", "FINDINGS", "TISSUE CHARACTERISATION",
                               "LATE GADOLINIUM ENHANCEMENT", "CONCLUSION"]

    assert LEAN_NO_HISTORY != LEAN
    calls = _stubs(monkeypatch)
    out = await _run(sheet=LEAN_NO_HISTORY, master=None)
    assert not out["history_inserted"] and "history_in" not in calls and calls["check"]["history"] == ""
    assert calls["gen"]["history_supplied"] is False and "Clinical details" not in out["report_content"]


async def test_gate_drops_are_applied(monkeypatch):
    # option 1 (impression) is asked of the conclusion; option 0 (finding negative) rides on the check
    calls = _stubs(monkeypatch, gate={"u1": 0.95}, check_extra={"u0": 0.1})
    out = await _run()
    assert "u0" in calls["check"]["extra"] and "u1" in calls["gate"]["qs"]
    assert calls["gate"]["state"].startswith("CONCLUSION:\n1. Normal study.")
    assert [o["id"] for o in out["options"]] == ["fn0"]
    assert [o["id"] for o in out["gate_dropped"]] == ["opt0"] and out["gate_dropped"][0]["outcome"] == "already_in_report"


async def test_signature_comes_last_after_the_check(monkeypatch):
    _stubs(monkeypatch)
    out = await _run(signature="Dr A")
    assert out["report_content"].endswith("CHECKED\n\nDr A")
    assert set(out["lat"]) >= {"brief_s", "generator_s", "options_s", "check_s", "gate_s"}


def test_choose_mirror_respects_flag_and_allowlist(monkeypatch):
    monkeypatch.delenv("RR_TEMPLATE_MIRROR", raising=False)
    monkeypatch.setenv("RR_PIPELINE_OVERRIDE_USERS", "a@x.com")
    assert tp.enabled() is False
    assert tp.choose_mirror(None, "a@x.com") is False                   # flag off
    assert tp.choose_mirror("mirror", "A@x.com") is True                # allowlisted "mirror"
    assert tp.choose_mirror("mirror", "b@x.com") is False               # not allowlisted: the flag's value
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "1")
    assert tp.choose_mirror(None, "b@x.com") is True
    assert tp.choose_mirror("current", "b@x.com") is True               # not allowlisted: the flag's value
    assert tp.choose_mirror("current", "a@x.com") is False              # flag on, allowlisted "current"


def test_keys_hash_sheet_and_stripped_history():
    s, h = tp.keys("SHEET", "  ?perforation \n")
    assert (s, h) == tp.keys("SHEET", "?perforation") and len(s) == len(h) == 16
    assert tp.keys("SHEET", "other")[1] != h and tp.keys("SHEET2", "?perforation")[0] != s


def test_candidate_record_has_quick_fields_plus_sections():
    rec = tp.candidate_record({"report_content": "r", "model_used": "q", "description": "d", "options": [{"id": "x"}],
                               "quality_check": {}, "brief_used": True, "brief_text": "t", "brief_decisions": {},
                               "sections": ["FINDINGS"], "lat": {"brief_s": 1.0}}, 1200)
    assert set(rec) >= {"model", "content", "latency_ms", "generated_at", "error", "description", "options",
                        "options_applied", "quality_check", "brief", "sections"}
    assert rec["options_applied"] == [] and rec["brief"] == {"text": "t", "decisions": {}}
    assert rec["options"] == [{"id": "x"}] and rec["lat"] == {"brief_s": 1.0} and rec["latency_ms"] == 1200


async def test_run_phase1_returns_the_master_and_raises_on_model_failure(monkeypatch):
    async def ok(sheet, summary, scan, history):
        return tp.ca.CaseResult(raw="r", ms=1500, model="m")
    monkeypatch.setattr(tp.ca, "deliberate", ok)
    monkeypatch.setattr(tp.ca, "summarise_template", lambda s: {})
    out = await tp.run_phase1(LEAN, "CT", "h")
    assert out["master_sheet"] == LEAN and out["latency_ms"] == 1500 and out["model"] == "m"
    assert out["case_result"]["raw"] == "r" and out["prompt_version"] == tp.PROMPT_VERSION

    async def failed(sheet, summary, scan, history):
        return tp.ca.CaseResult(errors=["model call failed: TimeoutError: x"])
    monkeypatch.setattr(tp.ca, "deliberate", failed)
    with pytest.raises(RuntimeError, match="model call failed"):
        await tp.run_phase1(LEAN, "CT", "h")
