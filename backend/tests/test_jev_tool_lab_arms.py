# backend/tests/test_jev_tool_lab_arms.py
from rapid_reports_ai.scripts.jev_tool_lab import prompts
from rapid_reports_ai.scripts.jev_tool_lab.scenarios import S1Item, s1_user

ITEM = S1Item(id="s1-t", origin="synthetic", scan_type="CT abdomen",
              dictation="Left renal lesion 3 cm with a thin wall and two thin septa. No enhancement.",
              finding="Left renal lesion 3 cm with a thin wall and two thin septa.", system="Bosniak 2019",
              gradable=True)


def test_s1_user_carries_case_finding_and_system():
    u = s1_user(ITEM)
    assert "DICTATED FINDINGS:\nLeft renal lesion" in u
    assert "FINDING: Left renal lesion 3 cm" in u
    assert "CLASSIFICATION SYSTEM: Bosniak 2019" in u


def test_author_prompt_lists_catalogue_and_forbids_inference():
    p = prompts.author_system()
    for t in ("T1", "T2", "T3", "T4", "T5", "T6"):
        assert t in p
    assert "Never ask what imaging would show" in p
    assert "before seeing any answer" in p


def test_free_prompt_has_no_catalogue():
    p = prompts.free_author_system()
    assert "T2" not in p and "noul" in p


def test_decide_prompt_treats_answers_as_evidence():
    assert "evidence" in prompts.decide_system() and "not as verdicts" in prompts.decide_system()
