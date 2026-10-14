import json
from pathlib import Path

import httpx
import pytest

from rapid_reports_ai.database.models import StackSlimSheet
from rapid_reports_ai.hybrid_stack import slim_sheet as SL
from rapid_reports_ai.hybrid_stack.schemas import Region
from rapid_reports_ai.hybrid_stack.template import jev_text, template_normal_labels, template_region_normals
from rapid_reports_ai.template_sheet_grammar import parse_sheet

SHEET = """## Scan Context
- **Modality:** CT, portal venous phase
- **Not assessable on this scan:** arterial phase enhancement; Doppler flow

## Structural Pattern
- **Sections:** TECHNIQUE, FINDINGS, IMPRESSION

## Region Normals
- **Liver:** "The liver is normal in size and attenuation." "No focal liver lesion."
- **Kidneys:** "The kidneys enhance symmetrically." "No hydronephrosis." "The kidneys measure 11 cm."
- **Spleen:** "The spleen is normal."
- **Unknown region:** "Something."

## Style Exemplars
- **Liver cyst:** "A 2 cm simple cyst in segment 6."
"""
REGIONS = [Region(name="Liver", includes="liver"), Region(name="Kidneys", includes="kidneys"),
           Region(name="Spleen", includes="spleen"), Region(name="Other findings", includes="other")]


@pytest.fixture(autouse=True)
def _no_sex_screen_call(monkeypatch):
    """No test here may reach OpenRouter: the sex screen passes every sentence unless a test stubs its own."""
    async def screen(normals, transport=None):
        return normals, []
    monkeypatch.setattr(SL, "screen_normals", screen)


def test_parse_keeps_known_regions_and_drops_measurements():
    normals, na = SL.parse_slim(SHEET, [r.name for r in REGIONS])
    assert normals == {"Liver": ["The liver is normal in size and attenuation.", "No focal liver lesion."],
                       "Kidneys": ["The kidneys enhance symmetrically.", "No hydronephrosis."],
                       "Spleen": ["The spleen is normal."]}
    assert na == "arterial phase enhancement; Doppler flow"
    assert SL.parse_slim("## Scan Context\n- x", ["Liver"]) == ({}, "")


