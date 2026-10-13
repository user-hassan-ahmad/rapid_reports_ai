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
