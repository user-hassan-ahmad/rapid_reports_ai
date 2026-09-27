"""pydantic-ai (1.14) reads only `max_tokens` and `extra_body` (plus `openai_reasoning_effort`)
from model settings: a top-level `reasoning_effort` or `max_completion_tokens` was silently
dropped, so every call ran at the provider's default reasoning with no cap (measured
2026-09-27: Cerebras qwen-3.8 asked for reasoning off + 1024 cap produced up to 18k tokens)."""
from __future__ import annotations

from rapid_reports_ai.enhancement_utils import TOKEN_CAP_FLOOR, normalise_model_settings


def test_reasoning_effort_reaches_the_request_for_models_that_accept_it():
    for model in ("gpt-oss-120b", "openai/gpt-oss-120b", "qwen-3.8-27b"):
        s = normalise_model_settings(model, {"temperature": 0.2, "reasoning_effort": "medium"})
        assert s == {"temperature": 0.2, "extra_body": {"reasoning_effort": "medium"}}


def test_an_explicit_extra_body_value_wins_and_other_keys_are_kept():
    s = normalise_model_settings("gpt-oss-120b", {"reasoning_effort": "high",
                                                  "extra_body": {"reasoning_effort": "low", "x": 1}})
    assert s["extra_body"] == {"reasoning_effort": "low", "x": 1}


def test_models_not_known_to_accept_it_keep_todays_behaviour():
    # Fireworks GLM / Groq qwen: dropped, exactly as before (Groq qwen rejects 'medium').
    for model in ("accounts/fireworks/models/glm-5p1", "qwen/qwen3.6-27b", "zai-glm-4.7"):
        s = normalise_model_settings(model, {"reasoning_effort": "high", "temperature": 0.6})
        assert s == {"temperature": 0.6}


def test_a_completion_cap_becomes_max_tokens_never_below_the_floor():
    # Caps written as max_completion_tokens were never enforced: a floor keeps anything that
    # works today from being cut off (a 50-token cap on a reasoning model would fail).
    assert normalise_model_settings("gpt-oss-120b", {"max_completion_tokens": 50})["max_tokens"] == TOKEN_CAP_FLOOR
    assert normalise_model_settings("gpt-oss-120b", {"max_completion_tokens": 32000})["max_tokens"] == 32000
    assert "max_completion_tokens" not in normalise_model_settings("gpt-oss-120b", {"max_completion_tokens": 50})


def test_an_explicit_max_tokens_is_left_alone():
    s = normalise_model_settings("gpt-oss-120b", {"max_tokens": 5000, "max_completion_tokens": 50})
    assert s == {"max_tokens": 5000}


def test_empty_and_none_settings():
    assert normalise_model_settings("gpt-oss-120b", None) == {}
    assert normalise_model_settings("gpt-oss-120b", {}) == {}
