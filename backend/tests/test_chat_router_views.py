"""Each targeted call gets only its part of the sheet (spec Flow 2)."""
from rapid_reports_ai import chat_router_ledger as L
from rapid_reports_ai import chat_router_views as V
from tests.template_sheet_fixtures import ROUTER_SHEET


def test_value_view_lists_each_value_with_its_need():
    led, _ = L.set_choice(L.seed_values([], ROUTER_SHEET), "value", "Depth", {"need": "relevant"})
    v = V.view("value", ROUTER_SHEET, led)
    assert "- Width: every report must state it" in v and "- Depth: stated only when relevant" in v
    assert "NORMAL" not in v and "Alpha" not in v


def test_concept_view_names_every_concept_and_the_printed_sentences():
    v = V.view("concept", ROUTER_SHEET, [])
    for name in L.CONCEPTS:
        assert f"- {name} (" in v
    assert "- contrast (Contrast; states: given, not_given): not stated" in v
    assert '- "No previous imaging available."' in v


def test_concept_view_names_the_usual_state_and_the_condition():
    from tests.template_sheet_fixtures import ROUTER_SHEET_CONCEPT
    v = V.view("concept", ROUTER_SHEET_CONCEPT, [])
    assert ('- comparison (Comparison with previous imaging; states: none, compared): default '
            '"No previous imaging available." (printed when none); when_met "Compared with the {study} of {date}." '
            '(condition: compared)') in v


def test_fixed_view_lists_sentences_with_their_paragraph():
    v = V.view("fixed", ROUTER_SHEET, [])
    assert '- in Technique: "Axial images were acquired."' in v and "PARAGRAPHS: Technique, Upper, Lower" in v


def test_normal_view_groups_by_paragraph():
    v = V.view("normal", ROUTER_SHEET, [])
    assert 'Paragraph "Upper" (reports: alpha, beta):' in v
    assert '  normal alpha: "Alpha is normal."' in v and '  negative: "No beta abnormality."' in v


def test_layout_view_uses_title_case_section_names():
    v = V.view("layout", ROUTER_SHEET, [])
    assert '- Findings (printed heading "Findings:", role findings)' in v and "- Lower, in section Findings" in v
    assert "FINDINGS" not in v


def test_style_view_shows_prose_blocks_only():
    v = V.view("style", ROUTER_SHEET, [])
    assert '[b4] under "Impression Construction":\nLead with the most important finding.' in v
    assert "An imaging study" not in v and "NORMAL" not in v and "FIXED" not in v
