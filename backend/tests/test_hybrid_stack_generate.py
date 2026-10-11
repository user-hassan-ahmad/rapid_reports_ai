def test_template_options_drop_declined_chips():
    from rapid_reports_ai.template_lean import without_declined
    opts = [{"kind": "finding_negative", "text": "No free intraperitoneal gas"}, {"kind": "recommendation", "text": "No free gas"},
            {"kind": "finding_negative", "text": "No abscess"}]
    assert [o["text"] for o in without_declined(opts, ["No free intraperitoneal gas."])] == ["No free gas", "No abscess"]
    assert without_declined(opts, []) == opts


async def test_quick_generator_passes_stack_mode_to_the_brief(monkeypatch):
    from rapid_reports_ai import quick_report_generator as G
    seen = {}

    async def brief(sheet, scan_type, findings, history, stack=False, declined=(), conclusion=""):
        seen.update(stack=stack, declined=list(declined), conclusion=conclusion)
        raise RuntimeError("stop here")
    monkeypatch.setattr(G, "compile_brief", brief)

    async def run(**k):
        raise RuntimeError("generator not under test")
    monkeypatch.setattr(G, "_run_agent_with_model", run, raising=False)
    try:
        await G.generate_quick_report(skill_sheet="x", scan_type="CT", findings="f", clinical_history="",
                                      stack=True, declined=["No free gas."], conclusion="Diverticulitis.")
    except Exception:
        pass
    assert seen == {"stack": True, "declined": ["No free gas."], "conclusion": "Diverticulitis."}


def test_chip_state_bands():
    from rapid_reports_ai.hybrid_stack.jev_stack import chip_state
    assert chip_state(0.85, 0.0) == "gone" and chip_state(0.1, 0.75) == "gone"
    assert chip_state(0.45, 0.1) == "optional" and chip_state(0.1, 0.35) == "optional"
    assert chip_state(0.2, 0.2) == "included"


async def test_stack_generation_never_falls_back_to_the_raw_sheet(monkeypatch):
    from rapid_reports_ai import quick_report_generator as G
    seen = {}

    async def brief(*a, **k):
        raise RuntimeError("brief down")

    def prompts(sheet, scan_type, findings, history, provider, brief=False):
        seen.update(sheet=sheet, brief=brief)
        raise RuntimeError("stop")
    monkeypatch.setattr(G, "compile_brief", brief)
    monkeypatch.setattr(G, "build_prompts", prompts)
    try:
        await G.generate_quick_report(skill_sheet="## Companion Matrix\n- **Mandatory negatives:**\n  - \"No x\"\n",
                                      scan_type="CT", findings="f", clinical_history="", stack=True, conclusion="C.")
    except Exception:
        pass
    assert seen["brief"] is True and "No x" not in seen["sheet"] and '"C."' in seen["sheet"]
