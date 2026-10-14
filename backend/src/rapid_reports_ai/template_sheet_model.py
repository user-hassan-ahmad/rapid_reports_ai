"""The model call behind sheet writing and repair: the lean analyser's model (SKILL_SHEET_ANALYZER)."""
from __future__ import annotations

from typing import Dict


async def model_call(system: str, user: str, settings: Dict) -> str:
    """The lean analyser's model (SKILL_SHEET_ANALYZER) with the given settings."""
    from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model

    result = await _run_agent_with_model(
        model_name=MODEL_CONFIG["SKILL_SHEET_ANALYZER"], output_type=str, system_prompt=system,
        user_prompt=user, api_key="", use_thinking=True, model_settings=settings)
    return result.output if hasattr(result, "output") else str(result)
