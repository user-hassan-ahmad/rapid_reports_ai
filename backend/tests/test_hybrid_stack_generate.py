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

    def prompts(sheet, scan_type, findings, history, provider, brief=False, stack=False):
        seen.update(sheet=sheet, brief=brief, stack=stack)
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
    assert "compiled" not in seen and seen["brief"] is True and seen["stack"] is True
    assert "Sections:" in seen["sheet"] and "The liver is normal." not in seen["sheet"] and "No x" not in seen["sheet"]
    assert 'DO NOT ASSERT: "No free gas."' in seen["sheet"] and '"Diverticulitis."' in seen["sheet"]


async def test_stack_generation_never_falls_back_to_the_raw_sheet(monkeypatch):
    from rapid_reports_ai import quick_report_generator as G
    seen = {}

    async def brief(*a, **k):
        raise RuntimeError("brief down")

    def prompts(sheet, scan_type, findings, history, provider, brief=False, stack=False):
        seen.update(sheet=sheet, brief=brief, stack=stack)
        raise RuntimeError("stop")
    monkeypatch.setattr(G, "compile_brief", brief)
    monkeypatch.setattr(G, "build_prompts", prompts)
    try:
        await G.generate_quick_report(skill_sheet="## Companion Matrix\n- **Mandatory negatives:**\n  - \"No x\"\n",
                                      scan_type="CT", findings="f", clinical_history="", stack=True, conclusion="C.")
    except Exception:
        pass
    assert seen["brief"] is True and "No x" not in seen["sheet"] and '"C."' in seen["sheet"]


def test_stack_prompts_replace_the_fill_and_synthesis_rules_and_production_keeps_them():
    from rapid_reports_ai.quick_report_generator import build_prompts
    st_sys, st_user = build_prompts("SHEET", "CT", "F", "H", "cerebras", brief=True, stack=True)
    br_sys, br_user = build_prompts("SHEET", "CT", "F", "H", "cerebras", brief=True)
    for dead in ("Coverage is obligatory", "Normal-study path", "Carry forward", "KEEP negative", "Clinical Lane",
                 "Four synthesis moves", "state it and\ncommit", "render the canonical default-normal line"):
        assert dead not in st_sys + st_user, dead
    for kept in ("Coverage is obligatory", "Carry forward", "Four synthesis moves"):
        assert kept in br_sys + br_user, kept     # production quick reports are unchanged
    assert "DO NOT ASSERT**: the radiologist removed this statement" in st_sys
    assert "phrases the confirmed conclusion" in st_user and st_sys.endswith("SHEET")


def test_stack_brief_drops_the_history_section_and_descriptor_propagation():
    from rapid_reports_ai.quick_report_brief import stack_fallback
    slim = ("## Structural Pattern\n- **Sections:** Clinical History, Technique, Findings, Impression\n\n"
            "## Impression Conventions\n- **Opening convention:** The diagnosis first.\n"
            "- **Descriptor propagation:** Size and grade carry into the impression.\n")
    text = stack_fallback(slim, "C.").text
    assert "- **Sections:** Technique, Findings, Impression" in text
    assert "Opening convention" in text and "Descriptor propagation" not in text
