import importlib.util
from pathlib import Path

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library.pack_preview import Drafted, Settlement
from rapid_reports_ai.hybrid_stack.copilot.library.schema import InputValue

spec = importlib.util.spec_from_file_location(
    "real_lab", Path(__file__).resolve().parents[1] / "scripts" / "guidelines" / "real_lab.py")
RL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RL)


def _label(**inputs):
    return {"inputs": {k: {"stated": v is not None, "value": v, "quote": "", "locator": "", "assumed": a,
                           "boundary": False, "note": ""} for k, (v, a) in inputs.items()},
            "lesions": [], "category": None, "served_by": "claude-opus-5-5 subagent"}


def test_sampling_caps_each_pack_and_the_total():
    cards = [{"pack": p, "id": f"{p}{n}"} for p in ("a", "b") for n in range(50)]
    got = RL.sample_cards(cards, per_pack=30, total=40)
    assert len(got) == 40 and max(sum(c["pack"] == p for c in got) for p in ("a", "b")) <= 30
    assert got == RL.sample_cards(cards, per_pack=30, total=40)          # seeded: the same sample every run


def test_an_inferred_value_is_wrong_and_a_stated_one_is_ok(toy_entry):
    s = Settlement(values={"kind": Drafted(InputValue(value="solid"), "solid", "read"), "risk": Drafted(InputValue(value="high"), "x", "read")})
    v = RL.verdicts(toy_entry, s, _label(kind=("solid", None), size=("7", None), risk=(None, "low"),
                                         margin=(None, None)))
    assert v == {"kind": "ok", "risk": "wrong", "size": "asked", "margin": "asked"}


def test_taps_count_answers_and_corrections_never_the_calculate_tap(toy_entry):
    s = Settlement(values={"kind": Drafted(InputValue(value="subsolid"), "subsolid", "read")})       # wrong: truth is solid
    n, outcome = RL.taps(toy_entry, s, _label(kind=("solid", None), size=("7", None), risk=(None, "high"),
                                              margin=(None, None)), patient={})
    assert (n, outcome) == (3, "ct6")          # correct kind, answer size, answer risk (assumed)


def test_a_wrong_draft_is_cleared_before_the_engine_runs_and_the_original_is_untouched(toy_entry):
    s = Settlement(values={"kind": Drafted(InputValue(value="subsolid"), "subsolid", "read")})
    lab = _label(kind=(None, None), size=("7", None), risk=(None, "high"), margin=(None, None))  # kind inferred
    seen = []
    real = RL.finish
    RL.finish = lambda e, st, answered, patient=None, **kw: (seen.append(dict(st.values)), real(e, st, answered, patient))[1]
    try:
        RL.taps(toy_entry, s, lab, patient={})
    finally:
        RL.finish = real
    assert seen and all("kind" not in v for v in seen)           # the wrong value never reached the engine
    assert "kind" in s.values                                     # the caller's settlement is not mutated


def _lib_with(toy_entry):
    class Lib:
        def lookup(self, key):
            return toy_entry if key in (toy_entry.key, toy_entry.id) else None
    return Lib()


CARDS = [{"id": "c1", "pack": "toy-nodule", "finding": "7 mm solid nodule.", "findings": "7 mm solid nodule.",
          "clinical_history": "Smoker."}]
ONE = {"inputs": [{"input": "kind", "stated": True, "value": "solid", "quote": "solid", "locator": "S1 p2",
                   "assumed": None, "boundary": False, "note": ""}], "lesions": [], "category": None}


def test_the_brief_names_every_source_folder_the_schema_and_never_the_settler(toy_entry, tmp_path):
    b = RL.write_brief(_lib_with(toy_entry), CARDS, tmp_path / "cards_1.json", tmp_path / "labels_1.json")
    assert "guidelines/toy-nodule/sources/" in b and "guidelines/toy-nodule/entry.json" in b
    assert str(tmp_path / "labels_1.json") in b and '"served_by"' in b       # the output path and the schema
    assert "settler" not in b.lower()


