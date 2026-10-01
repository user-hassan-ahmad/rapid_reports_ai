"""Shared clinical routing (report_reconcile.route_differential / route_recommendation): one test per row,
and equivalence with quick's inline routing in quick_report_brief.compile_brief, driven through quick's
own compiler on its own test sheet (quick is left untouched; these prove the shared functions match it)."""
from __future__ import annotations

import itertools

import pytest

from rapid_reports_ai import quick_report_brief as qb
from rapid_reports_ai import report_reconcile as rc

from tests.test_quick_report_brief import QWEN, SHEET, _stub

# ── route_differential ──────────────────────────────────────────────────────


@pytest.mark.parametrize("present,visible,expected", [
    (0.9, "yes", "present"), (0.9, "no", "present"), (0.9, "silent", "present"), (0.5, "no", "present"),
    (0.1, "yes", "closed"), (0.49, "yes", "closed"),
    (0.1, "no", "open"), (0.1, "silent", "open"),
])
def test_route_differential_rows(present, visible, expected):
    assert rc.route_differential(present, visible) == expected


# ── route_recommendation ────────────────────────────────────────────────────

def rec(decision, reason=None):
    return rc.RecDecision(index=0, decision=decision, exclude_reason=reason)


@pytest.mark.parametrize("unmet,decision,tag,room,expected", [
    (0.1, None, "IMAGING", True, "keep"),
    (0.1, rec("include"), "REFERRAL", True, "keep"),
    (0.1, rec("optional"), "IMAGING", True, "optional"),
    (0.1, rec("optional"), "IMAGING", False, "removed"),            # no room for another option
    (0.1, rec("exclude", "condition_unmet"), "IMAGING", True, "removed"),
    (0.1, rec("exclude", "routine_workup"), "IMAGING", True, "do_not_recommend"),
    (0.1, rec("exclude", "routine_workup"), "TISSUE", True, "do_not_recommend"),
    (0.1, rec("exclude", "routine_workup"), "REFERRAL", True, "removed"),  # only investigations are named
    (0.1, rec("exclude", "routine_workup"), "CORRELATION", True, "removed"),
    (0.9, rec("include"), "IMAGING", True, "removed"),              # Jev's unmet condition wins over include
    (0.9, None, "IMAGING", True, "removed"),
    (0.9, rec("exclude", "routine_workup"), "IMAGING", True, "do_not_recommend"),
])
def test_route_recommendation_rows(unmet, decision, tag, room, expected):
    assert rc.route_recommendation(unmet, decision, tag=tag, room=room) == expected


# ── equivalence with quick's inline routing ─────────────────────────────────

def _visible(line: str) -> str:
    """Quick's differential line annotations as the grammar's VISIBLE value."""
    if "imaging-silent" in line:
        return "silent"
    return "yes" if "visible on this technique: yes" in line else "no"


BASE = {"n0": 0.1, "n1": 0.1, "n2": 0.1, "s0": 0.1, "s1": 0.1}


def _jev(scores: dict) -> dict:
    out = {k: {"noul": v} for k, v in {**BASE, **scores}.items()}
    out["imp"] = {"choice": "v0"}
    return out


@pytest.mark.parametrize("scores", list(itertools.product((0.1, 0.9), repeat=4)))
async def test_route_differential_matches_quick(monkeypatch, scores):
    _stub(monkeypatch, _jev({f"d{k}": p for k, p in enumerate(scores)} | {"r0": 0.1, "r1": 0.1}), QWEN)
    b = await qb.compile_brief(SHEET, "CT head non-contrast", "8 mm right subdural")
    lines = qb.differential_lines(qb.parse_sheet(SHEET))
    quick = [d["action"] for d in b.decisions["differentials"]]
    shared = [{"closed": "removed"}.get(r, r) for r in
              (rc.route_differential(p, _visible(t)) for p, t in zip(scores, lines))]
    assert quick == shared


DECISIONS = [None, ("include", None), ("optional", None), ("exclude", "routine_workup"),
             ("exclude", "condition_unmet"), ("exclude", "not_radiology")]
RECS = ("  - REFERRAL: Neurosurgery for haemorrhage with mass effect\n"
        "  - IMAGING: CTA for large vessel occlusion\n"
        "  - TISSUE: Biopsy of an indeterminate mass\n"
        "  - MDT: Neuro-oncology MDT for a mass lesion\n"
        "  - CORRELATION: Comparison with prior imaging\n")
# Three contextual If-present negatives for a reported finding fill quick's options before the
# recommendations are routed: room=False.
IF_PRESENT = ('- **If present:**\n'
              '  - Acute subdural → "No contralateral collection" (contextual)\n'
              '  - Acute subdural → "No skull base fracture" (contextual)\n'
              '  - Acute subdural → "No uncal herniation" (contextual)\n')
ALL_RECS = SHEET[:SHEET.index("  - REFERRAL:")] + RECS
FULL = ALL_RECS.replace("- **Out-of-scope suppressed:** CTA\n", "- **Out-of-scope suppressed:** CTA\n" + IF_PRESENT)


@pytest.mark.parametrize("room", [True, False])
@pytest.mark.parametrize("unmet,dec", list(itertools.product((0.1, 0.9), DECISIONS)))
@pytest.mark.parametrize("k", range(5))  # REFERRAL, IMAGING, TISSUE, MDT, CORRELATION
async def test_route_recommendation_matches_quick(monkeypatch, unmet, dec, k, room):
    sheet = ALL_RECS if room else FULL
    recs = qb._recommendations(qb._section(qb.parse_sheet(sheet), "Impression Exemplars"))
    assert len(recs) == 5
    decs = [rc.RecDecision(index=i, decision="include") for i in range(5) if i != k]
    d = None
    if dec:
        d = rc.RecDecision(index=k, decision=dec[0], exclude_reason=dec[1])
        decs.append(d)
    plan = rc.ImpressionPlan(recommendations=decs, impression=[0])
    jev = {"d0": 0.1, "d1": 0.1, "d2": 0.1, "d3": 0.1, **{f"r{i}": 0.1 for i in range(5)}, f"r{k}": unmet}
    if not room:
        jev["f0"] = 0.9
    _stub(monkeypatch, _jev(jev), QWEN, plan)
    b = await qb.compile_brief(sheet, "CT head non-contrast", "8 mm right subdural")
    if not room:
        assert len([o for o in b.decisions["options"] if o["kind"] == "finding_negative"]) == 3
    action = b.decisions["recommendations"][k]["action"]
    body = recs[k].split(":", 1)[1].strip()
    barred = "Do not recommend" in b.text and f'"{body}"' in b.text
    quick = "do_not_recommend" if barred else action
    assert quick == rc.route_recommendation(unmet, d, tag=recs[k].split(":")[0], room=room)


@pytest.mark.parametrize("tag", ["IMAGING", "imaging", "Imaging", "IMAGING:", " imaging: "])
def test_route_recommendation_tag_case(tag):
    d = rec("exclude", "routine_workup")
    assert rc.route_recommendation(0.1, d, tag=tag) == "do_not_recommend"
    assert rc.route_recommendation(0.1, d, tag=tag.replace("maging", "MAGINGX").replace("MAGING", "MAGINGX")) == "removed"
