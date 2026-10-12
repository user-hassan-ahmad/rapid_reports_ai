"""Tests for the skill-sheet analyser's JSON extraction.

The skill sheet is markdown that often quotes example text in ``` fences and
uses {placeholder} slots, so the parser must not mistake inner fences or
placeholders for the JSON envelope.
"""
from __future__ import annotations

import json

import pytest

from rapid_reports_ai.template_manager import TemplateManager

KEYS = ["skill_sheet", "summary", "questions"]
SHEET = (
    "# Skill Sheet: MRI shoulder\n## Fixed Blocks\n"
    "```\nMRI of the {laterality} shoulder performed at 1.5 Tesla.\n```\n"
)
PAYLOAD = {"skill_sheet": SHEET, "summary": {"structure": {}}, "questions": []}
BODY = json.dumps(PAYLOAD)


@pytest.mark.parametrize(
    "raw",
    [
        BODY,
        f"```json\n{BODY}\n```",
        f"```\n{BODY}\n```",
        f"Here is the skill sheet:\n{BODY}\nLet me know if you need changes.",
        f"Here you go:\n```json\n{BODY}\n```\nDone.",
    ],
    ids=["bare", "json-fence", "plain-fence", "prose-around", "prose-and-fence"],
)
def test_parses_sheet_containing_code_fence(raw):
    parsed = TemplateManager._parse_skill_sheet_json(raw, KEYS)
    assert parsed == PAYLOAD


def test_missing_keys_still_raises():
    with pytest.raises(ValueError, match="missing keys"):
        TemplateManager._parse_skill_sheet_json(json.dumps({"skill_sheet": SHEET}), KEYS)


def test_no_json_raises_clear_error():
    with pytest.raises(ValueError, match="No JSON object"):
        TemplateManager._parse_skill_sheet_json("Sorry, I cannot help with {that}.", KEYS)