def test_labels_load_when_every_card_is_labelled(toy_entry):
    got, problems = RL.load_labels(_lib_with(toy_entry), CARDS,
                                   {"served_by": "claude-opus-5-5 subagent a1", "labels": {"c1": ONE}})
    assert problems == [] and got["c1"]["served_by"] == "claude-opus-5-5 subagent a1"
    assert got["c1"]["inputs"]["kind"]["value"] == "solid" and got["c1"]["inputs"]["size"]["stated"] is False


@pytest.mark.parametrize("raw,problem", [
    ({"labels": {"c1": ONE}}, "served_by"),
    ({"served_by": "x", "labels": {}}, "c1 is not labelled"),
    ({"served_by": "x", "labels": {"c1": {"inputs": [{"input": "kind"}]}}}, "c1: schema"),
    ({"served_by": "x", "labels": {"c1": ONE, "c9": ONE}}, "c9 is not a card"),
])
def test_a_bad_label_file_is_refused_with_its_problem(toy_entry, raw, problem):
    got, problems = RL.load_labels(_lib_with(toy_entry), CARDS, raw)
    assert any(problem in p for p in problems)


def test_a_label_value_the_pack_cannot_take_becomes_a_boundary_item(toy_entry):
    raw = {"inputs": [{"input": "kind", "stated": True, "value": "cystic", "quote": "q", "locator": "S1 p2",
                       "assumed": None, "boundary": False, "note": ""}], "lesions": [], "category": None}
    got = RL.parse_label(toy_entry, raw, "claude-opus-5-5 subagent")
    assert got["inputs"]["kind"]["boundary"] is True and "size" in got["inputs"]     # missing inputs: not stated


def test_spot_rows_list_flagged_and_disagreeing_items_only(toy_entry):
    s = Settlement(values={"kind": Drafted(InputValue(value="solid"), "solid", "read"), "size": Drafted(InputValue(value=8.0), "8 mm", "read")})
    lab = _label(kind=("solid", None), size=("7", None), risk=(None, "low"), margin=(None, None))
    lab["inputs"]["risk"]["boundary"] = True
    rows = RL.spot_rows(toy_entry, {"id": "c1", "pack": "toy-nodule"}, s, lab)
    assert sorted(r["input"] for r in rows) == ["risk", "size"]
    assert set(rows[0]) >= {"case", "pack", "input", "label_value", "label_quote", "locator", "settler_value",
                            "settler_tier", "settler_quote", "hassan_value", "hassan_note"}


def test_metrics_report_what_hassan_decides_on():
    rows = [{"card": "c1", "pack": "p", "taps": 1, "verdicts": {"a": "ok"}, "tiers": {"a": "read"}, "degraded": False},
            {"card": "c2", "pack": "p", "taps": 3, "verdicts": {"a": "wrong", "b": "wrong"},
             "tiers": {"a": "prefilled", "b": "read"}, "degraded": True}]
    m = RL.metrics(rows)
    assert m["wrong_read"] == ["c2:b"] and m["median_taps"] == 2 and m["taps_distribution"] == {1: 1, 3: 1}
    assert m["prefill_error"] == {"p.a": {"wrong": 1, "prefilled": 1, "rate": 1.0}} and m["degraded"] == ["c2"]
    assert "pass" not in m and "gate" not in m                   # measured and reported; Hassan decides


def test_outcome_agreement_counts_and_names_the_disagreeing_cards():
    rows = [{"card": "c1", "outcome": "ct6", "draft_outcome": "ct6"},
            {"card": "c2", "outcome": "ct6", "draft_outcome": "ct4"},
            {"card": "c3", "outcome": "ct4", "draft_outcome": None},
            {"card": "c4", "outcome": None, "draft_outcome": None}]
    assert RL.outcome_agreement(rows) == {"agree": 1, "disagree": 1, "none": 2, "disagreeing_cards": ["c2"]}


def test_wrong_prefill_total_counts_wrong_prefilled_values_only():
    rows = [{"card": "c1", "verdicts": {"a": "wrong", "b": "wrong", "c": "ok"},
             "tiers": {"a": "prefilled", "b": "read", "c": "prefilled"}}]
    assert RL.wrong_prefill_total(rows) == 1


def test_the_brief_paths_are_absolute(toy_entry, tmp_path):
    b = RL.write_brief(_lib_with(toy_entry), CARDS, tmp_path / "c.json", tmp_path / "l.json")
    for name in ("entry.json", "manifest.json", "sources/"):
        assert f"{RL.GUIDELINES}/toy-nodule/{name}" in b
    assert RL.GUIDELINES.is_absolute()


