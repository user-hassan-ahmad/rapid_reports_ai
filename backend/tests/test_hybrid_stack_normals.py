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


async def test_untouched_all_dictated_none_abnormal_checked(monkeypatch):
    seen = []
    monkeypatch.setattr(N, "ask_rows", _checks({"The ovaries are normal.": (0.0, 0.9, 0.0),
                                                 "No adnexal mass.": (0.4, 0.0, 0.0)}, seen))
    out = await N.assumed("A right ovarian cyst. Kidneys normal.", NORMALS, ["Pelvic organs"], ["Kidneys"], [])
    assert out.assumed == {"Liver": ["The liver is normal."], "Kidneys": [], "Pelvic organs": ["The uterus is normal."]}
    assert seen == [["The uterus is normal.", "The ovaries are normal.", "No adnexal mass."]]  # untouched not asked


async def test_removed_reaches_untouched_regions(monkeypatch):
    seen = []
    monkeypatch.setattr(N, "ask_rows", _checks({"The liver is normal.": (0.0, 0.0, 0.8)}, seen))
    out = await N.assumed("x", NORMALS, [], [], ["Normal liver."])
    assert out.assumed["Liver"] == [] and out.assumed["Kidneys"] == ["The kidneys are normal."]
    assert seen[0] == ["The liver is normal."]               # only the candidate is asked


async def test_failure_hides_abnormal_regions_and_filters_removed_exactly(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(N, "ask_rows", boom)
    out = await N.assumed("x", NORMALS, ["Pelvic organs"], [], ["liver normal"])
    assert out.assumed == {"Liver": [], "Kidneys": ["The kidneys are normal."], "Pelvic organs": []}
    assert "RuntimeError" in out.error                        # a candidate is never assumed unchecked


async def test_a_row_owns_its_check(monkeypatch):
    seen = []
    normals = {"Bowel": ["The appendix is normal in calibre.", "No diverticula."]}
    monkeypatch.setattr(N, "ask_rows", _checks({"The appendix is normal in calibre.": (0.0, 0.0, 0.9)}, seen))
    out = await N.assumed("A cyst.", normals, [], [], [], owned=["The appendix is normal."])
    assert out.assumed == {"Bowel": ["No diverticula."]}
    assert seen == [["The appendix is normal in calibre."]]
