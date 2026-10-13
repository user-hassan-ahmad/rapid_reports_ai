from pathlib import Path

import pytest

from rapid_reports_ai.hybrid_stack.protocol_library import bundle as PB
from rapid_reports_ai.hybrid_stack.protocol_library import compose as C

FIX = Path(__file__).parent / "fixtures" / "protocol_bundle_fixture.json"


@pytest.fixture
def b():
    return PB.load_bundle(FIX)


def test_resolve_default_phases(b):
    r = C.resolve(b, "TCAP", None, None)
    assert r.phases == ["portal_venous"] and r.sheet_key == "ct_ap_t" and r.contrast_class == "iv"
    assert r.scan_type_line == "CT Abdomen and Pelvis with contrast"
    assert [x.name for x in r.regions] == ["Liver", "Vessels", "Other findings"]
    assert r.sheet_id == "lib:TCAP|portal_venous|-|fixture-1"
    assert r.schema_key == "lib:ct_ap_t|iv"


def test_resolve_variant_names_phases_in_scan_line(b):
    r = C.resolve(b, "TCAP", ["arterial", "portal_venous"], None)
    assert r.scan_type_line == "CT Abdomen and Pelvis with contrast (arterial, portal venous)"


def test_resolve_rejects_unlisted_phases_and_unknown_entry(b):
    with pytest.raises(C.PickError):
        C.resolve(b, "TCAP", ["delayed"], None)
    with pytest.raises(C.PickError):
        C.resolve(b, "NOPE", None, None)


def test_laterality_required_and_named(b):
    with pytest.raises(C.PickError, match="laterality"):
        C.resolve(b, "TMKN", None, None)
    r = C.resolve(b, "TMKN", None, "left")
    assert r.scan_type_line == "MRI Knee (left)" and r.sheet_id == "lib:TMKN|none|left|fixture-1"
    with pytest.raises(C.PickError, match="laterality"):
        C.resolve(b, "TCTH", None, "left")


def test_quiet_and_level_groups(b):
    r = C.resolve(b, "TMWS", None, None)
    assert r.quiet == ["L4/5", "L5/S1"] and r.level_groups == {"Lumbar levels": ["L4/5", "L5/S1"]}
    assert [x.name for x in r.regions if x.quiet] == ["L4/5", "L5/S1"]


def test_compose_overlays_phase_normals_and_scan_context(b):
    s = C.compose_sheet(b, C.resolve(b, "TCAPT", None, None))
    assert s.region_normals["Liver"] == ["The liver is normal.", "No arterially enhancing focal liver lesion."]
    assert s.region_normals["Vessels"] == ["Fixture vessels sentence (base sheet)."]
    assert s.not_assessable == "collecting-system detail (fixture phase sheet, three phases)"
    assert "- **Modality:** CT with IV contrast: unenhanced, arterial, portal venous" in s.markdown
    assert "- **Imaged volume:** Diaphragm to symphysis." in s.markdown
    assert "placeholder" not in s.markdown
    assert "## Report Flow" in s.markdown


def test_compose_default_takes_not_assessable_from_the_phase_sheet(b):
    s = C.compose_sheet(b, C.resolve(b, "TCAP", None, None))
    assert s.not_assessable == "early-phase uptake (fixture phase sheet)"
    s = C.compose_sheet(b, C.resolve(b, "TCAP", ["arterial", "portal_venous"], None))
    assert s.not_assessable == "collecting-system detail (fixture phase sheet, two phases)"
    assert s.region_normals["Vessels"] == ["Fixture vessels sentence (early phase)."]


def test_compose_falls_back_to_entry_not_assessable_when_phase_sheet_is_empty(b):
    s = C.compose_sheet(b, C.resolve(b, "TMWS", None, None))   # TMWS|none has an empty scan_context
    assert s.not_assessable == "contrast uptake (fixture entry, unenhanced)"
    assert "- **Not assessable on this scan:** contrast uptake (fixture entry, unenhanced)" in s.markdown


def test_modality_line_agent_words_lowercase_except_abbreviations(b):
    assert C.modality_line(b.entry("TMBR"), ["dce"]) == "MR with gadolinium: DCE"
    assert C.modality_line(b.entry("TCAP"), ["portal_venous"]) == "CT with IV contrast: portal venous"
    assert C.modality_line(b.entry("TCTH"), []) == "CT without contrast"
    e = b.entry("TMBR").model_copy(update={"agent": "intra_articular"})
    assert C.modality_line(e, ["pre_contrast", "post_contrast"]) == "MR with intra-articular contrast: pre-contrast, post-contrast"
    e = b.entry("TMBR").model_copy(update={"agent": "iv_and_oral"})
    assert C.modality_line(e, ["dynamic_arterial", "dynamic_portal_venous", "dynamic_delayed", "angiographic"]) == \
        "MR with IV and oral contrast: arterial, portal venous, delayed, angiographic"


def test_compose_empty_change_removes_region_normal(b):
    s = C.compose_sheet(b, C.resolve(b, "TMKN", None, "right"))
    assert "Menisci" not in s.region_normals


def test_compose_never_offers_a_quiet_region_normal(b):
    assert b.phase_sheets["TMBR|dce"].changed_normals["Implants"]   # the phase sheet does offer one ...
    s = C.compose_sheet(b, C.resolve(b, "TMBR", None, None))
    assert "Implants" not in s.region_normals and s.region_normals["Right breast"]   # ... and compose pops it


def test_sheet_from_id_round_trip_and_garbage(b):
    r = C.resolve(b, "TMKN", None, "left")
    assert C.sheet_from_id(b, r.sheet_id).region_normals == C.compose_sheet(b, r).region_normals
    assert C.sheet_from_id(b, "lib:NOPE|none|-|x") is None
    assert C.sheet_from_id(b, "lib:garbage") is None
