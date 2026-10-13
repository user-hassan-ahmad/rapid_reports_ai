import importlib.util
from pathlib import Path

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library.pack_preview import Settlement
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
    s = Settlement(values={"kind": (InputValue(value="solid"), "solid"), "risk": (InputValue(value="high"), "x")})
    v = RL.verdicts(toy_entry, s, _label(kind=("solid", None), size=("7", None), risk=(None, "low"),
                                         margin=(None, None)))
    assert v == {"kind": "ok", "risk": "wrong", "size": "asked", "margin": "asked"}


def test_taps_count_answers_and_corrections_never_the_calculate_tap(toy_entry):
    s = Settlement(values={"kind": (InputValue(value="subsolid"), "subsolid")})       # wrong: truth is solid
    n, outcome = RL.taps(toy_entry, s, _label(kind=("solid", None), size=("7", None), risk=(None, "high"),
                                              margin=(None, None)), patient={})
    assert (n, outcome) == (3, "ct6")          # correct kind, answer size, answer risk (assumed)


def test_a_wrong_draft_is_cleared_before_the_engine_runs_and_the_original_is_untouched(toy_entry):
    s = Settlement(values={"kind": (InputValue(value="subsolid"), "subsolid")})
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
    s = Settlement(values={"kind": (InputValue(value="solid"), "solid"), "size": (InputValue(value=8.0), "8 mm")})
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


def test_cards_for_passes_known_systems_and_emits_a_sibling_once(monkeypatch):
    import asyncio
    from types import SimpleNamespace as NS
    a, b = NS(key="a", tier=1, display="A"), NS(key="b", tier=1, display="B")
    ref = NS(key="r", tier=2, display="R")

    class Lib:
        def find(self, name, version=""):
            return {"A": a, "B": b, "R": ref}.get(name)

        def siblings(self, p):
            return {"a": [b, ref], "b": [a]}.get(p.key, [])

        def known_text(self):
            return "- a: A [aliases: ]\n- b: B [aliases: ]"
    prompts = []

    async def call(prompt):
        prompts.append(prompt)
        sysm = lambda n: NS(name=n, version="")
        return NS(findings=[NS(id="F1", systems=[sysm("A"), sysm("B")])])

    async def pgate(text, pack, history):
        return 1.0

    async def schema(*a, **k):
        return NS(regions=[])

    async def group_update(*a, **k):
        return NS(units=[])
    import rapid_reports_ai.hybrid_stack.service as S
    monkeypatch.setattr(S, "resolve_schema", schema)
    monkeypatch.setattr(S, "group_update", group_update)
    monkeypatch.setattr(RL, "_coverage_lab", lambda: NS(findings=lambda units: [{"id": "F1", "text": "nodule"}]))
    monkeypatch.setattr(RL.LB, "get", lambda: Lib())
    monkeypatch.setattr(RL.M, "_call", call)
    monkeypatch.setattr(RL.M, "_pgate", pgate)
    case = {"id": "c", "scan_type": "CT", "clinical_history": "h", "findings": "x"}
    out = asyncio.run(RL._cards_for(case, asyncio.Semaphore(1)))
    assert Lib().known_text() in prompts[0]
    assert sorted(c["id"] for c in out) == ["c:F1:a", "c:F1:b"]   # b named by the model and as a's sibling: once; tier 2 dropped
