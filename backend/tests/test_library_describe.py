from rapid_reports_ai.hybrid_stack.copilot.library.describe import facts


def test_facts_cover_every_located_item(toy_entry):
    got = {fid: claim for fid, claim, _ in facts(toy_entry)}
    assert got["size_band"] == "Diameter bands: <6 mm; 6-8 mm; >8 mm"
    assert got["plan.case2"] == ("solid nodule …, … risk → CT at 12 months: when Nodule type is solid and size_band "
                                 "is 6-8 mm and Patient risk is low")
    assert got["outcome.pet"] == "solid nodule … → PET-CT"
    assert got["reference.sum.1"] == "A toy guideline for tests."
    assert all(loc is not None for _, _, loc in facts(toy_entry))


def test_every_bundled_pack_fits_the_ask_material_cap_with_the_late_facts_present():
    """New-I3: Ask grounds on the whole pack, never a silently truncated half: every bundled entry's material fits
    PACK_MATERIAL_MAX, and the facts added last (Fleischner does_not_apply, BTS resolved and volumetry) are in it."""
    import json
    from rapid_reports_ai.hybrid_stack.copilot import ask as A
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    from rapid_reports_ai.hybrid_stack.copilot.library import describe as D
    assert A.PACK_MATERIAL_MAX == 48000                                      # controller ruling 2026-10-13
    lib = LB.Library(json.loads(LB.BUNDLE.read_text()))
    texts = {}
    for e in lib.list():
        texts[e.id] = D.material(e, lib.sources(e.key))
        assert len(texts[e.id]) <= A.PACK_MATERIAL_MAX, (e.id, len(texts[e.id]))
    assert "Fleischner 2017 does not apply" in texts["fleischner-pulmonary-nodule"]
    assert "Lung-RADS" in texts["fleischner-pulmonary-nodule"]
    assert "resolved on this CT" in texts["bts-pulmonary-nodule"]
    assert "Assess growth by volumetry" in texts["bts-pulmonary-nodule"]
    body = texts["bts-pulmonary-nodule"].split("\n", 1)[1]                  # titles only on the first line
    assert "British Thoracic Society guidelines for the investigation" not in body


def test_a_short_citation_keeps_the_table_or_section_beside_the_page():
    from rapid_reports_ai.hybrid_stack.copilot.library import describe as D
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Locator
    assert D._short(Locator(source="S1", page=3, table="Table 2")) == "S1 p. 3, Table 2"
    assert D._short(Locator(source="S1", page=3)) == "S1 p. 3"
    assert D._short(Locator(source="S1", section="Groups not covered")) == "S1 Groups not covered"
    assert D._short(Locator(source="S1", page=3, section="x" * 80)) == "S1 p. 3, " + "x" * 40


def test_reference_view_gives_every_field_with_its_citation(toy_reference):
    from rapid_reports_ai.hybrid_stack.copilot.library import describe as D
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    v = D.reference_view(Entry.model_validate(toy_reference), [{"id": "S1", "title": "Toy grading", "edition": "2020"}])
    assert v["tables"][0]["rows"] == [["1", "softening"], ["2", "partial-thickness defect"]]
    assert v["definitions"][0]["citation"] == {"source": "S1", "title": "Toy grading", "edition": "2020", "page": 2}
    assert v["pitfalls"] == [] and "locator" not in v["summary"][0]


def test_material_for_a_reference_entry_has_no_inputs_line(toy_reference):
    from rapid_reports_ai.hybrid_stack.copilot.library import describe as D
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    m = D.material(Entry.model_validate(toy_reference), [{"id": "S1", "title": "Toy grading", "edition": "2020"}])
    assert "Inputs:" not in m and "Grade table" in m and "2 | partial-thickness defect" in m


def test_ask_material_drops_no_located_fact_of_any_bundled_pack():
    """Compact rows and shared caveats must not lose a fact: every outcome's wording, every caveat, every reference
    field and every rule or table row (as its outcome id) of every bundled entry is in its Ask material."""
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    from rapid_reports_ai.hybrid_stack.copilot.library import describe as D
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import RulesStep, TableStep
    lib = LB.Library(json.loads(LB.BUNDLE.read_text()))
    for e in lib.list():
        text = D.material(e, lib.sources(e.key))
        lines = text.splitlines()
        for fid, claim, _ in D.facts(e):
            if fid.startswith(("outcome.", "reference.")) or "." not in fid:
                assert claim in text, (e.id, fid)
        for s in e.logic:
            if isinstance(s, RulesStep):
                assert all(f"{D._expr(e, c.when)} → {c.result}" in text for c in s.cases if c.locator), (e.id, s.id)
            elif isinstance(s, TableStep) and s.locator:
                assert all(any(x.endswith(f" → {r.result}") for x in lines) for r in s.rows), (e.id, s.id)
