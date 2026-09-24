from __future__ import annotations

import json
from pathlib import Path

from rapid_reports_ai.dictation_triage import TriageDecision
from rapid_reports_ai.scripts.bundle_parity import (
    PARITY_CHECKLISTS,
    Unit,
    boundary_state,
    coverage_state,
    coverage_units,
    latency_gate,
    standalone_units,
    triage_state,
    triage_units,
    verdict,
)
from rapid_reports_ai.section_coverage import CoverageDecision
from rapid_reports_ai.utterance_boundary import BoundaryDecision
from rapid_reports_ai.utterance_bundle import BundleDecision

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return [json.loads(l) for l in (FIX / name).read_text().splitlines() if l.strip()]


def _td(action="append_new_finding", conf=0.97, ic=0.1, nce=0.1):
    return TriageDecision("jev", action, conf, {}, ic, nce, 300, None, None)


def _bd(action="append_new_finding", conf=0.97, ic=0.1, nce=0.1, standalone=0.8, coverage=None):
    return BundleDecision(_td(action, conf, ic, nce), standalone, coverage or {}, 320, 8, None, None)


def _bnd(standalone):
    return BoundaryDecision("complete", 0.9, {}, 0.1, 300, None, None, standalone=standalone)


def _u(ref, ref2, bun, conf=0.7):
    return Unit("q", "c", ref, ref2, bun, conf)


def test_every_fixture_scan_type_has_a_checklist():
    for name in ("triage_utterances.jsonl", "boundary_cases.jsonl"):
        for c in _load(name):
            assert c["scan_type"] in PARITY_CHECKLISTS, (name, c["id"])


def test_state_mappers():
    t = triage_state({"scan_type": "CT chest", "committed": "C", "active": "A", "utterance": "U"})
    assert (t.committed, t.active, t.open_line, t.latest_utterance) == ("C", "A", "", "U")
    assert t.checklist == PARITY_CHECKLISTS["CT chest"]
    b = boundary_state({"scan_type": "CT chest", "buffered": "B", "chunk": "K", "scratchpad_tail": "T"})
    assert (b.committed, b.active, b.open_line, b.latest_utterance) == ("", "T", "B", "K")
    c = coverage_state({"scan_type": "CT", "scratchpad": "S", "checklist": ["LIVER"]})
    assert (c.active, c.latest_utterance, c.checklist) == ("S", "", ["LIVER"])


def test_triage_units():
    case = {"id": "t1", "expected_action": "correct_previous_finding",
            "expected_is_correction": True, "expected_needs_committed_edit": False}
    us = triage_units(case, _td("correct_previous_finding", ic=0.9), _td("correct_previous_finding", ic=0.9),
                      _bd("append_new_finding", conf=0.96, ic=0.4))
    by_q = {u.question: u for u in us}
    assert set(by_q) == {"action", "is_correction", "needs_committed_edit"}
    assert by_q["action"].ref_ok and not by_q["action"].bundle_ok and by_q["action"].bundle_conf == 0.96
    assert by_q["is_correction"].ref_ok and not by_q["is_correction"].bundle_ok
    assert abs(by_q["is_correction"].bundle_conf - 0.6) < 1e-9
    assert by_q["needs_committed_edit"].bundle_ok


def test_standalone_units_skip_commands():
    assert standalone_units({"id": "c", "expected_boundary": "command"}, _bnd(0.1), _bnd(0.1), _bd()) == []
    [u] = standalone_units({"id": "k", "expected_boundary": "continues"}, _bnd(0.3), _bnd(0.6), _bd(standalone=0.2))
    assert u.question == "standalone" and u.ref_ok and not u.ref2_ok and u.bundle_ok


def test_coverage_units_one_per_section():
    case = {"id": "cv", "checklist": ["LIVER", "SPLEEN"], "expected_covered": ["LIVER"]}
    ref = CoverageDecision("jev", {"LIVER": 0.9, "SPLEEN": 0.1}, ["LIVER"], 300)
    us = coverage_units(case, ref, ref, _bd(coverage={"LIVER": 0.4, "SPLEEN": 0.1}))
    assert [u.case_id for u in us] == ["cv/LIVER", "cv/SPLEEN"]
    assert not us[0].bundle_ok and us[1].bundle_ok


def test_verdict_rules():
    assert verdict([_u(True, True, True)] * 10)["pass"]
    two_new = [_u(True, True, False)] * 2 + [_u(True, True, True)] * 8
    v = verdict(two_new)
    assert v["bundle_only_wrong"] == 2 and v["allowed_net_loss"] == 1 and not v["pass"]
    noisy = two_new + [_u(True, False, True)] * 2
    assert verdict(noisy)["allowed_net_loss"] == 2 and verdict(noisy)["pass"]
    offset = [_u(True, True, False), _u(False, False, True)] + [_u(True, True, True)] * 8
    assert verdict(offset)["pass"]
    confident = [_u(True, True, False, conf=0.97)] + [_u(True, True, True)] * 9
    assert verdict(confident)["confident_new_wrong"] == 1 and not verdict(confident)["pass"]
    assert verdict([_u(True, True, True)] * 200)["allowed_net_loss"] == 4


def test_latency_gate():
    assert latency_gate([300] * 100)["pass"]
    g = latency_gate([300] * 90 + [600] * 10)
    assert g["p95"] == 600 and not g["pass"]
    assert not latency_gate([])["pass"]
