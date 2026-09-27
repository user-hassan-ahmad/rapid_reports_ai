from __future__ import annotations

import asyncio
from types import SimpleNamespace

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.enhancement_utils import MODEL_CONFIG

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
    assert c["model"] == "qwen-3.8-27b" == MODEL_CONFIG["CANVAS_INTELLIPROMPTS"]
    assert c["thinking"] is False
    # the shape pydantic-ai forwards (top-level reasoning_effort / max_completion_tokens are dropped)
    assert c["settings"]["extra_body"] == {"reasoning_effort": "none"}
    assert "reasoning_effort" not in c["settings"] and "max_completion_tokens" not in c["settings"]


def test_intelliprompts_fall_back_to_groq_qwen_with_reasoning_off(monkeypatch):
    calls = _stub(monkeypatch, fail_primary=True)
    out = asyncio.run(cr._intelliprompts(REQ))
    assert len(out) == 1
    assert calls[1]["model"] == "qwen/qwen3.6-27b" == MODEL_CONFIG["CANVAS_INTELLIPROMPTS_FALLBACK"]
    assert calls[1]["thinking"] is False and calls[1]["settings"]["extra_body"] == {"reasoning_effort": "none"}
