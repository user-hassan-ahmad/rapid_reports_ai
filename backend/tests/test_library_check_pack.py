import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_pack", Path(__file__).resolve().parents[1] / "scripts" / "guidelines" / "check_pack.py")
CP = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(CP)


def test_a_good_pack_folder_passes_alone(toy_dir, capsys):
    assert CP.check(toy_dir / "toy-nodule") == 0
    assert "toy-nodule: gates 1-4 pass" in capsys.readouterr().out


def test_a_broken_pack_folder_fails_with_its_problems(toy_dir, capsys):
    e = json.loads((toy_dir / "toy-nodule" / "entry.json").read_text())
    e["outcomes"] = e["outcomes"][1:]                   # an outcome the rules still name
    (toy_dir / "toy-nodule" / "entry.json").write_text(json.dumps(e))
    assert CP.check(toy_dir / "toy-nodule") == 1
    assert "is not an outcome" in capsys.readouterr().out


def test_a_missing_folder_fails(tmp_path):
    assert CP.check(tmp_path / "nope") == 1
