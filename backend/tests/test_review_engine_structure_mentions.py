"""Quiet "area never mentioned" notes (review_engine/structure_mentions.py), Jev mocked."""
import asyncio

import pytest

from rapid_reports_ai.review_engine import structure_mentions as sm
from tests.test_review_engine_template_gaps import REPORT, RUN, _inp


def _ask(p_of):
    """A stand-in for the Jev call: P(yes) per structure name (default 0.95), recording the request."""
    seen = {}

    async def ask(report, names):
        seen["report"], seen["names"] = report, list(names)
        return [p_of.get(n, 0.95) for n in names]
    return ask, seen


def _notes(items):
    return [(it.kind, it.evidence["structure"]) for it in items]


def test_question_wording_and_state_are_the_lab_ones():
    q = sm.question("LMS")
    assert q == {"type": "noul", "instructions": "The REPORT states anything about the LMS."}
    assert sm.state("text") == "REPORT:\ntext"


@pytest.mark.asyncio
async def test_one_question_per_findings_covers_structure_and_a_clean_report_has_no_note():
    ask, seen = _ask({})
    items, log = await sm.mention_items(_inp(), RUN, ask=ask)
    assert items == [] and log["structure_asked"] == len(seen["names"])
    assert "LMS" in seen["names"] and "coronary calcium score" in seen["names"] and "BONES" in seen["names"]
    assert seen["report"] == REPORT


@pytest.mark.asyncio
async def test_a_structure_below_the_threshold_is_a_quiet_note():
    ask, _ = _ask({"LEFT ATRIAL APPENDAGE": 0.1, "LMS": 0.29, "RCA": 0.3})
    items, log = await sm.mention_items(_inp(), RUN, ask=ask)
    assert _notes(items) == [("structure_not_mentioned", "LMS"), ("structure_not_mentioned", "LEFT ATRIAL APPENDAGE")]
    it = items[1]
    assert it.label == "Not mentioned: Left Atrial Appendage — worth a look"
    assert it.cls == "info" and it.edit is None and it.anchor is None and it.status == "open"
    assert log["structure_not_mentioned"] == 2


@pytest.mark.asyncio
async def test_notes_are_capped_at_four():
    ask, seen = _ask({})
    await sm.mention_items(_inp(), RUN, ask=ask)
    ask2, _ = _ask({n: 0.0 for n in seen["names"]})
    items, log = await sm.mention_items(_inp(), RUN, ask=ask2)
    assert len(items) == sm.MAX_NOTES == 4 and log["capped"] == len(seen["names"]) - 4


@pytest.mark.parametrize("fail", ["raise", "short", "timeout"])
@pytest.mark.asyncio
async def test_a_jev_failure_gives_no_note_and_is_counted(fail, monkeypatch):
    async def ask(report, names):
        if fail == "raise":
            raise RuntimeError("down")
        if fail == "timeout":
            await asyncio.sleep(1)
        return [0.0]
    monkeypatch.setattr(sm, "TIMEOUT_S", 0.05)
    items, log = await sm.mention_items(_inp(), RUN, ask=ask)
    assert items == [] and log["structure_check_unavailable"] == 1


@pytest.mark.asyncio
async def test_quick_reports_ask_nothing():
    called = []

    async def ask(report, names):
        called.append(1)
        return []
    assert await sm.mention_items(_inp(template=False), RUN, ask=ask) == ([], None)
    assert called == []


@pytest.mark.asyncio
async def test_a_paragraph_a_suppress_rule_left_out_is_not_asked():
    _, seen = _ask({})
    i = _inp()
    st = dict(i.template_structure)
    st["rules"] = list(st["rules"]) + [{"id": "rx", "section": "FINDINGS", "paragraph": "p3", "condition": "c",
                                        "effect": "suppress_section", "target": "Coronary Findings",
                                        "source_lines": []}]
    start = REPORT.index("Coronary Findings:")
    gone = REPORT[:start] + REPORT[REPORT.index("Other findings:"):]
    ask, seen = _ask({})
    await sm.mention_items(i.model_copy(update={"template_structure": st, "artifacts": i.artifacts.model_copy(
        update={"report": gone})}), RUN, ask=ask)
    assert "LMS" not in seen["names"] and "BONES" in seen["names"]
    ask2, seen2 = _ask({})
    await sm.mention_items(i.model_copy(update={"template_structure": st}), RUN, ask=ask2)   # present: still asked
    assert "LMS" in seen2["names"]


def test_title():
    assert sm.title("LEFT ATRIAL APPENDAGE") == "Left Atrial Appendage"
    assert sm.title("LMS") == "LMS"
    assert sm.title("coronary calcium score") == "Coronary Calcium Score"
    assert sm.title("CTCA technique") == "CTCA Technique"


