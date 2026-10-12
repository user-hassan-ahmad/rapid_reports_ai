def test_template_options_drop_declined_chips():
    from rapid_reports_ai.template_lean import without_declined
    opts = [{"kind": "finding_negative", "text": "No free intraperitoneal gas"}, {"kind": "recommendation", "text": "No free gas"},
            {"kind": "finding_negative", "text": "No abscess"}]
    assert [o["text"] for o in without_declined(opts, ["No free intraperitoneal gas."])] == ["No free gas", "No abscess"]
    assert without_declined(opts, []) == opts


async def test_stack_sessions_skip_the_brief_and_use_the_slim_sheet(monkeypatch):
    from rapid_reports_ai import quick_report_generator as G
    seen = {}

    async def brief(*a, **k):
        seen["compiled"] = True
        raise RuntimeError("never in a stack session")

    def prompts(sheet, scan_type, findings, history, provider, brief=False):
        seen.update(sheet=sheet, brief=brief)
        raise RuntimeError("stop")
    monkeypatch.setattr(G, "compile_brief", brief)
    monkeypatch.setattr(G, "build_prompts", prompts)
    slim = "## Structural Pattern\n- **Sections:** FINDINGS, IMPRESSION\n\n## Region Normals\n- **Liver:** \"The liver is normal.\"\n"
    try:
        await G.generate_quick_report(skill_sheet="## Companion Matrix\n- **Mandatory negatives:**\n  - \"No x\"\n",
                                      scan_type="CT", findings="f", clinical_history="", stack=True,
                                      declined=["No free gas."], conclusion="Diverticulitis.", stack_sheet=slim)
    except Exception:
        pass
    assert "compiled" not in seen and seen["brief"] is True
    assert "Sections:" in seen["sheet"] and "The liver is normal." not in seen["sheet"] and "No x" not in seen["sheet"]
    assert 'DO NOT ASSERT: "No free gas."' in seen["sheet"] and '"Diverticulitis."' in seen["sheet"]


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
