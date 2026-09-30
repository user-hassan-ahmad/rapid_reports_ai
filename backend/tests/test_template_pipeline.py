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