@pytest.mark.asyncio
async def test_ask_mentioned_sends_one_request_and_refuses_a_partial_answer(monkeypatch):
    from rapid_reports_ai import jev_client
    sent = []

    class R:
        def __init__(self, ans):
            self.ans = ans

        def raise_for_status(self):
            pass

        def json(self):
            return {"answers": self.ans}

    def post(ans):
        async def f(body, key, timeout, transport=None):
            sent.append(body)
            return R(ans)
        return f
    monkeypatch.setattr(jev_client, "jev_post", post({"s0": {"noul": 0.9}, "s1": {"noul": 0.1}}))
    assert await sm.ask_mentioned("rep", ["LMS", "LAD"]) == [0.9, 0.1]
    assert len(sent) == 1 and sent[0]["state"] == "REPORT:\nrep" and sent[0]["model"] == jev_client.JEV_MODEL
    assert sent[0]["questions"]["s1"]["instructions"] == "The REPORT states anything about the LAD."
    monkeypatch.setattr(jev_client, "jev_post", post({"s0": {"noul": 0.9}}))
    with pytest.raises(ValueError):
        await sm.ask_mentioned("rep", ["LMS", "LAD"])


@pytest.mark.asyncio
async def test_run_review_carries_the_quiet_notes_beside_the_gap_flags(monkeypatch):
    from rapid_reports_ai import report_reconcile as rc
    from rapid_reports_ai.review_engine import adjudicator as adj
    from rapid_reports_ai.review_engine import engine, negatives
    from tests.review_engine_fakes import jev

    async def no_neg(inp_, run_id, types=None, owned=None):
        return [], {"candidates": []}

    async def judge(inp_, groups):
        return [adj.Outcome(group=g) for g in groups]

    async def ask(report, names):
        return [0.05 if n == "BONES" else 0.9 for n in names]
    monkeypatch.setattr(rc, "_jev", jev())
    monkeypatch.setattr(negatives, "classify_negatives", no_neg)
    monkeypatch.setattr(adj, "adjudicate", judge)
    monkeypatch.setattr(sm, "ask_mentioned", ask)
    res = await engine.run_review(_inp(), RUN)
    assert _notes([i for i in res.items if i.kind == sm.KIND]) == [(sm.KIND, "BONES")]
    log = res.run["template_gaps"]
    assert log[sm.KIND] == 1 and log["structure_check_unavailable"] == 0 and log["fixed_text_missing"] == 0

    async def down(report, names):
        raise RuntimeError("down")
    monkeypatch.setattr(sm, "ask_mentioned", down)
    res = await engine.run_review(_inp(), RUN)
    assert not [i for i in res.items if i.kind == sm.KIND] and res.run["template_gaps"]["structure_check_unavailable"] == 1


@pytest.mark.asyncio
async def test_structures_of_a_paragraph_of_only_conditional_fill_ins_are_not_asked():
    ask, seen = _ask({"LMS": 0.0})
    items, _ = await sm.mention_items(_inp(), RUN, ask=ask)
    for n in ("medication", "scan quality", "heart rate", "radiation dose"):
        assert n not in seen["names"]
    assert _notes(items) == [(sm.KIND, "LMS")]


FIXED_USE_SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Paragraph: Technique (FINDINGS)
COVERS ["contrast"]
FIXED "Images were acquired after intravenous contrast."
RULE WHEN [context: the contrast dose is stated] USE "Contrast dose: {dose} ml."

