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


def _live():
    return L.Library(json.loads(L.BUNDLE.read_text()))


def test_find_takes_the_display_without_its_edition_the_id_slug_and_the_key():
    lib = _live()
    assert lib.find("ESE adrenal incidentaloma", "2023").id == "ese-adrenal-incidentaloma"
    assert lib.find("ESE adrenal incidentaloma").id == "ese-adrenal-incidentaloma"
    assert lib.find("ESE adrenal incidentaloma", "2016") is None          # a given version must equal the edition
    assert lib.find("BTS pulmonary nodule").id == "bts-pulmonary-nodule"   # the id as a slug
    assert lib.find("bts-pulmonary-nodule").id == "bts-pulmonary-nodule"
    assert lib.find("bts-pulmonary-nodule@2015.1").id == "bts-pulmonary-nodule"   # the full key
    assert lib.find("BTS pulmonary nodule 2015").id == "bts-pulmonary-nodule"     # a trailing year stripped


def test_every_current_pack_is_found_by_its_slug_key_and_bare_display():
    """No pack's id slug, key or display-without-edition collides with another pack's names."""
    lib = _live()
    for e in lib._current():
        assert lib.find(e.id.replace("-", " ")) is e, e.key
        assert lib.find(e.key) is e, e.key
        bare = L._bare_display(e)
        assert bare and lib.find(bare) is e, (e.key, bare)


def test_find_never_guesses_between_two_packs_with_the_same_bare_display(toy):
    a = {**toy, "id": "toy-a", "display": "Toy 2020", "aliases": []}
    b = {**toy, "id": "toy-b", "display": "Toy 2021", "edition": "2021", "aliases": []}
    lib = L.Library({"entries": {f"{e['id']}@1.0": {"entry": e} for e in (a, b)}})
    assert lib.find("Toy") is None
    assert lib.find("Toy", "2021").id == "toy-b"


def test_known_text_line_carries_the_key_and_a_scope_from_the_entry_data(toy):
    lib = L.Library({"entries": {"toy-nodule@1.0": {"entry": toy}}})
    assert lib.known_text() == ("- toy-nodule@1.0: Toy 2020 [aliases: toy nodule | toy guideline] "
                                "(scope: nodule in chest, incidental, CT)")
    lines = {ln.split(":")[0][2:]: ln for ln in _live().known_text().splitlines()}
    ese = lines["ese-adrenal-incidentaloma@2023.1"]
    assert ese.startswith("- ese-adrenal-incidentaloma@2023.1: ESE adrenal incidentaloma 2023 [aliases: ")
    assert "(scope: adrenal mass in abdomen, CT/MRI; not: History of extra-adrenal malignancy; " in ese
    aaa = lines["nhs-aaa-surveillance@2025.1"]   # an eligibility input whose false (or other option) excludes
    assert "only: Scan done within the NHS AAA screening programme; Sex = male; not: AAA already treated)" in aaa
    assert all(ln.count(" | ") <= L.KNOWN_ALIASES - 1 for ln in lines.values())


def test_every_entry_has_a_purpose_and_exam_level_set_is_the_six():
    from rapid_reports_ai.hybrid_stack.copilot.library.bundle import compile_bundle
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    entries = [Entry.model_validate(v["entry"]) for v in compile_bundle()["entries"].values() if v["entry"]["status"] == "current"]
    assert entries and all(e.purpose.strip() and len(e.purpose) <= 400 for e in entries)
    assert all("no clinical" not in e.purpose.lower() and "is stated" not in e.purpose.lower() for e in entries)
    assert {e.id for e in entries if "exam" in e.trigger} == {
        "cad-rads-2", "cac-drs", "nhs-aaa-surveillance", "aspects", "lund-mackay", "pi-rads-2-1"}
    assert {e.id: e.exam_presets for e in entries if e.exam_presets} == {"nhs-aaa-surveillance": {
        "screening_programme": "true", "sex": "male", "previous_aaa_treatment": "false"}}
    assert {e.id: e.matcher_topic for e in entries if e.match_topic} == {"cac-drs": "coronary", "cad-rads-2": "coronary"}
