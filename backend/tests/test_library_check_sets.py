"""Spec 2026-10-14 §9.2: on each launch pack's golden cases, with every golden input drafted as pre-filled (the
worst case: nothing read), the exact inputs the card's Check zone lists (decisive pre-filled or assumed values, and
scope doubts), pinned in fixtures/check_sets.json; and `decisive` agrees with flipping each value through `finish` (the outcome changes or, with no outcome yet,
which outcomes remain possible).
Regenerate the pin with UPDATE_CHECK_SETS=1 only after a reviewed engine or pack change."""
import json
import os
from pathlib import Path

from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP
from rapid_reports_ai.hybrid_stack.copilot.library.schema import as_value

LAUNCH = ["bts-pulmonary-nodule", "bosniak-renal-cyst", "ese-adrenal-incidentaloma", "cad-rads-2", "cac-drs"]
SNAP = Path(__file__).parent / "fixtures" / "check_sets.json"
ROOT = Path(__file__).resolve().parents[2]


def _entry(pack_id):
    return LB.Library(json.loads(LB.BUNDLE.read_text())).lookup(pack_id)


def _cases(e):
    p = ROOT / "guidelines" / e.id / "cases.json"
    return json.loads(p.read_text())["cases"] if p.exists() else []


def _settle(e, inputs):
    return PP.Settlement(values={k: PP.Drafted(as_value(v), str(v), "prefilled", [PP.WHY_KIND])
                                 for k, v in inputs.items() if e.input(k) is not None})


def _check_set(p):
    return sorted({d.input for d in p.draft if d.state in ("prefilled", "assumed") and d.value
                   and d.decisive is not False} | set(p.scope_doubt))


def test_every_launch_pack_has_golden_cases():
    for pack_id in LAUNCH:
        assert _cases(_entry(pack_id)), pack_id


def test_check_sets_for_the_launch_packs():
    got = {}
    for pack_id in LAUNCH:
        e = _entry(pack_id)
        for c in _cases(e):
            got[f"{pack_id}/{c['name']}"] = _check_set(PP.finish(e, _settle(e, c["inputs"]), {}, None, []))
    if os.environ.get("UPDATE_CHECK_SETS"):
        SNAP.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n")
    assert got == json.loads(SNAP.read_text())


def test_decisive_agrees_with_flipping_each_prefilled_value():
    for pack_id in LAUNCH:
        e = _entry(pack_id)
        for c in _cases(e):
            s = _settle(e, c["inputs"])
            p = PP.finish(e, s, {}, None, [])
            if p.scope_doubt:
                continue                                   # a doubt changes what the draft is computed on
            base = (p.trace or {}).get("outcome")
            for d in p.draft:
                if d.state != "prefilled" or d.decisive is None:
                    continue
                others = [o for o in d.options if o not in (d.value, PP.NOT_STATED)]
                flips = [PP.finish(e, s, {d.input: o}, None, []) for o in others]
                moved = any((fp.trace or {}).get("outcome") != base
                            or (base is None and set(fp.possible) != set(p.possible)) for fp in flips)
                assert d.decisive == moved, (pack_id, c["name"], d.input)