def test_overrides_are_validated_against_the_pack_and_bad_ones_skipped(toy_entry, tmp_path):
    labels = {"c1": RL.parse_label(toy_entry, ONE, "x")}
    sheet = tmp_path / "s.csv"
    sheet.write_text("case,input,hassan_value\nc1,kind,subsolid\nc1,kind,cystic\nc1,size,none\n")
    n, problems = RL._apply_overrides(_lib_with(toy_entry), CARDS, labels, sheet)
    assert n == 2 and labels["c1"]["inputs"]["kind"]["value"] == "subsolid"     # the bad 'cystic' was not applied
    assert len(problems) == 1 and "cystic" in problems[0]


def test_run_records_a_failing_card_by_type_and_carries_on(toy_entry, tmp_path, monkeypatch):
    import asyncio
    import json

    async def boom(*a, **k):
        raise RuntimeError("clinical text must not leak")
    monkeypatch.setattr(RL, "_lib", lambda: _lib_with(toy_entry))
    monkeypatch.setattr(RL, "settle_pack", boom)
    cp = tmp_path / "cards.json"
    cp.write_text(json.dumps(CARDS))
    out = asyncio.run(RL.run(cp, tmp_path))
    assert json.loads(out.read_text()) == [{"card": "c1", "error": "RuntimeError"}]


def test_run_records_the_draft_outcome_now_that_packs_never_propose(toy_entry, tmp_path, monkeypatch):
    """Preflight row 11: proposal is None for every pack card; run records draft_outcome, so the lab keeps measuring."""
    import asyncio
    import json

    async def settle(e, findings, history, finding=""):
        return Settlement(values={"kind": Drafted(InputValue(value="solid"), "solid", "read"),
                                  "size": Drafted(InputValue(value=7.0), "7 mm", "read"),
                                  "risk": Drafted(InputValue(value="high"), "Smoker", "prefilled", ["why"])})
    monkeypatch.setattr(RL, "_lib", lambda: _lib_with(toy_entry))
    monkeypatch.setattr(RL, "settle_pack", settle)
    cp = tmp_path / "cards.json"
    cp.write_text(json.dumps(CARDS))
    rec = json.loads(asyncio.run(RL.run(cp, tmp_path)).read_text())[0]
    assert rec["draft_outcome"]["recommendation"] == "CT at 6 months" and rec["draft_outcome_id"] == "ct6"
    assert rec["drafts"]["risk"]["tier"] == "prefilled" and rec["drafts"]["risk"]["why"] == ["why"]
    assert RL._settlement(rec).values["risk"] == Drafted(InputValue(value="high"), "Smoker", "prefilled", ["why"])


def _export(ids):
    return {"data": {"cols": [{"name": n} for n in ("id", "scan_type", "clinical_history", "findings")],
                     "rows": [[i, "CT", "h", f"text {i}"] for i in ids]}}


def _card(case):
    return {"id": f"{case}:f1:p", "case": case, "pack": "p"}


def test_cases_file_keeps_only_listed_ids_in_file_order(tmp_path, monkeypatch, capsys):
    import asyncio
    import json
    seen = []

    async def fake(case, sem):
        seen.append(case["id"])
        return [_card(case["id"])]
    monkeypatch.setattr(RL, "_cards_for", fake)
    src, sel = tmp_path / "e.json", tmp_path / "s.json"
    src.write_text(json.dumps(_export(["a", "b", "c", "d"])))
    sel.write_text(json.dumps({"selected": [{"id": "c"}, {"id": "a"}, {"id": "zz"}]}))
    out = asyncio.run(RL.group(src, tmp_path / "o", max_cases=1, cases_file=sel))
    assert sorted(seen) == ["a", "c"]
    assert {c["case"] for c in json.loads(out.read_text())} == {"a", "c"}
    assert "1 selected ids not in the export" in capsys.readouterr().err
    assert [c["id"] for c in RL.select_cases(RL.cases_from_export(_export(["a", "b", "c"])), json.loads(sel.read_text()))] == ["c", "a"]