async def test_contrast_facet_is_a_jev_choice_and_fails_to_unknown(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    def handler(req):
        body = json.loads(req.content)
        assert set(body["questions"]["contrast"]["criteria"]) == set(SL.CONTRAST)
        assert "CT AP PV phase" in body["state"]
        return httpx.Response(200, json={"answers": {"contrast": {"choice": "portal_venous"}}})
    assert await SL.contrast_facet("CT AP PV phase ?appendicitis", transport=httpx.MockTransport(handler)) == "portal_venous"

    def bad(req):
        return httpx.Response(500)
    assert await SL.contrast_facet("CT", transport=httpx.MockTransport(bad)) == "unknown"


async def test_get_or_make_caches_by_family_and_contrast(db_session, monkeypatch):
    calls = []

    async def gen(scan_type, family, contrast, regions):
        calls.append((scan_type, contrast))
        return SHEET
    monkeypatch.setattr(SL, "generate", gen)

    async def facet(scan_type, transport=None):
        return "portal_venous"
    monkeypatch.setattr(SL, "contrast_facet", facet)
    a = await SL.get_or_make(db_session, "CT abdomen pelvis with contrast", "abdomen_pelvis", REGIONS)
    b = await SL.get_or_make(db_session, "CTAP PV ?appendicitis", "abdomen_pelvis", REGIONS)
    assert len(calls) == 1 and a.id == b.id and a.status == "provisional"
    assert b.region_normals["Spleen"] == ["The spleen is normal."]
    assert db_session.query(StackSlimSheet).count() == 1


async def test_failure_returns_none(db_session, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(SL, "generate", boom)

    async def facet(scan_type, transport=None):
        return "none"
    monkeypatch.setattr(SL, "contrast_facet", facet)
    assert await SL.get_or_make(db_session, "CT KUB", "kub", REGIONS) is None


def test_template_region_normals_from_the_stored_structure():
    from rapid_reports_ai.hybrid_stack.template import template_region_normals, template_regions
    from rapid_reports_ai.template_sheet_grammar import parse_sheet
    st = parse_sheet((Path(__file__).parent / "fixtures" / "template_pipeline" / "lean_cmr.md").read_text(), mode="template").structure
    normals = template_region_normals(st)
    names = {r.name for r in template_regions(st)}
    assert normals and set(normals) <= names
    assert all(s.strip() for ss in normals.values() for s in ss)


_PELVIS_MD = "## Region Normals\n- **Pelvic organs:** \"The bladder is normal.\" \"The prostate is normal in size.\" \"The uterus is unremarkable.\" \"The ovaries are normal.\"\n"


def test_parse_slim_keeps_sex_specific_sentences_for_the_async_screen():
    assert SL.parse_slim(_PELVIS_MD, ["Pelvic organs"])[0] == {"Pelvic organs": [
        "The bladder is normal.", "The prostate is normal in size.", "The uterus is unremarkable.", "The ovaries are normal."]}


async def test_sex_specific_sentences_never_become_shared_normals(db_session, monkeypatch):
    async def gen(*a, **k):
        return _PELVIS_MD
    monkeypatch.setattr(SL, "generate", gen)

    async def facet(scan_type, transport=None):
        return "none"
    monkeypatch.setattr(SL, "contrast_facet", facet)
    scores = {"The prostate is normal in size.": 0.95, "The uterus is unremarkable.": 0.9, "The ovaries are normal.": 0.97}

    async def screen(normals, transport=None):
        return await real_screen(normals, httpx.MockTransport(lambda req: httpx.Response(200, json={"answers": {"q": {
            "noul": scores.get(json.loads(req.content)["state"].removeprefix("SENTENCE: "), 0.02)}}})))
    from rapid_reports_ai.hybrid_stack.sex_screen import screen_normals as real_screen
    monkeypatch.setattr(SL, "screen_normals", screen)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    row = await SL.get_or_make(db_session, "CT pelvis", "pelvis", [Region(name="Pelvic organs", includes="pelvis")])
    assert row.region_normals == {"Pelvic organs": ["The bladder is normal."]}


def _lean_cfg(sheet=None):
    return {"generation_mode": "skill_sheet_guided", "scan_type": "CMR",
            "skill_sheet": sheet if sheet is not None else (Path(__file__).parent / "fixtures" / "template_pipeline" / "lean_cmr.md").read_text()}


def test_template_structure_reparses_a_sheet_with_no_fresh_stored_copy():
    """No stored structure (or a stale one): the sheet is parsed now, so the session still gets its normals."""
    from rapid_reports_ai.hybrid_stack.template import template_structure
    st = template_structure(_lean_cfg())
    assert st is not None and st.usable and st.normals
    stale = {**_lean_cfg(), "sheet_structure": {"failed": True}}
    assert template_structure(stale) is not None


def test_template_structure_is_none_for_a_sheet_that_is_not_clean_grammar():
    from rapid_reports_ai.hybrid_stack.template import template_structure
    assert template_structure(_lean_cfg("## FINDINGS\nDescribe the findings.")) is None   # not grammar
    broken = _lean_cfg().copy()
    broken["skill_sheet"] = broken["skill_sheet"] + "\nnormal [liver] \"lowercase keyword\"\n"   # lint error
    from rapid_reports_ai.template_sheet_grammar import parse_sheet
    assert not parse_sheet(broken["skill_sheet"]).structure.usable
    assert template_structure(broken) is None
    assert template_structure({**_lean_cfg(), "generation_mode": "auto"}) is None


_SUBJECTLESS = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Liver (FINDINGS)
COVERS ["liver"]
Opening: "The liver is normal."
NORMAL [liver] "Unremarkable."
NORMAL [spleen] "The spleen is normal in size."
"""


def _labels(label, sentence):
    sheet = _SUBJECTLESS.replace('NORMAL [liver] "Unremarkable."', f'NORMAL [{label}] "{sentence}"')
    return template_normal_labels(parse_sheet(sheet, mode="template").structure)


def test_subjectless_normal_is_offered_raw_and_labelled_for_jev():
    st = parse_sheet(_SUBJECTLESS, mode="template").structure
    assert st.usable
    assert template_region_normals(st)["Liver"] == ["Unremarkable.", "The spleen is normal in size."]
    assert template_normal_labels(st) == {"Unremarkable.": "liver"}


def test_jev_text_normalises_the_label():
    assert jev_text("Unremarkable.", '"LEFT VENTRICLE"') == "Left ventricle: Unremarkable."
    assert jev_text("MCL intact.", "knee joint") == "Knee joint: MCL intact."


def test_loose_match_of_label_to_sentence():
    assert "Lung volumes preserved." not in _labels("LUNGS", "Lung volumes preserved.")
    assert "Both menisci appear normal." not in _labels("medial meniscus, lateral meniscus", "Both menisci appear normal.")
    assert "No hydrocephalus and no mass effect." in _labels("ventricles and basal cisterns", "No hydrocephalus and no mass effect.")


from rapid_reports_ai.hybrid_stack.template import template_suppressions

_RULED = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Brain (FINDINGS)
COVERS ["brain"]
NEGATIVE "No other interval changes compared with the previous MRI."
NORMAL [ventricles] "The ventricles are normal in size."
RULE WHEN [context: no previous study is available] SUPPRESS "No other interval changes compared with the previous MRI."
"""


def test_context_suppressions_name_the_normal_they_hide():
    st = parse_sheet(_RULED, mode="template").structure
    assert st.usable
    assert template_suppressions(st) == [
        ("no previous study is available", "No other interval changes compared with the previous MRI.")]


def test_a_slot_placeholder_sentence_is_never_offered():
    sheet = _SUBJECTLESS + 'NORMAL [left ventricle] "LVEDVi {value} ml/m2."\n'
    st = parse_sheet(sheet, mode="template").structure
    assert st.usable
    assert not any("{" in s for ss in template_region_normals(st).values() for s in ss)
    assert "The spleen is normal in size." in template_region_normals(st)["Liver"]


def test_the_prompt_carries_the_standard_section_order_and_rules():
    assert SL.PROMPT_VERSION == "slim-7"   # bumped so cached free-text sheets regenerate
    assert "- **Sections:** Comparison; Technique; Limitations (only when applicable); Findings; Conclusion" \
        in SL.SLIM_SYS
    assert "Findings; Impression" not in SL.SLIM_SYS
    rules = next(ln for ln in SL.SLIM_SYS.splitlines() if ln.startswith("- **Section rules:**"))
    for needle in ("no prior imaging is available for comparison", "Modality line in Scan Context",
                   "never the not-assessable list", "Never a clinical history",
                   "CONCLUSION never restates the modality, region or technique; it opens with the finding."):
        assert needle in rules


def test_a_generated_sheet_with_the_standard_sections_still_parses():
    md = SHEET.replace("TECHNIQUE, FINDINGS, IMPRESSION",
                       "Comparison; Technique; Limitations (only when applicable); Findings; Conclusion")
    assert SL.parse_slim(md, [r.name for r in REGIONS]) == SL.parse_slim(SHEET, [r.name for r in REGIONS])


def test_label_case_keeps_mixed_case_and_acronym_tokens():
    from rapid_reports_ai.hybrid_stack.template import label_case
    assert label_case("LCx") == "LCx"
    assert label_case("proximal LAD and LCx") == "Proximal LAD and LCx"
    assert label_case("RCA") == "RCA" and label_case("CT findings") == "CT findings"
    assert label_case("LEFT VENTRICLE") == "Left ventricle" and label_case("Cardiac Chambers") == "Cardiac chambers"
    assert jev_text("Patent.", "LCx") == "LCx: Patent."
