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
    assert out.assumed == {"Liver": ["The liver is normal."], "Pelvic organs": ["The uterus is normal."]}
    assert seen == [["The uterus is normal.", "The ovaries are normal.", "No adnexal mass."]]  # untouched not asked


async def test_removed_reaches_untouched_regions(monkeypatch):
    seen = []
    monkeypatch.setattr(N, "ask_rows", _checks({"The liver is normal.": (0.0, 0.0, 0.8)}, seen))
    out = await N.assumed("x", NORMALS, [], [], ["Normal liver."])
    assert "Liver" not in out.assumed and out.assumed["Kidneys"] == ["The kidneys are normal."]
    assert "The liver is normal." in seen[0]


async def test_failure_hides_abnormal_regions_and_filters_removed_exactly(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(N, "ask_rows", boom)
    out = await N.assumed("x", NORMALS, ["Pelvic organs"], [], ["the liver is normal"])
    assert out.assumed == {"Kidneys": ["The kidneys are normal."]} and "RuntimeError" in out.error
