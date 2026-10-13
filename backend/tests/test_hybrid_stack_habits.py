"""Findings-triggered habits in the scratchpad (spec 2026-10-13-findings-triggered-rows-design): read from the
template, triggered by one Jev call."""
import json

import httpx
import pytest

from rapid_reports_ai import template_context_rules as tcr
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_sheet_grammar as tsg
from rapid_reports_ai.hybrid_stack import habits as H
from rapid_reports_ai.hybrid_stack.template import paragraph_regions, template_regions
from tests.template_sheet_fixtures import HABIT_SHEET
from tests.test_template_sheet_lab_prompts import CLINICAL

ASK_LINE = ('RULE WHEN [findings: a focal liver abnormality is reported] ASK "Extension into the gallbladder?" '
            'YES "The abnormality extends into the gallbladder." NO "No extension into the gallbladder."')
STATE_LINE = 'NEGATIVE "No delta extension." WHEN [findings: a focal delta abnormality is reported]'
SHEET = (HABIT_SHEET.replace('NEGATIVE "No focal liver lesion."\n', 'NEGATIVE "No focal liver lesion."\n' + ASK_LINE + "\n")
         .replace('NORMAL [delta] "Delta is normal."\n', 'NORMAL [delta] "Delta is normal."\n' + STATE_LINE + "\n"))


def _st():
    r = tsg.parse_sheet(SHEET)
    assert not r.errors and r.structure.usable, r.errors
    return r.structure


def test_paragraph_regions_name_paragraphs_as_template_regions_does():
    st = _st()
    assert list(paragraph_regions(st).values()) == [r.name for r in template_regions(st)][:-1] == ["Liver", "Lower"]


def test_template_habits_reads_both_forms_under_their_region_names():
    hs = H.template_habits(_st(), None, all_habits=True)   # the labs' hand-written sheets: every habit
    assert [(h.region, h.mode, h.condition) for h in hs] == [
        ("Liver", "ask", "a focal liver abnormality is reported"), ("Lower", "state", "a focal delta abnormality is reported")]
    assert (hs[0].question, hs[0].yes, hs[0].no) == (
        "Extension into the gallbladder?", "The abnormality extends into the gallbladder.", "No extension into the gallbladder.")
    assert hs[1].no == "No delta extension."


def test_with_a_ledger_only_confirmed_habits_are_active():
    st = _st()
    assert H.template_habits(st, []) == []   # Hassan H3: a line nobody confirmed is inactive
    led, _ = td.set_decision([], "habit", "Lower :: a focal delta abnormality is reported",
                             {"mode": "state", "no": "No delta extension."}, source="creation", at="t")
    assert [h.region for h in H.template_habits(st, led)] == ["Lower"]
    led, _ = td.set_decision(led, "habit", "Lower :: a focal delta abnormality is reported", {"mode": "removed"},
                             source="chat", at="t2")
    assert H.template_habits(st, led) == []


def test_condition_state_leaves_the_history_out_when_none():
    # item 1's shared builder; Hassan H1: a trigger reads the dictation and the scan type only
    assert tcr.condition_state("MR knee", None, "Liver: x.") == "SCAN TYPE:\nMR knee\nDICTATED FINDINGS:\nLiver: x."
    assert tcr.condition_state("MR knee", "Pain.", "Liver: x.") == (
        "SCAN TYPE:\nMR knee\nCLINICAL HISTORY:\nPain.\nDICTATED FINDINGS:\nLiver: x.")
    assert tcr.condition_state("", "", "Liver: x.") == "CLINICAL HISTORY:\n(not given)\nDICTATED FINDINGS:\nLiver: x."
    assert tcr.condition_state("MR knee", None, "Liver: x.\nDO NOT ASSERT (removed by the radiologist): y.") == (
        "SCAN TYPE:\nMR knee\nDICTATED FINDINGS:\nLiver: x.")


async def test_ask_triggers_asks_every_condition_in_one_call_on_the_scan_type_and_findings_only():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"answers": {k: {"noul": 0.9 if k == "t0" else 0.1} for k in body["questions"]}})
    conds = ["a focal liver abnormality is reported", "a focal delta abnormality is reported"]
    out = await H.ask_triggers("MR knee", "Liver: a focal abnormality.", conds, transport=httpx.MockTransport(handler))
    assert out == [0.9, 0.1] and len(seen) == 1
    assert seen[0]["state"] == "SCAN TYPE:\nMR knee\nDICTATED FINDINGS:\nLiver: a focal abnormality."
    assert "CLINICAL HISTORY" not in seen[0]["state"]
    q = seen[0]["questions"]["t0"]
    assert q["type"] == "noul" and q["instructions"] == H.TRIGGER_WORDING.format(condition=conds[0])
    b = H.TRIGGER_WORDINGS["A"]
    await H.ask_triggers("MR knee", "x", conds[:1], transport=httpx.MockTransport(handler), wording=b)
    assert seen[1]["questions"]["t0"]["instructions"] == b.format(condition=conds[0])


async def test_ask_triggers_raises_on_incomplete_answers():
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"answers": {}}))
    with pytest.raises(ValueError):
        await H.ask_triggers("MR knee", "x", ["a focal liver abnormality is reported"], transport=t)


def test_the_ledger_is_required_unless_a_lab_asks_for_every_habit():
    with pytest.raises(TypeError):
        H.template_habits(_st())
    with pytest.raises(ValueError):
        H.template_habits(_st(), None)
    assert len(H.template_habits(_st(), [], all_habits=True)) == 2   # the flag ignores the ledger


async def test_met_habits_uses_the_cut_off_and_fails_soft():
    hs = H.template_habits(_st(), None, all_habits=True)
    seen = []

    async def ask(scan_type, findings, conds):
        seen.append(scan_type)
        return [H.TRIGGER_MIN, H.TRIGGER_MIN - 0.01]   # Hassan H2: just below the cut-off stays silent
    met, err = await H.met_habits(hs, "MR knee", "x", ask=ask)
    assert [h.mode for h in met] == ["ask"] and err is None and seen == ["MR knee"]

    async def band(scan_type, findings, conds):
        return [0.49, 0.36]
    assert await H.met_habits(hs, "MR knee", "x", ask=band) == ([], None)

    async def boom(scan_type, findings, conds):
        raise RuntimeError("jev down")
    assert await H.met_habits(hs, "MR knee", "x", ask=boom) == ([], "RuntimeError: jev down")
    assert await H.met_habits(hs, "MR knee", "   ", ask=ask) == ([], None)
    assert await H.met_habits([], "MR knee", "x", ask=ask) == ([], None)


def test_trigger_wordings_are_case_agnostic_and_the_cut_off_is_the_context_rules_one():
    for w in H.TRIGGER_WORDINGS.values():
        assert "{condition}" in w
        for word in CLINICAL:
            assert word not in w.lower(), word
    assert H.TRIGGER_WORDING in H.TRIGGER_WORDINGS.values() and H.TRIGGER_MIN == 0.5