def test_checkpoint_is_written_per_case_and_resume_skips_done_and_retries_errored(tmp_path, monkeypatch):
    import asyncio
    import json

    async def first(case, sem):
        if case["id"] == "b":
            raise RuntimeError("clinical text must not leak")
        return [_card(case["id"])]
    monkeypatch.setattr(RL, "_cards_for", first)
    src = tmp_path / "e.json"
    src.write_text(json.dumps(_export(["a", "b"])))
    sel = tmp_path / "s.json"
    sel.write_text(json.dumps({"selected": [{"id": "a"}, {"id": "b"}]}))
    asyncio.run(RL.group(src, tmp_path / "o1", cases_file=sel))
    ck = next((tmp_path / "o1").glob("group_cases_*.jsonl"))
    recs = [json.loads(line) for line in ck.read_text().splitlines()]
    assert {"case": "a", "cards": [_card("a")]} in recs
    assert {"case": "b", "error": "RuntimeError"} in recs
    assert "leak" not in ck.read_text()

    ran = []

    async def second(case, sem):
        ran.append(case["id"])
        return [_card(case["id"])]
    monkeypatch.setattr(RL, "_cards_for", second)
    out = asyncio.run(RL.group(src, tmp_path / "o2", cases_file=sel, resume=ck))
    assert ran == ["b"]
    assert {c["case"] for c in json.loads(out.read_text())} == {"a", "b"}
    ck2 = next((tmp_path / "o2").glob("group_cases_*.jsonl"))
    recs2 = [json.loads(line) for line in ck2.read_text().splitlines()]
    assert {r["case"] for r in recs2} == {"a", "b"} and all("cards" in r for r in recs2)


def test_resume_survives_a_truncated_last_line_and_retries_that_case(tmp_path, monkeypatch, capsys):
    import asyncio
    import json
    ck = tmp_path / "ck.jsonl"
    ck.write_text(json.dumps({"case": "a", "cards": [_card("a")]}) + "\n" + '{"case": "b", "car')
    assert RL._read_checkpoint(ck) == {"a": [_card("a")]}
    assert "1 unreadable checkpoint lines skipped" in capsys.readouterr().err


def test_append_stamps_source_and_prefixes_ids_and_checkpoints(tmp_path, monkeypatch):
    import asyncio
    import json
    seen = []

    async def fake(case, sem):
        seen.append((case["id"], case["source"]))
        return [{**_card(case["id"]), "source": case["source"]}]
    monkeypatch.setattr(RL, "_cards_for", fake)
    src, base = tmp_path / "c.json", tmp_path / "cards.json"
    src.write_text(json.dumps([{"id": "1"}, {"id": "synthetic-2"}]))
    base.write_text("[]")
    out = asyncio.run(RL.hassan(src, base, tmp_path / "o1", source="synthetic"))
    assert sorted(seen) == [("synthetic-1", "synthetic"), ("synthetic-2", "synthetic")]
    assert {c["source"] for c in json.loads(out.read_text())} == {"synthetic"}
    ck = next((tmp_path / "o1").glob("group_cases_*.jsonl"))
    seen.clear()
    asyncio.run(RL.hassan(src, base, tmp_path / "o2", source="synthetic", resume=ck))
    assert seen == []                                                    # resumed: nothing rerun
    assert [c["id"] for c in RL.tag_cases([{"id": "x"}], "hassan")] == ["h-x"]
    assert [c["id"] for c in RL.tag_cases([{"id": "h-x"}], "hassan")] == ["h-x"]


def test_metrics_split_by_source_and_synthetic_never_joins_the_combined_view():
    def r(card, source, taps, verdict):
        return {"card": card, "pack": "p", "source": source, "taps": taps, "verdicts": {"k": verdict},
                "tiers": {"k": "read"}, "outcome": "o", "draft_outcome": "o"}
    rows = [r("a", "prod", 1, "ok"), r("b", "hassan", 2, "wrong"), r("c", "synthetic", 9, "wrong")]
    got = RL.by_source(rows)
    assert set(got) == {"prod", "hassan", "synthetic", "prod+hassan"}
    assert got["prod"]["cards"] == 1 and got["prod"]["wrong_read"] == []
    assert got["synthetic"]["wrong_read"] == ["c:k"]
    assert got["prod+hassan"]["cards"] == 2 and got["prod+hassan"]["wrong_read"] == ["b:k"]
    assert set(RL.by_source([r("a", "prod", 1, "ok")])) == {"prod"}


