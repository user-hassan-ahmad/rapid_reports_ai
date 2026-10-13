from itertools import product

from rapid_reports_ai.hybrid_stack.copilot import tnm
from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library import tnm_schema as TS
from rapid_reports_ai.hybrid_stack.copilot.library.schema import Cases, GoldenCase
from rapid_reports_ai.hybrid_stack.copilot.library.verify import check


def _golden(e):
    """One case per outcome, from the first row that reaches it."""
    t = e.step("stage")
    keys, seen, out = t.keys, set(), []
    for r in t.rows:
        if r.result not in seen:
            seen.add(r.result)
            out.append(GoldenCase(name=r.result, origin="ours", inputs=dict(zip(keys, r.match)), outcome=r.result))
    return Cases(cases=out)


def test_every_staged_site_passes_the_gates():
    assert len(TS.staged_sites()) == 36
    for site in TS.staged_sites():
        e = TS.site_entry(site)
        assert check(e, TS.MANIFEST, _golden(e)) == [], site


def test_the_engine_reproduces_every_verified_combination():
    n = 0
    for site in TS.staged_sites():
        e = TS.site_entry(site)
        for h in tnm.variants(site) or [""]:
            for t, nn, m in product(*(tnm._options(site, a) for a in "TNM")):
                given = {"T": t, "N": nn, "M": m, **({"histology": h} if h else {})}
                tr = E.evaluate(e, given)
                cls = E.render(e, tr, e.outcome(tr.outcome).classification)
                assert cls == tnm.proposal(site, given).classification, (site, given)
                n += 1
    assert n == 6479
