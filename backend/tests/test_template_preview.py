import uuid
from types import SimpleNamespace as NS

import pytest

from rapid_reports_ai import template_preview
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.main import app
from rapid_reports_ai.template_preview import confirmed_assumed, findings_block, region_states, region_text

R = [NS(name="Liver"), NS(name="Kidneys")]
A = "Assumed normal (confirmed by the radiologist):"


def U(text, group, abnormal=False, parts=None, covers=(), heading=False):
    return NS(text=text, group=group, abnormal=abnormal, parts=parts, covers=list(covers), heading=heading)


def P(text, group, abnormal=False):
    return NS(text=text, group=group, abnormal=abnormal)


def test_findings_block_matches_the_scratchpad_order():
    units = [NS(text="CT with contrast.", group="Technique", heading=False),
             NS(text="9 mm cyst.", group="Liver", heading=False),
             NS(text="Free fluid.", group="General", heading=False),
             NS(text="Odd sentence.", group=None, heading=False),
             NS(text="Appendicitis.", group="Conclusion", heading=False)]
    b = findings_block(units, R, {"Liver": ["No biliary dilatation."], "Kidneys": ["Normal kidneys."]},
                       "Appendicitis.", [])
    assert b.splitlines()[0] == "CT with contrast."
    assert f"Liver: 9 mm cyst. {A} No biliary dilatation." in b
    assert "Free fluid." in b and "Odd sentence." in b
    assert f"{A} Kidneys: Normal kidneys." in b
    assert b.endswith("Conclusion (confirmed by the radiologist): Appendicitis.")


def test_findings_block_follows_region_state_ts():
    """regionState.findingsText: regions in sheet order, other labelled groups, spanning sentences whole under their
    joined label (sheet order), every General line before every unplaced one; headings and Conclusion left out."""
    units = [U("Odd sentence.", None),
             U("Kidney cyst.", "Kidneys", abnormal=True),
             U("Free fluid.", "General", abnormal=True),
             U("Conclusion.", "Conclusion", heading=True),
             U("Liver and kidneys unremarkable.", "Kidneys",
               parts=[P("Kidneys unremarkable.", "Kidneys"), P("Liver unremarkable.", "Liver")]),
             U("Bones fine.", "Bones"),
             U("Gallstones.", "Liver", abnormal=True),
             U("No ascites.", "General")]
    b = findings_block(units, R, {}, "", ["Normal spleen."])
    assert b.split("\n\n") == [
        "Liver: Gallstones.\nKidneys: Kidney cyst.\nBones: Bones fine.\nLiver · Kidneys: Liver and kidneys unremarkable."
        "\nFree fluid.\nNo ascites.\nOdd sentence.",
        "DO NOT ASSERT (removed by the radiologist): Normal spleen."]


def test_a_region_reported_only_inside_a_split_sentence_takes_its_normals_inline():
    units = [U("Liver and kidneys unremarkable.", "Kidneys",
               parts=[P("Kidneys unremarkable.", "Kidneys"), P("Liver unremarkable.", "Liver")])]
    b = findings_block(units, R, {"Liver": ["No biliary dilatation."]}, "", [])
    assert b == f"Liver: {A} No biliary dilatation.\nLiver · Kidneys: Liver and kidneys unremarkable."


def test_region_states_and_confirmed_assumed_as_the_scratchpad():
    units = [U("Gallstones.", "Liver", abnormal=True), U("Solid organs normal.", "General", covers=["Spleen"])]
    pills = ["Liver", "Kidneys", "Spleen"]
    abnormal, dictated_normal, untouched = region_states(units, pills)
    assert (abnormal, dictated_normal, untouched) == (["Liver"], ["Spleen"], ["Kidneys"])
    got = confirmed_assumed({"Kidneys": ["Normal kidneys.", "No hydronephrosis"], "Liver": ["No biliary dilatation."],
                             "Spleen": ["Normal spleen."], "Other findings": ["x"]},
                            abnormal, untouched, ["no hydronephrosis."])
    assert got == {"Liver": ["No biliary dilatation."], "Kidneys": ["Normal kidneys."]}


SHEET = """# Skill Sheet: CT

## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Liver (FINDINGS)
COVERS ["liver"]
NORMAL [liver] "The liver is normal."
NEGATIVE "No biliary dilatation."
"""