def test_headline_excludes_synthetic_and_card_kinds_split_hits_from_siblings():
    rows = [{"source": "prod", "sibling": False}, {"source": "prod", "sibling": True},
            {"source": "hassan", "sibling": False}, {"source": "synthetic", "sibling": False}]
    assert [r["source"] for r in RL.headline_rows(rows)] == ["prod", "prod", "hassan"]
    assert RL.headline_rows([rows[3]]) == []
    assert RL.card_kinds(rows) == {"hassan": {"hit": 1, "sibling": 0}, "prod": {"hit": 1, "sibling": 1},
                                   "synthetic": {"hit": 1, "sibling": 0}}


def _lab_lib():
    import copy

    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L

    from .conftest import TOY_ENTRY, TOY_REFERENCE

    def e(base, id_, topic, **kw):
        d = copy.deepcopy(base)
        d.update(id=id_, topic=topic, display=f"{id_} 2020", system=f"{id_} system", aliases=[], **kw)
        return d
    ents = [e(TOY_ENTRY, "nod-a", "nodule"), e(TOY_ENTRY, "nod-b", "nodule"), e(TOY_REFERENCE, "nod-r", "nodule"),
            e(TOY_ENTRY, "ex", "ex", trigger=["exam"], exam="a study")]
    return L.Library({"version": "v", "entries": {f"{d['id']}@{d['version']}": {"entry": d} for d in ents}})


def test_cards_for_runs_the_live_library_path_through_the_shared_builder(monkeypatch):
    import asyncio
    from types import SimpleNamespace as NS

    import rapid_reports_ai.hybrid_stack.service as S
    from rapid_reports_ai.hybrid_stack.copilot import library_match as LM
    from rapid_reports_ai.hybrid_stack.copilot import tnm

    lib = _lab_lib()
    site = tnm.sites()[0]

    async def schema(*a, **k):
        return NS(regions=[])

    async def group_update(*a, **k):
        return NS(units=[])

    async def facts(scan, history):
        assert (scan, history) == ("CT", "h")
        return LM.CaseFacts(modality="CT", exams={"ex@1.0"})

    async def pick(scan, history, finding):
        return ([lib.lookup("nod-a"), lib.lookup("nod-b"), lib.lookup("nod-r")], site if finding == "t1" else None)

    async def gate(finding, s, history):
        return 0.9
    built = []
    real_build = RL.M.build_cards

    async def build(*a, **k):
        built.append(a)
        return await real_build(*a, **k)
    monkeypatch.setattr(S, "resolve_schema", schema)
    monkeypatch.setattr(S, "group_update", group_update)
    monkeypatch.setattr(RL, "_coverage_lab", lambda: NS(findings=lambda units: [{"id": "F1", "text": "t1"}]))
    monkeypatch.setattr(RL.LB, "get", lambda: lib)
    monkeypatch.setattr(LM, "case_facts", facts)
    monkeypatch.setattr(LM, "pick", pick)
    monkeypatch.setattr(RL.M, "_gate", gate)
    monkeypatch.setattr(RL.M, "build_cards", build)

    async def no_gptoss(prompt):
        raise AssertionError("the lab runs the library path: no gpt-oss")
    monkeypatch.setattr(RL.M, "_call", no_gptoss)
    case = {"id": "c", "scan_type": "CT", "clinical_history": "h", "findings": "t1. Rest normal."}
    out = asyncio.run(RL._cards_for(case, asyncio.Semaphore(1)))
    assert len(built) == 1
    got = [(c["id"], c["pack"], c["trigger"], c["finding"], c["via_sibling_of"]) for c in out]
    assert got == [
        ("c:exam:ex@1.0", "ex@1.0", "exam", "t1. Rest normal.", None),
        (f"c:F1:tnm:{site}", f"tnm:{site}", "finding", "t1", None),
        ("c:F1:nod-a@1.0", "nod-a@1.0", "finding", "t1", None),
        ("c:F1:nod-b@1.0", "nod-b@1.0", "finding", "t1", "nod-a@1.0"),   # tier 1 sibling once; tier 2 sibling dropped
    ]
    assert [c["pack"] for c in RL.settleable(out)] == ["ex@1.0", "nod-a@1.0", "nod-b@1.0"]


