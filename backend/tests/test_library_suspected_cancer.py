"""Spec §7.12 item 6: a hedged cancer statement ("?primary lung carcinoma", "likely primary lung carcinoma",
"suspicious for RCC") is no longer dropped and then assumed No, which hid it. It is kept as a pre-filled Yes, why
"suspected, not established": the scope-doubt machinery shows it ("would make the guideline not apply: confirm it"),
the card stays check_first, and it never excludes. A stated cancer is unchanged."""
import json

from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP
from rapid_reports_ai.hybrid_stack.copilot.library.schema import DOES_NOT_APPLY, InputValue
from tests.test_library_pack_preview import _model, jev  # noqa: F401  (fixture)

NODULE = "8 mm solid nodule in the right lower lobe."


def _pack(key):
    return LB.Library(json.loads(LB.BUNDLE.read_text())).lookup(key)


async def _fleischner(monkeypatch, history, quote, dictation=NODULE):
    _model(monkeypatch, {"input": "exclusion", "value": True, "quote": quote},
           {"input": "nodule_type", "value": "solid", "quote": "solid"},
           {"input": "diameter_mm", "value": 8, "quote": "8 mm"})
    e = _pack("fleischner-pulmonary-nodule")
    s = await PP.settle_pack(e, dictation, history, finding=NODULE)
    return e, s, PP.finish(e, s, {}, {}, [])


async def test_a_queried_primary_in_the_history_is_a_scope_doubt(monkeypatch, jev):
    e, s, p = await _fleischner(monkeypatch, "?primary lung carcinoma", "?primary lung carcinoma")
    d = s.values["exclusion"]
    assert d.tier == "prefilled" and PP.WHY_SUSPECTED in d.why
    row = next(x for x in p.draft if x.input == "exclusion")
    assert row.state == "prefilled" and PP.WHY_SUSPECTED in row.why and PP.WHY_WOULD_EXCLUDE in row.why
    assert "exclusion" in p.scope_doubt and p.state == "check_first" and p.state != DOES_NOT_APPLY
    assert p.exclusion is None


async def test_a_likely_primary_in_the_dictation_is_a_scope_doubt(monkeypatch, jev):
    dictation = f"{NODULE} Right hilar mass, likely primary lung carcinoma."
    e, s, p = await _fleischner(monkeypatch, "", "primary lung carcinoma", dictation=dictation)
    assert PP.WHY_SUSPECTED in s.values["exclusion"].why
    assert "exclusion" in p.scope_doubt and p.state == "check_first"


async def test_a_stated_cancer_is_not_suspected_and_is_a_scope_doubt_until_confirmed(monkeypatch, jev):
    e, s, p = await _fleischner(monkeypatch, "Known breast cancer.", "Known breast cancer")
    d = s.values["exclusion"]
    assert PP.WHY_SUSPECTED not in d.why and d.tier == "prefilled"        # a yes/no is never read: as before
    assert "exclusion" in p.scope_doubt and p.state == "check_first"      # the settle path: pre-filled, a doubt
    read = PP.Settlement(values={**s.values, "exclusion": PP.Drafted(InputValue(value=True), "Known breast cancer",
                                                                      "read")})
    assert PP.finish(e, read, {}, {}, []).state != DOES_NOT_APPLY          # read: still a doubt (Hassan 2026-10-15)
    assert PP.finish(e, read, {"exclusion": "Yes"}, {}, []).state == DOES_NOT_APPLY   # confirmed: it excludes


async def test_a_stated_cancer_with_queried_metastases_is_not_suspected(monkeypatch, jev):
    e, s, p = await _fleischner(monkeypatch, "Breast ca ?liver mets", "Breast ca")
    assert PP.WHY_SUSPECTED not in s.values["exclusion"].why


def test_only_cancer_inputs_carry_the_suspicion_backstop():
    f = _pack("fleischner-pulmonary-nodule")
    assert f.input("exclusion").suspected_doubt is True
    assert PP._hedged_cancer(f.input("exclusion"), InputValue(value=True), "?primary lung carcinoma")
    assert not PP._hedged_cancer(f.input("prior_growth"), InputValue(value=True), "?enlarging")
    ese = _pack("ese-adrenal-incidentaloma")
    assert not PP._hedged_cancer(ese.input("not_incidentaloma"), InputValue(value=True), "suspected phaeochromocytoma")
    assert "quote the hedge" in PP.SETTLE_SYS


# fix round 1 (task-4-review findings 1 and 2)
def test_the_ese_hint_returns_a_suspected_cancer_with_its_hedge():
    """Finding 1: the pack's own hint no longer tells the model to leave a suspected cancer out."""
    hint = _pack("ese-adrenal-incidentaloma").input("known_primary_cancer").how_stated
    assert "return it as true with the hedge in the quote" in hint


def test_only_cancer_inputs_are_marked_suspected_counts_in_the_prompt():
    """Finding 2: a suspicion is returned only for a cancer input; every other patient input leaves it out, as
    before, so a hedged non-cancer Yes ("?pregnant") never comes back as a plain pre-filled Yes."""
    f = _pack("fleischner-pulmonary-nodule")
    lines = PP._inputs_text(f, ["exclusion", "count", "risk"]).splitlines()
    assert PP.SUSPECTED_COUNTS in lines[0] and not any(PP.SUSPECTED_COUNTS in x for x in lines[1:])
    r = _pack("rcog-ovarian-mass-premenopausal")
    assert PP.SUSPECTED_COUNTS not in PP._inputs_text(r, ["pregnant_or_acute", "premenopausal"])
    ese = _pack("ese-adrenal-incidentaloma")
    assert PP.SUSPECTED_COUNTS in PP._inputs_text(ese, ["known_primary_cancer"])
    assert PP.SUSPECTED_COUNTS not in PP._inputs_text(ese, ["not_incidentaloma"])
    assert 'leave it out, unless the input is marked "suspected counts"' in PP.SETTLE_SYS
