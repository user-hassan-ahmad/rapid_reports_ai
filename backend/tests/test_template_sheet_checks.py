import pytest

from rapid_reports_ai import template_sheet_checks as C
from rapid_reports_ai.template_sheet_grammar import parse_sheet

SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Knee (FINDINGS)
COVERS ["menisci" | "cartilage" | "ligaments"]
NORMAL [menisci] "The menisci are intact."
NORMAL [cartilage] "Mild chondral irregularity and thinning."
NEGATIVE "No effusion, synovitis or loose body."
NORMAL [ligaments] "LVEF {value}%."
"""


def _structure():
    res = parse_sheet(SHEET, mode="template")
    assert res.structure.usable, res.errors
    return res.structure


async def test_checks_flag_placeholders_abnormal_and_multi_structure(monkeypatch):
    async def fake(units):
        return {u.text: (0.1 if "Mild" in u.text else 0.95, 0.9 if "effusion" in u.text else 0.1) for u in units}

    monkeypatch.setattr(C, "_jev_scores", fake)
    monkeypatch.setattr(C, "MULTI_MIN", 0.6)  # shipped off (no clean gap in the lab); the logic is still tested
    fails = await C.check_units(_structure(), SHEET)
    by = {f.text: f.reason for f in fails}
    assert by["LVEF {value}%."] == C.PLACEHOLDER
    assert by["Mild chondral irregularity and thinning."] == C.NOT_NORMAL
    assert by["No effusion, synovitis or loose body."] == C.MULTI_STRUCTURE
    assert "The menisci are intact." not in by
    lines = SHEET.splitlines()
    for f in fails:
        assert f.line > 0 and lines[f.line - 1] == f.source_line and f.text in f.source_line


async def test_multi_structure_check_is_off_by_default(monkeypatch):
    async def fake(units):
        return {u.text: (0.95, 0.99) for u in units}

    monkeypatch.setattr(C, "_jev_scores", fake)
    fails = await C.check_units(_structure(), SHEET)
    assert [f.reason for f in fails] == [C.PLACEHOLDER]


async def test_placeholder_units_are_not_sent_to_jev(monkeypatch):
    seen = []

    async def fake(units):
        seen.extend(u.text for u in units)
        return {u.text: (0.95, 0.1) for u in units}

    monkeypatch.setattr(C, "_jev_scores", fake)
    await C.check_units(_structure())
    assert "LVEF {value}%." not in seen and len(seen) == 3


async def test_jev_scores_chunks_large_sheets(monkeypatch):
    calls = []

    class R:
        def __init__(self, n):
            self.n = n

        def raise_for_status(self):
            pass

        def json(self):
            return {"answers": {f"{p}{i}": {"noul": 0.7} for i in range(self.n) for p in "nm"}}

    async def fake_post(body, key, timeout):
        n = len(body["questions"]) // 2
        calls.append(n)
        return R(n)

    monkeypatch.setattr(C, "jev_post", fake_post)

    class U:
        def __init__(self, t):
            self.text = t

    out = await C._jev_scores([U(f"Unit {i}.") for i in range(85)])
    assert calls == [40, 40, 5]
    assert len(out) == 85 and out["Unit 84."] == (0.7, 0.7)


async def test_jev_error_raises(monkeypatch):
    async def boom(units):
        raise RuntimeError("jev down")

    monkeypatch.setattr(C, "_jev_scores", boom)
    with pytest.raises(RuntimeError):
        await C.check_units(_structure())
