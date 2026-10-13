import re
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


STANDARD_SECTIONS = "- **Sections:** Comparison; Technique; Limitations (only when applicable); Findings; Conclusion"
CONCLUSION_RULE = "CONCLUSION never restates the modality, region or technique; it opens with the finding."


def _bullets(md, heading, label):
    sec = re.search(rf"^##\s+{heading}\s*$([\s\S]*?)(?=^##\s|\Z)", md, re.M)
    return [ln for ln in (sec.group(1) if sec else "").splitlines() if ln.startswith(f"- **{label}:**")]


def test_technique_statement_is_composed_from_the_entry_and_phases(b):
    def tech(entry, phases=None, lat=None):
        return _bullets(C.compose_sheet(b, C.resolve(b, entry, phases, lat)).markdown, "Scan Context",
                        "Technique statement")
    # CT multiphase / single phase: "CT <region> following intravenous contrast: <phases in words> phase(s)."
    assert tech("TCAPT") == ["- **Technique statement:** CT abdomen and pelvis following intravenous contrast: "
                             "unenhanced, arterial and portal venous phases."]
    assert tech("TCAP", ["portal_venous"]) == ["- **Technique statement:** CT abdomen and pelvis following "
                                               "intravenous contrast: portal venous phase."]
    # CT unenhanced
    assert tech("TCTH") == ["- **Technique statement:** CT head without intravenous contrast."]
    # MR: multiplanar multisequence, the gadolinium clause only with contrast
    assert tech("TMWS") == ["- **Technique statement:** Multiplanar multisequence MRI of the whole spine."]
    assert tech("TMKN", None, "left") == ["- **Technique statement:** Multiplanar multisequence MRI of the left knee."]
    assert tech("TMBR") == ["- **Technique statement:** Multiplanar multisequence MRI of the breast following "
                            "intravenous gadolinium."]


def test_technique_statement_region_drops_contrast_and_phase_words_and_takes_laterality(b):
    knee = _variant(b, "TMKN", display_name="MRI Knee with IV contrast", agent="gadolinium")
    assert C.technique_statement(knee, ["pre_contrast", "post_contrast"], "right") == \
        "Multiplanar multisequence MRI of the right knee following intravenous gadolinium."
    ct = _variant(b, "TCTH", display_name="CT Liver four phase", agent="iv_iodinated")
    assert C.technique_statement(ct, ["non_contrast", "late_arterial", "portal_venous", "delayed"]) == \
        "CT liver following intravenous contrast: unenhanced, late arterial, portal venous and delayed phases."
    for name in ("CT Liver dual phase", "CT Liver triple-phase", "CT Liver with IV and oral contrast"):
        assert C.technique_statement(_variant(b, "TCTH", display_name=name, agent="iv_iodinated"), ["arterial"]) == \
            "CT liver following intravenous contrast: arterial phase.", name
    wrist = _variant(b, "TCTH", display_name="CT Wrist without contrast")
    assert C.technique_statement(wrist, [], "left") == "CT left wrist without intravenous contrast."


def test_technique_statement_keeps_a_procedure_name_that_is_not_a_region(b):
    e = b.entry("TMKN").model_copy(update={"display_name": "MR Arthrogram hip", "agent": "intra_articular"})
    assert C.technique_statement(e, ["post_contrast"], "right") == \
        "Multiplanar multisequence MR arthrogram hip (right) following intra-articular gadolinium."
    cta = b.entry("TCAP").model_copy(update={"display_name": "CT Angiogram thoracic aorta"})
    assert C.technique_statement(cta, ["non_contrast", "arterial"]) == \
        "CT angiogram thoracic aorta following intravenous contrast: unenhanced and arterial phases."


def test_sweep_order_is_the_region_list_minus_other_findings_and_quiet_regions(b):
    def sweep(entry, lat=None):
        return _bullets(C.compose_sheet(b, C.resolve(b, entry, None, lat)).markdown, "Structural Pattern",
                        "Sweep order")
    assert sweep("TCAP") == ["- **Sweep order:** Liver → Vessels"]
    assert sweep("TMWS") == ["- **Sweep order:** Alignment and vertebrae → Lumbar levels"]   # L4/5, L5/S1 quiet
    assert sweep("TMBR") == ["- **Sweep order:** Right breast"]                               # Implants quiet


