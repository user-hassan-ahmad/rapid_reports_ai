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
                            abnormal, untouched, ["no hydronephrosis."], dictated_normal)
    # review R2: a dictated-normal region keeps the sentences the check did not find said
    assert got == {"Liver": ["No biliary dilatation."], "Spleen": ["Normal spleen."], "Kidneys": ["Normal kidneys."]}


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

    async def fake_assumed(dictation, region_normals, abnormal, removed, owned=None,
                           suppressions=None, clinical_history="", labels=None, region_text=None, rules=None,
                           confirm=False, scan_type=""):
        seen.update(normals=region_normals, abnormal=abnormal, removed=removed, assumed_scan=scan_type,
                    history=clinical_history, labels=labels, region_text=region_text, rules=rules, confirm=confirm)
        return NS(assumed={r: list(s) for r, s in region_normals.items()}, flagged={}, dropped={}, error=None)

    async def fake_lean(*, sheet, scan_type, findings, history, case, signature, declined=(), stack=None):
        seen.update(sheet=sheet, scan=scan_type, inputs={"FINDINGS": findings, "CLINICAL_HISTORY": history},
                    stack=stack, case=case, signature=signature, declined=declined)
        return {"report_content": "REPORT", "model_used": "m"}

    from rapid_reports_ai import template_lean
    monkeypatch.setattr(service, "group_update", fake_group)
    monkeypatch.setattr(normals, "assumed", fake_assumed)
    monkeypatch.setattr(template_lean, "generate_template_report_lean", fake_lean)
    from rapid_reports_ai.template_sheet_grammar import parse_sheet
    assert parse_sheet(SHEET, mode="template").structure.usable
    out = await template_preview.preview_report(SHEET, "CT", "Pain.", "Gallstones. Appendicitis.", declined=["x."])
    assert out["usable"] and out["report_content"] == "REPORT"
    liver = seen["regions"][0]
    assert seen["abnormal"] == [liver] and seen["history"] == "Pain."
    assert seen["removed"] == ["x."] and seen["region_text"] == {liver: "Gallstones."}
    assert seen["rules"] is None and seen["confirm"] is True   # one shot: decided now, as at Confirm (review R5)
    assert seen["assumed_scan"] == "CT"   # seam 21: the rules are decided on the scan type, as at Generate
    assert out["findings_block"].startswith(f"{liver}: Gallstones. {A} ")
    assert out["findings_block"].endswith("DO NOT ASSERT (removed by the radiologist): x.")
    assert "Conclusion (confirmed by the radiologist): Appendicitis." in out["findings_block"]
    assert seen["inputs"] == {"FINDINGS": out["findings_block"], "CLINICAL_HISTORY": "Pain."}
    assert seen["stack"] == {"conclusion": "Appendicitis.", "declined": ["x."]}
    # the scratchpad's own Generate path (context rules, required values, slot strip, check), not the bare generator
    assert seen["sheet"] == SHEET and seen["scan"] == "CT" and seen["case"] is None and seen["signature"] is None
    assert seen["declined"] == ["x."]


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
        return {"usable": True, "report_content": "R", "model_used": "m", "review": [{"kind": "value_missing"}]}

    monkeypatch.setattr(template_preview, "preview_report", fake_preview)
    r = client.post("/api/templates/skill-sheet/test-generate",
                    json={"skill_sheet": "S", "scan_type": "CT", "clinical_history": "H", "findings_input": "F"})
    assert r.json() == {"success": True, "report_content": "R", "model_used": "m", "review": [{"kind": "value_missing"}]}
    assert calls["args"] == ("S", "CT", "H", "F")

    async def unusable(*a, **k):
        return {"usable": False}

    monkeypatch.setattr(template_preview, "preview_report", unusable)
    r = client.post("/api/templates/skill-sheet/test-generate",
                    json={"skill_sheet": "S", "scan_type": "CT", "clinical_history": "H", "findings_input": "F"})
    assert r.json()["success"] is False


async def test_preview_report_surfaces_the_generate_paths_review_flags_once(monkeypatch):
    """The number check runs once, inside the Generate path; the preview returns its flags (number_flags) and every
    review flag the path raised (value_missing included) for the Test step."""
    from rapid_reports_ai.hybrid_stack import normals, service
    from rapid_reports_ai import template_lean, template_number_check

    async def fake_group(scan_type, text, regions, previous):
        return NS(units=[U("Gallstones 12 mm.", regions[0].name, abnormal=True), U("Cholelithiasis.", "Conclusion")])

    async def fake_assumed(dictation, region_normals, abnormal, removed, **kw):
        return NS(assumed={}, flagged={}, dropped={}, error=None)

    number = {"kind": "undictated_number", "text": "23 mm", "sentence": "A 23 mm cyst."}
    missing = {"kind": "value_missing", "text": "RVEF", "message": "Required value RVEF not found in the report"}

    async def fake_lean(**kw):
        return {"report_content": "Gallstones 12 mm. A 23 mm cyst.", "model_used": "m",
                "quality_check": {"enabled": True, "review": [number, missing]}}

    def never(*a, **k):
        raise AssertionError("the number check already ran in the Generate path")

    monkeypatch.setattr(service, "group_update", fake_group)
    monkeypatch.setattr(normals, "assumed", fake_assumed)
    monkeypatch.setattr(template_lean, "generate_template_report_lean", fake_lean)
    monkeypatch.setattr(template_number_check, "undictated_numbers", never)
    out = await template_preview.preview_report(SHEET, "CT", "Pain.", "Gallstones 12 mm. Cholelithiasis.")
    assert out["number_flags"] == [number] and out["review"] == [number, missing]

    async def unchecked(**kw):
        return {"report_content": "R", "model_used": "m", "quality_check": None}
    monkeypatch.setattr(template_lean, "generate_template_report_lean", unchecked)
    out = await template_preview.preview_report(SHEET, "CT", "Pain.", "Gallstones 12 mm. Cholelithiasis.")
    assert out["number_flags"] == [] and out["review"] == []


