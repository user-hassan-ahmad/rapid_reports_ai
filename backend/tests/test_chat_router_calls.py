"""The targeted calls: one kind each, the whole instruction, only their part of the sheet (spec Flow 2)."""
from rapid_reports_ai import chat_router_calls as C
from rapid_reports_ai import chat_router_changes as CH
from rapid_reports_ai import enhancement_utils as eu
from tests.test_template_sheet_lab_prompts import CLINICAL


def test_prompts_are_case_agnostic_and_scoped():
    for kind, system in C.SYSTEM.items():
        low = system.lower()
        for word in CLINICAL:
            assert word not in low, (kind, word)
        assert "Ignore every other part of the INSTRUCTION" in system, kind
    assert set(C.SYSTEM) == set(CH.OUTPUTS)


def test_user_prompt_carries_instruction_view_context_and_a_rejection():
    p = C.user_prompt("drop width", "VALUES:\n- Width", "Done.",
                      {"original_instruction": "remove width", "rejected_claim": "Width is no longer required."})
    assert p.startswith("INSTRUCTION:\ndrop width") and "CURRENT:\nVALUES:" in p and "YOUR PREVIOUS REPLY" in p
    assert 'They had asked: "remove width"' in p and "Width is no longer required." in p
    assert "REJECTED" not in C.user_prompt("x", "v")


async def test_call_kind_uses_qwen_with_the_kinds_output_type(monkeypatch):
    seen = {}

    async def run(model_name, output_type, system_prompt, user_prompt, api_key, model_settings):
        seen.update(model=model_name, out=output_type, system=system_prompt, settings=model_settings)
        return type("R", (), {"output": output_type()})()
    monkeypatch.setattr(eu, "_run_agent_with_model", run)
    out = await C.call_kind("value", "drop width", "VALUES:\n- Width")
    assert isinstance(out, CH.ValueOut) and seen["model"] == eu.MODEL_CONFIG["SKILL_SHEET_REFINER"]
    assert seen["system"] == C.SYSTEM["value"] and seen["settings"]["temperature"] == 0


async def test_call_kind_retries_once_on_gpt_oss_with_prompted_output(monkeypatch):
    from pydantic_ai import PromptedOutput
    seen = []

    async def run(model_name, output_type, system_prompt, user_prompt, api_key, model_settings):
        seen.append((model_name, output_type))
        if len(seen) == 1:
            raise TimeoutError()
        return type("R", (), {"output": output_type.outputs()})()
    monkeypatch.setattr(eu, "_run_agent_with_model", run)
    out = await C.call_kind("style", "shorter", "PROSE BLOCKS:")
    assert isinstance(out, CH.StyleOut)
    assert [m for m, _ in seen] == [eu.MODEL_CONFIG["SKILL_SHEET_REFINER"], eu.MODEL_CONFIG["STACK_REVIEW_FALLBACK"]]
    assert seen[0][1] is CH.StyleOut                            # Qwen keeps tool output
    assert isinstance(seen[1][1], PromptedOutput) and seen[1][1].outputs is CH.StyleOut   # gpt-oss: JSON in text