def test_standard_sections_and_rules_replace_the_sheets_own_list(b):
    base = b.base_sheets["ct_ap_t|iv"]
    base.markdown += ("\n## Structural Pattern\n- **Sections:** Findings, Impression\n- **Sweep order:** Liver, Vessels\n"
                      "- **Macro-structure:** FLAT\n\n## Style Exemplars\n- **Mass:** \"A mass.\"\n")
    md = C.compose_sheet(b, C.resolve(b, "TCAP", None, None)).markdown
    assert _bullets(md, "Structural Pattern", "Sections") == [STANDARD_SECTIONS]
    rules = _bullets(md, "Structural Pattern", "Section rules")
    assert len(rules) == 1
    for needle in ("COMPARISON", "no prior imaging is available for comparison", "TECHNIQUE", "Technique statement",
                   "LIMITATIONS", "not-assessable", "clinical history", CONCLUSION_RULE):
        assert needle in rules[0]
    assert "IMPRESSION" not in rules[0]
    assert _bullets(md, "Structural Pattern", "Sweep order") == ["- **Sweep order:** Liver → Vessels"]
    assert md.count("Findings, Impression") == 0 and md.count("## Structural Pattern") == 1


def test_a_sheet_without_a_structural_pattern_gets_one(b):
    for key in ("TCTH", "TMKN"):
        md = C.compose_sheet(b, C.resolve(b, key, None, "left" if key == "TMKN" else None)).markdown
        assert md.count("## Structural Pattern") == 1
        assert _bullets(md, "Structural Pattern", "Sections") == [STANDARD_SECTIONS]
        assert len(_bullets(md, "Structural Pattern", "Section rules")) == 1


def test_a_structural_pattern_with_no_sections_bullet_gains_one(b):
    b.base_sheets["ct_head_t|none"].markdown += "\n## Structural Pattern\n- **Macro-structure:** FLAT\n"
    md = C.compose_sheet(b, C.resolve(b, "TCTH", None, None)).markdown
    assert md.count("## Structural Pattern") == 1
    assert _bullets(md, "Structural Pattern", "Sections") == [STANDARD_SECTIONS]
    assert _bullets(md, "Structural Pattern", "Macro-structure") == ["- **Macro-structure:** FLAT"]


def test_the_generator_brief_keeps_the_sections_rules_and_technique_statement(b):
    # stack_fallback drops DROP_TOP_BULLETS / STACK_DROP_BULLETS / history sections: none may take the new bullets
    from rapid_reports_ai.quick_report_brief import stack_fallback
    text = stack_fallback(C.compose_sheet(b, C.resolve(b, "TCAPT", None, None)).markdown, "").text
    assert STANDARD_SECTIONS in text
    assert "Section rules" in text and "no prior imaging is available for comparison" in text
    assert CONCLUSION_RULE in text and "- **Sweep order:** Liver → Vessels" in text
    assert "Technique statement" in text and "following intravenous contrast: unenhanced, arterial and portal venous phases." in text


def _variant(b, entry, **update):
    return b.entry(entry).model_copy(update=update)


def test_contrast_wording_follows_the_phase_set_not_only_the_entry_agent(b):
    # an unenhanced-only phase set is "without contrast", whatever the entry's agent
    ct = _variant(b, "TCAP", agent="iv_iodinated")
    assert C.technique_statement(ct, ["non_contrast"]) == "CT abdomen and pelvis without intravenous contrast."
    assert C.modality_line(ct, ["non_contrast"]) == "CT without contrast: unenhanced"
    mr = _variant(b, "TMKN", agent="gadolinium")
    assert C.technique_statement(mr, ["cine", "flow"]) == "Multiplanar multisequence MRI of the knee."
    assert C.modality_line(mr, ["t2star"]) == "MR without contrast: T2*"
    # a contrast phase on an agent-none entry takes the modality default
    mr0 = _variant(b, "TMKN", agent="none")
    assert C.technique_statement(mr0, ["pre_contrast", "post_contrast"]) == \
        "Multiplanar multisequence MRI of the knee following intravenous gadolinium."
    assert C.modality_line(mr0, ["cine", "flow", "lge"]) == "MR with gadolinium: cine, flow, LGE"
    ct0 = _variant(b, "TCAP", agent="none")
    assert C.technique_statement(ct0, ["arterial", "portal_venous"]) == \
        "CT abdomen and pelvis following intravenous contrast: arterial and portal venous phases."
    assert C.modality_line(ct0, ["non_contrast", "arterial"]) == "CT with IV contrast: unenhanced, arterial"
    # an empty phase set keeps the entry's agent; a named agent with contrast phases is unchanged
    assert C.technique_statement(_variant(b, "TCAP", agent="iv_iodinated"), []) == \
        "CT abdomen and pelvis following intravenous contrast."
    assert C.modality_line(_variant(b, "TCTH", agent="none"), []) == "CT without contrast"
    assert C.modality_line(_variant(b, "TCAP", agent="iv_and_oral"), ["arterial"]) == "CT with IV and oral contrast: arterial"
    assert C.technique_statement(_variant(b, "TCAP", agent="iv_and_oral"), ["portal_venous"]) == \
        "CT abdomen and pelvis following intravenous and oral contrast: portal venous phase."