def test_region_text_is_each_findings_regions_own_sentences():
    units = [U("CT with contrast.", "Technique"), U("Normal study.", "General"), U("No acute abnormality.", "Conclusion"),
             U("Liver cyst.", "Liver", abnormal=True), U("Unplaced.", None), U("Liver:", "Liver", heading=True),
             U("Fatty liver and normal kidneys.", "Liver",
               parts=[P("Fatty liver", "Liver", True), P("normal kidneys.", "Kidneys")]),
             U("No hydronephrosis.", "Kidneys")]
    assert region_text(units) == {"Liver": "Liver cyst. Fatty liver", "Kidneys": "normal kidneys. No hydronephrosis."}
    assert region_text([U("normal", "General")]) == {}


async def test_preview_report_wires_the_scratchpad_path(monkeypatch):
    from rapid_reports_ai.hybrid_stack import normals, service
    from rapid_reports_ai import template_manager
    seen = {}

    async def fake_group(scan_type, text, regions, previous):
        seen["regions"] = [r.name for r in regions]
        return NS(units=[U("Gallstones.", regions[0].name, abnormal=True), U("Appendicitis.", "Conclusion")])

    async def fake_assumed(dictation, region_normals, abnormal, dictated_normal, removed, owned=None, touched=None,
                           suppressions=None, clinical_history="", labels=None, region_text=None):
        seen.update(normals=region_normals, abnormal=abnormal, dictated_normal=dictated_normal, removed=removed,
                    history=clinical_history, labels=labels, region_text=region_text)
        return NS(assumed={r: list(s) for r, s in region_normals.items()}, dropped={}, error=None)

    class FakeTM:
        async def generate_report_from_config(self, cfg, inputs, sig, stack=None):
            seen.update(cfg=cfg, inputs=inputs, stack=stack)
            return {"report_content": "REPORT", "model_used": "m"}

    monkeypatch.setattr(service, "group_update", fake_group)
    monkeypatch.setattr(normals, "assumed", fake_assumed)
    monkeypatch.setattr(template_manager, "TemplateManager", FakeTM)
    from rapid_reports_ai.template_sheet_grammar import parse_sheet
    assert parse_sheet(SHEET, mode="template").structure.usable
    out = await template_preview.preview_report(SHEET, "CT", "Pain.", "Gallstones. Appendicitis.", declined=["x."])
    assert out["usable"] and out["report_content"] == "REPORT"
    liver = seen["regions"][0]
    assert seen["abnormal"] == [liver] and seen["dictated_normal"] == [] and seen["history"] == "Pain."
    assert seen["removed"] == ["x."] and seen["region_text"] == {liver: "Gallstones."}
    assert out["findings_block"].startswith(f"{liver}: Gallstones. {A} ")
    assert out["findings_block"].endswith("DO NOT ASSERT (removed by the radiologist): x.")
    assert "Conclusion (confirmed by the radiologist): Appendicitis." in out["findings_block"]
    assert seen["inputs"] == {"FINDINGS": out["findings_block"], "CLINICAL_HISTORY": "Pain."}
    assert seen["stack"] == {"conclusion": "Appendicitis.", "declined": ["x."]}
    assert seen["cfg"]["skill_sheet"] == SHEET and seen["cfg"]["generation_mode"] == "skill_sheet_guided"


async def test_preview_report_unusable_sheet():
    assert (await template_preview.preview_report("nonsense", "CT", "", "x"))["usable"] is False


@pytest.fixture
def authed(client, db_session):
    u = User(id=uuid.uuid4(), email="rad@nhs.net", password_hash="x", full_name="T",
             is_active=True, is_verified=True, is_approved=True)
    db_session.add(u)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: u
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_test_generate_endpoint_uses_the_preview(authed, monkeypatch):
    client = authed
    calls = {}

    async def fake_preview(sheet, scan_type, history, dictation, conclusion="", declined=None):
        calls["args"] = (sheet, scan_type, history, dictation)
        return {"usable": True, "report_content": "R", "model_used": "m"}

    monkeypatch.setattr(template_preview, "preview_report", fake_preview)
    r = client.post("/api/templates/skill-sheet/test-generate",
                    json={"skill_sheet": "S", "scan_type": "CT", "clinical_history": "H", "findings_input": "F"})
    assert r.json() == {"success": True, "report_content": "R", "model_used": "m"}
    assert calls["args"] == ("S", "CT", "H", "F")

    async def unusable(*a, **k):
        return {"usable": False}

    monkeypatch.setattr(template_preview, "preview_report", unusable)
    r = client.post("/api/templates/skill-sheet/test-generate",
                    json={"skill_sheet": "S", "scan_type": "CT", "clinical_history": "H", "findings_input": "F"})
    assert r.json()["success"] is False