## Paragraph: Lungs (FINDINGS)
COVERS ["lungs"]
NORMAL [lungs] "The lungs are clear."
"""


def test_fixed_units_carry_their_paragraph_and_old_stored_ones_still_load():
    from rapid_reports_ai.template_sheet_grammar import parse_sheet
    from rapid_reports_ai.template_sheet_structure import FixedBlock
    st = parse_sheet(FIXED_USE_SHEET).structure
    assert st.usable and [f.paragraph for f in st.fixed_blocks] == ["p0"]
    assert FixedBlock.model_validate({"id": "f0", "section": "FINDINGS", "text": "x"}).paragraph == ""
    assert "paragraph" not in FixedBlock.model_json_schema()["properties"]


@pytest.mark.asyncio
async def test_a_paragraph_with_an_untargeted_fixed_line_and_only_use_rules_is_asked():
    from rapid_reports_ai.review_engine.template_text import template_inputs
    texts, st = template_inputs({"generation_mode": "skill_sheet_guided", "skill_sheet": FIXED_USE_SHEET})
    i = _inp().model_copy(update={"template_text": texts, "template_structure": st})
    ask, seen = _ask({})
    await sm.mention_items(i, RUN, ask=ask)
    assert seen["names"] == ["contrast", "lungs"]


@pytest.mark.asyncio
async def test_an_old_stored_structure_places_a_fixed_line_through_a_rule_that_targets_it():
    from rapid_reports_ai.review_engine.template_text import template_inputs
    texts, st = template_inputs({"generation_mode": "skill_sheet_guided", "skill_sheet": FIXED_USE_SHEET})
    for f in st["fixed_blocks"]:
        f.pop("paragraph", None)                      # stored before FIXED units carried their paragraph
    for r in st["rules"]:
        if r["effect"] == "use":
            r["target"] = st["fixed_blocks"][0]["text"]
    i = _inp().model_copy(update={"template_text": texts, "template_structure": st})
    ask, seen = _ask({})
    await sm.mention_items(i, RUN, ask=ask)
    assert seen["names"] == ["contrast", "lungs"]


def test_structures_of_missing_normals_map_normals_and_unambiguous_negatives_only():
    i = _inp()
    assert sm.structures_of(i, ["LMS: Normal."]) == {"LMS"}
    # "Other Findings" covers eight structures: an untagged negative there is ambiguous
    assert sm.structures_of(i, ["No pleural or pericardial effusion."]) == set()
    assert sm.structures_of(i, ["Not a template sentence."]) == set()


def test_structures_of_an_untagged_negative_in_a_one_structure_paragraph():
    from rapid_reports_ai.review_engine.template_text import template_inputs
    sheet = FIXED_USE_SHEET + 'NEGATIVE "No pleural effusion."\n'
    texts, st = template_inputs({"generation_mode": "skill_sheet_guided", "skill_sheet": sheet})
    i = _inp().model_copy(update={"template_text": texts, "template_structure": st})
    assert sm.structures_of(i, ["No pleural effusion."]) == {"lungs"}


@pytest.mark.asyncio
async def test_run_review_drops_the_note_of_a_structure_whose_confirmed_normal_is_flagged(monkeypatch):
    from rapid_reports_ai import report_reconcile as rc
    from rapid_reports_ai.review_engine import adjudicator as adj
    from rapid_reports_ai.review_engine import engine, negatives
    from tests.review_engine_fakes import jev
    from tests.test_review_engine_template_gaps import NORMALS

    async def no_neg(inp_, run_id, types=None, owned=None):
        return [], {"candidates": []}

    async def judge(inp_, groups):
        return [adj.Outcome(group=g) for g in groups]

    async def ask(report, names):
        return [0.05 if n in ("LMS", "BONES") else 0.9 for n in names]
    monkeypatch.setattr(rc, "_jev", jev())
    monkeypatch.setattr(negatives, "classify_negatives", no_neg)
    monkeypatch.setattr(adj, "adjudicate", judge)
    monkeypatch.setattr(sm, "ask_mentioned", ask)
    res = await engine.run_review(_inp(REPORT.replace(NORMALS[0] + "\n", "")), RUN)
    kinds = [(i.kind, i.evidence.get("structure") or i.evidence.get("text")) for i in res.items
             if i.kind in (sm.KIND, "assumed_normal_missing")]
    assert ("assumed_normal_missing", "LMS: Normal.") in kinds
    assert (sm.KIND, "BONES") in kinds and (sm.KIND, "LMS") not in kinds
    assert res.run["template_gaps"]["mention_dropped_for_gap"] == 1


def test_the_note_drop_compares_structure_names_case_and_space_insensitively():
    notes = [sm.ReviewItem(key=f"k{n}", report_id="r", run_id=RUN, lane="accuracy", detectors=[], kind=sm.KIND,
                           cls="info", label="", reason="", evidence={"structure": n}, status="open", history=[])
             for n in ("liver", "  Left  atrial appendage", "BONES")]
    kept = sm.drop_flagged(notes, {"Liver", "LEFT ATRIAL APPENDAGE"})
    assert [it.evidence["structure"] for it in kept] == ["BONES"]


async def test_a_structure_the_radiologist_removed_gets_no_note(monkeypatch):
    from rapid_reports_ai import report_reconcile as rc
    from rapid_reports_ai.review_engine import adjudicator as adj
    from rapid_reports_ai.review_engine import engine, negatives
    from tests.review_engine_fakes import jev
    from tests.test_review_engine_template_gaps import NORMALS

    async def no_neg(inp_, run_id, types=None, owned=None):
        return [], {"candidates": []}

    async def judge(inp_, groups):
        return [adj.Outcome(group=g) for g in groups]

    async def ask(report, names):
        return [0.05 if n == "LMS" else 0.9 for n in names]
    monkeypatch.setattr(rc, "_jev", jev())
    monkeypatch.setattr(negatives, "classify_negatives", no_neg)
    monkeypatch.setattr(adj, "adjudicate", judge)
    monkeypatch.setattr(sm, "ask_mentioned", ask)
    i = _inp(REPORT.replace(NORMALS[0] + "\n", ""), assumed=NORMALS[1:], removed=[NORMALS[0]])
    res = await engine.run_review(i, RUN)
    assert (sm.KIND, "LMS") not in [(x.kind, x.evidence.get("structure")) for x in res.items]
