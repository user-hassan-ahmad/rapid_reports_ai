"""Spec §7.12 item 1: Fleischner's table covers newly detected nodules. A nodule that has grown on earlier imaging is
outside it: the card says so in the pack's own words and points to the BTS card, never improvising management."""
import json

from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP
from rapid_reports_ai.hybrid_stack.copilot.library.schema import DOES_NOT_APPLY, Cases, Entry, Manifest
from rapid_reports_ai.hybrid_stack.copilot.library.verify import check

KEY = "fleischner-pulmonary-nodule"


def _lib():
    return LB.Library(json.loads(LB.BUNDLE.read_text()))


def _pack():
    lib = _lib()
    e = lib.lookup(KEY)
    return e, lib.sources(e.key)


def _read(**vals):
    """Read (certain) drafted values, as the real case settled them."""
    return {k: PP.Drafted(PP.InputValue(value=v), str(v), "read") for k, v in vals.items()}


_NODULE = {"nodule_type": "solid", "count": "single", "diameter_mm": 9.0}


def test_growth_read_excludes_with_growth_wording():
    e, src = _pack()
    p = PP.finish(e, PP.Settlement(values=_read(**_NODULE, prior_growth=True)), {}, {}, src)
    assert p.state == "does_not_apply"
    assert p.exclusion.headline == "Outside the Fleischner table: interval growth"
    assert "see the BTS card" in p.exclusion.recommendation
    assert p.exclusion.category == "not_applicable"
    assert p.exclusion_reason.input == "prior_growth"
    assert p.exclusion_reason.outcome == "outside_table_growth"
    pages = {(c.get("source"), c.get("page")) for c in p.exclusion.citations}
    assert ("S1", 3) in pages and ("S1", 5) in pages


def test_stable_nodule_unchanged():
    e, src = _pack()
    p = PP.finish(e, PP.Settlement(values=_read(**_NODULE, prior_growth=False)), {}, {}, src)
    assert p.state != "does_not_apply" and p.exclusion is None
    assert p.trace["outcome"] == "solid_single_gt8"


def test_growth_unstated_assumed_in_scope():
    e, src = _pack()
    p = PP.finish(e, PP.Settlement(values=_read(**_NODULE)), {}, {}, src)
    assert p.state == "check_first"
    assert "prior_growth" in {a.input for a in p.assumptions}
    row = next(d for d in p.draft if d.input == "prior_growth")
    assert row.state == "assumed" and row.value == "No"
    assert p.draft_outcome is not None and p.trace["outcome"] == "solid_single_gt8"


def test_growth_prefilled_is_scope_doubt():
    e, src = _pack()
    vals = {**_read(**_NODULE), "prior_growth": PP.Drafted(PP.InputValue(value=True), "now 9 mm, previously 6 mm",
                                                           "prefilled", [PP.WHY_KIND])}
    p = PP.finish(e, PP.Settlement(values=vals), {}, {}, src)
    assert "prior_growth" in p.scope_doubt
    assert p.state == "check_first" and p.exclusion is None


def test_generic_exclusion_keeps_generic_wording():
    e, src = _pack()
    p = PP.finish(e, PP.Settlement(values=_read(**_NODULE, exclusion=True)), {}, {}, src)
    assert p.state == "does_not_apply"
    assert p.exclusion.headline == e.outcome(DOES_NOT_APPLY).headline
    assert p.exclusion_reason.input == "exclusion" and p.exclusion_reason.outcome is None


def test_calculate_growth_answered_uses_growth_wording():
    e, src = _pack()
    s = PP.Settlement(values=_read(**_NODULE))
    c = PP.calculate(e, s, {"nodule_type": "solid", "count": "single", "diameter_mm": "9", "prior_growth": "Yes"},
                     {}, src, "b1")
    assert c.outcome == DOES_NOT_APPLY
    assert c.exclusion.headline == "Outside the Fleischner table: interval growth"
    assert c.exclusion_reason.outcome == "outside_table_growth"


def _real():
    d = LB.guidelines_root() / KEY
    return (json.loads((d / "entry.json").read_text()), Manifest.model_validate_json((d / "manifest.json").read_text()),
            Cases.model_validate_json((d / "cases.json").read_text()))


def test_the_real_pack_passes_the_gates():
    raw, m, c = _real()
    assert check(Entry.model_validate(raw), m, c) == []


def test_verify_rejects_a_missing_or_non_scope_exclusion_outcome():
    raw, m, c = _real()
    growth = next(i for i in raw["inputs"] if i["id"] == "prior_growth")
    growth["exclusion_outcome"] = "no_such_outcome"
    assert any("exclusion_outcome" in p for p in check(Entry.model_validate(raw), m, c))
    raw, m, c = _real()
    next(o for o in raw["outcomes"] if o["id"] == "outside_table_growth")["category"] = "workup"
    assert any("exclusion_outcome" in p for p in check(Entry.model_validate(raw), m, c))
    raw, m, c = _real()
    growth = next(i for i in raw["inputs"] if i["id"] == "prior_growth")
    growth["role"] = "clinical"
    assert any("exclusion_outcome" in p for p in check(Entry.model_validate(raw), m, c))
