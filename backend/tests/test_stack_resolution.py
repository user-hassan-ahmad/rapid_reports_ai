import pytest

from rapid_reports_ai.hybrid_stack import resolution as RS


def test_round_trip():
    p = {"src": "library", "eid": "ct_abdo", "ph": ["portal venous"], "lat": None, "bv": "9c29622", "sid": "lib:x"}
    assert RS.verify(RS.mint(p)) == {**p, "v": 1}


def test_tampered_token_rejected():
    t = RS.mint({"src": "free", "scan": "CT", "sk": "k", "sid": None})
    body, sig = t.split(".")
    forged = RS.mint({"src": "free", "scan": "MR", "sk": "k", "sid": None}).split(".")[0] + "." + sig
    with pytest.raises(RS.TokenError):
        RS.verify(forged)
    with pytest.raises(RS.TokenError):
        RS.verify("not-a-token")
    with pytest.raises(RS.TokenError):
        RS.verify(None)


def test_secret_rotation_invalidates(monkeypatch):
    t = RS.mint({"src": "free", "scan": "CT", "sk": "k", "sid": None})
    monkeypatch.setattr(RS, "_secret", lambda: b"other")
    with pytest.raises(RS.TokenError):
        RS.verify(t)
