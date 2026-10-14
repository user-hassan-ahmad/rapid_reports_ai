"""One recommendations rule in both stack briefs (integration spec §6, D22, seam 23): recommendations sit in the
impression's last line; no separate section and none of its leftovers."""
from pathlib import Path

from rapid_reports_ai.hybrid_stack.session_rules import RECOMMENDATIONS_RULE, SELECTED_RECS
from rapid_reports_ai.quick_report_brief import stack_fallback
from rapid_reports_ai.quick_report_generator import build_prompts
from rapid_reports_ai.template_stack import stack_brief

SRC = Path(__file__).resolve().parents[1] / "src" / "rapid_reports_ai"


def test_both_stack_briefs_carry_the_one_rule_once():
    q = stack_fallback("## Structural Pattern\n- x", "Normal study.", []).text
    t = stack_brief("## FINDINGS\nx", "Normal study.", [])
    assert q.count(RECOMMENDATIONS_RULE) == 1 and t.count(RECOMMENDATIONS_RULE) == 1
    assert SELECTED_RECS in RECOMMENDATIONS_RULE
    assert "Scratchpad Recommendations" not in q and "RECOMMENDATIONS:" not in q + t


def test_conclusion_lines_defer_to_the_session_rule():
    q = stack_fallback("## Structural Pattern\n- x", "Normal study.", []).text
    t = stack_brief("## FINDINGS\nx", "Normal study.", [])
    for b in (q, t):
        assert "no diagnosis, grade, negative or recommendation" not in b
        assert "a recommendation only as the session rules allow" in b


def test_stack_prompts_have_no_recommendations_section_and_no_contradiction():
    sys_p, user_p = build_prompts("SHEET", "CT", "f", "h", "cerebras", brief=True, stack=True)
    for p in (sys_p, user_p):
        assert "RECOMMENDATIONS:" not in p and "Scratchpad Recommendations" not in p
        assert "No recommendation appears unless the confirmed conclusion contains it;" not in p
        assert "A recommendation appears only where the confirmed conclusion contains one" not in p


def test_template_stack_prompts_have_no_contradiction():
    from rapid_reports_ai import global_style_guide as G
    for p in (G.GLOBAL_STYLE_GUIDE_STACK, G.PRE_WRITING_ANALYSIS_STACK, G.VERIFICATION_CHECKLIST_STACK):
        assert "No recommendation appears unless the confirmed conclusion contains it;" not in p
        assert "A recommendation appears only where the confirmed conclusion contains one" not in p


def test_no_recommendations_section_role_left():
    assert '"RECOMMENDATIONS")' not in (SRC / "report_review.py").read_text()
    assert '"recommendations"}' not in (SRC / "review_engine" / "alignment.py").read_text()
    assert "RECS_LINE" not in (SRC / "quick_report_brief.py").read_text()
