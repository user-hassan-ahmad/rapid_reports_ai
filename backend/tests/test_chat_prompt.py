"""
Unit tests for ``chat_prompt.build_chat_system_prompt`` and helpers.

The composer is a pure function — no fixtures, no DB, no client. We
assert directly on the rendered prompt structure.

See ``docs/superpowers/specs/2026-04-26-chat-prompt-revamp-design.md``
for the design.
"""
from __future__ import annotations

from rapid_reports_ai.chat_prompt import (
    CHAT_PROMPT_PREAMBLE,
    _build_active_context,
    _strip_leading_header,
    _wrap_audit_fix_mode,
    build_chat_system_prompt,
)


# ─────────────────────────────────────────────────────────────────────────────
# Static preamble
# ─────────────────────────────────────────────────────────────────────────────

def test_preamble_includes_orientation_and_all_principles():
    """The static constant carries every principle the spec promises."""
    assert "## Orientation" in CHAT_PROMPT_PREAMBLE
    assert "## Principle 1 — Address the clinician" in CHAT_PROMPT_PREAMBLE
    assert "## Principle 2 — Two voices for two destinations" in CHAT_PROMPT_PREAMBLE
    assert "## Principle 3 — Decide once whether to apply" in CHAT_PROMPT_PREAMBLE
    assert "## Principle 4 — Search only when evidence is missing" in CHAT_PROMPT_PREAMBLE
    assert "## Principle 5 — Declare your sources" in CHAT_PROMPT_PREAMBLE


def test_preamble_routing_default_is_apply():
    """Principle 3's default-to-apply stance must be explicit, not implied."""
    assert "default to applying" in CHAT_PROMPT_PREAMBLE


def test_preamble_sources_used_protocol_present():
    """The <SOURCES_USED> output protocol is in Principle 5."""
    assert "<SOURCES_USED>" in CHAT_PROMPT_PREAMBLE


# ─────────────────────────────────────────────────────────────────────────────
# _strip_leading_header
# ─────────────────────────────────────────────────────────────────────────────

def test_strip_leading_header_removes_h2():
    assert _strip_leading_header("## EVIDENCE\n\nbody text") == "body text"


def test_strip_leading_header_removes_h1():
    assert _strip_leading_header("# EVIDENCE\n\nbody text") == "body text"


def test_strip_leading_header_removes_deeper_levels():
    assert _strip_leading_header("### EVIDENCE\n\nbody") == "body"
    assert _strip_leading_header("#### EVIDENCE\n\nbody") == "body"
    assert _strip_leading_header("###### EVIDENCE\n\nbody") == "body"


def test_strip_leading_header_removes_setext_equals_delimiter():
    """`=== TITLE ===` is the form ``build_chat_guideline_context`` emits."""
    src = "\n\n=== EVIDENCE CONTEXT ===\nThe following source excerpts ground answers."
    assert _strip_leading_header(src) == "The following source excerpts ground answers."


def test_strip_leading_header_removes_setext_dashes_delimiter():
    src = "--- TITLE ---\nbody"
    assert _strip_leading_header(src) == "body"


def test_strip_leading_header_passthrough_when_no_header():
    assert _strip_leading_header("body only, no heading") == "body only, no heading"


def test_strip_leading_header_only_strips_one():
    """Two stacked headers — only the first is stripped."""
    src = "## Outer\n\n## Inner\n\nbody"
    assert _strip_leading_header(src) == "## Inner\n\nbody"


def test_strip_leading_header_handles_empty_input():
    assert _strip_leading_header("") == ""
    assert _strip_leading_header("   \n\n   ") == ""


def test_strip_leading_header_handles_leading_blank_lines():
    """Helpers like ``format_audit_fix_holistic_workflow_instructions`` open with `\\n\\n`."""
    src = "\n\n## AUDIT QA GROUNDING\nThe following is the anchor."
    assert _strip_leading_header(src) == "The following is the anchor."


# ─────────────────────────────────────────────────────────────────────────────
# _wrap_audit_fix_mode
# ─────────────────────────────────────────────────────────────────────────────

def test_wrap_audit_fix_mode_promotes_to_consistent_h2():
    src = (
        "\n\n## Audit-triggered fix (holistic workflow)\n\n"
        "**Trigger vs task:** ...rest of body..."
    )
    result = _wrap_audit_fix_mode(src)
    assert result.startswith("## Audit-fix mode\n\n")
    assert "**Trigger vs task:**" in result
    # Original (now-stripped) header should be absent.
    assert "Audit-triggered fix (holistic workflow)" not in result


def test_wrap_audit_fix_mode_returns_empty_for_empty_input():
    assert _wrap_audit_fix_mode("") == ""
    assert _wrap_audit_fix_mode("\n\n   ") == ""


# ─────────────────────────────────────────────────────────────────────────────
# _build_active_context
# ─────────────────────────────────────────────────────────────────────────────

