import json

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L


def _lib(toy_dir):
    return L.Library(L.compile_bundle(toy_dir))


def test_compile_is_deterministic_and_strips_file_paths(toy_dir):
    b = L.compile_bundle(toy_dir)
    assert len(b["version"]) == 12 and list(b["entries"]) == ["toy-nodule@1.0"]
    assert b == L.compile_bundle(toy_dir)
    src = b["entries"]["toy-nodule@1.0"]["sources"][0]
    assert src == {"id": "S1", "role": "primary", "title": "Toy guideline", "issuer": "TOY", "edition": "2020",
                   "url": "https://example.org/toy"}


def test_a_failing_gate_fails_the_build(toy_dir):
    p = toy_dir / "toy-nodule" / "entry.json"
    d = json.loads(p.read_text())
    d["logic"][1]["cases"].pop()
    p.write_text(json.dumps(d))
    with pytest.raises(L.BundleError, match="no case holds"):
        L.compile_bundle(toy_dir)


def test_folder_must_match_the_entry_id(toy_dir):
    (toy_dir / "toy-nodule").rename(toy_dir / "other")
    with pytest.raises(L.BundleError, match="folder"):
        L.compile_bundle(toy_dir)


def test_superseded_versions_are_kept(toy_dir, toy):
    h = toy_dir / "toy-nodule" / "history"
    h.mkdir()
    (h / "0.9.json").write_text(json.dumps({**toy, "version": "0.9", "status": "superseded"}))
    lib = _lib(toy_dir)
    assert lib.lookup("toy-nodule@0.9").status == "superseded"
    assert lib.lookup("toy-nodule").version == "1.0"
    assert lib.lookup("toy-nodule", "0.9").version == "0.9"


def test_library_interface(toy_dir, toy):
    sib = toy_dir / "toy-other"
    sib.mkdir()
    (sib / "entry.json").write_text(json.dumps({**toy, "id": "toy-other", "issuer": "OTHER", "display": "Other 2021",
                                                "aliases": ["other nodule"]}))
    for f in ("manifest.json", "cases.json"):
        (sib / f).write_text((toy_dir / "toy-nodule" / f).read_text())
    lib = _lib(toy_dir)
    toy_e = lib.lookup("toy-nodule@1.0")
    assert [e.id for e in lib.list(region="chest", finding_type="nodule")] == ["toy-nodule", "toy-other"]
    assert lib.list(region="abdomen") == []
    assert [e.id for e in lib.siblings(toy_e)] == ["toy-other"]
    assert lib.find("Toy Nodule").id == "toy-nodule" and lib.find("TOY NODULE", "2020").id == "toy-nodule"
    assert lib.find("Toy Nodule", "1999") is None and lib.find("Fleischner") is None
    assert lib.evaluate("toy-nodule@1.0", {"kind": "subsolid"}).outcome == "subsolid"
    assert "- toy-nodule@1.0: Toy 2020 [aliases: toy nodule | toy guideline]" in lib.known_text()
    assert lib.sources("toy-nodule@1.0")[0]["id"] == "S1"


def test_get_fails_open(monkeypatch, tmp_path):
    monkeypatch.undo()                                  # drop the autouse empty-library patch
    monkeypatch.setattr(L, "BUNDLE", tmp_path / "missing.json")
    L._load.cache_clear()
    try:
        assert L.get().version() == "" and L.get().lookup("x@1") is None
    finally:
        L._load.cache_clear()


def test_committed_bundle_matches_the_guidelines_folder():
    assert json.loads(L.BUNDLE.read_text()) == L.compile_bundle(L.guidelines_root())


def test_guidelines_root_is_safe_on_a_short_install_path():
    """A deploy layout shallower than the repo (e.g. /app/rapid_reports_ai/...) must not raise at import or lookup:
    the bundle is loaded from resources/, and the source folders are only needed to compile it."""
    from pathlib import Path
    root = L.guidelines_root(Path("/app/rapid_reports_ai/library/bundle.py"))
    assert isinstance(root, Path) and not root.exists()
    assert L.compile_bundle(root) == {"version": L.compile_bundle(root)["version"], "entries": {}}
    assert L.guidelines_root() == L.Path(L.__file__).resolve().parents[6] / "guidelines"
