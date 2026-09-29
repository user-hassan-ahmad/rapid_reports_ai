from __future__ import annotations

import asyncio
from types import SimpleNamespace

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.enhancement_utils import MODEL_CONFIG, normalise_model_settings

REQ = cr.CanvasReviewRequest(scratchpad_content="There is a 9 mm hypodense lesion in segment 8 of the liver.",
                             checklist_sections=["LIVER"], scan_type="CT abdomen", clinical_history="")


def _stub(monkeypatch, fail_primary=False):
    calls = []

    async def fake(*, model_name, output_type, system_prompt, user_prompt, api_key, use_thinking, model_settings):
        calls.append({"model": model_name, "thinking": use_thinking, "settings": model_settings})
        if fail_primary and len(calls) == 1:
            raise RuntimeError("primary down")
        q = cr.IntelliPrompt(question="Liver lesion characterised?", source_text="hypodense lesion")
        return SimpleNamespace(output=cr.PromptsOnlyResponse(prompts=[q]))

    monkeypatch.setattr(cr, "_run_agent_with_model", fake)
    monkeypatch.setattr(cr, "_get_api_key_for_provider", lambda p: "k")
    return calls


def test_intelliprompts_run_on_cerebras_qwen_with_reasoning_off(monkeypatch):
    # Reasoning on made every structured answer fail (Groq qwen thinking: tool_use_failed after
    # ~6.5 s; Cerebras qwen 'low': parser_error), leaving a 35–137 s fallback (lab log
    # 2026-09-27). Reasoning off: Cerebras 0.66–0.95 s, Groq 1.5–1.9 s, 3–5 sound prompts.
    calls = _stub(monkeypatch)
    out = asyncio.run(cr._intelliprompts(REQ))
    assert [p.question for p in out] == ["Liver lesion characterised?"]
    c = calls[0]
    assert c["model"] == MODEL_CONFIG["CANVAS_INTELLIPROMPTS"] == "qwen-3.8-27b"
    assert c["thinking"] is False
    # what reaches the provider after normalise_model_settings: reasoning off, a small cap
    sent = normalise_model_settings(c["model"], c["settings"])
    assert sent["extra_body"]["reasoning_effort"] == "none" and sent["max_tokens"] == 1500


def test_intelliprompts_fall_back_to_groq_qwen_with_reasoning_off(monkeypatch):
    calls = _stub(monkeypatch, fail_primary=True)
    out = asyncio.run(cr._intelliprompts(REQ))
    assert len(out) == 1
    assert calls[1]["model"] == MODEL_CONFIG["CANVAS_INTELLIPROMPTS_FALLBACK"]
    sent = normalise_model_settings(calls[1]["model"], calls[1]["settings"])
    assert calls[1]["thinking"] is False and sent["extra_body"]["reasoning_effort"] == "none"