def test_cards_for_merges_tnm_by_site_and_counts_needs_modality_cards_without_settling(monkeypatch):
    import asyncio
    import copy
    from types import SimpleNamespace as NS

    import rapid_reports_ai.hybrid_stack.service as S
    from rapid_reports_ai.hybrid_stack.copilot import library_match as LM
    from rapid_reports_ai.hybrid_stack.copilot import tnm
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as L

    from .conftest import TOY_ENTRY

    d = copy.deepcopy(TOY_ENTRY)
    d.update(id="thy", topic="thy", display="thy 2020", system="thy system", aliases=[], off_modality="redirect")
    d["applies_to"] = {**d["applies_to"], "modality": ["US"]}
    lib = L.Library({"version": "v", "entries": {"thy@1.0": {"entry": d}}})
    site = tnm.sites()[0]

    async def schema(*a, **k):
        return NS(regions=[])

    async def group_update(*a, **k):
        return NS(units=[])

    async def facts(scan, history):
        return LM.CaseFacts(modality="CT")

    async def pick(scan, history, finding):
        return ([lib.lookup("thy")], site)

    async def gate(finding, s, history):
        return 0.9
    monkeypatch.setattr(S, "resolve_schema", schema)
    monkeypatch.setattr(S, "group_update", group_update)
    monkeypatch.setattr(RL, "_coverage_lab", lambda: NS(findings=lambda units: [{"id": "F1", "text": "t1"},
                                                                                {"id": "F2", "text": "t2"}]))
    monkeypatch.setattr(RL.LB, "get", lambda: lib)
    monkeypatch.setattr(LM, "case_facts", facts)
    monkeypatch.setattr(LM, "pick", pick)
    monkeypatch.setattr(RL.M, "_gate", gate)
    case = {"id": "c", "scan_type": "CT", "clinical_history": "", "findings": "t1. t2."}
    out = asyncio.run(RL._cards_for(case, asyncio.Semaphore(1)))
    assert [(c["id"], c["needs_modality"]) for c in out] == [
        (f"c:F1:tnm:{site}", ""), ("c:F2:thy@1.0", "US"), ("c:F1:thy@1.0", "US")]   # rank order; one TNM card
    assert RL.settleable(out) == []


def _aaa():
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    src = Path(__file__).resolve().parents[2] / "guidelines" / "nhs-aaa-surveillance" / "entry.json"
    return Entry.model_validate_json(src.read_text())


def _aaa_label(sex="male"):
    return _label(screening_programme=(None, "Yes"), sex=(None, sex), previous_aaa_treatment=(None, "No"),
                  diameter_cm=("2.4", None), prior_programme_scan=(None, "No"), growth_12m_cm=(None, None))


def test_an_exam_card_gets_live_presets_and_they_count_as_prefilled_not_asked():
    e, s = _aaa(), Settlement(values={"diameter_cm": Drafted(InputValue(value=2.4), "aorta 2.4 cm", "read")})
    exam, finding = {"id": "c:exam:aaa", "pack": e.key, "trigger": "exam"}, {"id": "c:u1:aaa", "trigger": "finding"}
    pre = RL.card_presets(e, exam)
    assert pre == dict(e.exam_presets) and RL.card_presets(e, finding) == {}
    tiers = {k: t for k, (_, _, t) in RL.drafts(s, e, pre).items()}
    assert tiers == {"diameter_cm": "read", "screening_programme": "prefilled", "sex": "prefilled",
                     "previous_aaa_treatment": "prefilled"}
    v = RL.verdicts(e, s, _aaa_label(), pre)
    assert {k: v[k] for k in ("screening_programme", "sex", "previous_aaa_treatment")} == dict.fromkeys(
        ("screening_programme", "sex", "previous_aaa_treatment"), "ok")
    assert RL.taps(e, s, _aaa_label(), {}, presets=pre) == (1, "no_aaa")       # only prior_programme_scan answered
    assert RL.taps(e, s, _aaa_label(), {}) == (1, "no_aaa")      # no presets: eligibility assumed in scope (Hassan
    # 2026-10-13), and the truth agrees, so no tap; an assumption the truth contradicts is one correction tap:
    assert RL.taps(e, s, _aaa_label(sex="female"), {}) == (2, "does_not_apply")   # prior scan asked, sex corrected
    assert RL.verdicts(e, s, _aaa_label(sex="female"), pre)["sex"] == "wrong"   # a preset the truth contradicts
    assert RL.taps(e, s, _aaa_label(sex="female"), {}, presets=pre) == (1, "does_not_apply")  # correct sex; excluded


