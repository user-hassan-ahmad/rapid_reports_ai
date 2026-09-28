"""A model's API key comes from the model's provider, never from the caller.

Seventeen call sites fetch `get_system_api_key('cerebras', ...)` from when their roles ran
GLM on Cerebras. When those roles moved to Qwen on Groq the key was handed to Groq and
`_run_agent_with_model` wrote it into os.environ['GROQ_API_KEY'] (prod 401 on
/api/templates/skill-sheet/analyze, 2026-09-28). Writing keys into the process env also
races across concurrent requests.
"""
from __future__ import annotations

import os

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

import rapid_reports_ai.enhancement_utils as eu


class _Out(BaseModel):
    ok: bool


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("CEREBRAS_API_KEY", "cerebras-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")


@pytest.mark.asyncio
async def test_a_groq_model_uses_the_groq_key_even_when_handed_the_cerebras_key(keys, monkeypatch):
    seen = {}

    def fake_create(model_name, api_key, use_thinking=False):
        seen["key"] = api_key
        return TestModel()

    monkeypatch.setattr(eu, "_create_pydantic_model", fake_create)
    await eu._run_agent_with_model(
        model_name="qwen/qwen3.6-27b", output_type=_Out, system_prompt="s",
        user_prompt="u", api_key="cerebras-key",
    )
    assert seen["key"] == "groq-key"
    assert os.environ["GROQ_API_KEY"] == "groq-key"


@pytest.mark.parametrize("model_name,expected", [
    ("qwen/qwen3.6-27b", "groq-key"),
    ("claude-haiku-4-5-20251001", "anthropic-key"),
    ("gpt-oss-120b", "cerebras-key"),
    ("openai/gpt-oss-120b", "openrouter-key"),
])
def test_every_provider_client_carries_its_key_explicitly(keys, monkeypatch, model_name, expected):
    # Nothing may depend on the process env holding the right key at request time.
    for var in ("GROQ_API_KEY", "CEREBRAS_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(var, "wrong")
    model = eu._create_pydantic_model(model_name, expected)
    assert model.client.api_key == expected
