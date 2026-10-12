import json

from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP
from rapid_reports_ai.hybrid_stack.copilot.library.schema import DOES_NOT_APPLY


def _lib():
    return LB.Library(json.loads(LB.BUNDLE.read_text()))


def _elig(e):
    return [i.id for i in e.inputs if i.role == "eligibility"]


def test_each_pack_declares_its_scope_clause_as_eligibility():
    lib = _lib()
    f, b, k = (lib.lookup(x) for x in ("fleischner-pulmonary-nodule", "bts-pulmonary-nodule", "bosniak-renal-cyst"))
    assert _elig(f) == ["age", "exclusion"] and _elig(b) == ["age"] and _elig(k) == ["mimic"]
    assert f.input("age").fact == b.input("age").fact == "age_years" and b.input("sex").fact == "sex"
    assert f.input("exclusion").scope == "patient" and k.input("mimic").scope == "lesion"
    assert all(e.outcome(DOES_NOT_APPLY) is not None for e in (f, b, k))


def test_one_age_answer_fills_both_nodule_cards():
    lib = _lib()
    f, b = lib.lookup("fleischner-pulmonary-nodule"), lib.lookup("bts-pulmonary-nodule")
    assert E.evaluate(f, PP._given(f, {"exclusion": "No"}, {"age_years": "30"})).outcome == DOES_NOT_APPLY
    assert E.evaluate(b, PP._given(b, {}, {"age_years": "16"})).outcome == DOES_NOT_APPLY
    tf = E.evaluate(f, PP._given(f, {"exclusion": "No", "nodule_type": "solid", "count": "single",
                                     "diameter_mm": "7", "risk": "low"}, {"age_years": "60"}))
    assert tf.outcome not in (None, DOES_NOT_APPLY)


def test_an_excluding_answer_settles_without_the_other_eligibility_input():
    f = _lib().lookup("fleischner-pulmonary-nodule")
    assert E.evaluate(f, {"exclusion": True}).outcome == DOES_NOT_APPLY        # age unknown, still excluded


def test_a_bosniak_mimic_does_not_apply():
    k = _lib().lookup("bosniak-renal-cyst")
    assert E.evaluate(k, {"mimic": True}).outcome == DOES_NOT_APPLY
