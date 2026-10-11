from pathlib import Path

import pytest

from rapid_reports_ai.database.models import StackSchemaFamily
from rapid_reports_ai.hybrid_stack import service as S
from rapid_reports_ai.hybrid_stack.grouper import Placement
from rapid_reports_ai.hybrid_stack.reconciler import Reconciled
from rapid_reports_ai.hybrid_stack.schemas import OTHER, Region, family_regions
from rapid_reports_ai.hybrid_stack.units import StackUnit
from rapid_reports_ai.template_sheet_grammar import parse_sheet

CMR = Path(__file__).parent / "fixtures" / "template_pipeline" / "lean_cmr.md"


@pytest.fixture
def fakes(monkeypatch):
    calls = {"family": 0, "reconcile": 0}

    async def fam(scan_type, history, transport=None):
        calls["family"] += 1
        return ("knee", 0.9)

    async def rec(scan_type, history, transport=None):
        calls["reconcile"] += 1
        return Reconciled(regions=[Region(name="Tendons", includes="t"), Region(name=OTHER, includes="o")],
                          log={"new": ["Tendons"]})
    monkeypatch.setattr(S, "choose_family", fam)
    monkeypatch.setattr(S, "reconcile", rec)
    return calls


async def test_first_time_reconciles_caches_provisional_then_reads_cache(db_session, fakes):
    a = await S.resolve_schema("MRI  Ankle", "", None, db_session)
    assert a.source == "reconciled" and a.provisional and a.regions[0].name == "Tendons"
    b = await S.resolve_schema("mri ankle", "", None, db_session)
    assert b.regions == a.regions and fakes["reconcile"] == 1
    assert db_session.get(StackSchemaFamily, "mri ankle").status == "provisional"


async def test_reconciler_keeping_a_family_is_also_provisional(db_session, monkeypatch, fakes):
    # Picking an existing family is a model decision too: it is used at once but goes to review.
    async def keep(scan_type, history, transport=None):
        return Reconciled(regions=family_regions("knee"), family="knee", log={"family": "knee"})
    monkeypatch.setattr(S, "reconcile", keep)
    r = await S.resolve_schema("MRI knee", "", None, db_session)
    assert r.family == "knee" and r.provisional and r.source == "reconciled"
    row = db_session.get(StackSchemaFamily, "mri knee")
    assert row.status == "provisional" and row.source == "reconciler:family:knee"


async def test_reconciler_failure_uses_jev_family_and_caches_nothing(db_session, monkeypatch, fakes):
    async def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(S, "reconcile", boom)
    r = await S.resolve_schema("MRI knee", "", None, db_session)
    assert r.source == "family" and r.family == "knee"
    assert db_session.get(StackSchemaFamily, "mri knee") is None


async def test_rejected_row_uses_jev_family(db_session, fakes):
    db_session.add(StackSchemaFamily(key="mri ankle", scan_type="MRI ankle", regions=[], source="admin",
                                     status="rejected"))
    db_session.commit()
    r = await S.resolve_schema("MRI ankle", "", None, db_session)
    assert r.source == "family" and fakes["reconcile"] == 0


async def test_template_structure_wins(db_session, fakes):
    st = parse_sheet(CMR.read_text(), mode="template").structure
    r = await S.resolve_schema("Cardiac MRI", "", st, db_session)
    assert r.source == "template" and r.regions[0].name == "Left Ventricle" and fakes["family"] == 0


async def test_group_update_places_new_sentences_and_derives_pills(monkeypatch):
    async def place(scan_type, regions, units, new_ids, transport=None):
        return [Placement(id=i, group="Liver", structure="liver", covers=["Liver"]) for i in new_ids], "m", None

    async def no_gate(units, new_ids, transport=None):
        return []
    monkeypatch.setattr(S, "place", place)
    monkeypatch.setattr(S, "conclusion_gate", no_gate)
    regions = [Region(name="Liver", includes="l"), Region(name=OTHER, includes="o")]
    res = await S.group_update("CT", "Liver normal. Liver cyst.", regions, [])
    assert [u.group for u in res.units] == ["Liver", "Liver"] and res.pills == ["Liver"]
    assert res.new_ids == [0, 1] and "grouper" in res.timings_ms


async def test_group_update_with_nothing_new_makes_no_call(monkeypatch):
    async def place(*a, **k):
        raise AssertionError("no call expected")
    monkeypatch.setattr(S, "place", place)
    regions = [Region(name="Liver", includes="l")]
    prev = [StackUnit(id=0, text="Liver normal.", group="Liver", covers=["Liver"])]
    res = await S.group_update("CT", "Liver normal.", regions, prev)
    assert res.new_ids == [] and res.pills == ["Liver"]
