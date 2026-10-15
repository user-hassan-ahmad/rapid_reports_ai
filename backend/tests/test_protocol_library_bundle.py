import json
import logging
from pathlib import Path

import pytest

from rapid_reports_ai.hybrid_stack.protocol_library import bundle as PB

FIX = Path(__file__).parent / "fixtures" / "protocol_bundle_fixture.json"


@pytest.fixture(autouse=True)
def _clear():
    PB.reset_cache()
    yield
    PB.reset_cache()


@pytest.fixture(autouse=True)
def _logger_enabled():
    """An earlier test's logging config can leave this logger disabled; caplog would then see nothing."""
    lg = logging.getLogger(PB.__name__)
    was = lg.disabled
    lg.disabled = False
    yield
    lg.disabled = was


def test_phase_id():
    assert PB.phase_id([]) == "none"
    assert PB.phase_id(["arterial", "portal_venous"]) == "arterial+portal_venous"


def test_load_fixture_and_lookup():
    b = PB.load_bundle(FIX)
    assert b.version == "fixture-1"
    assert b.entry("TCAP").display_name == "CT Abdomen and Pelvis with contrast"
    assert b.entry("nope") is None
    spine = b.keys["mr_spine_t"]
    assert [r.name for r in spine.regions if r.quiet] == ["L4/5", "L5/S1"]
    assert spine.level_groups == {"Lumbar levels": ["L4/5", "L5/S1"]}


def test_validation_rejects_missing_phase_sheet(tmp_path):
    d = json.loads(FIX.read_text())
    del d["phase_sheets"]["TCAP|arterial+portal_venous"]
    p = tmp_path / "b.json"
    p.write_text(json.dumps(d))
    with pytest.raises(PB.BundleError, match="TCAP"):
        PB.load_bundle(p)


def test_validation_rejects_unknown_sheet_key(tmp_path):
    d = json.loads(FIX.read_text())
    d["entries"][0]["sheet_key"] = "missing_key"
    p = tmp_path / "b.json"
    p.write_text(json.dumps(d))
    with pytest.raises(PB.BundleError, match="missing_key"):
        PB.load_bundle(p)


def test_library_allowed_needs_flag_stack_and_bundle(monkeypatch):
    env = {"RR_DICTATION_V2": "1", "RR_PROTOCOL_LIBRARY": "1", "RR_PROTOCOL_LIBRARY_PATH": str(FIX)}
    assert PB.library_allowed(env) is True
    PB.reset_cache()
    assert PB.library_allowed({**env, "RR_PROTOCOL_LIBRARY": "0"}) is False
    assert PB.library_allowed({**env, "RR_STACK": "0"}) is False


def test_broken_bundle_turns_library_off(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger=PB.__name__)
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    env = {"RR_DICTATION_V2": "1", "RR_PROTOCOL_LIBRARY": "1", "RR_PROTOCOL_LIBRARY_PATH": str(p)}
    assert PB.library_allowed(env) is False
    assert "protocol library" in caplog.text.lower()


def test_directory_path_finds_bundle(tmp_path):
    (tmp_path / "bundle").mkdir()
    (tmp_path / "bundle" / "protocol_library.json").write_text(FIX.read_text())
    env = {"RR_DICTATION_V2": "1", "RR_PROTOCOL_LIBRARY": "1", "RR_PROTOCOL_LIBRARY_PATH": str(tmp_path)}
    assert PB.library_allowed(env) is True


@pytest.mark.parametrize("pin, want, commit", [("fixture-1 3ab958e", ("fixture-1", "3ab958e"), "3ab958e"),
                                               ("fixture-1", ("fixture-1", ""), "fixture-1"),
                                               ("", ("", ""), "")])
def test_read_pin_both_formats(tmp_path, pin, want, commit):
    p = tmp_path / "protocol_library.pin"
    p.write_text(pin + "\n")
    assert PB.read_pin(p) == want and PB.pin_commit(p) == commit
    assert PB.read_pin(tmp_path / "absent.pin") == ("", "")


@pytest.mark.parametrize("pin, warns", [("fixture-1 3ab958e", False), ("fixture-1", False),
                                        ("other 3ab958e", True), ("other", True)])
def test_pin_compares_only_the_bundle_version(monkeypatch, tmp_path, caplog, pin, warns):
    caplog.set_level(logging.WARNING, logger=PB.__name__)
    p = tmp_path / "protocol_library.pin"
    p.write_text(pin)
    monkeypatch.setattr(PB, "PIN_FILE", p)
    assert PB.get_bundle({"RR_PROTOCOL_LIBRARY_PATH": str(FIX)}) is not None
    assert ("does not match pin" in caplog.text) is warns


def test_the_repo_pin_names_the_bundle_version_then_the_private_commit():
    assert PB.read_pin() == ("c895506", "c81ab0a")
