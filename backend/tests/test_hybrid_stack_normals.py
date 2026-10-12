from rapid_reports_ai.hybrid_stack import jev_stack as J
from rapid_reports_ai.hybrid_stack import normals as N

NORMALS = {"Liver": ["The liver is normal."], "Kidneys": ["The kidneys are normal."],
           "Pelvic organs": ["The uterus is normal.", "The ovaries are normal.", "No adnexal mass."]}


def _checks(table, seen=None):
    async def fake(dictation, sentences, removed):
        if seen is not None:
            seen.append(list(sentences))
        return [J.RowCheck(*table.get(s, (0.0, 0.0, 0.0))) for s in sentences]
    return fake


async def test_every_region_is_checked_dictated_normal_regions_assume_nothing(monkeypatch):
    seen = []
    monkeypatch.setattr(N, "ask_rows", _checks({"The ovaries are normal.": (0.0, 0.9, 0.0),
                                                 "No adnexal mass.": (0.4, 0.0, 0.0)}, seen))
    out = await N.assumed("A right ovarian cyst. Kidneys normal.", NORMALS, ["Pelvic organs"], ["Kidneys"], [])
    assert out.assumed == {"Liver": ["The liver is normal."], "Kidneys": [], "Pelvic organs": ["The uterus is normal."]}
    assert sorted(sum(seen, [])) == sorted(["The liver is normal.", "The uterus is normal.", "The ovaries are normal.",
                                             "No adnexal mass."])


async def test_an_untouched_region_contradicted_by_a_misplaced_finding_assumes_nothing(monkeypatch):
    # the grouper filed "a splenic laceration" under another region: the spleen looks untouched
    normals = {"Spleen": ["The spleen is normal."], "Liver": ["The liver is normal."]}
    monkeypatch.setattr(N, "ask_rows", _checks({"The spleen is normal.": (0.0, 0.85, 0.0)}))
    out = await N.assumed("Small splenic laceration.", normals, ["Liver"], [], [])
    assert out.assumed == {"Spleen": [], "Liver": ["The liver is normal."]}


async def test_removed_and_owned_sentences_are_never_assumed(monkeypatch):
    normals = {"Kidneys": ["The kidneys are unremarkable."], "Bowel": ["The appendix is normal in calibre.", "No diverticula."]}
    table = {"The kidneys are unremarkable.": (0.0, 0.0, 0.7), "The appendix is normal in calibre.": (0.0, 0.0, 0.9)}
    monkeypatch.setattr(N, "ask_rows", _checks(table))
    out = await N.assumed("x", normals, [], [], ["No hydronephrosis."], owned=["The appendix is normal."])
    assert out.assumed == {"Kidneys": [], "Bowel": ["No diverticula."]}


async def test_sentences_are_asked_in_parallel_batches(monkeypatch):
    seen = []
    normals = {f"R{i}": [f"Normal {i} a.", f"Normal {i} b."] for i in range(20)}
    monkeypatch.setattr(N, "ask_rows", _checks({}, seen))
    out = await N.assumed("x", normals, [], [], [])
    assert [len(b) for b in seen] == [15, 15, 10] and sum(len(v) for v in out.assumed.values()) == 40


async def test_failure_assumes_nothing(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(N, "ask_rows", boom)
    out = await N.assumed("x", NORMALS, ["Pelvic organs"], [], [])
    assert out.assumed == {"Liver": [], "Kidneys": [], "Pelvic organs": []} and "RuntimeError" in out.error
