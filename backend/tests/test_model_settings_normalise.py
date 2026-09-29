"""pydantic-ai (1.14) reads only `max_tokens` and `extra_body` (plus `openai_reasoning_effort`)
from model settings: a top-level `reasoning_effort` or `max_completion_tokens` was silently
dropped, so every call ran at the provider's default reasoning with no cap (measured
2026-09-27: Cerebras qwen-3.8 asked for reasoning off + 1024 cap produced up to 18k tokens).

normalise_model_settings is the one place a role's settings become what the provider accepts:
- Cerebras qwen-3.8-27b defaults to reasoning HIGH, so an unset effort becomes medium (L-34).
- Groq qwen/qwen3.8-27b has a 16,384 output ceiling that reasoning counts toward, so it runs
  at low at most (L-41).
- gpt-oss cannot disable reasoning; `none` becomes low.
- Sonnet 5.5 rejects budget_tokens and any non-default temperature/top_p (HTTP 400).
- GLM-era `disable_reasoning` / `clear_thinking` toggles become an effort, never pass through.
"""
from __future__ import annotations

from rapid_reports_ai.enhancement_utils import (
    ANTHROPIC_MIN_MAX_TOKENS, GROQ_QWEN_MAX_TOKENS, TOKEN_CAP_FLOOR, normalise_model_settings,
)

CEREBRAS_QWEN = "qwen-3.8-27b"
GROQ_QWEN = "qwen/qwen3.8-27b"
SONNET = "claude-sonnet-5-5"


def effort(s):
    return (s.get("extra_body") or {}).get("reasoning_effort")


def test_reasoning_effort_reaches_the_request_for_models_that_accept_it():
    for model in ("gpt-oss-120b", "openai/gpt-oss-120b", CEREBRAS_QWEN):
        s = normalise_model_settings(model, {"temperature": 0.2, "reasoning_effort": "medium"})
        assert s == {"temperature": 0.2, "extra_body": {"reasoning_effort": "medium"}}


def test_an_explicit_extra_body_value_wins_and_other_keys_are_kept():
    s = normalise_model_settings("gpt-oss-120b", {"reasoning_effort": "high",
                                                  "extra_body": {"reasoning_effort": "low", "x": 1}})
    assert s["extra_body"] == {"reasoning_effort": "low", "x": 1}


def test_a_completion_cap_becomes_max_tokens_never_below_the_floor():
    # Caps written as max_completion_tokens were never enforced: a floor keeps anything that
    # works today from being cut off (a 50-token cap on a reasoning model would fail).
    assert normalise_model_settings("gpt-oss-120b", {"max_completion_tokens": 50})["max_tokens"] == TOKEN_CAP_FLOOR
    assert normalise_model_settings("gpt-oss-120b", {"max_completion_tokens": 32000})["max_tokens"] == 32000
    assert "max_completion_tokens" not in normalise_model_settings("gpt-oss-120b", {"max_completion_tokens": 50})


def test_an_explicit_max_tokens_is_left_alone():
    s = normalise_model_settings("gpt-oss-120b", {"max_tokens": 5000, "max_completion_tokens": 50})
    assert s == {"max_tokens": 5000, "extra_body": {"reasoning_effort": "medium"}}


def test_empty_and_none_settings_get_the_model_default_effort():
    assert normalise_model_settings("gpt-oss-120b", None) == {"extra_body": {"reasoning_effort": "medium"}}
    assert effort(normalise_model_settings(CEREBRAS_QWEN, {})) == "medium"
    assert effort(normalise_model_settings(GROQ_QWEN, {})) == "low"


# --- Cerebras Qwen 3.8 -------------------------------------------------------------------

def test_cerebras_qwen_never_falls_to_its_high_default():
    assert effort(normalise_model_settings(CEREBRAS_QWEN, {"temperature": 0.5})) == "medium"


def test_cerebras_qwen_off_stays_off_with_its_small_cap():
    s = normalise_model_settings(CEREBRAS_QWEN, {"max_tokens": 1500, "extra_body": {"reasoning_effort": "none"}})
    assert s == {"max_tokens": 1500, "extra_body": {"reasoning_effort": "none"}}


def test_cerebras_qwen_reasoning_on_is_never_capped_below_the_floor():
    # Reasoning counts toward the cap; a 3000 cap at medium truncates mid-reasoning (L-33).
    s = normalise_model_settings(CEREBRAS_QWEN, {"max_tokens": 3000})
    assert s["max_tokens"] == TOKEN_CAP_FLOOR


# --- Groq Qwen 3.8 -----------------------------------------------------------------------

def test_groq_qwen_runs_at_low_at_most():
    for asked in ("medium", "high"):
        assert effort(normalise_model_settings(GROQ_QWEN, {"reasoning_effort": asked})) == "low"
    assert effort(normalise_model_settings(GROQ_QWEN, {"reasoning_effort": "none"})) == "none"


def test_groq_qwen_cap_is_clamped_to_the_output_ceiling():
    assert normalise_model_settings(GROQ_QWEN, {"max_tokens": 65536})["max_tokens"] == GROQ_QWEN_MAX_TOKENS
    assert normalise_model_settings(GROQ_QWEN, {"max_completion_tokens": 50000})["max_tokens"] == GROQ_QWEN_MAX_TOKENS


# --- gpt-oss -----------------------------------------------------------------------------

def test_gpt_oss_cannot_disable_reasoning():
    assert effort(normalise_model_settings("gpt-oss-120b", {"reasoning_effort": "none"})) == "low"


# --- GLM-era toggles ---------------------------------------------------------------------

def test_glm_reasoning_toggles_become_an_effort():
    on = normalise_model_settings(CEREBRAS_QWEN, {"extra_body": {"disable_reasoning": False, "clear_thinking": False}})
    assert on["extra_body"] == {"reasoning_effort": "medium"}
    off = normalise_model_settings(GROQ_QWEN, {"extra_body": {"disable_reasoning": True}})
    assert off["extra_body"] == {"reasoning_effort": "none"}


def test_an_emptied_extra_body_is_dropped_for_models_without_effort():
    s = normalise_model_settings(SONNET, {"extra_body": {"disable_reasoning": False}})
    assert "disable_reasoning" not in str(s)


# --- Sonnet 5.5 --------------------------------------------------------------------------

def test_sonnet_drops_sampling_params_it_rejects():
    s = normalise_model_settings(SONNET, {"temperature": 1, "top_p": 0.9, "max_tokens": 6500})
    assert "temperature" not in s and "top_p" not in s


def test_sonnet_thinking_budget_becomes_adaptive_with_an_effort():
    s = normalise_model_settings(SONNET, {"anthropic_thinking": {"type": "enabled", "budget_tokens": 2048}})
    assert s["anthropic_thinking"] == {"type": "adaptive"}
    assert s["extra_body"]["output_config"] == {"effort": "medium"}
    s = normalise_model_settings(SONNET, {"reasoning_effort": "high"})
    assert s["extra_body"]["output_config"] == {"effort": "high"}
    assert "reasoning_effort" not in s["extra_body"]


def test_sonnet_cap_leaves_room_for_thinking():
    assert normalise_model_settings(SONNET, {"max_tokens": 3000})["max_tokens"] == ANTHROPIC_MIN_MAX_TOKENS