_RULED = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Brain (FINDINGS)
COVERS ["brain"]
NEGATIVE "No other interval changes compared with the previous MRI."
NORMAL [ventricles] "The ventricles are normal in size."
RULE WHEN [context: no previous study is available] SUPPRESS "No other interval changes compared with the previous MRI."
"""


async def test_preview_with_empty_findings_hides_a_suppressed_sentence(monkeypatch):
    # review R5: the Test run decides the context rules from the history, empty findings included
    from rapid_reports_ai.hybrid_stack import normals, service
    from rapid_reports_ai import template_lean
    seen = {"conds": []}

    async def fake_group(scan_type, text, regions, previous):
        return NS(units=[])

    async def never(*a, **k):
        raise AssertionError("no per-sentence check for empty findings")

    async def conds(state, conditions):
        seen["conds"].append((state, list(conditions)))
        return [0.9 for _ in conditions]

    async def fake_lean(**kw):
        seen["findings"] = kw["findings"]
        return {"report_content": "REPORT", "model_used": "m"}

    monkeypatch.setattr(service, "group_update", fake_group)
    monkeypatch.setattr(normals, "ask_rows", never)
    monkeypatch.setattr(normals, "ask_conditions", conds)
    monkeypatch.setattr(template_lean, "generate_template_report_lean", fake_lean)
    out = await template_preview.preview_report(_RULED, "MRI head", "First MRI. No previous imaging.", "")
    assert out["usable"] and out["assumed_error"] is None
    # seam 21: the session decision is condition_state's, on the scan type and the history, nothing dictated
    assert seen["conds"] == [("SCAN TYPE:\nMRI head\nCLINICAL HISTORY:\nFirst MRI. No previous imaging.\n"
                              "DICTATED FINDINGS:\n", ["no previous study is available"])]
    assert "compared with the previous MRI" not in out["findings_block"]
    assert "The ventricles are normal in size." in out["findings_block"]
    assert {"sentence": "No other interval changes compared with the previous MRI.", "reason": "rule"} in \
        sum(out["dropped"].values(), [])


def test_region_text_adds_a_collective_normal_to_every_region_it_covers():
    # review round 1: a region dictated normal by a collective sentence has that sentence as its text
    units = [U("Solid organs unremarkable.", "General", covers=["Spleen", "Pancreas"]),
             U("Liver, spleen and pancreas normal.", "Liver", covers=["Liver", "Spleen", "Pancreas"]),
             U("A splenic cyst.", "Spleen", abnormal=True, covers=["Kidneys"]),
             U("Kidneys:", "Kidneys", heading=True, covers=["Kidneys"])]
    assert region_text(units) == {
        "Liver": "Liver, spleen and pancreas normal.",
        "Spleen": "A splenic cyst. Solid organs unremarkable. Liver, spleen and pancreas normal.",
        "Pancreas": "Solid organs unremarkable. Liver, spleen and pancreas normal."}


_SOLID = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Liver (FINDINGS)
COVERS ["liver"]
NORMAL [liver] "The liver is normal."

## Paragraph: Spleen (FINDINGS)
COVERS ["spleen"]
NORMAL [spleen] "The spleen is normal in size."
"""


async def test_preview_a_collective_dictated_normal_covers_its_regions_sheet_sentence(monkeypatch):
    # through the Jev path: a text-sensitive fake covers the spleen sentence only when the spleen's text says so
    from rapid_reports_ai.hybrid_stack import jev_stack as J, normals, service
    from rapid_reports_ai import template_lean
    said = "Solid organs unremarkable."

    async def fake_group(scan_type, text, regions, previous):
        spleen = next(r.name for r in regions if "pleen" in r.name)
        return NS(units=[U("Gallstones.", regions[0].name, abnormal=True), U(said, "General", covers=[spleen])])

    async def rows(dictation, sentences, removed, *, stated=True, contra=True, hedge=None):
        return [J.RowCheck(0.95 if stated and said in dictation and "spleen" in s.lower() else 0.0, 0.0, 0.0)
                for s in sentences]

    async def fake_lean(**kw):
        return {"report_content": "REPORT", "model_used": "m"}

    monkeypatch.setattr(service, "group_update", fake_group)
    monkeypatch.setattr(normals, "ask_rows", rows)
    monkeypatch.setattr(template_lean, "generate_template_report_lean", fake_lean)
    out = await template_preview.preview_report(_SOLID, "CT", "Pain.", f"Gallstones. {said}")
    assert out["usable"] and out["assumed_error"] is None
    assert "The spleen is normal in size." not in out["findings_block"]
    assert {"sentence": "The spleen is normal in size.", "reason": "covered"} in sum(out["dropped"].values(), [])

