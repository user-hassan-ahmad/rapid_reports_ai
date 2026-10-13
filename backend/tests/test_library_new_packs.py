import json

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library.schema import DOES_NOT_APPLY

ALGORITHM = ["ese-adrenal-incidentaloma", "rcog-ovarian-mass-premenopausal", "rcog-ovarian-mass-postmenopausal",
             "pi-rads-2-1", "nhs-aaa-surveillance"]
LOOKUP = ["bta-thyroid-u-grading", "cad-rads-2", "cac-drs", "salter-harris", "sins"]
TIER2 = ["kellgren-lawrence", "garden-hip-fracture", "weber-ankle", "fazekas", "aspects", "ao-spine-thoracolumbar",
         "stoller-meniscus", "lund-mackay"]


def _lib():
    return LB.Library(json.loads(LB.BUNDLE.read_text()))


def _eligible(e) -> dict:
    """Eligibility booleans name the exclusion (true leads to does_not_apply), so false is in scope."""
    return {i.id: False for i in e.inputs if i.role == "eligibility" and i.type == "boolean"}


@pytest.mark.parametrize("pack_id", ALGORITHM + LOOKUP)
def test_a_tier1_pack_is_current_scoped_and_eligibility_bounded(pack_id):
    e = _lib().lookup(pack_id)
    assert e is not None and e.tier == 1 and e.status == "current"
    elig = [i for i in e.inputs if i.role == "eligibility"]
    assert len(elig) <= 3 and all(i.locator is not None for i in elig)
    assert (e.outcome(DOES_NOT_APPLY) is not None) == bool(elig)


@pytest.mark.parametrize("pack_id", LOOKUP)
def test_a_lookup_pack_reads_one_dictated_grade(pack_id):
    e = _lib().lookup(pack_id)
    cat = next(i for i in e.inputs if i.role == "clinical")
    assert cat.type in ("enum", "number") and cat.scope == "lesion" and cat.how_stated and cat.locator is not None
    if cat.type == "enum":
        modifiers = {i.id for i in e.inputs if i.role == "clinical" and i.id != cat.id}
        for opt in cat.options:
            t = E.evaluate(e, {**_eligible(e), cat.id: opt})
            if t.outcome is None:
                assert t.needed and set(t.needed) <= modifiers, (opt, t.needed)
            else:
                assert t.outcome != DOES_NOT_APPLY and e.outcome(t.outcome).classification, opt


@pytest.mark.parametrize("entry_id", TIER2)
def test_a_reference_card_is_read_only_and_located(entry_id):
    e = _lib().lookup(entry_id)
    assert e is not None and e.tier == 2 and not e.inputs and not e.logic and not e.outcomes
    r = e.reference
    assert r.summary and r.definitions and r.tables and all(f.locator is not None for f in r.fields())
    assert all(len(row) == len(t.columns) for t in r.tables for row in t.rows)
    assert e.applies_to.finding_type and e.aliases
