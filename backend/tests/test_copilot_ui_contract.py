"""The Copilot UI reads only the backend fields listed in frontend/src/lib/copilot/contract.json: every one must
still exist on its model, so a rename here fails in CI instead of silently blanking a card. No network."""

import json
from pathlib import Path

import pytest

CONTRACT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "copilot" / "contract.json"


def _models() -> dict:
    from rapid_reports_ai.hybrid_stack.copilot import routes as R
    from rapid_reports_ai.hybrid_stack.copilot import types as T

    return {
        "Card": T.Card,
        "Preview": T.Preview,
        "DraftValue": T.DraftValue,
        "Calculation": T.Calculation,
        "Assumption": T.Assumption,
        "OutcomeBrief": T.OutcomeBrief,
        "DecidingAnswer": T.DecidingAnswer,
        "ExclusionReason": T.ExclusionReason,
        "DecidingInput": T.DecidingInput,
        "Entry": T.Entry,
        "GuidelineContent": T.GuidelineContent,
        "Branch": T.Branch,
        "Input": T.Input,
        "CalculateRequest": R.CalculateRequest,
        "CalculateResult": R.CalculateResult,
        "Settled": T.Settled,
        "Proposal": T.Proposal,
        "OpenResult": R.OpenResult,
        "MatchResult": R.MatchResult,
        "MatchRequest": R.MatchRequest,
        "OpenRequest": R.OpenRequest,
        "CardIn": R.CardIn,
        "FindingIn": R.FindingIn,
    }


@pytest.mark.skipif(not CONTRACT.exists(), reason="frontend folder absent")
def test_every_contract_field_exists_on_its_model():
    contract = {k: v for k, v in json.loads(CONTRACT.read_text()).items() if not k.startswith("_")}
    models = _models()
    unknown = sorted(set(contract) - set(models))
    assert not unknown, f"contract names models the test does not map: {unknown}"
    missing = {name: [f for f in fields if f not in models[name].model_fields] for name, fields in contract.items()}
    missing = {k: v for k, v in missing.items() if v}
    assert not missing, f"fields the UI reads but the backend no longer has: {missing}"


@pytest.mark.skipif(not CONTRACT.exists(), reason="frontend folder absent")
def test_copilot_off_404_carries_the_detail_the_ui_reads(monkeypatch):
    """The UI turns the session off only on this exact detail; any other 404 is a card-local failure."""
    from fastapi import HTTPException

    from rapid_reports_ai.hybrid_stack.copilot import routes as R

    monkeypatch.setattr(R, "copilot_allowed", lambda *a, **k: False)
    with pytest.raises(HTTPException) as e:
        R._require()
    assert e.value.status_code == 404
    assert e.value.detail == json.loads(CONTRACT.read_text())["_off_detail"]


@pytest.mark.skipif(not CONTRACT.exists(), reason="frontend folder absent")
def test_value_and_card_states_match_what_the_ui_renders():
    """The draft card draws one style per value state and one per card state: a new or renamed literal must reach
    frontend/src/lib/copilot/types.ts (ValueState, CardState) and contract.json together."""
    from typing import get_args

    from rapid_reports_ai.hybrid_stack.copilot import types as T

    contract = json.loads(CONTRACT.read_text())
    assert set(get_args(T.ValueState)) == set(contract["_value_states"])
    assert set(get_args(T.CardState)) <= set(contract["_card_states"])
    kind = T.Assumption.model_fields["kind"].annotation
    assert set(get_args(kind)) == set(contract["_assumption_kinds"])
