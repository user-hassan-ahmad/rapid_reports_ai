"""Rebuild fixture (stable line IDs spec, "Tests"): two writer outputs for the same synthetic reports. Primary metric:
wrong matches, which must be 0. Secondary (printed, never asserted): the share of line-bound ledger entries resolved
by uid against today's text matching on the same rebuild. Run with -s to see the numbers."""
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_ledger_apply as tla
from rapid_reports_ai import template_line_registry as tlr
from rapid_reports_ai import template_sheet_grammar as tsg
from tests.template_line_fixtures import REBUILD_A, REBUILD_B, SAME


def _st(sheet):
    res = tsg.parse_sheet(sheet)
    assert not res.errors and res.structure.usable, res.errors
    return res.structure


def _labels(st):
    """parse ref -> a stable label: the raw line for a line unit, "Paragraph: <name>" or "SECTION <NAME>"."""
    out = {}
    for u in tlr.units(st):
        out[u.ref] = u.raw.strip() if u.raw else (f"Paragraph: {u.text}" if u.kind == "paragraph" else f"SECTION {u.text}")
    return out


def _ledger(st, registry):
    led = []
    for kind, key, choice in [
            ("normal", td.normal_key("Liver", "liver"), {"text": "The liver is normal in size and attenuation."}),
            ("normal", td.negative_key("Liver", "No focal liver lesion."), {"text": "No focal liver lesion."}),
            ("normal", td.negative_key("Chest base", "No pleural effusion."), {"text": "No pleural effusion."}),
            ("fixed", "No previous imaging is available.", {"keep": "always"}),
            ("fixed", "Axial images were acquired after contrast.", {"keep": "always"})]:
        led, _ = td.set_decision(led, kind, key, choice, source="creation", at="t")
    return tla.stamp_uids(led, st, registry)


def test_a_rebuild_makes_no_wrong_match():
    sa, sb = _st(REBUILD_A), _st(REBUILD_B)
    reg_a, _ = tlr.rebind(None, sa, now="T")
    reg_b, report = tlr.rebind(reg_a, sb, now="T")
    a_label = {uid: _labels(sa)[ref] for ref, uid in tlr.uids_for(sa, reg_a).items()}
    b_label = {uid: _labels(sb)[ref] for ref, uid in tlr.uids_for(sb, reg_b).items()}
    same = {(a, b) for a, b in SAME} | {(f"SECTION {n}", f"SECTION {n}") for n in ("TECHNIQUE", "FINDINGS", "IMPRESSION")}
    kept = {uid for uid in a_label if uid in b_label}
    wrong = sorted((a_label[u], b_label[u]) for u in kept if (a_label[u], b_label[u]) not in same)
    missed = sorted(p for p in same if p not in {(a_label[u], b_label[u]) for u in kept})
    print(f"\nrebuild: {tlr.summary(report)} kept={len(kept)} wrong={len(wrong)} missed={missed}")
    assert wrong == []


def test_the_rebuild_resolution_share_is_reported():
    sa = _st(REBUILD_A)
    reg_a, _ = tlr.rebind(None, sa, now="T")
    share = tla.uid_share(_ledger(sa, reg_a), REBUILD_B, reg_a)
    print(f"\nrebuild resolution: {share}")
    assert share["line_bound"] == 5
