from rapid_reports_ai.hybrid_stack.copilot.library.describe import facts


def test_facts_cover_every_located_item(toy_entry):
    got = {fid: claim for fid, claim, _ in facts(toy_entry)}
    assert got["size_band"] == "Diameter bands: <6 mm; 6-8 mm; >8 mm"
    assert got["plan.case2"] == ("solid nodule …, … risk → CT at 12 months: when Nodule type is solid and size_band "
                                 "is 6-8 mm and Patient risk is low")
    assert got["outcome.pet"] == "solid nodule … → PET-CT"
    assert got["reference.sum.1"] == "A toy guideline for tests."
    assert all(loc is not None for _, _, loc in facts(toy_entry))
