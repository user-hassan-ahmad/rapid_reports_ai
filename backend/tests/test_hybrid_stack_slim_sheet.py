import json
from pathlib import Path

import httpx

from rapid_reports_ai.database.models import StackSlimSheet
from rapid_reports_ai.hybrid_stack import slim_sheet as SL
from rapid_reports_ai.hybrid_stack.schemas import Region

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