def test_spot_rows_and_run_use_the_cards_presets(monkeypatch, tmp_path):
    import asyncio
    import json
    e = _aaa()

    async def settle(e_, findings, history, finding=""):
        return Settlement(values={"diameter_cm": Drafted(InputValue(value=2.4), "aorta 2.4 cm", "read")})
    monkeypatch.setattr(RL, "settle_pack", settle)
    monkeypatch.setattr(RL, "_lib", lambda: _lib_with(e))
    cards = [{"id": "c:exam:aaa", "pack": e.key, "trigger": "exam", "findings": "Aorta 2.4 cm.",
              "clinical_history": "", "finding": "Aorta 2.4 cm."}]
    p = tmp_path / "cards.json"
    p.write_text(json.dumps(cards))
    out = json.loads(asyncio.run(RL.run(p, tmp_path)).read_text())
    assert out[0]["missing"] == ["prior_programme_scan"] and out[0]["presets"] == dict(e.exam_presets)
    assert set(out[0]["drafts"]) == {"diameter_cm"}


@pytest.mark.parametrize("pack,inp,value,truth,same", [
    ("ese-adrenal-incidentaloma", "size_cm", 0.9, "under 1 cm", True),           # quote "9 mm"
    ("ese-adrenal-incidentaloma", "size_cm", 1.4, "1 cm to under 4 cm", True),
    ("ese-adrenal-incidentaloma", "size_cm", 4.0, "1 cm to under 4 cm", False),  # the edge: a genuine mismatch
    ("ese-adrenal-incidentaloma", "age", 67.0, "40 years or more", True),
    ("fleischner-pulmonary-nodule", "age", 67.0, "35 years or over", True),
    ("fleischner-pulmonary-nodule", "age", 30.0, "35 years or over", False),
    ("fleischner-pulmonary-nodule", "diameter_mm", 14.0, ">8 mm", True),         # an older band label: a bound
    ("fleischner-pulmonary-nodule", "diameter_mm", 5.0, "<6 mm", True),
    ("fleischner-pulmonary-nodule", "diameter_mm", 7.0, "<6 mm", False),
    ("rcog-ovarian-mass-postmenopausal", "size_cm", 2.8, "3 cm or less", True),
    ("rcog-ovarian-mass-premenopausal", "size_mm", 28.0, "under 50 mm", True),
    ("fleischner-pulmonary-nodule", "diameter_mm", 9.0, "9 mm", True),           # both numbers
    ("fleischner-pulmonary-nodule", "diameter_mm", 9.0, "0.9 cm", True),         # unit-normalised
    ("fleischner-pulmonary-nodule", "diameter_mm", 9.0, "8 mm", False)])
def test_a_read_number_is_compared_with_a_band_or_bound_truth_as_the_engine_bands_it(pack, inp, value, truth, same):
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    e = LB.Library(json.loads(LB.BUNDLE.read_text())).lookup(pack)
    assert RL._same(e, inp, InputValue(value=value), truth) is same


