from rapid_reports_ai.hybrid_stack import chips as C
from rapid_reports_ai.report_reconcile import FallbackItem, FallbackNegatives


def _fb(*lists):
    async def fake(state, items, keys):
        assert keys == []
        return FallbackNegatives(items=[FallbackItem(index=i, covered=False, negatives=n) for i, n in enumerate(lists)])
    return fake


async def _stated_none(dictation, chips):
    return [(0.0, 0.0)] * len(chips)


def _texts(out):
    return [c.text for c in out.chips]


async def test_flattens_dedupes_and_caps_at_three(monkeypatch):
    C.clear_cache()
    monkeypatch.setattr(C, "_fallback", _fb(["No free gas.", "No abscess."], ["no free gas", "No fistula.", "No obstruction."]))
    monkeypatch.setattr(C, "ask_checks", _stated_none)
    out = await C.suggest("CT AP", "", "Bowel", ["Sigmoid diverticulitis.", "Wall thickening."], "Sigmoid diverticulitis.")
    assert _texts(out) == ["No free gas.", "No abscess.", "No fistula."]
    assert {c.state for c in out.chips} == {"included"}
    assert out.cached is False and out.error is None


async def test_drops_what_the_dictation_says_and_what_jev_calls_stated(monkeypatch):
    C.clear_cache()
    monkeypatch.setattr(C, "_fallback", _fb(["No free gas.", "No abscess.", "No fistula."]))

    async def checks(dictation, chips):
        return [{"No fistula.": (0.9, 0.0), "No abscess.": (0.1, 0.0)}.get(c, (0.0, 0.0)) for c in chips]
    monkeypatch.setattr(C, "ask_checks", checks)
    out = await C.suggest("CT AP", "", "Bowel", ["Diverticulitis."], "Diverticulitis. No free gas.")
    assert _texts(out) == ["No abscess."]


async def test_cache_and_fail_open(monkeypatch):
    C.clear_cache()
    calls = []

    async def fb(state, items, keys):
        calls.append(1)
        return FallbackNegatives(items=[FallbackItem(index=0, covered=False, negatives=["No abscess."])])
    monkeypatch.setattr(C, "_fallback", fb)
    monkeypatch.setattr(C, "ask_checks", _stated_none)
    a = await C.suggest("CT AP", "", "Bowel", ["Diverticulitis."], "Diverticulitis.")
    b = await C.suggest("ct  ap", "", "Bowel", [" Diverticulitis. "], "Diverticulitis.")
    assert _texts(a) == _texts(b) == ["No abscess."] and b.cached and len(calls) == 1

    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(C, "_fallback", boom)
    out = await C.suggest("CT AP", "", "Liver", ["Cyst."], "Cyst.")
    assert out.chips == [] and "RuntimeError" in out.error


async def test_stated_check_failure_keeps_chips(monkeypatch):
    C.clear_cache()
    monkeypatch.setattr(C, "_fallback", _fb(["No abscess."]))

    async def boom(*a, **k):
        raise RuntimeError("jev down")
    monkeypatch.setattr(C, "ask_checks", boom)
    out = await C.suggest("CT AP", "", "Bowel", ["Diverticulitis."], "Diverticulitis.")
    assert [(c.text, c.state) for c in out.chips] == [("No abscess.", "optional")]  # unchecked: never included


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


async def test_cached_texts_are_rechecked_against_this_dictation_and_declined(monkeypatch):
    C.clear_cache()
    monkeypatch.setattr(C, "_fallback", _fb(["No biliary dilatation.", "No portal vein thrombus."]))
    monkeypatch.setattr(C, "ask_checks", _stated_none)
    a = await C.suggest("CT AP", "", "Pancreas", ["Pancreatic head mass."], "Pancreatic head mass.")
    assert [c.state for c in a.chips] == ["included", "included"]

    async def contra(dictation, chips):
        return [(0.0, 0.9) if "biliary" in c else (0.0, 0.0) for c in chips]
    monkeypatch.setattr(C, "ask_checks", contra)
    b = await C.suggest("CT AP", "", "Pancreas", ["Pancreatic head mass."], "CBD dilated to 12 mm. Pancreatic head mass.",
                        declined=["no portal vein thrombus is seen"])
    assert b.cached and _texts(b) == []   # contradicted here; the other removed earlier (reworded)



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