def test_active_context_renders_when_all_blocks_present():
    out = _build_active_context(
        report_content="FINDINGS: liver normal.",
        enhancement_context="=== EVIDENCE CONTEXT ===\nNICE NG147 …",
        audit_memory_block="## LATEST AUDIT GUIDELINE CONTEXT\nLast audit ran on …",
        audit_fix_block="## AUDIT QA GROUNDING\nCriterion: clinical_flagging …",
    )
    assert "## Active context" in out
    assert "### Report draft" in out
    assert "### Evidence retrieved" in out
    assert "### Audit memory" in out
    assert "### Audit fix in progress" in out
    # Subsection order must match the spec.
    assert out.index("### Report draft") < out.index("### Evidence retrieved")
    assert out.index("### Evidence retrieved") < out.index("### Audit memory")
    assert out.index("### Audit memory") < out.index("### Audit fix in progress")


def test_active_context_omits_empty_blocks():
    out = _build_active_context(
        report_content="FINDINGS: liver normal.",
        enhancement_context="",
        audit_memory_block="",
        audit_fix_block="",
    )
    assert "### Report draft" in out
    assert "### Evidence retrieved" not in out
    assert "### Audit memory" not in out
    assert "### Audit fix in progress" not in out


def test_active_context_header_omitted_when_all_blocks_empty():
    """Defensive — should never happen in production (report always present)
    but the helper must degrade gracefully."""
    out = _build_active_context(
        report_content="",
        enhancement_context="",
        audit_memory_block="",
        audit_fix_block="",
    )
    assert out == ""


def test_active_context_strips_existing_block_headers():
    """The envelope's H3 replaces the helper's own header — no duplication."""
    out = _build_active_context(
        report_content="report body",
        enhancement_context="=== EVIDENCE CONTEXT ===\nevidence body",
        audit_memory_block="",
        audit_fix_block="",
    )
    # Envelope header present, original helper header gone.
    assert "### Evidence retrieved" in out
    assert "=== EVIDENCE CONTEXT ===" not in out
    assert "evidence body" in out


# ─────────────────────────────────────────────────────────────────────────────
# build_chat_system_prompt — composition
# ─────────────────────────────────────────────────────────────────────────────

def test_composer_renders_principles_then_active_context():
    out = build_chat_system_prompt(
        report_content="FINDINGS: liver normal.",
        enhancement_context="",
        audit_memory_block="",
        audit_holistic_block="",
        audit_fix_block="",
    )
    assert "## Orientation" in out
    assert "## Principle 5" in out
    assert "## Active context" in out
    assert "### Report draft" in out
    # Principles come before Active context.
    assert out.index("## Principle 5") < out.index("## Active context")


def test_composer_includes_audit_fix_mode_only_when_holistic_block_set():
    holistic = (
        "\n\n## Audit-triggered fix (holistic workflow)\n\n"
        "**Trigger vs task:** ..."
    )
    with_holistic = build_chat_system_prompt(
        report_content="FINDINGS",
        enhancement_context="",
        audit_memory_block="",
        audit_holistic_block=holistic,
        audit_fix_block="",
    )
    assert "## Audit-fix mode" in with_holistic
    # Audit-fix mode sits between principles and Active context.
    assert with_holistic.index("## Principle 5") < with_holistic.index("## Audit-fix mode")
    assert with_holistic.index("## Audit-fix mode") < with_holistic.index("## Active context")

    without_holistic = build_chat_system_prompt(
        report_content="FINDINGS",
        enhancement_context="",
        audit_memory_block="",
        audit_holistic_block="",
        audit_fix_block="",
    )
    assert "## Audit-fix mode" not in without_holistic


def test_composer_no_triple_blank_lines():
    """Cosmetic — output should never contain three or more consecutive newlines."""
    out = build_chat_system_prompt(
        report_content="FINDINGS",
        enhancement_context="=== EVIDENCE CONTEXT ===\nbody",
        audit_memory_block="## LATEST AUDIT GUIDELINE CONTEXT\nbody",
        audit_holistic_block="## Audit-triggered fix (holistic workflow)\n\nbody",
        audit_fix_block="## AUDIT QA GROUNDING\nbody",
    )
    assert "\n\n\n" not in out


def test_composer_preserves_principle_substance():
    """Each principle's content survives composition (whitespace normalises)."""
    out = build_chat_system_prompt(
        report_content="x",
        enhancement_context="",
        audit_memory_block="",
        audit_holistic_block="",
        audit_fix_block="",
    )
    # Headers from every principle — composition must not drop or rename any.
    for header in (
        "## Orientation",
        "## Principle 1 — Address the clinician",
        "## Principle 2 — Two voices for two destinations",
        "## Principle 3 — Decide once whether to apply",
        "## Principle 4 — Search only when evidence is missing",
        "## Principle 5 — Declare your sources",
    ):
        assert header in out
    # Spot-check distinctive content from each principle survives.
    assert "Use British English throughout" in out
    assert "Speak to them in clinical terms" in out
    assert "different voice depending on" in out
    assert "default to applying" in out
    assert "Retrieve first" in out
    assert "<SOURCES_USED>" in out