def test_a_band_or_bound_label_for_a_number_is_kept_as_a_value_and_a_read_inside_it_is_ok():
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    e = LB.Library(json.loads(LB.BUNDLE.read_text())).lookup("fleischner-pulmonary-nodule")
    raw = {"inputs": [{"input": "diameter_mm", "stated": True, "value": ">8 mm", "quote": "14mm", "locator": "S1 p3",
                       "assumed": None, "boundary": False, "note": ""},
                      {"input": "age", "stated": True, "value": "35 years or over", "quote": "67-year-old",
                       "locator": "S1 p2", "assumed": None, "boundary": False, "note": ""}],
           "lesions": [], "category": None}
    lab = RL.parse_label(e, raw, "claude-opus-5-5 subagent")
    assert lab["inputs"]["diameter_mm"]["value"] == ">8 mm" and lab["inputs"]["diameter_mm"]["boundary"] is False
    s = Settlement(values={"diameter_mm": Drafted(InputValue(value=14.0), "14mm", "read"),
                           "age": Drafted(InputValue(value=67.0), "67-year-old", "read")})
    v = RL.verdicts(e, s, lab)
    assert v["diameter_mm"] == "ok" and v["age"] == "ok"
    s = Settlement(values={"diameter_mm": Drafted(InputValue(value=7.0), "7mm", "read")})
    assert RL.verdicts(e, s, lab)["diameter_mm"] == "wrong"                     # a genuine mismatch stays wrong


def test_a_scope_doubt_the_truth_agrees_with_is_confirmed_at_apply_then_excludes():
    """A pre-filled excluding eligibility value never excludes the draft; the radiologist confirms it at Apply (one
    tap), and Calculate then excludes."""
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    e = LB.Library(json.loads(LB.BUNDLE.read_text())).lookup("rcog-ovarian-mass-premenopausal")
    s = Settlement(values={"pregnant_or_acute": Drafted(InputValue(value=True), "Pelvic pain", "prefilled", ["x"])})
    lab = _label(**{i.id: (None, None) for i in e.inputs})
    lab["inputs"]["pregnant_or_acute"].update(stated=True, value="Yes")
    assert RL.taps(e, s, lab, {}) == (1, "does_not_apply")       # confirming the doubt is one tap (final review I2)


def test_a_number_right_only_by_its_band_is_tagged_apart():
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    e = LB.Library(json.loads(LB.BUNDLE.read_text())).lookup("fleischner-pulmonary-nodule")
    assert RL._agrees_by_band(e, "diameter_mm", InputValue(value=14.0), ">8 mm")
    assert not RL._agrees_by_band(e, "diameter_mm", InputValue(value=9.0), "9 mm")          # equal: verified
    assert not RL._agrees_by_band(e, "diameter_mm", InputValue(value=7.0), "<6 mm")         # wrong: not ok at all


def test_taps_to_ready_add_one_tick_per_decisive_guess_left_on_the_card(toy_entry):
    """Spec 2026-10-14 §9.4: the questionnaire card is ready after its answers plus one ✓ per decisive pre-filled or
    assumed value it still shows (never a read value, never a scope doubt: taps() already counts confirming it)."""
    s = Settlement(values={"kind": Drafted(InputValue(value="solid"), "solid", "prefilled", ["x"]),
                           "size": Drafted(InputValue(value=7.0), "7 mm", "read")})
    lab = _label(kind=("solid", None), size=("7", None), risk=(None, "high"), margin=(None, None))
    assert RL.taps(toy_entry, s, lab, patient={}) == (1, "ct6")          # risk answered
    assert RL.taps_to_ready(toy_entry, s, lab, patient={}) == 2          # + ✓ on the decisive pre-filled type
    read = Settlement(values={"kind": Drafted(InputValue(value="solid"), "solid", "read"),
                              "size": Drafted(InputValue(value=7.0), "7 mm", "read")})
    assert RL.taps_to_ready(toy_entry, read, lab, patient={}) == 1       # nothing guessed: no ✓


def test_an_excluded_card_has_no_tick_in_taps_to_ready(toy):
    """The real card shows no Check zone once the pack does not apply: taps_to_ready equals taps."""
    from tests.test_library_pack_preview import _elig
    e = _elig(toy)
    s = Settlement(values={"kind": Drafted(InputValue(value="solid"), "solid", "prefilled", ["x"]),
                           "size": Drafted(InputValue(value=7.0), "7 mm", "read"),
                           "known_cancer": Drafted(InputValue(value=True), "Yes", "read")})
    lab = _label(kind=("solid", None), size=("7", None), risk=(None, "high"), margin=(None, None), known_cancer=("Yes", None))
    n, outcome = RL.taps(e, s, lab, patient={})
    assert outcome == "does_not_apply"
    assert RL.taps_to_ready(e, s, lab, patient={}) == n
