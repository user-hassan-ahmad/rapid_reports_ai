import pytest
from pydantic import ValidationError

from rapid_reports_ai.hybrid_stack.copilot.library import schema as S


def test_toy_validates_and_has_a_key(toy_entry):
    assert toy_entry.key == "toy-nodule@1.0"
    assert toy_entry.input("risk").prerequisites[0].eq == "solid"
    assert toy_entry.step("plan").cases[2].result == "ct12"
    assert toy_entry.outcome("pet").recommendation == "PET-CT"
    assert toy_entry.input("nope") is None and toy_entry.step("nope") is None


def test_cond_needs_exactly_one_test():
    assert S.Cond.model_validate({"ref": "x", "in": ["a", "b"]}).in_ == ["a", "b"]
    assert S.Cond.model_validate({"ref": "x", "eq": False}).eq is False
    with pytest.raises(ValidationError):
        S.Cond.model_validate({"ref": "x", "eq": "a", "state": "absent"})
    with pytest.raises(ValidationError):
        S.Cond.model_validate({"ref": "x"})


def test_expr_shapes_parse():
    e = S.RulesStep.model_validate({"step": "rules", "id": "r", "cases": [
        {"when": {"count_gte": 2, "of": [{"ref": "a", "eq": 1}, {"none": [{"ref": "b", "state": "absent"}]},
                                         {"any": [{"ref": "c", "eq": True}]}]}, "result": "x"}]})
    assert sorted(c.ref for c in S.conds(e.cases[0].when)) == ["a", "b", "c"]
    assert e.refs() == ["a", "b", "c"]


def test_tier_rules(toy):
    bad = {**toy, "logic": []}
    with pytest.raises(ValidationError):
        S.Entry.model_validate(bad)
    with pytest.raises(ValidationError):
        S.Entry.model_validate({**toy, "tier": 2})
    t2 = {k: v for k, v in toy.items() if k not in ("logic", "outcomes", "result", "inputs")}
    assert S.Entry.model_validate({**t2, "tier": 2}).tier == 2


def test_options_only_for_enums():
    with pytest.raises(ValidationError):
        S.InputDef.model_validate({"id": "a", "label": "A", "type": "enum"})
    with pytest.raises(ValidationError):
        S.InputDef.model_validate({"id": "a", "label": "A", "type": "number", "options": ["1"]})


def test_unknown_fields_are_rejected(toy):
    toy["logic"][1]["default"] = "none"          # no default rows, structurally
    with pytest.raises(ValidationError):
        S.Entry.model_validate(toy)


def test_num_arity_and_step_kind():
    with pytest.raises(ValidationError):
        S.Num.model_validate({"op": "ln", "args": []})
    with pytest.raises(ValidationError):
        S.Num.model_validate({"op": "add", "args": [{"const": 1}]})
    assert S.Num.model_validate({"op": "div", "args": [{"ref": "a"}, {"const": 2}]}).refs() == ["a"]
    with pytest.raises(ValidationError):
        S.RulesStep.model_validate({"step": "magic", "id": "r", "cases": []})


def test_as_value():
    assert S.as_value(7) == S.InputValue(value=7)
    assert S.as_value({"state": "absent"}) == S.InputValue(state="absent")
    assert S.as_value({"band": "6to8"}).band == "6to8"
    iv = S.InputValue(value="x")
    assert S.as_value(iv) is iv


def test_scope_defaults_to_lesion_and_dims_belong_to_numbers():
    assert S.InputDef(id="a", label="A", type="boolean").scope == "lesion"
    assert S.InputDef(id="p", label="P", type="boolean", scope="patient").scope == "patient"
    assert S.InputDef(id="d", label="D", type="number", unit="mm", dims="mean").dims == "mean"
    with pytest.raises(ValidationError):
        S.InputDef(id="k", label="K", type="enum", options=["x"], dims="max")
    with pytest.raises(ValidationError):
        S.InputDef(id="s", label="S", type="boolean", scope="case")
